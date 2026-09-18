"""Multi-target fallback chain + priority routing.

Backstop used to support a single ``fallback_model`` (circuit-open -> one
backup deployment). The roadmap's P0#2 promotes this to an ordered
``fallback_chain`` (optionally priority-aware) walked within the same process.
"""
from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from backstop.config import BackstopConfig, Priority
from backstop.circuit import CircuitState
from backstop.latency import _LatencyTracker
from backstop.ledger import TenantBudget, get_ledger, reset_ledger, with_budget
from backstop.notifications import BudgetAlertManager
from backstop.state import BackstopState
from backstop.transports import AsyncBackstopTransport, BackstopTransport, _build_fallback_request


def _meta(priority: Priority = Priority.DEFAULT) -> SimpleNamespace:
    return SimpleNamespace(
        endpoint="/v1/chat/completions",
        priority=priority,
        estimated_tokens=10,
    )


def _tracker() -> _LatencyTracker:
    return _LatencyTracker()


def _request(model: str = "primary", headers: dict | None = None) -> httpx.Request:
    return httpx.Request(
        "POST",
        "https://example.local/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": "hi"}]},
        headers=headers or {},
    )


def _sink(captured: list) -> SimpleNamespace:
    return SimpleNamespace(send=lambda et, p: captured.append((et, p)))


# --- config resolution -----------------------------------------------------
def test_fallback_targets_single_pair() -> None:
    cfg = BackstopConfig(fallback_model="b1", fallback_base_url="https://fb")
    assert cfg.fallback_targets() == [{"model": "b1", "base_url": "https://fb"}]


def test_fallback_chain_overrides_single_pair() -> None:
    cfg = BackstopConfig(
        fallback_model="b1",
        fallback_chain=[{"model": "c1"}, {"model": "c2", "base_url": "https://fb2"}],
    )
    assert cfg.fallback_targets() == [{"model": "c1"}, {"model": "c2", "base_url": "https://fb2"}]


def test_priority_routing_selects_dedicated_chain() -> None:
    cfg = BackstopConfig(
        fallback_chain=[{"model": "c1"}],
        fallback_chain_for_priority={"critical": [{"model": "p1"}]},
    )
    assert cfg.fallback_targets(Priority.CRITICAL) == [{"model": "p1"}]
    assert cfg.fallback_targets(Priority.DEFAULT) == [{"model": "c1"}]
    assert cfg.fallback_targets(Priority.BACKGROUND) == [{"model": "c1"}]


# --- request rewriting -----------------------------------------------------
def test_build_fallback_request_repoints_model_and_url() -> None:
    req = _request("primary")
    fb = _build_fallback_request(req, "alt", "https://fb.local")
    body = json.loads(fb.content)
    assert body["model"] == "alt"
    assert str(fb.url).startswith("https://fb.local/")


def test_build_fallback_request_keeps_url_without_base() -> None:
    req = _request("primary")
    fb = _build_fallback_request(req, "alt", None)
    assert json.loads(fb.content)["model"] == "alt"
    assert str(fb.url).startswith("https://example.local/")


# --- chain walking ---------------------------------------------------------
def test_try_fallback_walks_chain_until_success() -> None:
    state = BackstopState.create(1000, BackstopConfig(fallback_chain=[{"model": "b1"}, {"model": "b2"}]))
    tried: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        tried.append(model)
        if model == "b1":
            raise httpx.ConnectError("down")
        return httpx.Response(200, content=json.dumps({"ok": True, "usage": {"total_tokens": 3}}).encode())

    transport = BackstopTransport(state, httpx.MockTransport(handler))
    resp = transport._try_fallback(_request("primary"), _meta(), None, None, _tracker(), {})
    assert resp is not None
    assert json.loads(resp.content)["ok"] is True
    assert tried == ["b1", "b2"]  # first failed, second succeeded


def test_try_fallback_all_fail_returns_none() -> None:
    state = BackstopState.create(1000, BackstopConfig(fallback_chain=[{"model": "b1"}]))

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    transport = BackstopTransport(state, httpx.MockTransport(handler))
    assert transport._try_fallback(_request("primary"), _meta(), None, None, _tracker(), {}) is None


def test_try_fallback_single_model_backcompat() -> None:
    state = BackstopState.create(1000, BackstopConfig(fallback_model="b1"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps({"ok": True, "usage": {"total_tokens": 3}}).encode())

    transport = BackstopTransport(state, httpx.MockTransport(handler))
    resp = transport._try_fallback(_request("primary"), _meta(), None, None, _tracker(), {})
    assert resp is not None


def test_try_fallback_no_config_returns_none() -> None:
    state = BackstopState.create(1000, BackstopConfig())
    transport = BackstopTransport(state, httpx.MockTransport(lambda r: httpx.Response(200)))
    assert transport._try_fallback(_request("primary"), _meta(), None, None, _tracker(), {}) is None


def test_try_fallback_priority_routing_end_to_end() -> None:
    cfg = BackstopConfig(
        fallback_chain=[{"model": "default1"}],
        fallback_chain_for_priority={"critical": [{"model": "prio1"}, {"model": "prio2"}]},
    )
    state = BackstopState.create(1000, cfg)
    tried: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tried.append(json.loads(request.content)["model"])
        if tried[-1] == "prio1":
            raise httpx.ConnectError("down")
        return httpx.Response(200, content=json.dumps({"ok": True, "usage": {"total_tokens": 1}}).encode())

    transport = BackstopTransport(state, httpx.MockTransport(handler))
    resp = transport._try_fallback(_request("primary"), _meta(Priority.CRITICAL), None, None, _tracker(), {})
    assert resp is not None
    assert tried == ["prio1", "prio2"]


# --- fallback budget alerts (regression) ------------------------------------
def _budget_crossed(captured: list, timeout: float = 2.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for event_type, payload in captured:
            if event_type == "budget_crossed":
                return payload
        time.sleep(0.05)
    return None


def _alert_handler() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"] != "b1":
            raise httpx.ConnectError("down")
        return httpx.Response(
            200, content=json.dumps({"ok": True, "usage": {"total_tokens": 1000}}).encode()
        )

    return httpx.MockTransport(handler)


def _drain_circuit(transport, request: httpx.Request) -> httpx.Response:
    # Probe until the circuit actually opens: failures are counted both in
    # _send_with_retries and by the outer handler, so the exact call count
    # that trips the breaker is an implementation detail. Once OPEN, the next
    # request is short-circuited into the fallback chain.
    circuit = transport.state.circuit
    for _ in range(20):
        if circuit.state is CircuitState.OPEN:
            break
        with pytest.raises(httpx.ConnectError):
            transport.handle_request(request)
    assert circuit.state is CircuitState.OPEN
    return transport.handle_request(request)


def test_fallback_success_fires_tenant_budget_alert() -> None:
    cfg = BackstopConfig(fallback_chain=[{"model": "b1"}], retry_max_attempts=1, default_max_output_tokens=1)
    state = BackstopState.create(1000, cfg)
    get_ledger().register({"tenant-a": TenantBudget("tenant-a", 1000)})
    captured: list = []

    transport = BackstopTransport(state, _alert_handler())
    transport._alerts = BudgetAlertManager(endpoints=[], sink=_sink(captured))
    try:
        with with_budget("tenant-a"):
            resp = _drain_circuit(transport, _request("primary"))
        assert json.loads(resp.content)["ok"] is True

        payload = _budget_crossed(captured)
        assert payload is not None, "fallback success must fire a budget_crossed alert"
        assert payload["tenant_id"] == "tenant-a"
        assert payload["used"] == 1000
        assert payload["limit"] == 1000
    finally:
        reset_ledger()


def test_fallback_success_fires_tenant_budget_alert_async() -> None:
    cfg = BackstopConfig(fallback_chain=[{"model": "b1"}], retry_max_attempts=1, default_max_output_tokens=1)
    state = BackstopState.create(1000, cfg)
    get_ledger().register({"tenant-a": TenantBudget("tenant-a", 1000)})
    captured: list = []

    transport = AsyncBackstopTransport(state, _alert_handler())
    transport._alerts = BudgetAlertManager(endpoints=[], sink=_sink(captured))

    async def scenario() -> httpx.Response:
        circuit = transport.state.circuit
        with with_budget("tenant-a"):
            for _ in range(20):
                if circuit.state is CircuitState.OPEN:
                    break
                with pytest.raises(httpx.ConnectError):
                    await transport.handle_async_request(_request("primary"))
            assert circuit.state is CircuitState.OPEN
            return await transport.handle_async_request(_request("primary"))

    try:
        resp = asyncio.run(scenario())
        assert json.loads(resp.content)["ok"] is True

        payload = _budget_crossed(captured)
        assert payload is not None, "async fallback success must fire a budget_crossed alert"
        assert payload["tenant_id"] == "tenant-a"
        assert payload["used"] == 1000
        assert payload["limit"] == 1000
    finally:
        reset_ledger()


def test_fallback_success_fires_global_budget_alert() -> None:
    cfg = BackstopConfig(fallback_chain=[{"model": "b1"}], retry_max_attempts=1, default_max_output_tokens=1)
    state = BackstopState.create(1000, cfg)
    captured: list = []

    transport = BackstopTransport(state, _alert_handler())
    transport._alerts = BudgetAlertManager(endpoints=[], sink=_sink(captured))

    resp = _drain_circuit(transport, _request("primary"))
    assert json.loads(resp.content)["ok"] is True

    payload = _budget_crossed(captured)
    assert payload is not None, "global-budget fallback success must fire a budget_crossed alert"
    assert payload["tenant_id"] == ""
    assert payload["used"] >= payload["limit"] == 1000
    assert state.budget.spent == 1000
    assert state.budget.remaining == 0


def test_fallback_alert_uses_virtual_key_tenant() -> None:
    cfg = BackstopConfig(
        fallback_chain=[{"model": "b1"}],
        retry_max_attempts=1,
        default_max_output_tokens=1,
        virtual_keys={"sk-vk-1": "tenant-vk"},
    )
    state = BackstopState.create(1000, cfg)
    get_ledger().register({"tenant-vk": TenantBudget("tenant-vk", 1000)})
    captured: list = []

    transport = BackstopTransport(state, _alert_handler())
    transport._alerts = BudgetAlertManager(endpoints=[], sink=_sink(captured))
    try:
        with with_budget("ctx-tenant"):
            req_headers = {"X-Backstop-Key": "sk-vk-1"}
            resp = _drain_circuit(transport, _request("primary", headers=req_headers))
        assert json.loads(resp.content)["ok"] is True

        payload = _budget_crossed(captured)
        assert payload is not None, "fallback success must fire a budget_crossed alert"
        assert payload["tenant_id"] == "tenant-vk"
    finally:
        reset_ledger()
