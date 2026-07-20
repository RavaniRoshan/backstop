# @ravanish/backstop

In-process LLM guardrails for the **OpenAI SDK** — a TypeScript port of the
Python [`backstop`](https://github.com/RavaniRoshan/backstop) `wrap()` API.

One drop-in call wraps your existing `OpenAI` client and adds:

- **Budget enforcement** — reserve/commit token budget per request, in-process.
- **Circuit breaker** — trip open after repeated failures, then probe recovery.
- **Automatic retry with exponential backoff** on 429/5xx.
- **In-process fallback model** — retry once against a backup model when the
  circuit opens (no proxy, no extra infra).

```bash
npm install @ravanish/backstop openai
```

```ts
import OpenAI from "openai";
import { wrap } from "@ravanish/backstop";

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

## Config

| Option              | Default   | Meaning                                              |
| ------------------- | --------- | ---------------------------------------------------- |
| `maxWrapSessions`   | `0`       | Soft cap on active sessions (warning only).          |
| `priorityHeader`    | `X-Backstop-Priority` | Header carrying per-request priority.          |
| `baseRetryDelayMs`  | `250`     | Base backoff; doubles each attempt.                  |
| `maxRetries`        | `3`       | Retries before the circuit opens.                    |
| `circuitCooldownMs` | `5000`    | Cooldown before the breaker goes half-open.          |
| `fallbackModel`     | —         | Model to retry against once the circuit opens.       |
| `fallbackBaseUrl`   | —         | Optional base URL for the fallback model.            |
| `estimateTokens`    | `chars/4` | Custom token estimator.                              |

## Status

This is a **scaffold** of the Python SDK's `wrap()` semantics. The Python
package is the canonical, fully-tested implementation; this port tracks it for
agentic / Node.js services. Distributed (Redis) budgets and OpenTelemetry export
are Python-only today.

## Scripts

```bash
npm run typecheck   # tsc --noEmit
npm run build       # emit dist/
npm test            # node --test (requires tsx)
```
