import threading

import httpx
import pytest

from backstop import BackstopConfig
from backstop.budget import Budget
from backstop.exceptions import BudgetExceededError
from backstop.ledger import (
    BudgetLedger,
    ReservationTicket,
    TenantBudget,
    get_current_tenant,
    get_ledger,
    reset_ledger,
    with_budget,
)
from backstop.pricing import estimate_cost, get_downgrade_target, register_pricing
from backstop.state import BackstopState
from backstop.transports import BackstopTransport


def test_tenant_budget_reserves_and_commits():
    budget = TenantBudget(tenant_id="alice", limit_tokens=100)
    assert budget.remaining == 100

    ticket = budget.reserve(40)
    assert isinstance(ticket, ReservationTicket)
    assert ticket.tenant_id == "alice"
    assert ticket.tokens == 40
    assert budget.remaining == 60

    budget.commit(ticket, 25)
    assert budget.used == 25
    assert budget.remaining == 75


def test_tenant_budget_blocks_when_exhausted():
    budget = TenantBudget(tenant_id="alice", limit_tokens=10)
    budget.reserve(10)
    with pytest.raises(BudgetExceededError, match="alice"):
        budget.reserve(1)


def test_tenant_budget_commit_refunds_unused():
    budget = TenantBudget(tenant_id="bob", limit_tokens=100)
    ticket = budget.reserve(50)
    budget.commit(ticket, 30)
    assert budget.used == 30
    assert budget.remaining == 70


def test_ledger_register_and_get():
    ledger = BudgetLedger()
    ledger.register({
        "alice": TenantBudget(tenant_id="alice", limit_tokens=100),
        "bob": TenantBudget(tenant_id="bob", limit_tokens=200),
    })
    assert ledger.get("alice") is not None
    assert ledger.get("bob") is not None
    assert ledger.get("carol") is None


def test_ledger_cross_tenant_isolation():
    ledger = BudgetLedger()
    ledger.register({
        "alice": TenantBudget(tenant_id="alice", limit_tokens=10),
        "bob": TenantBudget(tenant_id="bob", limit_tokens=100),
    })
    ledger.reserve("alice", 10)
    with pytest.raises(BudgetExceededError):
        ledger.reserve("alice", 1)
    ticket = ledger.reserve("bob", 50)
    assert ticket.tenant_id == "bob"
    ledger.commit("bob", ticket, 30)
    assert ledger.get("bob").used == 30
    assert ledger.get("alice").used == 0


def test_ledger_concurrent_reservation_caps_usage():
    ledger = BudgetLedger()
    ledger.register({
        "alice": TenantBudget(tenant_id="alice", limit_tokens=5_000),
    })
    results: list[int] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def try_reserve():
        try:
            ticket = ledger.reserve("alice", 1_000)
            with lock:
                results.append(ticket.tokens)
        except BudgetExceededError as e:
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=try_reserve) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 5
    assert len(errors) == 27


def test_with_budget_context_var():
    reset_ledger()
    assert get_current_tenant() is None
    with with_budget("alice"):
        assert get_current_tenant() == "alice"
    assert get_current_tenant() is None


def test_transport_rejects_tenant_budget_before_http():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"usage": {"total_tokens": 5}})

    ledger = get_ledger()
    ledger.register({
        "alice": TenantBudget(tenant_id="alice", limit_tokens=10),
    })

    state = BackstopState.create(100, BackstopConfig(default_max_output_tokens=1))
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )

    with with_budget("alice"):
        with pytest.raises(BudgetExceededError):
            client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "x" * 2000}], "max_tokens": 1})
    assert len(calls) == 0
    client.close()


def test_transport_tenant_budget_succeeds_when_enough():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"usage": {"total_tokens": 5}})

    ledger = get_ledger()
    ledger.register({
        "alice": TenantBudget(tenant_id="alice", limit_tokens=10_000),
    })

    state = BackstopState.create(100, BackstopConfig(default_max_output_tokens=1))
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )

    with with_budget("alice"):
        response = client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1})
    assert response.status_code == 200
    assert len(calls) == 1
    assert ledger.get("alice").used == 5
    client.close()


def test_downgrade_on_exceed_rewrites_model():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = _json_body_compat(request)
        calls.append(body)
        return httpx.Response(200, json={"usage": {"total_tokens": 5}})

    ledger = get_ledger()
    ledger.register({
        "alice": TenantBudget(tenant_id="alice", limit_tokens=100, on_exceed="downgrade"),
    })

    state = BackstopState.create(100, BackstopConfig(default_max_output_tokens=1))
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )

    with with_budget("alice"):
        response = client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": [{"role": "user", "content": "h" * 500}], "max_tokens": 1})
    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0].get("model") == "gpt-4o-mini"
    client.close()


def test_downgrade_target_lookup():
    assert get_downgrade_target("gpt-4o") == "gpt-4o-mini"
    assert get_downgrade_target("gpt-4o-mini") is None
    assert get_downgrade_target("claude-sonnet-4-20250514") == "claude-haiku-4-20250514"
    assert get_downgrade_target("unknown-model") is None


def test_estimate_cost():
    cost = estimate_cost(1000, 500, "gpt-4o")
    assert cost == 0.0075  # (1000/1000)*0.0025 + (500/1000)*0.01
    cost = estimate_cost(0, 0, "unknown")
    assert cost == 0.0


def test_register_pricing():
    register_pricing("custom-model", {
        "family": "openai",
        "input_cost_per_1k": 0.001,
        "output_cost_per_1k": 0.002,
        "downgrade_to": None,
    })
    assert get_downgrade_target("custom-model") is None
    cost = estimate_cost(1000, 500, "custom-model")
    assert cost == 0.002


def _json_body_compat(request: httpx.Request) -> dict | None:
    import json
    if not request.content:
        return None
    try:
        return json.loads(request.content.decode("utf-8"))
    except Exception:
        return None
