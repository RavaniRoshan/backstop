"""Secret provider default chain (Launch Improvement D1).

Resolution order for a virtual key ``vk``:
1. ``cfg.secret_provider(vk)`` — explicit callable set by the user
2. ``BACKSTOP_API_KEY_{upper(vk)}`` — env var derived from virtual key name
3. ``BACKSTOP_API_KEY`` — fallback env var
4. ``resolve_virtual_key(vk)`` — ``cfg.virtual_keys[vk]`` mapped to a literal key
5. No-op provider returns the virtual key itself (single-key mode)

The chain is lazy: each link is tried only if the previous one returns None.
No provider in the chain can raise — exceptions are swallowed and the next
link is tried.
"""
from __future__ import annotations

import os
from typing import Callable


def _try_callable(provider: Callable[[str], str | None], vk: str) -> str | None:
    try:
        result = provider(vk)
    except Exception:
        return None
    return result if result else None


def _try_env(vk: str) -> str | None:
    sanitized = vk.upper().replace("-", "_")
    for env_var in (f"BACKSTOP_API_KEY_{sanitized}", "BACKSTOP_API_KEY"):
        value = os.environ.get(env_var)
        if value:
            return value
    return None


def _try_virtual_keys(vk: str, virtual_keys: dict[str, str] | None) -> str | None:
    if virtual_keys is None:
        return None
    mapped = virtual_keys.get(vk)
    return mapped if mapped else None


def _noop(vk: str) -> str | None:
    return vk or None


def resolve_secret(provider: Callable[[str], str | None] | None, vk: str, virtual_keys: dict[str, str] | None = None) -> str:
    chain = [provider, lambda v: _try_virtual_keys(v, virtual_keys), _try_env, _noop]
    for link in chain:
        if link is None:
            continue
        result = _try_callable(link, vk)
        if result is not None:
            return result
    return vk


class SecretProviderChain:
    """Wraps resolve_secret for use as ``cfg.secret_provider``."""

    def __init__(self, virtual_keys: dict[str, str] | None = None) -> None:
        self._virtual_keys = virtual_keys

    def __call__(self, vk: str) -> str:
        return resolve_secret(None, vk, self._virtual_keys)
