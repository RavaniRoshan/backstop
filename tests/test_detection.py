"""Tests for the runaway-detection thresholds: the safe defaults, and the
validation that refuses a setting which would make a detector silently useless.

The thresholds are the part of detection a user is most likely to get wrong, and
every way of getting them wrong here fails *quietly* rather than loudly: a NaN
compares false against everything, a negative threshold is crossed by
everything, a multiplier below one inverts the comparison it feeds, and a
``min_samples`` larger than the window produces a detector that can never speak
while looking perfectly healthy. None of those raise at request time. All of
them are refused at construction, and each refusal has a test that names the
mistake it prevents.
"""
from __future__ import annotations

from typing import Any

import pytest

from backstop.detection import DetectionConfig


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
