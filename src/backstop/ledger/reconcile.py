"""Reconciling a priced ledger against a provider's statement.

**What this reconciles against.** A **statement file** — a CSV or a JSON document
that a provider's console, admin API or billing system produced. It does **not**
call a provider API, it has no credentials, and it has never seen a real statement.
Every provider field name it reads is centralised in
:data:`OPENAI_STATEMENT_FIELDS` and :data:`ANTHROPIC_STATEMENT_FIELDS` and marked
as needing verification against a real statement; the docstrings on
:func:`parse_invoice_csv` and :func:`parse_invoice_json` say which document shape
each one assumes. A reconciliation against a live invoice is a different program,
and this one does not pretend to be it.

The gap this closes is named in ``docs/planning/03-attribution-and-schema.md``
Part 5: ``build_chargeback`` produced a number nobody could check against the
provider's own paper, and M1 — ``abs(ledger - invoice) / invoice`` — was
*hypothesis* because nothing computed it. This module computes it, and it is
built so that the number it produces is worth auditing.

Five rules hold it together.

**Money is never a binary float.** Every amount is a
:class:`~decimal.Decimal`, quantised to :data:`backstop.pricing_catalog.MONEY_PLACES`
decimal places with ``ROUND_HALF_UP`` exactly as the catalog prices, and every
renderer in the ledger runs under :data:`~backstop.pricing_catalog.LEDGER_CONTEXT`
rather than the host's. A statement figure written as a JSON *number* has already
lost the distinction a decimal string keeps, so it is read back through its
shortest repr and refused if that repr is not a decimal — the same rule
``PriceCatalog.from_file`` follows.

**An unknown model is never guessed.** A model the catalog does not carry is a
row whose *ledger* side is **absent, not zero**, with a reason saying the model is
unpriced. There is no default rate, no neighbouring-model fallback, and no
dropping: the same rule ``compute_cost`` follows, for the same reason. The
``missing_from_ledger`` status is the *visible form* of "a missing price", which
``docs/planning/03-attribution-and-schema.md`` Part 4.3 calls the design thesis.

**Nothing is netted away silently.** A model present on one side only is reported
on its own row and is never offset against the other side, so a missing dollar
cannot hide inside a matched one. The per-model rows are the report; the total is
derived from them and carries how many rows had an absent side.

**The provider is on every line, and the statement's own categories are read
rather than assumed.** OpenAI's ``input_tokens`` counts the cached tokens *inside*
it and Anthropic's does not, so a statement row is stored as the provider's own
``token_categories`` mapping and normalised afterwards. Two names that resolve to
the same rate card are still two rows, because merging them is a guess.

**The result is self-auditing.** Every report carries how many events went in, how
many statement lines came in, and how many models reconciled cleanly, so a reader
can tell an empty reconciliation from a clean one. :func:`measure_error_budget`
reports the same three counts with the observed variance, and says in its own
output that it is a figure over the inputs it was given.
"""
from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from functools import wraps
from types import MappingProxyType
from typing import Any, Callable, TypeVar

from ..pricing_catalog import (
    BUNDLED_EFFECTIVE_FROM,
    CURRENCY,
    LEDGER_CONTEXT,
    MONEY_PLACES,
    PriceCatalog,
    compute_cost,
)
from .export import CSV_TERMINATOR, NO_VALUE, money
from .schema import Attribution, SpendEvent

__all__ = [
    "DEMO_PERIOD",
    "DEMO_STATEMENT_ROWS",
    "DEFAULT_TOLERANCE_PCT",
    "DEFAULT_TOLERANCE_USD",
    "INVOICE_COLUMNS",
    "RECONCILIATION_SCOPE",
    "STATUSES",
    "STATUS_MATCHED",
    "STATUS_MISSING_FROM_INVOICE",
    "STATUS_MISSING_FROM_LEDGER",
    "STATUS_VARIANCE",
    "STATUS_WITHIN_TOLERANCE",
    "ErrorBudget",
    "Invoice",
    "InvoiceLine",
    "InvoiceVariance",
    "ModelVariance",
    "demo_events",
    "demo_invoice",
    "measure_error_budget",
    "parse_invoice_csv",
    "parse_invoice_json",
    "reconcile_invoice",
    "reconciliation_csv",
    "run_demo",
]

# --------------------------------------------------------------------------
# Sentinels, statuses and defaults
# --------------------------------------------------------------------------

#: One sentence, printed by every renderer, because the scope of this module is the
#: single thing a reader is most likely to over-read. It reconciles a ledger against
#: a statement **file**; it does not call a provider and has never seen an invoice.
RECONCILIATION_SCOPE = (
    "This reconciles the ledger against a statement FILE supplied by the caller. It "
    "calls no provider API, holds no credentials, and has never been run against a "
    "real invoice in this repository."
)

#: The exact figure and the exact same answer. ``matched`` is the only state that
#: asserts the two sides are identical.
STATUS_MATCHED = "matched"
#: A real difference, inside the tolerance. Never "the same": the signed figure is
#: on the row either way, and a reader who wants zero tolerance can pass
#: ``tolerance_usd=0``.
STATUS_WITHIN_TOLERANCE = "within_tolerance"
#: A difference above the tolerance. Named, quantified, and attributed to a cause.
STATUS_VARIANCE = "variance"
#: The provider billed for something Backstop did not record: either the ledger has
#: no event for that model at all, or every event it has is unpriced.
STATUS_MISSING_FROM_LEDGER = "missing_from_ledger"
#: Backstop recorded spend the statement does not bill for.
STATUS_MISSING_FROM_INVOICE = "missing_from_invoice"

#: The five states, **in severity order**. A report's own status is the most severe
#: state any of its rows carries, and the order is declared rather than left to a
#: reader: a missing dollar is ranked above a mis-priced one, because a figure that
#: is absent is visible to whoever reconciles next and a figure that is quietly
#: wrong is not.
STATUSES: tuple[str, ...] = (
    STATUS_MATCHED,
    STATUS_WITHIN_TOLERANCE,
    STATUS_VARIANCE,
    STATUS_MISSING_FROM_LEDGER,
    STATUS_MISSING_FROM_INVOICE,
)

#: Decimal places a reported *percentage* is rendered with. Four, because "0.07" is
#: not a useful thing to tell a CFO about a gap they need to close. A percentage
#: rather than a ratio throughout, so :data:`DEFAULT_TOLERANCE_PCT` and
#: ``variance_pct`` are read on the same scale and never differ by a factor of 100.
SHARE_PLACES = 4

_SHARE_QUANTUM = Decimal(1).scaleb(-SHARE_PLACES)
#: Built from the catalog's own :data:`~backstop.pricing_catalog.MONEY_PLACES` rather
#: than written out as a literal, so the quantum every figure here is stated at
#: cannot drift from the quantum the catalog priced at. ``tests/test_reconcile.py``
#: asserts the two agree, which is the same guard ``export.py`` keeps on its own
#: re-declaration of the same constant.
_QUANTUM = Decimal(1).scaleb(-MONEY_PLACES)
#: A zero **at the money quantum**, which is what an accumulator has to start from:
#: ``Decimal(1).scaleb(-6)`` is one microdollar, not zero, and an accumulator seeded
#: with it adds a microdollar to every total. ``Decimal(0).scaleb(-6)`` is ``0E-6``.
_ZERO = Decimal(0).scaleb(-MONEY_PLACES)
_MTOK = Decimal(1_000_000)

#: The default dollar tolerance, per model row.
#:
#: **Reasoning, in full, because a tolerance is a number somebody will quote.**
#:
#: 1. It is the provider's own stated precision. Anthropic's cost report is
#:    denominated in cents and OpenAI's dashboard export renders cents, so a cent is
#:    the smallest difference a statement can express. A tolerance finer than the
#:    statement's own resolution classifies its rounding as a variance.
#: 2. It absorbs the ledger's own six-decimal quantisation without swallowing a
#:    single real difference. Per request that is at most $0.0000005, so a cent
#:    covers the worst case for 20,000 requests and there is no account whose
#:    rounding reaches it.
#: 3. It cannot hide a rate error. On a $100 row a 1% rate change is $1.00, a
#:    hundred times the tolerance. This is the direction that matters, because a
#:    stale rate card is gap #1 in the planning document's own list.
#: 4. It **is** loose in token terms on a large row, deliberately: a cent is 4,000
#:    input tokens at gpt-4o's $2.50/M, so on a high-volume model a few thousand
#:    tokens of disagreement sits inside the tolerance. A tolerance is a claim about
#:    *dollars*, and a rate card is a dollar claim. A deployment that wants a
#:    tighter answer on a specific model passes a smaller ``tolerance_usd``, and
#:    every row prints its exact signed variance regardless of the tolerance.
DEFAULT_TOLERANCE_USD = Decimal("0.01")

#: The default percentage tolerance, applied as ``invoice_usd * pct / 100`` and
#: compared against ``|variance_usd|`` alongside the dollar floor; the **looser** of
#: the two wins. 0.5% is the figure ``docs/planning/03-attribution-and-schema.md``
#: section 5.3 already names as the hypothesised M1 for a deployment with every
#: request wrapped, every model priced, no streaming and a fresh rate card, so it is
#: this repository's own documented number rather than a new one. The looser-of-two
#: rule matters in both directions: the cent floor keeps a $0.03 model row from
#: flagging a sub-cent statement rounding, and the percentage ceiling keeps a
#: $10,000 row from calling a $40 rate error acceptable.
DEFAULT_TOLERANCE_PCT = Decimal("0.5")

# --------------------------------------------------------------------------
# Provider statement field names
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# The names below are transcribed from each provider's *published* usage and cost
# reporting surface, not from a file in this repository — this module has never been
# handed a real statement. They are centralised here, in one clearly-marked block,
# for exactly that reason: a reader who owns a statement can correct one constant
# and every parse follows, and a provider that renames a column fails loudly at the
# parser rather than quietly reconciling nothing.
#
# **Verify them against a real statement before relying on them.** Each entry is a
# tuple of accepted spellings, most-canonical first, and the parser takes the first
# one the document carries. OpenAI's names come from the documented
# `GET /v1/organization/usage/completions` result fields (`input_tokens`,
# `input_uncached_tokens`, `input_cached_tokens`, `input_cache_write_tokens`,
# `output_tokens`, `model`) and the Usage dashboard's CSV export, whose headers
# mirror them. Anthropic's come from the documented Cost Report result fields
# (`model`, `amount`, `token_type`) and the Messages Usage Report
# (`uncached_input_tokens`, `cache_read_input_tokens`, `cache_creation.*`).
#
# One deliberate omission: **Anthropic's cost report `amount` is denominated in
# lowest currency units — cents — and a bare `amount` column is therefore not
# accepted in a CSV.** Reading a cents figure as dollars is a 100x error that a
# reconciliation would report as a real variance and a reader would believe. Only
# columns whose name says USD are read, and a statement that offers nothing else is
# refused with a message naming the trap rather than parsed at a hundred times its
# value.
# --------------------------------------------------------------------------

#: Category names that mean the fresh, non-cached input on **either** provider's
#: statement. The name that means the same thing on only one of them is
#: :data:`INCLUSIVE_INPUT_CATEGORY`, and the reason it is separate is below.
EXCLUSIVE_INPUT_CATEGORIES: tuple[str, ...] = (
    "input_uncached_tokens",
    "uncached_input_tokens",
    "fresh_input_tokens",
)

#: Backstop's four billable components, and the statement category names that mean
#: each one. Mirrors :data:`backstop.pricing_catalog.COST_COMPONENTS`.
#: ``input_tokens`` is deliberately *not* in the ``input`` tuple: it is resolved by
#: :func:`_normalise_counts` against the provider, because its meaning depends on
#: which vendor published it.
COMPONENT_CATEGORIES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "input": EXCLUSIVE_INPUT_CATEGORIES,
        "output": ("output_tokens",),
        "cache_read": (
            "input_cached_tokens",
            "cache_read_input_tokens",
            "cache_read_tokens",
            "cached_tokens",
        ),
        "cache_write": (
            "input_cache_write_tokens",
            "cache_creation_input_tokens",
            "cache_creation_5m_input_tokens",
            "cache_creation_1h_input_tokens",
            "cache_write_tokens",
        ),
    }
)

#: The statement name that carries a provider's input count, and the two meanings it
#: has. OpenAI publishes ``input_tokens`` covering the whole prompt, **cached
#: included**; Anthropic publishes ``input_tokens`` as the *fresh* count with the
#: cached figures in addition to it. Same name, opposite convention, and reading one
#: as the other is the size of the cache rather than a rounding difference — see
#: ``docs/planning/03-attribution-and-schema.md`` Part 4.5. The rule therefore keys on
#: the **provider**, which is recorded on every line, and never on the name alone.
INCLUSIVE_INPUT_CATEGORY = "input_tokens"

#: The only providers whose ``input_tokens`` counts the cached tokens inside it.
INCLUSIVE_INPUT_PROVIDERS: frozenset[str] = frozenset({"openai"})

#: Every column a document may use for the fresh input count. **Both** providers'
#: statements are read through this set, because both spellings appear in both
#: providers' outputs and which one is in force is a question about the provider.
INPUT_FIELDS: tuple[str, ...] = (INCLUSIVE_INPUT_CATEGORY, *EXCLUSIVE_INPUT_CATEGORIES)

_KNOWN_CATEGORIES = frozenset(
    (INCLUSIVE_INPUT_CATEGORY,)
    + tuple(name for names in COMPONENT_CATEGORIES.values() for name in names)
)


def _fields(
    model: tuple[str, ...],
    period: tuple[str, ...],
    charged_usd: tuple[str, ...],
) -> Mapping[str, tuple[str, ...]]:
    """Build one provider's field map: the shared five plus that provider's
    categories, so the two maps differ only where the providers do — which for the
    accepted *names* is nowhere, and is resolved on the provider at normalisation
    time instead (see :func:`_normalise_counts`)."""
    return MappingProxyType(
        {
            "model": model,
            "period": period,
            "charged_usd": charged_usd,
            **COMPONENT_CATEGORIES,
            "input": INPUT_FIELDS,
        }
    )


#: OpenAI statement fields. See the block comment above for the provenance and the
#: verification caveat.
OPENAI_STATEMENT_FIELDS: Mapping[str, tuple[str, ...]] = _fields(
    model=("model",),
    period=("date", "start_time", "bucket_start", "day"),
    charged_usd=("cost_usd", "total_cost_usd", "charged_usd", "amount_usd", "cost"),
)

#: Anthropic statement fields. See the block comment above for the provenance and
#: the verification caveat, and for why no bare ``amount`` column is accepted.
ANTHROPIC_STATEMENT_FIELDS: Mapping[str, tuple[str, ...]] = _fields(
    model=("model",),
    period=("date", "starting_at", "bucket_start"),
    charged_usd=("amount_usd", "cost_usd", "charged_usd", "total_cost_usd"),
)

#: The two providers this module reads, and their field maps. The provider is
#: recorded on every :class:`InvoiceLine` so a mismatch is reported rather than
#: resolved: a row whose provider disagrees with the ledger's events for the same
#: model is two rows, not one merged one.
PROVIDER_STATEMENT_FIELDS: Mapping[str, Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {"openai": OPENAI_STATEMENT_FIELDS, "anthropic": ANTHROPIC_STATEMENT_FIELDS}
)

#: The five things a statement row must carry for a comparison to be possible at
#: all. A row missing any of them is refused by name rather than parsed into zeros:
#: a reconciliation that quietly reconciles nothing is worse than one that refuses,
#: because a zero reconciles against a zero and looks clean.
REQUIRED_STATEMENT_FIELDS: tuple[str, ...] = (
    "model",
    "period",
    "input",
    "output",
    "charged_usd",
)

#: Rendered where a side of a row has no figure, beside the amount it would have
#: held. Distinct from :data:`~backstop.ledger.export.UNATTRIBUTED` because "nobody
#: said who spent this" and "there is no number here" are different facts; the same
#: distinction :data:`~backstop.ledger.export.NO_VALUE` already draws.
ABSENT = NO_VALUE

# --------------------------------------------------------------------------
# Decimal context
# --------------------------------------------------------------------------

_F = TypeVar("_F", bound=Callable[..., Any])


def _exact(fn: _F) -> _F:
    """Run one money function under :data:`~backstop.pricing_catalog.LEDGER_CONTEXT`.

    Every ``Decimal`` operator and every ``quantize`` reads the **thread's**
    context, and a decimal context is process-global. A host application that
    tightened ``prec`` would otherwise round this module's variance to a handful of
    significant digits — silently, because a rounded variance is still a variance.
    The catalog prices under this context and ``export._exact_money`` totals under
    it; a reconciliation that added up to a different figure from the one those two
    produced is the one thing this module cannot be.
    """

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with localcontext(LEDGER_CONTEXT):
            return fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def _quantise(amount: Decimal) -> Decimal:
    return amount.quantize(_QUANTUM, rounding=ROUND_HALF_UP)


def _wire_amount(value: Any) -> Any:
    """A JSON *number* has already been through a binary float: read it back through
    its shortest repr — the text the author wrote — and no other.

    Exactly the conversion :meth:`PriceCatalog.from_file` performs, and for the
    same reason: the digits are gone, but the digits the author *meant* are usually
    recoverable from the shortest repr, so a hand-written ``4.01`` can be read as
    exactly 4.01. Applied at the parser boundary, so the model below never sees a
    float and a caller who hands one in from anywhere else still gets a refusal.
    """
    return repr(value) if isinstance(value, float) else value


def _read_amount(value: Any, where: str) -> Decimal:
    """Read one money figure as a finite, non-negative ``Decimal``.

    A Python float is **refused** rather than coerced: by the time an amount is a
    float the cents it lost are gone, and presenting what is left confidently is
    worse than erroring. A JSON number is not refused, because it never arrives as
    one — :func:`_wire_amount` has already read it back through its shortest repr
    at the parser boundary.
    """
    if isinstance(value, bool):
        raise TypeError(f"{where} must be a decimal string or a number, not a bool")
    if isinstance(value, float):
        raise TypeError(
            f"{where} must be a Decimal or a decimal string, not a binary float "
            f"{value!r}; money is never a float"
        )
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        raise TypeError(
            f"{where} must be a decimal string or a number, got "
            f"{type(value).__name__} {value!r}"
        )
    text = value.strip().replace(",", "")
    if not text:
        raise ValueError(f"{where} is blank; a statement row with no amount is not a charge")
    try:
        amount = Decimal(text)
    except ArithmeticError as exc:
        raise ValueError(f"{where} is not a decimal number: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"{where} must be a finite amount, got {value!r}")
    if amount < 0:
        raise ValueError(f"{where} must be >= 0, got {value!r}")
    return amount


def _read_count(value: Any, where: str) -> int:
    """Read one token count as a non-negative ``int``; ``1_000``, ``"1,000"`` and
    ``1000`` all mean the same thing, because a statement formats them differently
    from each other and a token count is never a fraction."""
    if isinstance(value, bool):
        raise TypeError(f"{where} must be an integer token count, not a bool")
    if isinstance(value, int):
        count = value
    elif isinstance(value, float):
        raise TypeError(
            f"{where} must be an integer token count, not a binary float {value!r}"
        )
    else:
        text = str(value).strip().replace(",", "")
        if not text:
            return 0
        try:
            parsed = Decimal(text)
        except ArithmeticError as exc:
            raise ValueError(f"{where} is not a token count: {value!r}") from exc
        if parsed != parsed.to_integral_value():
            raise ValueError(f"{where} must be a whole number of tokens, got {value!r}")
        count = int(parsed)
    if count < 0:
        raise ValueError(f"{where} must be >= 0, got {count}")
    return count


def _normalise_counts(provider: str, categories: Mapping[str, int]) -> dict[str, int]:
    """Map the statement's own category names onto Backstop's four components.

    The two providers count cached tokens on **opposite sides** of the number they
    call the input, and the arithmetic is not symmetric — this is the asymmetry
    ``docs/planning/03-attribution-and-schema.md`` Part 4.5 calls the single most
    expensive correctness issue in the ledger half, and a name-based rule would be
    right for one provider and wrong for the other under the very same name. So the
    rule takes the provider from the line and resolves in this order:

    1. an explicitly **exclusive** count (``input_uncached_tokens``,
       ``uncached_input_tokens``, ``fresh_input_tokens``) wins outright and is the
       fresh input;
    2. otherwise a row carrying ``input_tokens`` is read according to the provider:
       for :data:`INCLUSIVE_INPUT_PROVIDERS` the cached count is subtracted from it,
       and for everyone else it already **is** the fresh count.

    The raw categories stay on the :class:`InvoiceLine` either way, so a reader can
    see what the statement actually published and check this arithmetic.
    """
    counts: dict[str, int] = {}
    for component, names in COMPONENT_CATEGORIES.items():
        if component == "input":
            continue
        counts[component] = sum(categories.get(name, 0) for name in names)
    counts["input"] = _fresh_input(provider, categories, counts["cache_read"])
    return counts


def _fresh_input(provider: str, categories: Mapping[str, int], cached: int) -> int:
    """The fresh, non-cached input count — the one a rate card charges at the full
    input rate — out of whatever this statement published."""
    for name in EXCLUSIVE_INPUT_CATEGORIES:
        if name in categories:
            return categories[name]
    if INCLUSIVE_INPUT_CATEGORY in categories:
        inclusive = categories[INCLUSIVE_INPUT_CATEGORY]
        return inclusive - cached if provider in INCLUSIVE_INPUT_PROVIDERS else inclusive
    return 0


def _unmapped_categories(categories: Mapping[str, int]) -> tuple[str, ...]:
    """The token categories a row carries that no Backstop component is built from.

    A non-empty result means the token comparison on that row is **incomplete**, and
    the row's status says so rather than reporting a delta that silently ignores a
    category. This is the forward-compatibility path: a provider that starts
    publishing a new category produces a visible "I cannot compare this" instead of
    a confident number that omits it.
    """
    return tuple(
        sorted(name for name, tokens in categories.items() if tokens and name not in _KNOWN_CATEGORIES)
    )


# --------------------------------------------------------------------------
# The invoice model
# --------------------------------------------------------------------------


def _check_text(name: str, value: Any) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str, got {type(value).__name__} {value!r}")
    if not value.strip():
        raise ValueError(f"{name} must be non-empty, got {value!r}")


@dataclass(frozen=True)
class InvoiceLine:
    """One row of a provider statement: what they billed, for what, and when.

    A statement row is not a :class:`~backstop.ledger.schema.SpendEvent` and does
    not pretend to be one. It is an aggregate — a day, a model, a set of token
    counts and one amount — and a single event does not correspond to a single row
    of it. What it carries that matters here:

    ``token_categories``
        The statement's **own** category names mapped to counts, kept verbatim and
        normalised into the four Backstop components by
        :func:`_normalise_counts` rather than assumed. OpenAI and Anthropic name
        and split cache tokens differently, and the difference is not cosmetic:
        OpenAI's ``input_tokens`` counts the cached tokens *inside* it and
        Anthropic's does not.
    ``provider``
        Recorded on the line, not inferred later. A statement row whose provider
        disagrees with the ledger's events for the same model is reported as two
        rows — a mismatch, not something to merge away.
    ``cost_type``
        The provider's own category for the *money*. ``"tokens"`` is the default
        and the only value that carries a token comparison; a row billing
        ``"web_search"`` or ``"code_execution"`` is real money with no tokens
        behind it, and a model carrying one cannot have its variance attributed to
        a count difference.

    ``charged_usd`` is quantised to :data:`backstop.pricing_catalog.MONEY_PLACES`
    decimal places with ``ROUND_HALF_UP`` because that is the quantum every ledger
    figure is stated at. A statement carrying finer precision loses at most half a
    microdollar per line here, which is four orders of magnitude below
    :data:`DEFAULT_TOLERANCE_USD`.
    """

    provider: str
    model: str
    period: str
    token_categories: Mapping[str, int]
    charged_usd: Decimal
    cost_type: str = "tokens"

    def __post_init__(self) -> None:
        for name in ("provider", "model", "period", "cost_type"):
            _check_text(name, getattr(self, name))
        categories = self.token_categories
        if not isinstance(categories, Mapping):
            raise TypeError(
                "token_categories must be a mapping of the statement's own category "
                f"names to counts, got {type(categories).__name__}"
            )
        checked: dict[str, int] = {}
        for name, value in categories.items():
            _check_text("a token category name", name)
            checked[name] = _read_count(value, f"token_categories[{name!r}]")
        if self.charged_usd is not None and not isinstance(self.charged_usd, Decimal):
            raise TypeError(
                f"charged_usd must be a Decimal, got {type(self.charged_usd).__name__} "
                f"{self.charged_usd!r}; money is never a binary float"
            )
        if not self.charged_usd.is_finite():
            raise ValueError(f"charged_usd must be finite, got {self.charged_usd!r}")
        if self.charged_usd < 0:
            raise ValueError(f"charged_usd must be >= 0, got {self.charged_usd!r}")
        object.__setattr__(self, "token_categories", MappingProxyType(checked))
        object.__setattr__(self, "charged_usd", _quantise(self.charged_usd))

    @property
    def counts(self) -> Mapping[str, int]:
        """The statement's categories as Backstop's four components."""
        return MappingProxyType(_normalise_counts(self.provider, self.token_categories))

    @property
    def input_tokens(self) -> int:
        return _normalise_counts(self.provider, self.token_categories)["input"]

    @property
    def output_tokens(self) -> int:
        return _normalise_counts(self.provider, self.token_categories)["output"]

    @property
    def cache_read_tokens(self) -> int:
        return _normalise_counts(self.provider, self.token_categories)["cache_read"]

    @property
    def cache_write_tokens(self) -> int:
        return _normalise_counts(self.provider, self.token_categories)["cache_write"]

    @property
    def total_tokens(self) -> int:
        return sum(_normalise_counts(self.provider, self.token_categories).values())

    @property
    def unmapped_categories(self) -> tuple[str, ...]:
        """Categories carrying tokens that no Backstop component is built from."""
        return _unmapped_categories(self.token_categories)

    @property
    def is_token_cost(self) -> bool:
        """Whether this row's money is token spend, and so carries a token
        comparison at all."""
        return self.cost_type == "tokens"

    def to_dict(self) -> dict[str, Any]:
        """The JSON form: the raw categories, the normalised four, and the money."""
        return {
            "provider": self.provider,
            "model": self.model,
            "period": self.period,
            "cost_type": self.cost_type,
            "token_categories": dict(self.token_categories),
            "charged_usd": format(self.charged_usd, "f"),
            "unmapped_categories": list(self.unmapped_categories),
        }


@dataclass(frozen=True)
class Invoice:
    """A statement file, read: its provenance, its window, and its rows.

    Immutable, like every other record in the ledger, and every line's ``provider``
    must agree with the invoice's own — a file that mixes two providers' rows under
    one statement is refused rather than normalised into one provider's shape,
    because a mixed file is either two files or a mistake and this module cannot
    tell which.
    """

    provider: str
    period: str
    source: str
    lines: tuple[InvoiceLine, ...]
    currency: str = CURRENCY
    #: Which column of the file satisfied each logical field, e.g.
    #: ``{"input": "input_uncached_tokens", "charged_usd": "cost_usd"}``.
    #:
    #: This exists because the accepted column names are transcribed from
    #: published reporting surfaces and have never been checked against a real
    #: statement file. A reconciliation that silently picked the wrong column
    #: would produce a confident, wrong variance. Recording the choice turns the
    #: assumption into something the reader can check against their own
    #: dashboard in one glance, which is the only honest way to ship an
    #: unverified parser.
    matched_fields: tuple[tuple[str, str], ...] = ()

    @property
    def columns_used(self) -> dict[str, str]:
        """The same mapping as a dict, for display."""
        return dict(self.matched_fields)

    def assumptions(self) -> str:
        """A one-line, human-checkable statement of what this parse assumed."""
        if not self.matched_fields:
            return "no column provenance recorded (this invoice was built, not parsed)"
        return ", ".join(f"{logical} <- {column}" for logical, column in self.matched_fields)

    def __post_init__(self) -> None:
        for name in ("provider", "period", "source", "currency"):
            _check_text(name, getattr(self, name))
        if self.currency != CURRENCY:
            raise ValueError(
                f"an invoice is reconciled in {CURRENCY}, which is the only currency "
                f"the ledger prices in; this statement is in {self.currency!r}"
            )
        if not isinstance(self.lines, tuple):
            raise TypeError(f"lines must be a tuple, got {type(self.lines).__name__}")
        for line in self.lines:
            if not isinstance(line, InvoiceLine):
                raise TypeError(
                    f"every line must be an InvoiceLine, got {type(line).__name__} {line!r}"
                )
        stray = sorted({line.provider for line in self.lines} - {self.provider})
        if stray:
            raise ValueError(
                f"invoice {self.source!r} is a {self.provider!r} statement but "
                f"carries lines from {stray}; reconcile the providers separately"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "period": self.period,
            "source": self.source,
            "currency": self.currency,
            "lines": [line.to_dict() for line in self.lines],
        }

    def models(self) -> tuple[str, ...]:
        """The distinct model names on the statement, in first-seen order."""
        seen: list[str] = []
        for line in self.lines:
            if line.model not in seen:
                seen.append(line.model)
        return tuple(seen)


# --------------------------------------------------------------------------
# The variance
# --------------------------------------------------------------------------

#: The reconciliation CSV's columns, in order. Money is a two-decimal string, the
#: tokens are integers, and ``reason`` carries the exact signed variance for every
#: row that is not ``matched`` — so nothing a two-decimal column rounds away is
#: lost from the file. There is **no totals row**: a totals line inside a table
#: finance intends to ``SUM`` is a double count waiting to happen, and the totals
#: belong in the report beside the table.
INVOICE_COLUMNS: tuple[str, ...] = (
    "provider",
    "model",
    "status",
    "currency",
    "ledger_usd",
    "invoice_usd",
    "variance_usd",
    "variance_pct",
    "ledger_events",
    "invoice_lines",
    "unpriced_events",
    "estimated_events",
    "ledger_input_tokens",
    "invoice_input_tokens",
    "input_token_delta",
    "ledger_output_tokens",
    "invoice_output_tokens",
    "output_token_delta",
    "ledger_cache_read_tokens",
    "invoice_cache_read_tokens",
    "cache_read_token_delta",
    "ledger_cache_write_tokens",
    "invoice_cache_write_tokens",
    "cache_write_token_delta",
    "unmapped_categories",
    "non_token_cost_types",
    "reason",
)

#: The columns a *displayed* table carries. Same convention as
#: :data:`backstop.ledger.export.DISPLAY_COLUMNS`: the count, the two money
#: figures, the signed variance, the token delta that attributes it, and the
#: status. Everything else is in the CSV and in the JSON.
_VARIANCE_DISPLAY: tuple[str, ...] = (
    "status",
    "ledger_usd",
    "invoice_usd",
    "variance_usd",
    "variance_pct",
    "input_token_delta",
    "output_token_delta",
    "reason",
)

_MONEY_COLUMNS = frozenset(("ledger_usd", "invoice_usd", "variance_usd", "variance_pct"))
_COUNT_COLUMNS = frozenset(
    name
    for name in INVOICE_COLUMNS
    if name.endswith("tokens") or name.endswith("token_delta") or name in ("ledger_events", "invoice_lines", "unpriced_events", "estimated_events")
)
_RIGHT_ALIGNED = _MONEY_COLUMNS | _COUNT_COLUMNS


def _optional_money(value: Decimal | None) -> str:
    """Render an exact amount, or the absent-value marker when there is none."""
    return ABSENT if value is None else format(value, "f")


def _optional_count(value: int | None) -> str:
    return ABSENT if value is None else str(value)


@dataclass(frozen=True)
class ModelVariance:
    """One model's worth of disagreement: the row a reconciliation is made of.

    **The sign convention**: ``variance_usd = ledger_usd - invoice_usd``, so a
    **positive** figure means Backstop claims more than the provider charged and a
    **negative** figure means Backstop claims less. A negative variance is not the
    safe direction — it is the one a streaming floor, an unpriced component and a
    stale rate card all produce — so both signs are reported, never an absolute.

    **Absent is not zero.** ``ledger_usd``, ``invoice_usd`` and therefore
    ``variance_usd`` and ``variance_pct`` are ``None`` when that side published no
    figure, and a difference cannot be taken against a number that does not exist.
    This is the ledger's own rule — a request the catalog cannot price is recorded
    with ``cost=None`` and reported as absent — and the reason string on the row
    says which side is missing and why.

    The token counts are on both sides and their delta is beside them, so a
    variance can be **attributed** rather than only reported: equal counts with a
    money difference is a price difference, and a count difference with equal
    prices is a measurement difference. :attr:`token_delta` is ``None`` whenever
    the comparison cannot be made like for like — one side absent, or the statement
    carrying a category no Backstop component is built from, or billing a non-token
    cost alongside the tokens.
    """

    provider: str
    model: str
    status: str
    currency: str
    ledger_usd: Decimal | None
    invoice_usd: Decimal | None
    variance_usd: Decimal | None
    variance_pct: Decimal | None
    ledger_events: int
    invoice_lines: int
    unpriced_events: int
    estimated_events: int
    price_source: str
    ledger_tokens: Mapping[str, int]
    invoice_tokens: Mapping[str, int]
    token_delta: Mapping[str, int | None]
    unmapped_categories: tuple[str, ...]
    non_token_cost_types: tuple[str, ...]
    reason: str | None

    def __post_init__(self) -> None:
        for name in ("provider", "model", "status", "currency", "price_source"):
            _check_text(name, getattr(self, name))
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {list(STATUSES)}, got {self.status!r}")
        for name in ("ledger_events", "invoice_lines", "unpriced_events", "estimated_events"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int, got {type(value).__name__} {value!r}")
            if value < 0:
                raise ValueError(f"{name} must be >= 0, got {value}")
        for name in ("unmapped_categories", "non_token_cost_types"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} must be a tuple, got {type(getattr(self, name)).__name__}")
        for name in ("ledger_usd", "invoice_usd", "variance_usd", "variance_pct"):
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, Decimal):
                raise TypeError(
                    f"{name} must be a Decimal or None, got {type(value).__name__} {value!r}; "
                    "money is never a binary float"
                )
        if (self.reason is None) != (self.status == STATUS_MATCHED):
            raise ValueError(
                f"a {self.status!r} row must carry a reason and only a "
                f"{STATUS_MATCHED!r} row may omit it; got {self.reason!r}"
            )
        for name in ("ledger_tokens", "invoice_tokens", "token_delta"):
            mapping = getattr(self, name)
            if not isinstance(mapping, Mapping):
                raise TypeError(f"{name} must be a mapping, got {type(mapping).__name__}")
            for component in COMPONENT_CATEGORIES:
                if component not in mapping:
                    raise ValueError(
                        f"{name} must carry every component {sorted(COMPONENT_CATEGORIES)}, "
                        f"missing {component!r}"
                    )
        object.__setattr__(self, "ledger_tokens", MappingProxyType(dict(self.ledger_tokens)))
        object.__setattr__(self, "invoice_tokens", MappingProxyType(dict(self.invoice_tokens)))
        object.__setattr__(self, "token_delta", MappingProxyType(dict(self.token_delta)))

    @property
    def ledger_total_tokens(self) -> int:
        return sum(self.ledger_tokens.values())

    @property
    def invoice_total_tokens(self) -> int:
        return sum(self.invoice_tokens.values())

    @property
    def is_reconciled(self) -> bool:
        """Whether the two sides are the same figure, not merely close."""
        return self.status == STATUS_MATCHED

    def as_dict(self) -> dict[str, Any]:
        """Every cell of this row, as a mapping, in :data:`INVOICE_COLUMNS` order.

        Money is the **exact** six-decimal string here rather than the two-decimal
        display string: this is the machine surface, and a reconciliation pipeline
        that reads a rounded variance cannot tell a rounding artefact from a real
        half-cent. The two-decimal form is the report's and the CSV's.
        """
        payload: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            "currency": self.currency,
        }
        for name in ("ledger_usd", "invoice_usd", "variance_usd", "variance_pct"):
            payload[name] = _optional_money(getattr(self, name))
        payload["variance_pct"] = (
            ABSENT if self.variance_pct is None else format(self.variance_pct, "f")
        )
        for name in ("ledger_events", "invoice_lines", "unpriced_events", "estimated_events"):
            payload[name] = getattr(self, name)
        for component in COMPONENT_CATEGORIES:
            payload[f"ledger_{component}_tokens"] = self.ledger_tokens[component]
            payload[f"invoice_{component}_tokens"] = self.invoice_tokens[component]
            payload[f"{component}_token_delta"] = self.token_delta[component]
        payload["unmapped_categories"] = list(self.unmapped_categories)
        payload["non_token_cost_types"] = list(self.non_token_cost_types)
        payload["reason"] = ABSENT if self.reason is None else self.reason
        return payload

    def to_dict(self) -> dict[str, Any]:
        return self.as_dict()

    def cells(self, columns: Sequence[str] = INVOICE_COLUMNS) -> tuple[str, ...]:
        """This row's cells for ``columns``, as strings.

        The one rendering path for the CSV, the markdown table and the JSON, so a
        table and the file exported beside it cannot disagree about a cell. Money is
        the two-decimal :func:`~backstop.ledger.export.money` form; an absent
        figure renders as :data:`ABSENT`, never as a blank and never as a zero.
        """
        exact = self.as_dict()
        rendered: dict[str, str] = {}
        for name in columns:
            value = exact[name]
            if value is None or value == ABSENT:
                # One branch for every absent figure, so no cell in the file can ever
                # be a Python ``None``: the marker, or nothing. The two cases are
                # separate — a count that is ``None`` reaches here from the record, a
                # money figure that is absent arrives already rendered — and a
                # blanket ``== ABSENT`` on the money branch would be a second path
                # for the same answer.
                rendered[name] = ABSENT
            elif name in _MONEY_COLUMNS:
                rendered[name] = money(Decimal(value))
            elif isinstance(value, list):
                rendered[name] = "|".join(value) or NO_VALUE
            else:
                rendered[name] = str(value)
        return tuple(rendered[name] for name in columns)

    def to_markdown_row(self) -> str:
        """One markdown table row, in :data:`_VARIANCE_DISPLAY` order."""
        cells = self.cells(_VARIANCE_DISPLAY)
        return (
            "| "
            + " | ".join(
                cell.replace("|", "\\|")
                for name, cell in zip(_VARIANCE_DISPLAY, cells, strict=True)
            )
            + " |"
        )


@dataclass(frozen=True)
class InvoiceVariance:
    """A whole reconciliation: every model's row, the total, and what went in.

    **Self-auditing by construction.** :attr:`events`, :attr:`invoice_lines` and
    :attr:`matched_models` are the three counts a reader needs to tell an empty
    reconciliation from a clean one. A report over no events and no statement lines
    is *not* a report of zero variance, and :attr:`is_empty` says so; a report where
    every row reconciled is :attr:`reconciled_models` of
    :attr:`models_count` rows, and both numbers are here.

    The total's :attr:`status` is the most severe state any row carries, in
    :data:`STATUSES` order. Its money is the sum of the rows that **have** a figure,
    and :attr:`rows_without_ledger_usd` and :attr:`rows_without_invoice_usd` say
    how many did not — because a total that quietly omitted an absent row would be
    the netting this module refuses to do.
    """

    provider: str
    period: str
    source: str
    currency: str
    tolerance_usd: Decimal
    tolerance_pct: Decimal
    rows: tuple[ModelVariance, ...]
    events: int
    invoice_lines: int

    def __post_init__(self) -> None:
        for name in ("provider", "period", "source", "currency"):
            _check_text(name, getattr(self, name))
        if not isinstance(self.rows, tuple):
            raise TypeError(f"rows must be a tuple, got {type(self.rows).__name__}")
        for name in ("tolerance_usd", "tolerance_pct"):
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                raise TypeError(
                    f"{name} must be a Decimal, got {type(value).__name__} {value!r}; money "
                    "is never a binary float"
                )
            if not value.is_finite() or value < 0:
                raise ValueError(f"{name} must be a finite, non-negative amount, got {value!r}")
        for name in ("events", "invoice_lines"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int, got {type(value).__name__} {value!r}")
            if value < 0:
                raise ValueError(f"{name} must be >= 0, got {value}")

    @property
    def providers(self) -> tuple[str, ...]:
        """Every provider name appearing on a row.

        Usually exactly :attr:`provider`, the statement's own. A second name means
        the ledger holds traffic for a provider this statement does not cover, and
        those rows are the mismatch report rather than an error to be raised — the
        whole point of recording the provider on every line is that a disagreement
        is *shown*.
        """
        names: list[str] = [self.provider]
        for row in self.rows:
            if row.provider not in names:
                names.append(row.provider)
        return tuple(names)

    @property
    def models_count(self) -> int:
        return len(self.rows)

    @property
    def reconciled_models(self) -> int:
        """Rows whose two sides are the same figure."""
        return sum(1 for row in self.rows if row.status == STATUS_MATCHED)

    @property
    def unmatched_models(self) -> int:
        return self.models_count - self.reconciled_models

    @property
    def is_empty(self) -> bool:
        """Whether there was nothing at all to reconcile.

        Distinct from "everything reconciled": a report over zero events and zero
        statement lines has reconciled nothing, and its zero variance means
        nothing. Every renderer that prints a total says so.
        """
        return not self.rows and not self.events and not self.invoice_lines

    @property
    def rows_without_ledger_usd(self) -> int:
        """Rows the ledger has no dollar figure for, so the total omits."""
        return sum(1 for row in self.rows if row.ledger_usd is None)

    @property
    def rows_without_invoice_usd(self) -> int:
        return sum(1 for row in self.rows if row.invoice_usd is None)

    @property
    def unpriced_events(self) -> int:
        return sum(row.unpriced_events for row in self.rows)

    @property
    def estimated_events(self) -> int:
        return sum(row.estimated_events for row in self.rows)

    @property
    @_exact
    def ledger_usd(self) -> Decimal | None:
        """The ledger's total across the rows that have one, or ``None`` if none do."""
        present = [row.ledger_usd for row in self.rows if row.ledger_usd is not None]
        return _quantise(sum(present, _ZERO)) if present else None

    @property
    @_exact
    def invoice_usd(self) -> Decimal | None:
        present = [row.invoice_usd for row in self.rows if row.invoice_usd is not None]
        return _quantise(sum(present, _ZERO)) if present else None

    @property
    @_exact
    def variance_usd(self) -> Decimal | None:
        ledger, invoice = self.ledger_usd, self.invoice_usd
        if ledger is None or invoice is None:
            return None
        return _quantise(ledger - invoice)

    @property
    @_exact
    def variance_pct(self) -> Decimal | None:
        """``variance_usd / invoice_usd`` as a **percentage**, four places.

        ``None`` rather than zero when the statement billed nothing: a share of
        zero has no denominator, and printing ``0.00%`` there would claim a
        perfect match on a row that does not exist.
        """
        variance, invoice = self.variance_usd, self.invoice_usd
        if variance is None or invoice is None or invoice == 0:
            return None
        return (variance / invoice * 100).quantize(_SHARE_QUANTUM, rounding=ROUND_HALF_UP)

    @property
    def status(self) -> str:
        """The most severe state any row carries, in :data:`STATUSES` order."""
        if not self.rows:
            return STATUS_MATCHED
        worst = STATUS_MATCHED
        for row in self.rows:
            if STATUSES.index(row.status) > STATUSES.index(worst):
                worst = row.status
        return worst

    @property
    def ledger_tokens(self) -> dict[str, int]:
        return {
            component: sum(row.ledger_tokens[component] for row in self.rows)
            for component in COMPONENT_CATEGORIES
        }

    @property
    def invoice_tokens(self) -> dict[str, int]:
        return {
            component: sum(row.invoice_tokens[component] for row in self.rows)
            for component in COMPONENT_CATEGORIES
        }

    @property
    @_exact
    def token_delta(self) -> dict[str, int | None]:
        """The total token delta per component, or ``None`` where it is not
        comparable on every row that carries tokens.

        Summing a total across rows that each have a different population is the
        netting this module refuses, so the component is ``None`` unless **every**
        row with tokens on both sides has a comparable delta.
        """
        result: dict[str, int | None] = {}
        for component in COMPONENT_CATEGORIES:
            deltas = [row.token_delta[component] for row in self.rows]
            result[component] = None if any(d is None for d in deltas) else sum(deltas)  # type: ignore[arg-type]
        return result

    def row_for(self, model: str) -> ModelVariance | None:
        """The row for one model name, or ``None`` when there is not one."""
        for row in self.rows:
            if row.model == model:
                return row
        return None

    def to_dict(self) -> dict[str, Any]:
        """The JSON form. Money is the exact six-decimal string everywhere."""
        return {
            "provider": self.provider,
            "period": self.period,
            "source": self.source,
            "currency": self.currency,
            "scope": RECONCILIATION_SCOPE,
            "tolerance_usd": format(self.tolerance_usd, "f"),
            "tolerance_pct": format(self.tolerance_pct, "f"),
            "status": self.status,
            "empty": self.is_empty,
            "counts": {
                "events": self.events,
                "invoice_lines": self.invoice_lines,
                "models": self.models_count,
                "reconciled_models": self.reconciled_models,
                "unmatched_models": self.unmatched_models,
                "unpriced_events": self.unpriced_events,
                "estimated_events": self.estimated_events,
                "rows_without_ledger_usd": self.rows_without_ledger_usd,
                "rows_without_invoice_usd": self.rows_without_invoice_usd,
            },
            "totals": {
                "ledger_usd": _optional_money(self.ledger_usd),
                "invoice_usd": _optional_money(self.invoice_usd),
                "variance_usd": _optional_money(self.variance_usd),
                "variance_pct": (
                    ABSENT if self.variance_pct is None else format(self.variance_pct, "f")
                ),
                "ledger_tokens": self.ledger_tokens,
                "invoice_tokens": self.invoice_tokens,
                "token_delta": self.token_delta,
            },
            "rows": [row.as_dict() for row in self.rows],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_markdown(self) -> str:
        """The whole reconciliation on one screen, with the honesty on it.

        The counts come first, before any money, because a reader who looks at a
        total and not at the counts cannot tell an empty reconciliation from a
        clean one — which is the whole reason the counts are on the record.
        """
        lines = [
            f"# Ledger vs statement — {self.provider}, {self.period}",
            "",
            f"- **statement file:** `{self.source}`",
        ]
        lines.extend(self.to_markdown_body().split("\n"))
        return "\n".join(lines)

    def to_markdown_body(self) -> str:
        """The report without its title: the counts, the table, the total, the scope.

        Split out because the CLI composes its own header — the ledger file, the
        statement file and the ledger's own integrity report all belong in front of
        this — and two copies of the counts in one screen is one too many.
        """
        lines = [
            f"- **inputs:** {self.events} ledger event(s), {self.invoice_lines} statement "
            f"line(s), across {self.models_count} model row(s)",
            f"- **reconciled exactly:** {self.reconciled_models} of {self.models_count} "
            f"model row(s); overall status **{self.status}**",
            f"- **tolerance:** ${format(self.tolerance_usd, 'f')} or "
            f"{format(self.tolerance_pct, 'f')}%, whichever is looser",
        ]
        if len(self.providers) > 1:
            lines.append(
                f"- **rows naming a provider this statement does not cover:** "
                f"{[p for p in self.providers if p != self.provider]}. Those rows are "
                "the mismatch report, not a merge: a model the ledger priced against "
                "one vendor and the statement billed against another is two facts."
            )
        if self.is_empty:
            lines.extend(
                [
                    "",
                    "**Nothing was reconciled.** There were no ledger events and no "
                    "statement lines, so every figure below is zero because the "
                    "inputs were empty, not because the two sides agree.",
                ]
            )
        lines.extend(
            [
                "",
                "## Per model",
                "",
                "| provider | model | status | ledger_usd | invoice_usd | variance_usd | "
                "variance_pct | input Δ | output Δ | reason |",
                "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in self.rows:
            lines.append(
                "| "
                + " | ".join(
                    cell.replace("|", "\\|")
                    for cell in (
                        row.provider,
                        row.model,
                        row.status,
                        *_row_money_cells(row),
                        _optional_count(row.token_delta["input"]),
                        _optional_count(row.token_delta["output"]),
                        row.reason or "",
                    )
                )
                + " |"
            )
        lines.extend(
            [
                "",
                "## Total",
                "",
                f"- ledger **{_optional_money(self.ledger_usd)} USD** against a statement of "
                f"**{_optional_money(self.invoice_usd)} USD** — variance "
                f"**{_optional_money(self.variance_usd)} USD**"
                + (
                    f" ({format(self.variance_pct, 'f')}%)"
                    if self.variance_pct is not None
                    else ""
                )
                + ".",
            ]
        )
        absent = []
        if self.rows_without_ledger_usd:
            absent.append(
                f"{self.rows_without_ledger_usd} row(s) have no ledger figure and are "
                "absent from the total, not zero"
            )
        if self.rows_without_invoice_usd:
            absent.append(
                f"{self.rows_without_invoice_usd} row(s) have no statement figure and are "
                "absent from the total, not zero"
            )
        if absent:
            lines.append("- " + "; ".join(absent) + ".")
        lines.extend(
            [
                f"- **{self.unpriced_events} event(s) carry no price** and "
                f"{self.estimated_events} were estimated rather than reported; both "
                "understate the ledger's side, and a total is only as good as the "
                "population behind it.",
                "",
                "## Scope",
                "",
                RECONCILIATION_SCOPE,
            ]
        )
        return "\n".join(lines)


def _row_money_cells(row: ModelVariance) -> tuple[str, ...]:
    exact = row.as_dict()
    return tuple(
        ABSENT if exact[name] == ABSENT else money(Decimal(exact[name]))
        for name in ("ledger_usd", "invoice_usd", "variance_usd")
    ) + ((ABSENT if row.variance_pct is None else format(row.variance_pct, "f")),)


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------


class _LedgerSide:
    """The ledger's figures for one ``(provider, model)``, accumulated."""

    __slots__ = (
        "events",
        "unpriced",
        "estimated",
        "sources",
        "total",
        "tokens",
    )

    def __init__(self) -> None:
        self.events = 0
        self.unpriced = 0
        self.estimated = 0
        self.sources: set[str] = set()
        self.total: Decimal | None = _ZERO
        self.tokens = {component: 0 for component in COMPONENT_CATEGORIES}

    def add(self, amount: Decimal | None, event: SpendEvent, price_source: str) -> None:
        self.events += 1
        for component in COMPONENT_CATEGORIES:
            self.tokens[component] += getattr(event, f"{component}_tokens")
        if event.estimated:
            self.estimated += 1
        if amount is None:
            self.unpriced += 1
            # One unpriced request in a model makes the model's *total* absent, not
            # understated: the other requests' dollars are known and this one's are
            # not, and a sum of the known alone would be a figure nobody can defend.
            self.total = None
            return
        self.sources.add(price_source)
        if self.total is not None:
            self.total = _quantise(self.total + amount)


class _InvoiceSide:
    """The statement's figures for one ``(provider, model)``, accumulated."""

    __slots__ = ("lines", "total", "tokens", "unmapped", "non_token_costs", "token_lines")

    def __init__(self) -> None:
        self.lines = 0
        self.total = Decimal(0)
        self.tokens = {component: 0 for component in COMPONENT_CATEGORIES}
        self.unmapped: set[str] = set()
        self.non_token_costs: set[str] = set()
        self.token_lines = 0

    def add(self, line: InvoiceLine) -> None:
        self.lines += 1
        self.total += line.charged_usd
        self.unmapped.update(line.unmapped_categories)
        if not line.is_token_cost:
            self.non_token_costs.add(line.cost_type)
            return
        self.token_lines += 1
        counts = _normalise_counts(line.provider, line.token_categories)
        for component, count in counts.items():
            self.tokens[component] += count


def _ledger_amount(event: SpendEvent, catalog: PriceCatalog | None) -> tuple[Decimal | None, str]:
    """What one event contributes to the ledger side, and which layer billed it.

    With a ``catalog`` the event is priced through :func:`compute_cost` whatever its
    own ``cost`` says, so a model the events were recorded against a catalog that
    did not carry is priced properly here. With no catalog the event's recorded
    ``cost`` is the only figure available, and an event recorded with ``cost=None``
    contributes **absent** dollars — the ledger's own rule, not a zero.
    """
    if catalog is not None:
        breakdown = compute_cost(event, catalog)
        if breakdown is None:
            return None, ""
        return breakdown.total_usd, breakdown.price_source
    if event.cost is None:
        return None, ""
    return event.cost.total_usd, event.cost.price_source


def _one_source(sources: set[str]) -> str:
    """One price layer's name, the mixture's name, or the empty-value marker.

    :func:`backstop.ledger.export._one_source` owns this rule and this report uses
    the same two sentinels for the same reason: a figure that does not say which
    rate card produced it is not auditable, and picking one of two layers would be a
    guess presented as a fact.
    """
    from .export import MIXED_PRICE_SOURCE

    if not sources:
        return NO_VALUE
    if len(sources) == 1:
        return next(iter(sources))
    return MIXED_PRICE_SOURCE


def _tolerance_for(invoice_usd: Decimal | None, usd: Decimal, pct: Decimal) -> Decimal:
    """The looser of a dollar floor and a percentage ceiling, for one row."""
    allowance = usd
    if invoice_usd is not None and invoice_usd > 0:
        allowance = max(allowance, _quantise(invoice_usd * pct / 100))
    return allowance


@_exact
def reconcile_invoice(
    events: Iterable[SpendEvent],
    invoice: Invoice,
    catalog: PriceCatalog | None = None,
    tolerance_usd: Decimal = DEFAULT_TOLERANCE_USD,
    tolerance_pct: Decimal = DEFAULT_TOLERANCE_PCT,
) -> InvoiceVariance:
    """Compare what Backstop recorded against what the provider billed.

    One row per ``(provider, model)``, plus a total derived from those rows. The
    sign convention is :attr:`ModelVariance.variance_usd`:
    ``ledger - invoice``, so positive means Backstop claims more than it was
    charged and negative means it claims less. Both signs are reported; a negative
    variance is the one a streaming floor, an unpriced component and a stale rate
    card all produce, and it is not the safe direction.

    **The five rules, and where each one shows up:**

    - **An unknown model is never guessed.** A model the catalog does not carry has
      no ledger figure, its row is :data:`STATUS_MISSING_FROM_LEDGER` with a reason
      saying so, and the total excludes it and says how many rows it excluded.
      There is no default rate and no neighbouring-model fallback.
    - **An unpriced request poisons its model's total.** One event with no price
      makes the whole model's ``ledger_usd`` absent rather than a sum of the events
      that did price, because a sum of the known alone is a figure nobody can
      defend. ``unpriced_events`` says how many.
    - **Nothing is netted away.** A model on one side only gets its own row, is
      never offset against the other side, and is reported as
      :data:`STATUS_MISSING_FROM_LEDGER` or :data:`STATUS_MISSING_FROM_INVOICE`.
    - **Rows are keyed on the exact model string**, not on a resolved price-card
      name. A statement that spells a model the way the ledger does not therefore
      produces a visible pair of rows rather than one merged row, because merging
      two names that happen to share a rate card is a guess.
    - **The result is self-auditing.** ``events``, ``invoice_lines`` and
      ``reconciled_models`` are on the record, so an empty reconciliation and a
      clean one are not the same report.

    ``catalog=None`` uses each event's own recorded ``cost``. A catalog, when given,
    prices every event through it, which is what lets a model the events were
    recorded without a price for still be compared — and what makes the unpriced case
    reproducible, because a catalog that does not carry the model reproduces it.

    The tolerance is the **looser** of ``tolerance_usd`` and
    ``invoice_usd * tolerance_pct / 100``; see :data:`DEFAULT_TOLERANCE_USD` for
    the reasoning behind each default. A row inside the tolerance is
    :data:`STATUS_WITHIN_TOLERANCE`, which is not "the same": its exact signed
    variance is on the row, and ``tolerance_usd=0`` turns every difference into a
    variance.

    Purity: no clock, no I/O, no global state. The same events and the same
    statement give the same rows in the same order, whatever order the events
    arrive in.
    """
    if not isinstance(invoice, Invoice):
        raise TypeError(f"invoice must be an Invoice, got {type(invoice).__name__}")
    if catalog is not None and not isinstance(catalog, PriceCatalog):
        raise TypeError(
            f"catalog must be a PriceCatalog or None, got {type(catalog).__name__}"
        )

    ledger: dict[tuple[str, str], _LedgerSide] = {}
    event_count = 0
    for event in events:
        if not isinstance(event, SpendEvent):
            raise TypeError(
                f"reconcile_invoice takes SpendEvent objects, got "
                f"{type(event).__name__} {event!r}"
            )
        event_count += 1
        amount, source = _ledger_amount(event, catalog)
        key = (event.provider, event.model)
        side = ledger.get(key)
        if side is None:
            side = ledger[key] = _LedgerSide()
        side.add(amount, event, source)

    statement: dict[tuple[str, str], _InvoiceSide] = {}
    for line in invoice.lines:
        key = (line.provider, line.model)
        side = statement.get(key)
        if side is None:
            side = statement[key] = _InvoiceSide()
        side.add(line)

    rows = [
        _model_row(key, ledger.get(key), statement.get(key), tolerance_usd, tolerance_pct)
        for key in sorted(set(ledger) | set(statement))
    ]
    return InvoiceVariance(
        provider=invoice.provider,
        period=invoice.period,
        source=invoice.source,
        currency=invoice.currency,
        tolerance_usd=tolerance_usd,
        tolerance_pct=tolerance_pct,
        rows=tuple(rows),
        events=event_count,
        invoice_lines=len(invoice.lines),
    )


def _model_row(
    key: tuple[str, str],
    ledger: _LedgerSide | None,
    statement: _InvoiceSide | None,
    tolerance_usd: Decimal,
    tolerance_pct: Decimal,
) -> ModelVariance:
    """Build one model's row, its status, and the sentence that explains it."""
    provider, model = key
    ledger_usd = ledger.total if ledger is not None else None
    invoice_usd = _quantise(statement.total) if statement is not None else None
    ledger_tokens = dict(ledger.tokens) if ledger is not None else {c: 0 for c in COMPONENT_CATEGORIES}
    invoice_tokens = (
        dict(statement.tokens) if statement is not None else {c: 0 for c in COMPONENT_CATEGORIES}
    )

    comparable = (
        ledger is not None
        and statement is not None
        and not statement.non_token_costs
        and not statement.unmapped
    )
    if comparable:
        delta = {c: ledger_tokens[c] - invoice_tokens[c] for c in COMPONENT_CATEGORIES}
    else:
        delta = {c: None for c in COMPONENT_CATEGORIES}

    variance = (
        _quantise(ledger_usd - invoice_usd)
        if ledger_usd is not None and invoice_usd is not None
        else None
    )
    pct = None
    if variance is not None and invoice_usd is not None and invoice_usd != 0:
        pct = (variance / invoice_usd * 100).quantize(_SHARE_QUANTUM, rounding=ROUND_HALF_UP)

    status, reason = _classify(
        provider=provider,
        ledger=ledger,
        statement=statement,
        ledger_usd=ledger_usd,
        invoice_usd=invoice_usd,
        variance=variance,
        delta=delta,
        tolerance_usd=tolerance_usd,
        tolerance_pct=tolerance_pct,
    )
    return ModelVariance(
        provider=provider,
        model=model,
        status=status,
        currency=CURRENCY,
        ledger_usd=ledger_usd,
        invoice_usd=invoice_usd,
        variance_usd=variance,
        variance_pct=pct,
        ledger_events=ledger.events if ledger is not None else 0,
        invoice_lines=statement.lines if statement is not None else 0,
        unpriced_events=ledger.unpriced if ledger is not None else 0,
        estimated_events=ledger.estimated if ledger is not None else 0,
        price_source=_one_source(ledger.sources if ledger is not None else set()),
        ledger_tokens=ledger_tokens,
        invoice_tokens=invoice_tokens,
        token_delta=delta,
        unmapped_categories=tuple(sorted(statement.unmapped)) if statement is not None else (),
        non_token_cost_types=tuple(sorted(statement.non_token_costs)) if statement is not None else (),
        reason=reason,
    )


def _classify(
    *,
    provider: str,
    ledger: _LedgerSide | None,
    statement: _InvoiceSide | None,
    ledger_usd: Decimal | None,
    invoice_usd: Decimal | None,
    variance: Decimal | None,
    delta: Mapping[str, int | None],
    tolerance_usd: Decimal,
    tolerance_pct: Decimal,
) -> tuple[str, str | None]:
    """Decide one row's status and write the sentence that explains it.

    The order matters and is the reason the module is trustworthy: **the missing
    cases are decided before the money is compared.** A model on one side only has
    no difference to measure, so comparing it and reporting a small variance would
    bury a whole missing model inside a rounding tolerance.
    """
    if ledger_usd is None and statement is None:
        return STATUS_MATCHED, None
    if ledger_usd is None:
        if ledger is not None and ledger.unpriced == ledger.events and ledger.events > 0:
            # Every event the ledger has for this model came back unpriced, so the
            # row has no ledger figure at all. The usual cause is that the catalog
            # has never heard of the model, and the sentence says so with the words
            # an operator will search for.
            return (
                STATUS_MISSING_FROM_LEDGER,
                f"unknown model to the price catalog: all {ledger.events} event(s) the "
                f"ledger recorded for this model on {provider!r} carry no price, so this "
                f"row's ledger figure is absent rather than zero. The statement bills "
                f"{format(invoice_usd, 'f')} USD for it, and Backstop claims nothing for "
                "it. No rate is invented for it and no neighbouring model is used; "
                "supply a catalog entry (price_catalog_path) and this row becomes "
                "comparable.",
            )
        return (
            STATUS_MISSING_FROM_LEDGER,
            f"the statement bills {format(invoice_usd, 'f')} USD for this model and the "
            "ledger recorded no event for it at all — traffic that did not go through a "
            "wrapped client, or a ledger that does not cover this window. Not offset "
            "against anything: it is reported on its own row.",
        )
    if statement is None:
        return (
            STATUS_MISSING_FROM_INVOICE,
            f"the ledger recorded {ledger.events} event(s) costing "
            f"{format(ledger_usd, 'f')} USD and the statement has no line for this "
            "model. Either the provider billed it elsewhere, or this is a period or a "
            "model name the two sides spell differently. Not offset against anything.",
        )

    allowance = _tolerance_for(invoice_usd, tolerance_usd, tolerance_pct)
    exact = format(variance, "f")
    if variance == 0:
        return STATUS_MATCHED, None

    attribution = _attribute(ledger, statement, delta, variance)
    if abs(variance) <= allowance:
        return (
            STATUS_WITHIN_TOLERANCE,
            f"{exact} USD against a {format(invoice_usd, 'f')} USD statement, inside the "
            f"{format(allowance, 'f')} USD allowed here; {attribution} Reported rather "
            "than rounded to zero, because a difference inside a tolerance is still a "
            "difference.",
        )
    return (
        STATUS_VARIANCE,
        f"{exact} USD against a {format(invoice_usd, 'f')} USD statement, above the "
        f"{format(allowance, 'f')} USD allowed here; {attribution}",
    )


def _attribute(
    ledger: _LedgerSide,
    statement: _InvoiceSide,
    delta: Mapping[str, int | None],
    variance: Decimal,
) -> str:
    """Say whether the difference is a price difference or a count difference.

    The point of carrying token counts on both sides: a variance that is *only*
    money is a rate-card problem, and a variance that comes with a token delta is a
    measurement problem, and those have completely different fixes. The clause names
    which one this is, or says why it cannot be attributed, and the caveat about
    estimated tokens is **appended** rather than leading — a reader who stops after
    the first clause should have read the cause, not the footnote.
    """
    if statement.non_token_costs:
        cause = (
            "it cannot be attributed to a token count: the statement bills "
            f"{', '.join(sorted(statement.non_token_costs))} cost for this model, which "
            "carries no tokens, so the two token sides are not like for like"
        )
    elif statement.unmapped:
        cause = (
            "it cannot be attributed to a token count: the statement publishes token "
            f"category(s) {list(sorted(statement.unmapped))} that no Backstop component "
            "is built from, so the two token sides are not like for like"
        )
    elif all(delta[component] in (None, 0) for component in COMPONENT_CATEGORIES):
        cause = (
            "every token count agrees exactly, so the whole difference is a price "
            "difference — the rate card the ledger billed is not the rate the statement "
            "applied"
        )
    else:
        cause = (
            "the token counts differ ("
            + _token_sentence(delta)
            + "), so this is at least partly a count difference rather than only a price "
            "difference"
        )
    if ledger.estimated:
        caveat = (
            f" — and {ledger.estimated} of the {ledger.events} event(s) on this row had "
            "estimated rather than provider-reported tokens, so the ledger's side is a "
            "floor"
        )
    else:
        caveat = ""
    return f"{cause}{caveat}."


def _token_sentence(delta: Mapping[str, int | None]) -> str:
    """The per-component token deltas, as one clause with a sign on each."""
    return ", ".join(
        f"{component} {delta[component]:+d}" for component in COMPONENT_CATEGORIES
    )


# --------------------------------------------------------------------------
# Parsing a statement file
# --------------------------------------------------------------------------


def _field_names(document: Mapping[str, Any], fields: Mapping[str, tuple[str, ...]]) -> dict[str, str]:
    """Resolve each logical field to the column the document actually carries."""
    present = {str(name) for name in document}
    resolved: dict[str, str] = {}
    for logical, candidates in fields.items():
        for candidate in candidates:
            if candidate in present:
                resolved[logical] = candidate
                break
    return resolved


def _field_candidates(
    fields: Mapping[str, tuple[str, ...]], field: str
) -> tuple[str, ...]:
    """Every column name this module would accept for one logical field.

    The ``input`` entry is the interesting one: a row may publish the exclusive
    count, or the inclusive one, or both, so the accepted set is the union of the
    component's own names and :data:`INCLUSIVE_INPUT_CATEGORY`. The error message
    lists this set, because the useful part of "missing required field" is what to
    type or what to correct.
    """
    if field == "input":
        return (INCLUSIVE_INPUT_CATEGORY, *COMPONENT_CATEGORIES["input"])
    return fields[field]


#: Appended to the "missing charged amount" message, and only for Anthropic, because
#: that is the provider whose published cost report is denominated in cents. A user
#: who hits this with a cents column needs to be told that the number in front of them
#: is a hundred times smaller than the amount it looks like.
_CENTS_HINT = (
    " A bare 'amount' column is deliberately not read: Anthropic's cost report is "
    "denominated in lowest currency units (cents), so reading it as dollars would be a "
    "100x error. Convert it yourself, or name the column so it says USD."
)


def _missing_fields(
    resolved: Mapping[str, str],
    fields: Mapping[str, tuple[str, ...]],
    path: str,
    provider: str,
) -> str:
    """The names of the required fields this document does not carry, in full."""
    absent: list[str] = []
    for field in REQUIRED_STATEMENT_FIELDS:
        if field in resolved:
            continue
        candidates = list(_field_candidates(fields, field))
        absent.append(f"{field!r} (any of {candidates})")
    hint = _CENTS_HINT if provider == "anthropic" and "charged_usd" not in resolved else ""
    return (
        f"invoice statement {path!r} is missing {len(absent)} required field(s): "
        + "; ".join(absent)
        + ". A statement row that does not carry a model, a period, both token counts "
        "and a charged amount cannot be compared with a ledger, and this parser refuses "
        "it rather than reporting zeros — a zero reconciles against a zero and looks "
        "clean. If the column is named differently in your provider's export, add the "
        "spelling to the OPENAI_STATEMENT_FIELDS / ANTHROPIC_STATEMENT_FIELDS constant "
        "in backstop.ledger.reconcile."
        + hint
    )


def _detect_provider(names: Iterable[str], path: str) -> str:
    """Which provider's statement these column names are.

    Decided by the **token category** names, which are the only ones the two
    providers spell differently — ``input_cached_tokens``/``input_uncached_tokens``
    for OpenAI against ``cache_read_input_tokens``/``uncached_input_tokens`` for
    Anthropic. A file that carries neither, or both, is refused with the two sets
    named, because guessing a provider would put one vendor's dollars in the other
    vendor's row.
    """
    present = {str(name) for name in names}
    markers = {
        "openai": {"input_cached_tokens", "input_uncached_tokens", "input_cache_write_tokens"},
        "anthropic": {
            "uncached_input_tokens",
            "cache_read_input_tokens",
            "cache_creation_5m_input_tokens",
            "cache_creation_1h_input_tokens",
            "cache_creation_input_tokens",
        },
    }
    matched = sorted(provider for provider, keys in markers.items() if present & keys)
    if len(matched) == 1:
        return matched[0]
    raise ValueError(
        f"cannot tell which provider's statement {path!r} is: it carries "
        f"{'none of' if not matched else 'both ' + ' and '.join(matched)} the token "
        f"category names that distinguish the two formats. Pass provider= explicitly. "
        f"The categories this module knows: {sorted(_KNOWN_CATEGORIES)}."
    )


def _lines_from_rows(
    rows: Sequence[Mapping[str, Any]],
    provider: str,
    period: str,
    path: str,
) -> tuple[InvoiceLine, ...]:
    """Turn statement rows in this module's own shape into :class:`InvoiceLine`\\ s."""
    fields = PROVIDER_STATEMENT_FIELDS.get(provider)
    if fields is None:
        raise ValueError(
            f"provider {provider!r} has no statement format in this module; it reads "
            f"{sorted(PROVIDER_STATEMENT_FIELDS)}. A provider whose statement format is "
            "not implemented is a provider whose invoice cannot be reconciled, and "
            "saying so is better than reading its columns as another vendor's."
        )
    lines: list[InvoiceLine] = []
    for index, row in enumerate(rows):
        where = f"invoice {path!r} row {index}"
        if not isinstance(row, Mapping):
            raise ValueError(
                f"{where}: must be an object, got {type(row).__name__}"
            )
        resolved = _field_names(row, fields)
        missing = [f for f in REQUIRED_STATEMENT_FIELDS if f not in resolved]
        if missing:
            raise ValueError(
                f"{where}: {_missing_fields(resolved, fields, path, provider)}\nRefusing the file: a "
                "statement with a hole in it must not reconcile."
            )
        categories = {
            resolved[component]: _read_count(row[resolved[component]], f"{where} {component}")
            for component in COMPONENT_CATEGORIES
            if component in resolved
        }
        if "input" not in resolved and INCLUSIVE_INPUT_CATEGORY in row:
            categories[INCLUSIVE_INPUT_CATEGORY] = _read_count(
                row[INCLUSIVE_INPUT_CATEGORY], f"{where} input_tokens"
            )
        model = row[resolved["model"]]
        _check_text(f"{where} model", model if isinstance(model, str) else str(model))
        lines.append(
            InvoiceLine(
                provider=provider,
                model=str(model).strip(),
                period=str(row[resolved["period"]]).strip() or period,
                token_categories=categories,
                charged_usd=_read_amount(
                    _wire_amount(row[resolved["charged_usd"]]), f"{where} charged_usd"
                ),
                cost_type=str(row.get("cost_type", "tokens")),
            )
        )
    return tuple(lines)


def _check_period(period: Any, path: str) -> str:
    if not isinstance(period, str) or not period.strip():
        raise ValueError(
            f"invoice statement {path!r} declares no period. A reconciliation is over a "
            "window, and a statement that does not say which one cannot be compared "
            "with a ledger that does."
        )
    return period.strip()


@_exact
def parse_invoice_csv(path: str | os.PathLike[str], provider: str | None = None) -> Invoice:
    """Read a provider's usage-statement **CSV**, and return one :class:`Invoice`.

    **The format assumed.** A delimited statement whose header carries, at least, a
    model name, a period, the two plain token counts and a charged amount in USD —
    the shape both providers' console and admin surfaces publish for a per-day,
    per-model usage statement. The accepted column names per provider are
    :data:`OPENAI_STATEMENT_FIELDS` and :data:`ANTHROPIC_STATEMENT_FIELDS`, and
    **they are transcribed from those providers' published reporting surfaces, not
    from a real statement: this repository has never been handed one.** They are
    centralised in one marked block for exactly that reason — a reader who owns a
    statement corrects one constant, and a provider that renames a column fails loudly
    here rather than quietly reconciling nothing. Note in particular that a bare
    ``amount`` column is **not** read: Anthropic's cost report is denominated in
    cents, and reading a cents figure as dollars is a 100x error a reader would
    believe.

    ``provider`` is sniffed from the token-category column names when omitted, and
    the sniffing is only ever between the two known formats — see
    :func:`_detect_provider`.

    **A row that does not match raises.** A missing required column, a missing
    required field on a row, a non-numeric amount, a float amount, a negative
    amount, or a negative token count each raise ``ValueError`` or ``TypeError``
    naming the row and the field. The parser never substitutes a zero: a statement
    that does not parse is a statement nobody has checked the money on, and
    producing a clean-looking report from it would be the worst outcome available.

    The returned :class:`Invoice` carries ``source`` as the path it was read from,
    and the provider on every line.
    """
    location = os.fspath(path)
    with open(location, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or ())
        if not header:
            raise ValueError(
                f"invoice statement {location!r} has no header row, so no column can "
                "be matched and nothing can be read from it."
            )
        name = provider or _detect_provider(header, location)
        if name not in PROVIDER_STATEMENT_FIELDS:
            raise ValueError(
                f"provider {name!r} has no statement format in this module; it reads "
                f"{sorted(PROVIDER_STATEMENT_FIELDS)}. A provider whose statement format "
                "is not implemented is a provider whose invoice cannot be reconciled, "
                "and saying so is better than reading its columns as another vendor's."
            )
        fields = PROVIDER_STATEMENT_FIELDS[name]
        resolved = _field_names(header, fields)
        missing = [f for f in REQUIRED_STATEMENT_FIELDS if f not in resolved]
        if missing:
            raise ValueError(_missing_fields(resolved, fields, location, name))
        rows = [
            {key: value for key, value in row.items() if key is not None}
            for row in reader
        ]
    if not rows:
        raise ValueError(
            f"invoice statement {location!r} has a header and no data rows, so it "
            "reconciles nothing. A reader that reported a clean result here would be "
            "reporting an empty file as a checked one."
        )
    period = _check_period(
        str(rows[0].get(resolved["period"], "")).strip()
        or str(max(str(row.get(resolved["period"], "")) for row in rows)),
        location,
    )
    return Invoice(
        provider=name,
        period=period,
        source=location,
        lines=_lines_from_rows(rows, name, period, location),
        matched_fields=tuple(sorted(resolved.items())),
    )


@_exact
def parse_invoice_json(path: str | os.PathLike[str], provider: str | None = None) -> Invoice:
    """Read an invoice statement in **this module's own JSON shape**, and return an
    :class:`Invoice`.

    **The format assumed, and why it is not a provider's.** A document that is
    either a list of statement rows or an object with ``provider``, ``period`` and
    ``lines``, where each row carries a model, a period, the token counts and a
    charged amount under the column names in
    :data:`OPENAI_STATEMENT_FIELDS` / :data:`ANTHROPIC_STATEMENT_FIELDS``:

    .. code-block:: json

        {
          "provider": "openai",
          "period": "2026-09",
          "lines": [
            {
              "model": "gpt-4o",
              "date": "2026-09-26",
              "input_uncached_tokens": "600000",
              "input_cached_tokens": "400000",
              "output_tokens": "12000",
              "cost_usd": "1.745000"
            }
          ]
        }

    Money is a **string**, and a JSON number is read back through its shortest
    repr — a JSON number has already been through a binary float. A Python float
    cannot arrive here at all, and one handed in directly is refused.

    This is Backstop's shape rather than either provider's, and that is a statement
    about the providers rather than a shortcut: **no provider publishes one document
    carrying both token counts and charged amounts.** Anthropic's cost report carries
    the amounts and names a ``token_type`` but no counts, and its usage report
    carries the counts and no amounts; OpenAI's cost endpoint carries the amounts
    with no per-model tokens at all. A document with both sides is assembled by the
    reader from two statements, and this parser reads that assembled file — and says
    so, rather than implying it has read an invoice a provider actually sent.

    Every refusal :func:`parse_invoice_csv` makes is made here too, with the same
    messages: a non-object document, a row with no model, period, token counts or
    amount, a blank amount, and an unparseable file all raise naming the row.
    """
    location = os.fspath(path)
    with open(location, "r", encoding="utf-8") as handle:
        raw = handle.read()
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"invoice statement {location!r} is not valid JSON: {exc}") from exc

    if isinstance(document, list):
        rows: list[Mapping[str, Any]] = []
        name = provider
        period = ""
        for index, item in enumerate(document):
            if not isinstance(item, Mapping):
                raise ValueError(
                    f"invoice {location!r} line {index}: must be an object, got "
                    f"{type(item).__name__}"
                )
            rows.append(item)
        if not rows:
            raise ValueError(
                f"invoice statement {location!r} is an empty list, so it reconciles "
                "nothing."
            )
        name = name or _detect_provider(rows[0].keys(), location)
        lines = _lines_from_rows(rows, name, "", location)
        period = _check_period(lines[0].period, location)
        return Invoice(provider=name, period=period, source=location, lines=lines)

    if not isinstance(document, Mapping):
        raise ValueError(
            f"invoice statement {location!r} must be a JSON object or a list of rows, "
            f"got {type(document).__name__}"
        )
    allowed = {"provider", "period", "currency", "source", "lines"}
    stray = sorted(set(document) - allowed)
    if stray:
        raise ValueError(
            f"invoice statement {location!r}: unknown key(s) {stray}; a statement "
            f"document accepts {sorted(allowed)}"
        )
    # The currency is a document-level fact and it is checked first: a statement in
    # another currency invalidates every figure in it, so there is no point counting
    # its rows before saying so.
    currency = document.get("currency", CURRENCY)
    if currency != CURRENCY:
        raise ValueError(
            f"invoice statement {location!r} is in {currency!r}; the ledger prices in "
            f"{CURRENCY} and this module will not convert between them."
        )
    listed = document.get("lines")
    if not isinstance(listed, list):
        raise ValueError(
            f"invoice statement {location!r}: 'lines' must be a list of statement rows, "
            f"got {type(listed).__name__}"
        )
    if not listed:
        raise ValueError(
            f"invoice statement {location!r} carries no lines, so it reconciles nothing."
        )
    name = document.get("provider", provider)
    if name is not None and not isinstance(name, str):
        raise TypeError(
            f"invoice statement {location!r}: 'provider' must be a string, got "
            f"{type(name).__name__}"
        )
    if name is None:
        first = listed[0]
        if not isinstance(first, Mapping):
            raise ValueError(f"invoice {location!r} line 0: must be an object")
        name = _detect_provider(first.keys(), location)
    period = _check_period(document.get("period", ""), location)
    return Invoice(
        provider=name,
        period=period,
        source=str(document.get("source", location)),
        lines=_lines_from_rows(listed, name, period, location),
    )


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


@_exact
def reconciliation_csv(variance: InvoiceVariance) -> str:
    """Return the per-model reconciliation as RFC 4180 CSV text.

    Header first, one line per model row, CRLF between and after every record
    including the last (:data:`~backstop.ledger.export.CSV_TERMINATOR`), minimal
    quoting, so a reason containing a comma is quoted and nothing else is. Stable
    column order (:data:`INVOICE_COLUMNS`), largest variance first, and **no totals
    row** — a totals line inside a table finance intends to ``SUM`` is a double
    count waiting to happen.

    Money cells are the two-decimal strings from
    :func:`~backstop.ledger.export.money`, so no cell in the file is a number a
    spreadsheet can re-round, and an absent figure renders as
    :data:`ABSENT` rather than as a zero. The exact six-decimal variance for every
    row that is not ``matched`` is inside that row's ``reason`` cell, so the
    two-decimal rounding of the money columns loses nothing a reader needs.
    """
    if not isinstance(variance, InvoiceVariance):
        raise TypeError(
            f"reconciliation_csv takes an InvoiceVariance, got {type(variance).__name__}"
        )
    ordered = sorted(
        variance.rows,
        key=lambda row: (
            row.provider,
            -(abs(row.variance_usd) if row.variance_usd is not None else Decimal(-1)),
            row.model,
        ),
    )
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator=CSV_TERMINATOR, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(INVOICE_COLUMNS)
    for row in ordered:
        writer.writerow(row.cells())
    return buffer.getvalue()


# --------------------------------------------------------------------------
# The error budget, measured
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ErrorBudget:
    """An **observed** error budget over the inputs it was given, and nothing else.

    The planning document proposed M1 as a *hypothesis* — "≤ 0.5%, unmeasured, no
    customer has run a billing period on this". This is the function that turns it
    into a measurement, over whatever statements the caller hands it, and it is
    deliberately worded so the result cannot be quoted as more than that.

    The observed figures are ``sum(|variance_usd|)`` over every model row and that
    sum as a percentage of what the statement billed **on the rows that had a figure
    on both sides**. **The absolute figure is the right one to quote**: a netted
    figure lets a model that is over-counted hide one that is under-counted, which is
    the netting this module refuses everywhere else. And the denominator is the
    statement's own billed total over the comparable rows, not over every row: a
    missing_from_ledger row contributes to neither side of the quotient, because
    folding a $3.00 the ledger never claimed into the denominator would understate
    the budget by making the ratio smaller.
    :attr:`worst_model` and :attr:`worst_variance_usd` name the single worst row, so
    a reader can go and look at it rather than trusting a percentage.

    :attr:`note` says the rest, in the words a CFO needs: this is empirical over the
    inputs given, an error budget is only an error budget over a population that
    resembles them, and a number measured over a few synthetic statements is not a
    promise about somebody else's account.
    """

    invoices: int
    models: int
    invoice_lines: int
    events: int
    reconciled_models: int
    observed_abs_variance_usd: Decimal | None
    observed_net_variance_usd: Decimal | None
    observed_rel_variance_pct: Decimal | None
    worst_model: str | None
    worst_variance_usd: Decimal | None
    worst_rel_variance_pct: Decimal | None
    tolerance_usd: Decimal
    tolerance_pct: Decimal
    rows_beyond_tolerance: int
    note: str

    @property
    def measured(self) -> bool:
        """Whether there was anything at all to measure."""
        return self.observed_abs_variance_usd is not None

    @property
    def within_tolerance(self) -> bool:
        """Whether every row sat inside the tolerance.

        ``False`` for an unmeasured budget rather than ``True``: a budget over
        nothing has not been shown to hold.
        """
        return self.measured and self.rows_beyond_tolerance == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoices": self.invoices,
            "models": self.models,
            "invoice_lines": self.invoice_lines,
            "events": self.events,
            "reconciled_models": self.reconciled_models,
            "measured": self.measured,
            "within_tolerance": self.within_tolerance,
            "observed_abs_variance_usd": _optional_money(self.observed_abs_variance_usd),
            "observed_net_variance_usd": _optional_money(self.observed_net_variance_usd),
            "observed_rel_variance_pct": (
                ABSENT
                if self.observed_rel_variance_pct is None
                else format(self.observed_rel_variance_pct, "f")
            ),
            "worst_model": ABSENT if self.worst_model is None else self.worst_model,
            "worst_variance_usd": _optional_money(self.worst_variance_usd),
            "worst_rel_variance_pct": (
                ABSENT
                if self.worst_rel_variance_pct is None
                else format(self.worst_rel_variance_pct, "f")
            ),
            "tolerance_usd": format(self.tolerance_usd, "f"),
            "tolerance_pct": format(self.tolerance_pct, "f"),
            "rows_beyond_tolerance": self.rows_beyond_tolerance,
            "note": self.note,
        }

    def to_markdown(self) -> str:
        """The budget as a markdown block, with the caveat inside it rather than
        below it."""
        if not self.measured:
            observed = "**not measured** — no row carried both a ledger figure and a statement figure"
        else:
            share = (
                f", which is **{format(self.observed_rel_variance_pct, 'f')}%** of what "
                "the statement billed on the rows that carried a figure on both sides"
                if self.observed_rel_variance_pct is not None
                else ""
            )
            observed = (
                f"**{format(self.observed_abs_variance_usd, 'f')} USD** absolute across "
                f"{self.models} model row(s) from {self.invoice_lines} statement line(s)"
                f"{share}"
            )
        worst = (
            f"{self.worst_model} at {format(self.worst_variance_usd, 'f')} USD"
            if self.worst_model is not None and self.worst_variance_usd is not None
            else "none — no row had a figure on both sides"
        )
        return "\n".join(
            [
                "## Error budget, measured over these inputs",
                "",
                f"- observed: {observed}",
                f"- netted (reported for completeness, never as the headline): "
                f"{_optional_money(self.observed_net_variance_usd)} USD",
                f"- worst single row: {worst}",
                f"- rows beyond the ${format(self.tolerance_usd, 'f')} / "
                f"{format(self.tolerance_pct, 'f')}% tolerance: {self.rows_beyond_tolerance}",
                f"- inputs: {self.invoices} statement file(s), {self.events} ledger "
                f"event(s), {self.reconciled_models} of {self.models} row(s) exact",
                "",
                f"> {self.note}",
            ]
        )


_BUDGET_NOTE = (
    "This is an empirical figure over the inputs it was given, not a guarantee. An "
    "error budget is only an error budget over a population that resembles the inputs "
    "it was measured on: a figure measured over a handful of statements says nothing "
    "about a deployment that streams, that sends traffic through an unwrapped client, "
    "that runs a model the catalog does not price, or that is on a rate card the "
    "providers have since changed. Treat it as the measured behaviour of the inputs "
    "in front of you, and tighten the tolerance per account rather than adopting a "
    "number from someone else's."
)


@_exact
def measure_error_budget(
    ledger_events: Sequence[SpendEvent],
    invoices: Sequence[Invoice],
    catalog: PriceCatalog | None = None,
    tolerance_usd: Decimal = DEFAULT_TOLERANCE_USD,
    tolerance_pct: Decimal = DEFAULT_TOLERANCE_PCT,
) -> ErrorBudget:
    """Reconcile one ledger against several statements and report what was observed.

    The multi-statement form of :func:`reconcile_invoice`, and the function that
    turns the planning document's hypothesised M1 into a number. It is deliberately
    a *measurement* and not a verdict: :attr:`ErrorBudget.note` states the limits in
    its own output, so the caveat travels with the figure instead of living in a
    docstring somebody has to have read.

    The headline figure is ``sum(|variance_usd|)`` over every model row, and it is
    reported as such rather than netted, because a netted total lets an
    over-counted model conceal an under-counted one. :attr:`ErrorBudget.worst_model`
    names the single worst row so a reader can go and look at it.

    Rows where either side published no figure are **counted, not measured**: they
    cannot contribute a variance, and pretending they reconciled would understate
    the budget. ``rows_beyond_tolerance`` counts only rows that had a figure on both
    sides, so the answer is never "0 beyond tolerance" for a window that was mostly
    unpriced.

    The tolerance parameters are :func:`reconcile_invoice`'s, and the defaults'
    reasoning is on :data:`DEFAULT_TOLERANCE_USD`.
    """
    if not isinstance(invoices, Sequence) or isinstance(invoices, (str, bytes)):
        raise TypeError(
            f"invoices must be a sequence of Invoice objects, got "
            f"{type(invoices).__name__}"
        )
    events = list(ledger_events)
    models = 0
    lines = 0
    reconciled = 0
    absolute = Decimal(0)
    netted = Decimal(0)
    basis = Decimal(0)
    measured_any = False
    worst: tuple[Decimal, str, Decimal] | None = None
    beyond = 0
    for invoice in invoices:
        if not isinstance(invoice, Invoice):
            raise TypeError(
                f"invoices must hold Invoice objects, got {type(invoice).__name__} {invoice!r}"
            )
        result = reconcile_invoice(
            events, invoice, catalog, tolerance_usd=tolerance_usd, tolerance_pct=tolerance_pct
        )
        models += result.models_count
        lines += result.invoice_lines
        reconciled += result.reconciled_models
        for row in result.rows:
            if row.variance_usd is None:
                continue
            measured_any = True
            absolute += abs(row.variance_usd)
            netted += row.variance_usd
            basis += row.invoice_usd if row.invoice_usd is not None else Decimal(0)
            if abs(row.variance_usd) > _tolerance_for(row.invoice_usd, tolerance_usd, tolerance_pct):
                beyond += 1
            if worst is None or abs(row.variance_usd) > abs(worst[0]):
                worst = (
                    row.variance_usd,
                    row.model,
                    _ZERO if row.variance_pct is None else row.variance_pct,
                )
    rel = (absolute / basis * 100).quantize(_SHARE_QUANTUM) if measured_any and basis > 0 else None
    return ErrorBudget(
        invoices=len(invoices),
        models=models,
        invoice_lines=lines,
        events=len(events),
        reconciled_models=reconciled,
        observed_abs_variance_usd=_quantise(absolute) if measured_any else None,
        observed_net_variance_usd=_quantise(netted) if measured_any else None,
        observed_rel_variance_pct=rel,
        worst_model=worst[1] if worst is not None else None,
        worst_variance_usd=_quantise(worst[0]) if worst is not None else None,
        worst_rel_variance_pct=worst[2] if worst is not None else None,
        tolerance_usd=tolerance_usd,
        tolerance_pct=tolerance_pct,
        rows_beyond_tolerance=beyond,
        note=_BUDGET_NOTE,
    )



# --------------------------------------------------------------------------
# The demo
# --------------------------------------------------------------------------

#: The synthetic statement's period. Fixed, not today's date, for the reason
#: :data:`backstop.ledger.demo.DEMO_DAY` is fixed: a demo whose figures move with
#: the calendar cannot be checked against a note taken last week, and cannot be
#: asserted byte for byte.
DEMO_PERIOD = "2026-09-26"

#: The one event added to the demo corpus so the ``matched`` row has a ledger side
#: at all. A fixed id rather than a generated one, because a demo that invented its
#: own event ids between runs could not be compared byte for byte.
DEMO_MATCHED_EVENT_ID = "0f5b9c4a7d2e1368000000000000beef"
DEMO_MATCHED_INPUT_TOKENS = 8_000
DEMO_MATCHED_OUTPUT_TOKENS = 400

#: 8,000 input tokens at gpt-5.6-sol's bundled $4.00/Mtok and 400 output tokens at
#: $20.00/Mtok is ``0.032000 + 0.008000 = 0.040000`` exactly, at the catalog's six
#: decimal places, with all four components priced.
DEMO_MATCHED_TOTAL_USD = Decimal("0.040000")

#: The attribution the added event carries. Present, so the row is attributable in
#: a charge-back too; reconciliation does not group on it.
DEMO_MATCHED_ATTRIBUTION = Attribution(team="platform", feature="reconcile-demo")


def _demo_provider(model: str) -> str:
    """Which provider a demo model belongs to, from the demo corpus's own naming.

    A reconciliation is per provider — that is how M1 is defined — and
    :class:`Invoice` refuses a statement that mixes two, so the demo builds one
    statement per provider rather than one that lies about both.
    """
    return "anthropic" if model.startswith("claude") else "openai"


@dataclass(frozen=True)
class _DemoStatementRow:
    """One model's worth of deliberate disagreement.

    **Every perturbation is named, fixed and declared here**, so a reader can see
    exactly why each row differs and check the arithmetic by hand. The seven rows
    are chosen to cover the causes this module claims it can tell apart, because a
    demo whose rows all differ for the same reason demonstrates nothing:

    - ``gpt-4o`` — the statement prices a cache write the bundled card does not
      publish, so the ledger charged those tokens at zero. ``docs/ledger.md`` names
      that as a silent under-count; here it is a **price** variance, visible.
    - ``gpt-4.1`` — the statement applies an input rate 10% above the bundled one
      with identical token counts: a stale rate card is a pure **price** variance.
    - ``claude-sonnet-4`` — the statement reports 10,000 more output tokens and bills
      for them: a **count** variance, which the row above is not.
    - ``gpt-5.6-sol`` — the statement bills the ledger's figure exactly, so there
      *is* a ``matched`` row and a reader can tell the tool reports one.
    - ``claude-haiku-4-5`` — absent from the statement: spend Backstop recorded that
      the statement does not bill.
    - ``vendor-preview-2027`` — billed at an amount the catalog cannot price: the
      unpriced row, with the ledger side absent rather than zero.
    - ``claude-opus-5`` — a model the ledger never saw: traffic that did not go
      through a wrapped client.

    ``ledger_side`` records what the ledger holds for the model, because the three
    ways a row can lack a ledger figure need three different sentences and inferring
    them would mislabel at least one.
    """

    model: str
    on_statement: bool = True
    ledger_side: str = "recorded"
    input_rate_per_mtok_usd: Decimal | None = None
    cache_write_rate_per_mtok_usd: Decimal | None = None
    output_token_delta: int = 0
    charged_usd: Decimal | None = None

    @property
    def label(self) -> str:
        if not self.on_statement:
            return "is absent from the statement"
        if self.ledger_side == "unpriced":
            return (
                f"bills {format(self.charged_usd, 'f')} USD, and the price catalog has no "
                "rate for this model, so the ledger's side of the row is absent rather "
                "than zero"
            )
        if self.ledger_side == "silent":
            return (
                f"bills {format(self.charged_usd, 'f')} USD for a model the ledger never "
                "recorded a single event on — traffic that did not go through a wrapped "
                "client"
            )
        if self.cache_write_rate_per_mtok_usd is not None:
            return (
                "prices the cache write at "
                f"{format(self.cache_write_rate_per_mtok_usd, 'f')} USD/Mtok, a rate the "
                "bundled card does not publish, so the ledger charged those tokens at zero"
            )
        if self.input_rate_per_mtok_usd is not None:
            return (
                f"applies an input rate of "
                f"{format(self.input_rate_per_mtok_usd, 'f')} USD/Mtok against the "
                "bundled card's lower one, with identical token counts"
            )
        if self.output_token_delta:
            return (
                f"reports {self.output_token_delta} more output tokens than the ledger "
                "did, and bills for them"
            )
        return "bills the ledger's figure exactly"


#: The statement the demo reconciles. Read it and you know every row before the
#: command prints anything, which is the contract
#: :data:`backstop.ledger.demo._PROFILES` has for the charge-back demo.
DEMO_STATEMENT_ROWS: tuple[_DemoStatementRow, ...] = (
    _DemoStatementRow("gpt-4o", cache_write_rate_per_mtok_usd=Decimal("2.50")),
    _DemoStatementRow("gpt-4.1", input_rate_per_mtok_usd=Decimal("2.20")),
    _DemoStatementRow("claude-sonnet-4-20250514", output_token_delta=10_000),
    _DemoStatementRow("gpt-5.6-sol"),
    _DemoStatementRow("claude-haiku-4-5", on_statement=False),
    _DemoStatementRow("vendor-preview-2027", ledger_side="unpriced", charged_usd=Decimal("0.075000")),
    _DemoStatementRow("claude-opus-5", ledger_side="silent", charged_usd=Decimal("1.240000")),
)


def _demo_matched_event() -> SpendEvent:
    """The single fixed event that gives the ``matched`` row something to match."""
    from dataclasses import replace

    from .demo import _BASE

    event = SpendEvent(
        event_id=DEMO_MATCHED_EVENT_ID,
        occurred_at=_BASE.isoformat(timespec="microseconds") + "Z",
        provider="openai",
        model="gpt-5.6-sol",
        endpoint="/v1/chat/completions",
        priority="default",
        outcome="success",
        input_tokens=DEMO_MATCHED_INPUT_TOKENS,
        output_tokens=DEMO_MATCHED_OUTPUT_TOKENS,
        estimated=False,
        attribution=DEMO_MATCHED_ATTRIBUTION,
    )
    return replace(event, cost=compute_cost(event, PriceCatalog()))


def demo_events() -> tuple[SpendEvent, ...]:
    """The demo's fixed synthetic ledger: the charge-back demo's corpus, plus one
    fixed event on a model the synthetic statement bills exactly.

    Deterministic to the event, exactly as
    :func:`backstop.ledger.demo.demo_events` is and for the same reasons: no clock,
    no file, no key, no network, and every price from the bundled rate card. The
    one added event exists so the reconciliation can show a ``matched`` row —
    without it every row would differ, and a reader could not tell "the tool reports
    a match" from "the tool only ever reports differences".
    """
    from .demo import demo_events as chargeback_demo_events

    return (*chargeback_demo_events(), _demo_matched_event())


def _demo_ledger_totals(
    events: Sequence[SpendEvent], catalog: PriceCatalog
) -> dict[str, tuple[Decimal, int, int, int, int]]:
    """Per-model ``(total_usd, input, output, cache_read, cache_write)`` for the demo.

    ``total_usd`` is the ledger's own sum of per-request amounts — including the
    unpriced models, at zero, which is exactly the point: the ledger charged
    ``vendor-preview-2027`` nothing because it could not price it.
    """
    totals: dict[str, tuple[Decimal, int, int, int, int]] = {}
    for event in events:
        amount, _ = _ledger_amount(event, catalog)
        counted = amount if amount is not None else _ZERO
        previous = totals.get(event.model)
        if previous is None:
            totals[event.model] = (
                counted,
                event.input_tokens,
                event.output_tokens,
                event.cache_read_tokens,
                event.cache_write_tokens,
            )
        else:
            totals[event.model] = (
                previous[0] + counted,
                previous[1] + event.input_tokens,
                previous[2] + event.output_tokens,
                previous[3] + event.cache_read_tokens,
                previous[4] + event.cache_write_tokens,
            )
    return totals


def _demo_statement_line(
    row: _DemoStatementRow, catalog: PriceCatalog, totals: dict[str, Any]
) -> InvoiceLine | None:
    """One statement line: the ledger's own aggregates under the declared offset.

    The charged amount is **the ledger's own figure plus the declared offset**, not
    a fresh recomputation. That is deliberate and it is the only way the demo's
    arithmetic is checkable: a statement line re-priced from aggregate token counts
    would differ from the ledger's sum of per-request roundings by a microdollar
    residue, and a reader recomputing the offset by hand would not get the number
    the table prints. The offset itself is declared in
    :data:`DEMO_STATEMENT_ROWS` and is exact.
    """
    if not row.on_statement:
        return None
    provider = _demo_provider(row.model)
    entry = catalog.resolve(provider, row.model)
    ledger_total, fresh, output, cached, written = totals.get(
        row.model, (_ZERO, 0, 0, 0, 0)
    )
    if row.charged_usd is not None:
        return InvoiceLine(
            provider=provider,
            model=row.model,
            period=DEMO_PERIOD,
            token_categories=_demo_categories(provider, fresh, output, cached, written),
            charged_usd=row.charged_usd,
        )
    if entry is None:
        # A model the catalog cannot price and a statement figure for: the two
        # fixed ``charged_usd`` rows above are this case, and reaching here would
        # mean one of them lost its amount.
        raise AssertionError(
            f"the demo statement row for {row.model!r} has neither a stated amount nor a "
            "price to derive one from"
        )
    offset = _ZERO
    if row.input_rate_per_mtok_usd is not None:
        offset += Decimal(fresh) * (row.input_rate_per_mtok_usd - entry.input_per_mtok_usd) / _MTOK
    if row.cache_write_rate_per_mtok_usd is not None:
        # The bundled card publishes no cache-write rate for this model, so the
        # ledger charged these tokens zero and the whole offset is new money.
        offset += Decimal(written) * row.cache_write_rate_per_mtok_usd / _MTOK
    if row.output_token_delta:
        offset += Decimal(row.output_token_delta) * entry.output_per_mtok_usd / _MTOK
    return InvoiceLine(
        provider=provider,
        model=row.model,
        period=DEMO_PERIOD,
        token_categories=_demo_categories(
            provider, fresh, output + row.output_token_delta, cached, written
        ),
        charged_usd=_quantise(ledger_total + offset),
    )


def _demo_categories(
    provider: str, fresh: int, output: int, cached: int, written: int
) -> dict[str, int]:
    """A statement line's categories, in **the provider's own spelling**.

    The two shapes are not cosmetic. OpenAI's ``input_tokens`` counts the cached
    tokens *inside* it, so the demo writes the inclusive count plus the cached
    count and lets the normaliser subtract — which is the asymmetry
    ``docs/planning/03-attribution-and-schema.md`` Part 4.5 calls the single most
    expensive correctness issue in the ledger half. Anthropic's ``input_tokens`` is
    the opposite convention under the very same name, so the anthropic lines write
    ``uncached_input_tokens`` and the cached figures beside it.

    The anthropic cache write goes entirely into the **5-minute** column, because
    that is the tier the bundled rate card bills; a 1-hour write is the known
    under-count ``docs/ledger.md`` documents, and pretending the statement split it
    would overstate what this demo knows.
    """
    if provider == "anthropic":
        return {
            "uncached_input_tokens": fresh,
            "output_tokens": output,
            "cache_read_input_tokens": cached,
            "cache_creation_5m_input_tokens": written,
        }
    return {
        "input_tokens": fresh + cached,
        "input_cached_tokens": cached,
        "input_cache_write_tokens": written,
        "output_tokens": output,
    }


@_exact
def demo_invoice(
    events: Sequence[SpendEvent] | None = None, catalog: PriceCatalog | None = None
) -> tuple[Invoice, ...]:
    """Build the demo's fixed synthetic statements — **one per provider**.

    Returned as a tuple because a reconciliation is per provider (that is how M1 is
    defined) and :class:`Invoice` refuses a statement whose lines disagree about
    which vendor they are. Reconciling OpenAI's statement against Anthropic's events
    would report three models as unbilled that are simply billed on the other
    statement, which is a false variance and the worst kind.

    Offline, keyless and deterministic: the token counts come from the fixed corpus
    and the money is the ledger's own figure plus a declared offset, so the same
    inputs give the same statement on every machine and every run.
    """
    corpus = tuple(events) if events is not None else demo_events()
    prices = catalog if catalog is not None else PriceCatalog()
    totals = _demo_ledger_totals(corpus, prices)
    by_provider: dict[str, list[InvoiceLine]] = {}
    for row in DEMO_STATEMENT_ROWS:
        line = _demo_statement_line(row, prices, totals)
        if line is not None:
            by_provider.setdefault(line.provider, []).append(line)
    return tuple(
        Invoice(
            provider=provider,
            period=DEMO_PERIOD,
            source=f"synthetic statement, {provider} ({DEMO_PERIOD})",
            lines=tuple(by_provider[provider]),
        )
        for provider in sorted(by_provider)
    )


@dataclass(frozen=True)
class DemoResult:
    """What the demo reconciled: one report and one measured budget per provider.

    A plain data record holding the real :class:`InvoiceVariance` and
    :class:`ErrorBudget` objects rather than flattened copies, so the markdown and
    the JSON are two views of one computation and cannot disagree about a number.
    ``simulated``, ``network_calls`` and ``deterministic`` are fields rather than
    prose printed around the table, so a reader of the JSON alone still knows what
    is real.
    """

    period: str
    variances: tuple[InvoiceVariance, ...]
    budgets: tuple[ErrorBudget, ...]
    rows: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "reconciliations": [variance.to_dict() for variance in self.variances],
            "error_budgets": [budget.to_dict() for budget in self.budgets],
            "declared_disagreements": [list(pair) for pair in self.rows],
            "scope": RECONCILIATION_SCOPE,
            "simulated": True,
            "network_calls": 0,
            "deterministic": True,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_markdown(self) -> str:
        """The whole demo on one screen: what was faked, what was computed, what
        the reader must not conclude from it.

        The order is the argument: what this is, what it is **not**, the
        disagreements declared in advance, the tables, the measured budget, and the
        limits.
        """
        declared = "\n".join(f"| `{model}` | {label} |" for model, label in self.rows)
        reports = "\n\n".join(variance.to_markdown() for variance in self.variances)
        budgets = "\n\n".join(budget.to_markdown() for budget in self.budgets)
        counted = ", ".join(
            f"**{variance.reconciled_models} of {variance.models_count}** on "
            f"`{variance.provider}`"
            for variance in self.variances
        )
        return "\n".join(
            [
                "# Backstop Reconciliation — a ledger against a statement file",
                "",
                "**What this is.** A priced ledger reconciled against a *synthetic* "
                "statement, built by this module from the ledger's own token counts. "
                "Both inputs are fixed and offline: no API key, no network, no file on "
                "disk, and the same bytes on every run.",
                "",
                "**What this is not.** It is **not** a reconciliation against a real "
                "provider invoice. This repository has never run one: neither real-provider "
                "smoke test is wired to a statement, and no statement file from either "
                "provider is committed here. The column names the parsers read are "
                "transcribed from the providers' published reporting surfaces, are "
                "centralised in one marked block for exactly that reason, and are marked "
                "as needing verification against a real statement.",
                "",
                "## The statement disagrees on purpose, and here is how",
                "",
                "A demo where everything reconciles teaches a reader nothing about what "
                "the tool is for, so every row below differs, and each difference is "
                "declared before the numbers are printed:",
                "",
                "| model | what the synthetic statement does |",
                "| --- | --- |",
                declared,
                "",
                "One statement is built **per provider** and each is reconciled against "
                "that provider's events only. M1 is defined per provider per month, and "
                "reconciling one vendor's statement against the other's traffic would "
                "report three models as unbilled that are simply billed on the other "
                "statement — a false variance, which is the worst kind.",
                "",
                reports,
                "",
                budgets,
                "",
                "## Read the counts first",
                "",
                f"Every table above is only meaningful next to its inputs. Rows that "
                f"reconciled exactly: {counted}. The full input counts — events in, "
                "statement lines in, rows matched — are on each report and in the JSON, "
                "because an empty reconciliation and a clean one produce a zero variance "
                "for completely different reasons and the difference is invisible in the "
                "money alone.",
                "",
                "## What a reader cannot conclude from this",
                "",
                "- **It is not a real invoice.** Every dollar above was chosen by this "
                "module. A real reconciliation's variance is a property of a real statement "
                "and a real rate card, and the gap between the two is precisely what this "
                "demo cannot demonstrate.",
                "- **The error budget is measured over this population only.** A synthetic "
                "statement over a synthetic day, on a bundled rate card dated "
                f"`{BUNDLED_EFFECTIVE_FROM}`, with no streaming, no unwrapped client and "
                "one deliberately unpriced model. It is not a promise about any other "
                "account, and not a promise about this one.",
                "- **The provider field names are unverified.** Correcting one against a "
                "real statement is a change to `OPENAI_STATEMENT_FIELDS` or "
                "`ANTHROPIC_STATEMENT_FIELDS`, not to this logic.",
            ]
        )


@_exact
def run_demo(
    events: Sequence[SpendEvent] | None = None, catalog: PriceCatalog | None = None
) -> DemoResult:
    """Reconcile the demo corpus against the demo statements, offline and keyless.

    Each provider's events are reconciled against that provider's statement and
    budgeted separately, which is the per-provider shape M1 is defined in. Purity:
    the same corpus and the same statements give the same report on every machine
    and every run, which is what makes ``backstop reconcile --demo`` safe to put in
    a slide. No clock, no file, no network, no key.
    """
    corpus = tuple(events) if events is not None else demo_events()
    prices = catalog if catalog is not None else PriceCatalog()
    invoices = demo_invoice(corpus, prices)
    variances: list[InvoiceVariance] = []
    budgets: list[ErrorBudget] = []
    for invoice in invoices:
        own = tuple(event for event in corpus if event.provider == invoice.provider)
        variances.append(reconcile_invoice(own, invoice, prices))
        budgets.append(measure_error_budget(own, (invoice,), prices))
    return DemoResult(
        period=DEMO_PERIOD,
        variances=tuple(variances),
        budgets=tuple(budgets),
        rows=tuple((row.model, row.label) for row in DEMO_STATEMENT_ROWS),
    )
