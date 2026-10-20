from __future__ import annotations

import threading
from typing import Any


class OtelMetrics:
    """Vendor-neutral metrics mirror of the Prometheus series.

    Lazily imports ``opentelemetry`` so installs without it are unaffected.
    When the SDK/exporter is unavailable this becomes a safe no-op. Gauges are
    exposed as observable gauges backed by the last value observed in-process.

    There is no exemplar bookkeeping here. An OTel exemplar is a trace link on
    a metric point, and the SDK attaches one from the active span when a point
    is recorded inside a span — so a hand-kept mapping from metric name to
    trace id was a second, parallel mechanism that nothing ever wrote to.
    """

    def __init__(self, meter_name: str = "backstop") -> None:
        self.enabled = False
        self._gauges: dict[str, float] = {}
        # The gauge dict is written from arbitrary request threads — one per
        # in-flight request — and read by the observable-gauge callback. A bare
        # dict write is atomic under CPython, but the callback iterating it
        # while another thread writes is not, so the lock is here for the
        # iteration, not for the write.
        self._gauge_lock = threading.Lock()
        try:
            from opentelemetry import metrics as otel_metrics
        except Exception:
            return

        try:
            meter = otel_metrics.get_meter(meter_name)
        except Exception:
            return

        self.enabled = True
        self._meter = meter

        self.requests = meter.create_counter(
            "backstop_requests_total",
            description="Backstop HTTP requests.",
        )
        self.duration = meter.create_histogram(
            "backstop_request_duration_seconds",
            description="Backstop request duration.",
        )
        self.budget_exceeded = meter.create_counter(
            "backstop_budget_exceeded_total",
            description="Requests blocked by token budget.",
        )
        self.queue_wait = meter.create_histogram(
            "backstop_queue_wait_seconds",
            description="Time spent waiting for admission.",
        )
        self.circuit_trips = meter.create_counter(
            "backstop_circuit_trips_total",
            description="Circuit breaker open transitions.",
        )
        self.retry_attempts = meter.create_counter(
            "backstop_retry_attempts_total",
            description="Retry attempts.",
        )
        self.aimd_changes = meter.create_counter(
            "backstop_aimd_changes_total",
            description="AIMD limit changes.",
        )
        self.cache_hits = meter.create_counter(
            "backstop_cache_hits_total",
            description="Cache hit count.",
        )
        self.cache_semantic_hits = meter.create_counter(
            "backstop_cache_semantic_hits_total",
            description="Semantic (near-duplicate) cache hit count.",
        )
        self.fallback_attempts = meter.create_counter(
            "backstop_fallback_attempts_total",
            description="Fallback attempts.",
        )
        self.rate_limited = meter.create_counter(
            "backstop_rate_limited_total",
            description="Requests rejected by pluggable rate limiter.",
        )
        self.tenant_budget_exceeded = meter.create_counter(
            "backstop_tenant_budget_exceeded_total",
            description="Requests blocked by per-tenant budget.",
        )
        self.detection_signals = meter.create_counter(
            "backstop_detection_signals_total",
            description="Runaway-spend signals raised, by detector and severity.",
        )
        self.detection_signal_magnitude = meter.create_histogram(
            "backstop_detection_signal_observed",
            description="The observed value that raised a runaway-spend signal.",
        )
        self.detection_evictions = meter.create_counter(
            "backstop_detection_evictions_total",
            description="Attribution keys dropped from the runaway-spend detector "
            "to stay within its key bound.",
        )

        for name, desc in (
            ("backstop_budget_remaining_tokens", "Remaining token budget."),
            ("backstop_queue_depth", "Queued requests."),
            ("backstop_concurrency_active", "Active admitted requests."),
            ("backstop_concurrency_limit", "Current AIMD concurrency limit."),
            ("backstop_circuit_state", "Circuit state: closed=0, half_open=1, open=2."),
        ):
            try:
                meter.create_observable_gauge(
                    name,
                    callbacks=[self._gauge_callback(name)],
                    description=desc,
                )
            except Exception:
                pass

    def _gauge_callback(self, name: str):
        def cb(options: Any):
            # The read is under the lock because the write happens on
            # arbitrary request threads; the callback may fire between two
            # of them.
            with self._gauge_lock:
                value = self._gauges.get(name, 0.0)
            from opentelemetry.metrics import Observation

            return [Observation(value)]

        return cb

    def _set_gauge(self, name: str, value: float) -> None:
        with self._gauge_lock:
            self._gauges[name] = float(value)

    def _inc_counter(self, counter: Any, amount: float, attrs: dict) -> None:
        try:
            counter.add(amount, attrs)
        except Exception:
            pass

    def _record_hist(self, hist: Any, amount: float, attrs: dict) -> None:
        try:
            hist.record(amount, attrs)
        except Exception:
            pass

    def call(self, name: str, *args: Any, method: str = "inc", **kwargs: Any) -> None:
        if not self.enabled:
            return

        attrs = {}
        if args:
            attr_keys = {
                "requests": ["endpoint", "priority", "outcome"],
                "duration": ["endpoint", "priority"],
                "queue_wait": ["priority"],
                "retry_attempts": ["endpoint"],
                "aimd_changes": ["direction"],
                "detection_signals": ["kind", "severity"],
                "detection_signal_magnitude": ["kind"],
            }.get(name)
            if attr_keys:
                for key, value in zip(attr_keys, args, strict=False):
                    attrs[key] = value

        try:
            if name == "requests":
                self._inc_counter(self.requests, 1, attrs)
            elif name == "duration":
                self._record_hist(self.duration, float(kwargs.get("amount", 0)), attrs)
            elif name == "budget_exceeded":
                self._inc_counter(self.budget_exceeded, 1, attrs)
            elif name == "queue_wait":
                self._record_hist(self.queue_wait, float(kwargs.get("amount", 0)), attrs)
            elif name == "circuit_trips":
                self._inc_counter(self.circuit_trips, 1, attrs)
            elif name == "retry_attempts":
                self._inc_counter(self.retry_attempts, 1, attrs)
            elif name == "aimd_changes":
                self._inc_counter(self.aimd_changes, 1, attrs)
            elif name == "cache_hits":
                self._inc_counter(self.cache_hits, 1, attrs)
            elif name == "cache_semantic_hits":
                self._inc_counter(self.cache_semantic_hits, 1, attrs)
            elif name == "fallback_attempts":
                self._inc_counter(self.fallback_attempts, 1, attrs)
            elif name == "rate_limited":
                self._inc_counter(self.rate_limited, 1, attrs)
            elif name == "tenant_budget_exceeded":
                self._inc_counter(self.tenant_budget_exceeded, 1, attrs)
            elif name == "detection_signals":
                self._inc_counter(self.detection_signals, 1, attrs)
            elif name == "detection_signal_magnitude":
                self._record_hist(
                    self.detection_signal_magnitude, float(kwargs.get("amount", 0)), attrs
                )
            elif name == "detection_evictions":
                self._inc_counter(self.detection_evictions, 1, attrs)
            elif name == "budget_remaining":
                self._set_gauge("backstop_budget_remaining_tokens", float(kwargs.get("value", 0)))
            elif name == "queue_depth":
                self._set_gauge("backstop_queue_depth", float(kwargs.get("value", 0)))
            elif name == "concurrency_active":
                self._set_gauge("backstop_concurrency_active", float(kwargs.get("value", 0)))
            elif name == "concurrency_limit":
                self._set_gauge("backstop_concurrency_limit", float(kwargs.get("value", 0)))
            elif name == "circuit_state":
                self._set_gauge("backstop_circuit_state", float(kwargs.get("value", 0)))
        except Exception:
            pass
