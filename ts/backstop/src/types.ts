/**
 * Type definitions for the Backstop TypeScript SDK.
 *
 * The SDK mirrors the Python `backstop.wrap(client, budget, config)` semantics:
 * one drop-in call wraps an OpenAI-like client and adds budget enforcement,
 * a circuit breaker, automatic retry with backoff, and an in-process fallback
 * model on sustained provider failure.
 */

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
  /** Custom token estimator; defaults to a chars/4 heuristic. */
  estimateTokens?: (req: unknown) => number;
}

export interface ChatCompletionRequest {
  model: string;
  messages: Array<{ role: string; content?: unknown }>;
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
