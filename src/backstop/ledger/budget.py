from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal

from ..exceptions import BudgetExceededError


@dataclass
class ReservationTicket:
    tenant_id: str
    tokens: int
    #: The dollar estimate this ticket holds, if the tenant has a dollar
    #: ceiling.
    usd: Decimal = Decimal("0.000000")


@dataclass
class TenantBudget:
    tenant_id: str
    limit_tokens: int
    window: str | None = None
    on_exceed: str = "raise"
    used: int = 0
    reserved: int = 0
    #: The tenant's dollar ceiling, or ``None`` for a token-only tenant. A
    #: request is admitted only if it fits under **both** ceilings.
    limit_usd: Decimal | None = None
    used_usd: Decimal = Decimal("0.000000")
    reserved_usd: Decimal = Decimal("0.000000")
    parent: "TenantBudget | None" = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def remaining(self) -> int:
        return max(0, self.limit_tokens - self.used - self.reserved)

    @property
    def remaining_usd(self) -> Decimal | None:
        """The dollars still available, or ``None`` when there is no ceiling."""
        if self.limit_usd is None:
            return None
        return max(Decimal("0.000000"), self.limit_usd - self.used_usd - self.reserved_usd)

    def reserve(self, tokens: int, usd: Decimal = Decimal("0.000000")) -> ReservationTicket:
        """Hold this tenant's budget for a request.

        Both ceilings are checked under the same lock, so a request is
        admitted only if it fits under the token ceiling *and* the dollar
        ceiling. The parent is reserved too, so a child's spend is always
        inside the parent's.
        """
        with self._lock:
            if self.remaining < tokens:
                raise BudgetExceededError(
                    f"tenant {self.tenant_id!r} budget {self.limit_tokens}: "
                    f"request estimate {tokens} tokens exceeds remaining {self.remaining}"
                )
            remaining_usd = self.remaining_usd
            if remaining_usd is not None and remaining_usd < usd:
                raise BudgetExceededError(
                    f"tenant {self.tenant_id!r} budget {self.limit_usd} USD: "
                    f"request estimate {usd} USD exceeds remaining {remaining_usd}"
                )
            self.reserved += tokens
            self.reserved_usd += usd
        if self.parent is not None and self.parent is not self:
            try:
                self.parent.reserve(tokens, usd)
            except BudgetExceededError:
                with self._lock:
                    self.reserved -= tokens
                    self.reserved_usd = max(Decimal("0.000000"), self.reserved_usd - usd)
                raise
        return ReservationTicket(self.tenant_id, tokens, usd)

    def commit(
        self,
        ticket: ReservationTicket,
        actual: int | None,
        actual_usd: Decimal | None = None,
    ) -> None:
        """Settle a reservation against what the request actually cost."""
        if ticket.tenant_id != self.tenant_id:
            return
        with self._lock:
            self.reserved = max(0, self.reserved - ticket.tokens)
            self.reserved_usd = max(Decimal("0.000000"), self.reserved_usd - ticket.usd)
            # ``actual`` is a measurement, and zero is a measurement. The old
            # ``actual or ticket.tokens`` treated a zero as "no measurement
            # available" and charged the *estimate* instead — so a request
            # that really did use no tokens was billed for the estimate, and
            # a tenant budget drifted upward for every such request. The
            # distinction the code needs is "None" from "zero", so it is
            # spelled out.
            charge = ticket.tokens if actual is None else actual
            self.used = min(self.limit_tokens, self.used + charge)
            usd_charge = ticket.usd if actual_usd is None else actual_usd
            if self.limit_usd is not None:
                self.used_usd = min(self.limit_usd, self.used_usd + usd_charge)
            else:
                self.used_usd += usd_charge
        if self.parent is not None and self.parent is not self:
            self.parent.commit(
                ReservationTicket(self.parent.tenant_id, ticket.tokens, ticket.usd),
                actual,
                actual_usd,
            )


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

    def reserve(
        self, tenant_id: str, tokens: int, usd: Decimal = Decimal("0.000000")
    ) -> ReservationTicket:
        budget = self.get(tenant_id)
        if budget is None:
            raise BudgetExceededError(f"no budget configured for tenant {tenant_id!r}")
        return budget.reserve(tokens, usd)

    def commit(
        self,
        tenant_id: str,
        ticket: ReservationTicket,
        actual: int | None,
        actual_usd: Decimal | None = None,
    ) -> None:
        budget = self.get(tenant_id)
        if budget is not None:
            budget.commit(ticket, actual, actual_usd)

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
