"""Shell, stylesheet and chart code for the built-in dashboard.

Kept as Python strings rather than package data on purpose:

* the wheel needs no extra include rules, so the dashboard cannot break because
  an asset went missing from an installed distribution;
* nothing is read from disk at request time, which keeps the server fast and
  immune to working-directory surprises;
* no build step and no CDN, so the dashboard renders air-gapped and makes zero
  outbound requests.

Design intent: this is an operations surface, not a marketing page. Dense but
uncluttered, dark-first, one accent hue, semantic colour reserved strictly for
health (green = ok, amber = degraded, red = breached), tabular figures for every
number, and no decoration that does not carry information.
"""

# Placeholders are substituted with str.replace (never str.format) so the CSS
# and JS bodies can contain arbitrary braces.
PAGE_HTML = """<!doctype html>
<html lang="en" data-theme="__THEME__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<meta name="robots" content="noindex, nofollow">
<title>__TITLE__</title>
<link rel="stylesheet" href="/assets/app.css">
</head>
<body data-mode="__MODE__" data-refresh="__REFRESH__" data-cost-model="__COST_MODEL__" data-theme="__THEME__">
<a class="skip" href="#main">Skip to content</a>

<header class="topbar">
  <div class="brand">
    <span class="mark" aria-hidden="true"></span>
    <span class="wordmark">Backstop</span>
    <span class="sub">guardrail telemetry</span>
  </div>
  <div class="topbar-right">
    <span class="badge" id="mode-badge">__MODE__</span>
    <span class="conn" id="conn" data-state="pending" title="snapshot freshness"></span>
    <span class="muted" id="updated" role="status" aria-live="polite">connecting</span>
    <label class="muted refresh-field">refresh
      <select id="refresh">
        <option value="1000">1s</option>
        <option value="2000">2s</option>
        <option value="5000">5s</option>
        <option value="30000">30s</option>
      </select>
    </label>
    <button class="badge theme-toggle" id="theme-toggle" type="button"
      title="switch colour theme">theme</button>
  </div>
</header>

<div class="data-status" id="data-status" role="status">Loading telemetry...</div>
<div class="warnings" id="warnings" hidden></div>

<main id="main" aria-busy="true">
  <section class="tiles" aria-label="Key indicators">
    <article class="tile" id="tile-budget">
      <h2>Budget remaining</h2>
      <p class="value" data-slot="value">--</p>
      <p class="meta" data-slot="meta"></p>
      <canvas class="spark" data-slot="spark" height="28"></canvas>
    </article>
    <article class="tile" id="tile-spend">
      <h2>Token spend</h2>
      <p class="value" data-slot="value">--</p>
      <p class="meta" data-slot="meta"></p>
      <canvas class="spark" data-slot="spark" height="28"></canvas>
    </article>
    <article class="tile" id="tile-prevented">
      <h2>Spend prevented</h2>
      <p class="value" data-slot="value">--</p>
      <p class="meta" data-slot="meta"></p>
      <canvas class="spark" data-slot="spark" height="28"></canvas>
    </article>
    <article class="tile" id="tile-requests">
      <h2>Requests</h2>
      <p class="value" data-slot="value">--</p>
      <p class="meta" data-slot="meta"></p>
      <canvas class="spark" data-slot="spark" height="28"></canvas>
    </article>
    <article class="tile" id="tile-latency">
      <h2>Request latency p95</h2>
      <p class="value" data-slot="value">--</p>
      <p class="meta" data-slot="meta"></p>
      <canvas class="spark" data-slot="spark" height="28"></canvas>
    </article>
    <article class="tile" id="tile-concurrency">
      <h2>Concurrency</h2>
      <p class="value" data-slot="value">--</p>
      <p class="meta" data-slot="meta"></p>
      <canvas class="spark" data-slot="spark" height="28"></canvas>
    </article>
    <article class="tile" id="tile-circuit">
      <h2>Circuit</h2>
      <p class="value" data-slot="value">--</p>
      <p class="meta" data-slot="meta"></p>
      <canvas class="spark" data-slot="spark" height="28"></canvas>
    </article>
  </section>

  <section class="panels">
    <article class="panel span-2">
      <header><h2>Throughput and prevention</h2><span class="unit">per second</span></header>
      <div class="chart-wrap"><canvas id="chart-traffic"></canvas></div>
      <div class="legend" id="legend-traffic"></div>
    </article>

    <article class="panel">
      <header><h2>Budget burn</h2><span class="unit">tokens / min</span></header>
      <div class="chart-wrap"><canvas id="chart-burn"></canvas></div>
      <div class="legend" id="legend-burn"></div>
    </article>

    <article class="panel span-2">
      <header><h2>Sessions</h2><span class="unit">per-agent budget isolation</span></header>
      <div class="table-wrap">
        <table id="tbl-sessions">
          <thead><tr>
            <th>Session</th><th>Provider</th><th class="num">Budget used</th>
            <th class="num">Remaining</th><th class="num">Concurrency</th>
            <th>Circuit</th><th class="num">Age</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </article>

    <article class="panel">
      <header><h2>Outcome mix</h2><span class="unit">requests</span></header>
      <div class="bars" id="outcome-mix"></div>
    </article>

    <article class="panel span-2">
      <header><h2>Enforcement events</h2><span class="unit">audit tail</span></header>
      <div class="table-wrap">
        <table id="tbl-events">
          <thead><tr>
            <th class="num">Time</th><th>Decision</th><th>Reason</th>
            <th>Endpoint</th><th>Priority</th><th class="num">Est. tokens</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </article>

    <article class="panel">
      <header><h2>Tenants</h2><span class="unit">request-scoped budgets</span></header>
      <div class="table-wrap">
        <table id="tbl-tenants">
          <thead><tr>
            <th>Tenant</th><th class="num">Used</th><th class="num">Remaining</th>
          </tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </article>
  </section>

  <footer class="foot">
    <p id="methodology"></p>
  </footer>
</main>

<script src="/assets/app.js" defer></script>
</body>
</html>
"""

APP_CSS = """
/* Tokens -------------------------------------------------------------------
   Dark-first, one accent hue, semantic colour reserved strictly for health.
   No gradients on text, no glassmorphism, no decorative shadows: on an
   operations surface every pixel should carry information. */
:root {
  --bg: #0b0c0e;
  --panel: #111316;
  --panel-2: #16181c;
  --raise: #1c1f24;
  --line: rgba(255, 255, 255, 0.07);
  --line-strong: rgba(255, 255, 255, 0.12);
  --text: #e6e8eb;
  --muted: #8b9199;
  --dim: #8b9199;
  --accent: #58a6ff;
  --ok: #3fb950;
  --warn: #d29922;
  --bad: #f85149;
  --info: #58a6ff;
  --neutral: #8b949e;
  --sans: system-ui, -apple-system, "Segoe UI Variable Text", "Segoe UI", Ubuntu,
    Cantarell, sans-serif;
  --mono: ui-monospace, "SF Mono", "JetBrains Mono", "Cascadia Mono",
    "Roboto Mono", Menlo, monospace;
  --r: 6px;
  --gap: 12px;
}
/* Theme override -----------------------------------------------------------
   The server stamps data-theme="auto"|"dark"|"light" on <html>. "auto" (the
   default) follows the OS via the media query below; explicit "dark"/"light"
   blocks override it because they come later at equal specificity. */
@media (prefers-color-scheme: light) {
  :root {
    --bg: #f6f7f9;
    --panel: #ffffff;
    --panel-2: #f2f4f7;
    --raise: #e9ecf1;
    --line: rgba(16, 22, 32, 0.10);
    --line-strong: rgba(16, 22, 32, 0.18);
    --text: #10141a;
    --muted: #5b6470;
    --dim: #626b76;
    --accent: #0b62d0;
    --ok: #1a7f37;
    --warn: #9a6700;
    --bad: #cf222e;
    --info: #0b62d0;
    --neutral: #6e7781;
  }
}
:root[data-theme="dark"] {
  --bg: #0b0c0e;
  --panel: #111316;
  --panel-2: #16181c;
  --raise: #1c1f24;
  --line: rgba(255, 255, 255, 0.07);
  --line-strong: rgba(255, 255, 255, 0.12);
  --text: #e6e8eb;
  --muted: #8b9199;
  --dim: #8b9199;
  --accent: #58a6ff;
  --ok: #3fb950;
  --warn: #d29922;
  --bad: #f85149;
  --info: #58a6ff;
  --neutral: #8b949e;
  color-scheme: dark;
}
:root[data-theme="light"] {
  --bg: #f6f7f9;
  --panel: #ffffff;
  --panel-2: #f2f4f7;
  --raise: #e9ecf1;
  --line: rgba(16, 22, 32, 0.10);
  --line-strong: rgba(18, 22, 32, 0.18);
  --text: #10141a;
  --muted: #5b6470;
  --dim: #626b76;
  --accent: #0b62d0;
  --ok: #1a7f37;
  --warn: #9a6700;
  --bad: #cf222e;
  --info: #0b62d0;
  --neutral: #6e7781;
  color-scheme: light;
}

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 12.5px/1.45 var(--sans);
  font-variant-numeric: tabular-nums;
}
h1, h2, h3 { margin: 0; font-weight: 600; }
p { margin: 0; }
a { color: var(--accent); }
.skip {
  position: absolute; left: -9999px; top: 0; background: var(--panel);
  padding: 8px 12px; z-index: 10;
}
.skip:focus { left: 8px; top: 8px; }

/* Numerals: monospace + tabular so digits do not jitter between refreshes. */
.value, .num, td.num, .mono, .badge {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1;
}

/* Topbar ------------------------------------------------------------------ */
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--gap);
  padding: 10px 16px;
  border-block-end: 1px solid var(--line);
  background: var(--bg);
  position: sticky; top: 0; z-index: 3;
}
.brand { display: flex; align-items: baseline; gap: 9px; min-width: 0; }
.mark {
  width: 11px; height: 11px; border-radius: 2px; background: var(--accent);
  align-self: center; flex: 0 0 auto;
}
.wordmark { font-size: 14px; font-weight: 650; letter-spacing: -0.01em; }
.sub {
  color: var(--dim); font-size: 11px; letter-spacing: 0.02em;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.topbar-right { display: flex; align-items: center; gap: 12px; flex: 0 0 auto; }
@media (max-width: 640px) {
  .topbar { flex-wrap: wrap; }
  .topbar-right {
    flex: 1 1 100%; min-width: 0; flex-wrap: wrap; row-gap: 6px;
    justify-content: space-between;
  }
  .brand { flex: 1 1 100%; }
  .brand .sub { display: none; }
}
.muted { color: var(--muted); font-size: 11px; }
.badge {
  border: 1px solid var(--line-strong); border-radius: 999px;
  padding: 2px 8px; font-size: 10px; letter-spacing: 0.07em;
  text-transform: uppercase; color: var(--muted);
}
body[data-mode="demo"] #mode-badge { color: var(--warn); border-color: var(--warn); }
.refresh-field { display: flex; align-items: center; gap: 6px; }
.theme-toggle {
  font: inherit; font-size: 10px; letter-spacing: 0.07em;
  text-transform: uppercase; color: var(--muted); cursor: pointer;
  background: none; border: 1px solid var(--line-strong); border-radius: 999px;
  padding: 2px 8px;
}
.theme-toggle:hover { color: var(--text); }
select {
  font: inherit; font-size: 11px; color: var(--text); background: var(--panel-2);
  border: 1px solid var(--line-strong); border-radius: 4px; padding: 2px 4px;
}
@media (pointer: coarse) {
  select, .theme-toggle { min-height: 44px; min-width: 44px; padding: 6px 8px; }
}
select:focus-visible, .theme-toggle:focus-visible, .skip:focus, a:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 1px;
}

.conn {
  width: 7px; height: 7px; border-radius: 50%; background: var(--dim);
  transition: background 240ms cubic-bezier(0.32, 0.72, 0, 1);
}
.conn[data-state="ok"] { background: var(--ok); }
.conn[data-state="stale"] { background: var(--warn); }
.conn[data-state="error"] { background: var(--bad); }

/* Warnings ---------------------------------------------------------------- */
.warnings {
  margin: 12px 16px 0; padding: 9px 12px;
  border: 1px solid var(--line); border-inline-start: 2px solid var(--warn);
  border-radius: var(--r); background: var(--panel);
  color: var(--muted); font-size: 11.5px;
}
.warnings ul { margin: 0; padding-inline-start: 16px; }
.warnings li + li { margin-top: 3px; }

/* Layout ------------------------------------------------------------------ */
main { padding: 12px 16px 24px; }
.tiles {
  display: grid; gap: var(--gap);
  grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
}
.panels {
  display: grid; gap: var(--gap); margin-top: var(--gap);
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.span-2 { grid-column: span 2; }
@media (max-width: 900px) {
  .panels { grid-template-columns: minmax(0, 1fr); }
  .span-2 { grid-column: span 1; }
}

/* Tiles ------------------------------------------------------------------- */
.tile {
  border: 1px solid var(--line); border-radius: var(--r);
  background: var(--panel); padding: 10px 11px 8px;
  display: flex; flex-direction: column; gap: 5px; min-width: 0;
}
.tile h2 {
  color: var(--muted); font-size: 10px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
}
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
.tile .spark { width: 100%; height: 28px; display: block; }

/* Health states drive colour on the value, never on decoration. */
.tile[data-health="ok"] .value { color: var(--text); }
.tile[data-health="warn"] .value { color: var(--warn); }
.tile[data-health="bad"] .value { color: var(--bad); }
.tile[data-health="idle"] .value { color: var(--dim); }

.chip {
  border: 1px solid var(--line); border-radius: 3px; padding: 0 5px;
  font-size: 10.5px; color: var(--muted); white-space: nowrap;
}
.chip[data-tone="ok"] { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 40%, transparent); }
.chip[data-tone="warn"] { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 40%, transparent); }
.chip[data-tone="bad"] { color: var(--bad); border-color: color-mix(in srgb, var(--bad) 40%, transparent); }

/* Panels ------------------------------------------------------------------ */
.panel {
  border: 1px solid var(--line); border-radius: var(--r);
  background: var(--panel); padding: 10px 12px 11px; min-width: 0;
  display: flex; flex-direction: column; gap: 9px;
}
.panel > header {
  display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between;
  gap: 4px 10px; padding-block-end: 8px; border-block-end: 1px solid var(--line);
}
.panel h2 { font-size: 12px; letter-spacing: -0.005em; }
.panel .unit {
  color: var(--dim); font-size: 10px; letter-spacing: 0.06em;
  text-transform: uppercase; font-family: var(--mono); overflow-wrap: anywhere;
}
.chart-wrap { position: relative; height: 168px; }
.chart-wrap canvas { width: 100%; height: 100%; display: block; }
.legend {
  display: flex; flex-wrap: wrap; gap: 4px 14px; color: var(--muted);
  font-size: 11px;
}
.legend .key { display: inline-flex; align-items: center; gap: 6px; }
.legend .swatch { width: 9px; height: 2px; border-radius: 2px; }

/* Outcome mix ------------------------------------------------------------- */
.bars { display: flex; flex-direction: column; gap: 8px; }
.bar-row { display: grid; grid-template-columns: 78px 1fr 52px; gap: 9px;
  align-items: center; font-size: 11px; }
.bar-track { background: var(--panel-2); border-radius: 3px; height: 8px; overflow: hidden; }
.bar-fill { display: block; height: 100%; border-radius: 3px;
  width: 100%; transform-origin: left;
  transition: transform 320ms cubic-bezier(0.32, 0.72, 0, 1); }
.bar-row .num { text-align: end; color: var(--muted); }

/* Tables ------------------------------------------------------------------ */
.table-wrap { overflow: auto; max-height: 260px; }
table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
th, td { padding: 5px 8px; text-align: start; white-space: nowrap; }
thead th {
  position: sticky; top: 0; background: var(--panel);
  color: var(--dim); font-size: 10px; font-weight: 600;
  letter-spacing: 0.07em; text-transform: uppercase;
  border-block-end: 1px solid var(--line-strong);
}
tbody tr { border-block-end: 1px solid var(--line); }
tbody tr:last-child { border-block-end: 0; }
tbody tr:hover { background: var(--panel-2); }
td.num, th.num { text-align: end; }
td.mut { color: var(--muted); }
.empty { color: var(--dim); padding: 14px 2px; font-size: 11.5px; }
.warn-text { color: var(--warn); }
.bad-text { color: var(--bad); }
.ok-text { color: var(--ok); }

/* Accuracy bar: uses the value as a compact visual, no chart junk. */
.meter { display: block; height: 3px; border-radius: 2px; background: var(--raise); margin-top: 4px; }
.meter > i { display: block; height: 100%; border-radius: 2px; background: var(--accent);
  width: 100%; transform-origin: left;
  transition: transform 320ms cubic-bezier(0.32, 0.72, 0, 1); }

/* Tooltip ---------------------------------------------------------------- */
.tip {
  position: fixed; z-index: 5; pointer-events: none; opacity: 0;
  transform: translate3d(-50%, -128%, 0);
  background: var(--raise); border: 1px solid var(--line-strong);
  border-radius: 4px; padding: 5px 7px; font-size: 11px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
  transition: opacity 120ms cubic-bezier(0.32, 0.72, 0, 1);
  white-space: nowrap;
}
.tip[data-on="1"] { opacity: 1; }
.tip b { font-family: var(--mono); font-weight: 550; }
.tip .tip-row { display: flex; justify-content: space-between; gap: 10px; }

/* Footer ------------------------------------------------------------------ */
.foot {
  margin-top: var(--gap); padding-top: 10px; border-top: 1px solid var(--line);
  color: var(--dim); font-size: 10.5px; max-width: 92ch;
}
.foot code { font-family: var(--mono); color: var(--muted); }
.table-wrap:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.scroll-hint { color: var(--dim); font-size: 10.5px; }
.data-status {
  margin: 12px 16px 0; padding: 9px 12px; border: 1px solid var(--line);
  border-radius: var(--r); background: var(--panel); color: var(--muted);
}
body[data-connection="error"] .data-status { border-color: var(--bad); }
body[data-connection="stale"] .data-status { border-color: var(--warn); }
@media (max-width: 640px) {
  .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tiles > .tile:last-child:nth-child(odd) { grid-column: 1 / -1; }
}
@media (prefers-reduced-motion: reduce) {
  .bar-fill, .meter > i, .conn, .tip { transition: none; }
}
"""

# Client code. Guardrails for this file: no third-party libraries, no build
# step, canvas-only drawing (no layout-thrashing animation), and every
# data-derived string is written with textContent — never innerHTML — because
# audit records and endpoints are attacker-influenced enough to matter.
APP_JS = """
"use strict";
(function () {
  var CONFIG = document.body.dataset;
  var CADENCE = { ok: 2000 };

  /* --- DOM helpers ------------------------------------------------------ */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function node(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined && text !== null) el.textContent = String(text);
    return el;
  }
  function clear(el) { while (el && el.firstChild) el.removeChild(el.firstChild); }

  /* --- formatting ------------------------------------------------------- */
  function isNil(v) { return v === null || v === undefined; }

  function compact(v) {
    if (isNil(v)) return "--";
    var abs = Math.abs(v);
    if (abs >= 1e9) return (v / 1e9).toFixed(2) + "B";
    if (abs >= 1e6) return (v / 1e6).toFixed(2) + "M";
    if (abs >= 1e4) return (v / 1e3).toFixed(1) + "k";
    if (abs >= 1000) return Math.round(v).toLocaleString();
    if (abs >= 10) return v.toFixed(1);
    if (abs >= 1) return v.toFixed(2);
    return abs === 0 ? "0" : v.toFixed(3);
  }
  function count(v) { return isNil(v) ? "--" : Math.round(v).toLocaleString(); }
  function ms(v) {
    if (isNil(v)) return "--";
    if (v === 0) return "0 ms";
    return v < 10 ? v.toFixed(2) + " ms" : v.toFixed(0) + " ms";
  }
  function usd(v) {
    if (isNil(v)) return "--";
    if (v === 0) return "$0";
    return "$" + (v < 1 ? v.toFixed(4) : v.toFixed(2));
  }
  function dur(seconds) {
    if (isNil(seconds)) return "--";
    var s = Math.max(0, Math.round(seconds));
    if (s < 60) return s + "s";
    if (s < 3600) return Math.floor(s / 60) + "m " + (s % 60) + "s";
    if (s < 86400) return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
    return Math.floor(s / 86400) + "d " + Math.floor((s % 86400) / 3600) + "h";
  }
  function pct(v, digits) {
    if (isNil(v)) return "--";
    return (v * 100).toFixed(digits === undefined ? 1 : digits) + "%";
  }
  function clock(t) {
    var d = new Date(t * 1000);
    return d.toLocaleTimeString(undefined, { hour12: false });
  }
  function rel(offsetSeconds) {
    var s = Math.round(offsetSeconds);
    var m = Math.floor(s / 60);
    return m + ":" + String(s % 60).padStart(2, "0");
  }

  /* --- tiles ------------------------------------------------------------ */
  function renderTile(selector, opts) {
    var tile = $(selector);
    if (!tile) return;
    tile.dataset.health = opts.health || "idle";

    var value = $('[data-slot="value"]', tile);
    clear(value);
    value.appendChild(node("span", null, opts.value));
    if (opts.unit) value.appendChild(node("span", "u", opts.unit));

    var meta = $('[data-slot="meta"]', tile);
    clear(meta);
    (opts.meta || []).forEach(function (entry) {
      if (isNil(entry) || entry === "") return;
      if (typeof entry === "string") { meta.appendChild(node("span", null, entry)); return; }
      var chip = node("span", "chip", entry.text);
      if (entry.tone) chip.dataset.tone = entry.tone;
      meta.appendChild(chip);
    });

    if (opts.spark) {
      drawSpark($('[data-slot="spark"]', tile), opts.spark, opts.color);
    }
  }

  /* --- canvas ----------------------------------------------------------- */
  var MONO = "ui-monospace, Menlo, Consolas, monospace";
  var THEME = {};
  function readTheme() {
    var cs = getComputedStyle(document.documentElement);
    ["accent", "ok", "warn", "bad", "neutral", "muted", "dim", "line", "line-strong", "text"]
      .forEach(function (key) { THEME[key] = cs.getPropertyValue("--" + key).trim(); });
  }
  function fit(canvas) {
    var dpr = window.devicePixelRatio || 1;
    var rect = canvas.getBoundingClientRect();
    var w = Math.max(1, Math.round(rect.width));
    var h = Math.max(1, Math.round(rect.height));
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx: ctx, w: w, h: h };
  }
  function niceMax(v) {
    if (v <= 1) return 1;
    var mag = Math.pow(10, Math.floor(Math.log10(v)));
    var n = v / mag;
    var step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10;
    return step * mag;
  }
  function trace(ctx, data, xAt, yAt) {
    var started = false;
    for (var i = 0; i < data.length; i++) {
      var v = data[i];
      if (isNil(v)) { started = false; continue; }
      var px = xAt(i), py = yAt(v);
      if (!started) { ctx.moveTo(px, py); started = true; } else { ctx.lineTo(px, py); }
    }
  }

  function drawSpark(canvas, values, color) {
    if (!canvas) return;
    var f = fit(canvas), ctx = f.ctx, w = f.w, h = f.h;
    ctx.clearRect(0, 0, w, h);
    var pts = (values || []).filter(function (v) { return !isNil(v); });
    if (pts.length < 2) return;
    var min = Math.min.apply(null, pts), max = Math.max.apply(null, pts);
    var span = (max - min) || 1, pad = 3;
    var xAt = function (i) { return i * (w / (pts.length - 1)); };
    var yAt = function (v) { return h - pad - ((v - min) / span) * (h - pad * 2); };
    var stroke = color || THEME.accent;

    ctx.beginPath();
    trace(ctx, pts, xAt, yAt);
    ctx.save();
    ctx.globalAlpha = 0.15;
    ctx.fillStyle = stroke;
    ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath(); ctx.fill();
    ctx.restore();

    ctx.beginPath();
    trace(ctx, pts, xAt, yAt);
    ctx.strokeStyle = stroke;
    ctx.lineWidth = 1.25;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();
  }

  var TIP = null;
  function tipEl() {
    if (!TIP) { TIP = node("div", "tip"); document.body.appendChild(TIP); }
    return TIP;
  }
  function showTip(rows, x, y) {
    var el = tipEl();
    clear(el);
    rows.forEach(function (row) {
      var line = node("div", "tip-row");
      line.appendChild(node("span", null, row.label));
      line.appendChild(node("b", null, row.value));
      el.appendChild(line);
    });
    el.style.left = x + "px";
    el.style.top = y + "px";
    el.dataset.on = "1";
  }
  function hideTip() { if (TIP) TIP.dataset.on = "0"; }

  var CHARTS = {};
  var PAD_L = 46, PAD_R = 10, PAD_T = 10, PAD_B = 22;

  function chart(id, spec) {
    var canvas = document.getElementById(id);
    if (!canvas) return;
    CHARTS[id] = spec;
    drawChart(canvas, spec);
    if (!canvas.__bound) {
      canvas.__bound = true;
      canvas.addEventListener("mousemove", function (ev) { onHover(canvas, id, ev); });
      canvas.addEventListener("mouseleave", function () {
        canvas.__hover = null;
        hideTip();
        if (CHARTS[id]) drawChart(canvas, CHARTS[id]);
      });
    }
  }

  function drawChart(canvas, spec) {
    var f = fit(canvas), ctx = f.ctx, w = f.w, h = f.h;
    ctx.clearRect(0, 0, w, h);
    var t = spec.t || [];
    var series = (spec.series || []).filter(function (s) { return s.data && s.data.length; });
    var innerW = Math.max(1, w - PAD_L - PAD_R);
    var innerH = Math.max(1, h - PAD_T - PAD_B);

    if (t.length < 2 || !series.length) {
      ctx.fillStyle = THEME.dim;
      ctx.font = "11px " + MONO;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("collecting samples", w / 2, h / 2);
      return;
    }

    var maxV = 0;
    series.forEach(function (s) {
      s.data.forEach(function (v) { if (!isNil(v) && v > maxV) maxV = v; });
    });
    if (!isNil(spec.threshold)) maxV = Math.max(maxV, spec.threshold);
    maxV = niceMax(maxV <= 0 ? 1 : maxV);

    var xAt = function (i) { return PAD_L + (i / (t.length - 1)) * innerW; };
    var yAt = function (v) { return PAD_T + innerH - (Math.max(0, v) / maxV) * innerH; };
    var yFmt = spec.yFormat || compact;

    ctx.strokeStyle = THEME.line;
    ctx.lineWidth = 1;
    ctx.fillStyle = THEME.dim;
    ctx.font = "10px " + MONO;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (var g = 0; g <= 4; g++) {
      var gv = (maxV / 4) * g;
      var gy = Math.round(yAt(gv)) + 0.5;
      ctx.beginPath(); ctx.moveTo(PAD_L, gy); ctx.lineTo(w - PAD_R, gy); ctx.stroke();
      ctx.fillText(yFmt(gv), PAD_L - 7, gy);
    }

    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    var lastIndex = t.length - 1;
    var ticks = [0, Math.floor(lastIndex / 2), lastIndex];
    ticks.forEach(function (index, position) {
      if (position > 0 && ticks[position - 1] === index) return;
      ctx.textAlign = index === 0 ? "left" : index === lastIndex ? "right" : "center";
      ctx.fillText(rel(t[index]), xAt(index), PAD_T + innerH + 5);
    });

    if (!isNil(spec.threshold)) {
      var ty = Math.round(yAt(spec.threshold)) + 0.5;
      ctx.save();
      ctx.setLineDash([4, 3]);
      ctx.strokeStyle = THEME.warn;
      ctx.beginPath(); ctx.moveTo(PAD_L, ty); ctx.lineTo(w - PAD_R, ty); ctx.stroke();
      ctx.restore();
    }

    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    series.forEach(function (s) {
      if (s.fill) {
        ctx.beginPath();
        trace(ctx, s.data, xAt, yAt);
        ctx.save();
        ctx.globalAlpha = 0.13;
        ctx.fillStyle = s.color;
        ctx.lineTo(xAt(lastIndex), PAD_T + innerH);
        ctx.lineTo(PAD_L, PAD_T + innerH);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      }
      ctx.beginPath();
      trace(ctx, s.data, xAt, yAt);
      ctx.strokeStyle = s.color;
      ctx.lineWidth = s.fill ? 1.3 : 1.5;
      if (s.dashed) ctx.setLineDash([3, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
    });

    var hover = canvas.__hover;
    if (!isNil(hover) && hover >= 0 && hover < t.length) {
      ctx.strokeStyle = THEME["line-strong"] || THEME.line;
      var hx = Math.round(xAt(hover)) + 0.5;
      ctx.beginPath(); ctx.moveTo(hx, PAD_T); ctx.lineTo(hx, PAD_T + innerH); ctx.stroke();
      series.forEach(function (s) {
        var v = s.data[hover];
        if (isNil(v)) return;
        ctx.beginPath();
        ctx.arc(xAt(hover), yAt(v), 2.6, 0, Math.PI * 2);
        ctx.fillStyle = s.color;
        ctx.fill();
      });
    }
  }

  function onHover(canvas, id, ev) {
    var spec = CHARTS[id];
    if (!spec || !spec.t || spec.t.length < 2) return;
    var rect = canvas.getBoundingClientRect();
    var innerW = Math.max(1, rect.width - PAD_L - PAD_R);
    var ratio = (ev.clientX - rect.left - PAD_L) / innerW;
    var idx = Math.max(0, Math.min(spec.t.length - 1, Math.round(ratio * (spec.t.length - 1))));
    canvas.__hover = idx;
    if (canvas.__raf) return;
    canvas.__raf = true;
    var point = { x: ev.clientX, y: ev.clientY };
    requestAnimationFrame(function () {
      canvas.__raf = false;
      drawChart(canvas, spec);
      var rows = [{ label: "t+" + rel(spec.t[idx]), value: "" }];
      spec.series.forEach(function (s) {
        var v = s.data[idx];
        rows.push({
          label: s.name,
          value: isNil(v) ? "--" : (s.format ? s.format(v) : compact(v)),
        });
      });
      showTip(rows, point.x, point.y);
    });
  }

  function renderLegend(id, entries) {
    var el = document.getElementById(id);
    if (!el) return;
    clear(el);
    entries.forEach(function (entry) {
      var key = node("span", "key");
      var swatch = node("span", "swatch");
      swatch.style.background = entry.color;
      if (entry.dashed) swatch.style.opacity = "0.6";
      key.appendChild(swatch);
      key.appendChild(node("span", null, entry.label));
      el.appendChild(key);
    });
  }

  /* --- tables ----------------------------------------------------------- */
  function tableAffordance(wrap) {
    var horizontal = !wrap.hidden && wrap.scrollWidth > wrap.clientWidth + 1;
    var scrollable = !wrap.hidden && (horizontal || wrap.scrollHeight > wrap.clientHeight + 1);
    wrap.tabIndex = scrollable ? 0 : -1;
    var hint = document.getElementById(wrap.dataset.hint);
    if (hint) {
      hint.hidden = !scrollable;
      hint.textContent = horizontal
        ? "Scroll for more columns. Focus the table and use arrow keys."
        : "Scroll for more rows. Focus the table and use arrow keys.";
      if (scrollable) wrap.setAttribute("aria-describedby", hint.id);
      else wrap.removeAttribute("aria-describedby");
    }
  }
  function fillTable(selector, rows, build, emptyMessage) {
    var body = $(selector + " tbody");
    if (!body) return;
    var wrap = body.closest(".table-wrap");
    var panel = wrap.closest(".panel");
    var id = body.closest("table").id;
    var empty = document.getElementById(id + "-empty");
    if (!empty) {
      empty = node("p", "empty");
      empty.id = id + "-empty";
      panel.appendChild(empty);
      var hint = node("p", "scroll-hint");
      hint.id = id + "-hint";
      panel.appendChild(hint);
      wrap.dataset.hint = hint.id;
      wrap.setAttribute("role", "region");
      wrap.setAttribute("aria-label", $("h2", panel).textContent + " table");
    }
    var active = document.activeElement;
    var focused = body.contains(active) ? active.closest("tr") : null;
    var index = focused ? Array.prototype.indexOf.call(body.children, focused) : -1;
    var key = focused ? focused.dataset.focusKey : null;
    clear(body);
    empty.hidden = !!(rows && rows.length);
    empty.textContent = emptyMessage;
    wrap.hidden = !empty.hidden;
    (rows || []).forEach(function (row) { body.appendChild(build(row)); });
    tableAffordance(wrap);
    if (index >= 0 && !wrap.hidden) {
      var fresh = key ? Array.from(body.children).find(function (row) {
        return row.dataset.focusKey === key;
      }) : body.children[index];
      var target = fresh || wrap;
      target.focus({ preventScroll: true });
    }
  }
  function cell(text, cls) {
    var td = node("td", cls);
    td.textContent = isNil(text) || text === "" ? "--" : String(text);
    return td;
  }
  function chipCell(text, tone) {
    var td = node("td");
    if (isNil(text) || text === "") {
      td.className = "mut";
      td.textContent = "--";
      return td;
    }
    var chip = node("span", "chip", text);
    if (tone) chip.dataset.tone = tone;
    td.appendChild(chip);
    return td;
  }
  function circuitTone(state) {
    return state === "open" ? "bad" : state === "half_open" ? "warn" : "ok";
  }
  function decisionTone(decision) {
    var value = String(decision || "").toLowerCase();
    if (value.indexOf("deny") === 0 || value.indexOf("block") === 0 || value.indexOf("exceed") >= 0) return "bad";
    if (value.indexOf("fallback") >= 0 || value.indexOf("downgrade") >= 0) return "warn";
    if (value.indexOf("cache") >= 0) return "ok";
    return null;
  }

  function sessionRow(row) {
    var tr = node("tr");
    tr.tabIndex = -1;
    tr.dataset.focusKey = row.session_id;
    tr.appendChild(cell(row.session_id, "mono"));
    tr.appendChild(cell(row.provider, row.provider ? "" : "mut"));
    var used = node("td", "num");
    used.appendChild(node("span", null, count(row.budget_spent)));
    if (!isNil(row.budget_limit)) {
      var meter = node("span", "meter");
      var bar = node("i");
      var percent = Math.max(0, Math.min(100, row.budget_pct_used || 0));
      bar.style.transform = "scaleX(" + percent / 100 + ")";
      bar.style.background = percent >= 95 ? THEME.bad : percent >= 80 ? THEME.warn : THEME.accent;
      meter.appendChild(bar);
      used.appendChild(meter);
    }
    tr.appendChild(used);
    tr.appendChild(cell(isNil(row.budget_remaining) ? "unlimited" : count(row.budget_remaining), "num"));
    tr.appendChild(cell(row.concurrency_active + " / " + row.concurrency_limit, "num"));
    tr.appendChild(chipCell(row.circuit, circuitTone(row.circuit)));
    tr.appendChild(cell(dur(row.age_s), "num"));
    return tr;
  }

  function eventRow(ev) {
    var tr = node("tr");
    tr.appendChild(cell(ev.ts ? clock(ev.ts) : null, "num mut"));
    tr.appendChild(chipCell(ev.decision, decisionTone(ev.decision)));
    tr.appendChild(cell(ev.reason, "mut"));
    tr.appendChild(cell(ev.endpoint, "mut"));
    tr.appendChild(cell(ev.priority, "mut"));
    tr.appendChild(cell(isNil(ev.estimated_tokens) ? null : count(ev.estimated_tokens), "num"));
    return tr;
  }

  function tenantRow(tenant) {
    var tr = node("tr");
    tr.appendChild(cell(tenant.tenant_id, "mono"));
    tr.appendChild(cell(count(tenant.used), "num"));
    tr.appendChild(cell(count(tenant.remaining), "num"));
    return tr;
  }

  /* --- outcome mix ------------------------------------------------------ */
  var OUTCOME_TONE = {
    success: "ok", fallback: "warn", error: "bad",
    circuit_open: "bad", exception: "warn",
  };

  function renderOutcomes(outcomes) {
    var host = document.getElementById("outcome-mix");
    if (!host) return;
    clear(host);
    var entries = Object.keys(outcomes || {}).map(function (key) { return [key, outcomes[key]]; });
    if (!entries.length) {
      host.appendChild(node("p", "empty", "No requests recorded yet."));
      return;
    }
    entries.sort(function (a, b) { return b[1] - a[1]; });
    var total = entries.reduce(function (sum, entry) { return sum + entry[1]; }, 0) || 1;
    entries.forEach(function (entry) {
      var row = node("div", "bar-row");
      row.appendChild(node("span", "mono", entry[0]));
      var track = node("span", "bar-track");
      var fill = node("i", "bar-fill");
      fill.style.transform = "scaleX(" + Math.max(0, Math.min(1, entry[1] / total)) + ")";
      fill.style.background = THEME[OUTCOME_TONE[entry[0]] || "neutral"];
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(node("span", "num", count(entry[1])));
      host.appendChild(row);
    });
  }

  /* --- render ----------------------------------------------------------- */
  function render(snap) {
    var kpi = snap.kpi;
    var series = snap.series || {};

    var budget = kpi.budget;
    var budgetHealth = "idle";
    if (!isNil(budget.remaining)) {
      var usedPct = budget.pct_used || 0;
      budgetHealth = usedPct >= 95 ? "bad" : usedPct >= 80 ? "warn" : "ok";
      if (!isNil(budget.eta_seconds) && budget.eta_seconds <= 3600 && budgetHealth === "ok") {
        budgetHealth = "warn";
      }
    }
    renderTile("#tile-budget", {
      value: compact(budget.remaining),
      unit: isNil(budget.remaining) ? "" : "tokens",
      health: budgetHealth,
      meta: [
        isNil(budget.pct_used) ? "no cap configured" : Math.round(budget.pct_used) + "% of cap used",
        budget.burn_tokens_per_min ? compact(budget.burn_tokens_per_min) + "/min burn" : null,
        isNil(budget.eta_seconds)
          ? null
          : {
              text: "exhausts in " + dur(budget.eta_seconds),
              tone: budget.eta_seconds <= 3600 ? "bad" : "warn",
            },
      ],
      spark: series.budget_remaining,
      color: THEME.accent,
    });

    var spend = kpi.spend;
    renderTile("#tile-spend", {
      value: isNil(spend.usd_lower_bound) ? compact(spend.tokens) : usd(spend.usd_lower_bound),
      unit: isNil(spend.usd_lower_bound) ? "tokens" : "USD",
      health: "ok",
      meta: [
        isNil(spend.usd_lower_bound) ? null : compact(spend.tokens) + " tokens",
        isNil(spend.usd_lower_bound) ? "set --cost-model for USD" : "input-rate lower bound",
      ],
      spark: series.burn_tokens_per_min,
      color: THEME.accent,
    });

    var prevention = kpi.prevention;
    renderTile("#tile-prevented", {
      value: count(prevention.total),
      unit: "calls",
      health: prevention.total > 0 ? "ok" : "idle",
      meta: [
        { text: count(prevention.budget_blocked) + " budget", tone: prevention.budget_blocked > 0 ? "warn" : null },
        { text: count(prevention.circuit_open) + " circuit", tone: prevention.circuit_open > 0 ? "bad" : null },
        count(prevention.rate_limited) + " rate-limit",
      ],
      spark: series.prevented,
      color: prevention.total > 0 ? THEME.ok : THEME.neutral,
    });

    var traffic = kpi.traffic;
    renderTile("#tile-requests", {
      value: traffic.rps >= 10 ? traffic.rps.toFixed(0) : traffic.rps.toFixed(2),
      unit: "req/s",
      health: traffic.requests > 0 ? "ok" : "idle",
      meta: [
        count(traffic.requests) + " total",
        count(traffic.provider_calls) + " provider calls",
        traffic.retries > 0
          ? { text: count(traffic.retries) + " retries", tone: "warn" }
          : "no retries",
      ],
      spark: series.rps,
      color: THEME.accent,
    });

    var latency = kpi.latency;
    renderTile("#tile-latency", {
      value: ms(latency.p95_ms),
      health: "ok",
      meta: ["p50 " + ms(latency.p50_ms), "p99 " + ms(latency.p99_ms), "incl. provider"],
      spark: series.latency_p95_ms,
      color: THEME.accent,
    });

    var concurrency = kpi.concurrency;
    var saturation = concurrency.capacity ? concurrency.active / concurrency.capacity : 0;
    renderTile("#tile-concurrency", {
      value: concurrency.active + " / " + concurrency.capacity,
      health: saturation >= 0.9 ? "warn" : "ok",
      meta: [count(concurrency.queued) + " queued", "AIMD limit"],
      spark: series.concurrency_active,
      color: THEME.accent,
    });

    var circuit = kpi.circuit;
    renderTile("#tile-circuit", {
      value: String(circuit.state || "unknown").replace("_", " "),
      health: circuit.state === "open" ? "bad" : circuit.state === "half_open" ? "warn" : "ok",
      meta: [
        count(circuit.trips) + " trips",
        { text: count(kpi.isolation.sessions) + " sessions", tone: null },
      ],
      color: circuit.state === "open" ? THEME.bad : THEME.ok,
    });

    var preventionColor = (series.prevented_rps || []).some(function (v) { return v > 0; })
      ? THEME.bad : THEME.neutral;
    chart("chart-traffic", {
      t: series.t,
      yFormat: function (v) { return v >= 10 ? v.toFixed(0) : v.toFixed(1); },
      series: [
        { name: "requests/s", color: THEME.accent, data: series.rps, fill: true },
        { name: "prevented/s", color: preventionColor, data: series.prevented_rps },
      ],
    });
    renderLegend("legend-traffic", [
      { label: "requests / s", color: THEME.accent },
      { label: "prevented / s", color: preventionColor },
    ]);

    chart("chart-burn", {
      t: series.t,
      series: [
        {
          name: "burn",
          color: THEME.accent,
          data: series.burn_tokens_per_min,
          fill: true,
          format: function (v) { return compact(v) + " tok/min"; },
        },
      ],
    });
    renderLegend("legend-burn", [{ label: "tokens / min", color: THEME.accent }]);

    fillTable("#tbl-sessions", snap.sessions, sessionRow,
      "No live sessions. Wrap a client in this process, or run with --demo.");
    fillTable("#tbl-events", snap.events, eventRow,
      "No audit log configured, or no enforcement decision recorded yet.");
    fillTable("#tbl-tenants", snap.tenants, tenantRow,
      "No request-scoped tenant budgets registered.");
    renderOutcomes(snap.outcomes);

    var warnHost = document.getElementById("warnings");
    var warnings = snap.warnings || [];
    clear(warnHost);
    if (!warnings.length) {
      warnHost.hidden = true;
    } else {
      var list = node("ul");
      warnings.forEach(function (text) { list.appendChild(node("li", null, text)); });
      warnHost.appendChild(list);
      warnHost.hidden = false;
    }

    // Methodology is printed, not implied: every derived number states how it
    // was derived, so the dashboard can be argued with.
    var notes = [];
    notes.push("Window " + dur(snap.uptime_s) + ", sampled every " + snap.sample_interval_s +
      "s, rates over a rolling " + dur(snap.window_seconds) + " window.");
    notes.push("Spend prevented counts requests the guardrails stopped before dispatch " +
      "(budget, rate limit, open circuit, transport exception); cache hits are counted " +
      "separately as calls avoided.");
    notes.push("Latency is end-to-end transport duration and includes provider time; " +
      "guardrail overhead is measured separately by backstop benchmark.");
    notes.push(snap.sinks.cost_model
      ? "USD is a lower bound: all tokens costed at the " + snap.sinks.cost_model +
        " input rate, because the counters do not split prompt from completion tokens."
      : "Set --cost-model to convert tokens into a USD lower bound.");
    notes.push("Session budgets are read from live BackstopState objects; the Prometheus " +
      "gauges are unlabelled and therefore last-writer-wins when one process runs " +
      "several sessions.");
    var methodology = document.getElementById("methodology");
    if (methodology) methodology.textContent = notes.join(" ");
  }

  /* --- polling ---------------------------------------------------------- */
  var refreshMs = parseInt(CONFIG.refresh, 10) || 2000;
  var timer = null;
  var latest = null;
  var inFlight = false;
  var disconnected = false;
  var lastContact = null;
  var sampleAge = null;
  var sampleReceived = 0;
  var etag = null;
  var REQUEST_TIMEOUT_MS = 10000;

  function setConn(state) {
    var el = document.getElementById("conn");
    if (el) el.dataset.state = state;
    document.body.dataset.connection = state;
  }

  function ageNow() {
    return isNil(sampleAge) ? null : sampleAge + (performance.now() - sampleReceived) / 1000;
  }

  function schedule() {
    clearTimeout(timer);
    timer = null;
    if (!document.hidden && !inFlight) timer = setTimeout(tick, refreshMs);
  }

  async function tick() {
    clearTimeout(timer);
    timer = null;
    if (document.hidden || inFlight) return;
    inFlight = true;
    var controller = new AbortController();
    var started = performance.now();
    var timeout = setTimeout(function () { controller.abort(); }, REQUEST_TIMEOUT_MS);
    try {
      var headers = { Accept: "application/json" };
      if (etag) headers["If-None-Match"] = etag;
      var res = await fetch("/api/snapshot", {
        headers: headers,
        cache: "no-store",
        signal: controller.signal,
      });
      if (res.status === 304) {
        if (!latest) throw new Error("No snapshot to revalidate");
      } else {
        if (!res.ok) throw new Error("HTTP " + res.status);
        var next = await res.json();
        if (controller.signal.aborted) throw new Error("Snapshot timed out");
        if (!next || !next.kpi || !next.sinks ||
            !["budget", "spend", "prevention", "traffic", "latency", "concurrency", "circuit", "isolation"]
              .every(function (key) { return next.kpi[key] && typeof next.kpi[key] === "object"; })) {
          throw new Error("Invalid snapshot");
        }
        var received = performance.now();
        var age = typeof next.sample_age_s === "number" && Number.isFinite(next.sample_age_s)
          ? Math.max(0, next.sample_age_s) + (received - started) / 1000 : null;
        if (latest && !isNil(next.sampled_at) && next.sampled_at === latest.sampled_at &&
            !isNil(age) && !isNil(sampleAge)) age = Math.max(age, ageNow());
        render(next);
        latest = next;
        sampleAge = age;
        sampleReceived = received;
        etag = res.headers.get("ETag");
      }
      disconnected = false;
      lastContact = performance.now();
    } catch (err) {
      disconnected = true;
    } finally {
      clearTimeout(timeout);
      inFlight = false;
      ticker();
      schedule();
    }
  }

  function ticker() {
    var el = document.getElementById("updated");
    var notice = document.getElementById("data-status");
    if (!el) return;
    var age = ageNow();
    var interval = latest && Number(latest.sample_interval_s) > 0
      ? Number(latest.sample_interval_s) * 1000 : refreshMs;
    var stale = !isNil(age) && age * 1000 > Math.max(interval, refreshMs) * 3;
    var quiet = !isNil(lastContact) && performance.now() - lastContact > refreshMs * 3;
    var message = "";
    if (disconnected) {
      setConn("error");
      el.textContent = "disconnected";
      message = latest
        ? "Connection lost. Showing stale data" + (isNil(age) ? "" : " from " + dur(age) + " ago") + ". Retrying automatically."
        : "Unable to load telemetry. Retrying automatically.";
    } else if (!latest) {
      setConn("pending");
      el.textContent = "connecting";
      message = "Loading telemetry...";
    } else if (isNil(age)) {
      setConn(quiet ? "stale" : "pending");
      el.textContent = "waiting for samples";
      message = "No telemetry samples yet. Waiting for the sampler.";
    } else if (stale || quiet) {
      setConn("stale");
      el.textContent = "sample " + dur(age) + " old";
      message = "Showing stale data. Last sample " + dur(age) + " ago; waiting for fresh telemetry.";
    } else {
      setConn("ok");
      el.textContent = age < 2 ? "sample just now" : "sample " + dur(age) + " ago";
    }
    if (notice) {
      notice.hidden = !message;
      notice.textContent = message;
    }
    document.getElementById("main").setAttribute("aria-busy", String(!latest && !disconnected));
  }

  function boot() {
    try {
      var stored = localStorage.getItem("backstop-theme");
      if (["auto", "dark", "light"].indexOf(stored) >= 0) {
        document.documentElement.dataset.theme = stored;
      }
    } catch (e) {}
    readTheme();
    var select = document.getElementById("refresh");
    if (select) {
      select.value = String(refreshMs);
      select.addEventListener("change", function () {
        refreshMs = parseInt(select.value, 10) || 2000;
        schedule();
      });
    }
    // Theme cycle: auto -> dark -> light -> auto. Stored per browser so the
    // choice survives reloads; the server's --theme flag sets the initial
    // value and remains the fleet-wide default.
    var toggle = document.getElementById("theme-toggle");
    if (toggle) {
      var order = ["auto", "dark", "light"];
      var start = order.indexOf(document.documentElement.dataset.theme);
      var idx = start >= 0 ? start : 0;
      var label = function () {
        toggle.textContent = "theme: " + order[idx];
      };
      label();
      toggle.addEventListener("click", function () {
        idx = (idx + 1) % order.length;
        document.documentElement.dataset.theme = order[idx];
        try { localStorage.setItem("backstop-theme", order[idx]); } catch (e) { /* private mode */ }
        label();
        readTheme();
        if (latest) render(latest);
      });
    }
    if (window.matchMedia) {
      var query = window.matchMedia("(prefers-color-scheme: light)");
      var sync = function () { readTheme(); if (latest) render(latest); };
      if (query.addEventListener) query.addEventListener("change", sync);
    }
    document.addEventListener("visibilitychange", function () {
      ticker();
      if (!document.hidden) tick();
      else schedule();
    });
    window.addEventListener("resize", function () {
      if (latest) render(latest);
    });
    setInterval(ticker, 1000);
    tick();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
"""