import { AgentGuard } from "./agent.js";
import { AuditLog } from "./audit.js";
import { AgentGuardViolationError, LatencyBudgetExceededError } from "./exceptions.js";
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

/**
 * The priorities, in the order the gate serves them.
 *
 * The npm package's vocabulary is a *refinement* of the Python package's
 * three levels rather than a different one. Python has `critical`,
 * `default` and `background`; here `critical` and `high` are the critical
 * level, `default` is the default level, and `low` and `bulk` are the
 * background level. A name that works in one package therefore means
 * something in the other.
 */
const ALL_PRIORITIES: Priority[] = ["critical", "high", "default", "low", "bulk"];

/** How many clients this process has wrapped and not released. */
let liveWraps = 0;

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

  // The soft cap on live wrap() sessions. It was accepted in the config and
  // never read, so a deployment that set it got no warning and no limit.
  if (config.maxWrapSessions != null && config.maxWrapSessions > 0) {
    liveWraps += 1;
    if (liveWraps > config.maxWrapSessions) {
      // A warning, not an error: the cap is a soft ceiling, and a process
      // that trips it still works.
      console.warn(
        `Backstop: ${liveWraps} live wrap() sessions exceed maxWrapSessions=` +
          `${config.maxWrapSessions}. Under the GIL, many concurrent in-process ` +
          `sessions serialize on it — consider fewer sessions per process, or a ` +
          `process per agent.`,
      );
    }
  }

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

  // --- Agent guardrail ---
  const agentGuard =
    config.agentMaxCalls != null
      ? new AgentGuard({
          maxCalls: config.agentMaxCalls,
          windowMs: config.agentWindowMs ?? 60_000,
          maxTokens: config.agentMaxTokens ?? null,
        })
      : null;

  const originalCreate = client.chat.completions.create.bind(client.chat.completions);

  async function withDeadline<T>(work: Promise<T>, ms: number | null): Promise<T> {
    if (ms == null) return work;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        work,
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(
            () => reject(new LatencyBudgetExceededError(ms)),
            ms,
          );
        }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }

  async function runOnce(r: ChatCompletionRequest): Promise<ChatCompletionResponse> {
    return originalCreate(r);
  }

  async function create(req: ChatCompletionRequest): Promise<ChatCompletionResponse> {
    const priority = ((req as Record<string, unknown>)[priorityHeader] as Priority | undefined) ?? "default";
    const reqPriority: Priority = ALL_PRIORITIES.includes(priority) ? priority : "default";
    const estimated = est(req);

    // The per-request deadline. `requestTimeoutMs` covers an ordinary request
    // and `streamTimeoutMs` a streaming one; a request that exceeds it fails
    // with a `LatencyBudgetExceededError` rather than hanging forever. Both
    // were accepted in the config and never consulted.
    const deadlineMs =
      (req.stream ? config.streamTimeoutMs : config.requestTimeoutMs) ?? null;

    // --- Budget reservation ---
    //
    // A hard ceiling, for every priority. The npm package used to let
    // `critical` and `high` past an exhausted budget, which is not what the
    // Python package does: there, a budget is a ceiling, and a priority
    // decides who waits, not who is exempt. A guardrail whose strength
    // depends on the caller's mood is not a guardrail.
    if (!ledger.reserve(estimated)) {
      audit?.record("deny", "budget_exceeded", { tokens: estimated });
      throw new BudgetExceededError(budget, estimated);
    }

    // --- Agent guardrail ---
    //
    // A per-agent fence for runaway loops, reading the agent id off the
    // request the same way the Python package does. It was accepted in the
    // config and then never consulted, so `agentMaxCalls` was a knob that
    // did nothing.
    const agentId = (req as Record<string, unknown>)["X-Backstop-Agent"] as string | undefined;
    if (agentGuard && agentId && !agentGuard.allow(agentId, estimated)) {
      ledger.release(estimated);
      audit?.record("deny", "agent_guardrail", { agent_id: agentId });
      throw new AgentGuardViolationError(agentId);
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
          response = await withDeadline(runOnce(req), deadlineMs);
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
