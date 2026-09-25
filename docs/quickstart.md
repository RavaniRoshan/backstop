# Quickstart

Get to a working budget guardrail in under 60 seconds.

## 1. Install

```bash
pip install "backstop-ai"             # OpenAI only
pip install "backstop-ai[anthropic]"  # OpenAI + Anthropic
```

> `0.6.0` is published. To work against unreleased work past that tag:
> ```bash
> git clone https://github.com/RavaniRoshan/backstop.git
> cd backstop && pip install -e ".[anthropic]"
> ```

## 2. Wrap your client

```python
from openai import OpenAI
from backstop import Backstop

client = Backstop.wrap(OpenAI(), budget=50_000)
```

That's it. The wrapped client behaves identically to the original — until the budget is hit.

## 3. Catch the error

```python
from backstop.exceptions import BudgetExceededError

try:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello"}],
    )
except BudgetExceededError:
    print("Budget exhausted — agent loop stopped.")
```

`BudgetExceededError` is a subclass of `openai.OpenAIError` (and `anthropic.AnthropicError` for Anthropic clients), so existing error-handling code continues to work.

## 4. Verify offline (no API key needed)

```bash
backstop verify
```

This proves enforcement works end-to-end using a local mock transport: it wraps
a real SDK client, runs ten requests through a 500-token budget, and shows 2
served and 8 blocked with `BudgetExceededError`. Eight mechanism checks follow
and the command exits 0, with no network and no key. The one figure that varies
per machine is the control-path overhead line.

Use `backstop verify` rather than `backstop doctor` as your compatibility check:
`doctor` is a wrap-and-import smoke test that does not send a request through
the wrapped transport.

## 5. See the guardrail in action

```bash
backstop demo
```

Runs a 10-iteration agent loop, unprotected vs wrapped, side by side. No API key needed.

## 6. Control the traffic you admit

`critical` requests are selected ahead of waiting `default` and `background`
ones; nothing is shed. `starvation_after_seconds` releases an aged ticket so it
cannot wait forever, and `queue_timeout` bounds the wait with an error instead.

```python
from openai import OpenAI
from backstop import Backstop, BackstopConfig

client = Backstop.wrap(
    OpenAI(),
    budget=50_000,
    config=BackstopConfig(starvation_after_seconds=1.0, queue_timeout=10.0),
)
```

---

## Next steps

- [SDK compatibility matrix](sdk-matrix.md)
- [Full install guide](install.md)
- [Architecture](architecture.md)
- [Examples](../examples/)
