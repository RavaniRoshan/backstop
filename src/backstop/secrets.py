"""Secret provider interface (Deep Research P2#9).

Mitigates the in-process secret-handling risk the research flagged (plaintext
env vars, the March-2026 LiteLLM incident class). Backstop never holds raw
provider keys; instead a ``SecretProvider`` resolves a virtual key / tenant id to
a secret at call time. Ships with env + static providers; cloud secret managers
(AWS Secrets Manager, Azure Key Vault, Vault) implement the same interface.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any


class SecretProvider(ABC):
    @abstractmethod
    def get(self, key: str) -> str | None:
        ...

    def resolve(self, key: str) -> str | None:
        return self.get(key)


class EnvSecretProvider(SecretProvider):
    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix

    def get(self, key: str) -> str | None:
        return os.environ.get(f"{self._prefix}{key}")


class StaticSecretProvider(SecretProvider):
    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    def get(self, key: str) -> str | None:
        return self._secrets.get(key)


def resolve_secret(provider: Any, key: str) -> str | None:
    if provider is None:
        return None
    if isinstance(provider, SecretProvider):
        return provider.resolve(key)
    if callable(provider):
        result = provider(key)
        return result if isinstance(result, str) else None
    return None
