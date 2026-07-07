# Benchmarks

Backstop benchmark claims must be reproducible. This project should separate local control-path overhead from provider latency.

## Local Overhead Benchmark

Run:

```bash
python3 benchmarks/local_overhead.py --requests 1000
```

This benchmark compares direct `httpx.MockTransport` calls with the same mock provider through `BackstopTransport`.

The result reports:

- p50, p95, and p99 latency for direct calls
- p50, p95, and p99 latency for Backstop-wrapped calls
- approximate p50 overhead
- provider calls
- remaining budget

## Harness Scenarios

Backstop also ships a CLI harness:

```bash
backstop harness --scenario burst
backstop harness --scenario steady-state
backstop harness --scenario error-storm
backstop harness --scenario budget-hit
```

These scenarios exercise budget blocking, provider pressure, retry behavior, AIMD changes, and circuit breaking.

## Benchmark Rules

- Do not compare local mock-provider results to real provider latency.
- Always report Python version, OS, CPU, and request count.
- Keep benchmark payloads synthetic.
- Do not include real prompts, responses, API keys, or customer data.
- Report Backstop overhead separately from provider latency.

## Latest Snapshot

See [`benchmark-results-2026-07-04.md`](benchmark-results-2026-07-04.md) for the first committed local benchmark snapshot.
