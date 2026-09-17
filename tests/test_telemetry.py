from __future__ import annotations

import gc
import re
import time
from pathlib import Path

import httpx
import pytest

from backstop.config import BackstopConfig
from backstop.state import BackstopState
from backstop.telemetry import (
    LABEL_NAMES,
    TelemetrySink,
    audit_events,
    get_registry,
    get_sink,
    install_sink,
    percentile,
    reset_telemetry,
    session_view,
    tenant_view,
    uninstall_sink,
)
from backstop.transports import BackstopTransport

_TRANSPORTS = Path(__file__).resolve().parents[1] / "src" / "backstop" / "transports.py"


@pytest.fixture(autouse=True)
def _clean_telemetry():
    reset_telemetry()
    yield
    reset_telemetry()


def _make_state(budget: int = 10_000) -> BackstopState:
    return BackstopState.create(budget, BackstopConfig())


def _exercise(state: BackstopState, *, status: int = 200) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}},
        )

    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )
    try:
        client.post("/v1/chat/completions", json={"model": "mock", "messages": []})
    finally:
        client.close()


# --- label schema contract ----------------------------------------------------


def test_label_schema_covers_every_labelled_transport_call_site():
    """LABEL_NAMES cannot drift from the events transports.py actually emits.

    A call is "labelled" when its first argument after the metric name is
    positional rather than a keyword such as ``method=`` or ``value=``. The
    lookahead must span the whole identifier so ``method=`` never passes as a
    label by backtracking into a shorter match.
    """
    source = _TRANSPORTS.read_text(encoding="utf-8")
    labelled = set(
        re.findall(
            r'_metrics\.call\(\s*"([a-z_]+)",\s*(?:"[^"]*"|[A-Za-z_][\w.\[\]]*)(?![\w.\[\]]*\s*=)',
            source,
        )
    )
    assert labelled, "expected to find instrumented call sites with labels"
    missing = sorted(labelled - set(LABEL_NAMES))
    stale = sorted(set(LABEL_NAMES) - labelled)
    assert not missing, f"telemetry.LABEL_NAMES is missing labels for: {missing}"
    assert not stale, f"telemetry.LABEL_NAMES has entries nothing emits: {stale}"


# --- sink ---------------------------------------------------------------------


def test_sink_records_counters_gauges_and_observations():
    sink = TelemetrySink()
    sink.record("requests", ("/v1/chat/completions", "default", "success"), "inc", {})
    sink.record("requests", ("/v1/chat/completions", "default", "success"), "inc", {})
    sink.record("requests", ("/v1/chat/completions", "critical", "circuit_open"), "inc", {})
    sink.record("budget_remaining", (), "set", {"value": 42})
    sink.record("duration", ("/v1/chat/completions", "default"), "observe", {"amount": 0.25})

    assert sink.counter_total("requests") == 3
    assert sink.counter_total("requests", {"outcome": "success"}) == 2
    assert sink.counter_total("requests", {"priority": "critical"}) == 1
    assert sink.counter_total("requests", {"outcome": "nope"}) == 0
    assert sink.gauge("budget_remaining") == 42
    assert sink.breakdown("requests", "outcome") == {"success": 2.0, "circuit_open": 1.0}
    assert sink.latency_snapshot() == [0.25]


def test_sink_ignores_missing_values_and_unknown_breakdown_labels():
    sink = TelemetrySink()
    sink.record("budget_remaining", (), "set", {})
    sink.record("duration", (), "observe", {})
    assert sink.gauge("budget_remaining") is None
    assert sink.latency_snapshot() == []
    assert sink.breakdown("requests", "not_a_label") == {}


def test_percentile_edges():
    assert percentile([], 50) == 0.0
    assert percentile([2.0], 95) == 2.0
    assert percentile([1.0, 2.0, 3.0], 50) == 2.0


# --- session registry --------------------------------------------------------


def test_state_create_registers_a_session():
    # The reference must be held: the registry is weak, so a session that
    # nobody owns is (correctly) not visible.
    state = _make_state()
    view = session_view()
    assert view["session_count"] == 1
    assert view["budget_limit"] == 10_000
    assert view["budget_remaining"] == 10_000
    assert view["sessions"][0]["session_id"].startswith("bs-")
    assert state.budget.remaining == 10_000


def test_registry_drops_sessions_whose_state_was_collected():
    state = _make_state()
    assert session_view()["session_count"] == 1
    del state
    gc.collect()
    assert session_view()["session_count"] == 0


def test_session_aggregate_sums_across_isolated_sessions():
    """Three runners must report three independent budgets, not one clobbered one.

    This is the case the unlabelled Prometheus gauges cannot express.
    """
    states = [_make_state(20_000) for _ in range(3)]
    try:
        view = session_view()
        assert view["session_count"] == 3
        assert view["budget_limit"] == 60_000
        assert view["budget_remaining"] == 60_000
        assert view["circuit"] == "closed"
    finally:
        del states
        gc.collect()


def test_unlimited_budget_aggregates_to_none():
    bounded = _make_state()
    unlimited = BackstopState.create(None, BackstopConfig())
    view = session_view()
    assert view["session_count"] == 2
    assert view["budget_limit"] is None
    assert view["budget_remaining"] is None
    assert bounded.budget.total == 10_000
    assert unlimited.budget.total is None


# --- sink installation -------------------------------------------------------


def test_install_and_uninstall_sink_toggles_capture():
    assert get_sink() is None
    _exercise(_make_state())
    assert get_sink() is None

    sink = install_sink()
    assert get_sink() is sink
    _exercise(_make_state())
    assert sink.counter_total("requests", {"outcome": "success"}) == 1

    uninstall_sink()
    assert get_sink() is None


def test_capture_works_without_prometheus_client():
    """A bare ``pip install backstop`` disables the Prometheus object; the
    dashboard must still capture events through the same call site."""
    from backstop import metrics as metrics_module

    metrics = metrics_module.get_metrics()
    original = metrics.enabled
    try:
        metrics.enabled = False
        sink = install_sink()
        _exercise(_make_state())
        assert sink.counter_total("requests", {"outcome": "success"}) == 1
        assert sink.latency_snapshot()  # duration was observed
    finally:
        metrics.enabled = original


def test_reset_telemetry_clears_sink_and_sessions():
    install_sink()
    state = _make_state()
    assert get_sink() is not None
    assert session_view()["session_count"] == 1
    reset_telemetry()
    assert get_sink() is None
    assert session_view()["session_count"] == 0
    del state
    gc.collect()


def test_registry_max_rows_is_bounded():
    registry = get_registry()
    rows = registry._rows
    try:
        registry._rows = type(rows)(maxlen=2)
        registry.reset()
        for _ in range(4):
            registry.register(_make_state())
        assert len(registry._rows) == 2
    finally:
        registry.reset()
        registry._rows = type(rows)(maxlen=rows.maxlen)


# --- sampler + snapshot ------------------------------------------------------


def test_sampler_records_nothing_without_a_sink():
    from backstop.telemetry import Sampler

    sampler = Sampler(interval=0.25)
    assert sampler.sample_once() is None
    assert sampler.series() == []


def test_snapshot_reports_null_budget_when_no_sessions_are_live():
    """A missing session must read as unknown, never as a confident zero."""
    from backstop.harness import run_harness
    from backstop.telemetry import Sampler, build_snapshot

    install_sink()
    sampler = Sampler(interval=0.25)
    sampler.sample_once()
    run_harness("burst")
    sampler.sample_once()

    snapshot = build_snapshot(sampler, mode="test")
    assert snapshot["kpi"]["isolation"]["sessions"] == 0
    assert snapshot["kpi"]["budget"]["limit"] is None
    assert snapshot["kpi"]["budget"]["pct_used"] is None
    assert snapshot["kpi"]["spend"]["tokens"] is None
    # Traffic counters are still real even though the sessions were collected.
    assert snapshot["kpi"]["traffic"]["requests"] == 50
    assert snapshot["kpi"]["traffic"]["rps"] > 0


def test_snapshot_derives_kpis_from_a_live_demo_session():
    """Demo KPIs come from the spawned child; the parent registry stays empty.

    Intentional contract change: the demo workload is a facade over an isolated
    child process, so the parent no longer registers demo sessions in the
    global registry and no longer needs a sink. The dashboard must still see
    real KPIs via bounded IPC.
    """
    from backstop.dashboard_demo import RUNNER_BUDGET, DemoWorkload

    workload = DemoWorkload(runners=2)
    try:
        workload.start(interval=0.25, cost_model="gpt-4o")
        deadline = 10.0
        elapsed = 0.0
        while workload.requests_driven < 6 and elapsed < deadline:
            time.sleep(0.25)
            elapsed += 0.25
        snapshot = workload.snapshot()
    finally:
        workload.stop()

    assert workload.requests_driven >= 6, "demo workload did not drive traffic"
    kpi = snapshot["kpi"]
    assert kpi["isolation"]["sessions"] == 2
    assert kpi["budget"]["limit"] == RUNNER_BUDGET * 2
    assert kpi["budget"]["remaining"] is not None
    assert kpi["traffic"]["requests"] > 0
    assert kpi["traffic"]["provider_calls"] >= 1
    assert kpi["latency"]["p95_ms"] > 0
    assert kpi["spend"]["usd_lower_bound"] > 0
    assert snapshot["mode"] == "demo"
    assert snapshot["sampled_at"] is not None
    assert snapshot["sample_age_s"] is not None and snapshot["sample_age_s"] < 5.0
    assert len(snapshot["series"]["t"]) == len(snapshot["series"]["rps"])
    assert json_roundtrip(snapshot)


def test_demo_process_isolated_from_parent_registry_and_sink():
    """All mock metrics, sessions, tenants, audits stay inside the child."""
    import gc

    from backstop.dashboard_demo import DemoWorkload

    assert get_registry().states() == []
    assert get_sink() is None
    workload = DemoWorkload(runners=2)
    workload.start(interval=0.25)
    try:
        deadline = 10.0
        elapsed = 0.0
        while workload.requests_driven < 3 and elapsed < deadline:
            time.sleep(0.25)
            elapsed += 0.25
        snapshot = workload.snapshot()
        assert workload.requests_driven >= 3
        gc.collect()
        # The parent's global registry must stay empty while the demo runs.
        assert get_registry().states() == []
        # Demo capture must not leak into the parent's telemetry sink.
        assert get_sink() is None
        # The child is a distinct process that owns the synthetic traffic.
        assert snapshot["kpi"]["isolation"]["sessions"] == workload.runners
        assert snapshot["mode"] == "demo"
        assert snapshot["sampled_at"] is not None
    finally:
        workload.stop()
    assert get_registry().states() == []
    assert get_sink() is None


def test_demo_construction_does_not_pollute_parent_telemetry():
    from backstop.dashboard_demo import DemoWorkload

    workload = DemoWorkload(runners=3)
    # Building the workload (which builds lanes and clients) registers nothing
    # and starts nothing: pollution happens only on start().
    assert get_registry().states() == []
    assert get_sink() is None
    del workload


def test_real_and_demo_traffic_coexist_without_cross_talk():
    """Real capture in the parent must run alongside an isolated demo child."""
    from backstop.dashboard_demo import DemoWorkload

    sink = install_sink()
    state = _make_state()
    _exercise(state)
    assert sink.counter_total("requests", {"outcome": "success"}) == 1

    workload = DemoWorkload(runners=2)
    workload.start(interval=0.25)
    try:
        deadline = 10.0
        elapsed = 0.0
        while workload.requests_driven < 3 and elapsed < deadline:
            time.sleep(0.25)
            elapsed += 0.25
        demo = workload.snapshot()
        assert demo["kpi"]["isolation"]["sessions"] == 2
    finally:
        workload.stop()

    # Demo isolation: the parent registry holds only the real session, and the
    # real sink only counted the real request.
    assert session_view()["session_count"] == 1
    assert sink.counter_total("requests", {"outcome": "success"}) == 1
    assert get_sink() is sink


def test_build_snapshot_reports_sample_freshness():
    from backstop.telemetry import Sampler, build_snapshot

    install_sink()
    sampler = Sampler(interval=0.25)
    snapshot = build_snapshot(sampler, mode="test")
    # No samples yet: the freshness fields are honest nulls.
    assert snapshot["sampled_at"] is None
    assert snapshot["sample_age_s"] is None

    sampler.sample_once()
    snapshot = build_snapshot(sampler, mode="test")
    assert snapshot["sampled_at"] is not None
    assert 0.0 <= snapshot["sample_age_s"] < 5.0
    assert json_roundtrip(snapshot)


def json_roundtrip(payload):
    import json

    return isinstance(json.loads(json.dumps(payload, default=str)), dict)


def test_snapshot_marks_prevention_and_provider_efficiency():
    from backstop.telemetry import Sampler, build_snapshot

    sink = install_sink()
    sink.record("requests", ("/v1/chat/completions", "default", "success"), "inc", {})
    sink.record("requests", ("/v1/chat/completions", "default", "circuit_open"), "inc", {})
    sink.record("budget_exceeded", (), "inc", {})
    sink.record("retry_attempts", ("/v1/chat/completions",), "inc", {})
    sampler = Sampler(interval=0.25)
    sampler.sample_once()

    kpi = build_snapshot(sampler, mode="test")["kpi"]
    assert kpi["prevention"]["total"] == 2  # budget_exceeded + circuit_open
    assert kpi["prevention"]["budget_blocked"] == 1
    assert kpi["prevention"]["circuit_open"] == 1
    # success(1) + error(0) + fallback(0) + retry(1)
    assert kpi["traffic"]["provider_calls"] == 2
    assert kpi["traffic"]["requests"] == 2
    assert kpi["traffic"]["provider_efficiency"] == 1.0


# --- cost, tenants, audit tail ----------------------------------------------


def test_cost_is_a_lower_bound_and_none_when_unconfigured():
    from backstop.telemetry import _cost_lower_bound

    assert _cost_lower_bound(1_000, None) is None
    assert _cost_lower_bound(0, "gpt-4o") is None
    assert _cost_lower_bound(None, "gpt-4o") is None
    assert _cost_lower_bound(1_000, "not-a-real-model") is None
    assert _cost_lower_bound(1_000, "gpt-4o") > 0


def test_tenant_view_reads_the_ledger():
    from backstop.ledger import TenantBudget, get_ledger, reset_ledger

    reset_ledger()
    try:
        get_ledger().register(
            {
                "acme": TenantBudget("acme", 1_000, used=250),
                "globex": TenantBudget("globex", 500, used=500),
            }
        )
        rows = tenant_view()
        assert [row["tenant_id"] for row in rows] == ["globex", "acme"]
        assert rows[0]["pct_used"] == 100.0
        assert rows[1]["remaining"] == 750
    finally:
        reset_ledger()


def test_audit_events_reads_a_tail_and_only_renders_safe_fields(tmp_path):
    from backstop.audit import AuditLog

    path = tmp_path / "audit.jsonl"
    log = AuditLog(str(path), "key")
    log.record("deny", "budget exceeded", endpoint="/v1/chat/completions", estimated_tokens=10)
    log.record("cache_hit", "semantic", endpoint="/v1/messages", secret_field="do-not-render")

    events = audit_events(str(path))
    assert len(events) == 2
    newest = events[0]
    assert newest["decision"] == "cache_hit"
    # Allowlisted fields only: unknown keys never reach the dashboard.
    assert "secret_field" not in newest
    assert events[1]["estimated_tokens"] == 10


def test_audit_events_tolerates_missing_and_corrupt_files(tmp_path):
    from backstop.telemetry import audit_events

    assert audit_events(None) == []
    assert audit_events(str(tmp_path / "absent.jsonl")) == []

    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text("not json\n{}\n", encoding="utf-8")
    assert audit_events(str(corrupt)) == []


def test_audit_path_is_discovered_from_a_live_session(tmp_path):
    from backstop.audit import AuditLog
    from backstop.telemetry import Sampler, _audit_path, build_snapshot

    path = tmp_path / "audit.jsonl"
    AuditLog(str(path), "key").record("deny", "budget exceeded")
    state = BackstopState.create(
        1_000, BackstopConfig(audit_enabled=True, audit_sink=str(path), audit_hmac_key="key")
    )
    try:
        assert _audit_path(None) == str(path)
        install_sink()
        sampler = Sampler(interval=0.25)
        sampler.sample_once()
        snapshot = build_snapshot(sampler, mode="test")
        assert snapshot["audit"]["path"] == str(path)
        # A tail cannot re-verify an HMAC chain that starts at genesis.
        assert snapshot["audit"]["verified"] is None
        assert snapshot["events"][0]["decision"] == "deny"
        assert not any("audit log" in w for w in snapshot["warnings"])
    finally:
        del state
        gc.collect()