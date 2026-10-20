"""A budget denominated in dollars.

A token ceiling says how much *work* a session may do. A dollar ceiling says
how much it may *cost*, which is the question a team with a budget actually
asks, and the question a token ceiling cannot answer: two models that take the
same number of tokens can differ in price by twenty times.

The rules this file pins down:

* a dollar ceiling is enforced *before* the request is sent, on a reservation
  of what the request is expected to cost;
* the reservation is settled against the *exact* cost once the request
  completes, so the ceiling tracks reality rather than a running estimate;
* a model the price catalog does not carry cannot be measured against a
  dollar ceiling, so it is refused — because a ceiling with a hole in it is
  not a ceiling;
* the money is :class:`~decimal.Decimal` end to end, and the shared Redis
  backend stores it in integer micro-dollars so no binary float ever touches
  it.
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import httpx
import pytest

from backstop import BackstopConfig
from backstop.exceptions import BudgetExceededError, PriceUnavailableError
from backstop.ledger import TenantBudget, get_ledger, reset_ledger
from backstop.state import BackstopState
from backstop.state_backends import (
    from_micro_dollars,
    to_micro_dollars,
)
from backstop.transports import AsyncBackstopTransport, BackstopTransport

OPENAI_BODY = {
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "hello"}],
    "max_tokens": 8,
}
# 120 input tokens at $2.50/MTok is $0.0003; 30 output at $10.00/MTok is
# $0.0003. The request costs $0.0006.
OPENAI_RESPONSE = {
    "id": "chatcmpl-usd-1",
    "object": "chat.completion",
    "model": "gpt-4o-2024-08-06",
    "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
}


def _handler(response: dict | None = None):
    body = response if response is not None else OPENAI_RESPONSE

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return handler


def _client(state: BackstopState, handler=None) -> httpx.Client:
    transport = BackstopTransport(state, httpx.MockTransport(handler or _handler()))
    # A realistic host, so the ledger identifies the provider and can price
    # the request exactly. An unidentifiable host is recorded as an unknown
    # provider and therefore unpriced — the ledger's conservative choice.
    return httpx.Client(transport=transport, base_url="https://api.openai.com")


def _aclient(state: BackstopState, handler=None) -> httpx.AsyncClient:
    transport = AsyncBackstopTransport(state, httpx.MockTransport(handler or _handler()))
    return httpx.AsyncClient(transport=transport, base_url="https://api.openai.com")


# ---------------------------------------------------------------------------
# The money
# ---------------------------------------------------------------------------


def test_micro_dollars_round_trip_exactly() -> None:
    """The Redis representation is exact, because it is an integer.

    Lua's ``tonumber`` is a double, and a double cannot represent most
    decimal fractions of a dollar. Storing integer micro-dollars is what
    keeps the shared backend's arithmetic exact.
    """
    for value in ("0.000001", "0.000600", "1.000000", "123.456789", "9999.999999"):
        micro = to_micro_dollars(Decimal(value))
        assert isinstance(micro, int)
        assert from_micro_dollars(micro) == Decimal(value)


def test_a_float_is_read_through_its_shortest_repr() -> None:
    """``0.1`` is ``0.1``, not the binary double nearest to it."""
    assert to_micro_dollars(0.1) == 100_000
    assert to_micro_dollars(0.0075) == 7_500


# ---------------------------------------------------------------------------
# The ceiling
# ---------------------------------------------------------------------------


def test_a_dollar_ceiling_is_enforced_before_the_request_is_sent() -> None:
    """A request that would breach the ceiling never reaches the provider."""
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(200, json=OPENAI_RESPONSE)

    state = BackstopState.create(
        None, BackstopConfig(budget_usd=Decimal("0.0001"), default_max_output_tokens=8)
    )
    with _client(state, handler) as client:
        with pytest.raises(BudgetExceededError):
            client.post("/v1/chat/completions", json=OPENAI_BODY)
    assert sent == 0, "the request was sent despite the dollar ceiling"


def test_the_exact_cost_settles_the_reservation() -> None:
    """The ceiling tracks what the request *cost*, not what it was estimated at.

    The estimate is a guess; the ledger's figure is a measurement. The
    reservation is settled against the measurement, so a request that cost
    less than it was estimated at leaves the ceiling with the difference.
    """
    state = BackstopState.create(
        None, BackstopConfig(budget_usd=Decimal("1.000000"), default_max_output_tokens=8)
    )
    with _client(state) as client:
        for _ in range(3):
            assert client.post("/v1/chat/completions", json=OPENAI_BODY).status_code == 200
    # 120 input at $2.50/MTok + 30 output at $10.00/MTok = $0.0006 each.
    assert state.budget.spent_usd == Decimal("0.001800")
    assert state.budget.remaining_usd == Decimal("0.998200")


def test_a_dollar_ceiling_turns_the_ledger_on() -> None:
    """A dollar ceiling needs every request measured, and the ledger measures it.

    The coupling is stated rather than hidden: the cost of a dollar ceiling
    is the cost of the ledger.
    """
    state = BackstopState.create(None, BackstopConfig(budget_usd=Decimal("5.00")))
    assert state.config.ledger_enabled is True
    assert state.prices is not None


def test_a_dollar_ceiling_and_a_token_ceiling_are_both_enforced() -> None:
    """A request is admitted only if it fits under both ceilings."""
    state = BackstopState.create(
        5, BackstopConfig(budget_usd=Decimal("5.00"), default_max_output_tokens=8)
    )
    with _client(state) as client:
        # The token ceiling is the tighter one here: the request is worth
        # about twenty tokens, and the ceiling is five.
        with pytest.raises(BudgetExceededError):
            client.post("/v1/chat/completions", json=OPENAI_BODY)
    assert state.budget.spent == 0
    assert state.budget.spent_usd == Decimal("0.000000")


# ---------------------------------------------------------------------------
# The unpriced model
# ---------------------------------------------------------------------------


def test_an_unpriced_model_is_refused_under_a_dollar_ceiling() -> None:
    """A ceiling with an unpriced hole in it is not a ceiling."""
    body = dict(OPENAI_BODY, model="some-model-nobody-priced")
    state = BackstopState.create(None, BackstopConfig(budget_usd=Decimal("5.00")))
    with _client(state) as client:
        with pytest.raises(PriceUnavailableError) as excinfo:
            client.post("/v1/chat/completions", json=body)
    assert excinfo.value.model == "some-model-nobody-priced"


def test_an_unpriced_model_may_be_allowed_explicitly() -> None:
    """The deployment decides, and the decision has a name."""
    body = dict(OPENAI_BODY, model="some-model-nobody-priced")
    state = BackstopState.create(
        None,
        BackstopConfig(
            budget_usd=Decimal("5.00"), budget_usd_unpriced_policy="allow"
        ),
    )
    with _client(state) as client:
        assert client.post("/v1/chat/completions", json=body).status_code == 200


def test_no_dollar_ceiling_means_no_price_is_needed() -> None:
    """A token-only budget does not need a price, and does not pay for one."""
    body = dict(OPENAI_BODY, model="some-model-nobody-priced")
    state = BackstopState.create(1000, BackstopConfig(default_max_output_tokens=8))
    with _client(state) as client:
        assert client.post("/v1/chat/completions", json=body).status_code == 200
    assert state.prices is None


# ---------------------------------------------------------------------------
# Per-tenant
# ---------------------------------------------------------------------------


def test_a_tenant_can_have_its_own_dollar_ceiling() -> None:
    """A tenant's ceiling is its own, and the parent still caps the child."""
    reset_ledger()
    try:
        parent = TenantBudget("org", 1_000_000, limit_usd=Decimal("1.00"))
        child = TenantBudget("acme", 1_000_000, limit_usd=Decimal("0.10"), parent=parent)
        get_ledger().register({"acme": child})

        state = BackstopState.create(
            None, BackstopConfig(budget_usd=Decimal("5.00"), default_max_output_tokens=8)
        )
        with _client(state) as client:
            from backstop.ledger import with_budget

            with with_budget("acme"):
                for _ in range(100):
                    assert client.post("/v1/chat/completions", json=OPENAI_BODY).status_code == 200
        assert child.used_usd > 0
        assert parent.used_usd == child.used_usd
        assert child.used_usd <= Decimal("0.10")
    finally:
        reset_ledger()


def test_a_tenant_ceiling_is_refused_when_it_would_be_breached() -> None:
    reset_ledger()
    try:
        child = TenantBudget("acme", 1_000_000, limit_usd=Decimal("0.0001"))
        get_ledger().register({"acme": child})
        state = BackstopState.create(
            None, BackstopConfig(budget_usd=Decimal("5.00"), default_max_output_tokens=8)
        )
        with _client(state) as client:
            from backstop.ledger import with_budget

            with with_budget("acme"):
                with pytest.raises(BudgetExceededError):
                    client.post("/v1/chat/completions", json=OPENAI_BODY)
    finally:
        reset_ledger()


# ---------------------------------------------------------------------------
# Sync and async
# ---------------------------------------------------------------------------


def test_the_async_path_enforces_the_dollar_ceiling_too() -> None:
    """A ceiling that only exists on the sync path is not a ceiling."""
    state = BackstopState.create(
        None, BackstopConfig(budget_usd=Decimal("0.0001"), default_max_output_tokens=8)
    )

    async def scenario() -> str:
        async with _aclient(state) as client:
            try:
                await client.post("/v1/chat/completions", json=OPENAI_BODY)
            except BudgetExceededError:
                return "denied"
            return "served"

    assert asyncio.run(scenario()) == "denied"


def test_the_async_path_settles_the_exact_cost_too() -> None:
    state = BackstopState.create(
        None, BackstopConfig(budget_usd=Decimal("1.000000"), default_max_output_tokens=8)
    )

    async def scenario() -> None:
        async with _aclient(state) as client:
            for _ in range(2):
                assert (
                    await client.post("/v1/chat/completions", json=OPENAI_BODY)
                ).status_code == 200

    asyncio.run(scenario())
    assert state.budget.spent_usd == Decimal("0.001200")


# ---------------------------------------------------------------------------
# The estimate
# ---------------------------------------------------------------------------


def test_the_estimate_split_sums_to_the_total() -> None:
    """Splitting the estimate cannot change what a token budget admits."""
    from backstop.config import BackstopConfig as Config
    from backstop.extract import estimate_token_split, estimate_tokens

    config = Config(default_max_output_tokens=8)
    for body in (
        OPENAI_BODY,
        {"model": "gpt-4o", "messages": [{"role": "user", "content": ""}]},
        {"model": "gpt-4o", "messages": []},
    ):
        raw = json.dumps(body).encode()
        total = estimate_tokens(body, raw, config)
        input_tokens, output_tokens = estimate_token_split(body, raw, config)
        assert input_tokens + output_tokens == total


def test_the_estimate_prices_the_split_not_a_blend() -> None:
    """Input and output are priced at their own rates.

    They are often three or four times apart, so a blended total would
    mis-reserve in both directions.
    """
    from backstop._httpcompat import HTTPX
    from backstop.config import Priority
    from backstop.extract import RequestMetadata
    from backstop.policy import build_policy

    state = BackstopState.create(None, BackstopConfig(budget_usd=Decimal("5.00")))
    policy = build_policy(state, compat=HTTPX)
    meta = RequestMetadata(
        priority=Priority.DEFAULT,
        estimated_tokens=1026,
        endpoint="/v1/chat",
        estimated_input_tokens=2,
        estimated_output_tokens=1024,
    )
    # 2 input at $2.50/MTok + 1024 output at $10.00/MTok.
    assert policy.estimate_usd(meta, "gpt-4o") == Decimal("0.010245")
