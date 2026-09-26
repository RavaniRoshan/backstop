"""What ``BackstopState.create`` builds for the spend ledger, before any request.

The ledger's default shape is the thing under test: off means a writer over a
``NullSink``, no price catalog, and a detector that is inert. A deployment that
has not opted in must not be paying to index a price list nobody bills from.
"""
from __future__ import annotations

import gc
import threading

from backstop import BackstopConfig
from backstop.detection import DetectionConfig, RunawayDetector
from backstop.ledger import (
    DRAIN_THREAD_NAME,
    Attribution,
    BoundedWriter,
    CloseReport,
    JsonlSink,
    MemorySink,
    NullSink,
    SpendEvent,
)
from backstop.pricing_catalog import PriceCatalog
from backstop.state import BackstopState


def _ledger_config(**overrides) -> BackstopConfig:
    return BackstopConfig(ledger_enabled=True, **overrides)


def _state(config: BackstopConfig, budget: int = 1_000_000) -> BackstopState:
    return BackstopState.create(budget, config)


# ---------------------------------------------------------------------------
# BackstopState.create: what the ledger is made of before any request arrives
# ---------------------------------------------------------------------------


def test_a_disabled_ledger_is_a_no_op_writer_over_a_null_sink():
    state = _state(BackstopConfig())
    assert isinstance(state.ledger, BoundedWriter)
    assert isinstance(state.ledger.sink, NullSink)
    # No catalog is built when nothing will ever ask for a price: the bundled
    # table is dozens of entries and a process that never bills anything should
    # not pay to index it.
    assert state.prices is None
    assert state.detector.config.enabled is False
    assert state.ledger_errors == 0


def test_an_enabled_ledger_without_a_path_keeps_a_bounded_memory_ring():
    state = _state(_ledger_config(ledger_memory_events=32))
    assert isinstance(state.ledger.sink, MemorySink)
    assert state.ledger.sink.maxlen == 32
    assert isinstance(state.prices, PriceCatalog)


def test_an_enabled_ledger_with_a_path_writes_ndjson(tmp_path):
    state = _state(_ledger_config(ledger_path=str(tmp_path / "nested" / "spend.jsonl")))
    assert isinstance(state.ledger.sink, JsonlSink)
    # Constructing a ledger touches no filesystem: the file opens on the first
    # write, so a bad path degrades the same way a bad write does.
    assert not (tmp_path / "nested").exists()


def test_a_user_price_catalog_replaces_the_bundled_rate(tmp_path):
    catalog = tmp_path / "prices.json"
    catalog.write_text(
        '{"entries": [{"model": "gpt-4o", "provider": "openai",'
        ' "input_per_mtok_usd": "1000.00", "output_per_mtok_usd": "2000.00",'
        ' "effective_from": "2026-01-01"}]}',
        encoding="utf-8",
    )
    state = _state(_ledger_config(price_catalog_path=str(catalog)))
    assert state.prices.resolve("openai", "gpt-4o").input_per_mtok_usd.as_tuple().exponent == -2
    assert str(state.prices.resolve("openai", "gpt-4o").input_per_mtok_usd) == "1000.00"


def test_the_detector_is_constructed_disabled_by_default_and_shadow_first():
    state = _state(BackstopConfig())
    assert isinstance(state.detector, RunawayDetector)
    assert state.detector.config.enabled is False
    # Shadow-first survives construction: turning a detector on must not turn
    # enforcement on with it.
    assert state.detector.shadow is True


def test_detection_enabled_builds_an_enabled_detector_still_in_shadow():
    state = _state(BackstopConfig(detection_enabled=True))
    assert state.detector.config == DetectionConfig(enabled=True, shadow=True)
    assert state.detector.shadow is True


def test_the_detector_is_built_from_the_configured_thresholds_not_the_defaults():
    """The knob survives the trip through ``BackstopState.create``.

    Reachability is only real if the value the user set is the value the running
    detector compares against, so this reads it back off the detector the state
    actually holds rather than off the config that produced it.
    """
    state = _state(
        BackstopConfig(
            detection_enabled=True,
            detection_velocity_threshold_usd_per_min=0.125,
            detection_baseline_multiplier=9.0,
            detection_retry_ratio_threshold=4.0,
            detection_context_growth_threshold=0.5,
            detection_window_size=16,
            detection_min_samples=4,
        )
    )
    config = state.detector.config
    assert config.velocity_threshold_usd_per_min == 0.125
    assert config.baseline_multiplier == 9.0
    assert config.retry_ratio_threshold == 4.0
    assert config.context_growth_threshold == 0.5
    assert state.detector.max_window() == 16


# ---------------------------------------------------------------------------
# Shutdown: the writer is released, and the loss figure comes back
# ---------------------------------------------------------------------------


def _event():
    return SpendEvent(
        provider="openai",
        model="gpt-4o",
        endpoint="https://api.openai.com/v1/chat/completions",
        priority="default",
        outcome="success",
        input_tokens=10,
        output_tokens=2,
        estimated=False,
        attribution=Attribution(team="payments"),
    )


def _drain_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name == DRAIN_THREAD_NAME]


def test_closing_the_state_releases_the_drain_thread():
    """The leak the missing close() left: a daemon thread per live writer.

    The thread is started by the first accepted submit, so the close has to come
    after one — and the assertion is on ``threading.enumerate`` rather than on
    the writer's own flag, because "it says it stopped" is not "it stopped".
    """
    state = _state(_ledger_config())
    assert _drain_threads() == []
    state.ledger.submit(_event())
    assert DRAIN_THREAD_NAME in _drain_threads()
    report = state.close()
    assert report.written == 1
    assert _drain_threads() == []


def test_closing_the_state_twice_returns_the_same_report():
    """Shutdown paths run more than once, and the second one must not lie.

    A close that recomputed its figures would report a smaller second number,
    which reads as "an event went missing since a minute ago".
    """
    state = _state(_ledger_config())
    state.ledger.submit(_event())
    first = state.close()
    assert state.close() is first
    assert state.close().lost == first.lost


def test_close_reports_the_loss_figure_a_stalled_sink_left_behind():
    """The reason to call close at all: the number that cannot be written.

    A sink that raises on every write is the case a report has to survive, since
    nothing is lost silently and the events leave the buffer either way.
    """
    class Exploding:
        def __init__(self) -> None:
            self.closed = False

        def write(self, event) -> None:
            raise OSError("disk is full")

        def flush(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    sink = Exploding()
    state = BackstopState.create(1_000_000, BackstopConfig(ledger_enabled=True))
    state.ledger = BoundedWriter(sink)
    for _ in range(3):
        state.ledger.submit(_event())
    report = state.close()
    assert report.submitted == 3
    assert report.sink_errors == 3
    assert report.landed == 0
    assert report.lost == 3
    assert sink.closed is True


def test_close_works_when_the_sinks_own_close_raises():
    """A sink that explodes on the way out must not take shutdown with it.

    ``flush`` and ``close`` are the two calls a shutdown is allowed to make, so
    neither may raise into it. The report still arrives, and says what happened.
    """
    class Hostile:
        def write(self, event) -> None:
            return None

        def flush(self) -> None:
            raise OSError("no")

        def close(self) -> None:
            raise OSError("no")

    state = _state(_ledger_config())
    state.ledger = BoundedWriter(Hostile())
    state.ledger.submit(_event())
    report = state.close()
    assert report.written == 1
    assert report.drained is True


def test_an_enabled_ledger_registers_its_own_exit_close_and_a_close_drops_it():
    """A user who enables ledger_path and exits should not have to know to close.

    And a close must take the registration with it: ``atexit.unregister`` drops
    every registration of the callable it is given, so the hook is per-state or a
    finished run's close would unregister every other session's.
    """
    import backstop.state as state_module

    state = _state(_ledger_config())
    assert state._atexit_hook is not None
    registered = state._atexit_hook

    dropped: list[object] = []
    original = state_module.atexit.unregister
    state_module.atexit.unregister = dropped.append
    try:
        state.close()
    finally:
        state_module.atexit.unregister = original
    assert dropped == [registered]
    assert state._atexit_hook is None
    # Calling the hook after a close is a no-op rather than a second close.
    registered()
    assert state._atexit_hook is None


def test_the_exit_hook_closes_a_state_that_is_still_alive_and_ignores_one_that_is_not():
    state = _state(_ledger_config())
    state.ledger.submit(_event())
    hook = state._atexit_hook
    assert hook is not None
    hook()
    assert state.ledger.written == 1
    # A collected state is left alone: the hook holds a weak reference on purpose,
    # so a finished session cannot be kept alive by its own shutdown hook.
    gone = _state(_ledger_config())
    gone_hook = gone._atexit_hook
    assert gone_hook is not None
    del gone
    gc.collect()
    gone_hook()  # must not raise


def test_a_disabled_ledger_registers_no_exit_hook():
    """Nothing to release, so nothing to register: the default stays free."""
    state = _state(BackstopConfig())
    assert state._atexit_hook is None
    report = state.close()
    assert report.submitted == 0
    assert report.lost == 0


def test_the_public_close_takes_a_wrapped_client_and_a_bare_one():
    from backstop import Backstop

    state = _state(_ledger_config())
    client = type("Client", (), {"_backstop_state": state})()
    state.ledger.submit(_event())
    report = Backstop.close(client)
    assert report.written == 1
    assert Backstop.close(client) is report
    assert _drain_threads() == []

    # A client Backstop never wrapped has no ledger, and says so with zeros.
    bare = Backstop.close(object())
    assert bare == CloseReport.nothing_submitted()
    assert bare.lost == 0
    assert bare.drained is True
