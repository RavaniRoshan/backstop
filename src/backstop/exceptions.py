class BackstopError(Exception):
    """Base class for Backstop failures."""


class BudgetExceededError(BackstopError):
    """Raised before dispatch when a request would exceed the configured budget."""


class CircuitBreakerOpenError(BackstopError):
    """Raised before dispatch when the circuit breaker is open."""


class UnsupportedClientError(BackstopError):
    """Raised when Backstop.wrap receives an unsupported client type."""


class LatencyBudgetExceededError(BackstopError):
    """Raised when a request exceeds the configured request_timeout."""


class RateLimitError(BackstopError):
    """Raised when a pluggable rate limiter rejects a request before dispatch."""


class GuardrailViolationError(BackstopError):
    """Raised when an agent guardrail (runaway loop / stall) blocks a request."""

