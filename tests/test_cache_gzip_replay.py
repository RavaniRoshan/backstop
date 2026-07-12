"""Regression test: response cache must replay compressed (gzip) responses.

Providers (OpenAI, OpenCode Zen, etc.) send `Content-Encoding: gzip`. httpx
auto-decompresses on read, so `response.content` stored in the cache is plain
text. Replaying with the stale `Content-Encoding` header made httpx try to
decompress plain bytes again -> zlib error -> APIConnectionError. The fix strips
content-encoding/content-length/transfer-encoding on replay.

Reproduces the live failure seen against OpenCode Zen.
"""
from __future__ import annotations

import gzip
import json

import httpx
import pytest

from backstop.config import BackstopConfig
from backstop.state import BackstopState
from backstop.transports import BackstopTransport


def _gzip_response(body: dict) -> httpx.Response:
    raw = json.dumps(body).encode()
    return httpx.Response(
        200,
        content=gzip.compress(raw),
        headers={"content-type": "application/json", "content-encoding": "gzip"},
    )


def _make_client() -> tuple[httpx.Client, dict, BackstopState]:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _gzip_response(
            {
                "choices": [{"message": {"content": "pong"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            }
        )

    state = BackstopState.create(1000, BackstopConfig(cache_enabled=True, cache_ttl=60, default_max_output_tokens=50))
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://example.local",
    )
    return client, calls, state


def _post(client: httpx.Client) -> None:
    client.post(
        "/v1/chat/completions",
        json={"model": "deepseek-v4-flash-free", "messages": [{"role": "user", "content": "PING"}]},
    )


def test_cache_replays_gzip_response_without_decode_error():
    client, calls, state = _make_client()
    _post(client)  # live (mock) -> cached, decompressed
    _post(client)  # cache hit -> replayed; previously crashed with zlib error
    assert calls["n"] == 1, "second identical request should be served from cache"
    assert state.budget.spent == 10, "budget should be charged once, not twice"


def test_cache_replayed_body_is_parseable():
    client, calls, _ = _make_client()
    r1 = client.post(
        "/v1/chat/completions",
        json={"model": "deepseek-v4-flash-free", "messages": [{"role": "user", "content": "PING"}]},
    )
    r2 = client.post(
        "/v1/chat/completions",
        json={"model": "deepseek-v4-flash-free", "messages": [{"role": "user", "content": "PING"}]},
    )
    assert r1.json()["choices"][0]["message"]["content"] == "pong"
    assert r2.json()["choices"][0]["message"]["content"] == "pong"
