"""Regression tests for the priority gate.

A gate acquirer that gives up must not leave its ticket behind: `_choose_ticket`
always returns the head of a priority deque, so a stale ticket at the head blocks
every later acquirer at that priority forever.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from backstop.aimd import AIMDController
from backstop.config import BackstopConfig, Priority
from backstop.admission import PriorityGate

QUEUE_TIMEOUT = 0.05
DISCARD_TIMEOUT = 0.25


def _saturated_gate() -> PriorityGate:
    """A gate with exactly one slot, so the second acquirer cannot be admitted."""
    config = BackstopConfig(
        initial_concurrency=1,
        min_concurrency=1,
        max_concurrency=1,
        queue_timeout=QUEUE_TIMEOUT,
        starvation_after_seconds=3600.0,
    )
    return PriorityGate(config, AIMDController(config))


def test_sync_timeout_does_not_wedge_the_priority_queue():
    gate = _saturated_gate()
    gate.acquire(Priority.DEFAULT, timeout=QUEUE_TIMEOUT)  # takes the only slot

    with pytest.raises(TimeoutError):
        gate.acquire(Priority.DEFAULT, timeout=QUEUE_TIMEOUT)

    assert gate.depth == 0, "the timed-out ticket was left in the queue"

    gate.release()
    assert gate.acquire(Priority.DEFAULT, timeout=QUEUE_TIMEOUT) >= 0
    gate.release()
    assert gate.depth == 0


@pytest.mark.anyio
async def test_async_timeout_does_not_wedge_the_priority_queue():
    gate = _saturated_gate()
    await gate.aacquire(Priority.DEFAULT, timeout=QUEUE_TIMEOUT)

    with pytest.raises(TimeoutError):
        await gate.aacquire(Priority.DEFAULT, timeout=QUEUE_TIMEOUT)

    assert gate.depth == 0, "the timed-out ticket was left in the queue"

    await gate.arelease()
    assert await gate.aacquire(Priority.DEFAULT, timeout=QUEUE_TIMEOUT) >= 0
    await gate.arelease()
    assert gate.depth == 0


def _one_slot_two_limit_gate() -> tuple[PriorityGate, AIMDController]:
    """A gate with one slot taken and room to grow, and no queue timeout.

    ``queue_timeout=None`` is what makes the notify load-bearing: a survivor
    asleep with no timeout would never be woken by anything but an explicit
    ``notify_all``.
    """
    config = BackstopConfig(
        initial_concurrency=1,
        min_concurrency=1,
        max_concurrency=2,
        aimd_adjustment_interval=0.0,
        queue_timeout=None,
        starvation_after_seconds=3600.0,
    )
    aimd = AIMDController(config)
    return PriorityGate(config, aimd), aimd


def test_discarded_ticket_wakes_the_survivor_queued_behind_it():
    """Discarding a ticket must re-evaluate whoever was queued behind it.

    The AIMD limit rises while both tickets sleep, so the survivor becomes
    admissible the instant the head is discarded. Without the notify it would
    sleep on until unrelated traffic, and with no queue timeout, forever.
    """
    gate, aimd = _one_slot_two_limit_gate()
    gate.acquire(Priority.DEFAULT)  # takes the only slot

    survivor_admitted = threading.Event()

    def doomed() -> None:
        with pytest.raises(TimeoutError):
            gate.acquire(Priority.DEFAULT, timeout=DISCARD_TIMEOUT)

    def survivor() -> None:
        gate.acquire(Priority.DEFAULT)
        survivor_admitted.set()

    first = threading.Thread(target=doomed, daemon=True)
    first.start()
    time.sleep(0.02)  # the doomed ticket must reach the head first
    second = threading.Thread(target=survivor, daemon=True)
    second.start()
    time.sleep(0.02)
    assert aimd.record_success() is True  # limit 1 -> 2, both tickets now admissible

    first.join(timeout=5)
    second.join(timeout=5)
    assert survivor_admitted.is_set(), "the survivor slept through the discard"
    assert gate.active == 2
    gate.release()
    gate.release()


@pytest.mark.anyio
async def test_async_discarded_ticket_wakes_the_survivor_queued_behind_it():
    gate, aimd = _one_slot_two_limit_gate()
    await gate.aacquire(Priority.DEFAULT)  # takes the only slot

    doomed = asyncio.create_task(gate.aacquire(Priority.DEFAULT, timeout=DISCARD_TIMEOUT))
    await asyncio.sleep(0.02)  # the doomed ticket must reach the head first
    survivor = asyncio.create_task(gate.aacquire(Priority.DEFAULT))
    await asyncio.sleep(0.02)
    assert aimd.record_success() is True  # limit 1 -> 2, both tickets now admissible

    with pytest.raises(TimeoutError):
        await doomed
    await asyncio.wait_for(survivor, timeout=5)
    assert gate.active == 2
    await gate.arelease()
    await gate.arelease()
