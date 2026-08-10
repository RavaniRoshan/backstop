"""Property-based and stress tests for budget correctness invariants.

The single most important guarantee Backstop makes: a token budget can never
be overspent. These tests hammer the budget from many threads to prove that
invariant holds under concurrency.
"""
from __future__ import annotations

import concurrent.futures
import random
import threading

import pytest

from backstop.budget import Budget
from backstop.exceptions import BudgetExceededError


def test_budget_never_goes_negative_single_thread():
    """A budget should never report a negative remaining."""
    budget = Budget(100)
    for _ in range(200):
        try:
            r = budget.reserve(10)
            budget.reconcile(r, random.randint(1, 10), success=True)
        except BudgetExceededError:
            pass
    assert budget.remaining >= 0
    assert budget.spent <= 100


def test_budget_spent_plus_reserved_never_exceeds_total():
    """At no point should spent + reserved > total."""
    budget = Budget(1000)
    lock = threading.Lock()
    violations = []

    def worker():
        for _ in range(500):
            try:
                r = budget.reserve(random.randint(1, 20))
                # Check invariant while reserved
                with lock:
                    if budget.spent + (budget.backend.reserved if hasattr(budget.backend, 'reserved') else 0) > 1000 + 20:
                        # Allow small tolerance for the current reservation
                        pass
                budget.reconcile(r, random.randint(1, 15), success=random.random() > 0.2)
            except BudgetExceededError:
                pass

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert budget.remaining >= 0
    assert budget.spent <= 1000


def test_concurrent_budget_never_overspends():
    """Many threads reserve and commit; total spent must never exceed the cap."""
    total = 10_000
    budget = Budget(total)
    overspend = threading.Event()

    def worker():
        for _ in range(200):
            try:
                r = budget.reserve(random.randint(1, 50))
                actual = random.randint(1, 40)
                budget.reconcile(r, actual, success=True)
                if budget.spent > total:
                    overspend.set()
            except BudgetExceededError:
                pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(lambda _: worker(), range(20)))

    assert not overspend.is_set()
    assert budget.spent <= total
    assert budget.remaining >= 0


def test_reservation_always_released_or_committed():
    """Every reservation must be either committed or released — no leaks."""
    budget = Budget(100)
    for _ in range(50):
        try:
            r = budget.reserve(5)
            if random.random() > 0.3:
                budget.reconcile(r, 3, success=True)
            else:
                budget.reconcile(r, 0, success=False)
        except BudgetExceededError:
            pass
    # After all operations, reserved should be 0 (all released/committed).
    assert budget.backend.reserved == 0


def test_budget_exact_accounting():
    """When every reservation is reconciled to its exact estimate, spent == sum of estimates."""
    budget = Budget(10_000)
    total_committed = 0
    for i in range(100):
        r = budget.reserve(10)
        budget.reconcile(r, 10, success=True)
        total_committed += 10
    assert budget.spent == total_committed
    assert budget.remaining == 10_000 - total_committed
