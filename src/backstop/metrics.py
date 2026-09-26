"""The metric surface every instrumented decision in Backstop reports through.

One object, one choke point: :meth:`Metrics.call` is fed by the transports, the
admission gate, the circuit breaker and the runaway-spend detector, and it fans
out to three consumers in one place — the optional Prometheus registry, the
optional OTel mirror, and the dependency-free :class:`~backstop.telemetry.TelemetrySink`
the built-in dashboard reads. A new instrument is declared here and nowhere
else, so a signal that is not on this surface is a signal nobody polls.

**The label rule, because it is the one that bites:** a label is a fixed,
bounded vocabulary, never a user-supplied string. ``endpoint``/``priority``/
``outcome`` and ``kind``/``severity`` are drawn from closed sets the code
declares; the attribution a runaway detector fired on is *not*, because a
per-team or per-session label multiplies the time series by the number of teams
or sessions — a cardinality explosion in the scrape, and a user identifier in a
label is a user identifier in everyone's monitoring storage. The offending key
belongs in the detector's own bounded ring and in the log line, not in a label.
"""
from __future__ import annotations

from typing import Any


_OTEL: Any | None = None

# Optional dependency-free consumer (the built-in dashboard). ``None`` unless a
# dashboard is running, so an ordinary install pays a single comparison per
# instrumented event — see ``backstop.telemetry``.
_TELEMETRY_SINK: Any | None = None


def set_telemetry_sink(sink: Any | None) -> None:
    """Install a callable receiving ``(name, args, method, kwargs)`` per event."""
    global _TELEMETRY_SINK
    _TELEMETRY_SINK = sink


def enable_otel(meter_name: str = "backstop") -> bool:
    """Initialize the optional OTel mirror. Returns True if it became active."""
    global _OTEL
    try:
        from .otel import OtelMetrics

        _OTEL = OtelMetrics(meter_name)
    except Exception:
        _OTEL = None
    return bool(_OTEL and _OTEL.enabled)


def disable_otel() -> None:
    global _OTEL
    _OTEL = None


class Metrics:
    def __init__(self) -> None:
        try:
            from prometheus_client import Counter, Gauge, Histogram
        except Exception:
            self.enabled = False
            return

        self.enabled = True
        self.requests = Counter(
            "backstop_requests_total",
            "Backstop HTTP requests.",
            ["endpoint", "priority", "outcome"],
        )
        self.duration = Histogram(
            "backstop_request_duration_seconds",
            "Backstop request duration.",
            ["endpoint", "priority"],
        )
        self.budget_exceeded = Counter(
            "backstop_budget_exceeded_total",
            "Requests blocked by token budget.",
        )
        self.budget_remaining = Gauge(
            "backstop_budget_remaining_tokens",
            "Remaining token budget.",
        )
        self.queue_depth = Gauge(
            "backstop_queue_depth",
            "Queued requests.",
        )
        self.queue_wait = Histogram(
            "backstop_queue_wait_seconds",
            "Time spent waiting for admission.",
            ["priority"],
        )
        self.concurrency_active = Gauge(
            "backstop_concurrency_active",
            "Active admitted requests.",
        )
        self.concurrency_limit = Gauge(
            "backstop_concurrency_limit",
            "Current AIMD concurrency limit.",
        )
        self.circuit_state = Gauge(
            "backstop_circuit_state",
            "Circuit state: closed=0, half_open=1, open=2.",
        )
        self.circuit_trips = Counter(
            "backstop_circuit_trips_total",
            "Circuit breaker open transitions.",
        )
        self.retry_attempts = Counter(
            "backstop_retry_attempts_total",
            "Retry attempts.",
            ["endpoint"],
        )
        self.aimd_changes = Counter(
            "backstop_aimd_changes_total",
            "AIMD limit changes.",
            ["direction"],
        )
        self.cache_hits = Counter(
            "backstop_cache_hits_total",
            "Cache hit count.",
        )
        self.cache_semantic_hits = Counter(
            "backstop_cache_semantic_hits_total",
            "Semantic (near-duplicate) cache hit count.",
        )
        self.fallback_attempts = Counter(
            "backstop_fallback_attempts_total",
            "Fallback attempts.",
        )
        self.rate_limited = Counter(
            "backstop_rate_limited_total",
            "Requests rejected by pluggable rate limiter.",
        )
        self.tenant_budget_exceeded = Counter(
            "backstop_tenant_budget_exceeded_total",
            "Requests blocked by per-tenant budget.",
            ["tenant_id"],
        )
        # --- Runaway-spend detection ---
        # ``kind`` and ``severity`` are the two closed sets
        # ``backstop.detection.SIGNAL_KINDS`` and ``SEVERITIES``, so the series
        # count is fixed at four by three however many attribution keys fire.
        # The key itself is deliberately absent: see the label rule in the module
        # docstring.
        self.detection_signals = Counter(
            "backstop_detection_signals_total",
            "Runaway-spend signals raised, by detector and severity.",
            ["kind", "severity"],
        )
        # The magnitude that crossed the threshold, so a threshold can be tuned
        # against the distribution of what actually crossed it rather than
        # against a count that says only that something did.
        self.detection_signal_magnitude = Histogram(
            "backstop_detection_signal_observed",
            "The observed value that raised a runaway-spend signal.",
            ["kind"],
        )
        self.detection_evictions = Counter(
            "backstop_detection_evictions_total",
            "Attribution keys dropped from the runaway-spend detector to stay "
            "within its key bound. Each one is a key whose baseline was reset.",
        )

    def call(self, name: str, *args: Any, method: str = "inc", **kwargs: Any) -> None:
        # Dependency-free consumer first: unlike Prometheus (an optional extra),
        # the built-in dashboard works in a bare `pip install backstop`.
        sink = _TELEMETRY_SINK
        if sink is not None:
            sink(name, args, method, kwargs)
        if not getattr(self, "enabled", False):
            return
        metric = getattr(self, name)
        if args:
            metric = metric.labels(*args)
        getattr(metric, method)(**kwargs)
        if _OTEL is not None and _OTEL.enabled:
            _OTEL.call(name, *args, method=method, **kwargs)


_METRICS = Metrics()


def get_metrics() -> Metrics:
    return _METRICS


def start_metrics_server(port: int = 9090) -> None:
    from prometheus_client import start_http_server

    start_http_server(port)


def metrics_app() -> object:
    from prometheus_client import make_wsgi_app

    return make_wsgi_app()

