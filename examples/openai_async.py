from __future__ import annotations

import asyncio
import os

from openai import AsyncOpenAI

from backstop import Backstop, BackstopConfig


async def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY to run this example.")

    client = Backstop.wrap(
        AsyncOpenAI(),
        budget=50_000,
        config=BackstopConfig(initial_concurrency=4),
    )

    response = await client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        messages=[{"role": "user", "content": "Say hello in five words."}],
        extra_headers={"X-Backstop-Priority": "critical"},
    )

    print(response.choices[0].message.content)
    print(getattr(response, "_backstop_meta", None))


if __name__ == "__main__":
    asyncio.run(main())
