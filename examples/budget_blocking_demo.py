from __future__ import annotations

import httpx

from backstop import BackstopConfig
from backstop.exceptions import BudgetExceededError
from backstop.state import BackstopState
from backstop.transports import BackstopTransport


class MockProvider:
    def __init__(self) -> None:
        self.calls = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_demo",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            },
        )


def main() -> None:
    provider = MockProvider()
    state = BackstopState.create(
        budget=75,
        config=BackstopConfig(default_max_output_tokens=8, retry_max_attempts=1),
    )
    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(provider.handle)),
        base_url="https://mock.openai.local",
    )

    successes = 0
    blocked = 0

    for index in range(10):
        try:
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "mock",
                    "messages": [{"role": "user", "content": f"demo request {index}"}],
                    "max_tokens": 8,
                },
            )
            response.raise_for_status()
            successes += 1
        except BudgetExceededError:
            blocked += 1

    client.close()

    print(f"successes={successes}")
    print(f"blocked_before_provider={blocked}")
    print(f"provider_calls={provider.calls}")
    print(f"remaining_budget={state.budget.remaining}")


if __name__ == "__main__":
    main()
