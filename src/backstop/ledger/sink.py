"""Where a spend event goes: the sink protocol, the three sinks, and the bounded
writer that keeps all of them off the request path.

Where an event ends up is a policy decision, so it is a ``Protocol`` rather than
a base class: a user who wants their events in their own database passes a plain
object with ``write``/``flush``/``close`` and it works. Four implementations ship:

``NullSink``
    Drops everything. This is what a disabled ledger gets, so ``write`` is a bare
    function call and nothing else.
``MemorySink``
    A bounded ``deque`` ring. ``backstop ledger demo`` and the tests read it.
``JsonlSink``
    Append-only NDJSON. The durable path.
``BoundedWriter``
    The hot-path component. Not a sink — it owns one.

The hot-path rule, once, because everything below follows from it: **the
transport never blocks on the ledger.** It calls :meth:`BoundedWriter.submit`,
which takes one short lock, appends to a bounded ``deque`` and returns. If that
``deque`` is full the event is *refused* — counted in ``dropped_events`` and
reported by ``submit``'s ``False`` — rather than queued. An unbounded queue
turns a traffic burst into an OOM and a blocking queue turns it into latency on
the request path, and both failure modes are worse than a gap in the ledger. A
gap that says ``dropped_events: 418`` is a fact an operator can act on. An OOM is
not a fact at all.

That trade is only honest if the loss is *visible*, so nothing here fails
quietly:

* a refused submit returns ``False`` and moves ``dropped_events``;
* a sink that raises is counted in ``sink_errors`` and never reaches a caller;
* a sink that swallows its own failure counts it on an optional ``sink_errors``
  counter of its own, which :meth:`BoundedWriter.close` folds into the report;
* a :class:`JsonlSink` that cannot write says so through ``degraded`` and stops
  appending, rather than interleaving partial lines into a file a reader trusts;
* :meth:`BoundedWriter.close` reports what was never written, with a bounded join
  so a stalled sink cannot hang shutdown.
"""
from __future__ import annotations

import json
import os
import threading
from collections import deque
from dataclasses import dataclass
from typing import Protocol, TextIO, runtime_checkable

from .schema import SpendEvent

__all__ = [
    "DEFAULT_CLOSE_TIMEOUT",
    "DEFAULT_MEMORY_EVENTS",
    "DEFAULT_QUEUE_SIZE",
    "DRAIN_THREAD_NAME",
    "BoundedWriter",
    "CloseReport",
    "JsonlSink",
    "LedgerSink",
    "MemorySink",
    "NullSink",
    "landed_events",
    "lost_events",
]

#: Default ring length for :class:`MemorySink`, and the default of
#: ``BackstopConfig.ledger_memory_events``. 10,000 events is a couple of minutes
#: of a busy process; past that a demo and a diagnostic want the file, not more RAM.
DEFAULT_MEMORY_EVENTS = 10_000

#: Default backlog depth for :class:`BoundedWriter`. A burst deeper than this is
#: a sink that cannot keep up, and the events that do not fit are reported
#: rather than buffered. The ceiling is memory, not latency: a queued
#: :class:`SpendEvent` is a few hundred bytes, so this is single-digit MB.
DEFAULT_QUEUE_SIZE = 10_000

#: Default ceiling on :meth:`BoundedWriter.close`'s join. Shutdown must not hang
#: on a sink that is blocked, so a drain that has not finished by then is
#: abandoned and its backlog reported as lost.
DEFAULT_CLOSE_TIMEOUT = 5.0

#: Name of the one drain thread a :class:`BoundedWriter` owns.
DRAIN_THREAD_NAME = "backstop-ledger-drain"


def lost_events(
    dropped_events: int, writer_sink_errors: int, sink_reported_errors: int
) -> int:
    """The submitted events that will never be written. The one definition of it.

    Three buckets, and they are disjoint by construction: a submit the writer
    refused, a write that raised out of the sink, and a write the sink took
    responsibility for and then failed to record. Adding them is the whole
    arithmetic, and both report classes — :class:`CloseReport` on the shutdown
    path and :class:`~backstop.ledger.export.DeliveryReport` on the live path —
    call this, so the number a user reads at shutdown is the number the demo
    prints and cannot drift from it.
    """
    return dropped_events + writer_sink_errors + sink_reported_errors


def landed_events(written: int, sink_reported_errors: int) -> int:
    """The writes that produced a record: ``written`` less the ones the sink lost.

    ``written`` counts the calls a sink *returned from*, which is the only thing
    the writer can see: a sink that swallows its own failure looks exactly like
    one that succeeded. So ``written`` is an upper bound on what reached
    storage, and this is the number of records a reader of the file will
    actually find.

    Floored at zero because a sink that counted more failures than the writer
    counted successes has contradicted itself, and a negative count of records
    would be a worse lie than a zero. The contract in :class:`LedgerSink` is
    that a sink counts the failures of the writes it *accepted*, so the two
    numbers are comparable by design.
    """
    return written - sink_reported_errors if sink_reported_errors < written else 0


@runtime_checkable
class LedgerSink(Protocol):
    """Where the ledger puts one event.

    Structural, not nominal: any object with these three methods is a sink, so a
    user can hand Backstop an object that writes to their own storage without
    subclassing anything. ``isinstance`` therefore answers on the methods alone
    and says nothing about where the events actually go.

    None of the three may raise into a caller on the request path. The ledger
    calls them from :class:`BoundedWriter`'s drain thread, but a user may also
    call ``write`` directly, so the contract holds either way.

    **The optional fourth member, ``sink_errors``.** A sink must not raise, so it
    has to be able to say that a write failed some other way — a closed handle, a
    full disk — and ``None`` is not available to it because raising is what it
    may not do. A sink that can lose an event therefore exposes an integer
    attribute ``sink_errors`` counting **the writes it returned from without
    raising and did not record**. :class:`JsonlSink` does; :class:`NullSink` and
    :class:`MemorySink` cannot lose anything and so do not.

    It is a convention rather than a protocol member on purpose: the protocol is
    ``runtime_checkable`` and a data member would make ``isinstance`` answer
    false for a user's perfectly good three-method sink.
    :func:`~backstop.ledger.export.delivery_report` and
    :meth:`BoundedWriter.close` read it with ``getattr`` and default it to zero,
    so a sink with no counter is asked nothing.
    """

    def write(self, event: SpendEvent) -> None:
        """Record one event. Must not block for long and must not raise."""

    def flush(self) -> None:
        """Push buffered records onward. Must not raise."""

    def close(self) -> None:
        """Release resources. Called once, at shutdown, and must not raise."""


class NullSink:
    """A sink that records nothing, for a disabled ledger.

    The three methods are empty bodies, so ``write`` costs a call and a
    ``return None`` — the cheapest thing Python can do while still being a
    callable the ledger can hold. This is the default, so a process that never
    turns the ledger on pays that and nothing else.
    """

    __slots__ = ()

    def write(self, event: SpendEvent) -> None:
        """Discard the event."""

    def flush(self) -> None:
        """Nothing is buffered."""

    def close(self) -> None:
        """Nothing is held."""

    def __repr__(self) -> str:
        return "NullSink()"


class MemorySink:
    """The last ``maxlen`` events, in a bounded ring.

    This is what ``backstop ledger demo`` and the tests read: no file, no I/O, no
    parsing. The ring evicts oldest-first, so what survives is the most recent
    window of traffic and nothing grows without bound.

    The ring deliberately outlives :meth:`close`. A caller that closes the writer
    and then reads the ring to print a table is doing the supported thing, so
    ``close`` releases nothing and clears nothing; :meth:`clear` is the explicit
    way to drop what was recorded.
    """

    def __init__(self, maxlen: int = DEFAULT_MEMORY_EVENTS) -> None:
        if isinstance(maxlen, bool) or not isinstance(maxlen, int):
            raise TypeError(f"maxlen must be an int, got {type(maxlen).__name__}")
        if maxlen < 1:
            raise ValueError(f"maxlen must be >= 1, got {maxlen}")
        self._ring: deque[SpendEvent] = deque(maxlen=maxlen)
        self._maxlen = maxlen
        # One lock for the ring, held only for the append. A reader takes the
        # same lock to copy the ring out, so a snapshot is never a torn view.
        self._lock = threading.Lock()

    @property
    def maxlen(self) -> int:
        """The ring's capacity, i.e. the number of events it can hold."""
        return self._maxlen

    @property
    def events(self) -> tuple[SpendEvent, ...]:
        """The retained events, oldest first, as a snapshot tuple."""
        with self._lock:
            return tuple(self._ring)

    def __len__(self) -> int:
        return len(self._ring)

    def clear(self) -> None:
        """Forget every retained event. The capacity is unchanged."""
        with self._lock:
            self._ring.clear()

    def write(self, event: SpendEvent) -> None:
        """Append the event, evicting the oldest one if the ring is full."""
        with self._lock:
            self._ring.append(event)

    def flush(self) -> None:
        """Nothing is buffered; the ring is the buffer."""

    def close(self) -> None:
        """Release nothing. The ring stays readable on purpose."""

    def __repr__(self) -> str:
        return f"MemorySink(maxlen={self._maxlen}, held={len(self)})"


class JsonlSink:
    """Append-only NDJSON: one JSON object per line, one line per event.

    The durable path. Each line is ``json.dumps(event.to_dict(), sort_keys=True)``
    plus a newline, UTF-8, LF-terminated whatever the platform: ``sort_keys``
    makes a line byte-stable so two runs diff cleanly, and ``\\n`` keeps the file
    one-object-per-line rather than one-object-per-platform-line.

    Every line is flushed as it is written, matching the audit log's discipline,
    so a crash costs the line in flight rather than the whole buffer. ``fsync``
    is available for the case where losing the tail on a *machine* crash is
    unacceptable, and is off by default because it costs a real disk round trip
    per event.

    **Failures degrade, they never raise.** A write that fails increments
    :attr:`sink_errors`, sets :attr:`degraded`, and stops appending. Nothing is
    retried: a retry per write turns a broken sink into a syscall per write, and
    a sink that is broken is a thing an operator fixes, not something the request
    path should keep discovering. The recovery point is a restart, and the
    counter is what tells you it happened.

    **A partial final line is possible, and it is the only corruption this sink
    can cause.** A write interrupted between the kernel accepting part of the
    line and the file being closed leaves a truncated object at the end of the
    file. Because a failed sink stops appending, that fragment is always the
    *last* line and there is exactly one of them. A reader recovers by parsing
    line by line and treating an unparseable final line as a torn write — which
    :meth:`~backstop.ledger.SpendEvent.from_dict` makes detectable rather than
    silent, since a truncated payload is either missing declared fields or fails
    its pattern checks and is refused with a message naming what was wrong. An
    unparseable line anywhere *other* than the end is real corruption and must be
    reported, never skipped.
    """

    def __init__(self, path: str | os.PathLike[str], *, fsync: bool = False) -> None:
        try:
            resolved = os.fspath(path)
        except TypeError as exc:
            raise TypeError(
                f"path must be a str or PathLike, got {type(path).__name__}"
            ) from exc
        if not isinstance(resolved, str) or not resolved:
            raise ValueError(f"path must be a non-empty str, got {resolved!r}")
        self._path = resolved
        self._fsync = bool(fsync)
        self._handle: TextIO | None = None
        self._errors = 0
        self._degraded = False
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        """The file this sink appends to."""
        return self._path

    @property
    def fsync(self) -> bool:
        """Whether every line is also ``os.fsync``-ed. ``False`` by default."""
        return self._fsync

    @property
    def sink_errors(self) -> int:
        """Writes that failed, or were refused because the sink is degraded."""
        with self._lock:
            return self._errors

    @property
    def degraded(self) -> bool:
        """Whether this sink has stopped appending after a failure.

        ``True`` means the file is no longer a complete record of the events
        this process submitted, and stays true until a new sink is built.
        """
        with self._lock:
            return self._degraded

    def write(self, event: SpendEvent) -> None:
        """Append one line. Never raises; a failure degrades and is counted."""
        try:
            line = json.dumps(event.to_dict(), sort_keys=True) + "\n"
        except Exception:
            # Not an expected path — an event cannot serialise to nothing — but
            # a caller that passed a non-event must not get an exception here.
            with self._lock:
                self._errors += 1
                self._degraded = True
            return
        with self._lock:
            if self._handle is None:
                if self._degraded:
                    self._errors += 1
                    return
                self._open_locked()
                if self._handle is None:
                    return  # _open_locked counted it
            try:
                self._handle.write(line)
                self._handle.flush()
                if self._fsync:
                    os.fsync(self._handle.fileno())
            except Exception:
                self._degraded = True
                self._errors += 1
                self._drop_handle_locked()

    def flush(self) -> None:
        """Flush the line buffer, and ``fsync`` when configured. Never raises."""
        with self._lock:
            if self._handle is None:
                return
            try:
                self._handle.flush()
                if self._fsync:
                    os.fsync(self._handle.fileno())
            except Exception:
                self._degraded = True
                self._errors += 1
                self._drop_handle_locked()

    def close(self) -> None:
        """Flush and close. Idempotent, and never raises."""
        with self._lock:
            if self._handle is None:
                return
            try:
                self._handle.flush()
                if self._fsync:
                    os.fsync(self._handle.fileno())
            except Exception:
                self._degraded = True
                self._errors += 1
            self._drop_handle_locked()

    def _open_locked(self) -> None:
        """Open the file, creating parent directories. Caller holds the lock.

        Opened on the first write rather than in ``__init__`` so that building a
        configured ledger touches no filesystem until there is an event to record,
        and so a bad path degrades the same way a bad write does. A failure here
        is counted exactly once, by this method.
        """
        try:
            parent = os.path.dirname(os.path.abspath(self._path))
            os.makedirs(parent, exist_ok=True)
            self._handle = open(self._path, "a", encoding="utf-8", newline="\n")
        except Exception:
            self._handle = None
            self._degraded = True
            self._errors += 1

    def _drop_handle_locked(self) -> None:
        """Close and forget the handle, so no later write can append after a
        partial one. Caller holds the lock."""
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"JsonlSink(path={self._path!r}, fsync={self._fsync})"


@dataclass(frozen=True)
class CloseReport:
    """What :meth:`BoundedWriter.close` found on the way out.

    The accounting invariant is ``submitted == written + dropped_events +
    sink_errors`` once the writer is closed and the drain finished: every event
    that ever entered :meth:`~BoundedWriter.submit` is in exactly one of those
    three buckets, none is counted twice, and none is missing.

    :attr:`drained` says whether that invariant is being asserted. When it is
    ``False`` the join timed out, :attr:`undrained` events were discarded, and
    the abandoned drain thread may still land one more write, so ``written`` is
    read as "at least this many".

    :attr:`written` counts the writes the sink *returned from*, and
    :attr:`sink_reported_errors` is the subset of those the sink took
    responsibility for and then failed to record — the failures it swallowed
    rather than raised, which :class:`LedgerSink` documents as the optional
    ``sink_errors`` counter. :attr:`landed` is therefore the number of records
    that actually reached storage, and it is the figure to quote next to
    ``submitted``: a sink that cannot write returns from every write, so without
    the subtraction a file that received nothing reports ``written=50`` and
    ``lost=0``. :attr:`lost` folds all three loss buckets through the same
    :func:`lost_events` that :class:`~backstop.ledger.export.DeliveryReport`
    uses, so the shutdown path and the live path cannot disagree.
    """

    submitted: int
    written: int
    dropped_events: int
    sink_errors: int
    #: Events still buffered when the join timed out, discarded rather than
    #: written late.
    undrained: int
    #: Whether the drain thread finished before the join expired.
    drained: bool
    close_timeout_s: float
    #: Writes this sink swallowed: returned from, and did not record. Read once
    #: at close from the sink's own ``sink_errors`` counter, defaulting to zero
    #: for a sink that has none.
    sink_reported_errors: int = 0
    #: Whether the sink says it has stopped appending, read at close. ``False``
    #: for a sink that cannot degrade, which is most of them.
    sink_degraded: bool = False

    @property
    def lost(self) -> int:
        """Events that will never be written: refused, discarded, or failed.

        The same number :attr:`backstop.ledger.export.DeliveryReport.lost` gives
        for the same writer, including the failures a sink counted itself.
        """
        return lost_events(self.dropped_events, self.sink_errors, self.sink_reported_errors)

    @property
    def landed(self) -> int:
        """Events that reached storage: the writes the sink did not lose."""
        return landed_events(self.written, self.sink_reported_errors)


class BoundedWriter:
    """Hands events to a sink from one background thread, without ever blocking.

    The transport calls :meth:`submit` and returns. Everything slow — the lock
    contention with other submitters, the sink's own write, the disk — happens on
    the single daemon thread started lazily by the first accepted submit.

    The buffer is a ``deque(maxlen=N)`` and the fullness check is explicit, so
    overflow *refuses the incoming event* rather than silently evicting the
    oldest one: a refused event is counted and reported by ``submit``'s return
    value, whereas a silent eviction would be a gap with no trace at all. The
    ``maxlen`` is kept as well, so a bug in the check still cannot grow the
    buffer.

    Exactly one drain thread exists per writer. It drains until the buffer is
    empty *and* the writer is closing, so a normal ``close`` loses nothing; a
    close whose join times out discards the backlog and says so.
    """

    def __init__(
        self,
        sink: LedgerSink,
        *,
        maxlen: int = DEFAULT_QUEUE_SIZE,
        close_timeout: float = DEFAULT_CLOSE_TIMEOUT,
    ) -> None:
        for name, value in (("maxlen", maxlen), ("close_timeout", close_timeout)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number, got {type(value).__name__}")
        if maxlen < 1:
            raise ValueError(f"maxlen must be >= 1, got {maxlen}")
        if close_timeout < 0:
            raise ValueError(f"close_timeout must be >= 0, got {close_timeout}")
        self._sink = sink
        self._buffer: deque[SpendEvent] = deque(maxlen=maxlen)
        self._condition = threading.Condition(threading.Lock())
        self._close_timeout = float(close_timeout)
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._report: CloseReport | None = None
        self._submitted = 0
        self._written = 0
        self._dropped_events = 0
        self._sink_errors = 0

    # --- counters. Each takes the lock, so a single-threaded reader sees a
    # --- coherent value; a reader wanting all four at once should call close().

    @property
    def submitted(self) -> int:
        """Every call to :meth:`submit`, including the ones that were refused."""
        with self._condition:
            return self._submitted

    @property
    def written(self) -> int:
        """Events the sink accepted."""
        with self._condition:
            return self._written

    @property
    def dropped_events(self) -> int:
        """Events refused at submit, plus any discarded at an unfinished close."""
        with self._condition:
            return self._dropped_events

    @property
    def sink_errors(self) -> int:
        """Writes that raised out of the sink.

        A sink that swallows its own failures — as :class:`JsonlSink` must —
        reports them on its own ``sink_errors`` instead, so this is the count of
        errors that actually escaped.
        """
        with self._condition:
            return self._sink_errors

    @property
    def backlog(self) -> int:
        """Events buffered and not yet handed to the sink.

        Read without the lock: ``len`` on a ``deque`` is a single C call, and a
        diagnostic that can be blocked by a busy drain thread is no diagnostic.
        """
        return len(self._buffer)

    @property
    def sink(self) -> LedgerSink:
        """The sink being written to."""
        return self._sink

    def submit(self, event: SpendEvent) -> bool:
        """Hand the event to the drain thread. ``True`` if it was accepted.

        Never blocks on the sink and never raises. ``False`` means the event was
        refused — the buffer was full, or the writer is closed — and
        :attr:`dropped_events` has been incremented, so a caller that cares can
        count its own losses and one that does not still leaves a trace.
        """
        condition = self._condition
        try:
            with condition:
                self._submitted += 1
                if self._stopping or len(self._buffer) >= self._buffer.maxlen:
                    self._dropped_events += 1
                    return False
                self._buffer.append(event)
                if self._thread is None:
                    self._start_drain_locked()
                condition.notify()
                return True
        except Exception:
            # Not a path any known input takes: the buffer is bounded and the
            # lock is held for two dict-free operations. Counted rather than
            # lost, because an event that vanishes unaccounted for is the one
            # outcome this component exists to prevent.
            with condition:
                self._dropped_events += 1
            return False

    def close(self) -> CloseReport:
        """Stop the drain thread with a bounded join, then close the sink.

        Idempotent: the first call does the work and every later call returns the
        same report. A sink that is mid-write when the join expires is
        abandoned — the thread is a daemon, so shutdown continues — and its
        backlog is discarded and reported as :attr:`CloseReport.undrained` rather
        than written after ``close`` returned.

        **The sink's own failure count is read here, once, after the drain has
        finished.** A sink that must not raise swallows its failures and counts
        them itself (``sink_errors`` in :class:`LedgerSink`); without this read
        the report says every event was written, because the writer only ever
        saw a ``write`` that returned. It is read *after* the join so the count
        is settled, and *before* the sink's own ``flush``/``close`` so those
        steps — which are not event writes — are not double counted.
        """
        with self._condition:
            if self._report is not None:
                return self._report
            self._stopping = True
            self._condition.notify_all()
            thread = self._thread
        drained = True
        if thread is not None:
            thread.join(self._close_timeout)
            drained = not thread.is_alive()
        sink_reported, sink_degraded = self._sink_own_counters()
        with self._condition:
            undrained = len(self._buffer)
            if undrained:
                self._buffer.clear()
                self._dropped_events += undrained
            report = CloseReport(
                submitted=self._submitted,
                written=self._written,
                dropped_events=self._dropped_events,
                sink_errors=self._sink_errors,
                sink_reported_errors=sink_reported,
                sink_degraded=sink_degraded,
                undrained=undrained,
                drained=drained,
                close_timeout_s=self._close_timeout,
            )
            self._report = report
        # A sink whose flush/close raises is not counted: these counters describe
        # events, and shutdown must complete either way.
        for step in (self._sink.flush, self._sink.close):
            try:
                step()
            except Exception:
                pass
        return report

    def _sink_own_counters(self) -> tuple[int, bool]:
        """The sink's own loss count and degraded flag, read defensively.

        Both are the optional ``sink_errors``/``degraded`` of :class:`LedgerSink`,
        defaulted: a sink with neither cannot have lost an event or stopped
        appending. A counter that is not an integer is read as no counter —
        there is nothing to add — and a sink whose health cannot be *confirmed*
        is reported degraded, so the operator looks rather than assumes. Neither
        read may raise: this runs inside ``close``, which is the one call a
        shutdown is allowed to make, and the reads are made after the join
        precisely so nothing here can be the reason a report never arrives.
        """
        try:
            counter = getattr(self._sink, "sink_errors", 0)
        except Exception:
            counter = 0
        try:
            degraded = bool(getattr(self._sink, "degraded", False))
        except Exception:
            degraded = True
        if isinstance(counter, bool) or not isinstance(counter, int):
            counter = 0
        return max(0, counter), degraded

    def _start_drain_locked(self) -> None:
        """Start the one drain thread. Caller holds the lock."""
        thread = threading.Thread(
            target=_drain, args=(self,), name=DRAIN_THREAD_NAME, daemon=True
        )
        self._thread = thread
        thread.start()

    def __repr__(self) -> str:
        return (
            f"BoundedWriter(sink={self._sink!r}, submitted={self.submitted}, "
            f"written={self.written}, dropped={self.dropped_events}, "
            f"backlog={self.backlog})"
        )


def _drain(writer: BoundedWriter) -> None:
    """Move ``writer``'s buffered events into its sink until it is closed.

    Module level, and a plain function of one argument, so the thread's target
    reads on its own and the writer's own state is not captured in a closure.

    The lock is dropped around ``sink.write`` — that is the whole design: a
    submitter never waits on a slow sink, and a slow sink never holds up the
    submits behind it. The counters are taken under the lock after each write,
    which is off the hot path and therefore cheap to be strict about.
    """
    condition = writer._condition
    while True:
        with condition:
            while not writer._buffer and not writer._stopping:
                condition.wait()
            if not writer._buffer:
                return
            event = writer._buffer.popleft()
        try:
            writer._sink.write(event)
        except Exception:
            with condition:
                writer._sink_errors += 1
        else:
            with condition:
                writer._written += 1
