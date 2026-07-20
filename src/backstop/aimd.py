from __future__ import annotations

import threading
import time

from .config import BackstopConfig


class AIMDController:
    def __init__(self, config: BackstopConfig) -> None:
        self._config = config
        self._limit = config.initial_concurrency
        # Initialize so the first adjustment is always allowed regardless
        # of how long this system has been running (monotonic clock).
        self._last_adjustment = -self._config.aimd_adjustment_interval
        self._lock = threading.Lock()

    @property
    def current_limit(self) -> int:
        with self._lock:
            return self._limit

    def record_success(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last_adjustment < self._config.aimd_adjustment_interval:
                return False
            if self._limit >= self._config.max_concurrency:
                return False
            self._limit = min(self._config.max_concurrency, self._limit + self._config.aimd_increase)
            self._last_adjustment = now
            return True

    def record_pressure(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last_adjustment < self._config.aimd_adjustment_interval:
                return False
            new_limit = max(
                self._config.min_concurrency,
                int(self._limit * self._config.aimd_decrease_factor),
            )
            if new_limit == self._limit:
                return False
            self._limit = new_limit
            self._last_adjustment = now
            return True

    def apply_external_decrease(self, pressure: float = 1.0) -> bool:
        """Proactively clamp the limit from an out-of-band signal (e.g. provider
        quota pressure). Bypasses the adjustment-interval throttle so a quota
        warning takes effect on the very next request."""
        with self._lock:
            factor = max(self._config.aimd_decrease_factor, min(1.0, pressure))
            new_limit = max(self._config.min_concurrency, int(self._limit * factor))
            if new_limit == self._limit:
                return False
            self._limit = new_limit
            self._last_adjustment = time.monotonic()
            return True

