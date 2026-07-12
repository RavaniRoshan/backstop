from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

    from .budget import Reservation
    from .state import BackstopState


def is_streaming(body: Any) -> bool:
    if isinstance(body, dict):
        return bool(body.get("stream", False))
    return False


def _extract_sse_usage(response_text: str) -> int | None:
    """Extract token usage from an SSE streaming response text.

    Delegates to :func:`backstop.extract._usage_from_sse_text` so the SSE
    usage-parsing logic lives in one place. Returns None if no usage is found;
    callers then fall back to the reservation estimate.
    """
    from .extract import _usage_from_sse_text

    return _usage_from_sse_text(response_text)


def _int_or_zero(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int) and value >= 0:
            return value
    return None


def _reconcile_usage(
    state: BackstopState,
    reservation: Reservation,
    tenant_budget: Any,
    actual_tokens: int | None,
    *,
    success: bool,
) -> None:
    """Commit/charge the budget to the actual streamed usage.

    Falls back to the reservation estimate only when the provider emitted no
    usage block in the stream (actual_tokens is None) and the request succeeded.
    """
    from .ledger import ReservationTicket as LedgerReservation

    if tenant_budget is not None and isinstance(reservation, LedgerReservation):
        if success:
            tenant_budget.commit(reservation, actual_tokens if actual_tokens is not None else 0)
        else:
            tenant_budget.commit(reservation, 0)
    else:
        state.budget.reconcile(reservation, actual_tokens, success=success)


def setup_streaming(
    response: httpx.Response,
    state: BackstopState,
    reservation: Reservation,
    *,
    success: bool,
    tenant_budget: Any = None,
    created_at: float | None = None,
) -> None:
    """Wire budget reconciliation onto a streaming response.

    The response body is consumed lazily by the caller (the SDK iterates the
    SSE stream). We wrap ``iter_raw`` so every chunk is accumulated; the budget
    is reconciled against the real usage parsed from the accumulated bytes when
    the response is closed. This avoids eagerly reading the stream at setup time
    (which would starve the consumer) while still reconciling to actual tokens.
    """
    from .ledger import ReservationTicket as LedgerReservation

    original_close = response.close
    original_iter_raw = response.iter_raw
    accumulated: list[bytes] = []
    reconciled = False
    first_chunk_at: float | None = None

    # If the transport already buffered the body (e.g. a mock transport that
    # materializes the SSE body up front), capture it now so reconciliation has
    # the full usage even though the consumer will use the cached fast path.
    if hasattr(response, "_content") and response._content:
        accumulated.append(response._content)

    def iter_raw_wrapper(*args: Any, **kwargs: Any):
        nonlocal first_chunk_at
        for chunk in original_iter_raw(*args, **kwargs):
            if first_chunk_at is None:
                first_chunk_at = time.monotonic()
            accumulated.append(chunk)
            yield chunk

    response.iter_raw = iter_raw_wrapper

    def reconcile_now() -> None:
        full_text = b"".join(accumulated).decode("utf-8", errors="replace")
        actual_tokens = _extract_sse_usage(full_text)
        _reconcile_usage(
            state, reservation, tenant_budget, actual_tokens, success=success
        )
        meta = getattr(response, "_backstop_meta", None)
        if meta is not None:
            meta.actual_tokens = actual_tokens
            if first_chunk_at is not None and created_at is not None:
                meta.first_chunk_ms = (first_chunk_at - created_at) * 1000

    def wrapped_close() -> None:
        nonlocal reconciled
        if reconciled:
            return
        reconciled = True
        try:
            reconcile_now()
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
    created_at: float | None = None,
) -> None:
    """Async twin of :func:`setup_streaming`."""
    original_aclose = response.aclose
    original_aiter_raw = response.aiter_raw
    accumulated: list[bytes] = []
    reconciled = False
    first_chunk_at: float | None = None

    if hasattr(response, "_content") and response._content:
        accumulated.append(response._content)

    async def aiter_raw_wrapper(*args: Any, **kwargs: Any):
        nonlocal first_chunk_at
        async for chunk in original_aiter_raw(*args, **kwargs):
            if first_chunk_at is None:
                first_chunk_at = time.monotonic()
            accumulated.append(chunk)
            yield chunk

    response.aiter_raw = aiter_raw_wrapper

    async def reconcile_now() -> None:
        full_text = b"".join(accumulated).decode("utf-8", errors="replace")
        actual_tokens = _extract_sse_usage(full_text)
        _reconcile_usage(
            state, reservation, tenant_budget, actual_tokens, success=success
        )
        meta = getattr(response, "_backstop_meta", None)
        if meta is not None:
            meta.actual_tokens = actual_tokens
            if first_chunk_at is not None and created_at is not None:
                meta.first_chunk_ms = (first_chunk_at - created_at) * 1000

    async def wrapped_aclose() -> None:
        nonlocal reconciled
        if reconciled:
            return
        reconciled = True
        try:
            await reconcile_now()
        finally:
            await original_aclose()

    response.aclose = wrapped_aclose
