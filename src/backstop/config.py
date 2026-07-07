from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .hooks import AfterHookCallback, BeforeHookCallback

TokenCounter = Callable[[str, str], int] | None


class Priority(str, Enum):
    CRITICAL = "critical"
    DEFAULT = "default"
    BACKGROUND = "background"

    @classmethod
    def from_header(cls, value: str | None) -> "Priority":
        if not value:
            return cls.DEFAULT
        normalized = value.strip().lower()
        for priority in cls:
            if priority.value == normalized:
                return priority
        return cls.DEFAULT


@dataclass(frozen=True)
class BackstopConfig:
    default_max_output_tokens: int = 1024
    chars_per_token: float = 4.0

    retry_max_attempts: int = 3
    retry_base_delay: float = 0.05
    retry_max_delay: float = 2.0
    retry_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504, 529})

    circuit_window_seconds: float = 60.0
    circuit_failure_threshold: float = 0.20
    circuit_cooldown_seconds: float = 30.0
    circuit_min_requests: int = 5

    initial_concurrency: int = 8
    min_concurrency: int = 1
    max_concurrency: int = 64
    aimd_increase: int = 1
    aimd_decrease_factor: float = 0.5
    aimd_adjustment_interval: float = 5.0

    starvation_after_seconds: float = 1.0

    queue_timeout: float | None = None
    request_timeout: float | None = None

    before_request: BeforeHookCallback | None = None
    after_response: AfterHookCallback | None = None

    cache_enabled: bool = False
    cache_max_entries: int = 256
    cache_ttl: float = 60.0

    token_counter: TokenCounter | None = None

    def __post_init__(self) -> None:
        if self.default_max_output_tokens < 0:
            raise ValueError("default_max_output_tokens must be >= 0")
        if self.chars_per_token <= 0:
            raise ValueError("chars_per_token must be > 0")
        if self.retry_max_attempts < 1:
            raise ValueError("retry_max_attempts must be >= 1")
        if self.retry_base_delay < 0 or self.retry_max_delay < 0:
            raise ValueError("retry delays must be >= 0")
        if not 0 < self.circuit_failure_threshold <= 1:
            raise ValueError("circuit_failure_threshold must be in (0, 1]")
        if self.circuit_window_seconds <= 0:
            raise ValueError("circuit_window_seconds must be > 0")
        if self.circuit_cooldown_seconds < 0:
            raise ValueError("circuit_cooldown_seconds must be >= 0")
        if self.circuit_min_requests < 1:
            raise ValueError("circuit_min_requests must be >= 1")
        if self.min_concurrency < 1:
            raise ValueError("min_concurrency must be >= 1")
        if self.max_concurrency < self.min_concurrency:
            raise ValueError("max_concurrency must be >= min_concurrency")
        if not self.min_concurrency <= self.initial_concurrency <= self.max_concurrency:
            raise ValueError("initial_concurrency must be within min/max bounds")
        if not 0 < self.aimd_decrease_factor < 1:
            raise ValueError("aimd_decrease_factor must be in (0, 1)")
        if self.aimd_adjustment_interval < 0:
            raise ValueError("aimd_adjustment_interval must be >= 0")
        if self.starvation_after_seconds < 0:
            raise ValueError("starvation_after_seconds must be >= 0")
        if self.queue_timeout is not None and self.queue_timeout <= 0:
            raise ValueError("queue_timeout must be > 0 when set")
        if self.request_timeout is not None and self.request_timeout <= 0:
            raise ValueError("request_timeout must be > 0 when set")
        if self.cache_max_entries < 1:
            raise ValueError("cache_max_entries must be >= 1")
        if self.cache_ttl <= 0:
            raise ValueError("cache_ttl must be > 0")

    def __getattr__(self, name: str) -> Any:
        if name == "priority_weights":
            warnings.warn(
                "priority_weights is removed in v0.2 and has no effect",
                DeprecationWarning,
                stacklevel=2,
            )
            return {}
        msg = f"{type(self).__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)

