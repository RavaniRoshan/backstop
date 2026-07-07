<div align="center">
  <p>
    <a href="README.md">README</a> •
    <a href="CODE_OF_CONDUCT.md">Code of Conduct</a>
  </p>
</div>

# Changelog

All notable changes to Backstop should be documented in this file.

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
