"""Semantic (near-duplicate) response caching.

The base ``ResponseCache`` already does exact-match caching. This module tests
the opt-in semantic layer: on an exact miss, the prompt embedding is compared
(cosine) against cached entries and a near-duplicate is short-circuited.
"""
from __future__ import annotations

import json

import httpx

from backstop.cache import ResponseCache
from backstop.config import BackstopConfig
from backstop.state import BackstopState
from backstop.transports import BackstopTransport


def _body(text: str, model: str = "m1") -> dict:
    return {"model": model, "messages": [{"role": "user", "content": text}]}


def test_exact_match_flagged_as_non_semantic() -> None:
    c = ResponseCache(max_entries=10, ttl=1000)
    b = _body("hello")
    c.set(b, b"resp", 7, None)
    content, usage, _headers, semantic = c.get(b)
    assert content == b"resp"
    assert usage == 7
    assert semantic is False


def test_semantic_hit_on_reformatted_near_duplicate() -> None:
    # A constant embedder makes every prompt a 1.0 cosine match.
    c = ResponseCache(max_entries=10, ttl=1000, embed=lambda t: [1.0, 0.0], similarity_threshold=0.95)
    c.set(_body("What is 2+2?"), b"four", 5, None)
    got = c.get(_body("what is 2 + 2 ?"))  # punctuation/whitespace only
    assert got is not None
    content, usage, _headers, semantic = got
    assert semantic is True
    assert content == b"four"


def test_semantic_miss_when_embeddings_differ() -> None:
    def embed(text: str) -> list[float]:
        return [1.0] if "apple" in text else [0.0]

    c = ResponseCache(max_entries=10, ttl=1000, embed=embed, similarity_threshold=0.95)
    c.set(_body("apple pie"), b"a", 1, None)
    assert c.get(_body("banana split")) is None


def test_semantic_below_threshold_is_miss() -> None:
    # cosine([1,0], [0.7,0.7]) ~= 0.707 < 0.95
    def embed(text: str) -> list[float]:
        return [1.0, 0.0] if "x" in text else [0.7, 0.7]

    c = ResponseCache(max_entries=10, ttl=1000, embed=embed, similarity_threshold=0.95)
    c.set(_body("xenon"), b"a", 1, None)
    assert c.get(_body("yellow")) is None


def test_no_semantic_lookup_without_embedder() -> None:
    c = ResponseCache(max_entries=10, ttl=1000)  # embedder omitted
    c.set(_body("hi"), b"a", 1, None)
    assert c.get(_body("HI")) is None  # exact miss, no semantic scan


def test_exact_match_wins_over_expired_semantic() -> None:
    # Make sure the exact path is still the fast path and not polluted.
    c = ResponseCache(max_entries=10, ttl=1000, embed=lambda t: [1.0, 0.0])
    b = _body("same")
    c.set(b, b"v1", 1, None)
    content, _usage, _h, semantic = c.get(b)
    assert content == b"v1"
    assert semantic is False


def test_transport_semantic_cache_short_circuits_near_duplicate() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            content=json.dumps(
                {"choices": [{"message": {"content": "pong"}}], "usage": {"total_tokens": 9}}
            ).encode(),
            headers={"content-type": "application/json"},
        )

    cfg = BackstopConfig(
        cache_enabled=True,
        cache_ttl=60,
        cache_semantic=True,
        cache_embedder=lambda t: [1.0, 0.0, 0.0],
        default_max_output_tokens=10,
    )
    state = BackstopState.create(1000, cfg)
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://example.local",
    )
    client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "PING"}]})
    # Near-duplicate (whitespace/punctuation only): exact miss, semantic hit.
    client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": " ping "}]})

    assert calls["n"] == 1, "near-duplicate should be served from the semantic cache"
    assert state.budget.spent == 9, "budget charged once, not twice"

