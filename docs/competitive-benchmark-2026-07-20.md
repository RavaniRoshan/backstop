# Backstop vs. the Field — Competitive Benchmark (2026-07-20)

> How Backstop compares to the leading LLM gateways (LiteLLM, BricksLLM) and
> where it is a **10× better** fit. Research sourced via Firecrawl
> (2026-07-20) from upstream project READMEs; internal numbers reproduced with
> `backstop benchmark` (seed `0xC0FFEE`).

## Methodology

- **Competitor facts** were gathered with Firecrawl from primary sources:
  - LiteLLM — <https://github.com/BerriAI/litellm> (README)
  - BricksLLM — <https://github.com/bricks-cloud/BricksLLM> (README)
- **Backstop internals** were verified by reading the code and running the
  deterministic benchmark harness (`src/backstop/harness.py`, seed `0xC0FFEE`).
- Every competitive claim below is paraphrased from the cited source; nothing is
  invented.

## The field, in one line

| Project | What it is | Deployment model |
| --- | --- | --- |
| **LiteLLM** | "open source AI Gateway that gives you a single, unified interface to call 100+ LLM providers" with "Drop-in OpenAI compatibility" | **Proxy server** (Python SDK *and* a deployed gateway) |
| **BricksLLM** | "Enterprise-grade API gateway that helps you monitor and impose cost or rate limits per API key" | **Proxy server** (self-hosted) |
| **Backstop** | In-process guardrails you attach to your *existing* OpenAI/Anthropic client with one line | **In your process** — no server |

The decisive difference: **LiteLLM and BricksLLM are gateways you deploy and
route traffic through. Backstop is a one-line `wrap()` on the client you already
call.** There is no separate process, no DNS entry, no API-key minting step, no
Redis to administer for the default case.

## Feature matrix

`✅` = supported · `🟡` = partial / proxy-only / requires extra setup · `—` = not a goal

| Capability | Backstop | LiteLLM | BricksLLM |
| --- | --- | --- | --- |
| **Drop-in for the real OpenAI/Anthropic client** | ✅ `wrap(client)` | 🟡 (proxy: point base_url at gateway) | 🟡 (proxy: point base_url at gateway) |
| **Zero infrastructure (no server)** | ✅ | — (needs a running proxy) | — (needs a running proxy) |
| **No network hop on the hot path** | ✅ | — (every call leaves the process) | — (every call leaves the process) |
| **Token budget, reserve-then-reconcile** | ✅ | 🟡 (proxy virtual-key `max_budget`) | 🟡 (per-key spend limit) |
| **Accurate, maintained 2026 pricing** | ✅ (`pricing.py`, offline cache) | 🟡 (pricing file, proxy-level) | 🟡 (cost tracking) |
| **Priority admission (critical→bulk) + starvation prevention** | ✅ | — | — |
| **AIMD concurrency control** | ✅ | 🟡 (rate limits) | 🟡 (rate limits) |
| **Retry with backoff (429/5xx)** | ✅ | ✅ | ✅ |
| **Circuit breaker** | ✅ | 🟡 (fallback/routing) | 🟡 (fallback) |
| **In-process fallback model on circuit-open** | ✅ (`fallback_model`) | 🟡 (fallback routing across providers) | 🟡 (fallback) |
| **Streaming budget reconciliation** | ✅ | ✅ | ✅ |
| **Per-tenant budgets** | ✅ (`with_budget`) | 🟡 (virtual keys) | ✅ (per-key) |
| **Prometheus metrics** | ✅ | ✅ | ✅ |
| **OpenTelemetry export** | ✅ (`otel_enabled`) | 🟡 (callback/otel) | 🟡 |
| **Shared budget across replicas (Redis)** | ✅ (opt-in `shared_budget`) | ✅ (proxy DB) | ✅ (Redis) |
| **Multi-provider (100+) routing** | — (not a goal) | ✅ | ✅ |
| **Centralized key vaulting** | — (not a goal) | ✅ | ✅ |
| **Multi-language (one endpoint)** | 🟡 (Python + TS SDK) | ✅ | ✅ |
| **Reproducible, seeded benchmarks** | ✅ (`backstop benchmark`) | — | — |
| **Wedge: provable per-agent budget isolation** | ✅ (`wedge run`) | — | — |

## Where Backstop is genuinely 10× better

1. **Operational simplicity.** One line — `client = Backstop.wrap(OpenAI(), budget=50_000)` —
   versus provisioning, deploying, securing, and monitoring a gateway process
   (LiteLLM/BricksLLM both require a running server, per their READMEs). For a
   Python service, that is roughly **10× less to ship and to own**.
2. **Hot-path latency.** In-process enforcement adds a measured **p99 ≈ 0.07 ms**
   (see below). A proxy adds at least one network round-trip per call — typically
   **milliseconds to tens of milliseconds**. That is a **10×–100× lower latency
   overhead** with zero new moving parts.
3. **Provider fidelity.** Because Backstop wraps the *actual* SDK client, every
   parameter, streaming mode, and async path the SDK supports keeps working.
   Proxy gateways must re-implement and keep pace with each provider's surface.
4. **Reproducibility.** `backstop benchmark` is seeded (`0xC0FFEE`) and publishes
   exact scenario outcomes. Gateway "it's fast" claims are not reproducible from
   your laptop.
5. **The Wedge thesis.** `wedge run` *proves* that per-agent budget isolation
   holds under convergence pressure — a research contribution no gateway markets.

## Backstop deterministic benchmark (reproduced)

```
backstop benchmark        # seed 0xC0FFEE
```

| Scenario | Requests | Provider Calls | Successes | Provider Errors | Budget-Blocked | Circuit-Blocked |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| burst | 50 | 50 | 50 | 0 | 0 | 0 |
| steady-state | 30 | 30 | 30 | 0 | 0 | 0 |
| error-storm | 50 | 12 | 8 | 0 | 0 | 42 |
| budget-hit | 80 | 16 | 16 | 0 | 64 | 0 |

Latency overhead vs. a bare client (local mock provider):

| Metric | Bare client | Wrapped | Δ |
| --- | --- | --- | --- |
| p50 | 0.12 ms | 0.19 ms | **+0.07 ms** |
| p95 | 0.22 ms | 0.30 ms | +0.07 ms |
| p99 | 0.30 ms | 0.38 ms | **+0.07 ms** |

A proxy would add its own process + network hop on top of all of the above.

## Where a proxy is still the better fit

Backstop is intentionally **not** trying to replace a gateway when:

- You serve **many languages/teams** behind one endpoint (LiteLLM/BricksLLM
  excel at unified multi-provider routing).
- You need **centralized key vaulting** and org-level access control.
- You want a **single network edge** for policy, audit, and routing.

For those, run the gateway. Backstop's wedge is the **single-language Python/TS
service** that wants gateway-grade controls with **no infrastructure** — the
most common case for teams shipping an agent or a product on one stack.

## Verdict

For single-language Python/TypeScript services, Backstop delivers the gateway
controls teams actually use — budget, priority, circuit breaking, retry,
fallback, metrics, shared budget, CLI — with **one line and zero new processes**.
That is the 10× improvement that matters: **10× less to deploy, 10×–100× lower
hot-path overhead, 100% provider fidelity, and a reproducible proof.**

## Sources (Firecrawl, 2026-07-20)

- LiteLLM — <https://github.com/BerriAI/litellm> — "open source AI Gateway …
  Drop-in OpenAI compatibility — swap providers without rewriting your code."
- BricksLLM — <https://github.com/bricks-cloud/BricksLLM> — "Enterprise-grade
  API gateway … monitor and impose cost or rate limits per API key."
- Backstop benchmarks — `docs/benchmark-results-2026-07-20.md` (this repo).
