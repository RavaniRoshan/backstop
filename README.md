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
| **Backstop** | **~0.09 ms p50** | **one wrap call** | **✓** |

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
| Wall-clock overhead| 0.07 ms           | Control-path p99 mediation latency        |

Summary: 8 passed, 0 warn, 0 failed, 0 skipped
Status: VERIFIED (real wrap enforcement active)
```

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

> **0.6.0 is unreleased.** Until published on PyPI, install from source (see below).

```bash
# After PyPI publication:
pip install "backstop-ai"           # OpenAI only
pip install "backstop-ai[anthropic]"  # OpenAI + Anthropic
```

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

That's the whole integration. No proxy, no call-site changes beyond the wrap.

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
| Priority admission | `critical` requests pass when `normal` ones are shed |
| Retry + backoff | Configurable exponential backoff with jitter |
| Shadow mode | Observe-without-enforce for safe rollout |

---

## What It Does Not Do

- **Not a proxy.** No network traffic passes through Backstop; requests go directly to the provider.
- **Not a control plane.** No central server, no key management, no multi-tenant routing.
- **Not a multi-provider router.** Use LiteLLM or similar if you need fallback across providers.
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

See [docs/compatibility.md](docs/compatibility.md) for the full version matrix and unsupported version notes.

---

## Architecture

Backstop replaces the SDK's internal `httpx` transport with a controlled pipeline:

```
SDK client → BackstopTransport → budget/circuit/concurrency check → original transport → provider
```

No monkey-patching. No import hooks. The SDK's own retry and auth logic runs above the transport, so Backstop errors propagate correctly.

See [docs/architecture.md](docs/architecture.md) for the full design.

---

## Benchmarks

Control-path overhead (local, not measuring network):

| Percentile | Overhead |
|---|---|
| p50 | ~0.09 ms |
| p99 | ~0.10 ms |

Measured on a MacBook M1 with openai 3.14 + httpx 0.28. Your numbers will vary; the mechanism is proven in `backstop verify`.

See [docs/benchmarks.md](docs/benchmarks.md).

---

## Examples

All examples in `examples/` that work offline are marked with a `# KEYLESS` header. Live examples require a real API key.

| File | Description | Keyless |
|---|---|---|
| `basic.py` | Minimal OpenAI wrap | No |
| `openai_sync.py` | Synchronous budget guard | No |
| `openai_async.py` | Async budget guard | No |
| `anthropic_sync.py` | Anthropic sync guard | No |
| `anthropic_async.py` | Anthropic async guard | No |
| `agent_loop_guard.py` | Runaway loop example | **Yes** |
| `anthropic_budget.py` | Anthropic offline demo | **Yes** |
| `fastapi_tenants.py` | Per-tenant budgets (FastAPI) | No |
| `background_priority.py` | Priority admission | No |

Run the keyless examples:

```bash
python examples/agent_loop_guard.py
python examples/anthropic_budget.py
```

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