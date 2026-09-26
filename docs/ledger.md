# The Spend Ledger

Backstop can tell you how many tokens a request cost before it happens. This page
is about the part that tells you, after the fact, **what the last day of traffic
actually cost, grouped by whoever is responsible for it** — and says so in a
form finance can use.

It is off by default. Turning it on adds one record per completed provider
request, priced in `Decimal` from a bundled rate card, and it never puts a file
open or a network call on the request path.

## What it is

- A `SpendEvent` per completed provider request: provider, model, endpoint,
  priority, outcome, four token counts, latency, retries, your attribution, and
  a priced cost breakdown.
- An ambient attribution context, so a call site says *who is spending this*
  once, at the top of the function that spends it.
- A price catalog with three precedence layers, and `Decimal` money end to end.
- A charge-back aggregator and an RFC 4180 CSV export, with the honesty columns
  (unattributed, unpriced, estimated) sitting next to the money.
- A runaway-spend detector that reports four kinds of unusual spending and, by
  default, blocks nothing.
- Three CLI subcommands: `backstop ledger demo`, `show` and `export`.

## What it is not

- **Not a metrics backend.** It writes a file, or keeps a bounded in-memory ring.
  Nothing ships to a collector, nothing is queried over HTTP, nothing is retained
  for longer than the file you chose.
- **Not a revenue system.** It never infers, allocates or fetches revenue. It
  joins cost against a revenue map *you* supply, on group keys you choose, and
  shows a visible `(none)` wherever either side is missing.
- **Not an enforcement primitive for spend.** The detector reports; it cannot
  block, cancel or kill. Spend *avoided* is not in the ledger either — see
  [Limitations](#known-limitations).
- **Not a cross-customer benchmark.** Nothing in it aggregates across
  deployments, and there is no published figure of what "normal" cost is.
- **Not exact.** It prices the token counts the provider reported, from a rate
  card that is a dated snapshot, and where either is missing it says so in a
  column rather than filling the hole.

---

## Quickstart

One flag, on a real client:

```python
from openai import OpenAI
from backstop import Backstop, BackstopConfig, attribution

client = Backstop.wrap(
    OpenAI(),
    budget=500_000,
    config=BackstopConfig(ledger_enabled=True, ledger_path="ledger.jsonl"),
)

with attribution(team="payments", feature="checkout-v2"):
    client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Hello"}],
    )
```

Every completed request now appends one line to `ledger.jsonl`. Read it back:

```bash
backstop ledger show --path ledger.jsonl
backstop ledger export --path ledger.jsonl --out chargeback.csv --group-by team,feature
```

No key and no file needed for the pitch:

```bash
backstop ledger demo
```

Three config fields do the wiring; all default to off or to a usable value, so
an existing `BackstopConfig()` is unchanged.

| field | default | what it does |
|---|---|---|
| `ledger_enabled` | `False` | master switch. With it off, the whole per-request cost is one truth test and no event is built |
| `ledger_path` | `None` | when set, append NDJSON to this path; parent directories are created on the first write |
| `ledger_memory_events` | `10_000` | with no path, the size of the in-memory ring |
| `price_catalog_path` | `None` | a JSON catalog of your own rates, layered over the bundled list prices. Checked at construction, so a typo fails at `wrap()` rather than silently pricing everything at the bundled rate |
| `detection_enabled` | `False` | the runaway-spend detector. Shadow-first: on by itself it reports and never blocks |

---

## The `SpendEvent` schema

One record per completed provider request. Frozen, validated on construction, and
round-trippable: `SpendEvent.from_dict(SpendEvent(...).to_dict()) == SpendEvent(...)`.
`schema_version` is the literal `"1.0"`.

| field | type | meaning |
|---|---|---|
| `event_id` | `str` | 32 lowercase hex characters, a version-4 UUID written directly into random bytes |
| `occurred_at` | `str` | RFC 3339 UTC with exactly six fractional digits: `2026-09-26T13:01:46.964576Z`. Fixed width, so string order is chronological order |
| `schema_version` | `str` | `"1.0"` |
| `provider` | `str` | `openai` or `anthropic`, matched from the request host. A host that is neither is `unknown`, which is therefore unpriced |
| `model` | `str` | what the **response** reported, not what the request asked for — a measurement of what was billed |
| `endpoint` | `str` | the full request URL, normalised: no query string, no fragment, no `user:pass@`. A credential-shaped query parameter is recorded as `?<redacted>` so the reader can see one was there without the value being stored |
| `priority` | `str` | `critical`, `default` or `background` |
| `outcome` | `str` | `success`, `error` or `fallback`. The vocabulary is wider (`circuit_open`, `budget_denied`, `queue_timeout` are reserved); see [Limitations](#known-limitations) |
| `input_tokens` | `int` | the **fresh, non-cached** prompt tokens — the ones a rate card charges at the full input rate |
| `output_tokens` | `int` | completion tokens |
| `cache_read_tokens` | `int` | cached prompt tokens read |
| `cache_write_tokens` | `int` | prompt tokens written to the cache |
| `latency_ms` | `float` | wall clock from entering the transport to this record |
| `retries` | `int` | attempts after the first |
| `estimated` | `bool` | `True` when the token counts are a local floor rather than a provider report. **Read this before any total** |
| `attribution` | `Attribution` | thirteen optional strings, below |
| `cost` | `CostBreakdown \| None` | `None` when no price is known. The absence is the record |
| `request_id` | `str \| None` | `x-request-id` or `request-id` off the response, so a row joins to a provider dashboard |

The four token counts are validated as `int` and `>= 0` on construction — `True`
is refused by name, because `bool` is an `int` subclass. A persisted line must
carry *exactly* the 18 declared fields: an unknown key and a missing key are both
`ValueError`s naming every offender, so a typo or a truncation cannot reload as
plausible data.

`Attribution` fields, all optional: `team`, `agent`, `session`, `task`,
`feature`, `surface`, `customer`, `tenant`, `environment`, `repo`, `cost_center`,
`gl_code`, `currency`.

Every amount on the wire is a **string** (`"0.010000"`), never a JSON number. A
JSON number is read back as a binary float, and a finance export that loses cents
is worse than one that is awkward to parse.

---

## Attribution

Three forms, imported from the top-level package. The transport reads the active
value when it builds each event, so nothing else in your code changes.

```python
from backstop import attribution, with_attribution, current_attribution

# 1. a block
with attribution(team="payments", feature="checkout-v2", customer="acme"):
    client.chat.completions.create(...)

# 2. a function or method, sync or async
@with_attribution(agent="refund-bot")
def handle_refund(ticket):
    ...

# 3. read it back
current_attribution().team
```

`current_attribution()` never returns `None`; in a process that has declared
nothing it returns an all-`None` `Attribution`, which is a valid record.

Nesting merges, and the outer value is restored on exit including when the body
raises. Both halves of this are in the output below — the inner scope sets two
fields, keeps the outer two, and the decorator on a separate function lands in
its own row:

```python
import httpx

from backstop import BackstopConfig, attribution, with_attribution
from backstop.ledger import build_chargeback
from backstop.ledger.export import render_chargeback_markdown
from backstop.state import BackstopState
from backstop.transports import BackstopTransport


def handle(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl_doc",
            "object": "chat.completion",
            "model": "gpt-4o-2024-08-06",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 2_000, "completion_tokens": 500, "total_tokens": 2_500},
        },
    )


state = BackstopState.create(
    100_000,
    BackstopConfig(
        default_max_output_tokens=500,
        retry_max_attempts=1,
        ledger_enabled=True,
    ),
)
client = httpx.Client(
    transport=BackstopTransport(state, httpx.MockTransport(handle)),
    base_url="https://api.openai.com",
)


def call(text: str) -> None:
    client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": text}]},
    )


with attribution(team="payments", feature="checkout-v2", customer="acme"):
    call("authorize a card")
    with attribution(agent="refund-bot", environment="prod"):
        call("refund ticket 8821")
    call("capture a card")


@with_attribution(team="support", feature="triage")
def triage(ticket: int) -> None:
    call(f"triage ticket {ticket}")


triage(4711)

client.close()
report = state.close()
print(f"submitted={report.submitted} landed={report.landed} lost={report.lost}")
print(render_chargeback_markdown(build_chargeback(state.ledger.sink.events)))
```

```
submitted=4 landed=4 lost=0
| team | feature | request_count | input_tokens | output_tokens | total_usd | unpriced_requests | unpriced_components |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| payments | checkout-v2 | 3 | 6000 | 1500 | 0.03 | 0 | (none) |
| support | triage | 1 | 2000 | 500 | 0.01 | 0 | (none) |
```

Three rules worth knowing before you rely on it:

- **A blank is not a value.** `None` and an empty or whitespace-only string both
  mean *unset*, so an environment variable that arrived empty cannot erase the
  value an outer scope set. A field passed as `None` means "do not override".
- **The value lives in a `ContextVar`**, so it follows `asyncio` tasks and any
  thread-pool submission that copies context. A bare `executor.submit` or
  `loop.run_in_executor` does **not** copy context and would record an empty
  attribution — copy it explicitly:

  ```python
  import contextvars

  ctx = contextvars.copy_context()
  loop.run_in_executor(executor, ctx.run, blocking_call, arg)
  ```

- **`with_attribution` refuses a deferred body.** A generator function, an async
  generator function, or a plain function returning a coroutine or generator is
  refused with `TypeError` rather than leaving the ledger silently unattributed.
  Scope the deferred body instead:

  ```python
  def stream_refunds(handle, ticket):
      def events():
          with attribution(agent="refund-bot"):
              yield handle(ticket)

      return events()
  ```

  An `asyncio.Future`/`Task` is allowed through, because the work was scheduled
  inside the scope and the task copied the context there.

An unknown field name, or a non-string value, raises `TypeError` at the call
rather than being dropped from the ledger.

---

## The price catalog

A `PriceEntry` is one model's rates in USD per million tokens, with its
provenance. `PriceCatalog.resolve(provider, model)` returns one, or `None`.

**Precedence, highest wins:**

1. an explicit per-call `price_overrides` passed to `compute_cost` — `price_source="override"`
2. your catalog file, `config.price_catalog_path` — `price_source="user"`
3. the bundled table — `price_source="bundled"`

Each layer is searched in full, across every name tier, before the next is
consulted. A user price for `gpt-4o` beats a bundled price for the exact string
`gpt-4o-2024-08-06`, because your layer is the higher one.

**Name resolution is three tiers:** the exact string, then the name with a
trailing snapshot marker stripped repeatedly (`-2024-08-06` OpenAI, `-20241022`
Anthropic, `-latest`), then a fixed alias map. So a dated snapshot, an
`-latest` alias and `claude-3.5-sonnet` all resolve.

**An unknown model is `None`, not a guess.** `compute_cost` returns `None`, the
event is recorded with `cost=None`, and the export counts it in
`unpriced_requests`. There is no default rate and no neighbouring-model fallback,
because a charge-back that is quietly wrong is worse than one that is absent.

**`cache_write` is separate.** A component the rate card publishes no rate for is
charged zero *and marked* in `CostBreakdown.priced_components`, so a row can say
its cache-write line is a floor instead of presenting a zero as a measurement.

Your own rates, from a JSON file:

```json
{
  "effective_from": "2026-10-01",
  "entries": [
    {
      "model": "gpt-4o",
      "provider": "openai",
      "input_per_mtok_usd": "2.10",
      "output_per_mtok_usd": "8.40",
      "cache_read_per_mtok_usd": "1.05"
    }
  ]
}
```

```python
from backstop.ledger import PriceCatalog

catalog = PriceCatalog.from_file("prices.json")
for model in ("gpt-4o", "gpt-4o-2024-08-06", "no-such-model"):
    entry = catalog.resolve("openai", model)
    print(model, entry.input_per_mtok_usd if entry else "no price")
```

```
gpt-4o 2.10
gpt-4o-2024-08-06 2.10
no-such-model no price
```

Every entry in a file you supply is filed as `source="user"`,
`confidence="negotiated"`: a rate a deployment wrote down is a rate it agreed to,
whatever it was copied from. Write money as a string; a JSON number is accepted
and read back through its shortest repr, so a hand-written `2.10` means exactly
`2.10`.

The arithmetic runs under the ledger's own `decimal` context — 28 significant
digits, `ROUND_HALF_UP`, every field named — never the host process's. A
`decimal` context is process-global and a library cannot ask the host to leave it
alone, so an application that tightened `prec` would otherwise void every cost
here silently: the request still succeeds, the ledger records nothing, and every
total is wrong by a rounding step nobody asked for.

---

## The charge-back export

`build_chargeback(events, group_by=("team", "feature"))` aggregates events into
one row per group, largest total first. `group_by` is validated against the
`Attribution` fields, so any of the thirteen dimensions works and an unknown one
is an error rather than a silently dropped column.

Columns, in export order — group keys first, then:

| column | what it is |
|---|---|
| `request_count` | requests in the group |
| `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens` | the four counts, summed |
| `total_usd` | the exact sum, rendered to 2 decimal places as a string |
| `currency` | `USD` |
| `price_source` | the layer that billed the group, `mixed` if more than one, `(none)` if nothing was priced |
| `unpriced_requests` | requests with `cost=None`. Their dollars are **absent, not zero** |
| `estimated_requests` | requests whose tokens are a local floor. Same population as `request_count`; **may overlap `unpriced_requests`** — a request that is both is in each |
| `unpriced_components` | token components the group carried tokens for with no published rate. `(none)` when every component was priced |
| `first_seen`, `last_seen` | RFC 3339 UTC, the group's window |

An unset group key renders as `(unattributed)`, never as a blank cell — an
unattributed dollar is the thing finance most needs to see, and a blank cell is
the one thing that hides it. There is no totals row in the CSV: a totals line
inside a table somebody intends to `SUM` is a double count waiting to happen.

```bash
backstop ledger export --path ledger.jsonl --out chargeback.csv --group-by team,feature
```

```
wrote 6 row(s) to chargeback.csv from 1967 event(s) in ledger.jsonl — 34.56 USD total, 34 unpriced, 1.54 unattributed
```

`revenue_join(rows, revenue_map)` emits a second CSV keyed on the same group
tuple: `request_count`, `total_usd`, `revenue_usd`, `margin_usd`, `match`,
`currency`. A group missing on one side carries `(none)` and a `match` column
naming the case — `both`, `cost_only` or `revenue_only` — because `margin_usd` is
absent unless both sides are present. A float revenue figure is refused rather
than read through its shortest repr.

---

## Delivery, and the loss numbers

Two reports, and they do not answer the same question.

**From a live writer** (`state.close()`, or `delivery_report(writer)`) — the only
place the process-local counters exist:

| counter | meaning |
|---|---|
| `submitted` | every call to `writer.submit`, including the ones refused |
| `written` | writes the sink *returned from* — an upper bound on records, not a count of them |
| `landed` | `written` less the failures the sink counted itself. **This is the number of records a reader of the file will find** |
| `dropped_events` | submits refused because the bounded buffer was full, plus anything discarded at an unfinished close |
| `sink_errors` | writes that *raised* out of the sink |
| `sink_reported_errors` | writes the sink returned from without raising and did not record |
| `sink_degraded` | the sink says it has stopped appending |
| `lost` | `dropped_events + sink_errors + sink_reported_errors`, through one shared function so the shutdown and live paths cannot disagree |

The accounting invariant is `submitted == written + dropped_events +
sink_errors`, asserted only when the report says `drained`.

**From a file** (`backstop ledger show --path ...`) — a JSONL line records an
event, never a counter. So a file read reports `dropped_events: unknown` and
`sink_errors: unknown` **with the reason**, rather than as `0`, because a zero is
a claim about a process it cannot see. The one loss a file *can* prove is a torn
final line:

- a final line that will not parse → reported as a torn write, the rest is read,
  exit 0;
- a final line that is unterminated but parses → reported, and **kept**, because
  dropping a complete event loses a dollar;
- an unparseable line anywhere **other** than the end → real corruption. The
  command names the line number, exits 1, and `export` writes nothing, because a
  charge-back that silently skips rows is worse than a failed command.

```bash
backstop ledger show --path ledger.jsonl      # exit 0
backstop ledger show --path missing.jsonl     # exit 1, message on stderr
```

`BoundedWriter` never blocks the caller. It is one short lock, one append to a
bounded `deque`, return; the sink's own work — including opening the JSONL file
— happens on a single daemon thread. **Overflow refuses the incoming event** and
counts it, rather than buffering without bound or silently evicting the oldest.
`close()` joins that thread with a bounded timeout, so a stalled sink cannot hang
shutdown; if the join expires the backlog is discarded and reported as
`undrained` rather than written after `close()` returned.

---

## Detection, and shadow mode

`detection_enabled=True` builds a `RunawayDetector` over a bounded window of the
last `detection_window_size` events **per attribution key**, and evaluates four
things on every submission:

| signal | fires when |
|---|---|
| `velocity` | priced spend in the window over the minutes it spans exceeds `detection_velocity_threshold_usd_per_min` |
| `drift` | mean tokens per request over the *recent* half of the window exceeds `detection_baseline_multiplier` × the *older* half |
| `context_growth` | this request's input tokens exceed the rest of the window's median by `detection_context_growth_threshold` |
| retry amplification | mean retries per request exceeds `detection_retry_ratio_threshold` |

Two of those choices are deliberate and worth stating. The window is split in
half and the older half is the reference period, because over one shared window
the median follows a sustained step change and a doubling stays silent forever.
And an **unpriced** event contributes zero to the velocity numerator while still
being observed for tokens and retries — padding it with a guessed rate would make
a finance-facing figure look measured.

Each signal is a frozen record: `kind`, `severity`, `key`, `observed`,
`threshold`, `detail`, `occurred_at`. It cannot block a request, cancel work, kill
an agent, or raise. That is structural, not a promise: nothing exported returns a
decision, and a test walks the public API for a verb that could act on a request.
Auto-kill is absent on purpose — an agent run can be six hours of work, and a
kill switch that cannot resume destroys it.

**Shadow mode is the default** (`detection_shadow=True`). In shadow, the same
signals are produced and also filed in a bounded log with a per-kind counter, so
a threshold can be tuned against evidence before it can interrupt anybody.
`BACKSTOP_DETECTION_SHADOW` overrides the config in both directions, so a
detector switched on by an over-eager edit can go back to shadow without a
redeploy.

The detector can be driven directly, with an injected clock so the numbers are
reproducible:

```python
from dataclasses import replace

from backstop.detection import DetectionConfig, RunawayDetector
from backstop.ledger import Attribution, PriceCatalog, SpendEvent, compute_cost

catalog = PriceCatalog()
config = DetectionConfig(
    enabled=True,
    shadow=True,
    velocity_threshold_usd_per_min=1.0,
    min_samples=8,
    window_size=16,
)

clock = {"now": 0.0}
detector = RunawayDetector(config, time_fn=lambda: clock["now"])


def priced(at: float, input_tokens: int, output_tokens: int) -> SpendEvent:
    base = SpendEvent(
        provider="openai",
        model="gpt-4o",
        endpoint="/v1/chat/completions",
        priority="default",
        outcome="success",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated=False,
        attribution=Attribution(team="payments", feature="checkout-v2"),
    )
    return replace(base, cost=compute_cost(base, catalog))


# Eight quiet minutes: one request a minute, 20k input tokens.
for minute in range(8):
    clock["now"] = minute * 60.0
    detector.observe(priced(clock["now"], 20_000, 500))
# Then an agent loop: 20 requests in 20 seconds, each with 200k input tokens.
for second in range(20):
    clock["now"] = 8 * 60.0 + second
    detector.observe(priced(clock["now"], 200_000, 2_000))

print("shadow:", detector.shadow, "keys:", detector.key_count(), "errors:", detector.errors)
print("counts:", {k: v for k, v in detector.counts().items() if v})
seen: set[str] = set()
for signal in detector.recorded():
    if signal.kind in seen:
        continue
    seen.add(signal.kind)
    print(signal.kind, signal.severity, round(signal.observed, 3), signal.threshold, signal.detail)
```

```
shadow: True keys: 1 errors: 0
counts: {'velocity': 10, 'drift': 10, 'context_growth': 8}
context_growth critical 10.0 2.0 input tokens 200000 against reference 20000 over 9 events
drift warning 93100.0 61500.0 tokens_per_request 93100.0 against reference 20500.0 (x1.514, multiplier 3) over 10 events
velocity info 1.16 1.0 $1.16/min over 16 events in 5.166667 min, 16/16 priced
```

Every threshold is reachable from `BackstopConfig` as a `detection_*` field, and a
nonsense one is refused at `wrap()` rather than discovered on the first request: a
negative or non-finite threshold, a `baseline_multiplier` below 1.0 (which inverts
the comparison rather than alerting earlier), a non-positive window, and
`min_samples > window_size` — a detector that can never speak, and looks exactly
like a healthy one. `detection_max_keys` (default 1,024) bounds the number of
keys; eviction is LRU and **counted** in `evictions` and reported to the signal
sink, because a silently evicted key is a key whose baseline silently restarts.

---

## What it costs

**With the ledger off, which is the default:** one attribute load, one truth
test, one function call per request. No event is built, nothing is read from the
response, no catalog is touched, nothing is offered to a queue. Verify that on
your host with the two committed commands:

```bash
backstop verify      # overhead check passes below a 5 ms p99 threshold
backstop benchmark   # the same measurement the README table quotes
```

**With the ledger on: it is material, and here is the number rather than a
promise.** Measured on this branch by calling
`BackstopTransport.handle_request` directly over an `httpx.MockTransport`, one
arm per subprocess, 7 alternating runs per arm, 3,000 iterations after 500
warm-up, Python 3.12.3 on Linux. Each cell is the **median of the 7 runs**:

| | p50 | p95 |
|---|---:|---:|
| ledger off | 150.5 us | 239.8 us |
| ledger on | 297.3 us | 507.0 us |
| **added** | **+146.8 us (+98%)** | **+267.2 us** |

The spread between runs is the honest uncertainty and it is wide: ledger-off p50
ranged 147.0-156.2 us, ledger-on p50 ranged 289.6-377.1 us. An independent
measurement of the same shape on this build
(`.superpowers/sdd/_build-plan/task-6-report.md`) put it at +130.0 us p50
(+84.6%) on a 153.6 us request. Two runs, one order of magnitude: **turning the
ledger on roughly doubles the cost of a request.** The default path is unaffected,
and the p95/p99 overhead class the library advertises still holds for it — but
anyone who opts in is paying this, and it is larger than the library's entire
advertised overhead budget.

Where it goes, measured from inside the ledger call on the request path
(`task-6-report.md`): `SpendEvent` construction 50.5 us, `compute_cost` 24.2 us,
`BoundedWriter.submit` 3.7 us, plus roughly 35-40 us of GIL time lost to waking
the drain thread. Reproduce it with:

```python
import json, sys, time

import httpx

from backstop import BackstopConfig
from backstop.state import BackstopState
from backstop.transports import BackstopTransport

arm, iterations = sys.argv[1], int(sys.argv[2])
body = {
    "id": "chatcmpl-measure",
    "object": "chat.completion",
    "model": "gpt-4o-2024-08-06",
    "choices": [{"message": {"role": "assistant", "content": "ok"}}],
    "usage": {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500},
}
config = BackstopConfig(
    initial_concurrency=64,
    max_concurrency=64,
    ledger_enabled=(arm == "on"),
    ledger_memory_events=20_000,
)
state = BackstopState.create(10**9, config)
transport = BackstopTransport(state, httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
request = httpx.Request(
    "POST",
    "https://api.openai.com/v1/chat/completions",
    json={"model": "gpt-4o", "messages": [{"role": "user", "content": "measure me"}]},
)

for _ in range(500):
    try:
        transport.handle_request(request)
    except Exception:
        pass

samples = []
for _ in range(iterations):
    start = time.perf_counter_ns()
    try:
        transport.handle_request(request)
    except Exception:
        pass
    samples.append((time.perf_counter_ns() - start) / 1000.0)
samples.sort()
print(arm, f"p50 {samples[len(samples) // 2]:.1f} us", f"p95 {samples[int(len(samples) * .95)]:.1f} us")
```

```bash
for i in 1 2 3 4 5 6 7; do
  PYTHONPATH=src python3 measure.py off 3000
  PYTHONPATH=src python3 measure.py on 3000
done
```

These are wall-clock figures on one host, so they are a measurement rather than a
guarantee — the same caveat the README attaches to its own committed benchmark
snapshot applies here. What is *not* a measurement is the shape: no file is
opened, no socket is touched, and no lock a sink could hold is taken on the
request path, and tests pin that against a deliberately stalled sink, a sink that
raises, and a state whose ledger is not a writer at all.

---

## Known limitations

- **The rate card is a dated snapshot.** The bundled table carries
  `BUNDLED_EFFECTIVE_FROM = "2026-09-26"`, transcribed from two published price
  pages. Nothing in this repository detects a provider rate change, and the
  bundled table is the *lowest* layer, so it is what every deployment uses until
  somebody notices it is wrong. `effective_from` exists on `PriceEntry` but is not
  a charge-back column today. If a total drifts from your invoice in one
  direction only, that is a rate, not a token-count bug.
- **The Anthropic cache-write rate is the 5-minute tier.** The schema has one
  `cache_write_per_mtok_usd` field and Anthropic publishes two (5-minute at 1.25×
  base input, 1-hour at 2×). A deployment on a **1-hour cache TTL is
  under-counted** on its cache writes by ~37.5% of that component — and nothing in
  the record reveals it, because `cache_write` *is* in `priced_components`: the row
  looks fully priced. This is a silent under-count, which is the worst failure
  class here, and it is the top open item in `docs/planning/07-risks-and-killshots.md`.
- **Three of the six outcomes never reach a ledger.** `circuit_open`,
  `budget_denied` and `queue_timeout` describe requests that never reached a
  provider: they have no usage report and no dollars, and a row for one would
  carry a pre-flight floor for spend that never happened — and push that floor
  into the detector's window, contaminating the very ratios the detectors exist to
  measure. They stay in the schema so a durable line written by a future build
  still validates. Spend *avoided* is on the enforcement surface instead:
  `budget_exceeded` / `rate_limited` counters, the
  `requests{outcome=circuit_open|exception}` breakdown, and the audit log's
  `deny` records.
- **A streaming request is a floor, not a measurement.** There is no usage report
  at stream setup, so the event is recorded at dispatch with
  `estimated=True`, `input_tokens` set to the pre-flight estimate and
  `output_tokens=0`. That is a visible, filterable understatement rather than a
  confident wrong split.
- **A request host that is neither provider is unpriced.** The provider is
  matched from the request URL, and a host that names neither `api.openai.com` nor
  `api.anthropic.com` is recorded as `provider="unknown"` and left unpriced —
  an invented provider produces a row that looks authoritative and is about the
  wrong vendor. Point `BackstopConfig` at a gateway and the price is yours to
  supply via `price_catalog_path`, keyed on the model rather than the host.
- **The three loss counters are process-local.** A JSONL line records an event,
  never a counter, so a file read reports `dropped_events` and `sink_errors` as
  unknown. If you need them, keep the writer in the process and read
  `state.close()`.
- **A burst can lose events, by design.** The writer's buffer is bounded, and
  overflow refuses the event rather than growing without limit. That is visible
  in `dropped_events`; the mitigation is `ledger_memory_events` and a longer queue
  at your own call site, not an unbounded queue.
- **The ledger has no tenancy, no retention and no query layer.** One file per
  process, whatever the process chose, until somebody deletes it. Rotation,
  archival and querying are yours.
- **The demo's teardown sentence is hardcoded.** `backstop ledger demo` with a
  `--group-by` other than `team,feature` still says requests "declared no `team`
  and no `feature`" in its prose. The numbers and the table are correct; that one
  sentence is not. `backstop ledger show` and `export` word it generically.

---

## Reference

| command | what it does | exit |
|---|---|---|
| `backstop ledger demo` | priced charge-back from fixed, offline, synthetic events. No key, no network, no file, byte-identical across runs | 0 |
| `backstop ledger show --path FILE` | the file's integrity report, then its charge-back. `--limit N` (0 for all), `--json` | 0; 1 on a corrupt non-final line or an unreadable path |
| `backstop ledger export --path FILE --out FILE.csv` | the RFC 4180 CSV, CRLF, UTF-8, money as 2dp strings. `--group-by team,feature`, `--json` | 0; 1 as above, and nothing is written |
| `backstop doctor` | a wrap-and-import smoke test. Does **not** send a request | 0 |
| `backstop verify` | eight reproducible proof checks, all offline by default | 0 |

Both `--group-by` flags take a comma-separated list of `Attribution` fields and
reject an unknown one as an argparse usage error (exit 2) listing the legal
dimensions, rather than failing later inside the aggregator.

`backstop ledger demo` is synthetic traffic: the request counts, token counts and
timestamps are fixed, and the *dollars* are exact for that volume under the
bundled rate card. One model, `vendor-preview-2027`, is deliberately absent from
the rate card, so its 34 requests are counted and their dollars are absent. That
row is the pitch: a tool that quietly filled that hole would be showing a number
nobody could defend.
