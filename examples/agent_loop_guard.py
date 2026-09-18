"""
# KEYLESS — runs with no API key (offline, mock transport)

Demonstrates a runaway agent loop hitting a hard token budget and stopping
cleanly with BudgetExceededError.
"""
from __future__ import annotations

import openai
import httpx

from backstop import Backstop, BackstopConfig
from backstop.exceptions import BudgetExceededError

# ---------------------------------------------------------------------------
# Build a mock OpenAI transport so this runs offline
# ---------------------------------------------------------------------------
_CALL_COUNT = 0


def _mock_handler(request: httpx.Request) -> httpx.Response:
    global _CALL_COUNT
    _CALL_COUNT += 1
    return httpx.Response(
        200,
        json={
            "id": f"chatcmpl-mock-{_CALL_COUNT}",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "step output"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 30,
                "total_tokens": 50,
            },
        },
    )


http_client = httpx.Client(transport=httpx.MockTransport(_mock_handler))
raw_client = openai.OpenAI(api_key="sk-test", http_client=http_client)

# ---------------------------------------------------------------------------
# Wrap with a 120-token budget — the loop will exhaust it after ~2 iterations
# ---------------------------------------------------------------------------
client = Backstop.wrap(
    raw_client,
    budget=120,
    config=BackstopConfig(default_max_output_tokens=30, retry_max_attempts=1),
)

print("Starting runaway agent loop (budget = 120 tokens)...\n")

calls_completed = 0
for step in range(10):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Agent step {step}: do something"}],
            max_tokens=30,
        )
        calls_completed += 1
        print(f"  Step {step}: completed — {response.choices[0].message.content!r}")
    except BudgetExceededError as exc:
        print(f"  Step {step}: BLOCKED — BudgetExceededError raised")
        print(f"  Loop stopped after {calls_completed} calls. No further spend possible.")
        break

print(f"\nResult: {calls_completed}/10 calls completed before budget was exhausted.")
print("BudgetExceededError is a subclass of openai.OpenAIError — existing error handling works.")
