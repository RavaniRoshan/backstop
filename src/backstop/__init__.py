from .config import BackstopConfig, Priority
from .cost import CostEstimate
from .cost import estimate as cost_estimate

__version__ = "0.6.0"
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
from .ledger import (
    Attribution,
    BudgetLedger,
    ReservationTicket,
    SpendEvent,
    TenantBudget,
    attribution,
    current_attribution,
    get_current_tenant,
    get_ledger,
    with_attribution,
    with_budget,
)
from .wrapper import Backstop

__all__ = [
    "AfterResponseHook",
    "Attribution",
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
    "SpendEvent",
    "TenantBudget",
    "UnsupportedClientError",
    "BackstopError",
    "attribution",
    "budgets",
    "count_tokens",
    "current_attribution",
    "get_current_tenant",
    "with_attribution",
    "with_budget",
    "cost",
]

# `backstop.budgets` is kept as a public alias for the process-global ledger, but
# it must never be a snapshot: `reset_ledger()` rebinds the module global, and a
# value bound at import time would keep pointing at the discarded instance. So it
# is resolved on every attribute access instead (PEP 562).


def __getattr__(name: str):
    if name == "budgets":
        return get_ledger()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
cost = type("_CostModule", (), {"estimate": staticmethod(cost_estimate)})()

