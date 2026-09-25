"""Backstop's spend ledger: the spend event schema and attribution context.

This package also owns the ``backstop.ledger`` import name that the in-process
budget ledger has held since the start (``TenantBudget``, ``BudgetLedger``,
``with_budget`` and friends). A package directory shadows a same-named module,
so the budget-ledger module is loaded here once under a private alias and
re-exported: every existing ``from backstop.ledger import ...`` call site keeps
resolving to the same live objects, and the module-level ledger singleton stays
shared.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from .context import attribution, current_attribution, with_attribution
from .schema import Attribution, SpendEvent

_BUDGET_LEDGER_ALIAS = "backstop._budget_ledger"
_BUDGET_LEDGER_SOURCE = Path(__file__).resolve().parent.parent / "ledger.py"


def _load_budget_ledger() -> ModuleType:
    """Load the sibling ``ledger.py`` under a private module name, once."""
    loaded = sys.modules.get(_BUDGET_LEDGER_ALIAS)
    if loaded is not None:
        return loaded
    spec = importlib.util.spec_from_file_location(
        _BUDGET_LEDGER_ALIAS, _BUDGET_LEDGER_SOURCE
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the budget ledger from {_BUDGET_LEDGER_SOURCE}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_BUDGET_LEDGER_ALIAS] = module
    spec.loader.exec_module(module)
    return module


_budget_ledger = _load_budget_ledger()
BudgetLedger = _budget_ledger.BudgetLedger
ReservationTicket = _budget_ledger.ReservationTicket
TenantBudget = _budget_ledger.TenantBudget
get_current_tenant = _budget_ledger.get_current_tenant
get_ledger = _budget_ledger.get_ledger
reset_ledger = _budget_ledger.reset_ledger
with_budget = _budget_ledger.with_budget

__all__ = [
    "Attribution",
    "BudgetLedger",
    "ReservationTicket",
    "SpendEvent",
    "TenantBudget",
    "attribution",
    "current_attribution",
    "get_current_tenant",
    "get_ledger",
    "reset_ledger",
    "with_attribution",
    "with_budget",
]
