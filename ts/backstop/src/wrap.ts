import { Budget, BudgetExceededError, defaultEstimateTokens, tokensFromUsage } from "./budget.js";
import { CircuitBreaker, CircuitBreakerOpenError } from "./circuit.js";
import type {
  BackstopConfig,
  ChatCompletionRequest,
  ChatCompletionResponse,
  OpenAILikeClient,
  Priority,
} from "./types.js";

const PRIORITIES: Priority[] = ["critical", "high", "default", "low", "bulk"];

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function isRetryable(err: unknown): boolean {
  const status = (err as { status?: number })?.status;
  if (status === 429 || status === 500 || status === 502 || status === 503 || status === 504) {
    return true;
  }
  const name = (err as { name?: string })?.name ?? "";
  return name === "APIConnectionError" || name === "APITimeoutError";
}

/**
 * Wrap an OpenAI-like client with Backstop guardrails. Drop-in: every
 * `client.chat.completions.create(req)` now enforces budget, retries with
 * backoff, trips a circuit breaker on repeated failures, and falls back to a
 * backup model once the circuit opens.
 */
export function wrap<T extends OpenAILikeClient>(
  client: T,
  budget: number | null = 50_000,
  config: BackstopConfig = {},
): T {
  const est = config.estimateTokens ?? (defaultEstimateTokens as (r: ChatCompletionRequest) => number);
  const priorityHeader = config.priorityHeader ?? "X-Backstop-Priority";
  const baseDelay = config.baseRetryDelayMs ?? 250;
  const circuit = new CircuitBreaker(config.maxRetries ?? 3, config.circuitCooldownMs ?? 5000);
  const ledger = new Budget(budget);

  const originalCreate = client.chat.completions.create.bind(client.chat.completions);

  async function create(req: ChatCompletionRequest): Promise<ChatCompletionResponse> {
    const priority = (req as Record<string, unknown>)[priorityHeader] as Priority | undefined;
    const reqPriority: Priority = priority && PRIORITIES.includes(priority) ? priority : "default";
    const estimated = est(req);

    if (!ledger.reserve(estimated) && reqPriority !== "critical" && reqPriority !== "high") {
      throw new BudgetExceededError(budget, estimated);
    }

    let lastErr: unknown = null;
    for (let attempt = 0; attempt < (config.maxRetries ?? 3) + 1; attempt++) {
      try {
        circuit.allow();
      } catch (e) {
        if (e instanceof CircuitBreakerOpenError && config.fallbackModel) {
          const fbReq = { ...req, model: config.fallbackModel };
          if (config.fallbackBaseUrl) (fbReq as Record<string, unknown>).baseURL = config.fallbackBaseUrl;
          return runOnce(fbReq);
        }
        throw e;
      }

      try {
        const res = await runOnce(req);
        circuit.recordSuccess();
        const actual = tokensFromUsage(res.usage, req, est);
        ledger.commit(estimated, actual);
        return res;
      } catch (err) {
        lastErr = err;
        circuit.recordFailure();
        if (!isRetryable(err)) {
          ledger.release(estimated);
          throw err;
        }
        await sleep(baseDelay * Math.pow(2, attempt));
      }
    }
    ledger.release(estimated);
    throw lastErr;

    async function runOnce(r: ChatCompletionRequest): Promise<ChatCompletionResponse> {
      return originalCreate(r);
    }
  }

  const wrapped = client as OpenAILikeClient & { _backstop?: true };
  wrapped.chat = {
    completions: {
      create: create as OpenAILikeClient["chat"]["completions"]["create"],
    },
  };
  wrapped._backstop = true;
  return wrapped as T;
}
