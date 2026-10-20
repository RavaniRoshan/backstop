<p align="center">
  <img width="200" alt="Backstop logo" src="../../docs/assets/backstop-logo.svg" />
</p>

# backstop-ai

In-process LLM guardrails for the **OpenAI SDK** — a TypeScript port of the
Python [`backstop`](https://github.com/RavaniRoshan/backstop) `wrap()` API.

One drop-in call wraps your existing `OpenAI` client and adds:

- **Budget enforcement** — reserve/commit token budget per request, in-process.
  A hard ceiling: a priority decides who waits, not who is exempt.
- **Circuit breaker** — trip open after repeated failures, then probe recovery.
- **Automatic retry with exponential backoff** on 429/5xx.
- **In-process fallback chains** — walk an ordered list of backup models when
  the circuit opens (no proxy, no extra infra).
- **Priority admission** — queue and prioritise across `critical` / `high` /
  `default` / `low` / `bulk`, with starvation protection.
- **AIMD concurrency** — the limit adapts to pressure rather than sitting at a
  fixed number.
- **Response cache** — exact matches, and near-duplicate semantic matches
  when you supply an embedder.
- **Agent guardrails** — fence a runaway agent loop by call count or token
  spend, per agent.
- **Request deadline** — fail a request that takes too long rather than
  letting it hang.
- **Hooks and audit log** — a `beforeRequest` / `afterResponse` hook, and a
  tamper-evident chain of every enforcement decision.

```bash
npm install backstop-ai openai
```

```ts
import OpenAI from "openai";
import { wrap } from "backstop-ai";

const client = wrap(new OpenAI(), 50_000, {
  fallbackModel: "gpt-4o-mini",
});

const res = await client.chat.completions.create({
  model: "gpt-4.1-mini",
  messages: [{ role: "user", content: "Hello." }],
});
```

## How it works

`wrap()` patches `client.chat.completions.create` (the only call-site you use)
and runs every request through a budget ledger + circuit breaker before calling
the original method. Your code does not change. Budget reconciliation uses the
provider's `usage` when available and a `chars/4` heuristic otherwise.

This is a **different interception strategy** from the Python package, which
injects a transport underneath the SDK. Both enforce the same things; this one
works at the call you make rather than at the HTTP layer, which is why it
supports the OpenAI SDK only and not Anthropic.

## Config

Every option, with its default. The options the Python package shares are
named the same way and mean the same thing.

### Budget and sessions

| Option              | Default   | Meaning                                              |
| ------------------- | --------- | ---------------------------------------------------- |
| `maxWrapSessions`   | `0`       | Soft cap on live `wrap()` sessions; warns past it.   |
| `estimateTokens`    | `chars/4` | Custom token estimator.                              |

### Priorities and admission

| Option              | Default             | Meaning                                   |
| ------------------- | ------------------- | ----------------------------------------- |
| `priorityHeader`    | `X-Backstop-Priority` | Header carrying the per-request priority. |
| `initialConcurrency`| `8`                 | Starting concurrency limit.               |
| `minConcurrency`    | `1`                 | Floor for the AIMD limit.                |
| `maxConcurrency`    | `64`                | Ceiling for the AIMD limit.              |
| `aimdDecreaseFactor`| `0.5`               | Multiplicative decrease on pressure.     |
| `aimdAdjustmentIntervalMs` | `5000`      | How often the limit may move.            |
| `starvationAfterMs` | `1000`              | Age at which a waiting ticket is released. |
| `queueTimeoutMs`    | `null`               | Bound on the wait; `null` waits forever.  |

The five priorities are a **refinement** of the Python package's three. Python
has `critical`, `default` and `background`; here `critical` and `high` are the
critical level, `default` is the default level, and `low` and `bulk` are the
background level. A name that works in one package means something in the
other.

### Retries, circuit, fallback

| Option              | Default   | Meaning                                              |
| ------------------- | --------- | ---------------------------------------------------- |
| `baseRetryDelayMs`  | `250`     | Base backoff; doubles each attempt.                  |
| `maxRetries`        | `3`       | Retries before the circuit opens.                    |
| `circuitCooldownMs` | `5000`    | Cooldown before the breaker goes half-open.          |
| `fallbackModel`     | —         | Model to retry against once the circuit opens.       |
| `fallbackBaseUrl`   | —         | Optional base URL for the fallback model.            |
| `fallbackChain`     | —         | Ordered list of fallback targets.                    |

### Cache

| Option                   | Default | Meaning                                |
| ------------------------ | ------- | -------------------------------------- |
| `cacheEnabled`           | `false` | Turn the response cache on.            |
| `cacheMaxEntries`        | `256`   | Entries held.                          |
| `cacheTtlMs`             | `60000` | Entry lifetime.                        |
| `cacheSemantic`          | `false` | Match near-duplicates, not just exact. |
| `cacheEmbedder`          | —       | `(text) => number[]` for semantic matching. |
| `cacheSimilarityThreshold` | `0.95` | Cosine threshold for a semantic hit.  |

### Agent guardrails, deadlines, hooks

| Option              | Default | Meaning                                        |
| ------------------- | ------- | ---------------------------------------------- |
| `agentMaxCalls`     | —       | Calls per agent inside the window.             |
| `agentWindowMs`     | `60000` | The window.                                    |
| `agentMaxTokens`    | `null`  | Token ceiling per agent inside the window.      |
| `requestTimeoutMs`  | `null`  | Deadline for an ordinary request.              |
| `streamTimeoutMs`   | `null`  | Deadline for a streaming request.              |
| `beforeRequest`     | —       | Hook, called before the request is sent.       |
| `afterResponse`     | —       | Hook, called after the response comes back.    |

The agent id is read off the `X-Backstop-Agent` header, the same way the
Python package reads it.

### Quota auto-tuning, audit, forecasting

| Option                   | Default | Meaning                                  |
| ------------------------ | ------- | ---------------------------------------- |
| `quotaAware`             | `true`  | Clamp the limit on provider pressure.    |
| `quotaPressureThreshold` | `0.85`  | The pressure that counts as pressure.    |
| `auditEnabled`           | `false` | Write the tamper-evident decision log.   |
| `auditSink`              | —       | A file path, or a `(line) => void`.      |
| `auditHmacKey`           | —       | The key the chain is anchored to.        |
| `forecastHorizonMs`      | —       | Tighten the limit when exhaustion is projected inside this horizon. |

## What it does not have

The Python package is the canonical implementation. This one is a subset, and
the difference is worth knowing before you choose it:

- **No Anthropic.** The OpenAI SDK only.
- **No transport injection.** It patches `create`, so it cannot see a request
  the SDK makes by any other route.
- **No distributed budget.** There is no Redis-shared budget; the budget is
  per process.
- **No OpenTelemetry export.** Prometheus metrics and the built-in dashboard
  are Python-only.
- **No spend ledger, no dollar budgets, no charge-back.** The money features
  are Python-only, and they are where the Python package's newest work is.
- **No gateway mode.** `backstop serve` is Python-only.
- **No shadow mode, no runaway-spend detection, no reconciliation.**

The Python package is at 0.8.0 and this one tracks it for Node.js services.
When a feature is in one and not the other, the Python one is the reference —
and this README is the list of the differences, not a claim of parity.

## Status

Tested, typed and published: `npm run typecheck`, `npm test` and `npm run
build` all run in CI on every push, and the release tag publishes the package
with provenance.

## Scripts

```bash
npm run typecheck   # tsc --noEmit
npm run build       # emit dist/
npm test            # node --test (requires tsx)
```

## Licence

MIT, the same licence as the Python package.
