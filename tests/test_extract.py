import httpx

from backstop.config import BackstopConfig, Priority
from backstop.extract import request_metadata, response_usage_tokens


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


def test_response_usage_fields():
    assert (
        response_usage_tokens(
            httpx.Response(200, json={"usage": {"prompt_tokens": 3, "completion_tokens": 4}})
        )
        == 7
    )
    assert response_usage_tokens(httpx.Response(200, json={"usage": {"total_tokens": 9}})) == 9
    assert response_usage_tokens(httpx.Response(200, json={"usage": {"bad": "value"}})) is None

