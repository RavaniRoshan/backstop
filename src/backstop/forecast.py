"""Cost forecasting + anomaly detection (Deep Research P1#7).

Burns the token budget at a measured rate and projects exhaustion, breaking the
"observability tools observe but never act" gap by turning ledger data into an
enforcement-triggering signal: when the projected burn breaches the horizon, the
caller can trip the circuit or tighten the budget. Pure functions over simple
inputs so they work with or without Prometheus.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BurnSample:
    used_tokens: int
    window_seconds: float

    @property
    def rate_per_sec(self) -> float:
        if self.window_seconds <= 0:
            return 0.0
        return self.used_tokens / self.window_seconds


def project_remaining_seconds(sample: BurnSample, total_tokens: int) -> float:
    """Seconds until the budget is exhausted at the current burn rate."""
    if sample.rate_per_sec <= 0:
        return float("inf")
    remaining = max(0, total_tokens - sample.used_tokens)
    return remaining / sample.rate_per_sec


def will_exhaust(sample: BurnSample, total_tokens: int, horizon_seconds: float) -> bool:
    return project_remaining_seconds(sample, total_tokens) <= horizon_seconds


def detect_spend_anomaly(
    baseline_rate: float,
    current_rate: float,
    sensitivity: float = 2.0,
) -> bool:
    """True when the current burn rate exceeds ``sensitivity`` x the baseline."""
    if baseline_rate <= 0:
        return current_rate > 0
    return current_rate >= sensitivity * baseline_rate


@dataclass
class CostForecaster:
    total_tokens: int

    def forecast(self, recent_used: int, recent_window: float, horizon_seconds: float) -> dict:
        sample = BurnSample(recent_used, recent_window)
        remaining = project_remaining_seconds(sample, self.total_tokens)
        return {
            "total_tokens": self.total_tokens,
            "used_tokens": recent_used,
            "rate_per_sec": sample.rate_per_sec,
            "projected_remaining_seconds": remaining,
            "will_exhaust_within_horizon": will_exhaust(sample, self.total_tokens, horizon_seconds),
        }
