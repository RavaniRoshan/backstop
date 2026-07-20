import type { ChatCompletionRequest, Usage } from "./types.js";

/** Default token estimator: ~4 chars per token plus per-message overhead. */
export function defaultEstimateTokens(req: ChatCompletionRequest): number {
  let chars = 0;
  for (const m of req.messages ?? []) {
    const c = m.content;
    if (typeof c === "string") chars += c.length;
    else if (c != null) chars += JSON.stringify(c).length;
    chars += 8; // per-message protocol overhead
  }
  if (req.model) chars += req.model.length;
  return Math.max(1, Math.ceil(chars / 4));
}

/** Extract total tokens from a response's usage, falling back to a heuristic. */
export function tokensFromUsage(
  usage: Usage | undefined,
  req: ChatCompletionRequest,
  estimate: (r: ChatCompletionRequest) => number,
): number {
  if (usage?.total_tokens) return usage.total_tokens;
  if (usage?.prompt_tokens) {
    return usage.prompt_tokens + (usage.completion_tokens ?? 0);
  }
  return estimate(req);
}

/**
 * In-process budget. Mirrors the Python InMemoryBudgetBackend: a single
 * reserve()/commit() ledger with an unbounded (null) mode.
 */
export class Budget {
  private total: number | null;
  private spent = 0;
  private reserved = 0;

  constructor(total: number | null) {
    this.total = total;
  }

  get remaining(): number {
    if (this.total === null) return Number.POSITIVE_INFINITY;
    return this.total - this.spent;
  }

  /** Reserve tokens. Returns false if the budget cannot cover it. */
  reserve(tokens: number): boolean {
    if (this.total === null) return true;
    if (this.spent + this.reserved + tokens > this.total) return false;
    this.reserved += tokens;
    return true;
  }

  /** Commit reserved tokens (called after we learn the real usage). */
  commit(reserved: number, actual: number): void {
    if (this.total === null) return;
    this.reserved -= reserved;
    this.spent += actual;
  }

  /** Release an uncommitted reservation (e.g. on failure). */
  release(reserved: number): void {
    if (this.total === null) return;
    this.reserved -= reserved;
  }
}

export class BudgetExceededError extends Error {
  constructor(public budget: number | null, public attempted: number) {
    super(
      budget === null
        ? "Budget exceeded"
        : `Budget exceeded: attempted +${attempted} tokens, remaining ${budget}`,
    );
    this.name = "BudgetExceededError";
  }
}
