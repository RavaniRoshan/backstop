# Technical Exploration Report & Handoff: Milestone 1 (Phase 2) Badges & Automated Verification

**Author**: Explorer 3 (`teamwork_preview_explorer_m1_3`)  
**Target Recipient**: Orchestrator (`parent` / `0eff67c6-f66b-4f42-832c-d208d4bd1f55`)  
**Date**: 2026-09-18  
**Scope**: Status badges in `README.md`, automated verification suite in `tests/`, `backstop verify` & `backstop demo` test requirements.

---

## 1. Observation

### 1.1 Existing Badges in `README.md`
Inspecting `/home/shiva/projects/backstop/README.md` lines 23–27 reveals:
```html
<p>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License MIT" />
  <img src="https://img.shields.io/badge/status-verified-green" alt="Status: verified" />
</p>
```

Testing all badge URLs with `curl -sI` and content inspection yielded:
1. **`https://img.shields.io/badge/status-verified-green`**:
   - HTTP status: `200 OK` (Shields static badge endpoint always returns 200 for arbitrary labels).
   - SVG Content: `<title>status: verified</title>`.
   - Backed by live service: **NO**. It is a completely static, hand-written badge.
   - Policy violation: Violates `PLAN.md` §4 line 123 & line 183 ("Banned vocabulary: ... verified (as a status badge)"), and §10 task 2.3.1.
2. **`https://img.shields.io/badge/license-MIT-green`**:
   - HTTP status: `200 OK`.
   - SVG Content: `<title>license: MIT</title>`.
   - Backed by live service: **NO**. It is a static shields badge.
   - Live alternative: `https://img.shields.io/github/license/RavaniRoshan/backstop` returns `HTTP 200 OK` with `<title>license: MIT</title>`, backed by GitHub's API reading `LICENSE.txt`.
3. **CI Status Badge**:
   - Currently **missing** from `README.md`.
   - GitHub Actions workflow exists at `.github/workflows/ci.yml` (name: `CI`).
   - GitHub native badge URL: `https://github.com/RavaniRoshan/backstop/actions/workflows/ci.yml/badge.svg` returns `HTTP 200 OK` with SVG `<title>CI - passing</title>`.
   - Shields workflow URL: `https://img.shields.io/github/actions/workflow/status/RavaniRoshan/backstop/ci.yml?branch=main` returns `HTTP 200 OK` with SVG `<title>build: passing</title>`.
   - Backed by live service: **YES**. Live-backed by GitHub Actions on branch `main`.
4. **PyPI Version Badge**:
   - URL: `https://img.shields.io/pypi/v/backstop-ai`.
   - HTTP status: `200 OK` (Shields response).
   - SVG Content: `<title>pypi: package or version not found</title>` (renders a RED badge).
   - PyPI query: `https://pypi.org/pypi/backstop-ai/json` returns `HTTP 404 Not Found`.
   - Reason: Package `backstop-ai` has not yet been published to PyPI (Phase 5 task in `PLAN.md` §13 / tag release `v0.6.0`). Note: `backstop` on PyPI is an unrelated database package.
5. **Python Versions Badge**:
   - PyPI URL: `https://img.shields.io/pypi/pyversions/backstop-ai` returns `HTTP 200` with SVG `<title>python: package or version not found</title>` (red) due to unreleased package.
   - Static/GitHub URL: `https://img.shields.io/badge/python-3.10%2B-blue` returns `HTTP 200` with SVG `<title>python: 3.10+</title>`. `pyproject.toml:10` explicitly defines `requires-python = ">=3.10"`.

### 1.2 Test Suite Execution & Baseline
1. Executed full test suite with `pytest`:
   - Command: `pytest`
   - Result: `226 passed, 8 skipped in 48.46s` (0 failed, exit code 0).
   - Skips are live-provider tests requiring API keys or optional deep research dependencies.
2. Executed `backstop verify` offline:
   - Command: `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY python3 -m backstop.cli verify`
   - Result: Completed in **0.18 seconds** (well under 30s limit), exit code 0, 8 checks passed:
     `config valid`, `wrap pipeline`, `budget block`, `overhead`, `cache hit`, `per-agent isolation`, `hierarchical budgets`, `shadow mode`.
   - `python3 -m backstop.cli verify --json`: Emits structured JSON summary and checks list in 0.12s.
3. Executed `backstop demo`:
   - Command: `python3 -m backstop.cli demo`
   - Result: `backstop: error: argument command: invalid choice: 'demo' (choose from 'harness', 'benchmark', 'doctor', 'serve', 'metrics', 'dashboard', 'verify', 'real-openai', 'real-anthropic')` (exit code 2).
   - Finding: `demo` subcommand is completely unimplemented in `src/backstop/cli.py`.
4. CLI Test Coverage in `tests/`:
   - Grep search for `backstop.cli` in `tests/` returned 0 matches.
   - No `test_cli.py` exists.
   - `tests/test_verify.py` only invokes `VerifyRunner` and `run_verify()`, never `backstop.cli.main()`.

### 1.3 Offline `Backstop.wrap` Mechanics
Executed offline loop test using `openai.OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(handler)))` and `Backstop.wrap(raw_client, budget=40)`:
```
Call 0: allowed
Call 1: allowed
Call 2: blocked with BudgetExceededError: request estimate 21 tokens exceeds remaining budget 10
Call 3: blocked with BudgetExceededError: request estimate 21 tokens exceeds remaining budget 10
Call 4: blocked with BudgetExceededError: request estimate 21 tokens exceeds remaining budget 10
Allowed: 2, Blocked: 3
```
- Real wrap path works completely offline without API keys or external network.
- `BudgetExceededError` surfaces directly from the client method invocation.

---

## 2. Logic Chain

1. **Badge Remediation**:
   - `status-verified-green` is explicitly prohibited by `PLAN.md` §4 line 183 and §10 task 2.3.1. It must be excised.
   - Both the GitHub Actions CI badge (`https://github.com/RavaniRoshan/backstop/actions/workflows/ci.yml/badge.svg`) and the GitHub License badge (`https://img.shields.io/github/license/RavaniRoshan/backstop`) return HTTP 200 and reflect genuine live repository state.
   - PyPI version badge (`https://img.shields.io/pypi/v/backstop-ai`) currently renders "package or version not found" because release happens in Phase 5. Per `PLAN.md` §10 task 2.3.2 ("Delete any badge that cannot be backed by a live service"), displaying a red broken badge in the README now undermines repo credibility. The PyPI badge should either be deferred until Phase 5 publish, or the README should use the live GitHub release/tag badge (`https://img.shields.io/github/v/tag/RavaniRoshan/backstop`) alongside Python `3.10+` and CI.
2. **`backstop verify` Enhancement**:
   - `src/backstop/verify.py` currently constructs a raw `httpx.Client` with `BackstopTransport`. It does not exercise `Backstop.wrap()` on an SDK client.
   - To satisfy `PLAN.md` §10 task 2.1.2, `_check_wrap()` must wrap a real SDK client (`openai.OpenAI` or `anthropic.Anthropic` using mock transport) and verify that runaway loop calls catch `BudgetExceededError`.
   - To satisfy §10 task 2.1.3, the output must present a compact result table containing: allowed calls, blocked calls, tokens reserved, tokens saved, exception name, and wall-clock overhead.
3. **`backstop demo` Implementation**:
   - Subcommand `demo` must be added to `src/backstop/cli.py`.
   - It must execute two sequential loops:
     - Unprotected loop: N calls executed with simulated token burn.
     - Wrapped loop: N calls executed through `Backstop.wrap()` with a tight budget, blocking at call 3 and raising `BudgetExceededError`.
   - Output must be rendered as a clean, copy-pasteable Markdown table without ANSI escape sequences.
4. **Automated Test Architecture**:
   - A dedicated `tests/test_cli.py` must be introduced to test `backstop.cli.main()` with `argv`.
   - In-process invocation via `main(argv)` with `capsys` fixture enables sub-second test execution.
   - A companion subprocess test ensures entry-point integrity in a stripped environment (`env -u ...`).

---

## 3. Caveats

1. **PyPI Badge Availability**: `backstop-ai` will only return HTTP 200 with valid version metadata once published to PyPI in Phase 5. Until then, any live badge querying PyPI will display "not found".
2. **Overhead Thresholds on Shared CI**: `_check_overhead()` measures control-path latency and warns if p99 exceeds 5.0ms. In `--strict` mode, high load on a CI runner could trigger a warning and exit with code 1. The test suite should account for this when running `--strict` tests.
3. **No Source Modifications Made**: In accordance with the Explorer role constraints, no source files were modified during this investigation.

---

## 4. Conclusion

### 4.1 Recommended Badges for `README.md`
Replace lines 23–27 in `README.md` with:

```html
<p>
  <a href="https://github.com/RavaniRoshan/backstop/actions/workflows/ci.yml">
    <img src="https://github.com/RavaniRoshan/backstop/actions/workflows/ci.yml/badge.svg" alt="CI Status" />
  </a>
  <a href="https://github.com/RavaniRoshan/backstop/blob/main/LICENSE.txt">
    <img src="https://img.shields.io/github/license/RavaniRoshan/backstop" alt="License: MIT" />
  </a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+" />
  <!-- PyPI badge activated upon Phase 5 release:
  <a href="https://pypi.org/project/backstop-ai/">
    <img src="https://img.shields.io/pypi/v/backstop-ai" alt="PyPI version" />
  </a>
  -->
</p>
```

### 4.2 Required Test Cases for `tests/test_cli.py` and `tests/test_verify.py`

#### A. `backstop verify` Test Cases
1. `test_cli_verify_default_offline(capsys)`:
   - Run `main(["verify"])`.
   - Assert exit code is 0.
   - Assert stdout contains the hero result table (allowed, blocked, tokens reserved, tokens saved, `BudgetExceededError`, overhead).
   - Assert output contains zero unmasked secrets.
2. `test_cli_verify_strict_mode(capsys, monkeypatch)`:
   - Run `main(["verify", "--strict"])` when all pass -> exits 0.
   - Monkeypatch one check to return `status="warn"` -> assert exit code is 1.
3. `test_cli_verify_json_output(capsys)`:
   - Run `main(["verify", "--json"])`.
   - Parse `json.loads(capsys.readouterr().out)`.
   - Validate schema: contains `summary` (`passed`, `warnings`, `failed`, `skipped`, `exit_code`) and `checks` list with dicts.
4. `test_cli_verify_zero_keys_env(monkeypatch)`:
   - Remove `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc. from `os.environ`.
   - Run `main(["verify"])` -> exits 0.
5. `test_verify_real_wrap_path()`:
   - Directly verify `_check_wrap()` in `VerifyRunner` exercises `Backstop.wrap(client, budget=...)` on an SDK client and catches `BudgetExceededError`.
6. `test_verify_error_handling(monkeypatch)`:
   - Monkeypatch a check function to raise an unhandled `RuntimeError`.
   - Verify runner catches the error defensively, marks check as `fail`, does not crash, and returns exit code 1.

#### B. `backstop demo` Test Cases
1. `test_cli_demo_offline_execution(capsys)`:
   - Run `main(["demo"])`.
   - Assert exit code is 0.
   - Assert stdout contains markdown table showing side-by-side comparison:
     - Unprotected: N calls allowed, 0 blocked, full token burn.
     - Wrapped: capped calls allowed, remainder blocked by `BudgetExceededError`, tokens saved.
2. `test_cli_demo_no_ansi_noise(capsys)`:
   - Run `main(["demo"])`.
   - Assert stdout contains no raw ANSI escape sequences (`\x1b[`).
   - Assert markdown table is copy-pasteable.
3. `test_cli_demo_zero_keys_env(monkeypatch)`:
   - Run in clean environment with unset provider keys -> exits 0.
4. `test_cli_demo_json_output(capsys)`:
   - If `--json` flag is supported on `demo`, assert valid JSON output with metrics delta.

---

## 5. Verification Method

### 5.1 Test Execution Commands
```bash
# 1. Run specific CLI and verification test modules
pytest tests/test_verify.py tests/test_cli.py -v

# 2. Run full test suite
pytest

# 3. Test CLI commands with unset API keys
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY python3 -m backstop.cli verify
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY python3 -m backstop.cli verify --strict
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY python3 -m backstop.cli verify --json
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY python3 -m backstop.cli demo

# 4. Verify badge URLs return HTTP 200
curl -sI "https://github.com/RavaniRoshan/backstop/actions/workflows/ci.yml/badge.svg" | grep "HTTP"
curl -sI "https://img.shields.io/github/license/RavaniRoshan/backstop" | grep "HTTP"
curl -sI "https://img.shields.io/badge/python-3.10%2B-blue" | grep "HTTP"
```

### 5.2 Invalidation Conditions
- Any check in `backstop verify` requiring an external network connection or live API key.
- `backstop demo` emitting terminal ANSI formatting that breaks Markdown rendering.
- `README.md` retaining `status-verified-green` or any badge returning non-200.
- `pytest` failing any existing tests (226 baseline tests must continue passing).
