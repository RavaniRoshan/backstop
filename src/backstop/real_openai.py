from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Literal

from .config import BackstopConfig
from .wrapper import Backstop


DEFAULT_REAL_MODEL = "gpt-4.1-mini"
SmokeAPI = Literal["responses", "chat"]


@dataclass(frozen=True)
class RealOpenAISmokeResult:
    model: str
    base_url: str
    api: str
    async_client: bool
    status: str
    elapsed_ms: float
    remaining_budget: int | None
    spent_tokens: int
    output_text: str

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# Backstop Real OpenAI Smoke Test",
                "",
                "| Metric | Value |",
                "| --- | ---: |",
                f"| Model | {self.model} |",
                f"| Base URL | {self.base_url} |",
                f"| API | {self.api} |",
                f"| Client | {'AsyncOpenAI' if self.async_client else 'OpenAI'} |",
                f"| Status | {self.status} |",
                f"| Elapsed | {self.elapsed_ms:.2f} ms |",
                f"| Budget remaining | {self.remaining_budget if self.remaining_budget is not None else 'unlimited'} |",
                f"| Tokens spent | {self.spent_tokens} |",
                f"| Output | {self.output_text.strip()} |",
            ]
        )


def run_real_openai_smoke(
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api: SmokeAPI = "responses",
    budget: int | None = 1_000,
    async_client: bool = False,
) -> RealOpenAISmokeResult:
    if async_client:
        return asyncio.run(
            arun_real_openai_smoke(
                api_key=api_key, model=model, base_url=base_url, api=api, budget=budget
            )
        )
    return _run_sync(api_key=api_key, model=model, base_url=base_url, api=api, budget=budget)


async def arun_real_openai_smoke(
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api: SmokeAPI = "responses",
    budget: int | None = 1_000,
) -> RealOpenAISmokeResult:
    try:
        from openai import AsyncOpenAI
    except Exception as exc:
        raise RuntimeError("install the openai package to run the real OpenAI smoke test") from exc

    resolved_key = _api_key(api_key)
    resolved_model = _model(model)
    resolved_base_url = _base_url(base_url)
    started = time.perf_counter()
    client_kwargs = {"api_key": resolved_key}
    if resolved_base_url:
        client_kwargs["base_url"] = resolved_base_url
    client = Backstop.wrap(
        AsyncOpenAI(**client_kwargs),
        budget=budget,
        config=BackstopConfig(default_max_output_tokens=16),
    )
    if api == "responses":
        response = await client.responses.create(
            model=resolved_model,
            input="Return exactly this text and nothing else: backstop-ok",
            max_output_tokens=16,
            extra_headers={"X-Backstop-Priority": "critical"},
        )
        output_text = _output_text(response)
    elif api == "chat":
        response = await client.chat.completions.create(
            model=resolved_model,
            messages=[{"role": "user", "content": "Return exactly: backstop-ok"}],
            max_tokens=16,
            extra_headers={"X-Backstop-Priority": "critical"},
        )
        output_text = response.choices[0].message.content or ""
    else:
        raise ValueError("api must be 'responses' or 'chat'")
    await client.close()
    state = getattr(client, "_backstop_state")
    return RealOpenAISmokeResult(
        model=resolved_model,
        base_url=resolved_base_url or "https://api.openai.com/v1",
        api=api,
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
    api: SmokeAPI,
    budget: int | None,
) -> RealOpenAISmokeResult:
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("install the openai package to run the real OpenAI smoke test") from exc

    resolved_key = _api_key(api_key)
    resolved_model = _model(model)
    resolved_base_url = _base_url(base_url)
    started = time.perf_counter()
    client_kwargs = {"api_key": resolved_key}
    if resolved_base_url:
        client_kwargs["base_url"] = resolved_base_url
    client = Backstop.wrap(
        OpenAI(**client_kwargs),
        budget=budget,
        config=BackstopConfig(default_max_output_tokens=16),
    )
    if api == "responses":
        response = client.responses.create(
            model=resolved_model,
            input="Return exactly this text and nothing else: backstop-ok",
            max_output_tokens=16,
            extra_headers={"X-Backstop-Priority": "critical"},
        )
        output_text = _output_text(response)
    elif api == "chat":
        response = client.chat.completions.create(
            model=resolved_model,
            messages=[{"role": "user", "content": "Return exactly: backstop-ok"}],
            max_tokens=16,
            extra_headers={"X-Backstop-Priority": "critical"},
        )
        output_text = response.choices[0].message.content or ""
    else:
        raise ValueError("api must be 'responses' or 'chat'")
    client.close()
    state = getattr(client, "_backstop_state")
    return RealOpenAISmokeResult(
        model=resolved_model,
        base_url=resolved_base_url or "https://api.openai.com/v1",
        api=api,
        async_client=False,
        status="ok",
        elapsed_ms=(time.perf_counter() - started) * 1000,
        remaining_budget=state.budget.remaining,
        spent_tokens=state.budget.spent,
        output_text=output_text,
    )


def _api_key(api_key: str | None) -> str:
    resolved = api_key or os.getenv("OPENAI_API_KEY")
    if not resolved:
        raise RuntimeError("OPENAI_API_KEY not set")
    return resolved


def _model(model: str | None) -> str:
    return model or os.getenv("OPENAI_MODEL") or DEFAULT_REAL_MODEL


def _base_url(base_url: str | None) -> str | None:
    return base_url or os.getenv("OPENAI_BASE_URL") or None


def _output_text(response: object) -> str:
    value = getattr(response, "output_text", None)
    if isinstance(value, str):
        return value
    return str(response)
