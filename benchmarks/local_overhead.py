from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass

import httpx

from backstop import BackstopConfig
from backstop.state import BackstopState
from backstop.transports import BackstopTransport


@dataclass
class Series:
    p50_ms: float
    p95_ms: float
    p99_ms: float


@dataclass
class Result:
    requests: int
    direct: Series
    backstop: Series
    overhead_p50_ms: float
    provider_calls_direct: int
    provider_calls_backstop: int
    remaining_budget: int | None


class MockProvider:
    def __init__(self) -> None:
        self.calls = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_benchmark",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            },
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    direct_provider = MockProvider()
    direct_client = httpx.Client(
        transport=httpx.MockTransport(direct_provider.handle),
        base_url="https://mock.openai.local",
    )

    backstop_provider = MockProvider()
    state = BackstopState.create(
        budget=args.requests * 100,
        config=BackstopConfig(
            initial_concurrency=64,
            max_concurrency=64,
            retry_max_attempts=1,
            circuit_min_requests=args.requests + 1,
        ),
    )
    backstop_client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(backstop_provider.handle)),
        base_url="https://mock.openai.local",
    )

    direct_latencies = run_series(direct_client, args.requests)
    backstop_latencies = run_series(backstop_client, args.requests)

    direct_client.close()
    backstop_client.close()

    result = Result(
        requests=args.requests,
        direct=summarize(direct_latencies),
        backstop=summarize(backstop_latencies),
        overhead_p50_ms=summarize(backstop_latencies).p50_ms - summarize(direct_latencies).p50_ms,
        provider_calls_direct=direct_provider.calls,
        provider_calls_backstop=backstop_provider.calls,
        remaining_budget=state.budget.remaining,
    )

    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print_markdown(result)
    return 0


def run_series(client: httpx.Client, requests: int) -> list[float]:
    latencies: list[float] = []
    for index in range(requests):
        started = time.perf_counter()
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock",
                "messages": [{"role": "user", "content": f"benchmark {index}"}],
                "max_tokens": 8,
            },
        )
        response.raise_for_status()
        latencies.append((time.perf_counter() - started) * 1000)
    return latencies


def summarize(values: list[float]) -> Series:
    values = sorted(values)
    return Series(
        p50_ms=round(statistics.median(values), 4),
        p95_ms=round(percentile(values, 95), 4),
        p99_ms=round(percentile(values, 99), 4),
    )


def percentile(values: list[float], pct: int) -> float:
    if len(values) == 1:
        return values[0]
    index = round((pct / 100) * (len(values) - 1))
    return values[index]


def print_markdown(result: Result) -> None:
    print("# Backstop Local Overhead Benchmark")
    print()
    print("| Metric | Direct | Backstop |")
    print("| --- | ---: | ---: |")
    print(f"| p50 latency | {result.direct.p50_ms:.4f} ms | {result.backstop.p50_ms:.4f} ms |")
    print(f"| p95 latency | {result.direct.p95_ms:.4f} ms | {result.backstop.p95_ms:.4f} ms |")
    print(f"| p99 latency | {result.direct.p99_ms:.4f} ms | {result.backstop.p99_ms:.4f} ms |")
    print()
    print(f"Approximate p50 overhead: {result.overhead_p50_ms:.4f} ms")
    print(f"Requests: {result.requests}")
    print(f"Provider calls: direct={result.provider_calls_direct}, backstop={result.provider_calls_backstop}")
    print(f"Remaining budget: {result.remaining_budget}")


if __name__ == "__main__":
    raise SystemExit(main())
