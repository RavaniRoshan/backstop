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

