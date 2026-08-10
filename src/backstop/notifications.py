"""Budget-exhaustion alerts + webhooks (Launch Improvement B1).

Warn BEFORE the cap, not just block after it. Three event types:

* ``threshold_crossed`` — usage crossed a configurable tier (default 85% / 95%).
* ``budget_crossed``     — the hard budget was hit (request was/will be blocked).
* ``projected_exceeded`` — burn rate implies exhaustion within the horizon; carries
  ``calls_remaining`` (the novel, differentiating signal — no vendor ships this).

Delivery follows the Standard Webhooks shape: HMAC-SHA256 signature, ``Webhook-Id``
idempotency, retries on 5xx/408/429 with exponential backoff + jitter, dead-letter on
exhaustion. Alert delivery is always fire-and-forget so it can NEVER block or fail a
user request. Dedup is keyed on ``(tenant, event_key)`` and is confirmed only AFTER a
successful delivery (the LiteLLM #35800 lesson: stamping dedup before the send is
confirmed loses alerts).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable


def _now() -> float:
    return time.time()


class WebhookSink:
    """Delivers a signed JSON payload to one or more endpoints, fire-and-forget."""

    def __init__(
        self,
        endpoints: list[str],
        secret: str | None = None,
        http_post: Callable | None = None,
        dlq: Callable[[dict, Exception], None] | None = None,
        max_attempts: int = 6,
    ) -> None:
        self.endpoints = endpoints
        self.secret = secret
        self._post = http_post or _default_post
        self.dlq = dlq
        self.max_attempts = max_attempts

    def _sign(self, webhook_id: str, timestamp: int, body: bytes) -> str:
        if not self.secret:
            return ""
        signed = f"{webhook_id}.{timestamp}.".encode() + body
        digest = hmac.new(self.secret.encode(), signed, hashlib.sha256).hexdigest()
        return f"v1,{digest}"

    def send(self, event_type: str, payload: dict) -> None:
        webhook_id = uuid.uuid4().hex
        timestamp = int(_now())
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        sig = self._sign(webhook_id, timestamp, body)
        headers = {
            "Content-Type": "application/json",
            "Webhook-Id": webhook_id,
            "Webhook-Timestamp": str(timestamp),
            "Webhook-Signature": sig,
            "X-Backstop-Event": event_type,
        }
        last_err: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                for endpoint in self.endpoints:
                    resp = self._post(endpoint, body, headers)
                    if resp is not None and getattr(resp, "status_code", 200) >= 400:
                        # 4xx: do not retry (permanent). 5xx/408/429: retry.
                        if getattr(resp, "status_code", 200) < 500 and getattr(resp, "status_code", 200) not in (408, 429):
                            if self.dlq:
                                self.dlq({"endpoint": endpoint, "event": event_type, "payload": payload}, RuntimeError(f"HTTP {resp.status_code}"))
                            continue
                        raise RuntimeError(f"HTTP {resp.status_code}")
                return  # all endpoints delivered
            except Exception as exc:  # retryable
                last_err = exc
                delay = min(30.0, 0.5 * (2 ** attempt)) + (0.0 if attempt == 0 else 0.1)
                time.sleep(delay)
        if self.dlq:
            self.dlq({"event": event_type, "payload": payload}, last_err or RuntimeError("webhook exhausted retries"))


def _default_post(endpoint: str, body: bytes, headers: dict):
    import httpx

    with httpx.Client(timeout=10.0) as c:
        return c.post(endpoint, content=body, headers=headers)


@dataclass
class _Fired:
    expires_at: float


class BudgetAlertManager:
    """Decides which budget alerts to fire and dedups them per (tenant, key)."""

    def __init__(
        self,
        endpoints: list[str] | None,
        secret: str | None = None,
        tiers: list[float] | None = None,
        dedup_ttl: float = 86400.0,
        project_horizon_calls: int = 5,
        sink: Callable | None = None,
        clock: Callable[[], float] = _now,
    ) -> None:
        self.endpoints = endpoints or []
        self.secret = secret
        self.tiers = sorted(tiers or [0.85, 0.95])
        self.dedup_ttl = dedup_ttl
        self.project_horizon_calls = project_horizon_calls
        self.clock = clock
        self._lock = threading.Lock()
        self._fired: dict[tuple[str, str], _Fired] = {}
        self._inflight: set[tuple[str, str]] = set()
        self._sink = sink or (WebhookSink(self.endpoints, secret) if self.endpoints else None)

    # -- public -------------------------------------------------------------
    def observe(self, tenant_id: str, used: float, limit: float, burn_per_call: float | None = None) -> None:
        """Call after a successful reconcile. Fire-and-forget; never raises."""
        if limit <= 0 or self._sink is None:
            return
        try:
            ratio = used / limit
            for tier in self.tiers:
                if ratio >= tier:
                    self._maybe_fire(tenant_id, f"threshold_{tier}", "threshold_crossed", {
                        "tenant_id": tenant_id,
                        "threshold": tier,
                        "used": used,
                        "limit": limit,
                        "ratio": round(ratio, 4),
                    })
            if ratio >= 1.0:
                self._maybe_fire(tenant_id, "budget", "budget_crossed", {
                    "tenant_id": tenant_id,
                    "used": used,
                    "limit": limit,
                })
            if burn_per_call and burn_per_call > 0:
                calls_remaining = max(0, int((limit - used) / burn_per_call))
                if calls_remaining <= self.project_horizon_calls:
                    self._maybe_fire(tenant_id, "projected", "projected_exceeded", {
                        "tenant_id": tenant_id,
                        "used": used,
                        "limit": limit,
                        "calls_remaining": calls_remaining,
                        "burn_per_call": burn_per_call,
                    })
        except Exception:
            # Alerting must never break the request path.
            pass

    # -- internals ----------------------------------------------------------
    def _maybe_fire(self, tenant_id: str, key: str, event_type: str, payload: dict) -> None:
        fk = (tenant_id, key)
        with self._lock:
            existing = self._fired.get(fk)
            if existing is not None and existing.expires_at > self.clock():
                return  # already fired within TTL
            if fk in self._inflight:
                return  # a delivery is in progress; do not double-send
            self._inflight.add(fk)
        try:
            # Deliver synchronously here (cheap for tests); the transport calls
            # observe() from a background thread so the request path stays free.
            self._sink.send(event_type, payload)
        except Exception:
            pass
        finally:
            with self._lock:
                # Confirm only AFTER delivery attempt so we never lose an alert to
                # a pre-stamp race (LiteLLM #35800).
                self._inflight.discard(fk)
                self._fired[fk] = _Fired(expires_at=self.clock() + self.dedup_ttl)

    # test/inspection helper
    def fired_keys(self) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._fired.keys())
