# Threat Model

Backstop's security promise is local-first LLM spend control. It should prevent runaway usage without requiring prompt payloads to pass through a Backstop-hosted proxy.

## Assets

- Provider API keys.
- Prompt and response payloads.
- Tenant identifiers and budget state.
- Cost, usage, latency, and reliability metrics.
- Policy configuration.

## Trust Boundaries

```text
Application process
  -> Backstop SDK transport
  -> official provider SDK HTTP transport
  -> provider API
```

In OSS local mode, Backstop code runs inside the application process. No Backstop-hosted service is required.

## Default Privacy Posture

- Provider API keys remain in the application environment.
- Prompt and response payloads are not sent to a Backstop service.
- Metrics should describe control-plane behavior and usage, not raw content.
- Hooks run in the application process and are controlled by the application owner.

## Risks

### Budget Bypass

If a service uses both wrapped and unwrapped SDK clients, unwrapped calls bypass Backstop.

Mitigation:

- Document wrapping at client construction boundaries.
- Add `backstop doctor` in a future phase to detect common misconfiguration.

### Metric Leakage

High-cardinality labels or raw user-provided strings can leak sensitive information.

Mitigation:

- Keep default metric labels limited to endpoint, priority, outcome, and safe operational dimensions.
- Document label hygiene for custom hooks and exporters.

### Provider SDK Drift

Provider SDK internals can change and break transport injection.

Mitigation:

- Maintain compatibility tests.
- Document supported SDK versions.
- Add real-provider smoke tests as opt-in checks.

### Distributed State Split-Brain

In local mode, replicated services enforce separate budgets.

Mitigation:

- Document local-mode limits.
- Add Redis-backed distributed state in Phase 1.

### Control Plane Outage

A future hosted control plane could become an availability dependency.

Mitigation:

- Make control-plane mode opt-in.
- Cache the last valid policy locally.
- Define explicit fail-open or fail-closed policy behavior.

## Non-Goals

- Backstop does not replace provider-side authentication.
- Backstop does not inspect or moderate prompt content by default.
- Backstop does not guarantee exact cost accounting when providers omit usage data.
- Backstop does not secure applications that keep unwrapped provider clients in production paths.
