# Backstop Architecture

Backstop is an in-process control layer for official LLM provider SDKs. It wraps supported SDK clients and injects an `httpx` transport that enforces budgets, admission control, retry policy, circuit breaking, caching, and metrics before and after provider calls.

## Request Flow

```text
Application code
  -> official OpenAI or Anthropic SDK client
  -> Backstop transport
  -> request metadata extraction
  -> cache check
  -> budget reservation
  -> priority admission gate
  -> circuit breaker check
  -> retry loop and AIMD pressure handling
  -> provider SDK HTTP transport
  -> response usage extraction
  -> budget reconciliation
  -> metrics and latency metadata
  -> application code
```

## Local Mode

Local mode is the default. Budget, circuit, queue, cache, and AIMD state live in the application process.

This is best for:

- Single-process apps.
- Development and CI.
- Small services where per-process budgets are acceptable.
- Teams that want prompt privacy without operating extra infrastructure.

Limitations:

- Multiple service replicas do not share budget state.
- Per-process circuit state can differ across containers.
- Enterprise-wide policy must be configured in each application.

## Tenant Budgets

Tenant budgets use a context variable:

```python
from backstop import TenantBudget, budgets, with_budget

budgets.register({
    "tenant_123": TenantBudget("tenant_123", limit_tokens=50_000),
})

with with_budget("tenant_123"):
    client.chat.completions.create(...)
```

Tenant budgets are currently in-process. Distributed tenant enforcement is a planned enterprise-pilot milestone.

## Streaming

Backstop detects streaming requests and wraps response streams so budget reconciliation can happen when the stream completes. Streaming usage extraction depends on provider response shape and may fall back to estimates when final usage is unavailable.

## Metrics

Prometheus metrics are optional through `backstop[metrics]`.

Metrics cover:

- request count
- request duration
- queue wait
- queue depth
- active concurrency
- AIMD limit
- remaining budget
- circuit state
- retries
- cache hits
- tenant budget blocks

Avoid adding prompt text, raw response content, API keys, or user identifiers as metric labels.

## Control Plane Direction

Backstop's long-term commercial architecture should keep this local transport as the data plane and add an optional control plane for:

- shared policy
- distributed budgets
- team governance
- audit logs
- dashboards
- alerting
- enterprise support

The local SDK path must remain useful without the control plane.
