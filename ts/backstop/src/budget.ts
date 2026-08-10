import type { ChatCompletionRequest, Usage } from "./types.js";

/** Default token estimator: ~4 chars per token plus per-message overhead. */
export function defaultEstimateTokens(req: ChatCompletionRequest): number {
  let chars = 0;
  for (const m of req.messages ?? []) {
    const c = m.content;
    if (typeof c === "string") chars += c.length;
    else if (c != null) chars += JSON.stringify(c).length;
    chars += 8;
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
  if (usage?.prompt_tokens) return usage.prompt_tokens + (usage.completion_tokens ?? 0);
  return estimate(req);
}

/**
 * In-process budget. Mirrors the Python InMemoryBudgetBackend.
 */
export class Budget {
  private total: number | null;
  private spentInternal = 0;
  private reservedInternal = 0;
  private parent: Budget | null;

  constructor(total: number | null, parent: Budget | null = null) {
    this.total = total;
    this.parent = parent;
  }

  /** Tokens spent (excluding reserved). */
  get spent(): number {
    return this.spentInternal;
  }

  /** Remaining tokens (total - spent - reserved). */
  get remaining(): number {
    if (this.total === null) return Number.POSITIVE_INFINITY;
    return Math.max(0, this.total - this.spentInternal - this.reservedInternal);
  }

  /** Reserve tokens. Returns false if the budget cannot cover it. */
  reserve(tokens: number): boolean {
    if (this.total === null) {
      if (this.parent) return this.parent.reserve(tokens);
      return true;
    }
    if (this.spentInternal + this.reservedInternal + tokens > this.total) return false;
    this.reservedInternal += tokens;
    if (this.parent) {
      try {
        if (!this.parent.reserve(tokens)) {
          this.reservedInternal -= tokens;
          return false;
        }
      } catch {
        this.reservedInternal -= tokens;
        return false;
      }
    }
    return true;
  }

  /** Commit reserved tokens (called after we learn the real usage). */
  commit(reserved: number, actual: number): void {
    if (this.total === null) {
      if (this.parent) this.parent.commit(reserved, actual);
      return;
    }
    this.reservedInternal = Math.max(0, this.reservedInternal - reserved);
    this.spentInternal += actual;
    if (this.parent) this.parent.commit(reserved, actual);
  }

  /** Release an uncommitted reservation (e.g. on failure). */
  release(reserved: number): void {
    if (this.total === null) return;
    this.reservedInternal = Math.max(0, this.reservedInternal - reserved);
  }
}

export class BudgetExceededError extends Error {
  constructor(
    public budget: number | null,
    public attempted: number,
  ) {
    super(
      budget === null
        ? "Budget exceeded"
        : `Budget exceeded: attempted +${attempted} tokens, remaining ${budget}`,
    );
    this.name = "BudgetExceededError";
  }
}
