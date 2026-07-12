import argparse
import asyncio
import os
import yaml
import sys

from wedge.runner import WedgeRunner
from wedge.diff_engine import compare_patches
from wedge.report import generate_report

async def run_task(task_file: str):
    with open(task_file, "r") as f:
        task = yaml.safe_load(f)

    task_name = task.get("name", "Unknown Task")
    prompt = task.get("prompt", "")
    test_cmd = task.get("test_command", "")
    num_runners = task.get("runners", 3)
    provider = task.get("provider", "anthropic")
    # model may come from task.yaml (lets tasks target a non-default model,
    # e.g. a provider-specific model not hard-coded in the runner).
    model = task.get("model")
    # base_url may come from task.yaml or the WEDGE_BASE_URL env var.
    base_url = task.get("base_url") or os.getenv("WEDGE_BASE_URL")

    print(f"Running task: {task_name} with {num_runners} concurrent runners ({provider})...")

    # Launch concurrent runners
    runners = [
        WedgeRunner(
            runner_id=f"R{i}",
            repo_path=".",
            provider=provider,
            base_url=base_url,
            model=model,
        )
        for i in range(num_runners)
    ]

    tasks = [r.run(prompt, test_cmd) for r in runners]
    results = await asyncio.gather(*tasks)
    
    # Extract patches
    patches = [r["patch"] for r in results]
    
    # Run diff engine
    print("Comparing patches...")
    diff_results = compare_patches(patches)
    
    # Generate report
    report_md = generate_report(task_name, diff_results, results)
    
    report_file = "wedge_report.md"
    with open(report_file, "w") as f:
        f.write(report_md)
        
    print(f"Done! Report saved to {report_file}")
    
    # Terminal summary
    print("\nConvergence Summary:")
    for f, res in diff_results.items():
        print(f"  {f}: {res['status'].upper()} (sim={res['average_similarity']:.2f})")

def main():
    parser = argparse.ArgumentParser(description="Wedge CLI")
    parser.add_argument("command", choices=["run"], help="Command to execute")
    parser.add_argument("task_file", help="Path to task.yaml")
    
    args = parser.parse_args()
    
    if args.command == "run":
        asyncio.run(run_task(args.task_file))

if __name__ == "__main__":
    main()
