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

The optional gateway mode changes this shape. `backstop serve` is a process of
itself: clients send request bodies to it, and it forwards them upstream. In
that mode the Backstop process does see payloads and does hold whichever
upstream credential it was configured with, so it becomes a component in your
trust boundary rather than a library inside yours. See
[docs/architecture.md](architecture.md#optional-gateway--sidecar-mode).

## Default Privacy Posture

- Provider API keys remain in the application environment, or in whatever
  process runs `backstop serve` if you use the gateway.
- Prompt and response payloads are not sent to a Backstop service. There is no
  Backstop service. In gateway mode they transit the gateway process you
  operate, which is a different statement.
- Metrics should describe control-plane behavior and usage, not raw content.
- Hooks run in the application process and are controlled by the application owner.

## Risks

### Budget Bypass

If a service uses both wrapped and unwrapped SDK clients, unwrapped calls bypass Backstop.

Mitigation:

- Document wrapping at client construction boundaries.
- `backstop doctor` exists and reports SDK versions and wrap status, but it does
  **not** scan your codebase for unwrapped clients. It cannot detect this
  misconfiguration today. Wrapping discipline is on the application.

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
- Redis-backed distributed state shipped in the `redis` extra: set
  `BackstopConfig(shared_budget=True, redis_url=...)` and the token budget is
  reserved and committed through Redis rather than process memory. It is
  optional and off by default. Note that CI does not install the `redis` extra,
  so that path has no automated coverage.

### Control Plane Outage

A future hosted control plane could become an availability dependency. There is
no control plane today, so this is a design constraint on hypothetical future
work, not a current risk.

Mitigation:

- Make control-plane mode opt-in.
- Cache the last valid policy locally.
- Define explicit fail-open or fail-closed policy behavior.

## Non-Goals

- Backstop does not replace provider-side authentication.
- Backstop does not inspect or moderate prompt content by default.
- Backstop does not guarantee exact cost accounting when providers omit usage data.
- Backstop does not secure applications that keep unwrapped provider clients in production paths.
