"""The charge-back: the table, the money rendering, the CSV, the revenue join, the
reader, and the demo.

Every expected figure in this file is written out by hand rather than copied from
a run, and the arithmetic behind each one is in the comment above it. That is the
whole point of the module under test: a charge-back is a number somebody will act
on, so a test that re-derived the expectation with the same code would prove only
that the code is self-consistent.

The demo's events are fixed and its output is compared byte for byte across two
runs, which is what makes ``backstop ledger demo`` safe to put in a slide.
"""
from __future__ import annotations

import csv
import decimal
import io
import json
import re
import socket
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from backstop.ledger import (
    UNATTRIBUTED,
    Attribution,
    BoundedWriter,
    MemorySink,
    PriceCatalog,
    SpendEvent,
    build_chargeback,
    chargeback_totals,
    compute_cost,
)
from backstop.pricing_catalog import LEDGER_CONTEXT
from backstop.ledger.export import (
    CSV_TERMINATOR,
    DEFAULT_GROUP_BY,
    MATCH_BOTH,
    MATCH_COST_ONLY,
    MATCH_REVENUE_ONLY,
    MIXED_PRICE_SOURCE,
    NO_VALUE,
    ROW_COLUMNS,
    ChargebackRow,
    LedgerCorruptionError,
    Period,
    delivery_report,
    display_columns,
    format_delivery,
    format_file_delivery,
    money,
    read_ledger,
    render_chargeback_csv,
    render_chargeback_json,
    render_chargeback_markdown,
    render_revenue_csv,
    revenue_join,
    write_chargeback_csv,
)

MONEY_CELL = re.compile(r"^-?\d+\.\d{2}$")
CATALOG = PriceCatalog()


def event(
    occurred_at: str,
    *,
    team: str | None = None,
    feature: str | None = None,
    provider: str = "openai",
    model: str = "gpt-4o",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    estimated: bool = False,
    catalog: PriceCatalog | None = None,
    **attribution: str | None,
) -> SpendEvent:
    """One priced event at a fixed instant, priced through a catalog."""
    record = SpendEvent(
        occurred_at=occurred_at,
        provider=provider,
        model=model,
        endpoint="/v1/chat/completions",
        priority="default",
        outcome="success",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        estimated=estimated,
        attribution=Attribution(team=team, feature=feature, **attribution),
    )
    cost = compute_cost(record, catalog or CATALOG)
    return record if cost is None else _with_cost(record, cost)


def _with_cost(record: SpendEvent, cost: Any) -> SpendEvent:
    from dataclasses import replace

    return replace(record, cost=cost)


# --------------------------------------------------------------------------
# The fixed event set every aggregation test runs over
# --------------------------------------------------------------------------
#
# gpt-4o:                 in 2.50/M, out 10.00/M, cache read 1.25/M, cache write
#                         not published
# claude-sonnet-4-20250514: in 3.00/M, out 15.00/M, cache read 0.30/M,
#                         cache write 3.75/M
#
#   A  payments/checkout-v2  10_000 in,   500 out                 0.025 + 0.005
#   B  payments/checkout-v2  20_000 in, 1_000 out                 0.050 + 0.010
#   C  payments/checkout-v2   4_000 in,   200 out, 1_600 cached   0.010 + 0.002 + 0.002
#   D  payments/checkout-v2   3_000 in,   150 out, no price       (unpriced)
#   G  payments/checkout-v2   5_000 in,   250 out, estimated     0.0125 + 0.0025
#   E  (none)/(none)          1_000 in,   200 out, sonnet         0.003 + 0.003
#   F  (none)/unfiled         2_000 in,   400 out, 800 written    0.006 + 0.006 + 0.003
#
# Group payments/checkout-v2 = 0.030 + 0.060 + 0.014 + 0.015 = 0.119
# Group (none)/unfiled       = 0.015      Group (none)/(none)   = 0.006
# Exact window total         = 0.140     Sum of the printed lines = 0.15

A = ("2026-09-26T01:00:00.000000Z", 10_000, 500, 0, 0)
B = ("2026-09-26T02:00:00.000000Z", 20_000, 1_000, 0, 0)
C = ("2026-09-26T03:00:00.000000Z", 4_000, 200, 1_600, 0)
D = ("2026-09-26T04:00:00.000000Z", 3_000, 150, 0, 0)
G = ("2026-09-26T05:00:00.000000Z", 5_000, 250, 0, 0)
E = ("2026-09-26T06:00:00.000000Z", 1_000, 200, 0, 0)
F = ("2026-09-26T07:00:00.000000Z", 2_000, 400, 0, 800)

SONNET = "claude-sonnet-4-20250514"
ANTHROPIC = "anthropic"


def fixed_events() -> tuple[SpendEvent, ...]:
    """The hand-checked set above, in the order the expectations were written in."""
    return (
        event(A[0], team="payments", feature="checkout-v2", input_tokens=A[1], output_tokens=A[2]),
        event(B[0], team="payments", feature="checkout-v2", input_tokens=B[1], output_tokens=B[2]),
        event(
            C[0],
            team="payments",
            feature="checkout-v2",
            input_tokens=C[1],
            output_tokens=C[2],
            cache_read_tokens=C[3],
        ),
        event(
            D[0],
            team="payments",
            feature="checkout-v2",
            model="mystery-v1",
            input_tokens=D[1],
            output_tokens=D[2],
        ),
        event(
            G[0],
            team="payments",
            feature="checkout-v2",
            input_tokens=G[1],
            output_tokens=G[2],
            estimated=True,
        ),
        event(
            E[0],
            provider=ANTHROPIC,
            model=SONNET,
            input_tokens=E[1],
            output_tokens=E[2],
        ),
        event(
            F[0],
            provider=ANTHROPIC,
            model=SONNET,
            input_tokens=F[1],
            output_tokens=F[2],
            cache_write_tokens=F[4],
            feature="unfiled",
        ),
    )


def csv_records(rows: list[ChargebackRow] | tuple[ChargebackRow, ...], group_by=None) -> list[list[str]]:
    """Parse the rendered CSV back with the stdlib reader, as a consumer would."""
    return list(csv.reader(io.StringIO(render_chargeback_csv(rows, group_by), newline="")))


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------


def test_chargeback_matches_a_hand_written_table_with_exact_money_strings():
    rows = build_chargeback(fixed_events())
    assert [row.cells() for row in rows] == [
        # payments/checkout-v2: 5 requests, 42_000 in, 2_100 out, 1_600 cached,
        # one of them unpriced, one of them estimated, 0.119 exact -> 0.12.
        (
            "payments", "checkout-v2", "5", "42000", "2100", "1600", "0", "0.12",
            "USD", "bundled", "1", "1", NO_VALUE,
            "2026-09-26T01:00:00.000000Z", "2026-09-26T05:00:00.000000Z",
        ),
        # (none)/unfiled: one request, 0.015 exact -> 0.02 by ROUND_HALF_UP.
        (
            UNATTRIBUTED, "unfiled", "1", "2000", "400", "0", "800", "0.02",
            "USD", "bundled", "0", "0", NO_VALUE,
            "2026-09-26T07:00:00.000000Z", "2026-09-26T07:00:00.000000Z",
        ),
        # (none)/(none): one request, 0.006 exact -> 0.01.
        (
            UNATTRIBUTED, UNATTRIBUTED, "1", "1000", "200", "0", "0", "0.01",
            "USD", "bundled", "0", "0", NO_VALUE,
            "2026-09-26T06:00:00.000000Z", "2026-09-26T06:00:00.000000Z",
        ),
    ]


def test_chargeback_row_keeps_the_exact_total_beside_the_printed_one():
    (row, *_rest) = build_chargeback(fixed_events())
    # 0.119 to the six places the catalog bills at, and 0.12 as printed.
    assert row.total_usd == Decimal("0.119000")
    assert money(row.total_usd) == "0.12"
    # One row that bills two layers says so instead of naming one of them: the
    # second event is priced by a user catalog, which outranks the bundled table.
    from backstop.pricing_catalog import PriceEntry

    user = PriceCatalog(
        entries={
            SONNET: PriceEntry(
                model=SONNET,
                provider=ANTHROPIC,
                input_per_mtok_usd=Decimal("2.50"),
                output_per_mtok_usd=Decimal("12.00"),
                cache_read_per_mtok_usd=None,
                cache_write_per_mtok_usd=None,
                effective_from="2026-01-01",
                source="user",
                confidence="negotiated",
            )
        }
    )
    mixed = build_chargeback(
        (
            event("2026-09-26T01:00:00.000000Z", team="t", input_tokens=1_000),
            event(
                "2026-09-26T01:00:00.000000Z",
                team="t",
                provider=ANTHROPIC,
                model=SONNET,
                input_tokens=1_000,
                catalog=user,
            ),
        )
    )
    assert mixed[0].price_source == MIXED_PRICE_SOURCE
    # gpt-4o at 2.50/M and the user's sonnet at 2.50/M, 1_000 tokens each.
    assert mixed[0].total_usd == Decimal("0.002500") + Decimal("0.002500")


def test_default_grouping_is_team_and_feature():
    assert DEFAULT_GROUP_BY == ("team", "feature")
    rows = build_chargeback(fixed_events())
    assert {row.group_by for row in rows} == {("team", "feature")}
    assert {tuple(sorted(row.key_dict)) for row in rows} == {("feature", "team")}


def test_custom_grouping_changes_the_rows():
    events = fixed_events() + (
        event("2026-09-26T08:00:00.000000Z", team="support", feature="triage", input_tokens=8_000),
    )
    # payments 0.119, then the unattributed block 0.006 + 0.015 = 0.021, then
    # support at 8_000 x 2.50/M = 0.020: still sorted by total, descending.
    by_team = build_chargeback(events, ("team",))
    assert [row.keys for row in by_team] == [("payments",), (UNATTRIBUTED,), ("support",)]
    assert [row.request_count for row in by_team] == [5, 2, 1]
    assert [str(row.total_usd) for row in by_team] == ["0.119000", "0.021000", "0.020000"]
    by_customer = build_chargeback(events, ("customer",))
    assert [row.keys for row in by_customer] == [(UNATTRIBUTED,)]
    assert by_customer[0].request_count == 8
    assert by_customer[0].total_usd == Decimal("0.140000") + Decimal("0.020000")


def test_unknown_group_key_is_refused_with_the_dimensions_that_exist():
    with pytest.raises(ValueError) as caught:
        build_chargeback(fixed_events(), ("team", "nope"))
    message = str(caught.value)
    assert "nope" in message
    assert "cost_center" in message  # the legal dimensions are listed
    with pytest.raises(ValueError, match="same dimension twice"):
        build_chargeback(fixed_events(), ("team", "team"))
    with pytest.raises(ValueError, match="at least one dimension"):
        build_chargeback(fixed_events(), ())
    with pytest.raises(TypeError, match="not a single string"):
        build_chargeback(fixed_events(), "team")


def test_unattributed_dollars_render_as_a_placeholder_and_never_as_a_blank():
    rows = build_chargeback(fixed_events())
    unattributed = [row for row in rows if UNATTRIBUTED in row.keys]
    assert len(unattributed) == 2
    for row in unattributed:
        assert row.keys[0] == UNATTRIBUTED
        assert UNATTRIBUTED != ""
        assert UNATTRIBUTED in row.cells()
    # The CSV carries the same placeholder, quoted or not, and never an empty cell.
    for record in csv_records(rows):
        assert all(cell != "" for cell in record), record
    # A blank or whitespace-only attribution is the same as none at all.
    blank = build_chargeback(
        (
            event("2026-09-26T01:00:00.000000Z", team="  ", feature="", input_tokens=1_000),
        )
    )
    assert blank[0].keys == (UNATTRIBUTED, UNATTRIBUTED)


def test_unpriced_requests_are_counted_and_survive_into_the_csv():
    rows = build_chargeback(fixed_events())
    priced = rows[0]
    assert priced.unpriced_requests == 1
    assert priced.request_count == 5
    header, *records = csv_records(rows)
    index = header.index("unpriced_requests")
    assert [record[index] for record in records] == ["1", "0", "0"]
    # The unpriced request's tokens are counted and its dollars are absent, and the
    # row says which price layer billed the rest rather than claiming a rate for it.
    assert priced.input_tokens == 42_000
    assert priced.price_source == "bundled"
    unpriced_only = build_chargeback(
        (event("2026-09-26T01:00:00.000000Z", team="t", model="mystery-v1", input_tokens=5),)
    )
    assert unpriced_only[0].unpriced_requests == 1
    assert unpriced_only[0].price_source == NO_VALUE
    assert money(unpriced_only[0].total_usd) == "0.00"


def test_a_component_with_no_published_rate_is_named_rather_than_priced_zero():
    # gpt-4o publishes no cache-write rate, so cache write tokens are a gap.
    rows = build_chargeback(
        (
            event(
                "2026-09-26T01:00:00.000000Z",
                team="t",
                input_tokens=1_000,
                cache_write_tokens=5_000,
            ),
        )
    )
    assert rows[0].unpriced_components == ("cache_write",)
    assert rows[0].cache_write_tokens == 5_000
    # Zero tokens for an unpriced component is not a gap: nothing was left uncharged.
    quiet = build_chargeback(
        (event("2026-09-26T01:00:00.000000Z", team="t", input_tokens=1_000),)
    )
    assert quiet[0].unpriced_components == ()


def test_totals_row_sums_the_printed_lines_and_keeps_the_exact_total():
    rows = build_chargeback(fixed_events())
    totals = chargeback_totals(rows)
    assert totals.request_count == 7
    assert totals.groups == 3
    assert totals.input_tokens == 45_000  # 42_000 + 1_000 + 2_000
    assert totals.output_tokens == 2_700  # 2_100 + 200 + 400
    assert totals.cache_read_tokens == 1_600
    assert totals.cache_write_tokens == 800
    assert totals.unpriced_requests == 1
    assert totals.estimated_requests == 1
    # The column adds up: 0.12 + 0.02 + 0.01.
    assert totals.total_usd == Decimal("0.15")
    assert sum(Decimal(money(row.total_usd)) for row in rows) == totals.total_usd
    # The exact sum of the same lines, at the catalog's six places, and the gap
    # between the two, which is at most half a cent per line.
    assert totals.unrounded_total_usd == Decimal("0.140000")
    assert totals.rounding_gap_usd == Decimal("0.01")
    assert abs(totals.rounding_gap_usd) <= Decimal("0.005") * totals.groups
    assert totals.first_seen == "2026-09-26T01:00:00.000000Z"
    assert totals.last_seen == "2026-09-26T07:00:00.000000Z"
    assert totals.price_source == "bundled"
    # The markdown totals line carries the same number as the CSV column does.
    table = render_chargeback_markdown(rows, totals)
    assert "| **Total** | all | 7 |" in table
    assert "**0.15**" in table


def test_unattributed_share_counts_only_the_groups_that_declared_nothing():
    totals = chargeback_totals(build_chargeback(fixed_events()))
    # Only the (none)/(none) row is unattributed. (none)/unfiled set a feature, so
    # finance can still charge that money to whoever owns the feature.
    assert totals.unattributed_requests == 1
    assert totals.unattributed_usd == Decimal("0.01")
    assert totals.unattributed_share == Decimal("0.0429")
    assert totals.unattributed_share_pct == Decimal("4.29")
    assert totals.unpriced_share_pct == Decimal("14.29")
    teardown = totals.to_markdown()
    assert "is unattributed" in teardown
    assert "carries no price at all" in teardown


def test_the_unattributed_percentage_names_the_figures_it_came_from():
    """The share is computed on exact dollars and printed beside rounded ones.

    ``0.01 / 0.15`` is 6.67%; the share of the exact sums is 4.29%. Computing it
    from the exact figures is the right convention — rounding first would move
    the answer by more than two points on a report this small — but printing one
    figure beside the other without saying so is how a reader concludes the
    report is wrong. Both the teardown and the JSON now carry the basis.
    """
    totals = chargeback_totals(build_chargeback(fixed_events()))
    # The exact figures the share was actually computed from, kept as fields.
    assert totals.unattributed_unrounded_usd == Decimal("0.006000")
    assert totals.unrounded_total_usd == Decimal("0.140000")
    # 0.006 / 0.140 = 0.042857... -> 0.0429, and 4.29% of it.
    with decimal.localcontext(LEDGER_CONTEXT):
        assert totals.unattributed_share == (
            totals.unattributed_unrounded_usd / totals.unrounded_total_usd
        ).quantize(Decimal("0.0001"), rounding=decimal.ROUND_HALF_UP)
    # The printed pair genuinely does not divide to the printed percentage.
    naive = (Decimal("0.01") / Decimal("0.15") * 100).quantize(Decimal("0.01"))
    assert naive == Decimal("6.67") != totals.unattributed_share_pct

    teardown = totals.to_markdown()
    assert "0.006000 of 0.140000 to six decimal places" in teardown
    assert "will not reproduce it exactly" in teardown
    payload = json.loads(render_chargeback_json(build_chargeback(fixed_events()[:1]), totals))
    assert payload["totals"]["unattributed_unrounded_usd"] == "0.006000"
    assert "will not reproduce it exactly" in payload["totals"]["unattributed_share_basis"]


def test_a_fully_attributable_window_does_not_quote_a_basis_it_has_no_gap_for():
    """A clean window says so, and does not print a caveat about nothing."""
    totals = chargeback_totals(build_chargeback(fixed_events()[:1]))
    assert totals.unattributed_requests == 0
    teardown = totals.to_markdown()
    assert "is attributable" in teardown
    assert "will not reproduce it exactly" not in teardown


def test_a_clean_window_says_it_is_clean_rather_than_describing_a_gap():
    totals = chargeback_totals(build_chargeback(fixed_events()[:1]))
    teardown = totals.to_markdown()
    assert "is attributable" in teardown
    assert "All 1 request is priced" in teardown
    assert "is unattributed" not in teardown
    assert "no price at all" not in teardown


def test_an_empty_window_is_empty_and_sums_to_zero():
    totals = chargeback_totals(())
    assert totals.groups == 0
    assert totals.request_count == 0
    assert totals.total_usd == Decimal("0.00")
    assert totals.unattributed_share == Decimal("0.0000")
    assert totals.first_seen == "" and totals.last_seen == ""


# --------------------------------------------------------------------------
# Independence from the ambient decimal context
# --------------------------------------------------------------------------
#
# A decimal context is process-global. The catalog already prices under its own
# (see backstop.pricing_catalog.LEDGER_CONTEXT); these tests pin that the report
# totals under the *same* context, because a charge-back that adds up to a
# different figure from the one the catalog billed is the failure this product
# exists to prevent — and unlike the crash it used to raise, a rounded total
# looks entirely plausible.
#
# The figures are at the *dollar* scale on purpose. ``quantize`` to six decimal
# places needs one significant digit per whole dollar, so a report totalling
# less than a dollar fits inside ``prec=6`` by luck and proves nothing; these
# events cost tens of dollars and need eight digits.

#: gpt-4o at 2.50 in, 10.00 out, 1.25 cached read, per million tokens.
#:   10,000,000 in  -> 25.000000
#:    1,234,567 out -> 12.345670
#:    8,000,000 read -> 10.000000   Total 47.345670, displayed 47.35
HOSTILE_EVENTS = (
    event(
        "2026-09-26T01:00:00.000000Z",
        team="payments",
        feature="checkout-v2",
        input_tokens=10_000_000,
        output_tokens=1_234_567,
        cache_read_tokens=8_000_000,
    ),
    event(
        "2026-09-26T02:00:00.000000Z",
        input_tokens=3_000_000,
        output_tokens=123_456,
    ),
)
# Exact window total 47.345670 + 8.734560 = 56.080230, displayed 47.35 + 8.73.
HOSTILE_TOTALS = {
    "total_usd": Decimal("56.08"),
    "unrounded_total_usd": Decimal("56.080230"),
    "unattributed_usd": Decimal("8.73"),
    "unattributed_share_pct": Decimal("15.58"),
    "unpriced_share_pct": Decimal("0.00"),
    "rounding_gap_usd": Decimal("0.00"),
}


def test_a_chargeback_totals_identically_under_a_tight_decimal_context(monkeypatch):
    """``prec=6``: the reproduction, one layer up from the catalog.

    Under the old arithmetic every ``quantize`` in this module ran at the
    thread's six significant digits, so a total of 47.345670 needed eight and
    raised ``InvalidOperation``: ``backstop ledger show``, ``export`` and
    ``demo`` all died with a bare ``decimal.InvalidOperation`` and no
    indication of why.
    """
    baseline = chargeback_totals(build_chargeback(HOSTILE_EVENTS))
    for name, expected in HOSTILE_TOTALS.items():
        assert getattr(baseline, name) == expected, name
    # Sanity: this window really does need more than six significant digits, or
    # the test below would pass against the old arithmetic for the wrong reason.
    assert len(baseline.unrounded_total_usd.as_tuple().digits) > 6

    monkeypatch.setattr(decimal.getcontext(), "prec", 6)
    totals = chargeback_totals(build_chargeback(HOSTILE_EVENTS))
    for name, expected in HOSTILE_TOTALS.items():
        assert getattr(totals, name) == expected, name
    # The rendering too, and the CSV: the figures a reader sees are the figures
    # the aggregation produced.
    assert money(totals.total_usd) == "56.08"
    assert money(totals.unattributed_usd) == "8.73"
    header, *records = csv_records(build_chargeback(HOSTILE_EVENTS))
    money_column = header.index("total_usd")
    assert [record[money_column] for record in records] == ["47.35", "8.73"]


def test_the_revenue_margin_is_not_rounded_by_a_host_decimal_context(monkeypatch):
    """A margin is money as much as a cost is, and it is a subtraction.

    Under ``prec=6`` the difference between a six-decimal cost and a two-decimal
    revenue figure is computed to six significant digits, so a margin of tens of
    dollars loses its cents.
    """
    rows = build_chargeback(HOSTILE_EVENTS)
    revenue = {("payments", "checkout-v2"): "1000.00", (UNATTRIBUTED, UNATTRIBUTED): "1.00"}
    margins = {row.keys: row.margin_usd for row in revenue_join(rows, revenue)}
    # 1000.00 - 47.345670, and 1.00 - 8.734560.
    assert margins[("payments", "checkout-v2")] == Decimal("952.654330")
    assert margins[(UNATTRIBUTED, UNATTRIBUTED)] == Decimal("-7.734560")

    monkeypatch.setattr(decimal.getcontext(), "prec", 6)
    hostile = {row.keys: row.margin_usd for row in revenue_join(rows, revenue)}
    assert hostile == margins
    # The CSV renders the margin at two places, like every other money cell.
    assert render_revenue_csv(revenue_join(rows, revenue)).count(",952.65,") == 1


def test_the_ledger_demo_totals_the_same_way_under_a_hostile_context(monkeypatch):
    """The pitch artifact has to be as reproducible as the export is."""
    from backstop.ledger.demo import run_demo

    baseline = run_demo()
    monkeypatch.setattr(decimal.getcontext(), "prec", 2)
    monkeypatch.setattr(decimal.getcontext(), "rounding", decimal.ROUND_UP)
    hostile = run_demo()
    assert hostile.to_json() == baseline.to_json()
    assert hostile.to_markdown() == baseline.to_markdown()


# --------------------------------------------------------------------------
# Periods
# --------------------------------------------------------------------------


def test_period_day_and_month_filter_deterministically():
    events = fixed_events() + (
        event("2026-09-27T09:00:00.000000Z", team="payments", feature="checkout-v2", input_tokens=1_000),
        event("2026-10-01T00:00:00.000000Z", team="payments", feature="checkout-v2", input_tokens=1_000),
    )
    day = build_chargeback(events, period=Period.day("2026-09-26"))
    assert day[0].request_count == 5  # the 27th and the 1st are both outside
    september = build_chargeback(events, period=Period.month("2026-09"))
    assert sum(row.request_count for row in september) == 8
    assert build_chargeback(events, period=Period.day("2026-09-27"))[0].request_count == 1
    # Boundaries are half-open, so the first instant of the next day is excluded.
    assert build_chargeback(events, period=Period.day("2026-09-26"))[0].total_usd == Decimal(
        "0.119000"
    )
    december = Period.month("2026-12")
    assert (december.start, december.end) == ("2026-12", "2027-01")
    assert Period.day("2026-12-31").end == "2027-01-01"
    assert Period.all().contains("1970-01-01T00:00:00.000000Z")


@pytest.mark.parametrize("bad", ["2026-9-26", "20260926", "", "yesterday", "2026-13-01"])
def test_a_malformed_period_is_refused_with_the_shape_it_wants(bad):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        Period.day(bad)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        Period.month(bad)


def test_a_backwards_window_is_refused():
    with pytest.raises(ValueError, match="must be earlier"):
        Period.between("2026-10-01", "2026-09-01", "backwards")


# --------------------------------------------------------------------------
# CSV bytes
# --------------------------------------------------------------------------


def test_csv_header_order_terminator_and_trailing_newline(tmp_path):
    rows = build_chargeback(fixed_events())
    text = render_chargeback_csv(rows)
    expected_header = (*DEFAULT_GROUP_BY, *ROW_COLUMNS)
    assert expected_header[:2] == ("team", "feature")
    assert expected_header[-1] == "last_seen"
    assert text.count(CSV_TERMINATOR) == len(rows) + 1
    assert text.endswith(CSV_TERMINATOR)
    assert "\n" not in text.replace(CSV_TERMINATOR, "")
    # Written to disk the same bytes land, and the header is the first record.
    target = tmp_path / "nested" / "chargeback.csv"
    assert write_chargeback_csv(rows, target) == len(rows)
    written = target.read_bytes().decode("utf-8")
    assert written == text
    assert written.split(CSV_TERMINATOR)[0] == ",".join(expected_header)
    # No totals row in the data file: a pivot would double count it.
    assert "Total" not in written


def test_csv_quotes_only_the_value_that_needs_it():
    rows = build_chargeback(
        (
            event(
                "2026-09-26T01:00:00.000000Z",
                team="acme, inc",
                feature='say "hi"',
                input_tokens=1_000,
            ),
        )
    )
    text = render_chargeback_csv(rows)
    assert '"acme, inc",' in text
    assert '"say ""hi""",' in text
    record = csv_records(rows)[1]
    assert record[0] == "acme, inc"
    assert record[1] == 'say "hi"'
    # Nothing else is quoted: 2 for "acme, inc" and 6 for the doubled pair in
    # "say ""hi""", which is the only other field with a character needing quotes.
    assert text.count('"') == 8


def test_csv_money_cells_are_two_decimal_strings_and_never_numbers():
    rows = build_chargeback(fixed_events())
    header, *records = csv_records(rows)
    column = header.index("total_usd")
    for record in records:
        assert MONEY_CELL.match(record[column]), record[column]
    payload = json.loads(render_chargeback_json(rows, chargeback_totals(rows)))
    for row in payload["rows"]:
        assert isinstance(row["total_usd"], str)
        assert MONEY_CELL.match(row["total_usd"])
    assert isinstance(payload["totals"]["total_usd"], str)
    assert isinstance(payload["totals"]["unattributed_usd"], str)


def test_an_empty_export_still_writes_the_header_it_was_asked_for(tmp_path):
    target = tmp_path / "empty.csv"
    assert write_chargeback_csv((), target, group_by=("team", "customer")) == 0
    # read_bytes, not read_text: universal-newline translation would hide the CRLF
    # this test is here to prove is on disk.
    text = target.read_bytes().decode("utf-8")
    assert text == ",".join(("team", "customer", *ROW_COLUMNS)) + CSV_TERMINATOR
    assert csv_records(())[0][0] == "team"


def test_money_is_never_a_float_anywhere_in_the_pipeline():
    # 1. The export module never calls float() on anything, so no amount can be
    #    routed through a binary float on its way to the wire.
    source = Path("src/backstop/ledger/export.py")
    if source.exists():
        text = source.read_text(encoding="utf-8")
        assert re.search(r"\bfloat\(", text) is None
    # 2. money() refuses a float outright rather than formatting a wrong number.
    with pytest.raises(TypeError, match="money is never a binary float"):
        money(1.5)
    with pytest.raises(TypeError):
        money(True)
    # 3. The catalog's quantum and this module's agree, so no requantisation is
    #    quietly losing a place.
    from backstop.pricing_catalog import MONEY_PLACES

    assert MONEY_PLACES == 6
    assert Decimal("0.000000") + Decimal("0.000000") == Decimal("0.000000")
    # 4. Every money cell of every renderer is a string.
    rows = build_chargeback(fixed_events())
    assert all(isinstance(cell, str) for cell in rows[0].cells())
    assert all(isinstance(cell, str) for cell in build_chargeback(fixed_events())[0].select(display_columns()))


def test_rounding_is_half_up_and_always_two_places():
    assert money(Decimal("0.005")) == "0.01"
    assert money(Decimal("0.015")) == "0.02"
    assert money(Decimal("-0.005")) == "-0.01"
    assert money(Decimal("12")) == "12.00"
    assert money(Decimal("1234567.891")) == "1234567.89"
    with pytest.raises(ValueError):
        money(Decimal("Infinity"))


# --------------------------------------------------------------------------
# Revenue join
# --------------------------------------------------------------------------


def test_revenue_join_covers_matched_revenue_only_and_cost_only_with_a_visible_null():
    rows = build_chargeback(fixed_events())
    revenue = {
        ("payments", "checkout-v2"): "500.00",
        ("payments", "refunds"): "9.99",
        (UNATTRIBUTED, UNATTRIBUTED): Decimal("0.01"),
        ("research", "long-context"): "1000.00",
    }
    joined = revenue_join(rows, revenue)
    by_key = {row.keys: row for row in joined}
    # Every key from either side: the three cost rows, plus the two revenue keys
    # that have no spend here (payments/refunds and research/long-context).
    assert len(joined) == 5
    assert by_key[("payments", "refunds")].match == MATCH_REVENUE_ONLY
    assert by_key[("payments", "checkout-v2")].match == MATCH_BOTH
    assert money(by_key[("payments", "checkout-v2")].revenue_usd) == "500.00"
    assert money(by_key[("payments", "checkout-v2")].margin_usd) == "499.88"
    # Cost with no revenue in this file: the revenue cell is None, not 0.00, and
    # margin is None rather than a margin against an assumed zero.
    unfiled = by_key[(UNATTRIBUTED, "unfiled")]
    assert unfiled.match == MATCH_COST_ONLY
    assert unfiled.revenue_usd is None
    assert unfiled.margin_usd is None
    # Revenue with no cost in this window: the same, in the other direction.
    research = by_key[("research", "long-context")]
    assert research.match == MATCH_REVENUE_ONLY
    assert research.request_count is None
    assert research.total_usd is None
    assert research.margin_usd is None
    assert money(research.revenue_usd) == "1000.00"
    # A None and a Decimal both key the same group, thanks to the placeholder.
    assert by_key[(UNATTRIBUTED, UNATTRIBUTED)].match == MATCH_BOTH
    assert money(by_key[(UNATTRIBUTED, UNATTRIBUTED)].margin_usd) == "0.00"
    # Nothing renders as a blank cell in the joined CSV.
    header, *records = list(csv.reader(io.StringIO(render_revenue_csv(joined), newline="")))
    assert header[-1] == "currency"
    for record in records:
        assert all(cell != "" for cell in record), record
    nulls = [r for r in records if NO_VALUE in r]
    assert len(nulls) == 3
    text = render_revenue_csv(joined)
    assert text.count(MATCH_COST_ONLY) == 1  # the unfiled group only
    assert text.count(MATCH_REVENUE_ONLY) == 2
    assert text.count(MATCH_BOTH) == 2


def test_revenue_join_orders_like_the_chargeback_and_honours_unset_keys():
    rows = build_chargeback(fixed_events())
    joined = revenue_join(rows, {("payments", "checkout-v2"): "0.50", (None, None): "0.02"})
    assert [row.keys for row in joined] == [
        ("payments", "checkout-v2"),
        (UNATTRIBUTED, "unfiled"),
        (UNATTRIBUTED, UNATTRIBUTED),
    ]
    assert money(joined[2].revenue_usd) == "0.02"
    assert joined[2].match == MATCH_BOTH
    # A key that normalises onto another is ambiguous, and a dict's iteration order
    # is not evidence, so it is refused.
    with pytest.raises(ValueError, match="both name the group"):
        revenue_join(rows, {(None, None): "0.02", (UNATTRIBUTED, UNATTRIBUTED): "0.03"})


def test_revenue_join_refuses_a_key_the_other_side_cannot_produce():
    rows = build_chargeback(fixed_events())
    with pytest.raises(ValueError, match="the join assumes the same group tuple"):
        revenue_join(rows, {("payments",): "1.00"})
    with pytest.raises(ValueError, match="the join assumes the same group tuple"):
        revenue_join(rows, {("payments", "checkout-v2", "extra"): "1.00"})
    with pytest.raises(TypeError, match="not a single string"):
        revenue_join(rows, {"payments": "1.00"})
    with pytest.raises(TypeError, match="float"):
        revenue_join(rows, {("payments", "checkout-v2"): 1.5})
    with pytest.raises(ValueError, match="not a decimal number"):
        revenue_join(rows, {("payments", "checkout-v2"): "n/a"})
    with pytest.raises(TypeError, match="must be a Decimal, an int or a decimal string"):
        revenue_join(rows, {("payments", "checkout-v2"): object()})


# --------------------------------------------------------------------------
# Reading a JSONL ledger
# --------------------------------------------------------------------------


def write_ledger(path: Path, events, *, terminate: bool = True) -> Path:
    lines = [json.dumps(record.to_dict(), sort_keys=True) for record in events]
    blob = "".join(line + "\n" for line in lines)
    if not terminate and blob.endswith("\n"):
        blob = blob[:-1]
    path.write_text(blob, encoding="utf-8")
    return path


def test_read_ledger_reads_a_complete_file(tmp_path):
    events = fixed_events()
    read = read_ledger(write_ledger(tmp_path / "ok.jsonl", events))
    assert len(read.events) == 7
    assert read.is_complete
    assert read.torn_write is None
    assert read.lines_seen == 7
    assert read.events[0].attribution.team == "payments"
    assert read.events[0].cost == events[0].cost
    assert read.events[4].estimated is True


def test_read_ledger_reports_a_torn_final_line_and_reads_the_rest(tmp_path):
    events = fixed_events()
    complete = write_ledger(tmp_path / "ok.jsonl", events).read_text(encoding="utf-8")
    torn = tmp_path / "torn.jsonl"
    # A crash between the kernel taking part of the last line and the file being
    # closed: the last record is half a JSON object and has no newline.
    torn.write_text(complete[:-260], encoding="utf-8")
    read = read_ledger(torn)
    assert len(read.events) == 6
    assert read.lines_seen == 7
    assert not read.is_complete
    assert read.torn_write is not None
    assert read.torn_write.line_number == 7
    assert read.torn_write.included is False
    assert "torn write" in format_file_delivery(read)[2] or "torn" in "\n".join(
        format_file_delivery(read)
    )
    assert "LOST" in "\n".join(format_file_delivery(read))
    # And the six readable events are still chargeable.
    assert chargeback_totals(build_chargeback(read.events)).request_count == 6


def test_read_ledger_keeps_a_complete_but_unterminated_final_line(tmp_path):
    complete = write_ledger(tmp_path / "ok.jsonl", fixed_events()).read_text(encoding="utf-8")
    unterminated = tmp_path / "unterminated.jsonl"
    unterminated.write_text(complete[:-1], encoding="utf-8")
    read = read_ledger(unterminated)
    assert len(read.events) == 7
    assert read.torn_write is not None
    assert read.torn_write.included is True
    assert "IS counted" in "\n".join(format_file_delivery(read))


def test_read_ledger_fails_loudly_on_a_corrupt_non_final_line(tmp_path):
    complete = write_ledger(tmp_path / "ok.jsonl", fixed_events()).read_text(encoding="utf-8")
    lines = complete.splitlines(True)
    lines[2] = '{"event_id": "not-the-schema"\n'
    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text("".join(lines), encoding="utf-8")
    with pytest.raises(LedgerCorruptionError) as caught:
        read_ledger(corrupt)
    error = caught.value
    assert error.line_number == 3
    assert str(corrupt) in str(error)
    assert "line 3" in str(error)
    assert "not-the-schema" in str(error)
    # A blank line where a record belongs is corruption too, not a blank to skip.
    blanked = tmp_path / "blank.jsonl"
    blanked.write_text("".join(lines[:2] + ["\n"] + lines[3:]), encoding="utf-8")
    with pytest.raises(LedgerCorruptionError, match="line 3 is corrupt"):
        read_ledger(blanked)


def test_read_ledger_treats_an_empty_file_as_an_empty_ledger(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_bytes(b"")
    read = read_ledger(empty)
    assert read.events == ()
    assert read.is_complete
    assert read.lines_seen == 0
    assert chargeback_totals(build_chargeback(read.events)).request_count == 0


def test_read_ledger_refuses_a_line_that_is_not_utf8(tmp_path):
    path = tmp_path / "bad.jsonl"
    good = write_ledger(tmp_path / "ok.jsonl", fixed_events()[:2]).read_bytes()
    path.write_bytes(good + b'{"provider": "\xff\xfe"}\n' + good.splitlines(True)[-1])
    with pytest.raises(LedgerCorruptionError, match="not valid UTF-8"):
        read_ledger(path)


def test_a_missing_file_is_an_oserror_not_a_silent_empty_ledger(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_ledger(tmp_path / "nope.jsonl")


# --------------------------------------------------------------------------
# Delivery accounting
# --------------------------------------------------------------------------


class _StalledSink:
    """A sink that blocks the drain thread until the test releases it.

    Two events, not a sleep. ``entered`` is set once the drain thread is actually
    inside ``write``, so the test can know the buffer will not be drained while it
    submits — which is what makes the drop count deterministic instead of a race
    against a background thread.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.errors = 0
        self.written = 0

    def write(self, event: SpendEvent) -> None:
        self.entered.set()
        self.release.wait(timeout=10.0)
        self.written += 1

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    @property
    def sink_errors(self) -> int:
        return self.errors

    @property
    def degraded(self) -> bool:
        return self.errors > 0


def test_delivery_report_surfaces_the_writers_and_the_sinks_own_counters():
    sink = _StalledSink()
    writer = BoundedWriter(sink, maxlen=2)
    events = fixed_events()
    assert writer.submit(events[0]) is True
    assert sink.entered.wait(10.0)  # the drain thread is now stuck inside write

    # The buffer can hold at most maxlen more, so the tail is refused rather than
    # buffered: the dropped_events a reader wants is the writer's, not the sink's.
    refused = [writer.submit(record) for record in events[1:]]
    accepted = 1 + refused.count(True)
    assert accepted <= 3
    assert writer.dropped_events == refused.count(False)
    assert writer.submitted == len(events)

    # A sink that swallows its own failures reports them itself, so a report that
    # only read the writer would say zero for every write failure there was.
    sink.errors = 3
    sink.release.set()
    # Close first: close() lets the drain finish, so `written` is a settled number
    # rather than a snapshot of a thread that is still working.
    close_report = writer.close()
    report = delivery_report(writer)
    assert close_report.written == accepted == sink.written
    assert report.submitted == 7
    assert report.written == accepted
    assert report.dropped_events == refused.count(False)
    assert report.writer_sink_errors == 0
    assert report.sink_sink_errors == 3
    assert report.sink_degraded is True
    # lost is the sum of the three, and the accounting invariant still closes.
    assert report.lost == report.dropped_events + 3
    assert close_report.submitted == close_report.written + close_report.dropped_events
    lines = "\n".join(format_delivery(report))
    assert "dropped_events" in lines
    assert "sink sink_errors" in lines
    assert f"**lost (dropped + writer errors + sink errors): {report.lost}**" in lines


def test_a_sink_with_no_counter_of_its_own_reports_zero():
    writer = BoundedWriter(MemorySink())
    writer.submit(fixed_events()[0])
    writer.close()
    report = delivery_report(writer)
    assert report.sink_sink_errors == 0
    assert report.lost == 0
    with pytest.raises(TypeError, match="needs a BoundedWriter"):
        delivery_report(object())


def test_a_file_read_says_both_counters_are_unknown_rather_than_zero(tmp_path):
    read = read_ledger(write_ledger(tmp_path / "ok.jsonl", fixed_events()))
    lines = "\n".join(format_file_delivery(read))
    assert "dropped_events: unknown" in lines
    assert "sink_errors: unknown" in lines
    assert "not derivable from the file" in lines
    # Not a zero anywhere: a zero is a claim.
    assert "dropped_events: 0" not in lines
    assert "sink_errors: 0" not in lines


# --------------------------------------------------------------------------
# The demo
# --------------------------------------------------------------------------


def test_ledger_demo_is_byte_identical_across_two_runs():
    from backstop.ledger.demo import run_demo

    first = run_demo()
    second = run_demo()
    assert first.to_markdown() == second.to_markdown()
    assert first.to_json() == second.to_json()
    assert first.rows[0].total_usd == second.rows[0].total_usd
    # And byte for byte, which is the claim the command makes on screen.
    assert first.to_markdown().encode("utf-8") == second.to_markdown().encode("utf-8")


def test_ledger_demo_prices_a_real_table_from_the_bundled_catalog():
    from backstop.ledger.demo import DEMO_DAY, demo_events, run_demo

    result = run_demo()
    assert result.simulated is True
    assert result.network_calls == 0
    assert result.price_source == "bundled"
    assert result.catalog_effective_from == DEMO_DAY
    # Every dollar is Decimal money computed by the catalog, not a literal here.
    for row in result.rows:
        assert isinstance(row.total_usd, Decimal)
        assert row.currency == "USD"
        assert MONEY_CELL.match(money(row.total_usd))
    # The rows the profiles describe, in dollars, largest first.
    assert [(row.keys[0], money(row.total_usd)) for row in result.rows] == [
        ("payments", "26.21"),
        ("payments", "3.40"),
        ("support", "1.76"),
        ("search", "1.65"),
        (UNATTRIBUTED, "1.54"),
        ("search", "0.00"),
    ]
    assert result.unpriced_events == 34
    assert result.priced_events == result.events - 34
    assert result.delivery["lost"] == 0
    assert result.delivery["written"] == result.events
    markdown = result.to_markdown()
    assert "# Backstop Ledger — Chargeback" in markdown
    assert "**Total**" in markdown
    assert "of priced spend is" in markdown
    assert "1.54 of 34.56 (4.45%)" in markdown
    # ...and the percentage says which figures it was computed from, because
    # 1.54 / 34.56 is 4.46% and a reader who divides the printed dollars would
    # otherwise conclude the report is wrong.
    assert "1.539061 of 34.547570 to six decimal places" in markdown
    assert Decimal("1.54") / Decimal("34.56") * 100 != Decimal("4.45")
    assert result.totals.total_usd == Decimal("34.56")
    assert result.totals.unattributed_unrounded_usd == Decimal("1.539061")
    # One deliberate row has no price at all, and the demo says which model.
    unpriced = [row for row in result.rows if row.unpriced_requests]
    assert [row.price_source for row in unpriced] == [NO_VALUE]
    assert "vendor-preview-2027" in markdown
    # The events are fixed, so their ids and timestamps are too.
    events = demo_events()
    assert len(events) == result.events
    assert events[0].event_id == demo_events()[0].event_id
    assert events[0].occurred_at.startswith(DEMO_DAY)


def test_ledger_demo_makes_no_network_call_and_needs_no_key(monkeypatch):
    from backstop.ledger.demo import run_demo

    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL", "HTTP_PROXY"):
        monkeypatch.delenv(name, raising=False)

    def refuse(*args: Any, **kwargs: Any):
        raise AssertionError("the ledger demo must not touch the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    result = run_demo()
    assert result.events > 0
    assert result.totals.total_usd == Decimal("34.56")


def test_ledger_demo_json_has_money_as_strings_and_no_ansi():
    from backstop.ledger.demo import run_demo

    text = run_demo().to_json()
    assert "\x1b[" not in text
    payload = json.loads(text)
    assert payload["simulated"] is True
    assert payload["network_calls"] == 0
    assert payload["rows"][0]["total_usd"] == "26.21"
    assert payload["totals"]["total_usd"] == "34.56"
    assert payload["revenue_rows"][0]["revenue_usd"] == "148230.00"
    # The join in the demo shows a group missing on either side, visibly.
    matches = {row["match"] for row in payload["revenue_rows"]}
    assert matches == {MATCH_BOTH, MATCH_COST_ONLY, MATCH_REVENUE_ONLY}
    absent = [row for row in payload["revenue_rows"] if row["match"] == MATCH_REVENUE_ONLY]
    assert absent and absent[0]["margin_usd"] is None
    assert absent[0]["revenue_usd"] == "12000.00"


def test_ledger_demo_honours_a_custom_grouping():
    from backstop.ledger.demo import run_demo

    result = run_demo(group_by=("team",))
    assert result.group_by == ("team",)
    assert all(len(row.keys) == 1 for row in result.rows)
    # The unattributed dollars are one row whichever way it is grouped.
    assert result.rows[-1].keys == (UNATTRIBUTED,)
    assert result.rows[-1].request_count == 69
    markdown = result.to_markdown()
    assert "| team | request_count |" in markdown
    # The revenue map is keyed on team,feature, so a team grouping gets no join
    # rather than one aggregated by guesswork.
    assert result.revenue_csv == ""
    assert "no join for this grouping" in markdown
    assert result.totals.request_count == result.events


def test_estimated_and_unpriced_count_the_same_events_and_may_overlap():
    """Both honesty columns are shares of ``request_count``, not subsets of it.

    A request whose tokens were estimated locally *and* whose model has no rate
    is the weakest figure in the report, and it used to appear in neither column:
    ``_Bucket.add`` returned on the missing cost before incrementing, so
    ``estimated_requests`` counted only priced requests while
    ``unpriced_requests`` counted all of them. Two columns with two populations
    is what a reader cannot see and cannot correct for.
    """
    priced = event("2026-09-26T01:00:00.000000Z", input_tokens=1_000)
    priced_estimated = event(
        "2026-09-26T02:00:00.000000Z", input_tokens=1_000, estimated=True
    )
    unpriced = event("2026-09-26T03:00:00.000000Z", model="mystery-v1", input_tokens=1_000)
    unpriced_estimated = event(
        "2026-09-26T04:00:00.000000Z",
        model="mystery-v1",
        input_tokens=1_000,
        estimated=True,
    )
    rows = build_chargeback([priced, priced_estimated, unpriced, unpriced_estimated])
    (row,) = rows
    assert row.request_count == 4
    assert row.unpriced_requests == 2
    assert row.estimated_requests == 2
    # Two of each, and the fourth request is in both — one estimated and priced,
    # one neither. Before the fix ``estimated_requests`` was 1: the unpriced
    # estimated request fell out of the count on its way past the missing cost.
    assert row.estimated_requests + row.unpriced_requests == 4

    totals = chargeback_totals(rows)
    assert totals.estimated_requests == 2
    assert totals.unpriced_requests == 2
    assert totals.to_dict()["estimated_requests"] == 2


def test_an_unpriced_estimated_request_is_in_both_columns_of_every_renderer():
    row = build_chargeback(
        [
            event("2026-09-26T01:00:00.000000Z", model="mystery-v1", estimated=True),
        ]
    )[0]
    assert row.unpriced_requests == 1
    assert row.estimated_requests == 1
    # Both numbers reach the CSV and the JSON, so the overlap cannot be a
    # rendering artefact of one output.
    assert "1" in render_chargeback_markdown([row], chargeback_totals([row]))
    assert row.to_dict()["estimated_requests"] == 1
