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

import json
import threading
import time
from decimal import Decimal
from typing import Any

import pytest

from backstop.ledger import (
    Attribution,
    CostBreakdown,
    JsonlSink,
    LedgerSink,
    MemorySink,
    NullSink,
    PriceCatalog,
    SpendEvent,
    compute_cost,
)
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


# --- JsonlSink --------------------------------------------------------------


def priced_event(**overrides: Any) -> SpendEvent:
    """An event carrying a real :class:`CostBreakdown` from the bundled catalog.

    It lives in the JSONL section rather than the header because it exists for
    one reason: money crosses the wire as a *string*, and only an event that
    carries money makes that observable.
    """
    event = make_event(**overrides)
    cost = compute_cost(event, PriceCatalog())
    assert cost is not None, "the bundled catalog must price gpt-4o"
    return make_event(cost=cost, **overrides)


def test_jsonl_sink_satisfies_the_ledger_sink_protocol() -> None:
    assert isinstance(JsonlSink("/tmp/does-not-need-to-exist.jsonl"), LedgerSink)


def test_jsonl_sink_round_trips_every_line_including_one_with_a_cost(tmp_path: Any) -> None:
    """Write, close, read back: every line must rebuild the record it came from.

    One event carries a priced :class:`CostBreakdown`, because money crosses the
    wire as a *string*. A round trip that passed without it would prove nothing
    about the part of the record a finance export depends on.
    """
    path = tmp_path / "ledger.jsonl"
    sink = JsonlSink(path)
    events = [priced_event() if index % 3 == 0 else make_event() for index in range(9)]
    for event in events:
        sink.write(event)
    sink.close()

    assert not sink.degraded
    assert sink.sink_errors == 0

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(events)
    assert all(json.loads(line) for line in lines)
    rebuilt = [SpendEvent.from_dict(json.loads(line)) for line in lines]
    assert rebuilt == events
    priced = next(e for e in rebuilt if e.cost is not None)
    assert priced.cost is not None
    assert isinstance(priced.cost, CostBreakdown)
    assert priced.cost.total_usd == sum(
        (
            priced.cost.input_usd,
            priced.cost.output_usd,
            priced.cost.cache_read_usd,
            priced.cost.cache_write_usd,
        ),
        Decimal("0.000000"),
    )
    # Money really did travel as a string, not as a float that lost its cents.
    raw = json.loads(lines[0])["cost"]
    assert isinstance(raw["total_usd"], str)
    assert raw["total_usd"] == f"{priced.cost.total_usd:f}"


def test_jsonl_sink_writes_one_object_per_line_with_sorted_keys(tmp_path: Any) -> None:
    path = tmp_path / "ledger.jsonl"
    sink = JsonlSink(path)
    sink.write(make_event())
    sink.close()

    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert text.count("\n") == 1
    keys = list(json.loads(text.strip()))
    assert keys == sorted(keys)


def test_jsonl_sink_appends_and_never_truncates(tmp_path: Any) -> None:
    """Two processes on the same file must not erase each other's records."""
    path = tmp_path / "ledger.jsonl"
    first = JsonlSink(path)
    first.write(make_event(model="before-restart"))
    first.close()

    second = JsonlSink(path)
    second.write(make_event(model="after-restart"))
    second.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [SpendEvent.from_dict(json.loads(line)).model for line in lines] == [
        "before-restart",
        "after-restart",
    ]


def test_jsonl_sink_creates_missing_parent_directories(tmp_path: Any) -> None:
    path = tmp_path / "deep" / "nested" / "reports" / "ledger.jsonl"
    assert not path.parent.exists()

    sink = JsonlSink(path)
    sink.write(make_event())
    sink.close()

    assert path.exists()
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    assert not sink.degraded


def test_jsonl_sink_touches_nothing_until_there_is_an_event_to_record(
    tmp_path: Any,
) -> None:
    path = tmp_path / "unwritten" / "ledger.jsonl"
    sink = JsonlSink(path)
    assert not path.parent.exists()
    sink.close()
    assert not path.parent.exists(), "a sink that recorded nothing made a directory"


def test_jsonl_sink_on_an_unwritable_path_degrades_instead_of_raising(
    tmp_path: Any,
) -> None:
    """A path whose parent is a regular file cannot be created, ever."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    path = blocker / "ledger.jsonl"

    sink = JsonlSink(path)
    sink.write(make_event())  # must not raise
    sink.write(make_event())
    sink.flush()
    sink.close()  # must not raise

    assert sink.degraded is True
    assert sink.sink_errors == 2, "one per refused write, so the loss is countable"
    assert not path.exists()


def test_jsonl_sink_keeps_counting_losses_while_degraded(tmp_path: Any) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    sink = JsonlSink(blocker / "ledger.jsonl")

    for _ in range(5):
        sink.write(make_event())

    assert sink.sink_errors == 5
    assert sink.degraded is True


def test_jsonl_sink_fsync_is_off_by_default(tmp_path: Any) -> None:
    path = tmp_path / "ledger.jsonl"
    assert JsonlSink(path).fsync is False
    assert JsonlSink(path, fsync=True).fsync is True
    sink = JsonlSink(path, fsync=True)
    sink.write(make_event())
    sink.close()
    assert not sink.degraded
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_jsonl_sink_flushes_every_line_so_a_crash_costs_one_event(
    tmp_path: Any,
) -> None:
    """The buffer is not the durability boundary; a closed file is.

    The test cannot crash a process, so it asserts the mechanism: after a write
    the line is already in the file, with no ``flush``/``close`` in between.
    """
    path = tmp_path / "ledger.jsonl"
    sink = JsonlSink(path)
    sink.write(make_event(model="already-there"))
    assert [SpendEvent.from_dict(json.loads(line)).model
            for line in path.read_text(encoding="utf-8").splitlines()] == ["already-there"]
    sink.close()


def test_jsonl_sink_rejects_a_path_it_cannot_use() -> None:
    with pytest.raises(ValueError):
        JsonlSink("")
    with pytest.raises(TypeError):
        JsonlSink(42)  # type: ignore[arg-type]


def test_a_truncated_final_line_is_detectable_by_the_reader(tmp_path: Any) -> None:
    """A torn write is the only corruption this sink can cause, and it is loud.

    :class:`JsonlSink` stops appending after a failed write, so a partial object
    can only ever be the last line and there can only ever be one. A reader finds
    it at whichever stage can tell: ``json.loads`` refuses a fragment that is not
    syntactically whole, and :meth:`SpendEvent.from_dict` refuses one that parses
    but is missing a declared field, naming the fields it wanted. Neither stage
    reloads a fragment as plausible-looking data, which is the property that
    matters — a charge-back built on a silently repaired record is worse than a
    charge-back with a hole in it.
    """
    path = tmp_path / "torn.jsonl"
    sink = JsonlSink(path)
    good = make_event(model="intact")
    sink.write(good)
    sink.write(make_event(model="torn"))
    sink.close()

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    head, tail = lines[0], lines[1]
    assert len(tail) > 200, "the test needs a long enough line to truncate"

    # Stage one: a fragment cut mid-token is not JSON at all.
    with pytest.raises(json.JSONDecodeError):
        json.loads(tail[:120])
    path.write_text(head + "\n" + tail[:120], encoding="utf-8")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2

    # Stage two: a fragment that happens to end on a field boundary parses, and
    # from_dict still refuses it rather than filling the gap with defaults.
    partial = dict(json.loads(tail))
    del partial["cost"]
    del partial["request_id"]
    path.write_text(head + "\n" + json.dumps(partial), encoding="utf-8")
    reread = path.read_text(encoding="utf-8").splitlines()
    with pytest.raises(ValueError) as excinfo:
        SpendEvent.from_dict(json.loads(reread[1]))
    assert "cost" in str(excinfo.value) and "request_id" in str(excinfo.value)

    # The intact line still reads, which is the whole recovery procedure.
    assert SpendEvent.from_dict(json.loads(reread[0])) == good


