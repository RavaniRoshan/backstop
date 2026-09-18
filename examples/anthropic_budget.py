"""
# KEYLESS — runs with no API key (offline, mock transport)

Demonstrates budget enforcement with the Anthropic SDK client.
"""
from __future__ import annotations

import anthropic
import httpx

from backstop import Backstop, BackstopConfig
from backstop.exceptions import BudgetExceededError
from backstop._httpcompat import compat_for

# ---------------------------------------------------------------------------
# Build a mock Anthropic transport so this runs offline
# ---------------------------------------------------------------------------
_probe = anthropic.Anthropic(api_key="sk-ant-test")
_compat = compat_for(_probe._client)

_CALL_COUNT = 0


def _mock_handler(request) -> httpx.Response:
    global _CALL_COUNT
    _CALL_COUNT += 1
    return _compat.Response(
        200,
        json={
            "id": "msg_mock",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "mock response"}],
            "model": "claude-3-5-sonnet-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 15, "output_tokens": 20},
        },
    )


http_client = _compat.Client(transport=_compat.MockTransport(_mock_handler))
raw_client = anthropic.Anthropic(api_key="sk-ant-test", http_client=http_client)

# ---------------------------------------------------------------------------
# Wrap with a 60-token budget — exhausted after 1–2 messages
# ---------------------------------------------------------------------------
client = Backstop.wrap(
    raw_client,
    budget=60,
    config=BackstopConfig(default_max_output_tokens=20, retry_max_attempts=1),
)

print("Anthropic budget demo (budget = 60 tokens, offline)\n")

calls_completed = 0
for i in range(5):
    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            messages=[{"role": "user", "content": f"Message {i}"}],
            max_tokens=20,
        )
        calls_completed += 1
        content = response.content[0].text if response.content else ""
        print(f"  Message {i}: OK — {content!r}")
    except BudgetExceededError:
        print(f"  Message {i}: BLOCKED — budget exhausted after {calls_completed} calls")
        break

print(f"\n{calls_completed}/5 messages completed before budget ceiling.")
print("BudgetExceededError is a subclass of anthropic.AnthropicError.")
