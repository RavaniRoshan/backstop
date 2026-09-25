# Backstop Architecture

Backstop is an in-process control layer for official LLM provider SDKs. It wraps supported SDK clients and injects an HTTP transport — `httpx` or `httpx2`, whichever the wrapped client itself uses — that enforces budgets, admission control, retry policy, circuit breaking, caching, and metrics before and after provider calls.

The two HTTP families expose the same transport API but their objects are
mutually incompatible: an SDK rejects an `http` client built from the other
module. `src/backstop/_httpcompat.py` picks the module from the wrapped
client's own internal HTTP client, so the choice always matches the SDK in
front of us. `openai>=3` and `anthropic>=1` moved to `httpx2`; older majors use
`httpx`. No configuration is needed.

## Retries are Backstop's, not the SDK's

Wrapping sets the wrapped client to `max_retries=0` and performs the retries
inside `BackstopTransport`, with Backstop's own backoff schedule and circuit
state (`src/backstop/wrapper.py`, `src/backstop/transports.py`). The guardrail
has to see and be able to stop each individual attempt, which it cannot do if
the SDK is retrying underneath it. The SDK's authentication and
request-construction logic does still run above the transport.

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

Prometheus metrics are optional through `backstop-ai[metrics]`.

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

## Priority admission

Admission is a priority **queue**, not a shedding policy. The three priorities
are `critical`, `default` and `background` (`backstop.Priority`); there is no
`normal`. When the AIMD concurrency limit is reached, a request waits for a
slot. Selection prefers `critical`, then the oldest ticket that has waited at
least `starvation_after_seconds` (default `1.0`), then `default`, then
`background` — so a starved `background` ticket is eventually released rather
than waiting forever behind a stream of `critical` ones. Nothing is cancelled
or discarded. `queue_timeout` bounds how long any request will wait before it
receives an error instead.

See `src/backstop/admission.py`.

## Optional gateway / sidecar mode

Everything above describes `Backstop.wrap()`, which is in-process and adds no
network hop. The package *also* ships an optional OpenAI-compatible reverse
proxy: `backstop serve --target https://api.openai.com/v1`, built in
`src/backstop/gateway.py`, needing the `fastapi` extra. The same policy engine
wraps every forwarded request, which makes the policy non-bypassable for
non-Python callers and for fleets where wrapping every client construction site
is impractical.

That is a different mode with a real network hop, and it is not exercised by CI
— the workflow never installs the `fastapi` extra.

## Control Plane Direction — roadmap, not shipped

Nothing in this section exists today. Backstop has no hosted control plane, no
central policy service, and no shared state server. What ships is the local
transport described above, plus optional in-process extras (Redis-backed shared
budget, OpenTelemetry export) that you host yourself.

The long-term commercial architecture is intended to keep this local transport
as the data plane and add an optional control plane for:

- shared policy
- distributed budgets
- team governance
- audit logs
- dashboards
- alerting
- enterprise support

Treat the list as direction, not a roadmap with dates, and not as a
compatibility promise. The local SDK path must remain useful without the
control plane.
