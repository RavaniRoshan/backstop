from __future__ import annotations

import gc
import json
import pytest

from backstop.cli import main
from backstop.telemetry import get_registry


@pytest.fixture(autouse=True)
def clean_registry():
    get_registry().reset()
    gc.collect()
    yield
    get_registry().reset()
    gc.collect()


def test_cli_verify_default(capsys):
    code = main(["verify"])
    assert code == 0
    out = capsys.readouterr().out
    assert "# Backstop Verify — 30-Second Keyless Proof" in out
    assert "| Allowed calls | 2 |" in out
    assert "| Blocked calls | 8 |" in out
    assert "Status: VERIFIED (real wrap enforcement active)" in out


def test_cli_verify_strict(capsys):
    code = main(["verify", "--strict"])
    assert code == 0


def test_cli_verify_json(capsys):
    code = main(["verify", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "proof" in data
    assert "summary" in data
    assert "checks" in data
    assert data["proof"]["allowed_calls"] == 2
    assert data["proof"]["blocked_calls"] == 8
    assert data["proof"]["tokens_saved"] == 2000


def test_cli_verify_zero_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = main(["verify"])
    assert code == 0


def test_cli_demo_default(capsys):
    code = main(["demo"])
    assert code == 0
    out = capsys.readouterr().out
    assert "# Backstop Demo: Runaway Loop Guardrail Comparison" in out
    assert "| Calls completed | 10 | 3 | -7 (-70.0%) |" in out
    assert "| Calls blocked | 0 | 7 | +7 (blocked in-process) |" in out
    assert "BudgetExceededError" in out
    # Verify no ANSI noise
    assert "\x1b[" not in out


def test_cli_demo_strict(capsys):
    code = main(["demo", "--strict"])
    assert code == 0


def test_cli_demo_json(capsys):
    code = main(["demo", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["scenario"] == "runaway_agent_loop"
    assert data["guardrail_enforced"] is True
    assert data["delta_calls_saved"] == 7
    assert data["delta_tokens_saved"] == 175
    assert data["wrapped"]["calls_completed"] == 3
    assert data["wrapped"]["calls_blocked"] == 7


def test_cli_demo_provider_anthropic(capsys):
    code = main(["demo", "--provider", "anthropic"])
    assert code == 0
    out = capsys.readouterr().out
    assert "anthropic" in out
    assert "| Calls completed | 10 | 3 | -7 (-70.0%) |" in out


def test_cli_demo_zero_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = main(["demo"])
    assert code == 0
