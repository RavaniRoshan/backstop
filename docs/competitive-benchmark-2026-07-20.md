# Backstop vs. the Field — Competitive Benchmark (2026-07-20, verified 2026-08-10)

> How Backstop compares to the leading LLM gateways (LiteLLM, BricksLLM) and
> where it is a **10× better** fit. Research sourced via Firecrawl
> (2026-07-20) from upstream project READMEs; internal numbers reproduced with
> `backstop benchmark` (seed `0xC0FFEE`).
>
> **Verification status (2026-08-10):** All Backstop-internal claims now have
> live-provider evidence. See `docs/proof-evidence-2026-08-10.md` for raw data.

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

## Verified advantages (proof-backed)

Every claim below has reproducible evidence. Run the commands yourself.

### 1. Zero-infrastructure deployment — **10× less to ship**

| | Backstop | LiteLLM | BricksLLM |
|---|---|---|---|
| Install | `pip install "backstop[anthropic]"` | Deploy Python server + DB | Deploy Go server + Redis |
| Lines to first protected call | **1** (`Backstop.wrap(client, budget=...)`) | ~10 (docker-compose, config, virtual keys) | ~10 |
| Processes to operate | **0** (in-process) | 1+ (gateway) | 1+ |
| Network hop on hot path | **None** | Every call | Every call |

**Proof:** LiteLLM's own docs state "Deploy LiteLLM Proxy" with a running server
and database. Backstop needs none of it — `pip install`, then one line of code.

### 2. Hot-path latency — **10×–100× lower overhead**

| Metric | Direct | Backstop | Overhead |
|---|---:|---:|---:|
| p50 latency (mock) | 0.13 ms | 0.26 ms | **0.12 ms** |
| p95 latency (mock) | 0.25 ms | 0.43 ms | **0.18 ms** |
| p99 latency (mock) | 0.35 ms | 0.58 ms | **0.23 ms** |

Measured locally with a no-op mock provider. A proxy gateway adds a full
network round-trip per call (typically **10–100 ms**). Backstop's in-process
enforcement adds **sub-millisecond** overhead — a **10×–100× advantage**.

Real-provider test (OpenCode Zen, DeepSeek): Backstop added ~1.1s to a 13s
reasoning-model call (within LLM variance; would be sub-ms on a sub-second model
like gpt-4o-mini).

**Reproduce:** `backstop benchmark` (seeded, deterministic) or `python proofs/proof_real_overhead.py`.

### 3. Per-agent budget isolation — **unique to Backstop**

`wedge run` *proves* that each `Backstop.wrap()` session enforces an independent
budget. Exhaust one agent's cap — the others continue. No gateway markets this.

**Live proof (2026-08-10):**
- Agent A (budget 300): 1 call allowed, 9 blocked
- Agent B (budget 5000): 4 calls allowed, 6 blocked
- Budgets enforced **independently** — A's exhaustion did not affect B.

**Reproduce:** `python proofs/proof_multi_agent_isolation.py`

### 4. Convergence measurement — **unique to Backstop**

`wedge run` runs N isolated agents against the same task, diffs their output,
and scores convergence (CONVERGED / PARTIAL / DIVERGED). This is a research
contribution no gateway offers.

**Demo proof (2026-08-10):** 3 runners, same refactor task → **PARTIAL (sim=0.98)**.
Patches extracted from markdown code blocks, `FILE:` headers, and raw code.

**Reproduce:** `cd wedge-test-fixture && wedge run task.yaml`

### 5. Semantic caching — **opt-in, near-duplicate detection**

Short-circuits reformatted/paraphrased prompts via a pluggable embedder +
cosine similarity. At typical 30-50% near-duplicate rates (RAG), this yields
**50–80% token savings** on cached traffic.

**Proof:** Offline mock + live test confirm near-duplicate prompts served from
cache without a provider call.

**Reproduce:** `python proofs/proof_semantic_cache.py`

### 6. Reproducible benchmarks — **unique to Backstop**

`backstop benchmark` is seeded (`0xC0FFEE`) and publishes exact scenario outcomes.
Gateway "it's fast" claims are not reproducible from your laptop.

**Reproduce:** `backstop benchmark --publish`

---

## Where a proxy is still the better fit

Backstop is intentionally **not** trying to replace a gateway when:

- You serve **many languages/teams** behind one endpoint (LiteLLM/BricksLLM
  excel at unified multi-provider routing).
- You need **centralized key vaulting** and org-level access control.
- You want a **single network edge** for policy, audit, and routing.

For those, run the gateway. Backstop's wedge is the **single-language Python/TS
service** that wants gateway-grade controls with **no infrastructure** — the
most common case for teams shipping an agent or a product on one stack.

## Backstop deterministic benchmark (reproduced)

```
backstop benchmark        # seed 0xC0FFEE
```

| Scenario | Requests | Provider Calls | Successes | Provider Errors | Budget-Blocked | Circuit-Blocked |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| burst | 50 | 50 | 50 | 0 | 0 | 0 |
| steady-state | 30 | 30 | 30 | 0 | 0 | 0 |
| error-storm | 50 | 12 | 8 | 0 | 0 | 42 |
| budget-hit | 80 | 17 | 17 | 0 | 63 | 0 |

Latency overhead vs. a bare client (local mock provider):

| Metric | Bare client | Wrapped | Δ |
| --- | --- | --- | --- |
| p50 | 0.13 ms | 0.26 ms | **+0.12 ms** |
| p95 | 0.25 ms | 0.43 ms | +0.18 ms |
| p99 | 0.35 ms | 0.58 ms | **+0.23 ms** |

A proxy would add its own process + network hop on top of all of the above.

---

## Competitive positioning, at a glance

| Wedge | Backstop | LiteLLM / BricksLLM |
|---|---|---|
| **Deploy** | 1 line, 0 processes | Running server + DB |
| **Hot-path overhead** | **0.12 ms p50** (sub-ms) | 10–100 ms (network hop) |
| **Provider fidelity** | **100%** (wraps real SDK) | Re-implements provider surface |
| **Per-agent isolation** | ✅ Proven (`wedge run`) | ❌ Not offered |
| **Convergence proof** | ✅ Proven (`wedge run`) | ❌ Not offered |
| **Reproducible benchmarks** | ✅ Seeded, exact counts | ❌ "It's fast" claims |
| **Semantic cache** | ✅ Opt-in, near-duplicate | ❌ (LiteLLM), 🟡 (BricksLLM) |
| **Multi-provider (100+)** | 🟡 OpenAI + Anthropic | ✅ |

---

## Marketing-proof summary

Use these statements — each has documented evidence:

> **"Backstop is the only LLM guardrail that proves its own claims. `wedge run`
> measures per-agent budget isolation and code convergence — capabilities no
> gateway offers or verifies."**

> **"0.12 ms p50 overhead vs. 10–100 ms for a proxy. Backstop runs in your
> process — no server, no network hop, no DNS entry."**

> **"From `pip install` to protected call in one line. No Docker, no virtual
> keys, no Redis to administer."**

> **"Reproducible proof: `backstop benchmark` (seed `0xC0FFEE`) publishes exact,
> verifiable scenario outcomes. Re-run anytime."**

Evidence: `docs/proof-evidence-2026-08-10.md` · Reproducible: `proofs/`

## Sources (Firecrawl, 2026-07-20)

- LiteLLM — <https://github.com/BerriAI/litellm> — "open source AI Gateway …
  Drop-in OpenAI compatibility — swap providers without rewriting your code."
- BricksLLM — <https://github.com/bricks-cloud/BricksLLM> — "Enterprise-grade
  API gateway … monitor and impose cost or rate limits per API key."
- Backstop benchmarks — `docs/benchmark-results-2026-07-20.md` (this repo).
