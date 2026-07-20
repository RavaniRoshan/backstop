# Concurrency & Scale Limits

Backstop runs **in your process**, so it inherits Python's execution model. This
page documents where that helps, where it bites, and how to stay safe.

## The GIL ceiling

Under CPython, all Backstop logic (budget reservation, circuit-breaker state
transitions, retry/backoff) executes under the **global interpreter lock**. That
is usually a non-issue — these are microsecond-scale in-memory operations and
the real cost is waiting on the provider's network I/O, which *does* release the
GIL. But it means:

- **10 / 20 / 50 concurrent `wrap()` sessions in one process** is fine for
  typical request workloads — they spend ~99% of their time awaiting the model
  API, not holding the lock.
- **Hundreds of CPU-bound, synchronous sessions** in one process will serialize
  and degrade tail latency. This is the same ceiling every in-process library
  (and every async framework) faces; it is not a Backstop bug.

**Takeaway:** if you need very high fan-out, run **one process per agent / per
tenant** rather than one giant process. Backstop is designed for exactly this —
each `wrap()` is a single line and is isolated.

## Configurable ceiling

To keep the ceiling from being a *surprise*, set a soft cap. When live
`wrap()` sessions exceed `max_wrap_sessions`, Backstop emits a `UserWarning`
instead of silently degrading:

```python
from openai import OpenAI
from backstop import Backstop, BackstopConfig

# Warn if more than 64 live sessions accumulate in this process.
config = BackstopConfig(max_wrap_sessions=64)
client = Backstop.wrap(OpenAI(), budget=50_000, config=config)
```

`max_wrap_sessions=0` (the default) disables the check.

## Shared budget across replicas

For multi-replica / multi-process deployments, don't scale threads — scale
processes and share **one** budget via Redis (Tier 1 / P1):

```bash
pip install "backstop[redis]"
```

```python
from openai import OpenAI
from backstop import Backstop, BackstopConfig

client = Backstop.wrap(
    OpenAI(),
    budget=1_000_000,
    config=BackstopConfig(shared_budget=True, redis_url="redis://localhost:6379"),
)
```

Redis operations use atomic Lua scripts, so N processes decrement the same cap
without a race. This is the recommended path for "AI SaaS with runaway spend"
and keeps the per-process GIL ceiling irrelevant to correctness (only to
throughput).

## Thread safety

- In-memory budget + circuit state use `threading.Lock`, so they are safe to
  share across threads in one process.
- The async transport uses `asyncio` locks; do not mix the sync and async
  clients on the same wrapped object.
- `BackstopConfig` is immutable after construction (validated once). Reuse one
  instance across sessions.

## When to use a proxy gateway instead

If you need **per-tenant request routing, key vaulting, or multi-language
services behind one endpoint**, a proxy (LiteLLM, BricksLLM) is a better fit.
Backstop's wedge is that for *single-language Python* services you get the same
controls with **zero infra and a one-line drop-in**. Pick the proxy when your
topology is inherently multi-language or multi-team at the network edge.
