# Integrations

Backstop has **two native surfaces** and **one wire protocol**. That is the
whole of it, and it is deliberately small:

- **In-process** — `Backstop.wrap(client)` injects the transport into an
  OpenAI or Anthropic Python SDK client. No proxy, no sidecar, no network hop.
- **The gateway** — `backstop serve` runs as an OpenAI-compatible reverse proxy
  in front of any upstream.

Everything else in this document is a consequence of the second one: because
the enforcement engine works on the request and the response rather than on a
provider's identity, **any server that speaks the OpenAI-compatible protocol is
a valid target**.

---

## The four kinds of server

| Server | Speaks | Backstop adds |
| --- | --- | --- |
| OpenAI, Anthropic | their own endpoints | budgets, breaker, concurrency, and a price from the bundled catalogue |
| vLLM, SGLang, llama.cpp, Ollama, LM Studio, TGI | an OpenAI-compatible endpoint | budgets, breaker, concurrency; price it yourself |
| DeepInfRA, Together AI, Groq, Fireworks, OpenRouter, Replicate, Baseten, Cohere, Mistral, NVIDIA | an OpenAI-compatible endpoint | budgets, breaker, concurrency; price it yourself |
| Amazon Bedrock, Azure OpenAI, Google Vertex AI | an OpenAI-compatible gateway | budgets, breaker, concurrency; price it yourself |

There is no per-provider plugin, and there is no need for one. The engine
counts requests, tokens and concurrent calls. It does not need to know who
served the model.

---

## Pointing at an OpenAI-compatible server

### In-process

Give the OpenAI SDK a `base_url` and wrap it. The wrapper keeps the SDK's own
`base_url` — it does not reset it to the provider's default — so the wrapped
client talks to the server you pointed it at.

```python
from decimal import Decimal

from openai import OpenAI
from backstop import Backstop, BackstopConfig

client = Backstop.wrap(
    OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed"),
    budget=50_000,                                   # a token ceiling
    budget_usd=Decimal("50.00"),                     # and a dollar one
    config=BackstopConfig(initial_concurrency=4),
)

client.chat.completions.create(
    model="Qwen/Qwen3-8B",
    messages=[{"role": "user", "content": "hello"}],
)
```

That is the whole integration. Nothing else changes: the client still has the
same methods, the same arguments and the same return value.

The Anthropic SDK is wrapped the same way, against Anthropic's own endpoint.

### As a gateway

When the caller is not a Python process — another service, a Go program, a
shell script — run Backstop in front of the server instead:

```bash
backstop serve --target https://api.deepinfra.com/v1/openai --port 8787
```

The gateway speaks the OpenAI-compatible API, so the caller points at
`http://localhost:8787/v1` instead.

Two things about the gateway worth knowing before you choose it:

- **It buffers.** The upstream response is read in full and then returned. A
  token-by-token stream is not streamed through the gateway. If you need
  incremental streaming, wrap the client in-process instead.
- **A denial is a 502.** An enforcement decision — a budget ceiling reached, a
  circuit open — stops the request and the gateway reports
  `502 upstream request failed`. The detail stays in the log; the response body
  deliberately does not echo an internal exception, because a proxy that does
  hands out hostnames and file paths. The in-process path raises the
  provider's own error type instead, which is catchable.

---

## The price list is the one difference

The limits do not change with the provider. The price list does.

The bundled catalogue prices **OpenAI and Anthropic models** only. A request to
any other host is recorded as `provider="unknown"` and an **unpriced** request,
because the engine refuses to invent a provider it does not recognise — an
invented provider produces a charge-back row that looks authoritative and is
wrong.

That matters the moment a dollar ceiling is in play:

```python
config = BackstopConfig(budget_usd=Decimal("50.00"))
```

With `budget_usd` set and the model unpriced, the request is **refused**:
a dollar ceiling is only enforceable for a model the catalogue prices, and a
ceiling with a hole in it is not a ceiling.

There are two ways forward, and both are explicit.

### File a price

Point `price_catalog_path` at a JSON file. It is layered over the bundled
catalogue, so it only needs the models you actually serve:

```json
{
  "effective_from": "2026-10-01",
  "entries": [
    {
      "model": "Qwen/Qwen3-8B",
      "provider": "unknown",
      "input_per_mtok_usd": "0.30",
      "output_per_mtok_usd": "0.60"
    }
  ]
}
```

```python
config = BackstopConfig(
    budget_usd=Decimal("50.00"),
    price_catalog_path="/etc/backstop/prices.json",
)
```

Money is a decimal string above all else, so `0.30` means exactly `0.30`. Every
entry filed this way is recorded as `source="user"`, `confidence="negotiated"`
— a file a deployment wrote is a rate it agreed to, whatever it was copied
from.

### Say that you mean it

If you would rather let the hole stand than guess, say so:

```python
config = BackstopConfig(
    budget_usd=Decimal("50.00"),
    budget_usd_unpriced_policy="allow",
)
```

The request is then allowed through and recorded as **unpriced** — the same
visible hole the ledger records for every unpriced request, rather than a
plausible wrong number. The token and concurrency limits still apply. Only the
dollar ceiling stops being enforceable.

---

## Frameworks

LangChain and LlamaIndex have adapters. They do not change how enforcement
works — the transport enforces regardless — but they give a framework's own
callback surface a way to carry a tenant id, so a framework run can be
labelled without editing every call site.

See [framework adapters](frameworks.md).

---

## What this does not do

- **It is not a router.** Backstop does not choose a provider, fail over
  between them, or pick the cheapest model. It limits the spend of whichever
  server you pointed it at.
- **It does not make an unpriced model priced.** The default is to refuse a
  dollar budget it cannot measure. Filing a price is a decision you make.
- **It is not a per-provider integration list.** There is no DeepInfRA adapter
  and no vLLM adapter, because the wire protocol is the integration.
