import os

import pytest

from backstop.real_openai import arun_real_openai_smoke, run_real_openai_smoke


pytestmark = pytest.mark.real_openai


def _has_real_openai_config() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


@pytest.mark.skipif(not _has_real_openai_config(), reason="OPENAI_API_KEY is not set")
def test_real_openai_responses_sync_smoke():
    pytest.importorskip("openai")
    result = run_real_openai_smoke(
        budget=1_000,
        api=os.getenv("OPENAI_REAL_API", "responses"),
    )
    assert result.status == "ok"
    assert result.spent_tokens > 0
    assert result.remaining_budget is None or result.remaining_budget < 1_000
    assert "backstop-ok" in result.output_text.lower()


@pytest.mark.anyio
@pytest.mark.skipif(not _has_real_openai_config(), reason="OPENAI_API_KEY is not set")
async def test_real_openai_responses_async_smoke():
    pytest.importorskip("openai")
    result = await arun_real_openai_smoke(
        budget=1_000,
        api=os.getenv("OPENAI_REAL_API", "responses"),
    )
    assert result.status == "ok"
    assert result.spent_tokens > 0
    assert result.remaining_budget is None or result.remaining_budget < 1_000
    assert "backstop-ok" in result.output_text.lower()
