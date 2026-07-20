"""Pluggable token-bucket rate limiter (Deep Research P1#12).

A self-contained, variable-cost token bucket. Unlike a simple requests/sec cap,
it charges the *estimated* token cost of each request, so expensive calls
consume more of the shared rate. Pluggable: pass any object with ``allow(tokens)
-> bool`` to ``BackstopConfig(rate_limiter=...)``. Used by Backstop to enforce a
second, finer-grained throttle in front of admission.
"""
from __future__ import annotations

import threading
import time


class TokenBucketLimiter:
    def __init__(self, capacity: int, refill_per_sec: float, refill_unit: int = 1) -> None:
        self._capacity = max(1, capacity)
        self._tokens = float(self._capacity)
        self._refill_per_sec = refill_per_sec
        self._refill_unit = refill_unit
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def allow(self, tokens: int = 1) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_per_sec * self._refill_unit)
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    @property
    def available(self) -> float:
        with self._lock:
            return self._tokens
