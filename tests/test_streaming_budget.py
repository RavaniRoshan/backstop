"""Offline tests for streaming budget reconciliation.

A streamed request must reconcile to the actual usage reported in the SSE
body, NOT to the estimated output tokens. When the provider emits no usage
in the stream, the estimate is used as a fallback.

Also covers circuit-breaker bookkeeping for streams: a stream that sets up
cleanly must record an outcome, or a circuit left half-open by an earlier 503
stays half-open and rejects every later request forever.
"""
import httpx
import pytest

from backstop import BackstopConfig
from backstop.circuit import CircuitState
from backstop.state import BackstopState
from backstop.streaming import setup_streaming
from backstop.transports import AsyncBackstopTransport, BackstopTransport


def _circuit_config() -> BackstopConfig:
    """One 503 opens the circuit; zero cooldown, so the next request probes it."""
    return BackstopConfig(
        default_max_output_tokens=20,
        retry_max_attempts=1,
        circuit_min_requests=1,
        circuit_failure_threshold=1.0,
        circuit_cooldown_seconds=0.0,
    )


def _open_the_circuit(state: BackstopState) -> None:
    """Drive the circuit to OPEN through the non-streaming recording path."""
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(lambda r: httpx.Response(503))),
        base_url="https://mock.local",
    )
    assert client.post("/v1/chat/completions", json={"model": "x", "messages": []}).status_code == 503
    client.close()
    assert state.circuit.state is CircuitState.OPEN


def _sse_ok() -> httpx.Response:
    return httpx.Response(
        200, content=STREAM_NO_USAGE, headers={"content-type": "text/event-stream"}
    )


def test_successful_stream_releases_the_half_open_probe():
    state = BackstopState.create(50_000, _circuit_config())
    _open_the_circuit(state)

    # This stream is the half-open probe. It succeeds, so the circuit must close.
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(lambda r: _sse_ok())),
        base_url="https://mock.local",
    )
    streamed = client.post(
        "/v1/chat/completions", json={"model": "x", "messages": [], "stream": True}
    )
    assert streamed.status_code == 200
    streamed.close()

    assert state.circuit.state is CircuitState.CLOSED, (
        "a successful stream must close a half-open circuit, not leave the probe set"
    )

    # The observable symptom of the bug: the probe was never released, so every
    # later request was rejected with CircuitBreakerOpenError.
    later = client.post("/v1/chat/completions", json={"model": "x", "messages": []})
    assert later.status_code == 200
    client.close()


@pytest.mark.anyio
async def test_async_successful_stream_releases_the_half_open_probe():
    state = BackstopState.create(50_000, _circuit_config())
    _open_the_circuit(state)

    async with httpx.AsyncClient(
        transport=AsyncBackstopTransport(state, httpx.MockTransport(lambda r: _sse_ok())),
        base_url="https://mock.local",
    ) as client:
        streamed = await client.post(
            "/v1/chat/completions", json={"model": "x", "messages": [], "stream": True}
        )
        assert streamed.status_code == 200
        await streamed.aclose()

        assert state.circuit.state is CircuitState.CLOSED, (
            "a successful stream must close a half-open circuit, not leave the probe set"
        )

        later = await client.post("/v1/chat/completions", json={"model": "x", "messages": []})
        assert later.status_code == 200


def test_failed_stream_reopens_the_circuit():
    """A stream that comes back as an error records a failure for the probe."""
    state = BackstopState.create(50_000, _circuit_config())
    _open_the_circuit(state)

    client = httpx.Client(
        transport=BackstopTransport(
            state, httpx.MockTransport(lambda r: httpx.Response(503, content=b"nope"))
        ),
        base_url="https://mock.local",
    )
    failed = client.post(
        "/v1/chat/completions", json={"model": "x", "messages": [], "stream": True}
    )
    assert failed.status_code == 503
    failed.close()

    assert state.circuit.state is CircuitState.OPEN, (
        "a failed stream must fail the half-open probe instead of leaving it set"
    )
    client.close()


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


@pytest.mark.anyio
async def test_async_failed_stream_reopens_the_circuit():
    """A stream that comes back as an error records a failure for the probe."""
    state = BackstopState.create(50_000, _circuit_config())
    _open_the_circuit(state)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"nope")

    async with httpx.AsyncClient(
        transport=AsyncBackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    ) as client:
        failed = await client.post(
            "/v1/chat/completions", json={"model": "x", "messages": [], "stream": True}
        )
        assert failed.status_code == 503
        await failed.aclose()

        assert state.circuit.state is CircuitState.OPEN, (
            "a failed stream must fail the half-open probe instead of leaving it set"
        )


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
