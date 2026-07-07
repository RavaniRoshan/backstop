# Backstop Unicorn COSS Master Plan

## Summary

Backstop should evolve from a strong Python SDK guardrail into an open-core AI spend-control platform for AI SaaS teams. The open-source core remains the in-process data plane: low-latency SDK interception, token budgets, retries, circuit breaking, fallbacks, metrics, streaming, caching, and tenant context.

The commercial product becomes the control plane: shared policy, distributed budgets, audit trails, dashboards, enterprise support, and team governance.

Current repo baseline:

- OpenAI and Anthropic support exist.
- Local tests pass: `47 passed, 5 skipped`.
- Core technical wedge is real: in-process privacy, pre-flight budget enforcement, and no proxy hop.
- Major gaps are distributed state, benchmark proof, governance, contributor trust, enterprise pilots, and a durable commercial surface.

## Strategic Positioning

Primary wedge: AI SaaS teams with runaway LLM spend risk.

One-line promise:

> Drop-in SDK guardrails that prevent LLM cost overruns without routing prompts through a proxy.

Clear differentiation:

- In-process by default, so prompt payloads do not need to pass through a third-party proxy.
- Sub-millisecond local control-path target.
- Pre-flight budget enforcement, not just post-hoc observability.
- Optional shared control plane for teams that need distributed budgets and policy management.

## Roadmap Index

- [Phase 0: Trust And Proof](./backstop-unicorn-coss-2026-07-04.phase-0-trust-proof.md)
- [Phase 1: Enterprise Pilots](./backstop-unicorn-coss-2026-07-04.phase-1-enterprise-pilots.md)
- [Phase 2: Control Plane MVP](./backstop-unicorn-coss-2026-07-04.phase-2-control-plane-mvp.md)
- [Phase 3: Platform Expansion](./backstop-unicorn-coss-2026-07-04.phase-3-platform-expansion.md)
- [Metrics](./backstop-unicorn-coss-2026-07-04.metrics.md)
- [Assumptions](./backstop-unicorn-coss-2026-07-04.assumptions.md)
- [Tracking Log](./backstop-unicorn-coss-2026-07-04.tracking-log.md)

## Product Thesis

Backstop cannot become a billion-dollar company as a pure Python utility library. It can become a venture-scale COSS product if the open-source SDK becomes the trusted local data plane and the commercial product owns team-wide policy, budgets, auditability, and enterprise support.

The winning path is hybrid:

- OSS SDKs protect every request locally.
- Optional distributed state solves multi-replica enforcement.
- Paid control plane centralizes policy, governance, reporting, support, and compliance.

## Public Interface Direction

Keep local-only usage as the default:

```python
client = Backstop.wrap(OpenAI(), budget=50_000)
```

Add distributed and commercial capabilities as explicit opt-ins:

```python
client = Backstop.wrap(
    OpenAI(),
    config=BackstopConfig(
        service_name="api",
        environment="prod",
        state_backend=RedisStateBackend.from_url("redis://..."),
    ),
)
```

```python
client = Backstop.wrap(
    OpenAI(),
    config=BackstopConfig(
        service_name="api",
        environment="prod",
        policy_url="https://control.backstop.dev/policy",
        api_key=os.environ["BACKSTOP_API_KEY"],
    ),
)
```

Planned CLI additions:

- `backstop doctor`
- `backstop benchmark`
- `backstop sync-policy --dry-run`
- `backstop init-policy`

## Revenue Model

Do not treat PyPI extras as monetization. Use extras for adoption and packaging clarity.

Revenue should come from:

- Hosted control plane.
- Self-hosted enterprise control plane.
- SSO/SAML and RBAC.
- Audit exports and compliance reports.
- SLA-backed premium support.
- Private deployment support.
- Policy approval workflows.
- Enterprise integrations.
- Paid pilot programs.

## Execution Sequence

1. Prove trust: governance, docs, benchmark evidence, examples.
2. Prove enterprise fit: Redis state, OpenTelemetry, policy files, pilot collateral.
3. Prove monetization: hosted/self-hosted control plane and paid pilots.
4. Prove platform scale: TypeScript SDK, integrations, marketplace monitors, partner channels.

## Non-Goals For The First Year

- Do not build a full proxy gateway as the main product.
- Do not add five language SDKs before Python and TypeScript are validated.
- Do not collect prompt payloads by default.
- Do not monetize by crippling the OSS SDK.
- Do not chase generic observability against mature APM vendors without owning budget enforcement.
