from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .config import Priority


@dataclass
class BeforeRequestHook:
    endpoint: str
    priority: Priority
    estimated_tokens: int
    metadata: dict[str, Any]


@dataclass
class AfterResponseHook:
    endpoint: str
    status_code: int
    actual_tokens: int | None
    latency_ms: float
    success: bool
    metadata: dict[str, Any]


BeforeHookCallback = Callable[[BeforeRequestHook], None]
AfterHookCallback = Callable[[AfterResponseHook], None]
