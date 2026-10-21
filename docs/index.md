---
title: Documentation
description: Backstop puts budgets, a circuit breaker and concurrency limits on AI agents, in the process that calls them.
---

# Documentation

The library is also a set of ideas worth understanding, whether or not you
install it: what a hard limit actually is, what a circuit breaker is for, why a
queue is better than a rejection, and how much a guardrail is allowed to cost.

## Start here

| If you want to | Read |
|---|---|
| Stop a runaway agent in the next ten minutes | [Quickstart](quickstart.md) |
| Install it, including air-gapped | [Installing Backstop](install.md) |
| See what it does before you install it | [The built-in dashboard](dashboard.md) |
| Understand how it fits together | [Architecture](architecture.md) |

## How it works

- **[Architecture](architecture.md)** — the transport, the gate and the ledger,
  and why the request path looks the way it does.
- **[Dollar budgets](usd-budgets.md)** — a ceiling in money, priced from the
  model you actually call.
- **[The spend ledger](ledger.md)** — one priced, attributed record per
  completed request, and the charge-back export built on it.
- **[Runaway-spend detection](detection.md)** — four detectors that notice a
  spend pattern before it becomes an invoice.
- **[Concurrency and scale limits](concurrency.md)** — how many requests can be
  in flight, and what happens when there are more than that.

## Reference

- **[Compatibility matrix](compatibility.md)** — which SDK versions are
  supported, and what is not.
- **[SDK matrix](sdk-matrix.md)** — what CI actually proves, version by
  version.
- **[Framework adapters](frameworks.md)** — LangChain, LlamaIndex, CrewAI and
  the rest.

## Operations

- **[The built-in dashboard](dashboard.md)** — a dependency-free view of the
  process you are already running.
- **[Budget alerts](alerts.md)** — telling someone before the ceiling, not
  after.
- **[Benchmarks](benchmarks.md)** — how the overhead numbers are measured, and
  the conditions they were measured under.
- **[Benchmark results](benchmark-results-2026-10-20.md)** — the current
  committed snapshot.
- **[Threat model](threat-model.md)** — what Backstop trusts, what it does
  not, and where its limits are.

## The short version

```bash
pip install backstop-ai
backstop verify
```

`verify` runs a real wrap against a local mock transport, blocks a runaway
loop, and prints what it measured. No API key, no network, about thirty
seconds.
