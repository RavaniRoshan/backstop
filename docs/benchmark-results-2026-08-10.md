# Backstop Benchmark Results

- Date: 2026-08-10
- Seed: `0x00C0FFEE` (deterministic)
- Method: local `httpx.MockTransport`; no network; counts are exact and reproducible.

## Overhead (local mock transport, measured)

| Metric | Direct | Backstop | Overhead |
| --- | ---: | ---: | ---: |
| p50 latency | 0.13 ms | 0.25 ms | **0.12 ms** |
| p95 latency | 0.28 ms | 0.43 ms | **0.15 ms** |
| p99 latency | 0.36 ms | 0.56 ms | **0.20 ms** |

> Latency is measured separately from provider latency. See `benchmarks/local_overhead.py`.

## Scenario results (deterministic, seeded)

| Scenario | Requests | Provider Calls | Successes | Provider Errors | Budget-Blocked | Circuit-Blocked |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| burst | 50 | 50 | 50 | 0 | 0 | 0 |
| steady-state | 30 | 30 | 30 | 0 | 0 | 0 |
| error-storm | 50 | 12 | 8 | 0 | 0 | 42 |
| budget-hit | 80 | 16 | 16 | 0 | 64 | 0 |

## How to reproduce

```bash
backstop benchmark --publish
```
