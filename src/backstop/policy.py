"""Every enforcement decision Backstop makes, written once.

The sync and async transports were near-duplicates of each other, and they
drifted. The async transport emitted two of the seven audit decisions the
sync one did, so an ``AsyncOpenAI`` deployment had no audit trail for a
budget denial, a downgrade, a fallback, or a circuit opening. Its semantic
cache was never constructed, so ``cache_semantic=True`` silently did nothing
for every async client while the metric that reports it kept counting up. And
its shadow mode consulted a different branch than the sync one, so the two
paths disagreed about whether a request should be let through.

The cause was structural, not a slip: the decision logic was written twice,
and twice is twice as likely to be once wrong.

This module is where the decisions live. A :class:`Policy` never awaits and
never touches the network — where an operation has to be asynchronous (a
shared Redis budget, the admission gate), the caller performs it and hands
the result back. What is left here is the part that drifted.

The two transports still have their own sequences, because a sequence that
contains an ``await`` cannot be one function. The parity test
(``tests/test_parity.py``) is what keeps those two sequences in step: it
drives both transports through the same scenarios and asserts the same audit
decisions, the same metric names and labels, and the same outcome.
"""
from __future__ import annotations

import json
import time
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

import httpx

from ._httpcompat import _HttpCompat
from .circuit import CircuitBreaker, CircuitState
from .config import BackstopConfig, Priority
from .exceptions import (
    BudgetExceededError,
    GuardrailViolationError,
    PriceUnavailableError,
    RateLimitError,
)
from .extract import RequestMetadata
from .ledger import get_ledger
from .metrics import get_metrics
from .pricing_catalog import LEDGER_CONTEXT, MONEY_PLACES, downgrade_target
from .retry import is_retryable_status

#: The budget is exhausted and the request was rewritten to a cheaper model.
#: The caller must reserve again against the new model's estimate.
DOWNGRADE = "downgrade"

#: The budget is exhausted but shadow mode is on: the request proceeds
#: without a reservation, and the would-block was recorded.
SHADOW = "shadow"


class Policy:
    """The decisions, shared by the sync and async transports.

    It holds no per-request state: every method takes what it needs as an
    argument, so one Policy can serve every concurrent request on a state.
    """

    def __init__(
        self,
        state: Any,
        *,
        compat: _HttpCompat,
        shadow: Any | None = None,
        alerts: Any | None = None,
        cache: Any | None = None,
    ) -> None:
        self.state = state
        self._compat = compat
        #: The shadow collector, or ``None`` when shadow mode is off. Public
        #: because a caller may want to read the ``would_*`` counters.
        self.shadow = shadow
        #: The budget alert manager, or ``None`` when alerts are unconfigured.
        self.alerts = alerts
        #: The response cache, or ``None`` when caching is off.
        self.cache = cache
        self._metrics = get_metrics()

    # ------------------------------------------------------------------
    # The budget decision
    # ------------------------------------------------------------------

    def budget_exhausted(
        self,
        meta: RequestMetadata,
        tenant_budget: Any | None,
        body: dict | None,
        request: httpx.Request,
        tenant_id: str | None,
    ) -> str:
        """The budget is exhausted. Decide what happens to the request.

        This is the decision that drifted. It used to exist in two places,
        and the two did not agree:

        * the sync path consulted the shadow collector only when there was
          **no** tenant budget, so a tenant configured to downgrade had its
          request denied in shadow mode — the exact opposite of what shadow
        mode promises;
        * the async path audited no decisions at all on this branch.

        So the order here is fixed and shared: try a downgrade; if that is
        not possible, offer the request to the shadow collector; and only if
        there is no shadow collector, deny it.

        The reservation itself is the caller's, not this method's, because
        reserving may be asynchronous — a shared Redis budget has to be
        awaited, and blocking the event loop on it is a bug this package has
        already had. The caller reserves, catches :class:`BudgetExceededError`,
        and calls this.

        :returns: :data:`DOWNGRADE` if the request was rewritten to a cheaper
            model and the caller must reserve again, or :data:`SHADOW` if it
            should proceed without a reservation.
        :raises BudgetExceededError: when the request cannot proceed.
        """
        if (
            tenant_budget is not None
            and getattr(tenant_budget, "on_exceed", None) == "downgrade"
            and body is not None
            and self.try_downgrade(request, body)
        ):
            self.audit("downgrade", "budget_exceeded", meta, tenant_id=tenant_id)
            return DOWNGRADE

        if self.shadow is not None:
            # Observe, never block. This is checked for *every* exhausted
            # budget, tenant or not.
            self.shadow.would_block(
                tenant_id=tenant_id, estimated_tokens=meta.estimated_tokens
            )
            return SHADOW

        self._metrics.call("budget_exceeded")
        if tenant_id:
            self._metrics.call("tenant_budget_exceeded", tenant_id)
        self.audit("deny", "budget_exceeded", meta, tenant_id=tenant_id)
        if tenant_budget is not None:
            remaining = getattr(tenant_budget, "remaining", 0) or 0
        else:
            remaining = self.state.budget.remaining or 0
        raise BudgetExceededError(
            f"request estimate {meta.estimated_tokens} tokens exceeds remaining budget {remaining}"
        )

    # ------------------------------------------------------------------
    # Dollars
    # ------------------------------------------------------------------

    def estimate_usd(self, meta: RequestMetadata, model: str) -> Decimal | None:
        """What this request is expected to cost, or ``None`` if it cannot be priced.

        The estimate is priced from the *split* — input tokens at the input
        rate, output tokens at the output rate — because the two rates are
        often three or four times apart, and pricing a blended total would
        mis-reserve in both directions.

        ``None`` means the catalog has no price for this model, which is a
        different answer from zero.
        """
        prices = self.state.prices
        if prices is None:
            return None
        entry = prices.resolve_model(model)
        if entry is None:
            return None
        with localcontext(LEDGER_CONTEXT):
            cost = (
                Decimal(meta.estimated_input_tokens) * entry.input_per_mtok_usd
                + Decimal(meta.estimated_output_tokens) * entry.output_per_mtok_usd
            ) / Decimal(1_000_000)
            return cost.quantize(
                Decimal(1).scaleb(-MONEY_PLACES), rounding=ROUND_HALF_UP
            )

    def require_price(self, model: str) -> None:
        """Refuse a request whose model cannot be priced, under a dollar ceiling.

        A dollar ceiling is only enforceable for a model the catalog prices.
        A model it does not carry would slip past the ceiling unmeasured,
        and a ceiling with a hole in it is not a ceiling.

        The default is to refuse. A deployment that would rather let the hole
        stand says so with ``budget_usd_unpriced_policy="allow"``, and the
        request is then recorded as unpriced — which is what the ledger
        already does with every unpriced request: a visible hole rather than
        a plausible wrong number.

        :raises PriceUnavailableError: when the model cannot be priced and
            the policy is ``"deny"``.
        """
        if self.state.config.budget_usd is None:
            return
        if self.state.config.budget_usd_unpriced_policy == "allow":
            return
        prices = self.state.prices
        if prices is not None and prices.resolve_model(model) is not None:
            return
        raise PriceUnavailableError(
            f"model {model!r} has no price in the catalog, so a dollar budget "
            "cannot be enforced for it. Add a price for it to the catalog file, "
            "or set budget_usd_unpriced_policy='allow' to let unpriced models "
            "through and record them as unpriced.",
            model=model,
            catalog_path=self.state.config.price_catalog_path,
        )

    def try_downgrade(self, request: httpx.Request, body: dict) -> bool:
        """Rewrite the request to use a cheaper model, if there is one.

        The target comes from the one price catalog, so a downgrade can never
        be to a model that costs more — a property the catalog's own test
        asserts for every entry in the map.
        """
        current_model = body.get("model", "")
        if not current_model:
            return False
        cheaper = downgrade_target(current_model)
        if cheaper is None:
            return False
        body["model"] = cheaper
        new_content = json.dumps(body).encode("utf-8")
        object.__setattr__(request, "_content", new_content)
        request.headers["content-length"] = str(len(new_content))
        return True

    # ------------------------------------------------------------------
    # Admission
    # ------------------------------------------------------------------

    def pre_admit_checks(
        self, request: httpx.Request, meta: RequestMetadata, tenant_id: str | None
    ) -> None:
        """The checks that run after the budget and before the request.

        :raises RateLimitError: when the pluggable rate limiter rejects it.
        :raises GuardrailViolationError: when an agent guardrail rejects it.
        """
        cfg = self.state.config
        if cfg.shadow_policy is not None and cfg.shadow_policy.should_shadow():
            cfg.shadow_policy.record(
                "shadow",
                "sampled",
                endpoint=getattr(meta, "endpoint", None),
                estimated_tokens=getattr(meta, "estimated_tokens", None),
                tenant_id=tenant_id,
            )
        if cfg.rate_limiter is not None and not cfg.rate_limiter.allow(
            getattr(meta, "estimated_tokens", 0)
        ):
            if self.shadow is not None:
                self.shadow.would_throttle(tenant_id=tenant_id)
            else:
                self._metrics.call("rate_limited")
                self.audit("deny", "rate_limited", meta, tenant_id=tenant_id)
                raise RateLimitError("rate limiter rejected request")
        agent_id = request.headers.get("X-Backstop-Agent")
        if cfg.agent_guard is not None and agent_id:
            if not cfg.agent_guard.allow(agent_id, getattr(meta, "estimated_tokens", 0)):
                if self.shadow is not None:
                    self.shadow.would_guardrail(tenant_id=tenant_id, agent_id=agent_id)
                else:
                    self.audit(
                        "deny",
                        "agent_guardrail",
                        meta,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                    )
                    raise GuardrailViolationError(
                        f"agent {agent_id!r} exceeded guardrail"
                    )

    def circuit_admits(self, circuit: CircuitBreaker, tenant_id: str | None) -> None:
        """Ask the circuit for permission, or record that shadow mode would not.

        In shadow mode an open circuit is observed and the request proceeds —
        the point of shadow mode is to see what *would* have been blocked
        without blocking it.
        """
        if self.shadow is None:
            circuit.before_request()
        else:
            self.shadow.would_open_circuit(tenant_id=tenant_id)

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def audit(self, decision: str, reason: str, meta: object, **fields: object) -> None:
        """Record an enforcement decision in the tamper-evident audit log."""
        audit_log = self.state.audit
        if audit_log is None:
            return
        fields.setdefault("endpoint", getattr(meta, "endpoint", None))
        fields.setdefault("priority", getattr(meta, "priority", None))
        fields.setdefault("estimated_tokens", getattr(meta, "estimated_tokens", None))
        audit_log.record(decision, reason, **fields)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def after_attempt(
        self, *, success: bool, pressure: bool, circuit: CircuitBreaker | None = None
    ) -> None:
        """Record one attempt's outcome against the circuit and the AIMD limit."""
        tripped = (circuit or self.state.circuit).after_request(success=success)
        if tripped:
            self._metrics.call("circuit_trips")
        if pressure and self.state.aimd.record_pressure():
            self._metrics.call("aimd_changes", "decrease")

    def record_outcome(
        self, status_code: int, *, success: bool, circuit: CircuitBreaker | None = None
    ) -> None:
        """Record a completed request's outcome against the circuit and the AIMD limit."""
        tripped = (circuit or self.state.circuit).after_request(success=success)
        if tripped:
            self._metrics.call("circuit_trips")
        if success:
            if self.state.aimd.record_success():
                self._metrics.call("aimd_changes", "increase")
        elif is_retryable_status(status_code, self.state.config):
            if self.state.aimd.record_pressure():
                self._metrics.call("aimd_changes", "decrease")

    def observe_queue(
        self,
        wait: float,
        priority: Priority,
        tenant_budget: Any | None = None,
        tenant_id: str | None = None,
        circuit: CircuitBreaker | None = None,
    ) -> None:
        """Publish the queue-wait observation and the gauges that go with it.

        The gauges are published **twice** per request — once here, as the
        request enters the service, and once when it leaves. That is not an
        oversight: the first reading is the in-flight one, and it is the only
        moment at which ``concurrency_active`` says how many requests are
        *running* rather than how many are running after this one finished.
        The second reading is the authoritative state.

        It costs about 3.3 µs, five gauge publications at roughly 0.7 µs
        each. The alternative — publishing once, at the end — would make the
        saturation gauge useless for exactly the question it exists to
        answer.
        """
        self._metrics.call("queue_wait", priority.value, method="observe", amount=wait)
        self.observe_gauges(circuit, tenant_budget=tenant_budget, tenant_id=tenant_id)

    def observe_request(
        self, endpoint: str, priority: Priority, started: float, outcome: str
    ) -> None:
        """Publish the request count and its duration."""
        self._metrics.call("requests", endpoint, priority.value, outcome)
        self._metrics.call(
            "duration", endpoint, priority.value, method="observe", amount=time.monotonic() - started
        )

    def observe_gauges(
        self,
        circuit: CircuitBreaker | None = None,
        tenant_budget: Any | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Publish the gauges.

        The tenant's budget is *passed in* rather than re-derived. It used to
        be re-read from the ledger here, on the strength of a ContextVar the
        caller had already resolved — which reported the global
        ``budget_remaining`` for every request made with a virtual key, so a
        per-tenant deployment saw a gauge describing a budget none of its
        requests were spending. The caller passes the budget it actually
        budgeted against, and ``tenant_id`` is the tenant it resolved to.

        The circuit is passed in too, so the gauge reports the circuit the
        request actually went through rather than the global one.
        """
        if tenant_budget is not None:
            remaining = getattr(tenant_budget, "remaining", None)
        elif tenant_id is not None:
            tb = get_ledger().get(tenant_id)
            remaining = tb.remaining if tb is not None else None
        else:
            remaining = self.state.budget.remaining
        if remaining is not None:
            self._metrics.call("budget_remaining", method="set", value=remaining)
        self._metrics.call("queue_depth", method="set", value=self.state.gate.depth)
        self._metrics.call("concurrency_active", method="set", value=self.state.gate.active)
        self._metrics.call("concurrency_limit", method="set", value=self.state.aimd.current_limit)
        active_circuit = circuit or self.state.circuit
        circuit_value = {
            CircuitState.CLOSED: 0,
            CircuitState.HALF_OPEN: 1,
            CircuitState.OPEN: 2,
        }[active_circuit.state]
        self._metrics.call("circuit_state", method="set", value=circuit_value)

    def maybe_forecast_enforce(self) -> None:
        """Proactively tighten AIMD when burn rate projects exhaustion.

        Called after every successful response. When ``forecast_horizon_seconds``
        is configured and the current burn rate would exhaust the budget within
        that horizon, clamp the AIMD concurrency limit to slow down before the
        cap is hit.
        """
        horizon = self.state.config.forecast_horizon_seconds
        if not horizon or self.state.budget.total is None:
            return
        remaining = self.state.budget.remaining
        if remaining is None or remaining <= 0:
            return
        spent = self.state.budget.spent
        if spent <= 0:
            return
        from .forecast import BurnSample, will_exhaust

        sample = BurnSample(used_tokens=spent, window_seconds=max(1.0, min(spent, 30.0)))
        if will_exhaust(sample, self.state.budget.total, horizon):
            self.state.aimd.record_pressure()
            self._metrics.call("aimd_changes", "decrease")

    # ------------------------------------------------------------------
    # Secrets
    # ------------------------------------------------------------------

    def resolve_secret(self, request: httpx.Request) -> None:
        """Resolve a virtual key to a provider secret at call time."""
        cfg = self.state.config
        if cfg.secret_provider is None or cfg.virtual_keys is None:
            return
        vk = request.headers.get(cfg.virtual_key_header)
        if vk is None or vk not in cfg.virtual_keys:
            return
        from .secrets import resolve_secret

        secret = resolve_secret(cfg.secret_provider, vk)
        if secret:
            request.headers["authorization"] = f"Bearer {secret}"

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def cache_get(self, body: dict) -> tuple | None:
        """A cached response for this body, or ``None``.

        The cache — including the semantic one — is built here, once, by
        whichever transport constructed this Policy. It used to be built
        separately by each transport, and the async one left out the
        embedder, so the semantic cache never ran for an async client.
        """
        if self.cache is None:
            return None
        return self.cache.get(body)

    def cache_set(
        self, body: dict, content: bytes, usage: int, headers: dict[str, str]
    ) -> None:
        """Remember this response for a later identical request."""
        if self.cache is None:
            return
        self.cache.set(body, content, usage, headers)

    def note_cache_hit(self, semantic: bool) -> None:
        """Publish a cache hit, and whether it was a near-duplicate match."""
        self._metrics.call("cache_hits")
        if semantic:
            self._metrics.call("cache_semantic_hits")

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def fallback_targets(self, priority: Priority | None) -> list[dict]:
        """The fallback chain to walk, for this request's priority."""
        return self.state.config.fallback_targets(priority)

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def alert_on_spend(self, tenant_id: str | None, tenant_budget: Any | None) -> None:
        """Fire the configured budget alerts, if the current spend crossed one.

        The alert manager is built once, by whichever transport constructed
        this Policy, so the dedup window is shared across requests. It used
        to be rebuilt per request in the gateway, which defeated the dedup
        entirely and fired the same alert on every proxied request.
        """
        if self.alerts is None:
            return
        from .transports import _dispatch_alert

        budget = tenant_budget if tenant_budget is not None else self.state.budget
        used = getattr(budget, "spent", None) or getattr(budget, "used", 0)
        limit = (
            getattr(budget, "total", None)
            or getattr(budget, "limit_tokens", None)
            or getattr(budget, "limit", 0)
        )
        _dispatch_alert(self.alerts, tenant_id, used, limit)


def build_policy(
    state: Any, *, compat: _HttpCompat, config: BackstopConfig | None = None
) -> Policy:
    """Build the Policy for a state: its shadow collector, alerts and cache.

    The cache is built here — with the embedder — so both transports get the
    same one. The semantic cache used to be constructed without the embedder
    on the async path, which is why it never fired there.
    """
    from .cache import ResponseCache
    from .rollout import ShadowCollector

    resolved = config if config is not None else state.config
    shadow = (
        ShadowCollector(sink=state.audit) if ShadowCollector.enabled(resolved.shadow) else None
    )
    alerts = build_alerts(resolved)
    cache = (
        ResponseCache(
            max_entries=resolved.cache_max_entries,
            ttl=resolved.cache_ttl,
            embed=resolved.cache_embedder if resolved.cache_semantic else None,
            similarity_threshold=resolved.cache_similarity_threshold,
        )
        if resolved.cache_enabled
        else None
    )
    return Policy(state, compat=compat, shadow=shadow, alerts=alerts, cache=cache)


def build_alerts(config: BackstopConfig) -> object | None:
    """Build a BudgetAlertManager from config, or None when unconfigured.

    Built here, once, so both transports share one manager and therefore one
    dedup window. It used to be built by each transport, and the gateway
    built one per request — so the same alert fired on every proxied request.
    """
    if not config.webhook_endpoints:
        return None
    from .notifications import BudgetAlertManager

    return BudgetAlertManager(
        endpoints=list(config.webhook_endpoints),
        secret=config.webhook_secret,
        tiers=list(config.alert_tiers) if config.alert_tiers else None,
        dedup_ttl=config.alert_dedup_ttl,
        project_horizon_calls=config.alert_project_horizon_calls,
    )
