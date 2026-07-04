from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

from .exceptions import BudgetExceededError


@dataclass(frozen=True)
class Reservation:
    tokens: int


class Budget:
    def __init__(self, total: int | None) -> None:
        if total is not None and total < 0:
            raise ValueError("budget must be >= 0 or None")
        self.total = total
        self._spent = 0
        self._reserved = 0
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()

    @property
    def remaining(self) -> int | None:
        if self.total is None:
            return None
        with self._lock:
            return max(0, self.total - self._spent - self._reserved)

    @property
    def spent(self) -> int:
        with self._lock:
            return self._spent

    def reserve(self, tokens: int) -> Reservation:
        tokens = max(0, tokens)
        if self.total is None:
            return Reservation(tokens)
        with self._lock:
            if self._spent + self._reserved + tokens > self.total:
                remaining = max(0, self.total - self._spent - self._reserved)
                raise BudgetExceededError(
                    f"request estimate {tokens} tokens exceeds remaining budget {remaining}"
                )
            self._reserved += tokens
            return Reservation(tokens)

    async def areserve(self, tokens: int) -> Reservation:
        tokens = max(0, tokens)
        if self.total is None:
            return Reservation(tokens)
        async with self._async_lock:
            if self._spent + self._reserved + tokens > self.total:
                remaining = max(0, self.total - self._spent - self._reserved)
                raise BudgetExceededError(
                    f"request estimate {tokens} tokens exceeds remaining budget {remaining}"
                )
            self._reserved += tokens
            return Reservation(tokens)

    def reconcile(self, reservation: Reservation, actual_tokens: int | None, *, success: bool) -> None:
        if self.total is None:
            return
        charge = reservation.tokens if success and actual_tokens is None else max(0, actual_tokens or 0)
        with self._lock:
            self._reserved = max(0, self._reserved - reservation.tokens)
            self._spent = min(self.total, self._spent + charge)

    async def areconcile(
        self, reservation: Reservation, actual_tokens: int | None, *, success: bool
    ) -> None:
        if self.total is None:
            return
        charge = reservation.tokens if success and actual_tokens is None else max(0, actual_tokens or 0)
        async with self._async_lock:
            self._reserved = max(0, self._reserved - reservation.tokens)
            self._spent = min(self.total, self._spent + charge)

