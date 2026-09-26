# Runaway eval loop: catch the loud blowup and the silent regression

An AI/ML engineer at a company of any size runs eval loops and iterates prompts.
Two failures, and they are not the same failure. At 02:40 a recursive agent loop
kept calling the model until the credit card noticed. Separately, a prompt edit
silently tripled cost per task — nothing blew up, nothing alerted, and nobody
noticed for thirteen days. The first needs a hard ceiling. The second needs a
ratio, a baseline and a window. Backstop ships both, and is explicit that only
one of them can stop anything.

![A terminal session where an ML engineer wraps an eval loop with a 50,000-token ceiling that blocks 7 of 10 calls before dispatch, then watches the drift detector find a 3.0x cost-per-task regression in shadow mode](./demo.gif)

## The situation

**The loud one.** A recursive loop is easy to fix once you know it happened, and
impossible to fix afterwards. The token cost is the *last* thing to go wrong —
the first thing to go wrong is that nothing in your code has a stopping
condition, because the stopping condition was supposed to be the model's
judgement. Eight hours and $612 later, the ceiling that stopped it was the
provider's.

**The quiet one.** This is the one that actually costs money over a quarter. A
prompt edit that adds two sentences of instructions triples the tokens per task.
Every individual request looks completely normal. No request is anomalous. No
threshold is crossed, because there is no threshold — the previous two weeks of
traffic are the baseline and the new traffic is the baseline now. Cost per task
is the only number that moved, and nobody was looking at cost per task.

You cannot fix the second one with a ceiling. A ceiling is an absolute number, and
an absolute number either fires on the regression (and takes thirteen days of
normal traffic with it) or does not fire at all.

## What backstop does here

### For the loud one: a hard ceiling, reserved before dispatch

- `Backstop.wrap(client, budget=50_000)` is a token ceiling for the session. Each
  request's **estimated** tokens are *reserved* before dispatch and reconciled
  against the provider's reported usage afterwards.
- The estimate is `max(1, prompt_tokens + output_tokens, body_floor)` where
  `output_tokens` is the request's own `max_tokens` or
  `default_max_output_tokens=1024`, and prompt tokens are
  `prompt_chars / chars_per_token` with `chars_per_token=4.0`. Setting
  `auto_token_count=True` swaps the chars/4 heuristic for `tiktoken` when it is
  installed.
- When the reservation does not fit, `BudgetExceededError` is raised before the
  network call. It subclasses `openai.OpenAIError` /
  `anthropic.AnthropicError`, so existing error handling still catches it.
- `backstop demo` shows the whole thing offline, with no key:

  ```
  | Metric            | Unprotected | Wrapped | Change |
  | Calls completed   | 10          | 3       | -7 (-70.0%) |
  | Calls blocked     | 0           | 7       | +7 (blocked in-process) |
  | Tokens consumed   | 250         | 75      | -175 (-70.0%) |
  ```

  10 attempted calls, 3 served, 7 blocked at a 75-token budget. The 7 blocked
  calls never reached the provider.
- `agent_guard` (`AgentGuard`) is a second, independent fence: per-agent-id
  sliding-window ceilings on call count and token spend, for the case where one
  agent inside a longer job is the thing that will not stop.

### For the quiet one: a ratio against your own recent history

- `detection_enabled=True` builds a `RunawayDetector` over a bounded window of
  the last `detection_window_size` events **per attribution key**, and evaluates
  four signals on every submission:

  | signal | fires when |
  |---|---|
  | `velocity` | priced spend per minute over the window exceeds `detection_velocity_threshold_usd_per_min` |
  | `drift` | mean tokens per request in the *recent* half of the window exceeds `detection_baseline_multiplier` × the *older* half |
  | `context_growth` | this request's input tokens exceed the rest of the window's median by `detection_context_growth_threshold` |
  | retry amplification | mean retries per request exceeds `detection_retry_ratio_threshold` |

- **The window is split in half and the older half is the reference period**,
  deliberately: over one shared window the median follows a sustained step change
  and a tripling stays silent forever. That single design choice is the whole
  reason the quiet regression is catchable.
- Each signal is a frozen `DetectionSignal` carrying `kind`, `severity`, `key`,
  `observed`, `threshold`, `detail` and `occurred_at`. In the shipped detector
  run, a 200k-token request against a 20k reference reports
  `context_growth critical 10.0 2.0`, and a tokens-per-request mean of 93,100
  against a 20,500 reference reports `drift warning 93100.0 61500.0 (x1.514,
  multiplier 3)`.
- An **unpriced** event contributes zero to the velocity numerator while still
  being observed for tokens and retries — padding it with a guessed rate would
  make a finance-facing figure look measured.
- Every threshold is a `BackstopConfig` field, and a threshold that would make a
  detector quietly useless is a **construction error**, not a runtime surprise: a
  negative or non-finite threshold, a `baseline_multiplier` below 1.0 (which
  inverts the comparison rather than alerting earlier), a non-positive window, and
  `min_samples > window_size` — a detector that can never speak and looks exactly
  like a healthy one.
- `detection_max_keys` (default 1,024) bounds the number of keys. Eviction is LRU
  and **counted** in `evictions` and exported to the signal sink, because a
  silently evicted key is a key whose baseline silently restarts.

### The part that matters most: detection is report-only

- `detection_shadow=True` is the default. In shadow the same signals are
  produced and also filed in a bounded ring with a per-kind counter, so a
  threshold can be tuned against evidence before it can interrupt anybody.
- **A signal cannot block a request, cancel work, kill an agent, or raise.** That
  is structural, not a promise: nothing exported from the detector returns a
  decision, and a test walks the public API for a verb that could act on a
  request. Auto-kill is absent on purpose — an agent run can be six hours of
  work, and a kill switch that cannot resume destroys it.
- Setting `detection_shadow=False` does **not** make the detector enforce. The
  flag controls whether signals are *filed*; in both modes the caller receives
  records and decides what they are worth. `BACKSTOP_DETECTION_SHADOW` overrides
  the config in either direction, without a redeploy or a restart.

## What you see in the demo

- **Cold open** — 02:40, a recursive loop, 8 hours, $612. And a prompt edit that
  tripled cost per task.
- **Submit** — `backstop demo`: offline mock transport, no key.
- **Stream** — reads `eval/runner.py`, wraps the client with
  `budget=50_000`, turns the ledger on. The demo says the thing out loud: the
  loop had no stopping condition.
- **The ceiling** — the pre-dispatch reservation, the estimate arithmetic,
  `auto_token_count`, and the real `backstop demo` figures: 10 calls served, 7
  blocked, 250 → 75 tokens, 0 provider calls for the 7.
- **The regression** — v8 at 4,100 tok/task, v9 at 12,300, x3.00, and no alert
  for 13 days. Then the three signals that would have caught it, and what each
  one compares.
- **The honest beat** — a signal cannot stop a request, and not in enforcing mode
  either. `detection_shadow=True` by default, signals in a bounded ring per key,
  thirteen days of shadow before tuning anything.
- **Dense resolution** — `Signal(drift, severity=warning)` at observed 93,100
  against threshold 61,500, `Signal(context_growth, critical)` at 200,000 input
  against a 20,000 median, a window per key LRU-capped at 1,024, and an export
  grouped by `agent,experiment` so the regression has an experiment name on it.
- **End card** — one hard ceiling, one soft signal. The ceiling stops; the signal
  explains.

## The commands

```bash
pip install "backstop-ai"

# the command in the GIF: side-by-side runaway loop, offline, no key
backstop demo

# eight offline mechanism checks, including shadow mode and hierarchical budgets
backstop verify

# the same loop against a real provider, opt-in
backstop real-openai

# the wedge, on a fixture repo, three runners
backstop wedge run task.yaml
```

The configuration the demo is describing:

```python
client = Backstop.wrap(
    OpenAI(),
    budget=50_000,                       # the hard ceiling
    config=BackstopConfig(
        ledger_enabled=True,             # so there is something to detect on
        ledger_path="ledger.jsonl",
        detection_enabled=True,
        detection_shadow=True,           # the default
        detection_window_size=16,
        detection_min_samples=8,
        detection_baseline_multiplier=3.0,
        detection_velocity_threshold_usd_per_min=1.0,
    ),
)
agent_guard = AgentGuard(max_calls=100, window_seconds=60.0, max_tokens=200_000)
```

and the per-key scoping that makes the ratio mean something:

```python
with attribution(agent="refund-bot", experiment="prompt-v9"):
    client.chat.completions.create(...)
```

## What this does NOT solve

- **The detector cannot stop anything.** It reports. It cannot block, cancel or
  kill, in shadow mode or out of it. Deciding what a `DetectionSignal` is worth —
  alerting, opening a ticket, tightening a budget by hand — is the caller's job,
  and nothing in this library makes that decision for you.
- **`detection_shadow=False` is not an enforcement switch.** It changes whether
  signals are filed in the shadow log. It does not make the detector act.
- **Spend avoided is not in the ledger.** A blocked request produces no
  `SpendEvent`, because there is no usage report and no dollars. Spend that was
  prevented lives on the enforcement surface instead: `budget_exceeded` /
  `rate_limited` counters, the `requests{outcome=circuit_open|exception}`
  breakdown, and the audit log's `deny` records. Do not expect the chargeback and
  the savings to be the same number.
- **Three of the six `SpendEvent` outcomes never reach the ledger.**
  `circuit_open`, `budget_denied` and `queue_timeout` describe requests that
  never reached a provider. They stay in the schema so a durable line written by a
  future build still validates, but there is no row for them.
- **Drift needs a baseline you actually generate.** The reference period is the
  older half of your own window, so a detector switched on *after* the prompt
  edit has nothing to compare against. Turning it on before the change is the
  whole trick.
- **A streaming request is a floor, not a measurement.** There is no usage report
  at stream setup, so the event is recorded at dispatch with `estimated=True` and
  `output_tokens=0`. That is a visible understatement rather than a confident
  wrong split — but it does bias a tokens-per-request ratio if your evals stream.
- **The rate card is a dated snapshot.** `BUNDLED_EFFECTIVE_FROM = "2026-09-26"`,
  and nothing in this repository detects a provider rate change. The `velocity`
  signal is denominated in dollars, so a stale rate moves it.
- **The Anthropic cache-write rate is the 5-minute tier.** A deployment on a
  **1-hour cache TTL is under-counted** on its cache writes by ~37.5% of that
  component, and nothing in the record reveals it, because `cache_write` *is* in
  `priced_components` — the row looks fully priced. This is a silent
  under-count, the worst failure class in the ledger, and the top open item in
  `docs/planning/07-risks-and-killshots.md`.
- **Turning the ledger on roughly doubles the cost of a request**: +147 µs p50
  (+98%) on a 150 µs request, measured on Python 3.12.3/Linux over 7 alternating
  runs, with the ledger-off p50 spread across runs being 147.0–156.2 µs. The
  default path (ledger off) is unaffected and stays sub-millisecond.
- **One day of one shape is not a trend.** `backstop forecast` projects *budget
  exhaustion* from a measured burn rate; it does not project spend, and there is
  no cross-customer benchmark to compare a number against.

## Where to read more

- [`docs/ledger.md`](../../docs/ledger.md) — "Detection, and shadow mode", the
  four signals, `observed`/`threshold` pairs, the measured cost of the ledger, and
  every known limitation.
- [`docs/planning/04-detection-design.md`](../../docs/planning/04-detection-design.md)
  — why the window is split in half, and why auto-kill is absent.
- [`src/backstop/detection/detector.py`](../../src/backstop/detection/detector.py)
  — `observe()`'s docstring is the clearest statement of the report-only contract.
- [`src/backstop/extract.py`](../../src/backstop/extract.py) — `estimate_tokens`
  and the priority header.
- [`src/backstop/agent_guard.py`](../../src/backstop/agent_guard.py) — the
  per-agent sliding window.
- [`CHANGELOG.md`](../../CHANGELOG.md) — the `## [Unreleased]` entry for the
  ledger and the detector, including the corrections.
- [`usecases/README.md`](../README.md) — the other use cases.
