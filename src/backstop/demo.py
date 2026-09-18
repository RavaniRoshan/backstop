from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from ._httpcompat import compat_for
from .config import BackstopConfig
from .exceptions import BudgetExceededError
from .pricing import Pricing
from .wrapper import Backstop


@dataclass
class LoopMetrics:
    calls_attempted: int
    calls_completed: int
    calls_blocked: int
    tokens_consumed: int
    tokens_saved: int
    cost_usd: float
    provider_calls: int
    exception_name: str | None
    duration_ms: float


@dataclass
class DemoResult:
    scenario: str
    provider: str
    model: str
    budget: int
    total_calls: int
    unprotected: LoopMetrics
    wrapped: LoopMetrics
    delta_calls_saved: int
    delta_tokens_saved: int
    delta_cost_saved_usd: float
    savings_pct: float
    guardrail_enforced: bool
    success: bool
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_markdown(self) -> str:
        diff_ms = self.wrapped.duration_ms - self.unprotected.duration_ms
        lines = [
            "# Backstop Demo: Runaway Loop Guardrail Comparison",
            "",
            f"- **Scenario:** Simulated runaway agent loop ({self.total_calls} iterations)",
            f"- **Provider:** {self.provider} (wrapped in-process via `Backstop.wrap`)",
            f"- **Model:** {self.model} | **Budget:** {self.budget} tokens",
            "- **Mode:** 100% offline (mock transport, zero API keys)",
            "",
            "| Metric | Unprotected | Wrapped (Backstop) | Delta / Savings |",
            "|---|---:|---:|---:|",
            f"| Calls attempted | {self.total_calls} | {self.total_calls} | 0 |",
            f"| Calls completed | {self.unprotected.calls_completed} | {self.wrapped.calls_completed} | -{self.delta_calls_saved} (-{self.savings_pct:.1f}%) |",
            f"| Calls blocked | {self.unprotected.calls_blocked} | {self.wrapped.calls_blocked} | +{self.wrapped.calls_blocked} (blocked in-process) |",
            f"| Tokens consumed | {self.unprotected.tokens_consumed} | {self.wrapped.tokens_consumed} | -{self.delta_tokens_saved} (-{self.savings_pct:.1f}%) |",
            f"| Tokens saved | 0 | {self.delta_tokens_saved} | +{self.delta_tokens_saved} tokens |",
            f"| Estimated cost | ${self.unprotected.cost_usd:.6f} | ${self.wrapped.cost_usd:.6f} | -${self.delta_cost_saved_usd:.6f} (-{self.savings_pct:.1f}%) |",
            f"| Guardrail exception | None | {self.wrapped.exception_name or 'BudgetExceededError'} | {self.wrapped.calls_blocked} calls blocked |",
            f"| Provider HTTP calls | {self.unprotected.provider_calls} | {self.wrapped.provider_calls} | -{self.delta_calls_saved} calls prevented |",
            f"| Total runtime | {self.unprotected.duration_ms:.1f} ms | {self.wrapped.duration_ms:.1f} ms | {diff_ms:+.1f} ms |",
        ]
        return "\n".join(lines)


class _MockProviderTransport:
    """Mock wire transport tracking exact count of requests reaching the wire."""

    def __init__(
        self,
        compat: Any,
        provider: str,
        model: str,
        prompt_tokens: int = 15,
        completion_tokens: int = 10,
    ) -> None:
        self.compat = compat
        self.provider = provider
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.call_count = 0

    def handler(self, request: Any) -> Any:
        self.call_count += 1
        if self.provider == "anthropic":
            return self.compat.Response(
                200,
                json={
                    "id": f"msg_demo_{self.call_count}",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "demo response"}],
                    "model": self.model,
                    "stop_reason": "end_turn",
                    "usage": {
                        "input_tokens": self.prompt_tokens,
                        "output_tokens": self.completion_tokens,
                    },
                },
            )
        else:
            return self.compat.Response(
                200,
                json={
                    "id": f"chatcmpl-demo-{self.call_count}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": self.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "demo response"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": self.prompt_tokens,
                        "completion_tokens": self.completion_tokens,
                        "total_tokens": self.prompt_tokens + self.completion_tokens,
                    },
                },
            )


def run_demo(
    calls: int = 10,
    budget: int = 75,
    provider: str = "openai",
    model: str | None = None,
    strict: bool = False,
) -> DemoResult:
    """Run side-by-side comparison of an unprotected vs Backstop-wrapped runaway loop."""
    prompt_tokens = 15
    completion_tokens = 10
    tokens_per_call = prompt_tokens + completion_tokens

    if provider == "anthropic":
        try:
            import anthropic
        except ImportError:
            err_msg = (
                "Anthropic provider requested but 'anthropic' is not installed. "
                "Install with: pip install 'backstop-ai[anthropic]'"
            )
            empty = LoopMetrics(calls, 0, 0, 0, 0, 0.0, 0, None, 0.0)
            return DemoResult(
                scenario="runaway_agent_loop",
                provider=provider,
                model=model or "claude-3-5-sonnet-20241022",
                budget=budget,
                total_calls=calls,
                unprotected=empty,
                wrapped=empty,
                delta_calls_saved=0,
                delta_tokens_saved=0,
                delta_cost_saved_usd=0.0,
                savings_pct=0.0,
                guardrail_enforced=False,
                success=False,
                error_message=err_msg,
            )
        target_model = model or "claude-3-5-sonnet-20241022"
        probe = anthropic.Anthropic(api_key="mock-key-demo")
        compat = compat_for(probe._client)
    else:
        import openai

        target_model = model or "gpt-4o-mini"
        probe = openai.OpenAI(api_key="mock-key-demo")
        compat = compat_for(probe._client)

    pricing = Pricing()
    cost_per_call = pricing.estimate_cost(prompt_tokens, completion_tokens, target_model)

    # ------------------------------------------------------------------
    # 1. Unprotected Run
    # ------------------------------------------------------------------
    unprotected_transport = _MockProviderTransport(
        compat, provider, target_model, prompt_tokens, completion_tokens
    )
    unprotected_http = compat.Client(transport=compat.MockTransport(unprotected_transport.handler))
    if provider == "anthropic":
        unprotected_client = anthropic.Anthropic(
            api_key="mock-key-demo", http_client=unprotected_http
        )
    else:
        unprotected_client = openai.OpenAI(
            api_key="mock-key-demo", http_client=unprotected_http
        )

    unprotected_completed = 0
    unprotected_blocked = 0
    unprotected_tokens = 0
    t0 = time.perf_counter()
    for _ in range(calls):
        try:
            if provider == "anthropic":
                unprotected_client.messages.create(
                    model=target_model,
                    messages=[{"role": "user", "content": "runaway prompt"}],
                    max_tokens=completion_tokens,
                )
            else:
                unprotected_client.chat.completions.create(
                    model=target_model,
                    messages=[{"role": "user", "content": "runaway prompt"}],
                    max_tokens=completion_tokens,
                )
            unprotected_completed += 1
            unprotected_tokens += tokens_per_call
        except Exception:
            unprotected_blocked += 1
    unprotected_duration = (time.perf_counter() - t0) * 1000
    try:
        unprotected_client.close()
    except Exception:
        pass

    unprotected_cost = cost_per_call * unprotected_completed
    unprotected_metrics = LoopMetrics(
        calls_attempted=calls,
        calls_completed=unprotected_completed,
        calls_blocked=unprotected_blocked,
        tokens_consumed=unprotected_tokens,
        tokens_saved=0,
        cost_usd=unprotected_cost,
        provider_calls=unprotected_transport.call_count,
        exception_name=None,
        duration_ms=round(unprotected_duration, 2),
    )

    # ------------------------------------------------------------------
    # 2. Wrapped Run (Protected by Backstop)
    # ------------------------------------------------------------------
    wrapped_transport = _MockProviderTransport(
        compat, provider, target_model, prompt_tokens, completion_tokens
    )
    wrapped_http = compat.Client(transport=compat.MockTransport(wrapped_transport.handler))
    if provider == "anthropic":
        raw_wrapped = anthropic.Anthropic(
            api_key="mock-key-demo", http_client=wrapped_http
        )
    else:
        raw_wrapped = openai.OpenAI(
            api_key="mock-key-demo", http_client=wrapped_http
        )

    wrapped_client = Backstop.wrap(
        raw_wrapped,
        budget=budget,
        config=BackstopConfig(
            default_max_output_tokens=completion_tokens,
            retry_max_attempts=1,
            chars_per_token=5.0 if provider == "anthropic" else 4.0,
        ),
    )

    wrapped_completed = 0
    wrapped_blocked = 0
    wrapped_tokens = 0
    wrapped_exc: Exception | None = None
    t0 = time.perf_counter()
    for _ in range(calls):
        try:
            if provider == "anthropic":
                wrapped_client.messages.create(
                    model=target_model,
                    messages=[{"role": "user", "content": "runaway prompt"}],
                    max_tokens=completion_tokens,
                )
            else:
                wrapped_client.chat.completions.create(
                    model=target_model,
                    messages=[{"role": "user", "content": "runaway prompt"}],
                    max_tokens=completion_tokens,
                )
            wrapped_completed += 1
            wrapped_tokens += tokens_per_call
        except BudgetExceededError as exc:
            wrapped_blocked += 1
            if wrapped_exc is None:
                wrapped_exc = exc
        except Exception as exc:
            wrapped_blocked += 1
            if wrapped_exc is None:
                wrapped_exc = exc
    wrapped_duration = (time.perf_counter() - t0) * 1000
    try:
        raw_wrapped.close()
    except Exception:
        pass

    tokens_saved = (calls - wrapped_completed) * tokens_per_call
    wrapped_cost = cost_per_call * wrapped_completed
    delta_calls_saved = unprotected_completed - wrapped_completed
    delta_tokens_saved = unprotected_tokens - wrapped_tokens
    delta_cost_saved = unprotected_cost - wrapped_cost
    savings_pct = (
        (delta_tokens_saved / unprotected_tokens * 100.0)
        if unprotected_tokens > 0
        else 0.0
    )

    wrapped_metrics = LoopMetrics(
        calls_attempted=calls,
        calls_completed=wrapped_completed,
        calls_blocked=wrapped_blocked,
        tokens_consumed=wrapped_tokens,
        tokens_saved=tokens_saved,
        cost_usd=wrapped_cost,
        provider_calls=wrapped_transport.call_count,
        exception_name=type(wrapped_exc).__name__ if wrapped_exc else None,
        duration_ms=round(wrapped_duration, 2),
    )

    guardrail_enforced = (
        wrapped_blocked > 0
        and isinstance(wrapped_exc, BudgetExceededError)
        and wrapped_transport.call_count == wrapped_completed
    )

    return DemoResult(
        scenario="runaway_agent_loop",
        provider=provider,
        model=target_model,
        budget=budget,
        total_calls=calls,
        unprotected=unprotected_metrics,
        wrapped=wrapped_metrics,
        delta_calls_saved=delta_calls_saved,
        delta_tokens_saved=delta_tokens_saved,
        delta_cost_saved_usd=delta_cost_saved,
        savings_pct=round(savings_pct, 1),
        guardrail_enforced=guardrail_enforced,
        success=guardrail_enforced,
    )
