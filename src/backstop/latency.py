from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BackstopMeta:
    queue_wait_ms: float = 0.0
    total_latency_ms: float = 0.0
    first_chunk_ms: float | None = None
    estimated_tokens: int = 0
    actual_tokens: int | None = None
    retry_count: int = 0
    circuit_state: str = "closed"
    endpoint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def provider_latency_ms(self) -> float:
        return self.total_latency_ms - self.queue_wait_ms


class _LatencyTracker:
    def __init__(self) -> None:
        self.created_at = time.monotonic()
        self.queue_entered_at: float = 0.0
        self.request_sent_at: float = 0.0
        self.first_byte_at: float | None = None
        self.completed_at: float = 0.0
        self.retry_count: int = 0

    @property
    def queue_wait_ms(self) -> float:
        if self.queue_entered_at == 0:
            return 0.0
        return (self.queue_entered_at - self.created_at) * 1000

    @property
    def total_latency_ms(self) -> float:
        if self.completed_at == 0:
            return 0.0
        return (self.completed_at - self.created_at) * 1000

    @property
    def first_chunk_ms(self) -> float | None:
        if self.first_byte_at is None:
            return None
        return (self.first_byte_at - self.created_at) * 1000

    def build_meta(
        self,
        estimated_tokens: int,
        actual_tokens: int | None,
        circuit_state: str,
        endpoint: str,
        metadata: dict[str, Any] | None = None,
    ) -> BackstopMeta:
        return BackstopMeta(
            queue_wait_ms=self.queue_wait_ms,
            total_latency_ms=self.total_latency_ms,
            first_chunk_ms=self.first_chunk_ms,
            estimated_tokens=estimated_tokens,
            actual_tokens=actual_tokens,
            retry_count=self.retry_count,
            circuit_state=circuit_state,
            endpoint=endpoint,
            metadata=metadata or {},
        )


def extract_backstop_headers(request: Any) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        if key.lower().startswith("x-backstop-") and key.lower() != "x-backstop-priority":
            headers[key] = value
    return headers
