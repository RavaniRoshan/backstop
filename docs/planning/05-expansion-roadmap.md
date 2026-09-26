# 05 — Expansion roadmap (Areas D, E, F)

Branch `feat/ledger-foundation`. Head at time of writing `39cb7f9`.

**A note on Area provenance.** `docs/planning/_build-plan.md` names Area A
(line 74), Area C (line 75), Area E (line 78) and Area B (line 79) and nothing
else. There is no document in this tree that defines Areas D, F or G. The brief
for this document assigns them to language expansion, framework integration,
the finance-facing feature set, forecasting, distribution surfaces, the
OSS/proprietary boundary and pricing. That mapping is taken from the brief and
is labelled here rather than smuggled in as a citation; everything *inside* each
section is grounded in the repository.

This document is forward-looking. It is therefore mostly **HYPOTHESIS**, and it
says so on every claim. The FACT tables are the parts where the code, the git
history or a measured number decides.

The two documents it must not contradict: the buyer split and the moat in
[01-north-star.md](01-north-star.md), and R9/R10/R11 in
[07-risks-and-killshots.md](07-risks-and-killshots.md), which already name the
TypeScript fork, the missing multi-tenancy story and the two-buyer problem.

---

# 1. Language priority

## 1.1 The starting fact, which changes the shape of the question

**A TypeScript package already exists, is already published, and is already
drifting.** The question is not "should we write a TypeScript SDK". It is
"what do we do about a same-named, same-versioned, differently-behaving package
that is already in users' `node_modules`".

| | measured | source |
|---|---|---|
| published | `backstop-ai@0.6.0` on npm, same name and same version as the PyPI distribution | `ts/backstop/package.json:2-3`; `PLAN.md:968-970` records the publish |
| Python source | **19,176** lines (`src/backstop` 18,318 + `src/wedge` 858), 56 `.py` files | `find … \| xargs wc -l` |
| TypeScript source | **989** lines across 10 files, plus 244 lines of tests | `wc -l ts/backstop/src/*.ts ts/backstop/tests/*.ts` |
| Python tests | 14,683 lines, 1,214 passing | `find tests -name "*.py" \| xargs wc -l`; suite run just now |
| interception | transport injection — `BackstopTransport.handle_request` | `src/backstop/transports.py` |
| TS interception | **`client.chat.completions.create` monkey-patch** | `ts/backstop/src/wrap.ts:96` |
| priorities | **3**: `critical`, `default`, `background` | `src/backstop/config.py:29-31` |
| TS priorities | **5**: `critical`, `high`, `default`, `low`, `bulk` | `ts/backstop/src/types.ts:1` |
| budget semantics | no priority bypass anywhere in the budget path | `grep -n critical src/backstop/{transports,budget}.py` returns nothing in the budget path |
| TS budget semantics | `critical` **and `high`** bypass the ceiling outright | `ts/backstop/src/wrap.ts:108` |
| Anthropic | supported (`>=0.98,<2`) | `pyproject.toml` `[project.optional-dependencies].anthropic` |
| TS Anthropic | none — `peerDependencies: { "openai": ">=4" }` and nothing else | `ts/backstop/package.json:29-31` |
| ledger / price catalog / detector | shipped, 6,350 lines | `wc -l src/backstop/ledger/ src/backstop/pricing_catalog.py src/backstop/detection/` |
| TS equivalents | **none of the three** | `ts/backstop/src/index.ts` — 21 lines of exports, no ledger, no detector |
| metrics | `backstop_*` Prometheus surface, `metrics.py` | — |
| TS metrics | **none.** `grep -rln "prometheus\|metrics\|otel\|redis" ts/backstop/src/` returns nothing | measured |
| OTel | `otel` extra, `src/backstop/otel.py` | — |
| TS OTel | **none** | measured |
| Redis shared budget | `redis` extra, `state_backends.py` with atomic Lua (`evalsha`) | `docs/architecture.md` |
| TS Redis | **none** | measured |
| hierarchical budgets | `src/backstop/hierarchical.py`, 167 lines — **not wired to the transport** (open item O2) | `00-current-state-audit.md` A2.1 |
| TS hierarchy | **none** | measured |
| audit chain | `src/backstop/audit.py` 79 lines, HMAC-chained, `verify()` replays it; plus 212 lines of sinks | `audit.py:20-22, 60-65` |
| TS audit chain | **it has one** — `ts/backstop/src/audit.ts`, 70 lines, same HMAC chain, same `verify()`. **This is the one thing the fork did not lose** | read in full |
| CI | 12 combinations + 1 cross-check, `ubuntu-latest` | `.github/workflows/ci.yml:14-29` |
| TS CI | **none.** `npm test` runs only by hand | `docs/sdk-matrix.md`; `docs/compatibility.md` |
| its own README's claim | "This is a **scaffold** of the Python SDK's `wrap()` semantics… Distributed (Redis) budgets and OpenTelemetry export are Python-only today." | `ts/backstop/README.md:52-55` |

**One correction to the brief, made because the code says so:** the fork does
*not* lack an audit chain. `ts/backstop/src/audit.ts` reimplements the HMAC
chain and `verify()` in 70 lines. What the fork lacks is the four pluggable
audit **sinks** (`audit_sink.py`, 212 lines, which
`00-current-state-audit.md` A2.2 records as unreachable from the product
*anyway*) and the transport-level enforcement that produces records worth
chaining. Recording this because "the fork is missing everything" is the kind of
claim this repository spent 81 commits removing.

**One concrete defect in the fork**, found while reading it, and the kind of
thing a CI job would have found: `audit.ts:34` calls `require("node:fs")` inside
a package whose `package.json:5` declares `"type": "module"` and whose
`tsconfig.json` sets `"module": "ESNext"`. `require` is not defined in ESM. The
call is inside `if (typeof sink === "string")`, so it is only reached when a
file-path audit sink is configured — which is the only configuration that
matters — and it would throw `ReferenceError: require is not defined` at
construction. There is no test for it because there is no CI to run the tests.

## 1.2 The order, and the reasoning

**Recommended order: TypeScript → Go → Rust → Java. Do not start Rust, and do
not start Java.** Every part of this ordering is **HYPOTHESIS** except the
TypeScript half, which is a *ruling* about an existing mess rather than a
forecast.

### First: TypeScript. Not because it is the biggest prize — because the mess is already in users' `node_modules`.

Three reasons, in order of weight:

1. **It is a live credibility problem, not an opportunity.** Same name, same
   version, different semantics, and a budget bypass that does not exist in
   Python. Anyone who reads the npm README and the PyPI README is being told
   two different truths about the same product. R10 in
   [07](07-risks-and-killshots.md) already scored this `survivable` for the
   Python wedge and high-urgency for anyone whose story involves TypeScript.
2. **The interception point is the *same* interception point, one layer down.**
   Python injects an `httpx` transport into the SDK client. The OpenAI Node SDK
   takes a `fetch` implementation, and the SDK's own HTTP layer is built on
   `undici`. Interception is `new OpenAI({ fetch: backstopFetch })` — a
   *supported, documented* configuration option, not a monkey-patch. That means
   the TS port can move from `create`-patching to transport injection, which
   makes it the same product rather than a different one, and makes budget
   enforcement non-bypassable in the way the Python side already is.
3. **The maintenance asymmetry is already lost and gets worse.** Every ledger
   commit widens the gap (989 TS lines against 10,558 Python at the base of this
   build; 989 against 19,176 today). Leaving it is a decision, and R10's
   counter-moves are (a) deprecate npm, or (b) make it a documented subset with
   its own version line. **Recommendation: do (a) and (b) in the same week** —
   deprecate the *current* package's claim to parity, give it a distinct version
   line, and then converge only the ledger, because the ledger is the product.

**HYPOTHESIS, and the thing to watch:** that Node/TypeScript is where the money
is. The argument is that the agent-framework ecosystem with the most funding and
the most production deployments sits in TypeScript, that Vercel AI SDK and Mastra
are both TypeScript, and that the two highest-growth agent surfaces a
finance-minded buyer would care about are both Node. **This is not measured
anywhere in this repository and I have no data.** What would falsify it: the
first three inbound enterprise conversations both being Go or Python shops, or a
single inbound request for a Rust SDK that is not about a performance complaint.

### Second: Go. Only for one reason — the interception point is the best in any language.

`http.RoundTripper` is an interface with one method, it is the documented way to
add behaviour to any `net/http` client, and `http.DefaultTransport` can be
replaced process-wide. A Go port is roughly 400 lines of interception and then
the same problem TypeScript has: re-implementing the ledger.

Go is second rather than first because of **where the money is relative to
effort** (**HYPOTHESIS**): Go is where a great deal of *platform* engineering
sits — the API gateways, the admission controllers, the egress proxies — and
those teams buy enforcement libraries, not finance artefacts. The ledger buyer
named in [01](01-north-star.md) is a finance person at a company whose agents
are written in whatever the agents are written in. There is no evidence in this
repo that Go-hosted agent fleets are a large share of spend.

**The one Go-specific argument that is not a guess**, and it is about the
library, not the market: Go's `http.RoundTripper` is the only interception point
among the four languages where the *whole* fleet — not just the LLM calls — can
be mediated without touching call sites. A Go team can put Backstop on
`http.DefaultTransport` and get the ledger for every outbound HTTP call the
process makes, attributed by whatever context the request carries. That is a
bigger blast radius than `wrap()` has, and it is a feature for a platform team
and a hazard for everyone else.

### Third: Rust, and explicitly **not** a shared core.

**There is no shared Rust core in this repository today.** Verified: no
`Cargo.toml`, no `*.rs`, no `go.mod`, no `*.go` anywhere in the tree. A
Rust-core-plus-thin-bindings strategy is **new work, not the exploitation of an
existing asset**, and the asset it would exploit does not exist.

I would still argue against doing it, on cost:

| consideration | reading |
|---|---|
| what a shared core would buy | one implementation of the schema, the pricing and the export, with 4 language bindings instead of 4 implementations |
| what it costs | a Rust toolchain, a FFI surface per language, a build matrix per language, and a synchronisation tax on every schema change. The schema changed shape **three times** during this build (`a228fcf` endpoint idempotence, `f42e8fd` field validation, `ddaba66` the `price_unknown` correction) and the `Attribution` validation grew to 13 fields x 5 bad values of tests |
| who maintains it | one person, part-time, per the 90-day plan in [06](06-90-day-plan.md) |
| who consumes it | nobody today |

**HYPOTHESIS:** if a second language ships, revisit the shared core at that
point and not before. The trigger is concrete: **the moment a second language has
a ledger implementation that has to be kept in step by hand.** One language does
not have that problem.

### Fourth: Java, and the reason is a boundary rather than a ranking.

A JVM artifact is a different distribution: a Maven coordinate, a shaded jar,
possibly a JPMS module, a different release cadence, and a compatibility matrix
against Spring Boot / Quarkus / Micronaut versions. It is the *most* different
packaging surface of the four, for the fleet-share argument it would need to win,
and **HYPOTHESIS** that fleet share is smallest. Java is last and is not
recommended inside any horizon this document can see.

### The table

| rank | language | interception point | ledger parity needed | effort (**HYPOTHESIS**, one part-time dev) | verdict |
|:-:|---|---|---|---:|---|
| 1 | TypeScript | `fetch` / `undici` passed to the OpenAI client constructor — a supported option, not a patch | transport injection + `SpendEvent` + JSONL + `compute_cost` + export | **8-12 d** | do it; the mess is already shipped |
| 2 | Go | `http.RoundTripper` | as above | **6-9 d** | only if inbound Go demand appears |
| 3 | Rust | `reqwest` middleware (`ClientBuilder::middleware`) or a `tower` layer | as above | **6-8 d** | not as a shared core; revisit only on the second-language trigger |
| 4 | Java | `java.net.http.HttpClient` interceptor, or a Spring `ClientHttpRequestInterceptor` | as above | **10-15 d** | no |

Every effort figure is a **HYPOTHESIS**. They are anchored on one measured fact:
the Python ledger half is **6,350 lines** (`wc -l src/backstop/ledger/
src/backstop/pricing_catalog.py src/backstop/detection/`), and roughly half of
that is validation and tests whose whole purpose is to be paranoid about money.
A port that skips the paranoia is not a port, it is a smaller product wearing the
same name — which is exactly the current state of the TypeScript package.

---

# 2. Framework integration order

## 2.1 The candidates

| framework | language | what it offers to hook | what a "native" integration would need |
|---|---|---|---|
| **LangGraph** | Python, TS | a checkpointer, an interrupt primitive, per-node execution | per-node budget, per-node attribution, resume-after-interrupt |
| **CrewAI** | Python | crew/agent/task callbacks, task callbacks | per-task budget, per-agent attribution |
| **AutoGen** | Python | agent message hooks, conversable-agent callbacks | per-turn budget, per-conversation attribution |
| **OpenAI Agents SDK** | Python, TS | lifecycle hooks, `Runner`, guardrails, sessions | per-run budget, per-run attribution, **and a resume story** |
| **Anthropic Claude Agent SDK** | Python, TS | hooks (`PreToolUse`, `PostToolUse`), subagents, MCP | per-tool-call budget, per-subagent attribution |
| **Pydantic AI** | Python | dependency-injected `ModelRequestInstrumented` | per-tool-call budget, per-agent attribution |
| **Mastra** | TypeScript | tool middleware, workflow steps | per-step budget, per-workflow attribution |
| **Vercel AI SDK** | TypeScript | `wrapLanguageModel`, middleware, `onStepFinish` | per-step budget, per-step attribution |

## 2.2 The first two: LangGraph, then CrewAI

**LangGraph first.** Three reasons, and the first is measured:

1. **It is the one framework that gives us the thing auto-kill needs.** A
   checkpointer and an interrupt primitive mean "resume" is a framework concept
   rather than something Backstop would have to invent. That makes LangGraph the
   only candidate on this list that could eventually unblock the §3 requirement
   in [04-detection-design.md](04-detection-design.md) — which is a strong
   reason to integrate it first even though the ledger buyer cannot use it.
2. **It is a graph, and a graph is a budget.** Nodes are addressable units of
   work. "This node's budget" and "this node's ledger row" are natural, and
   `Attribution` already has 13 fields to hang them on. Every other framework on
   this list is a call stack, not a graph, and a call stack has no natural unit
   below the conversation.
3. **Per-node budgets are the demo.** A graph that fans out to 200 nodes is
   visible, and a budget that stops the 201st is a screenshot.

**CrewAI second.** It is the other framework named in the repo's own public
roadmap, it is the most common Python multi-agent framework in the "research
crew" shape that burns money, and its task boundary gives a usable attribution
unit even though it has no resume primitive. **HYPOTHESIS:** CrewAI having no
equivalent interrupt primitive today is unverified against its current release.

**Not AutoGen third, despite being on the list.** It is a conversation, not a
task, so the attribution unit is the conversation — which is the same unit as
`Attribution.session` and therefore adds no new *kind* of dimension. It is a
one-week adapter once the seam exists, and it is not worth building a seam for.

**What "native" means beyond SDK-level.** This is the distinction that decides
whether an integration is worth anything, and the README already concedes the
current state honestly: *"Not LangGraph/CrewAI-native. Works with those
frameworks only at the SDK level, not via framework-specific hooks"*
(`README.md:245`). Three levels, and only the third is worth the name:

| level | what you get | what it is worth |
|---|---|---|
| **L1 — SDK level (today)** | `wrap()` works, so the budget is enforced per HTTP call, and the ledger gets a row per request | the enforcement half works. The ledger half gets `team`/`feature` from an `Attribution` the user has to set by hand around every node. **This is what ships today.** |
| **L2 — framework callbacks** | the framework's `on_llm_start` / `on_llm_end` / task-complete hooks feed `Backstop`'s metrics, audit and attribution | attribution becomes automatic and per-node, which is the actual product gap. `src/backstop/adapters/__init__.py` already has the shape of this — a `BackstopAdapter` with `on_llm_start`/`on_llm_end` and a `get_langchain_handler` — and it is currently a thin bridge that feeds metrics and the audit log, **not** the ledger and **not** enforcement |
| **L3 — native budget, checkpoint, resume** | per-node budgets enforced by the framework's own scheduler; a killed run resumes from the checkpointer; the ledger records a *node*, not a request | this is the only level at which auto-kill becomes safe, and the only level at which the ledger stops being an HTTP log and starts being a work log |

**The repo's own commitments.** `PLAN.md:934` lists the post-48h backlog item as
"Framework adapters with **real** enforcement: LangGraph, CrewAI, OpenAI Agents
SDK, Vercel AI SDK", and `PLAN.md:505` commits to seeding public GitHub issues
for the LangGraph, CrewAI and OpenAI Agents SDK adapters. `PLAN.md:958` records
that issues **#6-#9** were seeded. So **three of the four seeded issues are
framework adapters** and the fourth is `good first issue` — which is consistent
with the brief's statement that **#6, #7 and #9 are LangGraph, CrewAI and the
OpenAI Agents SDK**. The issue-number-to-framework mapping is taken from the
brief: I cannot read the live issues from this worktree and the tree only records
the range and the one `good first issue` marker. What the tree does establish is
the *set*: four issues, three of them framework adapters, matching a backlog
line that names four frameworks.

**Consequence for the order, which is a real constraint and not a preference:**
LangGraph, CrewAI and the OpenAI Agents SDK are already public commitments. If
the first two shipped integrations were Mastra and Vercel AI SDK — both
TypeScript, both not on that list — the repo would be shipping against its own
public roadmap and would have to explain why. **Ship LangGraph and CrewAI first,
and ship them for the reasons above, which happen to coincide.**

**Where the seam is, exactly.** One line in the transport is the whole story:
`_record_spend_if_enabled` at `transports.py:195`, gated on
`config.ledger_enabled or config.detection_enabled` (`transports.py:214-216`).
An L2 adapter's job is to set the ambient `Attribution` (the `ContextVar`, one
`set`/`reset` per node — `ledger/context.py:60,99,158`) and to scope a budget. If
the integration is anything more than that, it is re-implementing the transport,
and it will drift.

---

# 3. The coding-agent harness question

**This is the most important section in this document, and the answer is no.**

## 3.1 The setup

Claude Code, Codex, Cursor and OpenCode each **own the API key**. They
authenticate to the provider themselves, from a credential the end user
configures, and the model calls are made by the harness's own HTTP layer. A
library that intercepts an SDK client cannot intercept these, because there is
no SDK client to intercept.

## 3.2 Can Backstop wrap them? The four honest answers

| mechanism | verdict | reasoning |
|---|---|---|
| wrap the SDK client | **no** | there is no client object in the user's process that the harness will route its calls through |
| `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` redirection | **technically yes, structurally no** | the harnesses generally do honour a base-URL override, and this is the standard enterprise egress pattern. But: (a) the key is still sent to the endpoint, so the proxy now holds a live credential; (b) the interception point is a *string in an environment variable*, which is a different, weaker, and more breakable integration than a constructor argument; (c) the harness's own retry, model selection, compaction and tool loop all sit *above* the proxy, so the ledger sees the model calls and none of the work. It is a **token** ledger, not a **task** ledger — exactly the gap in §5.4 of [04](04-detection-design.md) |
| OS-level egress interception (a local TLS-terminating proxy the harness is configured to trust) | **yes, and it is the real answer** | it does not need the harness's cooperation beyond a CA trust and a base URL. It is what every large shop already runs. **HYPOTHESIS:** it is a worse product than `wrap()` — it sees bytes, so it cannot see `SpendEvent` fields the SDK only populates (`cache_read_tokens`, `request_id`), it cannot attach a `ContextVar` attribution, and it is one config error away from silently recording nothing |
| drive the harness as a subprocess and parse its output | **no** | this is not an interception, it is a scraper. It cannot see the API calls at all, only the transcript. |

**The verdict, stated plainly: Backstop cannot wrap a coding-agent harness at the
transport layer, and the four answers above are the complete list of ways to try.**

## 3.3 Why this matters more than it looks

**The entire competitive set sits on top of these harnesses.** Every
observability and cost product aimed at coding agents — and they are the direct
competitors named in R1 and R2 of [07](07-risks-and-killshots.md) — gets its
data by one of two routes: it is what the harness itself emits (session logs,
OTel spans, a vendor API), or it sits on the egress and parses bytes. Neither
route is "wrap the client", because the harness does not use a client the vendor
can wrap.

That is the uncomfortable reading, and it is the honest one: **the fastest-growing
surface in the category is the one surface where this library's architectural
wedge does not apply.** `wrap()` works because the user's own code constructs the
SDK client. A harness is a closed application that constructs the client itself.

## 3.4 The adjacent plays

Three, in the order I would attempt them. All are **HYPOTHESIS**; none is
verified to be technically achievable from this repository today.

| play | what it is | why it is plausible | what it costs | what would kill it |
|---|---|---|---|---|
| **A. The egress proxy, as a first-class supported mode** | promote `backstop serve` (`src/backstop/gateway.py`, 117 lines, `fastapi` extra) from "optional sidecar" to "the supported way to cover harnesses and non-Python fleets", and make it emit `SpendEvent` records rather than proxying bytes | it is already written, already an OpenAI-compatible reverse proxy, and already honest about being a different mode with a real network hop (`README.md:229-235`). A gateway that writes a ledger is a different and more valuable product than a gateway that forwards | it sees bytes, so it reconstructs token counts from the response body — which is exactly the `estimated` / aggregate-only problem the schema already models. The `SpendEvent` fields the SDK populates are recoverable from the response body, so this is more tractable than it first looks | it has **no CI** — `fastapi` is not installed by the workflow (`docs/sdk-matrix.md:37-38`), so the gateway path is untested today (open item O19) |
| **B. A harness plugin / MCP server** | each harness that supports plugins or MCP gets a Backstop server that the agent calls as a tool, which reads the ledger and *advises* or *refuses* | MCP is supported by several of these harnesses and by Claude Code specifically. The plugin surface is a legitimate integration point, and it is where a "how much have I spent on this task, should I keep going" tool naturally lives | it is **advisory**. The model can ignore it, and a guardrail a model can ignore is not a guardrail. It is a *dashboard* integration, not an enforcement integration | if the harnesses' plugin surfaces do not carry a blocking hook, this is play C wearing a different hat |
| **C. The host-level agent budget** | not a wrapper at all — a policy the *user's* code and CI enforce: a pre-flight `backstop ledger` report, a CI check that refuses a merge that raises a token budget, a scheduled job that reads the ledger and pages a human | it is the only one of the three that needs nothing from the harness. It is also the least differentiated: it is the export, run on a schedule | it is a report, not a control, and the enforcement buyer will not pay for a report | it is what the product already is, minus the novelty. `backstop ledger export` exists (`cli.py:482-491`) |

**The recommendation: attempt A, and be explicit in the docs that the harness is
not wrapped.** `README.md:229-245` is already honest and should stay that way.
The wrong move here is to write a Node harness wrapper and discover in month
three that the harness moved its HTTP layer.

---

# 4. The finance-facing feature set

## 4.1 Built

| capability | status | where | the honest limit |
|---|---|---|---|
| **the chargeback schema** | shipped | `SpendEvent`, 18 wire fields, strict round trip (`03-attribution-and-schema.md`) | 3 of 6 declared `outcome` values are ever emitted; a pre-dispatch denial never reaches a provider and so never reaches the ledger |
| **the CSV export** | shipped | `build_chargeback` + three writers, `ledger/export.py:817, 1024, 1050, 1411` | 13 columns + group keys; RFC 4180, money as 2-dp **strings** so a spreadsheet never reinterprets it |
| **the revenue join** | shipped | `revenue_join` / `RevenueRow` / `write_revenue_csv`, `export.py:1180, 1290` | it emits a second CSV on the same group keys. It does not become a revenue system and does not try to |
| **the unattributed-spend figure** | shipped | `unattributed_usd` / `unattributed_share` / `unattributed_share_basis`, `export.py:575-598`; surfaced in the demo at `01-north-star.md:61` | the share is computed on the **unrounded** totals, so dividing the printed dollars will not reproduce it — by design, and the basis string says so |
| **the unpriced-component figure** | shipped | `priced_components` per event, aggregated to `unpriced_components` per row, `export.py:178-193` | the schema has one `cache_write_per_mtok_usd` and Anthropic publishes two tiers, so a 1-hour-TTL deployment under-counts cache writes **and `priced_components` cannot reveal it** (open item O11) |
| **the delivery / loss report** | shipped | `delivery_report`, `CloseReport`, `lost` / `drained`, `export.py:1661`; `task-8-report.md:568-600` | a file read reports `dropped_events` and `sink_errors` as **unknown, never as zero** (`export.py:1724`) |
| an unattributed / unpriced **row label** | shipped | `UNATTRIBUTED = "(unattributed)"`, `export.py:108-111` — "loud, greppable and non-empty" | — |
| determinism | shipped | `backstop ledger demo` is byte-identical across runs, keyless, offline | fixed synthetic traffic; it is a pitch artefact, not a measurement of anyone's spend |

## 4.2 Missing

| # | missing | what it is | why it is on this list | effort (**HYPOTHESIS**) | blocked by |
|:-:|---|---|---|---:|---|
| **M1** | **the time series** | today `build_chargeback` takes a `Period` (`export.py:231`) and returns one table per call. There is no series, no per-day or per-hour trend, no "spend by day" output at all | a chargeback is a point in time; a finance review is a movement. The demo emits one day (`01-north-star.md:44`) | **2-3 d** | nothing. `Period` and `_next_day` / `_next_month` (`export.py:310, 317`) already exist and are unused for this |
| **M2** | **forecasting** | §5 below | agent workloads are not forecastable by a trend line | **10-15 d** | needs M1 and a defensible conditioning set |
| **M3** | **margin per feature as a product surface rather than a join** | `revenue_join` produces a *second CSV* keyed on the same group keys, and the join is the customer's to perform | the join is the right boundary for v1 and the wrong boundary forever. A CFO does not want a CSV to join; they want margin. But the moment Backstop computes margin it owns a revenue number, and a wrong revenue number is worse than a wrong cost number because revenue is a *decision* input | **5-8 d** plus the M1 time series |
| **M4** | **budget policy as a finance-owned artefact with an approval workflow and an audit trail** | today a budget is `BackstopConfig(budget=…)` in a deployment's config. It is an engineer's number, set in code, with no author, no date, no approver, no history, and no way to change it for next quarter without a deploy | this is the single largest gap between "an engineer's guardrail" and "a finance control". A budget nobody approved and cannot audit is not a control, it is a default. The `AuditLog` HMAC chain (`audit.py:20-22`) is the right substrate and it exists | **8-12 d** | needs M1 (a policy has to reference a period) and a store |
| **M5** | **invoice reconciliation** | today the ledger is compared *to* the user's own revenue (`revenue_join`). It is never compared *to the provider's invoice* | this is metric **M1** in [01-north-star.md](01-north-star.md), and it is the only metric that cannot be gamed. It also needs an invoice in a machine-readable form, which is a procurement question, not an engineering one | **5-8 d** for the comparison, plus an invoice ingest that is a separate problem |
| **M6** | **cross-process aggregation** | `ledger_path` is one NDJSON file per `BackstopState` (`config.py:203`). Forty services is forty tables and no total (R9 in [07](07-risks-and-killshots.md)) | a CFO with forty services cannot use the product today. This is the gap R9 calls `not survivable` if the product is sold into shared platforms | **2 d** for a merge read (accept many paths / a glob), more for a real store | nothing |
| **M7** | **a real token split for streams** | every streaming request is recorded `estimated=True` at stream setup, so every streaming deployment's chargeback is a **floor** (open item O12) | for a chat-heavy product this is most of the traffic, and a floor is not a number finance can sign | **2-3 d** | it changes the event count per stream, which is the contract the export is written against |

**The order, if there is a budget for exactly one: M6, then M1, then M7.**
M6 is 2 days and it is the difference between usable and unusable for any
multi-service deployment. M1 is what makes the product a review rather than a
report. M7 is the difference between a floor and a measurement for a large
fraction of deployments. M4 is the strategically important one and it is also the
most expensive, which is the tension the boundary in §6 has to resolve.

---

# 5. Forecasting

## 5.1 What is forecastable and what is not

This section is mostly **HYPOTHESIS** and the reason is structural, not
cautious.

**Agent workloads are bursty and recursive.** One goal can fan out to thousands
of subtasks. A research run is 20 minutes of intense tool use and hours of
waiting. Each turn appends the last turn, so input tokens grow smoothly and
monotonically *within* a run. `04-detection-design.md` §5.3 works through three
specific ways this breaks a rolling model. **Naive linear forecasting will be
badly wrong**, and the error will be *optimistic* in the dangerous direction —
under-predicting a fan-out that has not started yet.

The repository already has the thing that makes this obvious: `forecast.py` is a
**linear** projection (`project_remaining_seconds` = `remaining / rate_per_sec`,
`src/backstop/forecast.py:26-30`), and `docs/compatibility.md` lists "Cost
forecasting → enforcement | Supported". **That is true of the function and false
of the use.** A `rate_per_sec` measured over the last window, projected forward,
is exactly the estimator that gets a recursive fan-out wrong.

## 5.2 What a forecast must be conditioned on

A forecast is `E[cost | conditioning]`. The conditioning set is the whole design.
Five things, and each one is currently absent from the record:

| conditioning variable | what it changes | in the record today? |
|---|---|---|
| **the run's position in its own lifecycle** | a research run's cost is dominated by phase, and phase 3 (synthesis) is not phase 1 (search) | no. Nothing records a run's identity, let alone its phase |
| **declared intent — a budget, a deadline, a task size class** | "this run was told to spend at most $20" bounds the forecast from above and is already the number the enforcement buyer thinks in | no. A budget is in `BackstopConfig` on the process, not on the run |
| **traffic shape, not level** | a fan-out run's cost grows with *breadth*; a single-stream run's grows with *depth*. Mean and variance of the event stream are different quantities | partially: `distinct_model_ratio` exists and is unused; nothing measures breadth or depth |
| **the cohort's own history** | the only defensible estimator without any of the above is "what did runs like this one cost last month", which needs a task-type label | no |
| **an explicit confidence, and a refusal** | a forecast without a stated confidence is a lie with a decimal point | no |

## 5.3 What I would refuse to forecast

Stated as refusals, because a refusal is a design decision and an omission is
not:

1. **A forecast for a run that has produced fewer than N completed comparable
   runs.** N is unknown (**HYPOTHESIS**: something in the low tens). Below it,
   the honest output is "not enough history", and that string has to be a real
   possible output of the API, not an error.
2. **A single point estimate, ever.** Interval or nothing. A point estimate
   invites a decision that the number cannot support, and in a budget context a
   confident wrong number is worse than no number because it gets spent.
3. **A forecast for a run whose spend is dominated by unpriced or estimated
   components.** `unpriced_requests` and `estimated_requests` are the honest
   signals here (`export.py:186-187`), and a forecast computed on top of a floor
   is a forecast of a floor. The forecast should **degrade its own confidence
   using the same columns the export already prints** — which is a nice
   property, because the mechanism exists.
4. **A forecast that crosses a fan-out boundary without saying so.** If breadth
   in the window is growing, the forecast must widen or refuse; extrapolating
   from a narrowing window into an expanding one is the specific failure that
   makes a linear projection dangerous.
5. **Anything a finance team would put in a budget document on the strength of
   the number alone.** Which means the output has to carry the conditioning set
   and the confidence next to the estimate, always, in the same row — the same
   rule the export follows with the honesty columns, and for the same reason.

---

# 6. Dashboards versus exports versus API

## 6.1 The hypothesis

**HYPOTHESIS: finance consumes exports into their existing BI or ERP, and will
not adopt another dashboard.**

The reasoning, and it is the same reasoning as the `revenue_join` boundary in §4:

- The finance team's system of record is already installed, already reconciled
  against the provider's invoice, and already has a chart for everything. Adding
  a second dashboard does not remove a step; it adds one.
- **Backstop has no identity, no SSO and no access story.** The dashboard is a
  stdlib ops surface over in-process state (`dashboard_app.py`, `dashboard_ui.py`,
  `telemetry.py`), and the one place a user identifier now enters an
  operator-facing payload is the detection key (`task-8-report.md:723-728`).
  Handing that to a finance org is a security review, not a demo.
- The ledger's value is **the numbers joining to something the CFO already
  trusts**. A CSV joins. A dashboard does not.
- A finance team that *does* want a dashboard will build it on the CSV, in the
  tool they already have, in an afternoon. That is not a lost sale; that is the
  product working.

## 6.2 What I would build, in this order

| surface | verdict | effort (**HYPOTHESIS**) |
|---|---|---:|
| **exports** | **build.** The three CSV writers exist (`export.py:1024, 1290, 1050`); what is missing is M1 (the time series) and M6 (multi-file merge) | 2-4 d |
| **an API** | **build, but read-only and boring.** A `GET /chargeback?group_by=&period=` over the same `build_chargeback`, so a customer's BI tool can pull rather than scrape a file. It is the same calculation with a different serialiser, and it is a *customer-hosted* API, not ours | 3-5 d |
| **a dashboard** | **do not build a finance dashboard.** The existing ops dashboard is a different product for a different reader (an engineer looking at a live process) and it should stay that way. If a customer asks for a finance dashboard, the answer is the export plus a 20-line snippet | 0 d |

## 6.3 What would falsify it

Stated in advance, because a hypothesis with no falsifier is a belief:

| observation | what it would mean |
|---|---|
| two or more customers ask for hosted, authenticated, per-team views **and** have a BI tool they are unwilling to put this in | the hypothesis is wrong for a subset of the market, and the honest response is a read-only customer-hosted API, not a SaaS |
| a design partner's finance lead says "we cannot get this number into NetSuite without a UI" | the join boundary in §4 is wrong and margin-per-feature has to be ours (M3) |
| the same team runs the ledger for **several** internal entities and needs per-entity isolation | this is R9's `not survivable` case and it forces the multi-tenancy story, not the dashboard |
| adoption stalls at the engineer who cannot get a budget number past a finance review | then the product has one buyer, not two, and R11 in [07](07-risks-and-killshots.md) is the answer rather than a roadmap |

---

# 7. The OSS / proprietary boundary

## 7.1 The ruling I would defend

**MIT stays MIT: the enforcement library, the ledger core, the export, the
schema, the price catalog, the detector.**

**Paid: the multi-tenant cloud, the cross-customer benchmark, forecasting, and
the finance workflows (M1-M5).**

## 7.2 Defended line by line

| capability | licence | the argument |
|---|---|---|
| enforcement (`wrap`, budget, circuit, retry, AIMD, admission, cache, agent guard) | **MIT** | it is the adoption mechanism and the credibility mechanism. A guardrail you have to licence cannot be the thing a security team approves. Charging here also poisons the wedge: the first thing anyone does is `pip install` and evaluate |
| `SpendEvent` / `Attribution` / the wire format | **MIT** | a format that is proprietary is a format nobody can build a competitor's importer for, and a format nobody can import is not a standard. The strict round trip and the "a missing value is never a blank cell" rule (`export.py:20-23`) are *more* valuable as an open standard than as a moat |
| `pricing_catalog.py` and the bundled rate card | **MIT** | same, and stronger: the credibility claim in [01](01-north-star.md) is that a missing price is visible. A vendor that hides its price card is contradicting its own product claim on the one point finance cares about |
| the ledger sinks and the JSONL format | **MIT** | a customer must be able to leave. If the ledger file is only readable by us, the customer has not escaped the vendor, and the OSS distribution is a trial, not a distribution |
| the chargeback CSV, the revenue join, the delivery report | **MIT** | this is the product's whole claim to finance, and a paid CSV means the wedge demo is a lie. It is also the thing most likely to be screenshotted into a budget meeting, and screenshots are the acquisition channel |
| `backstop ledger demo` | **MIT** | ditto |
| the detector, in shadow mode | **MIT** | the shadow log is the tuning evidence. Charging for the evidence that tunes the free thing is the fastest way to stop anyone running it |
| the multi-tenant cloud (M6 as a service, not as a merge-read) | **paid** | this is a hosting and access-control product. It is also the thing R9 says is `not survivable` to skip if we sell into shared platforms |
| the cross-customer benchmark | **paid** | the moat in [01](01-north-star.md), and it is explicitly **HYPOTHESIS** at three points: legal, technical and trust. The third is the one I hold least confidence in — "finance teams will not send their cost structure to a vendor they have not bought anything from". **Selling it before the trust problem is solved would destroy the OSS distribution's credibility to buy a feature nobody has asked for** |
| forecasting (M2) | **paid** | it is the highest-effort, highest-uncertainty item on the list, it needs data the OSS product does not collect, and getting a forecast wrong in a budget document is a liability. It is also the most obviously "vendor" thing on the list, which makes it a good paid anchor |
| finance workflows M3/M4/M5 | **paid** | budget policy with an approval workflow and an audit trail is a *control*, and a control is bought, installed, supported and liable for. Margin per feature means owning a revenue number. Invoice reconciliation means being the thing that says whether the provider's bill is right |

**The one-line test I would use for anything new:** *does the free tier make
Backstop the obvious choice for an engineer, and does the paid tier make it the
only choice for a finance team?* If a proposed feature fails both halves, it is
a feature neither buyer wanted.

## 7.3 The sibling-project question

**The setup.** The user has another project that already promises an optional
cloud tier for shared policy versioning, live compliance feeds and audit trails.
Those three are not a small overlap with §7.1's paid column: *shared policy
versioning* is a control plane (which `docs/architecture.md:125-131` explicitly
says does not exist today), *live compliance feeds* is a benchmark-plus-alerts
product, and *audit trails* is the M4 budget-approval substrate.

**One product, two products, or a platform with two entry points.** My
recommendation is the third, and the reason is specific rather than diplomatic:
**the two projects have different data and the same buyer.**

| | this repo | the sibling |
|---|---|---|
| data | per-request priced spend events, a file the user owns | policy versions, compliance status, audit records |
| unit | a request | a policy or a control |
| buyer | a finance lead who wants a number | whoever owns the control, probably engineering leadership or a risk function |
| MIT core | yes, non-negotiable | unknown from here |
| overlap with the paid column | — | all three named features |

The three options:

| option | what it is | argument for | argument against |
|---|---|---|---|
| **one product** | merge, MIT enforcement + ledger + a paid cloud for both | one name, one sales motion, one roadmap. The data composes: "policy says team A gets $20/day, the ledger says team A spent $31" is a single product | the MIT core has to stay MIT and the cloud has to serve both readers, which means two UIs and two sales motions under one roof. And the trust objection in §7.2 gets *worse*, not better: a finance buyer now has to trust a vendor that also sells them policy management |
| **two products** | stay separate, share nothing but a name | each is simple, each has one buyer, each has one licence posture. No shared-data problem | duplicated enforcement and duplicated policy language. The "policy says $20/day, ledger says $31" join never happens, which is the most valuable sentence in the whole combined product |
| **a platform with two entry points — recommended** | one shared, versioned **policy and audit** substrate, and two front doors: the OSS library (MIT, in-process, spends money and writes a file) and a paid cloud (policy versioning, compliance feeds, cross-customer benchmarks, the finance workflows). The sibling's optional cloud tier becomes the platform; this repo's OSS core becomes one entry point into it | the data composes and the join happens, without putting a cloud dependency in the MIT path. The finance buyer gets the ledger, the control-plane reader gets the policy, and the one sentence that ties them together is the product. Licence posture stays clean: the core that has to be free is exactly the core that has no policy state in it | it requires one roadmap and one honest conversation about who owns the shared substrate. It is also the option most likely to be avoided by accident, by letting both projects ship their own cloud tier independently and ending up with two half-platforms |

**Recommendation: the third, with one condition.** The condition is that the
shared substrate is **policy and audit, not spend**. Spend events are
per-request, high-volume, and joined to a provider invoice; policies are
low-volume, versioned, and approved. Putting spend in the shared substrate would
mean the finance data and the control data have the same access story, and R9's
`not survivable` multi-tenancy problem would arrive attached to both.

---

# 8. Pricing shape

## 8.1 The five candidates

| shape | how it scales | the argument against |
|---|---|---|
| **per seat** | with humans | the enforcement buyer is an engineer who will not accept a per-seat charge for a library, and the ledger buyer is not a seat at all. It prices the wrong unit twice |
| **per host** | with machines | rewards horizontal scaling, punishes consolidation, and has no relationship to either the spend managed or the seats who care |
| **per agent** | with agent count | "agent" is undefined. A cron job is an agent. A 200-node fan-out is 200 agents or one, and the vendor picks. **HYPOTHESIS: undefined units are how pricing disputes start** |
| **per dollar of spend managed** | with exactly the thing the product is about | the incentive-alignment problem, below |
| **flat platform fee** | with nothing | uncorrelated with value, and it punishes the customer whose problem got worse |

## 8.2 The recommendation

**A flat platform fee on a metered *count* of something that is cheap to count
and expensive to fake, with spend NOT in the price.**

Concretely, three tiers on one axis — **managed services** (distinct hosts, or
distinct CI jobs, whatever a deployment actually enumerates) — and the paid
finance features attached to the tier, not metered separately. Percentage of
spend is a **separate, optional, capped add-on** if it is offered at all, and
§8.4 says how to structure it.

The reason: **the thing Backstop is for is a finance team learning a number they
cannot currently compute.** The value of the product is not proportional to the
spend; it is proportional to the *absence* of the number. A team spending $200 a
month with no cost attribution is the ideal customer and a percentage-of-spend
price charges them almost nothing. A team spending $2M a month already has a
cost dashboard and is a worse customer. **Percentage of spend prices the
customer backwards.**

## 8.3 The incentive-alignment argument for a percentage of spend

It is a real argument and it deserves stating at full strength:

- The vendor's revenue then rises with the customer's value delivered — more
  agents, more spend, more ledger rows, more reasons to keep it.
- It is self-aligning in the way per-seat never is.
- It is easy to explain and easy to budget against.

## 8.4 Why finance is scared of it, and how to defuse that

The objection, in the words of the person who signs:

> "If your revenue is a percentage of what I spend, the day inference gets
> cheaper you get poorer for the same service, and the day my bill goes up by
> $10,000 I have to ask whether that is a real cost or your price. I am being
> asked to trust a vendor whose income I cannot audit independently."

That is the same trust problem as the cross-customer benchmark in
[01-north-star.md), and it is the hardest one there. **HYPOTHESIS:** a finance
team's aversion to percentage-of-spend is close to absolute and is not a pricing
problem to be negotiated, it is a category problem.

Four structural defuses, in the order I would apply them:

| defuse | mechanism | what it removes |
|---|---|---|
| **1. Never make it the headline** | the base price is a flat platform fee. A spend percentage is an add-on a customer opts into *after* the ledger has already reconciled to an invoice once | the incentive conflict is opt-in and secondary, so the default purchase is a purchase a finance team can defend internally |
| **2. Cap it, hard, and publish the cap** | `min(0.5% of managed spend, $X/month)`, with the cap in the contract | the "your bill went up so the vendor got paid" failure is bounded by a number the customer wrote down |
| **3. Make the rate *decrease* with volume** | tiered: 1.0% above $10k/mo, 0.5% above $100k, 0.25% above $1M | the vendor's revenue grows sub-linearly with spend, so the customer's cost control is not in tension with the vendor's. **This is the only structure where the two interests point the same way, and it is the argument to lead with** |
| **4. Make the counter-price legible** | the fee is computed on **the ledger's own total**, from the same CSV the customer already accepted into a budget, and the invoice shows the figure the customer can recompute | the vendor's income is auditable by the customer using the vendor's own export. That is the only thing that makes the arrangement survivable in a procurement conversation |

**The honest summary of §8:** the percentage-of-spend argument is good for the
vendor and bad for the buyer, and the whole job is to structure it so the
buyer's downside is bounded and checkable. Defuse 3 is the one that actually
works; 1, 2 and 4 are what make it presentable.

---

# 9. FACT and HYPOTHESIS

## FACT — read out of this repository, or measured

| claim | evidence |
|---|---|
| A TypeScript package is published, at the same name and version as PyPI | `ts/backstop/package.json:2-3`; `PLAN.md:968-970` |
| It intercepts `create`, not the transport; 5 priorities, not 3; `critical` and `high` bypass the budget | `wrap.ts:96, 108`; `types.ts:1`; `config.py:29-31` |
| It has no metrics, OTel, Redis, hierarchical budgets, ledger, price catalog or detector | `grep -rln "prometheus\|metrics\|otel\|redis" ts/backstop/src/` returns nothing; `index.ts` is 21 lines |
| It **does** have an HMAC audit chain with `verify()` | `ts/backstop/src/audit.ts`, 70 lines, read in full |
| It has a latent `ReferenceError`: `require("node:fs")` in an ESM package | `audit.ts:34` vs `package.json:5` and `tsconfig.json` `"module": "ESNext"` |
| It has no CI; CI is Python-only | `docs/sdk-matrix.md`; `.github/workflows/ci.yml` |
| 989 TS source lines against 19,176 Python | `wc -l` |
| There is **no Rust, no Go and no Java** anywhere in the tree | no `Cargo.toml`, `*.rs`, `go.mod`, `*.go` |
| `src/backstop/adapters/` exists with a `BackstopAdapter` and a LangChain handler, and it feeds metrics and audit — not the ledger, not enforcement | `adapters/__init__.py:15-36` |
| The README already concedes SDK-level-only framework support | `README.md:245` |
| `backstop serve` is a 117-line OpenAI-compatible reverse proxy behind the `fastapi` extra, and it is never exercised by CI | `gateway.py`; `docs/sdk-matrix.md:37-38` |
| `forecast.py` is a **linear** rate projection | `forecast.py:26-30` |
| The chargeback export has 13 columns + group keys, three CSV writers, a revenue join, and a JSONL reader | `export.py:178-193, 1024, 1290, 1511` |
| `Period`, `_next_day` and `_next_month` already exist and no time series uses them | `export.py:231, 310, 317` |
| The four honesty columns exist and are computed from the record the tool wrote | `export.py:186-187, 575-598` |
| The architecture doc opens its control-plane section with "Nothing in this section exists today" | `docs/architecture.md:125-131` |
| GitHub issues #6-#9 were seeded; #8 is `good first issue` | `PLAN.md:958` |
| The post-48h backlog item is "Framework adapters with **real** enforcement: LangGraph, CrewAI, OpenAI Agents SDK, Vercel AI SDK" | `PLAN.md:934` |

## HYPOTHESIS — believed, not proven

| claim | what would have to happen to prove it |
|---|---|
| TypeScript, then Go, then Rust, then Java is the right order | the first three inbound enterprise conversations. **This is a market forecast with no data behind it in this repository** |
| Node/TypeScript is where the agent money is | one datapoint. There is none in the tree |
| LangGraph first because its checkpointer unblocks resumability | a written contract against the framework's current release. CrewAI having no interrupt primitive today is **unverified** |
| Backstop cannot wrap a coding-agent harness at the transport layer | this one I hold with high confidence, from the harness architecture rather than from a measurement. The falsifier would be a harness that constructs its client from a module a library can patch — none of the four does |
| The egress-proxy play is technically achievable at ledger fidelity | writing the `SpendEvent` from a byte-level proxy and showing the `cache_read_tokens` and `request_id` recovery |
| An MCP plugin surface can be blocking rather than advisory | a harness plugin API with a hard-deny hook. **Unverified for all four harnesses** |
| Finance uses exports into their existing BI/ERP rather than adopting a dashboard | two design partners saying the opposite, out loud, in a budget conversation |
| MIT core / paid cloud is the right boundary | a competitor's licence and a customer's procurement objection |
| The platform-with-two-entry-points answer to the sibling project | one conversation with the user about who owns the shared substrate |
| A flat platform fee on managed services beats every per-unit shape | five pricing conversations. The reasoning is about definition risk, not about arithmetic |
| Percentage of spend can be structured so finance accepts it | a procurement review. I hold this one at **low** confidence and §8.4 says why |

---

## What this document is not

It is not a commitment to any of it. Areas D, F and G have no definition in this
tree, the language order is a forecast with no data behind it, the framework
choice is constrained by public commitments rather than by merit, and the pricing
argument in §8 is the part of this document I hold with the least confidence. The
one thing here that is not a forecast is §3: **Backstop cannot wrap a coding-agent
harness at the transport layer**, and the competitive set knows that, which is
worth more attention than the rest of this roadmap combined.
