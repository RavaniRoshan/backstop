import pytest

from backstop import BackstopConfig, Priority


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

