from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

from .config import BackstopConfig
from .wrapper import Backstop


@dataclass(frozen=True)
class RealAnthropicSmokeResult:
    model: str
    base_url: str
    async_client: bool
    status: str
    elapsed_ms: float
    remaining_budget: int | None
    spent_tokens: int
    output_text: str

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# Backstop Real Anthropic Smoke Test",
                "",
                "| Metric | Value |",
                "| --- | ---: |",
                f"| Model | {self.model} |",
                f"| Base URL | {self.base_url} |",
                f"| Client | {'AsyncAnthropic' if self.async_client else 'Anthropic'} |",
                f"| Status | {self.status} |",
                f"| Elapsed | {self.elapsed_ms:.2f} ms |",
                f"| Budget remaining | {self.remaining_budget if self.remaining_budget is not None else 'unlimited'} |",
                f"| Tokens spent | {self.spent_tokens} |",
                f"| Output | {self.output_text.strip()} |",
            ]
        )


def run_real_anthropic_smoke(
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    budget: int | None = 1_000,
    async_client: bool = False,
) -> RealAnthropicSmokeResult:
    if async_client:
        return asyncio.run(
            arun_real_anthropic_smoke(
                api_key=api_key, model=model, base_url=base_url, budget=budget
            )
        )
    return _run_sync(api_key=api_key, model=model, base_url=base_url, budget=budget)


async def arun_real_anthropic_smoke(
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    budget: int | None = 1_000,
) -> RealAnthropicSmokeResult:
    try:
        from anthropic import AsyncAnthropic
    except Exception as exc:
        raise RuntimeError("install the anthropic package to run the real Anthropic smoke test") from exc

    resolved_key = _api_key(api_key)
    resolved_model = _model(model)
    resolved_base_url = _base_url(base_url)
    started = time.perf_counter()
    client_kwargs = {"api_key": resolved_key}
    if resolved_base_url:
        client_kwargs["base_url"] = resolved_base_url
    client = Backstop.wrap(
        AsyncAnthropic(**client_kwargs),
        budget=budget,
        config=BackstopConfig(default_max_output_tokens=16),
    )
    response = await client.messages.create(
        model=resolved_model,
        max_tokens=16,
        messages=[{"role": "user", "content": "Return exactly: backstop-ok"}],
        extra_headers={"X-Backstop-Priority": "critical"},
    )
    await client.close()
    state = getattr(client, "_backstop_state")
    output_text = _extract_content_text(response.content)
    return RealAnthropicSmokeResult(
        model=resolved_model,
        base_url=resolved_base_url or "https://api.anthropic.com",
        async_client=True,
        status="ok",
        elapsed_ms=(time.perf_counter() - started) * 1000,
        remaining_budget=state.budget.remaining,
        spent_tokens=state.budget.spent,
        output_text=output_text,
    )


def _run_sync(
    *,
    api_key: str | None,
    model: str | None,
    base_url: str | None,
    budget: int | None,
) -> RealAnthropicSmokeResult:
    try:
        from anthropic import Anthropic
    except Exception as exc:
        raise RuntimeError("install the anthropic package to run the real Anthropic smoke test") from exc

    resolved_key = _api_key(api_key)
    resolved_model = _model(model)
    resolved_base_url = _base_url(base_url)
    started = time.perf_counter()
    client_kwargs = {"api_key": resolved_key}
    if resolved_base_url:
        client_kwargs["base_url"] = resolved_base_url
    client = Backstop.wrap(
        Anthropic(**client_kwargs),
        budget=budget,
        config=BackstopConfig(default_max_output_tokens=16),
    )
    response = client.messages.create(
        model=resolved_model,
        max_tokens=16,
        messages=[{"role": "user", "content": "Return exactly: backstop-ok"}],
        extra_headers={"X-Backstop-Priority": "critical"},
    )
    client.close()
    state = getattr(client, "_backstop_state")
    output_text = _extract_content_text(response.content)
    return RealAnthropicSmokeResult(
        model=resolved_model,
        base_url=resolved_base_url or "https://api.anthropic.com",
        async_client=False,
        status="ok",
        elapsed_ms=(time.perf_counter() - started) * 1000,
        remaining_budget=state.budget.remaining,
        spent_tokens=state.budget.spent,
        output_text=output_text,
    )


def _extract_content_text(content: list) -> str:
    for block in content or []:
        if hasattr(block, "text") and block.text:
            return block.text
        if hasattr(block, "thinking") and block.thinking:
            return block.thinking
    return ""


def _api_key(api_key: str | None) -> str:
    resolved = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not resolved:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    return resolved


def _model(model: str | None) -> str:
    return model or os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-20250514"


def _base_url(base_url: str | None) -> str | None:
    return base_url or os.getenv("ANTHROPIC_BASE_URL") or None
