from __future__ import annotations

from backstop.verify import VerifyRunner, mask_secrets, run_verify


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
