"""Hierarchical budgets (Launch Improvement B2).

Per the deep-research finding, the only correct invariant is:
* a child's usage is charged to the child AND every ancestor (recursive)
* a child can never push any ancestor past its limit
* the most-restrictive limit always applies (parent wins if tighter)
* bounded ``max_tokens`` enables pre-reservation of headroom; unbounded
  requests accept a documented one-request overshoot (no surveyed system
  guarantees zero overshoot on cost/unknown-output requests).

``allow_children_limit_overcommit`` relaxes only the *sum-of-children ≤
parent* constraint — it never permits a single child to exceed its parent
(YTsaurus model, LiteLLM #17334 lesson).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .exceptions import BudgetExceededError


@dataclass
class BudgetNode:
    node_id: str
    limit_tokens: int
    parent: "BudgetNode | None" = None
    allow_children_overcommit: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _used: int = 0
    _reserved: int = 0
    _children: dict[str, "BudgetNode"] = field(default_factory=dict)

    @property
    def remaining(self) -> int:
        return max(0, self.limit_tokens - self._used - self._reserved)

    def effective_limit(self) -> int:
        """Most-restrictive wins: min(self.limit_tokens, parent.effective_limit())."""
        if self.parent is None or self.parent is self:
            return self.limit_tokens
        return min(self.limit_tokens, self.parent.effective_limit())

    def _ancestors(self) -> list["BudgetNode"]:
        out: list[BudgetNode] = []
        cur: BudgetNode | None = self.parent
        while cur is not None and cur is not self:
            out.append(cur)
            cur = cur.parent
        return out

    def reserve(self, tokens: int) -> "_Reservation":
        """Reserve ``tokens`` against this node AND every ancestor.

        Fails if any ancestor would exceed its effective limit. The parent
        reservation also validates that the *sum* of its children's usage
        does not push it past its limit — unless ``allow_children_overcommit``.
        """
        if tokens <= 0:
            return _Reservation(self.node_id, 0)
        effective = self.effective_limit()
        with self._lock:
            if self._used + self._reserved + tokens > effective:
                raise BudgetExceededError(
                    f"hierarchical budget {self.node_id!r}: "
                    f"request {tokens} would exceed effective limit {effective} "
                    f"(used={self._used}, reserved={self._reserved})"
                )
            self._reserved += tokens
        for ancestor in self._ancestors():
            # charge ancestor: validate its effective limit too
            eff = ancestor.effective_limit()
            with ancestor._lock:
                # sum-of-children constraint unless overcommit is allowed
                if not ancestor.allow_children_overcommit:
                    total_child_usage = ancestor._used + ancestor._reserved + tokens
                    if total_child_usage > eff:
                        raise BudgetExceededError(
                            f"hierarchical budget {ancestor.node_id!r}: "
                            f"sum of children + new {total_child_usage} would exceed limit {eff}"
                        )
                ancestor._reserved += tokens
        return _Reservation(self.node_id, tokens)

    def commit(self, ticket: "_Reservation", actual_tokens: int | None) -> None:
        if ticket.tokens <= 0:
            return
        charge = actual_tokens if actual_tokens is not None else ticket.tokens
        charge = max(0, charge)
        with self._lock:
            self._reserved = max(0, self._reserved - ticket.tokens)
            self._used = min(self.limit_tokens, self._used + charge)
        for ancestor in self._ancestors():
            with ancestor._lock:
                ancestor._reserved = max(0, ancestor._reserved - ticket.tokens)
                ancestor._used = min(ancestor.limit_tokens, ancestor._used + charge)

    @property
    def used(self) -> int:
        return self._used

    @property
    def reserved(self) -> int:
        return self._reserved


@dataclass
class _Reservation:
    node_id: str
    tokens: int


class HierarchicalBudgetTree:
    """Tree of BudgetNodes with hierarchical enforcements."""

    def __init__(self, nodes: dict[str, dict[str, Any]]) -> None:
        self._nodes: dict[str, BudgetNode] = {}
        self._root = BudgetNode(node_id="__root__", limit_tokens=10**18, allow_children_overcommit=True)
        self._nodes[self._root.node_id] = self._root
        # two-pass: build all nodes first, then wire parents
        raw: dict[str, BudgetNode] = {}
        for nid, cfg in nodes.items():
            raw[nid] = BudgetNode(
                node_id=nid,
                limit_tokens=int(cfg.get("limit_tokens", 0)),
                allow_children_overcommit=bool(cfg.get("allow_children_overcommit", False)),
            )
        for nid, cfg in nodes.items():
            parent_id = cfg.get("parent")
            if parent_id and parent_id in raw:
                raw[nid].parent = raw[parent_id]
                raw[parent_id]._children[nid] = raw[nid]
            else:
                raw[nid].parent = self._root
                self._root._children[nid] = raw[nid]
        self._nodes.update(raw)

    def node(self, node_id: str) -> BudgetNode | None:
        return self._nodes.get(node_id)

    def reserve(self, node_id: str, tokens: int) -> _Reservation:
        node = self._nodes.get(node_id)
        if node is None:
            raise BudgetExceededError(f"unknown hierarchical budget node {node_id!r}")
        return node.reserve(tokens)

    def commit(self, node_id: str, ticket: _Reservation, actual_tokens: int | None) -> None:
        node = self._nodes.get(node_id)
        if node is not None:
            node.commit(ticket, actual_tokens)

    def remaining(self, node_id: str) -> int:
        node = self._nodes.get(node_id)
        return node.remaining if node is not None else 0

    def used(self, node_id: str) -> int:
        node = self._nodes.get(node_id)
        return node.used if node is not None else 0

    def is_over_limit(self, node_id: str) -> bool:
        node = self._nodes.get(node_id)
        return node.remaining <= 0 if node is not None else True

    @property
    def nodes(self) -> dict[str, BudgetNode]:
        return dict(self._nodes)
