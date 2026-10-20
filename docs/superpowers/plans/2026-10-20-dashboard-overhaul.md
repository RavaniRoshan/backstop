# Dashboard Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** executed 2026-10-20. All nine tasks are complete; the audit harness
(`scripts/dashboard_audit.py`) exits zero at five viewports in two themes, and
the full test suite passes.

Two defects were found by looking at the screenshots rather than by reading the
code, and were fixed on top of the plan: a canvas whose auto height derived
from its intrinsic aspect ratio and fed that back into the backing store, so
the tile grew without bound; and a tile grid built on `auto-fit` that left
holes in the second row and truncated a headline value to fit. Both are now
covered by harness invariants.

**Goal:** Turn the built-in Backstop dashboard into a trustworthy operations surface: round axis ticks, one formatter per quantity, a wall-clock time axis with a window control, a pausable refresh, no wasted space, no colour-only status, keyboard paths to every value, and a screenshot-verified layout at five viewports in two themes.

**Architecture:** All three artefacts (`PAGE_HTML`, `APP_CSS`, `APP_JS`) stay as Python string literals in `src/backstop/dashboard_ui.py` and remain the exact bytes served by `/`, `/assets/app.css` and `/assets/app.js`. The JavaScript owns all formatting and chart logic; Python changes are limited to (a) removing one dead snapshot field and (b) nothing else — every new capability is derived client-side from the snapshot payload that already exists. Verification is two-layered: `scripts/dashboard_audit.py` (a Playwright screenshot + in-page assertion harness, development-only, not a dependency) and `tests/test_dashboard_ui.py` (cheap structural assertions over the shipped strings, runs in CI).

**Tech Stack:** Python 3.10+ stdlib only (`http.server`/WSGI), vanilla HTML5, CSS custom properties, ES5-compatible JavaScript (no build step, no bundler, no CDN). Playwright + Chromium for the audit harness only.

**Spec:** `docs/superpowers/specs/2026-10-20-dashboard-overhaul-design.md`

## Global Constraints

- The dashboard stays dependency-free: no framework, no CDN, no build step, no new runtime dependency. `Playwright` is a development harness and must never appear in `pyproject.toml` dependencies.
- The CSP stays `default-src 'none'` with self-only styles and scripts. The page must make zero outbound requests.
- No new snapshot fields and no change to the WSGI routes (`/`, `/api/snapshot`, `/assets/*`, `/healthz`). Everything added is derived client-side from the existing payload.
- Every data-derived string is written with `textContent`. `innerHTML` is forbidden anywhere in `APP_JS`.
- Status is never conveyed by colour alone: every state that carries colour also carries a text token.
- `role="status"` / `aria-live` regions are written only on a *state transition*, never on a timer tick.
- One formatter per quantity. A quantity never changes its textual shape mid-scale.
- The JS is ES5-compatible: `var`, `function`, no arrow functions, no template literals, no `let`/`const` — the file already follows this and the browser target is unknown.
- A structural assertion for a feature that has not landed yet carries `@pending("Task N")`,
  an `xfail` that keeps CI green and flips to a pass when the task lands. Each task
  removes the marker for its own assertions; the final verification asserts that no
  `@pending` marker remains, so a shipped feature can never keep a false-negative.
- Test command is `python3 -m pytest` from the repository root. The audit harness is run manually: `python3 scripts/dashboard_audit.py --out /tmp/shots-after`.

---

### Task 1: The screenshot and assertion audit harness

**Files:**
- Create: `scripts/dashboard_audit.py`
- Create: `tests/test_dashboard_ui.py`

**Interfaces:**
- Consumes: `backstop.dashboard_app.dashboard_wsgi_app` (nothing yet — the harness starts a real server process); the running page at `http://127.0.0.1:<port>/`.
- Produces: a CLI `python3 scripts/dashboard_audit.py --out DIR [--url URL] [--viewports ...] [--themes ...]` that writes `<viewport>-<theme>.png` full-page shots plus `panels/<viewport>-<theme>-<panel>.png` crops, prints one line per failed invariant, and exits `1` if any invariant failed.
- Produces: `tests/test_dashboard_ui.py` with a module-level helper `js() -> str`, `css() -> str`, `page() -> str` that return the shipped `APP_JS`, `APP_CSS` and `PAGE_HTML` strings, imported from `backstop.dashboard_ui`.

- [x] **Step 1: Write the structural test file**

Every structural assertion lives in `tests/test_dashboard_ui.py` from Task 1
onward, so the file does not churn. Assertions for a feature that a later task
has not implemented yet are marked `@pending("Task N")` — an `xfail` that keeps
CI green while the feature is absent, and that flips to a pass the moment the
task lands. **Each task removes the `@pending` marker from its own
assertions.** A marker that is left behind after the feature ships is a
false-negative, so the final verification step asserts that no `@pending`
marker remains.

Create `tests/test_dashboard_ui.py`:

```python
"""Structural assertions over the exact bytes the dashboard serves.

These are cheap and CI-safe: they read the shipped strings, not a browser. The
browser-level verification lives in ``scripts/dashboard_audit.py``, which is a
development harness and not a test dependency.

Assertions for a feature that has not landed yet carry ``@pending("Task N")``:
an xfail that keeps CI green and flips to a pass when the task lands. Every
task removes the marker for its own assertions.
"""
from __future__ import annotations

import pytest

from backstop.dashboard_ui import APP_CSS, APP_JS, PAGE_HTML


def js() -> str:
    return APP_JS


def css() -> str:
    return APP_CSS


def page() -> str:
    return PAGE_HTML


def pending(task: str):
    """Mark an assertion whose feature lands in a later task."""
    return pytest.mark.xfail(reason="lands in " + task, strict=False)


def test_the_page_loads_no_external_origin():
    assert "http://" not in page()
    assert "https://" not in page()
    assert "@import" not in css()


@pending("Task 3")
def test_the_refresh_control_can_be_turned_off():
    assert '<option value="0">off</option>' in page()


@pending("Task 3")
def test_the_window_control_exists():
    assert 'id="window"' in page()


@pending("Task 4")
def test_every_tile_has_a_status_token_slot():
    assert page().count('data-slot="status"') == 7


@pending("Task 4")
def test_the_dead_provider_column_is_gone():
    assert "<th>Provider</th>" not in page()
    assert "row.provider" not in js()


@pending("Task 3")
def test_the_connection_state_has_a_text_label():
    assert 'id="conn-label"' in page()


@pending("Task 3")
def test_the_updated_element_is_not_a_live_region():
    # Continuous aria-live announcements are a WCAG 2.2.2 / screen-reader bug:
    # the text changes every second, so the region must not be live.
    assert 'id="updated" role="status"' not in page()
    assert 'aria-live="polite"' in page()


@pending("Task 2")
def test_the_removed_compact_formatter_is_not_used():
    assert "function compact(" not in js()
    assert "compact(" not in js()


@pending("Task 2")
def test_the_axis_uses_a_nice_scale_not_max_over_four():
    assert "function niceScale(" in js()
    assert "maxV / 4" not in js()


@pending("Task 7")
def test_canvases_declare_a_text_alternative():
    assert 'role="img"' in page()
    assert "aria-label" in js()


@pending("Task 7")
def test_the_tooltip_can_be_dismissed_with_escape():
    assert '"Escape"' in js()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: FAIL — `test_the_refresh_control_can_be_turned_off` fails because `<option value="0">off</option>` is not in `PAGE_HTML`.

- [x] **Step 3: Write the audit harness**

Create `scripts/dashboard_audit.py`:

```python
#!/usr/bin/env python3
"""Screenshot the built-in dashboard and assert the invariants it must hold.

Development harness, not a test dependency: Playwright and Chromium are not
package dependencies of ``backstop-ai`` and CI does not run this.

    python3 scripts/dashboard_audit.py --out /tmp/shots

Starts ``backstop dashboard --demo`` on a free port, visits every
viewport/theme combination, writes a full-page PNG plus one crop per panel,
and asserts the in-page invariants the design spec lists. Exits non-zero if
any invariant fails.
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

VIEWPORTS = {
    "desktop": (1440, 900),
    "laptop": (1280, 800),
    "tablet": (820, 1180),
    "mobile": (390, 844),
    "narrow": (320, 700),
}
THEMES = ("dark", "light")

CHROMIUM = os.environ.get("DASHBOARD_AUDIT_CHROMIUM", "/snap/bin/chromium")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for(url: str, timeout: float = 25.0) -> bool:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as res:
                if res.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


# Each invariant runs in the page and returns a list of failure strings.
INVARIANTS = """
() => {
  const fails = [];
  const doc = document;

  // 1. Every tile carries a text status token next to its colour.
  doc.querySelectorAll('.tile').forEach((tile) => {
    const status = tile.querySelector('[data-slot="status"]');
    const text = status ? (status.textContent || '').trim() : '';
    if (!text) fails.push('tile ' + tile.id + ' has no status token');
  });

  // 2. The connection state is not colour-only.
  const label = doc.querySelector('#conn-label');
  if (!label || !(label.textContent || '').trim()) {
    fails.push('connection state has no text label');
  }

  // 3. No table is clipped: every cell is inside its scroll container's box.
  doc.querySelectorAll('.table-wrap').forEach((wrap) => {
    if (wrap.hidden) return;
    const rows = wrap.querySelectorAll('tbody tr');
    rows.forEach((row) => {
      const cells = row.querySelectorAll('td, th');
      cells.forEach((cell) => {
        const r = cell.getBoundingClientRect();
        if (r.width === 0) return;
        const w = wrap.getBoundingClientRect();
        if (r.right > w.right + 1 && wrap.scrollWidth <= wrap.clientWidth + 1) {
          fails.push('table cell clipped without scroll: ' + cell.textContent.trim());
        }
      });
    });
  });

  // 4. No panel void: a panel's content fills it.
  doc.querySelectorAll('.panel').forEach((panel) => {
    const h = panel.getBoundingClientRect().height;
    const kids = Array.from(panel.children).filter((c) => !c.classList.contains('empty'));
    const used = kids.reduce((sum, c) => {
      const r = c.getBoundingClientRect();
      return sum + (r.height || 0);
    }, 0);
    if (h > 0 && used > 0 && used < h * 0.45) {
      fails.push('panel ' + (panel.querySelector('h2') || {}).textContent +
        ' has a void: ' + Math.round(h) + 'px tall, ' + Math.round(used) + 'px used');
    }
  });

  // 5. Axis tick labels are round numbers.
  doc.querySelectorAll('canvas').forEach((canvas) => {
    const spec = canvas.__spec;
    if (!spec || !spec.tickLabels) return;
    spec.tickLabels.forEach((label) => {
      if (!/^-?[0-9]+(\\.[0-9]+)?(k|M|B)?$/.test(label)) {
        fails.push('axis label is not round: ' + label);
      }
    });
  });

  // 6. Canvas charts have a text alternative.
  doc.querySelectorAll('canvas.chart, canvas[data-chart]').forEach((canvas) => {
    if (!canvas.getAttribute('role')) fails.push('chart canvas has no role');
    if (!(canvas.getAttribute('aria-label') || '').trim()) {
      fails.push('chart canvas has no aria-label');
    }
  });

  // 7. Nothing overflows the viewport horizontally.
  if (doc.documentElement.scrollWidth > window.innerWidth + 1) {
    fails.push('horizontal page overflow: ' + doc.documentElement.scrollWidth +
      ' > ' + window.innerWidth);
  }

  return fails;
}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="output directory for PNGs")
    parser.add_argument("--url", default=None, help="use an already-running dashboard")
    parser.add_argument("--viewports", default=",".join(VIEWPORTS))
    parser.add_argument("--themes", default=",".join(THEMES))
    parser.add_argument("--keep-server", action="store_true")
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    panels_dir = out / "panels"
    panels_dir.mkdir(parents=True, exist_ok=True)

    proc = None
    url = args.url
    if url is None:
        port = free_port()
        url = f"http://127.0.0.1:{port}/"
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        proc = subprocess.Popen(
            [sys.executable, "-m", "backstop", "dashboard", "--port", str(port),
             "--demo", "--runners", "6", "--cost-model", "gpt-4o",
             "--theme", "auto", "--no-browser"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not wait_for(url):
            proc.terminate()
            print("dashboard did not start", file=sys.stderr)
            return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed; this is a development-only harness",
              file=sys.stderr)
        if proc and not args.keep_server:
            proc.terminate()
        return 2

    failures = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
            for name in args.viewports.split(","):
                name = name.strip()
                if name not in VIEWPORTS:
                    continue
                width, height = VIEWPORTS[name]
                for theme in args.themes.split(","):
                    theme = theme.strip()
                    if theme not in THEMES:
                        continue
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.goto(url, wait_until="networkidle")
                    page.evaluate("t => document.documentElement.dataset.theme = t", theme)
                    page.wait_for_timeout(1200)
                    shot = out / f"{name}-{theme}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    for index, panel in enumerate(page.query_selector_all(".panel")):
                        title = (panel.query_selector("h2") or {}).text_content or f"p{index}"
                        slug = "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-")
                        try:
                            panel.screenshot(path=str(panels_dir / f"{name}-{theme}-{slug}.png"))
                        except Exception:
                            pass
                    for problem in page().evaluate(INVARIANTS):
                        failures.append(f"[{name}-{theme}] {problem}")
                    page.close()
            browser.close()
    finally:
        if proc and not args.keep_server:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    print(f"shots written to {out}")
    if failures:
        print("\nFAILED INVARIANTS:")
        for line in failures:
            print("  -", line)
        return 1
    print("all invariants hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Run the harness to see it report the current failures**

Run: `python3 scripts/dashboard_audit.py --out /tmp/shots-before`
Expected: the harness starts the demo dashboard, writes 10 PNGs (5 viewports × 2 themes) plus panel crops, and exits `1` with a non-empty `FAILED INVARIANTS` list naming the missing status tokens, the missing connection label, the outcome-mix void, and the horizontal overflow.

- [x] **Step 5: Commit**

```bash
git add scripts/dashboard_audit.py tests/test_dashboard_ui.py
git commit -m "test(dashboard): add screenshot audit harness and structural UI tests"
```

---

### Task 2: Number and axis correctness

**Files:**
- Modify: `src/backstop/dashboard_ui.py` (`APP_JS`: the formatting block at the `/* --- formatting --- */` marker and the gridline loop inside `drawChart`; `APP_HTML` is not touched)
- Test: `tests/test_dashboard_ui.py`

**Interfaces:**
- Consumes: nothing from earlier tasks except the `js()` / `css()` / `page()` helpers from Task 1.
- Produces (JS, all inside the existing IIFE in `APP_JS`):
  - `count(v) -> string` — integer counts.
  - `axis(v) -> string` — axis tick labels.
  - `rate(v) -> string` — per-second rates.
  - `usd(v) -> string` — money.
  - `ms(v) -> string` — latency.
  - `dur(s) -> string` — durations (unchanged).
  - `pct(v, digits) -> string` — unchanged.
  - `niceScale(max, count) -> {max: number, step: number}`.
  - `axisTicks(max, step, format) -> string[]` — the label list, also stored on `canvas.__spec.tickLabels` for the audit harness.
- `compact(v)` is removed. Every former call site is rewritten.

- [x] **Step 1: Add the failing structural assertions**

In `tests/test_dashboard_ui.py`, remove the `@pending("Task N")` marker from
this task's assertions and add any assertion that is not already listed:

```python
def test_one_formatter_per_quantity():
    for name in ("count(", "axis(", "rate(", "usd(", "ms(", "dur(", "pct("):
        assert "function " + name in js()
    assert "function compact(" not in js()
    assert "compact(" not in js()


def test_the_traffic_chart_has_no_ad_hoc_formatter():
    assert "yFormat: function" not in js()


def test_nice_scale_produces_round_steps():
    # The scale must land on 1/2/5/10 x 10^n.
    assert "step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10" in js()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: FAIL on `test_one_formatter_per_quantity` — `compact(` is still present.

- [x] **Step 3: Replace the formatting block**

In `src/backstop/dashboard_ui.py`, replace the whole `compact`/`count`/`ms`/`usd`/`dur`/`pct`/`clock`/`rel` block inside `APP_JS` with:

```javascript
  /* --- formatting -------------------------------------------------------
     One formatter per quantity, and one textual shape per formatter. A
     quantity never changes shape mid-scale, so a reader never has to
     re-learn what "12.3k" or "12.50" means. */
  function isNil(v) { return v === null || v === undefined; }

  function sig(v, digits) {
    // At most `digits` significant digits, trailing zeros stripped.
    var abs = Math.abs(v);
    if (abs === 0) return "0";
    var mag = Math.pow(10, Math.floor(Math.log10(abs)));
    var scaled = v / mag;
    var rounded = Number(scaled.toFixed(digits - 1));
    if (Math.abs(rounded) >= 10) return String(rounded);
    return String(Number(rounded.toFixed(digits)));
  }

  function count(v) {
    if (isNil(v)) return "--";
    var abs = Math.abs(v);
    if (abs >= 1e9) return (v / 1e9).toFixed(2) + "B";
    if (abs >= 1e6) return (v / 1e6).toFixed(1) + "M";
    if (abs >= 1e4) return (v / 1e3).toFixed(1) + "k";
    return Math.round(v).toLocaleString();
  }

  function axis(v) {
    if (isNil(v)) return "--";
    var abs = Math.abs(v);
    if (abs >= 1e9) return (v / 1e9).toFixed(1) + "B";
    if (abs >= 1e6) return (v / 1e6).toFixed(1) + "M";
    if (abs >= 1e4) return (v / 1e3).toFixed(1) + "k";
    return sig(v, 3);
  }

  function rate(v) {
    if (isNil(v)) return "--";
    if (v === 0) return "0";
    var abs = Math.abs(v);
    if (abs >= 100) return v.toFixed(0);
    if (abs >= 10) return v.toFixed(1);
    return v.toFixed(2);
  }

  function usd(v) {
    if (isNil(v)) return "--";
    if (v === 0) return "$0";
    // Magnitude-tiered on purpose: sub-cent lower bounds are real, and a
    // lower bound that rounds to $0.00 would read as "free".
    return "$" + (Math.abs(v) < 1 ? v.toFixed(4) : v.toFixed(2));
  }

  function ms(v) {
    if (isNil(v)) return "--";
    if (v === 0) return "0 ms";
    return v < 10 ? v.toFixed(2) + " ms" : v.toFixed(0) + " ms";
  }

  function dur(seconds) {
    if (isNil(seconds)) return "--";
    var s = Math.max(0, Math.round(seconds));
    if (s < 60) return s + "s";
    if (s < 3600) return Math.floor(s / 60) + "m " + (s % 60) + "s";
    if (s < 86400) return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
    return Math.floor(s / 86400) + "d " + Math.floor((s % 3600) / 60) + "m";
  }

  function pct(v, digits) {
    if (isNil(v)) return "--";
    return (v * 100).toFixed(digits === undefined ? 1 : digits) + "%";
  }

  function clock(t) {
    var d = new Date(t * 1000);
    return d.toLocaleTimeString(undefined, { hour12: false });
  }
```

Delete the old `rel(offsetSeconds)` helper — the time axis becomes wall-clock in Task 3, so nothing needs a relative label afterwards.

- [x] **Step 4: Rewrite every `compact(` call site**

In `APP_JS`, replace the call sites with the formatter that matches the quantity:

| Old call | New call | Where |
|---|---|---|
| `compact(budget.remaining)` | `count(budget.remaining)` | `renderTile("#tile-budget", …)` |
| `compact(budget.burn_tokens_per_min)` | `count(budget.burn_tokens_per_min)` | budget tile meta |
| `compact(spend.tokens)` | `count(spend.tokens)` | spend tile |
| `compact(budget.pct_used)` (none) | — | — |
| `traffic.rps >= 10 ? traffic.rps.toFixed(0) : traffic.rps.toFixed(2)` | `rate(traffic.rps)` | requests tile value |
| `format: function (v) { return compact(v) + " tok/min"; }` | `format: function (v) { return count(v); }` | budget-burn series (the unit now lives in the panel header) |
| `var yFmt = spec.yFormat \|\| compact;` | `var yFmt = spec.yFormat \|\| axis;` | `drawChart` |

- [x] **Step 5: Replace the gridline loop with a nice scale**

In `APP_JS`, replace `function niceMax(v) { … }` with:

```javascript
  // A scale whose step is 1, 2, 5 or 10 times a power of ten, so every
  // gridline label is a round number an operator can do arithmetic on.
  function niceScale(max, count) {
    var target = count || 4;
    if (!(max > 0)) return { max: 1, step: 0.25 };
    var raw = max / target;
    var mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var n = raw / mag;
    var step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
    step *= mag;
    return { max: Math.ceil(max / step) * step, step: step };
  }
```

Then replace the gridline loop in `drawChart`:

```javascript
    var scale = niceScale(maxV, 4);
    maxV = scale.max;
    var step = scale.step;
    var tickLabels = [];
    ctx.strokeStyle = THEME.line;
    ctx.lineWidth = 1;
    ctx.fillStyle = THEME.dim;
    ctx.font = "10px " + MONO;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (var gv = 0; gv <= maxV + step * 0.001; gv += step) {
      var gy = Math.round(yAt(gv)) + 0.5;
      ctx.beginPath(); ctx.moveTo(PAD_L, gy); ctx.lineTo(w - PAD_R, gy); ctx.stroke();
      var label = yFmt(gv);
      tickLabels.push(label);
      ctx.fillText(label, PAD_L - 7, gy);
    }
    canvas.__tickLabels = tickLabels;
```

`maxV` is computed before the loop; keep the existing `maxV = Math.max(maxV, spec.threshold)` line and delete the old `maxV = niceMax(maxV <= 0 ? 1 : maxV);` line.

- [x] **Step 6: Run the tests**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: `test_one_formatter_per_quantity`, `test_the_traffic_chart_has_no_ad_hoc_formatter` and `test_nice_scale_produces_round_steps` PASS; `test_the_removed_compact_formatter_is_not_used` PASSES. Other assertions still fail (they belong to later tasks).

- [x] **Step 7: Commit**

```bash
git add src/backstop/dashboard_ui.py tests/test_dashboard_ui.py
git commit -m "feat(dashboard): one formatter per quantity and round axis ticks"
```

---

### Task 3: Wall-clock time axis, window control, pause, honest freshness

**Files:**
- Modify: `src/backstop/dashboard_ui.py` (`PAGE_HTML`: the top bar and the two chart panels; `APP_CSS`: the top-bar and chart-header rules; `APP_JS`: `drawChart`, the x-tick block, the polling block, `ticker`)
- Test: `tests/test_dashboard_ui.py`

**Interfaces:**
- Consumes: `axis(v)`, `count(v)` from Task 2.
- Produces (JS):
  - `absoluteTimes(snap) -> number[]` — absolute epoch seconds per sample, derived as `sampled_at - (series.t[last] - series.t[i])`; returns `[]` when `sampled_at` is null.
  - `sliceWindow(times, seconds) -> {from: number, to: number}` — the index range of the selected window.
  - `applyWindow(series, times, range) -> series` — the sliced series object.
  - `windowSeconds` (module state), set from `#window`.
  - `refreshMs` may be `0`, meaning paused.
- `PAGE_HTML` gains: `<select id="window">` with `1m`, `5m`, `15m`, `all`; `<option value="0">off</option>` in `#refresh`; `<span id="conn-label">`; `<span class="chip" id="paused-chip" hidden>paused</span>`.

- [x] **Step 1: Add the failing structural assertions**

In `tests/test_dashboard_ui.py`, remove the `@pending("Task N")` marker from
this task's assertions and add any assertion that is not already listed:

```python
def test_the_window_control_offers_ranges():
    assert 'id="window"' in page()
    for label in ("1m", "5m", "15m", "all"):
        assert ">%s</option>" % label in page()


def test_the_axis_is_wall_clock_not_relative():
    assert "function absoluteTimes(" in js()
    assert 'rel(' not in js()


def test_the_refresh_can_be_paused():
    assert '<option value="0">off</option>' in page()
    assert "paused" in js()


def test_the_live_region_is_only_written_on_a_transition():
    assert "function announce(" in js()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: FAIL on `test_the_window_control_offers_ranges`.

- [x] **Step 3: Add the controls to the page**

In `PAGE_HTML`, replace the top-bar right-hand block:

```html
  <div class="topbar-right">
    <span class="badge" id="mode-badge">__MODE__</span>
    <span class="conn" id="conn" data-state="pending" title="snapshot freshness"></span>
    <span class="muted" id="conn-label">connecting</span>
    <span class="muted" id="updated">connecting</span>
    <span class="chip" id="paused-chip" hidden>paused</span>
    <label class="muted refresh-field">refresh
      <select id="refresh">
        <option value="1000">1s</option>
        <option value="2000">2s</option>
        <option value="5000">5s</option>
        <option value="30000">30s</option>
        <option value="0">off</option>
      </select>
    </label>
    <label class="muted refresh-field">window
      <select id="window">
        <option value="60">1m</option>
        <option value="300">5m</option>
        <option value="900">15m</option>
        <option value="0">all</option>
      </select>
    </label>
    <button class="badge theme-toggle" id="theme-toggle" type="button"
      title="switch colour theme">theme</button>
  </div>
```

And replace the two chart panel headers so they can carry a window label:

```html
    <article class="panel span-2">
      <header><h2>Throughput and prevention</h2><span class="unit">per second</span></header>
      <div class="chart-wrap"><canvas id="chart-traffic" role="img" aria-label="throughput and prevention"></canvas></div>
      <div class="chart-axis" id="axis-traffic"></div>
      <div class="legend" id="legend-traffic"></div>
    </article>

    <article class="panel">
      <header><h2>Budget burn</h2><span class="unit">tokens / min</span></header>
      <div class="chart-wrap"><canvas id="chart-burn" role="img" aria-label="budget burn"></canvas></div>
      <div class="chart-axis" id="axis-burn"></div>
      <div class="legend" id="legend-burn"></div>
    </article>
```

- [x] **Step 4: Add the CSS for the new elements**

Append to `APP_CSS`:

```css
/* Context strip: the window a chart actually shows, so the x-axis never has
   to carry the unit and the range on every tick. */
.chart-axis {
  color: var(--dim); font-size: 10px; font-family: var(--mono);
  display: flex; justify-content: space-between; gap: 10px;
}
.conn-label { color: var(--muted); font-size: 11px; }
#paused-chip { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 40%, transparent); }
```

Also widen the chart's left gutter so a five-digit label fits:

```css
.chart-wrap { position: relative; height: 168px; }
```
becomes
```css
.chart-wrap { position: relative; height: 168px; }
```
with `var PAD_L = 46` raised to `var PAD_L = 54` in the JS (Task 3, Step 5).

- [x] **Step 5: Make the x-axis wall-clock and window-aware**

In `APP_JS`, add after the `clock` helper:

```javascript
  /* The snapshot carries sampled_at (absolute epoch of the newest sample) and
     series.t (offsets from the sampler's start). Recovering the sampler's
     start gives absolute wall-clock time for every point, so a spike can be
     lined up with a log line instead of a moving relative label. */
  function absoluteTimes(snap) {
    var series = snap.series || {};
    var offsets = series.t || [];
    if (!offsets.length) return [];
    var sampledAt = snap.sampled_at;
    if (isNil(sampledAt)) return [];
    var last = offsets[offsets.length - 1];
    return offsets.map(function (offset) { return sampledAt - (last - offset); });
  }

  function windowRange(times) {
    if (!times.length) return { from: 0, to: 0 };
    var seconds = windowSeconds;
    if (!seconds) return { from: 0, to: times.length - 1 };
    var newest = times[times.length - 1];
    var oldest = newest - seconds;
    var from = 0;
    for (var i = 0; i < times.length; i++) {
      if (times[i] >= oldest) { from = i; break; }
      from = i;
    }
    return { from: from, to: times.length - 1 };
  }
```

Replace the x-tick block in `drawChart` (the `var ticks = [0, Math.floor(lastIndex / 2), lastIndex];` block) with:

```javascript
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    var lastIndex = t.length - 1;
    var ticks = [0, Math.floor(lastIndex / 2), lastIndex];
    ticks.forEach(function (index, position) {
      if (position > 0 && ticks[position - 1] === index) return;
      ctx.textAlign = index === 0 ? "left" : index === lastIndex ? "right" : "center";
      var stamp = spec.times ? spec.times[index] : null;
      ctx.fillText(isNil(stamp) ? "--" : clock(stamp), xAt(index), PAD_T + innerH + 5);
    });
```

and set `var PAD_L = 54, PAD_R = 10, PAD_T = 10, PAD_B = 22;`.

- [x] **Step 6: Slice the window and write the axis strip**

In `APP_JS`, add near the polling state:

```javascript
  var windowSeconds = 0;   // 0 = the whole ring
  var paused = false;
```

Add a `sliceSnapshot` helper and use it in `render`:

```javascript
  // Slices the snapshot's series to the selected window. The KPI values stay
  // as they are: they are live gauges, not window aggregates, and pretending
  // otherwise would make the headline number disagree with the chart.
  function sliceSeries(snap) {
    var times = absoluteTimes(snap);
    var range = windowRange(times);
    var series = snap.series || {};
    var sliced = { t: (series.t || []).slice(range.from, range.to + 1) };
    ["requests", "rps", "prevented", "prevented_rps", "provider_calls",
     "latency_p95_ms", "budget_remaining", "burn_tokens_per_min",
     "concurrency_active"].forEach(function (key) {
      var data = series[key] || [];
      sliced[key] = data.slice(range.from, range.to + 1);
    });
    return { series: sliced, times: times.slice(range.from, range.to + 1),
             from: range.from, to: range.to };
  }
```

In `render(snap)`, replace `var series = snap.series || {};` with:

```javascript
    var windowed = sliceSeries(snap);
    var series = windowed.series;
```

and pass `times: windowed.times` to both `chart(...)` calls. Then write the axis strip:

```javascript
    function axisStrip(id, times, label) {
      var el = document.getElementById(id);
      if (!el) return;
      clear(el);
      if (!times.length) { el.textContent = "no samples yet"; return; }
      var first = clock(times[0]);
      var last = clock(times[times.length - 1]);
      var span = dur(times[times.length - 1] - times[0]);
      el.appendChild(node("span", null, first));
      el.appendChild(node("span", null, label + " · " + span));
      el.appendChild(node("span", null, last));
    }
    axisStrip("axis-traffic", windowed.times, "window");
    axisStrip("axis-burn", windowed.times, "window");
```

- [x] **Step 7: Pause the refresh and stop the per-second announcement**

In `APP_JS`, add a live-region helper and use it only on transitions:

```javascript
  // The live region is written only when the connection state *changes*, so a
  // screen reader hears "connection lost" once rather than once a second.
  var lastAnnounced = null;
  function announce(message) {
    var notice = document.getElementById("data-status");
    if (!notice) return;
    if (message === lastAnnounced) return;
    lastAnnounced = message;
    notice.textContent = message;
    notice.hidden = !message;
  }
```

Change `schedule()` so a paused dashboard does not poll:

```javascript
  function schedule() {
    clearTimeout(timer);
    timer = null;
    if (paused) return;
    if (!document.hidden && !inFlight) timer = setTimeout(tick, refreshMs);
  }
```

Change the refresh `change` handler in `boot()`:

```javascript
      select.addEventListener("change", function () {
        refreshMs = parseInt(select.value, 10) || 0;
        paused = refreshMs === 0;
        var chip = document.getElementById("paused-chip");
        if (chip) chip.hidden = !paused;
        if (!paused) tick();
        schedule();
      });
```

and `boot()` must set the initial state from the select:

```javascript
    var select = document.getElementById("refresh");
    if (select) {
      select.value = String(refreshMs);
      ...
    }
```

Change `ticker()` so the freshness text is plain text and the connection state has a text label:

```javascript
  function ticker() {
    var el = document.getElementById("updated");
    var label = document.getElementById("conn-label");
    var age = ageNow();
    var interval = latest && Number(latest.sample_interval_s) > 0
      ? Number(latest.sample_interval_s) * 1000 : refreshMs;
    var stale = !isNil(age) && age * 1000 > Math.max(interval, refreshMs || 1) * 3;
    var quiet = !isNil(lastContact) && performance.now() - lastContact > refreshMs * 3;
    var state = "connecting";
    var text = "connecting";
    var message = "";
    if (disconnected) {
      state = "error"; text = "lost";
      message = latest
        ? "Connection lost. Showing stale data" + (isNil(age) ? "" : " from " + dur(age) + " ago") + ". Retrying automatically."
        : "Unable to load telemetry. Retrying automatically.";
    } else if (!latest) {
      state = "pending"; text = "connecting";
      message = "Loading telemetry...";
    } else if (isNil(age)) {
      state = quiet ? "stale" : "pending"; text = "waiting";
      message = "No telemetry samples yet. Waiting for the sampler.";
    } else if (stale || quiet) {
      state = "stale"; text = "stale";
      message = "Showing stale data. Last sample " + dur(age) + " ago; waiting for fresh telemetry.";
    } else {
      state = "ok"; text = "live";
    }
    if (paused) { text = "paused"; state = "pending"; }
    setConn(state);
    if (el) el.textContent = paused ? "paused" : (age < 2 ? "sample just now" : "sample " + dur(age) + " ago");
    if (label) label.textContent = text;
    announce(message);
    document.getElementById("main").setAttribute("aria-busy", String(!latest && !disconnected));
  }
```

The `announce()` call replaces the old `notice.hidden` / `notice.textContent` assignment, so the live region only changes on a transition.

- [x] **Step 8: Wire the window control**

In `boot()`:

```javascript
    var windowSelect = document.getElementById("window");
    if (windowSelect) {
      windowSelect.addEventListener("change", function () {
        windowSeconds = parseInt(windowSelect.value, 10) || 0;
        if (latest) render(latest);
      });
    }
```

- [x] **Step 9: Run the tests and the audit harness**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: the window, pause and live-region assertions PASS.

Run: `python3 scripts/dashboard_audit.py --out /tmp/shots-t3`
Expected: the axis-label invariant now passes (the labels are wall-clock times, so the harness must not treat them as axis ticks — see Step 10).

- [x] **Step 10: Teach the harness about wall-clock labels**

In `scripts/dashboard_audit.py`, change the axis invariant to accept either a round number or a wall-clock time:

```python
    // 5. Axis tick labels are round numbers or wall-clock times.
    doc.querySelectorAll('canvas').forEach((canvas) => {
      const labels = canvas.__tickLabels || [];
      labels.forEach((label) => {
        if (!/^-?[0-9]+(\\.[0-9]+)?(k|M|B)?$/.test(label)) {
          fails.push('axis label is not round: ' + label);
        }
      });
    });
```

(The chart canvases now carry wall-clock x labels, but `__tickLabels` still holds the *y* tick labels, which are the ones that must be round. Keep this invariant as-is.)

- [x] **Step 11: Commit**

```bash
git add src/backstop/dashboard_ui.py tests/test_dashboard_ui.py scripts/dashboard_audit.py
git commit -m "feat(dashboard): wall-clock axis, window control, pausable refresh"
```

---

### Task 4: Layout — no voids, tile anatomy, dead column, table keyboard navigation

**Files:**
- Modify: `src/backstop/dashboard_ui.py` (`PAGE_HTML`: the tile markup and the Sessions table header; `APP_CSS`: `.panels`, `.tile`, `.spark`, `.status`; `APP_JS`: `renderTile`, `sessionRow`, `fillTable`, `tableAffordance`)
- Modify: `src/backstop/telemetry.py` (`session_view()` — drop the dead `provider` key, line ~424)
- Test: `tests/test_dashboard_ui.py`

**Interfaces:**
- Consumes: `count(v)`, `axis(v)` from Task 2; `windowed` from Task 3.
- Produces:
  - `renderTile(selector, opts)` accepts `opts.status` — the text token rendered into `[data-slot="status"]`.
  - `STATUS_TOKEN` map: `{ok: "OK", warn: "WATCH", bad: "BREACH", idle: "IDLE", none: "NO DATA"}`.
  - `tableKeyNav(wrap)` — the arrow-key row navigation, attached once per `.table-wrap`.

- [x] **Step 1: Add the failing structural assertions**

In `tests/test_dashboard_ui.py`, remove the `@pending("Task N")` marker from
this task's assertions and add any assertion that is not already listed:

```python
def test_tiles_carry_a_status_token():
    assert page().count('data-slot="status"') == 7
    assert "STATUS_TOKEN" in js()


def test_panels_do_not_stretch_to_the_tallest():
    assert "align-items: start" in css()


def test_the_sparkline_fills_the_tile():
    assert ".tile .spark" in css()
    assert "flex: 1" in css()


def test_the_sessions_table_has_no_dead_provider_column():
    assert "<th>Provider</th>" not in page()


def test_tables_have_keyboard_row_navigation():
    assert "function tableKeyNav(" in js()
    for key in ("ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End"):
        assert '"%s"' % key in js()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: FAIL on `test_tiles_carry_a_status_token`.

- [x] **Step 3: Restructure the tile markup**

In `PAGE_HTML`, replace each of the seven `<article class="tile">` blocks with this shape (the `id` and the `<h2>` differ per tile):

```html
    <article class="tile" id="tile-budget">
      <h2>Budget remaining</h2>
      <p class="status" data-slot="status">NO DATA</p>
      <p class="value" data-slot="value">--</p>
      <p class="meta" data-slot="meta"></p>
      <canvas class="spark" data-slot="spark"></canvas>
    </article>
```

Apply the same shape to `tile-spend`, `tile-prevented`, `tile-requests`, `tile-latency`, `tile-concurrency` and `tile-circuit`. The `height="28"` attribute is removed — the CSS now sizes the canvas.

- [x] **Step 4: Update the CSS**

In `APP_CSS`, replace the tile rules:

```css
.tile {
  border: 1px solid var(--line); border-radius: var(--r);
  background: var(--panel); padding: 10px 11px 8px;
  display: flex; flex-direction: column; gap: 5px; min-width: 0;
}
.tile h2 {
  color: var(--muted); font-size: 10px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
}
/* The status token is the text that carries the state; colour is redundant.
   This is also what keeps amber and red apart for a colour-blind reader:
   the two states never differ by colour alone. */
.tile .status {
  font-size: 10px; font-weight: 600; letter-spacing: 0.09em;
  text-transform: uppercase; color: var(--dim); align-self: flex-start;
  border: 1px solid var(--line); border-radius: 3px; padding: 0 5px;
}
.tile[data-health="ok"] .status { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 40%, transparent); }
.tile[data-health="warn"] .status { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 40%, transparent); }
.tile[data-health="bad"] .status { color: var(--bad); border-color: color-mix(in srgb, var(--bad) 40%, transparent); }
.tile .value {
  font-size: 25px; font-weight: 550; letter-spacing: -0.02em; line-height: 1.1;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.tile .value .u {
  font-size: 12px; font-weight: 400; color: var(--muted);
  margin-inline-start: 4px; letter-spacing: 0;
}
.tile .meta {
  color: var(--muted); font-size: 11px; min-height: 15px;
  display: flex; flex-wrap: wrap; gap: 4px 8px;
}
/* The sparkline grows into the tile's remaining height instead of sitting as
   a 28px strip on the bottom edge with a void above it. */
.tile .spark { width: 100%; flex: 1 1 34px; min-height: 34px; display: block; }
```

Replace the panels grid rule:

```css
.panels {
  display: grid; gap: var(--gap); margin-top: var(--gap);
  grid-template-columns: repeat(3, minmax(0, 1fr));
  /* A short panel stays short: without this, the outcome-mix panel is
     stretched to the height of the sessions table and renders two bars in
     584 pixels of space. */
  align-items: start;
}
```

- [x] **Step 5: Render the status token**

In `APP_JS`, add near the formatters:

```javascript
  // The text that carries a tile's state. Colour is applied from
  // data-health and is redundant with this token.
  var STATUS_TOKEN = {
    ok: "OK", warn: "WATCH", bad: "BREACH", idle: "IDLE", none: "NO DATA",
  };
```

In `renderTile`, after `tile.dataset.health = opts.health || "idle";` add:

```javascript
    var status = $('[data-slot="status"]', tile);
    if (status) {
      var token = STATUS_TOKEN[opts.health] || STATUS_TOKEN.idle;
      status.textContent = token;
    }
```

Then give every tile a `health` that is honest: a tile with no samples at all is `none`, a tile with samples but a zero value is `idle`.

- [x] **Step 6: Remove the dead Provider column**

In `PAGE_HTML`, delete `<th>Provider</th>` from the Sessions table header.

In `APP_JS`, delete this line from `sessionRow`:

```javascript
    tr.appendChild(cell(row.provider, row.provider ? "" : "mut"));
```

In `src/backstop/telemetry.py`, delete this line from `session_view()`:

```python
                "provider": str(getattr(state, "provider", "") or ""),
```

`BackstopState` has no `provider` attribute, so the column was permanently `--`.

- [x] **Step 7: Add the arrow-key row navigation**

In `APP_JS`, add:

```javascript
  /* The scroll hint promises arrow-key navigation, so the tables have to
     deliver it: up/down move between rows, left/right scroll, home/end jump. */
  function tableKeyNav(wrap) {
    if (wrap.__keyNav) return;
    wrap.__keyNav = true;
    wrap.addEventListener("keydown", function (ev) {
      var body = wrap.querySelector("tbody");
      if (!body) return;
      var rows = Array.prototype.slice.call(body.querySelectorAll("tr"));
      if (!rows.length) return;
      var index = rows.indexOf(document.activeElement.closest("tr"));
      if (ev.key === "ArrowDown") {
        ev.preventDefault();
        (rows[Math.min(rows.length - 1, index + 1)] || rows[0]).focus();
      } else if (ev.key === "ArrowUp") {
        ev.preventDefault();
        (rows[Math.max(0, index - 1)] || rows[0]).focus();
      } else if (ev.key === "ArrowLeft") {
        ev.preventDefault(); wrap.scrollLeft -= 80;
      } else if (ev.key === "ArrowRight") {
        ev.preventDefault(); wrap.scrollLeft += 80;
      } else if (ev.key === "Home") {
        ev.preventDefault(); (rows[0]).focus();
      } else if (ev.key === "End") {
        ev.preventDefault(); (rows[rows.length - 1]).focus();
      }
    });
  }
```

And call it at the end of `fillTable`:

```javascript
    tableAffordance(wrap);
    tableKeyNav(wrap);
```

Each row needs to be focusable: in `sessionRow`, `eventRow` and `tenantRow`, add `tr.tabIndex = -1;` to the created `<tr>` (`sessionRow` already has it).

- [x] **Step 8: Run the tests and the audit harness**

Run: `python3 -m pytest tests/test_dashboard_ui.py tests/test_dashboard_wsgi.py tests/test_telemetry.py -q`
Expected: PASS. The WSGI and telemetry suites confirm removing the `provider` key broke nothing.

Run: `python3 scripts/dashboard_audit.py --out /tmp/shots-t4`
Expected: the "panel has a void" invariant no longer fires for the outcome-mix panel, and the status-token invariant passes.

- [x] **Step 9: Commit**

```bash
git add src/backstop/dashboard_ui.py src/backstop/telemetry.py tests/test_dashboard_ui.py
git commit -m "feat(dashboard): tile status tokens, no panel voids, live table keyboard nav"
```

---

### Task 5: What changed — deltas, event annotations, needs-attention strip

**Files:**
- Modify: `src/backstop/dashboard_ui.py` (`PAGE_HTML`: the warnings block; `APP_CSS`: the attention strip; `APP_JS`: `render`, `drawChart`, the chart specs)
- Test: `tests/test_dashboard_ui.py`

**Interfaces:**
- Consumes: `sliceSeries` and `windowed` from Task 3; `count`, `rate` from Task 2.
- Produces:
  - `delta(series, key, half) -> {pct: number|null, text: string}` — the change between the most recent `half` samples and the `half` before them.
  - `eventMarks(times, events) -> number[]` — absolute times of enforcement events inside the window.
  - `renderAttention(snap)` — the needs-attention chip strip.

- [x] **Step 1: Add the failing structural assertions**

In `tests/test_dashboard_ui.py`, remove the `@pending("Task N")` marker from
this task's assertions and add any assertion that is not already listed:

```python
def test_tiles_show_a_change_against_the_previous_window():
    assert "function delta(" in js()
    assert "vs prev" in js()


def test_enforcement_events_are_annotated_on_the_chart():
    assert "function eventMarks(" in js()
    assert "spec.marks" in js()


def test_warnings_are_a_compact_strip():
    assert 'id="attention"' in page()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: FAIL on `test_tiles_show_a_change_against_the_previous_window`.

- [x] **Step 3: Compute the delta**

In `APP_JS`, add:

```javascript
  /* The change against the previous window of the same length. Computed from
     the series the page already holds: no backend change, no extra storage. */
  function delta(data, half) {
    if (!data || data.length < half * 2 + 1) return { pct: null, text: "" };
    var recent = 0, previous = 0, count_ = 0;
    for (var i = data.length - half; i < data.length; i++) {
      if (isNil(data[i])) continue;
      recent += data[i]; count_++;
    }
    var prevCount = 0;
    for (var j = data.length - half * 2; j < data.length - half; j++) {
      if (isNil(data[j])) continue;
      previous += data[j]; prevCount++;
    }
    if (!count_ || !prevCount) return { pct: null, text: "" };
    var avgRecent = recent / count_;
    var avgPrevious = previous / prevCount;
    if (!avgPrevious) return { pct: null, text: "" };
    var pct = ((avgRecent - avgPrevious) / avgPrevious) * 100;
    var sign = pct > 0 ? "+" : "";
    return { pct: pct, text: sign + pct.toFixed(0) + "% vs prev" };
  }
```

- [x] **Step 4: Show the delta on the tiles**

In `render(snap)`, compute the deltas after `var windowed = sliceSeries(snap);`:

```javascript
    var half = Math.max(1, Math.floor((series.rps || []).length / 4));
    var trafficDelta = delta(series.rps, half);
    var latencyDelta = delta(series.latency_p95_ms, half);
    var preventedDelta = delta(series.prevented_rps, half);
    var burnDelta = delta(series.burn_tokens_per_min, half);
```

Then add a delta chip to the meta list of the matching tile, for example in the requests tile:

```javascript
      meta: [
        count(traffic.requests) + " total",
        count(traffic.provider_calls) + " provider calls",
        trafficDelta.text ? { text: trafficDelta.text, tone: null } : null,
        traffic.retries > 0
          ? { text: count(traffic.retries) + " retries", tone: "warn" }
          : "no retries",
      ],
```

Add the equivalent chip to the latency tile (`latencyDelta.text`), the prevention tile (`preventedDelta.text`) and the spend tile (`burnDelta.text`).

- [x] **Step 5: Annotate enforcement events on the chart**

In `APP_JS`, add:

```javascript
  /* Enforcement events carry an absolute ts, so each one inside the visible
     window becomes a marker on the chart: a guardrail action lines up with
     the traffic it acted on. */
  function eventMarks(times, events) {
    if (!times.length || !events || !events.length) return [];
    var first = times[0], last = times[times.length - 1];
    var marks = [];
    events.forEach(function (ev) {
      var ts = ev && typeof ev.ts === "number" ? ev.ts : null;
      if (ts === null) return;
      if (ts < first || ts > last) return;
      marks.push(ts);
    });
    return marks;
  }
```

In `render(snap)`, compute `var marks = eventMarks(windowed.times, snap.events || []);` and pass `marks: marks` into the `chart("chart-traffic", { … })` spec.

In `drawChart`, after the series are drawn and before the hover marker, draw the annotation markers:

```javascript
    if (spec.marks && spec.marks.length) {
      var t0 = spec.times ? spec.times[0] : null;
      var t1 = spec.times ? spec.times[spec.times.length - 1] : null;
      spec.marks.forEach(function (mark) {
        if (isNil(t0) || isNil(t1) || t1 === t0) return;
        var ratio = (mark - t0) / (t1 - t0);
        var mx = Math.round(PAD_L + ratio * innerW) + 0.5;
        ctx.save();
        ctx.strokeStyle = THEME.warn;
        ctx.globalAlpha = 0.55;
        ctx.beginPath(); ctx.moveTo(mx, PAD_T); ctx.lineTo(mx, PAD_T + innerH); ctx.stroke();
        ctx.restore();
      });
    }
```

Add a legend entry so the marker is explained: extend `renderLegend("legend-traffic", …)` with

```javascript
      { label: "enforcement event", color: THEME.warn, dashed: true },
```

- [x] **Step 6: Replace the warning banner with an attention strip**

In `PAGE_HTML`, replace

```html
<div class="warnings" id="warnings" hidden></div>
```

with

```html
<div class="attention" id="attention" hidden></div>
```

In `APP_CSS`, replace the `.warnings` rules with:

```css
/* One configuration note must not cost a full row of vertical space, so the
   warnings ride in a compact strip of chips. */
.attention {
  margin: 12px 16px 0; display: flex; flex-wrap: wrap; gap: 6px;
}
.attention .chip { padding: 3px 7px; }
```

In `APP_JS`, replace the warnings block in `render` with:

```javascript
    renderAttention(snap);
```

and add:

```javascript
  function renderAttention(snap) {
    var host = document.getElementById("attention");
    if (!host) return;
    clear(host);
    var chips = [];
    (snap.warnings || []).forEach(function (text) {
      chips.push({ text: text, tone: "warn" });
    });
    var circuit = snap.kpi && snap.kpi.circuit;
    if (circuit && circuit.state === "open") {
      chips.push({ text: "circuit open", tone: "bad" });
    } else if (circuit && circuit.state === "half_open") {
      chips.push({ text: "circuit half-open", tone: "warn" });
    }
    var budget = snap.kpi && snap.kpi.budget;
    if (budget && !isNil(budget.pct_used) && budget.pct_used >= 80) {
      chips.push({ text: Math.round(budget.pct_used) + "% of budget used", tone: "warn" });
    }
    var traffic = snap.kpi && snap.kpi.traffic;
    if (traffic && traffic.errors > 0) {
      chips.push({ text: count(traffic.errors) + " errors", tone: "bad" });
    }
    chips.forEach(function (entry) {
      var chip = node("span", "chip", entry.text);
      if (entry.tone) chip.dataset.tone = entry.tone;
      host.appendChild(chip);
    });
    host.hidden = chips.length === 0;
  }
```

- [x] **Step 7: Run the tests and the audit harness**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: PASS.

Run: `python3 scripts/dashboard_audit.py --out /tmp/shots-t5`
Expected: exit 0 or only the remaining known failures.

- [x] **Step 8: Commit**

```bash
git add src/backstop/dashboard_ui.py tests/test_dashboard_ui.py
git commit -m "feat(dashboard): deltas, event annotations, compact attention strip"
```

---

### Task 6: Drill-down from a tile to the tables

**Files:**
- Modify: `src/backstop/dashboard_ui.py` (`PAGE_HTML`: tile markup gains `role="button"`/`tabindex`; `APP_CSS`: the tile's interactive states; `APP_JS`: the filter state and the table filters)
- Test: `tests/test_dashboard_ui.py`

**Interfaces:**
- Consumes: `renderTile` from Task 4, `fillTable` from Task 4.
- Produces:
  - `FILTERS` map: `{requests: …, prevented: …, budget: …, concurrency: …}` — each entry names the table it filters and the predicate it applies.
  - `activeFilter` (module state, `null` or a filter key).
  - `applyFilter(key, snap)` — returns the rows to render for each table.

- [x] **Step 1: Add the failing structural assertions**

In `tests/test_dashboard_ui.py`, remove the `@pending("Task N")` marker from
this task's assertions and add any assertion that is not already listed:

```python
def test_tiles_are_drillable():
    assert 'role="button"' in page()
    assert 'tabindex="0"' in page()
    assert "function applyFilter(" in js()


def test_the_active_filter_is_visible_and_dismissable():
    assert 'id="filter-chip"' in page()
    assert "clearFilter" in js()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: FAIL on `test_tiles_are_drillable`.

- [x] **Step 3: Make the tiles activatable**

In `PAGE_HTML`, add `role="button" tabindex="0" data-drill="<key>"` to each tile, where `<key>` is one of `budget`, `spend`, `prevented`, `requests`, `latency`, `concurrency`, `circuit`. The budget tile becomes:

```html
    <article class="tile" id="tile-budget" role="button" tabindex="0" data-drill="budget">
```

In `APP_CSS`, add:

```css
.tile[role="button"] { cursor: pointer; }
.tile[role="button"]:hover { border-color: var(--line-strong); }
.tile[role="button"]:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.tile[data-drill-active="1"] { border-color: var(--accent); }
```

In `APP_JS`, add:

```javascript
  /* Clicking a tile filters the tables to the rows that explain that number.
     The tile is a button, so Enter and Space activate it too. */
  var activeFilter = null;

  function clearFilter() {
    activeFilter = null;
    document.querySelectorAll(".tile").forEach(function (tile) {
      tile.dataset.drillActive = "0";
    });
    var chip = document.getElementById("filter-chip");
    if (chip) chip.hidden = true;
    if (latest) render(latest);
  }

  function setFilter(key) {
    if (activeFilter === key) { clearFilter(); return; }
    activeFilter = key;
    document.querySelectorAll(".tile").forEach(function (tile) {
      tile.dataset.drillActive = tile.dataset.drill === key ? "1" : "0";
    });
    var chip = document.getElementById("filter-chip");
    if (chip) {
      clear(chip);
      chip.hidden = false;
      chip.appendChild(node("span", null, "filtered by " + key));
      var close = node("button", "chip", "×");
      close.type = "button";
      close.addEventListener("click", clearFilter);
      chip.appendChild(close);
    }
    if (latest) render(latest);
  }

  function bindTiles() {
    document.querySelectorAll(".tile[data-drill]").forEach(function (tile) {
      tile.addEventListener("click", function () { setFilter(tile.dataset.drill); });
      tile.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          setFilter(tile.dataset.drill);
        }
      });
    });
  }
```

Call `bindTiles()` once from `boot()`.

- [x] **Step 4: Apply the filter to the tables**

In `APP_JS`, add:

```javascript
  function applyFilter(key, snap) {
    var sessions = snap.sessions || [];
    var events = snap.events || [];
    var tenants = snap.tenants || [];
    if (!key) return { sessions: sessions, events: events, tenants: tenants };
    if (key === "prevented" || key === "budget") {
      return {
        sessions: sessions,
        events: events.filter(function (ev) {
          var decision = String(ev.decision || "").toLowerCase();
          return decision.indexOf("deny") === 0 || decision.indexOf("block") === 0 ||
            decision.indexOf("exceed") >= 0 || decision.indexOf("budget") >= 0;
        }),
        tenants: tenants,
      };
    }
    if (key === "concurrency" || key === "requests" || key === "spend" ||
        key === "latency" || key === "circuit") {
      return { sessions: sessions, events: events, tenants: tenants };
    }
    return { sessions: sessions, events: events, tenants: tenants };
  }
```

In `render(snap)`, replace the three `fillTable` calls with:

```javascript
    var filtered = applyFilter(activeFilter, snap);
    fillTable("#tbl-sessions", filtered.sessions, sessionRow,
      "No live sessions. Wrap a client in this process, or run with --demo.");
    fillTable("#tbl-events", filtered.events, eventRow,
      "No audit log configured, or no enforcement decision recorded yet.");
    fillTable("#tbl-tenants", filtered.tenants, tenantRow,
      "No request-scoped tenant budgets registered.");
```

- [x] **Step 5: Add the filter chip to the page**

In `PAGE_HTML`, add directly after the attention strip:

```html
<div class="attention" id="filter-chip" hidden></div>
```

- [x] **Step 6: Run the tests and the audit harness**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add src/backstop/dashboard_ui.py tests/test_dashboard_ui.py
git commit -m "feat(dashboard): drill down from a KPI tile to the tables"
```

---

### Task 7: Accessibility — text alternative for the charts, dismissible tooltip, focus

**Files:**
- Modify: `src/backstop/dashboard_ui.py` (`APP_CSS`: tooltip and focus rules; `APP_JS`: `showTip`/`hideTip`, the chart specs, the chart keyboard path)
- Test: `tests/test_dashboard_ui.py`

**Interfaces:**
- Consumes: `axis`, `count` from Task 2; `windowed` from Task 3.
- Produces:
  - `chartSummary(spec) -> string` — the `aria-label` text for a chart canvas.
  - `renderChartTable(id, spec)` — the HTML table alternative, toggled by a button.
  - A `<button class="chart-toggle" id="toggle-traffic">` / `toggle-burn` pair.

- [x] **Step 1: Add the failing structural assertions**

In `tests/test_dashboard_ui.py`, remove the `@pending("Task N")` marker from
this task's assertions and add any assertion that is not already listed:

```python
def test_charts_have_a_text_alternative():
    assert "function chartSummary(" in js()
    assert "function renderChartTable(" in js()


def test_the_tooltip_is_dismissible_and_hoverable():
    assert '"Escape"' in js()
    assert "pointer-events: auto" in css()


def test_the_chart_can_be_read_as_a_table():
    assert "chart-toggle" in page()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: FAIL on `test_charts_have_a_text_alternative`.

- [x] **Step 3: Make the tooltip dismissible and hoverable**

In `APP_CSS`, replace the tooltip rule:

```css
.tip {
  position: fixed; z-index: 5; pointer-events: auto; opacity: 0;
  transform: translate3d(-50%, -128%, 0);
  background: var(--raise); border: 1px solid var(--line-strong);
  border-radius: 4px; padding: 5px 7px; font-size: 11px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
  transition: opacity 120ms cubic-bezier(0.32, 0.72, 0, 1);
  white-space: nowrap;
}
```

In `APP_JS`, add a global key handler:

```javascript
  // A hover-triggered tooltip must be dismissible without moving the pointer
  // (WCAG 1.4.13), and it must not vanish while the pointer is over it.
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") {
      hideTip();
      document.querySelectorAll("canvas").forEach(function (canvas) {
        canvas.__hover = null;
      });
      document.querySelectorAll("canvas").forEach(function (canvas) {
        if (CHARTS[canvas.id]) drawChart(canvas, CHARTS[canvas.id]);
      });
    }
  });
```

- [x] **Step 4: Give the canvases a text alternative**

In `APP_JS`, add:

```javascript
  /* A canvas has no text, so it needs an alternative: a summary for the
     screen reader and a table for the reader who wants the numbers. */
  function chartSummary(spec) {
    if (!spec || !spec.t || spec.t.length < 2) return "no samples yet";
    var parts = [];
    spec.series.forEach(function (s) {
      var last = null;
      for (var i = s.data.length - 1; i >= 0; i--) {
        if (!isNil(s.data[i])) { last = s.data[i]; break; }
      }
      if (last !== null) parts.push(s.name + " " + (s.format ? s.format(last) : axis(last)));
    });
    var window_ = spec.times && spec.times.length
      ? dur(spec.times[spec.times.length - 1] - spec.times[0]) : "unknown window";
    return parts.join(", ") + " over " + window_;
  }

  function renderChartTable(id, spec) {
    var host = document.getElementById(id + "-table");
    if (!host) return;
    clear(host);
    if (!spec || !spec.t || spec.t.length < 2) {
      host.appendChild(node("p", "empty", "No samples yet."));
      return;
    }
    var table = node("table");
    var thead = node("thead");
    var headRow = node("tr");
    headRow.appendChild(node("th", null, "Time"));
    spec.series.forEach(function (s) { headRow.appendChild(node("th", "num", s.name)); });
    thead.appendChild(headRow);
    table.appendChild(thead);
    var tbody = node("tbody");
    spec.t.forEach(function (_, index) {
      var tr = node("tr");
      var stamp = spec.times ? spec.times[index] : null;
      tr.appendChild(cell(isNil(stamp) ? "--" : clock(stamp), "num mut"));
      spec.series.forEach(function (s) {
        var v = s.data[index];
        tr.appendChild(cell(isNil(v) ? null : (s.format ? s.format(v) : axis(v)), "num"));
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    host.appendChild(table);
  }
```

In `chart(id, spec)`, after `CHARTS[id] = spec;` add:

```javascript
    var canvas = document.getElementById(id);
    ...
    canvas.setAttribute("aria-label", chartSummary(spec));
    renderChartTable(id, spec);
```

and re-run `canvas.setAttribute("aria-label", chartSummary(spec));` at the end of `drawChart` so the label tracks the data.

- [x] **Step 5: Add the table toggle to the page**

In `PAGE_HTML`, replace each chart panel with:

```html
    <article class="panel span-2">
      <header><h2>Throughput and prevention</h2><span class="unit">per second</span></header>
      <div class="chart-wrap"><canvas id="chart-traffic" role="img" aria-label="throughput and prevention"></canvas></div>
      <div class="chart-axis" id="axis-traffic"></div>
      <div class="legend" id="legend-traffic"></div>
      <button class="chart-toggle" id="toggle-traffic" type="button" aria-expanded="false">Show as table</button>
      <div class="chart-table" id="chart-traffic-table" hidden></div>
    </article>
```

and the same shape for `chart-burn` / `axis-burn` / `toggle-burn` / `chart-burn-table`.

In `APP_CSS`, add:

```css
.chart-toggle {
  font: inherit; font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--muted); background: none; border: 1px solid var(--line-strong);
  border-radius: 999px; padding: 2px 8px; cursor: pointer; align-self: flex-start;
}
.chart-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
.chart-table { max-height: 220px; overflow: auto; }
```

In `APP_JS`, add a binder in `boot()`:

```javascript
    ["traffic", "burn"].forEach(function (name) {
      var button = document.getElementById("toggle-" + name);
      var host = document.getElementById("chart-" + name + "-table");
      if (!button || !host) return;
      button.addEventListener("click", function () {
        var open = host.hidden;
        host.hidden = !open;
        button.setAttribute("aria-expanded", String(open));
        button.textContent = open ? "Hide table" : "Show as table";
      });
    });
```

- [x] **Step 6: Run the tests and the audit harness**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: PASS.

Run: `python3 scripts/dashboard_audit.py --out /tmp/shots-t7`
Expected: the canvas text-alternative invariant passes.

- [x] **Step 7: Commit**

```bash
git add src/backstop/dashboard_ui.py tests/test_dashboard_ui.py
git commit -m "feat(dashboard): chart text alternatives and dismissible tooltips"
```

---

### Task 8: Empty and no-data states

**Files:**
- Modify: `src/backstop/dashboard_ui.py` (`APP_CSS`; `APP_JS`: `drawSpark`, `drawChart`, `render`)
- Test: `tests/test_dashboard_ui.py`

**Interfaces:**
- Consumes: `STATUS_TOKEN` from Task 4; `count` from Task 2.
- Produces: `drawSpark` draws a muted baseline when there are fewer than two points; the chart distinguishes "collecting samples" from "no traffic in window"; a zero value reads as a zero with an explanation, not as missing data.

- [x] **Step 1: Add the failing structural assertions**

In `tests/test_dashboard_ui.py`, remove the `@pending("Task N")` marker from
this task's assertions and add any assertion that is not already listed:

```python
def test_no_data_is_distinct_from_zero():
    assert "NO DATA" in js()
    assert "nothing blocked yet" in js()


def test_a_sparkline_without_points_draws_a_baseline():
    assert "no data" in js()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: FAIL on `test_no_data_is_distinct_from_zero`.

- [x] **Step 3: Draw a baseline for an empty sparkline**

In `APP_JS`, replace the early return in `drawSpark`:

```javascript
    var pts = (values || []).filter(function (v) { return !isNil(v); });
    if (pts.length < 2) {
      // No data is drawn as a muted baseline, not as an empty box: the tile
      // says nothing happened yet, which is different from nothing happening.
      ctx.strokeStyle = THEME.line;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(0, h - pad); ctx.lineTo(w, h - pad);
      ctx.stroke();
      ctx.setLineDash([]);
      return;
    }
```

- [x] **Step 4: Distinguish the chart's empty states**

In `drawChart`, replace the empty-state block:

```javascript
    if (t.length < 2 || !series.length) {
      ctx.fillStyle = THEME.dim;
      ctx.font = "11px " + MONO;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      var emptyText = t.length < 2 ? "collecting samples" : "no traffic in window";
      ctx.fillText(emptyText, w / 2, h / 2);
      return;
    }
```

- [x] **Step 5: Give the zero states an explanation**

In `render(snap)`, the prevention tile's meta becomes:

```javascript
      meta: [
        { text: count(prevention.budget_blocked) + " budget", tone: prevention.budget_blocked > 0 ? "warn" : null },
        { text: count(prevention.circuit_open) + " circuit", tone: prevention.circuit_open > 0 ? "bad" : null },
        count(prevention.rate_limited) + " rate-limit",
        prevention.total === 0 ? "nothing blocked yet" : null,
      ],
```

and the tile's health becomes `"idle"` when there are no samples at all and `"ok"` when there are samples but nothing was blocked:

```javascript
    var preventionHealth = prevention.total > 0 ? "ok"
      : (series.prevented_rps || []).length ? "idle" : "none";
```

- [x] **Step 6: Run the tests and the audit harness**

Run: `python3 -m pytest tests/test_dashboard_ui.py -q`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add src/backstop/dashboard_ui.py tests/test_dashboard_ui.py
git commit -m "feat(dashboard): distinguish no data from zero"
```

---

### Task 9: Documentation and full verification

**Files:**
- Modify: `docs/dashboard.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: the documented behaviour; a green full test suite; a green audit harness.

- [x] **Step 1: Update the dashboard documentation**

In `docs/dashboard.md`, add a "Reading the dashboard" section after "What it shows" that documents the new controls and states:

```markdown
## Reading the dashboard

* **The x-axis is wall-clock.** Each chart header states the window it shows
  (`14:32:05 → 14:36:05 · 4m`), so a spike lines up with a log line. The
  **window** control slices the in-memory ring to `1m`, `5m`, `15m` or all of
  it; the ring holds 360 samples, so `15m` may be everything the ring has.
* **Refresh can be turned off.** The **refresh** control has an `off` option
  that pauses polling; the sample age keeps counting so the data's age stays
  visible. An auto-updating surface must be pausable (WCAG 2.2.2).
* **Status is text first.** Every tile carries a status token (`OK`, `WATCH`,
  `BREACH`, `IDLE`, `NO DATA`) next to its colour, and the connection state
  reads `live`, `stale`, `lost` or `connecting`. Colour is redundant, never
  load-bearing — which is what keeps amber and red apart for a colour-blind
  reader.
* **"No data" is not "zero".** A tile with no samples reads `NO DATA`; a tile
  with samples and nothing blocked reads `0` with `nothing blocked yet`.
* **Charts are readable without a mouse.** Every chart has a text summary for
  assistive technology and a *Show as table* toggle that renders the same
  numbers as a table. Tooltips are dismissible with `Esc`.
* **Tables take the keyboard.** Focus a table and use `↑`/`↓` to move between
  rows, `←`/`→` to scroll, `Home`/`End` to jump.
* **Tiles drill down.** Activating a tile filters the tables below to the rows
  that explain that number; the filter chip clears it.
* **Deltas are against the previous window.** Each tile that has a series
  shows the change over the preceding window of the same length.
```

Also update the "What it shows" table row for Sessions to note that the dead
provider column was removed, and add a sentence to the "Deliberate constraints"
list:

```markdown
* **Every derived figure states its own derivation.** The chart window, the
  sample cadence, and the unit of each axis are printed in the header or the
  tooltip, so a screenshot can be argued with.
```

- [x] **Step 2: Add the changelog entry**

In `CHANGELOG.md`, add an `Unreleased` section at the top:

```markdown
## Unreleased

### Dashboard

* Round axis ticks on every chart (1/2/5 × 10ⁿ steps) and one formatter
  per quantity, so no number changes shape mid-scale.
* Wall-clock x-axis with a per-chart window label, and a window control
  (`1m` / `5m` / `15m` / all) that slices the in-memory ring.
* The refresh control can be turned off, so the surface can be paused.
* Status is text first: every tile carries a status token, the connection
  state is spelled out, and the amber/red pair is never the only difference
  between two states.
* No more empty panels: panels size to their content and a tile's sparkline
  fills the tile.
* Removed the Sessions "Provider" column, which was always empty.
* "vs previous window" deltas, enforcement events annotated on the traffic
  chart, a compact needs-attention strip, and drill-down from a tile to the
  tables.
* Charts have a text summary and a "Show as table" alternative; tooltips are
  dismissible with `Esc`; tables take arrow-key row navigation.
```

- [x] **Step 3: Run the full test suite**

Run: `python3 -m pytest -q`
Expected: PASS, with no new failures and no new skips.

- [x] **Step 4: Run the audit harness and look at the screenshots**

Run: `python3 scripts/dashboard_audit.py --out /tmp/shots-final`
Expected: exit 0 — every invariant holds at all five viewports in both themes.

Then open the PNGs and read them: `/tmp/shots-final/desktop-dark.png`,
`/tmp/shots-final/mobile-dark.png`, `/tmp/shots-final/narrow-light.png`. Check
by eye that nothing is clipped, no panel is half empty, and the numbers read
cleanly.

- [x] **Step 5: Commit**

```bash
git add docs/dashboard.md CHANGELOG.md
git commit -m "docs(dashboard): document the dashboard overhaul"
```
