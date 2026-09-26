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
from backstop.exceptions import BudgetExceededError, CircuitBreakerOpenError
from backstop.ledger import (
    EMITTED_OUTCOMES,
    OUTCOMES,
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


# --- Cached prompt tokens, priced -------------------------------------------
#
# The two providers publish their cached-prompt count in shapes that need
# opposite arithmetic, and the difference is money: a cached read is a fraction
# of a fresh input on every rate card here. These two tests are the pair — the
# OpenAI figure is inside its prompt count and the Anthropic figure is beside
# its input count — so a reader that applied either convention to both would
# fail one of them.

#: A real ``/v1/chat/completions`` body with prompt caching, on the model the
#: other transport tests already use.
OPENAI_CACHED_RESPONSE = {
    "id": "chatcmpl-ledger-cache",
    "object": "chat.completion",
    "model": "gpt-4o-2024-08-06",
    "usage": {
        "prompt_tokens": 1_234_567,
        "completion_tokens": 500,
        "total_tokens": 1_235_067,
        "prompt_tokens_details": {"cached_tokens": 400_000, "audio_tokens": 0},
    },
}

#: A real ``/v1/messages`` body carrying the same magnitudes, where the cached
#: count is published *beside* the input count rather than inside it.
ANTHROPIC_CACHED_RESPONSE = {
    "id": "msg_ledger_cache",
    "type": "message",
    "model": "claude-sonnet-4-5",
    "usage": {
        "input_tokens": 1_234_567,
        "output_tokens": 500,
        "cache_creation_input_tokens": 7_000,
        "cache_read_input_tokens": 400_000,
    },
}


def test_openai_cached_prompt_tokens_are_charged_at_the_cache_read_rate():
    """The undercharge this pins: 400,000 cached tokens billed as fresh input.

    gpt-4o charges $2.50/Mtok for a fresh input and $1.25/Mtok for a cached
    read. OpenAI's ``prompt_tokens`` already includes the cached ones, so
    charging it whole bills 400,000 tokens at the full rate — 3.091418 instead
    of 2.591418, a 14.3% overcharge, with ``estimated`` still false and
    ``unpriced_components`` empty, because nothing about the event looks wrong.
    """
    state = _state(_ledger_config())
    with _sync_client(state, _handler(OPENAI_CACHED_RESPONSE)) as client:
        response = client.post("/v1/chat/completions", json=OPENAI_BODY)
    assert response.status_code == 200
    assert state.ledger_errors == 0

    (event,) = _events(state)
    assert (event.input_tokens, event.output_tokens) == (834_567, 500)
    assert event.cache_read_tokens == 400_000
    # A measurement, not an estimate: the provider published the cached count.
    assert event.estimated is False

    assert event.cost is not None
    # 834,567 fresh at $2.50/Mtok, 400,000 cached at $1.25/Mtok, 500 output at
    # $10.00/Mtok.
    assert str(event.cost.input_usd) == "2.086418"
    assert str(event.cost.cache_read_usd) == "0.500000"
    assert str(event.cost.output_usd) == "0.005000"
    assert str(event.cost.total_usd) == "2.591418"
    # The cache-read rate exists for this model, so the export's "what I could
    # not measure" column has nothing to report — and now that is true.
    assert event.cost.priced_components == {"input", "output", "cache_read"}


def test_anthropic_cached_tokens_are_priced_off_the_additive_counts():
    """The other convention, unchanged: the same magnitudes, opposite arithmetic.

    Anthropic's ``input_tokens`` already excludes the cached tokens, so the
    fresh count is 1,234,567 and not 834,567. Getting this wrong in the other
    direction would bill 400,000 tokens at the cache-read rate *and* drop them
    out of the fresh input, under-reporting the request twice.
    """
    state = _state(_ledger_config())
    client = httpx.Client(
        transport=_transport(state, _handler(ANTHROPIC_CACHED_RESPONSE)),
        base_url="https://api.anthropic.com",
    )
    with client:
        response = client.post(
            "/v1/messages",
            json={"model": "claude-sonnet-4-5", "max_tokens": 8, "messages": []},
        )
    assert response.status_code == 200
    (event,) = _events(state)
    assert (event.input_tokens, event.output_tokens) == (1_234_567, 500)
    assert (event.cache_read_tokens, event.cache_write_tokens) == (400_000, 7_000)
    assert event.estimated is False

    assert event.cost is not None
    # claude-sonnet-4-5: $3.00/Mtok in, $15.00/Mtok out, $0.30 cached read,
    # $3.75 cached write.
    assert str(event.cost.input_usd) == "3.703701"
    assert str(event.cost.cache_read_usd) == "0.120000"
    assert str(event.cost.cache_write_usd) == "0.026250"
    assert str(event.cost.output_usd) == "0.007500"
    assert str(event.cost.total_usd) == "3.857451"
    assert event.cost.priced_components == {
        "input",
        "output",
        "cache_read",
        "cache_write",
    }


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


def test_a_host_process_decimal_precision_does_not_void_the_ledger(monkeypatch):
    """The reproduction: ``prec=6`` in the host app, before Backstop is imported.

    A ``decimal`` context is process-global, and the cost arithmetic used to run
    in whatever context it found. The request still returned 200 — the ledger is
    never allowed to fail a request — and ``compute_cost`` raised
    ``InvalidOperation`` on every event, so ``state.ledger_errors`` climbed once
    per request and **no events were recorded at all**: a permanently empty
    ledger with no explanation and no wrong money. That is the whole symptom, and
    the counters are the only place it was ever going to show up.
    """
    import decimal

    monkeypatch.setattr(decimal.getcontext(), "prec", 6)
    state = _state(_ledger_config())
    with _sync_client(state, _handler(OPENAI_CACHED_RESPONSE)) as client:
        response = client.post("/v1/chat/completions", json=OPENAI_BODY)

    assert response.status_code == 200
    assert state.ledger_errors == 0, "the request path raised inside the ledger"
    (event,) = _events(state)
    assert event.cost is not None
    assert str(event.cost.total_usd) == "2.591418", "the same figure as any other context"


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


# ---------------------------------------------------------------------------
# The gauge must describe the tenant the request was actually billed against
# ---------------------------------------------------------------------------


@pytest.fixture
def recorded_metrics():
    """Capture every ``Metrics.call`` this process makes, and restore after."""
    from backstop.metrics import set_telemetry_sink

    calls: list[tuple] = []
    set_telemetry_sink(lambda name, args, method, kwargs: calls.append((name, args, method, kwargs)))
    try:
        yield calls
    finally:
        set_telemetry_sink(None)


def _budget_remaining_values(calls) -> list[float]:
    return [
        kwargs["value"]
        for name, _args, method, kwargs in calls
        if name == "budget_remaining" and method == "set"
    ]


def test_the_budget_gauge_reports_the_virtual_key_tenant_not_the_global(
    recorded_metrics,
):
    from backstop.ledger import TenantBudget, get_current_tenant, get_ledger, reset_ledger

    reset_ledger()
    try:
        get_ledger().register({"acme": TenantBudget(tenant_id="acme", limit_tokens=1_000)})
        state = _state(
            BackstopConfig(
                default_max_output_tokens=8,
                virtual_keys={"sk-acme": "acme"},
            ),
            budget=5_000,
        )
        with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
            response = client.post(
                "/v1/chat/completions",
                headers={"X-Backstop-Key": "sk-acme"},
                json=OPENAI_BODY,
            )
        assert response.status_code == 200
        # The tenant came from the header, not the context: nothing set a tenant
        # ContextVar, which is the whole point of the virtual-key path.
        assert get_current_tenant() is None

        tenant_remaining = get_ledger().get("acme").remaining
        reported = _budget_remaining_values(recorded_metrics)
        assert reported, "the budget_remaining gauge was never published"
        # The gauge is published twice per request — on admission and again on
        # release — so the last one is the settled figure.
        assert reported[-1] == tenant_remaining
        # Reporting the global budget here is the bug this pins: a plausible
        # number about a budget this request never spent. The tenant's cap is
        # 1,000 and the global one is 5,000, so a global-sized figure is
        # unmistakable.
        assert max(reported) <= 1_000
        assert tenant_remaining < state.budget.remaining
    finally:
        reset_ledger()


def test_the_budget_gauge_reports_the_global_budget_with_no_tenant(recorded_metrics):
    state = _state(BackstopConfig(default_max_output_tokens=8), budget=5_000)
    with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
        client.post("/v1/chat/completions", json=OPENAI_BODY)
    reported = _budget_remaining_values(recorded_metrics)
    assert reported, "the budget_remaining gauge was never published"
    # No tenant resolved, so the global budget is still the right answer — this
    # guards the fix against breaking the case it was not aimed at.
    assert reported[-1] == state.budget.remaining


@pytest.mark.anyio
async def test_async_the_budget_gauge_reports_the_virtual_key_tenant_not_the_global(
    recorded_metrics,
):
    from backstop.ledger import TenantBudget, get_current_tenant, get_ledger, reset_ledger

    reset_ledger()
    try:
        get_ledger().register({"acme": TenantBudget(tenant_id="acme", limit_tokens=1_000)})
        state = _state(
            BackstopConfig(
                default_max_output_tokens=8,
                virtual_keys={"sk-acme": "acme"},
            ),
            budget=5_000,
        )
        async with _async_client(state, _handler(OPENAI_RESPONSE)) as client:
            response = await client.post(
                "/v1/chat/completions",
                headers={"X-Backstop-Key": "sk-acme"},
                json=OPENAI_BODY,
            )
        assert response.status_code == 200
        assert get_current_tenant() is None
        tenant_remaining = get_ledger().get("acme").remaining
        reported = _budget_remaining_values(recorded_metrics)
        assert reported[-1] == tenant_remaining
        assert max(reported) <= 1_000
        assert tenant_remaining < state.budget.remaining
    finally:
        reset_ledger()


# ---------------------------------------------------------------------------
# A fallback that succeeded is a request that cost money
# ---------------------------------------------------------------------------


def _fallback_config(**overrides) -> BackstopConfig:
    return BackstopConfig(
        default_max_output_tokens=8,
        retry_max_attempts=1,
        aimd_adjustment_interval=0,
        circuit_min_requests=1,
        circuit_failure_threshold=1.0,
        circuit_cooldown_seconds=60.0,
        **overrides,
    )


def test_a_successful_fallback_is_billed_as_its_own_fallback_event():
    # One 503 opens the circuit; the cooldown keeps it open, so the next request
    # must take the fallback chain.
    state = _state(_fallback_config(ledger_enabled=True, fallback_model="gpt-4o-mini"))
    with _sync_client(state, _handler(OPENAI_RESPONSE, status=503)) as client:
        assert client.post("/v1/chat/completions", json=OPENAI_BODY).status_code == 503
    assert state.circuit.state is CircuitState.OPEN

    def fallback_handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["model"] == "gpt-4o-mini"
        return httpx.Response(200, json={**OPENAI_RESPONSE, "model": "gpt-4o-mini"})

    with _sync_client(state, fallback_handler) as client:
        response = client.post("/v1/chat/completions", json=OPENAI_BODY)
    assert response.status_code == 200
    # The 503 that opened the circuit is recorded as an error; the fallback that
    # answered the next request is recorded separately, under the model that
    # actually served it.
    outcomes = [event.outcome for event in _events(state)]
    assert outcomes == ["error", "fallback"]
    assert [event.model for event in _events(state)][-1] == "gpt-4o-mini"


@pytest.mark.anyio
async def test_async_a_successful_fallback_is_billed_as_its_own_fallback_event():
    state = _state(_fallback_config(ledger_enabled=True, fallback_model="gpt-4o-mini"))
    async with _async_client(state, _handler(OPENAI_RESPONSE, status=503)) as client:
        assert (await client.post("/v1/chat/completions", json=OPENAI_BODY)).status_code == 503
    assert state.circuit.state is CircuitState.OPEN

    def fallback_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={**OPENAI_RESPONSE, "model": "gpt-4o-mini"})

    async with _async_client(state, fallback_handler) as client:
        response = await client.post("/v1/chat/completions", json=OPENAI_BODY)
    assert response.status_code == 200
    assert [event.outcome for event in _events(state)] == ["error", "fallback"]


# ---------------------------------------------------------------------------
# The one-wrap-call adoption property, with the ledger off
# ---------------------------------------------------------------------------


def test_one_wrap_call_still_works_with_the_ledger_off():
    """The adoption property is one call. This task must not have changed it.

    ``Backstop.wrap(client, budget=...)`` is the whole integration story, and it
    is asserted here with the ledger at its default of off, because that is the
    configuration every existing user is on.
    """
    openai = pytest.importorskip("openai")
    from backstop import Backstop
    from backstop._httpcompat import compat_for

    probe = openai.OpenAI(api_key="sk-test")
    compat = compat_for(probe._client)
    probe._client.close()

    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=OPENAI_RESPONSE)

    raw = compat.Client(
        transport=BackstopTransport(_state(BackstopConfig()), compat.MockTransport(handle)),
        base_url="https://api.openai.com/v1",
    )
    client = openai.OpenAI(api_key="sk-test", http_client=raw)
    wrapped = Backstop.wrap(client, budget=100_000)
    try:
        assert wrapped.__class__ is openai.OpenAI
        completion = wrapped.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
        )
        assert completion.id == "chatcmpl-ledger-1"
        assert len(seen) == 1

        state = wrapped._backstop_state
        assert state.config.ledger_enabled is False
        # The default path: a NullSink writer that was never asked for anything.
        assert isinstance(state.ledger.sink, NullSink)
        assert state.ledger.submitted == 0
        assert state.ledger_errors == 0
        # And enforcement is untouched: the reservation was made and reconciled.
        assert state.budget.spent == 150
    finally:
        raw.close()
        client.close()


# ---------------------------------------------------------------------------
# Which outcomes reach a durable ledger, and which are reserved
# ---------------------------------------------------------------------------


def _open_circuit_config(**overrides) -> BackstopConfig:
    """One 503 opens the circuit and the cooldown keeps it open."""
    return BackstopConfig(
        default_max_output_tokens=8,
        retry_max_attempts=1,
        aimd_adjustment_interval=0,
        circuit_min_requests=1,
        circuit_failure_threshold=1.0,
        circuit_cooldown_seconds=60.0,
        ledger_enabled=True,
        **overrides,
    )


def test_the_ledger_records_only_outcomes_that_reached_a_provider():
    """Pin the decision that ``EMITTED_OUTCOMES`` documents.

    ``SpendEvent.OUTCOMES`` carries six values; three of them name requests the
    guardrails stopped before dispatch. Those are *reserved*, not produced, and
    this test is why: it drives a success, an error and a circuit-open denial
    through the transport and asserts the ledger contains exactly the first two.
    If someone starts emitting ``circuit_open`` or ``budget_denied`` rows, this
    fails and the reason has to be argued — a blocked request has no provider
    usage and no dollars, so the row would carry a pre-flight floor for spend
    that never happened, and it would feed that floor into the detector's window.
    """
    answered = _state(_open_circuit_config())
    with _sync_client(answered, _handler(OPENAI_RESPONSE)) as client:
        assert client.post("/v1/chat/completions", json=OPENAI_BODY).status_code == 200
    with _sync_client(answered, _handler(OPENAI_RESPONSE, status=500)) as client:
        assert client.post("/v1/chat/completions", json=OPENAI_BODY).status_code == 500
    assert {event.outcome for event in _events(answered)} == {"success", "error"}

    # A fresh state, because the circuit's window counts the successes above.
    denied = _state(_open_circuit_config())
    with _sync_client(denied, _handler(OPENAI_RESPONSE, status=503)) as client:
        client.post("/v1/chat/completions", json=OPENAI_BODY)
    assert denied.circuit.state is CircuitState.OPEN
    with pytest.raises(CircuitBreakerOpenError):
        with _sync_client(denied, _handler(OPENAI_RESPONSE)) as client:
            client.post("/v1/chat/completions", json=OPENAI_BODY)
    # The 503 is a provider call and is billed as one; the denial that followed
    # is not in the ledger at all.
    assert [event.outcome for event in _events(denied)] == ["error"]

    # The three reserved outcomes are still valid schema values, so a file
    # written by another producer still loads against this schema.
    assert set(EMITTED_OUTCOMES) < set(OUTCOMES)
    for reserved in ("circuit_open", "budget_denied", "queue_timeout"):
        assert reserved in OUTCOMES
        assert reserved not in EMITTED_OUTCOMES
        assert _event_with_outcome(reserved).outcome == reserved


def test_the_fallback_outcome_is_one_of_the_three_that_are_emitted():
    """The other half of the set, asserted rather than assumed."""
    state = _state(_fallback_config(ledger_enabled=True, fallback_model="gpt-4o-mini"))
    with _sync_client(state, _handler(OPENAI_RESPONSE, status=503)) as client:
        client.post("/v1/chat/completions", json=OPENAI_BODY)

    def fallback_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={**OPENAI_RESPONSE, "model": "gpt-4o-mini"})

    with _sync_client(state, fallback_handler) as client:
        assert client.post("/v1/chat/completions", json=OPENAI_BODY).status_code == 200
    outcomes = [event.outcome for event in _events(state)]
    assert outcomes == ["error", "fallback"]
    assert set(outcomes) <= set(EMITTED_OUTCOMES)


def _event_with_outcome(outcome: str) -> SpendEvent:
    return SpendEvent(
        provider="openai",
        model="gpt-4o",
        endpoint="/v1/chat/completions",
        priority="default",
        outcome=outcome,
        input_tokens=1,
        output_tokens=1,
        estimated=False,
        attribution=Attribution(team="payments"),
    )


def test_a_denied_request_is_still_visible_where_it_has_always_been_visible():
    """The blocked-request evidence lives on the enforcement surface, not here.

    A circuit-open denial costs no tokens and no dollars, so it must not appear
    in a charge-back — but it must not vanish either, and it does not: the
    request counter carries the outcome, while the ledger's own counters show no
    loss, because the transport never offered it an event to lose.
    """
    from backstop.telemetry import install_sink, reset_telemetry

    reset_telemetry()
    try:
        sink = install_sink()
        state = _state(_open_circuit_config())
        with _sync_client(state, _handler(OPENAI_RESPONSE, status=503)) as client:
            client.post("/v1/chat/completions", json=OPENAI_BODY)
        with pytest.raises(CircuitBreakerOpenError):
            with _sync_client(state, _handler(OPENAI_RESPONSE)) as client:
                client.post("/v1/chat/completions", json=OPENAI_BODY)
        assert sink.counter_total("requests", {"outcome": "circuit_open"}) == 1
        assert [event.outcome for event in _events(state)] == ["error"]
        report = state.ledger.close()
        assert report.lost == 0
    finally:
        reset_telemetry()
