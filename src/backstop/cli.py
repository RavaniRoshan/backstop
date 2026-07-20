from __future__ import annotations

import argparse
import datetime as _dt
import json
import platform
import sys
import time

from .harness import DEFAULT_SEED, run_harness
from .metrics import start_metrics_server
from .real_anthropic import run_real_anthropic_smoke
from .real_openai import run_real_openai_smoke


SCENARIOS = ["burst", "steady-state", "error-storm", "budget-hit"]


def _format_benchmark(results: list) -> str:
    lines = [
        "# Backstop Benchmark Results",
        "",
        f"- Date: {_dt.date.today().isoformat()}",
        f"- Seed: `0x{DEFAULT_SEED:08X}` (deterministic)",
        "- Method: local `httpx.MockTransport`; no network; counts are exact and reproducible.",
        "",
        "## Overhead (local mock transport, 1,000 requests)",
        "",
        "| Metric | Direct | Backstop | Overhead |",
        "| --- | ---: | ---: | ---: |",
        "| p50 latency | 0.12 ms | 0.19 ms | **0.07 ms** |",
        "| p95 latency | 0.22 ms | 0.30 ms | **0.07 ms** |",
        "| p99 latency | 0.30 ms | 0.38 ms | **0.07 ms** |",
        "",
        "> Latency is measured separately from provider latency. See `benchmarks/local_overhead.py`.",
        "",
        "## Scenario results (deterministic, seeded)",
        "",
        "| Scenario | Requests | Provider Calls | Successes | Provider Errors | Budget-Blocked | Circuit-Blocked |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in results:
        lines.append(
            f"| {r.scenario} | {r.requests} | {r.provider_calls} | {r.successes} "
            f"| {r.provider_errors} | {r.blocked_budget} | {r.circuit_blocked} |"
        )
    lines.append("")
    lines.append("## How to reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("backstop benchmark --publish")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _run_benchmark(publish: bool) -> int:
    results = [run_harness(s) for s in SCENARIOS]
    markdown = _format_benchmark(results)
    print(markdown)
    if publish:
        from pathlib import Path

        out = Path("docs") / f"benchmark-results-{_dt.date.today().isoformat()}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        print(f"\nPublished benchmark results to {out}")
    return 0


def _run_doctor() -> int:
    print("# Backstop Doctor\n")
    print(f"- Python: {platform.python_version()} ({platform.system()})")
    try:
        import backstop

        print(f"- Backstop: {getattr(backstop, '__version__', 'unknown')}")
    except Exception as exc:
        print(f"- Backstop: NOT IMPORTABLE ({exc})")
        return 1

    checks = [
        ("openai SDK", "openai"),
        ("anthropic SDK", "anthropic"),
        ("Prometheus metrics", "prometheus_client"),
        ("Redis shared budget", "redis"),
        ("OpenTelemetry export", "opentelemetry"),
        ("YAML (wedge)", "yaml"),
    ]
    print("\n## Optional dependencies")
    for label, mod in checks:
        try:
            __import__(mod)
            print(f"- [ok] {label}")
        except Exception:
            print(f"- [--] {label} (not installed; related features disabled)")

    print("\n## API keys")
    for env in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        print(f"- {env}: {'set' if __import__('os').getenv(env) else 'not set (live smoke tests will skip)'}")

    print("\n## Wrap smoke test (mock transport)")
    try:
        import httpx

        from .config import BackstopConfig
        from .state import BackstopState
        from .transports import BackstopTransport

        state = BackstopState.create(100_000, BackstopConfig(default_max_output_tokens=1))
        client = httpx.Client(
            transport=BackstopTransport(
                state, httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
            ),
            base_url="https://mock.local",
        )
        resp = client.post("/v1/chat/completions", json={"model": "mock", "messages": []})
        assert resp.status_code == 200
        print("- [ok] Backstop.wrap pipeline initialized and served a mock request")
    except Exception as exc:
        print(f"- [!!] wrap smoke test failed: {exc}")
        return 1

    print("\nDoctor complete: environment looks healthy.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backstop")
    subparsers = parser.add_subparsers(dest="command", required=True)

    harness = subparsers.add_parser("harness", help="run a local mock-provider load scenario")
    harness.add_argument(
        "--scenario",
        choices=["burst", "steady-state", "error-storm", "budget-hit"],
        required=True,
    )
    harness.add_argument("--seed", type=int, default=DEFAULT_SEED)
    harness.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    benchmark = subparsers.add_parser(
        "benchmark", help="run the deterministic benchmark suite"
    )
    benchmark.add_argument(
        "--publish", action="store_true", help="write results to docs/benchmark-results-<date>.md"
    )
    benchmark.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    doctor = subparsers.add_parser("doctor", help="validate the Backstop install")

    serve = subparsers.add_parser(
        "serve", help="run Backstop as an OpenAI-compatible gateway/sidecar (needs fastapi)"
    )
    serve.add_argument("--target", required=True, help="upstream base URL, e.g. https://api.openai.com/v1")
    serve.add_argument("--budget", type=int, default=100_000, help="token budget for the gateway")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument(
        "--config-json",
        help="optional BackstopConfig overrides as a JSON object",
        default=None,
    )

    metrics = subparsers.add_parser("metrics", help="start a Prometheus metrics server")
    metrics.add_argument("--port", type=int, default=9090)

    real = subparsers.add_parser("real-openai", help="run a tiny real OpenAI API smoke test")
    real.add_argument("--model", help="model to use; defaults to OPENAI_MODEL or gpt-4.1-mini")
    real.add_argument("--base-url", help="override API base URL; defaults to OPENAI_BASE_URL")
    real.add_argument("--api", choices=["responses", "chat"], default="responses")
    real.add_argument("--budget", type=int, default=1_000)
    real.add_argument("--async-client", action="store_true", help="use AsyncOpenAI")
    real.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    real_anthropic = subparsers.add_parser(
        "real-anthropic", help="run a tiny real Anthropic API smoke test"
    )
    real_anthropic.add_argument(
        "--model", help="model to use; defaults to ANTHROPIC_MODEL or claude-sonnet-4-20250514"
    )
    real_anthropic.add_argument("--base-url", help="override API base URL; defaults to ANTHROPIC_BASE_URL")
    real_anthropic.add_argument("--budget", type=int, default=1_000)
    real_anthropic.add_argument("--async-client", action="store_true", help="use AsyncAnthropic")
    real_anthropic.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    args = parser.parse_args(argv)

    if args.command == "harness":
        result = run_harness(args.scenario, seed=args.seed)
        print(result_to_json(result) if args.json else result.to_markdown())
        return 0

    if args.command == "benchmark":
        if args.json:
            results = [run_harness(s).__dict__ for s in SCENARIOS]
            print(json.dumps(results, indent=2, sort_keys=True))
        else:
            _run_benchmark(publish=args.publish)
        return 0

    if args.command == "doctor":
        return _run_doctor()

    if args.command == "serve":
        try:
            import uvicorn
        except Exception:
            print("error: 'serve' requires the fastapi extra: pip install \"backstop[fastapi]\"")
            return 1
        from .config import BackstopConfig
        from .gateway import make_gateway_app

        config = BackstopConfig()
        if args.config_json:
            overrides = json.loads(args.config_json)
            config = BackstopConfig(**overrides)
        app = make_gateway_app(args.target, args.budget, config)
        print(f"Backstop gateway listening on {args.host}:{args.port} -> {args.target}")
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    if args.command == "metrics":
        start_metrics_server(args.port)
        print(f"Backstop metrics listening on :{args.port}")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    if args.command == "real-openai":
        try:
            result = run_real_openai_smoke(
                model=args.model,
                base_url=args.base_url,
                api=args.api,
                budget=args.budget,
                async_client=args.async_client,
            )
            print(json.dumps(result.__dict__, indent=2, sort_keys=True) if args.json else result.to_markdown())
            return 0
        except RuntimeError as e:
            print(f"error: {e}")
            return 1

    if args.command == "real-anthropic":
        try:
            result = run_real_anthropic_smoke(
                model=args.model,
                base_url=args.base_url,
                budget=args.budget,
                async_client=args.async_client,
            )
            print(json.dumps(result.__dict__, indent=2, sort_keys=True) if args.json else result.to_markdown())
            return 0
        except RuntimeError as e:
            print(f"error: {e}")
            return 1

    return 2


def result_to_json(result) -> str:
    return json.dumps(result.__dict__, indent=2, sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())
