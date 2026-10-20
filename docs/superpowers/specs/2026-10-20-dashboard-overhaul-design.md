# Dashboard overhaul — design spec

**Date:** 2026-10-20
**Scope:** the dependency-free operations dashboard in `src/backstop/dashboard_ui.py`
**Status:** approved design; executed by `docs/superpowers/plans/2026-10-20-dashboard-overhaul.md`

## Problem

The dashboard renders correct numbers, but as an *operations surface* it fails on
several counts that were confirmed by screenshotting it at five viewports in two
themes:

1. **Numbers are hard to read.** Axis ticks are not round (`50 / 38 / 25 / 13 / 0`),
   because the gridline step is `max / 4`. One formatter (`compact`) mixes grouped
   (`1.2M`) and plain (`12.50`) forms and switches regime at `1e4`, and the traffic
   chart carries a third, ad-hoc formatter. `usd` mixes 4- and 2-decimal forms.
2. **Time is unusable.** The x-axis is relative (`t+0:24`) and shifts on every
   refresh, so a spike cannot be correlated with a log line. The window is fixed to
   the whole in-memory ring; there is no range control.
3. **Space is wasted.** The outcome-mix panel renders two bars inside a 584 px
   panel — the CSS grid stretches every panel to the tallest in its row.
   Sparklines are 28 px strips glued to the bottom edge of a 150 px tile, with a
   void above them.
4. **Dead and missing content.** The Sessions table has a "Provider" column that
   is always `--` (`BackstopState` has no `provider` attribute, so
   `getattr(state, "provider", "")` is always empty). The "exhausts in 52s" chip is
   outlined in red although it is a projection, not an error. The methodology
   footer is eight lines of grey prose. There is no "vs previous window" delta on
   any tile, no annotation of enforcement events on the charts, and no drill-down
   from a tile to the tables.
5. **Accessibility gaps.** Status is conveyed by colour alone (the connection dot,
   the health-coloured tile values, the amber/red chip pair — which is the CVD
   weak point: ΔE ≈ 16.5 under deuteranopia, against a ≈ 20 threshold). The
   `#updated` element is `role="status" aria-live="polite"` but is rewritten every
   second, so a screen reader announces it continuously. The canvases have no text
   alternative, the tooltips are mouse-only and cannot be dismissed with `Esc`,
   and the mobile table hint promises arrow-key navigation that does not exist.
   Auto-refresh cannot be paused (WCAG 2.2.2).

## Constraints (non-negotiable)

* **Dependency-free.** Stdlib-only WSGI, vanilla HTML/CSS/JS, no framework, no
  CDN, no build step. The page must still render air-gapped. `Playwright` is a
  *development* harness only and must not become a package dependency.
* **CSP `default-src 'none'`.** No external origins; the page may not fetch out.
* **No storage, no retention, no query language.** Everything stays derived from
  the in-memory ring, live session state, and the audit tail.
* **The shipped strings are the source of truth.** `PAGE_HTML`, `APP_CSS` and
  `APP_JS` are the exact bytes served by `/`, `/assets/app.css` and
  `/assets/app.js`. The JS owns formatting and chart logic; Python does not
  mirror it.
* **XSS-safe.** Every data-derived string is written with `textContent`.
* **No new runtime dependency, no new CLI flag** unless the task says so.

## Design

### 1. One formatter per quantity

Six named formatters, each used for exactly one kind of quantity, each with a
fixed rule that does not change shape mid-scale:

| Formatter | Quantity | Rule |
|---|---|---|
| `count(v)` | integer counts | `0` → `0`; ≥1e6 → `1.2M`; ≥1e4 → `12.3k`; else thousands-separated integer |
| `axis(v)` | axis ticks | `0` → `0`; ≥1e6 → `1.2M`; ≥1e4 → `12.3k`; else ≤3 significant digits, trailing zeros stripped |
| `rate(v)` | per-second rates | `0` → `0`; ≥100 → 0 dp; ≥10 → 1 dp; else 2 dp |
| `usd(v)` | money | `0` → `$0`; <1 → 4 dp; else 2 dp (magnitude-tiered, documented) |
| `ms(v)` | latency | `0` → `0 ms`; <10 → 2 dp; else 0 dp |
| `dur(s)` | durations | s / m s / h m / d h |

`compact()` is removed. The traffic chart's ad-hoc `yFormat` lambda is removed.
The budget-burn chart's tooltip formatter is replaced by `count()` + the unit
from the panel header.

### 2. Round axis ticks

`niceScale(max, count)` returns `{max, step}` where `step` is `1, 2, 5 or 10`
times a power of ten, and `max` is a whole multiple of `step`. Gridlines are drawn
at `0, step, 2·step, … max`, so every label is a round number and the top label
equals the axis maximum.

### 3. Absolute wall-clock time axis

The snapshot already carries `sampled_at` (absolute epoch of the newest sample)
and `series.t` (offsets from the sampler's start). The client recovers the
sampler's start as `sampled_at - series.t[last]`, so the absolute time of sample
*i* is `sampled_at - (series.t[last] - series.t[i])`. No backend change is
required, and the demo path (which publishes a pre-built snapshot from a child
process) benefits identically.

Each chart header states its own window (`14:32:05 → 14:36:05 · 4m`), so the
unit and the range live in the header rather than on every tick. The x-axis
labels become wall-clock times.

### 4. Window control

A range control (`1m`, `5m`, `15m`, `all`) slices the series client-side. The
ring holds 360 samples — about 12 minutes at the 2 s default and 6 minutes at the
1 s demo cadence — so `15m` legitimately shows everything the ring holds and the
control says so (`all available (6m)`) rather than pretending to have more.

### 5. Pause, and honest freshness

The refresh control gains an `off` option. With it selected, polling stops and
the top bar reads `paused`; the sample-age counter keeps ticking so the data's
age stays visible.

`#updated` stops being a live region. The live announcement moves to
`#data-status`, which is written only when the connection *state changes*, so a
screen reader hears "connection lost" once, not once a second. The connection dot
gains a text label (`live` / `stale` / `lost` / `connecting`), so the state is
never colour-alone.

### 6. Layout: no voids, real tile anatomy

* `.panels` gets `align-items: start`, so a short panel is short.
* The tile becomes a column of: title → status token + value → meta chips →
  sparkline that grows into the remaining height (`flex: 1`). The sparkline is no
  longer a 28 px strip pinned to the bottom.
* Every tile carries a **status token** (`OK` / `WATCH` / `BREACH` / `IDLE` /
  `NO DATA`) as text next to the colour. Colour becomes redundant rather than
  load-bearing, which also resolves the amber↔red CVD weakness: the pair is never
  the only difference between two states.
* The dead "Provider" column is removed from the Sessions table, and the dead
  `provider` key is removed from `session_view()`.
* The Sessions table gets the arrow-key row navigation its on-screen hint already
  promises: `↑`/`↓` move between rows, `←`/`→` scroll horizontally, `Home`/`End`
  jump to the first/last row.
* Warnings collapse from a full-width banner into a compact "needs attention"
  strip of inline chips next to the other top-bar state, so one configuration
  note does not cost a full row of vertical space.

### 7. What changed

* **Deltas.** Every tile that has a series shows the change over the previous
  window of the same length (`+12% vs prev 1m`), computed from the series the
  page already holds. No backend change, no extra storage.
* **Annotations.** Enforcement events carry an absolute `ts`; each event inside
  the visible window becomes a vertical marker on the traffic chart, so a
  guardrail action lines up with the traffic it acted on.
* **Needs attention.** A compact strip lists the actionable states — circuit
  open, budget near exhaustion, stale data, provider errors — as text chips.

### 8. Drill-down

Tiles become activatable (`role="button"`, `tabindex="0"`, Enter/Space
activation). Activating a tile filters the tables below to the rows that explain
that number (Requests → sessions; Spend prevented → enforcement events;
Tenants → tenant rows) and shows a dismissible filter chip. Clicking the active
tile again, or the chip's close button, clears the filter.

### 9. Accessibility

* Canvases get `role="img"` and an `aria-label` summarising the series
  (window, latest value, trend), plus a "table" toggle that renders the same
  numbers as an HTML table — the text alternative and the keyboard path to the
  values.
* The tooltip is dismissible with `Esc` (WCAG 1.4.13) and is hoverable
  (`pointer-events: auto`).
* The tile status tokens, the connection label and the annotation markers all
  carry text, so nothing depends on colour.
* Focus rings exist for every new interactive element.
* `prefers-reduced-motion` still disables all transitions.

### 10. Empty and no-data states

* "No data" is distinct from zero. A tile with no samples reads `NO DATA`; a
  tile with samples but a zero value reads its zero with an explanatory chip
  (`nothing blocked yet`).
* A sparkline with fewer than two points draws a muted dashed baseline instead
  of nothing.
* A chart with no traffic says `no traffic in window`; a chart still collecting
  samples says `collecting samples`. Neither is drawn as an empty box.

## Verification

Two layers, both required:

1. **`scripts/dashboard_audit.py`** — a development harness (Playwright +
   Chromium, `--no-sandbox`) that starts the dashboard in demo mode, visits five
   viewports (`1440×900`, `1280×800`, `820×1180`, `390×844`, `320×700`) in both
   themes, writes full-page and per-panel PNGs, and asserts in-page invariants
   (no clipped table columns, no panel void, round axis labels, a text status on
   every tile, no live-region rewrites). It is not a package dependency and is
   not run by CI.
2. **`tests/test_dashboard_ui.py`** — cheap structural assertions over the exact
   shipped strings (no CDN, the expected controls and ARIA attributes exist, the
   dead column is gone, the removed formatters are not referenced). These run in
   CI.

The goal's completion criterion is the conjunction: every screenshot at every
viewport and theme satisfies the in-page invariants, the audit harness exits
zero, and the full Python test suite passes.

## One backend change

The design needed one field the payload did not carry: a series for the circuit
tile. `BackstopState` exposes the breaker's state but not its history, and the
tile had no series to draw, so it rendered an empty sparkline — a void in the
tile grid. The snapshot now carries `series.circuit_open_rps`, the per-interval
rate of requests the open breaker turned away. It is derived from the sink
counter that was already being read for the `circuit_open` outcome count, so
the cost is one cumulative counter per sample and one series per snapshot. A
breaker that has never opened charts a flat line at zero, which is the honest
picture of that.

The dead `provider` key went the other way: `session_view()` published
`getattr(state, "provider", "")` for every session, and `BackstopState` has no
`provider` attribute, so the Sessions table carried a column that was always
`--`. It was removed from both.

## Out of scope

* No other backend schema change: everything else is derived client-side from
  the payload that already exists.
* No new CLI flag, no new dependency, no change to the WSGI routes.
* No multi-process aggregation, no history beyond the in-memory ring, no saved
  views — the same boundary `docs/dashboard.md` already states.
