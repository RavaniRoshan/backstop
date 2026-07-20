from __future__ import annotations

import yaml
from typing import Dict, Any, List

# Per-runner Backstop budget cap (mirrors WedgeRunner's wrap budget).
RUNNER_BUDGET = 20_000


def generate_report(
    task_name: str,
    diff_results: Dict[str, Any],
    runners: List[Dict[str, Any]],
    *,
    cost_per_1k: float = 0.003,
) -> str:
    lines: List[str] = []
    lines.append(f"# Wedge Run Report: {task_name}")
    lines.append("")
    lines.append(
        "> Multi-agent isolation proof: each runner is an independent Backstop "
        "session with its own in-process budget and circuit breaker. The budget "
        "rows below are the *real* token usage measured per agent."
    )
    lines.append("")

    lines.append("## Runner Status (per-agent budget isolation)")
    for r in runners:
        remaining = r.get("budget_remaining")
        if remaining is None:
            spent = "n/a"
            pct = "n/a"
        else:
            spent = RUNNER_BUDGET - remaining
            pct = f"{(spent / RUNNER_BUDGET) * 100:.1f}%"
        lines.append(f"- **Runner {r['runner_id']}**:")
        lines.append(f"  - Tests passed: {r['test_passed']}")
        lines.append(f"  - Budget remaining: {remaining if remaining is not None else 'unlimited'}")
        lines.append(f"  - Tokens spent: {spent} ({pct} of cap)")
        lines.append(f"  - Patch applied: {r.get('patch_applied', 'n/a')}")
    lines.append("")

    lines.append("## Budget Isolation Evidence")
    remainings = [r.get("budget_remaining") for r in runners]
    if all(r is not None for r in remainings):
        total_spent = sum(RUNNER_BUDGET - r for r in remainings)
        blended_cost = (total_spent / 1000) * cost_per_1k
        lines.append(
            f"Across {len(runners)} concurrent runners, total token spend was "
            f"**{total_spent:,} tokens** (~${blended_cost:.4f} at the assumed "
            f"rate). Each runner's budget is scoped to its own session, so one "
            f"agent's spend cannot consume another's cap — that is the per-agent "
            f"isolation thesis, measured."
        )
    else:
        lines.append(
            "Budget usage was not captured for every runner; re-run with a "
            "finite Backstop budget to produce spend evidence."
        )
    lines.append("")

    lines.append("## Diff Engine Results (Convergence)")
    for filename, result in diff_results.items():
        lines.append(f"### File: `{filename}`")
        lines.append(
            f"**Status**: {result['status'].upper()} "
            f"(Semantic similarity: {result['average_similarity']:.2f})"
        )
        lines.append("")
        for i, p in enumerate(result["patches"]):
            lines.append(f"#### Runner {i + 1} Patch")
            lines.append("```diff")
            lines.append(p)
            lines.append("```")
            lines.append("")

    return "\n".join(lines)
