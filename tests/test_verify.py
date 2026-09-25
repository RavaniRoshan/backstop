from __future__ import annotations

import gc

import httpx
import pytest

from backstop.cli import main
from backstop.telemetry import get_registry
from backstop.verify import (
    VerifyRunner,
    default_api_key_env,
    mask_secrets,
    run_verify,
)


_REAL_GET = httpx.Client.get

# (base_url, headers) of every intercepted live auth probe.
_PROBE_CALLS: list[tuple[str, dict[str, str]]] = []


def _record_probe_get(client, url, **kwargs) -> httpx.Response:
    """Stand in for ``httpx.Client.get`` on the live auth probe only.

    Deny by default: every client in ``verify`` that is allowed to answer from a
    mock carries a ``MockTransport`` (the offline proofs, and the clients handed
    to the SDKs). Anything else gets recorded instead of dialled out, so no test
    in this file can make a network call, whatever ``--base-url`` says.
    """
    if not isinstance(getattr(client, "_transport", None), httpx.MockTransport):
        _PROBE_CALLS.append((str(client.base_url or ""), kwargs.get("headers") or {}))
        return httpx.Response(200)
    return _REAL_GET(client, url, **kwargs)


@pytest.fixture
def auth_probe(monkeypatch):
    """Intercept the live auth probe; no network call is made."""
    _PROBE_CALLS.clear()
    monkeypatch.setattr(httpx.Client, "get", _record_probe_get)
    return _PROBE_CALLS


@pytest.fixture(autouse=True)
def clean_registry():
    get_registry().reset()
    gc.collect()
    yield
    get_registry().reset()
    gc.collect()


def test_mask_secrets_redacts_keys():
    text = "key sk-ABCDEFGHIJKLMNOPQRSTUVWX is here and also Zm9vYmFyYmF6cXF1d2Vy4thx"
    out = mask_secrets(text)
    assert "****" in out
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in out


def test_runner_offline_passes():
    runner = VerifyRunner()
    results = runner.run()
    statuses = {r.title: r.status for r in results}
    assert statuses["config valid"] == "pass"
    assert statuses["wrap pipeline"] == "pass"
    assert statuses["budget block"] == "pass"
    assert statuses["cache hit"] == "pass"
    assert statuses["per-agent isolation"] == "pass"
    # overhead is pass or warn depending on machine; never fail offline
    assert statuses["overhead"] in ("pass", "warn")


def test_runner_exit_code_zero_when_all_pass():
    code = run_verify()
    assert code == 0


def test_runner_strict_fails_on_warn():
    runner = VerifyRunner(strict=True)
    # force a warn by monkeypatching overhead to always warn is overkill; just
    # assert the summary contract: strict turns any warn into exit 1.
    results = [
        type("R", (), {"title": "x", "status": "warn", "detail": "", "fix": None, "duration_ms": 0.0})()
    ]
    summary = runner.summarize(results)
    assert summary["exit_code"] == 1


def test_provider_auth_skips_without_key():
    runner = VerifyRunner(live=True, api_key_env="DEFINITELY_NOT_SET_12345")
    res = runner._check_provider_auth()
    assert res.status == "skip"


def test_default_api_key_env_is_resolved_per_provider():
    assert default_api_key_env("openai") == "OPENAI_API_KEY"
    assert default_api_key_env("anthropic") == "ANTHROPIC_API_KEY"


def test_default_api_key_env_refuses_an_unknown_provider():
    # Never fall back to the OpenAI key for a provider we do not recognise.
    with pytest.raises(ValueError):
        default_api_key_env("cohere")


def test_runner_resolves_the_key_env_of_the_selected_provider():
    assert VerifyRunner(provider="openai").api_key_env == "OPENAI_API_KEY"
    assert VerifyRunner(provider="anthropic").api_key_env == "ANTHROPIC_API_KEY"


def test_explicit_api_key_env_wins_over_the_provider_default():
    runner = VerifyRunner(provider="anthropic", api_key_env="MY_PROXY_KEY")
    assert runner.api_key_env == "MY_PROXY_KEY"


def test_live_probe_never_sends_the_other_providers_key(monkeypatch, auth_probe):
    """The live auth probe must carry the selected provider's own key only.

    Asserted on the absence of the leaked value rather than an exact header dict,
    so this stays about *which credential* travels, not about how it is framed.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-must-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")

    res = VerifyRunner(live=True, provider="anthropic")._check_provider_auth()

    assert res.status == "pass"
    assert len(auth_probe) == 1
    base_url, headers = auth_probe[0]
    assert httpx.URL(base_url).host == "api.anthropic.com"
    assert "sk-openai-must-not-leak" not in str(headers)
    assert "sk-ant-secret-value" in str(headers)


def test_cli_verify_live_never_sends_the_other_providers_key(monkeypatch, auth_probe, capsys):
    """End-to-end through argparse: `verify --provider anthropic --live`.

    The helper tests cannot catch a wrong ``--api-key-env`` argparse default, so
    this drives the real CLI with both provider keys in the environment.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-must-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")

    exit_code = main(["verify", "--live", "--provider", "anthropic"])

    capsys.readouterr()
    assert exit_code == 0, "the whole verify run must still pass"
    assert auth_probe, "the live auth probe never ran"
    base_url, headers = auth_probe[-1]
    assert base_url.startswith("https://api.anthropic.com/")
    assert "sk-openai-must-not-leak" not in str(headers)
    assert "sk-ant-secret-value" in str(headers)


def test_cli_verify_rejects_live_and_offline_together(monkeypatch, auth_probe, capsys):
    """Asking for offline and live at once is a usage error, not a live probe.

    ``--offline`` used to be inert: the runner only ever read ``--live``, so
    this combination silently dialled out despite the user asking for no
    network. A key is exported so the probe *would* fire if it were honoured,
    and ``auth_probe`` fails the test on any un-mocked ``Client.get``.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-must-not-be-sent")

    with pytest.raises(SystemExit) as excinfo:
        main(["verify", "--live", "--offline"])

    assert excinfo.value.code != 0
    err = capsys.readouterr().err
    assert "usage:" in err
    assert "--offline" in err
    assert "--live" in err
    assert auth_probe == [], "a network call was made despite --offline"


def test_cli_verify_live_alone_still_probes(monkeypatch, auth_probe, capsys):
    """--live on its own is unchanged: it still probes, and still passes."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret-value")

    exit_code = main(["verify", "--live"])

    capsys.readouterr()
    assert exit_code == 0
    assert len(auth_probe) == 1, "the live auth probe never ran"


def test_cli_verify_offline_alone_still_probes_nothing(monkeypatch, auth_probe, capsys):
    """--offline on its own is unchanged: the default, fully offline run."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-must-not-be-sent")

    exit_code = main(["verify", "--offline"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert auth_probe == [], "a network call was made despite --offline"
    assert "provider auth (live)" not in out


def test_live_probe_uses_bearer_auth_for_openai(monkeypatch, auth_probe):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret-value")

    res = VerifyRunner(live=True, provider="openai")._check_provider_auth()

    assert res.status == "pass"
    _, headers = auth_probe[0]
    assert headers == {"Authorization": "Bearer sk-openai-secret-value"}


def test_live_probe_uses_x_api_key_for_anthropic(monkeypatch, auth_probe):
    """Anthropic rejects `Authorization: Bearer` even with a valid key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")

    res = VerifyRunner(live=True, provider="anthropic")._check_provider_auth()

    assert res.status == "pass"
    _, headers = auth_probe[0]
    assert headers["x-api-key"] == "sk-ant-secret-value"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in headers


def test_custom_base_url_warns_before_sending_the_credential(monkeypatch, auth_probe, capsys):
    """--base-url still works, but a foreign host gets a loud warning."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")

    res = VerifyRunner(
        live=True, provider="anthropic", base_url="https://proxy.internal/anthropic"
    )._check_provider_auth()

    assert res.status == "pass"
    err = capsys.readouterr().err
    assert "anthropic" in err
    assert "proxy.internal" in err
    assert "credential" in err
    # the flag is not blocked: the probe still went to the given host
    assert httpx.URL(auth_probe[0][0]).host == "proxy.internal"


def test_default_base_url_does_not_warn(monkeypatch, auth_probe, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")

    res = VerifyRunner(live=True, provider="anthropic")._check_provider_auth()

    assert res.status == "pass"
    assert capsys.readouterr().err == ""


def test_explicit_provider_default_base_url_does_not_warn(monkeypatch, auth_probe, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-secret-value")

    res = VerifyRunner(
        live=True, provider="openai", base_url="https://api.openai.com/v1"
    )._check_provider_auth()

    assert res.status == "pass"
    assert capsys.readouterr().err == ""


def test_shadow_records_without_blocking():
    res = VerifyRunner()._check_shadow()
    assert res.status == "pass"


def test_shadow_env_killswitch_disables():
    from backstop.rollout import ShadowCollector

    assert ShadowCollector.enabled(True) is True
    import os

    os.environ["BACKSTOP_SHADOW"] = "false"
    try:
        assert ShadowCollector.enabled(True) is False
    finally:
        del os.environ["BACKSTOP_SHADOW"]


def test_verify_real_wrap_proof_metrics():
    runner = VerifyRunner()
    results = runner.run()
    assert len(results) >= 8
    assert runner.proof is not None
    assert runner.proof["allowed_calls"] == 2
    assert runner.proof["blocked_calls"] == 8
    assert runner.proof["tokens_reserved"] == 500
    assert runner.proof["tokens_saved"] == 2000
    assert runner.proof["exception_name"] == "BudgetExceededError"
    assert runner.proof["exception_subclass_verified"] is True
    assert runner.proof["wall_clock_ms"] >= 0.0


def test_verify_anthropic_offline():
    runner = VerifyRunner(provider="anthropic")
    results = runner.run()
    statuses = {r.title: r.status for r in results}
    assert statuses["wrap pipeline"] == "pass"
    assert statuses["budget block"] == "pass"
    assert runner.proof is not None
    assert runner.proof["allowed_calls"] == 2
    assert runner.proof["blocked_calls"] == 8
    assert runner.proof["exception_name"] == "BudgetExceededError"
    assert runner.proof["exception_subclass_verified"] is True


def test_verify_json_output(capsys):
    import json

    code = run_verify(json_output=True)
    assert code == 0
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert "summary" in data
    assert "proof" in data
    assert "checks" in data
    assert data["summary"]["passed"] >= 7
    assert data["proof"]["allowed_calls"] == 2
    assert data["proof"]["blocked_calls"] == 8
    assert data["proof"]["tokens_saved"] == 2000
    assert data["proof"]["exception_name"] == "BudgetExceededError"


def test_verify_human_table_output(capsys):
    code = run_verify(json_output=False)
    assert code == 0
    out = capsys.readouterr().out
    assert "# Backstop Verify — 30-Second Keyless Proof" in out
    assert "| Allowed calls | 2 |" in out
    assert "| Blocked calls | 8 |" in out
    assert "| Tokens saved | 2,000 |" in out
    assert "| Exception surfaced | BudgetExceededError |" in out
    assert "Status: VERIFIED (real wrap enforcement active)" in out


def test_verify_zero_keys_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = run_verify()
    assert code == 0


def test_verify_execution_time_under_30s():
    import time

    t0 = time.perf_counter()
    code = run_verify()
    elapsed = time.perf_counter() - t0
    assert code == 0
    assert elapsed < 10.0  # Well under the 30s requirement
