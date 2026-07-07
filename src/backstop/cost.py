from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .extract import count_tokens
from .pricing import estimate_cost as _pricing_estimate


@dataclass
class CostEstimate:
    prompt_tokens: int
    expected_completion_tokens: int
    model: str
    cost_usd: float


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
