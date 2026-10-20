# Dollar budgets

A token ceiling says how much **work** a session may do. A dollar ceiling says
how much it may **cost**. They are different questions, and for a team with a
budget only one of them is the question that was asked.

Two models that take the same number of tokens can differ in price twenty
times. A token ceiling cannot tell them apart, so expressing a money budget in
tokens means doing the conversion yourself — with a rate card that drifts, and
a conversion that is only as good as the last time you updated it.

```python
from decimal import Decimal
from openai import OpenAI
from backstop import Backstop

client = Backstop.wrap(
    OpenAI(),
    budget=50_000,                # tokens — unchanged
    budget_usd=Decimal("5.00"),   # dollars
)
```

A dollar ceiling is a **second** ceiling, not a replacement. A request is
admitted only if it fits under both.

---

## What it costs, and what it buys

A dollar ceiling cannot be enforced without measuring what each request cost,
so **enabling one turns the spend ledger on**. The cost of a dollar ceiling is
the cost of the ledger: roughly 17 µs per request today (8.19 µs to build the
spend event, 9.12 µs to price it), measured on Python 3.12 over 100,000
iterations. The full numbers and the reproduction script are in
[ledger.md](ledger.md).

That is a deliberate trade, and it is stated rather than hidden:

| | token ceiling | dollar ceiling |
|---|---|---|
| needs a price catalog | no | **yes** |
| needs the ledger | no | **yes** (it is what measures the cost) |
| per-request cost | a boolean test | ~17 µs |
| answers "how much work?" | yes | yes |
| answers "how much money?" | no | yes |

The ledger is off by default and stays off unless you ask for it — by setting
`budget_usd`, or by setting `ledger_enabled` yourself.

---

## How a request is measured

The estimate is priced from the **split** — input tokens at the input rate,
output tokens at the output rate — and not from a blended total, because the
two rates are often three or four times apart and a blend would mis-reserve in
both directions.

```
estimated cost = input_tokens × input_rate + output_tokens × output_rate
```

The reservation is settled against the **exact** cost when the request
completes, so the ceiling tracks reality rather than a running estimate. A
request that cost less than it was estimated at leaves the difference on the
ceiling; a request that cost more is reported, not hidden.

All money is `decimal.Decimal`, quantised to six decimal places with
`ROUND_HALF_UP`, computed under the ledger's own decimal context so the host
process's `prec` is never read. A `float` is refused outright:

```python
BackstopConfig(budget_usd=5.0)
# TypeError: budget_usd must be a Decimal, got float. A float cannot
# represent most fractions of a dollar exactly, and a ceiling that is a cent
# out is a ceiling that lets the wrong request through.
```

The shared Redis backend stores the amount in **integer micro-dollars** (a
millionth of a dollar), because Lua's `tonumber` is a double and a double
cannot represent most decimal fractions of a dollar exactly. The round trip is
exact:

```python
to_micro_dollars(Decimal("123.456789"))  # 123456789
from_micro_dollars(123456789)            # Decimal("123.456789")
```

---

## Models it cannot price

A model the catalog does not carry **cannot be measured against a dollar
ceiling**. A request for it would slip past unmeasured, and a ceiling with a
hole in it is not a ceiling.

So the default is to refuse it:

```python
from backstop.exceptions import PriceUnavailableError

# With budget_usd set and the model unpriced:
# PriceUnavailableError: model 'some-model' has no price in the catalog, so
# a dollar budget cannot be enforced for it.
```

The alternative is to say so explicitly:

```python
config = BackstopConfig(
    budget_usd=Decimal("5.00"),
    budget_usd_unpriced_policy="allow",   # let it through, record it unpriced
)
```

Under `"allow"` the request proceeds and the ledger records it as **unpriced** —
the same way it records every other request it could not price: a visible hole
rather than a plausible wrong number, counted in the export's
`unpriced_requests` column.

The choice is the deployment's, and it is a choice *with a name*, because
"it silently did not enforce" is not one.

---

## Per-tenant and hierarchical dollar ceilings

A tenant budget carries a dollar ceiling too, and it is checked under the same
lock as its token ceiling — so a request is admitted only if it fits under
both, as of the same instant.

```python
from decimal import Decimal
from backstop import Backstop
from backstop.ledger import TenantBudget, get_ledger, with_budget

org = TenantBudget("org", limit_tokens=10_000_000, limit_usd=Decimal("100.00"))
acme = TenantBudget("acme", limit_tokens=1_000_000, limit_usd=Decimal("10.00"), parent=org)
get_ledger().register({"acme": acme})

with with_budget("acme"):
    client.chat.completions.create(...)
```

The parent is reserved too, so a child's spend is always inside the parent's.
A parent that runs out blocks the child; a sibling is unaffected.

---

## Where the prices come from

One table, in
[`backstop.pricing_catalog`](../src/backstop/pricing_catalog.py): 45 models,
exact decimal rates per million tokens, with the source and the confidence of
every rate.

Three layers, highest first:

1. a per-call `price_overrides` mapping;
2. your own catalog file — `config.price_catalog_path`, a JSON file, read
   explicitly, checked for existence at construction so a typo fails at
   `wrap()` rather than silently pricing every request from the bundled table;
3. the bundled list prices.

Your file looks like this:

```json
{
  "effective_from": "2026-10-01",
  "entries": [
    {
      "model": "gpt-4o",
      "provider": "openai",
      "input_per_mtok_usd": "2.10",
      "output_per_mtok_usd": "8.40",
      "cache_read_per_mtok_usd": "1.05"
    }
  ]
}
```

Money is a **string** above all else. A JSON number would come back as a
binary float, and a price that lost its cents is a price that is wrong in a
way nobody can see.

A model name resolves through three documented tiers: the exact string, the
string with a trailing snapshot marker stripped (`-2024-08-06`, `-20241022`,
`-latest`), and a fixed alias map. A dated OpenAI snapshot, an Anthropic
`-latest` alias and `claude-3-5-sonnet` all price.

**A model with no price is never guessed at.** `compute_cost` returns `None`,
the event is recorded with `cost=None`, and the export counts it in
`unpriced_requests`. A charge-back figure that is quietly wrong is worse than
one that is absent.

---

## Asking the question

Three commands answer the money questions, all offline and keyless:

```bash
# Where does the spend stand against a ceiling, and how much is left?
backstop budget --ledger ledger.jsonl --usd 500.00

# When does the budget run out, at the burn rate the ledger measured?
backstop forecast --ledger ledger.jsonl --usd 500.00 --horizon 3600

# What did the runaway-spend detectors see?
backstop detect --ledger ledger.jsonl
```

`budget` and `forecast` report at six decimal places rather than the ledger's
usual two. A charge-back CSV rounds to cents because that is how money is
conventionally stated; a headroom report rounds to cents too, and a spend of
$0.003 rendered as "$0.00" says nothing happened.

`forecast` projects **exhaustion**, not spend. A rate of spending says nothing
about what next month will cost; the ledger is a record of what happened, not
a model of what will.

---

## What it does not do

- **It is not a billing system.** Backstop measures what it sent; the
  provider's statement is what you are billed. `backstop reconcile` compares
  the two, and the difference is reported as a variance rather than resolved.
- **It does not forecast spend.** It forecasts exhaustion, at a measured rate.
- **It does not price a model the catalog does not carry**, and it does not
  guess. Refusing is the default; `"allow"` is the opt-out, and the hole is
  recorded.
- **It does not make the ledger cheap.** The ledger is what measures the cost,
  and the ledger costs ~17 µs a request. A dollar ceiling is a money decision
  with a performance price, and the price is stated.
