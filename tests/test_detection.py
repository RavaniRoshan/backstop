"""Tests for runaway-spend detection: the four detectors, the shadow mode, the
config validation, and the promise that nothing here can stop work.

Every signal in this file is produced by an injected clock rather than by
waiting. ``RunawayDetector`` takes a ``time_fn`` precisely so that a burst of
expensive requests is a burst of *timestamps* rather than a burst of wall-clock
time, which means the velocity test is exact instead of approximate and cannot
pass for the wrong reason on a loaded machine.

The two claims this module rests on are asserted structurally rather than by
construction. That it cannot enforce anything is checked by walking the exported
API for a verb that could act on a request, because a docstring is a promise
and a test is a fact. That it cannot fail is checked by feeding it every kind of
malformed, boundary and hostile input and asserting ``observe`` returns rather
than raises.

The hot-path claims are measured, not asserted: steady-state ``observe`` is
timed, memory is bounded by observation rather than by reading ``maxlen``, and
four threads are put on one detector to check the lock is really doing the work
it claims to.
"""
from __future__ import annotations

import threading
import time
from decimal import Decimal
from fractions import Fraction
from typing import Any, NamedTuple

import pytest

from backstop.detection import (
    SEVERITIES,
    SEVERITY_CRITICAL_FACTOR,
    SEVERITY_INFO_FACTOR,
    SHADOW_LOG_SIZE,
    SIGNAL_KINDS,
    UNATTRIBUTED_KEY,
    DetectionConfig,
    DetectionSignal,
    RunawayDetector,
    SpendSignal,
    signal_key,
)
from backstop.ledger import Attribution, CostBreakdown, SpendEvent

# ---------------------------------------------------------------------------
# fixtures and builders
# ---------------------------------------------------------------------------

QUANTUM = Decimal("0.000001")
PAYMENTS = Attribution(team="payments", feature="checkout-v2")
SUPPORT = Attribution(team="support", feature="refunds")


class Clock:
    """An injected monotonic clock the test advances by hand.

    Named rather than inlined as a list so that every test needing a burst
    reads as one, and so nothing in this file can depend on real time passing.
    """

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class Harness(NamedTuple):
    """A detector and the clock driving it, so a test never reads a private."""

    detector: RunawayDetector
    clock: Clock

    def observe(self, event: Any) -> list[DetectionSignal]:
        return self.detector.observe(event)

    def at(self, seconds: float, event: Any) -> list[DetectionSignal]:
        """Advance to ``seconds`` and observe ``event`` there."""
        self.clock.advance(seconds)
        return self.detector.observe(event)


def harness(config: DetectionConfig | None = None, **kwargs: Any) -> Harness:
    """Build an enabled detector on a manual clock, unless told otherwise."""
    clock = Clock()
    settings = config if config is not None else DetectionConfig(enabled=True)
    return Harness(RunawayDetector(settings, time_fn=clock, **kwargs), clock)


def make_event(**overrides: Any) -> SpendEvent:
    """Build a valid event; ``overrides`` replaces individual fields."""
    fields: dict[str, Any] = {
        "provider": "openai",
        "model": "gpt-4o",
        "endpoint": "/v1/chat/completions",
        "priority": "default",
        "outcome": "success",
        "input_tokens": 1000,
        "output_tokens": 200,
        "estimated": False,
        "attribution": PAYMENTS,
    }
    fields.update(overrides)
    return SpendEvent(**fields)


def make_cost(total: str) -> CostBreakdown:
    """Build a real :class:`CostBreakdown` for exactly ``total`` USD.

    A detector test should not depend on a price catalog: what is under test is
    "a priced event at this cost", not "what gpt-4o costs today". The total is
    spread across the input and output components, which is what a priced event
    looks like, so ``total_usd`` is the sum of its parts.
    """
    amount = Decimal(total)
    half = (amount / 2).quantize(QUANTUM)
    return CostBreakdown(
        input_usd=half,
        output_usd=(amount - half).quantize(QUANTUM),
        cache_read_usd=Decimal("0.000000"),
        cache_write_usd=Decimal("0.000000"),
        total_usd=amount.quantize(QUANTUM),
        currency="USD",
        price_source="bundled",
        estimated_tokens=False,
        priced_components=frozenset({"input", "output"}),
    )


def priced_event(usd: str = "5.000000", **overrides: Any) -> SpendEvent:
    """Build a priced event costing exactly ``usd``."""
    return make_event(cost=make_cost(usd), **overrides)


def tokens_of(total: int) -> dict[str, int]:
    """Split a token total 80/20, the shape the drift tests measure in."""
    return {"input_tokens": int(total * 0.8), "output_tokens": int(total * 0.2)}


def kinds(signals: list[DetectionSignal]) -> list[str]:
    return [signal.kind for signal in signals]


def only(signals: list[DetectionSignal], kind: str) -> DetectionSignal:
    """Return the one signal of ``kind``, failing loudly if there is not exactly one."""
    matching = [signal for signal in signals if signal.kind == kind]
    assert matching, f"expected a {kind} signal, got {kinds(signals)}"
    assert len(matching) == 1, f"expected exactly one {kind}, got {kinds(signals)}"
    return matching[0]


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def test_detection_config_defaults_to_disabled_and_shadowed():
    """The safe defaults: off, and reporting-only if switched on.

    Both are load-bearing. ``enabled=False`` keeps a detector nobody asked for
    off the request path. ``shadow=True`` means the first person to switch it on
    gets a monitor, not an enforcement primitive; a default of ``shadow=False``
    would make "turn detection on" mean "turn interruption on", which is the
    failure mode the whole package exists to avoid.
    """
    config = DetectionConfig()
    assert config.enabled is False
    assert config.shadow is True
    assert config.velocity_threshold_usd_per_min == 1.0
    assert config.baseline_multiplier == 3.0
    assert config.retry_ratio_threshold == 0.5
    assert config.context_growth_threshold == 2.0
    assert config.window_size == 50
    assert config.min_samples == 8


def test_detection_config_is_frozen():
    """A threshold cannot be re-tuned under a running detector.

    Two signals from the same burst are only comparable if the threshold they
    were measured against was the same for both.
    """
    config = DetectionConfig()
    with pytest.raises(Exception):
        config.enabled = True  # type: ignore[misc]


@pytest.mark.parametrize("field", ["shadow", "enabled"])
def test_detection_config_rejects_non_bool_flags(field: str):
    """``enabled=1`` is not ``enabled=True``.

    Truthiness would let a config carrying ``enabled: 1`` pass, and a flag is
    exactly the field where "probably meant" is not good enough.
    """
    with pytest.raises(TypeError, match="must be a bool"):
        DetectionConfig(**{field: 1})


@pytest.mark.parametrize("value", [0, -1, -50])
def test_detection_config_rejects_a_non_positive_window(value: int):
    """A window of zero retains nothing, so no detector could ever speak."""
    with pytest.raises(ValueError, match="window_size must be >= 1"):
        DetectionConfig(window_size=value)


def test_detection_config_rejects_min_samples_below_two():
    """One sample of history leaves no reference period and no prior median.

    Drift compares the recent half of the window against the older half, and
    context growth compares this request against the rest of the window; either
    needs two events before either ratio means anything.
    """
    with pytest.raises(ValueError, match="min_samples must be >= 2"):
        DetectionConfig(min_samples=1)


def test_detection_config_rejects_min_samples_above_window_size():
    """An unreachable sample count is a detector that can never speak.

    It would also look exactly like a healthy one: no signals, no errors, and a
    log that reads clean. Refusing it at construction is the only place the
    mistake is visible.
    """
    with pytest.raises(ValueError, match="min_samples must be <= window_size"):
        DetectionConfig(window_size=10, min_samples=11)
    with pytest.raises(ValueError, match="min_samples must be <= window_size"):
        # A one-event window is positive but unusable, and is rejected here.
        DetectionConfig(window_size=1)


@pytest.mark.parametrize("value", [0.99, 0.5, 0.0, -1.0, -0.001])
def test_detection_config_rejects_a_baseline_multiplier_below_one(value: float):
    """A multiplier under 1.0 does not mean "alert earlier".

    It inverts the comparison it feeds: the detector would raise drift signals
    when tokens-per-request *fell*, which is the opposite of the intended
    reading and would page an operator about an improvement.
    """
    with pytest.raises(ValueError, match="baseline_multiplier must be >= 1.0"):
        DetectionConfig(baseline_multiplier=value)


def test_detection_config_accepts_a_baseline_multiplier_of_exactly_one():
    """1.0 is the boundary of the rule, not a violation of it."""
    assert DetectionConfig(baseline_multiplier=1.0).baseline_multiplier == 1.0


THRESHOLD_FIELDS = [
    "velocity_threshold_usd_per_min",
    "baseline_multiplier",
    "retry_ratio_threshold",
    "context_growth_threshold",
]


@pytest.mark.parametrize("field", THRESHOLD_FIELDS)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_detection_config_rejects_non_finite_thresholds(field: str, value: float):
    """A non-finite threshold silently disables or makes unreachable a comparison.

    ``nan > x`` is false for every ``x``, so a NaN threshold switches a detector
    off with no error and no signal; ``inf`` makes it unable to fire at all.
    Both look exactly like a healthy key.
    """
    with pytest.raises(ValueError, match="must be finite"):
        DetectionConfig(**{field: value})


@pytest.mark.parametrize("field", THRESHOLD_FIELDS)
def test_detection_config_rejects_negative_thresholds(field: str):
    """A negative threshold does not make a detector stricter.

    The observations here are ratios and non-negative amounts, so a negative
    threshold is crossed by everything: the detector would raise a signal on
    every single request, which is how an alerting system gets switched off.
    """
    with pytest.raises(ValueError, match=f"{field} must be >= "):
        DetectionConfig(**{field: -0.001})


@pytest.mark.parametrize("field", THRESHOLD_FIELDS + ["window_size", "min_samples"])
@pytest.mark.parametrize("value", ["1.0", None, object(), 1.5j])
def test_detection_config_rejects_non_numeric_thresholds(field: str, value: Any):
    """A string that looks like a number is refused, not coerced.

    ``"0.5" > 1.0`` would be a ``TypeError`` at request time on the hot path
    rather than at construction, which is the worst place to find it.
    """
    with pytest.raises((TypeError, ValueError), match="must be (a number|an int)"):
        DetectionConfig(**{field: value})


def test_detection_config_rejects_a_bool_written_as_a_window():
    """``bool`` is an ``int`` subclass, so ``window_size=True`` must not pass."""
    with pytest.raises(TypeError, match="window_size must be an int"):
        DetectionConfig(window_size=True)


# ---------------------------------------------------------------------------
# signal keys
# ---------------------------------------------------------------------------


def test_signal_key_is_stable_hashable_and_comparable():
    """A key has to survive a day, a dict, and a sort.

    Stability is what makes the counters mean anything across a restart, and
    comparability is what lets an operator sort a day's signals by key.
    """
    key = signal_key(PAYMENTS)
    assert key == signal_key(Attribution(team="payments", feature="checkout-v2"))
    assert key == "feature=checkout-v2|team=payments"
    assert hash(key) == hash(signal_key(PAYMENTS))
    assert {key: 1}[signal_key(PAYMENTS)] == 1
    assert sorted([signal_key(SUPPORT), key]) == sorted([key, signal_key(SUPPORT)])


def test_signal_key_escapes_separators_so_attributions_cannot_collide():
    """A caller-supplied value must not be able to forge another key.

    Without escaping, ``team="a|b=c"`` and ``team="a", feature="b=c"`` produce
    the same key, and a runaway in one team is filed under another — the
    specific failure per-key isolation exists to prevent.
    """
    forged = signal_key(Attribution(team="a|b=c"))
    honest = signal_key(Attribution(team="a", feature="b=c"))
    assert forged != honest
    assert "%" in forged
    assert forged == "team=a%7Cb%3Dc"


def test_signal_key_for_an_unattributed_record():
    """An all-``None`` attribution is a value, not a missing field."""
    assert signal_key(Attribution()) == UNATTRIBUTED_KEY


def test_signal_key_rejects_a_non_attribution():
    with pytest.raises(TypeError, match="must be an Attribution"):
        signal_key({"team": "payments"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# velocity
# ---------------------------------------------------------------------------


def test_velocity_fires_on_a_burst_of_expensive_events():
    """Four $5 requests inside a second is $4000/minute, and that is a burst."""
    h = harness(DetectionConfig(enabled=True, window_size=8, min_samples=4))
    seen: list[float] = []
    for _ in range(4):
        signals = h.at(0.1, priced_event("5.000000"))
        seen.extend(s.observed for s in signals if s.kind == "velocity")
    assert seen, "a burst of expensive events must trip velocity"
    # $20 across 0.3 seconds, i.e. 0.005 minutes.
    assert seen[-1] == pytest.approx(4000.0, rel=1e-3)
    signal = only(h.at(0.1, priced_event("5.000000")), "velocity")
    assert signal.severity == "critical"
    assert signal.key == signal_key(PAYMENTS)


def test_the_velocity_detail_does_not_print_a_float_rate_as_six_place_money():
    """A rate derived from a float, rendered with the precision of a measurement.

    ``SpendSignal.cost_velocity_usd_per_min`` is a sum of binary floats divided
    by a float span, so six decimal places of it were not just more precision
    than the arithmetic has — they were a wrong digit. Three events of
    $12.345670 across exactly 3600 seconds are $0.6172835 per minute, which
    rounds to 0.617284, and the float's sixth place printed 0.617283. The
    detail is prose for a person: it now states the rate at the money precision
    the rest of this product renders dollars at, and the exact float is still on
    the signal as ``observed``.
    """
    h = harness(
        DetectionConfig(
            enabled=True, window_size=8, min_samples=3, velocity_threshold_usd_per_min=0.0
        )
    )
    for moment in (0.0, 1800.0, 3600.0):
        h.clock.now = moment
        signals = h.observe(priced_event("12.345670"))

    signal = only(signals, "velocity")
    # 3 x $12.345670 over 3600 seconds is 60 minutes, so 37.037010 / 60.
    assert Fraction(Decimal("12.345670") * 3) / 60 == Fraction(3703701, 6_000_000)
    # The float's own sixth place disagrees with the exact figure, which is the
    # whole reason the detail does not print one.
    assert f"{signal.observed:.6f}" == "0.617283"
    assert Decimal("0.617284") != Decimal(f"{signal.observed:.6f}")

    assert "$0.62/min over 3 events in 60.000000 min, 3/3 priced" == signal.detail
    # The measurement beside it keeps its places: 0.005 of a minute is real.
    assert "60.000000 min" in signal.detail
    # And the machine-readable value is untouched — nothing was rounded away.
    assert signal.observed == pytest.approx(0.6172835, rel=1e-12)
    assert signal.observed == signal.observed  # a float, as the dataclass declares


def test_velocity_does_not_fire_when_the_same_spend_is_spread_over_time():

    """Six $5 requests over fifty minutes is $6/hour, and nobody is in trouble.

    This is the pair that makes the detector useful rather than a spend-total
    alarm: the same rate of spending as :func:`test_velocity_fires_on_a_burst_of
    _expensive_events`, with the opposite verdict, decided entirely by the
    elapsed span of the window.
    """
    h = harness(DetectionConfig(enabled=True, window_size=8, min_samples=4))
    for _ in range(6):
        signals = h.at(600.0, priced_event("5.000000"))
        assert kinds(signals) == [], f"slow spend must be quiet, got {kinds(signals)}"
    features = h.detector.features(PAYMENTS)
    assert features is not None
    # $30 across 3000 seconds, i.e. 50 minutes.
    assert features.cost_velocity_usd_per_min == pytest.approx(0.6, rel=1e-3)


def test_velocity_is_silent_when_every_event_in_the_window_is_unpriced():
    """No price means no velocity, and the detector says so rather than guessing.

    Inventing a rate to make the number look measured is the one thing a
    finance-facing figure must never do. The honest output is a floor, and the
    signal's own detail reports how much of the window it was computed from.
    """
    h = harness(
        DetectionConfig(
            enabled=True,
            window_size=8,
            min_samples=4,
            velocity_threshold_usd_per_min=0.0,
        )
    )
    for _ in range(4):
        signals = h.at(0.01, make_event(model="unpriced-model"))
        assert kinds(signals) == [], f"an unpriced burst has no velocity, got {kinds(signals)}"
    features = h.detector.features(PAYMENTS)
    assert features is not None
    assert features.cost_velocity_usd_per_min == 0.0
    assert h.detector.errors == 0


def test_an_unpriced_event_still_reports_the_signals_it_can():
    """No cost does not mean no signal: the token-based detectors still have data.

    This is the "observe what it can" half. Refusing the event outright would
    lose context growth, drift and retry amplification for every model a user
    has not priced — which is exactly the tail a runaway tends to live in.
    """
    h = harness(
        DetectionConfig(
            enabled=True, window_size=8, min_samples=4, context_growth_threshold=2.0
        )
    )
    seen: list[list[str]] = []
    for input_tokens in (1000, 1000, 1000, 5000):
        seen.append(kinds(h.at(1.0, make_event(input_tokens=input_tokens))))
    assert "context_growth" in seen[3]
    features = h.detector.features(PAYMENTS)
    assert features is not None
    assert features.cost_velocity_usd_per_min == 0.0


def test_velocity_of_a_single_instant_is_zero_rather_than_a_division_error():
    """Every event at the same timestamp has an elapsed span of zero.

    That is a real state — a tight retry loop observed within one clock tick —
    and dividing by its span is how a detector manufactures an infinity and
    pages an operator about it.
    """
    h = harness(DetectionConfig(enabled=True, window_size=4, min_samples=2))
    h.clock.now = 12.5
    h.observe(priced_event("5.000000"))
    assert kinds(h.observe(priced_event("5.000000"))) == []
    features = h.detector.features(PAYMENTS)
    assert features is not None
    assert features.cost_velocity_usd_per_min == 0.0


@pytest.mark.parametrize(
    "cost",
    [{"total_usd": "5.000000"}, {"total_usd": Decimal("5.000000")}],
    ids=["mapping-of-strings", "mapping-of-decimals"],
)
def test_velocity_reads_the_shapes_a_rehydrated_cost_arrives_in(cost: Any):
    """The ledger's own wire form is a mapping of decimal *strings*.

    A detector that only understood a live :class:`CostBreakdown` would go blind
    on every event that had been through a sink, which is most of them by the
    time anyone reads a ledger file.
    """
    h = harness(DetectionConfig(enabled=True, window_size=4, min_samples=2))
    h.at(0.1, make_event(cost=cost))
    h.at(0.1, make_event(cost=cost))
    features = h.detector.features(PAYMENTS)
    assert features is not None
    # $10 across 0.1 seconds, i.e. 0.001667 minutes.
    assert features.cost_velocity_usd_per_min == pytest.approx(6000.0, rel=1e-3)


# ---------------------------------------------------------------------------
# drift
# ---------------------------------------------------------------------------


def test_drift_fires_when_tokens_per_request_sustains_above_the_multiplier():
    """A sustained doubling of request size is drift, and drift is a regime change.

    The reference period is the older half of the window, so a shift that
    settles in is compared against what the key used to send, rather than
    against a median that has already followed it. That is why the signal waits
    for the current regime to occupy the recent half rather than firing on the
    first oversized request: two big requests out of ten is not a regime, it is
    context growth.
    """
    h = harness(
        DetectionConfig(
            enabled=True,
            window_size=10,
            min_samples=8,
            baseline_multiplier=1.5,
            context_growth_threshold=100.0,
        )
    )
    seen: list[tuple[int, list[str]]] = []
    for index in range(15):
        total = 1000 if index < 10 else 2000
        seen.append((index, kinds(h.at(1.0, make_event(**tokens_of(total))))))
    fired = [index for index, got in seen if "drift" in got]
    assert fired == [12, 13, 14], f"drift fired on the wrong events: {fired}"
    signal = only(h.at(1.0, make_event(**tokens_of(2000))), "drift")
    assert signal.observed == pytest.approx(2000.0)
    assert signal.threshold == pytest.approx(1500.0)


def test_drift_ignores_a_single_spike_that_context_growth_owns():
    """One three-fold request is not a new regime, and must not be reported as one.

    This is the separation that makes both detectors worth having. A sustained
    2x regime is drift and not context growth; a single 3x request is context
    growth and not drift. Reporting either twice is how a threshold gets
    dismissed as noisy. (A spike large enough to genuinely drag the recent
    half's mean — 60x here — does trip both, and should.)
    """
    h = harness(
        DetectionConfig(enabled=True, window_size=10, min_samples=8, baseline_multiplier=1.5)
    )
    for _ in range(12):
        h.at(1.0, make_event(**tokens_of(1000)))
    assert kinds(h.at(1.0, make_event(**tokens_of(3000)))) == ["context_growth"]
    assert kinds(h.at(1.0, make_event(**tokens_of(60_000)))) == ["drift", "context_growth"]


def test_drift_stays_quiet_for_a_flat_key():
    """A key that never changes size is not drifting, whatever the multiplier.

    At 1.0 the comparison is exact, so any noise at all would show up here. The
    assertion is that a constant key produces nothing.
    """
    h = harness(
        DetectionConfig(enabled=True, window_size=8, min_samples=4, baseline_multiplier=1.0)
    )
    for _ in range(20):
        assert "drift" not in kinds(h.at(1.0, make_event(**tokens_of(1000))))


# ---------------------------------------------------------------------------
# retry amplification
# ---------------------------------------------------------------------------


def test_retry_amplification_fires_on_a_high_retry_ratio():
    """A key averaging 0.8 retries per request is amplifying someone else's failure."""
    h = harness(
        DetectionConfig(
            enabled=True, window_size=8, min_samples=4, retry_ratio_threshold=0.5
        )
    )
    seen: list[list[str]] = []
    for retries in (0, 0, 0, 2, 2):
        seen.append(kinds(h.at(1.0, make_event(retries=retries))))
    assert "retry_amplification" not in seen[3], (
        "a ratio sitting exactly on the threshold is the boundary of unusual, "
        "not the first value of it"
    )
    assert "retry_amplification" in seen[4]
    signal = only(h.at(1.0, make_event(retries=0)), "retry_amplification")
    assert signal.observed == pytest.approx(4 / 6)
    assert signal.threshold == 0.5


def test_retry_amplification_counts_one_badly_retried_request_loudly():
    """Mean retries, not the fraction of requests that retried.

    A fraction scores "ten requests that each retried once" and "one request
    that retried ten times" identically. The second is the one that burned the
    budget.
    """
    h = harness(
        DetectionConfig(
            enabled=True, window_size=4, min_samples=2, retry_ratio_threshold=0.5
        )
    )
    h.at(1.0, make_event(retries=0))
    signal = only(h.at(1.0, make_event(retries=10)), "retry_amplification")
    assert signal.observed == pytest.approx(5.0)


def test_retry_amplification_is_quiet_for_a_healthy_key():
    h = harness(
        DetectionConfig(
            enabled=True, window_size=8, min_samples=4, retry_ratio_threshold=0.5
        )
    )
    for index in range(20):
        assert "retry_amplification" not in kinds(
            h.at(1.0, make_event(retries=index % 2))
        )


# ---------------------------------------------------------------------------
# context growth
# ---------------------------------------------------------------------------


def test_context_growth_fires_when_input_tokens_grow_after_a_prompt_change():
    """The runaway-agent shape: each turn appends the last turn and resends it.

    The reference is the median of the *other* events in the window, so the
    request being measured does not contribute to the thing it is measured
    against — which is what lets a single five-fold jump be reported at its full
    size instead of being halved by its own presence.
    """
    h = harness(
        DetectionConfig(
            enabled=True, window_size=8, min_samples=4, context_growth_threshold=2.0
        )
    )
    seen: list[list[str]] = []
    for input_tokens in (1000, 1000, 1000, 5000):
        seen.append(kinds(h.at(1.0, make_event(input_tokens=input_tokens))))
    assert seen[:3] == [[], [], []], "a cold key cannot grow"
    assert "context_growth" in seen[3]
    signal = only(h.at(1.0, make_event(input_tokens=5000)), "context_growth")
    assert signal.observed == pytest.approx(5.0)
    assert signal.threshold == 2.0


def test_context_growth_stays_quiet_when_the_reference_period_had_no_input_tokens():
    """A ratio against a zero median is undefined, not infinite.

    Firing here would mean every key that starts sending input tokens gets a
    context-growth signal on its first real request.
    """
    h = harness(
        DetectionConfig(
            enabled=True, window_size=4, min_samples=2, context_growth_threshold=1.0
        )
    )
    for input_tokens in (0, 0, 5000):
        assert "context_growth" not in kinds(
            h.at(1.0, make_event(input_tokens=input_tokens))
        )
    features = h.detector.features(PAYMENTS)
    assert features is not None
    assert features.input_token_growth_ratio == 0.0


# ---------------------------------------------------------------------------
# min_samples, key isolation, enabled
# ---------------------------------------------------------------------------


def test_a_cold_detector_is_silent_until_it_has_min_samples():
    """Silence before there is history, by construction rather than by luck.

    A detector that fires on its first event is reporting a baseline of nothing
    against a threshold, which is how a threshold gets tuned on noise. So the
    five events here are *extreme* — if anything could fire it would be these —
    and the fifth differs only in size, which is what context growth measures.
    """
    h = harness(
        DetectionConfig(
            enabled=True, window_size=8, min_samples=5, context_growth_threshold=1.0
        )
    )
    for index in range(4):
        assert h.at(1.0, make_event(input_tokens=10_000_000)) == [], (
            f"a cold detector must be silent, but event {index} raised a signal"
        )
    # A ten-fold jump is large enough to be both a spike and a regime change.
    assert kinds(h.at(1.0, make_event(input_tokens=100_000_000))) == [
        "drift",
        "context_growth",
    ]
    assert h.detector.window_len(PAYMENTS) == 5


def test_a_disabled_detector_is_a_no_op_and_remembers_nothing():
    """Off means off: no measurement, no window, no allocation per request.

    This is the default, and the transport builds a detector whether or not one
    was asked for, so this branch is the one every untouched request takes.
    """
    det = RunawayDetector(DetectionConfig(), time_fn=Clock())
    for _ in range(50):
        assert det.observe(priced_event("1000.000000")) == []
    assert det.key_count() == 0
    assert det.sample_count() == 0
    assert det.counts() == dict.fromkeys(SIGNAL_KINDS, 0)
    assert det.recorded() == ()
    assert det.features(PAYMENTS) is None
    assert det.errors == 0


def test_a_runaway_in_one_team_does_not_implicate_another():
    """Windows are keyed by attribution, so one team's spend is not another's problem.

    Both keys see the same events; only the key that spent the money has a
    window full of it. This is also why the window is keyed by
    :class:`Attribution` rather than by a string: a frozen dataclass cannot be
    built two ways that should resolve to the same key.
    """
    h = harness(DetectionConfig(enabled=True, window_size=8, min_samples=4))
    flagged: list[list[str]] = []
    for _ in range(5):
        flagged.append(kinds(h.at(0.1, priced_event("5.000000"))))
    # The first three are cold; from the fourth the burst is unmistakable.
    assert all(seen == [] for seen in flagged[:3])
    assert all("velocity" in seen for seen in flagged[3:]), flagged
    assert kinds(h.at(0.1, priced_event("0.000001", attribution=SUPPORT))) == []
    assert h.detector.key_count() == 2
    assert h.detector.window_len(PAYMENTS) == 5
    assert h.detector.window_len(SUPPORT) == 1
    features = h.detector.features(SUPPORT)
    assert features is not None
    assert features.cost_velocity_usd_per_min == 0.0
    assert features.samples == 1


def test_features_reports_the_rolling_measurements_for_a_key():
    """Every feature the detectors read is readable by a caller too.

    A threshold is tuned against numbers, so the numbers have to be gettable
    without a signal being raised. The read is pure — it uses the window's own
    timestamp — so calling it cannot change what the detectors say next.
    """
    h = harness(DetectionConfig(enabled=True, window_size=4, min_samples=2))
    h.at(1.0, make_event(input_tokens=800, output_tokens=200, retries=1, model="m1"))
    h.at(1.0, make_event(input_tokens=800, output_tokens=200, retries=3, model="m2"))
    features = h.detector.features(PAYMENTS)
    assert isinstance(features, SpendSignal)
    assert features.samples == 2
    assert features.tokens_per_request == pytest.approx(1000.0)
    assert features.retry_ratio == pytest.approx(2.0)
    assert features.input_token_growth_ratio == pytest.approx(1.0)
    assert features.distinct_model_ratio == pytest.approx(1.0)
    assert h.detector.features(PAYMENTS) == features


def test_features_distinguishes_one_model_from_several():
    """``distinct_model_ratio`` is a thrash signal waiting for a threshold."""
    h = harness(DetectionConfig(enabled=True, window_size=4, min_samples=2))
    for model in ("m1", "m2", "m1", "m2"):
        h.at(1.0, make_event(model=model))
    features = h.detector.features(PAYMENTS)
    assert features is not None
    assert features.distinct_model_ratio == pytest.approx(0.5)


def test_features_for_an_unknown_key_is_none():
    assert harness().detector.features(Attribution(team="nobody")) is None


# ---------------------------------------------------------------------------
# shadow mode
# ---------------------------------------------------------------------------


def test_shadow_detector_reports_signals_but_never_blocks():
    """The default mode produces every signal and stops nothing.

    "Never blocks" is asserted the only way it can honestly be: by driving a
    detector that is deliberately firing on every single event, and showing the
    events keep being observed, the window keeps advancing, and the return value
    is a list of records rather than a verdict.
    """
    h = harness(
        DetectionConfig(enabled=True, shadow=True, window_size=8, min_samples=2)
    )
    assert h.detector.shadow is True
    raised = 0
    for index in range(200):
        signals = h.at(
            0.001,
            priced_event("500.000000", input_tokens=100_000 + index, output_tokens=1_000),
        )
        assert isinstance(signals, list)
        assert all(isinstance(signal, DetectionSignal) for signal in signals)
        raised += len(signals)
        # The work continued: every one of the 200 events was recorded.
        assert h.detector.window_len(PAYMENTS) == min(index + 1, 8)
    # Every event from the second onwards fires; only the cold first one cannot.
    assert raised >= 199, f"a detector firing on every event signalled only {raised} times"
    assert h.detector.counts()["velocity"] >= 199


def test_enforcing_detector_reports_the_same_signals_as_shadow():
    """Shadow changes bookkeeping, not arithmetic.

    If the two modes disagreed about a signal, the shadow log — the evidence
    used to tune a threshold — would be describing a detector that does not
    exist. The same events are replayed into both detectors, so the comparison
    includes the timestamp each signal was stamped with.
    """
    events = [
        priced_event("5.000000", **tokens_of(1000 if index < 8 else 9000), retries=index % 3)
        for index in range(12)
    ]

    def run(shadow: bool) -> list[tuple[str, float, float, str, str]]:
        h = harness(
            DetectionConfig(enabled=True, shadow=shadow, window_size=8, min_samples=4)
        )
        out: list[tuple[str, float, float, str, str]] = []
        for event in events:
            for signal in h.at(0.05, event):
                out.append(
                    (signal.kind, signal.observed, signal.threshold, signal.severity,
                     signal.occurred_at)
                )
        return out

    shadowed = run(True)
    enforcing = run(False)
    assert shadowed
    assert shadowed == enforcing


def test_shadow_env_switch_forces_shadow_off(monkeypatch: pytest.MonkeyPatch):
    """The environment wins over the config, in both directions.

    A detector switched on by an over-eager config edit has to be put back into
    shadow without a redeploy, which is the same escape hatch
    :class:`~backstop.rollout.ShadowCollector` offers.
    """
    h = harness(DetectionConfig(enabled=True, shadow=True))
    assert h.detector.shadow is True
    monkeypatch.setenv("BACKSTOP_DETECTION_SHADOW", "false")
    assert RunawayDetector.shadow_enabled(True) is False
    monkeypatch.setenv("BACKSTOP_DETECTION_SHADOW", "0")
    assert RunawayDetector.shadow_enabled(False) is False
    monkeypatch.setenv("BACKSTOP_DETECTION_SHADOW", "true")
    assert RunawayDetector.shadow_enabled(False) is True
    monkeypatch.delenv("BACKSTOP_DETECTION_SHADOW")
    assert RunawayDetector.shadow_enabled(True) is True
    assert RunawayDetector.shadow_enabled(False) is False


def test_shadow_log_is_bounded_and_counts_are_per_kind():
    """A runaway key must not make the detector itself the thing that grows.

    The log is a ring of :data:`SHADOW_LOG_SIZE`; the counters are the durable
    total. A log that grew one record per event would turn the component
    watching a runaway into a second unbounded structure.
    """
    h = harness(
        DetectionConfig(
            enabled=True,
            window_size=4,
            min_samples=2,
            velocity_threshold_usd_per_min=0.0,
            baseline_multiplier=1.0,
            retry_ratio_threshold=0.0,
            context_growth_threshold=0.0,
        )
    )
    for index in range(SHADOW_LOG_SIZE * 3):
        h.at(0.001, priced_event("5.000000", input_tokens=1000 + index, retries=index % 2))
    assert len(h.detector.recorded()) == SHADOW_LOG_SIZE
    counts = h.detector.counts()
    assert set(counts) == set(SIGNAL_KINDS)
    assert all(count > 0 for count in counts.values())
    assert sum(counts.values()) > len(h.detector.recorded()), (
        "the counters must outlast the ring, or a wrapped log loses the totals"
    )
    # Oldest first, so a log that has wrapped is still in order.
    stamps = [signal.occurred_at for signal in h.detector.recorded()]
    assert stamps == sorted(stamps)


def test_module_exposes_no_enforcement_primitive():
    """Nothing exported here can stop a request, by construction rather than by promise.

    A docstring saying "this does not kill anything" is a claim. Walking the
    exported API for a verb that could act on a request is a fact, and it fails
    the build if someone later adds a ``kill()``, a ``should_block()`` or a
    ``cancel()`` and wires it up.
    """
    import backstop.detection as package

    forbidden = (
        "allow", "block", "cancel", "deny", "denial", "enforce", "halt",
        "kill", "pause", "stop", "throttle",
    )
    exported = [name for name in package.__all__ if not name.isupper()]
    offenders = [
        f"{name}"
        for name in exported
        for verb in forbidden
        if verb in name.lower()
    ]
    assert offenders == [], f"detection must not export an enforcement verb: {offenders}"
    for name in exported:
        member = getattr(package, name)
        if isinstance(member, type):
            methods = [
                f"{name}.{attr}"
                for attr in dir(member)
                if not attr.startswith("_")
                for verb in forbidden
                if verb in attr.lower()
            ]
            assert methods == [], f"detection must not expose an enforcement method: {methods}"
    # The one entry point a caller has returns records, and that is the claim.
    assert callable(RunawayDetector.observe)
    assert set(DetectionSignal.__dataclass_fields__) == {
        "kind", "severity", "key", "observed", "threshold", "detail", "occurred_at",
    }


def test_all_four_detectors_report_and_stay_in_the_declared_vocabulary():
    """A record that leaves the declared vocabulary cannot be aggregated.

    ``severity`` is what an operator routes on, so a typo there is a signal that
    goes nowhere. Every detector is made to fire in one run, with every
    threshold at its floor.
    """
    h = harness(
        DetectionConfig(
            enabled=True,
            window_size=4,
            min_samples=2,
            velocity_threshold_usd_per_min=0.0,
            baseline_multiplier=1.0,
            retry_ratio_threshold=0.0,
            context_growth_threshold=1.0,
        )
    )
    seen_kinds: set[str] = set()
    for index in range(30):
        for signal in h.at(
            0.001,
            priced_event("5.000000", input_tokens=1000 + index * 10, retries=index),
        ):
            assert signal.kind in SIGNAL_KINDS
            assert signal.severity in SEVERITIES
            assert signal.observed > signal.threshold
            assert signal.detail
            assert signal.occurred_at.endswith("Z")
            seen_kinds.add(signal.kind)
    assert seen_kinds == set(SIGNAL_KINDS), f"only saw {sorted(seen_kinds)}"


def test_a_signal_carries_the_timestamp_of_the_event_it_describes():
    """A signal reads with its request, not with the moment it was noticed.

    The detector's clock is advanced arbitrarily far past both events, so a
    signal that used the reading clock would be wildly wrong. The event's own
    ``occurred_at`` is the one that matters to somebody reading the log next
    day, and it is the only one that is independent of this process.
    """
    h = harness(DetectionConfig(enabled=True, window_size=4, min_samples=2))
    h.clock.now = 1_000_000.0
    first = priced_event("500000.000000")
    h.at(1.0, first)
    second = priced_event("500000.000000", input_tokens=900_000)
    h.clock.now = 9_000_000.0
    signal = only(h.detector.observe(second), "velocity")
    assert signal.occurred_at == second.occurred_at
    assert signal.occurred_at != first.occurred_at


@pytest.mark.parametrize(
    ("input_tokens", "expected"),
    [
        (2200, "info"),  # 2.2x, inside the info band
        (3000, "warning"),  # 3.0x
        (12000, "critical"),  # 12x, past the critical band
    ],
)
def test_severity_escalates_with_the_margin_over_the_threshold(
    input_tokens: int, expected: str
):
    """Severity is a function of how far past the threshold, not of the kind.

    One rule for all four detectors means an operator learns one banding rather
    than four, and a threshold tuned tight does not turn every crossing into a
    page.
    """
    h = harness(
        DetectionConfig(
            enabled=True, window_size=2, min_samples=2, context_growth_threshold=2.0
        )
    )
    h.at(1.0, make_event(input_tokens=1000))
    signal = only(h.at(1.0, make_event(input_tokens=input_tokens)), "context_growth")
    assert signal.observed == pytest.approx(input_tokens / 1000)
    assert signal.severity == expected


def test_severity_bands_are_ordered_and_non_overlapping():
    assert 1.0 < SEVERITY_INFO_FACTOR < SEVERITY_CRITICAL_FACTOR
    assert SEVERITIES == ("info", "warning", "critical")


# ---------------------------------------------------------------------------
# bounded memory and hot-path cost
# ---------------------------------------------------------------------------


def test_window_memory_is_bounded_by_window_size_per_key():
    """Memory is observed, not asserted from ``maxlen``.

    Five thousand events on one key, then a hundred each on three more, and the
    retained window is exactly ``window_size`` for every key. A deque without a
    bound is the classic way a per-request component becomes an OOM.
    """
    h = harness(DetectionConfig(enabled=True, window_size=16, min_samples=8))
    assert h.detector.max_window() == 16
    for _ in range(5000):
        h.at(0.001, priced_event())
    assert h.detector.window_len(PAYMENTS) == 16
    for team in ("a", "b", "c"):
        attribution = Attribution(team=team)
        for _ in range(100):
            h.at(0.001, priced_event(attribution=attribution))
        assert h.detector.window_len(attribution) == 16
    assert h.detector.key_count() == 4
    assert h.detector.sample_count() == 4 * 16


def test_observe_steady_state_cost_stays_inside_the_overhead_class() -> None:
    """Measured, not asserted by construction, with both paths timed.

    Three paths, because they cost different amounts and all three matter. The
    *disabled* path is the one every untouched request takes, since the
    transport builds a detector whether or not one was asked for. The *quiet*
    path is a healthy key that crosses nothing. The *firing* path is a priced
    key on a burst, where every call also builds a record and percent-encodes
    the signal key — the most expensive thing this module does, and the reason
    the key is built only once a signal exists.

    The bound is a whole per-request overhead class rather than a tight figure,
    because the point of the test is to catch a regression that adds a sleep, a
    file, a regex compile or a pass over unbounded work — not to pin the
    machine.
    """
    quiet = [
        make_event(attribution=Attribution(team=f"team-{i % 8}"))
        for i in range(2000)
    ]
    firing = [priced_event(attribution=Attribution(team=f"team-{i % 8}")) for i in range(2000)]
    calls = 20_000

    def measure(events: list[SpendEvent], config: DetectionConfig) -> float:
        det = RunawayDetector(config, time_fn=time.monotonic)
        for event in events[:200]:
            det.observe(event)
        start = time.perf_counter()
        for index in range(calls):
            det.observe(events[index % len(events)])
        return (time.perf_counter() - start) / calls * 1e6

    disabled_us = measure(quiet, DetectionConfig())
    quiet_us = measure(quiet, DetectionConfig(enabled=True))
    firing_us = measure(firing, DetectionConfig(enabled=True))

    print(
        f"\n  observe: disabled {disabled_us:.2f}us, "
        f"enabled/quiet {quiet_us:.2f}us, enabled/firing {firing_us:.2f}us"
    )
    assert disabled_us < 5.0, f"a disabled detector must be free, cost {disabled_us:.2f}us"
    assert quiet_us < 100.0, f"observe cost {quiet_us:.1f}us escaped the budget"
    assert firing_us < 100.0, f"firing cost {firing_us:.1f}us escaped the budget"
    # The disabled path is a boolean test and nothing else.
    assert disabled_us * 20 < quiet_us, "the enabled check is not short-circuiting"


def test_concurrent_observe_is_safe_and_stays_bounded() -> None:
    """The transport calls this from a drain thread and from a request thread.

    Four threads hammering overlapping and distinct keys must produce no
    exception, no lost accounting, and no window over its bound. The windows are
    per key, so a thread cannot grow another's.
    """
    det = RunawayDetector(
        DetectionConfig(enabled=True, window_size=12, min_samples=2),
        time_fn=time.monotonic,
    )
    keys = [Attribution(team=f"team-{i}") for i in range(4)]
    failures: list[BaseException] = []
    barrier = threading.Barrier(len(keys))

    def drain(worker: int) -> None:
        try:
            barrier.wait(timeout=30.0)
            for index in range(500):
                det.observe(
                    priced_event(
                        "5.000000",
                        attribution=keys[(worker + index) % len(keys)],
                        input_tokens=1000 + index % 7,
                        retries=index % 4,
                    )
                )
        except BaseException as exc:  # noqa: BLE001 - the failure under test
            failures.append(exc)

    threads = [threading.Thread(target=drain, args=(i,)) for i in range(len(keys))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60.0)
        assert not thread.is_alive(), "a drain thread did not finish"

    assert failures == [], f"concurrent observe raised: {failures!r}"
    assert det.errors == 0
    assert det.key_count() == 4
    assert det.sample_count() == 4 * 12
    assert sum(det.counts().values()) > 0, "nothing was detected at all"


# ---------------------------------------------------------------------------
# a signal sink may not become a failure
# ---------------------------------------------------------------------------


def test_a_signal_sink_that_raises_never_reaches_the_caller() -> None:
    """Telemetry is not allowed to become a reason a request fails.

    The sink is called outside the lock, so a sink that blocks on I/O cannot
    hold the lock every other request thread needs, and a sink that raises is
    swallowed exactly as :meth:`~backstop.rollout.ShadowCollector.record` does.
    """

    class Exploding:
        def __init__(self) -> None:
            self.seen: list[DetectionSignal] = []

        def record(self, signal: DetectionSignal) -> None:
            self.seen.append(signal)
            raise RuntimeError("sink is down")

    sink = Exploding()
    h = harness(
        DetectionConfig(
            enabled=True,
            window_size=4,
            min_samples=2,
            context_growth_threshold=0.0,
        ),
        signal_sink=sink,
    )
    # Two events are needed before a ratio exists; the second one grows 5x.
    assert kinds(h.at(1.0, make_event(input_tokens=1000))) == []
    assert kinds(h.at(1.0, make_event(input_tokens=5000))) != []
    assert kinds(h.at(1.0, make_event(input_tokens=5000))) != []
    assert len(sink.seen) >= 2
    assert h.detector.errors == 0
    assert h.detector.counts()["context_growth"] >= 2


# ---------------------------------------------------------------------------
# adversarial input: observe is total
# ---------------------------------------------------------------------------

JUNK_EVENTS: list[Any] = [
    None, 0, 1, -1, 3.5, True, "", b"bytes", "text", [], {}, set(), (),
    object(), type, Ellipsis, NotImplemented,
]

EXTREME_CONFIGS = [
    DetectionConfig(enabled=True),
    DetectionConfig(enabled=True, window_size=2, min_samples=2),
    DetectionConfig(
        enabled=True,
        window_size=2,
        min_samples=2,
        velocity_threshold_usd_per_min=0.0,
        baseline_multiplier=1.0,
        retry_ratio_threshold=0.0,
        context_growth_threshold=0.0,
    ),
    DetectionConfig(
        enabled=True,
        window_size=4,
        min_samples=2,
        velocity_threshold_usd_per_min=1e308,
        baseline_multiplier=1e308,
    ),
]
CONFIG_IDS = ["default", "minimal", "every-threshold-at-floor", "every-threshold-huge"]


@pytest.mark.parametrize("junk", JUNK_EVENTS, ids=lambda value: type(value).__name__)
@pytest.mark.parametrize("config", EXTREME_CONFIGS, ids=CONFIG_IDS)
def test_observe_never_raises_for_a_non_event(config: DetectionConfig, junk: Any):
    """Input that is not an event at all is refused, not fatal.

    A detector that is only safe on well-formed input is not safe on a request
    path, and the refusal is counted rather than dropped silently — a detector
    that has quietly stopped working looks exactly like a healthy one.
    """
    det = RunawayDetector(config, time_fn=time.monotonic)
    assert det.observe(junk) == []
    # A real event still works afterwards, so one bad record does not wedge it.
    assert isinstance(det.observe(priced_event()), list)


def _tamper(event: SpendEvent, name: str, value: Any) -> SpendEvent:
    """Corrupt a frozen event the way a bug or a hostile caller would."""
    object.__setattr__(event, name, value)
    return event


TAMPERED_FIELDS: list[tuple[str, Any]] = [
    ("cost", "not a cost"),
    ("cost", 0),
    ("cost", {"total_usd": None}),
    ("cost", {"total_usd": "not a number"}),
    ("cost", {"total_usd": ""}),
    ("cost", type("NoTotal", (), {"total_usd": Decimal("NaN")})()),
    ("cost", type("NoTotal", (), {"total_usd": Decimal("Infinity")})()),
    ("cost", type("NoTotal", (), {"total_usd": "5.000000"})()),
    ("cost", type("NoTotal", (), {})()),
    ("cost", type("NoTotal", (), {"total_usd": None})()),
    ("input_tokens", 10**400),
    ("input_tokens", -1),
    ("input_tokens", "1000"),
    ("input_tokens", None),
    ("output_tokens", float("inf")),
    ("retries", -5),
    ("retries", 10**400),
    ("model", None),
    ("model", 42),
    ("occurred_at", None),
    ("occurred_at", 12345),
]


@pytest.mark.parametrize(
    ("field", "value"), TAMPERED_FIELDS, ids=[f"{f}={type(v).__name__}" for f, v in TAMPERED_FIELDS]
)
def test_observe_never_raises_for_a_tampered_event(field: str, value: Any):
    """A frozen record can still be corrupted from outside.

    ``SpendEvent`` validates at construction, which is a strong guarantee and
    not an absolute one: ``object.__setattr__`` reaches past it, a rehydrated
    record may come from somewhere else, and a future field may be missed by the
    validator. None of those may become a failed request.
    """
    h = harness(DetectionConfig(enabled=True, window_size=4, min_samples=2))
    for _ in range(6):
        signals = h.at(0.01, _tamper(priced_event(), field, value))
        assert isinstance(signals, list)
        for signal in signals:
            assert signal.kind in SIGNAL_KINDS
    assert isinstance(h.detector.features(PAYMENTS), SpendSignal)


def test_observe_never_raises_for_an_unhashable_attribution():
    """An unhashable attribution field cannot break the window lookup.

    The window dict is keyed by ``Attribution``, which is hashable *as the
    ledger builds it*. A corrupted one raises inside the lookup, and that has to
    stay inside :meth:`observe`.
    """
    det = RunawayDetector(
        DetectionConfig(enabled=True, window_size=4, min_samples=2), time_fn=time.monotonic
    )
    unhashable = _tamper(make_event(), "attribution", Attribution())
    object.__setattr__(unhashable.attribution, "team", ["not", "hashable"])
    for _ in range(6):
        assert det.observe(unhashable) == []
    # A tampered attribution is refused, not filed under a fiction.
    assert det.key_count() == 0
    assert det.errors > 0


def test_observe_never_raises_for_a_non_string_attribution_field():
    """A hashable but non-string field is kept; the key builder refuses it.

    The event is still observed — the token detectors work fine without a
    readable label — and only the key of a raised signal is refused, which the
    total-error path absorbs and counts. Degrading to "this key is
    unlabelable" beats crashing the request or filing it under a wrong team.
    """
    det = RunawayDetector(
        DetectionConfig(
            enabled=True, window_size=4, min_samples=2, context_growth_threshold=0.0
        ),
        time_fn=time.monotonic,
    )
    for _ in range(6):
        assert isinstance(det.observe(_tamper(make_event(), "attribution", _bad_field())), list)
    assert det.errors > 0
    assert det.key_count() == 1


def _bad_field() -> Attribution:
    record = Attribution()
    object.__setattr__(record, "team", 12345)
    return record


HOSTILE_CLOCKS: list[Any] = [
    lambda: float("nan"),
    lambda: float("inf"),
    lambda: float("-inf"),
    lambda: 0,
    lambda: -1e18,
    lambda: 10**300,
    lambda: "not a number",
    lambda: None,
    lambda: object(),
    lambda: (_ for _ in ()).throw(RuntimeError("clock is down")),
]
CLOCK_IDS = ["nan", "inf", "-inf", "zero", "negative", "huge", "string", "none", "object", "raises"]


@pytest.mark.parametrize("clock", HOSTILE_CLOCKS, ids=CLOCK_IDS)
def test_observe_never_raises_for_a_hostile_clock(clock: Any):
    """A bad reading is a detector with no elapsed span, not a failed request.

    Every non-numeric reading raises inside the span arithmetic; every
    non-monotonic one makes the span zero or negative. Both have to resolve to
    "no velocity", because the alternative is an exception on the request path
    of someone who injected a clock.
    """
    det = RunawayDetector(
        DetectionConfig(enabled=True, window_size=4, min_samples=2), time_fn=clock
    )
    for _ in range(8):
        assert isinstance(det.observe(priced_event("5.000000")), list)
    assert det.key_count() <= 1
    features = det.features(PAYMENTS)
    if features is not None:
        assert features.cost_velocity_usd_per_min == 0.0


def test_observe_never_raises_when_a_field_lookup_raises():
    """A property that raises is a refused event, not a failed one."""

    class Hostile:
        model = "gpt-4o"
        input_tokens = 1000
        output_tokens = 200
        cache_read_tokens = 0
        cache_write_tokens = 0
        retries = 0
        cost = None
        occurred_at = "2026-01-01T00:00:00.000000Z"

        @property
        def attribution(self) -> Any:
            raise RuntimeError("no attribution for you")

    det = RunawayDetector(
        DetectionConfig(enabled=True, window_size=4, min_samples=2), time_fn=time.monotonic
    )
    for _ in range(8):
        assert det.observe(Hostile()) == []
    assert det.errors > 0
    assert det.key_count() == 0


def test_observe_returns_a_list_for_a_stream_of_random_malformed_records() -> None:
    """A deterministic fuzz sweep: six hundred hostile events, no escapes.

    Seeded, so a failure is reproducible. The generator mixes valid events with
    every kind of corruption in a random order, through one detector whose
    window therefore fills with a mixture of real numbers and nonsense. What
    matters is that the return value is always a list of well-formed signals and
    that the window never exceeds its bound however hostile the input is.
    """
    import random

    rng = random.Random(20260926)
    det = RunawayDetector(
        DetectionConfig(
            enabled=True, window_size=8, min_samples=2, context_growth_threshold=0.5
        ),
        time_fn=time.monotonic,
    )
    hostile: list[Any] = [
        None, -1, 0, 10**400, float("nan"), float("inf"), "1000", b"x", [], {},
        Decimal("NaN"), Decimal("5.000000"), object(),
    ]
    teams = [Attribution(team=f"team-{i}") for i in range(4)]
    for _ in range(600):
        roll = rng.random()
        if roll < 0.15:
            event: Any = rng.choice(JUNK_EVENTS)
        elif roll < 0.45:
            event = priced_event(
                "5.000000",
                attribution=teams[rng.randrange(len(teams))],
                input_tokens=rng.randrange(0, 5_000_000),
                retries=rng.randrange(0, 4),
            )
        else:
            event = priced_event(
                "5.000000", attribution=teams[rng.randrange(len(teams))]
            )
            event = _tamper(
                event,
                rng.choice(["input_tokens", "output_tokens", "retries", "model", "cost"]),
                rng.choice(hostile),
            )
        signals = det.observe(event)
        assert isinstance(signals, list)
        for signal in signals:
            assert signal.kind in SIGNAL_KINDS
            assert signal.severity in SEVERITIES
            assert signal.observed > signal.threshold
    assert det.key_count() <= len(teams) + 1
    assert det.sample_count() <= det.key_count() * 8
