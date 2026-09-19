# BRIEFING — 2026-09-18T10:05:00Z

## Mission
Investigate and design the offline `backstop demo` command for Phase 2 of Backstop launch.

## 🔒 My Identity
- Archetype: explorer
- Roles: investigation, synthesis
- Working directory: /home/shiva/projects/backstop/.agents/explorer_m1_2
- Original parent: 0eff67c6-f66b-4f42-832c-d208d4bd1f55
- Milestone: Milestone 1 (Phase 2) - backstop demo command

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Must run 100% offline with zero API keys and finish in < 30 seconds
- No secrets committed
- Backstop is transport-layer, protocol-agnostic, NOT an MCP tool

## Current Parent
- Conversation ID: 0eff67c6-f66b-4f42-832c-d208d4bd1f55
- Updated: 2026-09-18T09:48:00Z

## Investigation State
- **Explored paths**:
  - `src/backstop/cli.py` (CLI argument parsing and command dispatch)
  - `src/backstop/verify.py` (offline verification runner)
  - `src/backstop/wrapper.py` (`Backstop.wrap` and client cloning)
  - `src/backstop/_httpcompat.py` (transport compatibility detection)
  - `src/backstop/pricing.py` (cost estimation and model pricing tables)
  - `src/backstop/budget.py` (budget reservation and reconciliation)
  - `src/backstop/dashboard_demo.py` & `examples/budget_blocking_demo.py` (existing demo infrastructure)
  - `tests/test_verify.py` & `tests/test_wrapper.py` (mock transport test patterns)
- **Key findings**:
  - `backstop demo` does not exist yet in `cli.py` (CLI error on `backstop demo`).
  - Tested `Backstop.wrap` with mock transport and `budget=75`: 3 calls succeed, call 4 blocked with `BudgetExceededError`.
  - Both `openai` (3.14.0) and `anthropic` (1.5.0) are installed and use `httpx2`.
  - `_httpcompat.compat_for` handles transport family matching automatically.
  - Runtime for 10 mock calls is ~20ms, fulfilling the < 30s requirement.
  - Zero API keys needed when passing mock transport and placeholder key.
  - Test suite currently passes (229 passed, 5 skipped).
- **Unexplored areas**: None for this phase. Full design specifications completed.

## Key Decisions Made
- `backstop demo` should be implemented in `src/backstop/demo.py` and dispatched from `src/backstop/cli.py`.
- Runaway loop scenario runs 10 iterations: unprotected vs wrapped with `budget=75` (or configurable).
- Markdown table formatting is clean without ANSI color codes for copy-pasting into `README.md`.
- Options: `--calls`, `--budget`, `--provider`, `--model`, `--json`, `--strict`.

## Artifact Index
- DISPATCH.md — Raw dispatch log
- BRIEFING.md — Working memory
- progress.md — Progress and liveness tracker
- handoff.md — 5-component technical exploration report
