import os

import pytest


@pytest.mark.real_anthropic
def test_real_anthropic_sync_smoke():
    anthropic = pytest.importorskip("anthropic")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("set ANTHROPIC_API_KEY to run real Anthropic tests")

    from backstop import Backstop, BackstopConfig

    client = Backstop.wrap(
        anthropic.Anthropic(api_key=api_key),
        budget=1_000,
        config=BackstopConfig(default_max_output_tokens=16),
    )
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=16,
        messages=[{"role": "user", "content": "Return exactly: backstop-ok"}],
        extra_headers={"X-Backstop-Priority": "critical"},
    )
    assert response.content
    client.close()


@pytest.mark.real_anthropic
@pytest.mark.anyio
async def test_real_anthropic_async_smoke():
    anthropic = pytest.importorskip("anthropic")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("set ANTHROPIC_API_KEY to run real Anthropic tests")

    from backstop import Backstop, BackstopConfig

    client = Backstop.wrap(
        anthropic.AsyncAnthropic(api_key=api_key),
        budget=1_000,
        config=BackstopConfig(default_max_output_tokens=16),
    )
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=16,
        messages=[{"role": "user", "content": "Return exactly: backstop-ok"}],
        extra_headers={"X-Backstop-Priority": "critical"},
    )
    assert response.content
    await client.close()
