import asyncio
import threading
import time

import httpx
import pytest

from backstop import BackstopConfig
from backstop.exceptions import BudgetExceededError
from backstop.state import BackstopState
from backstop.transports import AsyncBackstopTransport, BackstopTransport


def test_sync_transport_reconciles_usage_and_blocks_over_budget():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"usage": {"total_tokens": 5}, "ok": True})

    state = BackstopState.create(10, BackstopConfig(default_max_output_tokens=1))
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )
    first = client.post("/v1/responses", json={"input": "hello", "max_output_tokens": 1})
    assert first.status_code == 200
    assert state.budget.remaining == 5
    with pytest.raises(BudgetExceededError):
        client.post("/v1/responses", json={"input": "hello", "max_output_tokens": 10})
    assert calls == 1
    client.close()


def test_sync_transport_retries_retryable_statuses():
    statuses = [503, 200]
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(statuses.pop(0), json={"usage": {"total_tokens": 1}})

    state = BackstopState.create(
        100,
        BackstopConfig(default_max_output_tokens=1, retry_max_attempts=2, aimd_adjustment_interval=0),
    )
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler), sleep=sleeps.append),
        base_url="https://mock.local",
    )
    assert client.post("/v1/responses", json={"input": "x", "max_output_tokens": 1}).status_code == 200
    assert len(sleeps) == 1
    client.close()


def test_critical_queued_request_beats_background_when_capacity_opens():
    order: list[str] = []
    release_first = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        priority = request.headers.get("X-Backstop-Priority", "default")
        order.append(priority)
        if priority == "background" and len(order) == 1:
            release_first.wait(timeout=2)
        return httpx.Response(200, json={"usage": {"total_tokens": 1}})

    state = BackstopState.create(
        100,
        BackstopConfig(
            default_max_output_tokens=1,
            initial_concurrency=1,
            max_concurrency=1,
            starvation_after_seconds=60,
        ),
    )
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )

    def send(priority: str) -> None:
        client.post(
            "/v1/responses",
            headers={"X-Backstop-Priority": priority},
            json={"input": priority, "max_output_tokens": 1},
        )

    first = threading.Thread(target=send, args=("background",))
    second = threading.Thread(target=send, args=("background",))
    third = threading.Thread(target=send, args=("critical",))
    first.start()
    time.sleep(0.05)
    second.start()
    time.sleep(0.05)
    third.start()
    time.sleep(0.05)
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)
    third.join(timeout=2)
    client.close()
    assert order[:3] == ["background", "critical", "background"]


@pytest.mark.anyio
async def test_async_transport_reconciles_usage():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"usage": {"total_tokens": 3}})

    state = BackstopState.create(10, BackstopConfig(default_max_output_tokens=1))
    async with httpx.AsyncClient(
        transport=AsyncBackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    ) as client:
        response = await client.post("/v1/responses", json={"input": "hello", "max_output_tokens": 1})
    assert response.status_code == 200
    assert calls == 1
    assert state.budget.remaining == 7

