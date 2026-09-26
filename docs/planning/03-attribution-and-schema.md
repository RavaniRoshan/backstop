# 03 — Attribution and schema

Branch `feat/ledger-foundation`. Head at time of writing `39cb7f9`.

This document reads the schema **out of the code**, not out of
`docs/planning/_build-plan.md`. The implementation refined the plan in several
places — declaration order, the two-tier outcome vocabulary, the
`priced_components` coverage field — and where the two disagree, the code is
right and the plan is out of date.

The architecture around it is [02-ledger-architecture.md](02-ledger-architecture.md).

---

# Part 1 — The canonical event schema

`SpendEvent` is a `@dataclass(frozen=True)` at
`src/backstop/ledger/schema.py:388-591`. **18 fields**, all required on the
wire, all validated in `__post_init__` (`schema.py:418-508`).

Two things about the shape are not negotiable and are worth stating before the
table. The record is **frozen**: nothing in the ledger mutates an event, a
correction is a new event, and the endpoint is normalised exactly once during
construction (`schema.py:505-508`). And the wire form is a **contract**:
`to_dict` emits the 18 keys in schema order (`schema.py:510-535`) and
`from_dict` requires the payload to carry *exactly* those 18 — an undeclared key
is a `ValueError` naming it, a missing one is a `ValueError` naming it
(`schema.py:548-561`). A typo in a persisted line, or a truncated one, reloads as
an error rather than as plausible-looking data.

## 1.1 The 18 fields

"Cardinality" is the number of distinct values the field takes in a given
deployment, and it is what decides whether the field is safe as a metric label
(Part 1.3).

| # | field | type | required | default | cardinality | where the value comes from |
|---|---|---|:-:|---|---|---|
| 1 | `event_id` | `str` | yes | `new_event_id()` — 32 lowercase hex, v4 UUID written straight from `os.urandom(16)` (`schema.py:133-144`) | **unbounded — one per event** | never passed; `field(default_factory=...)` |
| 2 | `occurred_at` | `str` | yes | `utc_now()` — `2026-09-25T14:03:11.123456Z`, fixed-width RFC 3339 UTC, six fractional digits (`schema.py:116-126`) | **unbounded** (microsecond resolution) | never passed; construction time, `datetime.now(timezone.utc)` |
| 3 | `schema_version` | `str` | yes | literal `"1.0"` (`schema.py:51`) | **exactly 1** | never passed; validated to equal `SCHEMA_VERSION` |
| 4 | `provider` | `str` | yes | — (must be non-blank) | **3 today**: `openai`, `anthropic`, `unknown` | `transports.py:61-72`, `_provider_for_host`: domain-suffix match on `request.url.host` against `openai.com` / `anthropic.com`; anything else is `UNKNOWN_PROVIDER` (`transports.py:53`) |
| 5 | `model` | `str` | yes | — (must be non-blank) | **~45 bundled + 1 unknown**; unbounded in principle | `transports.py:353-369`, `_model_for`: `usage.model` (the response's own string, which names the build actually billed) else `body["model"]` (a stream, whose body is unread at setup) else `UNKNOWN_MODEL` (`transports.py:58`) |
| 6 | `endpoint` | `str` | yes | — (normalised in `__post_init__`) | **low in practice** — a handful of paths | `transports.py:314` `str(request.url)`, then `normalize_endpoint` (`schema.py:179-211`): query string dropped, fragment dropped, `user:pass@` stripped, a credential-shaped query param recorded as `?<redacted>`, never the value. Idempotent, so a stored line survives re-read. Normalises to `unknown` rather than to blank (`schema.py:160`) |
| 7 | `priority` | `str` | yes | — | **exactly 3** | `meta.priority.value` (`transports.py:317`), from `X-Backstop-Priority`; `PRIORITIES = ("critical", "default", "background")` (`schema.py:52`) |
| 8 | `outcome` | `str` | yes | — | **3 emitted**, 6 declared | `transports.py:226`: `"success"` / `"error"` from `status_code < 400`; `"fallback"` at the two `_try_fallback` sites. `EMITTED_OUTCOMES = ("success", "error", "fallback")` (`schema.py:90`); `OUTCOMES` declares 6 (`schema.py:58-65`) |
| 9 | `input_tokens` | `int` | yes | — (`>= 0`, `bool` refused) | **unbounded** | `transports.py:308` via `_tokens_for` → `response_usage` (`extract.py:168`). **`input_tokens` is the FRESH, non-cached input** (`extract.py:94-99`) — the count a price card charges at the full input rate, and nothing else |
| 10 | `output_tokens` | `int` | yes | — (`>= 0`) | **unbounded** | the provider's own split; **0** when the provider published no split |
| 11 | `cache_read_tokens` | `int` | no | `0` | **unbounded** | Anthropic `cache_read_input_tokens` (flat, additive); OpenAI `usage.prompt_tokens_details.cached_tokens` (nested, a *subset* — subtracted, not added). See Part 4.2 |
| 12 | `cache_write_tokens` | `int` | no | `0` | **unbounded** | Anthropic `cache_creation_input_tokens`. OpenAI publishes no such count in the reader today |
| 13 | `latency_ms` | `float` | no | `0.0` (`>= 0.0`, finite, `bool` refused) | **unbounded** | `transports.py:321`, `time.monotonic() - tracker.created_at`. Read at the insertion point, so it is slightly larger than `_backstop_meta.total_latency_ms` because the tracker is not yet closed |
| 14 | `retries` | `int` | no | `0` (`>= 0`) | **low** | `transports.py:322`, `tracker.retry_count`, set from `self._retry_count` one line above the branch |
| 15 | `estimated` | `bool` | yes | — | **exactly 2** | `transports.py:323` via `_tokens_for` (`transports.py:372-399`). **`True` means the token counts are a local floor, not a provider measurement** — an aggregate-only body, a body with no usage, or every streaming request |
| 16 | `attribution` | `Attribution` | yes | — (must be an `Attribution`) | see 1.2 | `transports.py:324`, `current_attribution()` — the ambient `ContextVar` |
| 17 | `cost` | `CostBreakdown \| None` | no | `None` | bounded: 9 `Decimal` fields + `priced_components` | `transports.py:328` `compute_cost(event, state.prices)`, filled in place with `object.__setattr__` (`transports.py:339`) — **`dataclasses.replace` measured 7.0 us against 0.18 us for this**, and it would re-run `__post_init__` on thirteen fields to set one (`transports.py:331-338`) |
| 18 | `request_id` | `str \| None` | no | `None` | **unbounded** — one per request | `transports.py:402-414`, `x-request-id` (OpenAI) or `request-id` (Anthropic) off the response. This is the field that joins a chargeback row to a provider dashboard |

### What the implementation changed relative to the plan

| | plan (`_build-plan.md:172-191`) | shipped | why |
|---|---|---|---|
| field order | plan table order | **dataclass order differs** — `provider…attribution` first (no defaults), then `event_id`…`request_id` | Python requires non-default fields before defaulted ones. The plan's order is preserved in `to_dict()`, which is the order that matters for the wire (`schema.py:516-535`) |
| outcomes | 6 | 6 declared, **3 emitted** | a budget-denied, queue-timed-out or circuit-open request **never reached a provider**, so it has no usage report and no dollars. Recording one would put a zero-cost row into a charge-back whose token counts could only be the local pre-flight estimate, and would feed that floor into the detector's window, contaminating the drift and context-growth ratios the four detectors exist to measure. Spend *avoided* is already visible on the metric surface (`budget_exceeded` / `rate_limited` counters, `requests{outcome=circuit_open\|exception}`) and in the audit log's `deny` records — a second system counting the same events differently would be worse. Full reasoning at `schema.py:67-89` |
| validation | non-negative counts, non-negative latency, known priority, known outcome | all of that **plus full type checking on all 18 fields** | `Attribution(team=1)` used to construct and then raise a bare `AttributeError` out of `keys()`. 13 fields x 5 bad values pinned (`task-3-report.md:839-850`) |
| `endpoint` | "normalised, no query string, no api-key" | normalised **at construction, once, idempotently** | three review rounds: it was documented and not done (`222d221`), then not idempotent so the wire round trip broke for any endpoint with a query (`a228fcf`), and it could produce a blank the validator rejects (`UNKNOWN_ENDPOINT = "unknown"`, `schema.py:160`) |

## 1.2 `Attribution` — 13 fields

`src/backstop/ledger/schema.py:229-332`. Every field is `str | None`, every
default `None`, so an un-attributed request is a valid all-`None` record and
**no existing call site has to be rewritten** (`schema.py:230-236`).

| field | cardinality in the demo window | note |
|---|---|---|
| `team` | 4 values + unset | a finance grouping dimension, so bounded by the org chart |
| `agent` | unset in the demo | the natural handle on an agent identity |
| `session` | unset | **high cardinality** — one per conversation |
| `task` | unset | **high cardinality** — one per unit of work |
| `feature` | 5 values + unset | a product surface, so low |
| `surface` | unset | the channel, e.g. web vs mobile |
| `customer` | unset in the demo | an **end customer**, which is the dimension that joins to revenue |
| `tenant` | unset | the multi-tenant id, distinct from `customer` |
| `environment` | unset | dev/staging/prod |
| `repo` | unset | **unbounded in practice** — one per repository |
| `cost_center` | unset | a GL dimension |
| `gl_code` | unset | a GL dimension, small closed set in a real finance org |
| `currency` | unset | **note the collision**: this is an attribution-dimension slot for a caller's revenue currency, and it is *not* the currency the cost was billed in. `CostBreakdown.currency` is `"USD"` and is validated to be (`pricing_catalog.py:747-753`). Two different currencies in one record under two different names is a footgun a reader will get wrong; see Part 6.3 |

Two behaviours that are easy to get wrong and are pinned by tests:

- **A field counts as set only when it is a non-blank string.** `None`, `""` and
  all-whitespace are unset (`schema.py:107-113`). So an environment variable that
  arrives empty cannot erase the value an outer scope set — which it did, before
  commit `0ee8435` (`task-3-report.md:613-624`).
- **The record answers like a mapping.** `keys()`, `__iter__`, `__contains__`
  and `__getitem__` are all defined over the *set* fields
  (`schema.py:280-315`), so `dict(record)`, `"team" in record` and
  `fn(**record)` all do the obvious thing. A known-but-unset field reads as
  `None` rather than raising `KeyError`, so `in`, `keys()` and `[]` agree on
  what is set. Verified just now:
  `Attribution(team='payments', customer='acme').keys()` ->
  `{'team': 'payments', 'customer': 'acme'}`; `['feature']` -> `None`.

## 1.3 The cardinality rule, and which fields are safe as Prometheus labels

The rule is in the repository, and it is stated as a rule rather than as a list
(`src/backstop/metrics.py:10-17`):

> **The label rule, because it is the one that bites:** a label is a fixed,
> bounded vocabulary, never a user-supplied string. `endpoint`/`priority`/
> `outcome` and `kind`/`severity` are drawn from closed sets the code declares;
> the attribution a runaway detector fired on is *not*, because a per-team or
> per-session label multiplies the time series by the number of teams or
> sessions — a cardinality explosion in the scrape, and a user identifier in a
> label is a user identifier in everyone's monitoring storage. The offending key
> belongs in the detector's own bounded ring and in the log line, not in a
> label.

`docs/threat-model.md:54-61` states the same risk from the security side:
*"High-cardinality labels or raw user-provided strings can leak sensitive
information."*

**The rule is already applied to the detector.** `DetectionSignalSink.record`
emits two instruments with two closed-set labels, `kind` and `severity`, and
`evicted(key: Attribution)` **accepts the key and ignores it** — the counter
exists, the tenant is not in it (`state.py:50-69`). The module docstring says
the consequence in one line: *"a process watching ten thousand sessions produces
the same four-by-three series as one watching ten."*

### Applied to the event schema

| verdict | fields | why |
|---|---|---|
| **SAFE as a label** | `provider` (3), `priority` (3), `outcome` (3), `estimated` (2), `schema_version` (1), `currency` (from `CostBreakdown`, 1) | every one is a closed set the code declares, or a boolean. `cost.price_source` is a closed set of 3 (`pricing_catalog.py:162`) — also safe |
| **CONDITIONALLY safe** | `model` (45 in the bundled card, +`unknown`), `endpoint` (a handful of paths), `retries` (small ints in practice) | bounded *for a well-behaved deployment on the bundled rate card*. `model` grows without bound as a deployment's fleet grows, and `endpoint` grows with a per-tenant `base_url`. They pass the rule today and would fail it after a refactor. Note the existing metric surface already labels `backstop_requests_total` on `endpoint` (`metrics.py:63-67`), so the repo has accepted this risk once and named it |
| **NOT safe as a label** | `event_id`, `occurred_at`, `request_id` | one per event. Any of them is a unique-value label, which is the cardinality explosion the rule names |
| **NOT safe as a label** | `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `latency_ms`, all nine `cost` amounts | continuous. These are **histogram observations and gauge values, not dimensions** |
| **NOT safe as a label** | **all 13 `Attribution` fields**, without exception | every one is a user-supplied string. `team` looks bounded and is, per org chart — but nothing in the code enforces that, `session` and `task` are one-per-conversation and one-per-task by construction, and `repo` is one per repository. The rule is about the *source* of the value, not its current size: a label that is bounded today and unbounded after a refactor is a scrape outage, and the repo has already been bitten by the "bounded by luck" version of this (the detection key count growing with the request count, `c156d58`) |

**The consequence for a hosted collector**, which is the shape recommended in
[02](02-ledger-architecture.md): an OTLP span carries attributes, not labels, and
the cardinality rule above is about *metric* dimensions. The rule as written
still applies to any bridge that aggregates, because the collector's
time-series backend will do to a `session` dimension exactly what Prometheus
does. The honest design is: **attributes on the span, aggregation keys in the
collector, never a metric label derived from a user string.** `signal_key`
(`detector.py:141-167`) is the model to copy — it percent-encodes every value with
`safe=''` so `team="a|b=c"` cannot forge another attribution's key, and an
all-`None` attribution files under a named unattributed key rather than the
empty string.

---

# Part 2 — OpenTelemetry GenAI semantic conventions: the decision

## 2.1 The case for adopting them

- **Interoperability.** Every OTel backend already stores `gen_ai.*` spans and
  `gen_ai.client.*` metrics. A customer who already has a Grafana with a GenAI
  panel gets Backstop's cost data in the same query as their latency data,
  with no dashboard written.
- **Credibility.** "We follow the standard" is a sentence that survives a
  procurement conversation. "We invented a schema" does not, and 07 risk R5
  (finance refusing to buy from an unknown OSS vendor) is the hardest risk on
  the list.
- **The attribute set is genuinely good.** The current registry
  (`model/gen-ai/registry.yaml`, `open-telemetry/semantic-conventions-genai`,
  fetched today) already has `gen_ai.usage.cache_read.input_tokens` and
  `gen_ai.usage.cache_write.input_tokens` as first-class attributes, with an
  explicit note that they SHOULD be included in `gen_ai.usage.input_tokens`.
  **The thing this repository spent its most expensive bug fixing — the
  two-provider token-convention asymmetry (Part 4.2) — is already a
  first-class concept in the standard.** That is a strong argument.
- **It is nearly free to map onto.** 13 of the 18 fields have a natural target
  (Part 2.3).

## 2.2 The case against

- **Cost attribution has no GenAI equivalent.** The registry has no
  `gen_ai.cost.*`, no `gen_ai.attribution.*`, no `gen_ai.cost_center`, no
  `gen_ai.customer`, no `gen_ai.margin`. The `gen_ai` attribute set is
  *operational*: which model, how many tokens, how long, which tools. The
  ledger's payload is *financial*: which cost centre gets charged, and what
  fraction of an end customer's revenue it consumed. A standard that has no
  field for the number the buyer cares about cannot be the record.
- **The standard's token convention is the opposite of ours, and getting it
  wrong moves real money.** `gen_ai.usage.input_tokens` is documented as
  *"SHOULD include all types of input tokens, including cached tokens"* —
  **inclusive**. `SpendEvent.input_tokens` is **exclusive**: the fresh,
  non-cached count (`extract.py:94-99`). Mapping them 1:1 without summing
  would under-report input by the cache-read count on every request. This is
  exactly the class of bug commit `d291fef` fixed, where reading OpenAI's
  inclusive count as Anthropic's charged 400,000 cached tokens at the full
  input rate and moved a cost from `3.091418` to `2.591418` — **14.3%**. A
  translation layer that gets this wrong is worse than no translation layer.
- **Everything is `stability: development`.** Every attribute in the registry
  carries `stability: development`. The conventions have also **moved
  repositories** — `opentelemetry.io/docs/specs/semconv/gen-ai/` now redirects
  to `open-telemetry/semantic-conventions-genai`, whose schema URL field is
  literally `TODO` at the time of writing. A schema under active restructuring
  is a poor thing to be the canonical record of a finance figure.
- **It is a client-observability convention, not an accounting one.** It
  models a span. The ledger models a *durable, immutable financial record* with
  a wire format that is strict in both directions, a version field, and a
  schema that refuses a line rather than defaulting it. Those are different
  jobs and they want different failure behaviour: an OTel span that is dropped
  by a sampling decision is unremarkable; a ledger line that is dropped is a
  missing dollar.

## 2.3 RULING

**The ledger record is canonical and native. The OTLP bridge is a translation
layer, not a redefinition.**

Reasoning, in the order that decided it:

1. The standard has no field for the thing finance buys. Everything GenAI
   defines is operational; the product's differentiator is coverage and
   attribution. Adopting an operational schema as the *record* would mean the
   differentiator lives in an extension namespace anyway.
2. The mapping is one-to-one for 13 of 18 fields and needs a *documented
   transformation* for the token counts. A standard that needs a correction to
   represent a record correctly is being used, not adopted.
3. Canonical-in-native is cheap and reversible. `SpendEvent.to_dict` already
   exists and is already the contract. A bridge is a pure function from
   `SpendEvent` to a span, unit-testable with no network and no OTel dependency,
   and it can be deleted without touching the record.
4. The counter-argument — credibility and interoperability — is answered by the
   bridge existing at all. A customer does not have to choose.

**The OTLP bridge is NOT shipped.** Verified: `grep -rn "gen_ai" src/` returns
zero matches; there is no OTLP exporter anywhere in `src/backstop/`; the only
`OtelMetrics` class is a *metrics* mirror (`src/backstop/otel.py:7`), and the one
OTLP transport in the tree is `audit_sink.py`'s `VectorAuditSink`, which 00 A2.2
records as unreachable from any product path. The table below is a
**specification for the next deliverable**, not a description of shipped code.

## 2.4 The mapping, field by field

`gen_ai.*` names verified against
`open-telemetry/semantic-conventions-genai@main`, `model/gen-ai/registry.yaml`,
fetched 2026-09-26. Every attribute there is `stability: development`.

| `SpendEvent` field | `gen_ai.*` attribute | transformation | notes |
|---|---|---|---|
| `provider` | `gen_ai.provider.name` | `"openai"` / `"anthropic"` map by identity; **`"unknown"` has no enum member** | the enum is a closed list of 15 providers. A third host needs either a provider-specific value or a `backstop.provider` attribute alongside; it must not be silently dropped. This is the same gap as 07 risk R13 |
| `model` | `gen_ai.response.model` (preferred) **and** `gen_ai.request.model` | the response's model goes to `.response.model`; the request's is not separately recorded by the ledger, so a bridge would set both from `event.model` | the registry distinguishes the two deliberately. The ledger records one value — the response's when it has one (`transports.py:353-369`) — so the bridge cannot be exactly faithful here and should say so |
| `input_tokens` + `cache_read_tokens` + `cache_write_tokens` | `gen_ai.usage.input_tokens` (aggregate), `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_write.input_tokens` | **`gen_ai.usage.input_tokens = input + cache_read + cache_write`.** The three components map individually and unchanged. | **the load-bearing row.** GenAI's input is inclusive; the ledger's is exclusive. A 1:1 copy under-reports. This is the same asymmetry as Part 4.2, and the same 14.3%-class error |
| `output_tokens` | `gen_ai.usage.output_tokens` | identity | — |
| `estimated` | *no target* | — | **the single most important thing GenAI has no field for.** A span cannot say "these token counts are a floor". It must go on a `backstop.*` attribute, and a consumer that reads only `gen_ai.*` will read an estimate as a measurement |
| `endpoint` | `server.address` + `url.path`, or `url.full` | split the normalised endpoint | `url.full` would reintroduce the query string the ledger deliberately dropped (`schema.py:179-211`), so the path form is the right target |
| `priority` | *no target* | — | `backstop.priority` |
| `outcome` | *no target*; the nearest is `error.type` on a failed span | map `error` to `error.type`; `success` and `fallback` have no standard home | `backstop.outcome` |
| `latency_ms` | `gen_ai.client.operation.duration` (histogram, seconds) | `/ 1000` | the span's own duration is authoritative in OTel; the ledger's is a second reading at a slightly later point (`transports.py:321`) |
| `retries` | *no target* | — | `backstop.retries` |
| `attribution.team` … `attribution.gl_code` (12 of 13) | *no target* | — | `backstop.team`, `backstop.feature`, `backstop.customer`, `backstop.cost_center`, … — **this is the whole chargeback payload and none of it is in the standard** |
| `attribution.currency` | *no target* | — | and it is not the billing currency (`Part 6.3`) |
| `cost.total_usd` (as a 6-dp string) | *no target* | — | `backstop.cost.total_usd` — emitted as the **string**, never a float, for the same reason the NDJSON line does (`pricing_catalog.py:786-806`) |
| `cost.price_source` | *no target* | — | `backstop.cost.price_source` — a charge-back that does not say which rate card produced the number is not auditable (`export.py:737-749`) |
| `cost.priced_components` | *no target* | — | `backstop.cost.priced_components` — the coverage field, and a consumer reading only `gen_ai.*` would read a zero cache-write charge as a measurement |
| `cost.estimated_tokens` | *no target* | — | the breakdown's copy of `estimated` (`pricing_catalog.py:741`) |
| `request_id` | `gen_ai.response.id` | identity | the provider's own id |
| `event_id` | the **OTLP trace/span id**, or `backstop.event_id` | the ledger id is a v4 UUID and must survive verbatim, because it is the dedup key for any future sync (02, shape (a)) | do not replace it with the span id |
| `occurred_at` | the span's start time | identity | fixed-width, so it sorts lexicographically (`export.py:287-291`) |
| `schema_version` | *no target* | — | `backstop.schema_version` — a bridge that emits a record a future `from_dict` would refuse is worse than one that does not emit |

**Summary of the mapping: 6 fields map cleanly, 2 need a documented
transformation, 10 have no standard target.** The 10 are the financial half of
the record.

---

# Part 3 — Context propagation

## 3.1 The design

One module-level `ContextVar[Attribution]`, defaulting to an all-`None`
`Attribution` (`src/backstop/ledger/context.py:55-57`). One variable, no other
state. The transport reads it once per request
(`transports.py:324`, `current_attribution()`), so the design has exactly one
producer and one consumer.

## 3.2 The three public API forms

| form | what it is | validation timing | source |
|---|---|---|---|
| `with attribution(**fields):` — context manager | `_AttributionScope`, a hand-written `AbstractContextManager` | **at the `attribution(...)` call**, not at `__enter__` — a typo fails at the call site rather than at the top of the block | `context.py:70-115` |
| `@with_attribution(**fields)` — decorator, sync and async | `functools.wraps` wrapper; the `Attribution` is built **once at decoration time** (so a bad field fails at import) but the **merge is resolved per call** | decoration time | `context.py:158-217` |
| `current_attribution()` — read it back | `_attribution_var.get()` | — | `context.py:60-62` |

```python
from backstop import attribution, with_attribution, current_attribution

# 1. scoped
with attribution(team="payments", feature="checkout-v2", customer="acme"):
    client.chat.completions.create(...)

# 2. decorator, for a function that makes calls
@with_attribution(agent="refund-bot")
def handle_refund(ticket): ...

# 3. read it back
current_attribution().team
```

Two design details worth naming:

- **A scope is single use.** `AbstractContextManager` cannot express that, and
  the `@contextmanager` it stood for answered a re-entry attempt with an
  `AttributeError` out of `contextlib`'s own internals — the author hit exactly
  that while writing a test. A second entry now raises `RuntimeError: an
  attribution scope is single use` (`context.py:83-90`; the review round that
  produced it is `task-3-report.md:648-656`). It is 20 lines against the 8 it
  replaced and it drops the generator indirection.
- **`Attribution` is frozen, and that is a second reason beyond immutability:
  it is used as a dict key** for per-attribution aggregation
  (`schema.py:230-236`).

## 3.3 Nesting

`merge` (`schema.py:261-278`) returns a **new** `Attribution`; neither argument
is mutated. An inner scope wins on the fields it **sets** and inherits the rest,
so nesting accumulates rather than replaces. A field is set when it is a
non-blank string; `None` means "do not override", and so does `""`.

```python
with attribution(team="payments", feature="checkout"):
    assert current_attribution().team == "payments"
    with attribution(feature="refunds", customer="acme"):
        assert current_attribution().keys() == {
            "team": "payments", "feature": "refunds", "customer": "acme"}
    assert current_attribution().keys() == {"team": "payments", "feature": "checkout"}
```

The outer value is restored on exit **including when the body raises** — it is a
`try/finally` around a `Token.reset` (`context.py:93-96`, `:200-201`), pinned by
`test_outer_value_is_restored_when_the_inner_body_raises` and three decorator
twins.

## 3.4 Thread pools: the `copy_context` recipe and the `run_in_executor` caveat

A `ContextVar` follows an `asyncio` task, and it follows a thread **only if the
context is copied**. A bare `executor.submit(fn)` does not copy it, and neither
does `loop.run_in_executor(executor, fn)` (`context.py:27-38`).

```python
import contextvars

ctx = contextvars.copy_context()
loop.run_in_executor(executor, ctx.run, blocking_call, arg)
ctx.run(lambda: some_function())
```

Both halves are tested, and **the "does not copy" half is asserted rather than
assumed**: `test_copy_context_propagates_attribution_into_a_worker_thread` and
`test_run_in_executor_needs_the_copied_context` both show a bare submit and a
bare `run_in_executor` recording an all-`None` `Attribution` while the copied
context carries `team="payments"` (`task-3-report.md:595-599`).

This is not a Backstop bug to fix — it is a Python property to document, and
documenting it with a tested recipe rather than a warning is the whole fix.

## 3.5 Async

`asyncio` tasks copy the context at creation, so a scope is visible inside a
task created within it, and a task's own scope does not leak back to the parent
(`context.py:24-26`; `test_attribution_propagates_into_an_asyncio_task`,
`test_a_task_scope_does_not_leak_back_to_the_parent_task`,
`test_concurrent_tasks_keep_their_own_scopes`). The async decorator wrapper sets
the token before the `await` and resets it in a `finally` on the same task
(`context.py:192-203`), so it restores correctly across suspension points.

## 3.6 The deliberate refusal: generator and coroutine-returning decorated functions

**Refused with a `TypeError` at the earliest moment the shape is provably
deferred.** Three refusals:

| shape | when it is caught | message |
|---|---|---|
| generator function | **decoration time**, `inspect.isgeneratorfunction` (`context.py:183-186`) | `with_attribution cannot decorate generator function 'f': the body would run after the scope had already been restored. Use 'with attribution(...)' in the body.` |
| async generator function | **decoration time**, `inspect.isasyncgenfunction` (`context.py:187-190`) | same shape, "async generator function" |
| a plain function **returning** a coroutine / generator / async generator | **call time**, on the result, inside the wrapper before the token is reset (`context.py:126-155`, `context.py:137-141`) | same shape, naming the returned type |

**Why refuse rather than document.** A generator body has not started when the
wrapper returns. The wrapper resets the token, and the body then runs in the
caller's context with no attribution — every event it produces lands in the
`(unattributed)` row. That is a **silent hole in a charge-back**, and a silent
hole is the one class of defect this product's entire positioning is about
(`01-north-star.md:20-26`). The first implementation's docstring example was
itself a generator function, so following the documentation raised the error it
was meant to prevent; the recipe was replaced and the replacement is `exec`'d
verbatim by a test (`task-3-report.md:827-837`).

Three shapes are deliberately **not** refused, because refusing them would be a
false positive:

- **`asyncio.Future` / `asyncio.Task`** — the work was scheduled *inside* the
  scope and the task copied the context there, so the attribution is already
  correct (`context.py:134-135`; `test_a_scheduled_future_is_allowed_because_its_context_was_copied`).
- **A plain value** such as a `list` — the body *did* run inside the scope.
- **A custom awaitable that is not a coroutine** — not provably deferred.

A refused coroutine or generator is `aclose()`/`close()`d before the `TypeError`,
so the discarded object cannot warn on collection
(`test_a_refused_deferred_body_is_closed_so_it_never_warns` asserts
`inspect.CORO_CLOSED`).

**Residual risk, stated:** a hand-rolled lazy awaitable returned from a decorated
sync function is not caught (`task-3-report.md:676-679`). It is vanishingly
rare, and the alternative — refusing all awaitables — would break the
`asyncio.gather` pattern.

---

# Part 4 — The price catalog

`src/backstop/pricing_catalog.py`, 1,061 lines. Two pricing modules ship in this
repository and they are **not interchangeable** (`pricing_catalog.py:4-17`):
`backstop.pricing` is the demo's float-based *estimator* that falls back to
"the cheapest model in the family" and refreshes itself from a cache file or a
URL; this module is the ledger's *priced* source, `Decimal` end to end, never
substituting a default, and never touching the network.

## 4.1 The three-tier precedence

Highest wins (`pricing_catalog.py:48-61`, implemented `:1049-1061` and
`:521-529`):

| tier | source | `CostBreakdown.price_source` | `PriceEntry.confidence` |
|---|---|---|---|
| 1 | explicit per-call `price_overrides` passed to `compute_cost` | `"override"` | `"negotiated"` |
| 2 | a user catalog file, `config.price_catalog_path` → `PriceCatalog.from_file` | `"user"` | `"negotiated"` |
| 3 | `BUNDLED_PRICES` | `"bundled"` | `"list"` |

`PRICE_SOURCES` is one wider than `SOURCES = ("bundled", "user")`
(`pricing_catalog.py:149-162`) because a per-call override is worth telling
apart from a catalog file: it is the price for *this request*, not the price the
deployment agreed to.

**The resolution order is layer-major, not specificity-major.** Each layer is
searched across *every* model-name normalisation tier before the next layer is
consulted at all (`pricing_catalog.py:521-529`). So a user entry filed under the
family name `gpt-4o` outranks a bundled entry for the exact string
`gpt-4o-2024-08-06`. The reasoning is at `task-4-report.md:82-89`: precedence
is a claim about layers, and making the higher layer win unconditionally is the
rule a reader can check without holding two orderings in their head. Pinned by
`test_no_lower_tier_beats_a_higher_one` (three input amounts
`0.010000 < 0.021000 < 0.030000` in override < user < bundled order) and
`test_the_user_layer_is_searched_across_every_tier_before_the_bundled_one`.

**Model-name normalisation, three tiers** (`model_candidates`,
`pricing_catalog.py:424-467`, `@lru_cache(maxsize=2048)`):

1. the name exactly as given;
2. the name with a trailing snapshot marker removed, repeatedly — `-YYYY-MM-DD`
   (OpenAI), `-YYYYMMDD` (Anthropic), `-latest`;
3. `MODEL_ALIASES[name]` for each name already offered, in the same order
   (ten undated Anthropic family names plus the dotted `claude-3.5-sonnet`
   spellings, `pricing_catalog.py:202-219`).

They compose: `claude-3-5-sonnet-latest` → `claude-3-5-sonnet` →
`claude-3-5-sonnet-20241022`. Tier 2 is a stated claim: a snapshot names a build,
not a price card, and the family publishes one list price for its dated
snapshots. A deployment that prices a specific snapshot differently writes a
catalog file, which is a higher layer and therefore wins.

## 4.2 The bundled table, and its dated-snapshot limitation

`BUNDLED_PRICES` is a `MappingProxyType` over **45** frozen `PriceEntry` values
— **29 openai, 16 anthropic**, counted by import just now. Every entry is
`source="bundled"`, `confidence="list"`, `effective_from="2026-09-26"`
(`BUNDLED_EFFECTIVE_FROM`, `pricing_catalog.py:226`), transcribed from two
published rate pages on that date (`pricing_catalog.py:228-240`).

**Where a provider publishes no rate for a component, the column is `None`,
never `0.00`** — a blank says "not priced", a zero would say "free". OpenAI
lists a cache-write rate only for the gpt-6 and gpt-5.6 families; every other
OpenAI row leaves it unpriced. Claude 3 has left Anthropic's rate card, so its
cache rates are recorded as unpriced rather than carried forward from a
superseded card.

**The limitation, stated plainly: it is a snapshot and nothing detects a rate
change.** `BUNDLED_EFFECTIVE_FROM` is a transcription date, not a claim that a
price has not changed. 07 risk R8 covers this in full. The mitigation is
architectural rather than automatic: the bundled table is the *lowest* tier, so
a user catalog file or a per-call override outranks it, and `confidence` says
plainly that a `user` entry is a rate somebody agreed to rather than a rate on a
public page — which a reader cannot check. **The honest statement is "these
prices were correct on 2026-09-26", not "these prices are current".**

## 4.3 The unknown-price rule, and why guessing is worse than a visible gap

`compute_cost` returns `None` and **never** falls back to a neighbouring model, a
family average, or a default rate (`pricing_catalog.py:1058-1060`,
`:1017-1029`).

The argument is the product's whole thesis. A charge-back that is quietly wrong
is worse than one that is absent, because a wrong number is one nobody can
detect: it reconciles against *something*, it gets approved, and the error
compounds for months. A missing number fails immediately and visibly. This is
the same reasoning as the detection shadow mode and the same reasoning as the
torn-line policy — **every place this codebase could have guessed, it chose a
visible gap instead.**

The gap is made visible at three levels:

| level | what it shows | measured in the demo window |
|---|---|---|
| the event | `cost is None` | 34 of 1,967 |
| the row | `unpriced_requests` count, `total_usd` rendered `0.00`, `price_source` left as `(none)` | `search / vendor-preview`: 34 requests, 8,211 input + 11,300 output tokens, `$0.00`, `unpriced_requests 34` |
| the report | a sentence that the cost is *absent, not zero* | *"every total above understates real spend by an unknown amount"* |

And there is **no separate counter that could drift from the export** — the row
*is* the record. That was itself a fix: two docstrings pointed at a
`price_unknown` counter that did not exist anywhere, and `ddaba66` named the
mechanism that actually exists (`00-current-state-audit.md:197`).

## 4.4 The cache read/write/input/output component model

`COST_COMPONENTS = ("input", "output", "cache_read", "cache_write")`
(`pricing_catalog.py:165`). Four billable components, each with:

- a **token field** on the event: `input_tokens`, `output_tokens`,
  `cache_read_tokens`, `cache_write_tokens` (`pricing_catalog.py:173-178`);
- a **rate field** on the price entry: `input_per_mtok_usd`,
  `output_per_mtok_usd`, `cache_read_per_mtok_usd`, `cache_write_per_mtok_usd`,
  all USD per million tokens (`pricing_catalog.py:167-172`);
- a **money field** on the breakdown: `input_usd`, `output_usd`,
  `cache_read_usd`, `cache_write_usd` (`pricing_catalog.py:179-184`);
- a **coverage marker**: `priced_components: frozenset[str]`
  (`pricing_catalog.py:742`).

`input` and `output` rates are **mandatory** on a `PriceEntry`; the two cache
rates are not. A component outside `priced_components` is charged `0.000000`
**and marked**, and the export reports the marked ones per row as
`unpriced_components`. So a model with no published cache-write rate under-counts
its cache writes and the report says so instead of presenting the zero as a
measurement. Measured in the demo window: **56 requests** on `gpt-4o` carry
`cache_write` tokens against a model with no published cache-write rate (computed
just now from `demo_events()`), and every affected row names the gap.

`priced_components` describes **the price record, not the request**: it does not
change with the token counts, so an empty request and a large one produce the
same coverage for the same model. The alternative — coverage meaning "this
component was billed something" — was rejected because it would make the field
depend on the event and stop answering the question a reader actually has about
the price (`pricing_catalog.py:727-731`).

A component with **zero** tokens and **no** rate is not a gap — nothing was left
uncharged — and does not appear (`export.py:809-813`).

## 4.5 The two-provider token-convention asymmetry

**This is the single most expensive correctness issue in the ledger half**, and
it is worth stating in full because it is exactly the kind of thing an
interop claim would silently re-introduce.

The two providers count cached tokens on **opposite sides** of the number they
call the input, and the arithmetic is not symmetric:

| provider / API | the count | the cached figure | the billable fresh input |
|---|---|---|---|
| Anthropic `/v1/messages` | `input_tokens` — **fresh only** | `cache_read_input_tokens` / `cache_creation_input_tokens` **in addition to** it | `input_tokens`, unchanged |
| OpenAI `/v1/chat/completions` | `prompt_tokens` — **includes** the cached | `prompt_tokens_details.cached_tokens`, a **subset** of it | `prompt_tokens - cached_tokens` |
| OpenAI `/v1/responses` | `input_tokens` — **includes** the cached | `input_tokens_details.cached_tokens`, a **subset** of it | `input_tokens - cached_tokens` |
| Vertex / Gemini | `prompt_token_count` | none published | `prompt_token_count` |

Reading OpenAI's inclusive count as Anthropic's charges cached tokens at the
**full input rate** — an overcharge. Subtracting from Anthropic's bills a
fraction of them twice and drops them out of the reservation. Neither is a
rounding difference; both are the size of the cache.

**The rule takes the inclusion from the KEY the number arrived under, not from
the field's name**, because OpenAI ships the inclusive count under two different
names (`prompt_tokens` on chat completions, `input_tokens` on the Responses API)
while Anthropic's `input_tokens` is the opposite convention under the very same
name. A name-based rule would have been wrong for one of the three rows
(`extract.py:239-256`).

**The convention the ledger states**: `input_tokens` is the **fresh,
non-cached** input — the count a price card charges at the full input rate, and
nothing else. `cache_read_tokens` and `cache_write_tokens` are the counts charged
at their own rates, and `total` is the sum of all four, which is the aggregate
both providers publish. The normalisation is therefore invisible to everything
downstream of it: `input + output + cache_read + cache_write == total` for
every body either provider sends (`extract.py:81-125`).

**The measured size of getting it wrong** (`task-7-report.md:655-663`): a
1,234,567-token prompt with 400,000 cached, on `gpt-4o`, cost `3.091418` before
commit `d291fef` and `2.591418` after — **14.3% lower**. The Anthropic case is
asserted as a regression guard with the same magnitudes and is unchanged at
`3.857451`, because the two cases are the pair: a reader that applied either
convention to both would fail one of them.

## 4.6 The known accuracy limitation, and the proposed fix

**The bundled Anthropic cache-write rate is the 5-minute tier** (1.25x base
input), because the schema has exactly one `cache_write_per_mtok_usd` field and
Anthropic publishes two: 5-minute at 1.25x and 1-hour at 2x. The choice is
stated in the source comment (`pricing_catalog.py:238-240`) and repeated in the
rate table's own header.

**The consequence:** a deployment on a **1-hour cache TTL** is under-counted on
its cache writes — by roughly 37.5% of the cache-write component, since
2.0/1.25 = 1.6. **And nothing in the record reveals it**, which is the part that
makes it a real defect rather than a documented approximation. `priced_components`
cannot help, because the entry *does* carry a write rate — `cache_write` is
present in `priced_components`, so the row looks fully priced. This is
`progress.md:111-112` and `task-4-report.md:441-446` verbatim, and 07 O11.

**The proposed fix, in preference order.** All three are schema changes, so none
is done, and all three are named here so the next task does not have to
rediscover them.

| option | what it costs | what it buys | honest assessment |
|---|---|---|---|
| **(i) record the TTL on the event and the tier in the price entry.** A second `cache_write_1h_per_mtok_usd` on `PriceEntry` and a `cache_write_ttl` on `SpendEvent`, defaulting to `"5m"`. `compute_cost` picks the tier; when the event does not declare a TTL, it uses the 5-minute rate and records the assumption. | +1 field on the entry, +1 on the event, +1 on the breakdown, a `schema_version` bump to `"1.1"`, and a **wire-format change that `from_dict`'s strict key check will refuse on old lines** (`schema.py:556-561`) | exact, and the assumption is stated rather than hidden | **the right answer.** It is also the only one that makes the gap *visible*, which is the whole design principle. The strict-wire cost is real and is the price |
| **(ii) add a `cache_write_tier_assumed` boolean to `CostBreakdown`** and report it in `unpriced_components` | one field, no event change, no version bump if added before 1.0 is consumed anywhere | says "this cache write was billed at the 5-minute tier, and we do not know that is right" | a cheap partial fix. It converts a silent error into a reported one without pretending to solve it. **If (i) is deferred, this should not be** |
| **(iii) infer the TTL from the request body** (`cache_control.ttl`) | no schema change at all | exact for the deployment that sets the TTL explicitly | **rejected**: it requires reading the request body at the ledger call site, which the transport deliberately does not do for the ledger (`transports.py:291-300` records the floor rather than re-reading a body a second time), and it still says nothing about a TTL the SDK sets by default |

Whatever ships, the rule is the one this document's Part 4.3 already states: **a
number that might be wrong must be able to say so.** Option (ii) is the minimum.

---

# Part 5 — Invoice reconciliation

**This is the trust question.** A CFO will not run chargeback off numbers they
cannot reconcile against the provider invoice, and
`01-north-star.md:18` names *"a total they cannot reconcile"* as the thing that
makes the ledger buyer churn. Metric M1 in `01-north-star.md:125` is therefore
the metric that matters, and it is defined as:

> `abs(ledger total - provider invoice total) / invoice total`, per provider,
> per month, **reported alongside `unpriced_requests` and `estimated_requests`,
> never alone.**

## 5.1 What can be reconciled today

| reconcilable | how | evidence it works |
|---|---|---|
| **per-request join to the provider dashboard** | `SpendEvent.request_id` is the provider's own `x-request-id` (OpenAI) or `request-id` (Anthropic) (`transports.py:402-414`). Every event has one when the provider sent one. | a row can be opened on the provider side, and the token counts compared field by field |
| **the arithmetic itself** | `Decimal` at exactly 6 dp under a named 28-digit context; `total_usd` is exactly the sum of the four components by construction, not a rounding artefact; a binary float is refused by name at every boundary; a JSON number is refused on the way back in | `pricing_catalog.py:134-143`, `:996-1004`; the wire form renders money as a **string** so a spreadsheet cannot reinterpret it (`:786-806`) |
| **the report's own internal consistency** | the displayed column adds up by `SUM`; `unrounded_total_usd` sits beside `total_usd`; the unattributed share is computed on the exact totals and `unattributed_share_basis` says so in words, because dividing the printed 1.54 by the printed 34.56 gives 4.46% where the report prints 4.45% | `export.py:541-560`, `:583-601`; the test asserts the disclosure is **necessary**, not merely present |
| **the loss figure, while the process lives** | `DeliveryReport` reads all three loss buckets — the writer's refusals, the errors that escaped the sink, and the errors the sink counted itself — through one shared `lost_events` helper that `CloseReport.lost` also calls, so the live and shutdown paths cannot disagree | `export.py:1618-1696`, `sink.py:86-99`; pinned by asserting the two APIs agree **on every field** |
| **which price produced the number** | `price_source` on every row, `"mixed"` rather than picking one, `(none)` when nothing in the group was priced | `export.py:737-749` |

**The accounting invariant, when the writer is closed and drained:**
`submitted == written + dropped_events + sink_errors`, and separately
`landed == written - sink_reported_errors` (`sink.py:414-436`). The demo's 1,967
events: submitted 1967, written 1967, landed 1967, lost 0, `sink degraded: no`
(run just now).

## 5.2 The residual gap

Stated as a list, because a CFO's actual objection is a list.

| # | gap | magnitude | visible? | source |
|---|---|---|---|---|
| 1 | **The rate card may be stale** | unbounded and silent; a 10% rate change is a 10% M1 | only through M1, which nothing computes yet | `progress.md:111`; 07 R8 |
| 2 | **The 1-hour Anthropic cache-write tier is not representable** | ~37.5% of the cache-write component on affected deployments | **no** — see Part 4.6 | `progress.md:111-112` |
| 3 | **A stream's tokens are a floor** | the entire cost of every streaming deployment is a lower bound | **yes** — `estimated_requests`, and every stream is in it | `task-6-report.md:423-431`; 07 O12 |
| 4 | **An aggregate-only body has no output count** | output is recorded as 0, so output spend is absent | **yes** — `estimated=True` | `transports.py:291-300` |
| 5 | **A model not in the bundled card is unpriced** | the whole request | **yes** — `unpriced_requests` | `pricing_catalog.py:1058-1060` |
| 6 | **A component with no published rate is charged zero and marked** | the whole component | **yes** — `unpriced_components`; 56 requests in the demo window | `export.py:806-813` |
| 7 | **`provider="unknown"`** (Azure, Bedrock, a gateway, vLLM) | the whole request | **yes** — `unpriced_requests` | `transports.py:61-72`; 07 R13 |
| 8 | **A provider rejects or discounts the request after the fact** (content filter, refund, committed-spend-tier credit) | unbounded | **no** — nothing in the record can see it | — |
| 9 | **Requests not made through a wrapped client** | unbounded | **no** — by construction | `docs/threat-model.md:43-52`, and `backstop doctor` does not scan for unwrapped clients |
| 10 | **A refused event never reaches the file** | bounded by the buffer, and the buffer is generous | **only while the process lives** — a file read reports `dropped_events` as *unknown*, never zero | `export.py:1749-1752` |

Gaps 3, 4, 5, 6 and 7 are all **floors, and all visible**, which is the intended
direction: the ledger under-reports and says so. Gaps 1, 2, 8 and 9 are the ones
that can make it **wrong in an undetectable direction**, and they are the
honest weak points of this document.

## 5.3 The error budget

**HYPOTHESIS. Unmeasured. No customer has run a billing period on this.** It is
stated as a number because a CFO will ask for one, and it is labelled because
this repository has never compared a ledger total to a provider invoice — there
is no real-provider fixture that does the comparison, because
`tests/test_real_openai.py` and `tests/test_real_anthropic.py` are **skipped
without a key** (`00-current-state-audit.md:48-51`).

| quantity | proposed budget | status | what would establish it |
|---|---|---|---|
| **M1, per provider per month, on a deployment with 100% of requests wrapped, every model in the bundled card, no streaming, and a rate card less than 30 days old** | **≤ 0.5%** | **HYPOTHESIS** | one real invoice, one real ledger, one comparison |
| M1, on a deployment **with** streaming | ≤ 2% | **HYPOTHESIS** | same; the floor is structural, not a defect |
| M1, on a deployment with any unpriced or unknown-provider traffic | **undefined** | **FACT that it is undefined** | the number is not knowable until the traffic is priced, which is why the export reports it as absent rather than estimating it |
| Attribution completeness, the demo window | 1,967 requests; **69 unattributed** (3.51%), **34 unpriced** (1.73%), **9 estimated**, **56 with a `cache_write` gap**. Spend coverage `1 - 103/1967 = 0.9476` | **FACT**, measured just now from `demo_events()`; see the decomposition below | already established |
| **Per-request dollar error** | **zero, for a priced model** | **FACT, structurally** | `Decimal` at 6 dp, `total_usd == sum(components)` by construction, a float is refused at every boundary, and the arithmetic is immune to the host's decimal context (the hostile-context failure mode is analysed in [02-ledger-architecture.md](02-ledger-architecture.md), *Failure-mode analysis*, row 7) |
| **Per-request dollar error, for a model whose card is stale** | **exactly the rate change** | **FACT that it is exactly the rate change** | M1 |

The framing that should go in the contract, in these words: **Backstop does not
promise a dollar. It promises that every dollar it reports is the product of a
documented rate, a measured token count and an explicit arithmetic, and that
every request it could not report that way is visible as a gap rather than as a
number.** That is a promise this codebase can keep, and it is the one a CFO can
actually audit.

### 5.3.1 The demo window's gap decomposition, measured

Measured just now from `backstop.ledger.demo.demo_events()`. This is included
because the **sum is not the union**, and a reader who adds the three counts
gets a different and wrong coverage figure.

| set | count | share of 1,967 |
|---|---:|---:|
| unattributed (no `team` and no `feature`) | 69 | 3.51% |
| unpriced (`cost is None`) | 34 | 1.73% |
| estimated (`estimated=True`) | 9 | 0.46% |
| `cache_write` component gap (priced event, unpriced component, tokens present) | 56 | 2.85% |
| **union of the first three** | **103** | **5.24%** |
| **coverage `1 - 103/1967`** | | **0.9476** |

Set intersections, measured: `unattributed ∩ unpriced = 0`,
`unattributed ∩ estimated = 9`, `unpriced ∩ estimated = 0`,
`cache_write gap ∩ unpriced = 0`.

**So the three sets are NOT disjoint: all 9 estimated requests are inside the 69
unattributed ones.** 69 + 34 + 9 = 112, and the union is 103 because the 9 are a
subset of the 69, not a fourth bucket.

The demo's own teardown does name an overlap — `src/backstop/ledger/demo.py:498`,
*"That count and the unpriced one are not disjoint: a request that is both
estimated and unpriced is in each"* — but that is a statement about the rule, not
about this window, and in this window `estimated ∩ unpriced` is **0**. The
overlap that is material here is `estimated ∩ unattributed = 9`, which the
teardown does not mention.

> **Correction to `01-north-star.md:126` and `:145`.** Both lines say the three
> gap sets are "disjoint" in the demo window. The figure those lines report —
> 103 of 1,967, coverage 0.9476 — is **correct and reproducible**; the stated
> justification is **wrong**, and the difference matters to anyone reasoning
> about the number. `01` was not modified, because this document's brief is two
> files. The correct statement is the decomposition above.

A second detail that is easy to misread: **"unattributed" in the charge-back is
evaluated against the *grouping*, not against the whole record.** All 69 of the
demo's unattributed requests carry `environment`; they set no `team` and no
`feature`. `ChargebackRow.is_unattributed` is `all(key == UNATTRIBUTED for key
in self.keys)` (`export.py:458-467`) — the rendered group keys, not
`Attribution.keys()`. A request that names a `customer` and nothing else is
*partially* attributed: finance can still charge it, so it is **not** counted in
`unattributed_usd`, and its unattributed cell is visible in the table instead
(`export.py:917-926`).

## 5.4 How a customer would audit it

In the order a finance team would actually do it. Every step is a command or a
file that exists in this repository today.

| step | command | what it proves | exit code |
|---|---|---|---|
| 1. Reproduce the pitch figure with no key and no network | `backstop ledger demo` | the arithmetic works, and the demo is byte-identical across runs (`task-7-report.md:362-372`: three runs, the same SHA-256) | 0 |
| 2. Read the file and get the integrity report | `backstop ledger show --path ledger.jsonl` | how many lines, how many events, whether the last line is torn, and — stated as **unknown, not zero** — what was lost before it reached the file | 0; **1** on a corrupt non-final line |
| 3. Check the file is a strict, complete record | `read_ledger` is the reader, and `SpendEvent.from_dict` refuses both an undeclared and a missing field | a typo or a truncation cannot reload as plausible data | — |
| 4. Verify one line's arithmetic by hand | every `cost` amount is a **string** with 6 dp; `total_usd` is the sum of the four; `price_source` names the layer | the per-request figure is reproducible with a calculator | — |
| 5. Verify one line against the provider | `request_id` → the provider dashboard | the token counts are the provider's, not Backstop's | — |
| 6. Get the charge-back and read the honesty columns **before** the total | `backstop ledger export --path ledger.jsonl --out chargeback.csv --group-by team,feature` | 13 columns + the group keys; `unpriced_requests`, `estimated_requests`, `unpriced_components`, `price_source` all sit beside the money | 0 |
| 7. Check the CSV is not going to re-round anything | money cells are `"12.34"`, never `12.34`; RFC 4180 CRLF; no totals row inside the data | a spreadsheet cannot silently convert a charge to a float, and there is no double count waiting in a pivot | — |
| 8. Join to their own revenue | `revenue_join(rows, revenue)` / `write_revenue_csv`, keyed on **the same group tuple** | margin, with `(none)` and a `match` column for every group missing on either side. Backstop does not fetch, infer or allocate revenue | — |
| 9. At close, read the loss figure | `Backstop.close(client)` → `CloseReport` (`src/backstop/wrapper.py:92-105`); or `atexit`, which `state.py:186-187` registers **only when the ledger is on** | `lost`, `landed`, `drained`, `undrained` | — |
| 10. Re-derive the same table next period | `build_chargeback` reads no clock, no I/O and no global state (`export.py:845`) | the same events give the same rows, byte for byte, on any machine | — |

**Step 2's asymmetry is the honest core of the trust story** and deserves to be
stated rather than smoothed: while the process is alive, the customer can get an
exact loss figure; from a file alone, they cannot, and the tool says
`unknown — a JSONL line records an event, never a counter` rather than printing
`0` (`export.py:1700-1705`, `:1749-1752`). A tool that reported zero there
would be claiming something it cannot know, and every other honesty decision in
this codebase follows from refusing to do that.

**Two things a customer cannot audit today, and should be told so up front:**

1. **Nothing computes M1.** Comparing a ledger total to a provider invoice is
   manual today. The `revenue_join` half is shipped; the *invoice* half is not,
   and it is the half that would make the product's M1 self-reported rather than
   customer-reported.
2. **A long-lived process that finishes a job must call `Backstop.close(client)`.**
   The `atexit` hook only covers interpreter exit, and "documentation is not a
   reminder" (`task-8-report.md:712-717`, 07 O14).

---

# Part 6 — Open items this document does not close

| # | item | status |
|---|---|---|
| 1 | The OTLP bridge does not exist | specified in Part 2.4, not built. `grep -rn "gen_ai" src/` returns zero |
| 2 | The Anthropic 1-hour cache-write tier | Part 4.6; three options, none taken. Option (ii) is the minimum |
| 3 | M1 is not computed | 5.4, step 1: nobody compares a ledger to an invoice automatically |
| 4 | A stream's cost is a floor | 07 O12; the upstream fix is a second event at stream close, which would change the event count per stream — a contract `export.py` is written against |
| 5 | `Attribution.currency` vs `CostBreakdown.currency` | Part 1.2. Two currencies, one record, two names. **PROPOSED: rename the attribution field to `revenue_currency`** — it is a caller-supplied revenue dimension and it collides with a name the schema already uses for something else. That is a wire-format change and needs the same version discipline as 4.6 option (i) |
| 6 | `provider="unknown"` has no `gen_ai.provider.name` enum member | Part 2.4 row 1. The bridge needs a `backstop.provider` attribute, not a silent drop |
| 7 | **`01-north-star.md:126,145` state the three demo gap sets are "disjoint"; they are not** | the figure 103 / 0.9476 is right and reproducible; the justification is wrong (all 9 estimated requests are inside the 69 unattributed). Corrected in 5.3.1; `01` left unmodified because it is outside this brief |
