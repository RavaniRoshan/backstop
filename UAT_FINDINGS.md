# Backstop / Wedge — End-to-End UAT Findings Report

**Role:** Software Testing Engineer (end-to-end, as a real user / enterprise)
**Date:** 2026-07-12
**Environment:** Linux, Python 3.12.3, venv with `backstop 0.1.0` (editable, local source),
`openai 2.45.0`, `anthropic 0.116.0`, `httpx 0.28.1`, `prometheus_client 0.25.0`, `pytest 9.1.1`.
**Scope:** Full offline end-to-end UAT. Live API paths (`real-anthropic`, `real-openai`,
live `wedge run`, live tenant budgets) were **NOT executed** (no credentials) and are flagged
as *untested* below. Everything else was exercised with `httpx.MockTransport`.

**Test execution results**
- `pytest` full suite: **36 passed, 4 skipped** (the 4 skipped are the live-API markers).
- Targeted mock-transport experiments: **19/19 passed** (budget, streaming, circuit, AIMD, retry,
  tenant, cache, hooks, metrics).
- All 4 harness scenarios ran and produced reports.
- Metrics server exposed all `backstop_*` Prometheus series.
- Diff engine + report generation validated with synthetic patches.

---

## CRITICAL

### C1. Wedge runner does not apply patches, run tests, or use worktrees — it is a stub, not the tool the README sells
**File:** `src/wedge/runner.py` (entire `WedgeRunner`), `src/wedge/cli.py`
**README claims:** each runner gets "its own isolated working directory (simulated git worktree)",
runs "an isolated coding agent", the diff engine scores "patch similarity", and the report shows
"each runner's Backstop budget usage — the first real usage evidence". The Architecture section says
"isolated context, not isolated infrastructure" with real runners.
**Actual:** `WedgeRunner._generate_patch` makes **one** LLM call and returns the raw model text as the
"patch". `_setup_worktree` creates a temp dir that is **never used** (no `git worktree`, repo_path is
ignored). The `test_command` from `task.yaml` is **parsed but never executed** (`test_passed` is
hard-coded `True`). The "patch" is just `{filename: model_output_text}` — diffed as raw strings.
**Impact:** Wedge does **not** measure what the README claims (real agentic coding convergence). It is a
single-shot prompt-to-text comparison with no repo interaction. README's core thesis ("does isolated
multi-agent execution reduce runaway-cost exposure") is **not actually demonstrated** by this code.
**Evidence:** `runner.py:46-52` returns `{"main.py": patch}` with `test_passed=True`; `run_task` diffs
`r["patch"]` strings; live run reached the API and returned only model text.

### C2. Wedge is broken against a real provider — hard-coded model `claude-3-5-sonnet-20241022` does not exist
**File:** `src/wedge/runner.py:67` (and `gpt-4` at line 75)
**Repro:** `wedge run task.yaml` (this env proxies to a model gateway).
**Actual:** `anthropic.NotFoundError: 404 - No endpoints found for anthropic/claude-3.5-sonnet.`
**Impact:** Even fixing C1, `wedge run` fails immediately for every runner. The model is also outdated
vs the README's own examples (`claude-sonnet-4-20250514`). The OpenAI path hard-codes `gpt-4`.
**Note:** There is also **no `base_url` override** for the Wedge runner, so it cannot target a custom
endpoint even if you fix the model name.

---

## HIGH

### H1. `backstop real-anthropic` / `real-openai` crash with a raw traceback when credentials are missing
**File:** `src/backstop/cli.py` (no try/except around `run_real_*_smoke`); `real_*.py` raise `RuntimeError`.
**Repro:** `backstop real-anthropic` with no `ANTHROPIC_API_KEY`.
**Actual:** Full Python traceback ending in `RuntimeError: set ANTHROPIC_API_KEY to run the real ...`.
Exit code 1.
**Expected (UX):** A clean one-line message + non-zero exit, e.g. `error: ANTHROPIC_API_KEY not set`.
**Impact:** Poor first-run experience for the exact command new users try first; looks like a crash.

### H2. README documents `get_metadata(...)` which does not exist
**File:** `README.md` (Tenant Budgets / hooks section) vs `src/backstop/__init__.py`
**Actual:** `backstop.get_metadata` → `AttributeError`. The module exports `get_current_tenant` (works).
**Impact:** Any user copy-pasting the README tenant/hook snippet fails. Doc/vs-code mismatch.

### H3. README's hard-coded models do not match the code's defaults (and one default is likely bogus)
- `backstop real-openai` defaults to `gpt-5.5` (`src/backstop/real_openai.py:12 DEFAULT_REAL_MODEL`),
  while the README's smoke example uses `gpt-4.1-mini`. `gpt-5.5` is not a known public model → the
  default `real-openai` smoke would fail even with a valid key unless `--model` is passed.
- Wedge hard-codes `claude-3-5-sonnet-20241022` (README examples use `claude-sonnet-4-20250514`). See C2.
**Impact:** Default commands don't work as documented; users must discover the correct model manually.

### H4. README "Key scenario results" benchmark table is stale / not reproducible from the current harness
**File:** `README.md` Benchmark section vs `src/backstop/harness.py`
**README claims:** Error Storm → 50 req, 28 provider calls, 30 blocked, "circuit breaker tripped after
7 errors"; Budget Hit → 80 req, 17 provider calls, 63 blocked.
**Actual harness run (current config):** Error Storm → 50 req, **12** provider calls, **42** circuit-blocked,
2 provider errors; Budget Hit → 80 req, 18 provider calls, **62** blocked.
**Why:** harness.py Error Storm uses `circuit_failure_threshold=0.5` (README's "after 7 errors" implies the
old 0.8 threshold) and the README table's parameters differ from the shipped harness. The numbers are
also non-deterministic (random error injection, thread timing).
**Impact:** A user re-running the documented benchmark gets different numbers and may suspect a bug. The
README table should either be regenerated from the current harness or labeled as illustrative.

---

## MEDIUM

### M1. Streaming requests charge the *estimated* tokens, never the real streamed usage
**File:** `src/backstop/transports.py` (streaming branch sets `usage=None`), `src/backstop/streaming.py`
(`reconcile(reservation, None, success=...)`), `src/backstop/budget.py:63` (`charge = reservation.tokens`
when `success and actual is None`).
**Verified:** A streamed request with `default_max_output_tokens=50` charged 50 (the estimate); the real
`output_tokens:3` in the SSE body was ignored. `remaining` = 50, `spent` = 50.
**Impact:** Streaming budgets only enforce the *upper-bound estimate*, not actual consumption. For long
streams this massively over-reserves and makes per-request budget accounting meaningless. This is the
single biggest correctness gap in the core pipeline. (Could be by design, but it is undocumented and
contradicts "Reconcile after response" in the feature list.)

### M2. `BackstopConfig` is frozen — README's `st.config.before_request = ...` pattern raises
**File:** `src/backstop/config.py:31` (`@dataclass(frozen=True)`) vs README Tenant example
`st.config.before_request = lambda ...`
**Actual:** `dataclasses.FrozenInstanceError: cannot assign to field 'before_request'`.
**Correct usage:** pass `config=BackstopConfig(before_request=..., after_response=...)` to `Backstop.wrap`.
**Impact:** The README's tenant/hook snippet crashes. Hooks work fine when set via constructor.

### M3. `examples/fastapi_tenants.py` is not runnable — `fastapi` is not a dependency
**File:** `examples/fastapi_tenants.py`, `pyproject.toml` (no `fastapi` extra)
**Actual:** `import fastapi` fails (not installed; not declared anywhere in pyproject).
**Impact:** An advertised example fails on a clean install. Either add a `fastapi` extra or document the
manual `pip install fastapi`.

### M4. Version / changelog inconsistency
- Installed/local `pyproject` version = `0.1.0`; the same file's README & changelog describe **v0.3.0**
  ("feat: Backstop v0.3.0 …"). On PyPI the latest is `0.1.1`.
- The git log's most recent feature commit says "Backstop v0.3.0" but the package version is 0.1.0.
**Impact:** Confusing release state; `pip install backstop` (0.1.1) may differ from source (0.1.0) and
from the documented 0.3.0 feature set.

### M5. `wed` / README describe "simulated git worktree" and `test_command` execution that do not exist (see C1)
Tracked under C1 but explicitly noted: `task.yaml`/`task_openai.yaml` both carry `test_command: "pytest tests/"`
which is silently ignored. The convergence verdict therefore has **no test signal** behind it.

---

## LOW / COSMETIC / QUESTIONS

### L1. Overly-broad `except (LatencyBudgetExceededError, Exception)` in transports
**File:** `src/backstop/transports.py:226` (sync), `:505` (async).
`... except (LatencyBudgetExceededError, Exception)` is equivalent to `except Exception` (since
`Exception` is in the tuple) and **swallows every error** (then re-raises, so behavior is OK, but the
specific `LatencyBudgetExceededError` branch is dead and misleading). Should be `except Exception:`.
Low severity — no functional bug, but it hides intent and could mask a future specific handler.

### L2. Redundant `deadline`-based LatencyBudgetExceededError raise is unreachable
**File:** `src/backstop/transports.py:265-267` — after `gate.acquire`, `if deadline is not None and
time.monotonic() >= deadline: raise ...`. Since `acquire` already raises `TimeoutError`->re-raised as
`LatencyBudgetExceededError` when it times out, this post-check is dead code. Harmless.

### L3. `latency.py` `first_chunk_ms` is computed but never populated for streams
`first_byte_at` is only set for non-streaming (`tracker.first_byte_at = tracker.request_sent_at`). For
streaming, `first_chunk_ms` in `BackstopMeta` is always `None`. The field is exported but never meaningful.
Minor; dead/confusing surface.

### L4. Circuit-breaker metrics labeling is fine — no crash (false alarm checked)
I hypothesized `circuit_trips`/`aimd_changes` might be called without their label and crash under
prometheus. **Verified false:** all call sites pass the label, and a real run with prometheus installed
exposed all series without error. (`src/backstop/metrics.py` + transports are correct here.)

### L5. `Budget.reconcile` thread math is safe but slightly sloppy
`src/backstop/budget.py:67-69`: `self._reserved = max(0, self._reserved - reservation.tokens)` then
`self._spent = min(self.total, self._spent + charge)`. Two separate locked operations; correct in practice
(no double-count), but not a single atomic step. Low risk given the GIL + per-request flow.

### L6. Convergence metric is character-level `difflib` similarity, not AST/semantic
**File:** `src/wedge/diff_engine.py`. Matches README's stated v1 limitation ("Not AST-level semantic
diffing"). Fragile for real code (whitespace/formatting changes flip CONVERGED→DIVERGED) but documented.
Informational.

### L7. `Priority` import works; `budget=None`/`budget=0` semantics match README
Verified: `budget=None` → unlimited pass-through, `remaining is None`; `budget=0` → blocks before dispatch.
Both as documented. (Positive result.)

---

## WHAT WORKS WELL (verified)
- Budget reserve/reconcile to **actual** usage for non-streaming requests (100-10=90 ✓).
- Circuit breaker opens under error storm, half-open/cooldown works (42 blocked in error-storm ✓).
- AIMD decreases under pressure (8→2) and recovers under success (→62) ✓.
- Retry + backoff on 429/500/502/503/504/529 recovers on next attempt ✓.
- Tenant budgets via `with_budget` isolate per-tenant spend from the global budget ✓.
- Response cache serves identical requests without a provider call ✓.
- before/after hooks fire with correct payloads (via constructor) ✓.
- Priority admission: critical beats background when capacity opens (unit test) ✓.
- `backstop metrics` serves a complete Prometheus `/metrics` exposition ✓.
- `backstop harness` (all 4 scenarios) + `--json`, and clean CLI usage errors ✓.
- All 36 unit/component tests pass; examples compile; budget demo runs offline with a mock ✓.

## OVERALL VERDICT
**Backstop core (the transport wrapper) is solid and does what it claims for the non-streaming path:**
budgets, circuit breaking, AIMD, retries, priority, tenant isolation, caching, hooks, and Prometheus
metrics all function correctly and are well-tested. The main product weaknesses are: (1) **streaming
budgets never reconcile to real usage** (M1) — a real correctness gap; (2) **documentation drift** —
missing `get_metadata`, frozen-config hook example, stale benchmark table, bogus `gpt-5.5` default,
version/changelog mismatch (H2/H3/H4/M4). **Wedge, the headline multi-agent feature, is effectively a
non-functional stub**: it does not apply patches, run tests, or use worktrees (C1), and its runner is
broken against a real provider due to a hard-coded nonexistent model with no base-URL override (C2).
Wedge needs a substantial reimplementation before its advertised value (multi-agent convergence +
real budget-usage evidence) can be tested.

## LIVE RE-TEST ADDENDUM — 2026-07-12

The live API paths previously flagged *untested* were executed this session against
**OpenCode Zen** (`https://opencode.ai/zen/v1`), model `deepseek-v4-flash-free` (free tier),
using a real API key supplied **only via environment variables** (never written to source/commit).

**Results — all pass:**
- `backstop real-openai` (chat, sync + async): status `ok`, budget reconciled (106/1000).
- Streaming budget reconcile: billed **actual** usage (290), not the 200-token estimate; reservation released.
- Response cache: cache HIT on 2nd identical call, zero extra spend.
- Hooks (before/after), tenant budgets, priority header: all functional.
- **Wedge live run (2 runners):** real LLM calls → isolated worktrees → `test_command` → convergence
  report; worktrees auto-cleaned.

**New defect found & fixed during live testing:**
- Response cache crashed on compressed (gzip) provider responses (`zlib.error` on replay). Fixed in
  `src/backstop/transports.py` (strip `content-encoding`/`content-length`/`transfer-encoding` on replay)
  with regression test `tests/test_cache_gzip_replay.py`.
- Wedge hard-coded model (C2) — added `model` override from `task.yaml` + `reasoning_content` fallback
  (DeepSeek is a reasoning model), wired through `wedge/cli.py`.

This supersedes the earlier "Wedge is a non-functional stub / streaming never reconciles" verdicts:
both were resolved by the fix pass and verified live.

## SCHEDULED RE-CHECK
**Next live end-to-end UAT: 2026-07-26 (+14 days from 2026-07-12).** Repeat the live suite above to
confirm the fixes hold against the real provider and that no regressions slipped in.
