# Phase 1: Enterprise Pilots

## Objective

Make Backstop usable by real AI SaaS teams running multiple service replicas in production.

Time window: 30 to 90 days.

## Why This Phase Matters

The main technical blocker from the commercial report is distributed state. Local budgets are useful for single-process apps, but enterprise services run across containers, workers, and regions. Backstop needs a shared enforcement mode while preserving its local-first architecture.

## Workstreams

### Distributed State

- Add a state backend interface for budgets, concurrency, rate pressure, and circuit state.
- Implement Redis-backed tenant budgets as the first shared backend.
- Support atomic reserve, commit, release, and budget-expiry operations.
- Keep in-memory state as the default backend.
- Document failure behavior when Redis is unreachable.

### Policy Files

- Add YAML or JSON policy files for:
  - tenant budgets
  - model allowlists
  - fallback rules
  - default priorities
  - retry and circuit settings
- Add `backstop init-policy`.
- Add `backstop validate-policy`.
- Support local file loading before any hosted control plane exists.

### OpenTelemetry

- Add `backstop[otel]`.
- Emit spans and metrics for request lifecycle, queue wait, budget decision, retry, fallback, circuit state, and cache hits.
- Do not emit prompt payloads by default.
- Add resource attributes for service name, environment, provider, endpoint, and model.

### Dashboards And Alerts

- Add Grafana dashboard JSON for Prometheus metrics.
- Add alert examples for:
  - budget exhaustion
  - provider error spikes
  - circuit open events
  - high queue wait
  - high fallback rate

### Pilot Package

- Create a pilot onboarding doc.
- Create an LLM spend incident review worksheet.
- Create a one-page security overview.
- Create a migration guide from direct OpenAI or Anthropic SDK usage.

## Deliverables

- Redis state backend.
- Policy file loader and validator.
- OpenTelemetry export.
- Grafana dashboard.
- Pilot onboarding package.
- Compatibility matrix updated with distributed-mode behavior.

## Acceptance Criteria

- Multiple worker processes share the same tenant budget correctly.
- Budget reserve and commit are atomic under concurrency.
- Redis outage behavior is explicit and test-covered.
- OpenTelemetry export works without prompt payloads.
- A pilot customer can deploy local mode first and enable Redis mode later.

## Success Metrics

- 500 GitHub stars.
- 3 active design partners.
- 1 public case study or anonymized pilot report.
- 10+ external issues or discussions.
- Redis-mode budget accuracy verified under concurrent load.
- Documented local p95 overhead and Redis-mode p95 overhead.

## Risks

- Redis can weaken the "zero infrastructure" story if positioned poorly.
- Distributed circuit and concurrency semantics can become too complex.
- Enterprise pilots may ask for custom features that distract from the core wedge.

## Exit Gate

Move to Phase 2 only when at least three design partners validate that shared budgets, policy files, and telemetry are enough to justify a paid control plane.
