# SDK Compatibility Matrix

Backstop wraps the SDK's internal HTTP transport — `httpx` or `httpx2`,
whichever the wrapped client itself uses. This table shows tested combinations.

## Supported versions

| Provider | SDK range | Python | httpx family | Status |
|---|---|---|---|---|
| OpenAI | `>=2.37,<4` | 3.10–3.12 | `httpx` below openai 3.0, `httpx2` from 3.0 | ✅ Supported |
| Anthropic | `>=0.98,<2` | 3.10–3.12 | `httpx` below anthropic 1.0, `httpx2` from 1.0 | ✅ Supported |

The range is the *tested* range, not a claim that every version inside it is
exercised. Read [What CI actually proves](#what-ci-actually-proves) before
citing this table as evidence.

## What CI actually proves

`.github/workflows/ci.yml` is a single `test` job on **ubuntu-latest** only.
The matrix is:

- **Python:** `3.10`, `3.11`, `3.12`
- **OpenAI:** `2.37.0`, `3.14.0`
- **Anthropic:** `0.99.0`, `1.6.0`
- plus one `include` row: Python `3.12` with `openai` at `latest` and
  `anthropic` at `0.99.0`

That is 12 full combinations plus 1 cross-check. The install step is
`pip install -e ".[test,metrics,anthropic]"`, and the two steps that follow are
`pytest` and `python -m backstop benchmark`.

What that does **not** cover — do not read these as verified:

| Not covered | Consequence |
|---|---|
| Any OS other than `ubuntu-latest` | No macOS or Windows signal at all |
| The `redis`, `otel`, `fastapi`, `tokenizers` extras | Those code paths get no CI execution |
| The TypeScript package in `ts/backstop/` | `npm test` never runs in CI |
| Lint or typecheck | No ruff, mypy, or pyright step exists |
| A coverage threshold | `pytest-cov` is available; no `--cov-fail-under` is configured |
| `openai`/`anthropic` `latest` beyond the one cross-check row | Only that single row tracks `latest` |
| Performance | The benchmark step has no threshold — see [docs/benchmarks.md](benchmarks.md) |

Because `fastapi` is not installed, the `backstop serve` gateway is never
exercised by CI. Because `redis` is not installed, the shared-budget path is
never exercised by CI either.

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
| OpenAI | `<2.37` | Below the propagate-as-is guard: the SDK catches `BudgetExceededError` and re-raises it as `APIConnectionError`. Bisected against 2.36.0. |
| OpenAI | `>=4` | No released version tested; would warn |
| Anthropic | `<0.98` | Same guard is absent below 0.98.0. Bisected against 0.97.0. |
| Anthropic | `>=2` | No released version tested; would warn |

Separately, SDKs below `openai<1.90` / `anthropic<0.40` crash against
`httpx>=0.28`, which removed the `proxies` kwarg. Those are already below the
enforcement floors above.

## Checking your environment

```bash
backstop doctor
```

Two caveats, so you do not read too much into a non-zero exit:

- `doctor` is a **wrap-and-import smoke test**. It builds mock clients, wraps
  them, and checks that HTTP-family detection resolves. It does **not** send a
  request through the wrapped transport, so it cannot prove enforcement works.
  `backstop verify` is the command that does that.
- `doctor` imports `httpx2` unconditionally in its wrap smoke test, but
  `httpx2` is not a declared dependency — it only arrives as a dependency of
  `openai>=3` / `anthropic>=1`. On an install resolving to the older SDK family
  the import fails and `doctor` exits 1. That is a defect in `doctor`, not a
  broken install. `backstop verify` is unaffected.

## httpx / httpx2

OpenAI SDKs `>=3.0` and Anthropic SDKs `>=1.0` migrated from `httpx` to `httpx2`. Backstop detects which library the SDK is using via `src/backstop/_httpcompat.py` and adapts automatically — the module is chosen from the wrapped client's own internal HTTP client, because an SDK rejects an `http` client built from the other module. No configuration needed.
