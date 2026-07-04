from __future__ import annotations

import enum
import threading
import time
from collections import deque

from .config import BackstopConfig
from .exceptions import CircuitBreakerOpenError


class CircuitState(str, enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, config: BackstopConfig) -> None:
        self._config = config
        self._events: deque[tuple[float, bool]] = deque()
        self._state = CircuitState.CLOSED
        self._opened_at = 0.0
        self._half_open_probe_active = False
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def before_request(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._state is CircuitState.OPEN:
                if now - self._opened_at >= self._config.circuit_cooldown_seconds:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_probe_active = False
                else:
                    raise CircuitBreakerOpenError("circuit breaker is open")

            if self._state is CircuitState.HALF_OPEN:
                if self._half_open_probe_active:
                    raise CircuitBreakerOpenError("circuit breaker is half-open")
                self._half_open_probe_active = True

    def after_request(self, *, success: bool) -> bool:
        now = time.monotonic()
        with self._lock:
            if self._state is CircuitState.HALF_OPEN:
                self._half_open_probe_active = False
                if success:
                    self._state = CircuitState.CLOSED
                    self._events.clear()
                    return False
                self._open(now)
                return True

            if self._state is CircuitState.OPEN:
                return False

            self._events.append((now, success))
            self._trim(now)
            if self._should_open():
                self._open(now)
                return True
            return False

    def _trim(self, now: float) -> None:
        cutoff = now - self._config.circuit_window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def _should_open(self) -> bool:
        total = len(self._events)
        if total < self._config.circuit_min_requests:
            return False
        failures = sum(1 for _, success in self._events if not success)
        return failures / total >= self._config.circuit_failure_threshold

    def _open(self, now: float) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = now
        self._half_open_probe_active = False

