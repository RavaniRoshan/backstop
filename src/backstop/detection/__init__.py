"""Thresholds for runaway-spend detection: what a detector is allowed to be
told, and the validation that refuses a setting which would make it lie.

This package owns the ``backstop.detection`` import name. The configuration
lives first and on its own because it is the part with no dependencies: the four
threshold numbers, the two window bounds, and the two switches. The detector
that reads them is in :mod:`backstop.detection.detector`.

Both defaults here are the inert ones. ``enabled`` is ``False``, so a detector
nobody asked for costs a single boolean test. ``shadow`` is ``True``, so the
first person to switch detection on gets a monitor rather than an enforcement
primitive — a threshold nobody has watched fire is a threshold that will
surprise someone, and the plan's own requirement is that thresholds get tuned
before they bite.
"""
from __future__ import annotations

from .config import (
    DEFAULT_BASELINE_MULTIPLIER,
    DEFAULT_CONTEXT_GROWTH_THRESHOLD,
    DEFAULT_MIN_SAMPLES,
    DEFAULT_RETRY_RATIO_THRESHOLD,
    DEFAULT_VELOCITY_THRESHOLD_USD_PER_MIN,
    DEFAULT_WINDOW_SIZE,
    DetectionConfig,
)

__all__ = [
    "DEFAULT_BASELINE_MULTIPLIER",
    "DEFAULT_CONTEXT_GROWTH_THRESHOLD",
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_RETRY_RATIO_THRESHOLD",
    "DEFAULT_VELOCITY_THRESHOLD_USD_PER_MIN",
    "DEFAULT_WINDOW_SIZE",
    "DetectionConfig",
]
