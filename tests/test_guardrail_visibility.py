"""Guardrail violation visibility — user-facing exception types.

PLAN 1.1.4 (OpenAI path) / 1.1.5 (Anthropic path).

Regression pin for 1.1.2: Backstop's errors inherit the provider SDK error
bases, so a blocked call surfaces to user code as a catchable
``BudgetExceededError`` — never as the SDK's relabelled
``APIConnectionError``. Each test fails if the 1.1.2 rebase is reverted.
"""

import pytest

from backstop import Backstop
from backstop.exceptions import BudgetExceededError


def test_openai_block_surfaces_catchable_backstop_error():
    """PLAN 1.1.4: OpenAI path — user code catches BudgetExceededError."""
    openai = pytest.importorskip("openai")
    client = openai.OpenAI(api_key="sk-test")
    wrapped = Backstop.wrap(client, budget=0)
    try:
        with pytest.raises(BudgetExceededError) as excinfo:
            wrapped.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hi"}],
            )
        assert isinstance(excinfo.value, openai.OpenAIError)
        assert not isinstance(excinfo.value, openai.APIConnectionError)
    finally:
        wrapped._client.close()
        client._client.close()


def test_anthropic_block_surfaces_catchable_backstop_error():
    """PLAN 1.1.5: Anthropic path — user code catches BudgetExceededError."""
    anthropic = pytest.importorskip("anthropic")
    client = anthropic.Anthropic(api_key="sk-ant-test")
    wrapped = Backstop.wrap(client, budget=0)
    try:
        with pytest.raises(BudgetExceededError) as excinfo:
            wrapped.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=10,
                messages=[{"role": "user", "content": "hi"}],
            )
        assert isinstance(excinfo.value, anthropic.AnthropicError)
        assert not isinstance(excinfo.value, anthropic.APIConnectionError)
    finally:
        wrapped._client.close()
        client._client.close()
