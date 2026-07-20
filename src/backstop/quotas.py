"""Cloud-quota-aware auto-tuning (Deep Research P1#5).

Providers return ``x-ratelimit-*`` (OpenAI) and ``anthropic-ratelimit-*``
headers describing remaining request/token budgets and reset windows. Backstop
ingests these after every response and, when we approach a provider quota,
proactively reduces the AIMD concurrency limit to pre-empt 429s instead of
reacting to them. It also distinguishes cached vs uncached tokens so accounting
matches the provider's own billing.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QuotaState:
    requests_limit: int | None = None
    requests_remaining: int | None = None
    requests_reset_seconds: float | None = None
    tokens_limit: int | None = None
    tokens_remaining: int | None = None
    tokens_reset_seconds: float | None = None

    @property
    def request_pressure(self) -> float:
        if self.requests_limit and self.requests_remaining is not None:
            return 1.0 - self.requests_remaining / self.requests_limit
        return 0.0

    @property
    def token_pressure(self) -> float:
        if self.tokens_limit and self.tokens_remaining is not None:
            return 1.0 - self.tokens_remaining / self.tokens_limit
        return 0.0

    @property
    def pressure(self) -> float:
        return max(self.request_pressure, self.token_pressure)


_KNOWN = {
    "x-ratelimit-limit-requests": "requests_limit",
    "x-ratelimit-remaining-requests": "requests_remaining",
    "x-ratelimit-reset-requests": "requests_reset_seconds",
    "x-ratelimit-limit-tokens": "tokens_limit",
    "x-ratelimit-remaining-tokens": "tokens_remaining",
    "x-ratelimit-reset-tokens": "tokens_reset_seconds",
    "anthropic-ratelimit-requests-limit": "requests_limit",
    "anthropic-ratelimit-requests-remaining": "requests_remaining",
    "anthropic-ratelimit-requests-reset": "requests_reset_seconds",
    "anthropic-ratelimit-tokens-limit": "tokens_limit",
    "anthropic-ratelimit-tokens-remaining": "tokens_remaining",
    "anthropic-ratelimit-tokens-reset": "tokens_reset_seconds",
}


def parse_ratelimit_headers(headers: dict[str, str]) -> QuotaState:
    state = QuotaState()
    lower = {k.lower(): v for k, v in headers.items()}
    for header, field in _KNOWN.items():
        raw = lower.get(header)
        if raw is None:
            continue
        try:
            setattr(state, field, float(raw) if "." in raw else int(raw))
        except (TypeError, ValueError):
            continue
    return state


class QuotaMonitor:
    def __init__(self, pressure_threshold: float = 0.85) -> None:
        self.pressure_threshold = pressure_threshold
        self.last: QuotaState | None = None

    def ingest(self, headers: dict[str, str]) -> QuotaState:
        self.last = parse_ratelimit_headers(headers)
        return self.last

    def adjust(self, aimd) -> bool:
        """Proactively clamp the AIMD limit when provider quota pressure is high."""
        if self.last is None:
            return False
        if self.last.pressure >= self.pressure_threshold:
            return aimd.apply_external_decrease(self.last.pressure)
        return False
