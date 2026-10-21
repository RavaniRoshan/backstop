<div align="center">
  <p>
    <a href="README.md">README</a> •
    <a href="CODE_OF_CONDUCT.md">Code of Conduct</a>
  </p>
</div>

# Changelog

All notable changes to Backstop should be documented in this file.

## [Unreleased]

### Dashboard

- **Round axis ticks on every chart** (1/2/5 × 10ⁿ steps) and **one formatter
  per quantity**, so no number changes shape mid-scale: a count is a count, a
  rate is a rate, an axis label is an axis label.
- **A wall-clock x-axis.** Each chart states the window it shows
  (`14:32:05 → 14:36:05 · 4m`), so a spike lines up with a log line instead of
  a label that shifts on every refresh. A **window** control (`1m` / `5m` /
  `15m` / all) slices the in-memory ring.
- **The refresh control can be turned off**, so the surface can be paused —
  an auto-updating view has to be pausable. The sample age keeps counting so
  the data's age stays visible.
- **Status is text first.** Every tile carries a status token (`OK`, `WATCH`,
  `BREACH`, `IDLE`, `NO DATA`) next to its colour, the connection state reads
  `live` / `stale` / `lost` / `connecting`, and the amber-red pair is never the
  only difference between two states — which is what keeps it apart for a
  colour-blind reader. The freshness line is no longer a live region, so a
  screen reader hears a state change once rather than once a second.
- **No more empty panels.** Panels size to their content, a tile's sparkline
  fills the tile, and a flat series is drawn across the middle instead of
  glued to the bottom edge where it reads as a crash.
- **The tile grid has no holes.** Seven tiles do not divide evenly, so the
  grid is a twelve-column one: the first row takes four tiles, the last row
  takes three of four columns each, and on a narrow screen the last tile
  becomes a full-width status bar. No value is ever truncated to fit.
- **Removed the Sessions "Provider" column**, which was always `--`:
  `BackstopState` has no such attribute.
- **"vs previous window" deltas** on every tile that has a series,
  **enforcement events annotated on the traffic chart**, a compact
  **needs-attention strip**, and **drill-down from a tile to the tables**.
- **Charts are readable without a mouse**: each has a text summary for
  assistive technology and a *Show as table* alternative; tooltips are
  dismissible with `Esc`; tables take arrow-key row navigation, which the
  on-screen hint already promised.
- **`series.circuit_open_rps`** was added to the snapshot so the circuit tile
  charts the requests the open breaker turned away rather than rendering an
  empty sparkline.

### The website

- **A marketing page and a documentation site**, in one static build. The
  documentation is not a copy: `site/scripts/prepare-content.mjs` derives the
  site's content from the repository's own `docs/*.md` at build time, so the
  documents people read on GitHub and the documents the site serves are the same
  files.
- **The site is built on [Blume](https://useblume.dev)** for the documentation
  — a zero-config, Markdown-first framework on Astro and Vite — and on plain
  Astro for the marketing page, mounted beside the docs so both share one
  header, one search and one theme toggle.
- **The palette is the dashboard's palette.** The site and the product it
  documents are the same colour, in both themes.
- **The site makes no outbound request.** The fonts are self-hosted at build
  time, and the Content-Security-Policy says `default-src 'none'`, exactly like
  the dashboard.
- **A link checker** (`site/scripts/check-links.mjs`) resolves every internal
  link in the built output, and CI builds the site and runs it.

### The website, second pass

- **The site has a new palette.** A paper white, a near-black that reads as
  ink, and one warm orange that carries every accent — the links, the hover
  states, the live wires in the diagram, the numbers on the loader. The dark
  theme is the same system on a black ground. The values are `oklch`, because
  that is where the palette was written.
- **The hero is two columns.** The words on the left, the request path on the
  right: the agents at the top, their requests falling into Backstop, and the
  two endpoint shapes Backstop forwards to. The headline is shorter and set
  much larger, because a headline that reads at that size cannot be a
  sentence.
- **The feature list is a bento.** [Aceternity](https://ui.aceternity.com)'s
  grid — three columns of eighteenrem rows, each card a bordered panel with
  the content at the bottom and the whole block sliding to the right on
  hover — with the "with skeletons" treatment: each card's upper half is a
  shimmering placeholder, the way a card looks before its content arrives.
- **There is a footer.** Four columns of links, a wordmark the size of the
  page behind it, and the legal line. There was none before.
- **The dithered hero field is gone.** It was a nice effect and the wrong
  one: a full-screen halftone behind a headline is decoration where the
  headline should be.

- **The real brand marks.** The marketing page now draws the actual logos of
  the tools it talks about — the agents on the left of the wiring diagram, the
  servers in the integrations section, the endpoints on the right. They are
  fetched once, committed as SVG under `site/assets/logos/`, and compiled by
  `site/scripts/prepare-logos.mjs` into a typed module. Nothing is fetched at
  runtime, and nothing is invented.
- **A mark that survives a dark page.** Most brand SVGs are drawn inside a
  square box with the artwork filling only part of it — the AWS mark uses 14 of
  its 24 units, NVIDIA 16. Rendered at one height, those came out visibly
  smaller than the ones that filled their box, so every mark's viewBox is now
  cropped to its own ink. A mark that was a single flat colour with the colour
  baked in (the Codex mark is `#111`, which vanished on a dark page) is
  normalised to `currentColor` and tinted by the page.
- **The wiring diagram.** The agents on the left, Backstop in the middle, the
  endpoint shapes on the right: one story in three columns, with the wires
  drawing themselves in and the requests travelling along them.
- **An integrations section, and the number behind it.** Backstop does not
  know what a provider is, so "how many servers does this work with?" has one
  answer: every server that speaks the OpenAI-compatible protocol, and the two
  that do not. Twenty-two of them are named, with their real marks, in four
  lanes — and the one line that differs between them: the price list.
- **A documentation page for it** (`docs/integrations.md`), with the commands:
  pointing an SDK at a local server, running the gateway in front of one, and
  filing a price for a model the bundled catalogue does not carry.
- **Motion across the page**, with three rules: nothing moves if the reader
  asked for it not to; nothing is hidden unless JavaScript is going to show it
  again, so the page is complete without it; and everything is revealed once.
  The hero enters on load, the sections arrive as the reader reaches them, the
  strip of marks fades in one after another, and the proof numbers count up.
- **The site is published to GitHub Pages**, at
  <https://ravaniroshan.github.io/backstop/>. The repository's Pages setting was
  already "GitHub Actions" as the build source, but nothing was building it —
  which is why the project URL 404'd. The base path is not written down
  anywhere: `configure-pages` reports where GitHub will actually serve the
  site, and the build takes its base path and its canonical URL from there.
- **The hero sits on a dithered field.** The dashboard screenshot, rendered as
  a one-bit halftone, tears open into full colour where the cursor sweeps. It
  is [Originkit](https://originkit.dev)'s `dither-reveal` component, ported:
  the component arrives as a React component that fetches a remote image, and
  the site has neither React nor a remote fetch — so the shader is Originkit's
  unchanged, the image is the one the site already serves, the driver is
  plain TypeScript, and the field is inverted on the light theme so the same
  halftone reads as ink on paper rather than as a dark band.
- **The page arrives behind a loader.** A grid of tiles fills with the page's
  own foreground as the load progresses, then shrinks away in a diagonal sweep
  to lift. It is [Originkit](https://originkit.dev)'s `tiles-loader`, ported:
  the component arrives as a React component with a fourteen-second default
  wait, and this site has neither React nor fourteen seconds to stand between
  a reader and a page. The page is rendered behind the loader the whole time,
  the loader cannot trap a reader — a `<noscript>` rule, a failsafe and
  `prefers-reduced-motion` all remove it — and the documentation has no
  loader at all, because a reader looking for an answer should not be made
  to wait for a curtain.

### Dashboard, second pass

- **Every signal the snapshot already carried is now visible.** Cache hits
  avoided, transport exceptions prevented, tenant-scoped budget blocks, and
  provider calls per request (which is where retry waste shows up) are on the
  tiles instead of being in the payload and nowhere else.
- **A panel for the runaway-spend detectors.** The four detectors reported
  into the snapshot and had no surface at all. There is now a panel that
  states whether detection is on, whether it is in shadow mode, and what each
  detector fired — in the detector's own unit: dollars per minute for
  velocity, tokens per request for drift, retries per request for retry
  amplification, a multiplier for context growth.
- **The demo now produces real enforcement events.** The audit log accepts a
  callable sink, so the demo workload holds its records in memory: the
  enforcement-events table, the chart markers and the outcome mix are populated
  by real decisions, and the demo still writes nothing to disk.
- **The demo's breaker now actually trips.** Its 60-second circuit window
  averaged the error storm together with the calm stages around it, so the
  failure rate never reached the threshold and the breaker never opened. The
  demo's window is now as long as its error stage.
- **The audit tail states what it cannot prove**, next to the rows it shows.

## 0.8.0 — "One Policy, Two Drivers"

The release theme is **every claim the product makes becomes true**. The same
enforcement logic was written twice — once in the sync transport, once in the
async one — and it drifted: the async path emitted 2 of the 7 audit decisions
the sync path did, its semantic cache was never constructed, and its shadow
mode consulted a different branch. A user on `AsyncOpenAI` was running a
different guardrail from a user on `OpenAI`, and nothing in the test suite
noticed.

### Added

- **A budget denominated in dollars.** `Backstop.wrap(client, budget=50_000,
  budget_usd=Decimal("5.00"))` is a second ceiling, not a replacement: a
  request is admitted only if it fits under both. The money is `Decimal` end to
  end and a float is refused, because a float cannot represent most fractions
  of a dollar exactly and a ceiling a cent out is a ceiling that lets the
  wrong request through. The shared Redis backend stores it in integer
  micro-dollars, because Lua's `tonumber` is a double. A model the catalog
  cannot price is **refused** under a dollar ceiling — a ceiling with a hole
  in it is not a ceiling — and `budget_usd_unpriced_policy="allow"` says so
  explicitly and records the request as unpriced. See `docs/usd-budgets.md`.
- **A sync/async parity test** (`tests/test_parity.py`) that drives both
  transports through the same scripted scenarios and asserts the same audit
  decisions, the same metric names *and* labels, and the same outcome. It
  would have caught every divergence listed below, and it makes future drift
  impossible rather than merely unlikely.
- **A mixed-mode admission test** (`tests/test_admission_mixed.py`) that
  reproduces the deadlock the two-condition gate allowed, in both directions.
- **A documentation-truthfulness test** (`tests/test_docs_consistency.py`):
  the version every version-claiming document names, that `llms.txt` lists
  every command the parser actually has, that no doc page is orphaned, and
  that no document links to a file that does not exist.
- **Four new commands.** `backstop budget` — where the spend stands against a
  ceiling, and the headroom left. `backstop detect` — the four runaway-spend
  detectors over a ledger file. `backstop forecast` — when the budget runs
  out, at the burn rate the ledger measured. `backstop audit` — verify the
  tamper-evident audit chain. All four are offline and need no key, and all
  take `--json`.
- **`backstop --version`**, which used to exit 2 with a usage error.
- **A grouped `--help`.** Twelve commands sat in one flat list, in the order
  they happened to be registered, with no indication of which needed a key.
  They are now grouped by what the operator is doing: *Prove it*, *Money*,
  *Run it*, *Live check*.
- **`AdmissionTimeoutError`**, which inherits from both `BackstopError` and
  the builtin `TimeoutError`. A queue timeout used to be raised as the bare
  builtin, so `except BackstopError` — the class every other enforcement
  failure belongs to — silently missed it.
- **A price table with 45 models and a downgrade map beside it.** The map
  used to live in a second table with 18 models and float rates, while the
  catalog held 45 with exact decimal ones, so **31 of the 45 models Backstop
  priced had no downgrade target at all** and the downgrade feature silently
  did nothing for every current-generation model.
- **New documentation pages**: `docs/usd-budgets.md`, `docs/detection.md`,
  `docs/alerts.md`, `docs/frameworks.md`.
- **A dependency audit in CI**, for both Python and npm, and a **coverage
  floor**.

### Fixed

- **A sync release never woke an async waiter.** `PriorityGate` guarded one
  set of counters and one set of queues with two independent conditions, one
  for each path. A request could wait forever for a slot that was already
  free — no error, no timeout, in an otherwise healthy process. The gate now
  has one lock discipline, and both paths are notified.
- **The async transport emitted 2 of 7 audit decisions.** Budget denial,
  downgrade, fallback and circuit-open produced no audit row at all on
  `AsyncOpenAI` / `AsyncAnthropic`.
- **The shadow-mode audit trail was always empty.** The shadow collector
  called `.record()` on `config.audit_sink`, which is documented as a file
  path or a callable; a `str` has no `.record`, and the `AttributeError` was
  swallowed. The shadow decisions now go into the audit log.
- **Sync shadow mode denied what it promised to let through**, on the tenant
  downgrade path.
- **The semantic cache was silently disabled for every async client**, while
  `cache_semantic_hits` kept counting — a metric that could never fire.
- **`fallback_chain_for_priority` validated only the last priority's chain.**
  Whether a malformed chain was caught depended on the order the dict keys
  happened to be written in.
- **`backstop serve` built a new transport — and a new connection pool — per
  request.** No connection reuse, a fresh TLS handshake every time, an always
  empty cache, shadow counters that reset on every request, and an alert dedup
  that never deduplicated.
- **`AuditLog.verify()` raised** `KeyError`/`ValueError` on a tampered line
  instead of returning `False`. It also took its lock twice per record, so the
  file's order and the chain's order could disagree and an untampered log
  could fail its own verification. And its file handle was never closed.
- **`TenantBudget.commit` treated a zero token count as "no measurement"**
  and charged the estimate instead, so a tenant budget drifted upward for
  every request that really used nothing.
- **The import-time read of `~/.cache/backstop/pricing.json`**, a file that
  could never be written because the only writer was dead code.
- **`backstop.cost` was a fake module** shadowing the real
  `backstop/cost.py`; `backstop.cost.CostEstimate` did not exist.
- **`from backstop.ledger import *` raised `AttributeError`** — `__all__`
  named a symbol the module never imported.
- **`max_wrap_sessions` counted lifetime wraps, not live ones**, and was never
  decremented, so a process that wrapped and closed a client in a loop kept
  warning about a ceiling it was nowhere near.
- **`Metrics` could not be constructed twice** — every instrument was
  registered on the global default registry, so a second instance raised
  `DuplicateTimeseries`. The registry is now injectable.
- **The semantic cache's embedding dict was never bounded**, so a process
  with the semantic cache on leaked one vector per distinct request.
- **`cache_semantic_hits` was missing from the OpenTelemetry mirror**, and the
  OTel gauge dict was read and written without a lock.
- **The request body was JSON-decoded twice per request**, and sniffing its
  first byte copied the whole body — `bytes.strip()` always allocates.
- **The quota monitor rebuilt a dict of every response header** and did twelve
  lookups on every response, to usually find nothing.
- **The TypeScript port's admission gate had two bugs of the same shape**:
  `high` was missing from the queue the gate chooses from, so a
  high-priority request waited for a slot that was never offered to it; and
  the waiters polled only when a timeout was configured, so with the default
  `queueTimeoutMs: null` a request that could not be admitted immediately
  hung forever. The waiters are now woken when a slot frees, and the timeout
  is a timer of its own.
- **Six TypeScript config options were accepted and read by nothing** —
  `agentMaxCalls`, `agentWindowMs`, `agentMaxTokens`, `maxWrapSessions`,
  `requestTimeoutMs` and `streamTimeoutMs`. The agent guardrail is now
  consulted, the deadline is enforced, and the wrap-session ceiling warns.
- **The TypeScript budget was not a hard ceiling** — `critical` and `high`
  were let past an exhausted budget, which is not what the Python package
  does. A guardrail whose strength depends on the caller's mood is not a
  guardrail.

### Changed

- **The version has one home.** `src/backstop/__init__.py` holds it, and
  `pyproject.toml` reads it at build time through hatchling's dynamic version.
  The npm package, the npm lockfile, `install.sh` and the `wedge` package are
  copies, and a test now checks that they agree.
- **The decisions live in `backstop.policy`**, written once, and the two
  transports keep only their own sequences — the parts that must await.
  `transports.py` went from 1,561 lines to 1,239, with 484 lines of shared
  policy beside it.
- **`log_json` and `log_sink` are removed.** They were documented, validated
  and never implemented. A configuration knob that does nothing is worse than
  no knob.
- **`RateLimitError` and `GuardrailViolationError` are exported** from
  `backstop`. Both are raised by the transport, and a user had to know to
  import them from a submodule to catch them.
- **The estimate is itemised** into its input and output parts, and the two
  sum to exactly the figure `estimate_tokens` has always returned — so
  splitting it cannot change what a token budget admits.
- **The `BudgetBackend` protocol is unchanged.** The dollar dimension is an
  addition — `reserve_with_usd`, `commit_with_usd` — so a backend written
  before dollar ceilings existed keeps working.
- **The OpenTelemetry mirror no longer keeps its own exemplar map.** An OTel
  exemplar is a trace link the SDK attaches from the active span; the
  hand-kept mapping was a second mechanism that nothing ever wrote to.
- **Every published version string moved to 0.8.0**, and the CI comment that
  claimed cosign, SLSA provenance and SBOM generation is now three real
  steps rather than three words.
- **The npm package is published by the release tag**, with provenance. It
  was published by hand, and it drifted: the lockfile shipped as
  `@ravanish/backstop@0.5.0` while `package.json` said `backstop-ai@0.6.0`,
  through a 0.6.0 release.
- **`py.typed` ships**, so a downstream type checker uses the package's
  annotations. The package is fully annotated and none of it was reaching
  anyone's editor.
- **The licence uses PEP 639's form**, so the licence *text* ships rather
  than a declaration that it exists.
- **The classifiers say Beta**, and list 3.13, which CI now tests.

### Removed

- `log_json` and `log_sink` — documented, validated, and never implemented.
- `src/backstop/wrapper.py.backup` and `wrapper.py.backup2` — 498 lines of
  stale source that were tracked, and that hatchling included in the wheel
  everybody installs. CI now asserts the wheel contains no `.backup`.
- The internal agent scratch, the one-shot patch script and the completed
  ledger checklist, which are no longer tracked.

### Documentation

- The README claimed the TypeScript package "is not in CI" — it is — and that
  it has no semantic cache — it has one. Both were the wrong way round: the
  document understated the package.
- The README's "no forecasting" contradicted the shipped forecast command.
- `llms.txt` — the file an agent installer reads first — is regenerated from
  the real parser and now lists every command. It had eight of twelve,
  omitting the entire money surface.
- The dashboard page, the Prometheus alert rules and the whole `usecases/`
  tree were shipped and reachable from nothing. The README has a
  documentation index now, and a test keeps it honest.
- The npm README called the package a "scaffold" while its metadata
  advertised a full feature set, and listed eight of the options that existed.

### Performance

- The request body is parsed **once** per request, and sniffing its first
  byte no longer copies the whole body.
- The quota monitor checks for a quota header before rebuilding a dict of
  every response header.
- **The committed overhead snapshot is now honest.** It measures **two payload
  sizes** — 94 bytes and 4 KB, because the overhead is body-proportional — and
  it records the host, the OS, the interpreter and the package versions, which
  the previous snapshot did not. The figure is *larger* than the old 0.07 ms,
  and the difference is stated rather than smoothed over: a number nobody can
  reproduce is not a better number for being smaller.

  | Payload | Overhead p50 | Overhead p99 |
  |---|---|---|
  | 94 B | 0.0972 ms | 0.1318 ms |
  | 4096 B | 0.1012 ms | 0.1105 ms |

### Deferred to 0.8.1

Recorded here so they are not lost:

- `AuditLog` on the ledger's `BoundedWriter` — it still does blocking file
  I/O on the request path.
- Streaming ledger reconciliation — a streaming row is still permanently
  `estimated=True`, so streaming spend is systematically under-reported.
- `BackstopState` thread-safety — `_circuits` is still a check-then-act race,
  and `ledger_errors` still under-counts.
- `RedisBudgetBackend.remaining` atomicity, and the `evalsha` `NoScriptError`
  fallback after a Redis restart.
- The framework adapters are still unwired and undocumented.
- `install.sh` still falls back to the GitHub source, and the checksum file is
  still not published — the installer now says so instead of pretending.
- The git history still holds ~185 MB of superseded media. The purge needs a
  force-push, so it is opt-in.
- The npm package is still published by hand: the release workflow now
  publishes it from the tag, but the repository has no `NPM_TOKEN` yet, so
  that step skips with a message rather than failing the release. PyPI and
  the GitHub Release are unaffected.

## 0.7.0 — 2026-09-27

The **spend ledger** build: Backstop can now record what a request actually cost,
attribute it, and export a charge-back. It is opt-in and off by default, and the
one-wrap-call adoption property is unchanged. Also in this release: the
`serve` gateway fixed (it returned HTTP 500 on every request), statement
reconciliation, and nineteen correctness fixes — of which four could lose
money, one could hand a credential to the wrong company, and two could bill
you wrongly without looking wrong.

### Packaging

- **The sdist was shipping things it should not.** It carried a 0-byte file
  named `=0.40` (created by a botched `pip install 'backstop>=0.40'` whose
  `>` was read as a redirect), a 2.5MB animated GIF that this release
  supersedes, 8.5MB of demo video, and `fix_wrapper.py` / `TODO.md` /
  `videos/` / `.github/`. The tarball was 8.6MB; it is now 640KB, and
  `twine check` passes. The code, tests, docs, proofs, `install.sh` and
  `llms.txt` are all still in it.
- **The version lived in three files with nothing keeping them in step** —
  `pyproject.toml`, `backstop.__version__`, and `ts/backstop/package.json` —
  so a release could ship a wheel reporting a different version from the
  installed package, and the npm package could fall arbitrarily far behind
  because publishing it is a separate manual step. `tests/test_version.py`
  now asserts all three agree, that the CHANGELOG has a section for the
  current version, and that the licence text is present and not merely
  declared.

### Added

- **Spend ledger (opt-in, `ledger_enabled=True`).** Every completed provider
  request now produces one immutable `SpendEvent` — provider, model, normalised
  endpoint, priority, outcome, the four token counts, latency, retries, your
  attribution, and a `Decimal` cost breakdown. The record is frozen, validated at
  construction (`TypeError` for a wrong type, `ValueError` for a wrong value,
  both naming the field), and round-trips exactly through
  `SpendEvent.from_dict(event.to_dict())`, and a persisted line must carry
  **exactly** the 18 declared fields: an unknown key and a missing key are both
  `ValueError`s naming every offender, so a typo or a truncation cannot reload as
  plausible-looking data. `schema_version` is `"1.0"`, and
  `occurred_at` is fixed-width RFC 3339 UTC, so string order is chronological
  order. Every money value crosses the wire as a **string**: a JSON number would
  come back as a binary float, and an export that loses cents is worse than one
  that is awkward to parse. A credential-shaped query parameter on the endpoint
  is recorded as `?<redacted>` rather than stored.
- **Ambient attribution context.** Declare who is spending money once, at the top
  of the function that spends it: `attribution(team=..., feature=...)` as a
  context manager, `with_attribution(...)` as a decorator on a sync or async
  function, and `current_attribution()` to read it back. All three import from
  `backstop`. Scopes merge — the inner one wins on the fields it sets, an unset
  or blank field never erases the outer one — and the outer value is restored on
  exit including when the body raises. It is a `ContextVar`, so it follows
  `asyncio` tasks and any thread-pool submission that copies context; a bare
  `executor.submit` or `run_in_executor` does not, and `docs/ledger.md` gives the
  `copy_context()` recipe. A process that declares nothing records an all-`None`
  `Attribution`, so **no existing call site has to change.** An unknown field name
  or a non-string value raises `TypeError` at the call rather than being dropped
  from the ledger, and one scope object is single use — re-entering it raises
  `RuntimeError` naming the fix rather than leaking an `AttributeError` out of
  `contextlib`'s internals.
- **Fourteen attribution dimensions**, all optional: `team`, `agent`, `session`,
  `task`, `feature`, `surface`, `customer`, `tenant`, `environment`, `repo`,
  `cost_center`, `gl_code`, `currency`.
- **Ledger sinks and a bounded non-blocking writer.** `LedgerSink` is a
  structural `Protocol` (`write` / `flush` / `close`), so a plain three-method
  object is a sink. `NullSink` (the default when the ledger is off),
  `MemorySink` (a bounded ring, 10,000 by default) and `JsonlSink` (append-only
  NDJSON) ship with it. `BoundedWriter` is the hot-path component: the transport
  calls `submit`, which takes one short lock, appends to a bounded `deque` and
  returns, and one daemon thread moves events to the sink with the lock dropped
  around the sink's own work. The request path never opens a file, never touches a
  socket, and never takes a lock a sink could hold. **Overflow refuses the
  incoming event** and counts it in `dropped_events` rather than buffering without
  limit or silently evicting the oldest. One writer, price catalog and detector
  are built per `BackstopState`, so the CLI, the gateway, the harness and the
  tests wire the same way; with the ledger off the writer wraps a `NullSink` and
  the bundled catalog is not built at all, because a process that will never bill
  anything should not pay to index a price list.
- **Visible shutdown.** `BackstopState.close()` and `Backstop.close(client)`
  close the writer with a bounded join and return a `CloseReport` — `submitted`,
  `written`, `landed`, `dropped_events`, `sink_errors`, `undrained`, `drained`,
  `lost`. Both are idempotent, and an enabled ledger registers its own `atexit`
  hook, held through a weak reference so a finished session does not go on showing
  up as a running one. Before this, nothing in the package closed the ledger: a
  deployment that set `ledger_path` held a file handle and a daemon thread until
  the operating system took them.
- **Price catalog with three-tier precedence** (`backstop.pricing_catalog`, also
  re-exported from `backstop.ledger`). A frozen `PriceEntry` per model in USD per
  million tokens, with `source` and `confidence` on every rate.
  Highest wins: a per-call `price_overrides`, then your catalog file
  (`config.price_catalog_path`, `source="user"`, `confidence="negotiated"`), then
  the bundled list prices. Each layer is searched in full across every name tier
  before the next is consulted. Model names resolve in three documented tiers —
  the exact string, the name with a trailing snapshot marker stripped repeatedly
  (`-2024-08-06`, `-20241022`, `-latest`), then a fixed alias map — so a dated
  OpenAI snapshot, an Anthropic `-latest` alias and `claude-3.5-sonnet` all
  price. `compute_cost` is `Decimal` end to end, quantised to six places with
  `ROUND_HALF_UP`. **An unknown model returns `None` and is never guessed**: the
  event is recorded with `cost=None` and the export counts it in
  `unpriced_requests`, so a missing price is a visible hole rather than a
  confident wrong number. A component the rate card publishes no rate for is
  charged zero *and marked* in `CostBreakdown.priced_components`.
- **Charge-back export and revenue join** (`backstop.ledger.export`).
  `build_chargeback(events, group_by=("team", "feature"))` aggregates into one row
  per group, largest total first, with the honesty columns beside the money:
  `unpriced_requests`, `estimated_requests`, `unpriced_components`,
  `price_source`. An unset group key renders as `(unattributed)`, never a blank
  cell. `write_chargeback_csv` emits RFC 4180, UTF-8, CRLF, money as 2-decimal
  strings, with **no totals row** — a totals line inside a table somebody intends
  to `SUM` is a double count waiting to happen. `revenue_join` emits a second CSV
  keyed on the same group tuple, with a visible `(none)` and a `match` column for
  any group missing on either side; Backstop does not become a revenue system.
- **Three of the six outcomes never reach a ledger, on purpose.**
  `circuit_open`, `budget_denied` and `queue_timeout` describe requests that
  never reached a provider, so they have no usage report and no dollars; a row
  for one would carry a pre-flight floor for spend that never happened and would
  push that floor into the detector's window, contaminating the ratios the
  detectors exist to measure. They stay in the schema's vocabulary so a durable
  line from a future build still validates. **Spend *avoided* is not in the
  ledger** — it is on the enforcement surface where it already was
  (`budget_exceeded` / `rate_limited` counters, the
  `requests{outcome=circuit_open|exception}` breakdown, the audit log's `deny`
  records).
- **`backstop ledger demo|show|export`.** `demo` is keyless, offline, needs no
  file, and is deterministic to the dollar from fixed synthetic traffic priced
  against the bundled card — one model in it is deliberately absent from the rate
  card, so its 34 requests are counted and their dollars are absent. `show`
  reports a JSONL ledger's integrity *before* its charge-back, so a reader who
  only looks at the total cannot miss a lost line, and states `dropped_events` /
  `sink_errors` as **unknown with the reason** rather than as `0`. `export`
  writes the CSV. Both fail loudly on a corrupt non-final line — naming the line
  number, exiting 1, and writing nothing.
- **Runaway-spend detection with shadow mode** (`backstop.detection`,
  `detection_enabled=True`). Four detectors over a bounded window of the last
  `detection_window_size` events **per attribution key**: velocity (priced spend
  per minute), drift (tokens-per-request over the recent half against the older
  half), retry amplification, and context growth. Each fires a frozen
  `DetectionSignal` carrying `kind`, `severity`, `key`, `observed`, `threshold`,
  `detail` and `occurred_at`. The window is keyed by the frozen `Attribution`
  itself, so per-key isolation cannot be got wrong, and both the per-key window
  and the number of keys (`detection_max_keys`, default 1,024) are bounded by
  construction — the bound matters most for a deployment attributing per session,
  which would otherwise hold one window per request for the life of the process.
  Eviction is least-recently-used and **counted**: a silently evicted key is a
  key whose baseline silently restarts, and a detector that has forgotten looks
  exactly like a healthy one. A threshold that would make a detector quietly
  useless is a construction error, not a runtime surprise — a negative or
  non-finite threshold, a `baseline_multiplier` below 1.0 (which inverts the
  comparison rather than alerting earlier), a non-positive window, and
  `min_samples > window_size`, which is a detector that can never speak and looks
  exactly like a healthy one.
  **`detection_shadow=True` is the default**: the same signals are produced and
  filed in a bounded log with a per-kind counter, so a threshold can be tuned
  against evidence before it can interrupt anybody. `BACKSTOP_DETECTION_SHADOW`
  overrides the config in both directions. Signals reach the existing `Metrics`
  object as a counter labelled by (detector kind, severity) and a histogram of
  the observed value; before this they were computed and then read by nothing, so
  a breach in production was indistinguishable from a detector that never fired.
- **New `BackstopConfig` fields**, all defaulted so every existing
  `BackstopConfig()` is unchanged and no call site has to be edited:
  `ledger_enabled=False`, `ledger_path=None`, `ledger_memory_events=10_000`,
  `price_catalog_path=None`, `detection_enabled=False`,
  `detection_shadow=True`, plus `detection_velocity_threshold_usd_per_min`,
  `detection_baseline_multiplier`, `detection_retry_ratio_threshold`,
  `detection_context_growth_threshold`, `detection_window_size`,
  `detection_min_samples` and `detection_max_keys` — every detection threshold is
  reachable from configuration, because a threshold that cannot be changed is a
  threshold nobody can tune, and tuning against a shadow log is the whole purpose
  of shadow mode. `price_catalog_path` is checked for existence at construction,
  so a typo fails at `wrap()` rather than silently pricing every event from the
  bundled table.

- **Statement reconciliation (`backstop reconcile`).** The ledger's cost is
  computed from Backstop's own token counts and a rate card; a provider's
  statement is computed from the provider's counts and the provider's own rates.
  Nothing previously compared the two, so a CFO had no way to check the
  charge-back against the invoice that actually arrived. `reconcile_invoice`
  returns a per-model and total variance as signed `Decimal`, the token counts
  on each side and their delta so a difference can be attributed to a price or a
  count, and a status of `matched`, `within_tolerance`, `variance`,
  `missing_from_ledger` (the provider billed for something Backstop never
  recorded) or `missing_from_invoice`. `measure_error_budget` reports the
  observed variance over the invoices it was given, and says plainly that this is
  an empirical figure over that population rather than a promise about anyone
  else's account. `parse_invoice_csv` / `parse_invoice_json` read a statement
  file; a header that does not match raises naming the row, the field and the
  accepted spellings rather than quietly reconciling nothing. A model the
  catalog has no rate for is reported as unpriced and is **never** priced at a
  default — a missing price stays visible instead of becoming a plausible
  number, and a row present on one side only is never netted against the other.
  Money is `Decimal` throughout. `reconciliation_csv` writes the per-model rows
  as RFC 4180 for finance to join against the charge-back export.

  **Scope, stated plainly:** this reconciles against a *statement file*, and this
  repository has never run one against a real provider statement. No statement
  from either provider is committed here and no live smoke test is wired to one.
  The column names the CSV parser reads are transcribed from the providers'
  published reporting surfaces, centralised in one marked block for that reason,
  and marked as needing verification against a real statement. `--demo` is
  offline, keyless and deterministic, and every row of it differs on purpose —
  a demo where everything reconciles would teach a reader nothing.

### Fixed

Each of these is the observable symptom, not the internal cause.

- **`backstop serve` returned HTTP 500 on every request.** The gateway read a
  local `key` that was assigned only inside `if api_keys is not None`, so with
  auth disabled — the default, and the configuration the docs lead with — every
  request raised `NameError`. The gateway has never worked as shipped. A
  security suite now runs it against a live local upstream rather than a mock,
  because a mock cannot catch an unbound local or a body that was never read;
  the existing `test_gateway_proxies_through_backstop` had been failing and
  invisible, because the whole module was skipped everywhere.
- **`uvicorn` was imported by `serve` and declared by no extra**, so
  `pip install "backstop[fastapi]" && backstop serve` raised
  `ModuleNotFoundError`. It is now declared, and `fastapi` is in the test extra
  so the gateway tests actually run.
- **A hung provider held a gateway request open forever.** There was no
  upstream deadline, so one slow provider could exhaust the worker's
  concurrency. There is now a configurable one, carried in
  `request.extensions` because httpx 0.28 accepts a timeout on neither the
  transport nor the request constructor.
- **The gateway relayed hop-by-hop headers in both directions**, letting a client
  inject `Connection`, `Upgrade`, `Transfer-Encoding` or `Proxy-Authorization`
  at the provider. RFC 7230 §6.1 headers, plus `content-length` and
  `content-encoding` (which describe the body as it arrived inbound, not as
  httpx re-serialises it), are now stripped in both directions.
- **A gateway 502 echoed `str(exc)` to the client**, handing out internal
  hostnames, ports and tracebacks. The detail is logged; the client gets a fixed
  body.
- **The gateway's 1 MB body cap did not bound memory,** because the body was
  read in full before being measured. `Content-Length` is now checked before
  buffering, and the buffered length re-checked, since a client may lie about or
  omit it.

- **Virtual keys never resolved to a provider secret.** `BackstopConfig` is a
  frozen dataclass, so the `self.secret_provider = SecretProviderChain(...)`
  assignment in `__post_init__` raised `FrozenInstanceError` and a bare
  `except Exception: pass` swallowed it. The documented default chain was
  therefore never installed for anyone: a deployment using `virtual_keys` sent
  the virtual key name upstream while believing it had per-tenant credentials,
  so its per-customer chargeback was built on a fiction. The default is now
  installed (and only when `virtual_keys` is configured, since there is nothing
  to resolve otherwise), and the header is rewritten to the resolved secret.
- **A wrapped client could silently lose the SDK's own transport
  configuration.** Reuse was decided with `isinstance(transport, httpx.BaseTransport)`,
  and that name is not stable: an installed SDK (`anthropic` 0.116.0) rebinds
  `httpx.BaseTransport` to its own class at import time. On a miss, backstop
  replaced the SDK's transport, discarding its proxy, TLS and connection-pool
  settings with it. Reuse is now duck-typed on `handle_request` /
  `handle_async_request`.
- **`ts/backstop` threw `ReferenceError` for any file-path audit sink.** The
  published package is declared `"type": "module"` but called
  `require("node:fs")` in its audit sink. `require` is not defined in an ES
  module, so constructing a sink with a file path failed immediately. Now a
  static import, with a test that writes to a real temporary file.
- **`tests/test_doctor.py` failed on every CI matrix job** while passing
  locally. It simulated a missing `httpx2` by reloading a module and asserted
  in a docstring that only the CLI would notice; the Anthropic wrap path
  resolves the same module. The state it simulated is also impossible in
  practice, since an SDK requiring `httpx2` cannot be installed without it. It
  now asserts the real contract, and exercises the absent case in a subprocess so
  no module state is shared.
- **A test named for an invariant never checked it.**
  `test_budget_spent_plus_reserved_never_exceeds_total` built a `violations`
  list under a lock and then asserted nothing about it. It now samples the
  invariant from a concurrent reader and fails if the ceiling is breached.
- **`backstop.budgets` could point at a discarded ledger.** It was bound once at
  import time, so after `reset_ledger()` the package attribute still referenced
  the old instance and a tenant registered through it was invisible to the
  transport. It is now resolved on every access.
- **`backstop verify --live --provider anthropic` sent your OpenAI API key to
  Anthropic.** The live probe read `OPENAI_API_KEY` regardless of the selected
  provider. The default key env var is now resolved from the provider
  (`openai` → `OPENAI_API_KEY`, `anthropic` → `ANTHROPIC_API_KEY`), an unknown
  provider raises instead of falling back to the OpenAI key, and an explicit
  `--api-key-env` still wins.
- **The Anthropic live probe sent `Authorization: Bearer` where Anthropic expects
  `x-api-key`**, so `--live --provider anthropic` returned 401 even with a valid
  key. The probe now sends the provider-correct header shape: `Bearer` for
  OpenAI, `x-api-key` + a pinned `anthropic-version` for Anthropic.
- **`--base-url` sent your provider credential to a foreign host with no
  warning.** The flag is real and still works; the probe now prints a warning to
  stderr naming the provider, the host and what is being sent whenever the base
  URL's host differs from that provider's default. The default host is silent.
- **A request that timed out in the priority queue left its ticket behind and
  permanently blocked that priority.** A single timeout was enough: the stale
  ticket stayed at the head of its deque and every later acquirer at that
  priority timed out forever. A survivor queued behind a discarded ticket also
  slept on for a full 250 ms, and never woke at all with the default
  `queue_timeout=None`.
- **A successful streaming response could leave the circuit breaker stuck in
  half-open**, so every subsequent request was rejected with
  `CircuitBreakerOpenError` indefinitely. Both transports now record the circuit
  outcome at stream setup, matching the non-streaming path.
- **Async clients skipped rate limiting, agent guardrails and shadow policy.**
  The async transport defined the pre-admission checks and never called them, so
  `rate_limiter`, `agent_guard` and `shadow_policy` were silently unenforced for
  `AsyncOpenAI` / `AsyncAnthropic` users.
- **Async budget reconciliation did blocking Redis I/O on the event loop.** Both
  transports called the synchronous `Budget.reconcile` from the async path, so a
  shared `redis`-backed budget blocked the loop; `Budget.areconcile` was dead
  code. The async path now awaits it, and the in-memory backend no longer pays a
  `to_thread` hop to do three integer operations.
- **A pre-admission denial permanently stranded the budget reservation.** A
  guardrail or rate-limit rejection left the reservation taken: `reserved=50,
  spent=0` after one denial, climbing by 50 on every subsequent denial until the
  budget was exhausted. A rejected request now costs nothing.
- **`backstop doctor` exited 1 on a base install** because its wrap smoke test
  required `httpx2`, which is not a declared dependency and only arrives
  transitively with newer `openai` / `anthropic` majors. It now reports
  `httpx2 not installed; the SDKs in use are on the httpx family` and continues.
- **`backstop verify --live --offline` performed a live network call anyway.**
  `--offline` was accepted but inert — the runner only ever read `--live` — so a
  user who explicitly asked for no network still dialled out. `--live` and
  `--offline` are now mutually exclusive (exit 2).
- **`backstop_budget_remaining_tokens` reported the global budget instead of the
  tenant a virtual key resolved to.** Per-tenant dashboards showed a plausible,
  moving number describing a budget none of their requests were spending.
  Both transports now publish the tenant they actually resolved.
- **OpenAI cached prompt tokens were silently dropped from billing.** Nothing
  read `usage.prompt_tokens_details.cached_tokens`, so a response with 400,000
  cached prompt tokens of 1,234,567 was charged the full input rate on all of
  them — 3.091418 instead of 2.591418, a 14.3% overcharge, with
  `estimated=False` claiming a measurement. The split is now read for both
  providers, and `input_tokens` means the fresh, non-cached count in both.
- **A tight process-global `decimal` context silently produced an empty
  ledger.** A host application that narrowed `prec` — which accounting code does
  — made `quantize` raise `InvalidOperation` on every event: the request still
  returned 200, nothing was recorded, and no wrong money appeared. Every cost and
  every total now runs under the ledger's own context, 28 significant digits with
  every field named, so the ambient `prec` / `rounding` / `traps` / `Emax` are
  never read.
- **A sink that swallowed its own write failure was reported on close as having
  lost nothing.** 50 events into a `JsonlSink` whose path could never be opened
  closed as `submitted=50 written=50 dropped=0 sink_errors=0` for a file that
  received zero records. `CloseReport` now carries `sink_reported_errors`,
  `sink_degraded` and a `landed` property, and the shutdown and live paths compute
  `lost` through one shared function so they cannot disagree.
- **`examples/background_priority.py` claimed background requests are shed when
  they are queued.** `PriorityGate` does not shed: it queues and prioritises, and
  starvation protection can admit an aged lower-priority ticket ahead of a
  waiting higher-priority one. Docstring only; the example's code is unchanged.
- **`@with_attribution` on a deferred function left the ledger silently
  unattributed.** Decorating a generator function, an async generator function,
  or a plain function that returned a coroutine or generator entered the scope,
  handed back an object whose work had not started, and restored the scope
  immediately — so every event was recorded with an empty attribution and nothing
  was raised. All three are now refused loudly with `TypeError` naming the
  callable, and the docstring's recipe scopes the deferred body instead. An
  `asyncio.Future`/`Task` still passes, because that work *was* scheduled inside
  the scope.
- **A detection signal printed a dollar rate with a wrong sixth decimal.** The
  velocity detail rendered a float with `:.6f`, the catalog's money precision,
  where the arithmetic has six digits at best: three events of $12.345670 across
  exactly 3,600 seconds are $0.6172835/min, and the float's sixth place printed
  `0.617283`. Rates are now rendered at two places like every other dollar here;
  the exact float is still on the signal as `observed`.
- **`estimated_requests` counted only the priced requests**, while
  `unpriced_requests` counted every one — two honesty columns with two different
  denominators, which is the mistake those columns exist to prevent. Both now
  count over the same population and may overlap: an estimated request on a model
  with no published rate is in each, and its dollars are absent rather than a
  floor.
- **Re-reading a stored ledger line lost the record that a credential had been
  there.** The endpoint was re-normalised on the way back in and the second pass
  stripped the `?<redacted>` marker, so a line read and written again was not
  byte-stable. Separately, normalising a URL that reduces to nothing (`"?"`,
  `"#frag"`) produced an empty endpoint — a value its own validator rejects.
  Normalisation is now a fixed point, and an endpoint that reduces away becomes
  the literal `unknown`.

### Changed

- **The transport is no longer bound to one HTTP library.** `BackstopTransport`
  and `AsyncBackstopTransport` inherited from `httpx.BaseTransport` /
  `httpx.AsyncBaseTransport` while the rest of the transport is
  family-agnostic, so the class was wrong for an `httpx2`-based SDK, and could
  not be pinned reliably at all because an installed SDK rebinds
  `httpx.BaseTransport` on import. Both now implement the duck-typed interface
  (plus the context-manager protocol `httpx`'s clients require). This was
  latent rather than active — the SDKs duck-type transports, so it worked — but
  it depended on a third-party package not mutating a shared namespace.

- **Custom dashboard hardened (visual audit follow-up).** Fixed the topbar
  collision between the mode badge and wordmark at phone widths (≤640px: the
  brand row now wraps onto its own line); fixed keyboard focus being dropped to
  `<body>` on every table re-render (row focus is restored across polls); grew
  the refresh control and badges to comfortable touch-target sizes under
  `pointer: coarse`.
- **Dashboard theme control.** `backstop dashboard --theme auto|dark|light` sets
  the initial theme (default `auto` follows the OS), and a new **theme** button
  in the topbar cycles auto → dark → light per browser, persisted in
  `localStorage`.
- **Grafana export removed.** `backstop.dashboard` (the JSON spec module),
  `tests/test_dashboard.py`, and `observability/grafana/` are gone — the built-in
  dashboard is the single custom ops surface. Prometheus metrics and
  `observability/prometheus-alerts.yml` are unchanged.
- The SDK transport Backstop builds is **described accurately**: it is `httpx` or
  `httpx2`, depending on which the wrapped SDK actually uses, because the two are
  mutually incompatible.
- **SDK retries are disabled in favour of Backstop's own.** Wrapping sets the
  wrapped client to `max_retries=0`; the guardrail has to be able to see and stop
  each individual attempt. The SDK's authentication and request-construction
  logic still runs above the transport, which is why Backstop's errors reach your
  code as the provider's own error subclasses.
- **Streamed requests now feed the AIMD controller** at dispatch, beside the
  circuit outcome, rather than only when the stream is consumed.
- **The unattributed share now prints the figures it was computed from.** The
  percentage is computed on the exact six-decimal totals while the dollars beside
  it are displayed cents, so a reader who divided them got a different answer
  (1.54/34.56 is 4.46% against a printed 4.45%). Computing on the exact sums is
  the right convention; not saying so was not. Every renderer that prints the
  percentage now prints the basis with it, and the JSON export carries the exact
  figures.
- **Building a spend event is cheaper.** `uuid4()` spent most of its time
  building a `UUID` object the hex form never needs, and `strftime` spent it
  re-parsing a format string; the id now writes the RFC 4122 version and variant
  nibbles straight into random bytes and the timestamp comes from `isoformat`.
  The attribution field list and the blank test were also rebuilt or reallocated
  on every scope entry and every merge. Measured over 100k iterations: 16.08 →
  11.93 µs for full construction, 12.55 → 9.58 µs for the shape the transport
  uses. Field names, types and defaults are unchanged and the id is still a
  32-character lowercase hex v4 UUID.
- **Internal hardening, no behaviour change.** A charge-back row's group keys are
  now zipped strictly against its grouping, so a row whose keys had drifted
  raises instead of quietly dropping a dimension from `key_dict` and from every
  display built on it — a dropped dimension is an unattributed dollar. The
  detector takes one lock instead of two for the recent-signals read. The
  transport's writer, catalog and detector are built once per state rather than
  per call site, and a memory ring is no longer allocated for a detector that
  nothing can write to.
- `ledger.py` moved into the `backstop.ledger` package, as
  `backstop/ledger/budget.py`. A module and a package of the same name in one
  directory is a packaging hazard — a wheel build ships both and which one wins
  depends on install order. **This is not a breaking import change** for every
  public name: `TenantBudget`, `ReservationTicket`, `BudgetLedger`, `get_ledger`,
  `get_current_tenant`, `with_budget` and `reset_ledger` are all still importable
  from `backstop.ledger` and from `backstop`, resolve to the same live objects as
  before, and the module-level ledger singleton is still shared. What changed is
  where they live: code that reached into the module's *private* attributes
  (`backstop.ledger._ledger`, `backstop.ledger._tenant_var`) must now use
  `backstop.ledger.budget`, and `__module__` on those objects reads
  `backstop.ledger.budget`. `backstop.ledger` is a package, so
  `backstop.ledger.__file__` and `backstop.ledger.__path__` replaced a `__file__`.
- The TypeScript lockfile still names the old package: `ts/backstop/package-lock.json`
  declares `"name": "@ravanish/backstop"` at version `0.5.0` while
  `ts/backstop/package.json` declares `backstop-ai` at `0.6.0`. Untouched on this
  branch; the npm name in the README refers to `package.json`.

### Docs

- **The five demo GIFs are 9x smaller and provably unchanged.** They were
  re-encoded so each frame keeps only the pixels that changed, taking the
  repository from 117 MB to 12.9 MB. The optimisation is only trusted because it
  is proved rather than assumed: the build keeps the full-canvas render and
  decodes both files to compare all 414 frames pixel for pixel, discarding the
  result if a single pixel or any frame/timing gate differs.
- Corrected the risk register so every known-defect row is re-verified against
  the current code and carries a status, rather than being left as a claim that
  has since gone stale.

- **0.6.0 is released.** The `0.6.0 is unreleased` banner is gone from
  `README.md`, `CHANGELOG.md`, `docs/install.md`, `docs/compatibility.md`,
  `install.sh` and `llms.txt`, and is replaced with the accurate framing:
  0.6.0 shipped (PyPI, the `v0.6.0` GitHub Release, npm), and the default branch
  carries unreleased work past that tag. The SDK floor boundary is recorded:
  below `openai>=2.37` / `anthropic>=0.98` the provider SDK catches
  `BudgetExceededError` and re-raises it as `APIConnectionError`, so enforcement
  is invisible to user code.
- **Behavioural claims corrected against the code.** The first README snippet
  caught `BudgetExceededError` without importing it. "Critical passes when normal
  ones are shed" described a priority that does not exist and a behaviour the gate
  does not have: there are three priorities, the gate queues and prioritises, and
  `starvation_after_seconds` is the anti-starvation valve. "Not a proxy" denied the
  shipped `backstop serve` reverse proxy, so the claim is now scoped to the
  default SDK wrap path. "No key management" denied the `virtual_keys` /
  `secret_provider` indirection. The `--offline` flag is documented as inert, and
  `--live` as resolving the key per provider and warning on a foreign
  `--base-url`. The examples table now covers all 13 files and stops
  over-claiming the `# KEYLESS` header convention. `docs/architecture.md` names
  both HTTP families, adds the gateway, and marks the control plane as roadmap
  with no dates. `docs/install.md` and `docs/quickstart.md` no longer route
  readers to `doctor` as a compatibility check, because `doctor` does not send a
  request through the wrapped transport. `docs/concurrency.md` drops an unmeasured
  "~99% of time awaiting the network" claim and stops telling the reader to use
  somebody else's proxy. `docs/threat-model.md` no longer lists `doctor` and Redis
  state as future work. `llms.txt`, which an agent installer reads first, gets the
  same corrections.
- **Benchmark numbers reconciled.** The README claimed ~0.09 ms p50 on a named
  MacBook M1 / openai 3.14 / httpx 0.28 configuration that no artifact in this
  repository records. It now reports the committed snapshot's 0.07 ms at
  p50/p95/p99, states the conditions the snapshot does record (date, seed, mock
  transport, 1,000 requests, no network) and the ones it does not (CPU, OS, Python,
  SDK version), and points at `backstop benchmark` to re-measure. The claim that
  the scenario counts are all deterministic is narrowed to `burst` and
  `steady-state`, which do reproduce; `error-storm` and `budget-hit` turn on
  wall-clock timers and are shown as indicative. CI is documented as running the
  benchmark as a threshold-free smoke test, so a green badge is not a performance
  gate. `docs/sdk-matrix.md` enumerates what the CI matrix does and does not
  cover.
- **New: `docs/ledger.md`**, the user-facing guide to the shipped ledger.
- **Docstrings that promised a mechanism which did not exist were corrected
  rather than built.** `pricing_catalog`'s module and `compute_cost` docstrings
  both told the caller to increment a `price_unknown` counter that was never
  written, in the two places a reader looks for how an unpriced model becomes
  visible. The mechanism that exists is the one the export already has — the
  event is recorded with `cost=None` and `build_chargeback` counts it in
  `unpriced_requests` — and a counter nobody polls would have been a second
  telemetry system. A test now fails if any docstring in the package promises an
  "increments ... counter" again. Two shipped docstring recipes that raised the
  error they were meant to avoid were fixed the same way, by extracting and
  executing the block verbatim in a test.
- **New: eight planning documents** under `docs/planning/`, written against the
  code that ships: `00-current-state-audit.md`, `01-north-star.md`,
  `02-ledger-architecture.md`, `03-attribution-and-schema.md`,
  `04-detection-design.md`, `05-expansion-roadmap.md`, `06-90-day-plan.md` and
  `07-risks-and-killshots.md`.
- **The README's "What It Does Not Do" is updated rather than left contradicting
  the new feature.** It is still true that Backstop is not a hosted control plane
  and not a metrics backend, but it now *does* have durable local storage, so the
  section says so precisely and then lists what is still absent: no cloud, no
  multi-tenancy of the ledger, no forecasting, no cross-customer benchmarks, no
  framework-native attribution, and no enforcement on spend.

## 0.6.0

- Renamed the Python distribution to `backstop-ai`; `import backstop` and the
  `backstop` / `wedge` console commands are unchanged.
- Added repository metadata, Python classifiers, and package keywords; aligned
  package and installer versions at `0.6.0`.
- Corrected install examples and removed unsupported PyPI verification claims.
  Historical install strings below are retained as history, not current guidance;
  see [the install guide](docs/install.md).
- Published. `twine upload` put 0.6.0 on PyPI; a clean virtualenv then resolved
  `backstop-ai[anthropic]` to 0.6.0, with `backstop doctor` and `backstop verify`
  both succeeding. The `v0.6.0` GitHub Release carries the wheel and sdist, and
  `backstop-ai@0.6.0` is on npm (a separate, partial TypeScript port of this
  project, not the Python distribution). Work after this tag is unreleased and
  lands under `## [Unreleased]` below.
- Enforcement-error propagation is bounded rather than open-ended: below the
  declared floors (`openai>=2.37`, `anthropic>=0.98`) the provider SDK catches
  `BudgetExceededError` and re-raises it as `APIConnectionError`, so enforcement
  is invisible to user code. Within the tested range it does not. See
  [docs/compatibility.md](docs/compatibility.md).

## v0.5.0 — 10× Better

Closes the gap between Backstop and proxy gateways (LiteLLM / BricksLLM) while
staying in-process and drop-in. All new infrastructure is opt-in; existing
installs keep their default behavior.

- **Competitive benchmark** — Firecrawl-sourced feature matrix vs LiteLLM /
  BricksLLM and the "10× better" wedge (`docs/competitive-benchmark-2026-07-20.md`).
- **Deep Research: 10× Better** — exhaustive 6-agent Firecrawl synthesis
  (gateways, observability, frameworks, clouds, in-process techniques, risks)
  with a prioritized 13-item roadmap (`docs/deep-research-10x-better-2026-07-20.md`).

- **P0#1 Semantic cache (near-duplicate)** — opt-in pluggable embedder +
  cosine `cache_similarity_threshold`. Exact match stays the zero-cost fast path;
  on a miss, the prompt embedding is compared against cached entries and a
  `>= threshold` match is short-circuited. Biggest single cost lever (50–80%
  savings at typical hit rates) — `BackstopConfig(cache_enabled=True,
  cache_semantic=True, cache_embedder=<callable>, cache_similarity_threshold=0.95)`.
- **P0#2 Fallback chain + priority routing** — the single `fallback_model` is
  promoted to an ordered `fallback_chain` (list of `{model, base_url?}`) walked
  in-process on circuit-open; `fallback_chain_for_priority` gives critical traffic
  its own chain. Also fixes a latent bug where the single-model fallback silently
  no-op'd (`httpx.Request` has no `copy()` in this httpx version).
- **P1 Shared (Redis) budget** — one token budget enforced across processes and
  replicas via atomic Lua scripts. `BackstopConfig(shared_budget=True, redis_url=...)`
  with `pip install "backstop[redis]"`.
- **P2 OpenTelemetry export** — mirrors the Prometheus series to a vendor-neutral
  OTel meter. `BackstopConfig(otel_enabled=True)` with `pip install "backstop[otel]"`.
- **P3 In-process fallback** — retries once against a backup model/deployment when
  the circuit opens, no proxy required. `BackstopConfig(fallback_model=...)`.
- **P4 Wedge semantic diff v2** — token/line-normalized similarity (identifier
  Dice + line ratio) that is format/whitespace/removal-immune; report now carries
  per-runner budget-isolation evidence and a cost estimate.
- **P5 Deterministic benchmarks** — seeded, reproducible `backstop benchmark`
  (seed `0xC0FFEE`) with a `--publish` flag; published results in
  `docs/benchmark-results-2026-07-20.md`.
- **P6 Accurate pricing** — maintained 2026 price table (Claude 4/3.5/3,
  GPT 4.1/4o/o1/o3) with prefix+family resolution and offline-cached
  `refresh_pricing()`.
- **P8 CLI ergonomics** — `backstop doctor` validates install/SDKs/keys and runs a
  wrap smoke test; `backstop benchmark` produces reproducible proof.
- **P7 Doc drift fixes** — README benchmarks, features, and "what this is NOT"
  corrected against current behavior.
- **P9 TypeScript SDK scaffold** — `@ravanish/backstop` mirrors `wrap()` (budget +
  circuit breaker + retry + fallback) for Node.js agents (`ts/backstop`).
- **P10 Concurrency ceiling** — configurable `max_wrap_sessions` soft cap with a
  warning, plus `docs/concurrency.md` guidance on the GIL ceiling and when to use
  a proxy gateway.
- **Housekeeping** — deleted the superseded `docs/research` deep-research dump;
  added `redis`/`otel` install extras.

### 10× Better — roadmap follow-up (this pass)

- **P1#3 Virtual keys + hierarchical budgets** — `virtual_keys` maps an API key
  header (`virtual_key_header`) to a tenant, and `TenantBudget(parent=...)` rolls
  spend up a team/org tree so a child budget can never exceed its parent.
- **P1#4 True per-tenant circuit breaker** — `per_tenant_circuit` keeps a separate
  breaker per tenant (falls back to the global one); failures from one tenant no
  longer trip the breaker for everyone.
- **P1#5 Cloud-quota-aware auto-tuning** — ingests provider `x-ratelimit-*` /
  `anthropic-ratelimit-*` headers and proactively clamps the AIMD concurrency
  limit (`apply_external_decrease`) before 429s hit, instead of reacting to them.
- **P1#6 Framework adapters** — `backstop.adapters` lazily bridges LangChain /
  LlamaIndex callbacks to Backstop's hooks/metrics/tenant scoping so Backstop
  becomes the guardrail *inside* the framework. Framework imports are deferred, so
  importing the module never requires the framework installed.
- **P1#7 Cost forecasting + anomaly detection** — `backstop.forecast` projects
  budget exhaustion from a measured burn rate and flags spend anomalies, turning
  ledger data into an enforcement-triggering signal.
- **P1#12 Pluggable rate limiter + tiktoken pre-estimation** — `rate_limiter`
  accepts any `allow(tokens) -> bool` object (e.g. `TokenBucketLimiter`, a
  variable-cost token bucket charged by estimated tokens); `auto_token_count`
  (opt-in) switches pre-dispatch estimates from the chars/4 heuristic to tiktoken;
  `compress` is a pre-send `callable(body, model) -> body` hook.
- **P2#8 Tamper-evident audit log** — `audit_enabled` writes a chained,
  HMAC-verifiable JSONL of every enforcement decision (`deny` / `fallback` /
  `downgrade` / `shadow`) via `AuditLog.verify()`; the enterprise "escape hatch"
  that makes in-process enforcement audit-ready.
- **P2#9 Secret provider** — `secret_provider` resolves virtual keys / tenant ids
  to provider secrets at call time (env + static ships; cloud vaults implement the
  same interface), avoiding plaintext key handling in-process.
- **P2#10 Gateway / sidecar mode** — `backstop gateway` (`backstop serve`) runs an
  OpenAI-compatible reverse proxy so policy is non-bypassable for non-Python
  services; `pip install "backstop[fastapi]"`.
- **P2#11 Agent guardrails** — `agent_guard` (`AgentGuard`) fences runaway agent
  loops per agent id via sliding-window call/token ceilings.
- **P2#13 Safe rollout: shadow / canary** — `shadow_policy` (`ShadowPolicy` /
  `CanaryRouter`) samples traffic to a candidate config/policy and records
  reason-coded decisions before any hard cutover.

### v0.5.0 — Launch Readiness (2026-08-10)

Production-readiness pass: every claim is now backed by proof, every stale
doc is corrected, and the TypeScript SDK reaches full feature parity.

- **Proof infrastructure** — runnable proof scripts (`proofs/`) demonstrate
  budget exhaustion prevention, multi-agent isolation, real-provider overhead,
  and semantic cache savings against live providers.
- **Wedge fixed** — patch extraction now handles markdown code blocks, `FILE:`
  headers, and multi-line LLM output (was unified-diff-only). Agent loop with
  retry/fix on test failure. Per-runner test timeout.
- **Bundled test fixture** — `wedge-test-fixture/` gives `wedge run task.yaml`
  a real repo to run against out of the box.
- **Docs corrected** — README benchmark table regenerated dynamically (was
  stale), benchmark overhead measured live, version strings unified at `0.5.0`
  across `pyproject.toml`, `wedge/__init__.py`, `install.sh`, and `docs/install.md`.
- **Gateway hardened** — auth (`--api-keys`), per-key rate limiting, 1 MB body
  size guard, path traversal rejection, and error handling.
- **Cost forecasting → enforcement** — `forecast_horizon_seconds` proactively
  tightens AIMD concurrency when burn rate projects exhaustion.
- **Secret provider wired** — virtual keys resolve to provider secrets at call
  time in the transport, not just at wrap time.
- **TypeScript SDK v0.5.0** — full parity: priority admission, AIMD concurrency,
  fallback chains, response cache (exact + semantic), hooks, audit log, agent
  guardrails, quota-aware auto-tuning, cost forecasting, and `shadow/canary`.
- **Concurrent budget stress tests** — 20-thread hammer proves the no-overspend
  invariant. CI matrix tests multiple SDK versions.

## v0.4.0

- Integrated the `wedge` tool directly into the `backstop` codebase as an executable package script (`wedge run task.yaml`).
- **Isolation Harness**: Built per-runner Git worktree simulation and task execution.
- **Diff Engine**: Added `difflib`-based patch similarity scoring (`CONVERGED`, `PARTIAL`, `DIVERGED`).
- **Reporting Engine**: Added terminal summary and Markdown report generation (`wedge_report.md`).
- Fully un-mocked and configured the Anthropic and OpenAI wrapper handlers for production-ready API integration.
- Added Phase 0 trust assets: security policy, contribution guide, code of conduct, public docs, examples, benchmark scaffold, and GitHub templates.

## v0.3.0

- Added per-tenant budget buckets.
- Added cost estimation helpers.
- Added downgrade behavior for exhausted tenant budgets.

## v0.2.0

- Added latency metadata.
- Added streaming handling.
- Added middleware hooks.
- Added request timeout support.
- Added response caching.
- Added token counting improvements.
- Removed dead `priority_weights` behavior.

## v0.1.0

- Added the initial Backstop package.
- Added OpenAI SDK wrapping.
- Added Anthropic SDK compatibility.
- Added budget enforcement, priority admission, AIMD concurrency, retry handling, circuit breaking, metrics, and CLI harness support.
