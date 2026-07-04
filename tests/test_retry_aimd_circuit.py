import time

import pytest

from backstop.aimd import AIMDController
from backstop.circuit import CircuitBreaker, CircuitState
from backstop.config import BackstopConfig
from backstop.exceptions import CircuitBreakerOpenError
from backstop.retry import backoff_delay, is_retryable_status


def test_retry_status_selection_and_jitter_bounds():
    config = BackstopConfig(retry_base_delay=0.1, retry_max_delay=0.2)
    assert is_retryable_status(429, config)
    assert not is_retryable_status(400, config)
    for _ in range(25):
        assert 0 <= backoff_delay(2, config) <= 0.2


def test_aimd_increase_decrease_bounds():
    config = BackstopConfig(
        initial_concurrency=2,
        min_concurrency=1,
        max_concurrency=3,
        aimd_adjustment_interval=0,
    )
    aimd = AIMDController(config)
    assert aimd.record_success()
    assert aimd.current_limit == 3
    assert not aimd.record_success()
    assert aimd.record_pressure()
    assert aimd.current_limit == 1


def test_aimd_adjustment_interval():
    aimd = AIMDController(BackstopConfig(initial_concurrency=2, aimd_adjustment_interval=60))
    assert aimd.record_success()
    assert not aimd.record_pressure()


def test_circuit_closed_open_half_open_transitions():
    config = BackstopConfig(
        circuit_failure_threshold=0.5,
        circuit_min_requests=2,
        circuit_cooldown_seconds=0.01,
    )
    circuit = CircuitBreaker(config)
    circuit.before_request()
    assert not circuit.after_request(success=False)
    circuit.before_request()
    assert circuit.after_request(success=False)
    assert circuit.state is CircuitState.OPEN
    with pytest.raises(CircuitBreakerOpenError):
        circuit.before_request()
    time.sleep(0.02)
    circuit.before_request()
    assert circuit.state is CircuitState.HALF_OPEN
    assert not circuit.after_request(success=True)
    assert circuit.state is CircuitState.CLOSED

