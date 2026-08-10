<div align="center">
  <p>
    <a href="README.md">README</a> •
    <a href="CODE_OF_CONDUCT.md">Code of Conduct</a>
  </p>
</div>

# Changelog

All notable changes to Backstop should be documented in this file.

## v0.5.0 — 10× Better

Closes the gap between Backstop and proxy gateways (LiteLLM / BricksLLM) while
staying in-process and drop-in. All new infrastructure is opt-in; existing
installs keep their default behavior.

- **Competitive benchmark** — Firecrawl-sourced feature matrix vs LiteLLM /
  BricksLLM and the "10× better" wedge (`docs/competitive-benchmark-2026-07-20.md`).
- **Deep Research: 10× Better** — exhaustive 6-agent Firecrawl synthesis
  (gateways, observability, frameworks, clouds, in-process techniques, risks)
  with a prioritized 13-item roadmap (`docs/deep-research-10x-better-2026-07-20.md`).

- **P0#1 Semantic cache (near-duplicate)** — opt-in pluggable embedder +
  cosine `cache_similarity_threshold`. Exact match stays the zero-cost fast path;
  on a miss, the prompt embedding is compared against cached entries and a
  `>= threshold` match is short-circuited. Biggest single cost lever (50–80%
  savings at typical hit rates) — `BackstopConfig(cache_enabled=True,
  cache_semantic=True, cache_embedder=<callable>, cache_similarity_threshold=0.95)`.
- **P0#2 Fallback chain + priority routing** — the single `fallback_model` is
  promoted to an ordered `fallback_chain` (list of `{model, base_url?}`) walked
  in-process on circuit-open; `fallback_chain_for_priority` gives critical traffic
  its own chain. Also fixes a latent bug where the single-model fallback silently
  no-op'd (`httpx.Request` has no `copy()` in this httpx version).
- **P1 Shared (Redis) budget** — one token budget enforced across processes and
  replicas via atomic Lua scripts. `BackstopConfig(shared_budget=True, redis_url=...)`
  with `pip install "backstop[redis]"`.
- **P2 OpenTelemetry export** — mirrors the Prometheus series to a vendor-neutral
  OTel meter. `BackstopConfig(otel_enabled=True)` with `pip install "backstop[otel]"`.
- **P3 In-process fallback** — retries once against a backup model/deployment when
  the circuit opens, no proxy required. `BackstopConfig(fallback_model=...)`.
- **P4 Wedge semantic diff v2** — token/line-normalized similarity (identifier
  Dice + line ratio) that is format/whitespace/removal-immune; report now carries
  per-runner budget-isolation evidence and a cost estimate.
- **P5 Deterministic benchmarks** — seeded, reproducible `backstop benchmark`
  (seed `0xC0FFEE`) with a `--publish` flag; published results in
  `docs/benchmark-results-2026-07-20.md`.
- **P6 Accurate pricing** — maintained 2026 price table (Claude 4/3.5/3,
  GPT 4.1/4o/o1/o3) with prefix+family resolution and offline-cached
  `refresh_pricing()`.
- **P8 CLI ergonomics** — `backstop doctor` validates install/SDKs/keys and runs a
  wrap smoke test; `backstop benchmark` produces reproducible proof.
- **P7 Doc drift fixes** — README benchmarks, features, and "what this is NOT"
  corrected against current behavior.
- **P9 TypeScript SDK scaffold** — `@ravanish/backstop` mirrors `wrap()` (budget +
  circuit breaker + retry + fallback) for Node.js agents (`ts/backstop`).
- **P10 Concurrency ceiling** — configurable `max_wrap_sessions` soft cap with a
  warning, plus `docs/concurrency.md` guidance on the GIL ceiling and when to use
  a proxy gateway.
- **Housekeeping** — deleted the superseded `docs/research` deep-research dump;
  added `redis`/`otel` install extras.

### 10× Better — roadmap follow-up (this pass)

- **P1#3 Virtual keys + hierarchical budgets** — `virtual_keys` maps an API key
  header (`virtual_key_header`) to a tenant, and `TenantBudget(parent=...)` rolls
  spend up a team/org tree so a child budget can never exceed its parent.
- **P1#4 True per-tenant circuit breaker** — `per_tenant_circuit` keeps a separate
  breaker per tenant (falls back to the global one); failures from one tenant no
  longer trip the breaker for everyone.
- **P1#5 Cloud-quota-aware auto-tuning** — ingests provider `x-ratelimit-*` /
  `anthropic-ratelimit-*` headers and proactively clamps the AIMD concurrency
  limit (`apply_external_decrease`) before 429s hit, instead of reacting to them.
- **P1#6 Framework adapters** — `backstop.adapters` lazily bridges LangChain /
  LlamaIndex callbacks to Backstop's hooks/metrics/tenant scoping so Backstop
  becomes the guardrail *inside* the framework. Framework imports are deferred, so
  importing the module never requires the framework installed.
- **P1#7 Cost forecasting + anomaly detection** — `backstop.forecast` projects
  budget exhaustion from a measured burn rate and flags spend anomalies, turning
  ledger data into an enforcement-triggering signal.
- **P1#12 Pluggable rate limiter + tiktoken pre-estimation** — `rate_limiter`
  accepts any `allow(tokens) -> bool` object (e.g. `TokenBucketLimiter`, a
  variable-cost token bucket charged by estimated tokens); `auto_token_count`
  (opt-in) switches pre-dispatch estimates from the chars/4 heuristic to tiktoken;
  `compress` is a pre-send `callable(body, model) -> body` hook.
- **P2#8 Tamper-evident audit log** — `audit_enabled` writes a chained,
  HMAC-verifiable JSONL of every enforcement decision (`deny` / `fallback` /
  `downgrade` / `shadow`) via `AuditLog.verify()`; the enterprise "escape hatch"
  that makes in-process enforcement audit-ready.
- **P2#9 Secret provider** — `secret_provider` resolves virtual keys / tenant ids
  to provider secrets at call time (env + static ships; cloud vaults implement the
  same interface), avoiding plaintext key handling in-process.
- **P2#10 Gateway / sidecar mode** — `backstop gateway` (`backstop serve`) runs an
  OpenAI-compatible reverse proxy so policy is non-bypassable for non-Python
  services; `pip install "backstop[fastapi]"`.
- **P2#11 Agent guardrails** — `agent_guard` (`AgentGuard`) fences runaway agent
  loops per agent id via sliding-window call/token ceilings.
- **P2#13 Safe rollout: shadow / canary** — `shadow_policy` (`ShadowPolicy` /
  `CanaryRouter`) samples traffic to a candidate config/policy and records
  reason-coded decisions before any hard cutover.

### v0.5.0 — Launch Readiness (2026-08-10)

Production-readiness pass: every claim is now backed by proof, every stale
doc is corrected, and the TypeScript SDK reaches full feature parity.

- **Proof infrastructure** — runnable proof scripts (`proofs/`) demonstrate
  budget exhaustion prevention, multi-agent isolation, real-provider overhead,
  and semantic cache savings against live providers.
- **Wedge fixed** — patch extraction now handles markdown code blocks, `FILE:`
  headers, and multi-line LLM output (was unified-diff-only). Agent loop with
  retry/fix on test failure. Per-runner test timeout.
- **Bundled test fixture** — `wedge-test-fixture/` gives `wedge run task.yaml`
  a real repo to run against out of the box.
- **Docs corrected** — README benchmark table regenerated dynamically (was
  stale), benchmark overhead measured live, version strings unified at `0.5.0`
  across `pyproject.toml`, `wedge/__init__.py`, `install.sh`, and `docs/install.md`.
- **Gateway hardened** — auth (`--api-keys`), per-key rate limiting, 1 MB body
  size guard, path traversal rejection, and error handling.
- **Cost forecasting → enforcement** — `forecast_horizon_seconds` proactively
  tightens AIMD concurrency when burn rate projects exhaustion.
- **Secret provider wired** — virtual keys resolve to provider secrets at call
  time in the transport, not just at wrap time.
- **TypeScript SDK v0.5.0** — full parity: priority admission, AIMD concurrency,
  fallback chains, response cache (exact + semantic), hooks, audit log, agent
  guardrails, quota-aware auto-tuning, cost forecasting, and `shadow/canary`.
- **Concurrent budget stress tests** — 20-thread hammer proves the no-overspend
  invariant. CI matrix tests multiple SDK versions.

## v0.4.0

- Integrated the `wedge` tool directly into the `backstop` codebase as an executable package script (`wedge run task.yaml`).
- **Isolation Harness**: Built per-runner Git worktree simulation and task execution.
- **Diff Engine**: Added `difflib`-based patch similarity scoring (`CONVERGED`, `PARTIAL`, `DIVERGED`).
- **Reporting Engine**: Added terminal summary and Markdown report generation (`wedge_report.md`).
- Fully un-mocked and configured the Anthropic and OpenAI wrapper handlers for production-ready API integration.
- Added Phase 0 trust assets: security policy, contribution guide, code of conduct, public docs, examples, benchmark scaffold, and GitHub templates.

## v0.3.0

- Added per-tenant budget buckets.
- Added cost estimation helpers.
- Added downgrade behavior for exhausted tenant budgets.

## v0.2.0

- Added latency metadata.
- Added streaming handling.
- Added middleware hooks.
- Added request timeout support.
- Added response caching.
- Added token counting improvements.
- Removed dead `priority_weights` behavior.

## v0.1.0

- Added the initial Backstop package.
- Added OpenAI SDK wrapping.
- Added Anthropic SDK compatibility.
- Added budget enforcement, priority admission, AIMD concurrency, retry handling, circuit breaking, metrics, and CLI harness support.
