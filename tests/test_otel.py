"""The OpenTelemetry mirror.

These tests must pass whether or not ``opentelemetry`` is installed. The
``otel`` extra is optional, so a test that assumed the packages were *absent*
passed in the default CI environment and failed in the environment that has
the extra installed — which is the environment where the mirror actually does
something. The disabled path is therefore forced explicitly rather than
inferred from what happens to be importable.
"""
from __future__ import annotations

import threading

import pytest

from backstop.otel import OtelMetrics

try:  # pragma: no cover - which branch runs depends on the install
    import opentelemetry.metrics as _otel_metrics

    HAS_OTEL = True
except Exception:  # pragma: no cover
    _otel_metrics = None  # type: ignore[assignment]
    HAS_OTEL = False


@pytest.fixture
def disabled_metrics(monkeypatch: pytest.MonkeyPatch) -> OtelMetrics:
    """An ``OtelMetrics`` whose meter cannot be created, so it is a no-op.

    Forced by making the meter factory raise, which is exactly the condition
    the constructor is meant to survive: an install without a usable OTel SDK.
    Where the SDK is not installed at all, the constructor already returns a
    disabled mirror and there is nothing to force.
    """
    if HAS_OTEL:
        def _no_meter(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("no meter here")

        monkeypatch.setattr(_otel_metrics, "get_meter", _no_meter)
    return OtelMetrics()


def test_the_mirror_is_a_no_op_when_no_meter_can_be_created(
    disabled_metrics: OtelMetrics,
) -> None:
    assert not disabled_metrics.enabled
    disabled_metrics.call("requests", "api", "high", "deny")
    disabled_metrics.call("duration", "api", "high", amount=0.1)
    disabled_metrics.call("budget_exceeded")
    disabled_metrics.call("nonexistent_metric_xyz")


@pytest.mark.skipif(not HAS_OTEL, reason="the OTel SDK is not installed")
def test_the_gauge_dict_is_written_and_read_under_a_lock() -> None:
    """The gauges are written from request threads and read by the callback."""
    metrics = OtelMetrics()
    metrics._set_gauge("backstop_queue_depth", 3.0)
    observation = metrics._gauge_callback("backstop_queue_depth")(None)[0]
    assert observation.value == 3.0


@pytest.mark.skipif(not HAS_OTEL, reason="the OTel SDK is not installed")
def test_concurrent_gauge_writes_do_not_raise() -> None:
    metrics = OtelMetrics()
    errors: list[Exception] = []

    def writer(index: int) -> None:
        try:
            for i in range(100):
                metrics._set_gauge(f"gauge_{i % 5}", float(index + i))
        except Exception as exc:  # noqa: BLE001 - the assertion is on the list
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
