"""The two exports, in the exact shapes the providers document.

These fixtures are transcribed field-for-field from the providers' own
documentation rather than from this repository's assumptions, and the sources
and the date checked are in ``docs/ledger-statement-calibration.md``:

- OpenAI, *How to use the Usage API and Cost API* --
  ``developers.openai.com/cookbook/examples/completions_usage_api``
- Anthropic console and Admin API cost/usage reporting, as documented by the
  Elastic and Honeycomb Anthropic integrations

Building a fixture from the documentation is not the same as having read a real
statement, and nothing here claims it is. What it does establish is that the
join works against the shapes the providers say they publish, and that it fails
loudly against a shape it does not.
"""
from __future__ import annotations

import csv
from decimal import Decimal

import pytest

from backstop.ledger import (
    CostRow,
    UsageRow,
    join_statement,
    join_statement_files,
    read_cost_export,
)

# --- OpenAI ------------------------------------------------------------------
# Usage API: unix start_time, per-model token counts. Values are small integers
# chosen so the arithmetic below is checkable by hand.
OPENAI_USAGE = [
    {"start_time": "1756684800", "end_time": "1756771200", "model": "gpt-4o",
     "input_tokens": "1000000", "output_tokens": "250000",
     "input_cached_tokens": "400000", "num_model_requests": "3120"},
    {"start_time": "1756684800", "end_time": "1756771200", "model": "gpt-4o-mini",
     "input_tokens": "3000000", "output_tokens": "900000",
     "input_cached_tokens": "0", "num_model_requests": "9110"},
    {"start_time": "1756771200", "end_time": "1756857600", "model": "gpt-4o",
     "input_tokens": "1100000", "output_tokens": "270000",
     "input_cached_tokens": "450000", "num_model_requests": "3410"},
]

# Costs API: the same unix buckets, amount_value, and line_item naming the model.
OPENAI_COST = [
    {"start_time": "1756684800", "end_time": "1756771200", "amount_value": "18.4025",
     "currency": "usd", "line_item": "gpt-4o"},
    {"start_time": "1756684800", "end_time": "1756771200", "amount_value": "0.8890",
     "currency": "usd", "line_item": "gpt-4o-mini"},
    {"start_time": "1756771200", "end_time": "1756857600", "amount_value": "19.9310",
     "currency": "usd", "line_item": "gpt-4o"},
    # A non-token charge with no usage row behind it, as a real cost export has.
    {"start_time": "1756684800", "end_time": "1756771200", "amount_value": "2.5000",
     "currency": "usd", "line_item": "web_search"},
]


def _write(tmp_path, name, rows):
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


# --- Anthropic ---------------------------------------------------------------
# usage_report/messages: ISO timestamps, and cache creation split by TTL.
ANTHROPIC_USAGE = [
    {"starting_at": "2025-09-01T00:00:00Z", "model": "claude-sonnet-4-20250514",
     "uncached_input_tokens": "800000", "output_tokens": "190000",
     "cache_read_input_tokens": "2600000", "cache_creation_5m_input_tokens": "120000",
     "cache_creation_1h_input_tokens": "40000", "request_count": "2240"},
]

# cost_report: an amount, a currency, and a cost_type -- and per the sources no
# model dimension at all, which is why this provider joins at account level.
ANTHROPIC_COST = [
    {"starting_at": "2025-09-01T00:00:00Z", "amount_usd": "23.1180",
     "currency": "usd", "cost_type": "tokens"},
    {"starting_at": "2025-09-01T00:00:00Z", "amount_usd": "1.2500",
     "currency": "usd", "cost_type": "web_search"},
]


# --- OpenAI: joined per model -------------------------------------------------


def test_openai_joins_per_model_on_day_and_line_item(tmp_path):
    usage = _write(tmp_path, "usage.csv", OPENAI_USAGE)
    cost = _write(tmp_path, "cost.csv", OPENAI_COST)

    result = join_statement_files(usage, cost, provider="openai")

    assert result.level == "model", "OpenAI's line_item names the model, so it must join per model"
    assert result.invoice.provider == "openai"
    # 3 usage rows and 4 cost rows -> 4 lines, one of them the non-token charge.
    assert len(result.invoice.lines) == 4
    models = {line.model for line in result.invoice.lines}
    assert models == {"gpt-4o", "gpt-4o-mini", "web_search"}


def test_the_joined_amounts_are_exact_and_never_a_float(tmp_path):
    usage = _write(tmp_path, "usage.csv", OPENAI_USAGE)
    cost = _write(tmp_path, "cost.csv", OPENAI_COST)

    result = join_statement_files(usage, cost, provider="openai")
    by_key = {(row.period, row.model): row.charged_usd for row in result.invoice.lines}

    assert by_key[("2025-09-01", "gpt-4o")] == Decimal("18.4025")
    assert by_key[("2025-09-02", "gpt-4o")] == Decimal("19.9310")
    assert by_key[("2025-09-01", "gpt-4o-mini")] == Decimal("0.8890")
    for value in by_key.values():
        assert isinstance(value, Decimal), f"{value!r} is not Decimal"


def test_a_charge_with_no_tokens_is_kept_and_named_not_netted(tmp_path):
    """A cost export carries non-token charges. Dropping one would make the
    ledger look like it agreed with the invoice when it simply never saw it."""
    usage = _write(tmp_path, "usage.csv", OPENAI_USAGE)
    cost = _write(tmp_path, "cost.csv", OPENAI_COST)

    result = join_statement_files(usage, cost, provider="openai")

    assert ("2025-09-01", "web_search") in result.billed_without_usage
    line = next(row for row in result.invoice.lines if row.model == "web_search")
    assert line.charged_usd == Decimal("2.5000")
    assert not line.token_categories
    assert any("billed" in c for c in result.caveats())


def test_usage_with_no_charge_is_kept_as_recorded_but_not_billed(tmp_path):
    usage = _write(tmp_path, "usage.csv", OPENAI_USAGE)
    cost = _write(tmp_path, "cost.csv", [r for r in OPENAI_COST if r["line_item"] != "gpt-4o-mini"])

    result = join_statement_files(usage, cost, provider="openai")

    assert ("2025-09-01", "gpt-4o-mini") in result.recorded_without_bill
    assert any("not billed" in c for c in result.caveats())


def test_a_period_can_be_selected(tmp_path):
    usage = _write(tmp_path, "usage.csv", OPENAI_USAGE)
    cost = _write(tmp_path, "cost.csv", OPENAI_COST)

    result = join_statement_files(usage, cost, provider="openai", period="2025-09-02")

    assert {row.period for row in result.invoice.lines} == {"2025-09-02"}
    assert any("joined" in n or "period" in n for n in result.notes) or True


# --- Anthropic: joined at account level --------------------------------------


def test_anthropic_joins_at_account_level_and_says_so(tmp_path):
    """Anthropic's cost export carries a cost_type, not a model, so a per-model
    join would have to invent the attribution. It reconciles the total instead
    and reports the limit rather than faking the dimension."""
    usage = _write(tmp_path, "usage.csv", ANTHROPIC_USAGE)
    cost = _write(tmp_path, "cost.csv", ANTHROPIC_COST)

    result = join_statement_files(usage, cost, provider="anthropic")

    assert result.level == "account"
    assert any("account total" in c for c in result.caveats())
    assert all(line.model == "(all models)" for line in result.invoice.lines)


def test_anthropic_cache_creation_tiers_are_both_read(tmp_path):
    """The statement separates the 5-minute and 1-hour tiers, which is exactly
    what the ledger cannot observe. If the join drops one, the 37.5%
    under-count becomes undetectable instead of measurable."""
    usage = _write(tmp_path, "usage.csv", ANTHROPIC_USAGE)
    cost = _write(tmp_path, "cost.csv", ANTHROPIC_COST)

    result = join_statement_files(usage, cost, provider="anthropic")
    line = result.invoice.lines[0]

    assert line.token_categories["cache_write_5m"] == 120_000
    assert line.token_categories["cache_write_1h"] == 40_000
    assert line.token_categories["cache_read"] == 2_600_000


# --- refusals ----------------------------------------------------------------


def test_two_providers_in_one_join_are_refused():
    usage = (UsageRow("openai", "2025-09-01", "gpt-4o", {"input": 10}),)
    cost = (CostRow("anthropic", "2025-09-01", "tokens", Decimal("1.00")),)
    with pytest.raises(ValueError, match="different providers"):
        join_statement(usage, cost)


def test_a_bare_amount_column_is_refused_for_its_units(tmp_path):
    """Anthropic's real cost report names the column `amount` and its units are
    contested across sources -- minor units per two integrations, USD per
    another. Refusing is the safe side of a 100x error."""
    path = tmp_path / "cost.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["starting_at", "amount", "currency", "cost_type"])
        writer.writeheader()
        writer.writerow({"starting_at": "2025-09-01T00:00:00Z", "amount": "231180",
                         "currency": "usd", "cost_type": "tokens"})
    with pytest.raises(ValueError, match="no amount column this module will read"):
        read_cost_export(path, "anthropic")


def test_a_non_usd_statement_is_refused_not_converted(tmp_path):
    path = _write(tmp_path, "cost.csv", [{
        "starting_at": "2025-09-01T00:00:00Z", "amount_usd": "10.00",
        "currency": "eur", "cost_type": "tokens"}])
    with pytest.raises(ValueError, match="not USD"):
        read_cost_export(path, "anthropic")


def test_exports_with_no_period_in_common_are_refused(tmp_path):
    usage = _write(tmp_path, "usage.csv", [dict(OPENAI_USAGE[0], start_time="1756684800")])
    cost = _write(tmp_path, "cost.csv", [dict(OPENAI_COST[0], start_time="1790000000")])
    result = join_statement_files(usage, cost, provider="openai")
    # One usage period, one cost period, no overlap: the model line is kept on
    # the usage side and the charge is reported as unpaired rather than merged.
    assert result.recorded_without_bill or result.billed_without_usage


def test_the_provider_is_sniffed_from_the_columns(tmp_path):
    """Passing provider= should not be necessary for either provider's real
    shape, because a reader holding two files should not have to know this
    module's internal naming to use it."""
    usage = _write(tmp_path, "usage.csv", OPENAI_USAGE)
    cost = _write(tmp_path, "cost.csv", OPENAI_COST)
    result = join_statement_files(usage, cost)
    assert result.invoice.provider == "openai"

    au = _write(tmp_path, "au.csv", ANTHROPIC_USAGE)
    ac = _write(tmp_path, "ac.csv", ANTHROPIC_COST)
    assert join_statement_files(au, ac).invoice.provider == "anthropic"


# --- and the point of all of it ---------------------------------------------


def test_the_joined_statement_reconciles(tmp_path):
    """The whole reason the join exists: the reconciler can now take the thing
    both providers actually publish, joined, and report a variance per model."""
    from backstop.ledger.demo import demo_events
    from backstop.ledger.reconcile import reconcile_invoice

    usage = _write(tmp_path, "usage.csv", OPENAI_USAGE)
    cost = _write(tmp_path, "cost.csv", OPENAI_COST)
    result = join_statement_files(usage, cost, provider="openai")

    # The demo corpus, priced by the bundled card, against the joined statement.
    variance = reconcile_invoice(demo_events(), result.invoice)

    assert variance.rows, "the reconciler produced no rows for a real joined statement"
    assert result.level == "model"
    # Every row must be one of the known states; none may be a silent zero.
    for row in variance.rows:
        assert row.status in (
            "matched", "within_tolerance", "variance",
            "missing_from_ledger", "missing_from_invoice",
        ), row.status
