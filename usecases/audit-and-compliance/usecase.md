# Audit and compliance: prove the spend, admit the gaps

Meridian is a ~1200-person regulated fintech. Two departments are blocking the
same project for two different reasons, and neither is answered by a cost
dashboard. Finance will not sign off on AI spend they cannot reconcile to a GL
code — 1,265 requests, $247.73, and no row that ties to a ledger they can post.
Legal will not approve prompts leaving the host, and will not approve an
enforcement decision they cannot audit after the fact. Backstop's answer is a
chained audit log, no new egress, and an RFC 4180 CSV with the honesty columns
sitting next to the money.

![A terminal session where a compliance engineer turns on an HMAC-chained audit log, traces every outbound byte, admits that the chain proves order rather than authorship, and exports a chargeback CSV grouped by GL code](./demo.gif)

## The situation

Compliance does not ask whether a control works. It asks whether you can
*demonstrate* that the control worked, to somebody who does not trust you and
cannot read your code, using artefacts that survive the question. Three
properties, and they are different:

- **Integrity of the decision log.** A log of enforcement decisions is only
  evidence if editing it is detectable. A JSONL file anyone can rewrite is a
  press release.
- **Egress.** "We don't send your data anywhere" is a claim about a topology. In
  a guardrail library the topology is a real question, because the tempting
  implementation — a proxy — puts every prompt through a component you now
  operate.
- **Reconciliation.** Finance's test is not "is this number right" but "does it
  tie to something I already sign". A total is not a chargeback. A row that
  names a cost centre is.

## What backstop does here

### A tamper-evident decision chain

- `BackstopConfig(audit_enabled=True, audit_sink="audit.jsonl",
  audit_hmac_key=...)`. `BackstopState.create` builds an
  `AuditLog(sink, hmac_key)` when the flag is on; you do not construct it in the
  normal path. The key comes from wherever your secrets come from — it is never
  written to the log.
- Each record carries an HMAC of its own payload **plus the previous record's
  chain hash**: `chain = SHA256(HMAC[key](prev + payload))`, where `prev` is the
  previous record's `_chain` (`src/backstop/audit.py`). Every link covers every
  record before it, so a change anywhere invalidates every hash after it.
- `AuditLog.verify()` replays the chain and returns a bool.
- The decisions the transport actually records are `deny` (with reason
  `budget_exceeded`, `circuit_open`, `rate_limited` or `agent_guardrail`),
  `fallback` (on `circuit_open`) and `downgrade` (on `budget_exceeded`), each
  stamped with `ts`, `decision`, `reason`, `endpoint`, `priority`,
  `estimated_tokens` and `tenant_id`.
- `backstop.audit_sink` extends the same chain with a CloudEvents v1.0.2
  envelope, PII redaction before emit, and NDJSON / BigQuery / S3 / OTel sinks.
  Fire-and-forget callables, so a sink can never break the request path.

### Egress, stated as a topology rather than a promise

- `Backstop.wrap()` **is not a proxy.** It injects a transport into the SDK
  client; the SDK's own HTTP client is what actually sends the request, and no
  network traffic passes through Backstop. `docs/threat-model.md` puts it as a
  trust boundary: `application process → Backstop SDK transport → official
  provider SDK HTTP transport → provider API`.
- The optional `backstop serve --target ...` reverse proxy (the `fastapi` extra)
  **is** a component that sees payloads and holds the upstream credential. That
  is a different deployment with a real network hop, it is not what `wrap()` does,
  and it is not exercised by CI.
- The ledger record has **no content field to leak**. `SpendEvent` is exactly 18
  declared fields — provider, model, normalised endpoint, priority, outcome, four
  token counts, latency, retries, `estimated`, attribution, cost, `request_id` —
  and a persisted line carrying an unknown or missing key is a `ValueError` at
  read time. Every money value crosses the wire as a **string**, so an export
  cannot lose cents to a binary float.
- The `endpoint` is normalised before storage: no query string, no fragment, no
  `user:pass@`, and a credential-shaped query parameter is recorded as
  `?<redacted>` so the reader can see one was there without the value being
  stored.

### A chargeback a controller can tie to a GL code

- `backstop ledger export --path ledger.jsonl --out chargeback.csv --group-by gl_code`.
  RFC 4180, CRLF, UTF-8, money as 2dp strings, stable column order.
- `group_by` is validated against the 13 `Attribution` fields — `team`, `agent`,
  `session`, `task`, `feature`, `surface`, `customer`, `tenant`, `environment`,
  `repo`, `cost_center`, `gl_code`, `currency`. An unknown one is an argparse
  usage error listing the legal dimensions, not a silently dropped column.
- The honesty columns sit **next to** the money, not in a footnote:
  `unpriced_requests`, `estimated_requests`, `unpriced_components`,
  `price_source`, `first_seen`, `last_seen`. An unset group key renders as
  `(unattributed)`, never as a blank cell, because a blank cell is the one thing
  that hides it.
- **There is no totals row in the CSV.** A totals line inside a table somebody
  intends to `SUM` is a double count waiting to happen.
- `revenue_join(rows, revenue_map)` emits a second CSV on the same group tuple
  with `match` naming the case — `both`, `cost_only` or `revenue_only` — and
  `margin_usd` absent unless both sides are present. It never infers or fetches
  revenue; you key your own map.
- Integrity is enforced on read. `backstop ledger show` reports a torn final
  line and keeps reading; an unparseable line anywhere *other* than the end is
  real corruption, so the command names the line number, exits 1, and `export`
  writes nothing. A file read reports `dropped_events` and `sink_errors` as
  **unknown with the reason**, not as `0` — a zero would be a claim about a
  process it cannot see.

## What you see in the demo

- **Cold open** — finance will not sign off on AI spend. Legal will not approve
  prompts leaving the host.
- **Submit** — `backstop ledger export --path ledger.jsonl --out chargeback.csv`:
  reads your own file, no key, no network.
- **Stream** — one `Backstop.wrap()` at the single client construction site,
  `audit_enabled=True`, `audit_sink` plus `audit_hmac_key`, and the key in a
  secret store rather than in the log.
- **The chain** — `Record(deny, budget_exceeded)` with its fields,
  `chain = SHA256(HMAC[k](prev + body))`, `fallback`, `downgrade` and
  `rate_limited`, `agent_guardrail` denials, and `AuditLog.verify(lines)`
  replaying the chain to one bool. Then the line the demo puts on screen:
  *tamper-evident, not tamper-proof*.
- **Egress** — the SDK's own transport still sends; backstop wraps it and does not
  replace it; egress is `api.openai.com` and nothing else; prompt text is not a
  `SpendEvent` field; no proxy, no relay, no key forwarding; and the endpoint is
  normalised before storage.
- **The honest beat** — `ts` is a wall clock with no external anchor; anyone
  holding the key can re-chain the file, so the chain proves order rather than
  authorship; retention is your filesystem, one file per process with no rotation
  and no query layer; and **ledger-to-invoice variance is not built** —
  `backstop ledger show` reads our file, not your invoice. Reconcile it by hand,
  and the gap is documented rather than hidden.
- **Dense resolution** — the export, `--group-by gl_code`, the 13 legal
  dimensions, the `gl_code=6420` row at 1,204 requests / 8.9M tokens / $233.71,
  the `(unattributed)` row at 61 requests / $14.02 that nobody can charge, and
  the absence of a totals row.
- **End card** — 1,204 attributed, 61 unattributed, chain intact at 2,190
  decisions. Prove the spend. Admit the gaps.

## The commands

```bash
pip install "backstop-ai[anthropic]"

# the command in the GIF: our own NDJSON -> an RFC 4180 chargeback
backstop ledger export --path ledger.jsonl --out chargeback.csv --group-by gl_code

# integrity report, then the chargeback. exit 1 on a corrupt non-final line.
backstop ledger show --path ledger.jsonl

# the pitch, keyless and offline
backstop ledger demo

# eight offline mechanism checks, including shadow mode
backstop verify
```

The configuration the demo is describing:

```python
client = Backstop.wrap(
    OpenAI(),
    budget=500_000,
    config=BackstopConfig(
        audit_enabled=True,
        audit_sink="audit.jsonl",           # a path, or any callable(str)
        audit_hmac_key=os.environ["BACKSTOP_AUDIT_KEY"],
        ledger_enabled=True,
        ledger_path="ledger.jsonl",
    ),
)
```

Verify a chain yourself — `AuditLog` lives in its own module, not the top-level
package:

```python
from backstop.audit import AuditLog

log = AuditLog("audit.jsonl", hmac_key=os.environ["BACKSTOP_AUDIT_KEY"])
assert log.verify()
```

## What this does NOT solve

- **The chain is tamper-evident, not tamper-proof.** It proves that the file has
  not been edited since it was written. It does not prove authorship: anyone
  holding `audit_hmac_key` can rewrite a record and re-chain the rest. Keep the
  key in a secret store with its own access log, or the chain is only as
  trustworthy as the key.
- **`ts` is a wall clock.** `AuditLog.record` writes `time.time()` and consults no
  external time source, so the chain gives you *order* and not *time*. If your
  evidence needs a defensible timestamp, anchor it somewhere else yourself.
- **There is no ledger-to-invoice reconciliation.** This is the biggest gap on the
  page. `backstop ledger show` reads our file; it cannot read a provider invoice.
  `docs/planning/07-risks-and-killshots.md` risk 7 names it as the counter-move
  that is **not built** and calls the metric (ledger-to-invoice variance) a
  hypothesis with no mechanism behind it. Until it exists, a controller ties the
  two by hand — and the bundled rate card is a dated snapshot
  (`BUNDLED_EFFECTIVE_FROM = "2026-09-26"`) that nothing detects a change to, so
  if a total drifts from the invoice in one direction only, that is a rate, not a
  token-count bug. Supply your negotiated rates via `price_catalog_path` and they
  outrank the bundled layer.
- **Retention, archival and querying are yours.** One file per process, whatever
  path that process chose, until somebody deletes it. There is no rotation, no
  retention policy and no query layer, and no Backstop service that reads it for
  you. `virtual_keys` and per-tenant budgets are about *enforcement*, not about
  partitioning storage.
- **A file read cannot see the loss counters.** A JSONL line records an event,
  never a counter, so `dropped_events` and `sink_errors` are reported as unknown.
  If you need them, keep the writer in the process and read `state.close()`. And
  note the bounded buffer **refuses** an overflowing event and counts it, rather
  than growing or silently evicting the oldest — so a burst can lose events, by
  design, and `dropped_events` is where you see it.
- **Unwrapped clients bypass the audit log too.** `backstop doctor` reports
  versions and wrap status but explicitly does not scan your codebase for
  unwrapped clients (`docs/threat-model.md`).
- **Gateway mode changes the topology.** If you turn on `backstop serve`, the
  Backstop process *does* see payloads and *does* hold the upstream credential.
  It becomes a component in your trust boundary rather than a library inside it,
  and that is a different statement from the one above.
- **The audit log is not an access log and not a SIEM feed by default.**
  `audit_sink` takes a path or a `callable(str)`; the CloudEvents / BigQuery /
  S3 / OTel sinks in `backstop.audit_sink` exist for that, but the shipped
  default is a local NDJSON file.
- **No data-loss-prevention, no prompt inspection, no content moderation.**
  Backstop does not inspect or moderate prompt content by default, and it does
  not replace provider-side authentication.
- **Not everything in the record is a measurement.** A streaming request is
  recorded at dispatch with `estimated=True` and `output_tokens=0`; a token
  component with no published rate is charged zero *and named* in
  `unpriced_components`. Read `estimated_requests` before you read a total.

## Where to read more

- [`src/backstop/audit.py`](../../src/backstop/audit.py) — the chain
  construction and `verify()`, in 79 lines.
- [`src/backstop/audit_sink.py`](../../src/backstop/audit_sink.py) — the
  CloudEvents envelope, PII redaction, and the concrete sinks.
- [`docs/threat-model.md`](../../docs/threat-model.md) — assets, trust
  boundaries, the default privacy posture, and the gateway caveat.
- [`docs/ledger.md`](../../docs/ledger.md) — the `SpendEvent` schema, the 18
  fields, the endpoint normalisation, the delivery and loss counters, and
  "Known limitations".
- [`docs/planning/07-risks-and-killshots.md`](../../docs/planning/07-risks-and-killshots.md)
  — R7 (numbers wrong for six months), R8 (the dated rate card), R9 (no
  multi-tenancy), and the defects this document does not fix.
- [`docs/planning/01-north-star.md`](../../docs/planning/01-north-star.md) — the
  two-buyer split and the FACT/HYPOTHESIS table, including why the honesty
  columns are columns.
- [`usecases/README.md`](../README.md) — the other use cases.
