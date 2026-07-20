"""Agent-native guardrails (Deep Research P2#11).

Coding/agent loops can run away: repeated tool calls, runaway generation, or
stalls. ``AgentGuard`` tracks per-agent request counts and token spend within a
sliding window and blocks (returns False) once a ceiling is hit, so a misbehaving
agent is fenced by Backstop rather than silently burning the whole budget.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class AgentGuard:
    def __init__(
        self,
        max_calls: int = 100,
        window_seconds: float = 60.0,
        max_tokens: int | None = None,
    ) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.max_tokens = max_tokens
        self._calls: dict[str, deque[float]] = {}
        self._tokens: dict[str, deque[tuple[float, int]]] = {}
        self._lock = threading.Lock()

    def allow(self, agent_id: str, tokens: int = 0) -> bool:
        now = time.monotonic()
        with self._lock:
            calls = self._calls.setdefault(agent_id, deque())
            self._trim(calls, now)
            if len(calls) >= self.max_calls:
                return False
            calls.append(now)

            if self.max_tokens is not None and tokens > 0:
                spent = self._tokens.setdefault(agent_id, deque())
                self._trim_tokens(spent, now)
                if sum(t for _, t in spent) + tokens > self.max_tokens:
                    return False
                spent.append((now, tokens))
            return True

    def _trim(self, calls: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while calls and calls[0] < cutoff:
            calls.popleft()

    def _trim_tokens(self, spent: deque[tuple[float, int]], now: float) -> None:
        cutoff = now - self.window_seconds
        while spent and spent[0][0] < cutoff:
            spent.popleft()
