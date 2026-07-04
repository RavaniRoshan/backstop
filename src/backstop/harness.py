from __future__ import annotations

import concurrent.futures
import json
import random
import statistics
import threading
import time
from dataclasses import dataclass
from typing import Literal

import httpx

from .config import BackstopConfig
from .exceptions import BudgetExceededError, CircuitBreakerOpenError
from .state import BackstopState
from .transports import BackstopTransport

Scenario = Literal["burst", "steady-state", "error-storm", "budget-hit"]


@dataclass
class HarnessResult:
    scenario: Scenario
    requests: int
    successes: int
    provider_errors: int
    blocked_budget: int
    circuit_blocked: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_rate: float
    remaining_budget: int | None
    final_concurrency: int
    provider_calls: int

    def to_markdown(self) -> str:
        return "\n".join(
            [
                f"# Backstop Harness: {self.scenario}",
                "",
                "| Metric | Value |",
                "| --- | ---: |",
                f"| Requests attempted | {self.requests} |",
                f"| Provider calls | {self.provider_calls} |",
                f"| Successes | {self.successes} |",
                f"| Provider errors | {self.provider_errors} |",
                f"| Budget-blocked requests | {self.blocked_budget} |",
                f"| Circuit-blocked requests | {self.circuit_blocked} |",
                f"| Effective error rate | {self.error_rate:.2%} |",
                f"| p50 latency | {self.p50_ms:.2f} ms |",
                f"| p95 latency | {self.p95_ms:.2f} ms |",
                f"| p99 latency | {self.p99_ms:.2f} ms |",
                f"| Remaining budget | {self.remaining_budget if self.remaining_budget is not None else 'unlimited'} |",
                f"| Final concurrency limit | {self.final_concurrency} |",
            ]
        )


def run_harness(scenario: Scenario) -> HarnessResult:
    if scenario not in {"burst", "steady-state", "error-storm", "budget-hit"}:
        raise ValueError(f"unknown scenario: {scenario}")

    provider = _MockProvider(error_rate=0.6 if scenario == "error-storm" else 0.0)
    config = BackstopConfig(
        initial_concurrency=8,
        max_concurrency=32,
        retry_max_attempts=2,
        circuit_min_requests=5,
        circuit_failure_threshold=0.5 if scenario == "error-storm" else 0.8,
        circuit_cooldown_seconds=0.5,
        aimd_adjustment_interval=0.1,
    )
    budget = 250 if scenario == "budget-hit" else 50_000
    state = BackstopState.create(budget, config)
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(provider.handle)),
        base_url="https://mock.openai.local",
        timeout=5.0,
    )

    total = 80 if scenario == "budget-hit" else 50
    latencies: list[float] = []
    successes = provider_errors = blocked_budget = circuit_blocked = 0
    lock = threading.Lock()

    def one_call(index: int) -> None:
        nonlocal successes, provider_errors, blocked_budget, circuit_blocked
        priority = "critical" if index % 10 == 0 else ("background" if index % 3 == 0 else "default")
        started = time.perf_counter()
        try:
            response = client.post(
                "/v1/chat/completions",
                headers={"X-Backstop-Priority": priority},
                json={
                    "model": "mock",
                    "messages": [{"role": "user", "content": f"request {index}"}],
                    "max_tokens": 8,
                },
            )
            elapsed = (time.perf_counter() - started) * 1000
            with lock:
                latencies.append(elapsed)
                if response.status_code < 400:
                    successes += 1
                else:
                    provider_errors += 1
        except BudgetExceededError:
            with lock:
                blocked_budget += 1
        except CircuitBreakerOpenError:
            with lock:
                circuit_blocked += 1

    if scenario == "steady-state":
        for idx in range(30):
            one_call(idx)
            time.sleep(0.2)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as pool:
            list(pool.map(one_call, range(total)))

    client.close()
    return HarnessResult(
        scenario=scenario,
        requests=total if scenario != "steady-state" else 30,
        successes=successes,
        provider_errors=provider_errors,
        blocked_budget=blocked_budget,
        circuit_blocked=circuit_blocked,
        p50_ms=_percentile(latencies, 50),
        p95_ms=_percentile(latencies, 95),
        p99_ms=_percentile(latencies, 99),
        error_rate=(provider_errors + blocked_budget + circuit_blocked)
        / max(1, total if scenario != "steady-state" else 30),
        remaining_budget=state.budget.remaining,
        final_concurrency=state.aimd.current_limit,
        provider_calls=provider.calls,
    )


class _MockAnthropicProvider:
    def __init__(self, *, error_rate: float) -> None:
        self.error_rate = error_rate
        self.calls = 0
        self._lock = threading.Lock()

    def handle(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.calls += 1
        time.sleep(random.uniform(0.005, 0.025))
        if self.error_rate and random.random() < self.error_rate:
            return httpx.Response(529, json={"error": {"message": "synthetic overload"}})
        return httpx.Response(
            200,
            json={
                "id": "msg_mock",
                "type": "message",
                "role": "assistant",
                "model": "mock",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 8, "output_tokens": 4},
            },
        )


class _MockProvider:
    def __init__(self, *, error_rate: float) -> None:
        self.error_rate = error_rate
        self.calls = 0
        self._lock = threading.Lock()

    def handle(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.calls += 1
        time.sleep(random.uniform(0.005, 0.025))
        if self.error_rate and random.random() < self.error_rate:
            return httpx.Response(503, json={"error": {"message": "synthetic overload"}})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_mock",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            },
        )


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    values = sorted(values)
    index = int(round((percentile / 100) * (len(values) - 1)))
    return values[index]


def result_to_json(result: HarnessResult) -> str:
    return json.dumps(result.__dict__, indent=2, sort_keys=True)

