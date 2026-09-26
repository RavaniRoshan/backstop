"""Tests for the ledger sinks: the protocol, the three sinks, and the bounded
writer that keeps all of them off the request path.

The hot-path claims are the ones that matter here, so they are measured rather
than asserted by construction: a burst of submits is timed against a sink that
has been told to stall, a stalled close is timed against its own bound, and
``NullSink.write`` is timed against a sink that does real work. Every
synchronisation is an ``Event`` or a ``Condition``, never a bare ``sleep`` — a
test that waits on the clock can pass for the wrong reason.
"""
from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from backstop.ledger import Attribution, LedgerSink, MemorySink, NullSink, SpendEvent
from backstop.ledger.sink import DEFAULT_MEMORY_EVENTS


def make_event(**overrides: Any) -> SpendEvent:
    """Build a valid event; ``overrides`` replaces individual fields."""
    fields: dict[str, Any] = {
        "provider": "openai",
        "model": "gpt-4o",
        "endpoint": "/v1/chat/completions",
        "priority": "default",
        "outcome": "success",
        "input_tokens": 120,
        "output_tokens": 45,
        "estimated": False,
        "attribution": Attribution(team="payments", feature="checkout-v2"),
    }
    fields.update(overrides)
    return SpendEvent(**fields)


class _StalledSink:
    """A sink whose writes block until the test releases them.

    Models a disk that has stopped responding, which is the case the writer's
    bounded submit and bounded close exist for. The first write sets
    :attr:`entered`, so a test can wait until the drain thread is genuinely
    parked inside the sink instead of guessing with a sleep.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.written: list[SpendEvent] = []
        self.flushes = 0
        self.closed = False

    def write(self, event: SpendEvent) -> None:
        self.written.append(event)
        self.entered.set()
        self.release.wait(30.0)

    def flush(self) -> None:
        self.flushes += 1

    def close(self) -> None:
        self.closed = True


class _CountingSink:
    """Records what it was handed, immediately."""

    def __init__(self) -> None:
        self.written: list[SpendEvent] = []
        self.flushes = 0
        self.closed = False

    def write(self, event: SpendEvent) -> None:
        self.written.append(event)

    def flush(self) -> None:
        self.flushes += 1

    def close(self) -> None:
        self.closed = True


class _ExplodingSink:
    """Raises on every write, to prove nothing reaches the submitter."""

    def __init__(self) -> None:
        self.attempts = 0

    def write(self, event: SpendEvent) -> None:
        self.attempts += 1
        raise RuntimeError("sink is on fire")

    def flush(self) -> None:
        raise RuntimeError("sink is on fire")

    def close(self) -> None:
        raise RuntimeError("sink is on fire")


class _SwitchableSink:
    """Records, but raises for any event whose model is marked doomed.

    Per-event rather than global, so one run can mix successes and failures
    without the result depending on which ones happened to be in flight. The
    gate is what parks the drain thread, and it is cleared so a reader that sees
    an event knows the drain thread is now blocked inside that write.
    """

    def __init__(self) -> None:
        self.written: list[SpendEvent] = []
        self.doomed: set[str] = set()
        self.gate = threading.Event()
        self.gate.set()  # open: writes complete immediately

    def write(self, event: SpendEvent) -> None:
        if event.model in self.doomed:
            raise RuntimeError("sink is on fire")
        self.written.append(event)
        self.gate.wait(30.0)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def run_bounded(fn: Any, timeout: float) -> tuple[Any, float]:
    """Call ``fn`` on a worker thread, returning ``(result, elapsed_s)``.

    A test that called ``fn`` on the main thread and merely measured it would
    *hang* rather than fail if the code under test blocked, which is the one
    outcome a regression test must not have. Running it here makes a block a
    diagnosable assertion failure with the elapsed time attached.
    """
    done = threading.Event()
    box: list[Any] = []

    def target() -> None:
        try:
            box.append((True, fn()))
        except BaseException as exc:  # noqa: BLE001 - reported through the box
            box.append((False, exc))
        finally:
            done.set()

    worker = threading.Thread(target=target, daemon=True)
    started = time.perf_counter()
    worker.start()
    finished = done.wait(timeout)
    elapsed = time.perf_counter() - started
    assert finished, f"the call did not return within {timeout}s; it blocked"
    ok, payload = box[0]
    if not ok:
        raise payload
    return payload, elapsed


def wait_for(predicate: Any, timeout: float = 5.0) -> bool:
    """Poll ``predicate`` on a short interval until it is true or time is up.

    Used only where the event to wait on is a counter, not an ``Event``; the
    interval is short enough that a failure is a failure, not a flake.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.002)
    return predicate()


# --- the protocol -----------------------------------------------------------


def test_null_sink_satisfies_the_ledger_sink_protocol() -> None:
    assert isinstance(NullSink(), LedgerSink)
    assert isinstance(MemorySink(), LedgerSink)


def test_an_object_missing_a_method_is_not_a_sink() -> None:
    class HalfASink:
        def write(self, event: SpendEvent) -> None:
            pass

    assert not isinstance(HalfASink(), LedgerSink)


# --- NullSink ---------------------------------------------------------------


def test_null_sink_discards_everything() -> None:
    sink = NullSink()
    for index in range(5):
        sink.write(make_event(model=f"model-{index}"))
    sink.flush()
    sink.close()


def test_null_sink_write_is_measurably_cheaper_than_a_sink_that_works() -> None:
    """The disabled ledger pays a call and nothing else.

    Measured against :class:`MemorySink`, which is the cheapest sink that does
    any work at all (a lock and an append), so the comparison is machine-speed
    independent: the ratio is what carries the claim, and the absolute ceiling is
    a backstop against a regression that made the empty body do something.
    """
    rounds = 50_000
    event = make_event()
    null = NullSink()
    memory = MemorySink(maxlen=8)

    def hit_null() -> None:
        for _ in range(rounds):
            null.write(event)

    def hit_memory() -> None:
        for _ in range(rounds):
            memory.write(event)

    # Warm both so neither pays first-call import or allocation costs.
    hit_null()
    hit_memory()

    null_start = time.perf_counter()
    hit_null()
    null_ns = (time.perf_counter() - null_start) / rounds * 1e9
    memory_start = time.perf_counter()
    hit_memory()
    memory_ns = (time.perf_counter() - memory_start) / rounds * 1e9

    assert null_ns < 1000.0, f"NullSink.write took {null_ns:.0f}ns per call"
    assert null_ns * 3 < memory_ns, (
        f"NullSink.write ({null_ns:.0f}ns) should be far cheaper than "
        f"MemorySink.write ({memory_ns:.0f}ns)"
    )


# --- MemorySink -------------------------------------------------------------


def test_memory_sink_defaults_to_ten_thousand_events() -> None:
    assert MemorySink().maxlen == DEFAULT_MEMORY_EVENTS == 10_000


def test_memory_sink_evicts_oldest_first_at_the_bound() -> None:
    sink = MemorySink(maxlen=4)
    events = [make_event(model=f"m{index}") for index in range(7)]
    for event in events:
        sink.write(event)

    assert len(sink) == 4
    assert [e.model for e in sink.events] == ["m3", "m4", "m5", "m6"]
    # Identity, not just equality: the survivors are the objects that were kept.
    assert sink.events[0] is events[3]
    assert sink.events[-1] is events[6]


def test_memory_sink_clear_empties_the_ring_but_keeps_its_capacity() -> None:
    sink = MemorySink(maxlen=3)
    for _ in range(5):
        sink.write(make_event())
    assert len(sink) == 3
    sink.clear()
    assert len(sink) == 0
    assert sink.events == ()
    sink.write(make_event())
    assert len(sink) == 1
    assert sink.maxlen == 3


def test_memory_sink_keeps_its_events_after_close() -> None:
    """`backstop ledger demo` closes the writer and then reads the ring."""
    sink = MemorySink(maxlen=10)
    sink.write(make_event(model="kept"))
    sink.flush()
    sink.close()
    assert [e.model for e in sink.events] == ["kept"]


def test_memory_sink_rejects_a_useless_bound() -> None:
    with pytest.raises(ValueError):
        MemorySink(maxlen=0)
    with pytest.raises(TypeError):
        MemorySink(maxlen="lots")  # type: ignore[arg-type]


def test_memory_sink_is_thread_safe_under_concurrent_writers() -> None:
    sink = MemorySink(maxlen=64)
    threads = [
        threading.Thread(target=lambda: [sink.write(make_event()) for _ in range(200)])
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10.0)
    # 1,600 writes into a 64-slot ring: the bound holds and nothing was lost
    # beyond the documented eviction.
    assert len(sink) == 64
    assert all(isinstance(e, SpendEvent) for e in sink.events)


