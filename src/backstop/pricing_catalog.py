"""The ledger's authoritative price source: a bundled table, a user catalog, and
exact decimal cost arithmetic.

Two pricing modules ship in this repository and they are **not**
interchangeable:

- :mod:`backstop.pricing` is the demo's rough estimator. It is float-based, it
  falls back to "the cheapest model in the family" when a model is unknown, and
  it refreshes itself from ``~/.cache/backstop/pricing.json`` or from a URL. A
  number from it is an estimate, which is what :func:`backstop.cost.estimate`
  wants and what ``backstop demo`` prints.
- This module is the ledger's *priced* source. It is
  :class:`decimal.Decimal` end to end, it never substitutes a default, and it
  never touches the network or reads a file except through an explicit
  :meth:`PriceCatalog.from_file` call. An unknown model yields ``None``, which
  the ledger records as an unpriced event, because a charge-back figure that is
  quietly wrong is worse than one that is absent.

Import cost
-----------

Importing this module reads no data file and reaches no network. The bundled
table is a literal built from module-level constants: no file read, no
``os.environ`` lookup, no ``socket``. The only paths an import touches are this
module's own bytecode and the standard library's, which the import machinery
must read either way. ``tests/test_pricing_catalog.py`` proves it in two
subprocesses: one with ``socket.socket`` replaced by a raiser, one with an audit
hook that records every file opened.

Money
-----

Every amount is a :class:`~decimal.Decimal` quantised to exactly
:data:`MONEY_PLACES` decimal places with ``ROUND_HALF_UP``. A binary float never
touches a price, an amount, or a wire form: on the wire money is a *string*, so
a JSON reader cannot reinterpret a charge as a float and lose the cents.

The arithmetic runs under this module's own :data:`LEDGER_CONTEXT` rather than
the decimal context the host process happens to have installed, because a
``decimal`` context is **process-global** and a library cannot ask the host to
leave it alone. Accounting code that tightens ``prec`` to tidy up a
float-heavy application would otherwise void every cost computed here — the
request still succeeds, the ledger records nothing, and every total is wrong by
a rounding step nobody asked for. So the guarantee is unconditional: the same
inputs give the same breakdown whatever the ambient ``prec``, ``rounding``,
``traps`` or ``Emax`` are, because none of them are read.

Precedence
----------

Highest wins:

1. explicit per-call ``price_overrides`` passed to :func:`compute_cost`
2. the user-supplied catalog file (:meth:`PriceCatalog.from_file`,
   ``source="user"``)
3. :data:`BUNDLED_PRICES` (``source="bundled"``)

Each layer is searched in full, across every model-name normalisation tier,
before the next layer is consulted at all: a user price for ``gpt-4o`` beats a
bundled price for the exact string ``gpt-4o-2024-08-06``, because the user's
layer is the higher one.

Missing prices
--------------

A missing price is visible, never filled. :func:`compute_cost` returns ``None`
and its caller increments a ``price_unknown`` counter; it never falls back to a
neighbouring model, a family average, or a default. A model that publishes an
input and output price but no cache price is a second, quieter case: the cache
components are charged at zero and
:attr:`CostBreakdown.priced_components` records that they were not priced, so
an export can report the gap instead of presenting a zero as a measurement.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import (
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from functools import lru_cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ledger.schema import SpendEvent

#: Deliberately not in ``__all__``: this module's four exported names are its
#: API, and its constants — :data:`COST_COMPONENTS`, :data:`CURRENCY`,
#: :data:`MONEY_PLACES`, :data:`BUNDLED_PRICES` — have always been public by name
#: without being re-exported. :data:`LEDGER_CONTEXT` is public the same way:
#: :mod:`backstop.ledger.export` imports it, because the charge-back has to total
#: money under the same context the catalog priced it in.
__all__ = ["CostBreakdown", "PriceCatalog", "PriceEntry", "compute_cost"]

#: The only currency a breakdown is denominated in. A future non-USD breakdown
#: has to add a field rather than reinterpret this one.
CURRENCY = "USD"

#: Decimal places every money value is quantised to.
MONEY_PLACES = 6

#: Significant digits the ledger's money arithmetic runs at. 28 is CPython's own
#: default, chosen here so that the answers are the ones every existing figure in
#: this repository was computed at: holding the ambient context fixed changes
#: *when* the arithmetic is immune to the host, never *what* it produces.
#: Six decimal places of money needs 8 digits to be exact, and the widest single
#: operand here is a token count times a three-figure rate, so 28 leaves more
#: than an order of magnitude of headroom over any count a request can carry.
MONEY_PRECISION = 28

#: The context every cost is computed in, named in full rather than built from
#: :data:`decimal.DefaultContext`, because ``Context(...)`` copies any field left
#: unspecified from the default context — and the whole point of this object is
#: that a host which tightened *that* cannot reach the arithmetic either.
#: ``flags=[]`` starts with no sticky condition recorded, and ``traps`` is the
#: default set spelled out: an inexact, invalid or overflowing price is an error
#: here rather than a quietly rounded dollar.
LEDGER_CONTEXT = Context(
    prec=MONEY_PRECISION,
    rounding=ROUND_HALF_UP,
    Emin=-999_999,
    Emax=999_999,
    capitals=1,
    clamp=0,
    flags=[],
    traps=[InvalidOperation, DivisionByZero, Overflow],
)

_QUANTUM = Decimal("0.000001")
_ZERO = Decimal("0.000000")
_MTOK = Decimal(1_000_000)

#: Where a :class:`PriceEntry`'s prices came from. ``"bundled"`` ships in this
#: module, ``"user"`` came from a caller: a catalog file or a per-call override.
SOURCES: tuple[str, ...] = ("bundled", "user")

#: How much the price is known to be worth. ``"list"`` is a published rate card;
#: ``"negotiated"`` is a rate somebody agreed to, so it is not on any public
#: page and cannot be checked by a reader.
CONFIDENCES: tuple[str, ...] = ("list", "negotiated")

#: What a :class:`CostBreakdown` records as the provenance of the price it used.
#: One more than :data:`SOURCES` because a per-call override is worth telling
#: apart from a catalog file: it is the price for this request, not the price
#: the deployment agreed to.
PRICE_SOURCES: tuple[str, ...] = ("override", "user", "bundled")

#: The four billable components, in the order they appear on a breakdown.
COST_COMPONENTS: tuple[str, ...] = ("input", "output", "cache_read", "cache_write")

_RATE_FIELDS: dict[str, str] = {
    "input": "input_per_mtok_usd",
    "output": "output_per_mtok_usd",
    "cache_read": "cache_read_per_mtok_usd",
    "cache_write": "cache_write_per_mtok_usd",
}
_TOKEN_FIELDS: dict[str, str] = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cache_read_tokens",
    "cache_write": "cache_write_tokens",
}
_MONEY_FIELDS: dict[str, str] = {
    "input": "input_usd",
    "output": "output_usd",
    "cache_read": "cache_read_usd",
    "cache_write": "cache_write_usd",
}

#: An ``effective_from`` is a plain ISO calendar date, checked against this and
#: against :func:`datetime.date.fromisoformat` so a day that does not exist is
#: refused. The pattern rather than the parser alone because
#: ``date.fromisoformat`` accepts more shapes on 3.11+ than on 3.10, and this
#: module supports both.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: A trailing date stamp or ``-latest`` marker. OpenAI writes ``-2024-08-06``,
#: Anthropic writes ``-20241022``, and both write ``-latest``. All three name a
#: snapshot or an alias rather than a different price card, so all three are
#: stripped before the alias map is consulted.
_SNAPSHOT_SUFFIX_RE = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{8}|latest)$")

#: Names a provider or a caller uses for a model the catalog keys differently.
#: Consulted only after every suffix-stripped form of the requested name has
#: been tried, so this is the last resort rather than a shortcut.
MODEL_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        # Anthropic's undated family names, which the catalog keys by their
        # launch snapshot because that is the only unambiguous spelling.
        "claude-opus-4": "claude-opus-4-20250514",
        "claude-sonnet-4": "claude-sonnet-4-20250514",
        "claude-haiku-4": "claude-haiku-4-20250514",
        "claude-3-opus": "claude-3-opus-20240229",
        "claude-3-sonnet": "claude-3-sonnet-20240229",
        "claude-3-haiku": "claude-3-haiku-20240307",
        "claude-3-5-sonnet": "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku": "claude-3-5-haiku-20241022",
        # The dotted spelling of the Claude 3.5 generation, which appears in
        # enough blog posts and config files to be worth accepting.
        "claude-3.5-sonnet": "claude-3-5-sonnet-20241022",
        "claude-3.5-haiku": "claude-3-5-haiku-20241022",
    }
)

#: The date the bundled rates below were transcribed from the providers'
#: published price pages. It is a snapshot date, not a claim that a price has
#: not changed since: a deployment that needs a fresher or a negotiated rate
#: writes a catalog file (:meth:`PriceCatalog.from_file`) or passes a per-call
#: override, and both outrank this table.
BUNDLED_EFFECTIVE_FROM = "2026-09-26"

# model, provider, input, output, cache read, cache write -- all USD per 1M tokens.
#
# Transcribed 2026-09-26 from the published rate cards:
# https://developers.openai.com/api/docs/pricing (Standard processing, short
# context, not Batch and not Fast mode) and
# https://platform.claude.com/docs/en/about-claude/pricing (standard API).
# Only published figures appear. Where a provider publishes no rate for a
# component, the column is ``None`` rather than a carried-forward number: a
# blank says "not priced", a zero would say "free".
#
# Cache write is Anthropic's 5-minute write (1.25x base input), the default
# prompt-cache TTL. OpenAI lists a cache-write rate only for the gpt-6 and
# gpt-5.6 families, so every other OpenAI row leaves it unpriced.
_BUNDLED_ROWS: tuple[tuple[str, str, str, str, str | None, str | None], ...] = (
    # --- OpenAI, current ---
    ("gpt-6-astra", "openai", "10.00", "50.00", "1.00", "12.50"),
    ("gpt-6-sol", "openai", "2.00", "10.00", "0.20", "2.50"),
    ("gpt-6-luna", "openai", "0.10", "0.50", "0.01", "0.125"),
    ("gpt-5.6-sol", "openai", "4.00", "20.00", "0.40", "5.00"),
    ("gpt-5.6-terra", "openai", "2.00", "12.00", "0.20", "2.50"),
    ("gpt-5.6-luna", "openai", "0.20", "1.20", "0.02", "0.25"),
    ("gpt-5.5", "openai", "5.00", "30.00", "0.50", None),
    ("gpt-5.4", "openai", "2.50", "15.00", "0.25", None),
    ("gpt-5.4-mini", "openai", "0.75", "4.50", "0.075", None),
    ("gpt-5.4-nano", "openai", "0.20", "1.25", "0.02", None),
    ("gpt-5.2", "openai", "1.75", "14.00", "0.175", None),
    ("gpt-5.1", "openai", "1.25", "10.00", "0.125", None),
    ("gpt-5", "openai", "1.25", "10.00", "0.125", None),
    ("gpt-5-mini", "openai", "0.25", "2.00", "0.025", None),
    ("gpt-5-nano", "openai", "0.05", "0.40", "0.005", None),
    ("o3-pro", "openai", "20.00", "80.00", None, None),
    ("o1-pro", "openai", "150.00", "600.00", None, None),
    # --- OpenAI, previous generations, still referenced by this repo ---
    ("gpt-4.1", "openai", "2.00", "8.00", "0.50", None),
    ("gpt-4.1-mini", "openai", "0.40", "1.60", "0.10", None),
    ("gpt-4.1-nano", "openai", "0.10", "0.40", "0.025", None),
    ("gpt-4o", "openai", "2.50", "10.00", "1.25", None),
    ("gpt-4o-mini", "openai", "0.15", "0.60", "0.075", None),
    ("o1", "openai", "15.00", "60.00", "7.50", None),
    ("o3", "openai", "2.00", "8.00", "0.50", None),
    ("o3-mini", "openai", "1.10", "4.40", "0.55", None),
    ("o4-mini", "openai", "1.10", "4.40", "0.275", None),
    ("gpt-4-turbo", "openai", "10.00", "30.00", None, None),
    ("gpt-4", "openai", "30.00", "60.00", None, None),
    ("gpt-3.5-turbo", "openai", "0.50", "1.50", None, None),
    # --- Anthropic, current ---
    ("claude-fable-5-1", "anthropic", "10.00", "50.00", "0.25", "12.50"),
    ("claude-opus-5-5", "anthropic", "4.00", "20.00", "0.20", "5.00"),
    ("claude-opus-5", "anthropic", "5.00", "25.00", "0.50", "6.25"),
    ("claude-opus-4-8", "anthropic", "5.00", "25.00", "0.50", "6.25"),
    ("claude-sonnet-5", "anthropic", "2.00", "10.00", "0.20", "2.50"),
    ("claude-sonnet-4-6", "anthropic", "3.00", "15.00", "0.30", "3.75"),
    ("claude-sonnet-4-5", "anthropic", "3.00", "15.00", "0.30", "3.75"),
    ("claude-haiku-4-5", "anthropic", "1.00", "5.00", "0.10", "1.25"),
    # --- Anthropic, previous generations, still referenced by this repo ---
    ("claude-opus-4-20250514", "anthropic", "15.00", "75.00", "1.50", "18.75"),
    ("claude-sonnet-4-20250514", "anthropic", "3.00", "15.00", "0.30", "3.75"),
    ("claude-haiku-4-20250514", "anthropic", "0.80", "4.00", "0.08", "1.00"),
    ("claude-3-5-sonnet-20241022", "anthropic", "3.00", "15.00", "0.30", "3.75"),
    ("claude-3-5-haiku-20241022", "anthropic", "0.80", "4.00", "0.08", "1.00"),
    ("claude-3-opus-20240229", "anthropic", "15.00", "75.00", "1.50", "18.75"),
    ("claude-3-sonnet-20240229", "anthropic", "3.00", "15.00", "0.30", "3.75"),
    ("claude-3-haiku-20240307", "anthropic", "0.25", "1.25", None, None),
)


def _check_rate(name: str, value: Any, *, required: bool) -> None:
    """Refuse a rate that is not a finite, non-negative ``Decimal``."""
    if value is None:
        if required:
            raise ValueError(f"{name} is required and must be a price, not None")
        return
    if not isinstance(value, Decimal):
        raise TypeError(
            f"{name} must be a Decimal, got {type(value).__name__} {value!r}; a price "
            "is never a binary float"
        )
    if not value.is_finite():
        raise ValueError(f"{name} must be a finite price, got {value}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")


def _check_money(name: str, value: Any) -> None:
    """Refuse an amount that is not a finite, non-negative, quantised Decimal."""
    if not isinstance(value, Decimal):
        raise TypeError(
            f"{name} must be a Decimal, got {type(value).__name__} {value!r}; money is "
            "never a binary float"
        )
    if not value.is_finite():
        raise ValueError(f"{name} must be a finite amount, got {value}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")
    # The exponent, rather than a comparison against a requantised copy: it says
    # the same thing without asking the decimal context to hold 30-odd digits of
    # an absurd amount, and it draws the line where the wire form draws it.
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent != -MONEY_PLACES:
        raise ValueError(
            f"{name} must be quantised to exactly {MONEY_PLACES} decimal places, got "
            f"{value}; quantise it with Decimal.quantize(Decimal('0.000001'), "
            "rounding=ROUND_HALF_UP)"
        )


def _check_effective_from(value: Any) -> None:
    if not isinstance(value, str):
        raise TypeError(
            f"effective_from must be a str, got {type(value).__name__} {value!r}"
        )
    if not _ISO_DATE_RE.match(value):
        raise ValueError(
            f"effective_from must be an ISO date, YYYY-MM-DD, got {value!r}"
        )
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"effective_from is not a real date: {value!r}") from exc


@dataclass(frozen=True)
class PriceEntry:
    """One model's price list, in USD per million tokens, with its provenance.

    A cache component that the provider publishes no rate for is ``None``, which
    is not the same as ``Decimal("0")``: ``None`` means the price is unknown and
    :func:`compute_cost` records the gap in
    :attr:`CostBreakdown.priced_components`, while a zero would claim the tokens
    were free. ``source`` says where the numbers came from (:data:`SOURCES`) and
    ``confidence`` says how checkable they are (:data:`CONFIDENCES`) — a
    negotiated rate is not on any public page, so a reader cannot confirm it.
    """

    model: str
    provider: str
    input_per_mtok_usd: Decimal
    output_per_mtok_usd: Decimal
    cache_read_per_mtok_usd: Decimal | None
    cache_write_per_mtok_usd: Decimal | None
    effective_from: str
    source: str
    confidence: str

    def __post_init__(self) -> None:
        for name in ("model", "provider"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(
                    f"{name} must be a str, got {type(value).__name__} {value!r}"
                )
            if not value.strip():
                raise ValueError(f"{name} must be non-empty, got {value!r}")
        _check_rate("input_per_mtok_usd", self.input_per_mtok_usd, required=True)
        _check_rate("output_per_mtok_usd", self.output_per_mtok_usd, required=True)
        _check_rate("cache_read_per_mtok_usd", self.cache_read_per_mtok_usd, required=False)
        _check_rate("cache_write_per_mtok_usd", self.cache_write_per_mtok_usd, required=False)
        _check_effective_from(self.effective_from)
        for name, allowed in (("source", SOURCES), ("confidence", CONFIDENCES)):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(
                    f"{name} must be a str, got {type(value).__name__} {value!r}"
                )
            if value not in allowed:
                raise ValueError(f"{name} must be one of {list(allowed)}, got {value!r}")

    def rate(self, component: str) -> Decimal | None:
        """Return the published rate for one of :data:`COST_COMPONENTS`, or ``None``."""
        return getattr(self, _RATE_FIELDS[component])


def _build_bundled() -> Mapping[str, PriceEntry]:
    entries: dict[str, PriceEntry] = {}
    for model, provider, input_rate, output_rate, cache_read, cache_write in _BUNDLED_ROWS:
        entries[model] = PriceEntry(
            model=model,
            provider=provider,
            input_per_mtok_usd=Decimal(input_rate),
            output_per_mtok_usd=Decimal(output_rate),
            cache_read_per_mtok_usd=Decimal(cache_read) if cache_read else None,
            cache_write_per_mtok_usd=Decimal(cache_write) if cache_write else None,
            effective_from=BUNDLED_EFFECTIVE_FROM,
            source="bundled",
            confidence="list",
        )
    return MappingProxyType(entries)


#: The shipped price list, keyed by model name, immutable. Every entry is
#: ``source="bundled"``, ``confidence="list"``, effective
#: :data:`BUNDLED_EFFECTIVE_FROM`.
BUNDLED_PRICES: Mapping[str, PriceEntry] = _build_bundled()


@lru_cache(maxsize=2048)
def model_candidates(model: str) -> tuple[str, ...]:
    """Return the names a lookup for ``model`` should try, most specific first.

    Providers append a snapshot or an alias to a family name, so the string that
    comes back on a response is rarely the string the catalog is keyed by. The
    reduction is three documented tiers, in this order:

    1. the name exactly as given — a catalog may be keyed on the exact string
       the provider reports, and an exact match always wins;
    2. the name with a trailing snapshot marker removed, repeatedly:
       ``-YYYY-MM-DD`` (OpenAI), ``-YYYYMMDD`` (Anthropic) and ``-latest``, so
       ``gpt-4o-2024-08-06`` also offers ``gpt-4o``;
    3. the target of :data:`MODEL_ALIASES` for each name already offered, in the
       same order, so ``claude-3-5-sonnet-latest`` offers ``claude-3-5-sonnet``
       and then, through the alias map, ``claude-3-5-sonnet-20241022``.

    Tier 2 exists because a snapshot names a build, not a price card: the family
    publishes one list price for its dated snapshots, so charging the family's
    price is correct. It is still a claim, and a deployment that prices a
    specific snapshot differently says so in a catalog file, which is a higher
    layer and therefore wins.

    The result is cached: :func:`compute_cost` runs once per request, and the
    two patterns above are compiled once at import rather than per call.
    """
    offered: list[str] = []
    seen: set[str] = set()

    def offer(name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            offered.append(name)

    offer(model)
    current = model
    while True:
        stripped = _SNAPSHOT_SUFFIX_RE.sub("", current)
        if stripped == current:
            break
        current = stripped
        offer(current)
    for name in offered:
        offer(MODEL_ALIASES.get(name, ""))
    return tuple(offered)


class PriceCatalog:
    """Resolves a ``(provider, model)`` pair to a :class:`PriceEntry` or ``None``.

    The catalog holds two layers: the explicit ``entries`` mapping, which is the
    user's, and :data:`BUNDLED_PRICES`. The user's layer is searched across
    every :func:`model_candidates` tier before the bundled layer is consulted at
    all, so a user price always outranks a bundled one. Both layers are keyed by
    ``(provider, model)``, so an entry filed under the wrong provider is not
    found rather than silently charged to the right one.

    Instances are immutable: nothing here mutates a layer after construction, so
    one catalog can be shared by every request without a lock.
    """

    def __init__(
        self,
        entries: Mapping[str, PriceEntry] | None = None,
        *,
        include_bundled: bool = True,
    ) -> None:
        user: dict[tuple[str, str], PriceEntry] = {}
        for model, entry in (entries or {}).items():
            if not isinstance(entry, PriceEntry):
                raise TypeError(
                    f"catalog entry {model!r} must be a PriceEntry, got "
                    f"{type(entry).__name__}"
                )
            if entry.model != model:
                raise ValueError(
                    f"catalog key {model!r} does not match its entry's model "
                    f"{entry.model!r}"
                )
            user[(entry.provider, model)] = entry
        self._user = user
        self._bundled = (
            {(entry.provider, model): entry for model, entry in BUNDLED_PRICES.items()}
            if include_bundled
            else {}
        )

    def resolve(self, provider: str, model: str) -> PriceEntry | None:
        """Return the price for ``provider``'s ``model``, or ``None`` if unknown.

        ``None`` is a real answer, not a failure: it means the ledger records
        the event as unpriced rather than charging a guess. See
        :func:`model_candidates` for the name tiers tried.
        """
        if not isinstance(provider, str):
            raise TypeError(f"provider must be a str, got {type(provider).__name__}")
        if not isinstance(model, str):
            raise TypeError(f"model must be a str, got {type(model).__name__}")
        candidates = model_candidates(model)
        for name in candidates:
            entry = self._user.get((provider, name))
            if entry is not None:
                return entry
        for name in candidates:
            entry = self._bundled.get((provider, name))
            if entry is not None:
                return entry
        return None

    @classmethod
    def from_file(
        cls, path: str | os.PathLike[str], *, include_bundled: bool = True
    ) -> "PriceCatalog":
        """Load a user catalog from a JSON file and layer it over the bundled one.

        JSON, because the repository already stores JSON and already depends on
        PyYAML; stdlib ``json`` keeps the ledger core dependency-free. The shape
        is a mapping with an optional file-level ``effective_from`` and a
        required ``entries`` list::

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

        An entry inherits the file-level ``effective_from`` unless it carries
        its own; with neither, the error names the entry, because a price with
        no date is not a price anybody can reason about. Money is a string
        above all else, but a JSON number is accepted and read back through its
        shortest repr, so a hand-written ``2.10`` means exactly ``2.10``.

        Every entry is filed as ``source="user"``, ``confidence="negotiated"``:
        a file a deployment wrote is a rate it agreed to, whatever it was copied
        from. Anything wrong with the document — a non-object at the top, an
        undeclared key, a missing rate, a negative one, a duplicate model, a
        day that does not exist — raises ``ValueError`` or ``TypeError`` naming
        the offending key and the entry it came from. This is called explicitly
        by a caller and never at import.
        """
        location = os.fspath(path)
        with open(location, "r", encoding="utf-8") as handle:
            raw = handle.read()
        try:
            document = json.loads(raw)
        except ValueError as exc:
            raise ValueError(
                f"price catalog {location!r} is not valid JSON: {exc}"
            ) from exc
        return cls(
            _entries_from_document(document, location), include_bundled=include_bundled
        )


_CATALOG_KEYS = frozenset({"effective_from", "entries"})
_CATALOG_ENTRY_KEYS = frozenset(
    {
        "model",
        "provider",
        "effective_from",
        "input_per_mtok_usd",
        "output_per_mtok_usd",
        "cache_read_per_mtok_usd",
        "cache_write_per_mtok_usd",
    }
)


def _to_rate(value: Any, where: str, name: str) -> Decimal:
    """Read one rate off a parsed document and return it as a ``Decimal``."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise TypeError(
            f"{where}: {name} must be a number or a decimal string, got "
            f"{type(value).__name__} {value!r}"
        )
    if isinstance(value, float):
        # A JSON number has already been through a binary float. Its shortest
        # repr is the text the author wrote, so read that back and no other.
        value = repr(value)
    try:
        rate = Decimal(value)
    except ArithmeticError as exc:
        raise ValueError(f"{where}: {name} is not a decimal number: {value!r}") from exc
    if not rate.is_finite():
        raise ValueError(f"{where}: {name} must be a finite price, got {value!r}")
    if rate < 0:
        raise ValueError(f"{where}: {name} must be >= 0, got {value!r}")
    return rate


def _entries_from_document(document: Any, location: str) -> dict[str, PriceEntry]:
    """Validate a parsed user catalog and return its entries by model name."""
    if not isinstance(document, dict):
        raise ValueError(
            f"price catalog {location!r} must be a JSON object, got "
            f"{type(document).__name__}"
        )
    unknown = sorted(set(document) - _CATALOG_KEYS)
    if unknown:
        raise ValueError(
            f"price catalog {location!r}: unknown key(s) {unknown}; a catalog "
            f"accepts {sorted(_CATALOG_KEYS)}"
        )
    if "entries" not in document:
        raise ValueError(
            f"price catalog {location!r}: missing 'entries'; a catalog carries "
            f"{sorted(_CATALOG_KEYS)}"
        )
    file_effective = document.get("effective_from")
    if file_effective is not None:
        try:
            _check_effective_from(file_effective)
        except (TypeError, ValueError) as exc:
            raise type(exc)(f"price catalog {location!r}: {exc}") from exc
    listed = document["entries"]
    if not isinstance(listed, list):
        raise ValueError(
            f"price catalog {location!r}: 'entries' must be a list, got "
            f"{type(listed).__name__}"
        )
    index: dict[str, PriceEntry] = {}
    for position, item in enumerate(listed):
        where = f"price catalog {location!r} entry {position}"
        if not isinstance(item, dict):
            raise ValueError(
                f"{where}: must be a JSON object, got {type(item).__name__}"
            )
        stray = sorted(set(item) - _CATALOG_ENTRY_KEYS)
        if stray:
            raise ValueError(
                f"{where}: unknown key(s) {stray}; an entry accepts "
                f"{sorted(_CATALOG_ENTRY_KEYS)}"
            )
        for name in ("model", "provider"):
            if name not in item:
                raise ValueError(f"{where}: missing {name!r}")
            if not isinstance(item[name], str) or not item[name].strip():
                raise ValueError(
                    f"{where}: {name} must be a non-empty string, got {item[name]!r}"
                )
        model = item["model"]
        where = f"{where} (model {model!r})"
        if model in index:
            raise ValueError(f"{where}: duplicate; the file prices it twice")
        for name in ("input_per_mtok_usd", "output_per_mtok_usd"):
            if name not in item:
                raise ValueError(f"{where}: missing {name!r}")
        effective = item.get("effective_from", file_effective)
        if effective is None:
            raise ValueError(
                f"{where}: no effective_from; set it on the entry or on the file"
            )
        index[model] = PriceEntry(
            model=model,
            provider=item["provider"],
            input_per_mtok_usd=_to_rate(
                item["input_per_mtok_usd"], where, "input_per_mtok_usd"
            ),
            output_per_mtok_usd=_to_rate(
                item["output_per_mtok_usd"], where, "output_per_mtok_usd"
            ),
            cache_read_per_mtok_usd=(
                None
                if item.get("cache_read_per_mtok_usd") is None
                else _to_rate(
                    item["cache_read_per_mtok_usd"], where, "cache_read_per_mtok_usd"
                )
            ),
            cache_write_per_mtok_usd=(
                None
                if item.get("cache_write_per_mtok_usd") is None
                else _to_rate(
                    item["cache_write_per_mtok_usd"], where, "cache_write_per_mtok_usd"
                )
            ),
            effective_from=effective,
            source="user",
            confidence="negotiated",
        )
    return index


@dataclass(frozen=True)
class CostBreakdown:
    """What one request cost, in USD, and how much of that is knowable.

    Every amount is a ``Decimal`` quantised to :data:`MONEY_PLACES` decimal
    places with ``ROUND_HALF_UP``, and ``total_usd`` is exactly the sum of the
    four components — a breakdown whose total disagrees with its parts is a bug,
    not a rounding artefact.

    ``price_source`` says which layer won (:data:`PRICE_SOURCES`) and
    ``estimated_tokens`` carries the event's own ``estimated`` flag through, so
    an estimated record is never mistaken for a measurement.

    ``priced_components`` records which of :data:`COST_COMPONENTS` the price
    source actually published a rate for. A component outside it is charged zero
    *and marked*, which is the whole point: a model with no published cache rate
    is under-counted on its cached tokens, and an export that reports
    ``priced_components`` can say so instead of presenting the zero as a
    measurement. It describes the price record, not the request, so it does not
    change with the token counts.
    """

    input_usd: Decimal
    output_usd: Decimal
    cache_read_usd: Decimal
    cache_write_usd: Decimal
    total_usd: Decimal
    currency: str
    price_source: str
    estimated_tokens: bool
    priced_components: frozenset[str]

    def __post_init__(self) -> None:
        for name in ("input_usd", "output_usd", "cache_read_usd", "cache_write_usd", "total_usd"):
            _check_money(name, getattr(self, name))
        if not isinstance(self.currency, str):
            raise TypeError(
                f"currency must be a str, got {type(self.currency).__name__} "
                f"{self.currency!r}"
            )
        if self.currency != CURRENCY:
            raise ValueError(f"currency must be {CURRENCY!r}, got {self.currency!r}")
        if not isinstance(self.price_source, str):
            raise TypeError(
                f"price_source must be a str, got {type(self.price_source).__name__} "
                f"{self.price_source!r}"
            )
        if self.price_source not in PRICE_SOURCES:
            raise ValueError(
                f"price_source must be one of {list(PRICE_SOURCES)}, got "
                f"{self.price_source!r}"
            )
        if not isinstance(self.estimated_tokens, bool):
            raise TypeError(
                "estimated_tokens must be a bool, got "
                f"{type(self.estimated_tokens).__name__} {self.estimated_tokens!r}"
            )
        components = self.priced_components
        if not isinstance(components, (frozenset, set)):
            raise TypeError(
                "priced_components must be a set of component names, got "
                f"{type(components).__name__} {components!r}"
            )
        unknown = sorted(components - set(COST_COMPONENTS))
        if unknown:
            raise ValueError(
                f"priced_components names {unknown}, which are not components; "
                f"the components are {list(COST_COMPONENTS)}"
            )
        # A frozen dataclass refuses assignment, so the set is normalised to a
        # frozenset exactly once, here: the record is hashable and immutable
        # from this point on, whatever collection the caller passed.
        object.__setattr__(self, "priced_components", frozenset(components))

    def to_dict(self) -> dict[str, Any]:
        """Return the wire form, with every amount as a decimal *string*.

        Money is a string on purpose. A JSON number would be read back as a
        binary float, and a finance export that loses cents is worse than one
        that is awkward to parse. ``priced_components`` is a sorted-by-position
        list, so a ledger line is byte-stable.
        """
        return {
            "input_usd": str(self.input_usd),
            "output_usd": str(self.output_usd),
            "cache_read_usd": str(self.cache_read_usd),
            "cache_write_usd": str(self.cache_write_usd),
            "total_usd": str(self.total_usd),
            "currency": self.currency,
            "price_source": self.price_source,
            "estimated_tokens": self.estimated_tokens,
            "priced_components": [
                name for name in COST_COMPONENTS if name in self.priced_components
            ],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> "CostBreakdown":
        """Rebuild a breakdown from :meth:`to_dict` output, running validation again.

        The payload must carry exactly the declared fields: an undeclared key is
        an error rather than something to ignore, and a missing one is an error
        rather than a default, because a typo or a truncation in a persisted
        line would otherwise reload as plausible-looking money. An amount must be
        a string — a JSON number has already lost the distinction this format
        exists to keep, so it is refused rather than coerced.
        """
        if not isinstance(payload, dict):
            raise TypeError(f"payload must be a mapping, got {type(payload).__name__}")
        declared = set(cls.__dataclass_fields__)
        unknown = sorted(set(payload) - declared)
        if unknown:
            raise ValueError(
                f"unknown CostBreakdown field(s) {unknown}; the schema declares "
                f"{sorted(declared)}"
            )
        missing = sorted(declared - set(payload))
        if missing:
            raise ValueError(
                f"missing CostBreakdown field(s) {missing}; every recorded line "
                "carries all of them"
            )
        components = payload["priced_components"]
        if not isinstance(components, (list, tuple)):
            raise TypeError(
                "priced_components must be a list on the wire, got "
                f"{type(components).__name__}"
            )
        offered: set[str] = set()
        duplicated: set[str] = set()
        for name in components:
            if name in offered:
                duplicated.add(name)
            offered.add(name)
        if duplicated:
            raise ValueError(f"priced_components names {sorted(duplicated)} more than once")
        return cls(
            input_usd=_money_from_wire(payload["input_usd"], "input_usd"),
            output_usd=_money_from_wire(payload["output_usd"], "output_usd"),
            cache_read_usd=_money_from_wire(payload["cache_read_usd"], "cache_read_usd"),
            cache_write_usd=_money_from_wire(payload["cache_write_usd"], "cache_write_usd"),
            total_usd=_money_from_wire(payload["total_usd"], "total_usd"),
            currency=payload["currency"],
            price_source=payload["price_source"],
            estimated_tokens=payload["estimated_tokens"],
            priced_components=frozenset(components),
        )


def _money_from_wire(value: Any, name: str) -> Decimal:
    if not isinstance(value, str):
        raise TypeError(
            f"{name} must be a decimal string, not {type(value).__name__} {value!r}; "
            "money is written as a string so that a reader cannot reinterpret it "
            "as a float"
        )
    try:
        amount = Decimal(value)
    except ArithmeticError as exc:
        raise ValueError(f"{name} is not a decimal number: {value!r}") from exc
    _check_money(name, amount)
    return amount


def _amount(tokens: int, rate: Decimal | None) -> Decimal:
    """Return what ``tokens`` cost at ``rate`` per million tokens, to 6 places.

    Zero when the rate is unknown *or* the token count is zero. The unknown rate
    is the caller's problem to record: it returns zero here and
    :func:`compute_cost` leaves the component out of ``priced_components``.

    **Read :data:`LEDGER_CONTEXT` from the caller.** The multiply, the divide and
    the quantise are all context-sensitive, and ``quantize`` raises
    ``InvalidOperation`` outright once the ambient precision is shorter than the
    result — which is the entire failure this module now guards against. Its one
    caller, :func:`_breakdown`, installs :data:`LEDGER_CONTEXT` once around all
    four components, because four context switches per request would cost four
    times what one does and this runs on the hot path.
    """
    if not tokens or rate is None:
        return _ZERO
    return (Decimal(tokens) * rate / _MTOK).quantize(_QUANTUM, rounding=ROUND_HALF_UP)


_OVERRIDE_KEYS = frozenset(
    {
        "provider",
        "effective_from",
        "input_per_mtok_usd",
        "output_per_mtok_usd",
        "cache_read_per_mtok_usd",
        "cache_write_per_mtok_usd",
    }
)
_OVERRIDE_REQUIRED = ("input_per_mtok_usd", "output_per_mtok_usd", "effective_from")


def _override_entry(
    overrides: Mapping[str, Any], provider: str, model: str
) -> PriceEntry | None:
    """Return the per-call override for ``model``, or ``None`` if there is none.

    Keys go through the same :func:`model_candidates` tiers as the catalog, so an
    override filed under the family name prices a dated snapshot too. A value is
    either a ready-made :class:`PriceEntry`, which must name this event's
    provider, or a mapping of rates that is completed from the event: the model
    from the key, the provider from the event, ``source="user"`` and
    ``confidence="negotiated"``, because a price somebody passed in by hand is
    not a published rate card. A mapping must still say when it took effect;
    there is no default date, because a price with no date is not a price
    anybody can reason about.
    """
    for name in model_candidates(model):
        if name not in overrides:
            continue
        value = overrides[name]
        if isinstance(value, PriceEntry):
            if value.provider != provider:
                raise ValueError(
                    f"price_overrides[{name!r}] is for provider {value.provider!r}, "
                    f"but the event is {provider!r}"
                )
            return value
        if not isinstance(value, Mapping):
            raise TypeError(
                f"price_overrides[{name!r}] must be a PriceEntry or a mapping of "
                f"rates, got {type(value).__name__}"
            )
        where = f"price_overrides[{name!r}]"
        stray = sorted(set(value) - _OVERRIDE_KEYS)
        if stray:
            raise ValueError(
                f"{where}: unknown key(s) {stray}; an override accepts "
                f"{sorted(_OVERRIDE_KEYS)}"
            )
        missing = [key for key in _OVERRIDE_REQUIRED if key not in value]
        if missing:
            raise ValueError(
                f"{where}: missing {missing}; an override accepts {sorted(_OVERRIDE_KEYS)}"
            )
        return PriceEntry(
            model=name,
            provider=value.get("provider", provider),
            input_per_mtok_usd=_to_rate(value["input_per_mtok_usd"], where, "input_per_mtok_usd"),
            output_per_mtok_usd=_to_rate(
                value["output_per_mtok_usd"], where, "output_per_mtok_usd"
            ),
            cache_read_per_mtok_usd=(
                None
                if value.get("cache_read_per_mtok_usd") is None
                else _to_rate(
                    value["cache_read_per_mtok_usd"], where, "cache_read_per_mtok_usd"
                )
            ),
            cache_write_per_mtok_usd=(
                None
                if value.get("cache_write_per_mtok_usd") is None
                else _to_rate(
                    value["cache_write_per_mtok_usd"], where, "cache_write_per_mtok_usd"
                )
            ),
            effective_from=value["effective_from"],
            source="user",
            confidence="negotiated",
        )
    return None


def _breakdown(
    event: "SpendEvent", entry: PriceEntry, price_source: str
) -> CostBreakdown:
    """Bill one event against one winning price, and record what it covered."""
    # One context for all four components and the total, rather than one each:
    # ``localcontext`` costs about three quarters of a microsecond to enter and
    # leave, which is 5% of a ``compute_cost`` call, and four of them would be
    # 20% of a figure this product promises not to change on the request path.
    with localcontext(LEDGER_CONTEXT):
        amounts: dict[str, Decimal] = {}
        priced: set[str] = set()
        for component in COST_COMPONENTS:
            rate = entry.rate(component)
            if rate is not None:
                priced.add(component)
            amounts[component] = _amount(getattr(event, _TOKEN_FIELDS[component]), rate)
        # Summing the four quantised components is exact at six decimal places, so
        # requantising is a no-op and the total always equals its parts.
        total = sum(amounts.values(), _ZERO)
        return CostBreakdown(
            input_usd=amounts["input"],
            output_usd=amounts["output"],
            cache_read_usd=amounts["cache_read"],
            cache_write_usd=amounts["cache_write"],
            total_usd=total.quantize(_QUANTUM, rounding=ROUND_HALF_UP),
            currency=CURRENCY,
            price_source=price_source,
            estimated_tokens=event.estimated,
            priced_components=frozenset(priced),
        )


def compute_cost(
    event: "SpendEvent",
    catalog: PriceCatalog,
    price_overrides: Mapping[str, Any] | None = None,
) -> CostBreakdown | None:
    """Price one event, or return ``None`` because no price is known for it.

    ``None`` is the honest answer for a model the catalog does not carry, and it
    is the answer this function is built around: it never falls back to a
    neighbouring model, a family average, or a default rate, because a
    charge-back that is quietly wrong is worse than one that is absent. **The
    caller owns the counter path**: when this returns ``None`` the event is
    recorded with ``cost=None`` and the ledger increments its
    ``price_unknown`` counter, so an unpriced model is visible in the export
    rather than absent from it.

    ``price_overrides`` wins over the catalog for this call only. Precedence, from
    :func:`PriceCatalog` and here together: per-call override, then the user's
    catalog, then the bundled table.

    Purity: the same ``(event, catalog, price_overrides)`` always gives the same
    breakdown. No clock, no global state, no I/O — this runs once per request on
    the hot path, so the model-name reduction is cached and both patterns are
    compiled at import.

    The event is read for ``provider``, ``model``, the four token counts and
    ``estimated``; ``SpendEvent`` has already refused negative counts, and
    :class:`CostBreakdown` refuses a negative amount, so a bad count surfaces
    here rather than as a credit.
    """
    if not isinstance(catalog, PriceCatalog):
        raise TypeError(
            f"catalog must be a PriceCatalog, got {type(catalog).__name__}"
        )
    if price_overrides is not None:
        if not isinstance(price_overrides, Mapping):
            raise TypeError(
                "price_overrides must be a mapping, got "
                f"{type(price_overrides).__name__}"
            )
        override = _override_entry(price_overrides, event.provider, event.model)
        if override is not None:
            return _breakdown(event, override, "override")
    entry = catalog.resolve(event.provider, event.model)
    if entry is None:
        return None
    return _breakdown(event, entry, entry.source)
