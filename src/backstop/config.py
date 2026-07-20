from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .hooks import AfterHookCallback, BeforeHookCallback

TokenCounter = Callable[[str, str], int] | None
Embedder = Callable[[str], "list[float]"] | None


class Priority(str, Enum):
    CRITICAL = "critical"
    DEFAULT = "default"
    BACKGROUND = "background"

    @classmethod
    def from_header(cls, value: str | None) -> "Priority":
        if not value:
            return cls.DEFAULT
        normalized = value.strip().lower()
        for priority in cls:
            if priority.value == normalized:
                return priority
        return cls.DEFAULT


@dataclass(frozen=True)
class BackstopConfig:
    default_max_output_tokens: int = 1024
    chars_per_token: float = 4.0

    retry_max_attempts: int = 3
    retry_base_delay: float = 0.05
    retry_max_delay: float = 2.0
    retry_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504, 529})

    circuit_window_seconds: float = 60.0
    circuit_failure_threshold: float = 0.20
    circuit_cooldown_seconds: float = 30.0
    circuit_min_requests: int = 5

    initial_concurrency: int = 8
    min_concurrency: int = 1
    max_concurrency: int = 64
    aimd_increase: int = 1
    aimd_decrease_factor: float = 0.5
    aimd_adjustment_interval: float = 5.0

    starvation_after_seconds: float = 1.0

    queue_timeout: float | None = None
    request_timeout: float | None = None

    before_request: BeforeHookCallback | None = None
    after_response: AfterHookCallback | None = None

    cache_enabled: bool = False
    cache_max_entries: int = 256
    cache_ttl: float = 60.0
    # Semantic (near-duplicate) caching: opt-in. Requires ``cache_embedder``; on
    # an exact miss the prompt embedding is compared (cosine) against cached
    # entries and a match >= ``cache_similarity_threshold`` is short-circuited.
    cache_semantic: bool = False
    cache_similarity_threshold: float = 0.95
    cache_embedder: Embedder = None

    token_counter: TokenCounter | None = None

    # --- Shared (distributed) budget backend (Tier 1 / P1) ---
    # When ``shared_budget`` is True (or ``redis_url`` is set), the token
    # budget is enforced through Redis so N processes/replicas share one cap.
    shared_budget: bool = False
    redis_url: str | None = None
    redis_key: str | None = None

    # --- In-process fallback (Tier 1 / P3) ---
    # On a sustained provider failure (circuit open) Backstop walks an ordered
    # fallback chain *within the same process* before failing. The single
    # ``fallback_model``/``fallback_base_url`` pair is still supported (it is
    # normalized into a one-entry chain); ``fallback_chain`` overrides it and
    # allows multiple backup models / deployments. ``fallback_chain_for_priority``
    # optionally maps a Priority to its own ordered chain for priority routing.
    fallback_model: str | None = None
    fallback_base_url: str | None = None
    fallback_chain: list[dict] | None = None
    fallback_chain_for_priority: dict | None = None

    # --- OpenTelemetry export (Tier 1 / P2) ---
    # Mirrors the Prometheus series to an OTel meter when installed. Off by
    # default so existing installs are unaffected.
    otel_enabled: bool = False
    otel_meter_name: str = "backstop"

    # --- Concurrency ceiling (Tier 3 / P10) ---
    # Soft cap on simultaneously-active ``wrap()`` sessions in one process. The
    # Python GIL means many concurrent in-process sessions serialize on it; past
    # this many live sessions Backstop emits a warning instead of silently
    # degrading. ``0`` disables the check.
    max_wrap_sessions: int = 0

    # --- Audit log (Deep Research P2#8) ---
    # Tamper-evident, chained JSONL of every enforcement decision. ``audit_sink``
    # is a file path or a callable(str). ``audit_hmac_key`` anchors the chain.
    audit_enabled: bool = False
    audit_sink: Any = None
    audit_hmac_key: str | None = None

    # --- Cloud-quota-aware auto-tuning (Deep Research P1#5) ---
    # Ingest provider ``x-ratelimit-*`` / ``anthropic-ratelimit-*`` headers and
    # proactively clamp AIMD concurrency before 429s hit.
    quota_aware: bool = True

    # --- True per-tenant circuit breaker (Deep Research P1#4) ---
    # Maintain a separate circuit per tenant id (falls back to the global one).
    per_tenant_circuit: bool = False

    # --- Virtual keys + hierarchical budgets (Deep Research P1#3) ---
    # api_key -> tenant_id; the key is read from ``virtual_key_header`` and the
    # request is scoped to that tenant's (possibly hierarchical) budget.
    virtual_keys: dict | None = None
    virtual_key_header: str = "X-Backstop-Key"

    # --- tiktoken pre-estimation (Deep Research P1#12) ---
    # Opt-in: use tiktoken (when installed) for accurate pre-dispatch token
    # counts instead of the chars/4 heuristic. Off by default so existing
    # installs keep identical budgeting behavior.
    auto_token_count: bool = False

    # --- Pluggable rate limiter + pre-send compression (Deep Research P1#12) ---
    # ``rate_limiter`` is any object with ``allow(tokens) -> bool`` (e.g.
    # ``TokenBucketLimiter``); ``compress`` is ``callable(body, model) -> body``.
    rate_limiter: Any = None
    compress: Callable | None = None

    # --- Secret provider (Deep Research P2#9) ---
    # Resolves virtual keys / tenant ids to provider secrets at call time.
    secret_provider: Any = None

    # --- Agent guardrails (Deep Research P2#11) ---
    # ``AgentGuard`` instance fencing runaway agent loops.
    agent_guard: Any = None

    # --- Safe rollout: shadow / canary (Deep Research P2#13) ---
    shadow_policy: Any = None

    def __post_init__(self) -> None:
        if self.default_max_output_tokens < 0:
            raise ValueError("default_max_output_tokens must be >= 0")
        if self.chars_per_token <= 0:
            raise ValueError("chars_per_token must be > 0")
        if self.retry_max_attempts < 1:
            raise ValueError("retry_max_attempts must be >= 1")
        if self.retry_base_delay < 0 or self.retry_max_delay < 0:
            raise ValueError("retry delays must be >= 0")
        if not 0 < self.circuit_failure_threshold <= 1:
            raise ValueError("circuit_failure_threshold must be in (0, 1]")
        if self.circuit_window_seconds <= 0:
            raise ValueError("circuit_window_seconds must be > 0")
        if self.circuit_cooldown_seconds < 0:
            raise ValueError("circuit_cooldown_seconds must be >= 0")
        if self.circuit_min_requests < 1:
            raise ValueError("circuit_min_requests must be >= 1")
        if self.min_concurrency < 1:
            raise ValueError("min_concurrency must be >= 1")
        if self.max_concurrency < self.min_concurrency:
            raise ValueError("max_concurrency must be >= min_concurrency")
        if not self.min_concurrency <= self.initial_concurrency <= self.max_concurrency:
            raise ValueError("initial_concurrency must be within min/max bounds")
        if not 0 < self.aimd_decrease_factor < 1:
            raise ValueError("aimd_decrease_factor must be in (0, 1)")
        if self.aimd_adjustment_interval < 0:
            raise ValueError("aimd_adjustment_interval must be >= 0")
        if self.starvation_after_seconds < 0:
            raise ValueError("starvation_after_seconds must be >= 0")
        if self.queue_timeout is not None and self.queue_timeout <= 0:
            raise ValueError("queue_timeout must be > 0 when set")
        if self.request_timeout is not None and self.request_timeout <= 0:
            raise ValueError("request_timeout must be > 0 when set")
        if self.cache_max_entries < 1:
            raise ValueError("cache_max_entries must be >= 1")
        if self.cache_ttl <= 0:
            raise ValueError("cache_ttl must be > 0")
        if self.shared_budget and self.redis_url is None:
            # Default Redis URL is acceptable; just ensure the flag is coherent.
            pass
        if self.fallback_model is not None and not isinstance(self.fallback_model, str):
            raise ValueError("fallback_model must be a string or None")
        if self.fallback_base_url is not None and not isinstance(self.fallback_base_url, str):
            raise ValueError("fallback_base_url must be a string or None")
        if self.otel_meter_name is None or not isinstance(self.otel_meter_name, str):
            raise ValueError("otel_meter_name must be a non-empty string")
        if self.max_wrap_sessions < 0:
            raise ValueError("max_wrap_sessions must be >= 0")
        if self.audit_enabled:
            if self.audit_hmac_key is None:
                raise ValueError("audit_enabled requires audit_hmac_key for tamper-evidence")
            if not (isinstance(self.audit_sink, str) or callable(self.audit_sink)):
                raise ValueError("audit_sink must be a file path (str) or callable when audit_enabled")
        if self.virtual_keys is not None and not isinstance(self.virtual_keys, dict):
            raise ValueError("virtual_keys must be a dict of api_key -> tenant_id")
        if not isinstance(self.virtual_key_header, str) or not self.virtual_key_header:
            raise ValueError("virtual_key_header must be a non-empty header name")
        if self.cache_semantic and self.cache_embedder is None:
            raise ValueError("cache_semantic requires cache_embedder (an embedding callable)")
        if not 0.0 < self.cache_similarity_threshold <= 1.0:
            raise ValueError("cache_similarity_threshold must be in (0, 1]")
        if self.fallback_chain is not None:
            if not isinstance(self.fallback_chain, list) or not self.fallback_chain:
                raise ValueError("fallback_chain must be a non-empty list of {model, base_url?} dicts")
            for entry in self.fallback_chain:
                if not isinstance(entry, dict) or not isinstance(entry.get("model"), str):
                    raise ValueError("each fallback_chain entry needs a string 'model'")
        if self.fallback_chain_for_priority is not None:
            if not isinstance(self.fallback_chain_for_priority, dict):
                raise ValueError("fallback_chain_for_priority must be a dict keyed by Priority")
            for prio, chain in self.fallback_chain_for_priority.items():
                if not isinstance(chain, list) or not chain:
                    raise ValueError(f"fallback_chain_for_priority[{prio!r}] must be a non-empty list")
                for entry in chain:
                    if not isinstance(entry, dict) or not isinstance(entry.get("model"), str):
                        raise ValueError(f"fallback_chain_for_priority[{prio!r}] entries need a string 'model'")

    # ------------------------------------------------------------------
    # Fallback chain resolution
    # ------------------------------------------------------------------
    def _entry(self, model: str, base_url: str | None) -> dict:
        entry = {"model": model}
        if base_url:
            entry["base_url"] = base_url
        return entry

    def fallback_targets(self, priority: "Priority | None" = None) -> list[dict]:
        """Ordered list of fallback targets to try on circuit-open.

        Priority-aware chains (``fallback_chain_for_priority``) take precedence
        when the request priority has a configured chain; otherwise the shared
        ``fallback_chain`` is used, then the single ``fallback_model`` pair.
        """
        if (
            priority is not None
            and self.fallback_chain_for_priority
            and priority.value in self.fallback_chain_for_priority
        ):
            return [e for e in self.fallback_chain_for_priority[priority.value] if isinstance(e, dict)]
        if self.fallback_chain:
            return [e for e in self.fallback_chain if isinstance(e, dict)]
        if self.fallback_model:
            return [self._entry(self.fallback_model, self.fallback_base_url)]
        return []

    def tenant_for_key(self, key: str | None) -> str | None:
        """Resolve a virtual key header value to a tenant id, if configured."""
        if key is None or self.virtual_keys is None:
            return None
        return self.virtual_keys.get(key)

    def __getattr__(self, name: str) -> Any:
        if name == "priority_weights":
            warnings.warn(
                "priority_weights is removed in v0.2 and has no effect",
                DeprecationWarning,
                stacklevel=2,
            )
            return {}
        msg = f"{type(self).__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)

