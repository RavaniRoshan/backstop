<div align="center">
  <h1>Backstop</h1>
  <p>
    <strong>In-process AI SDK backpressure, budgets, retries, circuit breaking, and metrics.</strong>
  </p>
  <p>
    <em>Hypothesis: transport-layer budget isolation becomes critical infrastructure when you go from 1 agent to N agents.</em>
  </p>
  <p>
    <a href="#quick-start">Quick Start</a> •
    <a href="#features">Features</a> •
    <a href="#wedge-multi-agent-diff-cli">Wedge</a> •
    <a href="#architecture">Architecture</a> •
    <a href="#benchmarks">Benchmarks</a> •
    <a href="#current-status">Status</a> •
    <a href="CHANGELOG.md">Changelog</a> •
    <a href="CODE_OF_CONDUCT.md">Code of Conduct</a>
  </p>
  <p>
    <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+" />
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License MIT" />
    <img src="https://img.shields.io/badge/status-14--day%20open%20test-orange" alt="Status: 14-day open test" />
  </p>
</div>

## The Problem

Running a single AI coding agent is already expensive and unpredictable. Running three in parallel — which is what multi-agent architectures require — triples your runaway-cost exposure. Today, your options are:

1. **No protection** — hope the agent stops. Production teams usually discover spend controls after the first cost incident.
2. **Proxy gateway** — route all traffic through an external service. Adds latency, a single point of failure, and network complexity.

Backstop takes a third path: **SDK-native guardrails that live inside your process.** No proxy, no network hop, no monkey-patching. It replaces the SDK's internal `httpx` transport with a controlled pipeline — budget enforcement, circuit breaking, priority admission, retry logic — before any request leaves your application.

The Wedge tool (bundled in this repo) tests whether this transport-layer isolation is sufficient to safely run multiple coding agents in parallel, each with their own budget and kill-switch.

---

## Quick Start

```bash
pip install -e ".[anthropic]"
```

Wrap any OpenAI or Anthropic client in one line:

```python
from openai import OpenAI
from backstop import Backstop

client = Backstop.wrap(OpenAI(), budget=50_000)

# Use the client exactly as before — Backstop intercepts at the transport layer
response = client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[{"role": "user", "content": "Hello."}],
)
```

```python
from anthropic import Anthropic
from backstop import Backstop

client = Backstop.wrap(Anthropic(), budget=50_000)

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello."}],
)
```

Run the multi-agent diff tool:

```bash
wedge run task.yaml
```

---

## Features

- **Token budget enforcement** — Reserve before dispatch, reconcile after response. Hard limits prevent runaway spend.
- **Priority admission** — `critical`, `default`, `background` queuing with starvation prevention.
- **AIMD concurrency** — Additive-increase/multiplicative-decrease adapts to provider pressure.
- **Retry with backoff** — Configurable attempts, jitter, and status codes (429/500/502/503/504/529).
- **Circuit breaker** — Trips on sustained failure, cooldowns automatically.
- **Streaming support** — Wraps streaming responses while preserving budget reconciliation.
- **Tenant budgets** — Request-scoped tenant budget buckets via `with_budget(...)`.
- **Response caching** — Optional in-memory cache for repeated deterministic calls.
- **Hooks** — Lightweight before/after hooks for local logging, policy, and metadata.
- **HTTP transport layer** — Plugs into the SDK's native `httpx` transport — no monkey-patching.
- **Prometheus metrics** — Optional export for dashboards and alerting.
- **Provider support** — OpenAI (sync & async) and Anthropic (sync & async).

---

## Wedge: Multi-Agent Diff CLI

Wedge is a sandboxed execution environment bundled with Backstop. It runs N isolated coding agents against the same task, wraps each in its own Backstop session, and diffs their output to measure convergence.

**Why this exists:** Testing whether isolated multi-agent execution with transport-layer budget isolation reduces runaway-cost exposure in coding agents.

```
Wedge tool (isolated multi-agent diff CLI)
        │
        ├──► Runner A: Backstop.wrap(Anthropic(), budget=20_000)
        ├──► Runner B: Backstop.wrap(Anthropic(), budget=20_000)
        └──► Runner C: Backstop.wrap(Anthropic(), budget=20_000)
                        │
              (each runner = one Backstop session,
               own budget, own kill-switch —
               isolated CONTEXT, not isolated INFRA)
```

Each runner gets:
- Its own `Backstop.wrap()` session — independent budget, independent circuit breaker
- Its own isolated working directory (simulated git worktree)
- No shared conversation history with other runners

After all runners complete, the diff engine scores patch similarity across all outputs:

| Status | Meaning |
|---|---|
| `CONVERGED` | All patches identical (similarity = 1.00) |
| `PARTIAL` | Patches share >80% similarity |
| `DIVERGED` | Patches differ significantly (<80%) |

### Example: Running Wedge

```yaml
# task.yaml
name: "Refactor to class-based"
prompt: "Refactor the main.py file to use a class-based approach."
test_command: "pytest tests/"
runners: 3
provider: "anthropic"   # or "openai"
```

```bash
$ wedge run task.yaml
Running task: Refactor to class-based with 3 concurrent runners (anthropic)...
Comparing patches...
Done! Report saved to wedge_report.md

Convergence Summary:
  main.py: CONVERGED (sim=1.00)
```

The report includes each runner's Backstop budget usage — the first real usage evidence for whether per-agent budget isolation works in practice.

---

## What This Is NOT

Backstop deliberately avoids:

- **Not a proxy/gateway** — No network hop. Runs entirely in-process.
- **Not an MCP tool** — Protocol-agnostic. Works with any SDK client that uses `httpx`/`requests`.
- **Not an observability platform** — It exports Prometheus metrics; it doesn't store, query, or visualize them.
- **Not an application-layer tool** — It does not consume signals like "disagreement" or "confidence." It operates at the transport layer only.
- **Not a caching layer** — Optional response caching exists for convenience, not as a primary feature.

Wedge deliberately avoids:

- **Not a production agent framework** — This is a 7-day spike to test a hypothesis, not a finished product.
- **Not AST-level semantic diffing** — v1 uses `difflib` string comparison. Semantic diffing is a v2 question gated on v1 results.

---

## Architecture

### Backstop Transport Pipeline

```mermaid
graph LR
    A[SDK Client<br/>OpenAI / Anthropic] --> B[Backstop.wrap]
    B --> C[Client.copy]
    B --> D[BackstopTransport]
    D --> E[Priority Gate]
    D --> F[Budget]
    D --> G[AIMD Controller]
    D --> H[Circuit Breaker]
    D --> I[Retry Logic]
    I --> J[httpx Transport]
```

Backstop replaces the SDK's internal `httpx.Client` with a custom transport that intercepts every request. No monkey-patching, no thread hacks — just standard SDK `http_client` injection.

### Wedge Multi-Runner Architecture

```
┌─────────────────────────────────────────────────┐
│  wedge run task.yaml                            │
│                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Runner A │  │ Runner B │  │ Runner C │      │
│  │          │  │          │  │          │      │
│  │ Backstop │  │ Backstop │  │ Backstop │      │
│  │ budget:  │  │ budget:  │  │ budget:  │      │
│  │  20,000  │  │  20,000  │  │  20,000  │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
│       │              │              │            │
│       ▼              ▼              ▼            │
│  ┌─────────────────────────────────────────┐    │
│  │         Provider API (shared)           │    │
│  │     Anthropic / OpenAI endpoints        │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  ┌─────────────────────────────────────────┐    │
│  │  Diff Engine → Convergence Report       │    │
│  └─────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

Key: **isolated context, not isolated infrastructure.** All runners share the same process and event loop. Isolation lives at the conversation/budget layer, enforced by Backstop's transport wrapper.

---

## Install

```bash
# Base install
pip install backstop

# With Prometheus metrics
pip install "backstop[metrics]"

# With Anthropic support
pip install "backstop[anthropic]"

# Everything (dev)
pip install -e ".[test,metrics,anthropic]"
```

From source:
```bash
git clone https://github.com/RavaniRoshan/backstop.git
cd backstop
pip install -e ".[test,metrics,anthropic]"
```

---

## Usage

### OpenAI

```python
from openai import OpenAI
from backstop import Backstop, BackstopConfig

client = Backstop.wrap(
    OpenAI(api_key="sk-..."),
    budget=50_000,
    config=BackstopConfig(initial_concurrency=8),
)

response = client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[{"role": "user", "content": "Summarize this in one paragraph."}],
    extra_headers={"X-Backstop-Priority": "critical"},
)
```

Async:
```python
from openai import AsyncOpenAI
from backstop import Backstop

client = Backstop.wrap(AsyncOpenAI(api_key="sk-..."), budget=10_000)
```

### Anthropic

```python
from anthropic import Anthropic
from backstop import Backstop, BackstopConfig

client = Backstop.wrap(
    Anthropic(api_key="sk-ant-..."),
    budget=50_000,
    config=BackstopConfig(initial_concurrency=8),
)

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Summarize this in one paragraph."}],
    extra_headers={"X-Backstop-Priority": "critical"},
)
```

Async:
```python
from anthropic import AsyncAnthropic
from backstop import Backstop

client = Backstop.wrap(AsyncAnthropic(api_key="sk-ant-..."), budget=10_000)
```

> `budget=None` — unlimited pass-through. `budget=0` — blocks before dispatch.

### Tenant Budgets

```python
from backstop import TenantBudget, budgets, with_budget

budgets.register({
    "tenant_123": TenantBudget("tenant_123", limit_tokens=50_000),
})

with with_budget("tenant_123"):
    client.chat.completions.create(...)
```

### Priority

Set per-request priority via the `X-Backstop-Priority` header:

| Value | Behavior |
|---|---|
| `critical` | Admitted first — use for user-facing requests |
| `default` | Normal queue position |
| `background` | Lowest priority — yields to higher |

---

## CLI

```bash
# Backstop harness scenarios
backstop harness --scenario burst
backstop harness --scenario error-storm
backstop harness --scenario budget-hit

# Prometheus metrics server
backstop metrics --port 9090

# Real API smoke tests (set API keys first)
backstop real-openai --model gpt-4.1-mini
backstop real-anthropic

# Wedge multi-agent diff
wedge run task.yaml
```

## Examples

Runnable examples live in [`examples/`](examples/):

**Backstop:**
- [`openai_sync.py`](examples/openai_sync.py) — Sync OpenAI with budget
- [`openai_async.py`](examples/openai_async.py) — Async OpenAI
- [`anthropic_sync.py`](examples/anthropic_sync.py) — Sync Anthropic with budget
- [`anthropic_async.py`](examples/anthropic_async.py) — Async Anthropic
- [`fastapi_tenants.py`](examples/fastapi_tenants.py) — Multi-tenant FastAPI
- [`background_priority.py`](examples/background_priority.py) — Priority queuing
- [`prometheus_metrics.py`](examples/prometheus_metrics.py) — Metrics export
- [`budget_blocking_demo.py`](examples/budget_blocking_demo.py) — Budget exhaustion

**Wedge:**
- [`wedge_basic.py`](examples/wedge_basic.py) — 3 Anthropic runners, diff output
- [`wedge_openai.py`](examples/wedge_openai.py) — 3 OpenAI runners, diff output

---

## Benchmarks

Backstop overhead is measured separately from provider latency using a local mock transport.

| Metric | Direct | Backstop | Overhead |
|---|---:|---:|---:|
| p50 latency | 0.12 ms | 0.19 ms | **0.07 ms** |
| p95 latency | 0.22 ms | 0.30 ms | **0.07 ms** |
| p99 latency | 0.30 ms | 0.38 ms | **0.07 ms** |

Key scenario results (1,000 requests, mock provider):

| Scenario | Requests | Provider Calls | Blocked | Why |
|---|---:|---:|---:|---|
| **Burst** | 50 | 50 | 0 | All requests within budget |
| **Error Storm** | 50 | 28 | 30 | Circuit breaker tripped after 7 errors |
| **Budget Hit** | 80 | 17 | 63 | Pre-flight budget blocking saved 63 API calls |

Full results: [`docs/benchmark-results-2026-07-04.md`](docs/benchmark-results-2026-07-04.md) · Methodology: [`docs/benchmarks.md`](docs/benchmarks.md)

---

## Metrics

Export Prometheus metrics by installing `backstop[metrics]`:

```python
from backstop import Backstop

# Start a standalone HTTP server
Backstop.start_metrics_server(port=9090)

# Or mount the WSGI app in your existing server
app = Backstop.metrics_app()
```

Starter observability assets:
- [`observability/grafana/backstop-dashboard.json`](observability/grafana/backstop-dashboard.json)
- [`observability/prometheus-alerts.yml`](observability/prometheus-alerts.yml)

---

## Current Status

**This is a 14-day open test.** Testing period: July 7 – July 21, 2026.

### What we're measuring
1. **Budget isolation correctness** — Does each runner's Backstop session correctly enforce independent budgets when 3 agents run concurrently?
2. **Convergence rates** — How often do isolated agents produce identical/similar patches for the same task?
3. **Cost exposure reduction** — Does per-agent budget capping actually prevent the 3x runaway-cost multiplier?

### What would change our mind
- If Backstop's AIMD/circuit-breaker state bleeds across `wrap()` calls under concurrent load, the isolation thesis fails. We'd need to redesign the state model.
- If convergence rates are consistently low (<50% across tasks), multi-agent diffing may not add enough signal to justify the cost multiplication.
- If the transport-layer overhead becomes significant under real provider latencies (>5ms added per call), the in-process model may not be worth the complexity over a proxy.

### Kill criteria
If none of these produce usable signal by July 21: archive Wedge, keep Backstop as a standalone transport wrapper, and document what we learned.

---

## Tests

```bash
# Unit tests (no API calls)
pytest

# Real OpenAI API (opt-in)
export OPENAI_API_KEY="sk-..."
pytest -m real_openai

# Real Anthropic API (opt-in)
export ANTHROPIC_API_KEY="sk-ant-..."
pytest -m real_anthropic
```

---

## Trust And Security

- [Architecture](docs/architecture.md)
- [Threat model](docs/threat-model.md)
- [Compatibility matrix](docs/compatibility.md)
- [Security policy](SECURITY.md)
- [Contributing guide](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Changelog](CHANGELOG.md)

---

## License

MIT — see [LICENSE](LICENSE.txt) for details.

---

<p align="center">
  <sub>Built with httpx, openai, anthropic · Backstop Contributors</sub>
</p>
