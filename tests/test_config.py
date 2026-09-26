import pytest

from backstop import BackstopConfig, Priority
from backstop.detection import DetectionConfig


def test_config_defaults_are_valid():
    config = BackstopConfig()
    assert config.initial_concurrency == 8
    assert config.min_concurrency == 1
    assert config.max_concurrency == 64


def test_config_validation():
    with pytest.raises(ValueError):
        BackstopConfig(initial_concurrency=0)
    with pytest.raises(ValueError):
        BackstopConfig(circuit_failure_threshold=2)
    with pytest.raises(ValueError):
        BackstopConfig(aimd_decrease_factor=1)


def test_priority_header_parsing():
    assert Priority.from_header("critical") is Priority.CRITICAL
    assert Priority.from_header("BACKGROUND") is Priority.BACKGROUND
    assert Priority.from_header("unknown") is Priority.DEFAULT


# --- Ledger Foundation: the five opt-in switches -------------------------
#
# Every one of them defaults to off or to a usable value, and every one of them
# is validated at construction. The reason to validate a *default* is the same
# as for a supplied value: a ledger that is quietly mis-configured produces a
# chargeback that looks authoritative and is wrong.


def test_ledger_config_defaults_leave_the_ledger_off():
    config = BackstopConfig()
    assert config.ledger_enabled is False
    assert config.ledger_path is None
    assert config.ledger_memory_events == 10_000
    assert config.price_catalog_path is None
    assert config.detection_enabled is False


def test_ledger_path_must_be_a_string_when_set():
    with pytest.raises(TypeError, match="ledger_path must be a string or None"):
        BackstopConfig(ledger_enabled=True, ledger_path=object())


def test_ledger_path_must_not_be_empty():
    # An empty path is not "unset": JsonlSink would open the process's working
    # directory, so it is refused rather than treated as "no path".
    with pytest.raises(ValueError, match="non-empty path"):
        BackstopConfig(ledger_enabled=True, ledger_path="")


def test_ledger_memory_events_must_be_positive():
    with pytest.raises(ValueError, match="ledger_memory_events must be >= 1"):
        BackstopConfig(ledger_enabled=True, ledger_memory_events=0)
    with pytest.raises(ValueError, match="ledger_memory_events must be >= 1"):
        BackstopConfig(ledger_enabled=True, ledger_memory_events=-5)


def test_ledger_memory_events_must_be_an_int_not_a_bool():
    # bool is an int subclass, so True would otherwise be a ring of one event.
    with pytest.raises(TypeError, match="ledger_memory_events must be an int"):
        BackstopConfig(ledger_memory_events=True)
    with pytest.raises(TypeError, match="ledger_memory_events must be an int"):
        BackstopConfig(ledger_memory_events=10.0)


def test_price_catalog_path_must_exist():
    with pytest.raises(ValueError, match="does not exist or is not a file"):
        BackstopConfig(ledger_enabled=True, price_catalog_path="/nonexistent/prices.json")


def test_price_catalog_path_must_be_a_file_not_a_directory(tmp_path):
    with pytest.raises(ValueError, match="does not exist or is not a file"):
        BackstopConfig(ledger_enabled=True, price_catalog_path=str(tmp_path))


def test_price_catalog_path_that_exists_is_accepted(tmp_path):
    catalog = tmp_path / "prices.json"
    catalog.write_text(
        '{"entries": [{"model": "gpt-4o", "provider": "openai",'
        ' "input_per_mtok_usd": "1.00", "output_per_mtok_usd": "2.00",'
        ' "effective_from": "2026-01-01"}]}',
        encoding="utf-8",
    )
    assert BackstopConfig(ledger_enabled=True, price_catalog_path=str(catalog))


def test_price_catalog_path_must_be_a_string_when_set():
    with pytest.raises(TypeError, match="price_catalog_path must be a string or None"):
        BackstopConfig(price_catalog_path=123)


def test_ledger_and_detection_switches_must_be_bools():
    with pytest.raises(TypeError, match="ledger_enabled must be a bool"):
        BackstopConfig(ledger_enabled="yes")
    with pytest.raises(TypeError, match="detection_enabled must be a bool"):
        BackstopConfig(detection_enabled=1)



# --- Runaway-spend detection: every threshold must be reachable ---------
#
# A detector whose knobs are frozen defaults can be switched on but not tuned,
# and tuning them against a shadow log before they bite is the entire purpose of
# the shadow mode. So each ``DetectionConfig`` field has a ``BackstopConfig``
# field of the same name behind a prefix, and this table is the inventory: a
# field added to one and not the other fails here.

#: ``(config field, DetectionConfig field, a value that is not the default)``
DETECTION_KNOBS = (
    ("detection_shadow", "shadow", False),
    ("detection_velocity_threshold_usd_per_min", "velocity_threshold_usd_per_min", 0.25),
    ("detection_baseline_multiplier", "baseline_multiplier", 12.5),
    ("detection_retry_ratio_threshold", "retry_ratio_threshold", 3.5),
    ("detection_context_growth_threshold", "context_growth_threshold", 0.75),
    # Above the default min_samples, which a smaller window would trip.
    ("detection_window_size", "window_size", 9),
    ("detection_min_samples", "min_samples", 3),
    ("detection_max_keys", "max_keys", 64),
)


@pytest.mark.parametrize(("field", "target", "value"), DETECTION_KNOBS)
def test_every_detection_knob_is_settable_from_config(field, target, value):
    config = BackstopConfig(detection_enabled=True, **{field: value})
    assert getattr(config.detection_config, target) == value


def test_the_detector_config_carries_the_enabled_switch_too():
    assert BackstopConfig(detection_enabled=True).detection_config.enabled is True
    assert BackstopConfig().detection_config.enabled is False
    # Shadow-first survives the join: turning the detector on must not turn
    # enforcement on with it, and the knob is reachable so a deployment can
    # deliberately choose otherwise.
    assert BackstopConfig(detection_enabled=True).detection_config.shadow is True
    assert BackstopConfig(detection_enabled=True, detection_shadow=False).detection_config.shadow is False


def test_the_default_detection_config_is_exactly_the_detector_default():
    """A knob left unset must read as the module default, not as a second default.

    Two default tables would be two things to keep in step; this asserts the
    config contributes none of its own.
    """
    assert BackstopConfig().detection_config == DetectionConfig()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("detection_velocity_threshold_usd_per_min", -1.0, "velocity_threshold_usd_per_min"),
        ("detection_baseline_multiplier", 0.5, "baseline_multiplier"),
        ("detection_retry_ratio_threshold", -0.1, "retry_ratio_threshold"),
        ("detection_context_growth_threshold", -2.0, "context_growth_threshold"),
        ("detection_window_size", 0, "window_size"),
        ("detection_min_samples", 1, "min_samples"),
        ("detection_max_keys", 0, "max_keys"),
        ("detection_shadow", "yes", "shadow"),
    ],
)
def test_an_invalid_detection_knob_is_refused_with_a_message_naming_it(field, value, message):
    with pytest.raises((TypeError, ValueError), match=message):
        BackstopConfig(detection_enabled=True, **{field: value})


def test_an_unreachable_min_samples_is_refused_at_construction():
    """A window that can never hold the history it needs is a mute detector.

    It would look exactly like a healthy one, which is why it is a construction
    error rather than a runtime surprise — and why the error names both bounds.
    """
    with pytest.raises(ValueError, match="min_samples must be <= window_size"):
        BackstopConfig(detection_window_size=4, detection_min_samples=9)
