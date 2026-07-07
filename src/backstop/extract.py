from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import BackstopConfig, Priority


@dataclass(frozen=True)
class RequestMetadata:
    priority: Priority
    estimated_tokens: int
    endpoint: str
    metadata: dict[str, Any] = field(default_factory=dict)


def request_metadata(request: httpx.Request, config: BackstopConfig) -> RequestMetadata:
    body = _json_body(request)
    endpoint = request.url.path
    return RequestMetadata(
        priority=Priority.from_header(request.headers.get("X-Backstop-Priority")),
        estimated_tokens=estimate_tokens(body, request.content, config, endpoint),
        endpoint=endpoint,
    )


def estimate_tokens(body: Any, raw: bytes, config: BackstopConfig, endpoint: str = "") -> int:
    if body is None:
        return max(1, int(len(raw) / (config.chars_per_token or 4.0)))

    if "/v1/messages" in endpoint and isinstance(body, Mapping):
        return _estimate_anthropic_tokens(body, raw, config)

    prompt_chars = _prompt_chars(body)
    output_tokens = _configured_output_tokens(body, config)
    body_floor = int(len(raw) / (config.chars_per_token or 4.0))

    model = body.get("model", "") if isinstance(body, Mapping) else ""
    if config.token_counter is not None:
        prompt_tokens = config.token_counter(str(body.get("messages", body)), model)
    else:
        prompt_tokens = int(prompt_chars / config.chars_per_token)

    return max(1, prompt_tokens + output_tokens, body_floor)


def _estimate_anthropic_tokens(body: dict, raw: bytes, config: BackstopConfig) -> int:
    messages = body.get("messages", [])
    prompt_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            prompt_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    prompt_chars += len(block.get("text", ""))

    system = body.get("system")
    if isinstance(system, str):
        prompt_chars += len(system)
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                prompt_chars += len(block.get("text", ""))

    output_tokens = body.get("max_tokens", config.default_max_output_tokens)

    prompt_tokens = int(prompt_chars / config.chars_per_token)
    body_floor = int(len(raw) / config.chars_per_token)
    return max(1, prompt_tokens + output_tokens, body_floor)


def response_usage_tokens(response: httpx.Response) -> int | None:
    try:
        payload = response.json()
    except Exception:
        return None
    usage = payload.get("usage") if isinstance(payload, Mapping) else None
    if not isinstance(usage, Mapping):
        return None

    for key in ("total_tokens", "total_token_count"):
        value = usage.get(key)
        if isinstance(value, int) and value >= 0:
            return value

    input_tokens = _int_or_zero(
        usage.get("input_tokens"),
        usage.get("prompt_tokens"),
        usage.get("prompt_token_count"),
    )
    output_tokens = _int_or_zero(
        usage.get("output_tokens"),
        usage.get("completion_tokens"),
        usage.get("completion_token_count"),
    )

    cache_creation = usage.get("cache_creation_input_tokens")
    cache_read = usage.get("cache_read_input_tokens")
    if isinstance(cache_creation, int) and cache_creation > 0:
        input_tokens = (input_tokens or 0) + cache_creation
    if isinstance(cache_read, int) and cache_read > 0:
        input_tokens = (input_tokens or 0) + cache_read

    if input_tokens is None and output_tokens is None:
        return None
    return (input_tokens or 0) + (output_tokens or 0)


def _json_body(request: httpx.Request) -> Any:
    if not request.content:
        return None
    content_type = request.headers.get("content-type", "")
    if "json" not in content_type and not request.content.strip().startswith((b"{", b"[")):
        return None
    try:
        return json.loads(request.content.decode("utf-8"))
    except Exception:
        return None


def _prompt_chars(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, (int, float, bool)):
        return len(str(value))
    if isinstance(value, Mapping):
        total = 0
        for key, item in value.items():
            if key in {"max_tokens", "max_output_tokens", "stream", "temperature", "top_p"}:
                continue
            if key in {"messages", "input", "prompt", "instructions", "content", "text"}:
                total += _prompt_chars(item)
            elif isinstance(item, (Mapping, Sequence)) and not isinstance(item, (str, bytes, bytearray)):
                total += _prompt_chars(item)
        return total
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sum(_prompt_chars(item) for item in value)
    return len(str(value))


def _configured_output_tokens(body: Any, config: BackstopConfig) -> int:
    if not isinstance(body, Mapping):
        return config.default_max_output_tokens
    for key in ("max_output_tokens", "max_tokens", "max_completion_tokens"):
        value = body.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    return config.default_max_output_tokens


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    try:
        import tiktoken
    except ImportError:
        return max(1, int(len(text) / 4.0))
    encoding_map = {
        "gpt-4o": "o200k_base",
        "gpt-4o-mini": "o200k_base",
        "gpt-4-turbo": "cl100k_base",
        "gpt-4": "cl100k_base",
        "gpt-3.5-turbo": "cl100k_base",
    }
    encoding_name = encoding_map.get(model, "cl100k_base")
    try:
        enc = tiktoken.get_encoding(encoding_name)
        return len(enc.encode(text))
    except Exception:
        return max(1, int(len(text) / 4.0))


def _int_or_zero(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int) and value >= 0:
            return value
    return None

