"""Proof: hierarchical budget isolation — parent exhaustion blocks child, sibling unaffected.

Run with:
    python proofs/proof_hierarchical.py
"""
from __future__ import annotations

import sys

from backstop.exceptions import BudgetExceededError
from backstop.hierarchical import HierarchicalBudgetTree


def main() -> int:
    tree = HierarchicalBudgetTree(
        {
            "team-a": {"limit_tokens": 500, "parent": "root"},
            "team-b": {"limit_tokens": 500, "parent": "root"},
            "service-a": {"limit_tokens": 500, "parent": "team-a"},
            "service-b": {"limit_tokens": 200, "parent": "team-b"},
        }
    )

    # 1) Exhaust team-a via service-a
    t1 = tree.reserve("service-a", 500)
    tree.commit("service-a", t1, 500)
    assert tree.remaining("team-a") == 0, "team-a should be exhausted"
    try:
        tree.reserve("service-a", 1)
    except BudgetExceededError:
        pass
    else:
        print("FAIL: child should be blocked when parent exhausted")
        return 1

    # 2) Sibling unaffected
    t3 = tree.reserve("service-b", 200)
    tree.commit("service-b", t3, 200)
    assert tree.used("service-b") == 200, "sibling should still serve"

    # 3) Most-restrictive-wins: child limit > parent limit
    tree2 = HierarchicalBudgetTree(
        {"c": {"limit_tokens": 1000, "parent": "p"}, "p": {"limit_tokens": 400}}
    )
    t4 = tree2.reserve("c", 400)
    tree2.commit("c", t4, 400)
    try:
        tree2.reserve("c", 1)
    except BudgetExceededError:
        pass
    else:
        print("FAIL: effective (most-restrictive) limit must enforce")
        return 1

    print("PROOF PASS: hierarchical isolation holds (parent blocks child, sibling serves, most-restrictive wins).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
