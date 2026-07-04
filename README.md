# Backstop

Backstop wraps OpenAI Python SDK clients with in-process controls for:

- conservative token budget enforcement
- priority-aware admission and backpressure
- AIMD concurrency control
- retry handling for provider pressure and transient failures
- circuit breaking
- optional Prometheus metrics
- a local mock-provider load harness

V1 supports `openai.OpenAI` and `openai.AsyncOpenAI` only. Integration is through the SDK-supported `http_client` option and custom `httpx` transports.

## Install

```bash
pip install backstop
pip install "backstop[metrics]"
```

From this repository:

```bash
pip install -e ".[test,metrics]"
```

## Usage

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

Async clients are supported the same way:

```python
from openai import AsyncOpenAI
from backstop import Backstop

client = Backstop.wrap(AsyncOpenAI(api_key="sk-..."), budget=10_000)
```

`budget=None` means unlimited pass-through. `budget=0` blocks requests before dispatch.

## Priority

Set priority per request with:

```python
extra_headers={"X-Backstop-Priority": "critical"}
```

Valid values are `critical`, `default`, and `background`. V1 prioritizes queued admission; it does not cancel active background HTTP requests.

## Metrics

Metrics are recorded when `prometheus-client` is installed. Backstop never starts a server implicitly:

```python
from backstop import Backstop

Backstop.start_metrics_server(port=9090)
app = Backstop.metrics_app()
```

## CLI

```bash
backstop harness --scenario burst
backstop harness --scenario steady-state
backstop harness --scenario error-storm
backstop harness --scenario budget-hit
backstop metrics --port 9090
```

The harness uses a local mock OpenAI-compatible provider and does not call real OpenAI services.

For a real provider smoke test, install the OpenAI SDK, set your API key, and run:

```bash
export OPENAI_API_KEY="sk-..."
backstop real-openai --model "${OPENAI_MODEL:-gpt-5.5}"
backstop real-openai --async-client --model "${OPENAI_MODEL:-gpt-5.5}"
```

This sends a tiny Responses API request through a Backstop-wrapped `OpenAI` or `AsyncOpenAI` client. The model can be overridden with `--model` or `OPENAI_MODEL`.

For OpenAI-compatible endpoints, set `OPENAI_BASE_URL` or pass `--base-url`:

```bash
export OPENAI_BASE_URL="https://your-compatible-provider.example/v1"
backstop real-openai --api chat --model "$OPENAI_MODEL" --base-url "$OPENAI_BASE_URL"
```

## Real OpenAI Tests

The regular test suite does not spend tokens. Real API tests are opt-in:

```bash
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="gpt-5.5"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # optional
pytest -m real_openai
```

## Notes

Token estimation is intentionally conservative. When provider `usage` is present, Backstop reconciles reservations against actual usage. When usage is absent on successful responses, the reserved estimate remains charged.
