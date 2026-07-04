from __future__ import annotations

import argparse
import json
import time

from .harness import result_to_json, run_harness
from .metrics import start_metrics_server
from .real_openai import run_real_openai_smoke


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backstop")
    subparsers = parser.add_subparsers(dest="command", required=True)

    harness = subparsers.add_parser("harness", help="run a local mock-provider load scenario")
    harness.add_argument(
        "--scenario",
        choices=["burst", "steady-state", "error-storm", "budget-hit"],
        required=True,
    )
    harness.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    metrics = subparsers.add_parser("metrics", help="start a Prometheus metrics server")
    metrics.add_argument("--port", type=int, default=9090)

    real = subparsers.add_parser("real-openai", help="run a tiny real OpenAI API smoke test")
    real.add_argument("--model", help="model to use; defaults to OPENAI_MODEL or gpt-5.5")
    real.add_argument("--base-url", help="override API base URL; defaults to OPENAI_BASE_URL")
    real.add_argument("--api", choices=["responses", "chat"], default="responses")
    real.add_argument("--budget", type=int, default=1_000)
    real.add_argument("--async-client", action="store_true", help="use AsyncOpenAI")
    real.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    args = parser.parse_args(argv)

    if args.command == "harness":
        result = run_harness(args.scenario)
        print(result_to_json(result) if args.json else result.to_markdown())
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
        result = run_real_openai_smoke(
            model=args.model,
            base_url=args.base_url,
            api=args.api,
            budget=args.budget,
            async_client=args.async_client,
        )
        print(json.dumps(result.__dict__, indent=2, sort_keys=True) if args.json else result.to_markdown())
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
