from __future__ import annotations

from openai import OpenAI

from backstop import Backstop, BackstopConfig


client = Backstop.wrap(
    OpenAI(),
    budget=100_000,
    config=BackstopConfig(initial_concurrency=8),
)


def user_facing_request(prompt: str) -> object:
    return client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        extra_headers={"X-Backstop-Priority": "critical"},
    )


def background_job(prompt: str) -> object:
    return client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}],
        extra_headers={"X-Backstop-Priority": "background"},
    )
