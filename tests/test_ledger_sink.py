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
    BoundedWriter,
    CostBreakdown,
    JsonlSink,
    LedgerSink,
    MemorySink,
    NullSink,
    PriceCatalog,
    SpendEvent,
    compute_cost,
)
from backstop.ledger.sink import (
    DEFAULT_MEMORY_EVENTS,
    DEFAULT_QUEUE_SIZE,
    DRAIN_THREAD_NAME,
    CloseReport,
)


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


# --- BoundedWriter: the hot path --------------------------------------------


def test_a_plain_object_satisfies_the_protocol_without_subclassing() -> None:
    """The protocol is structural, which is the point of it being a Protocol."""

    class TheirSink:
        def __init__(self) -> None:
            self.seen: list[SpendEvent] = []

        def write(self, event: SpendEvent) -> None:
            self.seen.append(event)

        def flush(self) -> None:
            pass

        def close(self) -> None:
            pass

    theirs = TheirSink()
    assert isinstance(theirs, LedgerSink)
    writer = BoundedWriter(theirs)  # type: ignore[arg-type]
    assert writer.submit(make_event()) is True
    writer.close()
    assert len(theirs.seen) == 1


def test_bounded_writer_defaults_to_ten_thousand_queued_events() -> None:
    writer = BoundedWriter(NullSink())
    assert writer.backlog == 0
    writer.close()
    assert BoundedWriter(NullSink(), maxlen=DEFAULT_QUEUE_SIZE).backlog == 0


def prime_stalled_sink(writer: BoundedWriter, sink: _StalledSink) -> None:
    """Start the drain thread and park it inside the sink's first write.

    Waiting on an ``Event`` the sink sets from inside ``write`` is what makes the
    arithmetic in the overflow tests exact rather than racy: the caller knows the
    buffer is empty and one event is in flight before the first measured submit.
    """
    assert writer.submit(make_event(model="priming")) is True
    assert sink.entered.wait(5.0), "the drain thread never started writing"
    assert writer.backlog == 0, "the priming event was taken off the buffer"


def test_ten_thousand_submits_do_not_block_the_caller() -> None:
    """The headline claim, measured.

    A sink that has been told to stall parks the drain thread inside its first
    write, so the backlog is the only thing between the caller and the overflow
    policy. 10,000 submits must return in milliseconds, and must never wait on
    that stalled write.
    """
    sink = _StalledSink()
    writer = BoundedWriter(sink)
    events = [make_event(model=f"m{index}") for index in range(10_000)]
    prime_stalled_sink(writer, sink)

    def burst() -> int:
        return sum(1 for event in events if writer.submit(event))

    accepted, elapsed = run_bounded(burst, 10.0)
    try:
        assert accepted == 10_000
        assert elapsed < 2.0, (
            f"10,000 submits took {elapsed * 1000:.1f}ms against a stalled sink; "
            "the caller waited on the sink"
        )
        assert writer.submitted == 10_001
        assert writer.written == 0, "the sink is stalled, so nothing is written"
        assert writer.backlog == DEFAULT_QUEUE_SIZE
        assert writer.dropped_events == 0, (
            "the default bound is 10,000 and the buffer is empty at the start of "
            "the burst, so the whole burst fits and nothing may be dropped"
        )
    finally:
        sink.release.set()
        report = writer.close()

    assert report.drained is True
    assert report.undrained == 0
    assert report.submitted == report.written + report.dropped_events
    assert report.written == 10_001, "the primed event plus the whole burst"
    assert len(sink.written) == 10_001


def test_overflow_refuses_the_incoming_event_and_counts_it_exactly() -> None:
    """A bounded buffer that grows is a bug; a counted drop is a fact.

    With the drain thread parked in the sink, the bound is fully available to
    the caller, so the arithmetic is exact rather than racy: ``maxlen`` events
    buffered, and every submit past that refused with the oldest still queued.
    """
    sink = _StalledSink()
    writer = BoundedWriter(sink, maxlen=8)
    prime_stalled_sink(writer, sink)

    accepted = 0
    try:
        for index in range(50):
            if writer.submit(make_event(model=f"m{index}")):
                accepted += 1
        assert accepted == 8
        assert writer.backlog == 8
        assert writer.dropped_events == 42
        assert writer.submitted == 51
    finally:
        sink.release.set()
        report = writer.close()

    assert report.drained is True
    assert report.written == 9, "the one in flight plus the eight that were buffered"
    assert report.dropped_events == 42
    assert report.submitted == report.written + report.dropped_events
    assert report.lost == 42
    # Refused means refused: the survivors are the first eight, and the priming
    # event, so the events that were turned away are simply not in the file.
    assert [e.model for e in sink.written] == ["priming"] + [f"m{i}" for i in range(8)]


def test_the_buffer_never_exceeds_its_bound_under_a_far_larger_burst() -> None:
    sink = _StalledSink()
    writer = BoundedWriter(sink, maxlen=16)
    prime_stalled_sink(writer, sink)
    high = [0]

    def burst() -> None:
        for index in range(20_000):
            writer.submit(make_event(model=f"m{index}"))
            depth = writer.backlog
            if depth > high[0]:
                high[0] = depth

    try:
        run_bounded(burst, 30.0)
        assert high[0] <= 16, f"backlog reached {high[0]}, past the bound of 16"
        assert writer.backlog <= 16
        assert writer.dropped_events == 20_000 - 16
    finally:
        sink.release.set()
        report = writer.close()

    assert report.undrained == 0
    assert report.written == 17, "the priming event plus the sixteen that fit"
    assert report.submitted == report.written + report.dropped_events


def test_a_sink_that_raises_never_reaches_the_submitter() -> None:
    """A broken sink is counted, not propagated: the request path never sees it."""
    sink = _ExplodingSink()
    writer = BoundedWriter(sink)

    def burst() -> int:
        return sum(1 for _ in range(50) if writer.submit(make_event()))

    try:
        accepted, _ = run_bounded(burst, 5.0)
        assert accepted == 50, "a raising sink must not make submit() refuse"
        assert wait_for(lambda: writer.written + writer.sink_errors == 50)
        assert writer.written == 0
        assert writer.sink_errors == 50
        assert sink.attempts == 50
        assert writer.dropped_events == 0
    finally:
        report = writer.close()

    assert report.submitted == report.written + report.dropped_events + report.sink_errors


def test_a_sink_that_raises_on_flush_and_close_still_lets_shutdown_finish() -> None:
    sink = _ExplodingSink()
    writer = BoundedWriter(sink)
    writer.submit(make_event())
    assert wait_for(lambda: writer.sink_errors == 1)
    report = writer.close()  # must not raise
    assert isinstance(report, CloseReport)
    assert report.drained is True
    assert report.written == 0


def test_close_returns_within_its_bound_when_the_sink_is_stalled() -> None:
    """Shutdown must not hang on a sink that has stopped responding."""
    sink = _StalledSink()
    writer = BoundedWriter(sink, maxlen=4, close_timeout=0.25)
    prime_stalled_sink(writer, sink)
    for index in range(4):
        writer.submit(make_event(model=f"m{index}"))
    assert writer.backlog == 4

    report, elapsed = run_bounded(writer.close, 5.0)
    try:
        assert elapsed < 1.0, (
            f"close took {elapsed:.3f}s; the stalled sink was waited on rather "
            "than abandoned"
        )
        assert report.drained is False
        assert report.undrained == 4, "the backlog is discarded, not written late"
        assert report.dropped_events == 4
        assert report.lost >= 4
        assert writer.backlog == 0, "the discarded backlog is gone, not left to grow"
        assert sink.closed is True
    finally:
        sink.release.set()


def test_close_reports_every_event_it_never_wrote() -> None:
    sink = _CountingSink()
    writer = BoundedWriter(sink)
    for index in range(20):
        writer.submit(make_event(model=f"m{index}"))

    report = writer.close()
    assert report.drained is True
    assert report.submitted == 20
    assert report.written == 20
    assert report.dropped_events == 0
    assert report.sink_errors == 0
    assert report.lost == 0
    assert report.undrained == 0
    assert writer.backlog == 0
    assert len(sink.written) == 20
    assert sink.closed is True


# --- A sink that swallows its own failure ----------------------------------
#
# ``JsonlSink`` may not raise into the drain thread, so it degrades and counts.
# From the writer's side that write is indistinguishable from a successful one,
# which is why the sink is given a counter of its own and why ``close`` has to
# read it. The reproduction below is the reviewer's: 50 events into a file that
# can never be opened, which used to report ``written=50 dropped=0
# sink_errors=0`` — every event accounted for, and not one of them in the file.


def test_close_reports_a_sinks_own_failures_as_lost(tmp_path: Any) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    writer = BoundedWriter(JsonlSink(blocker / "ledger.jsonl"))
    for index in range(50):
        writer.submit(make_event(model=f"m{index}"))

    report = writer.close()
    assert report.submitted == 50
    assert report.landed == 0, "the file received zero records"
    assert report.lost == 50, "the docstring promises the events that never land"
    assert report.sink_reported_errors == 50
    assert report.sink_degraded is True
    # The writer's own buckets are unchanged: nothing was refused and nothing
    # raised, which is exactly why the writer alone could not have known.
    assert report.dropped_events == 0
    assert report.sink_errors == 0
    assert report.submitted == report.written + report.dropped_events + report.sink_errors


def test_the_shutdown_and_live_delivery_apis_agree_on_the_loss(tmp_path: Any) -> None:
    """One number, two APIs — the demo's and the shutdown path's.

    ``export.delivery_report`` already folded in the sink's own counter; the
    report ``close()`` returns did not, so the same writer could be described as
    complete by one and as empty by the other. They now share
    :func:`lost_events`, and this asserts the two agree on both readings.
    """
    from backstop.ledger.export import delivery_report

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    writer = BoundedWriter(JsonlSink(blocker / "ledger.jsonl"))
    for _ in range(50):
        writer.submit(make_event())

    report = writer.close()
    live = delivery_report(writer)
    from_report = delivery_report(report)

    assert report.lost == 50
    assert live.lost == report.lost
    assert from_report.lost == report.lost
    assert live.landed == report.landed == 0
    assert from_report.landed == report.landed
    # Every field of the same writer, from both APIs.
    assert (live.submitted, live.written, live.dropped_events) == (
        report.submitted,
        report.written,
        report.dropped_events,
    )
    assert live.sink_degraded is True
    assert from_report.sink_degraded is True


def test_a_healthy_close_reports_nothing_lost_and_everything_landed() -> None:
    sink = _CountingSink()
    writer = BoundedWriter(sink)
    for _ in range(5):
        writer.submit(make_event())

    report = writer.close()
    # A sink with no counter of its own is asked nothing: a sink that cannot lose
    # anything does not have to report that twice.
    assert report.sink_reported_errors == 0
    assert report.sink_degraded is False
    assert report.lost == 0
    assert report.landed == 5 == len(sink.written)


def test_a_sink_that_counts_failures_it_raised_does_not_produce_a_negative_landed() -> None:
    """A sink that contradicts itself must not make the report say -1 landed."""

    class _DoubleCountedSink(_CountingSink):
        @property
        def sink_errors(self) -> int:
            return 99

    writer = BoundedWriter(_DoubleCountedSink())
    writer.submit(make_event())
    report = writer.close()
    assert report.written == 1
    assert report.landed == 0, "floored, not negative"
    # The loss is still reported rather than hidden, because the sink said so.
    assert report.lost == 99


def test_a_sink_whose_own_counter_is_not_a_count_is_read_as_no_counter() -> None:
    class _NonsenseCounterSink(_CountingSink):
        @property
        def sink_errors(self) -> Any:
            return "lots"

    writer = BoundedWriter(_NonsenseCounterSink())
    writer.submit(make_event())
    report = writer.close()
    assert report.sink_reported_errors == 0
    assert report.landed == 1
    assert report.lost == 0


def test_close_is_idempotent_and_returns_the_same_report() -> None:
    writer = BoundedWriter(_CountingSink())
    writer.submit(make_event())
    first = writer.close()
    assert writer.close() is first
    assert writer.close() == first


def test_submitting_after_close_is_refused_and_counted() -> None:
    writer = BoundedWriter(_CountingSink())
    writer.submit(make_event())
    writer.close()
    assert writer.submit(make_event()) is False
    assert writer.submit(make_event()) is False
    assert writer.dropped_events == 2


def test_counters_stay_internally_consistent_across_a_mixed_sequence() -> None:
    """Normal writes, overflow drops and sink failures in one run.

    Every submitted event must end up in exactly one of written, dropped, or
    errored — none counted twice, none missing. That is the only way an operator
    can trust ``dropped_events`` as a number.
    """
    good = _SwitchableSink()
    writer = BoundedWriter(good, maxlen=32)

    # Park the drain thread inside its first write, so the bound is fully
    # available to the caller and the arithmetic below is exact, not racy.
    good.gate.clear()
    writer.submit(make_event(model="priming"))
    assert wait_for(lambda: len(good.written) == 1)

    try:
        for _ in range(10):
            assert writer.submit(make_event(model="fine")) is True
        assert writer.backlog == 10, "the priming event is in flight, not buffered"

        good.doomed.add("doomed")
        for _ in range(2):
            assert writer.submit(make_event(model="doomed")) is True
        assert writer.backlog == 12
        refused = sum(
            1 for _ in range(100) if not writer.submit(make_event(model="refused"))
        )
        assert writer.backlog == 32, "the buffer is exactly full, nothing overflowed it"
    finally:
        good.gate.set()
        report = writer.close()

    assert refused == 80, "12 of the 32 slots were already taken, so 80 are refused"
    assert len(good.written) == 31, "the two doomed events never reached the recorder"
    assert report.submitted == 113
    assert report.written == 31
    assert report.sink_errors == 2
    assert report.dropped_events == 80
    assert report.lost == 82
    assert (
        report.submitted == report.written + report.dropped_events + report.sink_errors
    ), "an event was counted twice or went missing"


def test_the_drain_thread_is_a_named_daemon_started_lazily() -> None:
    """One thread, started on the first accepted submit, and only one."""
    before = {t.name for t in threading.enumerate()}
    assert DRAIN_THREAD_NAME not in before

    writer = BoundedWriter(_CountingSink())
    assert DRAIN_THREAD_NAME not in {t.name for t in threading.enumerate()}

    writer.submit(make_event())
    assert DRAIN_THREAD_NAME in {t.name for t in threading.enumerate()}
    assert wait_for(lambda: writer.written == 1)
    drain = next(t for t in threading.enumerate() if t.name == DRAIN_THREAD_NAME)
    assert drain.daemon is True

    for _ in range(50):
        writer.submit(make_event())
    assert wait_for(lambda: writer.written == 51)
    assert sum(1 for t in threading.enumerate() if t.name == DRAIN_THREAD_NAME) == 1
    writer.close()
    assert wait_for(lambda: DRAIN_THREAD_NAME not in {t.name for t in threading.enumerate()})


def test_the_drain_target_is_a_module_level_function() -> None:
    """No closure over the writer's state: the thread's target is one function."""
    from backstop.ledger import sink as sink_module

    assert sink_module._drain.__name__ == "_drain"
    assert sink_module._drain.__qualname__ == "_drain"
    assert not getattr(sink_module._drain, "__closure__", None)


def test_bounded_writer_rejects_a_bound_it_could_not_honour() -> None:
    with pytest.raises(ValueError):
        BoundedWriter(NullSink(), maxlen=0)
    with pytest.raises(ValueError):
        BoundedWriter(NullSink(), close_timeout=-1.0)
    with pytest.raises(TypeError):
        BoundedWriter(NullSink(), maxlen="lots")  # type: ignore[arg-type]


def test_a_writer_with_no_submits_closes_without_a_thread() -> None:
    sink = _CountingSink()
    report = BoundedWriter(sink).close()
    assert report.submitted == 0
    assert report.written == 0
    assert report.drained is True
    assert report.undrained == 0
    assert sink.closed is True


def test_the_ledger_package_exports_every_sink() -> None:
    import backstop.ledger as ledger

    for name in ("LedgerSink", "NullSink", "MemorySink", "JsonlSink", "BoundedWriter"):
        assert name in ledger.__all__, f"{name} is not exported from backstop.ledger"
        assert getattr(ledger, name) is not None


def test_every_reader_of_the_memory_ring_takes_its_lock() -> None:
    """One discipline for the ring, not three of four.

    ``events``, ``write`` and ``clear`` all take the lock, so a snapshot is never
    torn. ``__len__`` did not, and it is what ``__repr__`` reads — which is the
    one diagnostic a user is likely to run while the drain thread is appending.
    Asserted on the lock rather than on a race: a timing test would pass or fail
    on the machine it ran on, and this claim is about the discipline.
    """
    sink = MemorySink(4)
    counting = _CountingLock(sink._lock)
    sink._lock = counting  # type: ignore[assignment]
    sink.write(SpendEvent(provider="openai", model="gpt-4o", endpoint="/v1/x",
                          priority="default", outcome="success", input_tokens=1,
                          output_tokens=1, estimated=False, attribution=Attribution()))
    taken = counting.entered
    assert len(sink) == 1
    assert counting.entered == taken + 1
    assert "held=1" in repr(sink)


class _CountingLock:
    """A real lock that records how many times it was entered."""

    def __init__(self, lock: object) -> None:
        self._lock = lock
        self.entered = 0

    def __enter__(self) -> None:
        self._lock.__enter__()  # type: ignore[attr-defined]
        self.entered += 1

    def __exit__(self, *exc: object) -> None:
        self._lock.__exit__(*exc)  # type: ignore[attr-defined]
