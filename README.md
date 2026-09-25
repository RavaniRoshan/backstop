<div align="center">
  <img width="900" alt="Backstop — in-process AI guardrails" src="docs/assets/backstop-logo.svg" />
</div>

<p align="center">
  <strong>In-process token budget enforcement, circuit breaking, and concurrency control for OpenAI and Anthropic SDK clients.</strong>
</p>

<p align="center">
  <a href="https://github.com/RavaniRoshan/backstop/actions/workflows/ci.yml">
    <img src="https://github.com/RavaniRoshan/backstop/actions/workflows/ci.yml/badge.svg" alt="CI" />
  </a>
  <a href="https://github.com/RavaniRoshan/backstop/blob/main/LICENSE.txt">
    <img src="https://img.shields.io/github/license/RavaniRoshan/backstop" alt="License: MIT" />
  </a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+" />
</p>

---

## The Problem

A runaway agent loop will keep calling the LLM until something stops it. Without an in-process guardrail, the first thing that stops it is your credit card limit.

Your options today:

| Approach | Latency | Complexity | In-process |
|---|---|---|---|
| Hope the agent stops | 0 ms | none | n/a |
| Proxy gateway (LiteLLM, etc.) | +network hop | high | ✗ |
| **Backstop** | **0.07 ms p50** | **one wrap call** | **✓** |

---

## 30-Second Keyless Proof

No API key needed. This runs entirely offline:

```bash
pip install "backstop-ai"
backstop verify
```

Expected output:

```
# Backstop Verify — 30-Second Keyless Proof

Mode: offline (100% local mock transport, zero network, zero API keys)
Provider: openai (gpt-4o-mini simulation)

| Metric            | Result             | Notes                                     |
|-------------------|--------------------|-------------------------------------------|
| Allowed calls     | 2                  | Completed within budget (500 tokens)      |
| Blocked calls     | 8                  | Pre-empted before network dispatch        |
| Tokens reserved   | 500                | Enforced budget ceiling                   |
| Tokens saved      | 2,000              | 8 runaway calls prevented                 |
| Exception surfaced| BudgetExceededError| Caught cleanly (subclasses openai.OpenAIError) |
| Wall-clock overhead| 0.08 ms           | Control-path p99 mediation latency        |

## Mechanism Checks
- [PASS] config valid: BackstopConfig() constructed with sane bounds.
- [PASS] wrap pipeline: Backstop.wrap(client) served a mock request end-to-end.
- [PASS] budget block: 8/10 runaway calls blocked at 500-token budget (saved 2,000 tokens).
- [PASS] overhead: control-path overhead p99 = 0.080 ms (direct p99 0.261 ms). Sub-millisecond-class in-process control path.
- [PASS] cache hit: second identical request served from cache (cache_hits=1).
- [PASS] per-agent isolation: agent A blocked 5/5 at its own cap while agent B kept serving — budgets are independent.
- [PASS] hierarchical budgets: parent exhaustion blocks child; sibling unaffected; most-restrictive-wins enforced.
- [PASS] shadow mode: budget exhausted but 0/10 requests blocked; would_block recorded=10 (enabled!=enforced: observations without denial).

Summary: 8 passed, 0 warn, 0 failed, 0 skipped
Status: VERIFIED (real wrap enforcement active)
```

Everything above the `## Mechanism Checks` line is exact except the overhead
figure, which is a wall-clock measurement and varies with your host. The
check count and pass/fail verdicts are stable. Exit code is 0.

### Two flags worth knowing before you rely on `verify`

- **`--offline` does nothing.** It is accepted and defaults to off, but the
  runner only ever looks at `--live`. Passing `--offline` *together with*
  `--live` still performs the live probe. Omit `--live` if you want no network.
- **`--live` resolves the key per provider.** `--provider anthropic` reads
  `ANTHROPIC_API_KEY` and `--provider openai` reads `OPENAI_API_KEY`; an
  explicit `--api-key-env` always wins. Anthropic is probed with `x-api-key` +
  `anthropic-version`, OpenAI with `Authorization: Bearer`. If `--base-url`
  points at a host other than the provider's default, `verify` prints a
  warning to stderr naming the destination, because your provider credential
  is about to be sent there. The probe is a `GET /models`: it proves the key
  exists, **not** that it has scope, quota, or entitlement for a given model.

See the runaway loop demo:

```bash
backstop demo
```

```
| Calls completed | 10 | 3 | -7 (-70.0%) |
| Calls blocked   | 0  | 7 | +7 (blocked in-process) |
| Tokens consumed | 250| 75| -175 (-70.0%) |
```

---

## Install

`0.6.0` is published — on PyPI as `backstop-ai`, on npm as `backstop-ai`, and
as the `v0.6.0` GitHub Release. `pip install` gives you that release; the
default branch carries unreleased work past it, so the source install below
tracks `main` rather than `v0.6.0`.

```bash
pip install "backstop-ai"             # OpenAI only
pip install "backstop-ai[anthropic]"  # OpenAI + Anthropic
```

> The npm package of the same name is a **partial TypeScript port**, not the
> Python distribution. See [TypeScript](#typescript-partial-port) below.

### From source

```bash
git clone https://github.com/RavaniRoshan/backstop.git
cd backstop
pip install -e ".[anthropic]"
```

---

## Usage

```python
from openai import OpenAI
from backstop import Backstop, BackstopConfig
from backstop.exceptions import BudgetExceededError

client = Backstop.wrap(
    OpenAI(),
    budget=50_000,          # token ceiling for this session
    config=BackstopConfig(
        initial_concurrency=4,
    ),
)

try:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
    )
except BudgetExceededError:
    print("Budget hit — no runaway loop possible.")
```

That's the whole integration. No call-site changes beyond the wrap, and the
default path adds no network hop — see [What It Does Not Do](#what-it-does-not-do)
for the two places where that is not the whole story.

### Per-agent isolation

```python
from anthropic import Anthropic
from backstop import Backstop

agent_a = Backstop.wrap(Anthropic(), budget=10_000)
agent_b = Backstop.wrap(Anthropic(), budget=10_000)
# agent_a exhausting its budget does not affect agent_b
```

### Catching budget errors

```python
from backstop.exceptions import BudgetExceededError

try:
    response = client.chat.completions.create(...)
except BudgetExceededError as exc:
    # BudgetExceededError is also a subclass of openai.OpenAIError /
    # anthropic.AnthropicError, so existing error handling still works.
    log.warning("Budget ceiling reached", extra={"tokens_used": exc.tokens_used})
```

---

## What It Enforces

| Feature | Description |
|---|---|
| Token budgets | Hard ceiling on total tokens per session/agent |
| Per-agent isolation | Each wrapped client has its own independent budget |
| Hierarchical budgets | Parent budget caps all child agents |
| Circuit breaking | Trips on repeated provider errors |
| Concurrency control | Limits parallel in-flight requests |
| Priority admission | Queues and prioritises across `critical` / `default` / `background`; see below |
| Retry + backoff | Configurable exponential backoff with jitter |
| Shadow mode | Observe-without-enforce for safe rollout |

### Priority admission

There are exactly three priorities — `critical`, `default` and `background`
(`backstop.Priority`). There is no `normal`.

The gate **queues and prioritises; it does not shed.** When the concurrency
limit is reached, a request waits for a slot, and a `critical` request is
selected ahead of waiting `default` and `background` ones. It does not cancel
or discard the lower-priority waiters.

To stop a starved ticket waiting forever, `starvation_after_seconds`
(default `1.0`) releases the oldest ticket in any queue once it has waited that
long, even if a higher priority is also waiting. Set it to `0` to disable
starvation protection, and set `queue_timeout` to bound how long any request
will wait before it gets an error instead.

```python
from backstop import Backstop, BackstopConfig

client = Backstop.wrap(
    OpenAI(),
    budget=50_000,
    config=BackstopConfig(starvation_after_seconds=1.0, queue_timeout=10.0),
)
```

---

## What It Does Not Do

- **The default integration path is not a proxy.** When you `Backstop.wrap()`
  an SDK client, no network traffic passes through Backstop — the transport is
  injected in-process and requests go to the provider directly. The package
  *also* ships an optional OpenAI-compatible reverse proxy
  (`backstop serve`, needs the `fastapi` extra) for non-Python or
  hard-to-bypass deployments. That is a different mode with a real network hop;
  it is not what `wrap()` does.
- **Not a hosted control plane.** There is no central Backstop server and no
  shared policy service. Multi-tenant routing is in-process only, and each
  replica holds its own budget unless you opt into the `redis` extra. There is
  **no central key store**, but there is key-adjacent machinery: `virtual_keys`
  maps a caller-supplied key to a tenant id, and `secret_provider` resolves
  keys to provider secrets at call time. That is indirection over keys you
  already hold, not custody of them.
- **Not a multi-provider router.** Use LiteLLM or similar if you need fallback across providers. Backstop's fallback chain stays within one provider.
- **Not observability storage.** Backstop emits metrics; you send them to your own backend.
- **Not LangGraph/CrewAI-native.** Works with those frameworks only at the SDK level, not via framework-specific hooks.

---

## SDK Compatibility

| Provider | SDK range | Python | Status |
|---|---|---|---|
| OpenAI | `>=2.37,<4` | 3.10–3.12 | ✅ Supported |
| Anthropic | `>=0.98,<2` | 3.10–3.12 | ✅ Supported |

CI runs the full matrix (openai 2.37/3.14 × anthropic 0.99/1.6 × python 3.10/3.11/3.12).

Run `backstop doctor` to check your installed versions:

```bash
backstop doctor
```

What `doctor` is, precisely: a wrap-and-import smoke test. It constructs mock
clients, wraps them, and confirms the HTTP-family detection resolves. It does
**not** send a request through the wrapped transport, so it cannot prove
enforcement works — `backstop verify` is the command that does that.

Known caveat: `doctor` imports `httpx2` unconditionally, but `httpx2` is not a
declared dependency (it arrives only as a dependency of newer `openai` /
`anthropic` majors). On an install that resolves to the older SDK family, so
that `httpx2` is absent, `doctor` fails its wrap smoke test and **exits 1**. That
is a `doctor` bug, not a broken install — check whether `httpx2` is importable
before trusting a non-zero exit. `backstop verify` is unaffected.

See [docs/compatibility.md](docs/compatibility.md) for the full version matrix and unsupported version notes.

---

## Architecture

Backstop replaces the SDK's internal HTTP transport with a controlled pipeline:

```
SDK client → BackstopTransport → budget/circuit/concurrency check → original transport → provider
```

No monkey-patching. No import hooks. Backstop detects which HTTP library the
wrapped SDK actually uses — `httpx` on older SDK majors, `httpx2` on
`openai>=3` / `anthropic>=1` — and builds its transport from that same module,
because the two are mutually incompatible. No configuration needed; see
`src/backstop/_httpcompat.py`.

One correction worth stating plainly: **Backstop does not leave the SDK's retry
logic in place.** Wrapping sets the wrapped client to `max_retries=0`, and
Backstop's own transport performs the retries, with Backstop's own backoff and
circuit state. That is deliberate — the guardrail has to be able to see and stop
each individual attempt. The SDK's *authentication* and request-construction
logic does still run above the transport, which is why Backstop's errors
propagate to your code as the provider's own error subclasses.

See [docs/architecture.md](docs/architecture.md) for the full design.

---

## Benchmarks

Control-path overhead, from the committed snapshot
[`docs/benchmark-results-2026-07-20.md`](docs/benchmark-results-2026-07-20.md)
— 1,000 requests through a local `httpx.MockTransport`, no network:

| Percentile | Direct | Backstop | Overhead |
|---|---|---|---|
| p50 | 0.12 ms | 0.19 ms | **0.07 ms** |
| p95 | 0.22 ms | 0.30 ms | **0.07 ms** |
| p99 | 0.30 ms | 0.38 ms | **0.07 ms** |

Those are the only overhead numbers this repository commits. What the snapshot
records about conditions: date 2026-07-20, seed `0x00C0FFEE`, local mock
transport, no network, 1,000 requests. It does **not** record the host CPU, the
OS, the Python version, or the provider SDK version — so read 0.07 ms as one
recorded run, not a guarantee. (An earlier version of this file claimed
~0.09 ms p50 on a named MacBook M1 / openai 3.14 / httpx 0.28 configuration that
no artifact in this repo records; that claim is gone rather than restated.)

Reproduce the measurement yourself:

```bash
backstop benchmark
```

That prints the same table for your host. The counts in it (provider calls,
budget-blocked, circuit-blocked) are deterministic and match the snapshot
exactly; the latencies are wall-clock and will not. The same measurement is also
available standalone, with no CLI, as
`PYTHONPATH=src python3 benchmarks/local_overhead.py --requests 1000`.

The overhead check inside `backstop verify` passes below a **5 ms** p99
threshold — it proves the control path stayed in the sub-millisecond class, not
that it hit any particular figure.

See [docs/benchmarks.md](docs/benchmarks.md).

---

## Examples

All 13 files in `examples/` are listed below. Everything marked **Yes** runs
with no API key and no network; everything marked **No** needs a real key.

| File | Description | Runs offline |
|---|---|---|
| `agent_loop_guard.py` | Runaway loop stopped by a hard budget | **Yes** |
| `anthropic_budget.py` | Anthropic SDK, mock transport | **Yes** |
| `budget_blocking_demo.py` | Raw `BackstopTransport` over `httpx.MockTransport` | **Yes** |
| `prometheus_metrics.py` | Starts the metrics server on :9090 (local, no key) | **Yes** |
| `basic.py` | Minimal OpenAI wrap | No |
| `openai_sync.py` | Synchronous budget guard | No |
| `openai_async.py` | Async budget guard | No |
| `anthropic_sync.py` | Anthropic sync guard | No |
| `anthropic_async.py` | Anthropic async guard | No |
| `fastapi_tenants.py` | Per-tenant budgets (FastAPI) | No |
| `background_priority.py` | Priority admission | No |
| `wedge_basic.py` | Wedge harness, 3 Anthropic runners | No |
| `wedge_openai.py` | Wedge harness, 3 OpenAI runners | No |

Only `agent_loop_guard.py` and `anthropic_budget.py` carry the `# KEYLESS`
header in their docstring. The header is a documentation convention, not a
machine-checked property — this table is the authority.

Run the offline examples:

```bash
python examples/agent_loop_guard.py
python examples/anthropic_budget.py
python examples/budget_blocking_demo.py
```

---

## TypeScript (partial port)

`backstop-ai` on npm is a **partial** TypeScript port, not a mirror of the
Python package:

- It targets the **OpenAI SDK only**. No Anthropic support.
- It intercepts by patching `client.chat.completions.create` rather than by
  injecting a transport, so it is a different interception strategy, not the
  design documented above.
- It covers roughly half the Python `BackstopConfig` surface: budget, circuit,
  retry, fallback, cache, audit, agent guard, admission. No semantic cache, no
  Redis shared budget, no OTel, no gateway, no shadow mode, no Wedge.
- It is **not in CI.** `.github/workflows/ci.yml` is Python-only; the TypeScript
  tests run only when someone runs `npm test` in `ts/backstop/` by hand.

Use the Python package when you need the full feature set or Anthropic. Treat
the npm package as a smaller subset and verify it against your own SDK version.

---

## Contributing

PRs welcome. Run the test suite before opening one:

```bash
pytest tests -q
backstop verify
```

See [CHANGELOG.md](CHANGELOG.md) for release history.

---

## License

MIT — see [LICENSE.txt](LICENSE.txt).