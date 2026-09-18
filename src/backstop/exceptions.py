"""Resolve provider SDK error bases for Backstop exception transparency.

The wrapped SDKs re-raise transport exceptions as ``APIConnectionError`` /
``APIStatusError`` unless the raised error is an instance of their own error
base class (``openai.OpenAIError`` / ``anthropic.AnthropicError``). For user
code to catch Backstop guardrail errors, Backstop's exceptions must inherit
those bases — when the corresponding SDK is importable.

Bases are resolved once at import time: importable SDK -> its error base is
mixed in; missing SDK -> plain ``Exception`` fallback. With both SDKs
installed the exception classes inherit both bases, which is harmless because
SDK checks are ``isinstance``-based and both bases are plain exception
subclasses.
"""
from __future__ import annotations


def _provider_bases() -> tuple[type, ...]:
    bases: list[type] = []
    try:
        from openai import OpenAIError
    except ImportError:
        pass
    else:
        bases.append(OpenAIError)
    try:
        from anthropic import AnthropicError
    except ImportError:
        pass
    else:
        bases.append(AnthropicError)
    return tuple(bases)


class BackstopError(Exception):
    """Base class for Backstop failures."""


_PROVIDER_BASES = _provider_bases()


def _provider_subclass(name: str, doc: str) -> type:
    """Create a Backstop error class inheriting the provider error bases."""
    attrs = {"__doc__": doc, "__module__": __name__}
    if _PROVIDER_BASES:
        return type(name, (BackstopError, *_PROVIDER_BASES), attrs)
    return type(name, (BackstopError,), attrs)


BudgetExceededError = _provider_subclass(
    "BudgetExceededError",
    "Raised before dispatch when a request would exceed the configured budget.",
)

CircuitBreakerOpenError = _provider_subclass(
    "CircuitBreakerOpenError",
    "Raised before dispatch when the circuit breaker is open.",
)

LatencyBudgetExceededError = _provider_subclass(
    "LatencyBudgetExceededError",
    "Raised when a request exceeds the configured request_timeout.",
)

RateLimitError = _provider_subclass(
    "RateLimitError",
    "Raised when a pluggable rate limiter rejects a request before dispatch.",
)

GuardrailViolationError = _provider_subclass(
    "GuardrailViolationError",
    "Raised when an agent guardrail (runaway loop / stall) blocks a request.",
)


class UnsupportedClientError(BackstopError):
    """Raised when Backstop.wrap receives an unsupported client type."""
