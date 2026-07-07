from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

    from .budget import Reservation
    from .state import BackstopState


def is_streaming(body: Any) -> bool:
    if isinstance(body, dict):
        return bool(body.get("stream", False))
    return False


def setup_streaming(
    response: httpx.Response,
    state: BackstopState,
    reservation: Reservation,
    *,
    success: bool,
    tenant_budget: Any = None,
) -> None:
    from .ledger import ReservationTicket as LedgerReservation

    original_close = response.close
    reconciled = False

    def wrapped_close() -> None:
        nonlocal reconciled
        if reconciled:
            return
        reconciled = True
        try:
            if tenant_budget is not None and isinstance(reservation, LedgerReservation):
                if success:
                    tenant_budget.commit(reservation, None)
                else:
                    tenant_budget.commit(reservation, 0)
            else:
                state.budget.reconcile(reservation, None, success=success)
        finally:
            original_close()

    response.close = wrapped_close


async def async_setup_streaming(
    response: httpx.Response,
    state: BackstopState,
    reservation: Reservation,
    *,
    success: bool,
    tenant_budget: Any = None,
) -> None:
    from .ledger import ReservationTicket as LedgerReservation

    original_aclose = response.aclose
    reconciled = False

    async def wrapped_aclose() -> None:
        nonlocal reconciled
        if reconciled:
            return
        reconciled = True
        try:
            if tenant_budget is not None and isinstance(reservation, LedgerReservation):
                if success:
                    tenant_budget.commit(reservation, None)
                else:
                    tenant_budget.commit(reservation, 0)
            else:
                await state.budget.areconcile(reservation, None, success=success)
        finally:
            await original_aclose()

    response.aclose = wrapped_aclose
