"""Safe rollout: shadow + canary (Deep Research P2#13).

Lets a stricter / experimental policy ride alongside production without
hard-failing traffic. ``ShadowPolicy`` mirrors a sampled fraction of requests to
a secondary config and records *reason-coded* decisions (what the candidate
policy would have done) to the audit log, so a bad policy change is observed
before it ever blocks 100% of traffic. ``CanaryRouter`` sends a fraction of
traffic down a candidate fallback chain.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class ShadowPolicy:
    sample_rate: float = 0.0
    candidate_config: object | None = None
    sink: object | None = None
    _rand: object = field(default_factory=random.Random)

    def should_shadow(self) -> bool:
        return self.sample_rate > 0 and self._rand.random() < self.sample_rate

    def record(self, decision: str, reason: str, **fields) -> None:
        if self.sink is None:
            return
        try:
            self.sink.record(decision, reason, **fields)
        except Exception:
            pass


@dataclass
class CanaryRouter:
    sample_rate: float = 0.0
    candidate_chain: list[dict] | None = None
    _rand: object = field(default_factory=random.Random)

    def route(self, primary: list[dict]) -> list[dict]:
        if self.sample_rate > 0 and self.candidate_chain and self._rand.random() < self.sample_rate:
            return self.candidate_chain
        return primary
