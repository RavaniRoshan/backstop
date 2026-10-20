# Budget alerts

A budget that nobody is told about is a budget that is discovered on the
invoice. Backstop can send a webhook when a budget crosses a threshold, so the
person who owns the budget hears about it while there is still budget left.

```python
from backstop import BackstopConfig

config = BackstopConfig(
    webhook_endpoints=["https://hooks.example.com/backstop"],
    webhook_secret="shared-secret",         # signs the payload
    alert_tiers=[0.8, 0.95],                # fire at 80% and 95%
    alert_dedup_ttl=86400.0,                # do not repeat within 24h
    alert_project_horizon_calls=5,          # project 5 calls ahead
)
```

---

## What fires, and when

An alert fires when a budget crosses a **tier** — a fraction of its ceiling.
The default tiers are 80% and 95%.

`alert_project_horizon_calls` makes the alert look a little further ahead than
the call that crossed the tier: the request that will cross the threshold is
projected from the recent run rate, so the alert arrives with a few calls of
headroom rather than none.

---

## Dedup

The same alert does not fire twice inside `alert_dedup_ttl` (24 hours by
default). Without it, a budget sitting at 95% would fire on every single
request, and an endpoint that receives a webhook per request stops being
readable.

The dedup window is per **(tenant, tier)**, so one tenant crossing a threshold
does not silence another tenant's.

**The manager is built once, per transport, and shared.** It used to be rebuilt
per request by the gateway, which defeated the dedup entirely: the same alert
fired on every proxied request, because the manager that remembered what it
had already fired was a new one every time.

---

## The payload

The webhook body is JSON. It carries the tenant, the spend, the limit, the
tier that was crossed, and the moment it happened:

```json
{
  "tenant_id": "payments",
  "used": 4021.55,
  "limit": 5000.00,
  "tier": 0.8,
  "kind": "budget_crossed",
  "at": "2026-10-20T16:58:56.889577Z"
}
```

The `kind` field is what a receiver switches on. `budget_crossed` is the one
above.

---

## The signature

When `webhook_secret` is set, the request carries a signature header computed
over the body with HMAC-SHA256, so the receiver can tell that the request
came from this deployment and was not edited in flight:

```
X-Backstop-Signature: sha256=<hex digest>
```

The receiver recomputes it over the **raw** body and compares in constant
time. A signature over a re-serialised body will not match, so read the body
once, keep the bytes, and verify against those.

---

## Delivery

Delivery is **fire-and-forget**. The alert is dispatched on a background
thread, so the request path is never blocked by a slow or dead endpoint. That
also means delivery is not guaranteed: a process that exits immediately after
the request may not have sent the webhook yet.

The trade is deliberate. A budget guard that blocks a request because a
webhook endpoint is slow is a guard that has become an outage, and the
request it was protecting is exactly the one it just delayed.

Retries and a dead-letter queue are **not** implemented. If an endpoint needs
at-least-once delivery, put a queue in front of it — that is a solved problem
and not one a library should re-solve badly.

---

## What it does not do

- **It does not block anything.** An alert is information, not enforcement. A
  *ceiling* is what stops the spend.
- **It does not deliver exactly once.** It delivers at-most-once per tier per
  dedup window, on a best-effort basis, from a background thread.
- **It does not retry.** There is no dead-letter queue and no backoff. Put a
  queue in front of the endpoint if you need that.
- **It does not know your on-call.** It posts to a URL. What happens next is
  yours.
