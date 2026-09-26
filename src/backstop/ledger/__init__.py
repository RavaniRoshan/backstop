"""Backstop's spend ledger: the token budget ledger, the spend event schema, the
attribution context, and the price catalog.

This package owns the ``backstop.ledger`` import name. The per-tenant token
budget ledger has held that name since the start (``TenantBudget``,
``BudgetLedger``, ``with_budget`` and friends); it now lives in
``backstop.ledger.budget``, inside this package, so one directory owns the whole
name instead of a module and a package of the same name sitting side by side.
Every existing ``from backstop.ledger import ...`` call site keeps resolving to
the same live objects, and the module-level ledger singleton stays shared.

The price catalog itself lives one level up, in
:mod:`backstop.pricing_catalog`, because it is not ledger-internal: the chargeback
export and the CLI reach for it too. It is re-exported here so a caller holding
a ``SpendEvent`` has one import for the record and the price that fills its
``cost``.

The sinks — ``LedgerSink`` and its four implementations, plus the
``BoundedWriter`` that keeps them off the request path — are re-exported for the
same reason: a caller wiring a ledger needs the event, the price and the place it
goes, and three imports of the same object is three chances to get one wrong.
"""
from __future__ import annotations

from ..pricing_catalog import CostBreakdown, PriceCatalog, PriceEntry, compute_cost
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
    SECRET_QUERY_RE,
    UNKNOWN_ENDPOINT,
    Attribution,
    SpendEvent,
    cost_from_dict,
    cost_to_dict,
    normalize_endpoint,
    resolve_cost_type,
    utc_now,
)
from .sink import BoundedWriter, JsonlSink, LedgerSink, MemorySink, NullSink

__all__ = [
    "EVENT_ID_RE",
    "OCCURRED_AT_RE",
    "OUTCOMES",
    "PRIORITIES",
    "SCHEMA_VERSION",
    "SECRET_QUERY_RE",
    "UNKNOWN_ENDPOINT",
    "Attribution",
    "BoundedWriter",
    "BudgetLedger",
    "CostBreakdown",
    "JsonlSink",
    "LedgerSink",
    "MemorySink",
    "NullSink",
    "PriceCatalog",
    "PriceEntry",
    "ReservationTicket",
    "SpendEvent",
    "TenantBudget",
    "attribution",
    "compute_cost",
    "cost_from_dict",
    "cost_to_dict",
    "current_attribution",
    "get_current_tenant",
    "get_ledger",
    "normalize_endpoint",
    "reset_ledger",
    "resolve_cost_type",
    "utc_now",
    "with_attribution",
    "with_budget",
]
