# Quickstart

Get to a working budget guardrail in under 60 seconds.

## 1. Install

```bash
pip install "backstop-ai"           # OpenAI only
pip install "backstop-ai[anthropic]"  # OpenAI + Anthropic
```

> **0.6.0 is unreleased.** Until published, install from source:
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

This proves enforcement works end-to-end using a local mock transport. Should complete in under 5 seconds with 8/8 PASS.

## 5. See the guardrail in action

```bash
backstop demo
```

Runs a 10-iteration agent loop, unprotected vs wrapped, side by side. No API key needed.

---

## Next steps

- [SDK compatibility matrix](sdk-matrix.md)
- [Full install guide](install.md)
- [Architecture](architecture.md)
- [Examples](../examples/)
