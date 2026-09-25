"""
Priority admission control example. Requires OPENAI_API_KEY to be set.

When the concurrency limit is reached, a request waits for a slot and a
critical request is selected ahead of waiting default and background ones.
The gate queues and prioritises; it does not shed, so no background request
is cancelled or discarded. Once a ticket has waited `starvation_after_seconds`
(default 1.0) the oldest one in any queue is released even if a higher priority
is still waiting, so a background request that has aged can be admitted ahead
of a waiting critical one.
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
