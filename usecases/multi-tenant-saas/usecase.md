# Multi-tenant isolation: one customer's runaway loop is not everybody's outage

Tessera is a ~200-person multi-tenant AI SaaS on Series B. 312 tenants share one
Python process and one provider account, and at 02:14 a recursive agent loop
belonging to a single tenant, `acme-4417`, kept reserving against the pool cap —
every other tenant's p99 moved, and the whole cost landed on the quarter-end
invoice with no way to charge it back to the tenant that caused it. Backstop's
answer is not a smaller pool: it is a cap per tenant, a circuit breaker per
tenant, and a 402 at the route instead of a line item on the invoice.

![A terminal session where a backend architect scopes 312 tenant budgets on one wrapped client, watches one tenant's circuit open while 311 stay closed, sees a BudgetExceededError become a 402, and reads a per-tenant chargeback](./demo.gif)

## The situation

A multi-tenant AI product has a structural problem that a single shared budget
cannot solve: the budget is shared, but the consequences are not. When one
tenant's agent loop goes recursive, three things happen at once, and only the
first is obvious.

1. **It consumes the shared margin.** Every other tenant's calls are competing
   with it for the same ceiling, so the tenant that caused the problem is the one
   that cannot be charged for it.
2. **It degrades everyone else's latency.** Without per-tenant breakers, one
   tenant's provider 429s open the single circuit for the whole process, and a
   `CircuitBreakerOpenError` is now raised against every tenant's traffic.
3. **It is discovered at the invoice, not at the request.** By the time finance
   sees the number, the customer relationship is already load-bearing.

## What backstop does here

Everything below is in-process, in your process, with one wrap call and no
call-site edits.

- **A cap per tenant.** `backstop.budgets.register({...})` takes a dict of
  `TenantBudget(tenant_id, limit_tokens=...)`. `backstop.with_budget(tenant_id)`
  sets a `ContextVar`, and the transport reads the active tenant on every
  request and reserves against *that tenant's* node instead of the
  process-wide budget. `TenantBudget` also takes a `parent`, and the effective
  limit is the most restrictive of the two — so a per-plan cap and a global cap
  compose without either being able to exceed the other.
- **A key that carries the tenancy.** `BackstopConfig(virtual_keys={...})` maps a
  caller-supplied key to a tenant id, read per request from
  `virtual_key_header` (default `X-Backstop-Key`). If an API gateway in front of
  your service already issues per-customer keys, tenancy crosses the boundary in
  a header instead of in Python.
- **A breaker per tenant.** `BackstopConfig(per_tenant_circuit=True)` makes
  `BackstopState.circuit_for(tenant_id)` hand out a separate
  `CircuitBreaker` per tenant. `acme-4417` opening its breaker has no effect on
  the other 311. It is off by default, because one global breaker is the right
  default for a single-tenant service.
- **A 402 instead of an invoice.** When a tenant's reservation fails,
  `BudgetExceededError` is raised *before* the request is dispatched, so the
  provider is never called. `examples/fastapi_tenants.py` is the whole pattern:

  ```python
  from backstop import Backstop, TenantBudget, budgets, with_budget
  from backstop.exceptions import BudgetExceededError

  client = Backstop.wrap(OpenAI(), budget=None)
  budgets.register({
      "free": TenantBudget("free", limit_tokens=10_000),
      "pro":  TenantBudget("pro",  limit_tokens=250_000),
  })

  try:
      with with_budget(x_plan):
          response = client.chat.completions.create(...)
  except BudgetExceededError as exc:
      raise HTTPException(status_code=402, detail=str(exc)) from exc
  ```

  `BudgetExceededError` is also a subclass of `openai.OpenAIError` /
  `anthropic.AnthropicError`, so existing `except` clauses keep working.
- **A softer variant.** `TenantBudget(..., on_exceed="downgrade")` instead of
  raising: the transport rewrites the request's `model` to its `downgrade_to`
  entry (`gpt-4.1-mini` → `gpt-4.1-nano`, `gpt-4o` → `gpt-4o-mini`,
  `claude-sonnet-4` → `claude-haiku-4-20250514`) and re-reserves in the same
  call. The decision is recorded as a `downgrade`, not a `deny`.
- **Per-tenant counters.** `backstop_tenant_budget_exceeded_total` is labelled
  by `tenant_id`, and the audit log's `deny` records carry `tenant_id` too, so
  "which tenant is being refused" is a query, not an inference.
- **Per-tenant dollars.** With `ledger_enabled=True`, the same `SpendEvent`
  carries a `tenant` attribution dimension, so
  `backstop ledger export --group-by tenant,customer` is the chargeback. An
  undeclared call site renders as `(unattributed)`, never as a blank cell.

## What you see in the demo

- **Cold open** — 312 tenants on one process and one account, and a loop at
  02:14 that ate the shared cap.
- **Submit** — `backstop harness --scenario budget-hit`: a local mock provider,
  no key, no network.
- **Stream** — one `Backstop.wrap()` at the gateway chat route, 312 registered
  `TenantBudget`s, `virtual_keys` read from `X-Backstop-Key`, and
  `per_tenant_circuit=True`.
- **Isolation** — `acme-4417` reserves against its own node and opens its own
  breaker; `globex-0092` reserves against its own and stays closed; the parent
  cap composes most-restrictive-wins.
- **The block** — a real `BudgetExceededError` raised before dispatch, mapped by
  your FastAPI route to `HTTPException(402)`. The demo says on screen that the
  mapping is your route, not backstop's.
- **The honest beat** — 12 replicas is 12 caps unless you opt into
  `shared_budget=True, redis_url=...`; the ledger is one file per process, not a
  multi-tenant store; and `on_exceed="downgrade"` is the softer path.
- **Dense resolution** — the per-tenant chargeback: `globex` across 8 tenants,
  `initech` across 3, and the 19 requests nobody can charge. Detection is on in
  shadow, so the spike has one key attached to it and zero requests were killed.
- **End card** — blast radius: one tenant. A 402, not a quarter-end invoice.

## The commands

```bash
pip install "backstop-ai[anthropic]"

# the command in the GIF: budget exhaustion, offline, no key
backstop harness --scenario budget-hit

# eight offline mechanism checks, including per-agent isolation
backstop verify

# your own file -> a per-tenant chargeback
backstop ledger show   --path ledger.jsonl --group-by tenant,customer
backstop ledger export --path ledger.jsonl --out chargeback.csv --group-by tenant,customer
```

The configuration the demo is describing:

```python
client = Backstop.wrap(
    OpenAI(),
    budget=None,                       # the process cap is not the product's cap
    config=BackstopConfig(
        per_tenant_circuit=True,
        ledger_enabled=True,
        ledger_path="ledger.jsonl",
        virtual_keys={"vk_live_acme4417": "acme-4417"},
        virtual_key_header="X-Backstop-Key",
    ),
)
budgets.register({
    "acme-4417": TenantBudget("acme-4417", limit_tokens=2_000_000),
    "globex-0092": TenantBudget("globex-0092", limit_tokens=2_000_000),
    # ...
})
```

## What this does NOT solve

- **Replicas do not share state by default.** Twelve pods is twelve caps and
  twelve breakers, and `docs/architecture.md` lists per-replica circuit state
  and per-process budgets as the documented limits of local mode. The fix is
  `BackstopConfig(shared_budget=True, redis_url=...)` from the `redis` extra,
  which reserves and commits through atomic Lua. It is off by default **and CI
  does not install the `redis` extra**, so that path has no automated coverage
  in this repository (`docs/threat-model.md`). `docs/architecture.md` also calls
  *distributed tenant enforcement* a planned enterprise-pilot milestone, not a
  shipped feature.
- **The 402 is your route's job.** Backstop raises `BudgetExceededError` before
  dispatch and records the `deny`. Turning that into a 402, a 429 or a support
  ticket is a line in your handler.
- **Unwrapped clients bypass all of it.** If any call site keeps a raw
  `OpenAI()`, that call is outside every budget and every breaker.
  `backstop doctor` reports versions and wrap status but explicitly does not
  scan your codebase for unwrapped clients (`docs/threat-model.md`).
- **The ledger is not multi-tenant storage.** One file per process, whatever
  path that process chose, until somebody deletes it. Rotation, archival and
  querying are yours. `virtual_keys` and per-tenant budgets are about
  *enforcement*, not about partitioning storage.
- **No central key store, and do not lean on key rewriting.**
  `secret_provider` resolves a virtual key to a provider secret at call time,
  but `docs/planning/07-risks-and-killshots.md` records the *default* secret
  provider as silently dead (defect O1: a frozen-dataclass assignment plus a
  bare `except: pass`, with the measured effect that `BACKSTOP_API_KEY_VK_1`
  never rewrites `Authorization`). The tenant *resolution* works; the credential
  rewrite is not something to depend on until O1 is fixed.
- **Detection cannot stop anything.** The runaway-spend detector reports; it
  cannot block, cancel or kill, and spend avoided is not in the ledger at all.
- **No per-tenant forecasting, no metering product, no billing.** There is no
  Backstop service, no shared policy server and no invoice reconciliation.
  `backstop.forecast` projects *budget exhaustion* from a measured burn rate; it
  does not project spend.
- **Not a multi-provider router.** The fallback chain stays within one provider.

## Where to read more

- [`examples/fastapi_tenants.py`](../../examples/fastapi_tenants.py) — the 402
  pattern, runnable.
- [`docs/architecture.md`](../../docs/architecture.md) — tenant budgets,
  `circuit_for`, and the "Local Mode" limitations list.
- [`docs/threat-model.md`](../../docs/threat-model.md) — budget bypass, metric
  leakage, distributed split-brain.
- [`docs/concurrency.md`](../../docs/concurrency.md) — the GIL ceiling and the
  one-process-per-tenant advice.
- [`docs/ledger.md`](../../docs/ledger.md) — the `tenant` attribution dimension
  and `--group-by`.
- [`docs/planning/07-risks-and-killshots.md`](../../docs/planning/07-risks-and-killshots.md)
  — R9 (no multi-tenancy story) and defect O1 (the dead default secret provider).
- [`usecases/README.md`](../README.md) — the other use cases.
