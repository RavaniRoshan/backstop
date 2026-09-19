# Milestone 1 (Phase 2) Handoff Report: 30-Second Keyless Proof, Demo Command, and Live Badges

**Worker**: `teamwork_preview_worker_m1`  
**Working Directory**: `/home/shiva/projects/backstop/.agents/worker_m1`  
**Milestone**: Milestone 1 (Phase 2 — The 30-Second Proof)  
**Date**: 2026-09-18  

---

## 1. Observation

### 1.1 `backstop verify` Refactor (`src/backstop/verify.py`)
- Previously, `_check_wrap()` and `_check_budget_block()` in `src/backstop/verify.py` directly called `httpx.Client(transport=BackstopTransport(...))` rather than testing real SDK client wrapping via `Backstop.wrap(client)`.
- We refactored `_check_wrap()` and `_check_budget_block()` to construct real SDK client instances (`openai.OpenAI` by default, or `anthropic.Anthropic` when `--provider anthropic` is requested) with an in-process mock transport, and wrap them via `Backstop.wrap()`.
- Runaway agent loop execution:
  - Budget: 500 tokens, `default_max_output_tokens=150`, 10 iterations.
  - Call 1 & 2: Completed within budget (250 tokens committed per call = 500 tokens).
  - Calls 3–10: Blocked in-process before transport dispatch with `BudgetExceededError`.
  - Exactly 2 allowed, 8 blocked, saving 2,000 tokens.
  - Verified `isinstance(first_exc, openai.OpenAIError)` (or `anthropic.AnthropicError`) is True, and `isinstance(first_exc, APIConnectionError)` is False.
- Hero result table formatted at the top of human output:
  ```markdown
  # Backstop Verify — 30-Second Keyless Proof

  Mode: offline (100% local mock transport, zero network, zero API keys)
  Provider: openai (gpt-4o-mini simulation)

  | Metric | Result | Notes |
  |---|---|---|
  | Allowed calls | 2 | Completed within budget (500 tokens) |
  | Blocked calls | 8 | Pre-empted before network dispatch |
  | Tokens reserved | 500 | Enforced budget ceiling |
  | Tokens saved | 2,000 | 8 runaway calls prevented |
  | Exception surfaced | BudgetExceededError | Caught cleanly (subclasses openai.OpenAIError) |
  | Wall-clock overhead | 0.10 ms | Control-path p99 mediation latency |

  ## Mechanism Checks
  - [PASS] config valid: BackstopConfig() constructed with sane bounds.
  - [PASS] wrap pipeline: Backstop.wrap(client) served a mock request end-to-end.
  - [PASS] budget block: 8/10 runaway calls blocked at 500-token budget (saved 2,000 tokens).
  - [PASS] overhead: control-path overhead p99 = 0.100 ms (direct p99 0.264 ms). Sub-millisecond-class in-process control path.
  - [PASS] cache hit: second identical request served from cache (cache_hits=1).
  - [PASS] per-agent isolation: agent A blocked 5/5 at its own cap while agent B kept serving — budgets are independent.
  - [PASS] hierarchical budgets: parent exhaustion blocks child; sibling unaffected; most-restrictive-wins enforced.
  - [PASS] shadow mode: budget exhausted but 0/10 requests blocked; would_block recorded=10 (enabled!=enforced: observations without denial).

  Summary: 8 passed, 0 warn, 0 failed, 0 skipped
  Status: VERIFIED (real wrap enforcement active)
  ```
- `--json` emits structured JSON including `summary`, `proof`, and `checks`.
- Verified keyless offline execution:
  `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli verify` exits 0 in < 0.6 seconds.

### 1.2 `backstop demo` Command (`src/backstop/demo.py` & `src/backstop/cli.py`)
- Created `src/backstop/demo.py` implementing `run_demo(...)` and `DemoResult`.
- Wired `demo` subparser and execution dispatch into `src/backstop/cli.py`.
- Side-by-side comparison:
  - **Unprotected**: 10 calls issued, full cost ($0.000080 for gpt-4o-mini) and 250 tokens consumed, 10 provider HTTP requests made.
  - **Wrapped (Backstop)**: 3 calls allowed (75 tokens), 7 calls blocked in-process with `BudgetExceededError`, only 3 provider HTTP requests made.
  - **Delta / Savings**: -7 calls (-70.0%), -175 tokens (-70.0%), -$0.000056 (-70.0%), 7 calls blocked before network.
- Output renders a clean, copy-pasteable Markdown table without ANSI noise:
  ```markdown
  # Backstop Demo: Runaway Loop Guardrail Comparison

  - **Scenario:** Simulated runaway agent loop (10 iterations)
  - **Provider:** openai (wrapped in-process via `Backstop.wrap`)
  - **Model:** gpt-4o-mini | **Budget:** 75 tokens
  - **Mode:** 100% offline (mock transport, zero API keys)

  | Metric | Unprotected | Wrapped (Backstop) | Delta / Savings |
  |---|---:|---:|---:|
  | Calls attempted | 10 | 10 | 0 |
  | Calls completed | 10 | 3 | -7 (-70.0%) |
  | Calls blocked | 0 | 7 | +7 (blocked in-process) |
  | Tokens consumed | 250 | 75 | -175 (-70.0%) |
  | Tokens saved | 0 | 175 | +175 tokens |
  | Estimated cost | $0.000080 | $0.000024 | -$0.000056 (-70.0%) |
  | Guardrail exception | None | BudgetExceededError | 7 calls blocked |
  | Provider HTTP calls | 10 | 3 | -7 calls prevented |
  | Total runtime | 344.1 ms | 6.0 ms | -338.0 ms |
  ```
- Supports `--strict` (returns 0 on enforcement success, 1 on failure) and `--json`.
- Runs 100% offline with zero API keys in < 0.4 seconds.

### 1.3 Status Badges in `README.md`
- In `README.md` lines 23–27, excised the static, unbacked `status-verified-green` badge.
- Replaced with live-backed badges:
  - CI Status: `https://github.com/RavaniRoshan/backstop/actions/workflows/ci.yml/badge.svg` (tested: HTTP 200)
  - License: `https://img.shields.io/github/license/RavaniRoshan/backstop` (tested: HTTP 200)
  - Python: `https://img.shields.io/badge/python-3.10%2B-blue` (tested: HTTP 200)

### 1.4 Test Suite Execution
- Added new test modules and fixtures:
  - `tests/test_verify.py`: Added proof metrics, json output, human table output, anthropic offline, and zero-key tests.
  - `tests/test_demo.py`: Added 5 tests covering openai/anthropic demo execution, markdown formatting, json output, and runtime.
  - `tests/test_cli.py`: Added 9 CLI integration tests for `verify` and `demo` (`--strict`, `--json`, `--provider anthropic`, zero keys).
  - Added `clean_registry` autouse fixtures across test files to guarantee weakref session garbage collection between tests.
- Ran full test suite:
  `.venv/bin/pytest tests` -> **249 passed, 5 skipped in 50.41s** (0 failed).
- Ran linter:
  `/home/shiva/.local/bin/ruff check src/backstop/verify.py src/backstop/demo.py tests/test_verify.py tests/test_demo.py tests/test_cli.py` -> **All checks passed!**

---

## 2. Logic Chain

1. **Problem**:
   - `backstop verify` did not use `Backstop.wrap()` or SDK clients, leaving the installation vulnerable to the objection that it might do nothing in real SDK pipelines.
   - There was no `backstop demo` command to showcase the side-by-side runaway loop story.
   - `README.md` contained a banned static `status-verified-green` badge.
2. **Resolution for `verify`**:
   - By creating SDK client instances configured with `compat.MockTransport` and passing them to `Backstop.wrap()`, `_check_wrap()` and `_check_budget_block()` exercise the authentic `Backstop` wrapper, `BackstopTransport`, `BackstopState`, and SDK exception translation pathways.
   - Because a mock transport is supplied directly to the client constructor with dummy API keys (`mock-key-verify`), no external HTTP traffic is generated and environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) are never accessed.
   - 10 iterations with a 500-token budget cleanly allow 2 calls (250 tokens each = 500 total) and block the remaining 8 calls in-process with `BudgetExceededError`, preserving 2,000 tokens.
3. **Resolution for `demo`**:
   - Creating `src/backstop/demo.py` and wiring `demo` subcommand into `src/backstop/cli.py` allows users and CI to run `backstop demo` without network or API keys.
   - The unprotected loop simulates runaway consumption of 250 tokens across 10 calls, while the wrapped loop blocks at call 3, achieving exactly 70.0% savings (175 tokens saved) and proving the in-process interception value proposition.
4. **Resolution for Badges**:
   - Replacing `status-verified-green` with live GitHub Actions CI and GitHub License badges eliminates unverified marketing claims and adheres to the banned vocabulary policy in `PLAN.md` §4 line 183.
5. **Resolution for Test Isolation**:
   - `SessionRegistry` tracks live states via weak references. In long test sessions, uncollected cyclic references can temporarily leave rows in `get_registry().states()`. Adding autouse `clean_registry` fixtures calling `get_registry().reset()` and `gc.collect()` prevents cross-test contamination and ensures all 249 tests pass reliably.

---

## 3. Caveats

1. **Anthropic SDK Optional Dependency**:
   `openai` is a required package in `pyproject.toml`, while `anthropic` is in `optional-dependencies`. When `--provider anthropic` is invoked in an environment where `anthropic` is absent, both `verify` and `demo` report an informative error and exit cleanly rather than crashing.
2. **PyPI Version Badge Deferred**:
   `backstop-ai` has not yet been published to PyPI (scheduled for Phase 5). A live PyPI badge at this stage would display "package not found" in red; therefore, only the live GitHub Actions CI, License, and Python badges are active in `README.md`.

---

## 4. Conclusion

- Milestone 1 (Phase 2) of Backstop Launch is completely implemented and verified.
- `backstop verify` exercises real `Backstop.wrap()` on mock SDK clients, catches `BudgetExceededError`, verifies exception subclassing, and outputs a compact Markdown result table and structured JSON.
- `backstop demo` runs an offline side-by-side comparison, proving 70.0% token savings (175 tokens, 7 calls blocked before network), and outputs clean Markdown and JSON.
- `README.md` status badges are live-backed and free of banned vocabulary.
- Full test suite passes 100% (249 passed, 5 skipped, 0 failed), ruff is clean, and zero secrets are present in any commit or diff.

---

## 5. Verification Method

To independently verify this work:

1. **Full Test Suite**:
   ```bash
   .venv/bin/pytest tests
   ```
   *Expected*: 249 passed, 5 skipped, 0 failed.

2. **Milestone 1 Test Modules**:
   ```bash
   .venv/bin/pytest tests/test_verify.py tests/test_demo.py tests/test_cli.py -v
   ```
   *Expected*: 27 passed in < 4s.

3. **Keyless Offline Verify (Human & Strict & JSON)**:
   ```bash
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli verify
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli verify --strict
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli verify --json
   ```
   *Expected*: Exits 0, runtime < 1s, displays hero table showing 2 allowed, 8 blocked, 2,000 tokens saved.

4. **Keyless Offline Demo (Human & Strict & JSON & Anthropic)**:
   ```bash
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli demo
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli demo --strict
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli demo --json
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli demo --provider anthropic
   ```
   *Expected*: Exits 0, runtime < 0.5s, displays clean Markdown table showing 10 vs 3 calls, 7 blocked, -70.0% savings.

5. **Lint Check**:
   ```bash
   /home/shiva/.local/bin/ruff check src/backstop/verify.py src/backstop/demo.py tests/test_verify.py tests/test_demo.py tests/test_cli.py
   ```
   *Expected*: All checks passed!

6. **Badge HTTP Probes**:
   ```bash
   curl -sI "https://github.com/RavaniRoshan/backstop/actions/workflows/ci.yml/badge.svg" | grep "HTTP"
   curl -sI "https://img.shields.io/github/license/RavaniRoshan/backstop" | grep "HTTP"
   curl -sI "https://img.shields.io/badge/python-3.10%2B-blue" | grep "HTTP"
   ```
   *Expected*: All return HTTP/2 200.
