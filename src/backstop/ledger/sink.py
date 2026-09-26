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
* a :class:`JsonlSink` that cannot write says so through ``degraded`` and stops
  appending, rather than interleaving partial lines into a file a reader trusts;
* :meth:`BoundedWriter.close` reports what was never written, with a bounded join
  so a stalled sink cannot hang shutdown.
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Protocol, runtime_checkable

from .schema import SpendEvent

__all__ = [
    "DEFAULT_MEMORY_EVENTS",
    "LedgerSink",
    "MemorySink",
    "NullSink",
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


