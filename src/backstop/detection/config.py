"""Thresholds for runaway-spend detection, and the validation that refuses a
nonsense one.

Every field is defaulted, and the defaults are the safe ones rather than the
interesting ones:

``enabled`` is ``False``
    A detector nobody asked for must cost one boolean test. The transport
    constructs it unconditionally (see :class:`~backstop.detection.detector.RunawayDetector`),
    so "off" has to be the state that does no work.
``shadow`` is ``True``
    Detection has to be tuned before it bites. A threshold nobody has watched
    fire in shadow is a threshold that will, one day, interrupt a six-hour
    research run on its first real burst. So the default reports and never
    enforces, and turning enforcement on is a deliberate edit.

The remaining fields are the four detector thresholds plus the two window
parameters that bound what a detector can remember. A window is bounded by
*count*, not by age: :class:`~backstop.detection.detector.RunawayDetector` keeps
the last ``window_size`` events per attribution key, and derives the elapsed
span from the timestamps it holds. That is what makes velocity testable — the
window is a function of the events, not of when the clock happened to be read —
and it is also what makes memory bounded by ``window_size`` times the number of
distinct attribution keys, with nothing to expire on a timer.

Validation is strict because a silently-wrong threshold is the worst outcome
this module can produce. A negative threshold does not make the detector
*stricter*; it makes it fire on every event, including the ones that should be
quiet. A ``baseline_multiplier`` below 1.0 does not mean "alert earlier", it
means "alert when tokens *fall*". A ``min_samples`` larger than the window is
not a slow detector, it is a detector that can never speak, and it would look
exactly like a healthy one. Each of those is refused at construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

__all__ = [
    "DEFAULT_BASELINE_MULTIPLIER",
    "DEFAULT_CONTEXT_GROWTH_THRESHOLD",
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_RETRY_RATIO_THRESHOLD",
    "DEFAULT_VELOCITY_THRESHOLD_USD_PER_MIN",
    "DEFAULT_WINDOW_SIZE",
    "MIN_BASELINE_MULTIPLIER",
    "MIN_MIN_SAMPLES",
    "MIN_RATIO",
    "MIN_WINDOW_SIZE",
    "DetectionConfig",
]

#: Dollars per minute one key may spend before a velocity signal is raised.
DEFAULT_VELOCITY_THRESHOLD_USD_PER_MIN = 1.0

#: How far tokens-per-request may sit above the reference period before a drift
#: signal is raised. 3.0 is deliberately loose: drift is a *sustained* change
#: of regime, and the single-request spike belongs to context growth.
DEFAULT_BASELINE_MULTIPLIER = 3.0

#: Mean retries per request before a retry-amplification signal is raised.
DEFAULT_RETRY_RATIO_THRESHOLD = 0.5

#: How far one request's input tokens may sit above the key's recent median
#: before a context-growth signal is raised.
DEFAULT_CONTEXT_GROWTH_THRESHOLD = 2.0

#: Events retained per attribution key. Also the memory bound.
DEFAULT_WINDOW_SIZE = 50

#: Events required before any detector may speak.
DEFAULT_MIN_SAMPLES = 8

#: A multiplier below 1.0 inverts the comparison it feeds.
MIN_BASELINE_MULTIPLIER = 1.0

#: A ratio threshold below 0.0 is never crossed by a non-negative observation.
MIN_RATIO = 0.0

#: One event is a legal window; ``min_samples`` is what makes it unusable.
MIN_WINDOW_SIZE = 1

#: One sample of history leaves nothing to compare against: no reference period
#: for drift, no prior median for context growth.
MIN_MIN_SAMPLES = 2


def _check_flag(name: str, value: Any) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool, got {type(value).__name__} {value!r}")


def _check_count(name: str, value: Any, minimum: int) -> None:
    # ``bool`` is an ``int`` subclass, so ``enabled=True`` would otherwise be
    # accepted as a window of one.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__} {value!r}")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")


def _check_number(name: str, value: Any, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{name} must be a number, got {type(value).__name__} {value!r}"
        )
    if not isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return float(value)


@dataclass(frozen=True)
class DetectionConfig:
    """The four thresholds, the two window bounds, and the two switches.

    Frozen, so one config can be shared by every request without a lock and
    cannot be re-tuned underneath a running detector — a threshold that changes
    mid-window makes two signals from the same burst incomparable.

    The instance is also the only place a threshold can be wrong, so it refuses
    to be wrong: see the module docstring for why a negative ratio, a
    sub-1.0 multiplier, a non-finite number, a zero window and an unreachable
    ``min_samples`` are all construction errors rather than runtime surprises.
    """

    #: Report what *would* have fired and enforce nothing. The safe default.
    shadow: bool = True

    #: Off by default, so the hot path pays a single boolean test.
    enabled: bool = False

    velocity_threshold_usd_per_min: float = DEFAULT_VELOCITY_THRESHOLD_USD_PER_MIN
    baseline_multiplier: float = DEFAULT_BASELINE_MULTIPLIER
    retry_ratio_threshold: float = DEFAULT_RETRY_RATIO_THRESHOLD
    context_growth_threshold: float = DEFAULT_CONTEXT_GROWTH_THRESHOLD

    #: Events retained per attribution key, and the per-key memory bound.
    window_size: int = DEFAULT_WINDOW_SIZE

    #: History required before any detector may speak. A cold detector is silent
    #: by construction rather than by accident.
    min_samples: int = DEFAULT_MIN_SAMPLES

    def __post_init__(self) -> None:
        _check_flag("shadow", self.shadow)
        _check_flag("enabled", self.enabled)
        _check_number(
            "velocity_threshold_usd_per_min",
            self.velocity_threshold_usd_per_min,
            MIN_RATIO,
        )
        _check_number("baseline_multiplier", self.baseline_multiplier, MIN_BASELINE_MULTIPLIER)
        _check_number("retry_ratio_threshold", self.retry_ratio_threshold, MIN_RATIO)
        _check_number("context_growth_threshold", self.context_growth_threshold, MIN_RATIO)
        _check_count("window_size", self.window_size, MIN_WINDOW_SIZE)
        _check_count("min_samples", self.min_samples, MIN_MIN_SAMPLES)
        if self.min_samples > self.window_size:
            raise ValueError(
                f"min_samples must be <= window_size, got min_samples={self.min_samples} "
                f"window_size={self.window_size}; a window that can never hold the "
                f"samples it needs is a detector that can never speak"
            )
