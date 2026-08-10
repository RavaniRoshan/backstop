"""Proof: secret provider default chain — provider-first, env-last, noop fallback.

Run with:
    python proofs/proof_secrets.py
"""
from __future__ import annotations

import os
import sys

from backstop.secrets import SecretProviderChain, resolve_secret


def main() -> int:
    # 1) Explicit provider wins
    def my_provider(vk):
        return f"provider-${vk}"

    assert resolve_secret(my_provider, "key") == "provider-$key"

    # 2) Virtual keys mapping wins over env
    os.environ["BACKSTOP_API_KEY_VK1"] = "env-key"
    vks = {"vk1": "mapped-key"}
    result = resolve_secret(None, "vk1", vks)
    assert result == "mapped-key", f"virtual keys should win over env, got {result}"
    del os.environ["BACKSTOP_API_KEY_VK1"]

    # 3) Env fallback when no mapping
    os.environ["BACKSTOP_API_KEY_UNKNOWN"] = "env-unknown"
    result = resolve_secret(None, "unknown", {})
    assert result == "env-unknown", f"env should fall back, got {result}"
    del os.environ["BACKSTOP_API_KEY_UNKNOWN"]

    # 4) Noop returns virtual key when nothing else matches
    assert resolve_secret(None, "bare-key") == "bare-key"

    # 5) Provider exception falls through safely
    def raising(vk):
        raise RuntimeError("boom")

    os.environ["BACKSTOP_API_KEY_SAFE"] = "safe"
    result = resolve_secret(raising, "safe")
    assert result == "safe", f"provider exception should fall through to env, got {result}"
    del os.environ["BACKSTOP_API_KEY_SAFE"]

    # 6) SecretProviderChain default
    chain = SecretProviderChain()
    assert chain("vk") == "vk"

    # 7) SecretProviderChain with virtual_keys
    chain2 = SecretProviderChain({"vk1": "real1"})
    assert chain2("vk1") == "real1"

    print("PROOF PASS: secret provider default chain holds (provider > virtual_keys > env > noop).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
