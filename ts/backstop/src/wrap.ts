import { AuditLog } from "./audit.js";
import { AIMDController, PriorityGate } from "./admission.js";
import { Budget, BudgetExceededError, defaultEstimateTokens, tokensFromUsage } from "./budget.js";
import { CircuitBreaker, CircuitBreakerOpenError } from "./circuit.js";
import { ResponseCache } from "./cache.js";
import { QuotaMonitor } from "./quotas.js";
import { willExhaust } from "./forecast.js";
import type {
  AfterResponseHook,
  BackstopConfig,
  BeforeRequestHook,
  ChatCompletionRequest,
  ChatCompletionResponse,
  FallbackTarget,
  OpenAILikeClient,
  Priority,
} from "./types.js";

const ALL_PRIORITIES: Priority[] = ["critical", "high", "default", "low", "bulk"];

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function isRetryable(err: unknown): boolean {
  const status = (err as { status?: number })?.status;
  if (status === 429 || status === 500 || status === 502 || status === 503 || status === 504) return true;
  const name = (err as { name?: string })?.name ?? "";
  return name === "APIConnectionError" || name === "APITimeoutError";
}

function buildFallbackRequest(req: ChatCompletionRequest, target: FallbackTarget): ChatCompletionRequest {
  const fb = { ...req, model: target.model };
  if (target.base_url) (fb as Record<string, unknown>).baseURL = target.base_url;
  return fb;
}

function fallbackTargets(config: BackstopConfig, priority?: Priority): FallbackTarget[] {
  if (priority && config.fallbackChain) return config.fallbackChain;
  if (config.fallbackModel) return [{ model: config.fallbackModel, base_url: config.fallbackBaseUrl }];
  return [];
}

/**
 * Wrap an OpenAI-like client with Backstop guardrails. Drop-in: every
 * `client.chat.completions.create(req)` now enforces budget, priority
 * admission, AIMD concurrency, retry with backoff, circuit breaking,
 * fallback chains, caching, hooks, and audit logging.
 */
export function wrap<T extends OpenAILikeClient>(
  client: T,
  budget: number | null = 50_000,
  config: BackstopConfig = {},
): T {
  if ((client as Record<string, unknown>)._backstop) return client;

  const est = config.estimateTokens ?? (defaultEstimateTokens as (r: ChatCompletionRequest) => number);
  const priorityHeader = config.priorityHeader ?? "X-Backstop-Priority";
  const baseDelay = config.baseRetryDelayMs ?? 250;
  const maxRetries = config.maxRetries ?? 3;
  const circuit = new CircuitBreaker(maxRetries, config.circuitCooldownMs ?? 5000);
  const ledger = new Budget(budget);

  // --- AIMD + admission ---
  const aimd = new AIMDController({
    initial: config.initialConcurrency ?? 8,
    min: config.minConcurrency ?? 1,
    max: config.maxConcurrency ?? 64,
    decreaseFactor: config.aimdDecreaseFactor ?? 0.5,
    intervalMs: config.aimdAdjustmentIntervalMs ?? 5000,
  });
  const gate = new PriorityGate(aimd, {
    starvationMs: config.starvationAfterMs ?? 1000,
    timeoutMs: config.queueTimeoutMs ?? null,
  });

  // --- Cache ---
  const cache =
    config.cacheEnabled && config.cacheEmbedder
      ? new ResponseCache({
          maxEntries: config.cacheMaxEntries ?? 256,
          ttlMs: config.cacheTtlMs ?? 60_000,
          embed: config.cacheSemantic ? config.cacheEmbedder : null,
          threshold: config.cacheSimilarityThreshold ?? 0.95,
        })
      : null;

  // --- Quota monitor ---
  const quota = config.quotaAware !== false ? new QuotaMonitor(config.quotaPressureThreshold ?? 0.85) : null;

  // --- Audit ---
  const audit = config.auditEnabled
    ? new AuditLog(config.auditSink ?? null, config.auditHmacKey)
    : null;

  const originalCreate = client.chat.completions.create.bind(client.chat.completions);

  async function runOnce(r: ChatCompletionRequest): Promise<ChatCompletionResponse> {
    return originalCreate(r);
  }

  async function create(req: ChatCompletionRequest): Promise<ChatCompletionResponse> {
    const priority = ((req as Record<string, unknown>)[priorityHeader] as Priority | undefined) ?? "default";
    const reqPriority: Priority = ALL_PRIORITIES.includes(priority) ? priority : "default";
    const estimated = est(req);

    // --- Budget reservation ---
    if (!ledger.reserve(estimated) && reqPriority !== "critical" && reqPriority !== "high") {
      audit?.record("deny", "budget_exceeded", { tokens: estimated });
      throw new BudgetExceededError(budget, estimated);
    }

    // --- Before hook ---
    if (config.beforeRequest) {
      const hook: BeforeRequestHook = {
        endpoint: "/v1/chat/completions",
        priority: reqPriority,
        estimatedTokens: estimated,
        metadata: {},
      };
      config.beforeRequest(hook);
    }

    // --- Cache check ---
    if (cache && !(req.stream)) {
      const cached = await cache.get(req);
      if (cached) {
        if (config.afterResponse) {
          config.afterResponse({
            endpoint: "/v1/chat/completions",
            status: 200,
            actualTokens: cached.usage,
            latencyMs: 0,
            success: true,
            metadata: {},
          });
        }
        return { usage: { total_tokens: cached.usage }, choices: [{ message: { content: cached.content } }] };
      }
    }

    // --- Admission gate ---
    try {
      await gate.acquire(reqPriority);
    } catch (e) {
      ledger.release(estimated);
      throw e;
    }

    let lastErr: unknown = null;
    let response: ChatCompletionResponse | null = null;

    try {
      for (let attempt = 0; attempt < maxRetries + 1; attempt++) {
        try {
          circuit.allow();
        } catch (e) {
          if (e instanceof CircuitBreakerOpenError) {
            const fb = await tryFallback();
            if (fb) return fb;
            ledger.release(estimated);
            audit?.record("deny", "circuit_open", {});
            throw e;
          }
          throw e;
        }

        try {
          response = await runOnce(req);
          circuit.recordSuccess();
          const actual = tokensFromUsage(response.usage, req, est);
          ledger.commit(estimated, actual);
          await postProcess(response, actual);
          // --- After hook ---
          if (config.afterResponse) {
            config.afterResponse({
              endpoint: "/v1/chat/completions",
              status: 200,
              actualTokens: actual,
              latencyMs: 0,
              success: true,
              metadata: {},
            });
          }
          return response;
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
    } finally {
      gate.release();
    }

    // Retries exhausted — try fallback before giving up.
    const fb = await tryFallback();
    if (fb) return fb;

    ledger.release(estimated);
    throw lastErr;

    async function tryFallback(): Promise<ChatCompletionResponse | null> {
      const targets = fallbackTargets(config, reqPriority);
      for (const target of targets) {
        try {
          const res = await runOnce(buildFallbackRequest(req, target));
          const actual = tokensFromUsage(res.usage, req, est);
          ledger.commit(estimated, actual);
          audit?.record("fallback", "circuit_open", { model: target.model });
          return res;
        } catch {
          continue;
        }
      }
      return null;
    }

    async function postProcess(response: ChatCompletionResponse, actual: number): Promise<void> {
      // --- Quota-aware tuning ---
      if (quota && (response as Record<string, unknown>).headers) {
        quota.ingest((response as unknown as { headers: Record<string, string> }).headers);
        quota.adjust(aimd);
      }
      // --- Forecast enforcement ---
      if (config.forecastHorizonMs && budget != null && ledger["spent"] > 0) {
        if (willExhaust(ledger["spent"], 30, budget, config.forecastHorizonMs / 1000)) {
          aimd.recordPressure();
        }
      }
      // --- Cache store ---
      if (cache && response.choices?.[0]?.message?.content) {
        await cache.set(req, response.choices[0].message.content as string, actual);
      }
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
