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
