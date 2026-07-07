from __future__ import annotations

from typing import Any

ModelPricing = dict[str, Any]

MODEL_TABLE: dict[str, ModelPricing] = {
    "gpt-4o": {
        "family": "openai",
        "input_cost_per_1k": 0.0025,
        "output_cost_per_1k": 0.01,
        "downgrade_to": "gpt-4o-mini",
    },
    "gpt-4o-mini": {
        "family": "openai",
        "input_cost_per_1k": 0.00015,
        "output_cost_per_1k": 0.0006,
        "downgrade_to": None,
    },
    "gpt-4-turbo": {
        "family": "openai",
        "input_cost_per_1k": 0.01,
        "output_cost_per_1k": 0.03,
        "downgrade_to": "gpt-4o-mini",
    },
    "gpt-4": {
        "family": "openai",
        "input_cost_per_1k": 0.03,
        "output_cost_per_1k": 0.06,
        "downgrade_to": "gpt-4o-mini",
    },
    "gpt-3.5-turbo": {
        "family": "openai",
        "input_cost_per_1k": 0.0005,
        "output_cost_per_1k": 0.0015,
        "downgrade_to": None,
    },
    "claude-sonnet-4-20250514": {
        "family": "anthropic",
        "input_cost_per_1k": 0.003,
        "output_cost_per_1k": 0.015,
        "downgrade_to": "claude-haiku-3-20240307",
    },
    "claude-haiku-3-20240307": {
        "family": "anthropic",
        "input_cost_per_1k": 0.00025,
        "output_cost_per_1k": 0.00125,
        "downgrade_to": None,
    },
}


def get_downgrade_target(model: str) -> str | None:
    info = MODEL_TABLE.get(model)
    if info is None:
        return None
    return info.get("downgrade_to")


def estimate_cost(prompt_tokens: int, completion_tokens: int, model: str) -> float:
    info = MODEL_TABLE.get(model)
    if info is None:
        return 0.0
    input_cost = (prompt_tokens / 1000) * info["input_cost_per_1k"]
    output_cost = (completion_tokens / 1000) * info["output_cost_per_1k"]
    return round(input_cost + output_cost, 6)


def register_pricing(model: str, pricing: ModelPricing) -> None:
    MODEL_TABLE[model] = pricing
