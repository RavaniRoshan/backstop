"""Regression tests for the priority gate.

A gate acquirer that gives up must not leave its ticket behind: `_choose_ticket`
always returns the head of a priority deque, so a stale ticket at the head blocks
every later acquirer at that priority forever.
"""
from __future__ import annotations

import pytest

from backstop.aimd import AIMDController
from backstop.config import BackstopConfig, Priority
from backstop.admission import PriorityGate

QUEUE_TIMEOUT = 0.05


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
