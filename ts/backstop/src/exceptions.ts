/**
 * The errors Backstop raises that have no home of their own.
 *
 * `BudgetExceededError` lives in `budget.ts` and `CircuitBreakerOpenError` in
 * `circuit.ts`, next to the thing that raises them. These two had no such
 * neighbour until now, because nothing raised them: the agent guardrail and
 * the request deadline were accepted in the config and never consulted.
 */

/** An agent guardrail fenced the request: too many calls, or too many tokens. */
export class AgentGuardViolationError extends Error {
  readonly agentId: string;

  constructor(agentId: string) {
    super(`agent ${agentId} exceeded guardrail`);
    this.name = "AgentGuardViolationError";
    this.agentId = agentId;
  }
}

/** The request took longer than the configured deadline. */
export class LatencyBudgetExceededError extends Error {
  readonly timeoutMs: number;

  constructor(timeoutMs: number) {
    super(`request exceeded its ${timeoutMs}ms deadline`);
    this.name = "LatencyBudgetExceededError";
    this.timeoutMs = timeoutMs;
  }
}
