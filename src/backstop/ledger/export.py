"""Turning a priced ledger into a number finance can act on.

A :class:`~backstop.ledger.schema.SpendEvent` stream is the ledger's storage form:
exact, per-request, and useless to a person. This module is the other half — the
aggregation, the money rendering, the CSV, the revenue join, and the reader that
turns a JSONL file back into events under the torn-write policy that
:class:`~backstop.ledger.sink.JsonlSink` documents.

Four rules hold everything here together.

**Money is never a binary float.** Amounts arrive as
:class:`~decimal.Decimal` from :class:`~backstop.pricing_catalog.CostBreakdown`
and leave as *strings* with exactly two decimal places. A float is never used to
hold an amount, and a float is never accepted as one: :func:`revenue_join` refuses
a float revenue figure rather than quietly reading it back through its shortest
repr. A spreadsheet is handed ``"12.34"``, never ``12.34``, because a spreadsheet
that reads a charge as a float loses the cents somewhere and nobody can see it
happen.

**A missing value is never a blank cell.** An unattributed group key renders as
:data:`UNATTRIBUTED`, an empty component list as :data:`NO_VALUE`, and a null in
the revenue join as :data:`NO_VALUE` beside a ``match`` column that says which
side of the join was missing. An unattributed dollar is the thing finance most
needs to see, and a blank cell is the one thing that hides it.

**An unpriced request is a first-class outcome.** A group whose model is absent
from the rate card has ``cost is None`` on every event in it: the row is emitted
with its token counts, its ``unpriced_requests`` count, and a zero dollar total
that is labelled as unpriced rather than presented as free. Likewise
``unpriced_components`` names the token components a row carries tokens for but
has no published rate for — those dollars are a floor, not a measurement, and a
row that says so is worth more than a row that looks complete.

**Nothing reads a clock.** :class:`Period` filters on the ``occurred_at`` string
with a half-open comparison, and the format is fixed-width RFC 3339 UTC, so
lexicographic order *is* chronological order. The same event set always produces
the same table, byte for byte, and a test asserts exactly that by running the demo
twice and comparing the bytes.

The one thing a file cannot answer is how much spend was *lost* on the way to it.
A JSONL line records an event, never a counter, so :func:`read_ledger` cannot
report the writer's refusals or the sink's failures; it reports the one loss the
file itself can prove, a torn final line.
:func:`delivery_report` reads the real counters from a live writer, and the
formatter says plainly which of the two the caller is looking at.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from functools import wraps
from typing import Any, Callable, TypeVar

from ..pricing_catalog import COST_COMPONENTS, CURRENCY, LEDGER_CONTEXT
from .schema import Attribution, SpendEvent
from .sink import landed_events, lost_events

__all__ = [
    "CSV_TERMINATOR",
    "DEFAULT_GROUP_BY",
    "DISPLAY_COLUMNS",
    "FILE_DELIVERY_NOTE",
    "MATCH_BOTH",
    "MATCH_COST_ONLY",
    "MATCH_REVENUE_ONLY",
    "MIXED_PRICE_SOURCE",
    "NO_VALUE",
    "REVENUE_COLUMNS",
    "ROW_COLUMNS",
    "UNATTRIBUTED",
    "ChargebackRow",
    "ChargebackTotals",
    "DeliveryReport",
    "LedgerCorruptionError",
    "LedgerRead",
    "Period",
    "RevenueRow",
    "TornWrite",
    "build_chargeback",
    "chargeback_totals",
    "columns",
    "delivery_report",
    "display_columns",
    "format_delivery",
    "format_file_delivery",
    "money",
    "read_ledger",
    "render_chargeback_csv",
    "render_chargeback_json",
    "render_chargeback_markdown",
    "render_revenue_csv",
    "revenue_join",
    "write_chargeback_csv",
    "write_revenue_csv",
]

# --------------------------------------------------------------------------
# Sentinels
# --------------------------------------------------------------------------

#: Rendered in place of a group key the request never declared. Deliberately
#: loud, greppable and non-empty: ``"(unattributed)"`` cannot be mistaken for a
#: team called "n/a", and a spreadsheet that reads it as text will not turn it
#: into a blank cell.
UNATTRIBUTED = "(unattributed)"

#: Rendered where a cell has no value at all: an empty component list, a null in
#: the revenue join. Distinct from :data:`UNATTRIBUTED` because "nobody said who
#: spent this" and "there is no number here" are different facts.
NO_VALUE = "(none)"

#: A row's ``price_source`` when its requests were billed by more than one layer.
#: A charge-back that does not say which rate card produced the number is not
#: auditable, so the mixture is named rather than resolved to one of its members.
MIXED_PRICE_SOURCE = "mixed"

#: The three states of a revenue-join key, reported in the ``match`` column so a
#: null in the money columns is never ambiguous about *which* side was missing.
MATCH_BOTH = "both"
MATCH_COST_ONLY = "cost_only"
MATCH_REVENUE_ONLY = "revenue_only"

#: The grouping a caller gets when it does not ask for one: the two dimensions a
#: finance team almost always wants first, and the two the docs lead with.
DEFAULT_GROUP_BY: tuple[str, ...] = ("team", "feature")

#: RFC 4180 section 2.1: every record ends with a carriage return and a line
#: feed. Written explicitly, and paired with ``newline=""`` at the file, so the
#: export is CRLF on every platform rather than CRLF on Windows and LF elsewhere.
#: The value is a constant so a test can assert the exact bytes.
CSV_TERMINATOR = "\r\n"

#: Decimal places every reported money value is rendered with. Two, because a
#: charge-back is a currency amount and a currency amount has cents.
REPORT_PLACES = 2

#: Decimal places a share of spend is rendered with. Four, because "0.07" is not
#: a useful thing to tell a CFO about a gap they need to close.
SHARE_PLACES = 4

_REPORT_QUANTUM = Decimal("0.01")
_SHARE_QUANTUM = Decimal("0.0001")
#: The catalog's money quantum, re-declared here so :mod:`export` can requantise
#: a total without importing the catalog's private constants. A test asserts the
#: two agree.
_EXACT_QUANTUM = Decimal("0.000001")
_ZERO_EXACT = Decimal("0.000000")
_ZERO_REPORT = Decimal("0.00")

#: Component name -> the event field carrying that component's token count.
#: Mirrors :data:`backstop.pricing_catalog.COST_COMPONENTS`; a test asserts the
#: two stay the same set, because a new billable component with no column here
#: would silently under-count a row.
_COMPONENT_TOKENS: dict[str, str] = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cache_read_tokens",
    "cache_write": "cache_write_tokens",
}

_TOKEN_COLUMNS: tuple[str, ...] = tuple(
    _COMPONENT_TOKENS[component] for component in COST_COMPONENTS
)

#: The fixed columns of a charge-back row, after the group keys, in report
#: order. The group keys come first because a reader identifies a row by them;
#: the volume columns follow the count because they explain it; the money is
#: last among the numbers because it is the answer; the honesty columns
#: (``unpriced_requests``, ``estimated_requests``, ``unpriced_components``) sit
#: between the money and the window because they qualify the money; the window
#: closes the row.
ROW_COLUMNS: tuple[str, ...] = (
    "request_count",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_usd",
    "currency",
    "price_source",
    "unpriced_requests",
    "estimated_requests",
    "unpriced_components",
    "first_seen",
    "last_seen",
)

#: Columns a *displayed* table leads with: the volume, the money, and the three
#: honesty columns that qualify the money. The token breakdown, the currency, the
#: price source and the window are real columns with real values — they are in
#: the CSV and the JSON — but fifteen columns do not fit on a screen or in a
#: terminal, and a table nobody can read is not a report. Anything omitted from
#: the display is never omitted from the export.
DISPLAY_COLUMNS: tuple[str, ...] = (
    "request_count",
    "input_tokens",
    "output_tokens",
    "total_usd",
    "unpriced_requests",
    "unpriced_components",
)

#: Columns rendered right-aligned in markdown: the count-like ones. Everything
#: else is text, and a right-aligned word reads as a mistake.
_RIGHT_ALIGNED = frozenset(
    ("request_count", "estimated_requests", "unpriced_requests")
    + _TOKEN_COLUMNS
    + ("total_usd",)
)


# --------------------------------------------------------------------------
# Period
# --------------------------------------------------------------------------

#: A day and a month as the ledger writes them. The shapes are checked here and
#: the values are handed to :func:`datetime.date.fromisoformat`, which refuses a
#: day that does not exist, so "2026-02-30" fails here rather than matching a
#: window that no event can ever fall in.
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


@dataclass(frozen=True)
class Period:
    """A half-open window over ``occurred_at``, as a string comparison.

    ``occurred_at`` is fixed-width RFC 3339 UTC — ``YYYY-MM-DDTHH:MM:SS.ffffffZ``
    — so lexicographic order is chronological order and a filter is two string
    comparisons. No clock, no parsing, no timezone conversion: the same events and
    the same period give the same rows on every machine, which is what makes the
    demo's determinism assertable.

    ``start`` is inclusive and ``end`` exclusive, both plain prefixes, so
    ``Period.between("2026-09-01", "2026-10-01")`` is September and
    ``Period.month("2026-12")`` rolls the year over on its own. ``None`` on
    either side means unbounded in that direction, and :meth:`Period.all` is the
    window that takes every event.
    """

    start: str | None
    end: str | None
    label: str

    @classmethod
    def all(cls) -> "Period":
        """Every event, whatever it says it happened at."""
        return cls(None, None, "all time")

    @classmethod
    def day(cls, day: str) -> "Period":
        """The 24 hours of one UTC calendar day, e.g. ``"2026-09-25"``."""
        _check_prefix(day, _DAY_RE, "day", "2026-09-25")
        try:
            return cls(day, _next_day(day), f"day {day}")
        except ValueError as exc:  # a day that does not exist, e.g. 2026-02-30
            raise ValueError(
                f"a day must be YYYY-MM-DD and a real calendar date, got {day!r}: {exc}"
            ) from exc

    @classmethod
    def month(cls, month: str) -> "Period":
        """One UTC calendar month, e.g. ``"2026-09"``; December rolls the year."""
        _check_prefix(month, _MONTH_RE, "month", "2026-09")
        try:
            return cls(month, _next_month(month), f"month {month}")
        except ValueError as exc:  # a month outside 01..12
            raise ValueError(
                f"a month must be YYYY-MM and 01 to 12, got {month!r}: {exc}"
            ) from exc

    @classmethod
    def between(cls, start: str | None, end: str | None, label: str) -> "Period":
        """An arbitrary half-open window, ``start`` inclusive and ``end`` exclusive."""
        if start is not None and end is not None and start >= end:
            raise ValueError(
                f"period start {start!r} must be earlier than its end {end!r}"
            )
        return cls(start, end, label)

    def contains(self, occurred_at: str) -> bool:
        """Whether one event's timestamp falls in this window."""
        if self.start is not None and occurred_at < self.start:
            return False
        return not (self.end is not None and occurred_at >= self.end)


def _check_prefix(value: Any, pattern: re.Pattern[str], what: str, example: str) -> None:
    """Refuse anything not in the ledger's own UTC calendar shape.

    A period is given in ``YYYY-MM-DD`` for a day and ``YYYY-MM`` for a month,
    matching the wire format :class:`~backstop.ledger.schema.SpendEvent` writes,
    so the same string selects the same window wherever the command is run. A
    local date, a timestamp and a relative word are all refused rather than
    guessed at.
    """
    if not isinstance(value, str) or not pattern.match(value):
        raise ValueError(
            f"a {what} must be YYYY-MM-DD (a day) or YYYY-MM (a month), e.g. "
            f"{example!r}, got {value!r}"
        )


def _next_day(day: str) -> str:
    from datetime import date, timedelta

    parsed = date.fromisoformat(day)
    return (parsed + timedelta(days=1)).isoformat()


def _next_month(month: str) -> str:
    year_text, _, number_text = month.partition("-")
    year = int(year_text)
    index = int(number_text)
    if not 1 <= index <= 12:
        raise ValueError(f"the month number is 01 to 12, got {index:02d} in {month!r}")
    return f"{year + 1}-01" if index == 12 else f"{year}-{index + 1:02d}"


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------

_F = TypeVar("_F", bound=Callable[..., Any])


def _exact_money(fn: _F) -> _F:
    """Run one money function under :data:`~backstop.pricing_catalog.LEDGER_CONTEXT`.

    Every ``Decimal`` operator and every ``quantize`` reads the **thread's**
    context, and a decimal context is process-global: a host application that
    tightened ``prec`` would otherwise round this module's totals to a handful
    of significant digits — silently, because a rounded total is still a total.
    The catalog already prices under this context for the same reason, and a
    report that adds up to a different figure from the one the catalog billed
    is the one thing a charge-back cannot be.

    Applied to the public entry points rather than to each operation, so the
    whole of a function is covered whatever arithmetic a later change adds
    inside it. :class:`_Bucket` is deliberately *not* decorated: it is called
    once per event, and :func:`build_chargeback` holds the context around its
    whole loop instead of paying a context switch per row.
    """

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with localcontext(LEDGER_CONTEXT):
            return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


@_exact_money
def money(amount: Decimal) -> str:
    """Render an exact amount as a string with exactly two decimal places.

    Rounded half-up at the reporting place, which is the rounding a currency
    amount is conventionally stated at, and never formatted with a thousands
    separator: a grouping comma would force every money cell to be quoted in the
    CSV and would make the column depend on the value's magnitude.

    The input must already be a :class:`~decimal.Decimal`. A float is refused
    rather than coerced, because by the time an amount is a float the cents it
    lost are gone and formatting it would present a wrong number confidently.
    """
    if isinstance(amount, bool) or not isinstance(amount, Decimal):
        raise TypeError(
            f"an amount must be a Decimal, got {type(amount).__name__} {amount!r}; "
            "money is never a binary float"
        )
    if not amount.is_finite():
        raise ValueError(f"an amount must be finite, got {amount!r}")
    return format(amount.quantize(_REPORT_QUANTUM, rounding=ROUND_HALF_UP), "f")


@_exact_money
def _share(numerator: Decimal, denominator: Decimal) -> Decimal:
    """``numerator / denominator`` to four places, or zero when nothing divides it."""
    if denominator == 0:
        return _ZERO_REPORT.quantize(_SHARE_QUANTUM)
    return (numerator / denominator).quantize(_SHARE_QUANTUM, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ChargebackRow:
    """One group's worth of spend: the row a charge-back is made of.

    ``total_usd`` is the *exact* sum of the group's request amounts, at the
    catalog's six decimal places, and is not rounded for display. The display
    rounding lives in :func:`money`, so the machine value and the printed value
    are both available and neither is inferred from the other.

    ``price_source`` is the price layer that billed the group, or
    :data:`MIXED_PRICE_SOURCE` when the group's requests came from more than one,
    or :data:`NO_VALUE` when nothing in the group was priced at all.

    ``unpriced_requests`` counts events whose ``cost`` is ``None``: the price
    catalog does not know their model. Their tokens are counted and their dollars
    are absent, which is a different thing from a zero.

    ``unpriced_components`` names the billable components this group carried
    tokens for but had no published rate for — a model with no cache-write rate
    charges the cache write at zero *and says so*. Its members are a subset of
    :data:`backstop.pricing_catalog.COST_COMPONENTS` in that order, so a row's
    component list is comparable across rows and across runs.

    ``first_seen`` and ``last_seen`` are the earliest and latest ``occurred_at``
    in the group, compared as strings, which is chronological here because the
    format is fixed-width.
    """

    group_by: tuple[str, ...]
    keys: tuple[str, ...]
    request_count: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_usd: Decimal
    currency: str
    price_source: str
    unpriced_requests: int
    estimated_requests: int
    unpriced_components: tuple[str, ...]
    first_seen: str
    last_seen: str

    @property
    def key_dict(self) -> dict[str, str]:
        """The group keys as a mapping, for a caller joining on them.

        ``strict=True`` because the two are the same list by construction: a row
        whose ``keys`` did not line up with its ``group_by`` would quietly drop a
        dimension here, and a dropped dimension is an unattributed dollar.
        """
        return dict(zip(self.group_by, self.keys, strict=True))

    @property
    def is_unattributed(self) -> bool:
        """Whether this group declared nothing on any dimension it grouped on.

        This is the row an unattributed dollar lands in, and the one the
        unattributed share is computed from. A group that set some keys and left
        others unset is partially attributed: finance can still charge it, so it
        is not counted here.
        """
        return all(key == UNATTRIBUTED for key in self.keys)

    def to_dict(self) -> dict[str, Any]:
        """The JSON form: money as a two-decimal string, never as a number."""
        return {"group_by": list(self.group_by), **self.as_dict()}

    def as_dict(self) -> dict[str, Any]:
        """The row's own cells as a mapping, group keys first."""
        payload: dict[str, Any] = dict(self.key_dict)
        payload.update(
            {
                "request_count": self.request_count,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cache_read_tokens": self.cache_read_tokens,
                "cache_write_tokens": self.cache_write_tokens,
                "total_usd": money(self.total_usd),
                "currency": self.currency,
                "price_source": self.price_source,
                "unpriced_requests": self.unpriced_requests,
                "estimated_requests": self.estimated_requests,
                "unpriced_components": list(self.unpriced_components),
                "first_seen": self.first_seen,
                "last_seen": self.last_seen,
            }
        )
        return payload

    def cells(self) -> tuple[str, ...]:
        """The row as strings, in :func:`columns` order.

        The one rendering path. The CSV, the markdown table and the JSON all
        build from this, so a table and the file exported beside it cannot
        disagree about a single cell.
        """
        return (
            *self.keys,
            str(self.request_count),
            str(self.input_tokens),
            str(self.output_tokens),
            str(self.cache_read_tokens),
            str(self.cache_write_tokens),
            money(self.total_usd),
            self.currency,
            self.price_source,
            str(self.unpriced_requests),
            str(self.estimated_requests),
            "|".join(self.unpriced_components) or NO_VALUE,
            self.first_seen,
            self.last_seen,
        )

    def select(self, names: Sequence[str]) -> tuple[str, ...]:
        """This row's cells for a subset of the columns, in the order given.

        Lets a narrow display show the same numbers the wide export contains:
        both read the same cells, so a column cannot drift between the table a
        person reads and the file a spreadsheet imports. An unknown name is a
        ``KeyError`` naming it, because a silently dropped column is the one bug
        this module exists to prevent.
        """
        available = dict(zip(columns(self.group_by), self.cells(), strict=True))
        missing = [name for name in names if name not in available]
        if missing:
            raise KeyError(
                f"unknown charge-back column(s) {missing}; the row has {list(available)}"
            )
        return tuple(available[name] for name in names)


@dataclass(frozen=True)
class ChargebackTotals:
    """The line below the table: what the whole window cost, and what is missing.

    ``total_usd`` is the sum of the *displayed* line values, so the column adds
    up to the total a reader can verify by eye and a spreadsheet can verify with
    ``SUM``. ``unrounded_total_usd`` is the exact six-decimal sum of the same
    lines, kept so nothing is hidden: the two differ by at most half a cent per
    line, and a caller who needs the exact figure has it.

    ``unattributed_usd`` and ``unattributed_share`` answer the question a CFO
    asks first: how much of this spend can nobody be charged for. The share is
    of *priced* spend, because an unpriced request has no dollars to be a
    fraction of; ``unpriced_requests`` is reported next to it so the two gaps are
    never confused.

    ``unattributed_usd`` and ``total_usd`` are the *displayed* cents and
    ``unattributed_unrounded_usd`` and ``unrounded_total_usd`` the exact sums the
    share was actually computed from. The two pairs differ by up to half a cent
    per line, which is enough to move the quotient: dividing the printed 1.54 by
    the printed 34.56 gives 4.46% where the exact figures give 4.45%.
    :attr:`unattributed_share_basis` is the sentence that says so, and every
    renderer that prints the percentage prints it with.
    """

    group_by: tuple[str, ...]
    groups: int
    request_count: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_usd: Decimal
    unrounded_total_usd: Decimal
    currency: str
    price_source: str
    unpriced_requests: int
    estimated_requests: int
    unattributed_requests: int
    unattributed_usd: Decimal
    unattributed_unrounded_usd: Decimal
    unattributed_share: Decimal
    unpriced_components: tuple[str, ...]
    first_seen: str
    last_seen: str

    @property
    def unattributed_share_basis(self) -> str:
        """The exact figures the unattributed share was computed from.

        The share is ``unattributed_unrounded_usd / unrounded_total_usd`` at six
        decimal places, while the dollars printed beside it are the displayed
        cents. Rounding each side to cents first moves the quotient — dividing
        1.54 by 34.56 gives 4.46% where the exact figures give 4.45% — so a
        reader who does the arithmetic on the printed numbers concludes the
        report is wrong. Computing the share from the exact sums is the right
        convention and the only dishonest thing about it was not saying so, so
        every renderer that prints the percentage prints this with it.
        """
        return (
            f"The share is computed on the exact totals — "
            f"{format(self.unattributed_unrounded_usd, 'f')} of "
            f"{format(self.unrounded_total_usd, 'f')} to six decimal places — so "
            "dividing the rounded dollars above will not reproduce it exactly."
        )

    @property
    def unpriced_share(self) -> Decimal:
        """The share of requests in the window that carry no price at all."""
        return _share(Decimal(self.unpriced_requests), Decimal(self.request_count))

    @property
    @_exact_money
    def unpriced_share_pct(self) -> Decimal:
        """``unpriced_share`` as a percentage, to two places."""
        return (self.unpriced_share * 100).quantize(
            _REPORT_QUANTUM, rounding=ROUND_HALF_UP
        )

    @property
    @_exact_money
    def unattributed_share_pct(self) -> Decimal:
        """``unattributed_share`` as a percentage, to two places."""
        return (self.unattributed_share * 100).quantize(
            _REPORT_QUANTUM, rounding=ROUND_HALF_UP
        )

    @property
    @_exact_money
    def rounding_gap_usd(self) -> Decimal:
        """Displayed total minus exact total: at most half a cent per line."""
        return self.total_usd - self.unrounded_total_usd.quantize(
            _REPORT_QUANTUM, rounding=ROUND_HALF_UP
        )

    def to_dict(self) -> dict[str, Any]:
        """The JSON form, money as strings and the share as a decimal string."""
        return {
            "group_by": list(self.group_by),
            "groups": self.groups,
            "request_count": self.request_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total_usd": money(self.total_usd),
            "unrounded_total_usd": str(self.unrounded_total_usd),
            "currency": self.currency,
            "price_source": self.price_source,
            "unpriced_requests": self.unpriced_requests,
            "estimated_requests": self.estimated_requests,
            "unattributed_requests": self.unattributed_requests,
            "unattributed_usd": money(self.unattributed_usd),
            "unattributed_unrounded_usd": str(self.unattributed_unrounded_usd),
            "unattributed_share": format(self.unattributed_share, "f"),
            "unattributed_share_pct": format(self.unattributed_share_pct, "f"),
            "unattributed_share_basis": self.unattributed_share_basis,
            "unpriced_share": format(self.unpriced_share, "f"),
            "unpriced_components": list(self.unpriced_components),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    def to_markdown(self) -> str:
        """The teardown lines a reader should see before the table's fine print.

        Each line states what the number *is*, and a zero gets the sentence that
        is true for a zero rather than a sentence about a gap that is not there:
        "0.00% of priced spend is unattributed — nobody can be charged for that
        money" is a sentence about nothing, and a reader who has to work out
        whether a zero is good news or a rounding artefact stops reading.
        """
        if self.unattributed_requests:
            unattributed = (
                f"- **{money(self.unattributed_usd)} of {money(self.total_usd)} "
                f"({self.unattributed_share_pct}%) of priced spend is "
                f"unattributed** — {self.unattributed_requests} of "
                f"{self.request_count} requests declared no value on any grouped "
                f"dimension, so nobody can be charged for that money. "
                f"{self.unattributed_share_basis}"
            )
        else:
            unattributed = (
                f"- **All {money(self.total_usd)} of priced spend is attributable** — "
                f"every one of the {self.request_count} requests in this window "
                "named a value on every grouped dimension."
            )
        if self.unpriced_requests:
            plural = "" if self.unpriced_requests == 1 else "s"
            unpriced = (
                f"- **{self.unpriced_requests} request{plural} "
                f"({self.unpriced_share_pct}%) carr{'ies' if plural == '' else 'y'} "
                "no price at all.** The cost "
                "is absent, not zero: every total above understates real spend by an "
                "unknown amount, and adding a guess would make it worse."
            )
        else:
            unpriced = (
                f"- **All {self.request_count} request"
                f"{'' if self.request_count == 1 else 's'} "
                f"{'is' if self.request_count == 1 else 'are'} priced.** No total "
                "here is missing a rate card entry."
            )
        return "\n".join((unattributed, unpriced))


# --------------------------------------------------------------------------
# Grouping
# --------------------------------------------------------------------------


def _check_group_by(group_by: Sequence[str] | str) -> tuple[str, ...]:
    """Validate a grouping against :class:`~backstop.ledger.schema.Attribution`."""
    if isinstance(group_by, str):
        raise TypeError(
            "group_by must be a sequence of attribution field names, not a single "
            f"string {group_by!r}; pass ('team', 'feature') or 'team,feature' from a "
            "command line"
        )
    fields = tuple(Attribution.__dataclass_fields__)
    names = tuple(group_by)
    if not names:
        raise ValueError(f"group_by must name at least one dimension; try {list(DEFAULT_GROUP_BY)}")
    for name in names:
        if name not in fields:
            raise ValueError(
                f"unknown group-by dimension {name!r}; the ledger groups on "
                f"{list(fields)}"
            )
    if len(set(names)) != len(names):
        raise ValueError(f"group_by names the same dimension twice: {list(names)}")
    return names


def _key_value(attribution: Attribution, name: str) -> str:
    """One group key, rendered. An unset or blank value becomes the placeholder."""
    value = attribution[name]
    return UNATTRIBUTED if value is None else value


def _one_source(sources: set[str]) -> str:
    """One price layer's name, the mixture's name, or the empty-value marker.

    A row or a total that was billed by two layers says ``mixed`` rather than
    picking one: a charge-back that does not say which rate card produced the
    number is not auditable, and picking the first one would be a guess presented
    as a fact.
    """
    if not sources:
        return NO_VALUE
    if len(sources) == 1:
        return next(iter(sources))
    return MIXED_PRICE_SOURCE


class _Bucket:
    """The running totals for one group, accumulated event by event."""

    __slots__ = (
        "request_count",
        "tokens",
        "exact_total",
        "unpriced",
        "estimated",
        "sources",
        "unpriced_components",
        "first_seen",
        "last_seen",
    )

    def __init__(self, occurred_at: str) -> None:
        self.request_count = 0
        self.tokens = [0, 0, 0, 0]
        self.exact_total = _ZERO_EXACT
        self.unpriced = 0
        self.estimated = 0
        self.sources: set[str] = set()
        self.unpriced_components: set[str] = set()
        self.first_seen = occurred_at
        self.last_seen = occurred_at

    def add(self, event: SpendEvent) -> None:
        self.request_count += 1
        for index, component in enumerate(COST_COMPONENTS):
            self.tokens[index] += getattr(event, _COMPONENT_TOKENS[component])
        # The window covers every event in the group, priced or not: an unpriced
        # request still happened, and a group's last_seen that ignored it would
        # understate how long the group was spending.
        if event.occurred_at < self.first_seen:
            self.first_seen = event.occurred_at
        if event.occurred_at > self.last_seen:
            self.last_seen = event.occurred_at
        cost = event.cost
        if cost is None:
            self.unpriced += 1
            return
        if event.estimated:
            self.estimated += 1
        self.sources.add(cost.price_source)
        self.exact_total += cost.total_usd
        # A component is a gap only when the request actually carried tokens for
        # it *and* the winning price published no rate for it. Zero tokens and a
        # missing rate is not a gap, because nothing was left uncharged.
        for component in COST_COMPONENTS:
            if component not in cost.priced_components and getattr(
                event, _COMPONENT_TOKENS[component]
            ):
                self.unpriced_components.add(component)


@_exact_money
def build_chargeback(
    events: Iterable[SpendEvent],
    group_by: Sequence[str] = DEFAULT_GROUP_BY,
    period: Period | None = None,
    currency: str = CURRENCY,
) -> tuple[ChargebackRow, ...]:
    """Aggregate spend events into charge-back rows, largest total first.

    Every event whose ``occurred_at`` falls in ``period`` lands in exactly one
    row, keyed by its values for the ``group_by`` dimensions. An event that
    declared nothing on a dimension gets :data:`UNATTRIBUTED` there, so its
    dollars appear in a row somebody can find rather than in a row somebody has
    to guess at.

    An event with ``cost is None`` still counts: its tokens go in the row, its
    ``unpriced_requests`` count goes up, and its dollars are absent. An event
    whose ``cost.currency`` is not the requested ``currency`` is refused rather
    than summed, because adding two currencies produces a number that is not
    money in either of them.

    Ordering is ``total_usd`` descending with the rendered group key as the
    tie-break, so two runs over the same events produce the same table in the
    same order — the property the demo's byte-for-byte determinism rests on.

    Purity: no clock, no I/O, no global state. Same events, same call, same rows.

    The exact per-request totals are accumulated in the loop below, which
    :func:`_exact_money` holds :data:`~backstop.pricing_catalog.LEDGER_CONTEXT`
    around — once, rather than per event, which is why :class:`_Bucket` is not
    decorated itself. Without it a host's ``prec`` would round each addition and
    the report would quietly disagree with the figures the catalog billed.
    """
    names = _check_group_by(group_by)
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError(f"currency must be a non-empty str, got {currency!r}")
    buckets: dict[tuple[str, ...], _Bucket] = {}
    for event in events:
        if not isinstance(event, SpendEvent):
            raise TypeError(
                f"build_chargeback takes SpendEvent objects, got "
                f"{type(event).__name__} {event!r}"
            )
        if period is not None and not period.contains(event.occurred_at):
            continue
        cost = event.cost
        if cost is not None and cost.currency != currency:
            raise ValueError(
                f"cannot total {cost.currency!r} spend into a {currency!r} report; "
                f"event {event.event_id} is priced in {cost.currency}"
            )
        key = tuple(_key_value(event.attribution, name) for name in names)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = buckets[key] = _Bucket(event.occurred_at)
        bucket.add(event)
    rows = [
        _row(names, key, bucket, currency)
        for key, bucket in buckets.items()
    ]
    rows.sort(key=lambda row: (-row.total_usd, row.keys))
    return tuple(rows)


def _row(
    names: tuple[str, ...],
    key: tuple[str, ...],
    bucket: _Bucket,
    currency: str,
) -> ChargebackRow:
    sources = bucket.sources
    return ChargebackRow(
        group_by=names,
        keys=key,
        request_count=bucket.request_count,
        input_tokens=bucket.tokens[0],
        output_tokens=bucket.tokens[1],
        cache_read_tokens=bucket.tokens[2],
        cache_write_tokens=bucket.tokens[3],
        total_usd=bucket.exact_total,
        currency=currency,
        price_source=_one_source(sources),
        unpriced_requests=bucket.unpriced,
        estimated_requests=bucket.estimated,
        unpriced_components=tuple(
            component for component in COST_COMPONENTS if component in bucket.unpriced_components
        ),
        first_seen=bucket.first_seen,
        last_seen=bucket.last_seen,
    )


@_exact_money
def chargeback_totals(
    rows: Sequence[ChargebackRow], group_by: Sequence[str] | None = None
) -> ChargebackTotals:
    """Fold rows into the window totals, including what is unattributed.

    ``unattributed_usd`` is the total of the rows that declared nothing on any
    grouped dimension (:attr:`ChargebackRow.is_unattributed`). A row that set
    some keys and left others blank is *partially* attributed — finance can still
    charge it — so it is counted as attributed and its unattributed cells are
    visible in the table itself.

    With no rows the window is empty rather than zero-cost: a report over no
    events says so, and every count is zero. ``first_seen``/``last_seen`` are
    empty strings, because there is no window to describe.
    """
    names = _check_group_by(group_by if group_by is not None else _rows_group_by(rows))
    exact = _ZERO_EXACT
    display = _ZERO_REPORT
    tokens = [0, 0, 0, 0]
    unpriced = 0
    estimated = 0
    unattributed_requests = 0
    unattributed_display = _ZERO_REPORT
    unattributed_exact = _ZERO_EXACT
    components: set[str] = set()
    sources: set[str] = set()
    first_seen = ""
    last_seen = ""
    for row in rows:
        exact += row.total_usd
        display += Decimal(money(row.total_usd))
        for index, column in enumerate(_TOKEN_COLUMNS):
            tokens[index] += getattr(row, column)
        unpriced += row.unpriced_requests
        estimated += row.estimated_requests
        if row.price_source != NO_VALUE:
            sources.add(row.price_source)
        components.update(row.unpriced_components)
        if row.is_unattributed:
            unattributed_requests += row.request_count
            unattributed_display += Decimal(money(row.total_usd))
            unattributed_exact += row.total_usd
        if not first_seen or row.first_seen < first_seen:
            first_seen = row.first_seen
        if row.last_seen > last_seen:
            last_seen = row.last_seen
    return ChargebackTotals(
        group_by=names,
        groups=len(rows),
        request_count=sum(row.request_count for row in rows),
        input_tokens=tokens[0],
        output_tokens=tokens[1],
        cache_read_tokens=tokens[2],
        cache_write_tokens=tokens[3],
        total_usd=display.quantize(_REPORT_QUANTUM),
        unrounded_total_usd=exact.quantize(_EXACT_QUANTUM),
        currency=rows[0].currency if rows else CURRENCY,
        price_source=_one_source(sources),
        unpriced_requests=unpriced,
        estimated_requests=estimated,
        unattributed_requests=unattributed_requests,
        unattributed_usd=unattributed_display.quantize(_REPORT_QUANTUM),
        # The exact figure the share is computed from, kept beside the displayed
        # one for the same reason ``unrounded_total_usd`` is: a percentage that
        # cannot be reproduced from the numbers printed beside it invites the
        # reader to conclude the report is wrong.
        unattributed_unrounded_usd=unattributed_exact.quantize(_EXACT_QUANTUM),
        unattributed_share=_share(unattributed_exact, exact),
        unpriced_components=tuple(
            component for component in COST_COMPONENTS if component in components
        ),
        first_seen=first_seen,
        last_seen=last_seen,
    )


def _rows_group_by(rows: Sequence[ChargebackRow]) -> tuple[str, ...]:
    """The grouping a set of rows was built with.

    Rows carry their own grouping, so an empty result has none to carry; the
    default is used there and the CLI passes its own ``--group-by`` explicitly so
    the header of an empty export is still the header the user asked for.
    """
    if not rows:
        return DEFAULT_GROUP_BY
    first = rows[0]
    for row in rows[1:]:
        if row.group_by != first.group_by:
            raise ValueError(
                "every row must share one grouping to be totalled or exported "
                f"together; got {list(first.group_by)} and {list(row.group_by)}"
            )
    return first.group_by


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------


def columns(group_by: Sequence[str] = DEFAULT_GROUP_BY) -> tuple[str, ...]:
    """The CSV header: group keys in the caller's order, then the fixed columns."""
    return (*_check_group_by(group_by), *ROW_COLUMNS)


def _group_by_of(
    rows: Sequence[ChargebackRow], group_by: Sequence[str] | None
) -> tuple[str, ...]:
    return _check_group_by(group_by) if group_by is not None else _rows_group_by(rows)


def render_chargeback_csv(
    rows: Sequence[ChargebackRow], group_by: Sequence[str] | None = None
) -> str:
    """Return the charge-back as RFC 4180 CSV text.

    Header first, one line per row, CRLF between and after every record including
    the last, UTF-8 by the caller's choice of encoding. Quoting is minimal, so a
    group value containing a comma is quoted and nothing else is.

    **No totals row.** A totals line inside a table finance intends to pivot or
    ``SUM`` is a double count waiting to happen, and the totals belong in the
    report next to the table, not inside the data. :func:`chargeback_totals` is
    how a caller gets them.

    Money cells are the two-decimal strings from :func:`money`, so no cell in the
    file is a number a spreadsheet can re-round.
    """
    names = _group_by_of(rows, group_by)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator=CSV_TERMINATOR, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(columns(names))
    for row in rows:
        writer.writerow(row.cells())
    return buffer.getvalue()


def write_chargeback_csv(
    rows: Sequence[ChargebackRow],
    out: str | os.PathLike[str],
    group_by: Sequence[str] | None = None,
) -> int:
    """Write the charge-back CSV to ``out`` and return the number of data rows.

    UTF-8 with ``newline=""``, so the :data:`CSV_TERMINATOR` the writer emits is
    the terminator that reaches the file and the file is byte-identical on every
    platform. Parent directories are created, as the JSONL sink does, so an export
    into a fresh report directory is one command rather than two.
    """
    text = render_chargeback_csv(rows, group_by)
    path = os.fspath(out)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return len(rows)


# --------------------------------------------------------------------------
# Revenue join
# --------------------------------------------------------------------------

REVENUE_COLUMNS: tuple[str, ...] = (
    "request_count",
    "total_usd",
    "revenue_usd",
    "margin_usd",
    "match",
    "currency",
)


@dataclass(frozen=True)
class RevenueRow:
    """One group after joining our cost against somebody else's revenue.

    **The assumption, stated once:** revenue is keyed by the *same group tuple*
    the charge-back was built on — the same dimensions, in the same order, with
    the same placeholder for an unset key. A ``None`` or blank element in a
    caller's key is normalised to :data:`UNATTRIBUTED` *before* matching, so
    ``(None, None)`` and ``(UNATTRIBUTED, UNATTRIBUTED)`` both join the group that
    rendered as unattributed. A key present on one side and absent on the other
    is a real state, not a zero: a revenue-only group has no cost in this window
    and a cost-only group has no revenue in this file, and both are emitted with
    ``None`` money and a ``match`` column naming the case. ``margin_usd`` is
    ``None`` unless both sides are present, because a margin computed against an
    assumed zero is exactly the silent zero this module exists to avoid.

    Two revenue keys that normalise to the same group are refused rather than
    resolved: the map is ambiguous, and picking one of them would pick a revenue
    figure for a group on no evidence but the iteration order of a dict.

    Backstop does not become a revenue system: it does not fetch, infer or
    allocate revenue. It joins what a caller supplies and leaves the rest visible.
    """

    group_by: tuple[str, ...]
    keys: tuple[str, ...]
    request_count: int | None
    total_usd: Decimal | None
    revenue_usd: Decimal | None
    margin_usd: Decimal | None
    match: str
    currency: str

    @property
    def key_dict(self) -> dict[str, str]:
        return dict(zip(self.group_by, self.keys, strict=True))

    def to_dict(self) -> dict[str, Any]:
        """The JSON form, with an absent amount as ``None`` and never as ``0``."""
        payload: dict[str, Any] = {"group_by": list(self.group_by), **self.key_dict}
        payload.update(
            {
                "request_count": self.request_count,
                "total_usd": None if self.total_usd is None else money(self.total_usd),
                "revenue_usd": None if self.revenue_usd is None else money(self.revenue_usd),
                "margin_usd": None if self.margin_usd is None else money(self.margin_usd),
                "match": self.match,
                "currency": self.currency,
            }
        )
        return payload

    def cells(self) -> tuple[str, ...]:
        """The row as strings, in :data:`REVENUE_COLUMNS` order after the keys."""
        return (
            *self.keys,
            NO_VALUE if self.request_count is None else str(self.request_count),
            NO_VALUE if self.total_usd is None else money(self.total_usd),
            NO_VALUE if self.revenue_usd is None else money(self.revenue_usd),
            NO_VALUE if self.margin_usd is None else money(self.margin_usd),
            self.match,
            self.currency,
        )


def _revenue_amount(value: Any, key: tuple[str, ...]) -> Decimal:
    """Read one revenue figure, refusing anything that is not exact."""
    if isinstance(value, bool):
        raise TypeError(f"revenue for {key} must be a number, got a bool")
    if isinstance(value, float):
        raise TypeError(
            f"revenue for {key} is a float {value!r}; pass a decimal string or a "
            "Decimal, because a float has already lost the cents"
        )
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value)
        except ArithmeticError as exc:
            raise ValueError(
                f"revenue for {key} is not a decimal number: {value!r}"
            ) from exc
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"revenue for {key} must be finite, got {value!r}")
        return value
    raise TypeError(
        f"revenue for {key} must be a Decimal, an int or a decimal string, got "
        f"{type(value).__name__}"
    )


@_exact_money
def revenue_join(
    rows: Sequence[ChargebackRow],
    revenue: Mapping[tuple[str, ...], Any],
) -> tuple[RevenueRow, ...]:
    """Join a charge-back to a caller's revenue, keyed on the same group tuple.

    See :class:`RevenueRow` for the keying assumption, which is the only thing a
    reader has to know to use this correctly: **the same dimensions, in the same
    order, with the same placeholder.** A revenue key naming a dimension the rows
    were not grouped on is refused, because a join on a key the other side cannot
    produce is a join that silently matches nothing.

    The output holds every key from either side. Ordering is ``total_usd``
    descending with the rendered key as the tie-break — the same rule
    :func:`build_chargeback` uses, so a joined table reads in the same order as
    the table it came from and revenue-only groups land at the end, in key order.
    """
    names = _rows_group_by(rows)
    # Every key is normalised to the placeholder *before* anything is matched, so a
    # caller who keys on ``(None, None)`` joins the row that rendered as
    # ``(unattributed, (unattributed))`` rather than missing it. Two raw keys that
    # normalise to the same group are an ambiguous map, not a last-one-wins.
    wanted: dict[tuple[str, ...], Any] = {}
    raw_keys: dict[tuple[str, ...], Any] = {}
    for key, amount in revenue.items():
        canonical = _normalise_revenue_key(key, len(names), names)
        if canonical in wanted:
            raise ValueError(
                f"revenue keys {raw_keys[canonical]!r} and {tuple(key)!r} both name the "
                f"group {canonical!r} once unset keys are rendered; a join cannot "
                "choose between them"
            )
        wanted[canonical] = amount
        raw_keys[canonical] = tuple(key)
    joined: list[RevenueRow] = []
    for row in rows:
        key = row.keys
        has_revenue = key in wanted
        gain = _revenue_amount(wanted[key], key) if has_revenue else None
        joined.append(
            RevenueRow(
                group_by=names,
                keys=key,
                request_count=row.request_count,
                total_usd=row.total_usd,
                revenue_usd=gain,
                margin_usd=None if gain is None else gain - row.total_usd,
                match=MATCH_BOTH if has_revenue else MATCH_COST_ONLY,
                currency=row.currency,
            )
        )
    for key, amount in wanted.items():
        if any(row.keys == key for row in rows):
            continue
        joined.append(
            RevenueRow(
                group_by=names,
                keys=key,
                request_count=None,
                total_usd=None,
                revenue_usd=_revenue_amount(amount, key),
                margin_usd=None,
                match=MATCH_REVENUE_ONLY,
                currency=rows[0].currency if rows else CURRENCY,
            )
        )
    joined.sort(key=lambda row: (-(row.total_usd or _ZERO_EXACT), row.keys))
    return tuple(joined)


def _normalise_revenue_key(
    key: Any, width: int, names: tuple[str, ...]
) -> tuple[str, ...]:
    if isinstance(key, str):
        raise TypeError(
            f"a revenue key must be a tuple of the grouped dimensions {list(names)}, "
            f"not a single string {key!r}"
        )
    if not isinstance(key, (tuple, list)):
        raise TypeError(
            f"a revenue key must be a tuple of the grouped dimensions {list(names)}, "
            f"got {type(key).__name__} {key!r}"
        )
    if len(key) != width:
        raise ValueError(
            f"revenue key {tuple(key)!r} has {len(key)} elements but the rows are "
            f"grouped on {list(names)}; the join assumes the same group tuple"
        )
    return tuple(UNATTRIBUTED if item is None or not str(item).strip() else str(item) for item in key)


def render_revenue_csv(
    joined: Sequence[RevenueRow], group_by: Sequence[str] | None = None
) -> str:
    """Return the joined table as RFC 4180 CSV text, same discipline as the cost CSV.

    A group missing on one side carries :data:`NO_VALUE` in the money cells and a
    ``match`` column naming the case, so the file is a table a spreadsheet can
    read without a cell silently becoming zero.
    """
    names = group_by if group_by is not None else (joined[0].group_by if joined else DEFAULT_GROUP_BY)
    names = _check_group_by(names)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator=CSV_TERMINATOR, quoting=csv.QUOTE_MINIMAL)
    writer.writerow((*names, *REVENUE_COLUMNS))
    for row in joined:
        writer.writerow(row.cells())
    return buffer.getvalue()


def write_revenue_csv(
    joined: Sequence[RevenueRow],
    out: str | os.PathLike[str],
    group_by: Sequence[str] | None = None,
) -> int:
    """Write the joined table to ``out`` and return the number of data rows."""
    text = render_revenue_csv(joined, group_by)
    path = os.fspath(out)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return len(joined)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _markdown_cell(text: str) -> str:
    """One cell, safe inside a markdown table.

    A pipe would end the cell early and a newline would end the row, and a group
    value is an arbitrary string the caller put in an attribution, so both are
    neutralised. The escaped text is only for display; the CSV keeps the value.
    """
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def display_columns(group_by: Sequence[str] = DEFAULT_GROUP_BY) -> tuple[str, ...]:
    """The group keys plus :data:`DISPLAY_COLUMNS`: what a screen can show."""
    return (*_check_group_by(group_by), *DISPLAY_COLUMNS)


def render_chargeback_markdown(
    rows: Sequence[ChargebackRow],
    totals: ChargebackTotals | None = None,
    group_by: Sequence[str] | None = None,
    columns: Sequence[str] | None = None,
) -> str:
    """Render rows as a markdown table, with an optional totals row under it.

    The table is built from :meth:`ChargebackRow.cells`, the same cells the CSV
    writer writes, so the printed table and the exported file are the same
    numbers by construction rather than by two renderers agreeing. ``columns``
    narrows what is shown — ``None`` for all of them, :func:`display_columns` for
    a screen — and never changes a value.

    The totals row labels itself ``Total`` in the first cell and leaves the rest
    of the key columns empty. That is the one empty cell this module emits on
    purpose: a totals line is not a group, so it has no key value, and it is
    labelled rather than shaped like an attributed group that could be charged.
    """
    names = _group_by_of(rows, group_by)
    wanted = tuple(columns) if columns is not None else display_columns(names)
    _check_display(names, wanted)
    lines = [
        _markdown_row(wanted),
        _markdown_row(tuple("---:" if name in _RIGHT_ALIGNED else "---" for name in wanted)),
    ]
    for row in rows:
        lines.append(_markdown_row(row.select(wanted)))
    if totals is not None:
        lines.append(_markdown_row(_totals_cells(totals, wanted)))
    return "\n".join(lines)


def _check_display(names: tuple[str, ...], wanted: Sequence[str]) -> None:
    """Every displayed column must be one this table can produce."""
    available = set(columns(names))
    unknown = [name for name in wanted if name not in available]
    if unknown:
        raise KeyError(
            f"cannot display column(s) {unknown}; a charge-back row has "
            f"{list(available)}"
        )


def _markdown_row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(_markdown_cell(cell) for cell in cells) + " |"


def _totals_cells(
    totals: ChargebackTotals, wanted: Sequence[str] = ROW_COLUMNS
) -> tuple[str, ...]:
    """The totals line, for the columns ``wanted`` names.

    A totals line is not a group, so it has no key values: the first key cell
    says ``Total`` and the rest say ``all``, which together read as "every team"
    rather than as a team called "all". Every other cell carries its value, or
    :data:`NO_VALUE` where a total has none to give, so no cell in the summary row
    is blank either.
    """
    available = {
        "request_count": str(totals.request_count),
        "input_tokens": str(totals.input_tokens),
        "output_tokens": str(totals.output_tokens),
        "cache_read_tokens": str(totals.cache_read_tokens),
        "cache_write_tokens": str(totals.cache_write_tokens),
        "total_usd": f"**{money(totals.total_usd)}**",
        "currency": totals.currency,
        "price_source": totals.price_source,
        "unpriced_requests": str(totals.unpriced_requests),
        "estimated_requests": str(totals.estimated_requests),
        "unpriced_components": "|".join(totals.unpriced_components) or NO_VALUE,
        "first_seen": totals.first_seen,
        "last_seen": totals.last_seen,
    }
    cells: list[str] = []
    labelled = False
    for name in wanted:
        if name in totals.group_by:
            cells.append("**Total**" if not labelled else "all")
            labelled = True
        else:
            cells.append(available[name])
    return tuple(cells)


def render_chargeback_json(
    rows: Sequence[ChargebackRow], totals: ChargebackTotals | None = None
) -> str:
    """Render rows and totals as JSON, money as strings throughout."""
    payload: dict[str, Any] = {
        "group_by": list(_rows_group_by(rows)),
        "rows": [row.to_dict() for row in rows],
    }
    if totals is not None:
        payload["totals"] = totals.to_dict()
    return json.dumps(payload, indent=2, sort_keys=True)


# --------------------------------------------------------------------------
# Reading a JSONL ledger
# --------------------------------------------------------------------------


class LedgerCorruptionError(ValueError):
    """A non-final line of a JSONL ledger that will not parse.

    The line number is in the message and on the exception, because "your ledger
    is corrupt" is not actionable and "line 4,187 will not parse" is. Nothing is
    skipped: the command that reads a ledger either returns the events before
    this line or raises, and a finance figure that quietly lost rows is worse
    than a command that failed.
    """

    def __init__(self, path: str, line_number: int, reason: str, excerpt: str) -> None:
        super().__init__(
            f"{path}: line {line_number} is corrupt and is not the last line of the "
            f"file: {reason}. Refusing to read past it — a charge-back that silently "
            f"skips rows is worse than a failed command. Excerpt: {excerpt}"
        )
        self.path = path
        self.line_number = line_number
        self.reason = reason
        self.excerpt = excerpt


@dataclass(frozen=True)
class TornWrite:
    """The final line of a JSONL ledger that a crash interrupted.

    A :class:`~backstop.ledger.sink.JsonlSink` writes each line whole and stops
    appending once it fails, so a partial line is always the last one and there
    is at most one. ``included`` says whether the event behind it was still
    readable: a torn line that happens to parse is counted, because dropping a
    complete event would lose a dollar, and one that does not parse is not, so
    the loss is a named, countable one.
    """

    line_number: int
    reason: str
    bytes: int
    included: bool


@dataclass(frozen=True)
class LedgerRead:
    """What one read of a JSONL ledger found.

    ``lines_seen`` counts every physical line examined, ``events`` the records
    that came out of them, and ``torn_write`` names the one line that was
    incomplete. A file whose last line is not newline-terminated is reported as a
    torn write *whether or not it parses*: a complete record always has its
    newline, so its absence means the process died inside the last write.
    """

    path: str
    events: tuple[SpendEvent, ...]
    lines_seen: int
    torn_write: TornWrite | None
    bytes_read: int

    @property
    def is_complete(self) -> bool:
        """Whether every line in the file yielded an event."""
        return self.torn_write is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "events": len(self.events),
            "lines_seen": self.lines_seen,
            "bytes_read": self.bytes_read,
            "torn_write": None
            if self.torn_write is None
            else {
                "line_number": self.torn_write.line_number,
                "reason": self.torn_write.reason,
                "bytes": self.torn_write.bytes,
                "included": self.torn_write.included,
            },
        }


_EXCERPT_BYTES = 120


def read_ledger(path: str | os.PathLike[str]) -> LedgerRead:
    """Read a JSONL ledger, applying the sink's documented torn-write policy.

    The policy, which :class:`~backstop.ledger.sink.JsonlSink` states and this
    function implements:

    * a final line that will not parse is a **torn write** — a crash between the
      kernel taking part of the line and the file being closed. It is reported,
      not repaired, and the events before it are read;
    * a final line that is not newline-terminated is a torn write too, and is
      *included* if it parses, because a complete record always ends in a newline
      and losing a readable event is the worse failure;
    * an unparseable line anywhere **other** than the end is **corruption**: it
      names its line number and raises :class:`LedgerCorruptionError`, and
      nothing is skipped.

    Read as bytes, so a line truncated in the middle of a multi-byte character is
    still a line rather than an undecodable file. Blank lines are corruption
    anywhere: the sink writes one record per line and never a blank one, so a
    blank line means something else wrote to the file. An empty file is an empty
    ledger, not a corrupt one.
    """
    location = os.fspath(path)
    with open(location, "rb") as handle:
        blob = handle.read()
    events: list[SpendEvent] = []
    torn: TornWrite | None = None
    seen = 0
    lines = blob.split(b"\n")
    # A file ending in "\n" splits with a trailing empty element that is the
    # terminator, not a line. Anything else in that position is a real final line
    # that never got its newline.
    terminated = bool(lines) and lines[-1] == b""
    if terminated:
        lines.pop()
    last_index = len(lines) - 1
    for index, raw in enumerate(lines):
        seen += 1
        is_last = index == last_index
        if not raw.strip():
            # A blank line where a record belongs: the sink writes one record per
            # line and never a blank one, so something else wrote this file. A
            # blank *final* line is the degenerate torn write — a write that
            # produced no bytes at all — and is reported rather than raised,
            # because the rest of the file is still sound.
            if is_last and not terminated:
                torn = TornWrite(
                    line_number=index + 1,
                    reason="the last line is blank and unterminated",
                    bytes=len(raw),
                    included=False,
                )
                continue
            raise LedgerCorruptionError(
                location, index + 1, "the line is blank", _excerpt(raw)
            )
        try:
            event = _parse_line(raw)
        except (UnicodeDecodeError, ValueError) as exc:
            if is_last:
                torn = TornWrite(
                    line_number=index + 1, reason=str(exc), bytes=len(raw), included=False
                )
                continue
            raise LedgerCorruptionError(location, index + 1, str(exc), _excerpt(raw)) from exc
        events.append(event)
        if is_last and not terminated:
            torn = TornWrite(
                line_number=index + 1,
                reason="the last line is not newline-terminated, so the process "
                "died inside the write",
                bytes=len(raw),
                included=True,
            )
    return LedgerRead(
        path=location,
        events=tuple(events),
        lines_seen=seen,
        torn_write=torn,
        bytes_read=len(blob),
    )


def _parse_line(raw: bytes) -> SpendEvent:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"the line is not valid UTF-8: {exc}") from exc
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"the line is not valid JSON: {exc}") from exc
    return SpendEvent.from_dict(payload)


def _excerpt(raw: bytes) -> str:
    """A short, printable slice of a bad line, for the error message."""
    text = raw[:_EXCERPT_BYTES].decode("utf-8", "replace")
    return repr(text) + ("..." if len(raw) > _EXCERPT_BYTES else "")


# --------------------------------------------------------------------------
# Delivery accounting
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DeliveryReport:
    """How much spend the ledger lost on its way to the sink.

    Three counters, not one, because they are three different losses:

    ``dropped_events``
        Events the :class:`~backstop.ledger.sink.BoundedWriter` refused because
        its bounded buffer was full. Nothing was wrong with the sink.
    ``writer_sink_errors``
        What escaped a sink as an exception.
    ``sink_sink_errors``
        A sink that swallows its own failures —
        :class:`~backstop.ledger.sink.JsonlSink` must, since it is called from
        the drain thread and must never raise into a caller — counting them
        itself. A deployment that reports only ``writer.sink_errors`` reports
        zero for every write failure there was.

    ``lost`` is the sum of the three through
    :func:`~backstop.ledger.sink.lost_events`, the same function
    :attr:`~backstop.ledger.sink.CloseReport.lost` uses, so the live path and the
    shutdown path cannot report different numbers for the same writer. ``written``
    is the count of writes that *returned*; ``landed`` is how many of them
    produced a record.
    """

    submitted: int
    written: int
    dropped_events: int
    writer_sink_errors: int
    sink_sink_errors: int
    sink_degraded: bool

    @property
    def lost(self) -> int:
        """Events that will never be written."""
        return lost_events(self.dropped_events, self.writer_sink_errors, self.sink_sink_errors)

    @property
    def landed(self) -> int:
        """Events that reached storage: the writes the sink did not lose."""
        return landed_events(self.written, self.sink_sink_errors)


def delivery_report(writer: Any) -> DeliveryReport:
    """Read both loss counters from a live writer, and the sink's own with them.

    Takes a :class:`~backstop.ledger.sink.BoundedWriter` — a
    :class:`~backstop.ledger.sink.CloseReport`, or anything exposing the same
    counters, so a caller can pass a state, a test double, or the writer itself.
    A sink with no counter of its own reports zero rather than ``None``: a sink
    that cannot fail does not have to say so twice.

    A ``CloseReport`` already carries the sink's own count and its degraded flag,
    read once at close, and both are preferred over a live re-read when it is
    present: a report taken after ``close()`` is a settled number rather than a
    snapshot of a thread that may still be working, and re-reading the sink
    afterwards could catch counters that have moved.
    """
    for name in ("submitted", "written", "dropped_events", "sink_errors"):
        if not hasattr(writer, name):
            raise TypeError(
                f"delivery_report needs a BoundedWriter or something with {name!r}, "
                f"got {type(writer).__name__}"
            )
    sink = getattr(writer, "sink", None)
    reported = getattr(writer, "sink_reported_errors", None)
    degraded = getattr(writer, "sink_degraded", None)
    if reported is None:
        reported = getattr(sink, "sink_errors", 0) or 0
    if degraded is None:
        degraded = bool(getattr(sink, "degraded", False))
    return DeliveryReport(
        submitted=int(writer.submitted),
        written=int(writer.written),
        dropped_events=int(writer.dropped_events),
        writer_sink_errors=int(writer.sink_errors),
        sink_sink_errors=int(reported or 0),
        sink_degraded=bool(degraded),
    )


#: Why a file cannot answer the delivery question, in one sentence.
FILE_DELIVERY_NOTE = (
    "a JSONL line records an event, never a counter: dropped_events and "
    "sink_errors are process-local and are not written to the file, so a file "
    "read cannot report them. Read DeliveryReport from the live writer to get "
    "them."
)


def format_delivery(report: DeliveryReport) -> list[str]:
    """Markdown lines for a live writer's delivery report."""
    return [
        "## Delivery (this process)",
        "",
        f"- submitted: {report.submitted}",
        f"- written: {report.written}",
        f"- landed (written less the sink's own losses): {report.landed}",
        f"- dropped_events (writer buffer full): {report.dropped_events}",
        f"- writer sink_errors (escaped the sink): {report.writer_sink_errors}",
        f"- sink sink_errors (counted by the sink): {report.sink_sink_errors}",
        f"- sink degraded: {'yes' if report.sink_degraded else 'no'}",
        f"- **lost (dropped + writer errors + sink errors): {report.lost}**",
    ]


def format_file_delivery(read: LedgerRead) -> list[str]:
    """Markdown lines for a file read, naming what a file cannot tell you.

    The file proves exactly one loss — a torn final line — and says so. The two
    process-local counters are reported as unavailable with the reason, rather
    than as zero, because "zero" is a claim and "not recorded here" is a fact.
    """
    torn = read.torn_write
    if torn is None:
        torn_line = "- torn final line: none (every line parsed and was terminated)"
    elif torn.included:
        torn_line = (
            f"- torn final line: line {torn.line_number}, {torn.reason}; the record "
            "was readable and IS counted"
        )
    else:
        torn_line = (
            f"- torn final line: line {torn.line_number}, {torn.reason}; this event "
            "is LOST and is not counted"
        )
    return [
        "## Delivery (read from the file)",
        "",
        torn_line,
        f"- events read: {len(read.events)} of {read.lines_seen} lines",
        f"- dropped_events: unknown — {FILE_DELIVERY_NOTE}",
        f"- sink_errors: unknown — {FILE_DELIVERY_NOTE}",
        "- complete loss figure: not derivable from the file; ask the running "
        "process for its DeliveryReport.",
    ]
