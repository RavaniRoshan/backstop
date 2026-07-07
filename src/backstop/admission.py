from __future__ import annotations

import asyncio
import itertools
import threading
import time
from collections import deque
from dataclasses import dataclass

from .aimd import AIMDController
from .config import BackstopConfig, Priority


@dataclass
class _Ticket:
    priority: Priority
    sequence: int
    enqueued_at: float


class PriorityGate:
    def __init__(self, config: BackstopConfig, aimd: AIMDController) -> None:
        self._config = config
        self._aimd = aimd
        self._active = 0
        self._counter = itertools.count()
        self._queues: dict[Priority, deque[_Ticket]] = {
            Priority.CRITICAL: deque(),
            Priority.DEFAULT: deque(),
            Priority.BACKGROUND: deque(),
        }
        self._condition = threading.Condition()
        self._async_condition = asyncio.Condition()

    @property
    def active(self) -> int:
        with self._condition:
            return self._active

    @property
    def depth(self) -> int:
        with self._condition:
            return sum(len(queue) for queue in self._queues.values())

    def acquire(self, priority: Priority, timeout: float | None = None) -> float:
        ticket = _Ticket(priority, next(self._counter), time.monotonic())
        effective = timeout if timeout is not None else self._config.queue_timeout
        with self._condition:
            self._queues[priority].append(ticket)
            self._condition.notify_all()
            while not self._can_admit(ticket):
                if effective is None:
                    self._condition.wait()
                else:
                    if not self._condition.wait(timeout=effective):
                        raise TimeoutError("gate acquire timed out")
            self._queues[priority].popleft()
            self._active += 1
            return time.monotonic() - ticket.enqueued_at

    def release(self) -> None:
        with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()

    async def aacquire(self, priority: Priority, timeout: float | None = None) -> float:
        ticket = _Ticket(priority, next(self._counter), time.monotonic())
        effective = timeout if timeout is not None else self._config.queue_timeout
        async with self._async_condition:
            self._queues[priority].append(ticket)
            self._async_condition.notify_all()
            while not self._can_admit(ticket):
                try:
                    if effective is None:
                        await self._async_condition.wait()
                    else:
                        await asyncio.wait_for(self._async_condition.wait(), effective)
                except asyncio.TimeoutError:
                    raise TimeoutError("gate acquire timed out")
            self._queues[priority].popleft()
            self._active += 1
            return time.monotonic() - ticket.enqueued_at

    async def arelease(self) -> None:
        async with self._async_condition:
            self._active = max(0, self._active - 1)
            self._async_condition.notify_all()

    def _can_admit(self, ticket: _Ticket) -> bool:
        if self._active >= self._aimd.current_limit:
            return False
        chosen = self._choose_ticket()
        return chosen is ticket

    def _choose_ticket(self) -> _Ticket | None:
        now = time.monotonic()
        critical = self._queues[Priority.CRITICAL]
        if critical:
            return critical[0]

        aged = [
            queue[0]
            for queue in self._queues.values()
            if queue and now - queue[0].enqueued_at >= self._config.starvation_after_seconds
        ]
        if aged:
            return min(aged, key=lambda item: item.sequence)

        for priority in (Priority.DEFAULT, Priority.BACKGROUND):
            queue = self._queues[priority]
            if queue:
                return queue[0]
        return None

