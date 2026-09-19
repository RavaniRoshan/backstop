# Handoff Report: `backstop demo` Command Architecture & Design

**Author**: Explorer 2 (`teamwork_preview_explorer_m1_2`)  
**Task**: Milestone 1 (Phase 2) — Technical Exploration for `backstop demo`  
**Date**: 2026-09-18T10:05:00Z  

---

## 1. Observation

### 1.1 Existing CLI Architecture in `src/backstop/cli.py`
- Direct inspection of `src/backstop/cli.py` (lines 273–515) shows the following subcommands currently registered in `argparse`:
  - `harness` (dispatches to `run_harness` in `src/backstop/harness.py`)
  - `benchmark` (dispatches to `_run_benchmark`)
  - `doctor` (dispatches to `_run_doctor`)
  - `serve` (dispatches to `make_gateway_app` in `src/backstop/gateway.py`)
  - `metrics` (dispatches to `start_metrics_server`)
  - `dashboard` (serves web UI with optional `--demo` flag invoking `DemoWorkload` in `src/backstop/dashboard_demo.py`)
  - `verify` (dispatches to `run_verify` in `src/backstop/verify.py`)
  - `real-openai` (dispatches to `run_real_openai_smoke` in `src/backstop/real_openai.py`)
  - `real-anthropic` (dispatches to `run_real_anthropic_smoke` in `src/backstop/real_anthropic.py`)
- Running `.venv/bin/python -m backstop.cli demo` produces:
  ```
  backstop: error: argument command: invalid choice: 'demo' (choose from 'harness', 'benchmark', 'doctor', 'serve', 'metrics', 'dashboard', 'verify', 'real-openai', 'real-anthropic')
  ```
- **Conclusion**: There is currently NO `backstop demo` command in `src/backstop/cli.py`.

### 1.2 Existing Demo Artifacts in Repo
- `src/backstop/dashboard_demo.py`: Implements `DemoWorkload` for the web UI dashboard (`backstop dashboard --demo`). It drives synthetic traffic across 3 runners, but does not provide a CLI runaway loop comparison or print a markdown delta table.
- `examples/budget_blocking_demo.py`: A basic script demonstrating an `httpx.Client` wrapped with `BackstopTransport`, executing 10 requests against a mock provider with budget 75 tokens. It does not run side-by-side comparison, does not exercise real SDK clients (`OpenAI` / `Anthropic`), does not calculate cost or savings deltas, and is not a CLI command.

### 1.3 Python Environment and Dependencies
- Verified active environment via `.venv/bin/python`:
  - Python: 3.12
  - `openai`: 3.14.0 (satisfies `openai>=2.37,<4`)
  - `anthropic`: 1.5.0 (satisfies `anthropic>=0.98,<2`)
  - `httpx`: 0.28.1
  - `httpx2`: 2.13.0
- Baseline test suite status: `pytest tests` passes with `229 passed, 5 skipped in 47.94s`.

### 1.4 Mock Transport & Real Client Wrapping Prototyping
- When wrapping real SDK clients with a mock transport:
  ```python
  probe = openai.OpenAI(api_key="mock-key")
  compat = compat_for(probe._client)
  mock_transport = compat.MockTransport(handler)
  http_client = compat.Client(transport=mock_transport)
  client = openai.OpenAI(api_key="mock-key", http_client=http_client)
  wrapped = Backstop.wrap(client, budget=75, config=BackstopConfig(default_max_output_tokens=10, retry_max_attempts=1))
  ```
- Preflight estimation calculation:
  - Prompt: 15 tokens (`~60` characters).
  - Output tokens: `default_max_output_tokens = 10` (or `max_tokens = 10` in call body).
  - Reservation per call: `~21` tokens.
  - Actual tokens settled on response: `15` prompt + `10` completion = `25` tokens.
- Execution outcome with `budget = 75` across 10 iterations:
  - Call 1: Success (consumes 25 tokens, remaining: 50).
  - Call 2: Success (consumes 25 tokens, remaining: 25).
  - Call 3: Success (consumes 25 tokens, remaining: 0).
  - Call 4: Preflight check fails (`request estimate 21 tokens exceeds remaining budget 0`), raises `BudgetExceededError`.
  - Calls 5–10: Caught and blocked before transport.
  - Result: Exactly 3 calls completed, 7 calls blocked in-process. Provider HTTP call counter received only 3 requests.
- Runtime: ~0.02 seconds (well below the 30-second budget requirement).

---

## 2. Logic Chain

1. **Mission Requirement Alignment**:
   - `PLAN.md` §10 Phase 2 item 2.2 requires `backstop demo` to:
     1. Run the same runaway loop twice (unprotected vs wrapped).
     2. Show "N calls issued, full cost incurred" vs "3 calls, then blocked with `BudgetExceededError`".
     3. Print the side-by-side delta.
     4. Produce copy-pasteable clean markdown output without ANSI noise.
     5. Run 100% offline with zero API keys in < 30 seconds.
2. **Architectural Separation**:
   - Following Backstop's modular design (`verify.py`, `harness.py`, `real_openai.py`), all simulation, delta calculations, and formatting logic should be isolated in `src/backstop/demo.py`.
   - `src/backstop/cli.py` should only be responsible for argument parsing and delegating to `src/backstop/demo.py:run_demo()`.
3. **Transport Layer Integrity**:
   - Both `openai` and `anthropic` clients can be configured with a local mock `http_client` using `_httpcompat.compat_for(...)`.
   - In the **unprotected loop**, `client.chat.completions.create(...)` executes directly through the mock transport. All $N$ calls hit the provider mock, consuming tokens and incurring simulated cost.
   - In the **wrapped loop**, `Backstop.wrap(client, budget=75, config=BackstopConfig(default_max_output_tokens=10))` wraps the transport. The first 3 calls proceed and are reconciled; the 4th call is stopped by `BudgetExceededError`. The remaining $N-3$ calls are intercepted in-process before sending any HTTP request.
   - This directly proves the core value proposition: **"In-process guardrail that intercepts runaway calls before they incur provider costs or network hops."**
4. **Deterministic Delta Accounting**:
   - Total Calls Attempted: $N$ (e.g., 10)
   - Unprotected: 10 completed, 0 blocked, 250 tokens consumed, 10 HTTP requests.
   - Wrapped: 3 completed, 7 blocked, 75 tokens consumed, 3 HTTP requests.
   - Delta / Savings: -7 calls (-70.0%), -175 tokens (-70.0%), -$X cost (-70.0%), 7 calls blocked before network.
5. **Formatting and Output Stability**:
   - Output must be stable ASCII / UTF-8 Markdown using GitHub-compatible pipe tables.
   - No color codes (`\x1b[...]`) or terminal-specific formatting that would corrupt copy-pasted blocks in `README.md`.
   - Provide a `--json` flag producing a structured JSON payload for programmatic evaluation and CI assertions.
   - Provide a `--strict` flag that exits with code 0 on successful guardrail enforcement and code 1 if the guardrail fails to block.

---

## 3. Caveats

1. **SDK Dependency Variations**:
   - `openai` is a mandatory dependency in `pyproject.toml`, but `anthropic` is in `[project.optional-dependencies]`.
   - If `--provider anthropic` is invoked without `anthropic` installed, `demo.py` must return an informative error message (`pip install "backstop-ai[anthropic]"`) and exit with code 1 rather than raising an unhandled `ImportError`.
2. **Preflight Reservation Sizing**:
   - Backstop's `BackstopTransport` reserves `meta.estimated_tokens` *before* the request is made. If `default_max_output_tokens` is left at its default (1024), preflight reservation will attempt to reserve ~1025 tokens per request.
   - To achieve the exact "3 calls, then blocked" target with a compact token budget (e.g., 75 tokens), `BackstopConfig(default_max_output_tokens=10)` and `max_tokens=10` must be specified in the simulation.
3. **HTTP Client Resource Cleanup**:
   - Client instances (`client._client.close()`) must be closed in `finally:` blocks to prevent `ResourceWarning` / unclosed transport warnings during automated test runs.
4. **Shadow Mode / Global State**:
   - `BackstopState.create()` creates an independent, isolated in-process budget and circuit breaker. The demo must use an isolated state so that repeated runs or concurrent tests do not interfere with each other.

---

## 4. Conclusion & Concrete Design Proposal

### 4.1 Module: `src/backstop/demo.py`

#### Proposed Dataclasses & Interface:
```python
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from ._httpcompat import compat_for
from .config import BackstopConfig
from .exceptions import BudgetExceededError
from .pricing import Pricing
from .wrapper import Backstop


@dataclass
class LoopMetrics:
    calls_attempted: int
    calls_completed: int
    calls_blocked: int
    tokens_consumed: int
    tokens_saved: int
    cost_usd: float
    provider_calls: int
    exception_name: str | None
    duration_ms: float


@dataclass
class DemoResult:
    scenario: str
    provider: str
    model: str
    budget: int
    total_calls: int
    unprotected: LoopMetrics
    wrapped: LoopMetrics
    delta_calls_saved: int
    delta_tokens_saved: int
    delta_cost_saved_usd: float
    savings_pct: float
    guardrail_enforced: bool
    success: bool
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_markdown(self) -> str:
        # Returns clean Markdown table formatted without ANSI noise
        ...
```

#### Markdown Output Template:
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
| Estimated cost | $0.000082 | $0.000025 | -$0.000057 (-70.0%) |
| Guardrail exception | None | BudgetExceededError | 7 calls blocked |
| Provider HTTP calls | 10 | 3 | -7 calls prevented |
| Total runtime | 1.8 ms | 1.1 ms | -0.7 ms |
```

### 4.2 Wiring into `src/backstop/cli.py`

1. **Parser definition in `main(argv)`**:
   ```python
   demo = subparsers.add_parser(
       "demo", help="run a side-by-side comparison of an unprotected vs wrapped runaway loop"
   )
   demo.add_argument("--calls", type=int, default=10, help="number of loop iterations to simulate (default: 10)")
   demo.add_argument("--budget", type=int, default=75, help="token budget for the wrapped client (default: 75)")
   demo.add_argument("--provider", choices=["openai", "anthropic"], default="openai", help="client SDK to simulate (default: openai)")
   demo.add_argument("--model", default=None, help="model identifier for pricing and requests")
   demo.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
   demo.add_argument("--strict", action="store_true", help="exit non-zero if the guardrail fails to block")
   ```

2. **Command execution dispatch**:
   ```python
   if args.command == "demo":
       from .demo import run_demo

       result = run_demo(
           calls=args.calls,
           budget=args.budget,
           provider=args.provider,
           model=args.model,
           strict=args.strict,
       )
       if args.json:
           print(result.to_json())
       else:
           print(result.to_markdown())
       return 0 if (result.success or not args.strict) else 1
   ```

### 4.3 Automated Test Coverage (`tests/test_demo.py`)

Worker should create `tests/test_demo.py` with tests covering:
1. `test_demo_offline_openai`: Validates default offline demo execution with OpenAI client (10 calls, 3 completed, 7 blocked, `BudgetExceededError`).
2. `test_demo_offline_anthropic`: Validates offline demo execution with Anthropic client.
3. `test_demo_markdown_formatting`: Verifies table structure, headers, pipes, right-aligned numeric columns, and absence of ANSI escape codes (`\x1b[`).
4. `test_demo_json_output`: Validates JSON schema, serializability, and field consistency.
5. `test_demo_cli_invocation`: Tests CLI execution via `backstop.cli.main(["demo"])`, `main(["demo", "--json"])`, and `main(["demo", "--strict"])`.
6. `test_demo_strict_failure`: Asserts non-zero exit code if guardrail enforcement does not block runaway calls.

---

## 5. Verification Method

Downstream roles (Worker, Reviewer, Challenger, Auditor) can verify the implementation using these exact commands:

1. **Zero-Key Offline Execution Verification**:
   ```bash
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli demo
   ```
   *Expected*: Prints clean markdown table, finishes in < 0.5s, exit code 0.

2. **JSON Output Verification**:
   ```bash
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli demo --json | python -m json.tool
   ```
   *Expected*: Valid JSON with `unprotected`, `wrapped`, and `delta` keys.

3. **Strict Mode CI Verification**:
   ```bash
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli demo --strict
   ```
   *Expected*: Exit code 0 when guardrail blocks over-budget calls.

4. **Anthropic Provider Verification**:
   ```bash
   env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli demo --provider anthropic
   ```
   *Expected*: Executes clean side-by-side comparison using Anthropic SDK, exit code 0.

5. **Automated Unit Tests**:
   ```bash
   .venv/bin/pytest tests/test_demo.py -v
   ```
   *Expected*: All unit tests pass.

6. **Regression Suite**:
   ```bash
   .venv/bin/pytest tests
   ```
   *Expected*: 235+ passed, 0 failed.

7. **Invalidation Conditions**:
   - Any network call attempted during `demo` (must be 100% mock transport).
   - Any dependency on `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.
   - ANSI escape characters present in `--markdown` output.
   - Execution time $\ge 30$ seconds.
   - Wrapped client failing to raise `BudgetExceededError`.
