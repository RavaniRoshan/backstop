## 2026-09-18T10:16:41Z

You are the Worker for Milestone 1 (Phase 2) of Backstop Launch.
Your identity: teamwork_preview_worker_m1
Your working directory: /home/shiva/projects/backstop/.agents/worker_m1

MANDATORY FIRST STEP:
Read the authoritative user request at:
/home/shiva/projects/backstop/.agents/ORIGINAL_REQUEST.md
Also read the launch plan at:
/home/shiva/projects/backstop/PLAN.md (specifically §10 Phase 2: items 2.1, 2.2, 2.3)
and the reports from our 3 Explorers:
- /home/shiva/projects/backstop/.agents/explorer_m1_1/handoff.md (verify refactor)
- /home/shiva/projects/backstop/.agents/explorer_m1_2/handoff.md (demo command)
- /home/shiva/projects/backstop/.agents/explorer_m1_3/handoff.md (badges & tests)

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Scope & File Ownership:
You exclusively own and can modify/create:
- `src/backstop/verify.py`
- `src/backstop/demo.py` (new)
- `src/backstop/cli.py`
- `README.md` (specifically badge section lines 23-27)
- `tests/test_verify.py`
- `tests/test_demo.py` (new)
- `tests/test_cli.py` (new)

Detailed Requirements:
1. `backstop verify` refactor:
   - Make `_check_wrap()` and `_check_budget_block()` in `src/backstop/verify.py` exercise real `Backstop.wrap()` with a mock transport.
   - Run runaway agent loop (10 calls, 500 token budget) in `_check_budget_block`: 2 allowed, 8 blocked, surfaces `BudgetExceededError` inheriting from SDK error base (`OpenAIError` or `AnthropicError`).
   - Print compact, honest result markdown table at the top: allowed / blocked calls, tokens reserved (500), tokens saved (2,000), exception name (`BudgetExceededError`), wall-clock overhead.
   - Support `--strict` and `--json` (include proof metrics dict in json output).
   - Ensure 100% offline execution with zero API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` unset) in < 30s (expected < 1s).
2. `backstop demo` command:
   - Create `src/backstop/demo.py` and wire `demo` subcommand into `src/backstop/cli.py`.
   - Run side-by-side comparison:
     * Unprotected: 10 calls, full cost/tokens incurred.
     * Wrapped: 3 calls allowed, 7 blocked with `BudgetExceededError`.
   - Print clean, copy-pasteable Markdown table without ANSI noise.
   - Support `--strict` and `--json`.
   - Runs 100% offline with zero API keys in < 30s.
3. Status badges in `README.md`:
   - Remove `status-verified-green`.
   - Replace with live-backed CI status (`https://github.com/RavaniRoshan/backstop/actions/workflows/ci.yml/badge.svg`), license (`https://img.shields.io/github/license/RavaniRoshan/backstop`), and Python 3.10+ badges.
4. Testing & Verification:
   - Add/update tests in `tests/test_verify.py`, `tests/test_demo.py`, and `tests/test_cli.py`.
   - Run `pytest` locally and ensure 100% pass (229+ passed, 0 failed).
   - Run `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY .venv/bin/python -m backstop.cli verify` and `demo`.
   - Ensure ruff / lint clean.

Deliver your detailed report in `/home/shiva/projects/backstop/.agents/worker_m1/handoff.md` with build & test commands and results.
Send a message back to the orchestrator when finished.
