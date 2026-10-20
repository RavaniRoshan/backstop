# Runaway-spend detection

A budget is a ceiling. It stops you going over. It does not tell you that
you are *about* to go over, that the spend is accelerating, that every request
now costs three times what it did yesterday, or that a loop has started
retrying harder than it used to.

That is what the detectors are for. Four of them, over a bounded window of the
last N events **per attribution key**, each producing a signal when a
measurement crosses a threshold you set.

```python
from backstop import BackstopConfig

config = BackstopConfig(
    detection_enabled=True,
    detection_shadow=True,          # report, never block — the default
)
```

---

## The four detectors

| Detector | What it measures | Fires when |
|---|---|---|
| **Velocity** | priced spend per minute, per key | the rate crosses `detection_velocity_threshold_usd_per_min` |
| **Drift** | tokens per request, recent half against older half | the ratio crosses `detection_baseline_multiplier` |
| **Retry amplification** | retries against requests | the ratio crosses `detection_retry_ratio_threshold` |
| **Context growth** | the size of each request's context | the growth crosses `detection_context_growth_threshold` |

Every threshold is reachable from configuration, because a threshold that
cannot be changed is a threshold nobody can tune — and tuning against a
shadow log is the whole purpose of shadow mode.

---

## Shadow mode is the default

`detection_shadow=True` is the default, and it is the right default: the
signals are produced and filed in a bounded log with a per-kind counter, but
**nothing is blocked**. You watch a real traffic pattern for a while, tune the
thresholds against what you saw, and only then let them interrupt anybody.

```python
config = BackstopConfig(
    detection_enabled=True,
    detection_shadow=False,     # now they act
)
```

The kill-switch works in both directions: `BACKSTOP_DETECTION_SHADOW` overrides
the config, so a misconfigured shadow can be turned off without a redeploy.

**What shadow mode does not do:** it does not make the detector's verdict
enforceable on the spend itself. A detector reports; it cannot block, cancel
or kill. A dollar *ceiling* is what stops the spend — see
[usd-budgets.md](usd-budgets.md) — and a detector is how you find out you are
about to need one.

---

## Where the signals go

Two instruments and no more, so the series count is fixed however many
attribution keys fire:

- a counter, `detection_signals`, labelled by detector kind and severity, so
  a dashboard and an alert can see that a key is misbehaving;
- a histogram, `detection_signal_magnitude`, of the value that crossed the
  threshold, so the threshold can be set from the *distribution* of what
  actually crossed it rather than from a count that says only that something
  did.

**The attribution is not a label.** A per-team or per-session label multiplies
the time series by the number of teams or sessions — a cardinality explosion in
the scrape, and a user identifier in a label is a user identifier in everyone's
monitoring storage. The offending key belongs in the detector's own bounded
ring and in the log line, not in a label.

---

## Attribution keys

The window is keyed by the frozen `Attribution` itself, so per-key isolation
cannot be got wrong. Both the number of keys and the size of each window are
bounded by construction, and the bound matters most for a deployment
attributing per session — which would otherwise hold one window per request
for the life of the process.

```python
from backstop import attribution

with attribution(team="payments", feature="checkout-v2"):
    client.chat.completions.create(...)
```

**Eviction is least-recently-used and counted.** A silently evicted key is a
key whose baseline silently restarts, and a detector that has forgotten looks
exactly like a healthy one. `detection_evictions` counts them.

---

## A threshold that can never fire

A threshold that would make a detector quietly useless is a construction
error, not a runtime surprise. `BackstopConfig` refuses, at construction:

- a negative or non-finite threshold;
- a `baseline_multiplier` below 1.0, which inverts the comparison rather than
  alerting earlier;
- a non-positive window;
- `min_samples` greater than the window size, which is a detector that can
  never speak and looks exactly like a healthy one.

---

## Over a ledger file

The same detectors, run over a file rather than over live traffic — so you can
see what a deployment *would* have been told, before it is told:

```bash
backstop detect --ledger ledger.jsonl
backstop detect --ledger ledger.jsonl --json
```

---

## What it does not do

- **It does not block.** A detector reports. A ceiling is what stops the
  spend.
- **It does not forecast.** It measures the recent past. `backstop forecast`
  projects exhaustion from a burn rate; see [usd-budgets.md](usd-budgets.md).
- **It does not see across deployments.** Every signal is computed in one
  process, from one process's traffic.
- **It does not model intent.** A high velocity is not automatically a bug; it
  may be exactly what the deployment is for. The signal says "look here", not
  "this is wrong".
