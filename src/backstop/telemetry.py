"""Dependency-free in-process telemetry for the built-in dashboard.

Backstop already holds everything a dashboard needs in memory: the token budget,
the AIMD controller, the admission gate, the circuit breaker, the tenant ledger,
and one :class:`~backstop.state.BackstopState` per ``wrap()`` session. This
module turns that live state into a bounded, JSON-serialisable snapshot.

Deliberate constraints (rationale in ``docs/dashboard.md``):

* **No storage, no retention, no query language.** A fixed-size ring of samples
  in memory; nothing is written to disk and nothing survives the process.
  Backstop still does not store, query, or visualise metrics — it renders state
  it already owns.
* **No hot-path cost when unused.** The sink is ``None`` unless a dashboard is
  actually running, so an ordinary install pays a single comparison per
  instrumented event.
* **No required dependencies.** Everything here is stdlib. The Prometheus
  registry is read opportunistically when ``prometheus_client`` is installed,
  never required.
* **Bounded memory.** Sessions, events, and samples are all capped.
"""
from __future__ import annotations

import itertools
import json
import os
import threading
import time
import weakref
from collections import deque
from dataclasses import dataclass
from typing import Any

# --- Bounds. Every collection in this module is capped so that a long-running
# --- dashboard cannot grow without limit.
MAX_SAMPLES = 360            # 12 minutes of history at the 2s default cadence
MAX_SESSION_ROWS = 64
MAX_EVENT_ROWS = 200
MAX_LATENCY_SAMPLES = 512
MAX_AUDIT_TAIL_BYTES = 64 * 1024
DEFAULT_SAMPLE_INTERVAL = 2.0

# Label positions for each instrumented event, mirroring the declarations in
# ``backstop.metrics``. ``tests/test_telemetry.py`` asserts that this covers
# every call site in ``backstop.transports``, so the two cannot drift.
LABEL_NAMES: dict[str, tuple[str, ...]] = {
    "requests": ("endpoint", "priority", "outcome"),
    "duration": ("endpoint", "priority"),
    "queue_wait": ("priority",),
    "retry_attempts": ("endpoint",),
    "aimd_changes": ("direction",),
    "tenant_budget_exceeded": ("tenant_id",),
}

# Outcomes recorded by ``transports.py``: "success", "error", "fallback",
# "circuit_open", "exception". The first three imply a provider call; the last
# two are requests the guardrails stopped before dispatch.


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile over an unsorted list (0.0 when empty)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = int(round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[index]


def _matches(name: str, args: tuple[str, ...], match: dict[str, str]) -> bool:
    names = LABEL_NAMES.get(name, ())
    for label, wanted in match.items():
        if label not in names:
            return False
        if args[names.index(label)] != wanted:
            return False
    return True


class TelemetrySink:
    """Counts instrumented events with no third-party dependency.

    Fed from :meth:`backstop.metrics.Metrics.call`, which is the single choke
    point every enforcement decision already flows through. Keeping the sink
    behind that indirection is what makes the dashboard possible without
    touching the hot path in ``transports.py``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[str, ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[str, ...]], float] = {}
        self._durations: deque[float] = deque(maxlen=MAX_LATENCY_SAMPLES)
        self._queue_waits: deque[float] = deque(maxlen=MAX_LATENCY_SAMPLES)

    # --- write side (called once per instrumented event) ---
    def record(
        self, name: str, args: tuple[Any, ...], method: str, kwargs: dict[str, Any]
    ) -> None:
        key = (name, tuple(str(a) for a in args))
        if method == "observe":
            amount = kwargs.get("amount")
            if amount is None:
                return
            target = self._queue_waits if name == "queue_wait" else self._durations
            with self._lock:
                target.append(float(amount))
            return
        if method == "set":
            value = kwargs.get("value")
            if value is None:
                return
            with self._lock:
                self._gauges[key] = float(value)
            return
        amount = float(kwargs.get("amount", 1.0))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + amount

    # --- read side (called once per dashboard sample, not per request) ---
    def counter_total(self, name: str, match: dict[str, str] | None = None) -> float:
        with self._lock:
            items = [(k, v) for k, v in self._counters.items() if k[0] == name]
        if match:
            items = [(k, v) for k, v in items if _matches(name, k[1], match)]
        return float(sum(v for _, v in items))

    def gauge(self, name: str, match: dict[str, str] | None = None) -> float | None:
        with self._lock:
            items = [(k, v) for k, v in self._gauges.items() if k[0] == name]
        if match:
            items = [(k, v) for k, v in items if _matches(name, k[1], match)]
        if not items:
            return None
        return float(items[-1][1])

    def breakdown(self, name: str, label: str) -> dict[str, float]:
        """Totals for one counter split by a single label, e.g. outcome mix."""
        names = LABEL_NAMES.get(name, ())
        if label not in names:
            return {}
        position = names.index(label)
        out: dict[str, float] = {}
        with self._lock:
            items = [(k, v) for k, v in self._counters.items() if k[0] == name]
        for key, value in items:
            if len(key[1]) <= position:
                continue
            bucket = key[1][position]
            out[bucket] = out.get(bucket, 0.0) + value
        return out

    def latency_snapshot(self) -> list[float]:
        with self._lock:
            return list(self._durations)

    def queue_wait_snapshot(self) -> list[float]:
        with self._lock:
            return list(self._queue_waits)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._durations.clear()
            self._queue_waits.clear()


@dataclass
class SessionRow:
    """One live ``BackstopState`` (i.e. one ``wrap()`` session)."""

    session_id: str
    created_at: float
    ref: "weakref.ref[Any]"

    @property
    def alive(self) -> bool:
        return self.ref() is not None


class SessionRegistry:
    """Tracks live sessions so per-agent budget isolation is visible.

    Registration is automatic in :meth:`BackstopState.create`, and the reference
    is weak, so a wrapped client that is garbage collected silently leaves the
    registry. The row count is capped, so a process that churns sessions (or a
    test suite) cannot grow this without limit.
    """

    def __init__(self, max_rows: int = MAX_SESSION_ROWS) -> None:
        self._rows: deque[SessionRow] = deque(maxlen=max_rows)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def register(self, state: Any) -> str:
        session_id = f"bs-{next(self._ids)}"
        try:
            ref: weakref.ref[Any] = weakref.ref(state)
        except TypeError:  # pragma: no cover - all states are weakref-able
            return session_id
        with self._lock:
            self._rows.append(SessionRow(session_id, time.time(), ref))
        return session_id

    def states(self) -> list[tuple[SessionRow, Any]]:
        """Live (row, state) pairs, pruning entries whose state was collected."""
        with self._lock:
            rows = list(self._rows)
        live: list[tuple[SessionRow, Any]] = []
        dead: list[SessionRow] = []
        for row in rows:
            state = row.ref()
            if state is None:
                dead.append(row)
            else:
                live.append((row, state))
        if dead:
            with self._lock:
                for row in dead:
                    try:
                        self._rows.remove(row)
                    except ValueError:  # pragma: no cover - already pruned
                        pass
        return live

    def reset(self) -> None:
        with self._lock:
            self._rows.clear()


_SINK: TelemetrySink | None = None
_REGISTRY = SessionRegistry()
_SINK_LOCK = threading.RLock()
_DASHBOARD_USERS: dict[TelemetrySink, int] = {}
_DASHBOARD_OWNED: set[TelemetrySink] = set()


def get_sink() -> TelemetrySink | None:
    """The active sink, or ``None`` when capture is disabled."""
    return _SINK


def get_registry() -> SessionRegistry:
    return _REGISTRY


def install_sink() -> TelemetrySink:
    """Start capturing events into a fresh dependency-free sink."""
    global _SINK
    with _SINK_LOCK:
        _SINK = TelemetrySink()
        _bind_metrics()
        return _SINK


def uninstall_sink() -> None:
    """Stop capturing. After this the hot path is back to a single comparison."""
    global _SINK
    with _SINK_LOCK:
        _SINK = None
        _bind_metrics()


def acquire_dashboard_sink() -> TelemetrySink:
    """Share existing capture, or create capture owned by live dashboards."""
    with _SINK_LOCK:
        sink = get_sink()
        if sink is None:
            sink = install_sink()
            _DASHBOARD_OWNED.add(sink)
        _DASHBOARD_USERS[sink] = _DASHBOARD_USERS.get(sink, 0) + 1
        return sink


def release_dashboard_sink(sink: TelemetrySink) -> None:
    """Release a dashboard lease without disabling another owner's capture."""
    with _SINK_LOCK:
        users = _DASHBOARD_USERS.get(sink, 0)
        if users > 1:
            _DASHBOARD_USERS[sink] = users - 1
            return
        _DASHBOARD_USERS.pop(sink, None)
        if sink in _DASHBOARD_OWNED:
            _DASHBOARD_OWNED.remove(sink)
            if get_sink() is sink:
                uninstall_sink()


def _bind_metrics() -> None:
    from .metrics import set_telemetry_sink

    sink = _SINK
    if sink is None:
        set_telemetry_sink(None)
        return
    set_telemetry_sink(sink.record)


def reset_telemetry() -> None:
    """Drop the sink and every registered session (used by tests)."""
    uninstall_sink()
    _REGISTRY.reset()


_CIRCUIT_RANK = {"closed": 0, "half_open": 1, "open": 2}


def _circuit_label(circuit: Any) -> str:
    state = getattr(circuit, "state", None)
    value = getattr(state, "value", state)
    return str(value) if value is not None else "closed"


def session_view() -> dict[str, Any]:
    """Aggregate the live ``BackstopState`` objects into a fleet view.

    This is the one number the Prometheus export cannot provide: the global
    ``backstop_budget_remaining_tokens`` / ``backstop_circuit_state`` gauges are
    unlabelled, so with several ``wrap()`` sessions in one process they are
    last-writer-wins. Reading the states directly gives per-session truth and a
    correct aggregate.
    """
    rows: list[dict[str, Any]] = []
    limit_total = 0
    spent_total = 0
    remaining_total = 0
    any_unlimited = False
    active = 0
    capacity = 0
    queued = 0
    worst = "closed"
    now = time.time()

    for row, state in get_registry().states():
        budget = getattr(state, "budget", None)
        total = getattr(budget, "total", None)
        remaining = getattr(budget, "remaining", None)
        spent = int(getattr(budget, "spent", 0) or 0)
        aimd = getattr(state, "aimd", None)
        gate = getattr(state, "gate", None)
        circuit = getattr(state, "circuit", None)

        session_limit = int(getattr(aimd, "current_limit", 0) or 0)
        session_active = int(getattr(gate, "active", 0) or 0)
        session_queued = int(getattr(gate, "depth", 0) or 0)
        circuit_label = _circuit_label(circuit)

        if total is None:
            any_unlimited = True
        else:
            limit_total += int(total)
        if remaining is None:
            any_unlimited = True
        else:
            remaining_total += int(remaining)
        spent_total += spent
        active += session_active
        capacity += session_limit
        queued += session_queued
        if _CIRCUIT_RANK.get(circuit_label, 0) > _CIRCUIT_RANK.get(worst, 0):
            worst = circuit_label

        rows.append(
            {
                "session_id": row.session_id,
                "provider": str(getattr(state, "provider", "") or ""),
                "age_s": max(0.0, now - row.created_at),
                "budget_limit": int(total) if total is not None else None,
                "budget_spent": spent,
                "budget_remaining": int(remaining) if remaining is not None else None,
                "budget_pct_used": (
                    round(100.0 * spent / int(total), 1) if total else None
                ),
                "circuit": circuit_label,
                "concurrency_limit": session_limit,
                "concurrency_active": session_active,
                "queued": session_queued,
                "shared_budget": bool(getattr(getattr(state, "config", None), "shared_budget", False)),
            }
        )

    return {
        "sessions": rows,
        "session_count": len(rows),
        "budget_limit": None if any_unlimited else limit_total,
        "budget_spent": spent_total,
        "budget_remaining": None if any_unlimited else remaining_total,
        "concurrency_active": active,
        "concurrency_limit": capacity,
        "queued": queued,
        "circuit": worst,
    }


def _audit_path(default: str | None = None) -> str | None:
    """First file-backed audit sink visible from any live session."""
    if default and os.path.exists(default):
        return default
    for _, state in get_registry().states():
        sink = getattr(getattr(state, "config", None), "audit_sink", None)
        if isinstance(sink, str) and os.path.exists(sink):
            return sink
    return default


def _tail_lines(path: str, limit: int) -> list[str]:
    """Read the last ``limit`` lines of a file without loading the whole file."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    start = max(0, size - MAX_AUDIT_TAIL_BYTES)
    try:
        with open(path, "rb") as handle:
            handle.seek(start)
            chunk = handle.read()
    except OSError:
        return []
    text = chunk.decode("utf-8", errors="replace")
    if start > 0:
        # Drop the first, possibly partial, line.
        _, _, text = text.partition("\n")
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-limit:]


# Fields safe to render. Audit records never contain prompt text, but hooks can
# attach arbitrary metadata, so the dashboard renders an allowlist rather than
# whatever happens to be in the record.
_AUDIT_FIELDS = (
    "ts",
    "decision",
    "reason",
    "endpoint",
    "priority",
    "estimated_tokens",
    "tenant_id",
    "model",
)


def audit_events(path: str | None, limit: int = MAX_EVENT_ROWS) -> list[dict[str, Any]]:
    if not path:
        return []
    events: list[dict[str, Any]] = []
    for line in _tail_lines(path, limit)[::-1]:
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        event = {key: record.get(key) for key in _AUDIT_FIELDS if record.get(key) is not None}
        if not event:
            # A record with none of the allowlisted fields carries nothing the
            # dashboard can render, so it is dropped rather than shown blank.
            continue
        events.append(event)
    return events


@dataclass
class Sample:
    """One point in the dashboard's rolling window."""

    t: float
    requests: float = 0.0
    success: float = 0.0
    errors: float = 0.0
    prevented: float = 0.0
    provider_calls: float = 0.0
    cache_hits: float = 0.0
    retries: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    budget_spent: float = 0.0
    budget_remaining: float | None = None
    concurrency_active: float = 0.0
    concurrency_limit: float = 0.0


def collect_sample(sink: TelemetrySink) -> Sample:
    """Read the sink plus live session state into one point."""
    durations = sink.latency_snapshot()
    view = session_view()
    success = sink.counter_total("requests", {"outcome": "success"})
    errors = sink.counter_total("requests", {"outcome": "error"})
    fallback = sink.counter_total("requests", {"outcome": "fallback"})
    # "circuit_open" and "exception" outcomes are requests that never reached a
    # provider, so they are prevention, not traffic.
    prevented = (
        sink.counter_total("budget_exceeded")
        + sink.counter_total("rate_limited")
        + sink.counter_total("requests", {"outcome": "circuit_open"})
        + sink.counter_total("requests", {"outcome": "exception"})
    )
    retries = sink.counter_total("retry_attempts")
    return Sample(
        t=time.time(),
        requests=sink.counter_total("requests"),
        success=success,
        errors=errors,
        prevented=prevented,
        # Every retry is an additional provider call, so it is counted here.
        provider_calls=success + errors + fallback + retries,
        cache_hits=sink.counter_total("cache_hits") + sink.counter_total("cache_semantic_hits"),
        retries=retries,
        latency_p50_ms=percentile(durations, 50) * 1000.0,
        latency_p95_ms=percentile(durations, 95) * 1000.0,
        latency_p99_ms=percentile(durations, 99) * 1000.0,
        budget_spent=float(view["budget_spent"]),
        budget_remaining=view["budget_remaining"],
        concurrency_active=float(view["concurrency_active"]),
        concurrency_limit=float(view["concurrency_limit"]),
    )


class Sampler:
    """Samples the sink into a bounded ring at a fixed cadence.

    Sampling happens on a timer, never on the request path, so the dashboard's
    cost is proportional to the refresh rate and not to traffic.
    """

    def __init__(self, interval: float = DEFAULT_SAMPLE_INTERVAL) -> None:
        self.interval = max(0.25, float(interval))
        self.started_at = time.time()
        self._ring: deque[Sample] = deque(maxlen=MAX_SAMPLES)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sample_once(self) -> Sample | None:
        sink = get_sink()
        if sink is None:
            return None
        sample = collect_sample(sink)
        with self._lock:
            self._ring.append(sample)
        return sample

    def series(self) -> list[Sample]:
        with self._lock:
            return list(self._ring)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="backstop-dashboard-sampler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.sample_once()
            except Exception:  # pragma: no cover - a sampler must never die
                pass
            self._stop.wait(self.interval)


_RATE_WINDOW = 60.0


def _recent_window(
    samples: list[Sample], window_s: float = _RATE_WINDOW
) -> tuple[Sample, Sample] | None:
    """The oldest and newest samples spanning at most ``window_s``."""
    if len(samples) < 2:
        return None
    last = samples[-1]
    first = samples[0]
    for sample in reversed(samples):
        if last.t - sample.t > window_s:
            break
        first = sample
    if last.t <= first.t:
        return None
    return first, last


def _cost_lower_bound(tokens: float, model: str | None) -> float | None:
    """USD for ``tokens`` at the model's *input* rate — an explicit lower bound.

    Backstop's counters carry a single total-token figure, so the dashboard
    cannot split prompt from completion tokens. Costing everything at the input
    rate understates spend, which is the safe direction for a budget tool.
    Returns ``None`` when no model is configured or the model is unpriced
    (``estimate_cost`` returns 0.0 only for unknown models).
    """
    if not model or not tokens or tokens <= 0:
        return None
    try:
        from .pricing import estimate_cost

        cost = estimate_cost(int(tokens), 0, model)
    except Exception:
        return None
    return cost if cost > 0 else None


def tenant_view(limit: int = 50) -> list[dict[str, Any]]:
    from .ledger import get_ledger

    rows: list[dict[str, Any]] = []
    for tenant_id, tenant in get_ledger().tenants.items():
        cap = int(getattr(tenant, "limit_tokens", 0) or 0)
        used = int(getattr(tenant, "used", 0) or 0)
        rows.append(
            {
                "tenant_id": tenant_id,
                "limit": cap,
                "used": used,
                "reserved": int(getattr(tenant, "reserved", 0) or 0),
                "remaining": int(getattr(tenant, "remaining", 0) or 0),
                "pct_used": round(100.0 * used / cap, 1) if cap else None,
            }
        )
    rows.sort(key=lambda row: row["used"], reverse=True)
    return rows[:limit]


def _rate_series(samples: list[Sample], key: str, scale: float = 1.0) -> list[float]:
    """Per-sample rate of a cumulative counter, in units per second (* scale)."""
    out: list[float] = []
    prev: tuple[float, float] | None = None
    for sample in samples:
        value = float(getattr(sample, key) or 0.0)
        if prev is None:
            out.append(0.0)
        else:
            dt = sample.t - prev[0]
            out.append(round(((value - prev[1]) / dt) * scale, 4) if dt > 0 else 0.0)
        prev = (sample.t, value)
    return out


def build_snapshot(
    sampler: Sampler,
    *,
    mode: str = "live",
    cost_model: str | None = None,
    audit: str | None = None,
) -> dict[str, Any]:
    """Assemble the JSON document the dashboard renders.

    Pure derivation over the sampler ring, the sink and live session state — the
    only I/O is reading the audit tail, so this is safe to call at the refresh
    interval and can never block a request.
    """
    samples = sampler.series()
    latest = samples[-1] if samples else Sample(t=time.time())
    view = session_view()
    sink = get_sink()
    resolved_audit = _audit_path(audit)

    window = _recent_window(samples)
    if window is None:
        rps = 0.0
        burn_per_sec = 0.0
        window_seconds = 0.0
    else:
        first, last = window
        window_seconds = max(1e-9, last.t - first.t)
        rps = max(0.0, (last.requests - first.requests) / window_seconds)
        burn_per_sec = max(0.0, (last.budget_spent - first.budget_spent) / window_seconds)

    # Budget figures come from live sessions. When there are none (their states
    # were garbage-collected, or the dashboard is attached to a finished run)
    # report null rather than a misleading zero, falling back to the last gauge
    # value the sink observed.
    if view["session_count"] > 0:
        limit = view["budget_limit"]
        remaining = view["budget_remaining"]
        spent = view["budget_spent"]
    else:
        gauge = sink.gauge("budget_remaining") if sink is not None else None
        limit = None
        remaining = int(gauge) if gauge is not None else None
        spent = None
    # Projected exhaustion is only meaningful for a bounded budget that is
    # actually burning; otherwise it is explicitly null rather than a fake "inf".
    eta_seconds = (
        remaining / burn_per_sec
        if remaining is not None and remaining > 0 and burn_per_sec > 0
        else None
    )

    requests = int(latest.requests)
    provider_calls = int(latest.provider_calls)
    prevented = int(latest.prevented)
    cache_hits = int(latest.cache_hits)
    attempts = requests + prevented + cache_hits
    outcomes = sink.breakdown("requests", "outcome") if sink else {}

    warnings: list[str] = []
    if view["session_count"] == 0:
        warnings.append(
            "No live sessions registered yet. Wrap a client "
            "(Backstop.wrap(...)) in this process, or run with --demo."
        )
    if not resolved_audit:
        warnings.append(
            "No audit log configured, so the enforcement event stream is empty. "
            "Set BackstopConfig(audit_enabled=True, audit_sink='audit.jsonl')."
        )

    return {
        # Millisecond precision: enough for a "generated Ns ago" display, and
        # keeps payloads byte-stable across rapid polls (see the ETag in
        # ``dashboard_app.py``, which also excludes this field).
        "generated_at": round(time.time(), 3),
        "sampled_at": latest.t if samples else None,
        "sample_age_s": max(0.0, time.time() - latest.t) if samples else None,
        "uptime_s": round(max(0.0, time.time() - sampler.started_at), 1),
        "mode": mode,
        "sample_interval_s": sampler.interval,
        "window_seconds": round(window_seconds, 2),
        "sinks": {
            "telemetry": sink is not None,
            "prometheus": _prometheus_active(),
            "cost_model": cost_model,
        },
        "warnings": warnings,
        "kpi": {
            "budget": {
                "limit": limit,
                "spent": spent,
                "remaining": remaining,
                "pct_used": round(100.0 * spent / limit, 1) if limit and spent is not None else None,
                "burn_tokens_per_min": round(burn_per_sec * 60.0, 2),
                "eta_seconds": eta_seconds,
            },
            "spend": {
                "tokens": spent,
                "usd_lower_bound": _cost_lower_bound(spent, cost_model),
                "prevented_usd_lower_bound": _cost_lower_bound(prevented, cost_model),
            },
            "prevention": {
                "total": prevented,
                "budget_blocked": _counter(sink, "budget_exceeded"),
                # A subset of budget_blocked: blocks caused by a tenant bucket.
                "tenant_blocked": _counter(sink, "tenant_budget_exceeded"),
                "rate_limited": _counter(sink, "rate_limited"),
                "circuit_open": int(outcomes.get("circuit_open", 0)),
                "exceptions": int(outcomes.get("exception", 0)),
                "cache_avoided": cache_hits,
            },
            "traffic": {
                "requests": requests,
                "provider_calls": provider_calls,
                "success": int(latest.success),
                "errors": int(latest.errors),
                "retries": int(latest.retries),
                "rps": round(rps, 3),
                "provider_efficiency": round(provider_calls / requests, 3) if requests else None,
            },
            "latency": {
                # backstop_request_duration_seconds covers the whole transport
                # call, provider time included. This is end-to-end request
                # latency, *not* the guardrail overhead figure — that is the
                # separate in-process measurement reported by
                # `backstop benchmark` (~0.12 ms p50 on a mock transport).
                "p50_ms": round(latest.latency_p50_ms, 4),
                "p95_ms": round(latest.latency_p95_ms, 4),
                "p99_ms": round(latest.latency_p99_ms, 4),
                "includes_provider": True,
            },
            "concurrency": {
                "active": view["concurrency_active"],
                "capacity": view["concurrency_limit"],
                "queued": view["queued"],
            },
            "cache": {
                "hits": cache_hits,
                "hit_rate": round(cache_hits / attempts, 4) if attempts else None,
            },
            "circuit": {
                "state": view["circuit"],
                "trips": _counter(sink, "circuit_trips"),
            },
            "isolation": {"sessions": view["session_count"]},
        },
        "series": {
            "t": [round(sample.t - sampler.started_at, 2) for sample in samples],
            "requests": [int(sample.requests) for sample in samples],
            "rps": _rate_series(samples, "requests"),
            "prevented": [int(sample.prevented) for sample in samples],
            "prevented_rps": _rate_series(samples, "prevented"),
            "provider_calls": [int(sample.provider_calls) for sample in samples],
            "latency_p95_ms": [round(sample.latency_p95_ms, 4) for sample in samples],
            "budget_remaining": [sample.budget_remaining for sample in samples],
            "burn_tokens_per_min": _rate_series(samples, "budget_spent", 60.0),
            "concurrency_active": [int(sample.concurrency_active) for sample in samples],
        },
        "sessions": view["sessions"],
        "tenants": tenant_view(),
        "events": audit_events(resolved_audit),
        "outcomes": outcomes,
        "audit": {
            "path": resolved_audit,
            "verified": None,
            "note": (
                "Chain integrity is not re-checked here: the dashboard reads only a "
                "tail of the log, and the HMAC chain is verifiable only from genesis. "
                "Run `backstop verify` for a full replay."
            ),
        },
    }


def _counter(sink: TelemetrySink | None, name: str) -> int:
    return int(sink.counter_total(name)) if sink else 0


def _prometheus_active() -> bool:
    try:
        from .metrics import get_metrics

        return bool(getattr(get_metrics(), "enabled", False))
    except Exception:  # pragma: no cover - defensive
        return False