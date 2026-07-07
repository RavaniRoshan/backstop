# Compatibility Matrix

Backstop is early-stage. This matrix documents the intended support surface and should be updated whenever provider SDK behavior changes.

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
| Anthropic | `anthropic.Anthropic` | Supported | Optional dependency via `backstop[anthropic]` |
| Anthropic | `anthropic.AsyncAnthropic` | Supported | Optional dependency via `backstop[anthropic]` |

## Optional Extras

| Extra | Purpose |
| --- | --- |
| `backstop[metrics]` | Prometheus metrics export |
| `backstop[anthropic]` | Anthropic SDK support |
| `backstop[tokenizers]` | Optional token counting support |
| `backstop[test]` | Test dependencies |

## Supported Behavior

| Capability | Local Mode |
| --- | --- |
| Global token budget | Supported |
| Tenant token budget | Supported in-process |
| Priority admission | Supported |
| Retry handling | Supported |
| Circuit breaker | Supported |
| AIMD concurrency | Supported |
| Streaming | Supported |
| Response caching | Supported |
| Prometheus metrics | Optional |
| Distributed budgets | Planned |
| OpenTelemetry | Planned |
| Hosted control plane | Planned |

## Compatibility Policy

Until Backstop reaches a stable 1.0 release:

- Pin provider SDK versions in production if transport compatibility is critical.
- Run unit tests and real-provider smoke tests before provider SDK upgrades.
- Report compatibility issues with the provider issue template.
