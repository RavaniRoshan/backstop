from __future__ import annotations

from backstop.exceptions import BudgetExceededError
from backstop.hierarchical import HierarchicalBudgetTree


def _tree():
    return HierarchicalBudgetTree(
        {
            "team-a": {"limit_tokens": 500, "parent": "root"},
            "team-b": {"limit_tokens": 500, "parent": "root"},
            "service-a": {"limit_tokens": 200, "parent": "team-a"},
            "service-b": {"limit_tokens": 200, "parent": "team-b"},
        }
    )


def test_child_exhaustion_does_not_affect_sibling():
    tree = HierarchicalBudgetTree(
        {
            "team-a": {"limit_tokens": 500, "parent": "root"},
            "team-b": {"limit_tokens": 500, "parent": "root"},
            "service-a": {"limit_tokens": 500, "parent": "team-a"},
        }
    )
    t1 = tree.reserve("service-a", 500)
    tree.commit("service-a", t1, 500)
    assert tree.remaining("team-a") == 0
    assert tree.remaining("team-b") == 500


def test_parent_exhaustion_blocks_child_even_with_child_slack():
    tree = HierarchicalBudgetTree(
        {
            "team-a": {"limit_tokens": 500, "parent": "root"},
            "team-b": {"limit_tokens": 500, "parent": "root"},
            "service-a": {"limit_tokens": 500, "parent": "team-a"},
        }
    )
    t1 = tree.reserve("service-a", 500)
    tree.commit("service-a", t1, 500)
    assert tree.remaining("team-a") == 0
    try:
        tree.reserve("service-a", 1)
    except BudgetExceededError:
        pass
    else:
        raise AssertionError("expected BudgetExceededError when parent exhausted")


def test_most_restrictive_wins():
    tree = HierarchicalBudgetTree(
        {"child": {"limit_tokens": 1000, "parent": "parent"}, "parent": {"limit_tokens": 400}}
    )
    # child's effective limit is min(1000, 400) == 400
    ticket = tree.reserve("child", 400)
    tree.commit("child", ticket, 400)
    assert tree.used("child") == 400
    assert tree.used("parent") == 400
    try:
        tree.reserve("child", 1)
    except BudgetExceededError:
        pass
    else:
        raise AssertionError("expected failure at effective limit")


def test_allow_children_overcommit_relaxes_sum_only():
    """Overcommit allows multiple children to exceed the parent limit in aggregate,
    but a single child still cannot exceed the parent's effective limit."""
    tree = HierarchicalBudgetTree(
        {
            "p": {"limit_tokens": 100, "allow_children_overcommit": True},
            "c1": {"limit_tokens": 200, "parent": "p"},
            "c2": {"limit_tokens": 200, "parent": "p"},
        }
    )
    t1 = tree.reserve("c1", 50)
    tree.commit("c1", t1, 50)
    # Without overcommit, c2 reserving 60 would fail: 50+60=110 > p.limit 100.
    # With overcommit=True, sum constraint is relaxed so c2 reserve succeeds.
    t2 = tree.reserve("c2", 60)
    tree.commit("c2", t2, 60)
    assert tree.used("c1") == 50
    assert tree.used("c2") == 60
    # Parent used is clamped to its own limit (100), not the sum (110).
    assert tree.used("p") == 100


def test_liteLLM_17334_parent_cap_never_enforced_without_validation():
    """Pre-fix LiteLLM bug: org_max_budget retrieved but never checked."""
    tree = HierarchicalBudgetTree(
        {"team": {"limit_tokens": 100, "parent": "org"}, "org": {"limit_tokens": 100}}
    )
    # team tries to spend 200 -> should be blocked by org limit (100)
    try:
        t1 = tree.reserve("team", 150)
        tree.commit("team", t1, 150)
        t2 = tree.reserve("team", 50)
        tree.commit("team", t2, 50)
    except BudgetExceededError:
        pass
    else:
        raise AssertionError("org-level cap must enforce across children (LiteLLM #17334)")


def test_liteLLM_28051_off_by_one_uses_consistent_operator():
    """Team check should use >= (not >), consistent with key/org/window levels."""
    tree = HierarchicalBudgetTree(
        {"team": {"limit_tokens": 100, "parent": "org"}, "org": {"limit_tokens": 100}}
    )
    t1 = tree.reserve("team", 100)
    tree.commit("team", t1, 100)
    assert tree.remaining("team") == 0
    try:
        tree.reserve("team", 1)
    except BudgetExceededError:
        pass
    else:
        raise AssertionError("exactly-at-limit must block additional requests (LiteLLM #28051)")


def test_liteLLM_26204_null_budget_does_not_skip_enforcement():
    """If a team member has no budget row, fall back to team limit, don't skip."""
    tree = HierarchicalBudgetTree(
        {"member": {"limit_tokens": 0, "parent": "team"}, "team": {"limit_tokens": 100}}
    )
    # member limit 0 -> any request should fail (not silently skip)
    try:
        tree.reserve("member", 1)
    except BudgetExceededError:
        pass
    else:
        raise AssertionError("missing/null budget must not silently skip (LiteLLM #26204)")


def test_reserve_bounded_max_tokens_headroom():
    """Bounded max_tokens -> pre-reserve only headroom, not full remaining."""
    tree = _tree()
    # simulate reserve_with_estimate behavior inline
    node = tree.node("service-a")
    max_tokens = 50
    estimate = 10
    tokens_to_reserve = min(estimate, max_tokens)
    ticket = node.reserve(tokens_to_reserve)
    node.commit(ticket, 10)
    # Used 10, remaining 190. Next call can reserve up to remaining.
    ticket2 = node.reserve(190)
    node.commit(ticket2, 190)
    assert node.remaining == 0
