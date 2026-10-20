# Backstop control-path overhead — 2026-10-20

The only committed overhead figures for this project. Measured with
`PYTHONPATH=src python3 benchmarks/local_overhead.py --requests 2000`.

## Conditions

The previous snapshot recorded the date, the seed, the mock transport and the
request count, and nothing else. This one records the host, the OS, the
interpreter and the package versions, because a latency figure without the
conditions it was measured under is not a fact.

- **Host:** Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.39 (x86_64)
- **Python:** CPython 3.12.3
- **Packages:** httpx 0.28.1, openai 2.46.0, anthropic 0.116.0, prometheus-client 0.26.0
- **Transport:** local `httpx.MockTransport`, no network
- **Requests per payload:** 2,000
- **Seed:** none — the request bodies are deterministic per index

## The numbers

| Payload | Direct p50 | Backstop p50 | Overhead p50 | Overhead p95 | Overhead p99 |
|---|---:|---:|---:|---:|---:|
| 94 B | 0.1084 ms | 0.2056 ms | **0.0972 ms** | 0.1278 ms | 0.1318 ms |
| 4096 B | 0.1184 ms | 0.2196 ms | **0.1012 ms** | 0.1342 ms | 0.1105 ms |

## Reading these

**Two payload sizes, deliberately.** The 94-byte one is the body the
previously published 0.07 ms figure used. The 4 KB one is closer to a real
prompt. The overhead is body-proportional — the guardrail reads, parses and
inspects every request, so a larger request costs more to guard — and a
snapshot that only reported the small body would have made the guardrail look
cheaper than it is.

**These are not the old 0.07 ms.** They are larger, and the reason is
recorded: the previous figure was measured on a different host, without the
host, the OS, the interpreter or the package versions, so it could not be
checked on another machine or compared with anything. A number nobody can
reproduce is not a better number for being smaller.

**The overhead is the cost of the guardrail doing its job**: reserving and
reconciling a budget, checking the admission gate, recording the outcome,
publishing the gauges, and (with the ledger on) pricing the request. Turning
the ledger off removes its share; the rest is the ceiling itself.

**What is in the 0.097 ms**, measured on this host:

| | |
|---|---|
| JSON body parsed | once (it used to be twice) |
| Five gauges published | twice, ~3.3 µs each time — the in-flight reading and the final one |
| One labelled counter + one histogram | ~1.5 µs each |
| Quota header scan | only when a provider quota header is present (it used to rebuild a dict of every header, on every response) |
| Spend event + pricing | only when the ledger or the detector is on — ~17 µs, and it is off by default |

**Re-measure it yourself.** The numbers above are one machine on one day:

```bash
backstop benchmark
PYTHONPATH=src python3 benchmarks/local_overhead.py --requests 2000
```

The overhead check inside `backstop verify` passes below a **5 ms** p99 bound.
That proves the control path stayed in the sub-millisecond class; it does not
pin a figure.
