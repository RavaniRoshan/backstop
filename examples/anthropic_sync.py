from __future__ import annotations

import os

from anthropic import Anthropic

from backstop import Backstop, BackstopConfig


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY to run this example.")

    client = Backstop.wrap(
        Anthropic(),
        budget=50_000,
        config=BackstopConfig(initial_concurrency=4),
    )

    response = client.messages.create(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=64,
        messages=[{"role": "user", "content": "Say hello in five words."}],
        extra_headers={"X-Backstop-Priority": "critical"},
    )

    print(response.content[0].text)
    print(getattr(response, "_backstop_meta", None))


if __name__ == "__main__":
    main()
