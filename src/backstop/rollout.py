"""Safe rollout: shadow + canary (Deep Research P2#13).

Lets a stricter / experimental policy ride alongside production without
hard-failing traffic. ``ShadowPolicy`` mirrors a sampled fraction of requests to
a secondary config and records *reason-coded* decisions (what the candidate
policy would have done) to the audit log, so a bad policy change is observed
before it ever blocks 100% of traffic. ``CanaryRouter`` sends a fraction of
traffic down a candidate fallback chain.
"""
from __future__ import annotations

import os
import random
import threading
from dataclasses import dataclass, field


class ShadowCollector:
    """Records enforcement decisions that *would* have fired in shadow mode.

    Mirrors Envoy's shadow counters: ``would_block`` (budget), ``would_open_circuit``,
    ``would_throttle`` (rate-limit), ``would_guardrail``, ``would_latency``. In shadow
    mode these increment but the request is never denied, so operators can watch
    projected block rates before flipping enforcement on.

    A kill-switch (``BACKSTOP_SHADOW=false`` env) hard-disables shadow regardless of
    config, so a misconfigured shadow can be turned off without a redeploy.
    """

    def __init__(self, sink: object | None = None) -> None:
        self.sink = sink
        self._lock = threading.Lock()
        self._counts = {
            "would_block": 0,
            "would_open_circuit": 0,
            "would_throttle": 0,
            "would_guardrail": 0,
            "would_latency": 0,
        }

    @staticmethod
    def enabled(config_shadow: bool) -> bool:
        env = os.getenv("BACKSTOP_SHADOW")
        if env is not None:
            return env.strip().lower() not in ("0", "false", "off", "no")
        return bool(config_shadow)

    def record(self, decision: str, reason: str, **fields) -> None:
        with self._lock:
            if decision in self._counts:
                self._counts[decision] += 1
        try:
            if self.sink is not None:
                self.sink.record(decision, reason, **fields)
        except Exception:
            pass

    def counts(self) -> dict:
        with self._lock:
            return dict(self._counts)

    def would_block(self, **fields) -> None:
        self.record("would_block", "budget_exceeded", **fields)

    def would_open_circuit(self, **fields) -> None:
        self.record("would_open_circuit", "circuit_open", **fields)

    def would_throttle(self, **fields) -> None:
        self.record("would_throttle", "rate_limited", **fields)

    def would_guardrail(self, **fields) -> None:
        self.record("would_guardrail", "guardrail_violation", **fields)

    def would_latency(self, **fields) -> None:
        self.record("would_latency", "latency_budget_exceeded", **fields)


@dataclass
class ShadowPolicy:
    sample_rate: float = 0.0
    candidate_config: object | None = None
    sink: object | None = None
    _rand: object = field(default_factory=random.Random)

    def should_shadow(self) -> bool:
        return self.sample_rate > 0 and self._rand.random() < self.sample_rate

    def record(self, decision: str, reason: str, **fields) -> None:
        if self.sink is None:
            return
        try:
            self.sink.record(decision, reason, **fields)
        except Exception:
            pass


@dataclass
class CanaryRouter:
    sample_rate: float = 0.0
    candidate_chain: list[dict] | None = None
    _rand: object = field(default_factory=random.Random)

    def route(self, primary: list[dict]) -> list[dict]:
        if self.sample_rate > 0 and self.candidate_chain and self._rand.random() < self.sample_rate:
            return self.candidate_chain
        return primary
