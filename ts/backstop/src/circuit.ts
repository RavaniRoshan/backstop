/**
 * Minimal circuit breaker. On `maxRetries` consecutive failures it opens for
 * `cooldownMs`, then transitions to half-open for one probe before closing.
 * Mirrors the Python CircuitBreaker state machine.
 */
export type CircuitState = "closed" | "open" | "half-open";

export class CircuitBreaker {
  private state: CircuitState = "closed";
  private failures = 0;
  private openedAt = 0;

  constructor(
    private readonly maxRetries = 3,
    private readonly cooldownMs = 5000,
  ) {}

  get stateName(): CircuitState {
    return this.state;
  }

  /** Throw if the circuit is open (and not yet cooldown-elapsed). */
  allow(): void {
    if (this.state === "open") {
      if (Date.now() - this.openedAt >= this.cooldownMs) {
        this.state = "half-open";
      } else {
        throw new CircuitBreakerOpenError();
      }
    }
  }

  recordSuccess(): void {
    this.failures = 0;
    this.state = "closed";
  }

  recordFailure(): void {
    this.failures += 1;
    if (this.failures >= this.maxRetries) {
      this.state = "open";
      this.openedAt = Date.now();
    }
  }
}

export class CircuitBreakerOpenError extends Error {
  constructor() {
    super("Circuit breaker is open");
    this.name = "CircuitBreakerOpenError";
  }
}
