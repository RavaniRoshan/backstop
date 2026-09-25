import threading

import httpx
import pytest

from backstop import BackstopConfig
from backstop.budget import Budget
from backstop.exceptions import BudgetExceededError
from backstop.state import BackstopState
from backstop.state_backends import InMemoryBudgetBackend
from backstop.transports import AsyncBackstopTransport


def test_budget_reserves_and_reconciles_actual_usage():
    budget = Budget(100)
    reservation = budget.reserve(40)
    assert budget.remaining == 60
    budget.reconcile(reservation, 25, success=True)
    assert budget.spent == 25
    assert budget.remaining == 75


def test_budget_zero_blocks_immediately():
    budget = Budget(0)
    with pytest.raises(BudgetExceededError):
        budget.reserve(1)


def test_budget_none_is_unlimited():
    budget = Budget(None)
    reservation = budget.reserve(1_000_000)
    budget.reconcile(reservation, None, success=True)
    assert budget.remaining is None
    assert budget.spent == 0


def test_success_without_usage_keeps_estimate_charged():
    budget = Budget(100)
    reservation = budget.reserve(30)
    budget.reconcile(reservation, None, success=True)
    assert budget.spent == 30


def test_failed_request_releases_reservation_without_charge():
    budget = Budget(100)
    reservation = budget.reserve(30)
    budget.reconcile(reservation, None, success=False)
    assert budget.spent == 0
    assert budget.remaining == 100


class _RecordingBackend(InMemoryBudgetBackend):
    """In-memory backend that records which entry point committed, and where.

    ``sync_commits`` counts commits entered from outside the async path (i.e. a
    synchronous reconcile on the event loop); ``commit_threads`` records the
    thread each commit actually ran on, so a stray ``to_thread`` hop shows up.
    The same applies to ``reserve_threads``.
    """

    def __init__(self, total):
        super().__init__(total)
        self.acommits = 0
        self.sync_commits = 0
        self.commit_threads: list[int] = []
        self.reserve_threads: list[int] = []
        self._in_async_commit = False

    def commit(self, reserved, charge):
        if not self._in_async_commit:
            self.sync_commits += 1
        self.commit_threads.append(threading.get_ident())
        super().commit(reserved, charge)

    def reserve(self, tokens):
        self.reserve_threads.append(threading.get_ident())
        return super().reserve(tokens)

    async def acommit(self, reserved, charge):
        self.acommits += 1
        self._in_async_commit = True
        try:
            await super().acommit(reserved, charge)
        finally:
            self._in_async_commit = False


@pytest.mark.anyio
async def test_areconcile_uses_the_async_backend_path():
    backend = _RecordingBackend(100)
    budget = Budget(100, backend=backend)
    reservation = await budget.areserve(30)

    await budget.areconcile(reservation, 25, success=True)

    assert backend.acommits == 1
    assert backend.sync_commits == 0, "areconcile fell through to a sync commit"
    assert budget.spent == 25


@pytest.mark.anyio
async def test_in_memory_acommit_stays_on_the_event_loop():
    """The default backend has no I/O, so it must not pay a to_thread hop."""
    backend = _RecordingBackend(100)
    budget = Budget(100, backend=backend)
    reservation = await budget.areserve(30)

    await budget.areconcile(reservation, 25, success=True)

    assert backend.commit_threads == [threading.get_ident()], (
        "the in-memory commit hopped to another thread for no reason"
    )
    assert budget.spent == 25


@pytest.mark.anyio
async def test_in_memory_areserve_stays_on_the_event_loop():
    """The default backend has no I/O, so the reserve must not hop either."""
    backend = _RecordingBackend(100)
    budget = Budget(100, backend=backend)

    reservation = await budget.areserve(30)

    assert backend.reserve_threads == [threading.get_ident()], (
        "the in-memory reserve hopped to another thread for no reason"
    )
    assert reservation.tokens == 30
    assert budget.remaining == 70


@pytest.mark.anyio
async def test_async_transport_reconciles_through_the_async_backend_path():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"usage": {"total_tokens": 3}})

    backend = _RecordingBackend(1000)
    state = BackstopState.create(
        1000, BackstopConfig(default_max_output_tokens=1), backend=backend
    )
    async with httpx.AsyncClient(
        transport=AsyncBackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    ) as client:
        response = await client.post(
            "/v1/responses", json={"input": "hello", "max_output_tokens": 1}
        )
    assert response.status_code == 200
    assert backend.acommits == 1
    assert backend.sync_commits == 0, "the async transport reconciled synchronously"
    assert state.budget.spent == 3

