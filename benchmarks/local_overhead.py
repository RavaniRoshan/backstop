"""The control-path overhead, measured.

The number this project publishes — "0.07 ms p50" — was measured against a
**94-byte** request body. That is a real measurement, but it is a measurement
of a body small enough that the guardrail's own work dominates, and the
overhead it reports scales with the body: the guardrail reads, parses and
inspects every request, so a larger request costs more to guard.

So this script measures **two** payload sizes — the small one the published
figure used, and a 4 KB one that is closer to a real prompt — and reports
both. And it records the host, the OS, the Python version and the SDK
versions, because the previous snapshot recorded none of them, and a latency
figure without the conditions it was measured under is not a fact.

Run it directly, with no CLI:

    PYTHONPATH=src python3 benchmarks/local_overhead.py --requests 1000
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from backstop import BackstopConfig
from backstop.state import BackstopState
from backstop.transports import BackstopTransport

#: The payload sizes measured, in bytes of request body. The first is the one
#: the published 0.07 ms figure used; the second is closer to a real prompt.
PAYLOAD_SIZES = (94, 4096)


@dataclass
class Series:
    p50_ms: float
    p95_ms: float
    p99_ms: float


@dataclass
class PayloadResult:
    payload_bytes: int
    requests: int
    direct: Series
    backstop: Series
    overhead_p50_ms: float
    overhead_p95_ms: float
    overhead_p99_ms: float
    provider_calls_direct: int
    provider_calls_backstop: int
    remaining_budget: int | None


@dataclass
class Result:
    requests: int
    payloads: list[PayloadResult]
    environment: dict[str, Any]


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


def _body(index: int, payload_bytes: int) -> dict:
    """A request body of roughly ``payload_bytes`` bytes.

    The prompt is padded with filler so the body reaches the requested size,
    which is what makes the two payload sizes comparable.
    """
    base = {
        "model": "mock",
        "messages": [{"role": "user", "content": f"benchmark {index}"}],
        "max_tokens": 8,
    }
    if payload_bytes <= 0:
        return base
    overhead = len(json.dumps(base))
    filler = "x" * max(0, payload_bytes - overhead)
    base["messages"][0]["content"] = f"benchmark {index} {filler}"
    return base


def _measure(payload_bytes: int, requests: int) -> PayloadResult:
    direct_provider = MockProvider()
    direct_client = httpx.Client(
        transport=httpx.MockTransport(direct_provider.handle),
        base_url="https://mock.openai.local",
    )

    backstop_provider = MockProvider()
    state = BackstopState.create(
        budget=requests * 100,
        config=BackstopConfig(
            initial_concurrency=64,
            max_concurrency=64,
            retry_max_attempts=1,
            circuit_min_requests=requests + 1,
        ),
    )
    backstop_client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(backstop_provider.handle)),
        base_url="https://mock.openai.local",
    )

    direct_latencies = run_series(direct_client, requests, payload_bytes)
    backstop_latencies = run_series(backstop_client, requests, payload_bytes)

    direct_client.close()
    backstop_client.close()

    direct = summarize(direct_latencies)
    backstop = summarize(backstop_latencies)
    return PayloadResult(
        payload_bytes=payload_bytes,
        requests=requests,
        direct=direct,
        backstop=backstop,
        overhead_p50_ms=round(backstop.p50_ms - direct.p50_ms, 4),
        overhead_p95_ms=round(backstop.p95_ms - direct.p95_ms, 4),
        overhead_p99_ms=round(backstop.p99_ms - direct.p99_ms, 4),
        provider_calls_direct=direct_provider.calls,
        provider_calls_backstop=backstop_provider.calls,
        remaining_budget=state.budget.remaining,
    )


def run_series(client: httpx.Client, requests: int, payload_bytes: int) -> list[float]:
    latencies: list[float] = []
    for index in range(requests):
        body = _body(index, payload_bytes)
        started = time.perf_counter()
        response = client.post("/v1/chat/completions", json=body)
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


def environment() -> dict[str, Any]:
    """The conditions the numbers were measured under.

    The previous snapshot recorded the date, the seed, the mock transport and
    the request count, and nothing else — so the figure could not be checked
    on another machine, and a reader could not tell what it depended on.
    """
    import importlib.metadata as metadata

    versions: dict[str, str | None] = {}
    for name in ("httpx", "openai", "anthropic", "prometheus-client"):
        try:
            versions[name] = metadata.version(name)
        except Exception:
            versions[name] = None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "packages": versions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument(
        "--payload-bytes",
        type=int,
        default=0,
        help="measure one payload size instead of both (0 measures both)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    sizes = (args.payload_bytes,) if args.payload_bytes else PAYLOAD_SIZES
    result = Result(
        requests=args.requests,
        payloads=[_measure(size, args.requests) for size in sizes],
        environment=environment(),
    )

    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print_markdown(result)
    return 0


def print_markdown(result: Result) -> None:
    env = result.environment
    print("# Backstop control-path overhead\n")
    print(f"- Requests per payload: {result.requests}")
    print(f"- Host: {env['platform']} ({env['machine']})")
    print(f"- Python: {env['implementation']} {env['python']}")
    packages = ", ".join(
        f"{name} {version}" for name, version in env["packages"].items() if version
    )
    print(f"- Packages: {packages or '(none installed)'}")
    print("- Transport: local `httpx.MockTransport`, no network")
    print()
    print("| Payload | Direct p50 | Backstop p50 | Overhead p50 | Overhead p95 | Overhead p99 |")
    print("|---|---:|---:|---:|---:|---:|")
    for payload in result.payloads:
        print(
            f"| {payload.payload_bytes} B | {payload.direct.p50_ms:.4f} ms | "
            f"{payload.backstop.p50_ms:.4f} ms | {payload.overhead_p50_ms:.4f} ms | "
            f"{payload.overhead_p95_ms:.4f} ms | {payload.overhead_p99_ms:.4f} ms |"
        )
    print()
    print(
        "The overhead is body-proportional: the guardrail reads, parses and "
        "inspects every request, so a larger request costs more to guard. The "
        "small payload is the one the previously published 0.07 ms figure "
        "used."
    )


if __name__ == "__main__":
    raise SystemExit(main())
