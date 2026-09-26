import httpx
import pytest

from backstop.config import BackstopConfig, Priority
from backstop.extract import (
    _estimate_anthropic_tokens,
    estimate_tokens,
    request_metadata,
    response_usage,
    response_usage_tokens,
    sse_usage,
)


def test_request_metadata_for_chat_completions():
    request = httpx.Request(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        headers={"X-Backstop-Priority": "background"},
        json={
            "messages": [{"role": "user", "content": "hello world"}],
            "max_tokens": 5,
        },
    )
    meta = request_metadata(request, BackstopConfig(default_max_output_tokens=100))
    assert meta.priority is Priority.BACKGROUND
    assert meta.estimated_tokens >= 7
    assert meta.endpoint == "/v1/chat/completions"


def test_request_metadata_for_responses_api():
    request = httpx.Request(
        "POST",
        "https://api.openai.com/v1/responses",
        json={"input": "hello", "instructions": "be brief", "max_output_tokens": 3},
    )
    meta = request_metadata(request, BackstopConfig())
    assert meta.priority is Priority.DEFAULT
    assert meta.estimated_tokens >= 5


def test_estimate_anthropic_tokens_simple():
    config = BackstopConfig(chars_per_token=4, default_max_output_tokens=100)
    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 10,
        "messages": [{"role": "user", "content": "hello world"}],
    }
    raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":10,"messages":[{"role":"user","content":"hello world"}]}'
    result = estimate_tokens(body, raw, config, endpoint="/v1/messages")
    assert result >= 13  # 11 chars / 4 + 10 output


def test_estimate_anthropic_tokens_with_system_prompt():
    config = BackstopConfig(chars_per_token=4, default_max_output_tokens=100)
    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 5,
        "system": "You are a helpful assistant.",
        "messages": [{"role": "user", "content": "hi"}],
    }
    raw = b"{}"
    result = estimate_tokens(body, raw, config, endpoint="/v1/messages")
    assert result == 12  # 30 chars / 4 + 5 output


def test_estimate_anthropic_tokens_with_content_blocks():
    config = BackstopConfig(chars_per_token=4, default_max_output_tokens=100)
    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 5,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hello world"}],
            }
        ],
    }
    raw = b"{}"
    result = estimate_tokens(body, raw, config, endpoint="/v1/messages")
    assert result == 7  # 11 chars / 4 + 5 output


def test_estimate_anthropic_tokens_falls_through_for_non_anthropic():
    """Non-Anthropic endpoint should not use Anthropic estimation."""
    config = BackstopConfig(chars_per_token=4)
    body = {"max_tokens": 5, "messages": [{"role": "user", "content": "hello"}]}
    raw = b"{}"
    result = estimate_tokens(body, raw, config, endpoint="/v1/chat/completions")
    assert result >= 6


def test_estimate_anthropic_tokens_called_directly():
    config = BackstopConfig(chars_per_token=4, default_max_output_tokens=100)
    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 10,
        "messages": [{"role": "user", "content": "test"}],
    }
    raw = b"{}"
    result = _estimate_anthropic_tokens(body, raw, config)
    assert result >= 11


def test_response_usage_fields():
    assert (
        response_usage_tokens(
            httpx.Response(200, json={"usage": {"prompt_tokens": 3, "completion_tokens": 4}})
        )
        == 7
    )
    assert response_usage_tokens(httpx.Response(200, json={"usage": {"total_tokens": 9}})) == 9
    assert response_usage_tokens(httpx.Response(200, json={"usage": {"bad": "value"}})) is None


def test_response_usage_anthropic_format():
    result = response_usage_tokens(
        httpx.Response(
            200,
            json={
                "usage": {
                    "input_tokens": 2095,
                    "output_tokens": 503,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                }
            },
        )
    )
    assert result == 2598


def test_response_usage_anthropic_with_cache_tokens():
    result = response_usage_tokens(
        httpx.Response(
            200,
            json={
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 200,
                    "cache_read_input_tokens": 0,
                }
            },
        )
    )
    assert result == 350


def test_response_usage_anthropic_cache_read():
    result = response_usage_tokens(
        httpx.Response(
            200,
            json={
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 30,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 1000,
                }
            },
        )
    )
    assert result == 1080


# --- The split read the spend ledger needs -------------------------------
#
# ``response_usage_tokens`` above is the reconciliation number and its behaviour
# is pinned by the tests above. These tests pin the *split* the ledger bills
# from, and the rule that the split is a measurement of the parts while the
# total stays a measurement of the sum.


def test_response_usage_splits_openai_prompt_and_completion_tokens():
    usage = response_usage(
        httpx.Response(
            200,
            json={
                "model": "gpt-4o",
                "usage": {"prompt_tokens": 1234, "completion_tokens": 567, "total_tokens": 1801},
            },
        )
    )
    # OpenAI publishes an aggregate alongside the split, and the aggregate wins
    # for ``total`` — the same precedence the total-only reader has always had.
    assert usage.total == 1801
    assert usage.input_tokens == 1234
    assert usage.output_tokens == 567
    assert usage.model == "gpt-4o"
    assert usage.split is True


def test_response_usage_keeps_cache_tokens_out_of_the_fresh_input():
    usage = response_usage(
        httpx.Response(
            200,
            json={
                "model": "claude-sonnet-4-5",
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 30,
                    "cache_creation_input_tokens": 200,
                    "cache_read_input_tokens": 1000,
                },
            },
        )
    )
    # Anthropic counts cache on top of ``input_tokens`` and a price card charges
    # a cached read at a fraction of a fresh input, so folding them into one
    # number would overstate fresh tokens and lose the cheaper rate.
    assert usage.input_tokens == 50
    assert usage.output_tokens == 30
    assert usage.cache_read_tokens == 1000
    assert usage.cache_write_tokens == 200
    # ...while the reconciled total still counts them, as it always has.
    assert usage.total == 1280


def test_response_usage_marks_an_aggregate_only_report_as_not_split():
    # Gemini-style bodies publish a total and no parts. The split flag is what
    # stops a caller inventing one.
    usage = response_usage(httpx.Response(200, json={"usage": {"total_token_count": 90}}))
    assert usage.total == 90
    assert usage.split is False
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


# --- The two cache conventions ----------------------------------------------
#
# Anthropic counts cached tokens *in addition to* its ``input_tokens``; OpenAI
# counts them *inside* its prompt count and nests the cached figure. Both are
# real response shapes, and a test that only carries one of them cannot catch a
# reader that got the other wrong — which is the bug this pair exists to pin.

#: A real ``/v1/chat/completions`` body with prompt caching. The numbers are the
#: reviewer's reproduction: 1,234,567 prompt tokens of which 400,000 were served
#: from the cache.
OPENAI_CACHED_RESPONSE = {
    "id": "chatcmpl-cache-1",
    "object": "chat.completion",
    "model": "gpt-4o-2024-08-06",
    "usage": {
        "prompt_tokens": 1_234_567,
        "completion_tokens": 500,
        "total_tokens": 1_235_067,
        "prompt_tokens_details": {"cached_tokens": 400_000, "audio_tokens": 0},
    },
}

#: The same thing on ``/v1/responses``, where the inclusive count is *named*
#: ``input_tokens`` — the name Anthropic uses for the opposite convention.
OPENAI_RESPONSES_CACHED_RESPONSE = {
    "id": "resp-cache-1",
    "object": "response",
    "model": "gpt-4o-2024-08-06",
    "usage": {
        "input_tokens": 1_234_567,
        "input_tokens_details": {"cached_tokens": 400_000},
        "output_tokens": 500,
        "total_tokens": 1_235_067,
    },
}

#: A real ``/v1/messages`` body, where ``input_tokens`` is the fresh count and
#: the cache counts are published beside it.
ANTHROPIC_CACHED_RESPONSE = {
    "id": "msg_cache_1",
    "type": "message",
    "model": "claude-sonnet-4-5",
    "usage": {
        "input_tokens": 1_234_567,
        "output_tokens": 500,
        "cache_creation_input_tokens": 7_000,
        "cache_read_input_tokens": 400_000,
    },
}


def test_openai_cached_prompt_tokens_are_taken_out_of_the_fresh_input():
    usage = response_usage(httpx.Response(200, json=OPENAI_CACHED_RESPONSE))
    # OpenAI's prompt_tokens INCLUDES the 400,000 cached tokens, so the fresh
    # count is the difference. Billing prompt_tokens as the input would charge
    # 400,000 tokens at the full input rate that the provider gave at the
    # cache-read rate — an overcharge, on the most common caching shape there is.
    assert usage.input_tokens == 834_567
    assert usage.cache_read_tokens == 400_000
    assert usage.output_tokens == 500
    assert usage.cache_write_tokens == 0
    # OpenAI publishes no cache-write count, and the absence is a zero rather
    # than an invented one.
    assert usage.split is True, "the cached count is a measurement, not a guess"
    # The parts sum to the aggregate the provider published beside them.
    assert usage.total == 1_235_067
    assert usage.input_tokens + usage.output_tokens + usage.cache_read_tokens == usage.total


def test_openai_responses_api_cached_tokens_are_read_under_their_own_name():
    usage = response_usage(httpx.Response(200, json=OPENAI_RESPONSES_CACHED_RESPONSE))
    # Same numbers, same split: the Responses API nests the count under
    # ``input_tokens_details`` and names the inclusive count ``input_tokens``, the
    # very name Anthropic uses for the *exclusive* count. The reader takes the
    # convention from the nesting, not from the name.
    assert usage.input_tokens == 834_567
    assert usage.cache_read_tokens == 400_000
    assert usage.output_tokens == 500
    assert usage.total == 1_235_067


def test_anthropic_cache_tokens_stay_additive_to_its_fresh_input():
    usage = response_usage(httpx.Response(200, json=ANTHROPIC_CACHED_RESPONSE))
    # The opposite convention: Anthropic's input_tokens already excludes the
    # cached tokens, so subtracting here would bill a fraction of them twice and
    # drop 400,000 tokens out of the reservation on the way past.
    assert usage.input_tokens == 1_234_567
    assert usage.cache_read_tokens == 400_000
    assert usage.cache_write_tokens == 7_000
    assert usage.output_tokens == 500
    assert usage.split is True
    # No aggregate is published, so the total is the sum of the parts — and it is
    # the same magnitude either convention produces, which is what keeps
    # ``response_usage_tokens`` unchanged.
    assert usage.total == 1_642_067
    assert (
        usage.input_tokens
        + usage.output_tokens
        + usage.cache_read_tokens
        + usage.cache_write_tokens
        == usage.total
    )


def test_a_cached_count_larger_than_its_prompt_is_recorded_not_clamped():
    # A body no provider sends: the nested count is bigger than the prompt count
    # it claims to be part of. The reader must not clamp the remainder to zero —
    # a silently clamped count is the class of bug this normalisation fixes — and
    # must not hide the cached count either.
    usage = response_usage(
        httpx.Response(
            200,
            json={
                "model": "gpt-4o",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 5,
                    "prompt_tokens_details": {"cached_tokens": 150},
                },
            },
        )
    )
    assert usage.input_tokens == -50, "the provider's numbers, not a repaired split"
    assert usage.cache_read_tokens == 150
    # The parts still sum to what the provider said, so the reconciled total is
    # unaffected by an impossible split.
    assert usage.total == 105


def test_the_impossible_split_is_refused_by_the_event_schema_rather_than_billed():
    # Recorded faithfully above; refused here, loudly. SpendEvent refuses a
    # negative token count by name, and ``_record_spend`` counts that as a ledger
    # error, so a provider body that does not add up shows up on a counter
    # instead of becoming a plausible price.
    from backstop.ledger import Attribution, SpendEvent

    usage = response_usage(
        httpx.Response(
            200,
            json={"usage": {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 150}}},
        )
    )
    with pytest.raises(ValueError, match="input_tokens must be >= 0"):
        SpendEvent(
            provider="openai",
            model="gpt-4o",
            endpoint="/v1/chat/completions",
            priority="default",
            outcome="success",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            estimated=False,
            attribution=Attribution(),
        )


def test_a_nested_detail_with_no_usable_count_is_read_as_no_cache_detail():
    # A body that nests something which is not a count says nothing about
    # caching, and is treated as the plain shape it looks like rather than as
    # an error or as a fabricated zero-with-a-reason.
    for details in ({}, {"cached_tokens": "many"}, {"cached_tokens": True}, {"cached_tokens": -1}, "nope"):
        usage = response_usage(
            httpx.Response(
                200,
                json={"usage": {"prompt_tokens": 90, "completion_tokens": 5, "prompt_tokens_details": details}},
            )
        )
        assert (usage.input_tokens, usage.cache_read_tokens) == (90, 0), details
        assert usage.split is True


def test_an_explicit_zero_cached_count_leaves_the_prompt_untouched():
    usage = response_usage(
        httpx.Response(
            200,
            json={
                "usage": {
                    "prompt_tokens": 90,
                    "completion_tokens": 5,
                    "prompt_tokens_details": {"cached_tokens": 0},
                }
            },
        )
    )
    assert (usage.input_tokens, usage.cache_read_tokens) == (90, 0)
    assert usage.total == 95


def test_response_usage_total_agrees_with_the_total_only_reader():
    bodies = [
        {"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        {"usage": {"input_tokens": 10, "output_tokens": 5}},
        {"usage": {"total_tokens": 42}},
        {"usage": {}},
        {"model": "x", "no_usage_here": True},
    ]
    for body in bodies:
        response = httpx.Response(200, json=body)
        usage = response_usage(response)
        assert response_usage_tokens(response) == (None if usage is None else usage.total)


def test_response_usage_returns_none_when_the_provider_said_nothing():
    assert response_usage(httpx.Response(200, json={"ok": True})) is None
    assert response_usage(httpx.Response(200, content=b"not json at all")) is None


def test_response_usage_reads_the_usage_out_of_sse_text():
    text = (
        'data: {"type":"message_start","message":{"model":"claude-sonnet-4-5"}}\n\n'
        'data: {"type":"content_block_delta","delta":{"text":"hi"}}\n\n'
        'data: {"type":"message_delta","usage":{"input_tokens":11,"output_tokens":7}}\n\n'
        "data: [DONE]\n\n"
    )
    usage = sse_usage(text)
    assert (usage.input_tokens, usage.output_tokens, usage.total) == (11, 7, 18)
    # Anthropic names the model in a nested message_start object, not on the
    # usage chunk. The reader does not go looking for it, and says so by
    # reporting None rather than by inventing one.
    assert usage.model is None


def test_sse_usage_reports_a_model_the_usage_chunk_carries_itself():
    text = (
        'data: {"model":"gpt-4o","usage":{"prompt_tokens":4,"completion_tokens":2}}\n\n'
        "data: [DONE]\n\n"
    )
    assert sse_usage(text).model == "gpt-4o"


def test_sse_usage_without_a_usage_block_is_none():
    assert sse_usage("data: {\"delta\":{\"text\":\"hi\"}}\n\ndata: [DONE]\n") is None
    assert sse_usage("no sse here") is None


def test_response_usage_refuses_a_boolean_where_a_token_count_belongs():
    # bool is an int, and SpendEvent refuses a bool by name; the reader must not
    # hand one down.
    usage = response_usage(httpx.Response(200, json={"usage": {"total_tokens": True}}))
    assert usage is None
