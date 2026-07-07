from .config import BackstopConfig, Priority
from .cost import CostEstimate, estimate as cost_estimate
from .exceptions import (
    BackstopError,
    BudgetExceededError,
    CircuitBreakerOpenError,
    LatencyBudgetExceededError,
    UnsupportedClientError,
)
from .extract import count_tokens
from .hooks import AfterResponseHook, BeforeRequestHook
from .latency import BackstopMeta
from .ledger import BudgetLedger, ReservationTicket, TenantBudget, get_current_tenant, get_ledger, with_budget
from .wrapper import Backstop

__all__ = [
    "AfterResponseHook",
    "Backstop",
    "BackstopConfig",
    "BackstopMeta",
    "BeforeRequestHook",
    "BudgetExceededError",
    "BudgetLedger",
    "CircuitBreakerOpenError",
    "CostEstimate",
    "LatencyBudgetExceededError",
    "Priority",
    "ReservationTicket",
    "TenantBudget",
    "UnsupportedClientError",
    "BackstopError",
    "budgets",
    "count_tokens",
    "get_current_tenant",
    "with_budget",
    "cost",
]

budgets = get_ledger()
cost = type("_CostModule", (), {"estimate": staticmethod(cost_estimate)})()

