# The built-in dashboard

Backstop ships a dependency-free operations dashboard: `backstop dashboard`.
It answers "what is Backstop doing to my traffic right now?" — budgets, AIMD
concurrency, circuit state, per-session isolation, and enforcement events —
without asking you to stand up Prometheus, Alertmanager, or any exporter first.

## Quick start

```bash
# Look at it with synthetic traffic (no API keys, no network calls)
backstop dashboard --demo

# Watch a real process: run the dashboard alongside your workload
backstop dashboard                 # http://127.0.0.1:8787 (loopback only)
backstop dashboard --port 8788 --cost-model gpt-4o
backstop dashboard --audit audit.jsonl   # enable the enforcement event stream

# Exposing beyond loopback requires a bearer token
backstop dashboard --host 0.0.0.0 --token "$(openssl rand -hex 32)"
```

Or serve it at the root of a dedicated FastAPI app:

```python
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from backstop import Backstop

app = FastAPI()
app.mount("/", WSGIMiddleware(Backstop.dashboard_app()))
```

Subpath mounts such as `/dashboard` are not currently supported: assets and
snapshot requests use root-relative URLs.

The page polls `/api/snapshot` once per sample interval (2s live, 1s demo;
`--refresh` to override). Responses carry an `ETag`, so an unchanged snapshot
revalidates as `304 Not Modified` instead of being re-downloaded. The snapshot
distinguishes render time from data age: `sampled_at` is the absolute time the
last sample was taken, `sample_age_s` is how old it is (both null before the
first sample), and `sample_interval_s` gives the cadence — use
`sample_age_s` against `sample_interval_s` to show or warn about staleness.

## What it shows

| Panel | Meaning |
|---|---|
| Budget | live limit, spent, remaining, % used, burn rate, projected exhaustion |
| Spend | tokens and a USD **lower bound** (input-token rate of `--cost-model`) |
| Prevention | stopped calls, with budget, rate-limit, and circuit block counts |
| Traffic | requests/s, total requests, provider calls, and retries |
| Latency | p95 of observed transport calls, with p50 and p99; provider calls included |
| Concurrency | AIMD active/capacity, queue depth |
| Outcome mix | request counts and proportional bars by outcome |
| Circuit | breaker state and trip count |
| Isolation | live sessions, per-session rows (id, budget, spend, concurrency) |
| Tenants | per-tenant ledger usage and remaining |
| Events | tail of the audit log (allowlisted fields only) |

The methodology footer states exactly what each number is derived from, so a
screenshot cannot be mistaken for more than it is.

## Where the data comes from

The dashboard renders state the process already holds. `Metrics.call()` — the
single choke point every instrumented code path already goes through — feeds a
telemetry sink (`backstop.telemetry`) *before* the optional Prometheus path, so
the built-in dashboard works in a bare `pip install backstop` with nothing
installed beyond the stdlib.

Deliberate constraints:

* **No storage, no retention, no query language.** A fixed-size ring of samples
  in memory (360 samples ≈ 12 minutes at the 2s default), bounded session rows,
  event rows, and a 64 KiB audit tail. Nothing is written to disk, nothing
  survives the process. For retention, fleet-wide queries, and alerting, export
  Prometheus/OTel and point them at your own monitoring stack — that path is
  unchanged, and the dashboard
  reports whether those sinks are active.
* **No hot-path cost when unused.** The sink is `None` unless a dashboard is
  running in this process; an ordinary install pays one `is None` comparison per
  instrumented event.
* **Live sessions are the source of truth for gauges.** Process-global
  Prometheus gauges collapse across sessions (last writer wins), so budget and
  concurrency figures are read from the registered `BackstopState`s via
  weakrefs and aggregated in the snapshot. A session is visible exactly as long
  as its owner holds it.
* **Demo mode is process-isolated.** `--demo` runs the mock workload (its
  sessions, counters, and telemetry sink) in a spawned child process that
  publishes bounded snapshots over shared memory; the demo dashboard reads them
  and computes `sample_age_s` locally. Construction registers nothing in the
  parent: demo sessions never appear in the parent's session registry, demo
  capture never reaches the parent's sink, and demo mode cannot install,
  uninstall, or otherwise disturb a real sink the application is already using.
  Stopping the dashboard always leaves application-owned capture running, and a
  `live` dashboard rejects a demo workload outright (`ValueError`).
* **Honest nulls.** With no live sessions the budget KPI is `null`, not a
  misleading `0`. The cost figure is labelled a lower bound because output and
  cache-read tokens are not priced. The audit stream notes that a tail cannot
  re-verify the HMAC chain (run `backstop verify` for a full replay).

## Security model

* **Loopback by default.** Without a token the server refuses to bind any
  non-loopback address (`ValueError` from `serve()` and the CLI).
* **Bearer tokens.** `--token` (or `token=`) requires
  `Authorization: Bearer <token>` on every request, compared with
  `hmac.compare_digest`.
* **Restrictive CSP, no external origins.** `default-src 'none'` with
  self-only styles/scripts; the page cannot phone home. Responses also carry
  `nosniff`, `no-referrer`, `frame-ancestors 'none'`, and `X-Frame-Options`.
* **No write surface.** Only `GET`/`HEAD` are served; the dashboard never
  mutates a budget, a circuit, or any other state.
* **XSS-safe rendering.** The page builds DOM nodes with `textContent` only —
  no `innerHTML` — so values containing HTML cannot escape into markup.

## CLI reference

| Flag | Default | Meaning |
|---|---|---|
| `--port` | `8787` | listen port |
| `--host` | `127.0.0.1` | bind address; non-loopback requires `--token` |
| `--refresh` | 2.0s live, 1.0s demo | sample interval in seconds |
| `--cost-model` | none | model whose input rate prices the USD lower bound |
| `--audit` | none | audit JSONL path; enables the enforcement event stream |
| `--demo` | off | run the deterministic mock workload (3 lanes, no keys) |
| `--runners` | `3` | demo lane count (1–8) |
| `--theme` | `auto` | initial colour theme: `auto` (follow the OS), `dark`, or `light`; the page's **theme** button overrides per browser and is remembered |
| `--token` | none | require this bearer token |
| `--no-browser` | off | do not open a browser tab |

## Non-goals

No history beyond the in-memory ring, no multi-process aggregation, no user
accounts, no saved views. Anything you would want to keep belongs in
Prometheus/OTel, not here.
