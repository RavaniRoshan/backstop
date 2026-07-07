# Phase 2: Control Plane MVP

## Objective

Convert Backstop from an OSS library into a paid hybrid SaaS product.

Time window: 90 to 180 days.

## Why This Phase Matters

The control plane is the monetizable product. It should centralize policy, reporting, distributed budgets, alerts, and team governance while preserving Backstop's local in-process request path.

## Workstreams

### Agent Policy Sync

- Add `policy_url`, `api_key`, `service_name`, and `environment` config fields.
- Fetch signed policy bundles from the control plane.
- Cache the last valid policy locally.
- Continue operating with the last valid policy during control-plane outages.
- Add `backstop sync-policy --dry-run`.

### Hosted Dashboard

- Build views for:
  - orgs, projects, services, and environments
  - tenant budgets
  - cost over time
  - provider and model breakdown
  - fallback events
  - budget blocks
  - retry and circuit events
  - queue latency
  - cache savings

### Policy Management

- Let admins configure:
  - model allowlists
  - fallback chains
  - tenant budgets
  - per-environment defaults
  - retry and circuit thresholds
  - alert thresholds
- Require policy versioning and audit history.
- Support staged rollout by environment.

### Alerts

- Add Slack and webhook alerts for:
  - budget exhaustion
  - forecasted budget exhaustion
  - high fallback rate
  - provider degradation
  - circuit open state
  - unexpected model usage

### Enterprise Basics

- Add team accounts.
- Add API keys scoped by org/project/environment.
- Add RBAC foundation.
- Add audit logs.
- Add CSV export for usage and budget events.
- Prepare SSO/SAML as paid enterprise capability.

## Deliverables

- Hosted control plane MVP.
- Signed policy bundle format.
- SDK policy sync.
- Dashboard for spend, latency, fallbacks, and budget blocks.
- Slack/webhook alerts.
- Paid pilot package with support SLA.

## Acceptance Criteria

- SDK works if the control plane is temporarily unavailable.
- Policy updates propagate to SDKs without application redeploy.
- Dashboard can answer: who spent money, on which models, in which environment, and what Backstop prevented.
- Paid pilot customers can enforce budgets across multiple services.
- Prompt payload collection remains off by default.

## Success Metrics

- 10 active pilots.
- 3 paid customers.
- $10k to $25k MRR.
- 2 integration partners or design partners.
- 1 external security review or serious security design review.
- At least 30 days of production telemetry from one pilot.

## Risks

- Building a SaaS too early can outpace OSS trust.
- Policy sync can introduce operational risk if failure behavior is unclear.
- Customers may request full observability features that dilute spend-control focus.

## Exit Gate

Move to Phase 3 only after paid pilots prove that customers will pay for centralized policy, distributed budgets, auditability, and support.
