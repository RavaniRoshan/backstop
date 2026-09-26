# 01 — North star

## The product, in one sentence

`backstop` is an in-process enforcement library for the OpenAI and Anthropic
SDKs that, as a side effect of the traffic it already mediates, produces a
durable, priced, attributed spend ledger a finance team can charge back.

## The buyer — there are two, and they are not the same person

| | enforcement | ledger |
|---|---|---|
| buyer | the engineer who owns the agent | the finance/ops person who owns the invoice |
| trigger | "an agent loop burned $400 overnight" | "I cannot tell which team spent $61,000 last quarter" |
| what they are shown | `Backstop.wrap(client, budget=50_000)` | `backstop ledger export --path ledger.jsonl --out chargeback.csv` |
| what "working" means to them | the loop stops | the number joins to the invoice |
| who signs off | one engineer | a finance lead, who is not in the code review |
| what would make them churn | an SDK major breaks the transport | a total they cannot reconcile |

Saying this plainly matters because the two have different failure tolerances. An
engineer tolerates a guardrail that is occasionally conservative. A finance team
tolerates nothing: one wrong number and the report is not opened again. The
ledger's design follows from that asymmetry — it never guesses a price, never
fills a missing token split, and reports the gaps it cannot close in columns
beside the money (`unpriced_requests`, `estimated_requests`,
`unpriced_components`, unattributed share) rather than in a footnote.

## The wedge — `backstop ledger demo`

Keyless, offline, deterministic, and it names what it could not measure.

```bash
$ pip install backstop-ai
$ backstop ledger demo
```

Real output, run just now on this branch (`env -u OPENAI_API_KEY -u
ANTHROPIC_API_KEY`), exit 0, 1.67-2.07 s, no network, no key, no file:

```
# Backstop Ledger — Chargeback

- **1967 requests** on 2026-09-26 (day 2026-09-26), priced from the bundled rate card effective **2026-09-26** (`price_source=bundled`).
- **Window:** 2026-09-26T00:00:00.000000Z → 2026-09-26T23:59:28.002464Z
- **Grouped by:** team, feature
- **Models:** claude-haiku-4-5, claude-sonnet-4-20250514, gpt-4.1, gpt-4o, vendor-preview-2027
- **Mode:** 100% offline. No API key, no network call, no live provider data, no file. The traffic is synthetic and fixed; every price and every dollar is computed from the bundled rate card with `Decimal` arithmetic.

| team | feature | request_count | input_tokens | output_tokens | total_usd | unpriced_requests | unpriced_components |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| payments | checkout-v2 | 388 | 8532297 | 278259 | 26.21 | 0 | cache_write |
| payments | refunds | 96 | 520529 | 101931 | 3.40 | 0 | (none) |
| support | triage | 240 | 516754 | 87934 | 1.76 | 0 | (none) |
| search | query-rewrite | 1140 | 741077 | 165354 | 1.65 | 0 | (none) |
| (unattributed) | (unattributed) | 69 | 396310 | 39882 | 1.54 | 0 | (none) |
| search | vendor-preview | 34 | 82143 | 11300 | 0.00 | 34 | (none) |
| **Total** | all | 1967 | 10789110 | 684660 | **34.56** | 34 | cache_write |

## What a CFO reads first

- **1.54 of 34.56 (4.45%) of priced spend is unattributed** — 69 of 1967 requests declared no `team` and no `feature`, so nobody can be charged for that money. It is one row in the table, labelled `(unattributed)`, and it is the row a pivot table drops. The share is computed on the exact totals — 1.539061 of 34.547570 to six decimal places — so dividing the rounded dollars above will not reproduce it exactly.
- **34 requests (1.73%) have no price at all** — `vendor-preview-2027` is not in the rate card. Their cost is *absent, not zero*, so every total above understates real spend by an unknown amount. A guess would make the number wrong in a way nobody could detect; this one is wrong in a way everybody can.
- 1 token component carries no published rate in this window (`cache_write`), so the requests that used it are charged zero for it and every affected row names the gap. Those lines are a floor, not a measurement. 9 of 1967 requests carry tokens Backstop estimated locally because the provider reported no usage, so their cost is a floor too. That count and the unpriced one are not disjoint: a request that is both estimated and unpriced is in each, and its cost is absent rather than a floor, which is the weakest figure in this report.

## Delivery (this process)

- submitted: 1967
- written: 1967
- landed (written less the sink's own losses): 1967
- dropped_events (writer buffer full): 0
- writer sink_errors (escaped the sink): 0
- sink sink_errors (counted by the sink): 0
- sink degraded: no
- **lost (dropped + writer errors + sink errors): 0**

This run lost **0** of 1967 events, counted from the live writer. Both counters matter and neither is written to a ledger file: a file read reports them as unknown rather than as zero.
```

Byte-identical across three consecutive runs (asserted in
`tests/test_ledger_export.py::test_ledger_demo_is_byte_identical_across_two_runs`,
and re-checked in a scrubbed `env -i` with `socket.socket` replaced by a raiser).

Why this is the wedge and not a chart: the three sentences under "What a CFO
reads first" are the pitch. Every cost-attribution tool eventually tells a
finance team a total. Almost none of them tell the same tool, in the same
table, that 4.45% of the money cannot be charged to anyone and 1.73% of the
requests have no price at all. That is a claim a demo can make and a competitor
with a dashboard cannot, because it is a claim about *coverage*, and coverage is
the thing nobody reports.

## The moat — cross-customer anonymised cost baselines

**HYPOTHESIS, in full.** Nothing in this repository collects cross-customer
data. There is no Backstop service (`docs/threat-model.md:22, 35-37`), the
ledger is a file the user owns, and the bundled rate card is a local constant
(`src/backstop/pricing_catalog.py:226, 420`). What is hypothesised is that a
sufficient population of opted-in deployments would produce a corpus of
per-model, per-workload-shape cost distributions that a single customer cannot
compute alone: "your `claude-sonnet-4-5` calls are running 2.4x the median
input token count for teams with your traffic profile", or "your cache-read
share is 4%; the median is 61%".

What has to be true for that to be offerable:

| dimension | what must be true | honest status |
|---|---|---|
| legal | the ledger record carries no prompt or response content, so the corpus is metadata (tokens, latency, outcome, model, price) and not customer data. `SpendEvent` has no content field and the JSONL line is 18 fields of measurement. | **FACT** for the record shape. **HYPOTHESIS** for the legal conclusion: whether an aggregated per-tenant cost distribution is personal data or trade-secret-adjacent in the relevant jurisdictions is a question for counsel, not for this document. |
| legal | opt-in, per-deployment, revocable, and revocable *retroactively* — a customer must be able to withdraw its history, which means the corpus must be reconstructable without any single customer's rows. | **HYPOTHESIS.** No such mechanism is designed. |
| technical | enough population for the median to mean anything. A distribution over "your traffic profile" is only useful above some N, and N is unknown. | **HYPOTHESIS.** No sample size, no density estimate, no nearest-neighbour analysis exists. |
| technical | the corpus has to survive rate changes, or it is measuring the rate card and not the workload. A bundle that is snapshotted at `effective_from = 2026-09-26` and never refreshed will make every baseline wrong within a quarter. | **FACT** that the card is a dated snapshot and nothing detects a rate change. **HYPOTHESIS** that this is fixable. |
| trust | finance teams will not send their cost structure to a vendor they have not bought anything from, especially an unknown OSS one. This is the same objection as the whole finance-buyer question, and it is the hardest one. | **HYPOTHESIS**, and the one I hold least confidence in. |
| trust | a benchmark that is wrong is worse than no benchmark, because it is *actionable* wrong. The moat only holds if the baseline is right; the ledger's own quality is the input. | see [07-risks-and-killshots.md](07-risks-and-killshots.md) risk 7 |

Honest summary: the moat is a plausible data advantage, gated behind a trust
problem that has nothing to do with data. If the trust problem is not solved,
the ledger is a good library and the baselines never happen.

## Exactly three metrics

Chosen because each is computed by something outside the vendor's own
discretion, so none of them can be moved by shipping a better README.

| | metric | definition | why it is hard to game |
|---|---|---|---|
| **M1** | **Ledger-to-invoice variance** | Per billing period, `abs(ledger total - provider invoice total) / invoice total`, per provider, per month. Reported alongside `unpriced_requests` and `estimated_requests`, never alone. | The provider's invoice is a third party we do not control and cannot edit. A variance can only be closed by recording what actually happened. The design helps rather than hinders it: no price is ever guessed, an unpriced request is a visible zero-dollar row rather than a default rate, and an estimated token count is flagged as such. If the ledger quietly substituted a plausible default price, M1 would look *better* while the product got worse, so M1 must always be read next to the honesty columns — which is why they are columns and not a footnote. |
| **M2** | **Spend coverage** | The share of a customer's LLM requests that appear as a **priced, measured, attributed** row: `1 - |unattributed ∪ unpriced ∪ estimated| / total`, computed per group per period from the export, and reported next to a separate per-component gap (`unpriced_components`). Measured on the demo's own window: 1,967 requests, 69 unattributed, 34 unpriced, 9 estimated, and the three sets are **not** disjoint — all 9 estimated requests are inside the 69 unattributed ones, so their union is 103, not 112, and coverage = 1 − 103/1967 = **0.9476**. A further 56 requests carry `cache_write` tokens against a model with no published cache-write rate, so their dollars are a floor on one component; that is a fourth gap, overlapping the first three, and it is reported as its own column. | Every component of the gap is computed by the tool from the record it wrote, and the tool is built so it **cannot** close any of them by configuration: `compute_cost` returns `None` rather than a default (`pricing_catalog.py:1012`), a missing token split is recorded as `estimated=True` with the floor rather than a fabricated split (`transports.py:372-399`), and a component with no published rate costs zero *and is named* via `priced_components` (`export.py:178-193`). A user cannot make the number better by turning on an option; only by actually attributing, pricing and measuring. Note the counting rule: the gap is a **union**, not a sum, because the three sets are not guaranteed disjoint. The demo says so in its own output and the demo's teardown names it (`src/backstop/ledger/demo.py:498`), and `tests/test_ledger_export.py:1120, 1157` pin that `estimated_requests` and `unpriced_requests` count the same population and may overlap. A metric that summed them would reward a customer for making its own report harder to read. |
| **M3** | **Ledger-attached revenue** | ARR from accounts where a finance-side owner has accepted at least one chargeback row into a budget or a reconciliation process, counted from signed invoices. Tracked separately from enforcement-only revenue. | It is money, and money is counted by someone else. It cannot be inflated by usage growth that never touches a ledger, by a free-tier count, or by an engineer-only deployment that produces no accepted report. It is also the only one of the three that tells us whether the two-buyer split is real or whether we have one buyer and a side feature. |

Targets for all three are **HYPOTHESIS** and deliberately absent. A target
published before the first real invoice is a number someone will be held to by
accident.

## FACT vs HYPOTHESIS

Ruthless about the column. If it was measured in this repository it is FACT. If
it is believed, it is HYPOTHESIS, even when it is probably true.

### FACT — measured in this repository

| claim | evidence |
|---|---|
| `backstop ledger demo` runs keyless, offline, deterministically, and prints a per-team, per-feature chargeback | run just now, exit 0, `src/backstop/ledger/demo.py`; byte-identity asserted in `tests/test_ledger_export.py` |
| The demo's window: 1,967 requests, 10,789,110 input + 684,660 output tokens, **$34.56** total across 6 groups | demo output above |
| The demo's honesty figures: **4.45%** of priced spend unattributed (69 requests), **34 requests (1.73%)** unpriced, **9 requests** estimated, `cache_write` unpriced for one group | demo output above; `export.py:178-193` |
| The three gap sets are **not disjoint in the demo window** (`unattributed ∩ unpriced = 0`, `unpriced ∩ estimated = 0`, but `unattributed ∩ estimated = 9` — all 9 estimated requests are inside the 69 unattributed ones), so the coverage union is exactly 103 of 1,967, not 112 → **0.9476**. A further **56** requests carry `cache_write` tokens against a model with no published cache-write rate | computed from `backstop.ledger.demo.demo_events()` just now. Of the 1,933 priced events, `input`, `output` and `cache_read` are priced on all 1,933 and `cache_write` on only 1,263 |
| The demo lost **0 of 1,967** events, with all three loss counters at zero and `sink degraded: no` | demo output above; `sink.py:86-102` |
| The ledger ships **disabled by default**. With it off, the whole per-request cost is one attribute load, two truth tests, one function call | `config.py:202`; `transports.py:214-216`; `test_a_ledger_off_request_costs_nothing_worth_measuring` |
| The default (ledger off) path costs **+3 to +5 us p50, about +2 to +3%**, versus the pre-task tree. p95 and p99 deltas are inside the noise | `task-6-report.md:322-334`, two independent 14-run alternating pairings |
| The opt-in (ledger on) path costs **+130.0 us p50, +84.6%** | `task-6-report.md:348-353` |
| Enforcement overhead, ledger off, stays in the sub-millisecond class: `backstop verify` reports p99 **0.229 ms** against a 5 ms threshold | run just now |
| `submit` against a deliberately stalled sink costs **0.851 us median** over 10,000 submits, and never blocks | `task-5-report.md:167-169` |
| The bundled rate card has **45 models** (29 openai, 16 anthropic), `effective_from = 2026-09-26`, `source = "bundled"`, `confidence = "list"` | `pricing_catalog.py:226, 420`; counted by import |
| Money is `Decimal` at exactly 6 dp under an explicit 28-digit context; a binary float is refused by name; a JSON number is refused on the way back in | `pricing_catalog.py:134`; `task-7-report.md:667-702` |
| Price precedence is 3 layers, resolved layer-major: per-call override > user catalog file > bundled | `pricing_catalog.py:1012`; `test_no_lower_tier_beats_a_higher_one` |
| The chargeback export has 13 columns plus the group keys, three CSV writers, a revenue join, and a JSONL reader that refuses to read past a corrupt non-final line | `export.py:178-193, 1024, 1180, 1511` |
| The reader reports a file's `dropped_events` and `sink_errors` as **unknown, never as zero**, because a JSONL line records an event and not a counter | `export.py:1724`; `test_a_file_read_says_both_counters_are_unknown_rather_than_zero` |
| 4,124 lines in `src/backstop/ledger/`, 1,165 in `src/backstop/detection/`, 1,061 in `pricing_catalog.py` — 6,350 lines added by this build | `wc -l` |
| 1,214 tests pass; 868 of them are in files this build created | run just now; per-file `--collect-only` |
| Two properties that must not be lost: `Backstop.wrap(client, budget=...)` is unchanged, and the ledger is opt-in | `test_one_wrap_call_still_works_with_the_ledger_off`; `config.py:202` |

### HYPOTHESIS — believed, not proven

| claim | what would have to happen to prove it |
|---|---|
| A finance team will accept a chargeback row into a budget | one real customer, one real period, one accepted number |
| The unbundled-vs-bundled trust objection is surmountable | see [07](07-risks-and-killshots.md) risk 5 |
| `claude-sonnet-4-5` at 3.0/15.0 per Mtok and `gpt-4o` at 2.50/10.00 are the rates these customers actually pay | a real invoice, or a negotiated catalog file. The bundled card is a transcription of two public price pages dated 2026-09-26, nothing more. |
| A CFO reads the honesty columns before the total | user testing. Nobody has been watched doing this. |
| The unbundled coverage is the differentiator against a provider dashboard | a provider shipping a coverage column would disprove it |
| Cross-customer baselines are legally, technically and trust-wise offerable | see the moat table above; all three are open |
| Inference prices keep falling at roughly 10x/year, so absolute spend falls even as token volume rises | this is the assumption that makes the whole category worth selling into, and it is an assumption about someone else's P&L |
| Enforcement and the ledger reinforce rather than compete | the two-buyer question in [07](07-risks-and-killshots.md) risk 11; unresolved |
| An engineer who adopts `wrap()` will later turn on the ledger | no funnel data exists |
| Anything about a target for M1, M2 or M3 | no customer has run a billing period on this yet |

## What this document is not

It is not a plan and it contains no dates. `docs/planning/_build-plan.md` is
the plan; this is the statement of what has to be true. The honest current state
is [00-current-state-audit.md](00-current-state-audit.md); the honest list of
ways this fails is [07-risks-and-killshots.md](07-risks-and-killshots.md), and
that document names five defects this build did not fix.
