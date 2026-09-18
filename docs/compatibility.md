# Compatibility Matrix

> 0.6.0 is unreleased. The SDK ranges below are the **tested** ranges from
> `.github/workflows/ci.yml` — not a claim of universal support. Wrapping an
> SDK outside these ranges emits a loud `UserWarning` naming the tested range
> (PLAN 1.4.1) and proceeds unverified. Enforcement-error propagation
> (`BudgetExceededError` catchable by user code, not `APIConnectionError`) is
> verified on openai 3.14.0 + anthropic 1.5.0 (current) and openai 2.37.0 +
> anthropic 0.99.0 (legacy matrix) via `tests/test_guardrail_visibility.py`.
> See [installation limitations](install.md).

## Python

| Python | Status |
| --- | --- |
| 3.10 | Tested in CI |
| 3.11 | Tested in CI |
| 3.12 | Tested in CI |

## Providers

| Provider | Client | Tested SDK range | Verified | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| OpenAI | `openai.OpenAI` | `>=2.37,<4` | 2.37.0, 3.14.0, latest | Supported | Sync wrap; `httpx`/`httpx2` family auto-detected per client |
| OpenAI | `openai.AsyncOpenAI` | `>=2.37,<4` | 2.37.0, 3.14.0, latest | Supported | Async wrap; same family detection |
| Anthropic | `anthropic.Anthropic` | `>=0.98,<2` | 0.99.0, 1.5.0, 1.6.0, latest | Supported | Optional dependency via `backstop-ai[anthropic]`; `httpx2` client on `>=1.0` |
| Anthropic | `anthropic.AsyncAnthropic` | `>=0.98,<2` | 0.99.0, 1.5.0, 1.6.0, latest | Supported | Same as sync |

Unsupported: SDKs below the floors (`openai<2.37`, `anthropic<0.98`) — their
request loop catches every transport exception, including Backstop's
`BudgetExceededError`, and re-raises it as `APIConnectionError`, so budget
enforcement is invisible to user code. Bisected 2026-09-18: the
propagate-as-is guard first ships in openai 2.37.0 / anthropic 0.98.0
(openai 2.36.0 / anthropic 0.97.0 lack it). Older SDKs (`openai<1.90`,
`anthropic<0.40`) additionally crash against `httpx>=0.28`, which removed
the `proxies` kwarg. Also unsupported: future majors at/above the ceilings
(`openai>=4`, `anthropic>=2` — none released as of 2026-09-18).
`Backstop.wrap()` warns on these but does not refuse; verify with
`backstop doctor` before relying on them.

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

## Compatibility Policy

Until Backstop reaches a stable 1.0 release:

- Pin provider SDK versions in production if transport compatibility is critical.
- Run unit tests and real-provider smoke tests before provider SDK upgrades.
- Report compatibility issues with the provider issue template.
