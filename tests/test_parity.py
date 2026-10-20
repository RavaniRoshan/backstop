"""The sync and async transports must reach the same decisions.

Backstop ships two transports. They were written as near-duplicates of each
other, and they drifted: the async transport emitted 2 of the 7 enforcement
decisions the sync one did, its semantic cache was never constructed, and its
shadow mode consulted a different branch than the sync one. A user on
``AsyncOpenAI`` got a different guardrail than a user on ``OpenAI``, and
nothing in the test suite noticed.

This module is the guard that makes that impossible to reintroduce. It drives
both transports through the same scripted scenarios and asserts they produce
the same:

* **audit decisions**, in order — ``(decision, reason)`` pairs;
* **metric events**, by name *and* labels — the label is part of the contract,
  because a series with the wrong label is a series nobody queries;
* **outcome** — the same request either raises the same exception in both, or
  succeeds in both.

The scenarios live at the bottom of this file. Adding one is the cheapest way
to protect a new enforcement decision from being implemented on one side only.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from contextlib import nullcontext
from typing import Any, Callable

import httpx
import pytest

from backstop import BackstopConfig
from backstop.agent_guard import AgentGuard
from backstop.ledger import TenantBudget, get_ledger, reset_ledger, with_budget
from backstop.metrics import set_telemetry_sink
from backstop.state import BackstopState
from backstop.transports import AsyncBackstopTransport, BackstopTransport


class _Capture:
    """What one run of one transport produced."""

    def __init__(self) -> None:
        self.audit: list[tuple[str, str]] = []
        self.metrics: list[tuple[str, tuple]] = []
        self.outcome: str = "ok"

    # -- the AuditLog sink -----------------------------------------------
    # ``AuditLog`` accepts a callable and calls it with the JSON line.
    def __call__(self, line: str) -> None:
        rec = json.loads(line)
        self.audit.append((rec["decision"], rec["reason"]))

    # -- the shadow collector's sink -------------------------------------
    # ``ShadowCollector`` calls ``sink.record(decision, reason, **fields)``.
    def record(self, decision: str, reason: str, **_fields: Any) -> None:
        self.audit.append((decision, reason))

    def metric_sink(self, name: str, args: tuple, method: str, kwargs: dict) -> None:
        self.metrics.append((name, tuple(args)))

    def metric_counts(self) -> Counter:
        return Counter(self.metrics)


class _Scenario:
    """A scripted sequence of requests, plus the config and handler it runs under."""

    def __init__(
        self,
        name: str,
        config: BackstopConfig,
        handler: Callable[[httpx.Request], httpx.Response],
        bodies: list[dict],
        *,
        budget: int = 100_000,
        tenant: str | None = None,
        tenant_budget: Any | None = None,
    ) -> None:
        self.name = name
        self.config = config
        self.handler = handler
        self.bodies = bodies
        self.budget = budget
        #: The tenant every request in this scenario is attributed to, if any.
        self.tenant = tenant
        self.tenant_budget = tenant_budget


def _install_tenant(scenario: _Scenario) -> Any:
    """Register the scenario's tenant budget and return the scope to run under.

    The tenant ledger is a module-level singleton, so it is reset first: the
    sync run and the async run each get a clean budget, or the second run
    would start where the first one stopped and the comparison would be
    measuring the harness rather than the transports.
    """
    if scenario.tenant is None:
        return nullcontext()
    reset_ledger()
    if scenario.tenant_budget is not None:
        get_ledger().register({scenario.tenant: scenario.tenant_budget})
    return with_budget(scenario.tenant)


def _run_sync(scenario: _Scenario) -> _Capture:
    cap = _Capture()
    config = _replace_config(scenario.config, audit_sink=cap)
    state = BackstopState.create(scenario.budget, config)
    transport = BackstopTransport(state, httpx.MockTransport(scenario.handler), sleep=lambda _s: None)
    client = httpx.Client(transport=transport, base_url="https://mock.local")
    set_telemetry_sink(cap.metric_sink)
    try:
        with _install_tenant(scenario):
            for body in scenario.bodies:
                try:
                    client.post("/v1/responses", json=body)
                except Exception as exc:  # noqa: BLE001 - the outcome is the observation
                    cap.outcome = type(exc).__name__
                    break
    finally:
        set_telemetry_sink(None)
        client.close()
        state.close()
    return cap


async def _run_async(scenario: _Scenario) -> _Capture:
    cap = _Capture()
    config = _replace_config(scenario.config, audit_sink=cap)
    state = BackstopState.create(scenario.budget, config)
    transport = AsyncBackstopTransport(
        state, httpx.MockTransport(scenario.handler), sleep=_no_sleep
    )
    client = httpx.AsyncClient(transport=transport, base_url="https://mock.local")
    set_telemetry_sink(cap.metric_sink)
    try:
        with _install_tenant(scenario):
            for body in scenario.bodies:
                try:
                    await client.post("/v1/responses", json=body)
                except Exception as exc:  # noqa: BLE001 - the outcome is the observation
                    cap.outcome = type(exc).__name__
                    break
    finally:
        set_telemetry_sink(None)
        await client.aclose()
        state.close()
    return cap


async def _no_sleep(_seconds: float) -> None:
    return None


def _replace_config(config: BackstopConfig, **overrides: Any) -> BackstopConfig:
    """A copy of ``config`` with fields replaced.

    ``BackstopConfig`` is a frozen dataclass, so ``dataclasses.replace`` is the
    supported way to derive one. It re-runs ``__post_init__``, which is what we
    want: a derived config is validated exactly like a constructed one.
    """
    import dataclasses

    return dataclasses.replace(config, **overrides)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def _UNUSED_SINK(_line: str) -> None:
    """A placeholder audit sink.

    Every scenario replaces it with a per-run capture before the transport is
    built, but ``BackstopConfig`` validates the sink at construction time, so
    the scenario needs a valid one from the start.
    """
    return None


def _ok_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"usage": {"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2}},
    )


def _counting_handler(request: httpx.Request) -> httpx.Response:
    _counting_handler.calls += 1
    return httpx.Response(
        200,
        json={"usage": {"total_tokens": 5}, "n": _counting_handler.calls},
    )


_counting_handler.calls = 0


def _failing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, json={"error": "boom"})


def _embedder(text: str) -> list[float]:
    """A deliberately crude embedding: near-duplicate prompts collide."""
    return [float(len(text)), 1.0]


def _scenarios() -> list[_Scenario]:
    body = {"model": "gpt-4o", "input": "hello", "max_output_tokens": 1}
    big = {"model": "gpt-4o", "input": "hello", "max_output_tokens": 1000}

    return [
        _Scenario(
            "success",
            BackstopConfig(default_max_output_tokens=1, audit_enabled=True, audit_hmac_key="test-key", audit_sink=_UNUSED_SINK),
            _ok_handler,
            [body],
        ),
        _Scenario(
            "budget_deny",
            BackstopConfig(default_max_output_tokens=1, audit_enabled=True, audit_hmac_key="test-key", audit_sink=_UNUSED_SINK),
            _ok_handler,
            [body, big],
            budget=10,
        ),
        _Scenario(
            "budget_deny_shadow",
            BackstopConfig(
                default_max_output_tokens=1, audit_enabled=True, audit_hmac_key="test-key", audit_sink=_UNUSED_SINK, shadow=True
            ),
            _ok_handler,
            [body, big],
            budget=10,
        ),
        _Scenario(
            "rate_limited",
            BackstopConfig(
                default_max_output_tokens=1,
                audit_enabled=True, audit_hmac_key="test-key", audit_sink=_UNUSED_SINK,
                rate_limiter=type("AlwaysDeny", (), {"allow": staticmethod(lambda _t: False)})(),
            ),
            _ok_handler,
            [body],
        ),
        _Scenario(
            "agent_guardrail",
            BackstopConfig(
                default_max_output_tokens=1,
                audit_enabled=True, audit_hmac_key="test-key", audit_sink=_UNUSED_SINK,
                agent_guard=AgentGuard(max_calls=0),
            ),
            _ok_handler,
            [body],
        ),
        _Scenario(
            "circuit_open",
            BackstopConfig(
                default_max_output_tokens=1,
                audit_enabled=True, audit_hmac_key="test-key", audit_sink=_UNUSED_SINK,
                retry_max_attempts=1,
                circuit_min_requests=1,
                circuit_failure_threshold=1.0,
                circuit_cooldown_seconds=60.0,
            ),
            _failing_handler,
            [body, body],
        ),
        _Scenario(
            "semantic_cache_hit",
            BackstopConfig(
                default_max_output_tokens=1,
                audit_enabled=True, audit_hmac_key="test-key", audit_sink=_UNUSED_SINK,
                cache_enabled=True,
                cache_semantic=True,
                cache_embedder=_embedder,
                cache_similarity_threshold=0.5,
            ),
            _counting_handler,
            [
                {"model": "gpt-4o", "input": "hello", "max_output_tokens": 1},
                {"model": "gpt-4o", "input": "world", "max_output_tokens": 1},
            ],
        ),
        _Scenario(
            "tenant_downgrade",
            BackstopConfig(
                default_max_output_tokens=1,
                audit_enabled=True, audit_hmac_key="test-key", audit_sink=_UNUSED_SINK,
            ),
            _ok_handler,
            [big],
            budget=10_000,
            tenant="acme",
            tenant_budget=TenantBudget("acme", limit_tokens=10, on_exceed="downgrade"),
        ),
        _Scenario(
            "tenant_downgrade_shadow",
            BackstopConfig(
                default_max_output_tokens=1,
                audit_enabled=True, audit_hmac_key="test-key", audit_sink=_UNUSED_SINK,
                shadow=True,
            ),
            _ok_handler,
            [big],
            budget=10_000,
            tenant="acme",
            tenant_budget=TenantBudget("acme", limit_tokens=10, on_exceed="downgrade"),
        ),
    ]


# ---------------------------------------------------------------------------
# The parity assertions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda s: s.name)
def test_sync_and_async_reach_the_same_audit_decisions(scenario: _Scenario) -> None:
    """Both transports must record the same enforcement decisions, in the same order."""
    sync = _run_sync(scenario)
    async_ = asyncio.run(_run_async(scenario))
    assert sync.audit == async_.audit


@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda s: s.name)
def test_sync_and_async_reach_the_same_metrics(scenario: _Scenario) -> None:
    """Both transports must emit the same metric names and labels.

    Only the labels are compared, never the values: a latency or a queue-wait
    duration is a measurement of the host, not a contract. The name and the
    labels are the contract — they are what a dashboard and an alert query.
    """
    sync = _run_sync(scenario)
    async_ = asyncio.run(_run_async(scenario))
    assert sync.metric_counts() == async_.metric_counts()


@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda s: s.name)
def test_sync_and_async_reach_the_same_outcome(scenario: _Scenario) -> None:
    """The same request must succeed or fail identically on both paths."""
    sync = _run_sync(scenario)
    async_ = asyncio.run(_run_async(scenario))
    assert sync.outcome == async_.outcome
