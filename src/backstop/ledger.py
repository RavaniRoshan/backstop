from __future__ import annotations

import threading
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass, field

from .exceptions import BudgetExceededError


@dataclass
class ReservationTicket:
    tenant_id: str
    tokens: int


@dataclass
class TenantBudget:
    tenant_id: str
    limit_tokens: int
    window: str | None = None
    on_exceed: str = "raise"
    used: int = 0
    reserved: int = 0
    parent: "TenantBudget | None" = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def remaining(self) -> int:
        return max(0, self.limit_tokens - self.used - self.reserved)

    def reserve(self, tokens: int) -> ReservationTicket:
        with self._lock:
            if self.remaining < tokens:
                raise BudgetExceededError(
                    f"tenant {self.tenant_id!r} budget {self.limit_tokens}: "
                    f"request estimate {tokens} tokens exceeds remaining {self.remaining}"
                )
            self.reserved += tokens
        if self.parent is not None and self.parent is not self:
            try:
                self.parent.reserve(tokens)
            except BudgetExceededError:
                with self._lock:
                    self.reserved -= tokens
                raise
        return ReservationTicket(self.tenant_id, tokens)

    def commit(self, ticket: ReservationTicket, actual: int | None) -> None:
        if ticket.tenant_id != self.tenant_id:
            return
        with self._lock:
            self.reserved = max(0, self.reserved - ticket.tokens)
            self.used = min(self.limit_tokens, self.used + (actual or ticket.tokens))
        if self.parent is not None and self.parent is not self:
            self.parent.commit(ReservationTicket(self.parent.tenant_id, ticket.tokens), actual)


class BudgetLedger:
    def __init__(self) -> None:
        self._tenants: dict[str, TenantBudget] = {}
        self._lock = threading.Lock()

    def register(self, budgets: dict[str, TenantBudget]) -> None:
        with self._lock:
            self._tenants.update(budgets)

    def get(self, tenant_id: str) -> TenantBudget | None:
        with self._lock:
            return self._tenants.get(tenant_id)

    def reserve(self, tenant_id: str, tokens: int) -> ReservationTicket:
        budget = self.get(tenant_id)
        if budget is None:
            raise BudgetExceededError(f"no budget configured for tenant {tenant_id!r}")
        return budget.reserve(tokens)

    def commit(self, tenant_id: str, ticket: ReservationTicket, actual: int | None) -> None:
        budget = self.get(tenant_id)
        if budget is not None:
            budget.commit(ticket, actual)

    @property
    def tenants(self) -> dict[str, TenantBudget]:
        with self._lock:
            return dict(self._tenants)


_tenant_var: ContextVar[str | None] = ContextVar("backstop_tenant", default=None)
_ledger: BudgetLedger = BudgetLedger()


def get_ledger() -> BudgetLedger:
    return _ledger


def get_current_tenant() -> str | None:
    return _tenant_var.get()


@contextmanager
def with_budget(tenant_id: str):
    token = _tenant_var.set(tenant_id)
    try:
        yield
    finally:
        _tenant_var.reset(token)


def reset_ledger() -> None:
    global _ledger
    _ledger = BudgetLedger()
