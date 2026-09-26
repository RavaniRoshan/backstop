# 02 — Ledger architecture

Branch `feat/ledger-foundation`. Head at time of writing `39cb7f9`. Every number
below is measured in this repository and cited to a file, a line or a task
report, or it is labelled **HYPOTHESIS**.

The honest current state is [00-current-state-audit.md](00-current-state-audit.md);
what has to be true is [01-north-star.md](01-north-star.md); the failure modes
are [07-risks-and-killshots.md](07-risks-and-killshots.md).

---

## The tension, stated honestly

`README.md:229` and `README.md:236` say two things that a system of record
cannot also say:

| README claim | where | what a ledger needs |
|---|---|---|
| "The default integration path is not a proxy … no network traffic passes through Backstop — the transport is injected in-process and requests go to the provider directly." | `README.md:229-235` | cross-process visibility, or a file the user owns |
| "**Not a hosted control plane.** There is no central Backstop server and no shared policy service. Multi-tenant routing is in-process only" | `README.md:236-242` | aggregation across processes, and somewhere two processes can meet |

Both claims are **still true of the code that ships**, and both were verified as
true in this build's truthfulness pass rather than being softened. There is no
Backstop service (`docs/threat-model.md:22`:
`"In OSS local mode, Backstop code runs inside the application process. No
Backstop-hosted service is required."`), and
`docs/architecture.md:125-131` opens its control-plane section with
`"Nothing in this section exists today."`

The tension is real but it is **narrower than it looks**, and the reason is
that a system of record does not have to be a service. Three of the four
properties finance needs — durability, exactness, auditability — are properties
of a *format and a calculation*, and Backstop's are shipped and tested
(`src/backstop/ledger/schema.py`, `pricing_catalog.py`, `export.py`; 4,124 lines
in `ledger/`, 1,061 in `pricing_catalog.py`, measured by `wc -l`). The fourth
property, cross-process visibility, is a *distribution* problem, and it is
genuinely unsolved. That is the whole tension: **the ledger is a complete
record format with no distribution story, and the README is honest about both
halves.**

What is *not* true is that the tension is only a documentation problem. A
chargeback table computed by `backstop ledger export` describes **one process's
traffic**. A CFO with forty services has forty tables and no total. That is a
product gap, not a wording gap, and it is what the shape analysis below is for.

---

## What was actually built

**There is no network hop and no cloud component.** The shipped design is:

| component | file | what it is |
|---|---|---|
| `SpendEvent` | `src/backstop/ledger/schema.py:389-591` | a frozen dataclass, 18 wire fields, one per completed provider request |
| `Attribution` | `src/backstop/ledger/schema.py:229-332` | a frozen dataclass of 13 optional strings |
| `attribution()` / `with_attribution()` / `current_attribution()` | `src/backstop/ledger/context.py:60,99,158` | one `ContextVar` holding a frozen `Attribution` |
| `PriceCatalog` / `compute_cost` | `src/backstop/pricing_catalog.py:470,1012` | a 45-entry bundled table + a user file, resolved into `Decimal` money at exactly 6 dp |
| `LedgerSink` + `NullSink` / `MemorySink` / `JsonlSink` | `src/backstop/ledger/sink.py:121,159,183,246` | a `Protocol` and three implementations |
| `BoundedWriter` | `src/backstop/ledger/sink.py:492-703` | a `deque(maxlen=10000)` drained by **one** named daemon thread (`sink.py:83`) |
| `build_chargeback` / `read_ledger` / `delivery_report` | `src/backstop/ledger/export.py:817,1511,1661` | aggregation, a strict JSONL reader, and the loss counters |
| the four submission points | `src/backstop/transports.py:621,650,780,1168,1190,1295` | two per transport (streaming, non-streaming) plus fallback, sync and async |

The hot path is one function: `_record_spend_if_enabled`
(`src/backstop/transports.py:195`), whose entire body with both switches off is

```python
config = state.config
if not (config.ledger_enabled or config.detection_enabled):
    return
```

(`transports.py:214-216`). One attribute load, two truth tests, one call.

**The OTLP bridge is the next deliverable and is not shipped.** There is no
`gen_ai.*` reference anywhere in `src/` (verified by `grep -rn "gen_ai" src/` —
zero matches), no OTLP exporter, and no remote sink. `src/backstop/otel.py` is
an *Otel metrics* mirror (`OtelMetrics`, `enable_otel`), and the only OTLP
transport in the tree is `src/backstop/audit_sink.py`'s `VectorAuditSink`,
which is one of the four audit sinks `00-current-state-audit.md` A2.2 records as
**unreachable from any product path** (zero non-test consumers). The "bring your
own backend" path is not built; it is the natural next step, and the design
below is chosen so that adding it is one new `LedgerSink`.

---

## The data flow as shipped

Arrows marked `==X==` cross a **process** boundary; arrows marked `==N==` cross a
**network** boundary. There are no `==N==` arrows in the shipped system, and
that is the property the whole design is protecting.

```
   your application process
   ================================================================

   SDK client (openai / anthropic)
        |
        |  in-process, no hop
        v
   BackstopTransport.handle_request / handle_async_request
        |                                          [ HOT PATH ]
        |  gates, budget, admission, circuit, retry
        v
   _record_spend_if_enabled()                  transports.py:195
        |  one attribute load + two truth tests; returns immediately
        |  when both switches are off this IS the whole cost
        v
   _record_spend()                             transports.py:231
        |
        +--> current_attribution()             ledger/context.py:60
        |      (ContextVar -> frozen Attribution, 13 optional strings)
        |
        +--> SpendEvent(...)                   ledger/schema.py:389
        |      frozen; __post_init__ type- and value-checks all 18
        |      fields; normalises endpoint exactly once
        |
        +--> compute_cost(event, state.prices) pricing_catalog.py:1012
        |      3-tier precedence, Decimal @ 6 dp, returns None if unpriced
        |
        +--> state.detector.observe(event)     detection/detector.py:457
        |      0.14 us disabled / 14.0 us healthy / 25.2 us firing
        |
        +--> state.ledger.submit(event)        ledger/sink.py:583
               |
               |  ONE lock, one append to a bounded deque, return
               |  never blocks on the sink, never raises
               v
        +============== THREAD BOUNDARY ==============+   ==X==
               BoundedWriter buffer   deque(maxlen=10000)   sink.py:75
               drained by ONE daemon thread "backstop-ledger-drain"  sink.py:83
               |
               v  sink.write(event)   -- the Protocol, sink.py:121
              /         |            \
             /          |             \
    NullSink()   MemorySink(10000)   JsonlSink(path)
    sink.py:159  sink.py:183         sink.py:246
    (ledger off,  (ledger demo,        (durable NDJSON, append-only,
     or a          tests)               flushes every line, fsync off)
     detection-                           |
     only run)                            | write(2) + flush
                                         v
                                 ledger.jsonl  (a file the user owns)
                                         |
                                         |  off the request path entirely
                                         v
   backstop ledger show / export             cli.py
        |
        v
   read_ledger()      ledger/export.py:1511   strict; torn final line
                                                 reported, corrupt
                                                 non-final line raises
        |
        v
   build_chargeback() ledger/export.py:817
        |  groups on Attribution fields, default ("team","feature")
        v
   ChargebackRow x N  ->  money() at exactly 2 dp as a STRING  export.py:360
        |
        +--> revenue_join()  export.py:1180   joins THEIR revenue
        |
        v
   chargeback.csv  (RFC 4180, CRLF, money as "12.34" never 12.34)
        |
        v
   THE FINANCE SURFACE:  the row a CFO reads, with unpriced_requests,
   estimated_requests, unpriced_components and the unattributed share
   printed BESIDE the total, not in a footnote.
```

Two things the diagram is meant to make obvious. First, **the only crossing
is a thread boundary** — the data stays in the caller's address space and in
the caller's file. Second, **everything that is slow is above the crossing and
everything that is on the hot path is below it**, which is the mechanical
version of "the transport never blocks on the ledger" (`sink.py:18-26`).

---

## The four shapes

Every shape is assessed on the same six axes. "Code that survives" means the
proportion of the 6,350 lines this build added
(`wc -l src/backstop/ledger/*.py src/backstop/detection/*.py src/backstop/pricing_catalog.py`)
that would remain, unchanged, under that shape.

### (a) Local-first embedded store with opt-in sync

Keep the shipped file, and add a *separate*, optional process that syncs it
somewhere. The hot path does not change; sync is somebody else's process.

- **Hot-path latency impact:** zero. This is the shipped design plus an
  out-of-band process. The only new cost is the process itself.
- **Failure modes:** the file's today, plus "the sync target disagrees with the
  file". A sync that merges two files with the same `event_id` has to decide
  what a conflict is; the schema's answer is that an event is immutable
  (`schema.py:8-11`: *"Nothing in the ledger mutates an event; a correction is
  a new event"*), so a conflict is a duplicate, and `event_id` is a v4 UUID
  (`schema.py:133-144`) rather than a content hash, so a legitimate correction
  is a *different* id. That is a design decision that makes sync easy and
  makes dedup-by-content impossible.
- **Offline behaviour:** perfect, and unchanged. A sync that is down changes
  nothing about the local file.
- **Multi-tenancy:** no better than today. `ledger_path` is one file per
  `BackstopState` (`state.py:217-246`, `config.py:203`) with no partitioning
  and no access control — 07 risk R9 says this in full and calls it
  `survivable` as a deliberate scope boundary.
- **What must be true to scale to 10,000 concurrent agents:** 10,000 processes
  writing 10,000 files, and a sync process that can union them. Nothing in this
  repository does that union. `read_ledger` reads one file
  (`export.py:1511`) and `build_chargeback` takes any `Iterable[SpendEvent]`
  (`export.py:817`), so the *aggregation* half is already general — the missing
  half is enumerating and de-duplicating N files, and telling a user which
  process a gap came from.
- **Code that survives:** 100%. Sync is additive and touches nothing on the hot
  path.

### (b) Emit-only, bring-your-own-backend, OTLP as the wire format, hosted collector as the paid product

Keep the local file as the durable record. Add one more `LedgerSink` that ships
events to a collector the user chose, over OTLP.

- **Hot-path latency impact:** zero *if the sink is the drain thread's job*,
  which is exactly what `BoundedWriter` already guarantees: the lock is dropped
  around `sink.write` (`sink.py:712-716`). A network sink inherits the same
  non-blocking property for free. What it does **not** inherit for free is
  throughput: a sink slower than the request rate fills the 10,000-slot buffer
  and then refuses, and `dropped_events` climbs (`sink.py:595-597`). That is a
  *visible* loss, which is the design working, but at fleet scale it is a
  number someone has to watch.
- **Failure modes:** two new ones. (1) **A network partition looks like a
  healthy process**: the writer keeps accepting, the buffer drains into a
  socket that is not going anywhere, and nothing raises. (2) **A file and a
  collector can disagree**, and the file is the one that cannot be re-derived.
  Both are handled by the loss counters *only if someone reads them*, and the
  file explicitly cannot: `FILE_DELIVERY_NOTE` (`export.py:1700-1705`) states
  that a JSONL line records an event and never a counter, and
  `format_file_delivery` reports `dropped_events` and `sink_errors` as
  **unknown, never as zero** (`export.py:1749-1750`).
- **Offline behaviour:** the local file is untouched by the collector being
  down, which is what makes this shape compatible with the README. The
  in-process guarantee survives because nothing about the transport changes.
- **Multi-tenancy:** this is where it first appears, and it appears for free:
  `gen_ai.*` spans are per-tenant telemetry by construction and a collector
  already knows how to keep them apart. The *access control* question 07 R9
  names is not answered by a collector.
- **What must be true to scale to 10,000 concurrent agents:** batching. The
  single largest ledger-ON cost is already identified and unbatched: **~35-40 us
  of GIL time per submit lost waking the drain thread** (`task-6-report.md:375`,
  `progress.md:109-110`). Over a socket that number is not just latency, it is
  a syscall. A collector that wants 10,000 agents needs a sink that batches on
  the drain thread, and that is the same optimisation the local path wants.
- **Code that survives:** 100%. `LedgerSink` is a `runtime_checkable`
  `Protocol` with three methods (`sink.py:120-147`), so a network sink is a
  plain object — the docstring says a user "passes a plain object with
  `write`/`flush`/`close` and it works" and it does not need to subclass
  anything. The `gen_ai.*` mapping is a translation layer over `SpendEvent`, not
  a redefinition of it; [03-attribution-and-schema.md](03-attribution-and-schema.md)
  writes the mapping.
- **The cost of choosing it:** an OTLP dependency in the ledger core, or a new
  extra. Global Constraint 5 (`_build-plan.md:20-21`) forbids new required
  runtime dependencies, so this is at minimum `pip install backstop-ai[otlp]`.
  The `otel` extra already exists for metrics (`docs/compatibility.md:94-98`),
  so this is a widening, not a new axis.

### (c) Sidecar or daemon over a unix socket

Move the buffer, the drain thread and the file handle out of the application
process and into a long-lived local daemon; the SDK writes events to a unix
socket.

- **Hot-path latency impact:** the socket write *is* the hot path now. A
  `send(2)` on a unix socket is one syscall into the kernel; the measured cost
  of everything the ledger currently does in-process is +130.0 us p50
  (`task-6-report.md:350`), of which only 3.7 us is `submit` itself
  (`task-6-report.md:368`). A socket hop would replace 3.7 us of in-process
  work with a kernel round trip, in exchange for moving the ~35-40 us drain
  wake off the calling thread. **Net: probably cheaper per request, and
  categorically different in kind** — it is now I/O, so it can fail, and
  Global Constraint 2 (`_build-plan.md:13-15`) says the hot path "may only do
  in-memory work plus a non-blocking `put_nowait` onto a bounded queue". A
  non-blocking unix socket write is arguably within that letter and clearly
  against its spirit.
- **Failure modes:** a new crash domain. If the daemon is not running, every
  submit fails; if it is running and wedged, the socket buffer fills and then
  `EAGAIN`; if it is killed mid-write, the file is the *daemon's* file and
  the application's exit no longer implies anything about it. All of these are
  survivable and all of them are worse than "the file is yours".
- **Offline behaviour:** unchanged in the sense that matters (requests still go
  direct to the provider), but the ledger now depends on a second process the
  user must install, supervise and version-match. `docs/threat-model.md:22`'s
  claim survives literally but stops being the whole story.
- **Multi-tenancy:** a per-host sidecar is strictly better than per-process and
  strictly worse than per-customer. It does not answer R9.
- **What must be true to scale to 10,000 concurrent agents:** the same batching
  work as (b), plus a socket protocol with framing, backpressure and a
  reconnect story. All new.
- **Code that survives:** `schema.py`, `context.py`, `pricing_catalog.py`,
  `export.py`, `demo.py` and the whole CLI survive unchanged. `sink.py` is
  **replaced** — `BoundedWriter`, `MemorySink` and the drain thread are the
  three things a sidecar exists to remove. That is the largest rewrite of the
  four, and it is the only shape that throws away the component that was the
  most expensive to get right (the accounting invariant at `sink.py:414-436`
  and the three-bucket loss arithmetic at `sink.py:86-117`).

### (d) Two products, one spec: an MIT local core plus a proprietary multi-tenant control plane

The local core ships as it is. A separate, closed control plane ingests what
the core emits and serves the multi-tenant queries the file cannot.

- **Hot-path latency impact:** zero for the local core, which is the point. The
  control plane is off the request path entirely, and
  `docs/architecture.md:144-145` already states the requirement: *"The local SDK
  path must remain useful without the control plane."*
- **Failure modes:** the local core's are today's. The control plane adds the
  one 07 and `docs/threat-model.md:86-96` already flag: a hosted service as an
  availability dependency. The threat model's mitigations are written down and
  unimplemented — make it opt-in, cache the last valid policy, define
  fail-open/fail-closed.
- **Offline behaviour:** complete, because the local core is the product and
  the control plane is an upgrade. This is the shape the README's promise
  survives in.
- **Multi-tenancy:** the only shape that answers "can team A see only their own
  spend" with an access-control answer rather than a `WHERE` clause.
- **What must be true to scale to 10,000 concurrent agents:** the same as (b)
  plus tenancy isolation plus a per-tenant rate card, which is the one thing
  this build cannot supply: `BUNDLED_EFFECTIVE_FROM` is a single dated
  snapshot (`pricing_catalog.py:226`) and 07 risk R8 says nothing detects a
  rate change.
- **Code that survives:** 100% of the local core *by construction*, **provided
  the spec is drawn at the `SpendEvent` wire form** and the control plane is a
  consumer of it. The failure mode is the reverse direction: the moment the
  control plane starts *defining* fields, the local core becomes a client of a
  server it was supposed to replace, and Global Constraint 4
  (`_build-plan.md:18-19`) — *"Preserve the MIT license and the honest 'What It
  Does Not Do' section"* — is what stops that. This is a governance risk, not a
  technical one, and it is the real cost of (d).

---

## Recommendation

**Ship (b) as the next deliverable. Keep (a) as the foundation. Build (d) only if
a control plane is ever funded. Refuse (c).**

This is a judgement, and the reasoning is stated so it can be argued with:

1. **(b) is the only shape that costs the hot path nothing and buys
   interoperability.** `BoundedWriter` already guarantees the transport never
   blocks on a sink; adding an OTLP sink inherits that guarantee for free. Every
   other shape either adds a syscall to the request path ((c)) or adds nothing
   to the distribution story ((a) alone, (d) without (b) underneath it).
2. **(c) buys a process boundary nobody has asked for and spends the most
   code to get it.** It replaces the component this build spent a review round
   getting right, and it makes the ledger's availability depend on a second
   process for no gain in any of the six axes except per-host file sharing,
   which no customer has asked for in this repository.
3. **(d) is the right long-run answer and the wrong next step.** It is the only
   shape that answers multi-tenancy with access control, and 07 R9 is explicit
   that not survivable if the product is sold into shared platforms. But (d)
   without (b) underneath it is a control plane with no wire format, and (d) as
   a first step means designing a tenancy model before there is one customer
   who needs it — which is exactly the decision the build plan refuses
   elsewhere (`_build-plan.md:371-374`, on auto-kill).
4. **(a) alone is what ships today and is not enough**, because one file is one
   process and a CFO with forty services has forty tables.

**What would change this recommendation:** a real customer asking "can team A see
only their own spend" *and* an enterprise security review asking who can read
the file (the two early-warning signals 07 R9 names). Both are demand signals,
and neither has fired. **The cost of being wrong:** if (b) ships and nobody uses
it, we have an extra dependency, a translation layer and a maintenance burden
on a wire format that is still `stability: development` upstream. That is the
cheap direction to be wrong in.

---

## Latency budget

Machine: Python 3.12.3, `httpx.MockTransport`, `handle_request` called
directly, 4,000 iterations after 500 warm-up, median of 14 **alternating**
subprocess runs per arm; this box's single-run noise band is ±10 us p50, ±60 us
p99 (`task-6-report.md:310-318`). A delta is a paired comparison, not a
difference of two noisy numbers.

The "budget" column is what we are willing to say, not what we achieved. Where
the two differ, the row says so.

| # | line | budget (what we claim) | measured | verdict |
|---|---|---|---|---|
| 1 | **Ledger OFF, the default — total per-request delta** | sub-millisecond class preserved; publish the number | **+3 to +5 us p50, about +2 to +3%** on a ~150 us request. Two independent 14-run pairings: +4.60 us (+3.06%) and +3.20 us (+2.14%). The spread is the honest uncertainty. (`task-6-report.md:322-334`) | **PASS** |
| 2 | Ledger OFF — p95 / p99 delta | inside the noise band | +2.77 us p95 (+1.19%), +1.76 us p99 (+0.53%) — both inside ±10/±60 us (`task-6-report.md:327-328`) | **PASS** |
| 3 | Ledger OFF — the gate itself | one attribute load, two truth tests, one call; **zero** events submitted | asserted structurally: `state.ledger.submitted == 0` and median < 5.0 ms in `test_a_ledger_off_request_costs_nothing_worth_measuring` (`tests/test_ledger_transport.py:595-613`). The 5.0 ms bound is ~20x the measured median, so it catches reintroduced real work, not noise | **PASS** (loose bound, deliberately) |
| 4 | Ledger OFF — enforcement p99, whole library | < 5 ms threshold, sub-millisecond | `backstop verify` reports control-path overhead p99 **0.290 ms** (direct 0.434 ms), run just now. `task-6-report.md:341-344` recorded 0.330 ms on its machine; `01-north-star.md:150` recorded 0.229 ms. Three runs, three numbers, all sub-ms | **PASS** |
| 5 | **Ledger ON, opt-in — total per-request delta** | **must be published; the advertised class does not apply** | **+130.0 us p50 (+84.6%)** on a 153.6 us request; +253.4 us p95 (+115.3%); +335.1 us p99 (+113.3%); +90.4 us min (+78.4%) (`task-6-report.md:348-353`) | **FAIL against the ~0.09 ms class — ACCEPTED, see below** |
| 6 | Ledger ON — where the 130 us goes (in situ, per phase) | attribution, not a single suspect | `SpendEvent()` **50.5**, `compute_cost` **24.2**, `submit` **3.7**, `_request_id` **2.9**, `_provider_for_host` **1.3**, `str(url)+host` **~1.0**, `_tokens_for` **0.8**, `_model_for` **0.7**, `current_attribution()` **0.7**; total inside `_record_spend` **96.2 us** (p95 173.3, p99 212.9) (`task-6-report.md:363-374`) | measured, published |
| 7 | Ledger ON — GIL lost waking the drain thread | not visible inside `submit`; quantified separately | **~35-40 us per submit** (`task-6-report.md:375`). The single largest line item, identified, quantified and **unbatched** (`progress.md:109-110`) | **OPEN — highest-leverage optimisation available** |
| 8 | `BoundedWriter.submit` against a deliberately stalled sink | must not block; ~1 us | **0.841 / 0.851 / 1.04 us** per submit (min/median/max) over 10,000 submits, sink parked inside its first `write`. Test bound 2.0 s = 235x margin (`task-5-report.md:163-175`) | **PASS** |
| 9 | `SpendEvent()` construction | — | in situ **50.5 us**; tight-loop micro-benchmark **11.0 us**. Round-2 optimisation `cf98ffc` cut the transport shape 12.55 -> **9.59 us** and the full shape 16.08 -> 12.13 us (`task-3-report.md:747-754`, `task-6-report.md:365`) | measured |
| 10 | `SpendEvent.__post_init__` validation alone | must be cheap; O(fields), no per-call compile | **2.26 us**, of which ~0.6 us is the two regex matches (`task-3-report.md:890`, `:525-528`). The whole 13-field type+value check costs **2.1 us** (`task-3-report.md:525`) | **PASS** |
| 11 | `compute_cost` | pure, no I/O, no clock, cached name reduction | in situ **24.2 us**; tight loop **8.9 us**; after the decimal-context fix, **11.9-12.2 us/call** against 12.39 us before (`task-6-report.md:366`, `task-7-report.md:692`) | **PASS** |
| 12 | `model_candidates` (name reduction) | no per-request regex compile | `@lru_cache(maxsize=2048)`, patterns module-level. Pinned by a test that prices 50 fresh model names and asserts `re._cache` did not grow (`task-4-report.md:128-132`) | **PASS** |
| 13 | `detector.observe`, **disabled** (the default) | one boolean test | **0.14 us/call**, asserted < 5 us *and* < 1/20th of the enabled path (`task-8-report.md:139,145`) | **PASS** |
| 14 | `detector.observe`, enabled | O(window) | **14.0 us** healthy, **25.2 us** when `velocity` fires on every call, **8.4 us** at `window_size=8`, **6.2 us** cold (`task-8-report.md:138-143`) | measured, published |
| 15 | `NullSink.write` vs `MemorySink.write` | the disabled path must be the cheapest thing | **39.5 ns** vs **267.9 ns** — 6.8x. Test asserts a 3x ratio floor and a 1000 ns absolute ceiling (`task-5-report.md:177-179`) | **PASS** |
| 16 | The provider usage split read (`response_usage`) | one read, two consumers | the ledger's share is **0.4-1.4 us per response**; a second full JSON decode would have cost **3.6 us** and bought nothing (`task-6-report.md:337-339`, `:157-159`) | **PASS** |
| 17 | No blocking I/O on the request path | a regression that blocks must be a diagnosable failure | `test_a_stalled_sink_does_not_block_the_request` parks the sink with an `Event` set from inside `write` and asserts return in **< 500 ms**, ~100x the observed worst case. A loose bound on purpose: the claim it supports is "does not block", not "is fast" (`task-6-report.md:242-248`, `:447-451`) | **PASS** (loose bound, deliberately) |
| 18 | `close()` cannot hang shutdown | bounded join | `DEFAULT_CLOSE_TIMEOUT = 5.0 s` (`sink.py:80`); the stalled-sink test uses 0.25 s and gets `drained=False, undrained=4, dropped_events=4` (`task-5-report.md:181-183`) | **PASS** |
| 19 | **In-situ vs tight-loop divergence** | a methodology warning, not a budget | the same function measures **3-5x** higher in situ than in a warmed micro-benchmark. Every leaf number in this repo's history, including the one behind `cf98ffc`, was measured the first way (`task-6-report.md:378-386`) | **methodology caveat** |
| 20 | Ledger-ON cost against a real agent LLM call | invisible in an agent workload | **HYPOTHESIS.** 130 us against a request that takes seconds is a fraction of a percent, so the opt-in cost should be unnoticeable in agent workloads and clearly visible in a tight synchronous loop. **This repository has no measurement of real LLM request latency.** An earlier version of `docs/concurrency.md` claimed agents spend "~99% of their time awaiting the model API"; that claim was removed in this build as unverified (`00-current-state-audit.md` R13), and the current text at `docs/concurrency.md:14-16` says only that "the exact fraction is workload-dependent". Nothing here proves it. | **HYPOTHESIS** |

### Why the ledger-ON failure is accepted rather than fixed

The ruling is recorded at `progress.md:100-108` and repeated in
`01-north-star.md:149`. The reasoning, in full:

- Global Constraint 2 (`_build-plan.md:13-15`) protects the **default** path.
  Row 1 above is the default path and it passes with margin.
- The ledger is **opt-in** (`config.py:202`, `ledger_enabled: bool = False`).
  Nobody pays row 5 unless they ask to.
- The alternative to accepting it is to make the ledger lossy enough to be
  cheap — sample it, batch it, drop fields — and a ledger that is lossy cannot
  be reconciled against an invoice, which is the entire product claim
  (`01-north-star.md:18`: *"what would make them churn: a total they cannot
  reconcile"*).
- Row 20 is **HYPOTHESIS**, and it is the weakest load-bearing claim in this
  document. It is stated as a hypothesis because it is one, and the honest
  framing is `task-6-report.md:355-358`: *"This is material and I am not
  rounding it in our favour: turning the ledger on nearly doubles the cost of a
  request."*

The one thing that would make it a *non*-issue and has not been done: **batch the
drain-thread wake** (row 7, ~35-40 us of 130). `progress.md:109-110` carries it
as an open item. It is the highest-leverage single optimisation in the ledger
and it was correctly deferred rather than rushed.

---

## Failure-mode analysis

Seven modes. For each: what the user sees, what the system does, what is lost.
Every row is grounded in code, not in a plausible story.

### 1. Sink unavailable — the path cannot be opened at all

- **User sees:** a 200 from every request and an empty file. Nothing else. No
  exception, no log line, no warning at startup.
- **System does:** `JsonlSink` opens lazily on the **first write**, not in
  `__init__` (`sink.py:379-394`), so building a state touches no filesystem. The
  open fails, `_degraded` is set, `_errors` becomes 1, and the handle stays
  `None`. Every later write increments `_errors` again and returns
  (`sink.py:335-340`). The file is **not** created — which is why a wrong
  `ledger_path` is silent until there is traffic.
- **What is lost:** every event. And it is worse than a crash would be, because
  the file's existence is the usual way a user finds out.
- **What makes it visible, and when:** only `CloseReport` /
  `DeliveryReport`, at close or on a live read. The reviewer's exact scenario —
  50 events into a `JsonlSink` whose path can never be opened — asserts
  `lost == 50`, `landed == 0`, `sink_reported_errors == 50`, `sink_degraded is
  True`, and the writer's own `dropped_events` and `sink_errors` both still 0
  (`00-current-state-audit.md:193`, `task-7-report.md:769-774`). The
  `atexit` hook registered in `state.py:186-187` closes the state, so an ordinary
  process exit does produce the report. **A long-lived process that finishes a
  job and keeps running does not** — 07 O14 / `task-8-report.md:712-717`: "the
  ownership sits with the caller — documented, but documentation is not a
  reminder."

### 2. Disk full

- **User sees:** the same as #1. Every request succeeds.
- **System does:** the same degraded path — the `write(2)` or the `flush`
  raises `OSError: ENOSPC`, which is an `Exception`, which is caught at
  `sink.py:346-349`; `_degraded = True`, `_errors += 1`, and the handle is
  dropped so **no later write can append after a partial one**
  (`sink.py:396-405`). That ordering is deliberate and it is the only thing
  that keeps the file parseable: a retry per write would turn a broken sink
  into a syscall per write (`sink.py:262-265`).
- **What is lost:** everything from the first failure onward. Nothing before it:
  every line is flushed as it is written (`sink.py:342-343`), so a crash costs
  the line in flight rather than the buffer.
- **What makes it visible:** `sink_errors` and `degraded`, reported at close. A
  full disk is indistinguishable from a bad path in every number the ledger
  reports — both are "the sink lost N".

### 3. Process killed mid-write — a torn final NDJSON line

- **User sees:** `backstop ledger show` succeeds, exits 0, and prints one extra
  line under *Delivery*: `torn final line: line N, the line is not valid JSON:
  …; this event is LOST and is not counted`.
- **System does:** the read policy is three rules, implemented at
  `export.py:1511-1591` and pinned by five tests
  (`task-7-report.md:118-126`). (1) A final line that will not parse is a **torn
  write**: reported as `TornWrite(included=False)`, not repaired, and every
  event before it is read. (2) A final line that parses but is **not
  newline-terminated** is a torn write whose event is **kept** — a complete
  record always ends in a newline, so a missing one means the process died
  inside the write, but if the record is still readable, dropping it would lose
  a real dollar. (3) An unparseable line anywhere **other** than the end is
  **corruption**: `LedgerCorruptionError` naming the line number, the reason and
  a 120-byte excerpt (`export.py:1429-1448`), and *nothing is read past it*.
  The file is read as **bytes** and split on `b"\n"`, so a line truncated
  mid-UTF-8-character is still a line.
- **What is lost:** at most one event, and it is named with its line number. A
  corrupt non-final line loses nothing, because the command fails instead.
- **Why the schema makes this detectable rather than silent:** `from_dict`
  requires the payload to carry *exactly* the 18 declared fields — an undeclared
  key is a `ValueError` naming it, a missing one is a `ValueError` naming it
  (`schema.py:538-561`). A fragment that happens to end on a field boundary
  does parse as JSON and is then **refused** by the schema rather than
  reloading with defaults. The strictness is the recovery mechanism.

### 4. The drain thread dies

- **User sees:** `dropped_events` climbing, one per request, after a delay equal
  to the buffer depth. Nothing else — no exception, no log, no metric.
- **System does:** `_drain` (`sink.py:706-732`) wraps `sink.write` in
  `try/except Exception`, so a sink that raises cannot kill the thread; the
  failure becomes `sink_errors` and the loop continues. What **is not guarded**
  is the thread itself: `_drain`'s own body is not wrapped, so an exception
  raised inside it (not in the sink) ends the thread. And
  `BoundedWriter._start_drain_locked` is only ever called when
  `self._thread is None` (`sink.py:599-600`), and `_thread` is never reset to
  `None` after a start — so **a dead drain thread is never restarted.**
- **What is lost:** every event submitted after the thread dies. They are
  accepted into the buffer (so `submit` returns `True` and the loss is *not*
  counted as a drop) until the buffer reaches 10,000, at which point every
  submit returns `False` and `dropped_events` moves.
- **Honest verdict:** this is the one failure mode in this document that is
  **detectable only indirectly and not currently instrumented**. There is no
  drain-thread heartbeat, no liveness check, and nothing on the metric surface
  (`src/backstop/metrics.py` declares no ledger instrument at all — `grep -rn
  "metrics.call" src/backstop/ledger/` returns zero). The observable signature
  is `backlog` pinned at 10,000 with `dropped_events` climbing, which is
  distinguishable from a slow sink only by the fact that a slow sink recovers.
  **Proposed, not built:** a `ledger_drain_alive` gauge and a drain-thread
  restart on the next `submit` after a `is_alive()` check.

### 5. An unpriced model

- **User sees:** a row with real token counts, `total_usd = "0.00"`, and
  `unpriced_requests = 34`. The demo's `vendor-preview-2027` row is exactly
  this: 34 requests, 8,211 input tokens, 11,300 output tokens, `$0.00`,
  `unpriced_requests 34` (run just now, `backstop ledger demo`).
- **System does:** `compute_cost` returns `None` (`pricing_catalog.py:1058-1060`)
  and never falls back to a neighbouring model, a family average or a default
  rate. The event is recorded with `cost=None` and the export counts it in the
  row's `unpriced_requests`, leaving `price_source` as `(none)`. There is **no
  separate counter that could drift from the export** — the row *is* the record
  (`ddaba66`, `00-current-state-audit.md:197`, which fixed two docstrings
  pointing at a `price_unknown` counter that did not exist).
- **What is lost:** the dollars, by an amount nobody can name. `provider="unknown"`
  — Azure, Bedrock, a gateway, a self-hosted vLLM (`transports.py:61-72`) —
  produces the same row, and 07 R13 says this is most non-OpenAI/non-Anthropic
  deployments. The escape hatch is already shipped: a deployment on a custom
  host files an entry with `"provider": "unknown"` in its own
  `price_catalog_path` and it matches (`task-6-report.md:190-195`).
- **A second-order consequence nobody has written down:** the runaway detector
  cannot see unpriced spend. `RunawayDetector._usd` returns `(0.0, False)` for a
  `None` cost (`detector.py:701-704`) and its docstring says the numerator "can
  be smaller than the real spend rather than being padded to look measured" — so
  a key running entirely on an unpriced model can never raise a `velocity`
  signal. That is the correct direction to be wrong in, and it is invisible.

### 6. A hostile clock

- **User sees:** wrong `first_seen` / `last_seen`, events landing in the wrong
  `Period`, and — for a monotonic clock that jumps backwards — a `velocity` of
  exactly 0.
- **System does, in two places.** (a) **`occurred_at`** is
  `datetime.now(timezone.utc)` at construction (`schema.py:116-126`). Nothing
  validates it against anything; `OCCURRED_AT_RE` checks *format* only
  (`schema.py:93`). A wrong clock therefore produces a well-formed, wrong
  timestamp, and `Period.contains` — two string comparisons, correct because
  the format is fixed-width (`export.py:287-291`) — filters on the wrong value.
  (b) **The detector does not use `occurred_at` at all.** It reads
  `time_fn`, default `time.monotonic` (`detector.py:423`), which is immune to
  wall-clock changes. A backwards jump makes `span_minutes <= 0`, and
  `velocity` is guarded by `if span_minutes > 0.0` (`detector.py:763`), so it
  reads 0 rather than a negative or a division error. A `time_fn` that raises,
  a non-finite clock and a negative one are all absorbed by `_safe_number`
  (`detector.py:172-197`) into `0.0`, and `observe` is total — the exception is
  caught and counted on `errors` (`detector.py:470-479`).
- **What is lost:** nothing structurally. The wall clock's only in-record use is
  `occurred_at`, and it is a *measurement of when Backstop saw the response*,
  not a claim about provider billing time. A customer who needs
  invoice-accurate time has to get it from `request_id` joining to the provider
  dashboard, which is exactly why `request_id` is in the schema.
- **The demo is immune by construction:** `DEMO_DAY = "2026-09-26"` is a fixed
  constant, never today's date (`demo.py:77-81`), which is what makes the
  output byte-identical across runs.

### 7. A host application that tightens the global decimal context

This one has a body count, because it was a real defect found by review and
fixed (`00-current-state-audit.md:192`).

- **User saw, before the fix:** a 200 from every request, `state.ledger_errors`
  climbing once per request, and **zero events recorded** — `compute_cost` raised
  `InvalidOperation` on *every* event, so the ledger was permanently empty with
  no explanation. All three `backstop ledger` subcommands died with a bare
  `decimal.InvalidOperation`. Two failure modes of one cause: `quantize` **raises**
  when the ambient precision is shorter than the result, and the operators around
  it **round silently** when the precision is merely tight — so the export layer
  was the *quieter*, worse half (`task-7-report.md:667-702`).
- **System does now:** every cost and every report figure runs under
  `LEDGER_CONTEXT`, a `decimal.Context` named in **full** — `prec`, `rounding`,
  `Emin`, `Emax`, `capitals`, `clamp`, `flags`, `traps`
  (`pricing_catalog.py:134-143`) — because `Context(...)` copies any field left
  unspecified from `decimal.DefaultContext`, so a context naming only `prec` would
  still be reachable by a host that tightened the *default*'s traps. It is
  installed **once** around all four components and the total
  (`pricing_catalog.py:988`), and once more per public export entry point via the
  `_exact_money` decorator (`export.py:333-356`), so a later arithmetic change
  inside a decorated function is covered without remembering the context.
  `_Bucket` is deliberately not decorated: it runs once per event, so
  `build_chargeback` holds the context around its whole loop instead.
- **What is lost:** nothing. The guarantee is unconditional — the same inputs
  give the same breakdown whatever the ambient `prec`, `rounding`, `traps` or
  `Emax` are, because none of them are read
  (`pricing_catalog.py:41-46`). A test sets `prec=2` with `ROUND_UP`, `Inexact`
  and `Rounded` trapped and `Emax=9`, and asserts the same figure through
  `str()` so a round-up cannot pass; another asserts the ambient context is left
  exactly as found (`task-7-report.md:722-733`).
- **Cost of the fix, and the reason it is done this way:** one `localcontext`
  per component would cost +0.77 us x 4 = +3 us per priced event; the explicit
  `Context.multiply/divide/add/quantize` verbs cost +1.3 us; one context for the
  whole breakdown costs **+0.6 us** (`task-7-report.md:689-693`). The hot path
  is why the pattern differs between the two modules and both are commented as
  such.

---

## What this document does not decide

| question | where it should be decided |
|---|---|
| Whether the drain-thread wake is batched | engineering, next cycle; identified, quantified (`progress.md:109-110`), not started |
| Whether a `provider_map` config field closes the `provider="unknown"` gap | with the OTLP bridge — the bridge is where per-provider mapping belongs |
| Whether a control plane is ever built | 07 risk R9, against a real demand signal |
| The error budget on a reported dollar figure | [03-attribution-and-schema.md](03-attribution-and-schema.md), the invoice-reconciliation section |
| Whether the GenAI semconv is adopted, mapped, or ignored | [03-attribution-and-schema.md](03-attribution-and-schema.md), the OTel decision |
