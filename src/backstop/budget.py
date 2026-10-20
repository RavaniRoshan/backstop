from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .exceptions import BudgetExceededError
from .state_backends import BudgetBackend, InMemoryBudgetBackend


@dataclass(frozen=True)
class Reservation:
    """What a request is holding: tokens, and optionally dollars.

    ``usd`` is the *estimate* of what the request will cost. It is zero when
    there is no dollar ceiling, and it is reconciled against the exact cost
    when the request completes.
    """

    tokens: int
    usd: Decimal = Decimal("0.000000")


class Budget:
    """Token budget that delegates storage to a pluggable :class:`BudgetBackend`.

    The default backend is in-process (``InMemoryBudgetBackend``). Pass a
    shared backend (e.g. ``RedisBudgetBackend``) to enforce one budget across
    processes/replicas. The public API (``reserve`` / ``reconcile`` /
    ``remaining`` / ``spent``) is unchanged from the in-process version so
    existing call sites keep working.

    **A second ceiling, in dollars.** ``total_usd`` caps what the session may
    spend, and it is checked against the *same* reservation as the token
    ceiling: a request is admitted only if both would survive it. The dollar
    figure is a reservation of an estimate, reconciled to the exact cost when
    the request completes — so the ceiling is a real ceiling rather than a
    running total that is always slightly behind.
    """

    def __init__(
        self,
        total: int | None,
        backend: BudgetBackend | None = None,
        total_usd: Decimal | None = None,
    ) -> None:
        self.backend = backend or InMemoryBudgetBackend(total, total_usd=total_usd)

    @property
    def total(self) -> int | None:
        return self.backend.total

    @property
    def remaining(self) -> int | None:
        return self.backend.remaining

    @property
    def spent(self) -> int:
        return self.backend.spent

    @property
    def total_usd(self) -> Decimal | None:
        """The dollar ceiling, or ``None`` when there is none."""
        return self.backend.total_usd

    @property
    def spent_usd(self) -> Decimal:
        """The dollars spent so far."""
        return self.backend.spent_usd

    @property
    def reserved_usd(self) -> Decimal:
        """The dollars reserved by in-flight requests."""
        return self.backend.reserved_usd

    @property
    def remaining_usd(self) -> Decimal | None:
        """The dollars still available, or ``None`` when there is no ceiling."""
        total = self.backend.total_usd
        if total is None:
            return None
        return max(
            Decimal("0.000000"),
            total - self.backend.spent_usd - self.backend.reserved_usd,
        )

    def reserve(self, tokens: int, usd: Decimal = Decimal("0.000000")) -> Reservation:
        tokens = max(0, tokens)
        if not self.backend.reserve_with_usd(tokens, usd):
            remaining = self.remaining or 0
            remaining_usd = self.remaining_usd
            raise BudgetExceededError(
                f"request estimate {tokens} tokens exceeds remaining budget {remaining}"
                + (
                    f" (and {usd} USD against {remaining_usd} remaining)"
                    if remaining_usd is not None
                    else ""
                )
            )
        return Reservation(tokens, usd)

    async def areserve(
        self, tokens: int, usd: Decimal = Decimal("0.000000")
    ) -> Reservation:
        tokens = max(0, tokens)
        if not await self.backend.areserve(tokens, usd):
            remaining = self.remaining or 0
            remaining_usd = self.remaining_usd
            raise BudgetExceededError(
                f"request estimate {tokens} tokens exceeds remaining budget {remaining}"
                + (
                    f" (and {usd} USD against {remaining_usd} remaining)"
                    if remaining_usd is not None
                    else ""
                )
            )
        return Reservation(tokens, usd)

    def reconcile(
        self,
        reservation: Reservation,
        actual_tokens: int | None,
        *,
        success: bool,
        actual_usd: Decimal | None = None,
    ) -> None:
        """Settle a reservation against what the request actually cost.

        ``actual_usd`` is the exact cost from the ledger. ``None`` means there
        is no measurement — the request failed, or the ledger is off — and the
        estimate stands.
        """
        charge = (
            reservation.tokens if success and actual_tokens is None else max(0, actual_tokens or 0)
        )
        usd_charge = (
            reservation.usd
            if success and actual_usd is None
            else max(Decimal("0.000000"), actual_usd or Decimal("0.000000"))
        )
        if usd_charge == 0:
            # The one-argument form, so a backend written before dollar
            # ceilings existed keeps working.
            self.backend.commit(reservation.tokens, charge)
        else:
            self.backend.commit_with_usd(reservation.tokens, charge, usd_charge)

    async def areconcile(
        self,
        reservation: Reservation,
        actual_tokens: int | None,
        *,
        success: bool,
        actual_usd: Decimal | None = None,
    ) -> None:
        charge = (
            reservation.tokens if success and actual_tokens is None else max(0, actual_tokens or 0)
        )
        usd_charge = (
            reservation.usd
            if success and actual_usd is None
            else max(Decimal("0.000000"), actual_usd or Decimal("0.000000"))
        )
        if usd_charge == 0:
            # The one-argument form, so a backend written before dollar
            # ceilings existed keeps working.
            await self.backend.acommit(reservation.tokens, charge)
        else:
            await self.backend.acommit(reservation.tokens, charge, usd_charge)
