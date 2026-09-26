# Use cases

Backstop is an in-process guardrail for the OpenAI and Anthropic SDKs: you wrap
the client once and it enforces token budgets, priority admission, concurrency
ceilings, circuit breaking and retry policy before and after every provider call,
with no network hop and no call-site changes. As a side effect of the traffic it
already mediates, it can write a priced, attributed spend ledger to a file — so
the same deployment that stops a runaway agent can also tell finance which team
spent the money.

Five situations, five different people. Each one is a rendered terminal capture,
not a screen recording, and every number on screen is either a real fact from
this repository or a labelled scenario figure for the fictional company in the
caption. Where a number is a scenario, the `usecase.md` says so.

---

## Flagship — the chargeback

**A backend architect at a ~500-person AI company with a six-figure invoice and
no way to answer "which team spent it."**

![A terminal session where a backend architect reads a repo, wraps a client, turns the ledger on, prices every request, builds a per-team chargeback, hits a real CSV error, admits an unpriced model and an unattributed share, and settles](./major-end-to-end/demo.gif)

→ [Read the full use case](./major-end-to-end/usecase.md)

---

## Multi-tenant SaaS — isolate one tenant's blast radius

**A backend architect at a ~200-person multi-tenant AI SaaS whose customers
share one pool, one process and one provider account.**

![A terminal session where a backend architect scopes 312 tenant budgets on one wrapped client, watches one tenant's circuit open while 311 stay closed, sees a BudgetExceededError become a 402, and reads a per-tenant chargeback](./multi-tenant-saas/demo.gif)

→ [Read the full use case](./multi-tenant-saas/usecase.md)

---

## Agent fleet SLO — protect a p99 under load

**The platform / SRE lead at an ~800-person company running an agent fleet
against a 2-second p99 SLO through a 10x spike and a provider 429 storm.**

![A terminal session where an SRE lead reads the fleet config, sets an AIMD ceiling, watches a priority queue admit a critical ticket ahead of a background one, sees a CircuitBreakerOpenError from an error storm, and watches the p99 hold at 1.9s](./agent-fleet-slo/demo.gif)

→ [Read the full use case](./agent-fleet-slo/usecase.md)

---

## Runaway eval loop — catch the loud blowup and the silent regression

**An AI/ML engineer iterating prompts and running eval loops, whose recursive
agent loop burned a night of budget and whose prompt edit tripled cost per task
without anyone noticing for a fortnight.**

![A terminal session where an ML engineer wraps an eval loop with a 50,000-token ceiling that blocks 7 of 10 calls before dispatch, then watches the drift detector find a 3.0x cost-per-task regression in shadow mode](./runaway-eval-loop/demo.gif)

→ [Read the full use case](./runaway-eval-loop/usecase.md)

---

## Audit and compliance — prove it

**A security & compliance engineer at a ~1200-person regulated fintech, where
finance will not sign off on unreconcilable AI spend and legal will not approve
prompts leaving the host.**

![A terminal session where a compliance engineer turns on an HMAC-chained audit log, traces every outbound byte, admits that the chain proves order rather than authorship, and exports a chargeback CSV grouped by GL code](./audit-and-compliance/demo.gif)

→ [Read the full use case](./audit-and-compliance/usecase.md)

---

## About these captures

They are **rendered terminal captures, not screen recordings** — a compositor in
[`_build/`](./_build/) draws each frame, so there is no keystroke latency, no
window chrome, no typos and no scrollback. They are 414 frames, 42.4 seconds,
~24MB each, and they play once. The ledger, the audit chain, the detection
window and the CSV in them are all real; the tenant names, the company names, the
dollar figures and the p99 numbers are scenario.

If you want the real thing rather than a picture of it:

```bash
pip install "backstop-ai"
backstop verify        # eight offline mechanism checks, no key, no network
backstop ledger demo   # a priced chargeback, byte-identical across runs
```
