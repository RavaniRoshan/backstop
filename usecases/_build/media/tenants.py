"""Serve the real dashboard with real tenant budgets registered.

The demo workload does not register tenants, so its Tenants panel is always
empty. A multi-tenant demo built on an empty panel would be a mock-up, so this
registers actual per-tenant budgets against a real BackstopState and drives real
requests through a wrapped client, then serves the dashboard over it.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from wsgiref.simple_server import make_server

sys.path.insert(0, "/home/shiva/projects/backstop/src")

import backstop
from backstop import BackstopConfig
from backstop.dashboard_app import (
    Dashboard, _QuietHandler, _ThreadingWSGIServer, make_dashboard_app,
)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8822

# Real budgets, in the unit the ledger and the dashboard both use: tokens.
TENANTS = {
    "acme-corp": 40_000,
    "globex": 25_000,
    "initech": 8_000,      # the one that runs away
    "hooli": 15_000,
}

from backstop.ledger import get_ledger, with_budget
from backstop.ledger.budget import TenantBudget

state = backstop.state.BackstopState.create(120_000, BackstopConfig())
# Register the tenant budgets for real. The Tenants panel reads this ledger, so
# without this it is permanently empty and a multi-tenant demo would be fiction.
get_ledger().register({t: TenantBudget(tenant_id=t, limit_tokens=b)
                       for t, b in TENANTS.items()})

dashboard = Dashboard(
    mode="live", demo=None, cost_model="gpt-4o", title="Backstop — multi-tenant",
)

# In live mode the Dashboard acquires the process-wide telemetry sink itself,
# so starting it is the wiring; the wrapped clients below then feed it.
app = make_dashboard_app(dashboard)


def hammer() -> None:
    """Drive the real openai SDK through a wrapped client, per tenant.

    A raw httpx.Client is not wrappable: Backstop supports the provider SDKs, so
    this uses the real OpenAI client with a mock transport, which is the same
    path `backstop demo` takes.
    """
    import httpx
    from openai import OpenAI

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={
                "object": "list", "model": "text-embedding-3-small",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.01] * 64}],
                "usage": {"prompt_tokens": 420, "total_tokens": 420},
            })
        return httpx.Response(200, json={
            "id": "chatcmpl-x", "object": "chat.completion", "created": int(time.time()),
            "model": "gpt-4o", "choices": [{"index": 0, "message": {
                "role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 260, "total_tokens": 1160},
        })

    clients = {
        t: backstop.Backstop.wrap(
            OpenAI(api_key="mock", base_url="https://api.mock.invalid/v1",
                   http_client=httpx.Client(transport=httpx.MockTransport(handler))),
            budget=b,
        )
        for t, b in TENANTS.items()
    }
    order = list(TENANTS)
    i = 0
    while True:
        t = order[i % len(order)]
        i += 1
        try:
            # with_budget is the real scoping primitive the transport reads.
            with with_budget(t):
                if i % 4:
                    clients[t].chat.completions.create(
                        model="gpt-4o", messages=[{"role": "user", "content": "tenant workload"}])
                else:
                    clients[t].embeddings.create(model="text-embedding-3-small", input="tenant workload")
        except Exception:
            # A BudgetExceededError here is the point: initech runs away, is cut
            # off, and the other three tenants keep spending.
            pass
        time.sleep(0.05)


dashboard.start()
threading.Thread(target=hammer, daemon=True).start()
srv = make_server("127.0.0.1", PORT, app,
                  server_class=_ThreadingWSGIServer, handler_class=_QuietHandler)
print(f"tenants: {json.dumps(TENANTS)}", flush=True)
print(f"listening http://127.0.0.1:{PORT}/", flush=True)
srv.serve_forever()
