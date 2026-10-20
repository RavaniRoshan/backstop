from __future__ import annotations

import asyncio
import itertools
import threading
import time
from collections import deque
from dataclasses import dataclass

from .aimd import AIMDController
from .config import BackstopConfig, Priority
from .exceptions import AdmissionTimeoutError


@dataclass
class _Ticket:
    priority: Priority
    sequence: int
    enqueued_at: float


class PriorityGate:
    """One admission gate, reached from two paths.

    The sync transport calls :meth:`acquire` and :meth:`release`; the async
    transport calls :meth:`aacquire` and :meth:`arelease`. Both paths guard
    **the same** ``_active`` counter and **the same** ``_queues``, because
    they are the same gate: a sync request holding the only slot and an async
    request waiting for it are contending for one resource, not two.

    That is why there is exactly one lock. It used to be two — a
    ``threading.Condition`` for the sync path and an ``asyncio.Condition`` for
    the async one — over the same shared state, with each side notifying only
    its own condition. A release on one side therefore never woke a waiter on
    the other, and a request could wait forever for a slot that was already
    free. The symptom was a hang with no error and no timeout, in a process
    that was otherwise healthy.

    The async path waits on an :class:`asyncio.Event` rather than an
    ``asyncio.Condition``, because an event can be set from another thread
    through ``loop.call_soon_threadsafe`` — which is exactly what a sync
    release has to do — while a condition's ``notify_all`` may only be called
    with its own lock held, from its own loop.

    The lock is never held across an ``await``: it is taken for the short
    critical sections that read or mutate the counter and the queues, and
    released before the wait.
    """

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
        # One lock over `_active` and `_queues`, for both paths.
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        #: The async waiters, as (event loop, event) pairs. A waiter
        #: registers its event before it checks whether it can be admitted,
        #: so a release that lands between the check and the wait is not
        #: lost.
        #:
        #: The registry has its own lock, deliberately. The main lock is held
        #: for long stretches on the sync path, and a waiter that is being
        #: woken must be able to read the registry *while* the main lock is
        #: held — a single lock for both would mean a thread waking a waiter
        #: deadlocks against itself.
        self._waiter_lock = threading.Lock()
        self._async_waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    @property
    def depth(self) -> int:
        with self._lock:
            return sum(len(queue) for queue in self._queues.values())

    def acquire(self, priority: Priority, timeout: float | None = None) -> float:
        ticket = _Ticket(priority, next(self._counter), time.monotonic())
        effective = timeout if timeout is not None else self._config.queue_timeout
        acquired = False
        with self._condition:
            self._queues[priority].append(ticket)
            self._condition.notify_all()
            try:
                while not self._can_admit(ticket):
                    if effective is None:
                        self._condition.wait()
                    else:
                        if not self._condition.wait(timeout=effective):
                            raise AdmissionTimeoutError("gate acquire timed out")
                self._queues[priority].popleft()
                self._active += 1
                acquired = True
                return time.monotonic() - ticket.enqueued_at
            finally:
                if not acquired:
                    self._discard(priority, ticket)
                    # A survivor behind the discarded ticket may now be admissible
                    # (the deque head moved, or an AIMD raise freed a slot), so
                    # wake it instead of leaving it asleep until unrelated traffic.
                    self._condition.notify_all()
            # Reached only when the acquire did *not* succeed — the success
            # path returns from inside the `try`. That is the right moment to
            # wake the other path: the ticket is gone, so a waiter that was
            # behind it may now be admissible. The waiter registry has its own
            # lock, so this does not deadlock against the gate lock the `with`
            # block above still holds.
            self._wake_async_waiters()

    def release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
        # The slot is free. Both paths have to hear about it: a sync waiter
        # blocked on the threading condition, and an async waiter blocked on
        # its event, which may be waiting for *this* release.
        self._notify_waiters()

    async def aacquire(self, priority: Priority, timeout: float | None = None) -> float:
        ticket = _Ticket(priority, next(self._counter), time.monotonic())
        effective = timeout if timeout is not None else self._config.queue_timeout
        acquired = False
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        with self._lock:
            self._queues[priority].append(ticket)
        with self._waiter_lock:
            self._async_waiters.append((loop, event))
        try:
            while True:
                # Clear before checking: a release that lands after the check
                # sets the event again, and the next wait returns at once. A
                # release that landed before the check is already reflected in
                # `_active`, so the check admits. There is no window in which
                # a notification is lost.
                event.clear()
                with self._lock:
                    if self._can_admit(ticket):
                        self._queues[priority].popleft()
                        self._active += 1
                        acquired = True
                        break
                if effective is None:
                    await event.wait()
                else:
                    try:
                        await asyncio.wait_for(event.wait(), effective)
                    except asyncio.TimeoutError:
                        raise AdmissionTimeoutError("gate acquire timed out")
        finally:
            with self._lock:
                if not acquired:
                    self._discard(priority, ticket)
            with self._waiter_lock:
                try:
                    self._async_waiters.remove((loop, event))
                except ValueError:
                    pass
            # A discarded ticket may have been the one blocking a survivor, and
            # a slot may have just been freed on the other path.
            self._notify_waiters()
        return time.monotonic() - ticket.enqueued_at

    async def arelease(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
        self._notify_waiters()

    def _notify_waiters(self) -> None:
        """Wake every waiter, on both paths.

        The threading condition and the async events are separate objects, so
        both are signalled — that is the whole point of this rewrite. The
        previous version signalled only the caller's own side, which is how a
        sync release left an async waiter asleep on a free slot.
        """
        with self._lock:
            self._condition.notify_all()
        self._wake_async_waiters()

    def _wake_async_waiters(self) -> None:
        """Set the async waiters' events from any thread.

        ``loop.call_soon_threadsafe`` is the only safe way to touch an
        ``asyncio.Event`` from a thread that is not the loop's. A loop that
        has already closed raises ``RuntimeError``, which means the waiter is
        gone; there is nothing to wake.
        """
        with self._waiter_lock:
            waiters = list(self._async_waiters)
        for loop, event in waiters:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                pass

    def _discard(self, priority: Priority, ticket: _Ticket) -> None:
        """Drop a ticket that never reached ``_can_admit``.

        ``_choose_ticket`` only ever looks at the head of each deque, so a
        ticket left behind by a timed-out or failed acquirer would be reselected
        forever and wedge that priority permanently.
        """
        queue = self._queues[priority]
        for index, queued in enumerate(queue):
            if queued is ticket:
                del queue[index]
                return

    def _can_admit(self, ticket: _Ticket) -> bool:
        """Whether ``ticket`` may take a slot. **The lock must be held.**"""
        if self._active >= self._aimd.current_limit:
            return False
        chosen = self._choose_ticket()
        return chosen is ticket

    def _choose_ticket(self) -> _Ticket | None:
        """The ticket that should go next. **The lock must be held.**"""
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
