# Compatibility Matrix

Backstop is early-stage. This matrix documents the intended support surface and should be updated whenever provider SDK behavior changes.

> 0.6.0 is unreleased. The intended support below is not a verified SDK-version
> matrix. Current Anthropic SDK wrapping and enforcement-error propagation have
> known failures; see [installation limitations](install.md). SDK dependency
> bounds remain unchanged pending the compatibility decision.

## Python

| Python | Status |
| --- | --- |
| 3.10 | Tested in CI |
| 3.11 | Tested in CI |
| 3.12 | Tested in CI |

## Providers

| Provider | Client | Status | Notes |
| --- | --- | --- | --- |
| OpenAI | `openai.OpenAI` | Supported | Sync client wrapping through `httpx` transport injection |
| OpenAI | `openai.AsyncOpenAI` | Supported | Async client wrapping through `httpx` transport injection |
| Anthropic | `anthropic.Anthropic` | Supported | Optional dependency via `backstop-ai[anthropic]` |
| Anthropic | `anthropic.AsyncAnthropic` | Supported | Optional dependency via `backstop-ai[anthropic]` |

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
