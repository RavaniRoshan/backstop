import pytest

from backstop.budget import Budget
from backstop.exceptions import BudgetExceededError


def test_budget_reserves_and_reconciles_actual_usage():
    budget = Budget(100)
    reservation = budget.reserve(40)
    assert budget.remaining == 60
    budget.reconcile(reservation, 25, success=True)
    assert budget.spent == 25
    assert budget.remaining == 75


def test_budget_zero_blocks_immediately():
    budget = Budget(0)
    with pytest.raises(BudgetExceededError):
        budget.reserve(1)


def test_budget_none_is_unlimited():
    budget = Budget(None)
    reservation = budget.reserve(1_000_000)
    budget.reconcile(reservation, None, success=True)
    assert budget.remaining is None
    assert budget.spent == 0


def test_success_without_usage_keeps_estimate_charged():
    budget = Budget(100)
    reservation = budget.reserve(30)
    budget.reconcile(reservation, None, success=True)
    assert budget.spent == 30


def test_failed_request_releases_reservation_without_charge():
    budget = Budget(100)
    reservation = budget.reserve(30)
    budget.reconcile(reservation, None, success=False)
    assert budget.spent == 0
    assert budget.remaining == 100

