# SDK Compatibility Matrix

Backstop wraps the SDK's internal `httpx` transport. This table shows tested combinations.

## Supported versions

| Provider | SDK range | Python | httpx | Status |
|---|---|---|---|---|
| OpenAI | `>=2.37,<4` | 3.10–3.12 | 0.27–0.29 | ✅ Supported |
| Anthropic | `>=0.98,<2` | 3.10–3.12 | 0.27–0.29 | ✅ Supported |

## CI test matrix

The CI workflow runs all combinations of:

- **OpenAI:** `2.37.0`, `3.14.0`
- **Anthropic:** `0.99.0`, `1.6.0`
- **Python:** `3.10`, `3.11`, `3.12`

Plus a cross-check run with `openai` and `anthropic` at latest.

## Version guard

At `Backstop.wrap()` time, Backstop checks the installed SDK version and emits a `UserWarning` if it is outside the supported range — but does not raise. This allows you to test newer SDKs before they are officially supported.

```python
import warnings
# Suppress if you've tested the version yourself:
warnings.filterwarnings("ignore", category=UserWarning, module="backstop")
```

## Known unsupported versions

| Provider | SDK | Reason |
|---|---|---|
| OpenAI | `<2.37` | Older httpx internal, not bisected |
| OpenAI | `>=4` | Not yet tested |
| Anthropic | `<0.98` | httpx2 migration not complete |
| Anthropic | `>=2` | Not yet tested |

## Checking your environment

```bash
backstop doctor
```

Reports SDK versions and whether each provider's wrap path is working in your current environment.

## httpx / httpx2

OpenAI SDKs `>=3.0` and Anthropic SDKs `>=1.0` migrated from `httpx` to `httpx2`. Backstop detects which library the SDK is using via `src/backstop/_httpcompat.py` and adapts automatically. No configuration needed.
