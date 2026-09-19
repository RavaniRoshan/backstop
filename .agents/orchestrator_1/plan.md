# Orchestrator Execution Plan: Backstop Launch Phases 2–5

## Context & Objectives
Complete the remaining phases of the 48-Hour Zero-to-One Launch Plan for Backstop (`/home/shiva/projects/backstop/PLAN.md`), fulfilling all acceptance criteria in `/home/shiva/projects/backstop/.agents/ORIGINAL_REQUEST.md`:
1. Phase 2: 30-Second Keyless Proof CLI Commands (`backstop verify`, `backstop demo`, real wrap, `--strict`, `--json`, offline, badge verification)
2. Phase 3: Repository Surface & Credibility (concise README <= 350 lines, no overclaims, documentation updates, zero 404 links, site drift check)
3. Phase 4: Frictionless Examples & Docs (`examples/agent_loop_guard.py`, `examples/anthropic_budget.py`, `examples/fastapi_tenant_budget.py`, `docs/quickstart.md`, `docs/sdk-matrix.md`)
4. Phase 5: Launch Distribution Assets & Packaging Verification (Show HN draft, secondary channels, packaging `python -m build` & `python -m twine check dist/*`)
5. Verification & Git Delivery: Full test suite passing 100% (229+ tests), offline CLI checks, PLAN.md dashboard/checkboxes/log updated, secret-free clean git commit & push to `main`, notify Sentinel.

## Milestones
| Milestone | Description | Dependencies | Status |
|---|---|---|---|
| M1: Phase 2 | 30-Second Proof CLI (`verify`, `demo`, table, strict, json, badges) | Phase 1 (Done) | IN_PROGRESS |
| M2: Phase 3 | Surface & Credibility (README rewrite <=350 lines, docs, no overclaims, site drift check) | M1 | PLANNED |
| M3: Phase 4 | Frictionless Keyless Examples & Docs (`examples/`, `docs/quickstart.md`, `docs/sdk-matrix.md`) | M2 | PLANNED |
| M4: Phase 5 & Delivery | Launch Assets, Packaging, Full Verification, Git Commit & Push to Main | M3 | PLANNED |

## Milestone 1 Breakdown (Phase 2)
1. **Explorer Investigation**: Inspect current implementation of `src/backstop/verify.py`, `src/backstop/cli.py`, existing demo / verify commands, mock transport usage, badge configurations. Formulate concrete implementation strategy.
2. **Worker Implementation**:
   - `backstop verify`: Exercise `Backstop.wrap()` with simulated runaway agent loop & tiny budget, catching `BudgetExceededError`. Print compact result table (allowed/blocked calls, tokens reserved, tokens saved, exception name, wall-clock overhead). Support `--strict` and `--json`. Ensure offline & zero API keys.
   - `backstop demo`: Implement offline side-by-side comparison command (unprotected vs wrapped), outputs stable markdown / table without ANSI noise.
   - Badges: replace hand-written status badges with live-backed badges.
   - Add/update automated tests in `tests/` verifying `backstop verify` and `backstop demo`.
3. **Reviewers**: 2 independent reviewers checking correctness, CLI options, offline execution, zero key requirement, test coverage.
4. **Challengers**: 2 challengers testing edge cases, strict exit codes, json format validity, time < 30s.
5. **Auditor**: Forensic integrity audit verifying no hardcoded outputs, genuine wrap enforcement.
6. **Gate Evaluation**: All must pass before advancing to M2.
