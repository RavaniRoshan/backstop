import argparse
import asyncio
import os
import yaml
import sys

from wedge.runner import WedgeRunner
from wedge.diff_engine import compare_patches
from wedge.report import generate_report

async def run_task(task_file: str, overrides: dict | None = None):
    with open(task_file, "r") as f:
        task = yaml.safe_load(f)

    overrides = overrides or {}
    task_name = task.get("name", "Unknown Task")
    prompt = task.get("prompt", "")
    test_cmd = task.get("test_command", "")
    num_runners = overrides.get("runners", task.get("runners", 3))
    provider = overrides.get("provider", task.get("provider", "anthropic"))
    model = overrides.get("model", task.get("model"))
    base_url = overrides.get("base_url", task.get("base_url")) or os.getenv("WEDGE_BASE_URL")
    test_timeout = overrides.get("test_timeout", task.get("test_timeout", 60.0))
    max_retries = overrides.get("max_retries", task.get("max_retries", 2))
    repo_path = overrides.get("repo_path", task.get("repo_path", "."))

    print(f"Running task: {task_name} with {num_runners} concurrent runners ({provider})...")

    runners = [
        WedgeRunner(
            runner_id=f"R{i}",
            repo_path=repo_path,
            provider=provider,
            base_url=base_url,
            model=model,
            test_timeout=test_timeout,
            max_retries=max_retries,
        )
        for i in range(num_runners)
    ]

    tasks = [r.run(prompt, test_cmd) for r in runners]
    results = await asyncio.gather(*tasks)

    patches = [r["patch"] for r in results]

    print("Comparing patches...")
    diff_results = compare_patches(patches)

    report_md = generate_report(task_name, diff_results, results)

    report_file = "wedge_report.md"
    with open(report_file, "w") as f:
        f.write(report_md)

    print(f"Done! Report saved to {report_file}")

    print("\nConvergence Summary:")
    for f, res in diff_results.items():
        print(f"  {f}: {res['status'].upper()} (sim={res['average_similarity']:.2f})")

    passed = sum(1 for r in results if r["test_passed"])
    print(f"\nTests passed: {passed}/{num_runners}")

def main():
    parser = argparse.ArgumentParser(description="Wedge CLI — multi-agent diff tool")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run a task.yaml")
    run_p.add_argument("task_file", help="Path to task.yaml")
    run_p.add_argument("--runners", type=int, help="Number of concurrent runners")
    run_p.add_argument("--provider", choices=["anthropic", "openai"], help="Override provider")
    run_p.add_argument("--model", help="Override model name")
    run_p.add_argument("--base-url", help="Override API base URL")
    run_p.add_argument("--repo-path", help="Path to the repo to patch (default: current dir)")
    run_p.add_argument("--test-timeout", type=float, help="Per-runner test timeout in seconds")
    run_p.add_argument("--max-retries", type=int, help="Max fix attempts per runner")

    args = parser.parse_args()

    if args.command == "run":
        overrides = {k: v for k, v in vars(args).items()
                     if k not in ("command", "task_file") and v is not None}
        asyncio.run(run_task(args.task_file, overrides))

if __name__ == "__main__":
    main()
