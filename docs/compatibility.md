# Compatibility Matrix

> 0.6.0 is published (PyPI `backstop-ai`, GitHub Release `v0.6.0`). The SDK
> ranges below are the **tested** ranges from `.github/workflows/ci.yml` — not
> a claim of universal support, and not a claim that every combination is
> exercised. Wrapping an SDK outside these ranges emits a loud `UserWarning`
> naming the tested range (PLAN 1.4.1) and proceeds unverified.
> Enforcement-error propagation (`BudgetExceededError` catchable by user code,
> not `APIConnectionError`) is verified on openai 3.14.0 + anthropic 1.5.0
> (current) and openai 2.37.0 + anthropic 0.99.0 (legacy matrix) via
> `tests/test_guardrail_visibility.py`.
> See [installation limitations](install.md).

## Python

| Python | Status |
| --- | --- |
| 3.10 | Tested in CI |
| 3.11 | Tested in CI |
| 3.12 | Tested in CI |

## Providers

| Provider | Client | Tested SDK range | Verified in CI | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| OpenAI | `openai.OpenAI` | `>=2.37,<4` | 2.37.0, 3.14.0, latest¹ | Supported | Sync wrap; `httpx`/`httpx2` family auto-detected per client |
| OpenAI | `openai.AsyncOpenAI` | `>=2.37,<4` | 2.37.0, 3.14.0, latest¹ | Supported | Async wrap; same family detection |
| Anthropic | `anthropic.Anthropic` | `>=0.98,<2` | 0.99.0, 1.6.0 | Supported | Optional dependency via `backstop-ai[anthropic]`; `httpx2` client on `>=1.0` |
| Anthropic | `anthropic.AsyncAnthropic` | `>=0.98,<2` | 0.99.0, 1.6.0 | Supported | Same as sync |

¹ `latest` is resolved in a single CI cross-check row (Python 3.12, `openai`
latest against `anthropic` 0.99.0), not across the full matrix. Anthropic
`latest` is **not** tracked by CI at all — the 1.5.0 and 1.6.0 figures in the
header note come from `tests/test_guardrail_visibility.py` on a developer
machine, not from the CI matrix. Treat "1.5.0 verified" as a local observation.

CI runs on **ubuntu-latest only**, and installs
`pip install -e ".[test,metrics,anthropic]"` — so the `redis`, `otel`,
`fastapi` and `tokenizers` extras get no CI execution, and neither does the
TypeScript package. See [docs/sdk-matrix.md](sdk-matrix.md#what-ci-actually-proves)
for the full list of what the matrix does and does not cover.

Unsupported: SDKs below the floors (`openai<2.37`, `anthropic<0.98`) — their
request loop catches every transport exception, including Backstop's
`BudgetExceededError`, and re-raises it as `APIConnectionError`, so budget
enforcement is invisible to user code. Bisected 2026-09-18: the
propagate-as-is guard first ships in openai 2.37.0 / anthropic 0.98.0
(openai 2.36.0 / anthropic 0.97.0 lack it). Older SDKs (`openai<1.90`,
`anthropic<0.40`) additionally crash against `httpx>=0.28`, which removed
the `proxies` kwarg. Also unsupported: future majors at/above the ceilings
(`openai>=4`, `anthropic>=2` — none released as of 2026-09-18).
`Backstop.wrap()` warns on these but does not refuse; check with
`backstop verify --live` before relying on an untested version, and read
[the `doctor` caveats](sdk-matrix.md#checking-your-environment) before
trusting a `doctor` exit code.

## Optional Extras

| Extra | Purpose |
| --- | --- |
| `backstop-ai[metrics]` | Prometheus metrics export |
| `backstop-ai[anthropic]` | Anthropic SDK support |
| `backstop-ai[redis]` | Shared/distributed budget across replicas |
| `backstop-ai[otel]` | OpenTelemetry metrics export |
| `backstop-ai[fastapi]` | Gateway/sidecar mode |
| `backstop-ai[tokenizers]` | Optional token counting support |
| `backstop-ai[test]` | Test dependencies |

## Supported Behavior

| Capability | Local Mode |
| --- | --- |
| Global token budget | Supported |
| Tenant token budget | Supported in-process |
| Priority admission | Supported |
| AIMD concurrency | Supported |
| Retry handling | Supported |
| Circuit breaker | Supported (per-tenant opt-in) |
| Streaming | Supported |
| Response caching | Supported (exact + semantic) |
| Fallback chains | Supported (priority-aware) |
| Agent guardrails | Supported |
| Cloud-quota auto-tuning | Supported |
| Cost forecasting → enforcement | Supported |
| Audit log | Supported (tamper-evident) |
| Secret provider | Supported |
| Prometheus metrics | Optional |
| OpenTelemetry | Optional (`otel` extra) |
| Distributed budgets | Optional (`redis` extra) |
| Gateway / sidecar | Optional (`fastapi` extra) |
| Shadow / canary rollout | Supported |
| Hosted control plane | Planned |

"Supported" in this table means the feature ships and is documented. It does
**not** mean CI exercises it. The four rows marked Optional depend on extras
that `.github/workflows/ci.yml` does not install, so the distributed-budget,
OpenTelemetry, gateway and tiktoken paths have no automated coverage today.
The `pyyaml` wedge dependency *is* installed by CI.

## TypeScript package

A separate `backstop-ai` on **npm** implements a subset of the above for the
OpenAI TypeScript SDK. It is not covered by anything in this page: it is a
different interception strategy (`client.chat.completions.create` patching, not
transport injection), has no Anthropic support, roughly half the config surface,
and no CI. Do not read the tables here as describing it.

## Compatibility Policy

Until Backstop reaches a stable 1.0 release:

- Pin provider SDK versions in production if transport compatibility is critical.
- Run unit tests and real-provider smoke tests before provider SDK upgrades.
- Report compatibility issues with the provider issue template.
