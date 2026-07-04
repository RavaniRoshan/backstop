import httpx
import pytest

from backstop.config import BackstopConfig, Priority
from backstop.extract import (
    _estimate_anthropic_tokens,
    estimate_tokens,
    request_metadata,
    response_usage_tokens,
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

