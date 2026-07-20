# Backstop Benchmark Results

- Date: 2026-07-20
- Seed: `0x00C0FFEE` (deterministic)
- Method: local `httpx.MockTransport`; no network; counts are exact and reproducible.

## Overhead (local mock transport, 1,000 requests)

| Metric | Direct | Backstop | Overhead |
| --- | ---: | ---: | ---: |
| p50 latency | 0.12 ms | 0.19 ms | **0.07 ms** |
| p95 latency | 0.22 ms | 0.30 ms | **0.07 ms** |
| p99 latency | 0.30 ms | 0.38 ms | **0.07 ms** |

> Latency is measured separately from provider latency. See `benchmarks/local_overhead.py`.

## Scenario results (deterministic, seeded)

| Scenario | Requests | Provider Calls | Successes | Provider Errors | Budget-Blocked | Circuit-Blocked |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| burst | 50 | 50 | 50 | 0 | 0 | 0 |
| steady-state | 30 | 30 | 30 | 0 | 0 | 0 |
| error-storm | 50 | 15 | 11 | 0 | 0 | 39 |
| budget-hit | 80 | 16 | 16 | 0 | 64 | 0 |

## How to reproduce

```bash
backstop benchmark --publish
```
