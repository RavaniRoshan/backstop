from __future__ import annotations

import os
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from .detection.config import (
    DEFAULT_BASELINE_MULTIPLIER,
    DEFAULT_CONTEXT_GROWTH_THRESHOLD,
    DEFAULT_MAX_KEYS,
    DEFAULT_MIN_SAMPLES,
    DEFAULT_RETRY_RATIO_THRESHOLD,
    DEFAULT_VELOCITY_THRESHOLD_USD_PER_MIN,
    DEFAULT_WINDOW_SIZE,
    DetectionConfig,
)

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
    # Default: provider-first env-last chain (SecretProviderChain).
    secret_provider: Any = None

    # --- Agent guardrails (Deep Research P2#11) ---
    # ``AgentGuard`` instance fencing runaway agent loops.
    agent_guard: Any = None

    # --- Structured logging ---
    # When True, emit a JSON line per request/response to the ``log_sink``
    # (a file path or callable(str)) for operational debugging.
    log_json: bool = False
    log_sink: Any = None

    # --- Cost forecasting → enforcement (Deep Research P1#7) ---
    # When the projected burn rate would exhaust the budget within this
    # horizon, proactively tighten the AIMD concurrency limit. ``0`` disables.
    forecast_horizon_seconds: float = 0.0

    # --- Budget-exhaustion alerts / webhooks (Launch Improvement B1) ---
    # Warn BEFORE the cap. ``webhook_endpoints`` is a list of URLs; ``webhook_secret``
    # anchors the HMAC-SHA256 signature. ``alert_tiers`` are usage fractions that
    # fire ``threshold_crossed``; ``alert_dedup_ttl`` bounds repeat alerts; the
    # manager also emits ``projected_exceeded`` (calls-remaining) when burn rate
    # implies exhaustion within ``alert_project_horizon_calls`` more calls.
    webhook_endpoints: list | None = None
    webhook_secret: str | None = None
    alert_tiers: list[float] | None = None
    alert_dedup_ttl: float = 86400.0
    alert_project_horizon_calls: int = 5

    # --- Safe rollout: shadow / canary (Deep Research P2#13) ---
    # When ``shadow`` is True every enforcement decision (budget block, circuit
    # open, rate-limit, agent-guardrail, latency budget) is *recorded* as a
    # "would-have" but NEVER acted on — requests flow through untouched. This is
    # the enabled!=enforced two-axis rollout primitive (Envoy filter_enabled vs
    # filter_enforced): turn shadow on, watch would_* counters, then flip it off
    # to start enforcing. A kill-switch via env (BACKSTOP_SHADOW=false) overrides.
    shadow: bool = False
    shadow_policy: Any = None

    # --- Spend ledger (Ledger Foundation) ---
    # Off by default, so a process that has not opted in pays one boolean test
    # per request and records nothing. When on, one ``SpendEvent`` is built per
    # completed provider request and handed to a background writer; the request
    # path never touches a file, a socket or a sink. ``ledger_path`` writes
    # append-only NDJSON; without it the events are kept in a bounded in-memory
    # ring of ``ledger_memory_events``, which is what ``backstop ledger demo``
    # and the tests read.
    ledger_enabled: bool = False
    ledger_path: str | None = None
    ledger_memory_events: int = 10_000

    # --- Price catalog (Ledger Foundation) ---
    # A JSON file of negotiated rates, layered over the bundled list prices by
    # ``PriceCatalog.from_file``. Checked for existence here, at construction, so
    # a typo fails at wrap time rather than silently pricing every event at the
    # bundled rate — or at nothing — from the first request onwards.
    price_catalog_path: str | None = None

    # --- Runaway-spend detection (Ledger Foundation) ---
    # Off by default, and shadow-first when on: the detector reports what it
    # would have flagged and never blocks a request.
    #
    # Every threshold and window bound is a field here rather than a frozen
    # default inside :class:`~backstop.detection.config.DetectionConfig`,
    # because a threshold a deployment cannot change is a threshold nobody can
    # tune, and tuning them against a shadow log *before* they bite is the whole
    # purpose of the shadow mode. Each field is the ``DetectionConfig`` field of
    # the same name with a ``detection_`` prefix, which is the convention every
    # other subsystem on this class already follows (``circuit_*``, ``retry_*``,
    # ``cache_*``). :attr:`detection_config` is the one place the two are joined,
    # and therefore the only place the validation rules live.
    detection_enabled: bool = False
    detection_shadow: bool = True
    detection_velocity_threshold_usd_per_min: float = (
        DEFAULT_VELOCITY_THRESHOLD_USD_PER_MIN
    )
    detection_baseline_multiplier: float = DEFAULT_BASELINE_MULTIPLIER
    detection_retry_ratio_threshold: float = DEFAULT_RETRY_RATIO_THRESHOLD
    detection_context_growth_threshold: float = DEFAULT_CONTEXT_GROWTH_THRESHOLD
    detection_window_size: int = DEFAULT_WINDOW_SIZE
    detection_min_samples: int = DEFAULT_MIN_SAMPLES
    detection_max_keys: int = DEFAULT_MAX_KEYS

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
        if self.forecast_horizon_seconds < 0:
            raise ValueError("forecast_horizon_seconds must be >= 0")
        if self.log_json and self.log_sink is None:
            raise ValueError("log_json requires log_sink (file path or callable)")
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
        if not isinstance(self.ledger_enabled, bool):
            raise TypeError(
                f"ledger_enabled must be a bool, got {type(self.ledger_enabled).__name__}"
            )
        if self.ledger_path is not None and not isinstance(self.ledger_path, str):
            raise TypeError(
                f"ledger_path must be a string or None, got "
                f"{type(self.ledger_path).__name__}"
            )
        if self.ledger_path == "":
            raise ValueError("ledger_path must be a non-empty path when set")
        # ``bool`` is an ``int`` subclass, so a stray True would otherwise be
        # read as a ring of one event.
        if isinstance(self.ledger_memory_events, bool) or not isinstance(
            self.ledger_memory_events, int
        ):
            raise TypeError(
                f"ledger_memory_events must be an int, got "
                f"{type(self.ledger_memory_events).__name__}"
            )
        if self.ledger_memory_events < 1:
            raise ValueError(f"ledger_memory_events must be >= 1, got {self.ledger_memory_events}")
        if self.price_catalog_path is not None:
            if not isinstance(self.price_catalog_path, str):
                raise TypeError(
                    f"price_catalog_path must be a string or None, got "
                    f"{type(self.price_catalog_path).__name__}"
                )
            if not os.path.isfile(self.price_catalog_path):
                # Loudly, and here. Loading this file is the first thing
                # BackstopState.create does when a ledger is on, so a bad path
                # found any later would surface as an exception on a request
                # path or — worse — as every event silently priced from the
                # bundled table instead of the rates the user negotiated.
                raise ValueError(
                    f"price_catalog_path does not exist or is not a file: "
                    f"{self.price_catalog_path!r}"
                )
        if not isinstance(self.detection_enabled, bool):
            raise TypeError(
                f"detection_enabled must be a bool, got "
                f"{type(self.detection_enabled).__name__}"
            )
        # Building the detector's config is the validation of every other
        # ``detection_*`` field, so it runs here rather than at the first
        # request: a threshold that could never fire fails at wrap time, beside
        # every other configuration error, with a message naming the knob.
        _detection_config(self)
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
        if self.secret_provider is None and self.virtual_keys:
            # `BackstopConfig` is a frozen dataclass, so a plain assignment raises
            # FrozenInstanceError. That used to be swallowed by a bare
            # `except Exception: pass`, which meant the documented default
            # SecretProviderChain was NEVER installed for anyone: a deployment
            # using virtual keys believed it had per-tenant credentials and
            # silently did not, and its chargeback was built on a fiction.
            # object.__setattr__ is the standard idiom for a frozen dataclass.
            try:
                from .secrets import SecretProviderChain

                object.__setattr__(
                    self, "secret_provider", SecretProviderChain(self.virtual_keys)
                )
            except ImportError:
                # the secrets module is always importable, so this is a guard
                # against a partial install rather than a silent failure path
                pass

    # ------------------------------------------------------------------
    # Runaway-spend detection
    # ------------------------------------------------------------------

    @property
    def detection_config(self) -> DetectionConfig:
        """The resolved :class:`~backstop.detection.config.DetectionConfig`.

        Built from the ``detection_*`` fields, so it cannot disagree with them:
        there is no second copy of a threshold anywhere. Constructing it is also
        how a bad knob is refused, which is why ``__post_init__`` calls the same
        builder — a user sees the error at ``BackstopConfig(...)`` rather than at
        the first request.
        """
        return _detection_config(self)

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



def _detection_config(resolved: BackstopConfig) -> DetectionConfig:
    """Join a config's ``detection_*`` fields into one frozen ``DetectionConfig``.

    A module-level function rather than a method body so ``__post_init__`` and
    :attr:`BackstopConfig.detection_config` cannot drift into two different
    mappings — the mistake this shape exists to prevent, because a threshold set
    on one path and ignored on the other is a threshold that does not exist.

    The prefix is stripped here and nowhere else, so the two vocabularies meet
    at exactly one line. Validation is not repeated:
    :class:`~backstop.detection.config.DetectionConfig` refuses a negative
    threshold, a multiplier below 1.0, a non-finite number, a zero window, a
    ``min_samples`` larger than the window and a non-``bool`` switch, with a
    message naming the knob — so a deployment cannot reach a state the detector
    module itself considers nonsense, and there is one implementation of that
    rule rather than two that can disagree.
    """
    return DetectionConfig(
        enabled=resolved.detection_enabled,
        shadow=resolved.detection_shadow,
        velocity_threshold_usd_per_min=resolved.detection_velocity_threshold_usd_per_min,
        baseline_multiplier=resolved.detection_baseline_multiplier,
        retry_ratio_threshold=resolved.detection_retry_ratio_threshold,
        context_growth_threshold=resolved.detection_context_growth_threshold,
        window_size=resolved.detection_window_size,
        min_samples=resolved.detection_min_samples,
        max_keys=resolved.detection_max_keys,
    )
