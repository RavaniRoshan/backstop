from __future__ import annotations

import gc
import json
import time
import pytest

from backstop.demo import DemoResult, run_demo
from backstop.telemetry import get_registry


@pytest.fixture(autouse=True)
def clean_registry():
    get_registry().reset()
    gc.collect()
    yield
    get_registry().reset()
    gc.collect()


def test_demo_offline_openai():
    result = run_demo(calls=10, budget=75, provider="openai")
    assert isinstance(result, DemoResult)
    assert result.success is True
    assert result.guardrail_enforced is True
    assert result.unprotected.calls_attempted == 10
    assert result.unprotected.calls_completed == 10
    assert result.unprotected.calls_blocked == 0
    assert result.unprotected.tokens_consumed == 250
    assert result.unprotected.provider_calls == 10

    assert result.wrapped.calls_attempted == 10
    assert result.wrapped.calls_completed == 3
    assert result.wrapped.calls_blocked == 7
    assert result.wrapped.tokens_consumed == 75
    assert result.wrapped.tokens_saved == 175
    assert result.wrapped.exception_name == "BudgetExceededError"
    assert result.wrapped.provider_calls == 3

    assert result.delta_calls_saved == 7
    assert result.delta_tokens_saved == 175
    assert result.savings_pct == 70.0
    assert result.delta_cost_saved_usd > 0.0


def test_demo_offline_anthropic():
    result = run_demo(calls=10, budget=75, provider="anthropic")
    assert isinstance(result, DemoResult)
    assert result.success is True
    assert result.guardrail_enforced is True
    assert result.unprotected.calls_completed == 10
    assert result.wrapped.calls_completed == 3
    assert result.wrapped.calls_blocked == 7
    assert result.wrapped.tokens_saved == 175
    assert result.wrapped.exception_name == "BudgetExceededError"
    assert result.wrapped.provider_calls == 3
    assert result.delta_calls_saved == 7


def test_demo_markdown_formatting():
    result = run_demo(calls=10, budget=75, provider="openai")
    md = result.to_markdown()

    # Zero ANSI noise
    assert "\x1b[" not in md
    assert "\x1b" not in md

    # Table structure
    assert "# Backstop Demo: Runaway Loop Guardrail Comparison" in md
    assert "| Metric | Unprotected | Wrapped (Backstop) | Delta / Savings |" in md
    assert "| Calls completed | 10 | 3 | -7 (-70.0%) |" in md
    assert "| Calls blocked | 0 | 7 | +7 (blocked in-process) |" in md
    assert "| Tokens consumed | 250 | 75 | -175 (-70.0%) |" in md
    assert "| Tokens saved | 0 | 175 | +175 tokens |" in md
    assert "BudgetExceededError" in md
    assert "| Provider HTTP calls | 10 | 3 | -7 calls prevented |" in md


def test_demo_json_output():
    result = run_demo(calls=10, budget=75, provider="openai")
    raw_json = result.to_json()
    data = json.loads(raw_json)

    assert data["scenario"] == "runaway_agent_loop"
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o-mini"
    assert data["budget"] == 75
    assert data["total_calls"] == 10
    assert data["guardrail_enforced"] is True
    assert data["success"] is True
    assert data["delta_calls_saved"] == 7
    assert data["delta_tokens_saved"] == 175
    assert data["savings_pct"] == 70.0
    assert data["unprotected"]["calls_completed"] == 10
    assert data["wrapped"]["calls_completed"] == 3
    assert data["wrapped"]["calls_blocked"] == 7
    assert data["wrapped"]["exception_name"] == "BudgetExceededError"


def test_demo_execution_time_under_30s():
    t0 = time.perf_counter()
    result = run_demo(calls=10, budget=75)
    elapsed = time.perf_counter() - t0
    assert result.success is True
    assert elapsed < 5.0  # Well under the 30s requirement
