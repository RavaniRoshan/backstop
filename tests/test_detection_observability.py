"""A runaway-spend signal has to reach somewhere an operator already looks.

The detector's own return value is not a surface: a signal recorded in a
process-local ring that no module reads is indistinguishable from a detector
that never fired. So these tests are written from the *outside* — a threshold
breach, driven through the transport, read back off the metric surface and off
the dashboard's session view — because that is the only claim a user can rely
on.

The cardinality rule is part of that contract and is asserted rather than
documented: a signal names the attribution it fired on, and that string is a
user identifier with unbounded variety, so it must not become a Prometheus
label. Every label these instruments carry is drawn from a closed set the code
declares.
"""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from backstop import BackstopConfig
from backstop.detection import SEVERITIES, SIGNAL_KINDS
from backstop.ledger import Attribution, CostBreakdown, SpendEvent
from backstop.state import BackstopState, DetectionSignalSink
from backstop.telemetry import (
    TelemetrySink,
    detection_view,
    get_registry,
    install_sink,
    reset_telemetry,
    session_view,
)
from backstop.transports import BackstopTransport

OPENAI_BODY = {
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "hello"}],
    "max_tokens": 8,
}
#: A response whose usage is large enough that a handful of requests crosses even
#: the deliberately low velocity threshold these tests configure.
OPENAI_RESPONSE = {
    "id": "chatcmpl-detect-1",
    "object": "chat.completion",
    "model": "gpt-4o-2024-08-06",
    "usage": {
        "prompt_tokens": 900_000,
        "completion_tokens": 100_000,
        "total_tokens": 1_000_000,
    },
}
QUANTUM = Decimal("0.000001")


@pytest.fixture(autouse=True)
def _clean_telemetry():
    reset_telemetry()
    yield
    reset_telemetry()


def _state(**overrides) -> BackstopState:
    """A state whose detector is on, in shadow, and tuned to trip on a burst.

    Tuning the threshold is the point of the exercise, so the test does the
    tuning rather than waiting for a real runaway: a small window, two samples of
    history, and a velocity threshold a real provider call clears by a mile.
    """
    config = BackstopConfig(
        default_max_output_tokens=8,
        retry_max_attempts=1,
        aimd_adjustment_interval=0,
        detection_enabled=True,
        detection_window_size=8,
        detection_min_samples=2,
        detection_velocity_threshold_usd_per_min=0.0001,
        **overrides,
    )
    return BackstopState.create(10_000_000, config)


def _handler(payload: dict, status: int = 200):
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handle


def _burst(state: BackstopState, count: int = 4) -> None:
    """``count`` successful requests, each one priced and each one observed."""
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(_handler(OPENAI_RESPONSE))),
        base_url="https://api.openai.com",
    )
    with client:
        for _ in range(count):
            response = client.post("/v1/chat/completions", json=OPENAI_BODY)
            assert response.status_code == 200


def _priced_event(**overrides) -> SpendEvent:
    """A real priced event, so a detector test does not depend on a rate card."""
    amount = Decimal("5.000000")
    half = (amount / 2).quantize(QUANTUM)
    return SpendEvent(
        provider="openai",
        model="gpt-4o",
        endpoint="https://api.openai.com/v1/chat/completions",
        priority="default",
        outcome="success",
        input_tokens=1000,
        output_tokens=200,
        estimated=False,
        attribution=Attribution(team="payments", feature="checkout-v2"),
        cost=CostBreakdown(
            input_usd=half,
            output_usd=(amount - half).quantize(QUANTUM),
            cache_read_usd=Decimal("0.000000"),
            cache_write_usd=Decimal("0.000000"),
            total_usd=amount.quantize(QUANTUM),
            currency="USD",
            price_source="bundled",
            estimated_tokens=False,
            priced_components=frozenset({"input", "output"}),
        ),
        **overrides,
    )


def _recorded(sink: TelemetrySink) -> list[tuple[str, tuple[str, ...]]]:
    """Every detection instrument name and label set the sink has seen."""
    with sink._lock:
        return [
            (name, labels)
            for name, labels in sink._counters
            if name.startswith("detection_")
        ]


# ---------------------------------------------------------------------------
# The signal leaves the detector
# ---------------------------------------------------------------------------


def test_a_threshold_breach_reaches_the_metric_surface_from_a_real_request():
    """The whole claim in one test: a breach, over HTTP, visible in metrics.

    Driven through the transport rather than by calling the detector directly,
    because the reported failure was that the transport discarded the signals:
    a detector fed by hand would pass while the production path lost them.
    """
    sink = install_sink()
    state = _state()
    assert sink.counter_total("detection_signals") == 0

    _burst(state)

    assert sink.counter_total("detection_signals") > 0
    # Read back through the label positions the telemetry map declares, which is
    # the only way a per-detector total is a number rather than a guess.
    assert sink.counter_total("detection_signals", {"kind": "velocity"}) > 0
    assert sink.counter_total("detection_signals", {"kind": "drift"}) == 0
    critical = sink.counter_total("detection_signals", {"severity": "critical"})
    assert critical == sink.counter_total("detection_signals")
    # Nothing about the request path changed: the burst succeeded, and neither
    # the ledger nor the detector had to fail a request to report it.
    assert state.ledger_errors == 0
    assert state.detector.errors == 0


def test_the_signal_magnitude_is_recorded_as_a_histogram_of_observed_values():
    """A count says a threshold was crossed; the magnitude is what tunes it."""
    sink = install_sink()
    state = _state()
    _burst(state)
    magnitudes = sink.detection_magnitude_snapshot()
    assert magnitudes
    assert all(value > 0.0 for value in magnitudes)
    # And they are not request latencies: different quantities in different
    # units, so sharing a percentile would make the latency figure a number
    # about nothing.
    assert sink.latency_snapshot()
    assert set(magnitudes).isdisjoint(set(sink.latency_snapshot()))


def test_the_prometheus_registry_carries_the_detection_series():
    """The same numbers, on the surface a production deployment exports.

    Skipped rather than faked when the optional extra is absent, because the
    claim is about the registry a user scrapes rather than about a stand-in.
    """
    prometheus = pytest.importorskip("prometheus_client")
    state = _state()
    state.detector.observe(_priced_event())
    raised = state.detector.observe(_priced_event())
    assert raised, "the fixture must breach the threshold it configured"
    for signal in raised:
        DetectionSignalSink().record(signal)

    for label in {(signal.kind, signal.severity) for signal in raised}:
        total = prometheus.REGISTRY.get_sample_value(
            "backstop_detection_signals_total", {"kind": label[0], "severity": label[1]}
        )
        assert total is not None and total >= 1
    assert prometheus.REGISTRY.get_sample_value(
        "backstop_detection_signal_observed_sum", {"kind": raised[0].kind}
    ) is not None


def test_no_detection_label_is_a_user_identifier():
    """The cardinality rule, asserted rather than documented.

    A label naming a team or a session multiplies the series by the number of
    them and puts a user identifier in everyone's monitoring storage. The key
    belongs in the signal record, not in a label.
    """
    sink = install_sink()
    _burst(_state())
    recorded = _recorded(sink)
    assert recorded, "the burst must have reached a detection instrument"
    for name, labels in recorded:
        assert name in {"detection_signals", "detection_evictions"}
        # Every label position is a declared constant, and the attribution that
        # fired appears in none of them.
        for value in labels:
            assert value in SIGNAL_KINDS or value in SEVERITIES
        assert "payments" not in labels
        assert "checkout-v2" not in labels


def test_the_sink_reports_through_the_metrics_choke_point_and_survives_its_absence():
    """A reporter that raised would be a reason a request fails.

    The detector already swallows a sink that raises; this pins the other half —
    the sink is on the standard path, so it has to be safe by construction.
    """
    install_sink()
    state = _state()
    _burst(state)
    assert state.detector.recorded()


# ---------------------------------------------------------------------------
# The signal is readable without a metrics backend
# ---------------------------------------------------------------------------


def test_the_dashboard_view_reports_the_threshold_the_key_crossed():
    """A counter cannot say which key, or against what. The view can."""
    state = _state()
    _burst(state)
    view = detection_view()
    assert view["enabled"] is True
    assert view["shadow"] is True
    assert view["keys"] >= 1
    assert sum(view["by_kind"].values()) == sum(state.detector.counts().values())
    assert set(view["by_kind"]) <= set(SIGNAL_KINDS)
    assert set(view["by_severity"]) <= set(SEVERITIES)
    assert view["evictions"] == 0
    recent = view["recent"]
    assert recent
    assert all(row["observed"] > row["threshold"] for row in recent)
    # The key is present here on purpose — it is the operator's next question —
    # and this is an operator-facing payload, not a time series.
    assert all(row["key"] for row in recent)
    assert [row["session_id"] for row in view["sessions"]]


def test_the_detection_view_reports_nothing_rather_than_guessing():
    """No live session means no detector, not a healthy one reading zero."""
    reset_telemetry()
    view = detection_view()
    assert view == {
        "enabled": False,
        "shadow": True,
        "sessions": [],
        "session_count": 0,
        "by_kind": {},
        "by_severity": {},
        "keys": 0,
        "samples": 0,
        "evictions": 0,
        "errors": 0,
        "recent": [],
    }
    assert session_view()["session_count"] == 0


def test_the_detection_view_covers_every_live_session_separately():
    """Two sessions in one process are two detectors, and both are reported.

    A process-wide counter cannot tell them apart, which is the whole reason the
    view reads the states rather than the sink.
    """
    first = _state()
    # a second live state, so the view has two sessions to tell apart
    _state()
    _burst(first, count=2)
    view = detection_view()
    assert view["session_count"] == 2
    # the untouched state is reported, with a signal count of its own
    assert any(int(row["signals"]) == 0 for row in view["sessions"])
    assert {row["session_id"] for row in view["sessions"]} == {
        row.session_id for row, _ in get_registry().states()
    }
    assert sum(int(row["signals"]) for row in view["sessions"]) == sum(
        view["by_kind"].values()
    )


def test_the_snapshot_carries_the_detection_view():
    from backstop.telemetry import Sampler, build_snapshot

    state = _state()
    _burst(state)
    install_sink()
    snapshot = build_snapshot(Sampler(interval=0.25), mode="test")
    assert snapshot["detection"]["by_kind"] == detection_view()["by_kind"]
    assert snapshot["detection"]["session_count"] == 1


# ---------------------------------------------------------------------------
# The bound is visible
# ---------------------------------------------------------------------------


def test_an_eviction_reaches_the_metric_surface_so_it_can_be_alerted_on():
    """A bound nobody can see is a detector that quietly stops reporting.

    Two attribution keys into a bound of one: the first is dropped, and the drop
    is countable from outside the detector.
    """
    from backstop.ledger import attribution

    sink = install_sink()
    state = _state(detection_max_keys=1)
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(_handler(OPENAI_RESPONSE))),
        base_url="https://api.openai.com",
    )
    with client:
        for team in ("payments", "support"):
            with attribution(team=team):
                client.post("/v1/chat/completions", json=OPENAI_BODY)

    assert state.detector.evictions == 1
    assert sink.counter_total("detection_evictions") == 1
    # The eviction is a count, not a label: naming the key would put a team in a
    # label, which is the one thing these instruments may not do.
    assert _recorded(sink) == [("detection_evictions", ())]
    view = detection_view()
    assert view["evictions"] == 1
    assert view["sessions"][0]["max_keys"] == 1
