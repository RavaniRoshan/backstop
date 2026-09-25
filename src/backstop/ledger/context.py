"""Ambient attribution for the Backstop spend ledger.

The transport reads :func:`current_attribution` when it builds a
:class:`~backstop.ledger.schema.SpendEvent`, so a call site declares who is
spending money once, at the top of the function that spends it:

.. code-block:: python

    from backstop import attribution, with_attribution, current_attribution

    with attribution(team="payments", feature="checkout-v2"):
        client.chat.completions.create(...)

    @with_attribution(agent="refund-bot")
    def handle_refund(ticket): ...

    current_attribution().team

The value lives in one module-level :class:`~contextvars.ContextVar` holding a
frozen ``Attribution``, defaulting to an all-``None`` ``Attribution()``. An
un-attributed process behaves exactly as before, so no existing call site has
to be rewritten.

Scopes merge: an inner scope wins on the fields it sets and inherits the rest,
and the outer value is restored on exit, including when the body raises.

Because it is a ``ContextVar``, an active scope follows ``asyncio`` tasks and
any thread-pool submission that copies context — which is what the transport
needs, since it is called from async code. A raw ``loop.run_in_executor`` call
does *not* copy context; wrap the callable so it copies one.
"""
from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar, Token
from typing import Any, TypeVar, cast

from .schema import Attribution

__all__ = ["attribution", "current_attribution", "with_attribution"]

_F = TypeVar("_F", bound=Callable[..., Any])

_attribution_var: ContextVar[Attribution] = ContextVar(
    "backstop_attribution", default=Attribution()
)


def current_attribution() -> Attribution:
    """Return the attribution active in the current context, never ``None``."""
    return _attribution_var.get()


def _enter(override: Attribution) -> Token:
    """Merge ``override`` onto the active value and install the result."""
    return _attribution_var.set(current_attribution().merge(override))


def attribution(**fields: str) -> AbstractContextManager[Attribution]:
    """Scope attribution to a block, merging onto whatever is already active.

    Entering the scope yields the merged ``Attribution``, so a caller can assert
    on it or pass it on. The previous value is restored on exit, including on
    exception. Field names and value types are checked here, at the call, so a
    typo fails at the call site rather than at the start of the block.
    """
    return _scope(Attribution.from_fields(**fields))


@contextmanager
def _scope(override: Attribution) -> Iterator[Attribution]:
    token = _enter(override)
    try:
        yield _attribution_var.get()
    finally:
        _attribution_var.reset(token)


def with_attribution(**fields: str) -> Callable[[_F], _F]:
    """Decorate a function or method so every call runs under these fields.

    Works on sync and async callables. The merge is resolved per call, not per
    decoration, so a decorated function called inside an outer scope inherits
    that scope and its own fields win. Methods are ordinary functions here: the
    receiver is passed through untouched.
    """
    override = Attribution.from_fields(**fields)

    def decorate(func: _F) -> _F:
        if inspect.isgeneratorfunction(func):
            raise TypeError(
                "with_attribution cannot decorate generator function "
                f"{func.__qualname__!r}: the body would run after the scope had "
                "already been restored. Use `with attribution(...)` in the body."
            )
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                token = _enter(override)
                try:
                    return await func(*args, **kwargs)
                finally:
                    _attribution_var.reset(token)

            return cast(_F, async_wrapper)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            token = _enter(override)
            try:
                return func(*args, **kwargs)
            finally:
                _attribution_var.reset(token)

        return cast(_F, wrapper)

    return decorate
