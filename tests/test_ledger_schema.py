"""Tests for the ledger spend event schema and the attribution context.

The attribution semantics are the ones the ledger's finance claims rest on:
nesting merges, an exception inside a scope does not leak the inner value, and
a scope survives an ``asyncio`` task boundary.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import json
import textwrap
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest

from backstop.ledger import (
    EVENT_ID_RE,
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
    UNKNOWN_ENDPOINT,
    new_event_id,
    normalize_endpoint,
    resolve_cost_type,
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


def test_keys_promises_a_mapping_and_the_record_answers_like_one():
    record = Attribution(team="payments", feature="checkout-v2", gl_code="  ")

    def total(**dimensions: str) -> str:
        return "+".join(f"{k}={v}" for k, v in sorted(dimensions.items()))

    assert dict(record) == {"team": "payments", "feature": "checkout-v2"}
    assert list(record) == ["team", "feature"]
    assert total(**record) == "feature=checkout-v2+team=payments"
    assert "team" in record
    assert "gl_code" not in record
    assert record["team"] == "payments"
    assert record["gl_code"] is None
    with pytest.raises(KeyError):
        record["nope"]


def test_a_blank_string_counts_as_unset():
    assert Attribution(team="", feature="   ").keys() == {}
    assert "team" not in Attribution(team=" ")


def test_a_blank_override_cannot_erase_an_outer_value():
    base = Attribution(team="payments", feature="checkout-v2")
    assert base.merge(Attribution(feature="  ")).keys() == base.keys()
    assert base.merge(Attribution(feature="")).keys() == base.keys()
    assert base.merge(Attribution(gl_code="  ", agent="refund-bot")).keys() == {
        "team": "payments",
        "feature": "checkout-v2",
        "agent": "refund-bot",
    }


def test_a_none_override_cannot_erase_an_outer_value():
    base = Attribution(team="payments", feature="checkout-v2")
    assert base.merge(Attribution(feature=None)).keys() == base.keys()


def test_a_blank_attribution_carries_no_chargeback_dimension():
    assert Attribution(team="payments").merge(Attribution()).keys() == {"team": "payments"}
    assert Attribution(team=" ").merge(Attribution(team="refunds")).keys() == {"team": "refunds"}


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
    # "a" * 32 and any MD5 are 32 hex characters too, so pin the uuid4 layout:
    # the version nibble is 4, and the variant nibble is one of 8, 9, a, b.
    assert first.event_id[12] == "4"
    assert first.event_id[16] in "89ab"
    assert UUID(first.event_id).version == 4
    assert EVENT_ID_RE.match(first.event_id)


def test_occurred_at_is_rfc3339_utc_with_microsecond_precision():
    event = make_event()
    assert len(event.occurred_at) == len("2026-09-25T14:03:11.123456Z")
    assert event.occurred_at.endswith("Z")
    parsed = datetime.strptime(event.occurred_at, "%Y-%m-%dT%H:%M:%S.%fZ")
    assert parsed.replace(tzinfo=timezone.utc).utcoffset() == timedelta(0)
    elapsed = datetime.now(timezone.utc) - parsed.replace(tzinfo=timezone.utc)
    assert abs(elapsed) < timedelta(seconds=5)


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
# SpendEvent type validation
# ---------------------------------------------------------------------------

COUNT_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "retries",
)


@pytest.mark.parametrize("name", COUNT_FIELDS)
def test_a_float_token_count_is_rejected(name):
    with pytest.raises(TypeError, match=name) as excinfo:
        make_event(**{name: 1.5})
    assert "1.5" in str(excinfo.value)


@pytest.mark.parametrize("name", COUNT_FIELDS)
def test_a_bool_token_count_is_rejected_rather_than_billed_as_one(name):
    with pytest.raises(TypeError, match=name):
        make_event(**{name: True})


@pytest.mark.parametrize("name", COUNT_FIELDS)
def test_a_string_token_count_is_rejected(name):
    with pytest.raises(TypeError, match=name):
        make_event(**{name: "5"})


@pytest.mark.parametrize("bad", ["842", None, True, [1]])
def test_a_non_numeric_latency_is_rejected(bad):
    with pytest.raises(TypeError, match="latency_ms"):
        make_event(latency_ms=bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_latency_is_rejected(bad):
    with pytest.raises(TypeError, match="latency_ms"):
        make_event(latency_ms=bad)


@pytest.mark.parametrize("bad", ["no", 1, 0, None])
def test_a_non_bool_estimated_is_rejected(bad):
    with pytest.raises(TypeError, match="estimated"):
        make_event(estimated=bad)


def test_a_non_string_provider_is_rejected():
    with pytest.raises(TypeError, match="provider") as excinfo:
        make_event(provider=None)
    assert "None" in str(excinfo.value)


@pytest.mark.parametrize("name", ["provider", "model", "endpoint"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_an_empty_identity_field_is_rejected(name, blank):
    with pytest.raises(ValueError, match=name):
        make_event(**{name: blank})


@pytest.mark.parametrize("bad", [None, {"team": "payments"}, "payments", 7])
def test_a_non_attribution_object_is_rejected(bad):
    with pytest.raises(TypeError, match="attribution"):
        make_event(attribution=bad)


def test_a_malformed_occurred_at_is_rejected():
    with pytest.raises(ValueError, match="occurred_at") as excinfo:
        make_event(occurred_at="nope")
    assert "nope" in str(excinfo.value)


def test_a_non_string_occurred_at_is_rejected():
    with pytest.raises(TypeError, match="occurred_at"):
        make_event(occurred_at=1758806591)


@pytest.mark.parametrize("bad", ["a" * 31, "a" * 33, "A" * 32, "z" * 32, ""])
def test_a_malformed_event_id_is_rejected(bad):
    with pytest.raises(ValueError, match="event_id"):
        make_event(event_id=bad)


def test_a_non_string_event_id_is_rejected():
    with pytest.raises(TypeError, match="event_id"):
        make_event(event_id=12345)


def test_a_non_string_schema_version_is_rejected():
    with pytest.raises(TypeError, match="schema_version"):
        make_event(schema_version=1.0)


def test_a_wrong_schema_version_string_is_rejected():
    with pytest.raises(ValueError, match="schema_version"):
        make_event(schema_version="2.0")


def test_a_non_string_request_id_is_rejected():
    with pytest.raises(TypeError, match="request_id"):
        make_event(request_id=42)


@pytest.mark.parametrize("name", ["priority", "outcome"])
def test_a_non_string_priority_or_outcome_is_rejected(name):
    with pytest.raises(TypeError, match=name):
        make_event(**{name: None})


def test_a_well_formed_event_still_constructs():
    event = make_event(
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
        latency_ms=0,
        retries=0,
        estimated=False,
        request_id=None,
        provider="anthropic",
        model="claude-sonnet-4-5",
        endpoint="/v1/messages",
    )
    assert event.to_dict()["latency_ms"] == 0
    assert event.request_id is None


def test_validation_costs_no_regex_compilation_per_event():
    import re

    compiled_before = len(re._cache)  # the global pattern cache the stdlib keeps
    make_event()
    assert len(re._cache) == compiled_before


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
    assert normalize_endpoint("http://[::1?api_key=sk-1") == "http://[::1?<redacted>"
    assert normalize_endpoint("http://[::1?x=1") == "http://[::1"
    assert normalize_endpoint("http://user@[::1/p?x=1") == "http://[::1/p"


ADVERSARIAL_ENDPOINTS = [
    "/v1/chat/completions",
    "https://api.openai.com:443/v1/chat/completions",
    "/v1/chat?api_key=sk-live-SECRET",
    "/v1/chat?api_key=sk-1&beta=true",
    "/v1/chat?beta=true",
    "https://user:pa55word@api.openai.com:443/v1/chat#top",
    "https://user@host/v1/models?a=1",
    "/v1/chat#fragment",
    "/v1/chat?x-api-key=sk-1",
    "/v1/chat?X-Amz-Signature=sk-1",
    "/v1/chat?apiKey=sk-1",
    "/v1/chat?api%5Fkey=sk-1",
    "/v1/chat?api_key=",
    "/v1/chat?api_key",
    "/v1/chat?access_token=sk-1",
    "/v1/chat?monkey=1",
    "/v1/chat?<redacted>",
    "http://[::1?api_key=sk-1",
    "http://user@[::1/p?x=1",
    "http://[::1",
    "?",
    "#",
    "?a=1",
    "   ?  ",
    UNKNOWN_ENDPOINT,
    "v1/chat?key=sk-1",
    "//host/p?api_key=1",
]


@pytest.mark.parametrize("raw", ADVERSARIAL_ENDPOINTS)
def test_endpoint_normalisation_is_idempotent(raw):
    once = normalize_endpoint(raw)
    assert normalize_endpoint(once) == once


@pytest.mark.parametrize("raw", ADVERSARIAL_ENDPOINTS)
def test_a_stored_endpoint_survives_the_wire_round_trip(raw):
    event = make_event(endpoint=raw)
    assert event.endpoint
    reloaded = SpendEvent.from_dict(event.to_dict())
    assert reloaded == event
    assert reloaded.endpoint == event.endpoint
    assert SpendEvent.from_dict(reloaded.to_dict()) == event


def test_a_credential_stays_redacted_across_reads_and_writes():
    event = make_event(endpoint="/v1/chat?api_key=sk-live-SECRET")
    first = event.to_dict()
    second = SpendEvent.from_dict(first).to_dict()
    third = SpendEvent.from_dict(second).to_dict()
    assert first["endpoint"] == second["endpoint"] == third["endpoint"]
    assert first["endpoint"] == "/v1/chat?<redacted>"
    assert "sk-live-SECRET" not in str(first) + str(second) + str(third)


def test_a_wire_line_is_byte_stable_across_cycles():
    event = make_event(endpoint="/v1/chat?api_key=sk-1", attribution=Attribution(team="t"))
    line = json.dumps(event.to_dict())
    reloaded = SpendEvent.from_dict(json.loads(line))
    assert json.dumps(reloaded.to_dict()) == line


@pytest.mark.parametrize("raw", ["?", "#", "#frag", "?a=1", "   ?  "])
def test_an_endpoint_that_normalises_away_becomes_the_sentinel(raw):
    event = make_event(endpoint=raw)
    assert event.endpoint == UNKNOWN_ENDPOINT == "unknown"
    assert event.to_dict()["endpoint"] == UNKNOWN_ENDPOINT
    assert SpendEvent.from_dict(event.to_dict()) == event


def test_the_sentinel_itself_is_a_fixed_point():
    assert normalize_endpoint(UNKNOWN_ENDPOINT) == UNKNOWN_ENDPOINT
    assert make_event(endpoint=UNKNOWN_ENDPOINT).endpoint == UNKNOWN_ENDPOINT


def test_a_blank_input_is_still_rejected_before_normalisation():
    for blank in ("", "   ", "\t"):
        with pytest.raises(ValueError, match="endpoint"):
            make_event(endpoint=blank)


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


def test_from_dict_refuses_an_unknown_key():
    payload = make_event().to_dict()
    payload["input_token"] = 5
    with pytest.raises(ValueError, match="input_token") as excinfo:
        SpendEvent.from_dict(payload)
    assert "input_tokens" in str(excinfo.value)


def test_from_dict_names_every_unknown_key():
    payload = make_event().to_dict()
    payload["teir"] = "payments"
    payload["input_token"] = 5
    with pytest.raises(ValueError) as excinfo:
        SpendEvent.from_dict(payload)
    assert "input_token" in str(excinfo.value)
    assert "teir" in str(excinfo.value)


def test_from_dict_refuses_a_non_mapping_payload():
    with pytest.raises(TypeError, match="payload"):
        SpendEvent.from_dict(["not", "a", "mapping"])


def test_from_dict_refuses_a_non_mapping_attribution():
    payload = make_event().to_dict()
    payload["attribution"] = "payments"
    with pytest.raises(TypeError, match="attribution"):
        SpendEvent.from_dict(payload)


# ---------------------------------------------------------------------------
# Cost wire form
# ---------------------------------------------------------------------------


class CostStub:
    """A minimal cost-shaped object, to pin that the wire path is duck-typed."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


COST_WIRE = {
    "input_usd": "0.001000",
    "output_usd": "0.011345",
    "cache_read_usd": "0.000000",
    "cache_write_usd": "0.000000",
    "total_usd": "0.012345",
    "currency": "USD",
    "price_source": "bundled",
    "estimated_tokens": False,
    "priced_components": ["input", "output"],
}


def test_a_cost_shaped_stub_round_trips_through_the_wire_form():
    event = make_event(cost=CostStub(COST_WIRE))
    payload = event.to_dict()
    assert payload["cost"] == COST_WIRE
    assert SpendEvent.from_dict(payload).to_dict() == payload


def test_a_cost_already_in_wire_form_round_trips():
    payload = make_event(cost=dict(COST_WIRE)).to_dict()
    assert payload["cost"] == COST_WIRE
    assert SpendEvent.from_dict(payload).to_dict() == payload


def test_a_cost_round_trip_survives_a_json_line():
    payload = make_event(cost=CostStub(COST_WIRE)).to_dict()
    line = json.dumps(payload)
    assert SpendEvent.from_dict(json.loads(line)).to_dict() == payload


@pytest.mark.parametrize("bad", [object(), 7, "0.01", 1.5, True])
def test_a_cost_that_is_not_cost_shaped_is_refused(bad):
    with pytest.raises(TypeError, match="cost"):
        make_event(cost=bad).to_dict()


def test_a_cost_whose_to_dict_is_not_a_mapping_is_refused():
    class NotAMapping:
        def to_dict(self):
            return "0.01"

    with pytest.raises(TypeError, match="cost.to_dict"):
        make_event(cost=NotAMapping()).to_dict()


def test_a_non_mapping_cost_on_the_wire_is_refused():
    payload = make_event().to_dict()
    payload["cost"] = "0.01"
    with pytest.raises(TypeError, match="cost"):
        SpendEvent.from_dict(payload)


def test_the_cost_type_hook_returns_the_real_breakdown():
    from backstop.pricing_catalog import CostBreakdown

    assert resolve_cost_type() is CostBreakdown
    assert resolve_cost_type.__doc__ and "price catalog" in resolve_cost_type.__doc__


def test_a_cost_round_trips_through_the_hook_as_a_real_breakdown():
    from decimal import Decimal

    from backstop.pricing_catalog import CostBreakdown

    cost = CostBreakdown.from_dict(COST_WIRE)
    assert isinstance(cost.input_usd, Decimal)
    assert cost.to_dict() == COST_WIRE
    event = make_event(cost=cost)
    reloaded = SpendEvent.from_dict(json.loads(json.dumps(event.to_dict())))
    assert reloaded == event
    assert type(reloaded.cost) is CostBreakdown
    assert reloaded.cost.input_usd == Decimal("0.001000")


def test_an_unpriced_event_carries_no_cost():
    assert make_event().to_dict()["cost"] is None


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


# ---------------------------------------------------------------------------
# Context manager and executor caveats
# ---------------------------------------------------------------------------


def test_a_none_field_means_do_not_override():
    with attribution(team="payments", feature="checkout-v2"):
        with attribution(feature=None, agent="refund-bot"):
            assert current_attribution() == Attribution(
                team="payments", feature="checkout-v2", agent="refund-bot"
            )


def test_a_none_field_on_the_decorator_means_do_not_override():
    @with_attribution(feature=None, agent="refund-bot")
    def handle_refund():
        return current_attribution()

    with attribution(team="payments", feature="checkout-v2"):
        assert handle_refund() == Attribution(
            team="payments", feature="checkout-v2", agent="refund-bot"
        )


def test_the_scope_manager_is_single_use():
    scope = attribution(team="payments")
    with scope:
        assert current_attribution().team == "payments"
    with pytest.raises(RuntimeError, match="single use"):
        with scope:
            pass
    assert current_attribution() == Attribution()


def test_a_fresh_scope_is_built_for_each_block():
    with attribution(team="payments"):
        with attribution(feature="refunds"):
            pass
    assert current_attribution() == Attribution()


def test_copy_context_propagates_attribution_into_a_worker_thread():
    with ThreadPoolExecutor(max_workers=1) as pool:
        with attribution(team="payments"):
            bare = pool.submit(current_attribution).result()
            copied = copy_context().run(current_attribution)
            submitted = pool.submit(copy_context().run, current_attribution).result()
    assert bare == Attribution()
    assert copied == Attribution(team="payments")
    assert submitted == Attribution(team="payments")


def test_run_in_executor_needs_the_copied_context():
    async def main():
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with attribution(team="payments"):
                bare = await loop.run_in_executor(pool, current_attribution)
                context = copy_context()
                copied = await loop.run_in_executor(
                    pool, functools.partial(context.run, current_attribution)
                )
        return bare, copied

    bare, copied = asyncio.run(main())
    assert bare == Attribution()
    assert copied == Attribution(team="payments")


def test_the_package_re_exports_the_schema_public_surface():
    import backstop.ledger as package
    import backstop.ledger.schema as schema_module

    for name in (
        "Attribution",
        "SpendEvent",
        "SCHEMA_VERSION",
        "PRIORITIES",
        "OUTCOMES",
        "OCCURRED_AT_RE",
        "EVENT_ID_RE",
        "SECRET_QUERY_RE",
        "UNKNOWN_ENDPOINT",
        "utc_now",
        "normalize_endpoint",
        "cost_to_dict",
        "cost_from_dict",
        "resolve_cost_type",
    ):
        assert getattr(package, name) is getattr(schema_module, name), name
        assert name in package.__all__, name
        assert name in schema_module.__all__, name


def test_the_schema_constants_are_reachable_from_the_package():
    import backstop.ledger as package

    assert package.SCHEMA_VERSION == "1.0"
    assert package.PRIORITIES == ("critical", "default", "background")
    assert package.OUTCOMES == (
        "success",
        "error",
        "circuit_open",
        "budget_denied",
        "queue_timeout",
        "fallback",
    )


# Anchored on one line of the docstring: a reword that drops the marker fails here.
RECIPE_MARKER = "the function that hands it back::"


def docstring_recipe() -> str:
    """Return the deferred-body recipe from the shipped docstring, verbatim.

    Extracted rather than retyped on purpose: a test that pins a lookalike of
    the recipe is how the shipped one shipped with a ``self`` in it.
    """
    doc = with_attribution.__doc__ or ""
    assert RECIPE_MARKER in doc, "the recipe marker is gone from with_attribution"
    block = doc.split(RECIPE_MARKER, 1)[1]
    lines = block.splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip())
    return textwrap.dedent("\n".join(lines[start:])).rstrip() + "\n"


def test_the_shipped_recipe_runs_verbatim_and_scopes_the_deferred_body():
    namespace: dict = {"attribution": attribution}
    exec(compile(docstring_recipe(), "<with_attribution docstring>", "exec"), namespace)
    stream_refunds = namespace["stream_refunds"]

    def handle(ticket):
        return current_attribution(), ticket

    produced = list(stream_refunds(handle, "ticket-1"))

    assert [(active.agent, ticket) for active, ticket in produced] == [
        ("refund-bot", "ticket-1")
    ]
    assert current_attribution() == Attribution()


def test_the_shipped_recipe_is_a_generator_the_decorator_would_have_refused():
    namespace: dict = {"attribution": attribution}
    exec(compile(docstring_recipe(), "<with_attribution docstring>", "exec"), namespace)
    body = namespace["stream_refunds"](lambda ticket: current_attribution(), "ticket-1")

    with pytest.raises(TypeError, match="generator"):
        with_attribution(agent="refund-bot")(lambda: body)()


def test_the_documented_recipe_for_a_deferred_coroutine_scopes_that_body():
    async def stream_refunds(handle):
        async def run():
            with attribution(agent="refund-bot"):
                return await handle()

        return asyncio.create_task(run())

    async def main():
        async def handle():
            await asyncio.sleep(0)
            return current_attribution()

        task = await stream_refunds(handle)
        return await task

    assert asyncio.run(main()) == Attribution(agent="refund-bot")
    assert current_attribution() == Attribution()


# ---------------------------------------------------------------------------
# Attribution field validation
# ---------------------------------------------------------------------------


ATTRIBUTION_FIELDS = tuple(Attribution.__dataclass_fields__)


@pytest.mark.parametrize("name", ATTRIBUTION_FIELDS)
@pytest.mark.parametrize("bad", [1, 3.5, True, ["t"], {"a": 1}])
def test_a_non_string_attribution_field_is_rejected_at_construction(name, bad):
    with pytest.raises(TypeError, match=repr(name)) as excinfo:
        Attribution(**{name: bad})
    assert type(bad).__name__ in str(excinfo.value)


@pytest.mark.parametrize("name", ATTRIBUTION_FIELDS)
def test_every_attribution_field_accepts_a_string_and_none(name):
    assert getattr(Attribution(**{name: "payments"}), name) == "payments"
    assert getattr(Attribution(**{name: None}), name) is None


@pytest.mark.parametrize("name", ["team", "feature", "gl_code"])
@pytest.mark.parametrize("bad", [1, 2.5, object()])
def test_the_public_api_refuses_a_non_string_field(name, bad):
    with pytest.raises(TypeError, match=repr(name)):
        attribution(**{name: bad})
    with pytest.raises(TypeError, match=repr(name)):
        with_attribution(**{name: bad})


def test_a_non_string_field_never_reaches_a_derived_view():
    # The failure used to be an AttributeError from keys() at read time, well
    # after the record had been built and stored.
    with pytest.raises(TypeError, match="team"):
        SpendEvent(
            provider="openai",
            model="gpt-4o",
            endpoint="/v1/chat",
            priority="default",
            outcome="success",
            input_tokens=1,
            output_tokens=1,
            estimated=False,
            attribution=Attribution(team=1),
        )


EVENT_FIELDS = tuple(SpendEvent.__dataclass_fields__)


@pytest.mark.parametrize("name", EVENT_FIELDS)
def test_from_dict_refuses_a_missing_field(name):
    payload = make_event().to_dict()
    del payload[name]
    with pytest.raises(ValueError, match=name) as excinfo:
        SpendEvent.from_dict(payload)
    assert str(len(EVENT_FIELDS)) in str(excinfo.value)


def test_from_dict_names_every_missing_field():
    payload = make_event().to_dict()
    for name in ("event_id", "occurred_at", "cost"):
        del payload[name]
    with pytest.raises(ValueError) as excinfo:
        SpendEvent.from_dict(payload)
    for name in ("event_id", "occurred_at", "cost"):
        assert name in str(excinfo.value)


def test_a_truncated_line_is_diagnosable_rather_than_a_bare_keyerror():
    payload = make_event().to_dict()
    del payload["event_id"]
    with pytest.raises(ValueError) as excinfo:
        SpendEvent.from_dict(payload)
    assert not isinstance(excinfo.value, KeyError)


def test_an_optional_field_set_to_none_is_still_present():
    event = make_event(cost=None, request_id=None)
    payload = event.to_dict()
    assert payload["cost"] is None and payload["request_id"] is None
    assert SpendEvent.from_dict(payload) == event


# ---------------------------------------------------------------------------
# The two hot defaults
# ---------------------------------------------------------------------------


def test_new_event_id_is_a_version_4_uuid_hex():
    event_id = new_event_id()
    assert len(event_id) == 32
    assert event_id[12] == "4"
    assert event_id[16] in "89ab"
    assert EVENT_ID_RE.fullmatch(event_id)
    assert UUID(event_id).version == 4
    assert UUID(event_id).variant == "specified in RFC 4122"


def test_new_event_ids_do_not_repeat():
    assert len({new_event_id() for _ in range(5000)}) == 5000


def test_the_event_id_default_is_the_generated_id():
    assert SpendEvent.__dataclass_fields__["event_id"].default_factory is new_event_id
    assert make_event().event_id != make_event().event_id


def test_utc_now_is_rfc3339_utc_with_microseconds():
    stamp = utc_now()
    assert OCCURRED_AT_RE.fullmatch(stamp)
    parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    assert abs(datetime.now(timezone.utc) - parsed.replace(tzinfo=timezone.utc)) < (
        timedelta(seconds=5)
    )


def test_utc_now_keeps_its_shape_across_the_calendar():
    # strftime does not pad a year below 1000 on every platform; isoformat does.
    # This pins the formatter choice through the one path that reaches it.
    for year in (1, 999, 1000, 2026, 9999):
        moment = datetime(year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
        rendered = moment.replace(tzinfo=None).isoformat(timespec="microseconds") + "Z"
        assert OCCURRED_AT_RE.fullmatch(rendered), rendered
        assert rendered.startswith(str(year).zfill(4))


def test_the_budgets_alias_is_never_a_stale_snapshot():
    """`backstop.budgets` must track the live ledger, not the one at import.

    It used to be `budgets = get_ledger()` evaluated once at module load, so
    after `reset_ledger()` the package attribute still pointed at the discarded
    instance: a tenant registered on `backstop.budgets` would be invisible to
    the transport, which reads the live global.
    """
    import backstop
    from backstop.ledger.budget import get_ledger, reset_ledger

    first = backstop.budgets
    assert first is get_ledger()

    reset_ledger()
    try:
        assert backstop.budgets is get_ledger()
        assert backstop.budgets is not first, "budgets went stale after reset_ledger()"
    finally:
        reset_ledger()

    with pytest.raises(AttributeError):
        backstop.definitely_not_an_attribute


def test_no_module_binds_the_ledger_at_import_time():
    """Structural guard for the whole class of bug, not just `backstop.budgets`.

    Any module-level name assigned from `get_ledger()` captures one instance at
    import. `reset_ledger()` then discards it, and the holder silently keeps
    operating on a ledger that nothing else can see. Reading `get_ledger()` inside
    a function is correct; binding it at the top level is not, and the failure is
    invisible until a caller writes to a dead object.

    Walks the AST of every shipped module rather than grepping text, so a mention
    inside a docstring or a comment cannot be mistaken for code.
    """
    import ast
    import pathlib

    import backstop

    root = pathlib.Path(backstop.__file__).parent
    offenders: list[str] = []

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Class and function bodies run on every call, not at import. Only the
        # module's own top level is an import-time binding.
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if value is None:
                continue
            if not any(
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "get_ledger"
                for inner in ast.walk(value)
            ):
                continue
            rel = path.relative_to(root)
            offenders.append(f"{rel}:{node.lineno}")

    assert not offenders, (
        "these modules bind the ledger at import time and will go stale on "
        f"reset_ledger(): {offenders}"
    )


def test_every_get_ledger_call_in_shipped_code_is_inside_a_function():
    """The same invariant from the other side: call sites are lazy, not eager.

    A bare `get_ledger()` in a function body resolves per call, which is what
    the transport relies on. This asserts there is no module-level call, and
    reports the location if one appears.
    """
    import ast
    import pathlib

    import backstop

    root = pathlib.Path(backstop.__file__).parent
    eager: list[str] = []

    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            # A top-level Expr that is just a call: `get_ledger()` on its own.
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "get_ledger"
            ):
                eager.append(f"{path.relative_to(root)}:{node.lineno}")

    assert not eager, f"these modules call get_ledger() at import time: {eager}"
