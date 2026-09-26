"""Runaway-spend detection: four cheap per-submission detectors over a bounded
window of recent spend events.

**This module detects and reports. It does not enforce, and it cannot.** There is
no kill, no cancel, no block, no throttle, and nothing on the request path that
can raise into a caller. The strongest form of that claim is structural, not a
promise: nothing exported here returns a decision that could stop work, and the
only method a caller invokes is :meth:`RunawayDetector.observe`, which returns
a list of records and cannot fail. Auto-kill is deliberately absent from this
build, because killing an agent mid-flight is not a thing you can do safely yet:
a single run can be six to eight hours of work or a multi-day research
trajectory, and a kill switch that cannot resume is worse than no kill switch at
all. Resumability and idempotency have to be designed first. Until they are, a
detector that could destroy in-flight work would be a liability wearing the
cost of a feature.

What is here instead: the four detectors the plan names, each of which turns a
window of recent events for one attribution key into at most one record saying
"this key is doing something unusual, here is the number and here is the
threshold". Deciding what to *do* about a record is the caller's job, and in
the default configuration the caller's job is "log it" — see shadow mode below.

Shadow mode
-----------
``DetectionConfig(shadow=True)`` is the default, and it is the point of the
module. A threshold nobody has watched fire is a threshold that will surprise
someone, so :meth:`RunawayDetector.observe` computes and returns the same
signals in both modes and the *only* difference is bookkeeping: in shadow mode
every signal is additionally recorded in a bounded log and a per-kind counter,
so an operator can read "this key would have been flagged 400 times yesterday,
at what severity, for how much" before deciding that a threshold is wrong. The
signals are returned either way because a record nobody receives is a record
nobody can tune against; enforcement is not this module's decision to make.

The detectors
-------------
All four read one deque of the last ``window_size`` events for a key, and all
four split that deque in half: the older half is the *reference period* and the
recent half is the *current regime*. The split is what makes a ratio meaningful.
A single window cannot distinguish "this key has started sending larger
requests" from "this key has always sent larger requests", because its median
moves with the drift it is supposed to measure — mean-over-shared-median is
mathematically incapable of reporting a sustained step change. Splitting the
window fixes that, and it also keeps the two "this one request is wrong"
detectors honest: a lone spike in the recent half moves the mean by a
twentieth and never reaches a drift threshold, which is what makes drift and
context growth separate signals instead of the same signal twice.

Cost discipline
---------------
:meth:`RunawayDetector.observe` runs once per request, so it is allocation-light,
takes one short lock, and does no I/O, no regex, and no unbounded work. It is a
no-op when ``enabled`` is false. The work it does when enabled is O(window):
one pass to reduce, at most two sorts of at most ``window_size`` floats, and the
mediains that come from them. The clock is read *outside* the lock, so a
caller-supplied ``time_fn`` cannot serialise requests or deadlock against one.
Memory is ``window_size`` samples per distinct attribution key and nothing else
that grows — the shadow log is a bounded ring.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from typing import Any, NamedTuple
from urllib.parse import quote

from ..ledger.schema import Attribution, SpendEvent
from .config import DetectionConfig

__all__ = [
    "SEVERITIES",
    "SEVERITY_CRITICAL_FACTOR",
    "SEVERITY_INFO_FACTOR",
    "SHADOW_LOG_SIZE",
    "SIGNAL_KINDS",
    "UNATTRIBUTED_KEY",
    "DetectionSignal",
    "RunawayDetector",
    "SpendSignal",
    "signal_key",
]

#: The four detectors, in the order :meth:`RunawayDetector.observe` reports them.
SIGNAL_KINDS = ("velocity", "drift", "retry_amplification", "context_growth")

#: Severities, from "look at this" to "something is wrong right now".
SEVERITIES = ("info", "warning", "critical")

#: Past this multiple of a threshold, a signal is ``critical`` rather than
#: ``warning``. A detector that only ever says "warning" is a monitor; the
#: escalation band is what makes it usable in an alert.
SEVERITY_CRITICAL_FACTOR = 4.0

#: Past this multiple of a threshold, a signal is at least ``warning``. Below it
#: the observation has only just crossed and is reported as ``info``, so a
#: threshold tuned to be tight does not turn every request into a page.
SEVERITY_INFO_FACTOR = 1.25

#: The shadow log is a ring, not a buffer: a detector watching a genuinely
#: runaway key would otherwise accumulate one record per event forever.
SHADOW_LOG_SIZE = 256

#: The key for a request that carried no attribution at all.
UNATTRIBUTED_KEY = "unattributed"

_SECONDS_PER_MINUTE = 60.0
_MONEY_PLACES = 6
_RATIO_PLACES = 3

#: The env switch, following ``ShadowCollector``'s ``BACKSTOP_SHADOW``. Reading
#: the environment rather than only the config means a misconfigured detector
#: can be put back into shadow without a redeploy.
_DETECTION_SHADOW_ENV = "BACKSTOP_DETECTION_SHADOW"

_FALSY = ("0", "false", "off", "no")


def signal_key(attribution: Attribution) -> str:
    """Return the stable, hashable, sortable string a signal is filed under.

    Two things need to be true of this string. It must be *stable*, so a signal
    from yesterday and a signal from today filed against the same attribution
    land on the same key and the counters mean something. And it must be
    *injective*, because the alternative — joining ``name=value`` with a bare
    separator — lets a caller-supplied value forge another attribution's key:
    ``team="a|b=c"`` and ``team="a", feature="b=c"`` would collide, and a
    runaway in one team would be filed under another. Every value is therefore
    percent-encoded with nothing left safe, which closes that gap for any value
    at all.

    Fields are emitted in sorted order and only when set, so the key is
    canonical: two equal ``Attribution`` records always produce equal keys. An
    all-``None`` attribution — every call site that has not adopted attribution
    yet — files under :data:`UNATTRIBUTED_KEY` rather than the empty string, so
    "unattributed" reads as a value in a log instead of as a missing field.
    """
    if not isinstance(attribution, Attribution):
        raise TypeError(
            f"attribution must be an Attribution, got {type(attribution).__name__}"
        )
    set_fields = attribution.keys()
    if not set_fields:
        return UNATTRIBUTED_KEY
    return "|".join(
        f"{name}={quote(value, safe='')}" for name, value in sorted(set_fields.items())
    )


def _safe_number(value: Any) -> float:
    """Return ``value`` as a finite, non-negative float, or ``0.0``.

    The ledger already refuses a negative token count, but a detector that
    trusts that is one ``object.__setattr__`` away from dividing by zero or
    comparing against a value no observation can exceed. Every number that
    reaches the window goes through here, which is also why a token count too
    large to become a float — ``float(10**400)`` raises ``OverflowError`` — is
    read as absent rather than propagated.

    ``Decimal`` is accepted explicitly because money in this codebase *is* a
    ``Decimal``: :class:`~backstop.pricing_catalog.CostBreakdown` refuses binary
    floats for exactly the reason this module cannot simply trust a number's
    type. A ``Decimal`` is neither an ``int`` nor a ``float`` subclass, so
    without this branch every priced event reads as unpriced and a velocity can
    never exist — a detector that is silent because of its own type check is the
    worst failure mode available, so it is covered by a test.
    """
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float, Decimal)):
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError):
            return 0.0
        return number if isfinite(number) and number >= 0.0 else 0.0
    return 0.0


def _median(ordered: list[float]) -> float:
    """Return the median of a list already sorted ascending, ``0.0`` if empty."""
    count = len(ordered)
    if count == 0:
        return 0.0
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


@dataclass(frozen=True)
class SpendSignal:
    """The cheap per-submission measurements the four detectors read.

    Computed in one pass over the key's window plus at most two sorts of it, so
    it is O(window) and allocates nothing per event beyond the window entry
    itself. No I/O and no clock beyond the injected one, because this runs on the
    request path.

    Every field is a ratio or an average, never a raw count, so two keys with
    wildly different budgets are compared on the same scale:

    ``cost_velocity_usd_per_min``
        Priced spend in the window divided by the minutes it spans. **Zero when
        the window holds no price at all**, and zero when every event in the
        window landed at the same instant. A request whose model has no
        published price contributes nothing to the numerator — see
        :meth:`RunawayDetector.features` — because inventing a rate to make a
        velocity look measured is the one thing a finance-facing number must
        never do.
    ``tokens_per_request``
        Mean tokens per request over the *recent half* of the window — every
        token the request moved, input plus output plus both cache counts. The
        older half is the reference period that drift compares it against, so
        this is a mean of the regime being measured rather than a mean
        contaminated by the baseline.
    ``input_token_growth_ratio``
        This request's input tokens over the median input tokens of the rest of
        the window. Prior events only, because the current event is the thing
        being measured and including it would halve the very spike it exists to
        catch. Zero when the reference period had no input tokens, since the
        ratio is undefined there rather than infinite.
    ``retry_ratio``
        Mean retries per request across the window. Deliberately a *mean* and
        not a fraction of requests that retried: one request that retried ten
        times is the interesting case, and a fraction would score it the same as
        ten requests that each retried once.
    ``distinct_model_ratio``
        Distinct models over window size, in ``[0.0, 1.0]``. A key thrashing
        between models is worth seeing even though no threshold in
        :class:`~backstop.detection.config.DetectionConfig` acts on it yet.
    ``samples``
        How many events the window holds. Every ratio above is undefined at
        ``0`` samples, and a caller reading ``retry_ratio == 0.0`` has to be
        able to tell "no retries" from "no history".
    """

    cost_velocity_usd_per_min: float
    tokens_per_request: float
    input_token_growth_ratio: float
    retry_ratio: float
    distinct_model_ratio: float
    samples: int

    def __post_init__(self) -> None:
        if isinstance(self.samples, bool) or not isinstance(self.samples, int):
            raise TypeError(
                f"samples must be an int, got {type(self.samples).__name__} "
                f"{self.samples!r}"
            )
        if self.samples < 0:
            raise ValueError(f"samples must be >= 0, got {self.samples}")


@dataclass(frozen=True)
class DetectionSignal:
    """One observation that one key is behaving unusually. **A record, not an
    instruction.**

    This class carries no verdict and no remedy. It says what was measured
    (:attr:`observed`), what it was measured against (:attr:`threshold`), and
    what kind of thing that is (:attr:`kind`). It cannot block, cancel, kill or
    raise: there is no field that names a request, no method that acts, and
    nothing on it a caller could wire into an interrupt. Acting on a record —
    paging, annotating a chargeback, pausing an agent — is the caller's
    decision, and the reason it stays the caller's is in the module docstring:
    an agent run can be hours long, and nothing here knows how to resume one.

    :attr:`kind` is one of :data:`SIGNAL_KINDS` and :attr:`severity` is one of
    :data:`SEVERITIES`; the four detectors are the only producers, and they are
    the only reason those sets are not validated per instance on the hot path.
    Frozen, so a signal can be passed between threads, logged, serialised and
    compared without copying it or worrying that something rewrote it.

    :attr:`key` is a :func:`signal_key` string — stable, hashable and sortable.
    :attr:`occurred_at` is the ``occurred_at`` of the event that produced the
    signal, not the moment the detector noticed, so a signal reads with the
    request it describes.
    """

    kind: str
    severity: str
    key: str
    observed: float
    threshold: float
    detail: str
    occurred_at: str


class _Sample:
    """One event, reduced to the five numbers the detectors need.

    The only allocation :meth:`RunawayDetector.observe` makes per request, and
    the record the reduction loop then walks ``window_size`` times — so it is a
    ``__slots__`` class rather than a ``NamedTuple``. Slot attribute reads are
    the fastest of the three immutable-record options and measured about 40%
    cheaper than named-tuple attribute reads over a full window, which is the
    loop that actually runs on the hot path.

    ``usd`` is the priced total, or ``0.0`` when no price is known; ``priced``
    records which of the two it was, so the velocity detail can say how much of
    the window it was computed from instead of presenting a floor as a
    measurement.
    """

    __slots__ = ("at", "input_tokens", "model", "priced", "retries", "total_tokens", "usd")

    def __init__(
        self,
        at: float,
        usd: float,
        priced: bool,
        total_tokens: float,
        input_tokens: float,
        retries: float,
        model: str,
    ) -> None:
        self.at = at
        self.usd = usd
        self.priced = priced
        self.total_tokens = total_tokens
        self.input_tokens = input_tokens
        self.retries = retries
        self.model = model


class _Reading(NamedTuple):
    """One reduction of a window: the public features plus what details quote.

    The detectors need a few values the public :class:`SpendSignal` does not
    carry — the span, the priced count, the reference medians — so they travel
    together and are computed once, inside the lock, from the same window the
    features came from.
    """

    features: SpendSignal
    span_minutes: float
    priced: int
    retries_total: float
    reference_tokens: float
    reference_input: float
    current_tokens: float
    current_input: float


def _severity(observed: float, threshold: float) -> str:
    """Return the severity for a margin over a threshold.

    Two bands over a common scale, so every detector escalates the same way and
    a threshold tuned tight does not turn every crossing into a page. A
    non-positive threshold has no meaningful margin — a zero threshold fires on
    every event by definition — so it reports ``warning`` rather than computing
    a division-free but meaningless ``critical``.
    """
    if threshold <= 0.0:
        return "warning"
    if observed >= threshold * SEVERITY_CRITICAL_FACTOR:
        return "critical"
    if observed >= threshold * SEVERITY_INFO_FACTOR:
        return "warning"
    return "info"


class RunawayDetector:
    """Four detectors over a bounded window of events per attribution key.

    :meth:`observe` is the whole interface. It appends the event to that key's
    window, and if there is now enough history, returns the signals the four
    detectors raised for it. It never blocks, cancels or raises, and it returns
    an empty list for anything it cannot read — a malformed event, a hostile
    clock, a cost that is not a number. Those are counted in :attr:`errors`
    rather than dropped silently, so a detector that has quietly stopped working
    says so.

    Thread safety
    -------------
    All mutable state is guarded by one non-reentrant :class:`threading.Lock`:
    the per-key windows, the shadow log, the per-kind counters and the error
    count. That is enough because the lock is only ever held for in-memory
    arithmetic on the calling thread's own window — no I/O, no callback into
    caller code, no acquisition order to get wrong, and nothing that could make
    shutdown wait on another thread. Two things are deliberately *outside* it:
    the injected clock, so a user-supplied ``time_fn`` that re-enters the
    detector cannot deadlock a request thread, and the signal sink, so a sink
    that blocks on I/O — or raises — cannot hold the lock every other request
    needs. The detector is called from a background drain thread and from a
    sync request thread, so this is a real requirement rather than a theoretical
    one.

    A key's window is a ``deque(maxlen=window_size)``, so per-key memory is
    capped at construction and cannot grow however long the run continues. The
    number of distinct keys is the one dimension this class does not cap: see
    :meth:`key_count` for the honest statement of what that means.
    """

    def __init__(
        self,
        config: DetectionConfig | None = None,
        *,
        time_fn: Callable[[], float] = time.monotonic,
        signal_sink: object | None = None,
    ) -> None:
        self._config = config if config is not None else DetectionConfig()
        self._time_fn = time_fn
        self._signal_sink = signal_sink
        self._windows: dict[Attribution, deque[_Sample]] = {}
        self._shadow = self.shadow_enabled(self._config.shadow)
        self._log: deque[DetectionSignal] = deque(maxlen=SHADOW_LOG_SIZE)
        self._counts: dict[str, int] = dict.fromkeys(SIGNAL_KINDS, 0)
        self._errors = 0
        self._lock = threading.Lock()

    # -- the interface ----------------------------------------------------

    @staticmethod
    def shadow_enabled(config_shadow: bool) -> bool:
        """Return whether signals are recorded as hypothetical.

        Mirrors :meth:`backstop.rollout.ShadowCollector.enabled`, and reads the
        same way: an explicit ``BACKSTOP_DETECTION_SHADOW`` wins over the config
        in both directions, so a detector turned on by an over-eager config
        edit can be put back into shadow without a redeploy or a restart.
        """
        env = os.getenv(_DETECTION_SHADOW_ENV)
        if env is not None:
            return env.strip().lower() not in _FALSY
        return bool(config_shadow)

    def observe(self, event: SpendEvent) -> list[DetectionSignal]:
        """Record ``event`` and return the signals it raised. Never raises.

        Returns an empty list when the detector is disabled, when the key has
        not yet reached ``min_samples`` — a cold detector is silent, and stays
        silent by construction rather than by luck — and when nothing crossed a
        threshold. The returned list is informational: in shadow mode (the
        default) and in enforcing mode alike, the caller receives records and
        decides what they are worth. There is no code path here that stops a
        request.
        """
        if not self._config.enabled:
            return []
        try:
            return self._observe(event)
        except Exception:
            # The promise is total, not best-effort: a detector that is only
            # safe when the input is well-formed is not safe on a request path.
            # The lock, if held, has already been released by the ``with``
            # inside ``_observe``, so it is safe to take it again here.
            with self._lock:
                self._errors += 1
            return []

    def features(self, attribution: Attribution) -> SpendSignal | None:
        """Return the current measurements for ``attribution``, or ``None``.

        The window's own most recent timestamp is used as "now" rather than the
        clock, so this is a pure read of what the detector already knows: it
        does not depend on when it is called, and it cannot perturb the
        detectors by advancing anything. Off the hot path, and O(window).
        """
        with self._lock:
            window = self._windows.get(attribution)
            if not window:
                return None
            return self._measure(window).features

    def window_len(self, attribution: Attribution) -> int:
        """Return how many events are retained for ``attribution``."""
        with self._lock:
            window = self._windows.get(attribution)
            return 0 if window is None else len(window)

    def key_count(self) -> int:
        """Return how many attribution keys are being tracked.

        Per-key memory is capped at ``window_size`` samples by construction, so
        the detector's total footprint is ``window_size`` times this number. A
        caller with unboundedly many distinct attributions — one per request,
        say — needs to bound it upstream; this class deliberately does not
        evict, because a silently dropped key is a key whose baseline silently
        resets, and a detector that forgets is worse than one that grows.
        """
        with self._lock:
            return len(self._windows)

    def sample_count(self) -> int:
        """Return the total number of retained events across every key.

        This is the detector's memory, counted rather than described, so
        ``sample_count() <= window_size * key_count()`` is a fact a test can
        check rather than a claim about ``deque(maxlen=...)``.
        """
        with self._lock:
            return sum(len(window) for window in self._windows.values())

    def max_window(self) -> int:
        """Return the per-key event bound, the ``deque``'s own ``maxlen``."""
        return self._config.window_size

    def counts(self) -> dict[str, int]:
        """Return signals raised per kind since construction, shadow or not."""
        with self._lock:
            return dict(self._counts)

    def recorded(self) -> tuple[DetectionSignal, ...]:
        """Return the most recent signals, oldest first, bounded by the ring."""
        with self._lock:
            return tuple(self._log)

    @property
    def config(self) -> DetectionConfig:
        """The frozen configuration. Read-only by construction."""
        return self._config

    @property
    def shadow(self) -> bool:
        """Whether signals are being recorded as hypothetical."""
        return self._shadow

    @property
    def errors(self) -> int:
        """How many observations were refused and counted.

        Non-zero means the detector has seen an event or a clock it could not
        read: a tampered record, an unhashable or non-``Attribution``
        attribution, a ``time_fn`` that raised. It is visible on purpose,
        because a detector that quietly stopped working looks exactly like a
        healthy one. A *signal sink* that raises is deliberately not counted
        here — that is telemetry failing, not the detector, and the sink has
        its own visibility.
        """
        with self._lock:
            return self._errors

    # -- internals -------------------------------------------------------

    def _observe(self, event: SpendEvent) -> list[DetectionSignal]:
        # Read the clock before the lock: a caller-supplied ``time_fn`` is
        # caller code, and caller code does not get to serialise the request
        # path or hold a lock this class needs elsewhere.
        now = _safe_number(self._time_fn())
        attribution = getattr(event, "attribution", None)
        if not isinstance(attribution, Attribution):
            # Nothing to key a window on, and inventing an unattributed key
            # would file a real signal under a fiction. Counted, not raised.
            with self._lock:
                self._errors += 1
            return []

        sample = self._sample(event, now)
        with self._lock:
            window = self._windows.get(attribution)
            if window is None:
                window = deque(maxlen=self._config.window_size)
                self._windows[attribution] = window
            window.append(sample)
            if len(window) < self._config.min_samples:
                # A cold detector is silent. Nothing is measured and nothing is
                # allocated past the sample itself.
                return []
            reading = self._measure(window)

        # Signals and the shadow bookkeeping are built outside the lock: signal
        # construction touches a caller-supplied sink, and the lock is the one
        # thing every other request thread needs.
        signals = self._evaluate(event, attribution, reading)
        if signals:
            self._record(signals)
        return signals

    @staticmethod
    def _sample(event: Any, at: float) -> _Sample:
        """Reduce one event to a :class:`_Sample`, refusing nothing loudly."""
        usd, priced = RunawayDetector._usd(event)
        model = getattr(event, "model", None)
        return _Sample(
            at=at,
            usd=usd,
            priced=priced,
            total_tokens=(
                _safe_number(getattr(event, "input_tokens", 0))
                + _safe_number(getattr(event, "output_tokens", 0))
                + _safe_number(getattr(event, "cache_read_tokens", 0))
                + _safe_number(getattr(event, "cache_write_tokens", 0))
            ),
            input_tokens=_safe_number(getattr(event, "input_tokens", 0)),
            retries=_safe_number(getattr(event, "retries", 0)),
            model=model if isinstance(model, str) else "",
        )

    @staticmethod
    def _usd(event: Any) -> tuple[float, bool]:
        """Return ``(total_usd, priced)`` for an event, or ``(0.0, False)``.

        ``False`` is the honest answer for a model with no published price, and
        it is why the numerator of a velocity can be smaller than the real spend
        rather than being padded to look measured. A cost that arrives as a
        mapping or as a decimal *string* is read rather than rejected, because
        both are shapes the ledger's own wire form produces.
        """
        cost = getattr(event, "cost", None)
        if cost is None:
            return (0.0, False)
        if isinstance(cost, dict):
            total = cost.get("total_usd")
        else:
            total = getattr(cost, "total_usd", None)
        if isinstance(total, str):
            try:
                total = float(total)
            except ValueError:
                return (0.0, False)
        number = _safe_number(total)
        return (number, True)

    def _measure(self, window: deque[_Sample]) -> _Reading:
        """Reduce a window to the features and the values the details quote.

        One pass to sum and to lift the two value lists out of the deque, then
        at most two sorts: the older half's tokens for the drift reference
        period, and the rest of the window's input tokens for the
        context-growth reference. Both sorts are over at most ``window_size``
        floats.

        The window is split at ``len // 2``. The split is the whole reason the
        ratios work: over a single shared window the median follows a sustained
        step change, so mean-over-median can never report drift, and a lone
        spike moves a whole-window mean enough to be reported as one.
        """
        count = len(window)
        if count == 0:
            return _Reading(
                SpendSignal(0.0, 0.0, 0.0, 0.0, 0.0, 0), 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0
            )
        first = window[0]
        last = window[-1]
        span_minutes = (last.at - first.at) / _SECONDS_PER_MINUTE
        total_usd = 0.0
        priced = 0
        tokens_total = 0.0
        retries_total = 0.0
        token_values: list[float] = []
        input_values: list[float] = []
        for sample in window:
            total_usd += sample.usd
            if sample.priced:
                priced += 1
            tokens_total += sample.total_tokens
            retries_total += sample.retries
            token_values.append(sample.total_tokens)
            input_values.append(sample.input_tokens)

        velocity = 0.0
        if span_minutes > 0.0 and total_usd > 0.0:
            velocity = total_usd / span_minutes
            if not isfinite(velocity):
                velocity = 0.0

        split = count // 2
        reference_tokens = _median(sorted(token_values[:split]))
        # The recent half is the regime being measured; its mean is the
        # tokens-per-request the drift detector reports.
        tokens_per_request = (tokens_total - sum(token_values[:split])) / (count - split)
        reference_input = _median(sorted(input_values[:-1]))
        growth = 0.0
        if reference_input > 0.0:
            growth = last.input_tokens / reference_input
            if not isfinite(growth):
                growth = 0.0

        return _Reading(
            features=SpendSignal(
                cost_velocity_usd_per_min=velocity,
                tokens_per_request=tokens_per_request,
                input_token_growth_ratio=growth,
                retry_ratio=retries_total / count,
                distinct_model_ratio=len({sample.model for sample in window}) / count,
                samples=count,
            ),
            span_minutes=span_minutes,
            priced=priced,
            retries_total=retries_total,
            reference_tokens=reference_tokens,
            reference_input=reference_input,
            current_tokens=last.total_tokens,
            current_input=last.input_tokens,
        )

    def _evaluate(
        self, event: Any, attribution: Attribution, reading: _Reading
    ) -> list[DetectionSignal]:
        """Run the four detectors and return the signals they raised, in order.

        Every threshold comparison is strictly greater-than, so an observation
        exactly at the threshold is quiet: a threshold is the boundary of
        "unusual", not the first value of it.
        """
        config = self._config
        features = reading.features
        # Collected first, keyed last. Building the key percent-encodes every
        # attribution field, and on the hot path — a healthy key — nothing
        # crosses a threshold, so paying for a key nobody reads would be the
        # single most expensive thing in this method.
        raised: list[tuple[str, float, float, str]] = []

        # 1. velocity — priced spend per minute over the window's real span.
        threshold = config.velocity_threshold_usd_per_min
        if features.cost_velocity_usd_per_min > threshold:
            raised.append((
                "velocity",
                features.cost_velocity_usd_per_min,
                threshold,
                f"${features.cost_velocity_usd_per_min:.{_MONEY_PLACES}f}/min over "
                f"{features.samples} events in "
                f"{reading.span_minutes:.{_MONEY_PLACES}f} min, "
                f"{reading.priced}/{features.samples} priced",
            ))

        # 2. drift — tokens per request in the current regime against the
        #    median of the reference period it drifted away from.
        threshold = config.baseline_multiplier * reading.reference_tokens
        if reading.reference_tokens > 0.0 and features.tokens_per_request > threshold:
            raised.append((
                "drift",
                features.tokens_per_request,
                threshold,
                f"tokens_per_request {features.tokens_per_request:.1f} against "
                f"reference {reading.reference_tokens:.1f} "
                f"(x{features.tokens_per_request / threshold:.{_RATIO_PLACES}f}, "
                f"multiplier {config.baseline_multiplier:g}) over "
                f"{features.samples} events",
            ))

        # 3. retry amplification — mean retries per request, which counts a
        #    single badly-retried request as loudly as ten mildly-retried ones.
        threshold = config.retry_ratio_threshold
        if features.retry_ratio > threshold:
            raised.append((
                "retry_amplification",
                features.retry_ratio,
                threshold,
                f"{reading.retries_total:.1f} retries over {features.samples} events",
            ))

        # 4. context growth — this request's input against the key's own recent
        #    median, which is the runaway-agent shape: each turn appends the
        #    last turn and sends the lot again.
        threshold = config.context_growth_threshold
        if features.input_token_growth_ratio > threshold:
            raised.append((
                "context_growth",
                features.input_token_growth_ratio,
                threshold,
                f"input tokens {reading.current_input:.0f} against reference "
                f"{reading.reference_input:.0f} over {features.samples} events",
            ))

        if not raised:
            return []
        key = signal_key(attribution)
        occurred_at = getattr(event, "occurred_at", "")
        if not isinstance(occurred_at, str):
            occurred_at = ""
        return [
            DetectionSignal(
                kind=kind,
                severity=_severity(observed, threshold),
                key=key,
                observed=observed,
                threshold=threshold,
                detail=detail,
                occurred_at=occurred_at,
            )
            for kind, observed, threshold, detail in raised
        ]

    def _record(self, signals: list[DetectionSignal]) -> None:
        """File signals in the bounded log and the per-kind counters.

        Counted in both modes on purpose. In shadow mode this log is the
        operator's evidence for tuning a threshold; in enforcing mode it is the
        same evidence about real events. The sink is called outside the lock and
        its exceptions are swallowed, exactly as
        :meth:`backstop.rollout.ShadowCollector.record` does — a telemetry sink
        is not allowed to become a reason a request fails.
        """
        with self._lock:
            for signal in signals:
                self._counts[signal.kind] += 1
                self._log.append(signal)
        if self._signal_sink is not None:
            for signal in signals:
                try:
                    self._signal_sink.record(signal)
                except Exception:
                    pass
