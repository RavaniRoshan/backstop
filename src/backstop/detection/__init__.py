"""Runaway-spend detection for the ledger: a bounded window of recent spend
events per attribution, four detectors over it, and a shadow mode that reports
without enforcing.

This package is a *reporting* package. It measures four ways a key can be
spending unusually — velocity, drift, retry amplification, context growth — and
hands the caller a record when one of them crosses a threshold. It cannot block
a request, cancel work, or kill an agent, and nothing here raises on the request
path. That is not an omission waiting to be filled in: killing an agent run
mid-flight is unsafe until resumption is designed, because a run can be six to
eight hours of work or a multi-day research trajectory, and a kill switch that
cannot resume destroys it. See :mod:`backstop.detection.detector` for the full
argument.

The default configuration is therefore inert twice over: ``enabled=False`` so the
hot path pays one boolean test, and ``shadow=True`` so a detector that has been
switched on reports what it *would* have flagged without that report being
allowed to decide anything. Thresholds get tuned against the shadow log before
anyone considers acting on a signal, and acting on a signal stays the caller's
decision.
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
from .detector import (
    SEVERITIES,
    SEVERITY_CRITICAL_FACTOR,
    SEVERITY_INFO_FACTOR,
    SHADOW_LOG_SIZE,
    SIGNAL_KINDS,
    UNATTRIBUTED_KEY,
    DetectionSignal,
    RunawayDetector,
    SpendSignal,
    signal_key,
)

__all__ = [
    "DEFAULT_BASELINE_MULTIPLIER",
    "DEFAULT_CONTEXT_GROWTH_THRESHOLD",
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_RETRY_RATIO_THRESHOLD",
    "DEFAULT_VELOCITY_THRESHOLD_USD_PER_MIN",
    "DEFAULT_WINDOW_SIZE",
    "SEVERITIES",
    "SEVERITY_CRITICAL_FACTOR",
    "SEVERITY_INFO_FACTOR",
    "SHADOW_LOG_SIZE",
    "SIGNAL_KINDS",
    "UNATTRIBUTED_KEY",
    "DetectionConfig",
    "DetectionSignal",
    "RunawayDetector",
    "SpendSignal",
    "signal_key",
]
