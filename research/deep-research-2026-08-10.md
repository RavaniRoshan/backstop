# Backstop Deep Research — Production Readiness Audit & Launch Plan

**Date:** 2026-08-10
**Scope:** Full codebase audit, competitive analysis, proof-gap analysis, 1-week launch plan
**Input:** User directive to make Backstop production-ready, prove all claims, and achieve TS parity in one week.

---

## 1. Executive Summary

Backstop is an **in-process LLM SDK guardrail** that wraps OpenAI/Anthropic clients at the httpx transport layer. It enforces token budgets, priority admission, AIMD concurrency, retry/backoff, circuit breaking, fallback chains, streaming reconciliation, response caching (exact + semantic), tenant budgets, Prometheus/OTel metrics, shared Redis budgets, audit logs, agent guardrails, and an optional gateway sidecar. Bundled **Wedge** runs N isolated agents against the same task to prove per-agent budget isolation.

**What genuinely works (verified from source + tests):** The core transport pipeline — budget reserve/reconcile against real usage, circuit breaker, AIMD, retry+backoff, priority admission, tenant isolation, streaming reconciliation, response cache (incl. gzip), semantic cache, fallback chain, hooks, all 4 harness scenarios, Prometheus exposition, CLI doctor/benchmark/harness/metrics. 36 unit/component tests pass.

**The core problem:** A significant gap exists between what the product *claims* and what it *demonstrates*. The Wedge headline proof tool is broken against real LLM output. README docs are stale and crash when copy-pasted. Version numbers are inconsistent. And critically — **there is no reproducible real-provider evidence** that Backstop's budget isolation reduces runaway cost. The product is a strong library that has not yet earned its "10× better" claims with proof.

**The opportunity:** Be the FIRST in the space to actually prove cost reduction and budget isolation with real-provider evidence. No competitor has this.

---

## 2. What Works vs. What Does Not

### Verified Working

| Component | File | Evidence |
|---|---|---|
| Budget reserve/reconcile to real usage | `budget.py`, `transports.py` | `test_budget.py`, `test_transport.py` |
| Streaming reconcile to real SSE usage | `streaming.py` | `test_streaming_budget.py` |
| Circuit breaker state machine | `circuit.py` | `test_retry_aimd_circuit.py`, error-storm harness |
| AIMD concurrency adaptation | `aimd.py` | `test_retry_aimd_circuit.py` |
| Priority admission + starvation prevention | `admission.py` | `test_transport.py` |
| Tenant budget isolation + hierarchical rollup | `ledger.py` | `test_ledger.py`, `test_deep_research.py` |
| Response cache (exact + gzip replay) | `cache.py`, `transports.py` | `test_cache_gzip_replay.py` |
| Semantic (near-duplicate) cache | `cache.py` | `test_cache_semantic.py` |
| Fallback chain walking | `transports.py` | `test_fallback_chain.py` |
| Diff engine semantic similarity | `diff_engine.py` | `test_diff_engine.py` |
| CLI: doctor, benchmark, harness, metrics | `cli.py` | Manual + CI |
| TS SDK wrap() basics | `ts/backstop/src/wrap.ts` | `tests/wrap.test.ts` |
| Audit log (tamper-evident + verifiable) | `audit.py` | `test_deep_research.py` |
| Agent guard (sliding window) | `agent_guard.py` | `test_deep_research.py` |
| Quota-aware AIMD auto-tuning | `quotas.py` | `test_deep_research.py` |
| Secret provider interface | `secrets.py` | `test_deep_research.py` |
| Shadow/canary rollout | `rollout.py` | `test_deep_research.py` |
| Framework adapter bridge | `adapters/__init__.py` | `test_deep_research.py` |
| Gateway scaffold | `gateway.py` | `test_deep_research.py` |

### Partially Working (Functional but Fragile)

| Component | Problem |
|---|---|
| Wedge runner | Patch extraction handles only unified diffs; LLMs rarely output clean diffs |
| Gateway mode | Bare scaffold — no auth, no validation, no rate limiting |
| Framework adapters | Thin bridges that record metadata but do NOT enforce budgets inside the framework |
| Cost forecasting | Pure functions with no integration point to trigger enforcement |
| Secret provider | Interface exists but never called from the wrapper |
| Audit log | Works but not wired to default path; only fires when enabled |

### Broken / Misleading

| Component | Severity | Detail |
|---|---|---|
| README benchmark table | HIGH | Shows "Error Storm: 28 calls, 30 blocked" — current harness produces 12 calls, 42 blocked |
| `get_metadata()` in README | HIGH | `AttributeError` — export is `get_current_tenant` |
| Frozen-config hook example in README | MEDIUM | `FrozenInstanceError` when assigning to frozen dataclass |
| Version inconsistency | MEDIUM | pyproject=0.5.0, wedge=0.1.0, install.sh=0.4.0, docs=0.4.0 |
| `fastapi` extra undeclared | MEDIUM | `examples/fastapi_tenants.py` imports fastapi; extra exists in pyproject but not advertised |
| Wedge patch extraction | CRITICAL | Fails on code-block output (most common LLM format); returns raw text as "patch" |
| Wedge test execution | HIGH | test_command runs in worktree but patch may not be applied, so tests run against unmodified code |

---

## 3. Critical Gaps by Category

### A. Wedge — The Proof Tool (MOST CRITICAL)

1. **Patch extraction is the single point of failure.** `_extract_patch_from_output` only recognizes clean unified diffs. Real LLM outputs come as markdown code blocks, file-based formats (`FILE: main.py`), or raw code — none are parsed.
2. **Single-shot, no agent loop.** One LLM call, expects perfect patch. Not representative of real multi-agent coding.
3. **Hardcoded filename assumption.** Defaults to `main.py`; real repos have many files.
4. **No timeout on test execution.** `_run_test_command` has no timeout.
5. **No bundled test repo.** `task.yaml` references a repo structure that doesn't exist in the repo.
6. **No convergence evidence.** Running one task 3 times proves nothing.

### B. Backstop Core — Production Gaps

1. **No real-provider CI.** All tests use `MockTransport`. Real SDK changes silently break the wrapper.
2. **Provider fidelity risk.** Client cloning reads private SDK attributes (`_client`, `_transport`). Untested against multiple SDK versions.
3. **Gateway not production-ready.** No auth, no request validation, no rate limiting, no TLS.
4. **Framework adapters don't enforce.** LangChain handler only records metadata, doesn't wrap calls.
5. **Cost forecasting → enforcement gap.** `forecast.py` exists but nothing calls it to auto-trip.
6. **No structured logging.** Observability is counters-only; no JSON log output for debugging.
7. **Secret provider not wired.** Exists but never called from the transport.

### C. Proof & Evidence Gap

| Claim | Current Evidence | Required Evidence |
|---|---|---|
| "10× less to deploy" | README narrative | Side-by-side install time comparison |
| "p99 ≈ 0.07 ms overhead" | Local mock only | Real provider direct vs wrapped |
| "Per-agent budget isolation" | Wedge with broken patches | Real multi-agent: exhaust one runner, others continue |
| "50–80% semantic cache savings" | None | Measured hit rate on real workload |
| "Prevents runaway cost" | Harness scenario | Live test: budget=20k blocks 100k agent loop |
| "Wedge convergence" | None | 10+ tasks × 3 runners, reported distribution |

### D. Documentation & UX Gaps

1. Stale README benchmark table
2. `get_metadata` doesn't exist
3. Frozen-config hook example crashes
4. Version inconsistency across files
5. No API reference
6. No migration guide 0.1→0.5
7. No troubleshooting section
8. Missing examples for: semantic cache, fallback chain, OTel, Redis, audit, agent guard

### E. Security Gaps

1. `install.sh` uses `curl | sh` — supply chain risk
2. Secret provider not wired — env vars hold keys
3. Gateway has no authentication
4. No request body size limits
5. No PII redaction in audit/metrics
6. No rate limiting on gateway

### F. Installation & Distribution Gaps

1. install.sh references v0.4.0, code is at v0.5.0
2. No Docker image
3. No checksum/signature in install.sh
4. No SBOM

### G. TypeScript SDK Gaps

The TS SDK (`ts/backstop/`) is at v0.1.0 and covers only: budget, circuit breaker, retry, single fallback model. It is missing:

- Async support
- Priority admission
- AIMD concurrency
- Fallback chains (has single fallback only)
- Streaming budget reconciliation
- Tenant budgets
- Response caching (exact or semantic)
- Prometheus/OTel metrics
- Hooks
- Shared Redis budget
- Audit log
- Agent guardrails
- Cloud-quota auto-tuning
- Framework adapters
- Shadow/canary
- Gateway mode

---

## 4. Competitive Honest Assessment

| Dimension | Backstop | LiteLLM | Portkey |
|---|---|---|---|
| Drop-in wrapping | ✅ Best | 🟡 Proxy | 🟡 Proxy |
| Zero infra | ✅ | ❌ Server | ❌ Managed |
| Hot-path overhead | ✅ ~0.07ms | ❌ Network hop | ❌ Network hop |
| Semantic cache | ✅ | ❌ | ✅ |
| Fallback chains | ✅ | ✅ | ✅ |
| Multi-provider (100+) | ❌ | ✅ | ✅ |
| Virtual keys | ✅ | ✅ | ✅ |
| Audit log | ✅ | ✅ | ✅ |
| Reproducible benchmarks | ✅ | ❌ | ❌ |
| Multi-language | 🟡 Python+TS | ✅ Any | ✅ Any |
| Self-hosted | ✅ | ✅ | ❌ Managed |
| Real evidence of cost reduction | ❌ | ❌ | ❌ |

**Verdict:** Genuine technical differentiation (in-process, sub-ms, reproducible). But "10× better" is aspirational. No competitor has cost-reduction proof either — industry-wide gap. Opportunity: be FIRST to prove it.

---

## 5. Prioritized 1-Week Launch Plan

**User direction:** Both proofs (budget isolation + cost savings) at lighter depth; real API keys available; TS full parity; bump versions to 0.5.0.

### Day 1 — Fix Documentation & Wedge Foundation

| # | Task | Category |
|---|---|---|
| 1 | Fix README: benchmark table (regenerate from current harness) | Docs |
| 2 | Fix README: `get_metadata` → `get_current_tenant` | Docs |
| 3 | Fix README: frozen-config hook example (use constructor) | Docs |
| 4 | Bump wedge/__init__.py to 0.5.0 | Version |
| 5 | Bump install.sh to 0.5.0 | Version |
| 6 | Fix docs/install.md version refs to 0.5.0 | Version |
| 7 | Fix Wedge patch extraction: handle code-block format, file-based format, raw code | Wedge |
| 8 | Add test execution timeout to Wedge runner | Wedge |

### Day 2 — Create Proof Infrastructure & Bundled Test Repo

| # | Task | Category |
|---|---|---|
| 9 | Create bundled test repo (`wedge-test-fixture/`) with main.py + tests/ | Wedge |
| 10 | Update task.yaml to reference the fixture repo | Wedge |
| 11 | Add Wedge CLI: `--runners N`, `--budget N`, `--model`, `--base-url` | Wedge |
| 12 | Add Wedge runner: agent loop (plan → patch → test → retry) | Wedge |
| 13 | Add Wedge: proper multi-file patch application | Wedge |
| 14 | Add Wedge: report with per-runner budget evidence + cost estimate | Wedge |

### Day 3 — Real-Provider Proof (Budget Isolation + Cost Savings)

| # | Task | Category |
|---|---|---|
| 15 | Live budget exhaustion proof script (real OpenAI or Anthropic) | Proof |
| 16 | Live multi-agent isolation: 2 real runners, exhaust one, other continues | Proof |
| 17 | Real-provider overhead measurement (direct vs wrapped, p50/p99) | Proof |
| 18 | Semantic cache hit-rate demo (near-duplicate prompts, measure savings) | Proof |
| 19 | Publish all proofs to `docs/proof-2026-08-10.md` | Proof |

### Day 4 — Backstop Core Hardening

| # | Task | Category |
|---|---|---|
| 20 | Multi-SDK-version CI matrix (openai/anthropic 2-3 recent versions) | Core |
| 21 | Gateway: add API key auth | Core |
| 22 | Gateway: add per-key rate limiting | Core |
| 23 | Gateway: add request body size limit | Core |
| 24 | Structured JSON logging option (`BackstopConfig`) | Core |
| 25 | Wire secret provider into transport (resolve at call time) | Core |
| 26 | Cost forecasting → enforcement (auto-trip on horizon breach) | Core |

### Day 5 — TypeScript SDK Full Parity

| # | Task | Category |
|---|---|---|
| 27 | TS: Add async wrap support | TS |
| 28 | TS: Add priority admission + AIMD concurrency | TS |
| 29 | TS: Add fallback chains + priority routing | TS |
| 30 | TS: Add streaming budget reconciliation | TS |
| 31 | TS: Add tenant budgets (with_budget pattern) | TS |
| 32 | TS: Add response caching (exact + semantic) | TS |
| 33 | TS: Add hooks (before/after) | TS |
| 34 | TS: Add audit log | TS |
| 35 | TS: Add agent guardrails | TS |
| 36 | TS: Add quota-aware auto-tuning | TS |
| 37 | TS: Add cost forecasting | TS |
| 38 | TS: Add shadow/canary rollout | TS |
| 39 | TS: Expand test suite to cover all new features | TS |
| 40 | TS: Bump version to 0.5.0, update package.json | TS |

### Day 6 — Polish & Documentation

| # | Task | Category |
|---|---|---|
| 41 | Add API reference docs (from docstrings) | Docs |
| 42 | Add troubleshooting guide | Docs |
| 43 | Add migration guide 0.1→0.5 | Docs |
| 44 | Add examples: semantic cache, fallback chain, OTel, Redis, audit | Docs |
| 45 | Add end-to-end Wedge test (mock-based, CI-runnable) | Tests |
| 46 | Property-based tests for budget accounting (no overspend invariant) | Tests |
| 47 | Concurrent stress test (N threads reserve/commit, assert no overspend) | Tests |

### Day 7 — Final Integration & Launch Readiness

| # | Task | Category |
|---|---|---|
| 48 | Full test suite green (Python + TS) | QA |
| 49 | Live proof run end-to-end (real providers) | QA |
| 50 | Verify install.sh works for fresh install | QA |
| 51 | Generate and publish benchmark results with `--publish` | QA |
| 52 | Final README review against actual behavior | QA |
| 53 | Create GitHub release draft v0.5.0 | QA |

---

## 6. Proof Strategy

### A. Correctness Proof (automated, CI)
- Property-based tests: budget never negative, reservation always released, reconcile within [0, total]
- Concurrent stress: N threads reserve/commit simultaneously, assert no overspend
- SDK version matrix: CI passes against 3 latest SDK versions

### B. Performance Proof (benchmark, published)
- Overhead: direct vs wrapped against real provider (not mock), p50/p99
- Budget saved: agent loop that would spend X without Backstop, capped to Y with Backstop
- Cache hit rate: measured on realistic prompt distribution

### C. Isolation Proof (Wedge, the differentiator)
- Per-agent budget: 3 runners, exhaust one, others continue (live, real provider)
- Convergence rate: 10+ tasks × 3 runners, report CONVERGED/PARTIAL/DIVERGED distribution
- Budget-usage report: each runner's spend independent, sum ≤ N × per-runner budget

---

## 7. Key Decisions Made

| Decision | Choice |
|---|---|
| Proof strategy | Both (budget isolation + cost savings), lighter depth |
| API access | Real credentials available (OpenAI + Anthropic) |
| TS SDK scope | Full parity with Python v0.5.0 |
| Version numbering | Bump everything to 0.5.0 |
| Launch target | 1 week |

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| TS full parity in remaining days is large | Prioritize core features (budget, circuit, retry, fallback, cache) over advanced (gateway, Redis, OTel) |
| Live proof depends on API availability | Build mock-based fallback proofs that run in CI; run live proofs in parallel on Days 3-4 |
| Wedge agent loop complexity | Keep it simple: 1-3 retries max, not a full agent framework |
| Breaking changes in 0.5.0 | Document all breaking changes in migration guide; keep backward compat where possible |

---

*Saved to `research/deep-research-2026-08-10.md`*
