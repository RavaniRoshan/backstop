"""Join a provider's two exports into one statement that can be reconciled.

Both providers publish money and tokens from **separate endpoints**, and both
dashboards offer two separate downloads. Neither file holds both halves, so a
single-file statement — which is what ``reconcile_invoice`` consumes — does not
correspond to anything either provider actually publishes. That was the finding
in ``docs/ledger-statement-calibration.md``, and this module is the answer to
it: read both exports, join them, and hand the reconciler the thing it needs.

The join is where the two halves can disagree, so every disagreement is
surfaced rather than resolved:

- a cost row with no matching usage row is kept, as a line with tokens it does
  not have, and the reconciliation reports it as billed-but-unrecorded
- a usage row with no cost row is kept, with a charge of ``None``, so it reads
  as "recorded but not billed" instead of as free
- a period present in one export and not the other is named in the result

Where the join is *possible* differs by provider, and the difference is not an
implementation detail:

- **OpenAI** can be joined per model. Its cost export carries ``line_item``,
  which for token charges is the model, and both exports carry the same unix
  ``start_time``. So the key is (day, line_item) and every line reconciles
  against a model-specific charge.
- **Anthropic** may not be joinable per model at all. Its cost report is
  documented as carrying an amount and a currency, with a ``cost_type``
  (``tokens``, ``web_search``, ``code_execution``, ``session_usage``) rather than
  a model, and at least one integration vendor reports the table as having no
  model dimension whatsoever. So Anthropic joins at **account level** by
  default, which reconciles the total and cannot attribute it to a model. That
  is a limit of the provider's export, not of this code, and
  :func:`join_statement_files` says which level it achieved on the result.

Money is :class:`~decimal.Decimal` throughout, as everywhere else in this
package, and a cost that cannot be attributed is never spread across models to
make the join succeed.
"""
from __future__ import annotations

import csv
import datetime as _dt
import os
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from .reconcile import (
    Invoice,
    InvoiceLine,
)

OPENAI = "openai"
ANTHROPIC = "anthropic"

#: Anthropic's cost categories. Only ``tokens`` is reconcilable against token
#: counts; the rest are charges with no tokens behind them, and are carried
#: through with their own ``cost_type`` so a reader can see why a charge has no
#: counts to compare it to.
ANTHROPIC_TOKEN_COST = "tokens"

_ANTHROPIC_CACHE_5M = "cache_creation_5m_input_tokens"
_ANTHROPIC_CACHE_1H = "cache_creation_1h_input_tokens"


@dataclass(frozen=True)
class UsageRow:
    """One row of a provider's *usage* export: tokens, by period and model."""

    provider: str
    period: str
    model: str
    categories: Mapping[str, int]
    requests: int | None = None


@dataclass(frozen=True)
class CostRow:
    """One row of a provider's *cost* export: money, keyed by whatever it has.

    ``key`` is the model for OpenAI (its ``line_item``) and the cost category for
    Anthropic (its ``cost_type``), because that is what each provider actually
    publishes. It is called ``key`` rather than ``model`` because for Anthropic it
    is not one.
    """

    provider: str
    period: str
    key: str
    amount_usd: Decimal
    cost_type: str = ANTHROPIC_TOKEN_COST


@dataclass
class JoinResult:
    """The joined statement, plus what the join could and could not line up."""

    invoice: Invoice
    #: (period, key) present in the cost export with no usage row behind it.
    billed_without_usage: tuple[tuple[str, str], ...] = ()
    #: (period, key) present in the usage export with no cost row behind it.
    recorded_without_bill: tuple[tuple[str, str], ...] = ()
    #: "model" when every line reconciles against a model-specific charge,
    #: "account" when the provider's export only supports the total.
    level: str = "model"
    notes: tuple[str, ...] = ()

    def caveats(self) -> tuple[str, ...]:
        """What a reader must know before quoting a figure from this join."""
        out = list(self.notes)
        if self.billed_without_usage:
            out.append(
                f"{len(self.billed_without_usage)} charged period(s) had no matching "
                "usage rows -- billed activity the usage export does not describe "
                "(non-token charges, or a different granularity). Not netted away."
            )
        if self.recorded_without_bill:
            out.append(
                f"{len(self.recorded_without_bill)} recorded period(s) had no matching "
                "cost row -- present as tokens with no charge to compare against, "
                "which reads as 'not billed' rather than as free."
            )
        if self.level == "account":
            out.append(
                "This provider's cost export carries no model dimension, so the join "
                "reconciles the account total only. Per-model attribution is not "
                "available from this export and has not been faked."
            )
        return tuple(out)


# --- field reading -----------------------------------------------------------

#: The columns each provider's usage export is read from, most-canonical first.
#: Taken from the providers' own documentation; see
#: ``docs/ledger-statement-calibration.md`` for the sources and the date checked.
USAGE_COLUMNS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    OPENAI: {
        "model": ("model",),
        "input": ("input_tokens",),
        "output": ("output_tokens",),
        "cache_read": ("input_cached_tokens", "cached_tokens"),
        "requests": ("num_model_requests",),
    },
    ANTHROPIC: {
        "model": ("model",),
        "input": ("uncached_input_tokens",),
        "output": ("output_tokens",),
        "cache_read": ("cache_read_input_tokens",),
        "cache_write_5m": (_ANTHROPIC_CACHE_5M,),
        "cache_write_1h": (_ANTHROPIC_CACHE_1H,),
        "requests": ("request_count",),
    },
}

#: And each provider's cost export. ``amount`` is deliberately absent for
#: Anthropic: its units are contested between minor-units and USD across
#: sources, and a 100x error is not worth guessing at. See the calibration doc.
COST_COLUMNS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    OPENAI: {
        "amount": ("amount_value",),
        "key": ("line_item",),
        "cost_type": ("cost_type",),
    },
    ANTHROPIC: {
        # Read only when the column says USD, which is the same refusal
        # reconcile.py makes and for the same reason.
        "amount": ("amount_usd", "cost_usd", "total_cost_usd"),
        "key": ("cost_type",),
        "cost_type": ("cost_type",),
    },
}

_PERIOD_NUMERIC = ("start_time", "bucket_start", "starting_at", "date", "day")
_CURRENCY = ("currency",)


def _pick(row: Mapping[str, str], names: Sequence[str]) -> str | None:
    for name in names:
        if name in row and str(row[name]).strip() != "":
            return str(row[name]).strip()
    return None


def _period(row: Mapping[str, str]) -> str:
    """The row's day, as an ISO date.

    OpenAI's exports carry unix seconds; Anthropic's carry ISO timestamps. Both
    are reduced to a calendar day in UTC, because that is the granularity both
    providers' cost exports bucket to and therefore the only key a join on
    (period, line_item) can be sound.
    """
    raw = _pick(row, _PERIOD_NUMERIC)
    if raw is None:
        raise ValueError(
            f"no period column in a usage or cost row; looked for {list(_PERIOD_NUMERIC)}, "
            f"got {sorted(row)}"
        )
    if raw.isdigit() and len(raw) >= 9:
        return (
            _dt.datetime.fromtimestamp(int(raw), tz=_dt.timezone.utc)
            .date()
            .isoformat()
        )
    try:
        return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise ValueError(
            f"cannot read {raw!r} as a period; it is neither unix seconds nor an "
            f"ISO timestamp ({exc})"
        ) from exc


def _int(row: Mapping[str, str], names: Sequence[str]) -> int:
    raw = _pick(row, names)
    if raw is None:
        return 0
    try:
        return int(float(raw))
    except ValueError as exc:
        raise ValueError(f"token count {raw!r} is not an integer ({exc})") from exc


def _read_rows(path: str | os.PathLike[str]) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return [dict(r) for r in csv.DictReader(handle)]


def read_usage_export(
    path: str | os.PathLike[str], provider: str
) -> tuple[UsageRow, ...]:
    """Read a provider's usage export into normalised token rows."""
    if provider not in USAGE_COLUMNS:
        raise ValueError(f"no usage-export columns known for provider {provider!r}")
    cols = USAGE_COLUMNS[provider]
    out: list[UsageRow] = []
    for index, row in enumerate(_read_rows(path)):
        model = _pick(row, cols["model"])
        if model is None:
            raise ValueError(
                f"usage row {index} of {os.fspath(path)!r} has no model column; "
                f"looked for {list(cols['model'])}"
            )
        categories = {
            logical: _int(row, cols[logical])
            for logical in cols
            if logical not in ("model", "requests") and logical in cols
        }
        out.append(
            UsageRow(
                provider=provider,
                period=_period(row),
                model=model,
                categories={k: v for k, v in categories.items() if v},
                requests=_int(row, cols["requests"]) if "requests" in cols else None,
            )
        )
    return tuple(out)


def read_cost_export(
    path: str | os.PathLike[str], provider: str
) -> tuple[CostRow, ...]:
    """Read a provider's cost export into normalised money rows.

    The currency column is checked where the file carries one, and a row in a
    currency other than USD is refused rather than summed: adding two currencies
    produces a number that is money in neither.
    """
    if provider not in COST_COLUMNS:
        raise ValueError(f"no cost-export columns known for provider {provider!r}")
    cols = COST_COLUMNS[provider]
    out: list[CostRow] = []
    for index, row in enumerate(_read_rows(path)):
        raw_amount = _pick(row, cols["amount"])
        if raw_amount is None:
            raise ValueError(
                f"cost row {index} of {os.fspath(path)!r} has no amount column this "
                f"module will read; looked for {list(cols['amount'])}. A bare "
                f"'amount' is refused because its units are contested across the "
                f"provider's own sources -- see docs/ledger-statement-calibration.md."
            )
        currency = (_pick(row, _CURRENCY) or "usd").lower()
        if currency not in ("usd", "$"):
            raise ValueError(
                f"cost row {index} of {os.fspath(path)!r} is in {currency!r}, not USD; "
                "a statement in another currency cannot be added to a USD ledger"
            )
        key = _pick(row, cols["key"]) or "(unattributed)"
        out.append(
            CostRow(
                provider=provider,
                period=_period(row),
                key=key,
                amount_usd=Decimal(raw_amount),
                cost_type=_pick(row, cols["cost_type"]) or ANTHROPIC_TOKEN_COST,
            )
        )
    return tuple(out)


# --- the join ----------------------------------------------------------------


def join_statement(
    usage: Sequence[UsageRow],
    cost: Sequence[CostRow],
    *,
    period: str | None = None,
) -> JoinResult:
    """Join usage and cost rows into one :class:`Invoice`.

    Joins on ``(period, key)`` where ``key`` is the model for OpenAI. For
    Anthropic the cost export's key is a *cost category* rather than a model, so
    the join falls back to the account total for that period and says so on the
    result, because a provider that does not publish the dimension cannot have it
    reconstructed honestly.
    """
    if not usage and not cost:
        raise ValueError("nothing to join: both the usage and the cost export are empty")
    providers = {r.provider for r in (*usage, *cost)}
    if len(providers) > 1:
        raise ValueError(
            f"the two exports are from different providers ({sorted(providers)}); "
            "one vendor's money must not be joined to another vendor's tokens"
        )
    provider = providers.pop()

    usage_by_key: dict[tuple[str, str], dict[str, int]] = defaultdict(dict)
    for row in usage:
        if period and row.period != period:
            continue
        bucket = usage_by_key[(row.period, row.model)]
        for logical, count in row.categories.items():
            bucket[logical] = bucket.get(logical, 0) + count

    cost_by_key: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    cost_types: dict[tuple[str, str], str] = {}
    for row in cost:
        if period and row.period != period:
            continue
        k = (row.period, row.key)
        cost_by_key[k] += row.amount_usd
        cost_types[k] = row.cost_type

    # Does the cost export's key name models at all? OpenAI's line_item does;
    # Anthropic's cost_type does not, and those are different worlds.
    usage_keys = {key for _, key in usage_by_key}
    model_level = provider == OPENAI or bool(
        cost_by_key and all(key in usage_keys for key in cost_by_key)
    )

    lines: list[InvoiceLine] = []
    billed_without: list[tuple[str, str]] = []
    recorded_without: list[tuple[str, str]] = []

    for key in sorted(set(usage_by_key) | set(cost_by_key)):
        row_period, model = key
        categories = usage_by_key.get(key)
        amount = cost_by_key.get(key)
        if model_level:
            if categories is None:
                billed_without.append(key)
                amount_value, cats = amount, {}
            elif amount is None:
                recorded_without.append(key)
                amount_value, cats = None, categories
            else:
                amount_value, cats = amount, categories
        else:
            # Account level: one line per period, tokens summed across models.
            cats = {
                logical: sum(
                    value.get(logical, 0) for (p, _), value in usage_by_key.items() if p == row_period
                )
                for logical in {
                    logical
                    for value in usage_by_key.values()
                    for logical in value
                }
            }
            amount_value = amount
            model = "(all models)"

        if not cats and amount_value is None:
            continue
        lines.append(
            InvoiceLine(
                provider=provider,
                model=model,
                period=row_period,
                token_categories={k2: v for k2, v in sorted(cats.items()) if v},
                # A charge we do not have stays None. Zero would say "free", and
                # that is a different claim from "not in the export".
                charged_usd=amount_value if amount_value is not None else Decimal(0),
                cost_type=cost_types.get(key, ANTHROPIC_TOKEN_COST),
            )
        )

    if not lines:
        raise ValueError(
            "the join produced no lines: the usage and cost exports have no period "
            "in common. Check that both cover the same month, and note that "
            "OpenAI invoices a calendar month in the month after it."
        )

    periods = sorted({line.period for line in lines})
    notes: list[str] = []
    if len(periods) > 1:
        notes.append(
            f"joined {len(periods)} periods ({periods[0]} to {periods[-1]}); pass "
            "period= to reconcile one month at a time"
        )
    return JoinResult(
        invoice=Invoice(
            provider=provider,
            period=period or periods[0],
            source=(
                f"joined usage+cost exports, {len(usage)} usage row(s) and "
                f"{len(cost)} cost row(s)"
            ),
            lines=tuple(lines),
        ),
        billed_without_usage=tuple(billed_without),
        recorded_without_bill=tuple(recorded_without),
        level="model" if model_level else "account",
        notes=tuple(notes),
    )


def join_statement_files(
    usage_path: str | os.PathLike[str],
    cost_path: str | os.PathLike[str],
    *,
    provider: str | None = None,
    period: str | None = None,
) -> JoinResult:
    """Read both of a provider's exports and join them in one call."""
    resolved = provider or _sniff(usage_path) or _sniff(cost_path)
    if resolved is None:
        raise ValueError(
            "cannot tell which provider these exports are from; pass provider= "
            f"explicitly. Known: {sorted(USAGE_COLUMNS)}"
        )
    return join_statement(
        read_usage_export(usage_path, resolved),
        read_cost_export(cost_path, resolved),
        period=period,
    )


#: The columns that actually tell the two providers apart. `model` does not --
#: both have it -- and neither does `output_tokens`, which is also common to both.
#: The first version of this sniff matched on `model` plus any of input/output,
#: which classified an Anthropic usage export as OpenAI because they both carry
#: `output_tokens`. The cache category names are the discriminating ones, and are
#: the same discriminator reconcile.py's own provider detection uses.
_DISCRIMINATORS: Mapping[str, frozenset[str]] = {
    OPENAI: frozenset({
        "input_cached_tokens", "input_uncached_tokens", "input_cache_write_tokens",
        "cached_tokens",
    }),
    ANTHROPIC: frozenset({
        "uncached_input_tokens", "cache_read_input_tokens",
        _ANTHROPIC_CACHE_5M, _ANTHROPIC_CACHE_1H, "cache_creation_input_tokens",
    }),
}


def _sniff(path: str | os.PathLike[str]) -> str | None:
    """Guess the provider from the export's own column names."""
    try:
        header = set(_read_rows(path)[0])
    except (OSError, IndexError, KeyError):
        return None
    matched = [p for p, keys in _DISCRIMINATORS.items() if header & keys]
    if len(matched) == 1:
        return matched[0]
    if not matched:
        for provider, cols in USAGE_COLUMNS.items():
            if header & set(cols["model"]):
                # A usage export with no cache column at all: fall back to the
                # input-token name, which does differ between the two.
                other = ANTHROPIC if provider == OPENAI else OPENAI
                return provider if not (header & set(USAGE_COLUMNS[other]["input"])) else None
    for provider, cols in COST_COLUMNS.items():
        if header & set(cols["amount"]):
            return provider
    return None
