from __future__ import annotations

from dataclasses import dataclass

from .admission import PriorityGate
from .aimd import AIMDController
from .budget import Budget
from .circuit import CircuitBreaker
from .config import BackstopConfig


@dataclass
class BackstopState:
    config: BackstopConfig
    budget: Budget
    aimd: AIMDController
    gate: PriorityGate
    circuit: CircuitBreaker

    @classmethod
    def create(cls, budget: int | None, config: BackstopConfig | None = None) -> "BackstopState":
        resolved = config or BackstopConfig()
        aimd = AIMDController(resolved)
        return cls(
            config=resolved,
            budget=Budget(budget),
            aimd=aimd,
            gate=PriorityGate(resolved, aimd),
            circuit=CircuitBreaker(resolved),
        )

