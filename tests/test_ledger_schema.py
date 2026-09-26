"""Tests for the ledger spend event schema and the attribution context.

The attribution semantics are the ones the ledger's finance claims rest on:
nesting merges, an exception inside a scope does not leak the inner value, and
a scope survives an ``asyncio`` task boundary.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from backstop.ledger import (
    Attribution,
    SpendEvent,
    attribution,
    current_attribution,
    with_attribution,
)
from backstop.ledger.schema import (
    OCCURRED_AT_RE,
    OUTCOMES,
    PRIORITIES,
    SCHEMA_VERSION,
    normalize_endpoint,
    utc_now,
)


def make_event(**overrides) -> SpendEvent:
    """Build a valid event; ``overrides`` replaces individual fields."""
    fields = {
        "provider": "openai",
        "model": "gpt-4o",
        "endpoint": "/v1/chat/completions",
        "priority": "default",
        "outcome": "success",
        "input_tokens": 120,
        "output_tokens": 45,
        "estimated": False,
        "attribution": Attribution(team="payments", feature="checkout-v2"),
    }
    fields.update(overrides)
    return SpendEvent(**fields)


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def test_attribution_defaults_to_all_none():
    empty = Attribution()
    assert empty.keys() == {}
    assert all(value is None for value in empty.to_dict().values())


def test_attribution_is_frozen():
    with pytest.raises(FrozenInstanceError):
        Attribution(team="payments").team = "refunds"  # type: ignore[misc]


def test_attribution_is_hashable_so_it_can_key_aggregation():
    totals: dict[Attribution, int] = {}
    totals[Attribution(team="payments")] = 1
    totals[Attribution(team="payments")] += 1
    totals[Attribution(team="refunds")] = 5
    assert totals[Attribution(team="payments")] == 2
    assert totals[Attribution(team="refunds")] == 5
    assert len(totals) == 2


def test_attribution_keys_returns_only_set_fields():
    set_fields = Attribution(team="payments", customer="acme", currency="USD")
    assert set_fields.keys() == {"team": "payments", "customer": "acme", "currency": "USD"}


def test_merge_lets_the_override_win_on_set_fields():
    base = Attribution(team="payments", feature="checkout-v2")
    override = Attribution(feature="refunds", agent="refund-bot")
    merged = base.merge(override)
    assert merged == Attribution(
        team="payments", feature="refunds", agent="refund-bot"
    )


def test_merge_returns_a_new_object_and_never_mutates_either_input():
    base = Attribution(team="payments")
    override = Attribution(feature="refunds")
    merged = base.merge(override)
    assert merged is not base and merged is not override
    assert base == Attribution(team="payments")
    assert override == Attribution(feature="refunds")


def test_merge_with_an_empty_override_keeps_the_base():
    base = Attribution(team="payments", feature="checkout-v2")
    assert base.merge(Attribution()) == base


# ---------------------------------------------------------------------------
# SpendEvent shape
# ---------------------------------------------------------------------------


def test_event_defaults_match_the_schema():
    event = make_event()
    assert event.schema_version == SCHEMA_VERSION == "1.0"
    assert event.cache_read_tokens == 0
    assert event.cache_write_tokens == 0
    assert event.latency_ms == 0.0
    assert event.retries == 0
    assert event.cost is None
    assert event.request_id is None


def test_event_id_is_a_uuid4_hex_and_unique_per_event():
    first, second = make_event(), make_event()
    assert len(first.event_id) == 32
    assert int(first.event_id, 16) >= 0
    assert first.event_id != second.event_id


def test_occurred_at_is_rfc3339_utc_with_microsecond_precision():
    event = make_event()
    assert len(event.occurred_at) == len("2026-09-25T14:03:11.123456Z")
    assert event.occurred_at.endswith("Z")
    parsed = datetime.strptime(event.occurred_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    assert parsed.replace(tzinfo=timezone.utc).utcoffset() == timedelta(0)
    assert abs((datetime.now(timezone.utc) - parsed.replace(tzinfo=timezone.utc))) < timedelta(seconds=5)


def test_occurred_at_matches_the_exported_regex():
    assert OCCURRED_AT_RE.fullmatch(make_event().occurred_at)
    assert OCCURRED_AT_RE.fullmatch(utc_now())
    assert OCCURRED_AT_RE.fullmatch("2026-09-25T14:03:11.123456Z")
    assert OCCURRED_AT_RE.fullmatch("2026-09-25T14:03:11Z") is None
    assert OCCURRED_AT_RE.fullmatch("2026-09-25T14:03:11.123Z") is None
    assert OCCURRED_AT_RE.fullmatch("2026-09-25T14:03:11.123456+00:00") is None


def test_event_is_frozen():
    with pytest.raises(FrozenInstanceError):
        make_event().outcome = "error"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SpendEvent validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"]
)
def test_negative_token_counts_are_rejected_and_name_the_field(name):
    with pytest.raises(ValueError, match=name) as excinfo:
        make_event(**{name: -1})
    assert "-1" in str(excinfo.value)


def test_negative_latency_is_rejected_and_names_the_field():
    with pytest.raises(ValueError, match="latency_ms"):
        make_event(latency_ms=-0.5)


def test_negative_retries_are_rejected_and_name_the_field():
    with pytest.raises(ValueError, match="retries"):
        make_event(retries=-1)


def test_unknown_priority_is_rejected_and_shows_the_bad_value():
    with pytest.raises(ValueError, match="priority") as excinfo:
        make_event(priority="urgent")
    assert "urgent" in str(excinfo.value)


def test_unknown_outcome_is_rejected_and_shows_the_bad_value():
    with pytest.raises(ValueError, match="outcome") as excinfo:
        make_event(outcome="exploded")
    assert "exploded" in str(excinfo.value)


@pytest.mark.parametrize("priority", PRIORITIES)
def test_every_documented_priority_is_accepted(priority):
    assert make_event(priority=priority).priority == priority


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_every_documented_outcome_is_accepted(outcome):
    assert make_event(outcome=outcome).outcome == outcome


# ---------------------------------------------------------------------------
# Endpoint normalisation
# ---------------------------------------------------------------------------


def test_a_normal_path_is_recorded_unchanged():
    assert make_event(endpoint="/v1/chat/completions").endpoint == "/v1/chat/completions"
    assert (
        make_event(endpoint="https://api.openai.com:443/v1/messages").endpoint
        == "https://api.openai.com:443/v1/messages"
    )


def test_a_query_string_is_stripped_from_the_recorded_endpoint():
    event = make_event(endpoint="/v1/chat/completions?beta=true&stream=false")
    assert event.endpoint == "/v1/chat/completions"
    assert event.to_dict()["endpoint"] == "/v1/chat/completions"


def test_a_credential_in_the_query_string_is_redacted_not_stored():
    event = make_event(endpoint="/v1/chat/completions?api_key=sk-live-SECRET")
    assert "sk-live-SECRET" not in event.endpoint
    assert "sk-live-SECRET" not in repr(event)
    assert "sk-live-SECRET" not in str(event.to_dict())
    assert event.endpoint == "/v1/chat/completions?<redacted>"


@pytest.mark.parametrize(
    "raw",
    [
        "/v1/chat/completions?api_key=sk-1",
        "/v1/chat/completions?key=sk-1",
        "/v1/chat/completions?access_token=sk-1",
        "/v1/chat/completions?X-Api-Key=sk-1",
        "/v1/chat/completions?authorization=Bearer+sk-1",
        "/v1/chat/completions?X-Amz-Signature=sk-1",
        "/v1/chat/completions?apiKey=sk-1",
        "/v1/chat/completions?beta=true&api_key=sk-1",
    ],
)
def test_every_credential_shaped_query_parameter_is_redacted(raw):
    normalised = normalize_endpoint(raw)
    assert "sk-1" not in normalised
    assert normalised == "/v1/chat/completions?<redacted>"


def test_a_credential_free_query_is_dropped_without_a_redaction_marker():
    assert normalize_endpoint("/v1/chat/completions?monkey=1&stream=false") == (
        "/v1/chat/completions"
    )


def test_userinfo_and_fragment_are_stripped_from_the_recorded_endpoint():
    event = make_event(endpoint="https://user:pa55word@api.openai.com:443/v1/chat#top")
    assert event.endpoint == "https://api.openai.com:443/v1/chat"
    assert "pa55word" not in repr(event)


def test_an_unparsable_url_is_still_stripped_textually():
    assert normalize_endpoint("http://[::1?api_key=sk-1") == "http://[::1"
    assert normalize_endpoint("http://user@[::1/p?x=1") == "http://[::1/p"


def test_a_non_string_endpoint_is_rejected():
    with pytest.raises(TypeError, match="endpoint"):
        make_event(endpoint=None)


# ---------------------------------------------------------------------------
# SpendEvent wire form
# ---------------------------------------------------------------------------


def test_to_dict_is_json_serialisable_in_schema_order():
    payload = make_event(cache_read_tokens=7, retries=2, request_id="req_1").to_dict()
    assert list(payload) == [
        "event_id",
        "occurred_at",
        "schema_version",
        "provider",
        "model",
        "endpoint",
        "priority",
        "outcome",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "latency_ms",
        "retries",
        "estimated",
        "attribution",
        "cost",
        "request_id",
    ]
    json.dumps(payload)
    assert payload["cost"] is None
    assert payload["attribution"] == {
        "team": "payments",
        "feature": "checkout-v2",
        "agent": None,
        "session": None,
        "task": None,
        "surface": None,
        "customer": None,
        "tenant": None,
        "environment": None,
        "repo": None,
        "cost_center": None,
        "gl_code": None,
        "currency": None,
    }


def test_round_trip_through_dict_reproduces_the_event():
    event = make_event(
        cache_read_tokens=11,
        cache_write_tokens=13,
        latency_ms=842.5,
        retries=1,
        estimated=True,
        request_id="req_abc",
        attribution=Attribution(
            team="payments", customer="acme", gl_code="4120", currency="USD"
        ),
    )
    assert SpendEvent.from_dict(event.to_dict()) == event


def test_round_trip_survives_a_json_line():
    event = make_event()
    line = json.dumps(event.to_dict())
    assert SpendEvent.from_dict(json.loads(line)) == event


def test_from_dict_revalidates():
    payload = make_event().to_dict()
    payload["priority"] = "urgent"
    with pytest.raises(ValueError, match="priority"):
        SpendEvent.from_dict(payload)


# ---------------------------------------------------------------------------
# Attribution context: scoping
# ---------------------------------------------------------------------------


def test_current_attribution_is_never_none_outside_any_scope():
    assert isinstance(current_attribution(), Attribution)


def test_attribution_context_manager_yields_the_merged_value():
    with attribution(team="payments") as active:
        assert active == Attribution(team="payments")
        assert current_attribution() is active


def test_nested_scope_wins_on_conflicts_and_inherits_the_rest():
    with attribution(team="payments", feature="checkout-v2"):
        with attribution(feature="refunds", agent="refund-bot"):
            active = current_attribution()
            assert active == Attribution(
                team="payments", feature="refunds", agent="refund-bot"
            )
        assert current_attribution() == Attribution(
            team="payments", feature="checkout-v2"
        )
    assert current_attribution() == Attribution()


def test_outer_value_is_restored_when_the_inner_body_raises():
    with attribution(team="payments"):
        with pytest.raises(RuntimeError, match="boom"):
            with attribution(feature="refunds"):
                assert current_attribution().feature == "refunds"
                raise RuntimeError("boom")
        assert current_attribution() == Attribution(team="payments")


def test_outer_value_is_restored_when_an_outer_body_raises():
    with pytest.raises(RuntimeError, match="boom"):
        with attribution(team="payments"):
            raise RuntimeError("boom")
    assert current_attribution() == Attribution()


def test_unknown_field_name_raises_type_error():
    with pytest.raises(TypeError, match="cost_centerz"):
        with attribution(team="payments", cost_centerz="cc-1"):
            pass


def test_unknown_field_name_raises_before_the_scope_is_entered():
    with attribution(team="payments"):
        with pytest.raises(TypeError, match="nope"):
            with attribution(nope="x"):
                pass
        assert current_attribution() == Attribution(team="payments")


@pytest.mark.parametrize("bad", [1, 3.5, object(), ["team"], {"a": 1}])
def test_non_string_values_raise_type_error(bad):
    with pytest.raises(TypeError, match="team"):
        attribution(team=bad)


def test_decorator_rejects_a_non_string_value_at_decoration_time():
    with pytest.raises(TypeError, match="team"):
        with_attribution(team=7)


# ---------------------------------------------------------------------------
# Attribution context: decorator
# ---------------------------------------------------------------------------


def test_decorated_function_runs_under_its_fields():
    @with_attribution(agent="refund-bot")
    def handle_refund(ticket):
        return current_attribution()

    assert handle_refund("t-1") == Attribution(agent="refund-bot")
    assert current_attribution() == Attribution()


def test_decorated_function_merges_with_the_enclosing_scope():
    with attribution(team="payments"):
        @with_attribution(agent="refund-bot")
        def handle_refund():
            return current_attribution()

        assert handle_refund() == Attribution(team="payments", agent="refund-bot")
        assert current_attribution() == Attribution(team="payments")


def test_decorator_restores_the_outer_value_when_the_body_raises():
    with attribution(team="payments"):

        @with_attribution(feature="refunds")
        def boom():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            boom()
        assert current_attribution() == Attribution(team="payments")


def test_decorator_works_on_methods_and_preserves_metadata():
    class Refunds:
        @with_attribution(agent="refund-bot")
        def handle(self, ticket):
            return current_attribution(), self

        @staticmethod
        @with_attribution(agent="refund-bot")
        def statics(ticket):
            return current_attribution(), ticket

    refunds = Refunds()
    active, receiver = refunds.handle("t-1")
    assert active == Attribution(agent="refund-bot")
    assert receiver is refunds
    assert Refunds.handle.__name__ == "handle"

    active, ticket = Refunds.statics("t-1")
    assert active == Attribution(agent="refund-bot")
    assert ticket == "t-1"


def test_decorator_refuses_a_generator_function():
    with pytest.raises(TypeError, match="generator"):

        @with_attribution(agent="refund-bot")
        def stream():
            yield current_attribution()


def test_decorator_refuses_an_async_generator_function():
    with pytest.raises(TypeError, match="async generator function"):

        @with_attribution(agent="refund-bot")
        async def stream():
            yield current_attribution()


def test_decorator_refuses_a_function_that_returns_a_coroutine():
    @with_attribution(agent="refund-bot")
    def bridge():
        async def body():
            return current_attribution()

        return body()

    with pytest.raises(TypeError, match="coroutine"):
        bridge()

    with pytest.raises(TypeError, match="coroutine"):
        asyncio.run(bridge())


def test_decorator_refuses_a_function_that_returns_a_generator():
    @with_attribution(agent="refund-bot")
    def bridge():
        def body():
            yield current_attribution()

        return body()

    with pytest.raises(TypeError, match="generator"):
        bridge()


def test_decorator_refuses_a_coroutine_returned_from_a_coroutine_function():
    @with_attribution(agent="refund-bot")
    async def bridge():
        async def body():
            return current_attribution()

        return body()

    with pytest.raises(TypeError, match="coroutine"):
        asyncio.run(bridge())


def test_a_refused_deferred_body_leaves_the_scope_clean():
    @with_attribution(agent="refund-bot")
    def bridge():
        async def body():
            return current_attribution()

        return body()

    with pytest.raises(TypeError):
        bridge()
    assert current_attribution() == Attribution()


def test_a_refused_deferred_body_is_closed_so_it_never_warns():
    captured: list[object] = []

    @with_attribution(agent="refund-bot")
    def bridge():
        async def body():
            return current_attribution()

        coroutine = body()
        captured.append(coroutine)
        return coroutine

    with pytest.raises(TypeError, match="coroutine"):
        bridge()
    assert inspect.getcoroutinestate(captured[0]) == inspect.CORO_CLOSED


def test_a_scheduled_future_is_allowed_because_its_context_was_copied():
    async def work():
        await asyncio.sleep(0)
        return current_attribution()

    @with_attribution(agent="refund-bot")
    async def gatherer():
        return await asyncio.gather(work())

    assert asyncio.run(gatherer()) == [Attribution(agent="refund-bot")]


def test_a_plain_value_result_is_allowed():
    @with_attribution(agent="refund-bot")
    def compute():
        return [current_attribution(), current_attribution()]

    assert compute() == [Attribution(agent="refund-bot")] * 2
    assert current_attribution() == Attribution()


# ---------------------------------------------------------------------------
# Attribution context: async
# ---------------------------------------------------------------------------


def test_decorated_coroutine_runs_under_its_fields():
    @with_attribution(agent="refund-bot")
    async def handle_refund(ticket):
        await asyncio.sleep(0)
        return current_attribution()

    async def main():
        return await handle_refund("t-1")

    assert asyncio.run(main()) == Attribution(agent="refund-bot")
    assert current_attribution() == Attribution()


def test_decorated_coroutine_restores_the_outer_value_after_await():
    with attribution(team="payments"):

        @with_attribution(agent="refund-bot")
        async def handle_refund():
            await asyncio.sleep(0)
            return current_attribution()

        async def main():
            return await handle_refund()

        assert asyncio.run(main()) == Attribution(team="payments", agent="refund-bot")
        assert current_attribution() == Attribution(team="payments")


def test_decorated_coroutine_restores_the_outer_value_when_it_raises():
    with attribution(team="payments"):

        @with_attribution(agent="refund-bot")
        async def boom():
            await asyncio.sleep(0)
            raise RuntimeError("boom")

        async def main():
            await boom()

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(main())
        assert current_attribution() == Attribution(team="payments")


def test_coroutine_wrapper_is_not_marked_async_when_wrapping_sync_callables():
    @with_attribution(agent="refund-bot")
    def sync_callable():
        return None

    assert not asyncio.iscoroutinefunction(sync_callable)


def test_coroutine_wrapper_is_awaitable_for_async_callables():
    @with_attribution(agent="refund-bot")
    async def async_callable():
        return 1

    assert asyncio.iscoroutinefunction(async_callable)


def test_attribution_context_manager_spans_an_await():
    async def main():
        with attribution(team="payments", feature="checkout-v2"):
            await asyncio.sleep(0)
            return current_attribution()

    assert asyncio.run(main()) == Attribution(team="payments", feature="checkout-v2")
    assert current_attribution() == Attribution()


def test_attribution_propagates_into_an_asyncio_task():
    seen: list[Attribution] = []

    async def child():
        seen.append(current_attribution())
        with attribution(feature="refunds"):
            seen.append(current_attribution())

    async def main():
        with attribution(team="payments", feature="checkout-v2"):
            await asyncio.create_task(child())
        seen.append(current_attribution())

    asyncio.run(main())

    assert seen[0] == Attribution(team="payments", feature="checkout-v2")
    assert seen[1] == Attribution(team="payments", feature="refunds")
    assert seen[2] == Attribution()


def test_a_task_scope_does_not_leak_back_to_the_parent_task():
    async def child():
        with attribution(team="refunds"):
            return current_attribution()

    async def main():
        with attribution(team="payments"):
            inside = await asyncio.create_task(child())
            return inside, current_attribution()

    inside, after = asyncio.run(main())

    assert inside == Attribution(team="refunds")
    assert after == Attribution(team="payments")


def test_concurrent_tasks_keep_their_own_scopes():
    observed: dict[str, Attribution] = {}

    async def worker(name):
        with attribution(team=name):
            await asyncio.sleep(0)
            observed[name] = current_attribution()

    async def main():
        await asyncio.gather(worker("payments"), worker("refunds"))

    asyncio.run(main())

    assert observed == {
        "payments": Attribution(team="payments"),
        "refunds": Attribution(team="refunds"),
    }


# ---------------------------------------------------------------------------
# Top-level exports
# ---------------------------------------------------------------------------


def test_top_level_package_reexports_the_ledger_public_api():
    import backstop

    from backstop import ledger

    assert backstop.Attribution is ledger.Attribution
    assert backstop.SpendEvent is ledger.SpendEvent
    assert backstop.attribution is ledger.attribution
    assert backstop.with_attribution is ledger.with_attribution
    assert backstop.current_attribution is ledger.current_attribution


def test_top_level_ledger_exports_are_declared_in_dunder_all():
    import backstop

    for name in (
        "Attribution",
        "SpendEvent",
        "attribution",
        "current_attribution",
        "with_attribution",
    ):
        assert name in backstop.__all__


def test_documented_top_level_import_form_works():
    from backstop import attribution, current_attribution, with_attribution

    @with_attribution(agent="refund-bot")
    def handle_refund():
        return current_attribution()

    with attribution(team="payments", feature="checkout-v2"):
        assert handle_refund() == Attribution(
            team="payments", feature="checkout-v2", agent="refund-bot"
        )
        assert current_attribution() == Attribution(team="payments", feature="checkout-v2")
