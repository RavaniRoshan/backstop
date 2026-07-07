import yaml
from typing import Dict, Any, List

def generate_report(task_name: str, diff_results: Dict[str, Any], runners: List[Dict[str, Any]]) -> str:
    lines = []
    lines.append(f"# Wedge Run Report: {task_name}")
    lines.append("")
    
    lines.append("## Runner Status")
    for r in runners:
        lines.append(f"- **Runner {r['runner_id']}**:")
        lines.append(f"  - Tests passed: {r['test_passed']}")
        lines.append(f"  - Budget remaining: {r['budget_remaining']}")
    lines.append("")
    
    lines.append("## Diff Engine Results (Convergence)")
    for filename, result in diff_results.items():
        lines.append(f"### File: `{filename}`")
        lines.append(f"**Status**: {result['status'].upper()} (Similarity: {result['average_similarity']:.2f})")
        lines.append("")
        for i, p in enumerate(result['patches']):
            lines.append(f"#### Runner {i+1} Patch")
            lines.append("```diff")
            lines.append(p)
            lines.append("```")
            lines.append("")
            
    return "\n".join(lines)
