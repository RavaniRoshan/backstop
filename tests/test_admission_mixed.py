"""The admission gate must not deadlock when a state carries both transports.

``PriorityGate`` guards one set of counters and one set of queues, and it is
reached from two places: the sync transport calls ``acquire``/``release`` and
the async transport calls ``aacquire``/``arelease``. Before v0.8.0 each path
waited on its own condition variable — a ``threading.Condition`` for the sync
path and an ``asyncio.Condition`` for the async one — while both mutated the
same shared state.

Two independent conditions over shared state means a release on one side never
wakes a waiter on the other. The result was a request that waits forever: the
slot was free, the counter said so, and the waiter was never told. This module
pins that down.

A ``BackstopState`` is per-``wrap()`` call, so a single wrapped client cannot
reach this on its own. It bites a deployment that shares one state between a
sync and an async transport — which the public constructor signatures permit
and the gateway came close to doing.
"""
from __future__ import annotations

import asyncio
import time

from backstop.admission import PriorityGate
from backstop.aimd import AIMDController
from backstop.config import BackstopConfig, Priority


def _gate(limit: int = 1) -> PriorityGate:
    config = BackstopConfig(
        initial_concurrency=limit,
        min_concurrency=limit,
        max_concurrency=limit,
        starvation_after_seconds=0.0,
        queue_timeout=None,
    )
    return PriorityGate(config, AIMDController(config))


def _wait_until_queued(gate: PriorityGate, priority: Priority, timeout: float = 2.0) -> bool:
    """Wait until a ticket for ``priority`` is actually sitting in the queue.

    The queue is read directly rather than through ``gate.depth`` because
    ``depth`` takes the sync condition, and the async path mutates the queue
    under the async condition — which is the very split under test. Reading the
    deque's length is a single atomic read of a CPython list, which is enough
    to know the ticket is enqueued.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(gate._queues[priority]) > 0:
            return True
        time.sleep(0.005)
    return False


def test_a_sync_release_wakes_an_async_waiter() -> None:
    """A sync release must free a waiter that is parked in the async path."""
    gate = _gate(limit=1)
    gate.acquire(Priority.DEFAULT)
    assert gate.active == 1

    async def scenario() -> str:
        waiter = asyncio.create_task(gate.aacquire(Priority.DEFAULT))
        # Give the task a chance to enqueue and start waiting.
        await asyncio.sleep(0.05)
        gate.release()
        try:
            await asyncio.wait_for(waiter, timeout=2.0)
        except asyncio.TimeoutError:
            return "hung"
        return "acquired"

    assert asyncio.run(scenario()) == "acquired"
    assert gate.active == 1


def test_an_async_release_wakes_a_sync_waiter() -> None:
    """An async release must free a waiter that is parked in the sync path."""
    gate = _gate(limit=1)

    async def scenario() -> str:
        await gate.aacquire(Priority.DEFAULT)
        assert gate.active == 1

        waiter_ran = asyncio.Event()

        def sync_waiter() -> None:
            gate.acquire(Priority.DEFAULT)
            waiter_ran.set()

        import threading

        thread = threading.Thread(target=sync_waiter, daemon=True)
        thread.start()
        # Wait until the sync ticket is queued, then release from the async side.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and len(gate._queues[Priority.DEFAULT]) == 0:
            await asyncio.sleep(0.005)
        await gate.arelease()
        try:
            await asyncio.wait_for(waiter_ran.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            return "hung"
        return "acquired"

    assert asyncio.run(scenario()) == "acquired"


def test_both_paths_share_one_active_count() -> None:
    """The two paths must account for the same slots, not each their own."""
    gate = _gate(limit=2)
    gate.acquire(Priority.DEFAULT)

    async def scenario() -> int:
        await gate.aacquire(Priority.DEFAULT)
        return gate.active

    assert asyncio.run(scenario()) == 2
    gate.release()
    assert gate.active == 1
