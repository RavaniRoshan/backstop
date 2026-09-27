from __future__ import annotations

import os

from backstop.secrets import _try_env, _try_virtual_keys, resolve_secret, SecretProviderChain


def test_resolve_secret_explicit_provider_wins():
    def my_provider(vk):
        return f"provider-{vk}"

    assert resolve_secret(my_provider, "key-abc") == "provider-key-abc"


def test_resolve_secret_env_var_matches_sanitized_name():
    try:
        os.environ["BACKSTOP_API_KEY_MY_KEY"] = "env-key"
        assert resolve_secret(None, "my-key") == "env-key"
    finally:
        os.environ.pop("BACKSTOP_API_KEY_MY_KEY", None)


def test_resolve_secret_fallback_env():
    try:
        os.environ["BACKSTOP_API_KEY"] = "fallback-key"
        assert resolve_secret(None, "unknown-key") == "fallback-key"
    finally:
        os.environ.pop("BACKSTOP_API_KEY", None)


def test_resolve_secret_virtual_keys_mapping():
    vks = {"my-key": "mapped-real-key"}
    assert resolve_secret(None, "my-key", vks) == "mapped-real-key"


def test_resolve_secret_noop_returns_virtual_key():
    assert resolve_secret(None, "bare-key") == "bare-key"


def test_resolve_secret_order_provider_over_env():
    def my_provider(vk):
        return f"provider-{vk}"

    try:
        os.environ["BACKSTOP_API_KEY_MY_KEY"] = "env-key"
        assert resolve_secret(my_provider, "my-key") == "provider-my-key"
    finally:
        os.environ.pop("BACKSTOP_API_KEY_MY_KEY", None)


def test_resolve_secret_provider_returning_none_falls_through():
    def returning_none(vk):
        return None

    try:
        os.environ["BACKSTOP_API_KEY_FALLBACK"] = "env-fallback"
        assert resolve_secret(returning_none, "fallback") == "env-fallback"
    finally:
        os.environ.pop("BACKSTOP_API_KEY_FALLBACK", None)


def test_resolve_secret_provider_exception_falls_through():
    def raising(vk):
        raise RuntimeError("boom")

    try:
        os.environ["BACKSTOP_API_KEY_RAISE"] = "env-raise"
        assert resolve_secret(raising, "raise") == "env-raise"
    finally:
        os.environ.pop("BACKSTOP_API_KEY_RAISE", None)


def test_secret_provider_chain_default():
    chain = SecretProviderChain()
    assert chain("my-key") == "my-key"


def test_secret_provider_chain_with_virtual_keys():
    chain = SecretProviderChain({"vk-1": "real-key-1"})
    assert chain("vk-1") == "real-key-1"


def test_try_env_sanitizes_dashes():
    try:
        os.environ["BACKSTOP_API_KEY_MY_KEY"] = "sanitized"
        assert _try_env("my-key") == "sanitized"
    finally:
        os.environ.pop("BACKSTOP_API_KEY_MY_KEY", None)


def test_try_virtual_keys_missing_key_returns_none():
    assert _try_virtual_keys("missing", {"a": "b"}) is None


def test_the_default_secret_provider_is_actually_installed():
    """Regression: the documented default chain was never installed.

    `BackstopConfig` is a frozen dataclass, so the `self.secret_provider = ...`
    assignment in `__post_init__` raised `FrozenInstanceError` - which a bare
    `except Exception: pass` swallowed. So `secret_provider` stayed `None` for
    every user, the documented default `SecretProviderChain` never existed at
    runtime, and a deployment using virtual keys believed it had per-tenant
    credentials while silently sending the virtual key name upstream.
    """
    from backstop import BackstopConfig
    from backstop.secrets import SecretProviderChain

    # no virtual keys means nothing to resolve, so no chain is built
    assert BackstopConfig().secret_provider is None

    config = BackstopConfig(virtual_keys={"tenant_a": "sk-literal"})
    assert isinstance(config.secret_provider, SecretProviderChain), (
        "the default SecretProviderChain was not installed; virtual keys are dead"
    )
    assert config.secret_provider("tenant_a") == "sk-literal"

    # and an explicit provider still wins over the default
    explicit = BackstopConfig(secret_provider=lambda vk: "sk-explicit")
    assert explicit.secret_provider("anything") == "sk-explicit"
