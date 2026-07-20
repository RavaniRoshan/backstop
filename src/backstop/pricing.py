from __future__ import annotations

import json
import os
import threading
from typing import Any

ModelPricing = dict[str, Any]

# Default offline table. This is the always-available fallback: it ships with the
# package and works with no network. `refresh_pricing()` can extend/replace it from a
# local JSON file or a reachable URL; results are cached to the XDG cache dir so a
# single successful fetch improves every later run on the same machine.
DEFAULT_TABLE: dict[str, ModelPricing] = {
    # --- Anthropic Claude (current, 2026) ---
    "claude-opus-4-20250514": {
        "family": "anthropic",
        "input_cost_per_1k": 0.015,
        "output_cost_per_1k": 0.075,
        "downgrade_to": "claude-sonnet-4-20250514",
    },
    "claude-sonnet-4-20250514": {
        "family": "anthropic",
        "input_cost_per_1k": 0.003,
        "output_cost_per_1k": 0.015,
        "downgrade_to": "claude-haiku-4-20250514",
    },
    "claude-haiku-4-20250514": {
        "family": "anthropic",
        "input_cost_per_1k": 0.0008,
        "output_cost_per_1k": 0.004,
        "downgrade_to": None,
    },
    # Older Claude generations kept for back-compat references.
    "claude-3-5-sonnet-20241022": {
        "family": "anthropic",
        "input_cost_per_1k": 0.003,
        "output_cost_per_1k": 0.015,
        "downgrade_to": "claude-3-5-haiku-20241022",
    },
    "claude-3-5-haiku-20241022": {
        "family": "anthropic",
        "input_cost_per_1k": 0.0008,
        "output_cost_per_1k": 0.004,
        "downgrade_to": None,
    },
    "claude-3-opus-20240229": {
        "family": "anthropic",
        "input_cost_per_1k": 0.015,
        "output_cost_per_1k": 0.075,
        "downgrade_to": "claude-3-5-sonnet-20241022",
    },
    "claude-3-sonnet-20240229": {
        "family": "anthropic",
        "input_cost_per_1k": 0.003,
        "output_cost_per_1k": 0.015,
        "downgrade_to": "claude-3-haiku-20240307",
    },
    "claude-3-haiku-20240307": {
        "family": "anthropic",
        "input_cost_per_1k": 0.00025,
        "output_cost_per_1k": 0.00125,
        "downgrade_to": None,
    },
    # --- OpenAI (current, 2026) ---
    "gpt-4.1": {
        "family": "openai",
        "input_cost_per_1k": 0.002,
        "output_cost_per_1k": 0.008,
        "downgrade_to": "gpt-4.1-mini",
    },
    "gpt-4.1-mini": {
        "family": "openai",
        "input_cost_per_1k": 0.0004,
        "output_cost_per_1k": 0.0016,
        "downgrade_to": "gpt-4.1-nano",
    },
    "gpt-4.1-nano": {
        "family": "openai",
        "input_cost_per_1k": 0.0001,
        "output_cost_per_1k": 0.0004,
        "downgrade_to": None,
    },
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
    "o1": {
        "family": "openai",
        "input_cost_per_1k": 0.015,
        "output_cost_per_1k": 0.06,
        "downgrade_to": "gpt-4o",
    },
    "o3-mini": {
        "family": "openai",
        "input_cost_per_1k": 0.0011,
        "output_cost_per_1k": 0.0044,
        "downgrade_to": "gpt-4o-mini",
    },
}


def _cache_path() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return os.path.join(base, "backstop", "pricing.json")


def load_cached_table() -> dict[str, ModelPricing]:
    path = _cache_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def save_cached_table(table: dict[str, ModelPricing]) -> None:
    path = _cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(table, fh, sort_keys=True, indent=2)
    except OSError:
        pass


class Pricing:
    """Resolves model pricing with an offline default table and optional refresh.

    Resolution order for a given model string:
      1. Exact match in the merged table (offline defaults + any refresh/register).
      2. Prefix match (e.g. ``"gpt-4o"`` matches ``"gpt-4o-2024-..."``).
      3. Family default (cheapest known model for the inferred family).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._table: dict[str, ModelPricing] = dict(DEFAULT_TABLE)
        self._table.update(load_cached_table())

    def register(self, model: str, pricing: ModelPricing) -> None:
        with self._lock:
            self._table[model] = pricing

    def as_dict(self) -> dict[str, ModelPricing]:
        with self._lock:
            return dict(self._table)

    def get(self, model: str) -> ModelPricing | None:
        with self._lock:
            table = dict(self._table)
        if model in table:
            return table[model]
        # Prefix match: pick the longest key that is a prefix of the requested id
        # (so ``gpt-4o`` resolves to ``gpt-4o`` before ``gpt-4o-mini``).
        candidate = None
        for key, value in table.items():
            if model.startswith(key) or key.startswith(model):
                if candidate is None or len(key) > len(candidate[0]):
                    candidate = (key, value)
        if candidate is not None:
            return candidate[1]
        # Family default: cheapest model for the inferred provider family.
        family = self._infer_family(model)
        if family is None:
            return None
        cheapest = None
        for value in table.values():
            if value.get("family") != family:
                continue
            cost = value.get("input_cost_per_1k", 0.0) + value.get("output_cost_per_1k", 0.0)
            if cheapest is None or cost < cheapest[0]:
                cheapest = (cost, value)
        return cheapest[1] if cheapest is not None else None

    @staticmethod
    def _infer_family(model: str) -> str | None:
        lowered = model.lower()
        if "claude" in lowered or "anthropic" in lowered:
            return "anthropic"
        if "gpt" in lowered or "o1" in lowered or "o3" in lowered or "o4" in lowered:
            return "openai"
        return None

    def estimate_cost(
        self, prompt_tokens: int, completion_tokens: int, model: str
    ) -> float:
        info = self.get(model)
        if info is None:
            return 0.0
        in_rate = info.get("input_cost_per_1k") or 0.0
        out_rate = info.get("output_cost_per_1k") or 0.0
        return round((prompt_tokens / 1000) * in_rate + (completion_tokens / 1000) * out_rate, 6)

    def get_downgrade_target(self, model: str) -> str | None:
        info = self.get(model)
        if info is None:
            return None
        return info.get("downgrade_to")

    def refresh(self, source: str | None = None) -> int:
        """Merge pricing from an optional source into the active table.

        ``source`` may be a path/URL to a JSON document mapping model name to a
        pricing object. When ``None``, a previously cached refresh file is loaded
        if present. Network/parse failures are ignored: the offline table always
        remains usable. Returns the number of models merged.
        """
        data = self._fetch_source(source)
        if not data:
            return 0
        count = 0
        with self._lock:
            for model, info in data.items():
                if isinstance(info, dict) and "input_cost_per_1k" in info:
                    self._table[model] = info
                    count += 1
        if source is None or source.startswith(("http://", "https://")):
            save_cached_table(self._table)
        else:
            try:
                save_cached_table(self._table)
            except OSError:
                pass
        return count

    def _fetch_source(self, source: str | None) -> dict[str, ModelPricing]:
        if source is None:
            return load_cached_table()
        if source.startswith(("http://", "https://")):
            try:
                import urllib.request

                with urllib.request.urlopen(source, timeout=5) as resp:  # noqa: S310
                    raw = resp.read().decode("utf-8")
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        try:
            with open(source, "r", encoding="utf-8") as fh:
                parsed = json.load(fh)
            return parsed if isinstance(parsed, dict) else {}
        except (OSError, ValueError):
            return {}


_PRICING = Pricing()


def get_pricing() -> Pricing:
    return _PRICING


def get_downgrade_target(model: str) -> str | None:
    return _PRICING.get_downgrade_target(model)


def estimate_cost(prompt_tokens: int, completion_tokens: int, model: str) -> float:
    return _PRICING.estimate_cost(prompt_tokens, completion_tokens, model)


def register_pricing(model: str, pricing: ModelPricing) -> None:
    _PRICING.register(model, pricing)


def refresh_pricing(source: str | None = None) -> int:
    return _PRICING.refresh(source)
