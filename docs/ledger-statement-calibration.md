# Statement calibration — what the providers actually publish

The reconciliation parser's column names were transcribed from published
reporting surfaces and had never been read against a statement. This records
what the providers actually document, checked against their own documentation
rather than inferred. Two real defects came out of it, and one premise this
module was built on turns out to be **contested**.

Sources, checked 2026-09-27:

- OpenAI, *How to use the Usage API and Cost API* —
  `developers.openai.com/cookbook/examples/completions_usage_api`
- OpenAI, *How do I export monthly usage details from the API Usage Dashboard?* —
  `help.openai.com/articles/20001072`
- Anthropic console cost/usage reporting; the Cost and Usage Reports Admin API
  as described by Elastic and Honeycomb's Anthropic integrations

## Defect 1: the one column OpenAI actually publishes was missing

OpenAI's Costs API returns `start_time`, `end_time`, **`amount_value`**,
`currency`, `line_item`, `project_id`. The parser's accepted spellings for a
charged amount were `cost_usd`, `total_cost_usd`, `charged_usd`, `amount_usd`,
`cost` — so the real column was refused and the parser demanded a field that
does not exist. `amount_value` is now accepted, first.

## Defect 2: no provider ships tokens and money in one file

This is the structural one, and it invalidates an assumption the module's
docstrings state plainly.

| provider | tokens | money |
|---|---|---|
| OpenAI | `GET /v1/organization/usage/completions` | `GET /v1/organization/costs` |
| Anthropic | `GET /v1/organizations/usage_report/messages` | `GET /v1/organizations/cost_report` |

Both are separate endpoints, and both providers' dashboard exports are separate
downloads — OpenAI's Export dialog offers an **Activity data** tab and a **Cost
data** tab. A cost export carries an amount and no token categories at all, so
provider detection, which works off the token category names, could not see one:
it reported "cannot tell which provider's statement this is", which is true and
useless to someone holding a legitimate export.

A cost-only export is now named for what it is, with the endpoint to fetch
alongside it, and the refusal says plainly that this module does not yet join
the two. That is a real capability gap, not a parsing bug.

## Finding: the statement *can* tell you the cache tier — the ledger cannot

Anthropic's usage report separates cache creation by TTL:
`cache_creation.ephemeral_5m` and `cache_creation.ephemeral_1h`, with matching
token fields `cache_creation_5m_input_tokens` and
`cache_creation_1h_input_tokens`.

So the 37.5% under-count the ledger documents is **detectable from a
statement**: a row whose 1h cache-creation tokens are non-zero has a
corresponding ledger row priced at the 5-minute tier, and the gap is
computable rather than hypothetical. The ledger still cannot see the tier
during recording, because it does not observe the request's `cache_control`. The
reconciliation is the place this becomes visible, and closing the loop there —
flagging a model whose 1h cache writes explain its variance — is the obvious
next piece of work.

## Contested premise: is Anthropic's `amount` in cents?

This module refuses to read a bare `amount` column, on the stated ground that
Anthropic's cost report is denominated in cents and reading it as dollars is a
100x error. The sources disagree:

| source | what it says `amount` is |
|---|---|
| Elastic, Anthropic metrics | "Cost amount in **lowest units (e.g. cents)**" |
| Honeycomb, Anthropic usage | "Cost amount in **minor currency units**" |
| A monitoring-vendor walkthrough | "returns each amount as a **decimal string in USD**" |

Two of three say minor units; one says USD. **This has not been resolved, and
the refusal stands**, because refusing a column whose units are uncertain is the
safe side of a 100x error. But it is a refusal built on a contested premise, and
it should not be described in the code as though it were settled fact. Resolving
it needs one real statement: run a request worth a known number of cents and
read what the cost report says.

## Also worth knowing

- **Anthropic's cost rows are not all token costs.** `cost_type` covers
  `tokens`, `web_search`, `code_execution` and `session_usage`. A cost row with
  no tokens is not a parser error, it is a non-token charge, and a reconciler
  that expects token counts on every row will report it as a variance.
- **Anthropic's cost report may carry no model dimension at all** — one
  integration vendor reports the cost table as "only amount and currency",
  making per-model attribution impossible from that table. Per-model
  reconciliation against Anthropic may therefore not be achievable, only
  per-account. The reconciler already refuses to net a model across providers;
  this is a different, harder limit.
- **OpenAI's invoice-reconciling export is grouped by line item**, not by model
  (`Group by: Line item` in OpenAI's own instructions for reconciling to the
  invoiced amount). The reconciler is per-model, so a line-item-grouped export
  will not map onto its rows one-to-one.
- **OpenAI stops putting detailed API costs on invoices** for Enterprise
  customers on invoices issued from 2026-04-01, replaced by this export flow. So
  "reconcile against the invoice" is becoming "reconcile against the export",
  and a tool that only reads an invoice line will stop working.

## What this means for the launch

`backstop reconcile` is **not** calibrated. It parses a single file that no
provider actually publishes. The honest claim is narrower: it will parse a
statement in the documented shape, it reports the columns it read so a reader
can check them, and it refuses rather than guesses. The gap between that and
"reconciles against a real invoice" is a join across two exports per provider,
which is not built.
