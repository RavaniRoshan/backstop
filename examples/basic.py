from openai import OpenAI

from backstop import Backstop, BackstopConfig


client = Backstop.wrap(
    OpenAI(),
    budget=50_000,
    config=BackstopConfig(initial_concurrency=4),
)

response = client.chat.completions.create(
    model="gpt-4.1-mini",
    messages=[{"role": "user", "content": "Say hello in five words."}],
    extra_headers={"X-Backstop-Priority": "critical"},
)

print(response)

