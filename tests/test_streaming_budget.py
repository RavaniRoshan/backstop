"""Offline tests for streaming budget reconciliation.

A streamed request must reconcile to the actual usage reported in the SSE
body, NOT to the estimated output tokens. When the provider emits no usage
in the stream, the estimate is used as a fallback.
"""
import httpx

from backstop import BackstopConfig
from backstop.state import BackstopState
from backstop.streaming import setup_streaming
from backstop.transports import BackstopTransport


class _LazyByteStream(httpx.SyncByteStream):
    """A non-buffered stream: delivery happens only as the caller iterates.

    This mirrors a real HTTP stream (unlike MockTransport, which pre-buffers
    the body into ``_content``), so it exercises the ``iter_raw`` accumulation
    path that the SDK uses when consuming SSE chunks.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    def __iter__(self):
        for chunk in self._chunks:
            yield chunk


def test_streaming_reconciles_via_iter_lines_non_buffered():
    """Real SDK-style consumption (iter_lines) on a lazy stream reconciles."""
    state = BackstopState.create(50_000, BackstopConfig(default_max_output_tokens=50))
    reservation = state.budget.reserve(50)
    response = httpx.Response(
        200,
        stream=_LazyByteStream([STREAM_WITH_USAGE]),
        headers={"content-type": "text/event-stream"},
    )
    setup_streaming(response, state, reservation, success=True)
    # Consume exactly like the OpenAI SDK does.
    for _ in response.iter_lines():
        pass
    response.close()

    assert state.budget.spent == 13, f"expected 13 actual, got {state.budget.spent}"


class _LazyAsyncByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk


def test_async_streaming_reconciles_via_aiter_lines_non_buffered():
    """Async SDK-style consumption (aiter_lines) on a lazy stream reconciles."""
    import asyncio

    from backstop.streaming import async_setup_streaming

    async def go() -> int:
        state = BackstopState.create(50_000, BackstopConfig(default_max_output_tokens=50))
        reservation = state.budget.reserve(50)
        response = httpx.Response(
            200,
            stream=_LazyAsyncByteStream([STREAM_WITH_USAGE]),
            headers={"content-type": "text/event-stream"},
        )
        await async_setup_streaming(response, state, reservation, success=True)
        async for _ in response.aiter_lines():
            pass
        await response.aclose()
        return state.budget.spent

    assert asyncio.run(go()) == 13, "expected 13 actual"



STREAM_WITH_USAGE = (
    b'data: {"id":"1","object":"chat.completion.chunk",'
    b'"choices":[{"delta":{"content":"hi"}}]}\n'
    b'\n'
    b'data: {"id":"2","object":"chat.completion.chunk",'
    b'"choices":[{"delta":{"content":"!"}}]}\n'
    b'\n'
    b'data: {"id":"3","object":"chat.completion.chunk","choices":[],'
    b'"usage":{"prompt_tokens":10,"completion_tokens":3,"total_tokens":13}}\n'
    b'\n'
    b'data: [DONE]\n'
)


STREAM_NO_USAGE = (
    b'data: {"id":"1","object":"chat.completion.chunk",'
    b'"choices":[{"delta":{"content":"hi"}}]}\n'
    b'\n'
    b'data: [DONE]\n'
)


def test_streaming_reconciles_to_actual_usage():
    """A streamed request with usage in body should be billed the real total."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            content=STREAM_WITH_USAGE,
            headers={"content-type": "text/event-stream"},
        )

    # Estimate: prompt_chars/4 + max_tokens(50) = ~50. Actual: 13. 
    state = BackstopState.create(50_000, BackstopConfig(default_max_output_tokens=50))
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )
    r = client.post(
        "/v1/chat/completions",
        json={"model": "x", "messages": [], "max_tokens": 50, "stream": True},
    )
    assert r.status_code == 200
    # Drain stream so the SSE body is fully parsed for usage
    _ = r.text
    r.close()
    client.close()

    assert calls["n"] == 1
    # Actual usage was 13 tokens, NOT the estimate (50). Streaming
    # previously over-billed streamed requests by the estimate.
    assert state.budget.spent == 13, f"expected 13 actual, got {state.budget.spent}"


def test_streaming_falls_back_to_estimate_when_provider_omits_usage():
    """If no usage appears in the stream, charge the estimate."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            content=STREAM_NO_USAGE,
            headers={"content-type": "text/event-stream"},
        )

    state = BackstopState.create(50_000, BackstopConfig(default_max_output_tokens=20))
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )
    r = client.post(
        "/v1/chat/completions",
        json={"model": "x", "messages": [], "max_tokens": 20, "stream": True},
    )
    _ = r.text
    r.close()
    client.close()

    assert calls["n"] == 1
    # No usage in stream: charged the reservation amount (estimate).
    assert state.budget.spent > 0
