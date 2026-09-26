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

The charge-back export is re-exported with them. A deployment that turns the
ledger on gets events and prices; what it wants next is the number finance asks
for, and that is :func:`build_chargeback` over the same objects rather than a
reimplementation of them. :func:`read_ledger` is here for the same reason: the
JSONL file a :class:`JsonlSink` writes is read by the module that wrote it.
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
from .export import (
    UNATTRIBUTED,
    ChargebackRow,
    ChargebackTotals,
    LedgerCorruptionError,
    LedgerRead,
    Period,
    build_chargeback,
    chargeback_totals,
    money,
    read_ledger,
    revenue_join,
    write_chargeback_csv,
)
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
from .sink import (
    DRAIN_THREAD_NAME,
    BoundedWriter,
    CloseReport,
    JsonlSink,
    LedgerSink,
    MemorySink,
    NullSink,
)

__all__ = [
    "DRAIN_THREAD_NAME",
    "EVENT_ID_RE",
    "OCCURRED_AT_RE",
    "OUTCOMES",
    "PRIORITIES",
    "SCHEMA_VERSION",
    "SECRET_QUERY_RE",
    "UNKNOWN_ENDPOINT",
    "UNATTRIBUTED",
    "Attribution",
    "BoundedWriter",
    "BudgetLedger",
    "ChargebackRow",
    "ChargebackTotals",
    "CloseReport",
    "CostBreakdown",
    "JsonlSink",
    "LedgerCorruptionError",
    "LedgerRead",
    "LedgerSink",
    "MemorySink",
    "NullSink",
    "Period",
    "PriceCatalog",
    "PriceEntry",
    "ReservationTicket",
    "SpendEvent",
    "TenantBudget",
    "attribution",
    "build_chargeback",
    "chargeback_totals",
    "compute_cost",
    "cost_from_dict",
    "cost_to_dict",
    "current_attribution",
    "get_current_tenant",
    "get_ledger",
    "money",
    "normalize_endpoint",
    "read_ledger",
    "reset_ledger",
    "resolve_cost_type",
    "revenue_join",
    "utc_now",
    "with_attribution",
    "with_budget",
    "write_chargeback_csv",
]
