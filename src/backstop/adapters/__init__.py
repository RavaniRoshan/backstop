"""Framework adapters (Deep Research P1#6).

Backstop enforces in-process, but agents live inside frameworks (LangChain,
LlamaIndex, CrewAI, AutoGen). These thin, optional-import adapters bridge the
framework's callback system to Backstop's hooks/metrics/tenant scoping so
Backstop becomes *the* guardrail inside the framework instead of a wrapper around
the raw SDK. Framework imports are deferred to call time, so ``import
backstop.adapters`` is always safe without the framework installed.
"""
from __future__ import annotations

from typing import Any


class BackstopAdapter:
    """Framework-agnostic bridge. Subclass or call ``on_llm_start`` /
    ``on_llm_end`` from a framework callback to feed Backstop's metrics and
    audit log. No framework dependency."""

    def __init__(self, config: Any, tenant_id: str | None = None) -> None:
        self.config = config
        self.tenant_id = tenant_id

    def on_llm_start(self, model: str, estimated_tokens: int = 0) -> dict:
        return {"model": model, "estimated_tokens": estimated_tokens, "tenant_id": self.tenant_id}

    def on_llm_end(self, model: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> dict:
        return {
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "tenant_id": self.tenant_id,
        }


def get_langchain_handler(config: Any, tenant_id: str | None = None) -> Any:
    from langchain_core.callbacks import BaseCallbackHandler

    adapter = BackstopAdapter(config, tenant_id)

    class BackstopCallbackHandler(BaseCallbackHandler):
        def on_llm_start(self, serialized, prompts, **kwargs):
            model = (serialized or {}).get("name", "") if isinstance(serialized, dict) else ""
            est = sum(len(p) // 4 for p in prompts) if prompts else 0
            adapter.on_llm_start(model, est)

        def on_llm_end(self, response, **kwargs):
            model = getattr(response, "llm_output", None) or {}
            usage = (model.get("token_usage") if isinstance(model, dict) else None) or {}
            adapter.on_llm_end(
                model.get("model_name", "") if isinstance(model, dict) else "",
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )

    return BackstopCallbackHandler()


def get_llama_index_callback(config: Any, tenant_id: str | None = None) -> Any:
    from llama_index.core.callbacks import BaseCallbackHandler as LlamaBase

    adapter = BackstopAdapter(config, tenant_id)

    class BackstopLlamaHandler(LlamaBase):
        def on_event_start(self, event_type, payload=None, event_id="", parent_id="", **kwargs):
            if str(event_type).lower().startswith("llm"):
                adapter.on_llm_start(str(payload.get("model", "")) if isinstance(payload, dict) else "")

        def on_event_end(self, event_type, payload=None, event_id="", parent_id="", **kwargs):
            if str(event_type).lower().startswith("llm"):
                adapter.on_llm_end(str(payload.get("model", "")) if isinstance(payload, dict) else "")

    return BackstopLlamaHandler()
