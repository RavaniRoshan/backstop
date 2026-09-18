"""
Minimal OpenAI integration example. Requires OPENAI_API_KEY to be set.
For a keyless offline example, see examples/agent_loop_guard.py.
"""
import os

from openai import OpenAI

from backstop import Backstop, BackstopConfig

if not os.environ.get("OPENAI_API_KEY"):
    print("Set OPENAI_API_KEY to run this example.")
    raise SystemExit(0)

client = Backstop.wrap(
    OpenAI(),
    budget=50_000,
    config=BackstopConfig(initial_concurrency=4),
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Say hello in five words."}],
    extra_headers={"X-Backstop-Priority": "critical"},
)

print(response)
