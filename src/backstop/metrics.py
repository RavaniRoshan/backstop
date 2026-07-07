from __future__ import annotations

from typing import Any


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
        self.budget_remaining = Gauge(
            "backstop_budget_remaining_tokens",
            "Remaining token budget.",
        )
        self.budget_exceeded = Counter(
            "backstop_budget_exceeded_total",
            "Requests blocked by token budget.",
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
        self.tenant_budget_exceeded = Counter(
            "backstop_tenant_budget_exceeded_total",
            "Requests blocked by per-tenant budget.",
            ["tenant_id"],
        )

    def call(self, name: str, *args: Any, method: str = "inc", **kwargs: Any) -> None:
        if not getattr(self, "enabled", False):
            return
        metric = getattr(self, name)
        if args:
            metric = metric.labels(*args)
        getattr(metric, method)(**kwargs)


_METRICS = Metrics()


def get_metrics() -> Metrics:
    return _METRICS


def start_metrics_server(port: int = 9090) -> None:
    from prometheus_client import start_http_server

    start_http_server(port)


def metrics_app() -> object:
    from prometheus_client import make_wsgi_app

    return make_wsgi_app()

