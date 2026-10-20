"""A price lookup for the places that want a number, not a charge.

This module used to carry its own price table: 18 models, float rates, per
1,000 tokens, with a network refresh and a cache file. The ledger's
:mod:`backstop.pricing_catalog` carried another: 45 models, exact
:class:`~decimal.Decimal` rates, per million tokens, never touching the
network. The transport read the downgrade map from here and the ledger read
the prices from there, so the two disagreed — 31 of the 45 models Backstop
priced had no downgrade target at all, and the downgrade feature silently did
nothing for every current-generation model.

So there is now **one** table. This module is a thin adapter over
:mod:`backstop.pricing_catalog` for the callers that want "what does this
model cost" rather than the ledger's "price this specific event":

* :func:`backstop.cost.estimate` — the public estimator;
* the built-in dashboard's cost panel;
* the ``backstop demo`` comparison.

What it does **not** do any more:

* it does not keep a second price table;
* it does not refresh itself from the network or from
  ``~/.cache/backstop/pricing.json``. A price a deployment negotiated is
  supplied through ``config.price_catalog_path`` — a file, read explicitly —
  and :meth:`PriceCatalog.from_file` is where that happens. The refresh path
  wrote a cache file that nothing could ever write, and read it on every
  ``import backstop``;
* its money is :class:`~decimal.Decimal`, like every other amount in this
  package. A float estimate of a cost is a rounding error waiting to be
  quoted to somebody as a fact.

The price *data* — which models exist, what they cost, and what each one
downgrades to — is in :mod:`backstop.pricing_catalog`.
"""
from __future__ import annotations

import threading
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from .pricing_catalog import (
    BUNDLED_PRICES,
    LEDGER_CONTEXT,
    MONEY_PLACES,
    PriceEntry,
    downgrade_target,
    model_candidates,
)

#: A registered price, in the shape a caller supplies it. The rates are per
#: 1,000 tokens because that is the shape the public API has always taken.
ModelPricing = dict[str, Any]


class Pricing:
    """Resolves a model to its price, from the one catalog.

    The catalog is immutable and shared, so this object holds no mutable
    price state of its own beyond the user-registered overlay.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._overrides: dict[str, PriceEntry] = {}

    def register(self, model: str, pricing: ModelPricing) -> None:
        """Register a price for ``model``, overriding the bundled one.

        ``pricing`` is a mapping with ``input_cost_per_1k`` and
        ``output_cost_per_1k`` in dollars, and optionally ``downgrade_to``.
        The rates are converted into the catalog's exact-decimal per-million
        representation, so a registered price is a first-class catalog entry
        rather than a parallel float table.
        """
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"model must be a non-empty str, got {model!r}")
        if not isinstance(pricing, dict):
            raise TypeError(f"pricing must be a dict, got {type(pricing).__name__}")
        in_rate = pricing.get("input_cost_per_1k")
        out_rate = pricing.get("output_cost_per_1k")
        if in_rate is None or out_rate is None:
            raise ValueError(
                "pricing needs both 'input_cost_per_1k' and 'output_cost_per_1k'"
            )
        provider = str(pricing.get("family") or _infer_provider(model))
        entry = PriceEntry(
            model=model,
            provider=provider,
            input_per_mtok_usd=_per_1k_to_per_mtok(in_rate),
            output_per_mtok_usd=_per_1k_to_per_mtok(out_rate),
            cache_read_per_mtok_usd=None,
            cache_write_per_mtok_usd=None,
            effective_from=date.today().isoformat(),
            source="user",
            confidence="negotiated",
        )
        with self._lock:
            self._overrides[model] = entry

    def as_dict(self) -> dict[str, ModelPricing]:
        """Every price this object knows about, in the per-1K float-ish shape."""
        with self._lock:
            overrides = dict(self._overrides)
        out: dict[str, ModelPricing] = {}
        for model, entry in list(BUNDLED_PRICES.items()) + list(overrides.items()):
            out[model] = {
                "family": entry.provider,
                "input_cost_per_1k": float(entry.input_per_mtok_usd) / 1000,
                "output_cost_per_1k": float(entry.output_per_mtok_usd) / 1000,
                "downgrade_to": downgrade_target(model),
            }
        return out

    def get(self, model: str) -> PriceEntry | None:
        """The price entry for ``model``, or ``None`` if the catalog has none.

        The name tiers are the catalog's: the exact string, then the string
        with a trailing snapshot marker stripped, then the alias map. A model
        the catalog has never heard of resolves to ``None`` rather than to
        the cheapest model in its family — a price that is quietly wrong is
        worse than one that is absent.
        """
        with self._lock:
            overrides = dict(self._overrides)
        for candidate in model_candidates(model):
            if candidate in overrides:
                return overrides[candidate]
            entry = BUNDLED_PRICES.get(candidate)
            if entry is not None:
                return entry
        return None

    def estimate_cost(
        self, prompt_tokens: int, completion_tokens: int, model: str
    ) -> Decimal:
        """What ``model`` costs for the given token counts.

        ``Decimal``, quantised to the catalog's money precision, computed
        under the catalog's own decimal context so the ambient one is never
        read. A model with no price returns ``Decimal("0")`` — the same
        "no price known" answer the ledger records, expressed as zero
        because this is an estimator and not a charge.
        """
        entry = self.get(model)
        if entry is None:
            return Decimal("0.00")
        with localcontext(LEDGER_CONTEXT):
            cost = (
                Decimal(prompt_tokens) * entry.input_per_mtok_usd
                + Decimal(completion_tokens) * entry.output_per_mtok_usd
            ) / Decimal(1_000_000)
            return cost.quantize(Decimal(1).scaleb(-MONEY_PLACES), rounding=ROUND_HALF_UP)

    def get_downgrade_target(self, model: str) -> str | None:
        return downgrade_target(model)


def _per_1k_to_per_mtok(rate: Any) -> Decimal:
    """Convert a per-thousand-token rate to a per-million-token rate."""
    return (Decimal(rate) * Decimal(1000)).quantize(
        Decimal(1).scaleb(-MONEY_PLACES), rounding=ROUND_HALF_UP
    )


def _infer_provider(model: str) -> str:
    lowered = model.lower()
    if "claude" in lowered or "anthropic" in lowered:
        return "anthropic"
    return "openai"


_PRICING = Pricing()


def get_pricing() -> Pricing:
    return _PRICING


def get_downgrade_target(model: str) -> str | None:
    return downgrade_target(model)


def estimate_cost(prompt_tokens: int, completion_tokens: int, model: str) -> Decimal:
    return _PRICING.estimate_cost(prompt_tokens, completion_tokens, model)


def register_pricing(model: str, pricing: ModelPricing) -> None:
    _PRICING.register(model, pricing)
