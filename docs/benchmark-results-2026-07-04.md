# Benchmark Results: 2026-07-04

These results were collected from a local mock-provider benchmark in the project workspace. They measure Backstop control-path overhead separately from real provider latency.

## Environment

- Date: 2026-07-04
- Command: `.venv/bin/python benchmarks/local_overhead.py --requests 1000 --json`
- Provider: local `httpx.MockTransport`
- Requests: 1,000 direct calls and 1,000 Backstop-wrapped calls
- Payloads: synthetic chat-completion shaped JSON

## Local Overhead

| Metric | Direct | Backstop |
| --- | ---: | ---: |
| p50 latency | 0.1202 ms | 0.1873 ms |
| p95 latency | 0.2243 ms | 0.2950 ms |
| p99 latency | 0.3047 ms | 0.3752 ms |

Approximate p50 overhead: `0.0671 ms`

Provider calls:

- Direct: 1,000
- Backstop: 1,000

Remaining Backstop budget after run: `88,000` tokens

## Harness Scenarios

### Burst

Command: `.venv/bin/backstop harness --scenario burst --json`

| Metric | Value |
| --- | ---: |
| Requests | 50 |
| Successes | 50 |
| Provider calls | 50 |
| Provider errors | 0 |
| Budget-blocked | 0 |
| Circuit-blocked | 0 |
| Error rate | 0.00% |
| p50 latency | 26.25 ms |
| p95 latency | 79.84 ms |
| p99 latency | 86.42 ms |
| Remaining budget | 49,400 |
| Final concurrency | 9 |

### Error Storm

Command: `.venv/bin/backstop harness --scenario error-storm --json`

| Metric | Value |
| --- | ---: |
| Requests | 50 |
| Successes | 13 |
| Provider calls | 28 |
| Provider errors | 7 |
| Budget-blocked | 0 |
| Circuit-blocked | 30 |
| Error rate | 74.00% |
| p50 latency | 27.88 ms |
| p95 latency | 78.70 ms |
| p99 latency | 82.98 ms |
| Remaining budget | 49,844 |
| Final concurrency | 9 |

### Budget Hit

Command: `.venv/bin/backstop harness --scenario budget-hit --json`

| Metric | Value |
| --- | ---: |
| Requests | 80 |
| Successes | 17 |
| Provider calls | 17 |
| Provider errors | 0 |
| Budget-blocked | 63 |
| Circuit-blocked | 0 |
| Error rate | 78.75% |
| p50 latency | 19.94 ms |
| p95 latency | 24.54 ms |
| p99 latency | 38.55 ms |
| Remaining budget | 46 |
| Final concurrency | 9 |

## Interpretation

- The local mock benchmark shows sub-millisecond Backstop overhead in this environment.
- The budget-hit scenario demonstrates pre-flight blocking: 63 requests were blocked before reaching the provider, and provider calls stopped at 17.
- The error-storm scenario demonstrates circuit protection: 30 requests were circuit-blocked while provider calls were limited to 28.

## Caveats

- These are local synthetic results, not real provider latency measurements.
- Results vary by CPU, Python version, load, and benchmark payload shape.
- Real provider benchmarks should report provider latency separately from Backstop overhead.
