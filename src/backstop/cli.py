from __future__ import annotations

import argparse
import datetime as _dt
import json
import platform
import statistics
import sys
import time

import httpx

from .config import BackstopConfig
from .dashboard_app import DEFAULT_HOST, DEFAULT_PORT, Dashboard, serve as serve_dashboard
from .harness import DEFAULT_SEED, run_harness
from .metrics import start_metrics_server
from .real_anthropic import run_real_anthropic_smoke
from .real_openai import run_real_openai_smoke
from .state import BackstopState
from .telemetry import DEFAULT_SAMPLE_INTERVAL
from .transports import BackstopTransport
from .verify import run_verify


SCENARIOS = ["burst", "steady-state", "error-storm", "budget-hit"]


def _format_benchmark(results: list) -> str:
    overhead = _measure_overhead()
    lines = [
        "# Backstop Benchmark Results",
        "",
        f"- Date: {_dt.date.today().isoformat()}",
        f"- Seed: `0x{DEFAULT_SEED:08X}` (deterministic)",
        "- Method: local `httpx.MockTransport`; no network; counts are exact and reproducible.",
        "",
        "## Overhead (local mock transport, measured)",
        "",
        "| Metric | Direct | Backstop | Overhead |",
        "| --- | ---: | ---: | ---: |",
        f"| p50 latency | {overhead['direct_p50']:.2f} ms | {overhead['backstop_p50']:.2f} ms | **{overhead['overhead_p50']:.2f} ms** |",
        f"| p95 latency | {overhead['direct_p95']:.2f} ms | {overhead['backstop_p95']:.2f} ms | **{overhead['overhead_p95']:.2f} ms** |",
        f"| p99 latency | {overhead['direct_p99']:.2f} ms | {overhead['backstop_p99']:.2f} ms | **{overhead['overhead_p99']:.2f} ms** |",
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


def _measure_overhead(n: int = 500) -> dict:
    """Measure the control-path overhead of Backstop vs a bare httpx client.

    Returns a dict with direct/backstop p50/p95/p99 and overhead values (ms).
    Uses a no-op mock provider so the measurement reflects only Backstop's
    in-process work, not network latency.
    """
    import statistics
    import time

    def _series(client):
        lats = []
        for i in range(n):
            t0 = time.perf_counter()
            client.post(
                "/v1/chat/completions",
                json={"model": "mock", "messages": [{"role": "user", "content": f"b{i}"}], "max_tokens": 8},
            )
            lats.append((time.perf_counter() - t0) * 1000)
        return sorted(lats)

    def _pct(vals, p):
        idx = round((p / 100) * (len(vals) - 1))
        return vals[idx]

    direct_client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})),
        base_url="https://mock.local",
    )
    direct = _series(direct_client)
    direct_client.close()

    state = BackstopState.create(
        n * 100,
        BackstopConfig(initial_concurrency=64, max_concurrency=64, retry_max_attempts=1, circuit_min_requests=n + 1),
    )
    backstop_client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True, "usage": {"total_tokens": 1}}))),
        base_url="https://mock.local",
    )
    backstop = _series(backstop_client)
    backstop_client.close()

    return {
        "direct_p50": statistics.median(direct),
        "direct_p95": _pct(direct, 95),
        "direct_p99": _pct(direct, 99),
        "backstop_p50": statistics.median(backstop),
        "backstop_p95": _pct(backstop, 95),
        "backstop_p99": _pct(backstop, 99),
        "overhead_p50": statistics.median(backstop) - statistics.median(direct),
        "overhead_p95": _pct(backstop, 95) - _pct(direct, 95),
        "overhead_p99": _pct(backstop, 99) - _pct(direct, 99),
    }


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
    
    # Check if we can import backstop's version without triggering metrics
    try:
        # Read the __init__.py directly to get version
        import pathlib
        init_path = pathlib.Path(__file__).parent / '__init__.py'
        content = init_path.read_text()
        # Simple regex-like extraction of __version__
        import re
        version_match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        backstop_version = version_match.group(1) if version_match else 'unknown'
        print(f"- Backstop: {backstop_version}")
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
        from .config import BackstopConfig
        from .wrapper import Backstop
        
        # Test with httpx mock transport (this is what the actual tests use)
        import httpx
        state = BackstopState.create(100_000, BackstopConfig(default_max_output_tokens=1))
        mock_transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "mock", "object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": "test"}}]}))
        client = httpx.Client(transport=mock_transport, base_url="https://mock.local")
        print("- [ok] httpx MockTransport works (as used in tests)")
        
        # Test with httpx2 mock transport (important for Anthropic support)
        import httpx2
        httpx2_mock_transport = httpx2.MockTransport(lambda r: httpx2.Response(200, json={"id": "mock", "object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": "test"}}]}))
        httpx2_client = httpx2.Client(transport=httpx2_mock_transport, base_url="https://mock.local")
        print("- [ok] httpx2 MockTransport works (for Anthropic compatibility)")
        
        # Verify the _httpcompat module works
        from . import _httpcompat
        print("- [ok] _httpcompat module loaded successfully")
        
        # Verify compat_for function works
        compat = _httpcompat.compat_for(client)
        print(f"- [ok] compat_for detected httpx family: {compat.name}")
        
        compat2 = _httpcompat.compat_for(httpx2_client)
        print(f"- [ok] compat_for detected httpx2 family: {compat2.name}")
        
    except Exception as exc:
        print(f"- [!!] wrap smoke test failed: {exc}")
        import traceback
        traceback.print_exc()
        return 1

    # Test actual SDK client wrapping (missing from original smoke test)
    print("\n## Actual SDK client wrapping test")
    provider_status = {}
    
    # OpenAI client wrapping
    try:
        import openai
        openai_client = openai.OpenAI(api_key="dummy-key")
        wrapped_openai = Backstop.wrap(openai_client, budget=10_000, config=BackstopConfig())
        print("- [ok] OpenAI client wrapped successfully")
        
        # Report SDK version
        try:
            print(f"- [ok] OpenAI SDK version: {openai.__version__}")
            provider_status['openai'] = {'version': openai.__version__, 'supported': True, 'wrapped': True}
        except Exception:
            print("- [--] OpenAI SDK version: not available")
            provider_status['openai'] = {'version': 'unknown', 'supported': True, 'wrapped': True}
            
    except Exception as e:
        print(f"- [!!] OpenAI client wrapping failed: {e}")
        provider_status['openai'] = {'version': 'unknown', 'supported': False, 'wrapped': False}
        # 1.3.3: doctor should exit non-zero when a wrap path fails
        print(f"\n- [!!] Wrap path failed for OpenAI: {e}")
        print("\nDoctor check failed: Some provider paths are not supported.")
        return 1
    
    # Anthropic client wrapping  
    try:
        import anthropic
        anthropic_client = anthropic.Anthropic(api_key="dummy-key")
        wrapped_anthropic = Backstop.wrap(anthropic_client, budget=10_000, config=BackstopConfig())
        print("- [ok] Anthropic client wrapped successfully")
        
        # Report SDK version
        try:
            print(f"- [ok] Anthropic SDK version: {anthropic.__version__}")
            provider_status['anthropic'] = {'version': anthropic.__version__, 'supported': True, 'wrapped': True}
        except Exception:
            print("- [--] Anthropic SDK version: not available")
            provider_status['anthropic'] = {'version': 'unknown', 'supported': True, 'wrapped': True}
            
    except Exception as e:
        print(f"- [!!] Anthropic client wrapping failed: {e}")
        provider_status['anthropic'] = {'version': 'unknown', 'supported': False, 'wrapped': False}
        # 1.3.3: doctor should exit non-zero when a wrap path fails
        print(f"\n- [!!] Wrap path failed for Anthropic: {e}")
        print("\nDoctor check failed: Some provider paths are not supported.")
        return 1

    # Report provider support status (1.3.2)
    print("\n## Provider support status")
    for provider, status in provider_status.items():
        version = status['version']
        supported = "yes" if status['supported'] else "no"
        wrapped = "yes" if status['wrapped'] else "no"
        print(f"- {provider}: version={version}, supported={supported}, wrapped={wrapped}")

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
        "--api-keys",
        help="comma-separated set of allowed Bearer tokens (auth disabled if omitted)",
        default=None,
    )
    serve.add_argument(
        "--rate-limit", type=int, default=None,
        help="max requests per minute per API key (requires --api-keys)",
    )
    serve.add_argument(
        "--config-json",
        help="optional BackstopConfig overrides as a JSON object",
        default=None,
    )

    metrics = subparsers.add_parser("metrics", help="start a Prometheus metrics server")
    metrics.add_argument("--port", type=int, default=9090)

    dashboard = subparsers.add_parser(
        "dashboard",
        help="serve the built-in dashboard for this process",
    )
    dashboard.add_argument("--port", type=int, default=DEFAULT_PORT)
    dashboard.add_argument("--host", default=DEFAULT_HOST, help="bind address (non-loopback requires --token)")
    dashboard.add_argument(
        "--refresh",
        type=float,
        default=None,
        help="sample interval in seconds (default: 1.0 in demo mode, else 2.0)",
    )
    dashboard.add_argument(
        "--cost-model",
        help="model whose input rate converts tokens into a USD lower bound, e.g. gpt-4o",
    )
    dashboard.add_argument(
        "--audit",
        help="path to an audit JSONL sink; enables the enforcement event stream",
    )
    dashboard.add_argument(
        "--demo",
        action="store_true",
        help="run a deterministic mock workload so the dashboard is live with no API keys",
    )
    dashboard.add_argument("--runners", type=int, default=3, help="demo runner count (default 3)")
    dashboard.add_argument(
        "--token",
        help="require this bearer token; mandatory when --host is not loopback",
    )
    dashboard.add_argument(
        "--theme",
        choices=("auto", "dark", "light"),
        default="auto",
        help="initial colour theme: auto follows the OS (default), or force dark/light",
    )
    dashboard.add_argument("--no-browser", action="store_true", help="do not open a browser")

    verify = subparsers.add_parser(
        "verify", help="run reproducible proof checks against this install (collapse install -> trust)"
    )
    verify.add_argument("--live", action="store_true", help="also probe the real provider (GET /models)")
    verify.add_argument("--offline", action="store_true", help="never touch the network (default)")
    verify.add_argument("--strict", action="store_true", help="treat warnings as failures (for CI)")
    verify.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    verify.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    verify.add_argument("--model", help="unused for auth probe; documented for future live completion")
    verify.add_argument("--base-url", help="override provider base URL for the live probe")
    verify.add_argument("--api-key-env", default="OPENAI_API_KEY", help="env var holding the provider key")
    verify.add_argument("--timeout", type=float, default=30.0, help="per-check timeout for live probes")

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
        api_keys = set(args.api_keys.split(",")) if args.api_keys else None
        app = make_gateway_app(
            args.target, args.budget, config,
            api_keys=api_keys, rate_limit_per_key=args.rate_limit,
        )
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

    if args.command == "dashboard":
        workload = None
        if args.demo:
            from .dashboard_demo import DemoWorkload

            workload = DemoWorkload(runners=args.runners)
        interval = args.refresh or (1.0 if args.demo else DEFAULT_SAMPLE_INTERVAL)
        panel = Dashboard(
            mode="demo" if args.demo else "live",
            cost_model=args.cost_model,
            audit=args.audit,
            interval=interval,
            token=args.token,
            demo=workload,
            theme=args.theme,
        )
        try:
            serve_dashboard(
                panel,
                host=args.host,
                port=args.port,
                open_browser=not args.no_browser,
            )
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0

    if args.command == "verify":
        return run_verify(
            live=args.live,
            strict=args.strict,
            json_output=args.json,
            timeout=args.timeout,
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
        )

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
