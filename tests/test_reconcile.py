"""Reconciling a priced ledger against a provider's statement.

Every expected figure in this file is written out by hand rather than copied from a
run, and the arithmetic behind each one is in the comment above it. That is the
whole point of the module under test: a reconciliation is the number a CFO decides
whether to run a charge-back on, so a test that re-derived the expectation with the
same code would prove only that the code is self-consistent.

The suite is deliberately **not** a suite where everything matches. The headline
cases assert an exact **signed** variance that is not zero, one model the catalog
has never heard of, one model the statement does not carry, one statement that
raises rather than producing zeros, and one determinism check that feeds the same
events in a different order.

The demo's own figures are fixed and its report is compared byte for byte across
two runs, which is what makes ``backstop reconcile --demo`` safe to put in a slide.
"""
from __future__ import annotations

import csv
import decimal
import io
import json
import socket
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from backstop.ledger import (
    Attribution,
    PriceCatalog,
    SpendEvent,
    compute_cost,
    measure_error_budget,
    parse_invoice_csv,
    parse_invoice_json,
    reconcile_invoice,
    reconciliation_csv,
)
from backstop.ledger.export import CSV_TERMINATOR, NO_VALUE
from backstop.ledger.reconcile import (
    DEFAULT_TOLERANCE_PCT,
    DEFAULT_TOLERANCE_USD,
    INVOICE_COLUMNS,
    RECONCILIATION_SCOPE,
    STATUS_MATCHED,
    STATUS_MISSING_FROM_INVOICE,
    STATUS_MISSING_FROM_LEDGER,
    STATUS_VARIANCE,
    STATUS_WITHIN_TOLERANCE,
    STATUSES,
    ErrorBudget,
    Invoice,
    InvoiceLine,
    InvoiceVariance,
    ModelVariance,
    demo_events,
    run_demo,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

CATALOG = PriceCatalog()

#: The bundled rates this file leans on, written out so a reader can check any
#: expectation below with a calculator. gpt-4o's cache write is ``None``: the rate
#: card publishes no rate for it, which is the case several tests below exercise.
RATES = {
    "gpt-4o": (Decimal("2.50"), Decimal("10.00"), Decimal("1.25"), None),
    "gpt-4.1": (Decimal("2.00"), Decimal("8.00"), Decimal("0.50"), None),
    "gpt-5.6-sol": (Decimal("4.00"), Decimal("20.00"), Decimal("0.40"), Decimal("5.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00"), Decimal("0.10"), Decimal("1.25")),
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00"), Decimal("0.50"), Decimal("6.25")),
    # Not in the bundled card at all: the ledger demo uses it for the same reason.
    "vendor-preview-2027": None,
}


def event(
    index: int,
    *,
    provider: str = "openai",
    model: str = "gpt-4o",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    estimated: bool = False,
    priced: bool = True,
) -> SpendEvent:
    """One fixed event. The id and the timestamp are literals, never generated."""
    base = SpendEvent(
        event_id=f"{index:032x}",
        occurred_at=f"2026-09-26T0{index}:00:00.000000Z",
        provider=provider,
        model=model,
        endpoint="/v1/chat/completions" if provider == "openai" else "/v1/messages",
        priority="default",
        outcome="success",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        estimated=estimated,
        attribution=Attribution(team="payments", feature="checkout-v2"),
    )
    if not priced:
        return base
    return replace(base, cost=compute_cost(base, CATALOG))


def line(
    model: str = "gpt-4o",
    *,
    provider: str = "openai",
    charged_usd: str = "0.000000",
    categories: dict[str, int] | None = None,
    cost_type: str = "tokens",
    period: str = "2026-09-26",
) -> InvoiceLine:
    """One fixed statement line, with an explicit category mapping."""
    return InvoiceLine(
        provider=provider,
        model=model,
        period=period,
        token_categories=categories if categories is not None else {},
        charged_usd=Decimal(charged_usd),
        cost_type=cost_type,
    )


def invoice(*lines: InvoiceLine, provider: str = "openai", source: str = "statement.csv") -> Invoice:
    return Invoice(provider=provider, period="2026-09-26", source=source, lines=tuple(lines))


def openai_categories(fresh: int, output: int, cached: int = 0, written: int = 0) -> dict[str, int]:
    """An OpenAI-shaped statement row: ``input_uncached_tokens`` is the fresh count."""
    return {
        "input_uncached_tokens": fresh,
        "input_cached_tokens": cached,
        "input_cache_write_tokens": written,
        "output_tokens": output,
    }


def anthropic_categories(fresh: int, output: int, cached: int = 0, written: int = 0) -> dict[str, int]:
    """An Anthropic-shaped statement row: ``uncached_input_tokens`` is the fresh count."""
    return {
        "uncached_input_tokens": fresh,
        "cache_read_input_tokens": cached,
        "cache_creation_5m_input_tokens": written,
        "output_tokens": output,
    }


# --------------------------------------------------------------------------
# The variance is not zero, and the sign is the one that matters
# --------------------------------------------------------------------------


def test_a_price_variance_carries_its_exact_signed_figure() -> None:
    """The ledger priced gpt-4o's input at $2.50/Mtok and the statement charged $2.75.

    1,000,000 fresh input tokens at $2.50/Mtok is ``1000000 * 2.50 / 1000000`` =
    **2.500000**, exact at six decimal places. The statement charged 2.750000, so
    ``variance_usd = 2.500000 - 2.750000 = -0.250000`` — Backstop claims a quarter
    of a dollar *less* than it was charged, and a negative variance is not the safe
    direction. ``variance_pct = -0.25 / 2.75 * 100 = -9.090909...`` to four places.
    """
    events = [event(1, model="gpt-4o", input_tokens=1_000_000)]
    statement = invoice(
        line("gpt-4o", charged_usd="2.750000", categories=openai_categories(1_000_000, 0))
    )

    row = reconcile_invoice(events, statement, CATALOG).rows[0]

    assert row.ledger_usd == Decimal("2.500000")
    assert row.invoice_usd == Decimal("2.750000")
    assert row.variance_usd == Decimal("-0.250000")
    assert row.variance_pct == Decimal("-9.0909")
    # 0.5% of 2.75 is 0.013750, so the looser allowance is 0.013750 — and a quarter
    # of a dollar is nineteen times that.
    assert row.status == STATUS_VARIANCE
    # Every token count agrees, which is what makes this attributable to a price and
    # not to a measurement.
    assert row.token_delta == {
        "input": 0,
        "output": 0,
        "cache_read": 0,
        "cache_write": 0,
    }
    assert "price difference" in (row.reason or "")


def test_a_positive_variance_is_reported_as_positive_not_absolutised() -> None:
    """The mirror of the case above, because only one sign is a bug you would ship.

    1,000,000 input tokens at $3.00/Mtok is 3.000000 against a statement of
    2.500000, so the variance is **+0.500000** and the share **+20.0000%**. An
    absolute figure would report both of these as 0.25 and 0.50 and a reader could
    not tell which side the money is on.
    """
    only_gpt_4o = PriceCatalog(
        {
            "gpt-4o": replace(CATALOG.resolve("openai", "gpt-4o"), input_per_mtok_usd=Decimal("3.00"))
        }
    )
    events = [event(1, model="gpt-4o", input_tokens=1_000_000)]
    statement = invoice(
        line("gpt-4o", charged_usd="2.500000", categories=openai_categories(1_000_000, 0))
    )

    row = reconcile_invoice(events, statement, only_gpt_4o).rows[0]

    assert row.ledger_usd == Decimal("3.000000")
    assert row.variance_usd == Decimal("0.500000")
    assert row.variance_pct == Decimal("20.0000")
    assert row.variance_usd > 0


def test_a_count_variance_is_distinguishable_from_a_price_variance() -> None:
    """The reason a statement row carries token counts on both sides.

    The ledger saw 1,000,000 input and 500,000 output on gpt-4o: 2.500000 + 5.000000 =
    **7.500000**. The statement reports 10,000 *more* output tokens and charges the
    same 7.700000, so the variance is **-0.200000** and the output delta is **-10,000**
    — a measurement difference, and the reason says so rather than blaming the rate.
    """
    events = [event(1, model="gpt-4o", input_tokens=1_000_000, output_tokens=500_000)]
    statement = invoice(
        line("gpt-4o", charged_usd="7.700000", categories=openai_categories(1_000_000, 510_000))
    )

    row = reconcile_invoice(events, statement, CATALOG).rows[0]

    assert row.ledger_usd == Decimal("7.500000")
    assert row.variance_usd == Decimal("-0.200000")
    assert row.token_delta["output"] == -10_000
    assert row.token_delta["input"] == 0
    assert "the token counts differ" in (row.reason or "")
    assert "output -10000" in (row.reason or "")
    # It explicitly rules out the other cause, which is the half of the attribution
    # that makes it useful.
    assert "rather than only a price difference" in (row.reason or "")


def test_an_exact_match_says_matched_and_carries_no_reason() -> None:
    """8,000 input at $4.00/Mtok is 0.032000 and 400 output at $20.00/Mtok is
    0.008000, so gpt-5.6-sol costs exactly 0.040000 — and a statement billing the
    same figure reconciles."""
    events = [event(1, model="gpt-5.6-sol", input_tokens=8_000, output_tokens=400)]
    statement = invoice(
        line("gpt-5.6-sol", charged_usd="0.040000", categories=openai_categories(8_000, 400))
    )

    result = reconcile_invoice(events, statement, CATALOG)

    assert events[0].cost is not None
    assert events[0].cost.total_usd == Decimal("0.040000")
    assert result.rows[0].status == STATUS_MATCHED
    assert result.rows[0].variance_usd == Decimal("0.000000")
    assert result.rows[0].reason is None
    assert result.reconciled_models == 1
    assert result.status == STATUS_MATCHED


def test_a_difference_inside_the_tolerance_is_reported_and_not_rounded_away() -> None:
    """`within_tolerance` is not "the same": the exact figure is on the row.

    The statement charges 2.505000 against a ledger of 2.500000, so the variance is
    **-0.005000** — half a cent, inside the default one-cent floor. Tighten the
    tolerance to zero and the same inputs become a `variance`, which is the point of
    making it a parameter.
    """
    events = [event(1, model="gpt-4o", input_tokens=1_000_000)]
    statement = invoice(
        line("gpt-4o", charged_usd="2.505000", categories=openai_categories(1_000_000, 0))
    )

    loose = reconcile_invoice(events, statement, CATALOG)
    assert loose.rows[0].variance_usd == Decimal("-0.005000")
    assert loose.rows[0].status == STATUS_WITHIN_TOLERANCE
    assert "-0.005000 USD" in (loose.rows[0].reason or "")

    # Zeroing only the dollar floor leaves the 0.5% ceiling: 0.5% of 2.505 is
    # 0.012525, which is looser still, so the row stays inside. Both knobs have to
    # go for "no difference is acceptable", and that is what the pair of parameters
    # is for.
    half_tight = reconcile_invoice(events, statement, CATALOG, tolerance_usd=Decimal("0"))
    assert half_tight.rows[0].status == STATUS_WITHIN_TOLERANCE

    tight = reconcile_invoice(
        events, statement, CATALOG, tolerance_usd=Decimal("0"), tolerance_pct=Decimal("0")
    )
    assert tight.rows[0].status == STATUS_VARIANCE
    assert tight.rows[0].variance_usd == Decimal("-0.005000")


def test_a_zero_charge_statement_line_has_no_percentage_rather_than_a_division_error() -> None:
    """A share of zero has no denominator, and printing 0.00% would claim a perfect
    match on a row that does not exist."""
    events = [event(1, model="gpt-4o", input_tokens=1_000_000)]
    statement = invoice(
        line("gpt-4o", charged_usd="0.000000", categories=openai_categories(1_000_000, 0))
    )

    result = reconcile_invoice(events, statement, CATALOG)

    assert result.rows[0].variance_usd == Decimal("2.500000")
    assert result.rows[0].variance_pct is None
    assert result.variance_pct is None
    assert result.status == STATUS_VARIANCE


# --------------------------------------------------------------------------
# An unknown model is never guessed
# --------------------------------------------------------------------------


def test_a_model_the_catalog_has_never_heard_of_is_missing_from_the_ledger() -> None:
    """The unpriced row. `vendor-preview-2027` is not in the bundled rate card, so
    ``compute_cost`` returns ``None`` and this module refuses to invent a rate: the
    ledger's side of the row is **absent**, so there is no variance to compute and
    none is printed."""
    events = [event(1, model="vendor-preview-2027", input_tokens=10_000, priced=False)]
    statement = invoice(
        line(
            "vendor-preview-2027",
            charged_usd="0.042000",
            categories=openai_categories(10_000, 0),
        )
    )

    result = reconcile_invoice(events, statement, CATALOG)
    row = result.rows[0]

    assert events[0].cost is None
    assert row.status == STATUS_MISSING_FROM_LEDGER
    assert row.ledger_usd is None
    assert row.invoice_usd == Decimal("0.042000")
    assert row.variance_usd is None
    assert row.variance_pct is None
    assert row.unpriced_events == 1
    assert "unknown model" in (row.reason or "")
    assert "absent rather than zero" in (row.reason or "")
    # The total says the row is missing from it rather than quietly reporting zero.
    assert result.rows_without_ledger_usd == 1
    assert result.ledger_usd is None
    assert result.variance_usd is None


def test_an_unpriced_request_makes_its_model_total_absent_rather_than_understated() -> None:
    """One unpriced request in a model takes the model's whole total with it.

    Two events on ``vendor-preview-2027``: 1,000,000 input tokens and 10,000. A sum of
    the events that *did* price would be 0.000000 here, and a reader would take that
    for a measurement. It is not one: the second request's cost is unknown, so the
    row's figure is absent, and the row says how many events were unpriced.
    """
    events = [
        event(1, model="vendor-preview-2027", input_tokens=1_000_000, priced=False),
        event(2, model="vendor-preview-2027", input_tokens=10_000, priced=False),
    ]
    statement = invoice(
        line("vendor-preview-2027", charged_usd="0.042000", categories=openai_categories(1_010_000, 0))
    )

    row = reconcile_invoice(events, statement, CATALOG).rows[0]

    assert row.ledger_usd is None
    assert row.unpriced_events == 2
    assert row.ledger_events == 2
    assert row.ledger_tokens["input"] == 1_010_000


def test_a_user_catalog_makes_the_unpriced_row_comparable_without_touching_the_module() -> None:
    """The other half of the rule: the gap is a *missing price*, not a missing
    feature. Supply a rate for the model and the same three inputs reconcile.

    A vendor-preview rate of $4.00/Mtok on 1,000,000 input tokens is 4.000000, against
    a statement of 4.200000, so the variance is **-0.200000**.
    """
    catalog_file = Path(__file__).parent / "_tmp_reconcile_prices.json"
    catalog_file.write_text(
        json.dumps(
            {
                "effective_from": "2026-09-26",
                "entries": [
                    {
                        "model": "vendor-preview-2027",
                        "provider": "openai",
                        "input_per_mtok_usd": "4.00",
                        "output_per_mtok_usd": "16.00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    try:
        catalog = PriceCatalog.from_file(catalog_file)
        events = [event(1, model="vendor-preview-2027", input_tokens=1_000_000, priced=False)]
        statement = invoice(
            line(
                "vendor-preview-2027",
                charged_usd="4.200000",
                categories=openai_categories(1_000_000, 0),
            )
        )

        row = reconcile_invoice(events, statement, catalog).rows[0]

        assert row.ledger_usd == Decimal("4.000000")
        assert row.variance_usd == Decimal("-0.200000")
        assert row.status == STATUS_VARIANCE
        assert row.price_source == "user"
    finally:
        catalog_file.unlink()


def test_a_model_absent_from_the_catalog_takes_no_neighbouring_models_price() -> None:
    """A catalog that prices gpt-4o and nothing else must not price
    ``vendor-preview-2027`` at gpt-4o's rate, which is the failure mode the ledger's
    whole design is against."""
    only_gpt_4o = PriceCatalog(
        {"gpt-4o": CATALOG.resolve("openai", "gpt-4o")}, include_bundled=False
    )
    assert only_gpt_4o.resolve("openai", "gpt-4o") is not None

    events = [event(1, model="vendor-preview-2027", input_tokens=1_000_000, priced=False)]
    statement = invoice(
        line("vendor-preview-2027", charged_usd="2.500000", categories=openai_categories(1_000_000, 0))
    )

    row = reconcile_invoice(events, statement, only_gpt_4o).rows[0]

    assert row.ledger_usd is None
    assert row.invoice_usd == Decimal("2.500000")
    assert "2.500000" not in (row.reason or "").replace("2.500000 USD for it", "")


# --------------------------------------------------------------------------
# One side only
# --------------------------------------------------------------------------


def test_a_model_in_the_ledger_and_absent_from_the_statement_is_reported_on_its_own_row() -> None:
    """1,000,000 input tokens on gpt-4o is 2.500000 in the ledger and nowhere in the
    statement. The row exists, the figure is on it, and it is not offset against
    gpt-4.1's statement line."""
    events = [event(1, model="gpt-4o", input_tokens=1_000_000)]
    statement = invoice(
        line("gpt-4.1", charged_usd="1.000000", categories=openai_categories(400_000, 0))
    )

    result = reconcile_invoice(events, statement, CATALOG)
    by_model = {row.model: row for row in result.rows}

    assert by_model["gpt-4o"].status == STATUS_MISSING_FROM_INVOICE
    assert by_model["gpt-4o"].ledger_usd == Decimal("2.500000")
    assert by_model["gpt-4o"].invoice_usd is None
    assert by_model["gpt-4o"].variance_usd is None
    assert by_model["gpt-4o"].token_delta["input"] is None
    assert by_model["gpt-4.1"].status == STATUS_MISSING_FROM_LEDGER
    # The total holds the one side it has and says how many rows it could not include.
    assert result.ledger_usd == Decimal("2.500000")
    assert result.invoice_usd == Decimal("1.000000")
    assert result.rows_without_invoice_usd == 1
    assert result.status == STATUS_MISSING_FROM_INVOICE


def test_a_model_the_statement_bills_and_the_ledger_never_saw_is_missing_from_the_ledger() -> None:
    """Traffic that did not go through a wrapped client: the statement bills
    claude-opus-5 for 1.240000 and the ledger holds no event for it."""
    statement = invoice(
        line(
            "claude-opus-5",
            charged_usd="1.240000",
            categories=anthropic_categories(100_000, 0),
        )
    )

    result = reconcile_invoice([], statement, CATALOG)
    row = result.rows[0]

    assert row.status == STATUS_MISSING_FROM_LEDGER
    assert row.ledger_usd is None
    assert row.invoice_usd == Decimal("1.240000")
    assert row.ledger_events == 0
    assert row.invoice_lines == 1
    assert "no event for it at all" in (row.reason or "")


def test_a_provider_mismatch_is_two_rows_rather_than_one_merged_row() -> None:
    """The same model name from two vendors is two facts, not one. Merging them
    would put one vendor's dollars in the other vendor's row."""
    events = [event(1, provider="openai", model="gpt-4o", input_tokens=1_000_000)]
    statement = Invoice(
        provider="anthropic",
        period="2026-09-26",
        source="anthropic.csv",
        lines=(
            line(
                "gpt-4o",
                provider="anthropic",
                charged_usd="3.000000",
                categories=anthropic_categories(1_000_000, 0),
            ),
        ),
    )

    result = reconcile_invoice(events, statement, CATALOG)
    by_key = {(row.provider, row.model): row for row in result.rows}

    assert len(result.rows) == 2
    assert result.providers == ("anthropic", "openai")
    assert by_key[("anthropic", "gpt-4o")].status == STATUS_MISSING_FROM_LEDGER
    assert by_key[("anthropic", "gpt-4o")].invoice_usd == Decimal("3.000000")
    # The openai row with the very same model name is a different row, and the
    # report says so rather than hiding the disagreement.
    assert by_key[("openai", "gpt-4o")].status == STATUS_MISSING_FROM_INVOICE
    assert by_key[("openai", "gpt-4o")].ledger_usd == Decimal("2.500000")
    assert "this statement does not cover" in result.to_markdown()


def test_an_invoice_whose_lines_disagree_about_the_provider_is_refused() -> None:
    with pytest.raises(ValueError, match="carries lines from"):
        Invoice(
            provider="openai",
            period="2026-09-26",
            source="mixed.csv",
            lines=(
                line("gpt-4o", provider="openai", charged_usd="1.000000"),
                line("claude-opus-5", provider="anthropic", charged_usd="1.000000"),
            ),
        )


def test_a_model_spelled_differently_is_two_rows_and_this_is_deliberate() -> None:
    """The catalog resolves ``gpt-4o-2024-08-06`` to gpt-4o's price, so a
    reconciliation could merge them. It does not, because two names that happen to
    share a rate card are two names and merging them is a guess. The cost of the
    choice is a visible pair of rows; the cost of the alternative is an invisible
    merge."""
    events = [event(1, model="gpt-4o", input_tokens=1_000_000)]
    statement = invoice(
        line(
            "gpt-4o-2024-08-06",
            charged_usd="2.500000",
            categories=openai_categories(1_000_000, 0),
        )
    )

    result = reconcile_invoice(events, statement, CATALOG)

    assert [row.status for row in result.rows] == [
        STATUS_MISSING_FROM_INVOICE,
        STATUS_MISSING_FROM_LEDGER,
    ]
    assert result.reconciled_models == 0


# --------------------------------------------------------------------------
# The statement's own categories, and the two providers' conventions
# --------------------------------------------------------------------------


def test_openai_and_anthropic_count_their_cached_tokens_on_opposite_sides() -> None:
    """The asymmetry ``docs/planning/03-attribution-and-schema.md`` Part 4.5 calls the
    single most expensive correctness issue in the ledger half.

    OpenAI's ``input_tokens`` counts the cached tokens *inside* it: 1,000,000 of which
    400,000 were cached is 600,000 fresh. Anthropic's ``input_tokens`` is the fresh
    count with the cached figures beside it. Both rows must normalise to the same four
    components — 600,000 input and 400,000 cache read — or the ledger either
    overcharges cached tokens at the full input rate or bills a fraction of them
    twice.
    """
    openai = line(
        "gpt-4o",
        charged_usd="1.750000",
        categories={
            "input_tokens": 1_000_000,
            "input_cached_tokens": 400_000,
            "output_tokens": 0,
        },
    )
    anthropic = line(
        "claude-opus-5",
        provider="anthropic",
        charged_usd="3.000000",
        categories={
            "input_tokens": 600_000,
            "cache_read_input_tokens": 400_000,
            "output_tokens": 0,
        },
    )

    assert openai.input_tokens == 600_000
    assert openai.cache_read_tokens == 400_000
    assert anthropic.input_tokens == 600_000
    assert anthropic.cache_read_tokens == 400_000
    assert openai.counts == anthropic.counts
    assert openai.unmapped_categories == ()


def test_an_exclusive_input_count_wins_over_the_inclusive_one() -> None:
    """A row publishing both an inclusive and an exclusive count is read as the
    exclusive one, because that is the figure the ledger records."""
    both = line(
        "gpt-4o",
        charged_usd="1.750000",
        categories={
            "input_tokens": 1_000_000,
            "input_uncached_tokens": 600_000,
            "input_cached_tokens": 400_000,
            "output_tokens": 0,
        },
    )

    assert both.input_tokens == 600_000
    assert both.cache_read_tokens == 400_000
    assert both.total_tokens == 1_000_000


def test_a_token_category_no_component_is_built_from_is_reported_not_dropped() -> None:
    """A provider that starts publishing a new category must produce "I cannot
    compare this", not a confident number that quietly omits it."""
    events = [event(1, model="gpt-4o", input_tokens=1_000_000)]
    statement = invoice(
        line(
            "gpt-4o",
            charged_usd="2.500000",
            categories={**openai_categories(1_000_000, 0), "reasoning_tokens": 5_000},
        )
    )

    result = reconcile_invoice(events, statement, CATALOG)
    row = result.rows[0]

    assert row.unmapped_categories == ("reasoning_tokens",)
    assert row.token_delta == {
        "input": None,
        "output": None,
        "cache_read": None,
        "cache_write": None,
    }
    assert row.status == STATUS_MATCHED  # the money agrees exactly
    assert "reasoning_tokens" in (row.reason or "") or row.variance_usd == Decimal("0.000000")
    # The category is still in the record, on the line, for a reader to look at.
    assert statement.lines[0].token_categories["reasoning_tokens"] == 5_000


def test_a_non_token_cost_line_is_real_money_and_is_not_attributed_to_tokens() -> None:
    """Anthropic's cost report bills ``web_search`` and ``code_execution`` alongside
    tokens, and Backstop has no token count for either. The money is real and is
    compared; the token sides are declared incomparable rather than pretending to
    agree."""
    events = [event(1, model="claude-opus-5", provider="anthropic", input_tokens=1_000_000)]
    statement = Invoice(
        provider="anthropic",
        period="2026-09-26",
        source="anthropic.csv",
        lines=(
            line(
                "claude-opus-5",
                provider="anthropic",
                charged_usd="5.000000",
                categories=anthropic_categories(1_000_000, 0),
            ),
            line(
                "claude-opus-5",
                provider="anthropic",
                charged_usd="0.400000",
                categories={},
                cost_type="web_search",
            ),
        ),
    )

    row = reconcile_invoice(events, statement, CATALOG).rows[0]

    assert row.invoice_usd == Decimal("5.400000")
    assert row.ledger_usd == Decimal("5.000000")
    assert row.variance_usd == Decimal("-0.400000")
    assert row.non_token_cost_types == ("web_search",)
    assert row.token_delta["input"] is None
    assert "cannot be attributed to a token count" in (row.reason or "")
    assert "web_search" in (row.reason or "")


# --------------------------------------------------------------------------
# Decimal discipline
# --------------------------------------------------------------------------


def test_the_money_quantum_is_the_catalogs_own() -> None:
    """The reconciler requantises, so its quantum has to be the catalog's. The
    accumulator's zero is at that quantum too: ``Decimal(1).scaleb(-6)`` is one
    microdollar rather than zero, and an accumulator seeded with it adds a microdollar
    to every total it goes on to report."""
    from backstop.ledger.reconcile import _MTOK, _QUANTUM, _ZERO

    assert _QUANTUM == Decimal("0.000001")
    assert _ZERO == Decimal("0.000000")
    assert _ZERO.is_zero()
    assert _MTOK == Decimal(1_000_000)

    events = [event(1, model="gpt-4o", input_tokens=1_000_000)]
    statement = invoice(
        line("gpt-4o", charged_usd="2.500000", categories=openai_categories(1_000_000, 0))
    )
    result = reconcile_invoice(events, statement, CATALOG)
    assert result.ledger_usd == Decimal("2.500000")
    assert result.rows[0].status == STATUS_MATCHED


def test_a_hostile_decimal_context_does_not_change_the_answer() -> None:
    """A ``decimal`` context is process-global, so a host that tightened ``prec``
    would otherwise round this module's totals to a handful of digits — silently,
    because a rounded variance is still a variance."""
    events = [event(1, model="gpt-4o", input_tokens=1_234_567, output_tokens=987_654)]
    statement = invoice(
        line(
            "gpt-4o",
            charged_usd="13.000000",
            categories=openai_categories(1_234_567, 987_654),
        )
    )
    clean = reconcile_invoice(events, statement, CATALOG).to_dict()

    hostile = decimal.Context(prec=3, rounding=decimal.ROUND_DOWN, traps=[decimal.Inexact])
    previous = decimal.getcontext()
    decimal.setcontext(hostile)
    try:
        assert reconcile_invoice(events, statement, CATALOG).to_dict() == clean
    finally:
        decimal.setcontext(previous)


def test_money_is_never_a_binary_float_at_any_boundary() -> None:
    """A statement figure arrives as a string and leaves as a string; a float handed
    in directly is refused, because by the time an amount is a float the cents it
    lost are gone."""
    with pytest.raises(TypeError, match="never a binary float"):
        line("gpt-4o", charged_usd="1.00")
        InvoiceLine(
            provider="openai",
            model="gpt-4o",
            period="2026-09-26",
            token_categories={},
            charged_usd=1.0,  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="never a binary float"):
        ModelVariance(
            provider="openai",
            model="gpt-4o",
            status=STATUS_VARIANCE,
            currency="USD",
            ledger_usd=1.0,  # type: ignore[arg-type]
            invoice_usd=Decimal("1.0"),
            variance_usd=Decimal("0.0"),
            variance_pct=Decimal("0.0"),
            ledger_events=1,
            invoice_lines=1,
            unpriced_events=0,
            estimated_events=0,
            price_source="bundled",
            ledger_tokens={c: 0 for c in ("input", "output", "cache_read", "cache_write")},
            invoice_tokens={c: 0 for c in ("input", "output", "cache_read", "cache_write")},
            token_delta={c: 0 for c in ("input", "output", "cache_read", "cache_write")},
            unmapped_categories=(),
            non_token_cost_types=(),
            reason="a reason",
        )


def test_every_amount_this_module_produces_is_a_decimal_at_six_places() -> None:
    events = [event(1, model="gpt-4o", input_tokens=1_234_567, output_tokens=987_654)]
    statement = invoice(
        line("gpt-4o", charged_usd="13.000000", categories=openai_categories(1_234_567, 987_654))
    )

    result = reconcile_invoice(events, statement, CATALOG)

    for amount in (
        result.ledger_usd,
        result.invoice_usd,
        result.variance_usd,
        result.rows[0].ledger_usd,
        result.rows[0].invoice_usd,
        result.rows[0].variance_usd,
    ):
        assert isinstance(amount, Decimal)
        assert amount.as_tuple().exponent == -6
    assert result.rows[0].variance_pct.as_tuple().exponent == -4


# --------------------------------------------------------------------------
# Self-auditing
# --------------------------------------------------------------------------


def test_an_empty_reconciliation_is_not_a_clean_one() -> None:
    """No events and no statement lines produce a zero variance for a completely
    different reason than agreement, and the report says so in words."""
    result = reconcile_invoice([], invoice(), CATALOG)

    assert result.is_empty
    assert result.events == 0
    assert result.invoice_lines == 0
    assert result.models_count == 0
    assert result.reconciled_models == 0
    assert result.variance_usd is None
    assert "Nothing was reconciled" in result.to_markdown()


def test_a_clean_reconciliation_and_an_empty_one_report_different_counts() -> None:
    events = [event(1, model="gpt-4o", input_tokens=1_000_000)]
    statement = invoice(
        line("gpt-4o", charged_usd="2.500000", categories=openai_categories(1_000_000, 0))
    )

    clean = reconcile_invoice(events, statement, CATALOG)
    empty = reconcile_invoice([], invoice(), CATALOG)

    assert clean.is_empty is False
    assert clean.events == 1
    assert clean.reconciled_models == 1
    assert empty.is_empty is True
    assert empty.reconciled_models == 0


def test_the_report_carries_the_three_counts_a_reader_needs() -> None:
    events = [event(1, model="gpt-4o", input_tokens=1_000_000)]
    statement = invoice(
        line("gpt-4o", charged_usd="2.750000", categories=openai_categories(1_000_000, 0))
    )

    payload = reconcile_invoice(events, statement, CATALOG).to_dict()

    assert payload["counts"] == {
        "events": 1,
        "invoice_lines": 1,
        "models": 1,
        "reconciled_models": 0,
        "unmatched_models": 1,
        "unpriced_events": 0,
        "estimated_events": 0,
        "rows_without_ledger_usd": 0,
        "rows_without_invoice_usd": 0,
    }
    assert payload["scope"] == RECONCILIATION_SCOPE


def test_every_row_that_is_not_matched_carries_a_reason() -> None:
    """The rule, asserted over the whole demo rather than one fixture, so a status
    that slipped through without an explanation would fail here."""
    result = run_demo()

    assert result.variances
    rows = [row for variance in result.variances for row in variance.rows]
    assert rows
    unmatched = []
    for row in rows:
        if row.status == STATUS_MATCHED:
            assert row.reason is None
        else:
            assert row.reason, f"{row.provider}/{row.model} is {row.status} with no reason"
            unmatched.append(row)
    assert unmatched
    matched = [row for row in rows if row.status == STATUS_MATCHED]
    assert matched
    # And the model itself refuses both impossible shapes, not just the renderers: a
    # reason on a row that matched, and no reason on one that did not.
    with pytest.raises(ValueError, match="must carry a reason"):
        replace(matched[0], reason="a reason on a matched row")
    with pytest.raises(ValueError, match="must carry a reason"):
        replace(unmatched[0], reason=None)


def test_estimated_events_are_counted_beside_the_money() -> None:
    """M1 is defined as *reported alongside* ``unpriced_requests`` and
    ``estimated_requests``, never alone, so the row carries the count."""
    events = [
        event(1, model="gpt-4o", input_tokens=1_000_000),
        event(2, model="gpt-4o", input_tokens=1_000_000, estimated=True),
    ]
    statement = invoice(
        line("gpt-4o", charged_usd="2.500000", categories=openai_categories(2_000_000, 0))
    )

    row = reconcile_invoice(events, statement, CATALOG).rows[0]

    assert row.estimated_events == 1
    assert row.unpriced_events == 0
    assert "estimated rather than provider-reported tokens" in (row.reason or "")


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_the_same_inputs_always_produce_the_same_variance_in_any_order() -> None:
    """The events arrive in a different order, and the report is byte-identical: the
    rows are sorted by ``(provider, model)`` and nothing in the comparison reads an
    input order."""
    events = [
        event(1, model="gpt-4o", input_tokens=1_000_000, output_tokens=400),
        event(2, model="gpt-4.1", input_tokens=2_000_000),
        event(3, model="gpt-4o", input_tokens=500_000, cache_read_tokens=200_000),
    ]
    statement = invoice(
        line("gpt-4o", charged_usd="4.000000", categories=openai_categories(1_500_000, 400, 200_000)),
        line("gpt-4.1", charged_usd="4.100000", categories=openai_categories(2_000_000, 0)),
    )

    first = reconcile_invoice(events, statement, CATALOG)
    second = reconcile_invoice(events, statement, CATALOG)
    reversed_order = reconcile_invoice(list(reversed(events)), statement, CATALOG)

    assert first.to_dict() == second.to_dict()
    assert reversed_order.to_dict() == first.to_dict()
    assert reconciliation_csv(first) == reconciliation_csv(reversed_order)
    # A concrete figure, so a test that passed by comparing two empty results could
    # not pass here: the first row's variance is 0.100000, not nothing.
    assert first.row_for("gpt-4.1") is not None
    assert first.row_for("gpt-4.1").variance_usd == Decimal("-0.100000")
    assert [row.model for row in first.rows] == ["gpt-4.1", "gpt-4o"]


# --------------------------------------------------------------------------
# The export
# --------------------------------------------------------------------------


def test_the_reconciliation_csv_is_rfc_4180_with_two_decimal_money() -> None:
    events = [event(1, model="gpt-4o", input_tokens=1_000_000)]
    statement = invoice(
        line("gpt-4o", charged_usd="2.750000", categories=openai_categories(1_000_000, 0)),
        line("gpt-4.1", charged_usd="9.990000", categories=openai_categories(0, 0)),
    )
    result = reconcile_invoice(events, statement, CATALOG)

    text = reconciliation_csv(result)
    lines = text.split(CSV_TERMINATOR)

    assert lines[0] == ",".join(INVOICE_COLUMNS)
    assert text.endswith(CSV_TERMINATOR)
    # Two model rows and no totals row: a totals line inside a table finance intends
    # to SUM is a double count waiting to happen.
    assert len([line_ for line_ in lines if line_]) == 3
    assert "total_usd" not in INVOICE_COLUMNS
    parsed = list(csv.reader(io.StringIO(text, newline=""), lineterminator=CSV_TERMINATOR))
    assert parsed[0] == list(INVOICE_COLUMNS)
    # Largest variance first, so the row a reader must act on is at the top.
    rows = {cells[INVOICE_COLUMNS.index("model")]: cells for cells in parsed[1:]}
    # gpt-4.1 is on the statement and nowhere in the ledger, so it has no ledger
    # figure and therefore no variance to report — the marker, never a zero.
    assert rows["gpt-4.1"][INVOICE_COLUMNS.index("status")] == STATUS_MISSING_FROM_LEDGER
    assert rows["gpt-4.1"][INVOICE_COLUMNS.index("ledger_usd")] == NO_VALUE
    assert rows["gpt-4.1"][INVOICE_COLUMNS.index("variance_usd")] == NO_VALUE
    assert rows["gpt-4.1"][INVOICE_COLUMNS.index("invoice_usd")] == "9.99"
    # Money is a two-decimal string, and the exact signed figure survives in the
    # reason cell even where the money column rounds it.
    assert rows["gpt-4o"][INVOICE_COLUMNS.index("ledger_usd")] == "2.50"
    assert rows["gpt-4o"][INVOICE_COLUMNS.index("invoice_usd")] == "2.75"
    assert rows["gpt-4o"][INVOICE_COLUMNS.index("variance_usd")] == "-0.25"
    assert "-0.250000 USD" in rows["gpt-4o"][INVOICE_COLUMNS.index("reason")]
    # An absent figure is the marker, never a zero and never a blank cell.
    assert rows["gpt-4.1"][INVOICE_COLUMNS.index("ledger_usd")] == NO_VALUE
    assert rows["gpt-4.1"][INVOICE_COLUMNS.index("ledger_events")] == "0"


def test_no_cell_in_the_reconciliation_csv_is_a_python_none() -> None:
    """A row with no figure on one side leaves several cells with no value, and the
    one rendering path has to turn every one of them into the marker rather than
    str() of a None — which is what a ``None`` in a CSV column is."""
    events = [event(1, model="gpt-4o", input_tokens=1_000_000)]
    statement = invoice(
        line("gpt-4o", charged_usd="2.750000", categories=openai_categories(1_000_000, 0)),
        line("gpt-4.1", charged_usd="9.990000", categories=openai_categories(0, 0)),
        line("claude-opus-5", charged_usd="1.000000", categories=anthropic_categories(1, 0)),
    )
    result = reconcile_invoice(events, statement, CATALOG)

    text = reconciliation_csv(result)

    assert "None" not in text
    parsed = list(csv.reader(io.StringIO(text, newline=""), lineterminator=CSV_TERMINATOR))
    by_model = {row[1]: row for row in parsed[1:]}
    missing = by_model["gpt-4.1"]
    assert missing[INVOICE_COLUMNS.index("ledger_usd")] == NO_VALUE
    assert missing[INVOICE_COLUMNS.index("variance_pct")] == NO_VALUE
    # Every token delta is absent for a row with no ledger side, and every one of
    # them is the marker rather than a zero.
    for component in ("input", "output", "cache_read", "cache_write"):
        assert missing[INVOICE_COLUMNS.index(f"{component}_token_delta")] == NO_VALUE
        assert missing[INVOICE_COLUMNS.index(f"ledger_{component}_tokens")] == "0"


def test_the_reconciliation_csv_column_order_is_stable_and_ends_with_the_reason() -> None:
    """Stable order is what lets finance join the file to the charge-back CSV."""
    assert INVOICE_COLUMNS[:8] == (
        "provider",
        "model",
        "status",
        "currency",
        "ledger_usd",
        "invoice_usd",
        "variance_usd",
        "variance_pct",
    )
    assert INVOICE_COLUMNS[-1] == "reason"
    assert INVOICE_COLUMNS.index("status") < INVOICE_COLUMNS.index("ledger_usd")
    # Every component appears on both sides with a delta beside it.
    for component in ("input", "output", "cache_read", "cache_write"):
        assert f"ledger_{component}_tokens" in INVOICE_COLUMNS
        assert f"invoice_{component}_tokens" in INVOICE_COLUMNS
        assert f"{component}_token_delta" in INVOICE_COLUMNS


# --------------------------------------------------------------------------
# The error budget, measured
# --------------------------------------------------------------------------


def test_the_error_budget_reports_what_was_observed_and_says_what_it_is_not() -> None:
    """Two statements, one ledger, four rows, and every figure below is arithmetic.

    - gpt-4o: the ledger priced 1,000,000 input at $2.50 = 2.500000, the statement
      charged 2.750000, so the row is **-0.250000**.
    - gpt-4.1: the ledger priced 2,000,000 input at $2.00 = 4.000000, the statement
      charged 4.000000, so the row is **0.000000** and reconciles exactly.
    - claude-opus-5: on one statement only, so it has no ledger figure and
      contributes no variance.
    - gpt-4.1 is on the second statement for 3.900000, so it has **-0.100000** there.

    Five model rows over the two statements and four statement lines: the second
    statement names only gpt-4.1, so it also reports a gpt-4o row the ledger priced
    and it did not bill, and a row with no figure on one side cannot contribute to
    either half of the quotient.

    The absolute figure is the sum of the absolute row variances, not the net:
    0.250000 + 0 + 0.100000 = **0.350000**, where netting would report 0.150000 and
    let gpt-4o's over-claim hide gpt-4.1's. The denominator is what the statement
    billed on the rows that had a figure on both sides: 2.750000 + 4.000000 + 3.900000
    = 10.650000, so the relative figure is 0.350000 / 10.650000 * 100 = **3.2864%** to
    four places. The worst single row is gpt-4o at 0.250000, and two rows sit beyond
    the tolerance.
    """
    events = [
        event(1, model="gpt-4o", input_tokens=1_000_000),
        event(2, model="gpt-4.1", input_tokens=2_000_000),
    ]
    first = invoice(
        line("gpt-4o", charged_usd="2.750000", categories=openai_categories(1_000_000, 0)),
        line("gpt-4.1", charged_usd="4.000000", categories=openai_categories(2_000_000, 0)),
        line(
            "claude-opus-5",
            charged_usd="3.000000",
            categories=anthropic_categories(500_000, 0),
        ),
        source="first.csv",
    )
    second = invoice(
        line("gpt-4.1", charged_usd="3.900000", categories=openai_categories(2_000_000, 0)),
        source="second.csv",
    )

    budget = measure_error_budget(events, (first, second), CATALOG)

    assert isinstance(budget, ErrorBudget)
    assert budget.measured
    assert budget.invoices == 2
    assert budget.events == 2
    assert budget.models == 5  # the second statement also reports the gpt-4o row
    assert budget.invoice_lines == 4
    assert budget.reconciled_models == 1
    assert budget.observed_abs_variance_usd == Decimal("0.350000")
    # The netted figure is -0.150000, and that is exactly why it is not the
    # headline: netting lets gpt-4o's 0.25 of over-claim shrink against gpt-4.1's
    # 0.10 of under-claim and report a number a third of the size of the worst row.
    assert budget.observed_net_variance_usd == Decimal("-0.150000")
    assert budget.observed_rel_variance_pct == Decimal("3.2864")
    assert budget.worst_model == "gpt-4o"
    assert budget.worst_variance_usd == Decimal("-0.250000")
    assert budget.rows_beyond_tolerance == 2
    assert budget.within_tolerance is False
    # The caveat travels with the figure, not in a docstring.
    assert "empirical figure over the inputs" in budget.note
    assert "not a guarantee" in budget.note
    assert "population that resembles" in budget.note
    assert "tighten the tolerance per account" in budget.note
    assert budget.note in budget.to_markdown()
    assert budget.note in budget.to_dict()["note"]


def test_an_unmeasured_error_budget_is_not_a_clean_bill_of_health() -> None:
    """No statement, no measurement — and ``within_tolerance`` is ``False`` rather
    than vacuously ``True``, because a budget over nothing has not been shown to
    hold."""
    budget = measure_error_budget([event(1, model="gpt-4o", input_tokens=1_000_000)], (), CATALOG)

    assert budget.invoices == 0
    assert budget.measured is False
    assert budget.within_tolerance is False
    assert budget.observed_abs_variance_usd is None
    assert budget.observed_rel_variance_pct is None
    assert budget.worst_model is None
    assert "not measured" in budget.to_markdown()


def test_the_default_tolerance_is_a_cent_and_the_claims_it_makes_hold() -> None:
    """A tolerance is a number somebody will quote, so the three claims its reasoning
    rests on are checked rather than the prose.

    1. It is a cent — the smallest unit both providers' statements state.
    2. It absorbs the ledger's own six-decimal quantisation: $0.0000005 per request,
       so one cent covers the worst case for 20,000 requests.
    3. It cannot hide a rate error: 1% of $100.00 is $1.00, a hundred times the
       tolerance.
    4. And it is deliberately loose in *token* terms on a large row: a cent is 4,000
       input tokens at gpt-4o's $2.50/Mtok, which is why it is a parameter.
    """
    assert DEFAULT_TOLERANCE_USD == Decimal("0.01")
    assert DEFAULT_TOLERANCE_PCT == Decimal("0.5")

    # 2. A cent against the worst-case per-request rounding.
    rounding_step = Decimal("0.0000005")
    assert int(DEFAULT_TOLERANCE_USD / rounding_step) == 20_000

    # 3. A one percent rate error on a hundred dollar row.
    rate_error = Decimal("100.00") * Decimal("0.01")
    assert rate_error == Decimal("1.000000")
    assert int(rate_error / DEFAULT_TOLERANCE_USD) == 100

    # 4. A cent in tokens at gpt-4o's input rate, and the reason it is a parameter.
    #    On a 4,000,000-token row (10.000000) a difference of exactly one cent —
    #    which is 4,000 tokens' worth — is inside the default floor, and only
    #    zeroing the tolerance calls it a variance.
    tokens_in_a_cent = DEFAULT_TOLERANCE_USD / (Decimal("2.50") / Decimal(1_000_000))
    assert int(tokens_in_a_cent) == 4_000
    events = [event(1, model="gpt-4o", input_tokens=4_000_000)]
    statement = invoice(
        line("gpt-4o", charged_usd="10.010000", categories=openai_categories(4_004_000, 0))
    )
    default = reconcile_invoice(events, statement, CATALOG).rows[0]
    assert default.variance_usd == Decimal("-0.010000")
    assert default.status == STATUS_WITHIN_TOLERANCE
    strict = reconcile_invoice(
        events, statement, CATALOG, tolerance_usd=Decimal("0"), tolerance_pct=Decimal("0")
    ).rows[0]
    assert strict.status == STATUS_VARIANCE
    assert strict.variance_usd == Decimal("-0.010000")

    # The percentage side is a percentage, not a ratio, and it is read at four places
    # because "0.07" is not a useful thing to tell anybody about a gap.
    from backstop.ledger import reconcile as module

    assert module.SHARE_PLACES == 4
    assert module.DEFAULT_TOLERANCE_PCT == DEFAULT_TOLERANCE_PCT


def test_the_percentage_tolerance_and_the_reported_percentage_are_on_one_scale() -> None:
    """The one conversion that would silently make every row pass: a 0.005 ratio
    compared against a 0.5 percentage. 0.5% of 1.00 is 0.005, so a statement billing
    1.00 against a ledger of 1.004 is inside the default allowance."""
    events = [event(1, model="gpt-4.1", input_tokens=500_000)]  # 500000 * 2.00 = 1.000000
    statement = invoice(
        line("gpt-4.1", charged_usd="1.004000", categories=openai_categories(500_000, 0))
    )

    row = reconcile_invoice(events, statement, CATALOG).rows[0]

    assert row.ledger_usd == Decimal("1.000000")
    assert row.variance_usd == Decimal("-0.004000")
    assert row.variance_pct == Decimal("-0.3984")
    assert row.status == STATUS_WITHIN_TOLERANCE


# --------------------------------------------------------------------------
# Parsing a statement file
# --------------------------------------------------------------------------


def test_a_csv_with_no_charged_amount_raises_instead_of_returning_zeros(tmp_path: Path) -> None:
    """The refusal the whole parser design rests on. A header with no cost column
    would reconcile as 0.00 against a ledger that also reads 0.00, and the report
    would look perfect."""
    path = tmp_path / "no-cost.csv"
    path.write_text(
        "date,model,input_uncached_tokens,output_tokens\n2026-09-26,gpt-4o,1000,200\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as caught:
        parse_invoice_csv(path)

    message = str(caught.value)
    assert "'charged_usd'" in message
    for spelling in ("cost_usd", "total_cost_usd", "amount_usd"):
        assert spelling in message
    assert "refuses it rather than reporting zeros" in message


def test_a_csv_with_a_missing_token_count_raises_and_names_the_field(tmp_path: Path) -> None:
    path = tmp_path / "no-output.csv"
    path.write_text(
        "date,model,input_uncached_tokens,cost_usd\n2026-09-26,gpt-4o,1000,2.500000\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="'output'"):
        parse_invoice_csv(path)


def test_a_csv_with_a_header_and_no_rows_raises_rather_than_reconciling_nothing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("date,model,input_uncached_tokens,output_tokens,cost_usd\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no data rows"):
        parse_invoice_csv(path)


def test_an_anthropic_cents_column_is_refused_rather_than_read_as_dollars(tmp_path: Path) -> None:
    """Anthropic's cost report is denominated in lowest currency units, so a bare
    ``amount`` of 250 is $2.50 — and read as dollars it would be a 100x error a
    reader would believe. The parser says so instead."""
    path = tmp_path / "anthropic.csv"
    path.write_text(
        "date,model,uncached_input_tokens,output_tokens,cache_read_input_tokens,amount\n"
        "2026-09-26,claude-opus-5,1000,200,0,250\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as caught:
        parse_invoice_csv(path)

    message = str(caught.value)
    assert "'charged_usd'" in message
    assert "lowest currency units (cents)" in message
    assert "100x error" in message


def test_a_csv_reads_both_providers_own_shapes(tmp_path: Path) -> None:
    """The provider is sniffed from the token-category column names, which are the
    only ones the two spell differently."""
    openai_path = tmp_path / "openai.csv"
    openai_path.write_text(
        "date,model,input_tokens,input_cached_tokens,output_tokens,cost_usd\n"
        "2026-09-26,gpt-4o,1000000,400000,0,1.750000\n",
        encoding="utf-8",
    )
    anthropic_path = tmp_path / "anthropic.csv"
    anthropic_path.write_text(
        "date,model,uncached_input_tokens,output_tokens,cache_read_input_tokens,cost_usd\n"
        "2026-09-26,claude-opus-5,600000,0,400000,3.200000\n",
        encoding="utf-8",
    )

    openai_invoice = parse_invoice_csv(openai_path)
    anthropic_invoice = parse_invoice_csv(anthropic_path)

    assert openai_invoice.provider == "openai"
    assert openai_invoice.period == "2026-09-26"
    assert openai_invoice.source == str(openai_path)
    assert openai_invoice.lines[0].input_tokens == 600_000
    assert openai_invoice.lines[0].cache_read_tokens == 400_000
    assert openai_invoice.lines[0].charged_usd == Decimal("1.750000")

    assert anthropic_invoice.provider == "anthropic"
    assert anthropic_invoice.lines[0].input_tokens == 600_000
    assert anthropic_invoice.lines[0].cache_read_tokens == 400_000
    assert anthropic_invoice.lines[0].charged_usd == Decimal("3.200000")


def test_a_csv_whose_header_names_neither_provider_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "mystery.csv"
    path.write_text(
        "date,model,fresh,completions,cost_usd\n2026-09-26,gpt-4o,1000,200,2.500000\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cannot tell which provider"):
        parse_invoice_csv(path)

    # Naming the provider explicitly does not help when the columns are not there,
    # and says so rather than reading the wrong columns.
    with pytest.raises(ValueError, match="'input'"):
        parse_invoice_csv(path, provider="openai")


def test_a_provider_this_module_does_not_read_is_refused_by_name(tmp_path: Path) -> None:
    path = tmp_path / "gemini.csv"
    path.write_text(
        "date,model,input_tokens,output_tokens,cost_usd\n2026-09-26,gemini-2.5,1000,200,0.1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="has no statement format in this module"):
        parse_invoice_csv(path, provider="google")


def test_a_csv_with_a_malformed_amount_names_the_row_and_the_field(tmp_path: Path) -> None:
    path = tmp_path / "bad-amount.csv"
    path.write_text(
        "date,model,input_uncached_tokens,output_tokens,cost_usd\n"
        "2026-09-26,gpt-4o,1000,200,2.500000\n"
        "2026-09-26,gpt-4o,1000,200,not-a-number\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="row 1"):
        parse_invoice_csv(path)


def test_a_negative_amount_or_a_negative_token_count_is_refused(tmp_path: Path) -> None:
    negative_money = tmp_path / "negative-money.csv"
    negative_money.write_text(
        "date,model,input_uncached_tokens,output_tokens,cost_usd\n"
        "2026-09-26,gpt-4o,1000,200,-1.000000\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=">= 0"):
        parse_invoice_csv(negative_money)

    negative_tokens = tmp_path / "negative-tokens.csv"
    negative_tokens.write_text(
        "date,model,input_uncached_tokens,output_tokens,cost_usd\n"
        "2026-09-26,gpt-4o,-1000,200,1.000000\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=">= 0"):
        parse_invoice_csv(negative_tokens)


def test_a_json_statement_reads_money_as_a_string_and_a_number_through_its_repr(
    tmp_path: Path,
) -> None:
    """Money is a string on the wire because a JSON number has already been through a
    binary float. One is read back through its shortest repr — the text the author
    wrote — and 4.01 means exactly 4.01, not 4.0100000000000002."""
    path = tmp_path / "statement.json"
    path.write_text(
        json.dumps(
            {
                "provider": "openai",
                "period": "2026-09-26",
                "lines": [
                    {
                        "date": "2026-09-26",
                        "model": "gpt-4o",
                        "input_uncached_tokens": "1000000",
                        "output_tokens": "0",
                        "cost_usd": "2.500000",
                    },
                    {
                        "date": "2026-09-26",
                        "model": "gpt-4.1",
                        "input_uncached_tokens": "2000000",
                        "output_tokens": "0",
                        "cost_usd": 4.01,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    statement = parse_invoice_json(path)

    assert statement.provider == "openai"
    assert statement.period == "2026-09-26"
    assert statement.lines[1].charged_usd == Decimal("4.010000")
    assert statement.lines[1].input_tokens == 2_000_000


def test_a_json_statement_with_a_missing_field_names_the_row_and_the_field(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "provider": "openai",
                "period": "2026-09-26",
                "lines": [{"model": "gpt-4o", "output_tokens": 5}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as caught:
        parse_invoice_json(path)

    message = str(caught.value)
    assert "row 0" in message
    assert "'input'" in message
    assert "'charged_usd'" in message
    assert "must not reconcile" in message


def test_a_json_statement_that_is_not_json_raises_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "statement.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="is not valid JSON"):
        parse_invoice_json(path)


def test_a_json_statement_declaring_another_currency_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "eur.json"
    path.write_text(
        json.dumps({"provider": "openai", "period": "2026-09-26", "currency": "EUR", "lines": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="will not convert between them"):
        parse_invoice_json(path)


def test_a_statement_file_reconciles_against_a_ledger_file_end_to_end(tmp_path: Path) -> None:
    """The whole path a CFO would actually run, with a hardcoded expectation.

    The ledger holds one gpt-4o request of 1,000,000 input tokens, which the bundled
    card prices at 2.500000. The statement charges 2.750000, so the report's exact
    signed variance is **-0.250000** and the status is ``variance``.
    """
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            json.dumps(event(index, model="gpt-4o", input_tokens=1_000_000).to_dict())
            for index in (1, 2)
        )
        + "\n",
        encoding="utf-8",
    )
    statement = tmp_path / "openai.csv"
    statement.write_text(
        "date,model,input_uncached_tokens,output_tokens,cost_usd\n"
        "2026-09-26,gpt-4o,2000000,0,5.500000\n",
        encoding="utf-8",
    )

    from backstop.ledger import read_ledger

    read = read_ledger(ledger)
    result = reconcile_invoice(read.events, parse_invoice_csv(statement), CATALOG)

    assert len(read.events) == 2
    assert result.events == 2
    assert result.rows[0].ledger_usd == Decimal("5.000000")
    assert result.rows[0].invoice_usd == Decimal("5.500000")
    assert result.rows[0].variance_usd == Decimal("-0.500000")
    assert result.rows[0].status == STATUS_VARIANCE


# --------------------------------------------------------------------------
# The demo
# --------------------------------------------------------------------------


def test_the_demo_reconciles_every_status_this_module_can_report() -> None:
    """A demo whose rows all differ for the same reason demonstrates nothing, so the
    synthetic statement is declared to differ in five distinct ways. Asserted over
    the whole result so a status that stopped occurring would fail here."""
    result = run_demo()
    statuses = {row.status for variance in result.variances for row in variance.rows}

    assert statuses == {
        STATUS_MATCHED,
        STATUS_VARIANCE,
        STATUS_MISSING_FROM_INVOICE,
        STATUS_MISSING_FROM_LEDGER,
    }
    assert result.variances[0].provider != result.variances[1].provider


def test_the_demo_carries_a_row_that_reconciles_exactly() -> None:
    """Without this, a reader could not tell "the tool reports a match" from "the tool
    only ever reports differences"."""
    result = run_demo()

    matched = [
        row
        for variance in result.variances
        for row in variance.rows
        if row.status == STATUS_MATCHED
    ]

    assert len(matched) == 1
    assert matched[0].model == "gpt-5.6-sol"
    # 8,000 input at $4.00/Mtok is 0.032000 and 400 output at $20.00/Mtok is 0.008000.
    assert matched[0].ledger_usd == Decimal("0.040000")
    assert matched[0].invoice_usd == Decimal("0.040000")
    assert matched[0].variance_usd == Decimal("0.000000")


def test_the_demo_has_a_row_the_catalog_cannot_price() -> None:
    """The row the whole ledger pitch is about, in the reconciliation's own words."""
    result = run_demo()
    rows = {row.model: row for variance in result.variances for row in variance.rows}

    unpriced = rows["vendor-preview-2027"]
    assert unpriced.status == STATUS_MISSING_FROM_LEDGER
    assert unpriced.ledger_usd is None
    assert unpriced.invoice_usd == Decimal("0.075000")
    assert unpriced.unpriced_events == 34
    assert "unknown model" in (unpriced.reason or "")

    # And a model the ledger never saw, which is a different failure.
    silent = rows["claude-opus-5"]
    assert silent.status == STATUS_MISSING_FROM_LEDGER
    assert silent.ledger_events == 0
    assert silent.invoice_usd == Decimal("1.240000")
    assert silent.reason != unpriced.reason


def test_the_demo_tells_a_price_difference_from_a_count_difference() -> None:
    """The two rows that exist to prove the attribution works, with the exact figures
    the declaration implies."""
    result = run_demo()
    rows = {row.model: row for variance in result.variances for row in variance.rows}

    # gpt-4.1: identical token counts, a 10% higher input rate on the statement.
    rate = rows["gpt-4.1"]
    assert rate.status == STATUS_VARIANCE
    assert rate.token_delta["input"] == 0
    assert rate.variance_usd is not None and rate.variance_usd < 0
    assert "price difference" in (rate.reason or "")

    # claude-sonnet-4: 10,000 more output tokens on the statement, billed for.
    count = rows["claude-sonnet-4-20250514"]
    assert count.status == STATUS_VARIANCE
    assert count.token_delta["output"] == -10_000
    assert "count difference" in (count.reason or "")


def test_the_demo_output_is_byte_identical_across_two_runs() -> None:
    assert run_demo().to_markdown() == run_demo().to_markdown()
    assert run_demo().to_json() == run_demo().to_json()


def test_the_demo_is_offline_keyless_and_reads_no_clock() -> None:
    """No socket, no key, no file, and the events are the canonical fixed corpus."""
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("backstop reconcile --demo must not touch the network")

    original = socket.socket
    socket.socket = forbidden  # type: ignore[assignment]
    try:
        first = run_demo()
        second = run_demo()
    finally:
        socket.socket = original  # type: ignore[assignment]

    assert first.to_markdown() == second.to_markdown()
    assert first.to_dict()["simulated"] is True
    assert first.to_dict()["network_calls"] == 0
    assert first.to_dict()["deterministic"] is True


def test_the_demo_says_in_its_own_output_that_it_is_not_a_real_invoice() -> None:
    """Three places, because the over-claim is the failure mode this whole module is
    guarding against: the module docstring, the report, and the error budget."""
    from backstop.ledger import reconcile as module

    text = run_demo().to_markdown()
    assert "not** a reconciliation against a real" in text
    assert "has never run one" in text
    assert "column names the parsers read are" in text
    assert "verification against a real statement" in text
    # The budget carries its own caveat into the report.
    assert run_demo().budgets[0].note in text
    # The module docstring, for a reader who never runs the command.
    assert "statement file" in (module.__doc__ or "")
    assert "does **not**\ncall a provider API" in (module.__doc__ or "")


def test_the_demo_event_count_is_the_chargeback_corpus_plus_one() -> None:
    """1,967 events from the charge-back demo plus the one added event that gives the
    ``matched`` row a ledger side, and the added event's id is a fixed literal."""
    from backstop.ledger.demo import demo_events as chargeback_demo_events

    corpus = demo_events()

    assert len(chargeback_demo_events()) == 1_967
    assert len(corpus) == 1_968
    assert corpus[-1].model == "gpt-5.6-sol"
    assert corpus[-1].event_id == "0f5b9c4a7d2e1368000000000000beef"
    assert corpus[-1].cost is not None
    assert corpus[-1].cost.total_usd == Decimal("0.040000")


def test_the_status_vocabulary_is_five_and_declared_in_severity_order() -> None:
    assert STATUSES == (
        "matched",
        "within_tolerance",
        "variance",
        "missing_from_ledger",
        "missing_from_invoice",
    )


def test_the_scope_sentence_is_on_every_render() -> None:
    result = reconcile_invoice(
        [event(1, model="gpt-4o", input_tokens=1_000_000)],
        invoice(line("gpt-4o", charged_usd="2.500000", categories=openai_categories(1_000_000, 0))),
        CATALOG,
    )

    assert RECONCILIATION_SCOPE in result.to_markdown()
    assert result.to_dict()["scope"] == RECONCILIATION_SCOPE
    assert isinstance(result, InvoiceVariance)
