# Technical Exploration Report: `backstop verify` Phase 2 Refactor

**Explorer**: `teamwork_preview_explorer_m1_1`  
**Working Directory**: `/home/shiva/projects/backstop/.agents/explorer_m1_1`  
**Milestone**: Milestone 1 (Phase 2 — The 30-Second Proof)  
**Date**: 2026-09-18  

---

## 1. Observation

### 1.1 Current CLI Interface (`src/backstop/cli.py`)
- **Location**: `src/backstop/cli.py:359–371`, `468–479`
- **Subparser**: `verify`
- **Supported Flags**:
  - `--live`: flag (`action="store_true"`), triggers live probe via `GET /models`.
  - `--offline`: flag (`action="store_true"`), default behavior (runs offline).
  - `--strict`: flag (`action="store_true"`), treats warnings as failures (`exit_code = 1`).
  - `--json`: flag (`action="store_true"`), outputs JSON instead of human-readable text.
  - `--provider`: `choices=["openai", "anthropic"]`, default="openai".
  - `--model`: optional string for provider model.
  - `--base-url`: optional string to override API endpoint.
  - `--api-key-env`: string, defaults to `"OPENAI_API_KEY"`.
  - `--timeout`: float, default 30.0s.
- **Dispatch**:
  ```python
  if args.command == "verify":
      return run_verify(
          live=args.live,
          strict=args.strict,
          json_output=args.json,
          timeout=args.timeout,
          provider=args.provider,
          model=args.model,
          base_url=args.base_url,
          api_key_env=args.api_key_env,
      )
  ```
- **Missing CLI Feature**: There is currently no `backstop demo` command in `cli.py` (only `dashboard --demo`).

### 1.2 Current Verify Runner (`src/backstop/verify.py`)
- **Location**: `src/backstop/verify.py:58–480`
- **Execution**:
  `run()` executes 8 checks in offline mode:
  1. `_check_config` (line 96)
  2. `_check_wrap` (line 109)
  3. `_check_budget_block` (line 127)
  4. `_check_overhead` (line 165)
  5. `_check_cache_hit` (line 211)
  6. `_check_isolation` (line 261)
  7. `_check_hierarchical` (line 309)
  8. `_check_shadow` (line 349)
  Plus `_check_provider_auth` (line 395) if `live=True`.
- **Critical Flaws in Existing Implementation**:
  1. **Does not use `Backstop.wrap()`**:
     In `_check_wrap` (lines 112–117):
     ```python
     state = BackstopState.create(100_000, BackstopConfig(default_max_output_tokens=1))
     client = httpx.Client(
         transport=BackstopTransport(state, httpx.MockTransport(self._mock_response())),
         base_url="https://mock.local",
     )
     resp = client.post("/v1/chat/completions", json={"model": "mock", "messages": []})
     ```
     This bypasses `Backstop.wrap()` entirely. It directly attaches `BackstopTransport` to a raw `httpx.Client`.
  2. **No Real SDK Client in `_check_budget_block`**:
     In `_check_budget_block` (lines 130–145):
     ```python
     state = BackstopState.create(20, BackstopConfig(retry_max_attempts=1, circuit_min_requests=10_000))
     client = httpx.Client(
         transport=BackstopTransport(state, httpx.MockTransport(self._mock_response({"ok": True, "usage": {"total_tokens": 10}}))),
         base_url="https://mock.local",
     )
     for _ in range(10):
         try:
             client.post("/v1/chat/completions", json={"model": "mock", "messages": [{"role": "user", "content": "x"}]})
         except Exception:
             blocked += 1
     ```
     It does not instantiate an `openai.OpenAI` or `anthropic.Anthropic` client, does not call `Backstop.wrap()`, and catches generic `Exception` instead of checking `BudgetExceededError`.
  3. **No Result Table**:
     `render_human` (lines 482–494) formats only a list of check statuses:
     ```
     # Backstop Verify

     - [PASS] config valid: BackstopConfig() constructed with sane bounds.
     - [PASS] wrap pipeline: BackstopTransport served a mock request end-to-end.
     ...
     Summary: 8 passed, 0 warn, 0 failed, 0 skipped
     ```
     It does NOT render the compact enforcement proof table required by PLAN 2.1.3 (allowed / blocked calls, tokens reserved, tokens saved, exception name, wall-clock overhead).
  4. **`--json` Output Lacks Proof Metrics**:
     Emits only `{"summary": summary, "checks": [...]}` without structured proof metrics.

### 1.3 `Backstop.wrap()` Underlying Mechanism (`src/backstop/wrapper.py`)
- **Inspection of `wrap()`**:
  `Backstop.wrap(client, budget, config)` inspects `client.__class__`, detects provider via `_detect_provider(cls)` (`"openai"` or `"anthropic"`), extracts `client._client`'s transport via `_sync_transport_from(base)`, builds `BackstopTransport(state, underlying, compat=compat)`, and clones the client with `http_client=wrapped_http_client`.
- **Mock Transport Verification**:
  When an `openai.OpenAI` client is initialized with:
  `raw = openai.OpenAI(api_key="mock-key-verify", http_client=httpx.Client(transport=httpx.MockTransport(handler)))`
  `Backstop.wrap(raw, budget=500)` successfully wraps the client, preserves the mock transport, and prevents all external network calls.
- **Keyless Execution Verification**:
  Verified with `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY`:
  The client initializes and executes 100% offline without reading environment variables.
  Output from live probe:
  `Keyless wrap success: allowed=2, blocked=8, provider_calls=2`
  `Exception: BudgetExceededError, OpenAIError subclass: True`

### 1.4 Wall-Clock Performance
- Execution duration of `VerifyRunner().run()`:
  - Client initialization and `wrap()`: ~3.3 ms
  - Runaway loop (10 calls): ~410 ms (initial OpenAI SDK schema cache ~399 ms, subsequent calls ~1 ms each)
  - Overhead check (300 calls direct vs Backstop): ~100 ms
  - Total `backstop verify` wall-clock execution: **~0.55 seconds**.
  - Target requirement: `< 30 seconds`. Measured runtime is **< 1 second** (>50x faster than required).

### 1.5 Current Test Suite Status
- Command: `.venv/bin/pytest tests`
- Result: **229 passed, 5 skipped in 45.81s**
- Tests covering verify: only `tests/test_verify.py` (7 tests).

---

## 2. Logic Chain

### Step 1: Connecting Plan Requirements to Code Deficiencies
- **Observation**: PLAN.md §10 (Phase 2.1.2) dictates: *"Make it exercise the real path: `Backstop.wrap()` → simulated runaway agent loop → tiny budget → assert the block surfaces as a catchable `BudgetExceededError`"*.
- **Gap**: Current `_check_wrap` and `_check_budget_block` in `src/backstop/verify.py` call `httpx.Client(transport=BackstopTransport(...))` directly, completely bypassing `Backstop.wrap()` and `openai.OpenAI` / `anthropic.Anthropic`.
- **Inference**: `_check_budget_block` must be upgraded to instantiate a real SDK client (`openai.OpenAI` by default, `anthropic.Anthropic` when `--provider anthropic`), wrap it using `Backstop.wrap()`, execute a 10-iteration runaway loop with a 500-token budget, and record proof metrics.

### Step 2: Ensuring Complete Offline & Keyless Invariants
- **Observation**: Acceptance criteria demand `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY backstop verify` passes in < 30s.
- **Mechanism**: The provider SDK client constructor accepts `api_key` and `http_client` parameters. When `api_key="mock-key-verify"` and `http_client=httpx.Client(transport=httpx.MockTransport(handler))` are passed to `openai.OpenAI(...)`, the SDK:
  1. Never inspects `os.environ["OPENAI_API_KEY"]`.
  2. Directs all wire requests into the mock transport callback.
  3. Operates entirely in-memory with zero network overhead.
- **Inference**: Offline mode is 100% airtight and requires no API keys.

### Step 3: Determining Token Math for Runaway Simulation
- **Observation**:
  - `budget = 500` tokens.
  - `BackstopConfig(default_max_output_tokens=150, retry_max_attempts=1)`.
  - Mock response usage: `prompt_tokens = 100`, `completion_tokens = 150`, `total_tokens = 250`.
- **Execution**:
  - Call 1: Estimate = 151 tokens ≤ 500. Allowed. Commits 250 tokens. Remaining budget = 250.
  - Call 2: Estimate = 151 tokens ≤ 250. Allowed. Commits 250 tokens. Remaining budget = 0.
  - Call 3: Estimate = 151 tokens > 0. Blocked by `BudgetExceededError`!
  - Calls 4–10: All blocked by `BudgetExceededError`.
- **Inference**:
  - Allowed calls = 2
  - Blocked calls = 8
  - Tokens reserved = 500
  - Tokens saved = 8 calls × 250 tokens = 2,000 tokens saved!
  - Surface exception = `BudgetExceededError` (inheriting from `openai.OpenAIError` or `anthropic.AnthropicError`).

### Step 4: Formatting the Compact Result Table and JSON Output
- **Observation**: PLAN.md §10 (Phase 2.1.3) requires: *"Print a compact, honest result table: allowed / blocked calls, tokens reserved, tokens saved, exception name, wall-clock overhead"*.
- **Inference**:
  The human-readable output should present the markdown enforcement proof table right under the header, followed by the individual mechanism checks and summary.
  The JSON output should include top-level `"proof"` object with these metrics alongside `"summary"` and `"checks"`, preserving backwards compatibility with existing assertions in `test_verify.py`.

### Step 5: Exit Code and `--strict` Behavior
- **Observation**: In `VerifyRunner.summarize(results)`:
  `exit_code = 1` if `failed > 0` or (`self.strict and warned > 0`), else `0`.
- **Inference**: This logic already handles `--strict` correctly, but test coverage must verify that warnings trigger exit 1 under `--strict` and exit 0 without `--strict`.

---

## 3. Caveats

1. **CPython Startup / SDK Model Import Overhead**:
   The first call to `openai.chat.completions.create` takes ~390 ms due to lazy loading of Pydantic models in the OpenAI SDK. Subsequent calls take ~1 ms. Total runtime remains under 0.6 seconds, far below the 30-second budget.
2. **Provider Availability**:
   `openai` is a mandatory core dependency in `pyproject.toml` (`openai>=2.37,<4`). However, `anthropic` is in `optional-dependencies`. If `--provider anthropic` is requested in an environment without `anthropic` or `httpx2`, it should fail cleanly with a clear fix instruction.
3. **Compatibility with Existing Tests**:
   `tests/test_verify.py` checks for specific check titles: `"config valid"`, `"wrap pipeline"`, `"budget block"`, `"overhead"`, `"cache hit"`, `"per-agent isolation"`. To prevent breaking regressions, the updated checks must maintain these titles.

---

## 4. Conclusion & Concrete Recommendations

### 4.1 Proposed Implementation Architecture

#### A. In `src/backstop/verify.py`:
1. Add mock provider response handlers returning realistic payloads:
   ```python
   def _mock_openai_handler(self) -> Callable[[httpx.Request], httpx.Response]:
       def handler(request: httpx.Request) -> httpx.Response:
           return httpx.Response(200, json={
               "id": "chatcmpl-verify-mock",
               "object": "chat.completion",
               "created": int(time.time()),
               "model": "gpt-4o-mini",
               "choices": [{"index": 0, "message": {"role": "assistant", "content": "proof"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 100, "completion_tokens": 150, "total_tokens": 250},
           })
       return handler
   ```
2. Refactor `_check_wrap()` to test real `Backstop.wrap()` with a single call:
   - Instantiates `openai.OpenAI(api_key="mock-key-verify", http_client=httpx.Client(transport=httpx.MockTransport(...)))`.
   - Wraps with `Backstop.wrap(raw_client, budget=100_000)`.
   - Executes `wrapped.chat.completions.create(...)`.
   - Verifies response status and client cleanup.
3. Refactor `_check_budget_block()` to execute the **real runaway loop proof**:
   - Budget: 500 tokens, `default_max_output_tokens=150`.
   - 10 iterations.
   - Asserts:
     - `allowed == 2`
     - `blocked == 8`
     - `first_exc` is `BudgetExceededError`
     - `isinstance(first_exc, sdk_base_error)` is True
     - `isinstance(first_exc, sdk_api_connection_error)` is False
   - Populates `self.proof`:
     ```python
     self.proof = {
         "provider": self.provider,
         "budget": 500,
         "iterations": 10,
         "allowed_calls": allowed,
         "blocked_calls": blocked,
         "tokens_reserved": 500,
         "tokens_saved": blocked * 250,
         "exception_name": type(first_exc).__name__,
         "exception_subclass_verified": isinstance(first_exc, base_error),
         "overhead_p99_ms": overhead_ms,
         "wall_clock_ms": round(loop_duration_ms, 2),
     }
     ```
4. Update `render_human(results, summary, strict, proof=None)`:
   Print markdown header, the compact enforcement proof table:
   ```markdown
   # Backstop Verify — 30-Second Keyless Proof

   Mode: offline (100% local mock transport, zero network, zero API keys)
   Provider: OpenAI (gpt-4o-mini simulation)

   | Metric | Result | Notes |
   |---|---|---|
   | Allowed calls | 2 | Completed within budget (500 tokens) |
   | Blocked calls | 8 | Pre-empted before network dispatch |
   | Tokens reserved | 500 | Enforced budget ceiling |
   | Tokens saved | 2,000 | 8 runaway calls prevented |
   | Exception surfaced | BudgetExceededError | Caught cleanly (subclasses openai.OpenAIError) |
   | Wall-clock overhead | 0.12 ms | Control-path p99 mediation latency |

   ## Mechanism Checks
   - [PASS] config valid: BackstopConfig() constructed with sane bounds.
   - [PASS] wrap pipeline: Backstop.wrap(client) served a mock request end-to-end.
   - [PASS] budget block: 8/10 runaway calls blocked at 500-token budget (saved 2,000 tokens).
   - [PASS] overhead: control-path overhead p99 = 0.120 ms (direct p99 0.235 ms). Sub-millisecond-class in-process control path.
   - [PASS] cache hit: second identical request served from cache (cache_hits=1).
   - [PASS] per-agent isolation: agent A blocked 5/5 at its own cap while agent B kept serving — budgets are independent.
   - [PASS] hierarchical budgets: parent exhaustion blocks child; sibling unaffected; most-restrictive-wins enforced.
   - [PASS] shadow mode: budget exhausted but 0/10 requests blocked; would_block recorded=10.

   Summary: 8 passed, 0 warn, 0 failed, 0 skipped
   Status: VERIFIED (real wrap enforcement active)
   ```
5. Update `--json` rendering:
   Output `{"summary": summary, "proof": runner.proof, "checks": [r.to_dict() for r in results]}`.

### 4.2 Recommended New Test Cases in `tests/test_verify.py`
Add the following dedicated test functions:
1. `test_verify_real_wrap_proof_metrics()`: Verify that `VerifyRunner()` populates `runner.proof` with `allowed_calls=2`, `blocked_calls=8`, `tokens_saved=2000`, `exception_name="BudgetExceededError"`.
2. `test_verify_anthropic_offline()`: Verify `VerifyRunner(provider="anthropic")` when `anthropic` is installed.
3. `test_verify_keyless_environment()`: Explicitly clear `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` in `monkeypatch` and assert `run_verify() == 0`.
4. `test_verify_json_output(capsys)`: Call `run_verify(json_output=True)` and assert `json.loads(capsys.readouterr().out)` contains `proof`, `summary`, and `checks`.
5. `test_verify_human_table_output(capsys)`: Call `run_verify(json_output=False)` and verify that the table headers and metrics (`| Allowed calls |`, `| Blocked calls |`, etc.) appear in stdout.
6. `test_verify_execution_time_under_30s()`: Measure `run_verify()` execution time and assert `elapsed < 5.0` seconds.
7. `test_cli_verify_commands()`: Test invoking CLI with `main(["verify"])`, `main(["verify", "--strict"])`, `main(["verify", "--json"])`.

---

## 5. Verification Method

To independently verify the recommendations and the subsequent worker implementation:

1. **Keyless Offline CLI Test**:
   ```bash
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli verify
   ```
   - Must exit with code `0`.
   - Must display the enforcement proof markdown table showing `Allowed calls: 2`, `Blocked calls: 8`, `Tokens saved: 2,000`, `Exception surfaced: BudgetExceededError`.
   - Must finish in `< 30s` (measured `< 1s`).

2. **Strict Mode & JSON Mode**:
   ```bash
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli verify --strict --json | .venv/bin/python -m json.tool
   ```
   - Must output valid JSON containing top-level `"proof"` and `"summary"`.
   - Must exit `0`.

3. **Full Automated Test Suite**:
   ```bash
   .venv/bin/pytest tests
   ```
   - All 229+ existing tests plus new verify tests must pass (0 failures).
