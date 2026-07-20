from __future__ import annotations

from dataclasses import dataclass

from .exceptions import BudgetExceededError
from .state_backends import BudgetBackend, InMemoryBudgetBackend


@dataclass(frozen=True)
class Reservation:
    tokens: int


class Budget:
    """Token budget that delegates storage to a pluggable :class:`BudgetBackend`.

    The default backend is in-process (``InMemoryBudgetBackend``). Pass a
    shared backend (e.g. ``RedisBudgetBackend``) to enforce one budget across
    processes/replicas. The public API (``reserve`` / ``reconcile`` /
    ``remaining`` / ``spent``) is unchanged from the in-process version so
    existing call sites keep working.
    """

    def __init__(
        self,
        total: int | None,
        backend: BudgetBackend | None = None,
    ) -> None:
        self.backend = backend or InMemoryBudgetBackend(total)

    @property
    def total(self) -> int | None:
        return self.backend.total

    @property
    def remaining(self) -> int | None:
        return self.backend.remaining

    @property
    def spent(self) -> int:
        return self.backend.spent

    def reserve(self, tokens: int) -> Reservation:
        tokens = max(0, tokens)
        if self.backend.total is None:
            return Reservation(tokens)
        if not self.backend.reserve(tokens):
            remaining = self.remaining or 0
            raise BudgetExceededError(
                f"request estimate {tokens} tokens exceeds remaining budget {remaining}"
            )
        return Reservation(tokens)

    async def areserve(self, tokens: int) -> Reservation:
        tokens = max(0, tokens)
        if self.backend.total is None:
            return Reservation(tokens)
        if not await self.backend.areserve(tokens):
            remaining = self.remaining or 0
            raise BudgetExceededError(
                f"request estimate {tokens} tokens exceeds remaining budget {remaining}"
            )
        return Reservation(tokens)

    def reconcile(
        self, reservation: Reservation, actual_tokens: int | None, *, success: bool
    ) -> None:
        charge = (
            reservation.tokens if success and actual_tokens is None else max(0, actual_tokens or 0)
        )
        self.backend.commit(reservation.tokens, charge)

    async def areconcile(
        self, reservation: Reservation, actual_tokens: int | None, *, success: bool
    ) -> None:
        charge = (
            reservation.tokens if success and actual_tokens is None else max(0, actual_tokens or 0)
        )
        await self.backend.acommit(reservation.tokens, charge)
