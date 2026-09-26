"""Multi-tenant isolation — one customer's agent loop must not become everyone
else's outage.

Persona: a backend architect at a ~200-person multi-tenant AI SaaS (Series B).
312 tenants share one process and one provider account. At 02:14 one tenant's
recursive agent loop kept reserving against the shared cap; every other tenant's
p99 moved, and the quarter-end invoice carried the whole cost with no way to
charge any of it back to anybody.

Storyline, mapped onto the normative 8-phase grid:
  1 cold open    one tenant's loop, everybody else's latency
  2 submit       run it
  3 stream       wrap once, register 312 caps, key -> tenant, breaker -> tenant
  4 isolate      the reservation and the circuit, per tenant
  5 block        a real BudgetExceededError and the 402 it becomes
  6 honest       replicas do not share state; the 402 is your own route
  7 dense        per-tenant chargeback, per-tenant detection
  8 settle       blast radius = one tenant

Real repo facts on screen: `budgets.register` / `TenantBudget` / `with_budget`,
`per_tenant_circuit`, `virtual_keys` read from `X-Backstop-Key`, the 402 in
`examples/fastapi_tenants.py`, hierarchical most-restrictive-wins, the
`budget-hit` harness counts, and the 13 legal `--group-by` dimensions. The
tenant names, the dollar figures and the request counts are this company's
scenario, not measurements.
"""

from render import Phase, Row

OUT_NAME = "multi-tenant-saas.gif"


def R(kind, text, dot="", indent=0, pill=""):
    return Row(kind=kind, text=text, dot=dot, indent=indent, pill=pill)


BRIEF = {
    # ---- window chrome + header -------------------------------------------
    "window_title": "Noisy neighbour",
    "product": "backstop",
    "version": "v0.6.0",
    "model": "gpt-4.1-mini",
    "path": "~/tessera/agent-api",
    "branch": "fix/tenant-isolation",
    "command": "backstop harness --scenario budget-hit",
    "command_hint": "harness",
    "submitted": False,

    # ---- beats -----------------------------------------------------------
    "phases": [
        # 1. cold open (frames 0-2)
        Phase(
            rows=[
                R("dim", "312 tenants, one process, one account"),
                R("dim", "02:14: one agent loop ate the shared cap"),
            ],
            status="/harness",
        ),

        # 2. submit (frames 3-20)
        Phase(
            rows=[
                R("action", "Run", "run", 0, "->|"),
                R("dim", "local mock provider. no key, no network."),
            ],
            status="Thinking on (tab to toggle)",
        ),

        # 3. thinking / stream begins (frames 21-74)
        Phase(
            rows=[
                R("running", "Wrapping the client... (esc to interrupt)", "run", 0, "<-"),
                R("dim", "Next: scope, cap, breaker"),
                R("action", "Read(app/gateway/chat.py)", "ok"),
                R("dim", "one Backstop.wrap() for 312 tenants"),
                R("action", "budgets.register(312 tenants)", "ok"),
                R("dim", "free 10k  pro 250k  enterprise 2M tokens"),
                R("action", "virtual_keys -> tenant id", "ok"),
                R("dim", "read from X-Backstop-Key, per request"),
                R("action", "per_tenant_circuit=True", "ok"),
                R("dim", "one breaker per tenant, not one per app"),
                R("thought", "one wrap call. no call-site edits.", "", 0),
            ],
            scroll_at={6: 1},
        ),

        # 4. the isolation itself (frames 75-143)
        Phase(
            rows=[
                R("action", "Reserve(tenant=acme-4417)", "ok"),
                R("dim", "ContextVar, set by the request handler"),
                R("action", "Reserve(tenant=globex-0092)", "ok"),
                R("dim", "charged to its own node, not the pool"),
                R("action", "Circuit(acme-4417) -> OPEN", "err", 0, "<-"),
                R("dim", "its own 429s, its own cooldown"),
                R("action", "Circuit(globex-0092) -> CLOSED", "ok"),
                R("dim", "311 other breakers never saw the storm"),
                R("action", "Parent(cap=1,000,000)", "ok"),
                R("dim", "most-restrictive wins: min(self, parent)"),
                R("thought", "one tenant's noise, contained.", "", 0),
            ],
            scroll_at={8: 1},
        ),

        # 5. a real block, and the 402 (frames 144-195)
        Phase(
            rows=[
                R("running", "Harness: budget-hit, 250 token cap", "run"),
                R("action", "Harness(budget-hit)", "ok"),
                R("dim", "80 attempted  16 provider calls"),
                R("dim", "64 blocked in-process  58 tokens left"),
                R("error", "BudgetExceededError(acme-4417)"),
                R("dim", "raised before dispatch. 0 provider calls."),
                R("action", "FastAPI: except -> HTTPException(402)", "ok"),
                R("dim", "the 402 is your route, not backstop's job"),
                R("action", "Metrics(tenant_budget_blocks)", "ok"),
            ],
            scroll_at={6: 1},
        ),

        # 6. the honest part (frames 196-252)
        Phase(
            rows=[
                R("action", "Replicas do not share state", "err"),
                R("dim", "12 pods is 12 caps. that is the default."),
                R("action", "shared_budget=True, redis_url=...", "ok"),
                R("dim", "one cap across N processes, atomic Lua"),
                R("action", "The ledger is one file per process", "err"),
                R("dim", "not a multi-tenant store. rotate it."),
                R("action", "on_exceed='downgrade' is the soft path", "ok"),
                R("dim", "same call, model rewritten to downgrade_to"),
            ],
            scroll_at={6: 1},
        ),

        # 7. dense resolution (frames 253-340)
        Phase(
            rows=[
                R("action", "Export: --group-by tenant", "ok"),
                R("dim", "312 groups, largest total first"),
                R("action", "Group(customer=globex)", "ok"),
                R("dim", "8 tenants  1.9M tok  41.20 USD"),
                R("action", "Group(customer=initech)", "ok"),
                R("dim", "3 tenants  0.4M tok   9.83 USD"),
                R("action", "Group(tenant=(unattributed))", "err"),
                R("dim", "19 requests, nobody to charge"),
                R("action", "Detect(velocity), per tenant key", "ok"),
                R("dim", "shadow: 1 key flagged, 0 requests killed"),
                R("thought", "the spike has an owner now.", "", 0),
            ],
            scroll_at={8: 1},
        ),

        # 8. settle + end card (frames 341-413)
        Phase(
            rows=[
                R("action", "Isolated(312 tenants)", "ok"),
                R("dim", "1 cap reached  1 breaker open"),
                R("action", "Blast radius = 1 tenant", "ok"),
                R("dim", "311 never saw the error"),
                R("action", "Settled", "ok"),
                R("dim", "a 402, not a quarter-end invoice"),
            ],
        ),
    ],
}
