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

## How CI uses this

`.github/workflows/ci.yml` runs one step labelled "Run benchmark smoke":

```yaml
- name: Run benchmark smoke
  run: python -m backstop benchmark
```

Read that as a **smoke test, not a regression gate.** The command exits 0 as
long as the benchmark harness runs at all. There is no threshold comparison
against any committed baseline, no stored artifact from the run, and no
annotation of the result on the PR. A genuine performance regression — overhead
tripling, or the deterministic scenario counts changing — will not fail the
build. You have to read the output yourself.

For the same reason, do not treat a green CI badge as evidence that overhead is
still in the sub-millisecond class. `backstop verify` has an internal
5 ms p99 bound (`src/backstop/verify.py`), but that runs from your shell, not
from CI.

## What the committed snapshot does and does not pin

[`benchmark-results-2026-10-20.md`](benchmark-results-2026-10-20.md) records
the overhead over 2,000 requests against a local `httpx.MockTransport`, with
no network, at **two payload sizes** — 94 bytes and 4 KB — because the
overhead is body-proportional and a single small body made the guardrail look
cheaper than it is.

That snapshot records the host, the OS, the interpreter and the package
versions, which the previous one did not. It also records a larger overhead
figure than the previous snapshot's 0.07 ms. The figure is not comparable to
the old one — different host, different conditions, and the old one recorded
too little to check — and the difference is stated rather than smoothed over.

The 2026-07-20 snapshot is kept for history. It is superseded.

**Nothing in that file reproduces digit-for-digit, including the counts.** The
seed makes the *input sequence* deterministic, not the outcome of every path.
Two independent kinds of wall-clock dependence are baked in:

- **Latencies**, obviously. Re-running on the same machine moves them.
- **Scenario counts for the timing-dependent scenarios.** `error-storm`
  exercises retry backoff and circuit cooldown, and `budget-hit` competes
  requests against that same machinery. Both are wall-clock timers, so their
  counts can differ between runs on one host and between hosts.

Concretely, against the current tree:

| Scenario | Snapshot (2026-07-20) | Re-running now | Reproduces? |
|---|---|---|---|
| `burst` | 50 requests / 50 provider calls / 50 successes | same | yes |
| `steady-state` | 30 / 30 / 30 | same | yes |
| `error-storm` | 50 / **15** / **11** / **39** circuit-blocked | 50 / **12** / **8** / **42** circuit-blocked | **no** |
| `budget-hit` | 80 / 16 / 16 / **64** budget-blocked | usually 80 / 16 / 16 / 64, sometimes 80 / 18 / 18 / 62 | **not always** |

So: `burst` and `steady-state` are safe to compare across runs. Treat
`error-storm` and `budget-hit` as indicative only. The snapshot also does not
record the host CPU, OS, Python version, or provider SDK version, so a
difference between two snapshots cannot be attributed to a cause.

Report the conditions alongside any number, per the rules above.

## Benchmark Rules

- Do not compare local mock-provider results to real provider latency.
- Always report Python version, OS, CPU, and request count.
- Keep benchmark payloads synthetic.
- Do not include real prompts, responses, API keys, or customer data.
- Report Backstop overhead separately from provider latency.

## Latest Snapshot

See [`benchmark-results-2026-10-20.md`](benchmark-results-2026-10-20.md) for
the current committed local benchmark snapshot.

Regenerate it with:

```bash
PYTHONPATH=src python3 benchmarks/local_overhead.py --requests 2000
```

which prints the table **and** the environment it was measured in — the host,
the OS, the interpreter, the package versions, and both payload sizes. Copy
the output into a dated `docs/benchmark-results-<date>.md` and commit it, so a
regeneration is a diff you review rather than a silent update of the existing
snapshot.
