# Contributing

Thanks for helping improve Backstop. This project is optimized for practical LLM spend control: budgets, backpressure, retries, circuit breaking, fallbacks, metrics, and provider SDK compatibility.

## Local Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[test,metrics,anthropic]"
pytest
```

## Development Guidelines

- Keep the local SDK path useful without a hosted service.
- Do not send prompt payloads to external services by default.
- Prefer provider SDK compatibility over custom HTTP API abstractions.
- Add tests for budget, retry, circuit, streaming, metrics, or wrapper behavior when changing those paths.
- Keep public APIs typed and documented.
- Avoid broad refactors in feature PRs.

## Pull Request Checklist

- Tests pass with `pytest`.
- New behavior has tests or a clear reason tests are not practical.
- Docs or examples are updated when public behavior changes.
- Security and privacy implications are called out.
- Provider SDK compatibility impact is described.

## Real Provider Tests

Real API tests are opt-in and require credentials:

```bash
export OPENAI_API_KEY="..."
pytest -m real_openai

export ANTHROPIC_API_KEY="..."
pytest -m real_anthropic
```

Do not include real API keys, prompts, responses, or customer data in issues, tests, fixtures, screenshots, or logs.
