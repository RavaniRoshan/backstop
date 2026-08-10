export type Priority = "critical" | "high" | "default" | "low" | "bulk";

export interface BackstopConfig {
  /** Soft ceiling on simultaneously active wrap() sessions; 0 disables. */
  maxWrapSessions?: number;
  /** Priority header name used to pass per-request priority. */
  priorityHeader?: string;
  /** Base backoff (ms) for retries. */
  baseRetryDelayMs?: number;
  /** Max retries before opening the circuit breaker. */
  maxRetries?: number;
  /** Cooldown (ms) the circuit breaker waits before half-open. */
  circuitCooldownMs?: number;
  /** Model to retry against once the circuit opens. */
  fallbackModel?: string;
  /** Optional base URL for the fallback model. */
  fallbackBaseUrl?: string;
  /** Ordered list of fallback targets walked on circuit-open. */
  fallbackChain?: FallbackTarget[];
  /** Custom token estimator; defaults to a chars/4 heuristic. */
  estimateTokens?: (req: unknown) => number;

  // --- AIMD concurrency ---
  initialConcurrency?: number;
  minConcurrency?: number;
  maxConcurrency?: number;
  aimdDecreaseFactor?: number;
  aimdAdjustmentIntervalMs?: number;

  // --- Priority admission ---
  starvationAfterMs?: number;
  queueTimeoutMs?: number | null;
  requestTimeoutMs?: number | null;

  // --- Hooks ---
  beforeRequest?: (hook: BeforeRequestHook) => void;
  afterResponse?: (hook: AfterResponseHook) => void;

  // --- Caching ---
  cacheEnabled?: boolean;
  cacheMaxEntries?: number;
  cacheTtlMs?: number;
  cacheSemantic?: boolean;
  cacheEmbedder?: (text: string) => number[] | Promise<number[]>;
  cacheSimilarityThreshold?: number;

  // --- Streaming ---
  streamTimeoutMs?: number;

  // --- Agent guardrails ---
  agentMaxCalls?: number;
  agentWindowMs?: number;
  agentMaxTokens?: number | null;

  // --- Quota-aware auto-tuning ---
  quotaAware?: boolean;
  quotaPressureThreshold?: number;

  // --- Audit ---
  auditEnabled?: boolean;
  auditSink?: AuditSink;
  auditHmacKey?: string;

  // --- Forecasting ---
  forecastHorizonMs?: number;
}

export interface FallbackTarget {
  model: string;
  base_url?: string;
}

export interface BeforeRequestHook {
  endpoint: string;
  priority: Priority;
  estimatedTokens: number;
  metadata: Record<string, string>;
}

export interface AfterResponseHook {
  endpoint: string;
  status: number;
  actualTokens: number | null;
  latencyMs: number;
  success: boolean;
  metadata: Record<string, string>;
}

export type AuditSink = string | ((line: string) => void);

export interface ChatCompletionRequest {
  model: string;
  messages: Array<{ role: string; content?: unknown }>;
  stream?: boolean;
  [key: string]: unknown;
}

export interface Usage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
}

export interface ChatCompletionResponse {
  usage?: Usage;
  choices?: Array<{ message?: { content?: string | null } }>;
  [key: string]: unknown;
}

/** A minimal shape of the OpenAI client surface we intercept. */
export interface OpenAILikeClient {
  chat: {
    completions: {
      create: (req: ChatCompletionRequest) => Promise<ChatCompletionResponse>;
    };
  };
  [key: string]: unknown;
}
