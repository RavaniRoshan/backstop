"""
Priority admission control example. Requires OPENAI_API_KEY to be set.

Critical requests pass through when background requests are shed under load.
"""
from __future__ import annotations

import os

from openai import OpenAI

from backstop import Backstop, BackstopConfig

if not os.environ.get("OPENAI_API_KEY"):
    print("Set OPENAI_API_KEY to run this example.")
    raise SystemExit(0)

client = Backstop.wrap(
    OpenAI(),
    budget=100_000,
    config=BackstopConfig(initial_concurrency=8),
)


def user_facing_request(prompt: str) -> object:
    return client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        extra_headers={"X-Backstop-Priority": "critical"},
    )


def background_job(prompt: str) -> object:
    return client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        extra_headers={"X-Backstop-Priority": "background"},
    )
