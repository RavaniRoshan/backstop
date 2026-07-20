# Build Plan — Making Backstop a 10× Better LLM Guardrail

> Derived from `docs/deep-research-10x-better-2026-07-20.md` (exhaustive 6-agent
> Firecrawl synthesis). Goal: close the gap with gateway-grade products while
> keeping the zero-infrastructure, one-line `wrap()` wedge. Build order follows
> the research's prioritized roadmap (P0 → P1 → P2). Everything is opt-in; the
> default `wrap()` behavior is unchanged.

## Guiding principles (from the research)
1. **Zero-infra default.** New power is behind an opt-in flag/extra. Never add a
   network hop or a required dependency to the default path.
2. **Compose, don't reimplement.** Wrap mature libraries (`tenacity`,
   `pyrate-limiter`, `tiktoken`, `GPTCache` pattern) rather than reinventing.
3. **Budget is the first-class unit.** Every new control (cache, fallback,
   compression, routing) is driven by / reported into the token budget + metrics.
4. **One library, two shapes (later).** In-process `wrap()` now; optional gateway
   sidecar later (P2) — no feature fork.

## Phase 0 — Close the two P0 gaps (this iteration)
- **P0#1 Semantic cache layer.** Extend `ResponseCache` with an optional
  pluggable embedder + cosine similarity threshold. Exact match stays the fast
  path; on exact miss, a near-duplicate (>= `cache_similarity_threshold`) is
  short-circuited. Opt-in via `cache_semantic` + `cache_embedder`. Directly
  targets the biggest cost lever no in-process lib leads on (50–80% savings at
  typical hit rates).
- **P0#2 Multi-target fallback chain + priority routing.** Promote the single
  `fallback_model` to an ordered `fallback_chain` (list of `{model, base_url}`);
  `_try_fallback` walks the chain on circuit-open. Priority-aware chain selection
  scaffolded via `fallback_chain_for_priority`. Mirrors LiteLLM/Portkey
  declarative fallback (table-stakes for gateways).

## Phase 1 — Gateway-grade depth (next iterations)
- **P1#3 Virtual keys + hierarchical budgets** (`customer/team/key/provider`) —
  extend `ledger`/`TenantBudget`.
- **P1#4 True circuit-breaker semantics** — promote the AIMD+retry into an
  observable breaker (trip on cost-velocity/429/error-rate, per-identity,
  exported to Prom/OTel already shipped).
- **P1#5 Cloud-quota-aware auto-tuning** — parse `x-ratelimit-*` /
  `anthropic-ratelimit-*` + cache-aware ITPM to pre-empt 429s and count cached vs
  uncached tokens.
- **P1#6 Framework adapters** — thin LangChain `BaseCallbackHandler`,
  CrewAI/AutoGen hook, LlamaIndex callback, NeMo action (Backstop as the guardrail
  *inside* the framework).
- **P1#7 Cost dashboards + forecasting + anomaly alerts** — burn-rate projection,
  per-tenant/feature attribution, webhook alerts (enforcement-triggering).
- **P1#12 Pluggable token-bucket rate limiter + tiktoken pre-estimation +
  LLMLingua compression hook** — `pyrate-limiter` backend with variable per-op
  cost; auto-use `count_tokens` when `tiktoken` present; opt-in compression
  stage when budget tight.

## Phase 2 — Enterprise / escape-hatch (later iterations)
- **P2#8 Tamper-evident, exportable audit log** (JSONL + reason codes + policy
  version + sinks).
- **P2#9 Secret-manager integration + virtual-key auth** (AWS SM / Azure Vault /
  Vault; never plaintext env) — mitigates the Mar-2026 LiteLLM attack class.
- **P2#10 Optional gateway/sidecar mode** — same policy engine behind an
  OpenAI-compatible endpoint for non-bypassable / multi-language coverage.
- **P2#11 Agent-native guardrails** — runaway-loop / stall detection, per-agent
  cost ceilings.
- **P2#13 Safe rollout: shadow / canary + reason-coded decisions** — a bad policy
  change never hard-fails 100% of traffic at once.

## This iteration's deliverables
- `src/backstop/cache.py` — `ResponseCache` gains `embed` + `similarity_threshold`.
- `src/backstop/config.py` — `cache_semantic`, `cache_similarity_threshold`,
  `cache_embedder`, `fallback_chain`, `fallback_chain_for_priority`,
  `fallback_targets()` helper.
- `src/backstop/transports.py` — wire semantic cache; chain-aware `_try_fallback`.
- Tests for both; full suite green; CHANGELOG + docs updated.
