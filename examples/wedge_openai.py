"""
Wedge OpenAI example: 3 OpenAI runners, diff output.

Same as wedge_basic.py but uses OpenAI's GPT-4 as the provider.
Demonstrates that Backstop's transport-layer wrapping is provider-agnostic.

Requirements:
    pip install -e "."
    export OPENAI_API_KEY="sk-..."

Usage:
    python examples/wedge_openai.py
"""

import asyncio
from wedge.runner import WedgeRunner
from wedge.diff_engine import compare_patches
from wedge.report import generate_report


async def main():
    prompt = "Refactor this function to use a class-based approach with proper error handling."
    num_runners = 3

    print(f"Launching {num_runners} isolated OpenAI runners...")
    print(f"Each runner: Backstop.wrap(AsyncOpenAI(), budget=20_000)\n")

    runners = [
        WedgeRunner(runner_id=f"R{i}", repo_path=".", provider="openai")
        for i in range(num_runners)
    ]

    tasks = [r.run(prompt, "pytest tests/") for r in runners]
    results = await asyncio.gather(*tasks)

    # Compare patches across runners
    patches = [r["patch"] for r in results]
    diff_results = compare_patches(patches)

    # Print results
    print("=" * 50)
    print("CONVERGENCE REPORT")
    print("=" * 50)

    for runner in results:
        budget = runner["budget_remaining"]
        spent = 20_000 - budget
        print(f"  {runner['runner_id']}: budget spent={spent}, remaining={budget}")

    print()
    for filename, res in diff_results.items():
        print(f"  {filename}: {res['status'].upper()} (similarity={res['average_similarity']:.2f})")

    # Save full report
    report = generate_report("Wedge OpenAI Example", diff_results, results)
    with open("wedge_report.md", "w") as f:
        f.write(report)
    print(f"\nFull report saved to wedge_report.md")


if __name__ == "__main__":
    asyncio.run(main())
