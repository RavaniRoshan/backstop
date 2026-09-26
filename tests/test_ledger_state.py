"""What ``BackstopState.create`` builds for the spend ledger, before any request.

The ledger's default shape is the thing under test: off means a writer over a
``NullSink``, no price catalog, and a detector that is inert. A deployment that
has not opted in must not be paying to index a price list nobody bills from.
"""
from __future__ import annotations


from backstop import BackstopConfig
from backstop.detection import DetectionConfig, RunawayDetector
from backstop.ledger import BoundedWriter, JsonlSink, MemorySink, NullSink
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
