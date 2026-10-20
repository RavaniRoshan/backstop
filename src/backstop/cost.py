"""A rough cost estimate for a request, before it is made.

This is the "what would this call probably cost" number, not a charge. The
charge is the ledger's, and it is computed from the usage the provider
actually reported.

The two used to disagree in kind, not just in precision: the ledger's money
was :class:`~decimal.Decimal` end to end, and this estimate was a binary
float. A float cannot represent most decimal fractions exactly, so an estimate
of ``$0.0075`` was not ``$0.0075`` — it was the nearest double to it, and a
caller who printed it, summed it, or sent it to a finance system inherited
that error. It is now a ``Decimal``, like every other amount in this package.

The prices themselves come from :mod:`backstop.pricing_catalog` — the one
table — so an estimate and a charge agree about what a model costs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .extract import count_tokens
from .pricing import estimate_cost as _pricing_estimate


@dataclass
class CostEstimate:
    prompt_tokens: int
    expected_completion_tokens: int
    model: str
    #: The estimated cost in US dollars, exact to the ledger's money
    #: precision. A ``Decimal``, not a float.
    cost_usd: Decimal


def estimate(
    messages: list[dict[str, Any]] | str,
    model: str = "gpt-4o",
    max_tokens: int | None = None,
) -> CostEstimate:
    if isinstance(messages, list):
        text = json.dumps(messages, separators=(",", ":"))
    else:
        text = messages
    prompt_tokens = count_tokens(text, model)
    completion_tokens = max_tokens or 1024
    cost_usd = _pricing_estimate(prompt_tokens, completion_tokens, model)
    return CostEstimate(
        prompt_tokens=prompt_tokens,
        expected_completion_tokens=completion_tokens,
        model=model,
        cost_usd=cost_usd,
    )
