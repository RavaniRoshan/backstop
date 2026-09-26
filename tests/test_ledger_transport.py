"""The spend ledger on the transport hot path, sync and async.

The ledger's value proposition is that it is off by default and costs a boolean
test when off. Every test here is written from that side: a process that has not
opted in records nothing, opens nothing and blocks on nothing, and a process
that has opted in still cannot have a request fail, hang or slow down because of
where its events go.

The two transports are near-duplicates by design, so the assertions are written
once and run against both. A test that covers only the sync path would leave the
async path free to drift, which is the one way this feature could ship broken
without any test failing.
"""
from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from backstop import BackstopConfig
from backstop.circuit import CircuitState
from backstop.detection import DetectionConfig, RunawayDetector
from backstop.exceptions import BudgetExceededError
from backstop.ledger import (
    Attribution,
    BoundedWriter,
    JsonlSink,
    MemorySink,
    NullSink,
    SpendEvent,
    attribution,
)
from backstop.pricing_catalog import PriceCatalog
from backstop.state import BackstopState
from backstop.transports import AsyncBackstopTransport, BackstopTransport

OPENAI_BODY = {
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "hello"}],
    "max_tokens": 8,
}
OPENAI_RESPONSE = {
    "id": "chatcmpl-ledger-1",
    "object": "chat.completion",
    "model": "gpt-4o-2024-08-06",
    "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
}
ANTHROPIC_RESPONSE = {
    "id": "msg_ledger_1",
    "type": "message",
    "model": "claude-sonnet-4-5",
    "usage": {
        "input_tokens": 90,
        "output_tokens": 20,
        "cache_read_input_tokens": 400,
        "cache_creation_input_tokens": 0,
    },
}


def _ledger_config(**overrides) -> BackstopConfig:
    return BackstopConfig(
        default_max_output_tokens=8,
        retry_max_attempts=1,
        aimd_adjustment_interval=0,
        ledger_enabled=True,
        **overrides,
    )


def _state(config: BackstopConfig, budget: int = 1_000_000) -> BackstopState:
    return BackstopState.create(budget, config)


def _events(state: BackstopState) -> tuple[SpendEvent, ...]:
    """Drain the writer and read its sink's ring.

    ``close()`` joins the drain thread, so this is a real synchronisation point
    rather than a sleep: the ring is complete when it returns.
    """
    state.ledger.close()
    return tuple(getattr(state.ledger.sink, "events", ()))


def _handler(payload: dict, status: int = 200):
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handle


def _sync_client(state: BackstopState, handler) -> httpx.Client:
    return httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://api.openai.com",
    )


def _async_client(state: BackstopState, handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=AsyncBackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://api.openai.com",
    )


def _transport(state: BackstopState, handler) -> BackstopTransport:
    return BackstopTransport(state, httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# BackstopState.create: what the ledger is made of before any request arrives
# ---------------------------------------------------------------------------


def test_a_disabled_ledger_is_a_no_op_writer_over_a_null_sink():
    state = _state(BackstopConfig())
    assert isinstance(state.ledger, BoundedWriter)
    assert isinstance(state.ledger.sink, NullSink)
    # No catalog is built when nothing will ever ask for a price: the bundled
    # table is dozens of entries and a process that never bills anything should
    # not pay to index it.
    assert state.prices is None
    assert state.detector.config.enabled is False
    assert state.ledger_errors == 0


def test_an_enabled_ledger_without_a_path_keeps_a_bounded_memory_ring():
    state = _state(_ledger_config(ledger_memory_events=32))
    assert isinstance(state.ledger.sink, MemorySink)
    assert state.ledger.sink.maxlen == 32
    assert isinstance(state.prices, PriceCatalog)


def test_an_enabled_ledger_with_a_path_writes_ndjson(tmp_path):
    state = _state(_ledger_config(ledger_path=str(tmp_path / "nested" / "spend.jsonl")))
    assert isinstance(state.ledger.sink, JsonlSink)
    # Constructing a ledger touches no filesystem: the file opens on the first
    # write, so a bad path degrades the same way a bad write does.
    assert not (tmp_path / "nested").exists()


def test_a_user_price_catalog_replaces_the_bundled_rate(tmp_path):
    catalog = tmp_path / "prices.json"
    catalog.write_text(
        '{"entries": [{"model": "gpt-4o", "provider": "openai",'
        ' "input_per_mtok_usd": "1000.00", "output_per_mtok_usd": "2000.00",'
        ' "effective_from": "2026-01-01"}]}',
        encoding="utf-8",
    )
    state = _state(_ledger_config(price_catalog_path=str(catalog)))
    assert state.prices.resolve("openai", "gpt-4o").input_per_mtok_usd.as_tuple().exponent == -2
    assert str(state.prices.resolve("openai", "gpt-4o").input_per_mtok_usd) == "1000.00"


def test_the_detector_is_constructed_disabled_by_default_and_shadow_first():
    state = _state(BackstopConfig())
    assert isinstance(state.detector, RunawayDetector)
    assert state.detector.config.enabled is False
    # Shadow-first survives construction: turning a detector on must not turn
    # enforcement on with it.
    assert state.detector.shadow is True


def test_detection_enabled_builds_an_enabled_detector_still_in_shadow():
    state = _state(BackstopConfig(detection_enabled=True))
    assert state.detector.config == DetectionConfig(enabled=True, shadow=True)
    assert state.detector.shadow is True


# ---------------------------------------------------------------------------
# One event per completed non-streaming request
# ---------------------------------------------------------------------------


def test_one_event_carries_the_provider_model_tokens_endpoint_priority_and_outcome():
    state = _state(_ledger_config())
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        response = client.post(
            "/v1/chat/completions",
            headers={"X-Backstop-Priority": "background"},
            json=OPENAI_BODY,
        )
    assert response.status_code == 200
    (event,) = _events(state)
    assert event.provider == "openai"
    # The model the *response* reported, which is a real value and not the one
    # the caller asked for: a dated snapshot is what actually got billed.
    assert event.model == "gpt-4o-2024-08-06"
    assert event.input_tokens == 120
    assert event.output_tokens == 30
    assert event.endpoint == "https://api.openai.com/v1/chat/completions"
    assert event.priority == "background"
    assert event.outcome == "success"
    assert event.estimated is False
    assert event.retries == 0
    assert event.latency_ms >= 0.0
    assert event.request_id is None  # the mock sends no x-request-id


def test_the_event_is_priced_from_the_bundled_catalog():
    state = _state(_ledger_config())
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        client.post("/v1/chat/completions", json=OPENAI_BODY)
    (event,) = _events(state)
    assert event.cost is not None
    # 120 fresh input at gpt-4o's $2.50/Mtok, 30 output at $10/Mtok.
    assert str(event.cost.total_usd) == "0.000600"
    assert event.cost.currency == "USD"


def test_an_error_response_is_recorded_as_an_error_outcome():
    state = _state(_ledger_config())
    with _sync_client(state, _handler(OPENAI_RESPONSE, status=500)) as client:
        response = client.post("/v1/chat/completions", json=OPENAI_BODY)
    assert response.status_code == 500
    (event,) = _events(state)
    assert event.outcome == "error"


def test_anthropic_cache_tokens_are_kept_out_of_the_fresh_input():
    state = _state(_ledger_config())
    client = httpx.Client(
        transport=_transport(state, _handler(ANTHROPIC_RESPONSE)),
        base_url="https://api.anthropic.com",
    )
    with client:
        client.post("/v1/messages", json={"model": "claude-sonnet-4-5", "max_tokens": 8, "messages": []})
    (event,) = _events(state)
    assert event.provider == "anthropic"
    assert event.input_tokens == 90
    assert event.output_tokens == 20
    assert event.cache_read_tokens == 400
    assert event.cache_write_tokens == 0


def test_a_provider_the_host_does_not_identify_is_recorded_as_unknown():
    state = _state(_ledger_config())
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        client.post("/v1/chat/completions", json=OPENAI_BODY)
    (event,) = _events(state)
    assert event.provider == "openai"

    other = _state(_ledger_config())
    with httpx.Client(
        transport=_transport(other, _handler(OPENAI_RESPONSE)),
        base_url="https://llm.internal.corp",
    ) as client:
        client.post("/v1/chat/completions", json=OPENAI_BODY)
    (unidentified,) = _events(other)
    # A host Backstop does not recognise gets no invented provider. The event is
    # still recorded, unpriced, rather than being charged to whichever provider
    # somebody guessed.
    assert unidentified.provider == "unknown"
    assert unidentified.cost is None


def test_the_provider_request_id_is_recorded_when_the_response_carries_one():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=OPENAI_RESPONSE, headers={"x-request-id": "req_abc123"})

    state = _state(_ledger_config())
    with _sync_client(state, handle) as client:
        client.post("/v1/chat/completions", json=OPENAI_BODY)
    (event,) = _events(state)
    assert event.request_id == "req_abc123"


def test_a_model_absent_from_the_request_and_the_response_is_recorded_as_unknown():
    payload = {k: v for k, v in OPENAI_RESPONSE.items() if k != "model"}
    state = _state(_ledger_config())
    with _sync_client(state, _handler(payload)) as client:
        client.post("/v1/chat/completions", json={"messages": []})
    (event,) = _events(state)
    # Not a placeholder the caller chose: a SpendEvent cannot hold an empty
    # model, and "unknown" is the honest name for "we could not recover it".
    assert event.model == "unknown"
    assert event.cost is None


def test_no_event_is_recorded_for_a_request_denied_before_dispatch():
    state = _state(_ledger_config(), budget=1)
    sent = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=OPENAI_RESPONSE)

    with _sync_client(state, handle) as client:
        with pytest.raises(BudgetExceededError):
            client.post(
                "/v1/chat/completions",
                json={**OPENAI_BODY, "messages": [{"role": "user", "content": "x" * 4000}]},
            )
    assert sent == []
    # A denied request never reached a provider, so there is nothing to bill.
    # Recording one would put a zero-token row in a chargeback for work that
    # never happened.
    assert _events(state) == ()
    assert state.ledger.submitted == 0


def test_the_event_carries_the_ambient_attribution():
    state = _state(_ledger_config())
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        with attribution(team="payments", feature="checkout-v2"):
            client.post("/v1/chat/completions", json=OPENAI_BODY)
    (event,) = _events(state)
    assert event.attribution.team == "payments"
    assert event.attribution.feature == "checkout-v2"
    assert event.attribution == Attribution(team="payments", feature="checkout-v2")


def test_the_event_round_trips_through_the_ledger_wire_form(tmp_path):
    state = _state(_ledger_config(ledger_path=str(tmp_path / "spend.jsonl")))
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        with attribution(team="payments"):
            client.post("/v1/chat/completions", json=OPENAI_BODY)
    state.ledger.close()
    lines = (tmp_path / "spend.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert SpendEvent.from_dict(json.loads(lines[0])).attribution.team == "payments"


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


def test_a_streaming_request_is_recorded_once_at_stream_setup():
    state = _state(_ledger_config())
    sse = b'data: {"type":"content_block_delta","delta":{"text":"hi"}}\n\ndata: [DONE]\n\n'

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    with _sync_client(state, handle) as client:
        streamed = client.post("/v1/chat/completions", json={**OPENAI_BODY, "stream": True})
        assert streamed.status_code == 200
        streamed.close()
    (event,) = _events(state)
    assert event.outcome == "success"
    assert event.provider == "openai"
    # No usage block has been read at stream setup — the stream has not been
    # consumed — so the record says so rather than claiming a measurement.
    assert event.estimated is True
    assert event.input_tokens > 0
    assert event.model == "gpt-4o"


def test_a_failed_stream_is_recorded_as_an_error():
    state = _state(_ledger_config())

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "overloaded"})

    with _sync_client(state, handle) as client:
        client.post("/v1/chat/completions", json={**OPENAI_BODY, "stream": True})
    (event,) = _events(state)
    assert event.outcome == "error"


# ---------------------------------------------------------------------------
# The hot path must not block, must not raise, and must not touch a file
# ---------------------------------------------------------------------------


def test_a_stalled_sink_does_not_block_the_request():
    release = threading.Event()
    parked = threading.Event()

    class StalledSink:
        def write(self, event):
            parked.set()
            release.wait(timeout=5.0)

        def flush(self):
            pass

        def close(self):
            pass

    state = _state(_ledger_config())
    state.ledger = BoundedWriter(StalledSink())
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        started = time.perf_counter()
        response = client.post("/v1/chat/completions", json=OPENAI_BODY)
        elapsed_ms = (time.perf_counter() - started) * 1000
        # Wait until the drain thread really is inside the sink, so the test is
        # measuring a contended writer rather than one that had not started.
        assert parked.wait(timeout=5.0)
    release.set()
    assert response.status_code == 200
    assert elapsed_ms < 500.0, f"the request waited {elapsed_ms:.1f}ms on a stalled sink"


def test_a_sink_that_raises_never_breaks_the_request():
    class RaisingSink:
        def write(self, event):
            raise RuntimeError("the database is on fire")

        def flush(self):
            pass

        def close(self):
            pass

    state = _state(_ledger_config())
    state.ledger = BoundedWriter(RaisingSink())
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        response = client.post("/v1/chat/completions", json=OPENAI_BODY)
    assert response.status_code == 200
    report = state.ledger.close()
    assert report.submitted == 1
    assert report.sink_errors == 1
    assert report.written == 0
    # Counted, not raised and not silently lost.
    assert state.ledger_errors == 0


def test_a_ledger_failure_is_counted_and_never_reaches_the_caller():
    state = _state(_ledger_config())
    state.ledger = "not a writer at all"
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        response = client.post("/v1/chat/completions", json=OPENAI_BODY)
    assert response.status_code == 200
    assert state.ledger_errors == 1


def test_the_ledger_off_path_records_nothing_and_opens_no_file(monkeypatch):
    state = _state(BackstopConfig(default_max_output_tokens=8))
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        # One warm-up request first, so every lazy import has already happened
        # and arming the patch below cannot fail on an unrelated codec lookup.
        assert client.post("/v1/chat/completions", json=OPENAI_BODY).status_code == 200

        import builtins

        real_open = builtins.open

        def refuse(*args, **kwargs):
            raise AssertionError(f"the request path opened {args[0]!r}")

        monkeypatch.setattr(builtins, "open", refuse)
        assert client.post("/v1/chat/completions", json=OPENAI_BODY).status_code == 200
        monkeypatch.undo()

        assert builtins.open is real_open
    assert state.ledger.submitted == 0
    assert state.ledger.written == 0
    assert state.ledger.backlog == 0


def test_a_ledger_off_request_costs_nothing_worth_measuring():
    state = _state(BackstopConfig(default_max_output_tokens=8))
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        for _ in range(50):
            client.post("/v1/chat/completions", json=OPENAI_BODY)
        latencies = []
        for _ in range(600):
            started = time.perf_counter()
            client.post("/v1/chat/completions", json=OPENAI_BODY)
            latencies.append((time.perf_counter() - started) * 1000)
    latencies.sort()
    median = latencies[len(latencies) // 2]
    # The gate itself is one attribute load and a truth test, so the whole
    # request stays in the sub-millisecond class the library advertises. The
    # bound is deliberately ~20x the measured median so it catches a regression
    # that reintroduces real work (a file open, a network call) rather than
    # machine noise.
    assert median < 5.0, f"ledger-off median request took {median:.3f}ms"
    assert state.ledger.submitted == 0


# ---------------------------------------------------------------------------
# The detector
# ---------------------------------------------------------------------------


def test_the_detector_sees_every_event_that_is_submitted():
    state = _state(_ledger_config(detection_enabled=True))
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        with attribution(team="payments"):
            for _ in range(12):
                client.post("/v1/chat/completions", json=OPENAI_BODY)
    events = _events(state)
    assert len(events) == 12
    assert state.detector.window_len(Attribution(team="payments")) == 12
    assert state.detector.errors == 0


def test_a_shadow_detector_reports_but_never_blocks():
    # min_samples is 8 by default, so 12 same-key events are enough for the
    # detectors to be able to speak, and a shadow detector speaks by recording.
    state = _state(_ledger_config(detection_enabled=True))
    assert state.detector.config.shadow is True
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        with attribution(team="payments"):
            for _ in range(12):
                response = client.post("/v1/chat/completions", json=OPENAI_BODY)
                assert response.status_code == 200
    assert state.detector.recorded()
    assert all(s.key == "team=payments" for s in state.detector.recorded())


def test_a_disabled_detector_is_silent_and_is_never_consulted():
    state = _state(_ledger_config())
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        for _ in range(12):
            client.post("/v1/chat/completions", json=OPENAI_BODY)
    assert _events(state) != ()
    assert state.detector.recorded() == ()
    assert state.detector.key_count() == 0


# ---------------------------------------------------------------------------
# Async parity: the same assertions, not a subset
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_async_records_one_event_per_request_with_the_same_fields():
    state = _state(_ledger_config())
    async with _async_client(state, _handler(OPENAI_RESPONSE)) as client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"X-Backstop-Priority": "critical"},
            json=OPENAI_BODY,
        )
    assert response.status_code == 200
    (event,) = _events(state)
    assert event.provider == "openai"
    assert event.model == "gpt-4o-2024-08-06"
    assert (event.input_tokens, event.output_tokens) == (120, 30)
    assert event.endpoint == "https://api.openai.com/v1/chat/completions"
    assert event.priority == "critical"
    assert event.outcome == "success"
    assert str(event.cost.total_usd) == "0.000600"


@pytest.mark.anyio
async def test_async_records_nothing_for_a_request_denied_before_dispatch():
    state = _state(_ledger_config(), budget=1)
    async with _async_client(state, _handler(OPENAI_RESPONSE)) as client:
        with pytest.raises(BudgetExceededError):
            await client.post(
                "/v1/chat/completions",
                json={**OPENAI_BODY, "messages": [{"role": "user", "content": "x" * 4000}]},
            )
    assert _events(state) == ()


@pytest.mark.anyio
async def test_async_event_carries_the_ambient_attribution():
    state = _state(_ledger_config())
    async with _async_client(state, _handler(OPENAI_RESPONSE)) as client:
        with attribution(team="platform", feature="summariser"):
            await client.post("/v1/chat/completions", json=OPENAI_BODY)
    (event,) = _events(state)
    assert event.attribution.team == "platform"
    assert event.attribution.feature == "summariser"


@pytest.mark.anyio
async def test_async_records_a_streaming_request():
    sse = b'data: {"usage":{"input_tokens":5,"output_tokens":2}}\n\ndata: [DONE]\n\n'

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    state = _state(_ledger_config())
    async with _async_client(state, handle) as client:
        streamed = await client.post("/v1/chat/completions", json={**OPENAI_BODY, "stream": True})
        assert streamed.status_code == 200
        await streamed.aclose()
    (event,) = _events(state)
    assert event.outcome == "success"
    assert event.estimated is True


@pytest.mark.anyio
async def test_async_a_stalled_sink_does_not_block_the_request():
    release = threading.Event()
    parked = threading.Event()

    class StalledSink:
        def write(self, event):
            parked.set()
            release.wait(timeout=5.0)

        def flush(self):
            pass

        def close(self):
            pass

    state = _state(_ledger_config())
    state.ledger = BoundedWriter(StalledSink())
    async with _async_client(state, _handler(OPENAI_RESPONSE)) as client:
        started = time.perf_counter()
        response = await client.post("/v1/chat/completions", json=OPENAI_BODY)
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert await _wait_async(parked)
    release.set()
    assert response.status_code == 200
    assert elapsed_ms < 500.0, f"the request waited {elapsed_ms:.1f}ms on a stalled sink"


@pytest.mark.anyio
async def test_async_a_sink_that_raises_never_breaks_the_request():
    class RaisingSink:
        def write(self, event):
            raise RuntimeError("the database is on fire")

        def flush(self):
            pass

        def close(self):
            pass

    state = _state(_ledger_config())
    state.ledger = BoundedWriter(RaisingSink())
    async with _async_client(state, _handler(OPENAI_RESPONSE)) as client:
        response = await client.post("/v1/chat/completions", json=OPENAI_BODY)
    assert response.status_code == 200
    assert state.ledger.close().sink_errors == 1


@pytest.mark.anyio
async def test_async_ledger_off_path_records_nothing():
    state = _state(BackstopConfig(default_max_output_tokens=8))
    async with _async_client(state, _handler(OPENAI_RESPONSE)) as client:
        assert (await client.post("/v1/chat/completions", json=OPENAI_BODY)).status_code == 200
    assert state.ledger.submitted == 0


@pytest.mark.anyio
async def test_async_the_detector_sees_every_submitted_event():
    state = _state(_ledger_config(detection_enabled=True))
    async with _async_client(state, _handler(OPENAI_RESPONSE)) as client:
        with attribution(team="payments"):
            for _ in range(12):
                await client.post("/v1/chat/completions", json=OPENAI_BODY)
    assert len(_events(state)) == 12
    assert state.detector.window_len(Attribution(team="payments")) == 12


async def _wait_async(event: threading.Event) -> bool:
    """Wait for a threading.Event without blocking the event loop."""
    import anyio

    with anyio.move_on_after(5.0):
        while not event.is_set():
            await anyio.sleep(0.005)
    return event.is_set()
