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
needs, since it is called from async code. A bare ``executor.submit`` does
*not* copy context, and neither does ``loop.run_in_executor``, so the worker
would record an empty attribution. Copy the context where the work is handed
over:

.. code-block:: python

    ctx = contextvars.copy_context()
    loop.run_in_executor(executor, ctx.run, blocking_call, arg)
    ctx.run(lambda: some_function())
"""
from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from contextlib import AbstractContextManager
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


class _AttributionScope(AbstractContextManager[Attribution]):
    """One attribution scope, single use because it holds one token.

    ``contextlib``'s generator context manager answers a re-entry attempt with an
    ``AttributeError`` out of its own internals, so the scope is spelled out
    here instead: entering twice says what happened and points at the fix.
    """

    def __init__(self, override: Attribution) -> None:
        self._override = override
        self._entered = False
        self._token: Token | None = None

    def __enter__(self) -> Attribution:
        if self._entered:
            raise RuntimeError(
                "an attribution scope is single use; call attribution(...) again "
                "for each block instead of reusing one"
            )
        self._entered = True
        self._token = _enter(self._override)
        return _attribution_var.get()

    def __exit__(self, *exc_info: Any) -> None:
        assert self._token is not None
        _attribution_var.reset(self._token)
        self._token = None


def attribution(**fields: str | None) -> AbstractContextManager[Attribution]:
    """Scope attribution to a block, merging onto whatever is already active.

    Entering the scope yields the merged ``Attribution``, so a caller can assert
    on it or pass it on. The previous value is restored on exit, including on
    exception. Field names and value types are checked here, at the call, so a
    typo fails at the call site rather than at the start of the block.

    The returned scope is single use: entering it twice raises ``RuntimeError``,
    which is the one thing the ``AbstractContextManager`` type cannot say, so
    build a fresh one per block.

    A field passed as ``None`` means "do not override", so an outer value
    survives it; an empty or all-whitespace string is likewise treated as unset
    rather than as an instruction to erase the outer value.
    """
    return _AttributionScope(Attribution.from_fields(**fields))


def _deferred_decoration_message(kind: str, name: str) -> str:
    return (
        f"with_attribution cannot decorate {kind} {name!r}: the body would run "
        "after the scope had already been restored. Use `with attribution(...)` "
        "in the body."
    )


def _reject_deferred_body(result: Any, func: Callable[..., Any]) -> None:
    """Refuse a result whose body has not run yet.

    A decorated plain function is indistinguishable, before it is called, from
    one that defers its work, so the check happens on what it returned. A
    coroutine, a generator, or an async generator has not started, so running it
    after the scope is restored would record an un-attributed event — a silent
    hole in a charge-back, which is worse than a loud refusal. An
    ``asyncio.Future``/``Task`` is allowed through: the work was scheduled
    inside the scope, and the task copied the context there.
    """
    if not (inspect.iscoroutine(result) or inspect.isgenerator(result) or inspect.isasyncgen(result)):
        return
    for closer in ("aclose", "close"):
        finish = getattr(result, closer, None)
        if callable(finish):
            # The result is being discarded; close it so a never-awaited
            # coroutine or never-started generator does not warn on collection.
            finish()
            break
    raise TypeError(
        f"with_attribution cannot scope {func.__qualname__!r}: it returned "
        f"{type(result).__name__}, whose body runs after the scope is restored. "
        "Use `with attribution(...)` in the body."
    )


def with_attribution(**fields: str | None) -> Callable[[_F], _F]:
    """Decorate a function or method so every call runs under these fields.

    Works on sync and async callables. The merge is resolved per call, not per
    decoration, so a decorated function called inside an outer scope inherits
    that scope and its own fields win. Methods are ordinary functions here: the
    receiver is passed through untouched. A field passed as ``None`` means "do
    not override".

    A callable whose body does not run during the call — a generator function,
    an async generator function, or a plain function that returns a coroutine,
    generator or async generator — is refused with ``TypeError`` rather than
    silently leaving the ledger unattributed. Scope the deferred body itself::

        @with_attribution(agent="refund-bot")
        def stream_refunds(ticket):
            def events():
                with attribution(agent="refund-bot"):
                    yield current_attribution()
            return events()
    """
    override = Attribution.from_fields(**fields)

    def decorate(func: _F) -> _F:
        if inspect.isgeneratorfunction(func):
            raise TypeError(_deferred_decoration_message("generator function", func.__qualname__))
        if inspect.isasyncgenfunction(func):
            raise TypeError(
                _deferred_decoration_message("async generator function", func.__qualname__)
            )
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                token = _enter(override)
                try:
                    result = await func(*args, **kwargs)
                    _reject_deferred_body(result, func)
                    return result
                finally:
                    _attribution_var.reset(token)

            return cast(_F, async_wrapper)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            token = _enter(override)
            try:
                result = func(*args, **kwargs)
                _reject_deferred_body(result, func)
                return result
            finally:
                _attribution_var.reset(token)

        return cast(_F, wrapper)

    return decorate
