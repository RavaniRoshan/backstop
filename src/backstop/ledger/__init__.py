"""Backstop's spend ledger: the token budget ledger, the spend event schema and
the attribution context.

This package owns the ``backstop.ledger`` import name. The per-tenant token
budget ledger has held that name since the start (``TenantBudget``,
``BudgetLedger``, ``with_budget`` and friends); it now lives in
``backstop.ledger.budget``, inside this package, so one directory owns the whole
name instead of a module and a package of the same name sitting side by side.
Every existing ``from backstop.ledger import ...`` call site keeps resolving to
the same live objects, and the module-level ledger singleton stays shared.
"""
from __future__ import annotations

from .budget import (
    BudgetLedger,
    ReservationTicket,
    TenantBudget,
    get_current_tenant,
    get_ledger,
    reset_ledger,
    with_budget,
)
from .context import attribution, current_attribution, with_attribution
from .schema import (
    EVENT_ID_RE,
    OCCURRED_AT_RE,
    OUTCOMES,
    PRIORITIES,
    SCHEMA_VERSION,
    Attribution,
    SpendEvent,
    normalize_endpoint,
    utc_now,
)

__all__ = [
    "EVENT_ID_RE",
    "OCCURRED_AT_RE",
    "OUTCOMES",
    "PRIORITIES",
    "SCHEMA_VERSION",
    "Attribution",
    "BudgetLedger",
    "ReservationTicket",
    "SpendEvent",
    "TenantBudget",
    "attribution",
    "current_attribution",
    "get_current_tenant",
    "get_ledger",
    "normalize_endpoint",
    "reset_ledger",
    "utc_now",
    "with_attribution",
    "with_budget",
]
