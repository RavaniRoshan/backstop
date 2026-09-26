# 04 — Detection design (Area B, resolved against what shipped)

Branch `feat/ledger-foundation`. Head at time of writing `39cb7f9`. Suite at
that SHA: **1214 passed, 9 skipped**, measured just now.

This document reads the detector **out of the code** —
`src/backstop/detection/detector.py` (905 lines) and
`src/backstop/detection/config.py` (194 lines) — not out of
`docs/planning/_build-plan.md:346-374`. Where the plan and the code disagree,
the code is right and the plan is out of date; the disagreements are listed
explicitly in "Plan vs shipped" at the end.

The architecture around it is [02-ledger-architecture.md](02-ledger-architecture.md);
the schema the detector reads is [03-attribution-and-schema.md](03-attribution-and-schema.md);
the failure modes are [07-risks-and-killshots.md](07-risks-and-killshots.md).

Every number below is either measured in this repository and cited, measured
again by me for this document and labelled as such, or labelled **HYPOTHESIS**.
Nothing is estimated and presented as a measurement.

---

## The one-sentence version

`RunawayDetector.observe(event)` is a pure function of one bounded deque of the
last `window_size` events for one attribution key, plus a comparison against a
threshold. It returns a **list of records**. It has no code path that stops,
cancels, blocks or raises into a caller, and that is enforced by a test rather
than by a promise (`tests/test_detection.py::test_module_exposes_no_enforcement_primitive`).

---

# 1. The signals

## 1.1 The reduction, which is where most of the design is

`RunawayDetector._measure` (`detector.py:725-796`) reduces one window to one
`_Reading` (a `NamedTuple`, `detector.py:348-364`) in **one pass plus at most
two sorts**, both over at most `window_size` floats. The pass sums USD and
retries, counts priced events, and lifts two value lists out of the deque; the
sorts produce the two medians the ratios need.

The load-bearing decision is the **split**. Every detector that compares
something to something splits the window at `count // 2`
(`detector.py:768`): the older half is the *reference period*, the recent half is
the *current regime*, and the current event is always in the recent half.

| ratio | numerator | denominator | why this pair |
|---|---|---|---|
| drift | mean `total_tokens` of the **recent half** (`detector.py:772`) | median `total_tokens` of the **older half** (`detector.py:769`) | mean-of-regime against median-of-baseline |
| context growth | **this** request's `input_tokens` (`detector.py:776`) | median `input_tokens` of the window **minus the current event** (`detector.py:773`) | prior events only; including the current one would halve the spike it exists to catch |
| velocity | sum of `total_usd` over **priced** samples | `(t_last - t_first) / 60` (`detector.py:746, 762-766`) | the window's real elapsed span, from the events' own timestamps |
| retry | `sum(retries)` over the whole window | `count` | a mean, deliberately — see below |

`total_tokens` is every token the request moved: `input + output + cache_read +
cache_write` (`detector.py:689-694`).

**Why the split exists, stated as arithmetic rather than intuition.** Over one
shared window the median *follows* a sustained step change, so mean-over-median
is mathematically incapable of reporting one. The split fixes that and it also
separates the two "this one request is wrong" detectors: a lone 3x spike is
`context_growth` and not `drift`; a sustained 4x regime is `drift` and not
`context_growth`. A 60x spike legitimately trips both.

**The split does not fully fix it, and this is measured, not asserted.** See
§1.5: a sustained **2x** step never fires drift at the default multiplier, and
the reason is that once the new regime occupies more than half the window the
*reference* half starts containing the new regime too.

## 1.2 The four detectors, exactly as coded

Read out of `detector.py:815-865`. All four comparisons are **strictly `>`**
(`_evaluate` docstring, `detector.py:800-806`), so an observation exactly on the
threshold is quiet. A threshold is the boundary of "unusual", not the first
value of it.

| # | kind | observed (1 line) | threshold (default) | extra guard | default value |
|:-:|---|---|---|---|---:|
| 1 | `velocity` | `sum(usd of priced samples) / (span_minutes)` | `velocity_threshold_usd_per_min` | numerator is 0 when no sample is priced; span 0 → 0.0 | **1.0** USD/min |
| 2 | `drift` | `mean(total_tokens, recent half)` | `baseline_multiplier * median(total_tokens, older half)` | fires only if `reference > 0` | **3.0** |
| 3 | `retry_amplification` | `sum(retries) / count` | `retry_ratio_threshold` | — | **0.5** |
| 4 | `context_growth` | `this.input_tokens / median(input_tokens of the rest of the window)` | `context_growth_threshold` | ratio is 0.0 when the reference median is 0 | **2.0** |

Severities, from `_severity` (`detector.py:367-382`), one rule for all four on
the observed/threshold margin:

| band | rule | value |
|---|---|---:|
| `info` | `threshold * 1.25 <= observed` is false | `SEVERITY_INFO_FACTOR = 1.25` (`detector.py:105`) |
| `warning` | `observed >= threshold * 1.25` | |
| `critical` | `observed >= threshold * 4.0` | `SEVERITY_CRITICAL_FACTOR = 4.0` (`detector.py:100`) |

A non-positive threshold reports `warning` rather than a division-free but
meaningless `critical`, because a zero threshold fires on every event by
definition (`detector.py:376-377`).

**Severity is only meaningful for a fixed threshold.** A `warning` at threshold
1.0 and a `warning` at threshold 50 are not the same event. The signal carries
both `observed` and `threshold` (`DetectionSignal`, `detector.py:276-308`)
precisely so this is computable rather than guessed.

## 1.3 The three formula choices that are not obvious, and would be re-derived wrongly

**(a) `retry_ratio` is a mean, not a fraction of requests that retried**
(`detector.py:786`, SpendSignal docstring `detector.py:244-248`). A fraction
scores "ten requests that each retried once" and "one request that retried ten
times" identically. The second is the one that burned the budget.

**(b) An unpriced event contributes 0.0 to the velocity numerator, and that is
not a floor — it is silence** (`_usd`, `detector.py:700-723`). A model with no
published price has no rate, and inventing one to make a velocity look measured
is the one thing a finance-facing number must never do. A window with no priced
event reports velocity `0.0` and raises nothing. The `detail` string reports
`N/M priced` so a floor is never presented as a measurement. **The event is
still observed for tokens and retries**, which matters more than it sounds: a
runaway on an unpriced model still trips `context_growth`,
`retry_amplification` and (at 4x or more) `drift`.

**(c) `distinct_model_ratio` is computed and exposed but no threshold reads it**
(`detector.py:787`, SpendSignal docstring `detector.py:249-252`). A key
thrashing between models is worth seeing. It is exposed on `features()` and it
is not in the four-signal contract, deliberately: a fifth detector with a fifth
default is a fifth thing to tune in shadow.

## 1.4 `SpendSignal` — what a caller can read

`SpendSignal` (`detector.py:212-273`) is frozen and every field is a ratio or an
average, never a raw count, so two keys with wildly different budgets are
compared on the same scale.

| field | type | definition | zero means |
|---|---|---|---|
| `cost_velocity_usd_per_min` | `float` | §1.2 #1 | no price in the window, or every event at the same instant |
| `tokens_per_request` | `float` | mean of the **recent half**, `detector.py:772` | no samples |
| `input_token_growth_ratio` | `float` | §1.2 #4 | the reference period had no input tokens (undefined, not infinite) |
| `retry_ratio` | `float` | `sum(retries) / count` | no retries |
| `distinct_model_ratio` | `float` | `len({model}) / count`, in `[0,1]` | one model throughout |
| `samples` | `int` | `len(window)`, validated `int` and `>= 0` (`detector.py:266-273`) | — |

`samples` exists so a caller reading `retry_ratio == 0.0` can tell "no retries"
from "no history" (`detector.py:253-257`).

**Read it as a pure read.** `features()` uses the window's own most recent
timestamp as "now" rather than the clock (`detector.py:481-493`), so it does not
depend on when it is called and cannot perturb the detectors.

## 1.5 What a real trigger looks like — measured

These are not illustrations. I drove the real `RunawayDetector` on this branch
with an injected monotonic clock, real `SpendEvent` objects and real
`CostBreakdown` values, at the shipped defaults
(`window_size=50`, `min_samples=8`, multiplier 3.0, thresholds 1.0 / 0.5 / 2.0).
One event per second unless stated.

| scenario | what happened | signal raised | observed | threshold | severity | `detail` verbatim |
|---|---|---|---:|---:|---|---|
| **velocity** — 40 requests at **$0.05** each, 1 req/s | fires on the **8th** event (the first at which a detector may speak) and stays up | `velocity` | **3.4286** | 1.0 | `warning` | `$3.43/min over 8 events in 0.116667 min, 8/8 priced` |
| …same key, 40 events later | the window is fuller, the rate is lower, still over | `velocity` | **3.0769** | 1.0 | `warning` | `$3.08/min over 40 events in 0.650000 min, 40/40 priced` |
| **velocity, quiet** — $0.15 of spend in 3 events, then 117 idle events | fires 3 times, then stops | `velocity` (3) | **1.0000** | 1.0 | `info` | `$1.00/min over 10 events in 0.150000 min, 10/10 priced` |
| **context growth** — 9 flat requests at 10,000 input tokens, then one at **30,000** | fires on the spike, and only on the spike | `context_growth` | **3.0000** | 2.0 | `warning` | `input tokens 30000 against reference 10000 over 10 events` |
| **retry amplification** — 9 quiet requests, then one with **6 retries** | one event with six retries is enough | `retry_amplification` | **0.6000** | 0.5 | `info` | `6.0 retries over 10 events` |
| **drift** — 9 flat requests at 10,000/500 tokens, then a **sustained 2x** step (30 events) | **never fires.** 39 events, 0 signals, 0 errors | — | — | — | — | — |
| **drift** — same, but a **sustained 4x** step | `context_growth` fires on the first new event; `drift` first fires on the **35th** event overall, i.e. the 26th event of the new regime | `drift` | **40500.0** | **31500.0** (x1.286) | `warning` | `tokens_per_request 40500.0 against reference 10500.0 (x1.286, multiplier 3) over 35 events` |
| **unpriced window** — 12 requests, `cost=None` on every one | never fires, and says nothing about it | — | — | — | — | `features` on that key: `cost_velocity_usd_per_min=0.0`, `tokens_per_request=10500.0`, `samples=12`, `errors=0` |

Two things in that table are worth more than the rest.

**The 2x case is the honest limit, and it is a real one.** A sustained doubling
of tokens per request — the single most common way an agent loop starts costing
more than it did last week — produces **no drift signal at the default
multiplier, ever**, at any window size the default config permits. Worked
through by hand at `window=50`: after 9 flat and 30 doubled events, the older
half of a 39-event window is 9 flat samples and 10 doubled samples, so its
**median is already the doubled value** (20,500), the threshold becomes 61,500,
and the observed mean is 20,500. The reference follows the regime. The split
delays that failure; it does not remove it. Removing it needs a baseline that
is not recomputed from the same window — an explicitly aged reference period, or
a decay-weighted baseline. That is not built (§5.3).

**The 4x case shows the cost of the delay.** Drift is a *sustained* signal: 26
events into a new regime before the first one, at the shipped defaults. That is
the right trade (a fast drift detector is a noisy one, and the per-request case
is context growth's job — see `config.py:71-74`) but an operator watching a
single burst sees only `velocity` and `context_growth`.

**Severity `info` at exactly the threshold's neighbourhood** is the third row:
`1.0000` against a threshold of `1.0` is a ratio of 1.0x, below the 1.25x
`warning` band, so it reports `info` and does not page. That is the band doing
its job.

## 1.6 The two switches and the knobs

`DetectionConfig` is frozen and validated in `__post_init__`
(`config.py:139-194`). Both switches default to inert.

| field | default | validation | where it is set from `BackstopConfig` |
|---|---:|---|---|
| `shadow` | `True` | `bool` | `detection_shadow` (`config.py:227`) |
| `enabled` | `False` | `bool` | `detection_enabled` (`config.py:226`) |
| `velocity_threshold_usd_per_min` | `1.0` | finite, `>= 0` | `detection_velocity_threshold_usd_per_min` (`config.py:228`) |
| `baseline_multiplier` | `3.0` | finite, `>= 1.0` | `detection_baseline_multiplier` (`config.py:231`) |
| `retry_ratio_threshold` | `0.5` | finite, `>= 0` | `detection_retry_ratio_threshold` (`config.py:232`) |
| `context_growth_threshold` | `2.0` | finite, `>= 0` | `detection_context_growth_threshold` (`config.py:233`) |
| `window_size` | `50` | `int`, not `bool`, `>= 1` | `detection_window_size` (`config.py:234`) |
| `min_samples` | `8` | `int`, `>= 2`, **and `<= window_size`** | `detection_min_samples` (`config.py:235`) |
| `max_keys` | `1024` | `int`, not `bool`, `>= 1` | `detection_max_keys` (`config.py:236`) |

Three of these validations are beyond the plan's minimum list and each exists
because the failure it prevents is **silent** (`config.py:26-32`):

- `baseline_multiplier >= 1.0`. A multiplier below 1.0 does not mean "alert
  earlier"; it means "alert when tokens *fall*". Refused (`config.py:100`).
- `min_samples >= 2`. One sample of history leaves no reference half for drift
  and no prior median for context growth. Refused (`config.py:110`).
- `min_samples <= window_size`. A window that can never hold the samples it
  needs is a detector that can never speak, and it is **indistinguishable from
  a healthy one**: no signals, no errors, a clean log. Refused
  (`config.py:189-194`).

**Every knob is reachable**, which was not true at first ship. The first two
commits (`492d8ce`, `beee968`) left the six thresholds frozen inside the
detector; `4871f8b` made all eight reachable from `BackstopConfig` by way of one
module-level joiner, `_detection_config` (`config.py:436-463`), which
`__post_init__` calls (`config.py:350`) so a bad knob fails at `wrap()` rather
than on the first request. The joiner **delegates every rule** to
`DetectionConfig` rather than re-implementing it, so there is one implementation
of each rule and not two that can disagree.

**The knobs are flat on `BackstopConfig`, not a nested `DetectionConfig`
field.** The justification is recorded at
`.superpowers/sdd/_build-plan/task-8-report.md:436-442`: every other subsystem's
knobs on that class are flat and prefixed (`circuit_*`, `retry_*`, `cache_*`,
`aimd_*`), there is not one nested config object on `BackstopConfig` today, and
a nested field would create a second source of truth for `enabled` (the flag
*and* `config.enabled`) that has to be reconciled on every read.

---

# 2. What runs where

## 2.1 In-process, per request

| step | where | cost class | blocking? |
|---|---|---|:-:|
| the gate: one attribute load, two truth tests | `transports.py:214-216` | ~0 | no |
| build one `SpendEvent` | `transports.py:231` `_record_spend`, event at `:324` | 50.5 us in situ (`task-6-report.md:365`) | no |
| price it (`compute_cost`) | `transports.py:328` | 24.2 us in situ (`task-6-report.md:366`) | no |
| `writer.submit(event)` — one short lock, one `deque.append`, return | `transports.py:346` is the detector call; submit is the line above | 3.7 us in situ, 0.851 us median against a stalled sink (`task-5-report.md:167-169`) | no |
| `detector.observe(event)` — the whole detector | `transports.py:346` | see §2.2 | no |
| **return from the request** | | | |

The transport call site is **one call, deliberately unchanged**
(`transports.py:342-346`, and the comment there says why): iterating the
returned signal list at that site would put a per-signal loop and a per-signal
metric dispatch on the request path to learn nothing the sink does not already
record.

## 2.2 The measured cost of each detector path

Two separate measurements exist and they do not agree, and the disagreement is
the point.

**Tight loop** — `timeit`-style, prebuilt events so event construction is not
counted, 20,000 calls, `window_size=50`, one key, Python 3.12 / x86-64
(`task-8-report.md:133-143`):

| path | us/call | what it is doing |
|---|---:|---|
| `enabled=False` — **the default, and what every untouched request pays** | **0.14** | one boolean test and a return (`detector.py:468-469`) |
| enabled, cold, below `min_samples` | 6.2 | append one `_Sample`, no measurement (`detector.py:618-621`) |
| enabled, healthy, nothing fires | **14.0** | O(window): one pass, at most two sorts of at most 50 floats, two medians |
| enabled, priced, `velocity` fires every call | **25.2** | the above, plus four `DetectionSignal` constructions and one `signal_key` percent-encoding pass |
| enabled, `window_size=8`, nothing fires | 8.4 | the same work over a shorter window |

The test's bound is **100 us** — deliberately a whole per-request overhead class
rather than a tight figure, because the point is to catch a regression that adds
a sleep, a file, a regex compile or a pass over unbounded work, not to pin the
machine (`task-8-report.md:163-166`).

**In situ, on the request path** — measured from inside the transport
(`task-6-report.md:376`): `detector.observe` costs **+36.5 us** with detection
on, against a **12.3 us** tight-loop figure for the same function. That is a
**~3x** discrepancy, and it is the concrete instance of the general finding
recorded at `task-6-report.md:378-386`: **in-situ costs are 3-5x the tight-loop
micro-benchmark for the same function**, because a loop leaves CPython's
specialising interpreter fully warmed and the allocator hot, and a request path
runs the code once per ~200 us interleaved with thousands of other bytecodes.
Every leaf-function number in this repository's history was measured the first
way.

**I re-measured the three paths on this host at a different moment** and got
0.095 / 27.4 / 27.2 us for disabled / healthy-50 / firing. So: the **absolute**
tight-loop figures are host- and load-dependent and the recorded 0.14 / 14.0 /
25.2 should not be treated as portable. The **ratio** is the load-bearing claim
and it is stable across both measurements: the disabled path is roughly **two
orders of magnitude** below the enabled one, and the firing path is within about
2x of the healthy one. The disabled path is asserted to be both under 5 us and
under a twentieth of the enabled path (`task-8-report.md:145-146`).

**One cost the original measurement did not include**, recorded as an open item
at `task-8-report.md:718-722`: detection signals now cost a metric dispatch per
signal plus a `TelemetrySink` lock when a dashboard is running. The 25.2 us
firing figure predates that. The figure is only paid by a key that is actually
misbehaving, and detection is off by default — but if it is ever turned on for
everyone, the benchmark must be re-run with a sink attached.

## 2.3 Deferred, and to whom

| deferred work | where it runs | why it cannot run on the request path |
|---|---|---|
| opening the JSONL file | `JsonlSink` opens on **first write**, from the drain thread (`state.py:227-230`) | a `stat`/`open` on the hot path is the thing Global Constraint 1 forbids |
| the sink's own write, `flush`, `close` | `BoundedWriter`'s single named daemon thread (`ledger/sink.py:83`) | the sink may block or raise; neither may reach a caller |
| `signal.record()` to the metric surface | the `DetectionSignalSink`, called from `detector._record` **after the lock is released** (`detector.py:900-905`) | a sink that blocks must not hold the one lock every other request thread needs |
| `evicted(key)` notification | same, outside the lock (`detector.py:659-678`) | ditto; reporting a drop may block on telemetry |
| the per-kind counters and the shadow ring | under the lock, but only when a signal exists (`detector.py:896-899`) | a healthy key pays for none of it |
| clock read | **before** the lock (`detector.py:586-590`) | `time_fn` is caller code; caller code does not get to serialise the request path |
| pricing | on the request path but as `Decimal` arithmetic only, never a network call | Global Constraint 1: no network hop, ever, on the hot path |

## 2.4 The lock, and the two things deliberately outside it

One non-reentrant `threading.Lock` guards the per-key windows, the shadow log,
the per-kind counters and the error count (`detector.py:439`). That is
sufficient because it is only ever held for in-memory arithmetic on the calling
thread's own window — no I/O, no callback into caller code, no acquisition order
(`detector.py:396-409`). The most recent commit on the branch, `39cb7f9`, is
exactly this: *"take one lock instead of two for the recent-signals read"*.

Outside it, on purpose: the injected clock, and the signal sink. Both are caller
code. The detector is called from a background drain thread and from a sync
request thread, so this is a real requirement and not a theoretical one
(`detector.py:405-409`).

`observe` is **total**: it wraps `_observe` in a bare `except Exception`,
increments `errors` and returns `[]` (`detector.py:470-479`). Four parametrized
test families assert that against non-events, tampered events, hostile clocks
and a 600-event seeded fuzz sweep (`task-8-report.md:194-201`). The promise is
total, not best-effort: a detector that is only safe when the input is
well-formed is not safe on a request path.

---

# 3. Why there is no auto-kill

**This is a design decision, taken deliberately, with a recorded ruling.** It is
not an omission and it is not a gap waiting to be filled in a hurry.

The ruling, from `.superpowers/sdd/_build-plan/progress.md:39-41`:

> Ruling: auto-kill is deferred out of Task 8. The plan's Area B requires a
> resumability and idempotency design first. Cost if wrong: detection ships
> report-only for one cycle, which is the safe direction to be wrong in.

The build plan says the same at `_build-plan.md:370-374`: auto-kill is "not in
this build", and "shipping an unresumable kill switch to save time is exactly
the kind of decision the plan says to refuse."

## 3.1 The reason, in one paragraph

A legitimate agent run is not a request. It is a six-to-eight hour trajectory, or
a multi-day research run, in which each turn appends the last turn and sends the
lot again — which is precisely the shape `context_growth` is built to detect
(`detector.py:854-857`). A kill switch that cannot resume is **worse than no
kill switch at all**: it converts a spend anomaly into a lost day of work, and
the operator who reaches for it is the operator in the middle of that day. So a
detector that could destroy in-flight work would be a liability wearing the
cost of a feature (`detector.py:9-15`).

## 3.2 Detection currently CANNOT block, and that is structural

Not "does not block by default" — **cannot**. Three independent reasons, in
increasing order of how much they can be worked around:

1. **There is no decision to act on.** `observe` returns `list[DetectionSignal]`
   (`detector.py:457`). `DetectionSignal` has seven fields — `kind`, `severity`,
   `key`, `observed`, `threshold`, `detail`, `occurred_at`
   (`detector.py:302-308`) — and **not one of them names a request, a session or
   a run**. There is no field a caller could route into a cancellation, because
   there is no identifier to cancel.
2. **Nothing exported is an enforcement primitive.** The test
   `test_module_exposes_no_enforcement_primitive` walks
   `backstop.detection.__all__` and then every public method of every exported
   class looking for `allow, block, cancel, deny, denial, enforce, halt, kill,
   pause, stop, throttle`, and **fails the build** if one appears
   (`task-8-report.md:189-193`). A docstring is a promise; a test is a fact.
3. **The signal is a record with a timestamp that is not the detector's clock.**
   `DetectionSignal.occurred_at` is the *event's* `occurred_at`
   (`detector.py:870-872`), not the moment the detector noticed. That is the
   right choice for reading the log tomorrow, and it is also what makes the
   record useless as a kill trigger: by the time you read it, the run is over.

## 3.3 What the auto-kill design must contain before it is even considered

Five things. Each is stated as the property it has to have, not as an
implementation.

| # | requirement | the property it must have | why it is load-bearing |
|:-:|---|---|---|
| 1 | **Idempotency key** | every unit of agent work carries a stable, caller-supplied idempotency key, persisted outside the agent process, and re-submitting a key is a no-op rather than a second charge and a second side effect | without it, a resume double-charges and double-acts. For an agent, the side effects are tool calls — an email sent twice, a refund issued twice — and no ledger can undo that |
| 2 | **Resumability contract** | an explicit, documented contract for what "resumed" means for each supported framework: which node is safe to replay, which is not, and what the framework itself guarantees on `interrupt()`/`checkpoint` | the frameworks differ. LangGraph has a checkpointer; CrewAI does not have an equivalent primitive today (**HYPOTHESIS** — I did not verify this against either framework's current release). Assuming a shared contract exists is the assumption that makes an unresumable kill ship |
| 3 | **Partial-work policy** | what happens to work already done inside the killed window: kept, discarded, or marked. And for tool calls specifically — a side effect that already fired is not rolled back by resuming | a detector measures tokens, not side effects. It cannot know whether the 400th turn already sent the email |
| 4 | **Blast-radius limit** | a hard, configured ceiling on what a single kill may destroy: at most N nodes, at most one agent, at most one session — and never the whole fleet | "the detector killed production" is a different and much worse incident than "the detector fired 40 times" |
| 5 | **Long-running-task exemption** | a durable, operator-declared exemption that a human sets for a known multi-hour or multi-day run, and that a detector cannot revoke | this is the requirement that makes the others survivable. It converts the failure mode from "the tool destroyed my work" to "the tool warned me and I acknowledged it" |

Items 1-3 are the load-bearing ones and none of them is designed. Item 5 is the
one I would build first, because it is the only one that can be built entirely
inside this repository and it converts an unbounded risk into a bounded one.

## 3.4 What the system does instead

**It reports.** Concretely, today:

| surface | what an operator gets | where |
|---|---|---|
| a Prometheus counter | `backstop_detection_signals_total{kind, severity}` — 4 kinds x 3 severities, both closed sets | `metrics.py:145` |
| a histogram | `backstop_detection_signal_observed{kind}` — the *magnitude*, which is what a threshold should be set from rather than from a count | `metrics.py:153` |
| an eviction counter | `backstop_detection_evictions_total` | `metrics.py:158` |
| two alert rules | `BackstopRunawaySpendSignal` (critical, on any critical-severity signal) and `BackstopDetectionKeyEvictions` (warning, on `increase(...[15m]) > 0`) | `observability/prometheus-alerts.yml:44, 59` |
| a readable per-session view | `telemetry.detection_view()` — per session, per kind, per severity, the key bound in force, what is retained, the eviction count, the recent signals **with their keys** | `telemetry.py:453, 946` |
| the dashboard | the same payload under `detection` on the snapshot | `telemetry.py:946` |
| the process exit | `BackstopState.close()` / `Backstop.close(client)` return a `CloseReport` whose `lost` is the number of submitted events that will never reach storage | `task-8-report.md:568-600` |

**The attribution key is deliberately not a metric label.** It is a user
identifier with unbounded variety, and `metrics.py` now documents the rule: a
label is a position in a closed vocabulary. It goes in the signal record and the
bounded ring, and it is in the dashboard payload on purpose, because the
operator's next question is whose spend is running away
(`task-8-report.md:482-497`).

## 3.5 The one thing that would change the decision

Not "when detection is mature". Specifically: **when a framework integration
ships a resumability contract** (item 2). Until there is a framework whose
documented interrupt/resume semantics Backstop can rely on, an auto-kill has
nothing to resume into, and the correct number of kill switches in the codebase
is zero.

---

# 4. Shadow mode

## 4.1 How it works

`observe` returns **the same signals in both modes**. That is enforced, not
described: `test_enforcing_detector_reports_the_same_signals_as_shadow` replays
the *same event objects* into a shadow detector and an enforcing detector and
asserts the full tuples — kind, observed, threshold, severity, `occurred_at` —
are identical (`task-8-report.md:216-219`). If they disagreed, the shadow log
would be describing a detector that does not exist.

**Shadow changes bookkeeping only** (`detector.py:23-33`): in shadow, every
signal is *additionally* filed in a bounded ring of
`SHADOW_LOG_SIZE = 256` records (`detector.py:109`) and a per-kind counter
(`detector.py:436`). The counters are maintained in both modes, because in
enforcing mode the same log is the evidence about real events.

Three things this is designed around:

- **The ring, not a buffer.** A detector watching a genuinely runaway key would
  otherwise accumulate one record per event forever
  (`detector.py:107-109`).
- **The signal is returned either way.** A record nobody receives is a record
  nobody can tune against (`detector.py:31-33`).
- **The sink's exceptions are swallowed**, exactly as
  `ShadowCollector.record` does (`detector.py:900-905`). A telemetry sink is not
  allowed to become a reason a request fails.

## 4.2 Why the default

`DetectionConfig.shadow = True` (`config.py:154`) and
`BackstopConfig.detection_shadow = True` (`config.py:227`). The stated reason
(`config.py:12-16`):

> Detection has to be tuned before it bites. A threshold nobody has watched fire
> in shadow is a threshold that will, one day, interrupt a six-hour research run
> on its first real burst.

Combined with `enabled = False` (`config.py:157`), the sequence is: nobody asked
for it, so it costs one boolean test; the first person who *does* ask for it gets
a **monitor**, not an enforcement primitive; and turning enforcement on is a
deliberate edit with a shadow log full of evidence behind it.

## 4.3 The precedent, and the kill switch

This is the second shadow mechanism in the codebase and it deliberately mirrors
the first:

| | existing | detection |
|---|---|---|
| class | `ShadowCollector` (`rollout.py:18`) | `RunawayDetector` + `_record` |
| env switch | `BACKSTOP_SHADOW` (`rollout.py:43`) | `BACKSTOP_DETECTION_SHADOW` (`detector.py:136`) |
| resolver | `ShadowCollector.enabled(config_shadow)` (`rollout.py:41-46`) | `RunawayDetector.shadow_enabled(config_shadow)` (`detector.py:443-455`) |
| falsy set | `("0", "false", "off", "no")` (`rollout.py:45`) | the same four (`detector.py:138`) |
| direction | env wins over config **in both directions** | the same |
| sink contract | `record(decision, reason, **fields)`, exceptions swallowed | `record(signal)`, exceptions swallowed |

The direction matters and is the point: an env switch that can only *enable*
shadow is a safety belt. One that can also *disable* it is the incident-response
control, because a detector switched on by an over-eager config edit can be put
back into shadow without a redeploy or a restart
(`detector.py:133-135`, `detector.py:445-451`).

## 4.4 The tuning workflow, before a threshold bites

This is the workflow the default exists to make possible. It is a loop, and
every step is a command or a query that exists today.

**Step 0 — leave the default on and do nothing else.** `detection_enabled=True`
with no other knob. Cost: ~0.14 us per request in a tight loop, more like 36.5
us in situ (`task-6-report.md:376`). Nothing is blocked in any configuration,
because nothing can be.

**Step 1 — collect.** Let it run for a full representative period. Read
`backstop_detection_signal_observed{kind}` (the magnitude histogram) rather than
`backstop_detection_signals_total` (the count). A count tells you a threshold
was crossed; the distribution tells you **what the threshold should be**, and
those are different numbers. Rule of thumb that is a **HYPOTHESIS, not a
measured value**: set the threshold at roughly the 99th percentile of the observed
magnitudes and the alert rate becomes roughly 1% of events, which is a number a
human will still read.

**Step 2 — check for evictions before believing any of it.**
`backstop_detection_evictions_total > 0` means keys are being dropped and their
baselines are restarting. Read the dashboard's `detection` block
(`telemetry.py:453`) for the key bound in force and what is retained. If
`evictions` is climbing, raise `detection_max_keys` — a threshold tuned against
a window that keeps resetting is not a threshold
(`detector.py:552-564`).

**Step 3 — read the actual signals, per key.** `detection_view()` carries the
recent signals with their keys, their severities and the observed/threshold pair
(`telemetry.py:453`). The `detail` string is written to be read by a human at
2 a.m. and it says how much of the window it was computed from: `$3.08/min over
40 events in 0.650000 min, 40/40 priced` (§1.5). If the `priced` fraction is
low, the velocity is a floor and the threshold is meaningless until the models
are priced.

**Step 4 — change one knob at a time, and change it in config, not in code.**
`BackstopConfig` is frozen (`config.py:44`), so a running detector cannot be
re-tuned underneath itself — a threshold that changes mid-window makes two
signals from the same burst incomparable (`config.py:143-145`). Edit the
config, re-`wrap()`, and compare one week of shadows to the previous week.

**Step 5 — leave `shadow` on for at least one period after the last change.**
The failure mode this defends against is a threshold that looks quiet in
testing and fires on the first real burst in production. The counter that proves
it is `backstop_detection_signals_total`, and the number that proves the
threshold was right is that the *magnitude* histogram's tail moved, not that the
alert count went down.

**What not to do:** do not set `shadow=False` to "test enforcement". There is
nothing to test: `observe` returns the same signals in both modes, so setting
`shadow=False` changes no behaviour a caller can observe, and the only thing it
does is delete the evidence you tuned against. `shadow=False` is a statement
that the evidence is sufficient, and it should be made once, with the evidence
in hand.

---

# 5. The known limits

Every one of these is a real limit of the shipped code, not a caveat.

## 5.1 Bounded keys, LRU eviction, and a silent baseline reset

`window_size` bounds one key's samples. The **number of keys** is the other
thing that grows, so it is bounded too: `max_keys`, default **1024**
(`config.py:90`), enforced on insert in `_evict_locked` (`detector.py:640-657`).
`_windows` is an `OrderedDict`; the least-recently-**observed** key is dropped.

**Recency is advanced by observation only** (`detector.py:612-616`). A read
(`features`, `window_len`) does not promote, so whether a baseline survived
cannot depend on who looked at it, and `features()` keeps the pure-read
contract it already documents.

**The cost of eviction is a silently cold key, and this is the whole reason the
eviction counter exists.** A dropped key's window goes with it, so that key is
cold again and **silent until it has `min_samples` events**
(`detector.py:552-564`). A detector that forgets is, in a dashboard,
indistinguishable from a healthy one. So every drop is counted in
`detector.evictions` (`detector.py:653-656`), reported to a Prometheus counter,
alerted on by `BackstopDetectionKeyEvictions`, and shown in the dashboard.

Measured: **5,000 requests with 5,000 distinct attributions stays at 64 keys
with 4,936 counted evictions** (`task-8-report.md:561-562`). The default of 1024
was chosen so the retained event count (~51,200 at the default window) is the
same order as the in-memory ledger ring the codebase already treats as an
acceptable bound (`task-8-report.md:551-556`).

**It is a judgement call, not a measurement, and it will be wrong for a large
multi-tenant deployment** (`task-8-report.md:706-711`). The failure is quiet by
design. Nothing yet watches that counter in production, because no production
deployment exists.

## 5.2 Drift is deliberately slow, and the delay is larger than it reads

At the shipped defaults, a sustained 4x step first fires on the **26th** event of
the new regime (§1.5, measured). A sustained 2x step **never fires at all**
(§1.5, measured), because the reference half of the window eventually contains
the new regime and its median follows it up.

That is the correct trade and it is a deliberate one (`config.py:71-74`, "drift
is a *sustained* change of regime, and the single-request spike belongs to
context growth"). The operator-visible consequence: **an operator watching a
single burst sees `velocity` and `context_growth` and no `drift` at all.**

## 5.3 Most agent workloads are bursty and recursive, and a rolling baseline is the wrong shape for them

This is the deepest limit and it is structural.

The detector's model is a **rolling window over a per-key event stream**, and its
four questions are all "is this key behaving like itself lately". For a
request-per-call service that is the right model. For an agent workload it is
not, in three specific ways:

| agent reality | why a rolling per-key window gets it wrong |
|---|---|
| **Recursive fan-out.** One goal can spawn thousands of subtasks, and each subtask is its own subtree with its own depth. A single deep trace produces a burst of tens of thousands of events across many keys in seconds, then nothing for an hour | the window is bounded by **count**, not by time (`config.py:18-24`), so 50 events can be 50 milliseconds or 50 hours. Velocity divides by the span the events themselves declare, which is right for a burst and useless for a slow ramp |
| **Bursty by construction.** A research run is 20 minutes of intense tool use and hours of waiting on a human. The `drift` reference period is contaminated by whichever regime happened to be in the older half | there is no notion of a *task* in the window. The unit is the attribution key, and an agent's natural unit is the run |
| **Recursive context, not a step change.** Each turn appends the last turn, so input tokens grow *smoothly and monotonically* within a run rather than stepping | `context_growth` compares this request to the key's own recent median, so a healthy agent loop is a series of modest ratios and a genuinely broken one is one enormous ratio against a median it has already contaminated. What the loop actually needs is "is this turn's input consistent with the turn index", which requires a turn counter the record does not carry |

The specific fix is a **task-scoped, time-aware baseline**: a key that is
declared per *run* rather than per team, a window that is aged as well as
counted, and a `context_growth` reference that is the previous turn's input
rather than the window's median. None of that is built. The honest statement is
that **the shipped detector is tuned for a service, not for an agent**, and
that the two want different windows.

## 5.4 The detector measures tokens, not outcomes — and that is the gap that matters

Every one of the four signals is a function of tokens, dollars-per-minute,
retries and model count. Not one of them reads a field that says whether the
work **succeeded**.

The schema has no outcome-of-the-work field. `SpendEvent.outcome` is the
outcome of the **HTTP request** — `success`, `error`, `fallback`
(`schema.py:90`, `EMITTED_OUTCOMES`), and a request that a budget denied never
reaches a provider and so never reaches the ledger at all
(`task-8-report.md:650-673`). A `context_growth` signal on a run that is
converging is indistinguishable from one on a run that has been failing for six
hours and is about to burn another $2,000 finding that out.

**The metric that closes this gap is cost per completed task, and it is the next
hard problem.** What it needs, in dependency order:

| need | why the current record cannot supply it |
|---|---|
| a **task identifier** on every event | `Attribution` already carries `task` and `session` (`schema.py:240-241`), and `03-attribution-and-schema.md` documents `task` as "one per unit of work". But both default to `None`, nothing validates or requires them, and a caller that never sets them gets 100% unattributed rows — which is exactly the demo's `(unattributed)` row, 69 of 1,967 requests |
| a **completion event** with a timestamp | the ledger records requests. A run that ends has no record, so "hours elapsed" is not derivable — and the elapsed time is the denominator |
| a **terminal success marker** the caller supplies | only the caller knows whether the agent finished. The library observes HTTP, not intent |
| an **outcome taxonomy** a finance team will accept | "the task succeeded" has to be defensible in a chargeback, which means the caller has to define it, and the definition has to be stable across teams |
| **cross-key aggregation** | a fan-out run spans many keys today, and `window_size x max_keys` per key is the wrong unit for a total |

Until those five exist, the honest claim is: **Backstop can tell you what a key
spent. It cannot tell you what that money bought.** For an enforcement buyer
that is a complete product. For the ledger buyer named in
[01-north-star.md](01-north-star.md) — the finance person who owns the invoice —
it is the difference between a cost report and a chargeback, and it is the
single largest remaining gap in the ledger half.

## 5.5 The smaller ones, recorded so they are not re-discovered

| limit | effect | where |
|---|---|---|
| a tampered attribution with a hashable non-string field | the event is observed and counted, but `signal_key` refuses it, so the signal is dropped rather than filed under a wrong team. `errors > 0` with a **silent** key | `task-8-report.md:377-381` |
| `distinct_model_ratio` has no threshold | a thrashing key is measurable but never fires | `detector.py:787` |
| a non-positive threshold reports `warning`, never `critical` | by design; a zero threshold fires on everything so it has no meaningful margin | `detector.py:376-377` |
| `errors` does not count a raising signal sink | telemetry failing is not the detector failing, and the sink has its own `sink_errors` | `detector.py:569-582` |
| the `atexit` close hook covers only interpreter exit | a long-lived process that finishes a job must call `Backstop.close(client)`, and nothing reminds it to | `task-8-report.md:712-717` |
| the firing-path figure predates the metric dispatch | re-measure before turning detection on for everyone | `task-8-report.md:718-722` |

---

# 6. Plan vs shipped

Where `docs/planning/_build-plan.md:346-374` and the code disagree.

| | plan | shipped | why the code is right |
|---|---|---|---|
| signals | five named features including `distinct_model_ratio` | five computed and exposed, **four detectors** | a feature nobody reads is not a feature; `distinct_model_ratio` is on `features()` and available to any future threshold |
| `distinct_model_ratio` | listed as a signal | no threshold reads it | same |
| key bound | unspecified | `max_keys=1024`, LRU, **counted** evictions | the first ship had an unbounded key count (`task-8-report.md:345-354`); a silently evicted key is a key whose baseline silently resets, so the bound is visible |
| thresholds | four names | the same four names, plus `window_size`, `min_samples`, `max_keys` and both switches, all reachable from `BackstopConfig` | a frozen default nobody can set is not a threshold |
| auto-kill | "not in this build", resumability first | identical, and now stated in three docstrings plus a test that fails the build if an enforcement primitive appears | a test is a fact; a docstring is a promise |
| `min_samples` | unspecified | `>= 2` and `<= window_size`, both construction errors | each prevents a *silent* failure (`config.py:26-32`) |
| reported cost | not stated | 0.14 / 14.0 / 25.2 us tight-loop, +36.5 us in situ | — |

---

# 7. FACT and HYPOTHESIS

## FACT — measured or read out of the code in this repository

| claim | evidence |
|---|---|
| Four detectors, named `velocity`, `drift`, `retry_amplification`, `context_growth`, reported in that order | `SIGNAL_KINDS`, `detector.py:92`; `_evaluate`, `:815-865` |
| Every comparison is strictly `>` | `_evaluate` docstring, `detector.py:800-806` |
| `enabled=False` costs 0.14 us in a tight loop; 14.0 us enabled and healthy; 25.2 us firing | `task-8-report.md:137-143` |
| `detector.observe` costs +36.5 us in situ on the request path | `task-6-report.md:376` |
| In-situ costs run 3-5x the tight-loop figure for the same function | `task-6-report.md:378-386`, measured for this function as 36.5 vs 12.3 |
| Re-measured on this host: 0.095 / 27.4 / 27.2 us disabled / healthy / firing | my probe, §2.2; the ratio is stable, the absolute figures are not |
| A sustained **2x** step produces **no** drift signal at the default multiplier, over 39 events | measured, §1.5 |
| A sustained **4x** step first fires on the 35th event overall (the 26th of the new regime), at only 1.286x its own threshold | measured, §1.5 |
| A 3x input spike on a flat key fires `context_growth` at 3.0000 against a 2.0 threshold, on the first new event | measured, §1.5 |
| One request with 6 retries among 10 fires `retry_amplification` at 0.6000 against 0.5, severity `info` | measured, §1.5 |
| An entirely unpriced window reports velocity `0.0`, raises nothing, and records `errors == 0` while still measuring tokens | measured, §1.5 |
| 5,000 requests with 5,000 distinct attributions stays at 64 keys with 4,936 counted evictions | `task-8-report.md:561-562` |
| `enabled=False` and `shadow=True` are the defaults, on `DetectionConfig` and on `BackstopConfig` | `config.py:154, 157, 226-227` |
| All eight knobs are reachable from `BackstopConfig` and land on the detector the state actually holds | `config.py:436-463`; `4871f8b`; `task-8-report.md:452-459` |
| Three Prometheus instruments, two alert rules, one dashboard view | `metrics.py:145, 153, 158`; `observability/prometheus-alerts.yml:44, 59`; `telemetry.py:453` |
| A test fails the build if any public name contains an enforcement verb | `task-8-report.md:189-193` |
| `observe` is total: it never raises, for non-events, tampered events, hostile clocks, or a 600-event seeded fuzz sweep | `task-8-report.md:194-201` |
| Shadow and enforcing modes return identical signal tuples | `task-8-report.md:216-219` |
| The env switch mirrors `ShadowCollector`/`BACKSTOP_SHADOW` in both directions | `detector.py:133-136, 443-455` vs `rollout.py:41-46` |
| 1,614 lines of detection tests in `test_detection.py`, 352 in `test_detection_observability.py` | `wc -l` |

## HYPOTHESIS — believed, not proven

| claim | what would have to happen to prove it |
|---|---|
| Setting a threshold at roughly the 99th percentile of the observed magnitudes gives an alert rate a human will still read | one shadow deployment, one tuning cycle, one observed rate |
| The default `max_keys=1024` is right for a real multi-tenant deployment | a real deployment reporting its live key count; the number is explicitly a judgement call (`task-8-report.md:706-711`) |
| `velocity_threshold_usd_per_min = 1.0` is a sensible default | one finance team, one invoice, one week of real spend |
| `baseline_multiplier = 3.0` is a sensible default | the §1.5 measurement says a 2x step is invisible at 3.0; whether 3.0 or 2.0 is right depends on how often real agent loops double |
| Resumability is designable for LangGraph and CrewAI | a written contract for each, per §3.3 item 2. CrewAI having no equivalent interrupt primitive today is **unverified** against either framework's current release |
| A time-aware, task-scoped baseline would fix the bursty/recursive problem | it has not been built and the failure modes in §5.3 are structural, not tuning |
| Cost per completed task is achievable with the current schema | the five dependencies in §5.4; none of them exists |

---

## What this document is not

It is not a case for auto-kill, and §3 is not a placeholder for one. It is not
a tuning guide for a threshold other than the default one — §4.4 is the loop for
that, and it runs against evidence rather than against this document. And it is
not a claim that detection is finished: §5.4 is the gap that matters, it is not
a polish item, and it is the reason "cost per completed task" is the next hard
problem rather than the next feature.
