#!/usr/bin/env python3
"""Wedge end-to-end demo with a mock LLM.

Proves the full pipeline: 3 concurrent runners, real patch extraction
(including code-block format), diff engine, convergence verdict, per-agent
budget isolation evidence, and markdown report. No network needed.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import wedge.cli as wedge_cli
from wedge.runner import WedgeRunner

# --- Mock LLM responses: realistic code-block output from 3 "agents" ---
# All 3 produce nearly-identical class-based refactors (will CONVERGE).
# They use different output formats to prove the patch extractor handles each.
CONVERGED_PATCH = (
    "class Item:\n"
    "    def __init__(self, name, price, qty=1):\n"
    "        self.name = name\n"
    "        self.price = price\n"
    "        self.qty = qty\n"
    "        self.total = price * qty\n\n"
    "    def apply_discount(self, percent):\n"
    "        if not 0 <= percent <= 100:\n"
    "            raise ValueError('percent must be between 0 and 100')\n"
    "        result = Item(self.name, self.price, self.qty)\n"
    "        result.total = round(self.total * (1 - percent / 100), 2)\n"
    "        return result\n\n"
    "    def format(self):\n"
    "        return f'{self.name}: {self.qty} x ${self.price:.2f} = ${self.total:.2f}'\n"
)

MOCK_PATCHES = [
    # Agent A: markdown code block with filename comment
    f"Here is the refactor:\n```python\n# main.py\n{CONVERGED_PATCH}```",
    # Agent B: FILE: header format
    f"FILE: main.py\n{CONVERGED_PATCH}",
    # Agent C: raw multi-line code (no markers)
    CONVERGED_PATCH,
]


async def mock_run_task(task_file: str, overrides: dict):
    """Run the wedge CLI with a mocked LLM."""
    captured = []
    original_init = WedgeRunner.__init__

    def patched_init(self, runner_id, repo_path, provider="anthropic", base_url=None, model=None, **kwargs):
        original_init(self, runner_id, repo_path, provider=provider, base_url=base_url, model=model, **kwargs)
        # Patch the LLM call to return a deterministic mock patch.
        async def mock_llm(prompt):
            idx = int(self.runner_id[1:])  # R0 -> 0, R1 -> 1, R2 -> 2
            return MOCK_PATCHES[idx % len(MOCK_PATCHES)]
        self._generate_patch_from_llm = mock_llm

    WedgeRunner.__init__ = patched_init
    try:
        await wedge_cli.run_task(task_file, overrides)
    finally:
        WedgeRunner.__init__ = original_init


def main():
    # Set up the fixture repo for the demo.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixture_dir = os.path.join(repo_root, "wedge-test-fixture")
    task_file = os.path.join(fixture_dir, "task.yaml")

    print("=" * 70)
    print("WEDGE END-TO-END DEMO (mock LLM)")
    print("=" * 70)
    print(f"Task: {task_file}")
    print(f"Runners: 3 (concurrent)")
    print(f"Provider: anthropic (mocked)")
    print()

    asyncio.run(mock_run_task(task_file, overrides={"runners": 3, "max_retries": 0, "test_command": "true"}))

    # Read and display the report (wedge_report.md is written to CWD).
    report_file = os.path.join(os.getcwd(), "wedge_report.md")
    if os.path.exists(report_file):
        report = open(report_file).read()
        print("\n" + "=" * 70)
        print("GENERATED REPORT")
        print("=" * 70)
        print(report[:3000])
        if len(report) > 3000:
            print(f"\n... ({len(report)} chars total)")
    else:
        print("ERROR: wedge_report.md not generated")


if __name__ == "__main__":
    main()
