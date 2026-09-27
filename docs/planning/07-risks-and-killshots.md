# 07 — Risks and killshots

The honest list. Every risk gets the same four things: what it is, the early
warning signal, the counter-move, and how survivable it is.

**Survivability scale.** `survivable` — the product absorbs it. `survivable but
it costs the wedge` — we can respond, but the specific thing we are selling
weakens. `not survivable as a standalone product` — if this happens, the ledger
is a feature of something else or it is not a business.

Two conventions. A number with a file and line is measured. A number without
one is **HYPOTHESIS** and is marked. No risk below has a probability attached,
because nobody here has a base rate to attach one to.

---

## Part 1 — market risks

### R1. Model providers ship native spend dashboards

**What it is.** OpenAI and Anthropic both already have console spend views and
both have the exact data a chargeback needs: per-request tokens, per-project
spend, dated. The provider's own dashboard is free, authoritative, and needs no
integration. A buyer choosing between "the provider's console" and "an OSS
library" is choosing between zero setup and a CSV.

**Early warning signal.** Any of:
- a provider console gains an *exportable per-dimension* breakdown (team, project,
  tag) rather than a fixed chart set. That is the moment the chargeback is
  commoditised, because a finance team can stop asking us.
- a provider publishes a **cost-attribution API**, not just a dashboard. The
  dashboard is a chart; an API is a join key.
- a provider's console starts showing an **unpriced or unattributed** figure.
  That is the one thing their data model makes hard and ours makes easy, and if
  they ship it our differentiator is gone.

**Counter-move.** Move up the stack, not sideways. The provider knows what it
charged; it does not know what the spend was *for*, and it has no cross-provider
view, no `team`/`feature`/`cost_center` dimensions, and no offline reconciliation
against a customer's own revenue. `revenue_join` is that answer and it already
ships (`export.py:1180`). Second: make the cross-provider case explicit — one
chargeback across both providers, which neither console can produce.

**Survivability.** `survivable but it costs the wedge`. The multi-provider
chargeback and the revenue join are real and defensible. The single-provider
part of the pitch is not, and the demo should probably stop leading with a
single-provider table.

### R2. Datadog or another observability incumbent adds an AI-cost module

**What it is.** Backstop's enforcement already emits Prometheus metrics
(`src/backstop/metrics.py`, 196 lines) and a dashboard. A company that already
sits in the customer's observability budget can ship an LLM cost view as a
dashboard over data it already collects. The sales motion is zero marginal:
same buyer, same call, same budget line.

**Early warning signal.**
- LLM cost panels appear in a major APM's default LLM integration. These are
  announced loudly and early, usually at the LLM-focused conference circuit.
- the incumbent starts ingesting **provider usage payloads** rather than only
  request latency, because that is the only way to get a dollar figure. This is
  the tell: cost needs `usage`, not `duration`.
- a customer says "we already see our LLM cost in <incumbent>". Ask what
  fraction of their spend that number covers. If the answer is "all of it" and
  they are happy, the ledger is not needed for cost, only for chargeback.

**Counter-move.** Do not compete on cost *visibility*; compete on cost
*attribution and reconciliation*. A dashboard shows a number. Backstop produces
a row that joins to a revenue key, states its own coverage, and refuses to
produce a CSV at all when the file is corrupt (`export.py:1511` raising
`LedgerCorruptionError` rather than skipping rows). That is a different job with
a different buyer inside the same company. Second: make sure the enforcement
half stands alone commercially, because it will be the thing that survives an
observability incumbent.

**Survivability.** `survivable`. The two products are adjacent, not identical,
and Backstop's honest-coverage design is not something a vendor dashboard ships
by default, because it makes their own numbers look bad.

### R3. Compression and routing startups move up into accounting

**What it is.** The routing layer is one hop above Backstop and already sees
every request. A router that starts emitting a cost breakdown is one feature
away from emitting an attributed one. They have the request context (the model
name, the caller, often the app identity) that Backstop only gets if the user
adds an attribution scope by hand. That is a real data advantage they have and
we do not.

**Early warning signal.**
- a routing vendor ships a "cost" tab that is per-team or per-tenant rather than
  per-model. Per-model is a utilisation view they can build today. Per-team means
  they built attribution.
- a routing vendor adds a **CSV export**. That is the moment they are talking to
  finance rather than to engineers, which is the same buyer conversation we are
  having.
- a routing vendor starts charging for "cost attribution" as a named SKU. Named
  SKUs are the clearest possible signal.

**Counter-move.** Beat them on the property they structurally cannot have: they
route, so their cost number is a *function of their own routing decisions*. A
chargeback built by the thing that chose the model is not an independent
measurement. Backstop sits below the routing decision and does not choose the
model, so the number is a measurement rather than a consequence. That argument
is real but it is a **HYPOTHESIS** and it needs a customer to accept it.

**Survivability.** `not survivable as a standalone product` if they ship
attributed cost and we are still selling the ledger as the primary product. It
is `survivable` if the enforcement half carries the company. This is the risk
that most directly argues for the two-buyer framing in
[01-north-star.md](01-north-star.md) being a real structure and not a hedge.

### R4. OpenRouter adds a ledger

**What it is.** OpenRouter is the layer where many teams already aggregate
multi-provider traffic, so it already has the cross-provider view we sell. It
also already sells the volume discount, so it has a direct financial incentive
to make per-model costs legible and to show the customer what they saved. A
built-in ledger is a retention and upsell feature for them.

**Early warning signal.**
- OpenRouter exports a per-model cost breakdown with a stable identifier per
  request. The stable request identifier is the tell, because that is what makes
  a row joinable to anything.
- OpenRouter publishes a spend API rather than only a console. Same tell as R1.
- OpenRouter's own marketing starts using chargeback or showback language. That
  is the buyer changing, not the feature.

**Counter-move.** The defence is the same as R1 plus one: teams that route
through a gateway and teams that wrap in-process are different populations, and
the second group has privacy reasons to keep payloads out of a third party
(`docs/threat-model.md:22-37`). But note honestly: for a team *already* on
OpenRouter, the incremental value of a second cost record is low, and that
segment is exactly the segment most likely to be early adopters.

**Survivability.** `survivable but it costs the wedge`, and the overlap with
our most likely early adopters is the uncomfortable part. **HYPOTHESIS**: how
much, nobody here knows.

### R5. Finance simply refuses to buy from an unknown OSS vendor

**What it is.** This is the risk that kills the ledger half outright, and it is
not a competitive risk, it is an adoption risk. The enforcement half sells to a
developer who can `pip install` and read the source. The ledger half asks a
finance team to put a number from an unknown vendor into a budget. That
organisation has a vendor risk register, a procurement process, and a rule about
whose numbers may be used for allocation. An unaudited OSS library with no
company behind it is not on the list.

**Early warning signal.**
- engineers love it and finance never asks for the export. That is the strongest
  single indicator, and it is visible within one quarter.
- the first request for a signed SLA, a SOC 2 report, or a DPA. Nothing in this
  repository can produce any of the three.
- an export is produced and then quietly not used. Ask what happened to it. The
  answer is usually "finance asked where the unattributed 4% went" and nobody
  had an answer.
- a single request for the number to be *certified* rather than *computed*.

**Counter-move.** Three, in order of cost.
1. Sell the ledger to the **engineer who is already the customer** as an
   internal tool, and let finance adopt it bottom-up. This is the cheapest path
   and it is how OSS infrastructure actually gets in. It is also how we end up
   with a used product and no revenue, which is a different failure.
2. Put an entity behind it: a company, a DPA, a support contract. Costs money
   before it earns any.
3. Make the number **auditable without trusting us**: the export is a
   deterministic function of a file the customer owns, and every rate carries
   `source` and `effective_from` (`pricing_catalog.py:350`). A finance team can
   re-derive any row from the customer's own NDJSON. That is the strongest
   argument available and it is already true of the artifact.

**Survivability.** `not survivable as a standalone product` without one of the
three counter-moves. `survivable` with counter-move 1, as a product that is used
rather than bought. That is a legitimate outcome but it is not the one being
planned for.

### R6. AI spend plateaus as inference costs fall roughly 10x/year

**What it is.** If the price of a token falls an order of magnitude per year, the
dollar-denominated problem gets smaller every year even as token volume grows
faster. A $5,000/month problem becomes a $500/month problem. A finance team
that was going to spend engineering money on allocation stops, because the
misallocation is no longer worth chasing. The entire category is priced in
dollars of misallocation.

**Early warning signal.**
- a customer's absolute spend falls quarter over quarter while their token
  volume rises. That is the signal, and it is measurable per customer from the
  ledger itself.
- a customer's *unattributed* share falls below the point where anyone argues
  about it. Below roughly 2% there is no conversation.
- a customer says "we just capped the team budget" instead of "we need to know
  who spent it". A cap is a substitute for a chargeback.
- a rising share of workloads on a small local model, where the price is a
  GPU-hour, not a token.

**Counter-move.** Change the denominator, not the pitch. The durable claim is not
"we save you money on tokens", it is "we give you a per-dimension record of
machine consumption that reconciles to the bill", which survives a falling token
price, a self-hosted model, and a GPU-hour. That is a bigger product and a slower
sale. It is also the honest reading of what `Attribution` already has fields
for (`customer`, `cost_center`, `gl_code`, `repo`) and what the revenue join
already does.

**Survivability.** `survivable but it changes the product`. The 10x/year figure
is a **HYPOTHESIS** about someone else's pricing, and it is the single most
load-bearing unproven assumption in the business. It is also worth noting that
it cuts both ways: cheaper inference is what makes agent workloads viable at all,
so volume and price may not move the way the naive model says.

---

## Part 2 — internal risks, in this repository

### R7. The ledger's own numbers are wrong in a way nobody notices for six months

**What it is.** The worst risk on this page, because it is the one that ends the
product rather than capping it. A finance team accepts a chargeback, budgets
from it, and nobody checks it against the invoice for two quarters. Meanwhile
the number is quietly wrong: a stale rate, a mis-read token split, a dropped
event, an unattributed row nobody noticed. By the time it surfaces, the trust is
gone and no amount of accuracy brings it back, because the failure was not a bug
report, it was a budget that was wrong.

The design fights this deliberately — no guessed prices, visible unpriced rows,
`estimated` flags, three separate loss counters, a reader that refuses to skip a
corrupt line. Those defences only help if someone is *looking*, and nothing in
this repository makes looking happen.

**Early warning signal.**
- `backstop ledger show` is never run. A deployment writing NDJSON and never
  reading it back is a deployment that has found the feature too slow to use or
  too alarming to look at, and both are failures.
- `ledger_errors` non-zero and unmonitored (`state.py:99`, `transports.py:349-350`). This is the counter that says "the transport could
  not turn a request into a record" and nothing reads it.
- `unpriced_requests` or `unpriced_components` non-zero and *stable* rather than
  trending down. A customer who never fixes the gap has stopped reading the
  column.
- the first customer who says "that total does not match the invoice". At that
  point we learn the truth and the relationship at the same time.
- nobody has ever run M1 from [01-north-star.md](01-north-star.md) on a real
  invoice. This is the true leading indicator today, and today it is true.

**Counter-move.**
1. Make reconciliation a first-class command, not a documentation exercise. It
   is not built. `backstop ledger show` reads our file; it cannot read a provider
   invoice. Until a customer can hand us both and get a variance, M1 is a
   **HYPOTHESIS** with no mechanism behind it.
2. Make `ledger_errors` and the delivery counters alertable. `lost` and
   `dropped_events` are already computed (`sink.py:86-102`) and already printed
   in the demo; nothing ships them anywhere an operator watches. There are
   `observability/prometheus-alerts.yml` rules for detection
   (`backstop_detection_evictions_total`) and none for ledger loss.
3. Refuse to sell the ledger to anyone who will not reconcile it once. This is
   commercially hostile and it is the right call.

**Survivability.** `not survivable` if it happens. This is the risk that makes
the other five survivable or not.

### R8. The bundled rate card is a dated snapshot and nothing detects a rate change

**What it is.** `BUNDLED_EFFECTIVE_FROM = "2026-09-26"`
(`pricing_catalog.py:226`) is a transcription date for 45 model prices
(`pricing_catalog.py:420`), taken from two published price pages. Nothing in
this repository can tell when a provider changes a rate. The bundled table is
the **lowest** precedence layer, so a user catalog file overrides it, which is
the right design and also means the bundled table is what every new deployment
uses until the user notices they are wrong.

There is a worse variant already known and documented: the bundled Anthropic
cache-write rate is the **5-minute tier**, and the schema has one
`cache_write_per_mtok_usd` field, so a deployment on a 1-hour cache TTL
under-counts its cache writes — and because the entry *does* carry a write rate,
`priced_components` cannot reveal it (`progress.md:111-112`,
`task-4-report.md:441-446`). The record has no way to say which TTL it priced.

**Early warning signal.**
- `effective_from` on the bundled table is more than ~90 days old. That is a
  `HYPOTHESIS` threshold; nobody has data on how often providers reprice.
- the count of `unpriced_requests` rises as new model names appear. New models
  are priced last and go unpriced first, and `vendor-preview-2027` in the demo
  is exactly that shape.
- a customer's total drifts from their invoice in one direction only, and the
  direction does not change when they fix something else. That is a rate, not a
  token-count bug.
- a provider ships a price page change and nobody in this project notices for a
  month. Given no refresh job exists, this is the base case, not the tail case.

**Counter-move.**
1. A refresh job that re-fetches the two pages on a schedule and opens a diff
   PR. Deliberately out of scope for the hot path and for the first release
   (`task-4-report.md:435-440`).
2. Make `effective_from` visible in the export next to `price_source`, so a
   reader can at least see the age of the number. It exists on `PriceEntry`
   (`pricing_catalog.py:350`) and is **not** a chargeback column today
   (`export.py:178-193`). Cheap and worth doing.
3. For the TTL problem: a second `cache_write_1h_per_mtok_usd` field or a
   per-event TTL. Both are schema changes.

**Survivability.** `survivable` and already partially mitigated by precedence:
a customer with negotiated rates is immune, and the unpriced path is visible
rather than silent. It is a credibility risk before it is a correctness risk.

### R9. The ledger ships with no multi-tenancy story

**What it is.** `ledger_path` is one NDJSON file per `BackstopState`
(`config.py:203`, `state.py:_build_ledger`). There is no tenant-scoped ledger,
no per-tenant file, no shared store, no partitioning, no access control. Every
attribution dimension is a *string in a row*, not a boundary. A customer who
wants to give team A their own spend file gets a group-by, not a ledger.

The in-process multi-tenancy that does exist — `virtual_keys` and
`TenantBudget` — is a different feature on a different axis, and note that it is
partly broken today: the default secret provider is silently dead
(`00-current-state-audit.md` A2.5 / O1), so a virtual-key deployment does not
resolve per-key credentials at all.

**Early warning signal.**
- a customer asks "can team A see only their own spend?" and the answer is a
  `WHERE team = 'a'` in their own warehouse.
- a customer tries to run one `backstop` process as a shared service for several
  internal teams and finds the budget and the ledger are one process's.
- an enterprise security review asks who can read the file. The honest answer
  today is "whoever can read the path you configured", which is correct and
  insufficient for a shared platform.

**Counter-move.** Say plainly that the ledger is **per process**, and lean on the
fact that this is a feature for the in-process `wrap()` model: a team that
wraps in one process and wants a chargeback gets a file they own with no service
in the boundary at all (`docs/threat-model.md:22`). Where that fails, the answer
is a group-by plus their own warehouse, not a feature we should build before
there is demand.

**Survivability.** `survivable` as a deliberate scope boundary; `not survivable`
if the product is sold into shared multi-tenant platforms, where it will be.

### R10. The TypeScript package is a divergent fork

**What it is.** `backstop-ai` on npm is the **same name and same version**
(`0.6.0`, `ts/backstop/package.json:2-3`) as the Python distribution, and it is
a different product. Measured, not alleged:

| | Python | TypeScript |
|---|---|---|
| source lines | 19,176 (incl. `src/wedge`) | 1,233 |
| interception | transport injection (`transports.py`) | `client.chat.completions.create` patching (`wrap.ts:96`) |
| priorities | 3: `critical`, `default`, `background` (`config.py:30-32`) | **5**: `critical`, `high`, `default`, `low`, `bulk` (`types.ts:1`) |
| budget semantics | no priority bypass | `critical` **and `high`** bypass the budget ceiling outright (`wrap.ts:108`) |
| Anthropic | supported | none (`package.json:29-31`: `peerDependencies: openai >=4`) |
| ledger, price catalog, detector | shipped | none |
| CI | 12 combinations + 1 cross-check | **none**; `npm test` runs only by hand |

The gap is also widening: 989 TS source lines against 10,558 Python lines at the
base of this build; 1,233 against 19,176 today. Every ledger commit widens it
further.

**Early warning signal.**
- an npm user files a bug describing behaviour that matches neither the Python
  nor the TS documentation. That is the signature of a fork nobody is tracking.
- the `0.6.0` version on both packages starts implying a shared feature set.
  It already does: same name, same version, different products.
- a Python changelog entry adds a config field the TS README's field list does
  not have, and nobody notices because nothing checks.

**Counter-move.** Pick one, and do it explicitly:
(a) deprecate npm and say so in both READMEs and both package descriptions; or
(b) make the TS package a *documented subset* with its own version line
(`0.6.0-py.0`) and a generated field-compatibility test that fails when the
config surfaces diverge. (a) is one commit. (b) is a real project. Option (c),
leave it, is what produced the current state.

**Survivability.** `survivable` and low urgency for the Python-led wedge, high
urgency for anyone whose story involves TypeScript users, because a same-named
package that behaves differently is a support burden and a credibility problem
rather than a technical one.

### R11. Enforcement and the ledger have different buyers and pull the product in two directions

**What it is.** The structural risk, and the one that decides whether the company
is one product or two. The enforcement buyer wants: fast, no dependencies, no
new required surface, no surprises, works offline, one wrap call. The ledger
buyer wants: exports, files, threads, a price catalog to maintain, a rate card
that has to be right, a format they can hand to finance.

Concretely, the two have already collided once and the ruling went one way.
Global Constraint 2 protects the default path, and the measured cost of the
opt-in ledger is **+130.0 us p50, +84.6%**, nearly doubling a request
(`task-6-report.md:348-353`) — roughly 1.4x the library's entire advertised
~90 us overhead class. The ruling accepted it and said so in `progress.md:100-108`:
*"Accepted because the alternative is a ledger that is too lossy to reconcile
against an invoice."* That is a ledger decision overriding an enforcement
constraint, and it will happen again.

**Early warning signal.**
- a default changes. Any new field that is not `False`/off by default starts
  being treated as a bug, which means the two buyers are writing the same
  issues.
- an engineer adopts `wrap()` for the budget and then asks us to remove the
  ledger, or a finance team asks for enforcement and gets a library whose
  headline feature is a CSV.
- the release notes start having two audiences in one section, which is the
  writing tell.
- the enforcement half's adoption is measured in installs and the ledger half's
  in accounts, and they are never the same denominator. That is already true in
  the plan: `Backstop.wrap()` adoption and accepted chargebacks are separate
  questions with no shared instrument.
- roadmap items start with the word "and".

**Counter-move.** Hold the separation explicitly and write it down:
enforcement and the ledger are **two products in one package with two version
histories in one changelog**, not one product with two features. Concretely: the
enforcement half keeps a hard guarantee (no required deps, one wrap call, default
path in the sub-millisecond class, works fully offline) that the ledger half is
forbidden from weakening; the ledger half is allowed to be slower, heavier and
opinionated because it is opt-in and it says so. If that separation cannot be
maintained, the ledger becomes a separate distribution. That is a legitimate
outcome, not a failure.

**Survivability.** `survivable if stated, not survivable if discovered`. The
pull is real and both directions are defensible, which is exactly why it has to
be a written constraint rather than a judgement made under deadline.

### R12. The ledger is too slow for the highest-volume Python workloads

**What it is.** Related to R11 but separable, because it is a measured number
rather than a tension. The ledger-ON path costs **+130.0 us p50, +253.4 us p95,
+335.1 us p99** (`task-6-report.md:348-353`). The single largest line item is
not the event, not the pricing and not the queue: it is roughly **35-40 us of GIL
time lost to `condition.notify()` waking the drain thread**, per submit
(`task-6-report.md:406-409`, `progress.md:109-110`). That is the part of the cost
that is invisible inside `submit` itself.

The consequence is specific: a tight synchronous loop — a batch job, a
high-QPS synchronous API, an eval harness — sees its per-request cost roughly
double. The workloads that would generate the *best* cross-customer cost
baselines are exactly the ones that cannot afford it.

**Early warning signal.**
- a customer measures the ledger ON path against their p99 and files a
  performance issue, not a feature request.
- `dropped_events` is non-zero on a burst. That is the buffer hitting 10,000
  (`sink.py:75`) because the drain thread is not keeping up, which is the same
  story told a different way.
- adoption clusters in low-volume, high-value-per-request workloads and never
  appears in a batch pipeline. The baseline corpus develops a hole exactly where
  the volume is.

**Counter-move.** Batch the notify. It is identified, quantified and unbatched.
A cheap first version: only wake the drain thread when the buffer crosses a
low-water mark, or on a short timer, amortising the GIL cost over N submits. It
is the highest-leverage single optimisation available in the ledger and it was
correctly deferred rather than rushed.

**Survivability.** `survivable`. The default path is untouched and the
enforcement half is unaffected.

### R13. Deployments on any non-OpenAI/non-Anthropic provider get an unusable ledger

**What it is.** `provider` is derived from the request host, matched against
`openai.com` and `anthropic.com`; anything else is recorded as `"unknown"` and
therefore **unpriced** (`transports.py:61, 307`, and the reasoning in
the `_record_spend` docstring). Azure OpenAI, AWS Bedrock, Google Vertex, any
gateway, any self-hosted vLLM: a real event, a real token count, and no dollars.

This was a deliberate choice — guessing `openai` from the model name would
produce a chargeback row that looks authoritative and is about the wrong vendor
— and the escape hatch is a user catalog file with `"provider": "unknown"`. But
the escape hatch is a *manual* per-model file, and the default deployment shape
in 2026 is not `api.openai.com`.

**Early warning signal.**
- `unpriced_requests` is high on day one rather than near zero. It is the very
  first number the demo teaches a reader to look at, and it will be the first
  thing that greets a Bedrock user.
- a customer filing a price catalog with `"provider": "unknown"` entries. That is
  the workaround being used, and it does not scale.
- a request for the ledger to price a self-hosted model at all, which requires a
  cost model Backstop does not have.

**Counter-move.** A `provider_map` config field — host prefix to catalog
provider — closes the routing half. It was explicitly not built
(`task-6-report.md:417-422`). For genuinely self-hosted spend the answer is a
different product: a per-GPU-hour ledger, not a per-token one.

**Survivability.** `survivable` for the OpenAI/Anthropic segment, which is real
and growing; `not survivable` if the market moves to self-hosting faster than
this gets built.

### R14. A provider major removes the propagate-as-is guard and enforcement silently stops

**What it is.** Below `openai<2.37` and `anthropic<0.98`, the SDK's request loop
catches every transport exception including `BudgetExceededError` and re-raises
it as `APIConnectionError`, so the guardrail is **invisible to user code**
(`docs/compatibility.md:43-51`, bisected 2026-09-18). `Backstop.wrap()` warns
rather than refuses. So the failure mode on a future SDK major is: the budget
still blocks, the user still gets an exception, and the exception is the wrong
type — which in most codebases means an unhandled 500 rather than a caught
budget error. The budget is still enforced. Nobody is told.

**Early warning signal.**
- the `UserWarning` on `wrap()` starts appearing in customer logs and nobody
  investigates.
- a CI row tracking `latest` fails. The matrix has exactly one such row
  (`docs/sdk-matrix.md:25-26`) and it pairs `openai latest` only with
  `anthropic 0.99.0`; **anthropic `latest` is not tracked at all**
  (`docs/compatibility.md:31-35`).
- `tests/test_guardrail_visibility.py` is the only test that pins the behaviour,
  and the versions it pins are 3.14.0 / 1.5.0 and 2.37.0 / 0.99.0.

**Counter-move.** Add SDK majors to the CI matrix, including an `anthropic
latest` row. Refuse to wrap an untested major rather than warn — the
"test before you rely on it" posture is currently opt-in and the failure is
silent. That is a one-line change with a real cost in support, which is the
trade.

**Survivability.** `survivable` if CI catches it before a customer does, which is
a scheduling problem rather than a design one.

### R15. The repo ships four defects the ledger half's credibility rests on

**What it is.** Not a market risk, an honesty risk, and it is the reason this
document exists. The known-defect register below is the one place in the
repository that is expected to shrink as work lands, so it is kept honest about
what is still true.

**Status as of the current `main`.** Every item in the table has been re-checked
against the code. O1 was real and is now **fixed**; O20, O21, O22 and O24 are
also **fixed**. The register is retained rather than deleted, because the next
audit needs the history of what was found and when.

| | defect | status | why it mattered to the ledger story specifically |
|---|---|---|---|
| O1 | The default secret provider was silently dead: `BackstopConfig` is a frozen dataclass, so `self.secret_provider = SecretProviderChain(...)` in `__post_init__` raised `FrozenInstanceError` and a bare `except Exception: pass` swallowed it. `secret_provider` stayed `None` for every user. | **FIXED** — now installed with `object.__setattr__`, and only when `virtual_keys` are configured, which is the only case where there is anything to resolve. Covered by `test_the_default_secret_provider_is_actually_installed`. | The attribution story depends on virtual keys resolving to real per-tenant credentials. A deployment that believed it had them, and did not, was building its chargeback on a fiction. |
| O1b | `secrets.py` documented the resolution order with the environment *before* `virtual_keys`, while the code and its tests did the opposite. | **FIXED** — docstring corrected to state the shipped, tested order, with the rationale. No behaviour change. | Anyone reasoning about which credential wins was reasoning from a wrong spec. |
| O20 | `docs/ledger.md` did not exist | **FIXED** — 731-line user-facing document shipped. | The build plan gates it on Task 7, which has landed. |
| O21 | `CHANGELOG.md` `## [Unreleased]` had no ledger or detection entry | **FIXED** — the whole build is recorded. | Three user-visible commands had shipped unannounced. |
| O24 | `README.md` did not mention the ledger, the price catalog, or the detector | **FIXED** — the README documents all three, and `docs/ledger.md` links from it. | The wedge was not discoverable from the front door. |

Plus, adjacent: O22 (`docs/install.md` still describing the two CLI defects this
build fixed, so the docs understated the product) is **FIXED**; and `TODO.md`
previously showed tasks
4-8 unchecked although they shipped (O23).

**Early warning signal.**
- a customer finds `docs/ledger.md` before the changelog does.
- a security review reads `config.py:366-370`, sees `except Exception: pass`, and
  asks what else is swallowed. It is a fair question.
- a `pypi` release goes out with the ledger unannounced, because that is the
  default when `CHANGELOG.md` is the last thing written.

**Counter-move.** Task 10, before anything else. Fix O1 as a one-line change to a
frozen-dataclass assignment. Write `docs/ledger.md`. Write the changelog. Add
the ledger to the README. None of it is hard and all of it is currently
un-done.

**Survivability.** `survivable` and embarrassing rather than fatal. The fix is
four documents and one line.

---

## Part 3 — what would make us STOP

Stated as observable conditions, not feelings. Each is a measurement somebody
could take, not a judgement somebody could argue.

**We stop building the ledger as a product if any of these is true for two
consecutive quarters:**

1. **Zero accepted chargebacks.** No customer's finance function has put a
   Backstop-produced number into a budget or a reconciliation, and none has run
   M1 (ledger-to-invoice variance) even once. The mechanism does not exist yet,
   so this is observable as "no customer has asked us for one".
2. **The variance is not close.** For the first three customers who do reconcile,
   M1 exceeds 5% of invoice total. Below that it is a rounding story; above it,
   the number is not a chargeback.
3. **The trust objection is the modal reason, not a minority one.** In more than
   half of evaluation conversations the blocker is "we cannot take numbers from
   an unknown vendor" rather than a feature gap or a price. That is a reason to
   found an entity or to stop, and there is no third option.
4. **Enforcement and ledger adoption never overlap.** In every account we have,
   only one of the two is live. The two-buyer thesis in
   [01-north-star.md](01-north-star.md) is then a hedge, not a structure, and the
   honest move is to pick the enforcement half and say so.
5. **A routing or observability incumbent ships attributed, per-dimension cost
   with a CSV export** (R1 + R2 + R3 combined). The wedge is gone; what remains
   is enforcement.

**We stop the whole project if any of these is true:**

6. **A customer's published incident traces to a Backstop number.** One
   chargeback that a business acted on and that was materially wrong ends the
   finance motion. There is no recovery from that; the thing's value was that it
   was right.
7. **A default-path regression reaches users.** The one-wrap-call property, the
   no-required-dependencies property, or the sub-millisecond default path breaks
   for someone who never opted into anything. The enforcement half is the durable
   half; breaking it to serve the ledger is the trade that ends the company.
8. **The ledger's own error counters cannot be made alertable.** If `lost`,
   `dropped_events` and `ledger_errors` cannot reach somewhere an operator
   already looks, then R7 has no counter-move and the product is a number nobody
   can check, which is worse than no product.

**We do not stop for any of these:**

- a slow quarter of installs. Distribution is not the claim being tested.
- losing a competitive bake-off on features. Neither product has a feature moat;
  R1-R4 say so plainly.
- a provider repricing without telling us. That is R8, and the counter-move is a
  refresh job plus visible `effective_from`, not an exit.
- the TypeScript fork diverging further. That is R10, and the fix is one commit
  that deprecates it.
