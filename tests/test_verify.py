from __future__ import annotations

import gc
import pytest

from backstop.telemetry import get_registry
from backstop.verify import VerifyRunner, mask_secrets, run_verify


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
