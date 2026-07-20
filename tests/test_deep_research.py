"""Tests for the Deep-Research roadmap features (P1#3, P1#4, P1#5, P1#7, P1#12,
P2#8, P2#9, P2#11, P2#13) plus gateway scaffold.

Each feature is opt-in; the default path (tests elsewhere) is unchanged.
"""
from __future__ import annotations

import json

import httpx
import pytest

from backstop.agent_guard import AgentGuard
from backstop.audit import AuditLog
from backstop.config import BackstopConfig, Priority
from backstop.forecast import BurnSample, CostForecaster, detect_spend_anomaly, will_exhaust
from backstop.limiter import TokenBucketLimiter
from backstop.quotas import QuotaMonitor, parse_ratelimit_headers
from backstop.rollout import CanaryRouter, ShadowPolicy
from backstop.secrets import EnvSecretProvider, SecretProvider, StaticSecretProvider, resolve_secret
from backstop.state import BackstopState
from backstop.transports import AsyncBackstopTransport, BackstopTransport
from backstop.ledger import TenantBudget


# --- P2#8 audit log --------------------------------------------------------
def test_audit_log_tamper_evident_and_verifiable(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(str(path), hmac_key="secret")
    log.record("deny", "budget_exceeded", tenant_id="t1", tokens=12)
    log.record("fallback", "circuit_open", model="gpt-4o-mini")
    log.close()
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["decision"] == "deny"
    assert "_chain" in json.loads(lines[0])
    assert AuditLog(str(path), hmac_key="secret").verify()


def test_audit_log_detects_tampering(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(str(path), hmac_key="secret")
    log.record("deny", "budget_exceeded")
    log.close()
    lines = path.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["reason"] = "tampered"
    lines[0] = json.dumps(rec)
    path.write_text("\n".join(lines))
    assert not AuditLog(str(path), hmac_key="secret").verify()


def test_audit_log_callable_sink(tmp_path):
    records = []
    log = AuditLog(records.append, hmac_key="k")
    log.record("allow", "ok")
    assert len(records) == 1


# --- P1#5 cloud-quota auto-tuning -----------------------------------------
def test_parse_ratelimit_headers_openai_and_anthropic():
    headers = {
        "x-ratelimit-limit-requests": "100",
        "x-ratelimit-remaining-requests": "10",
        "anthropic-ratelimit-tokens-limit": "5000",
        "anthropic-ratelimit-tokens-remaining": "4000",
    }
    s = parse_ratelimit_headers(headers)
    assert s.requests_limit == 100
    assert s.requests_remaining == 10
    assert s.tokens_limit == 5000
    assert s.token_pressure == pytest.approx(0.2)
    assert s.request_pressure == pytest.approx(0.9)
    assert s.pressure == pytest.approx(0.9)


def test_quota_monitor_adjusts_aimd():
    from backstop.aimd import AIMDController

    cfg = BackstopConfig(initial_concurrency=8)
    aimd = AIMDController(cfg)
    mon = QuotaMonitor(pressure_threshold=0.85)
    mon.ingest({"x-ratelimit-limit-requests": "100", "x-ratelimit-remaining-requests": "5"})
    assert mon.adjust(aimd) is True
    assert aimd.current_limit < 8


# --- P1#7 forecasting ------------------------------------------------------
def test_forecast_will_exhaust_and_anomaly():
    sample = BurnSample(used_tokens=800, window_seconds=10)
    assert will_exhaust(sample, 1000, horizon_seconds=100) is True
    assert will_exhaust(sample, 1000, horizon_seconds=1) is False
    fore = CostForecaster(1000).forecast(800, 10, 100)
    assert fore["will_exhaust_within_horizon"] is True
    assert detect_spend_anomaly(10.0, 25.0, sensitivity=2.0) is True
    assert detect_spend_anomaly(10.0, 15.0, sensitivity=2.0) is False


# --- P1#12 rate limiter ----------------------------------------------------
def test_token_bucket_limiter_refill_and_deny():
    lim = TokenBucketLimiter(capacity=2, refill_per_sec=0)
    assert lim.allow(1) is True
    assert lim.allow(1) is True
    assert lim.allow(1) is False


# --- P2#9 secrets ----------------------------------------------------------
def test_secret_providers(monkeypatch):
    monkeypatch.setenv("BS_KEY", "v1")
    assert EnvSecretProvider().get("BS_KEY") == "v1"
    assert StaticSecretProvider({"a": "b"}).get("a") == "b"
    assert resolve_secret(StaticSecretProvider({"a": "b"}), "a") == "b"
    assert resolve_secret(lambda k: "x", "anything") == "x"

    class _Concrete(SecretProvider):
        def get(self, key):
            return "z"

    assert _Concrete().get("anything") == "z"


# --- P2#11 agent guard -----------------------------------------------------
def test_agent_guard_blocks_runaway():
    guard = AgentGuard(max_calls=2, window_seconds=60, max_tokens=100)
    assert guard.allow("a", 10) is True
    assert guard.allow("a", 10) is True
    assert guard.allow("a", 10) is False
    assert guard.allow("b", 10) is True


# --- P2#13 shadow / canary -------------------------------------------------
def test_shadow_policy_samples_and_canary_routes():
    sink = _Sink()
    shadow = ShadowPolicy(sample_rate=1.0, sink=sink)
    assert shadow.should_shadow()
    shadow.record("shadow", "x", tenant_id="t")
    assert sink.records and sink.records[0]["decision"] == "shadow"
    canary = CanaryRouter(sample_rate=1.0, candidate_chain=[{"model": "c"}])
    assert canary.route([{"model": "primary"}]) == [{"model": "c"}]


# --- P1#3 hierarchical budgets + virtual keys -----------------------------
def test_hierarchical_budget_rolls_up():
    parent = TenantBudget("org", 1000)
    child = TenantBudget("team", 100, parent=parent)
    t = child.reserve(50)
    assert child.reserved == 50 and parent.reserved == 50
    child.commit(t, 40)
    assert child.used == 40 and parent.used == 40


def test_hierarchical_parent_enforcement_rolls_back_child():
    parent = TenantBudget("org", 100)
    child = TenantBudget("team", 1000, parent=parent)
    with pytest.raises(Exception):
        child.reserve(150)  # parent can't cover it
    assert child.reserved == 0 and parent.reserved == 0


def test_config_virtual_key_resolution():
    cfg = BackstopConfig(virtual_keys={"ak_1": "tenant_A"})
    assert cfg.tenant_for_key("ak_1") == "tenant_A"
    assert cfg.tenant_for_key("unknown") is None


# --- P1#12 tiktoken auto-estimation ---------------------------------------
def test_auto_token_count_uses_tiktoken_when_enabled():
    from backstop.extract import count_tokens, estimate_tokens

    body = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hello world"}]}
    raw = json.dumps(body).encode()
    cfg_auto = BackstopConfig(auto_token_count=True, default_max_output_tokens=1)
    cfg_manual = BackstopConfig(
        token_counter=lambda text, model: count_tokens(text, model), default_max_output_tokens=1
    )
    auto = estimate_tokens(body, raw, cfg_auto)
    manual = estimate_tokens(body, raw, cfg_manual)
    assert auto == manual
    assert auto >= 1


# --- config validation ----------------------------------------------------
def test_audit_config_requires_sink_and_key():
    with pytest.raises(ValueError):
        BackstopConfig(audit_enabled=True)
    with pytest.raises(ValueError):
        BackstopConfig(audit_enabled=True, audit_sink=lambda s: None)


# --- P1#4 per-tenant circuit wiring ---------------------------------------
def test_per_tenant_circuit_returns_distinct_breakers():
    cfg = BackstopConfig(per_tenant_circuit=True)
    state = BackstopState.create(1000, cfg)
    a = state.circuit_for("tenant_a")
    b = state.circuit_for("tenant_b")
    assert a is not b
    assert state.circuit_for(None) is state.circuit


# --- transport wiring: rate limiter, agent guard, shadow, quota, audit ----
class _Deny:
    def allow(self, *args):
        return False


class _Sink:
    def __init__(self):
        self.records: list = []

    def record(self, decision: str, reason: str, **fields):
        self.records.append({"decision": decision, "reason": reason, **fields})


def _make_sync_client(cfg, handler):
    state = BackstopState.create(1000, cfg)
    return httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )


def test_rate_limiter_denies_request():
    from backstop.exceptions import RateLimitError

    cfg = BackstopConfig(rate_limiter=_Deny(), default_max_output_tokens=1)
    client = _make_sync_client(cfg, lambda r: httpx.Response(200, json={"ok": True}))
    with pytest.raises(RateLimitError):
        client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})


def test_agent_guard_denies_request():
    from backstop.exceptions import GuardrailViolationError

    cfg = BackstopConfig(agent_guard=_Deny(), default_max_output_tokens=1)
    client = _make_sync_client(cfg, lambda r: httpx.Response(200, json={"ok": True}))
    with pytest.raises(GuardrailViolationError):
        client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Backstop-Agent": "agent-1"},
        )


def test_shadow_policy_records_sampled_request():
    sink = _Sink()
    cfg = BackstopConfig(shadow_policy=ShadowPolicy(sample_rate=1.0, sink=sink), default_max_output_tokens=1)
    client = _make_sync_client(cfg, lambda r: httpx.Response(200, json={"ok": True}))
    client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert any(r.get("decision") == "shadow" for r in sink.records)


def test_quota_ingest_adjusts_aimd_on_response():
    cfg = BackstopConfig(default_max_output_tokens=1)  # quota_aware default True
    state = BackstopState.create(1000, cfg)
    start = state.aimd.current_limit

    def handler(request):
        return httpx.Response(
            200,
            json={"ok": True, "usage": {"total_tokens": 3}},
            headers={"x-ratelimit-limit-requests": "100", "x-ratelimit-remaining-requests": "3"},
        )

    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )
    client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert state.quota is not None and state.quota.last is not None
    assert state.quota.last.request_pressure > 0.85
    assert state.aimd.current_limit < start


def test_compress_hook_transforms_request_body():
    seen = {}

    def compress(body, model):
        seen["model"] = body.get("model")
        new = dict(body)
        new["model"] = "compressed-model"
        return new

    cfg = BackstopConfig(compress=compress, default_max_output_tokens=1)
    state = BackstopState.create(1000, cfg)

    def handler(request):
        seen["received"] = json.loads(request.content).get("model")
        return httpx.Response(200, json={"ok": True, "usage": {"total_tokens": 1}})

    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )
    client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert seen["received"] == "compressed-model"


def test_audit_records_deny_on_budget_exceeded(tmp_path):
    path = tmp_path / "audit.jsonl"
    cfg = BackstopConfig(
        audit_enabled=True, audit_sink=str(path), audit_hmac_key="k",
        default_max_output_tokens=1, chars_per_token=40,
    )
    state = BackstopState.create(5, cfg)

    def handler(request):
        return httpx.Response(200, json={"usage": {"total_tokens": 5}, "ok": True})

    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )
    # First request (estimate ~2) fits; after commit the 5-token budget is
    # exhausted, so the second request is denied and audited.
    client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "x"}]})
    with pytest.raises(Exception):
        client.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "x"}]})
    lines = path.read_text().splitlines()
    assert any(json.loads(l)["decision"] == "deny" for l in lines)
    assert AuditLog(str(path), hmac_key="k").verify()


# --- P1#6 framework adapters ----------------------------------------------
def test_backstop_adapter_bridge_is_framework_agnostic():
    from backstop.adapters import BackstopAdapter

    adapter = BackstopAdapter(BackstopConfig(), tenant_id="t1")
    start = adapter.on_llm_start("gpt-4o", 12)
    assert start["model"] == "gpt-4o" and start["tenant_id"] == "t1"
    end = adapter.on_llm_end("gpt-4o", 10, 20)
    assert end["completion_tokens"] == 20


def test_langchain_adapter_factory_requires_framework():
    from backstop.adapters import get_langchain_handler

    try:
        import langchain_core  # noqa: F401

        handler = get_langchain_handler(BackstopConfig(), tenant_id="t")
        assert handler is not None
    except ImportError:
        with pytest.raises(ImportError):
            get_langchain_handler(BackstopConfig())
    from backstop.ledger import get_ledger, reset_ledger

    reset_ledger()
    ledger = get_ledger()
    ledger.register({"team_a": TenantBudget("team_a", 5)})
    cfg = BackstopConfig(
        virtual_keys={"ak_a": "team_a"}, default_max_output_tokens=1, chars_per_token=40
    )
    state = BackstopState.create(1000, cfg)

    def handler(request):
        return httpx.Response(200, json={"usage": {"total_tokens": 5}, "ok": True})

    client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(handler)),
        base_url="https://mock.local",
    )
    r = client.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "x"}]},
        headers={"X-Backstop-Key": "ak_a"},
    )
    assert r.status_code == 200
    reset_ledger()


# --- P2#10 gateway scaffold (requires fastapi) ----------------------------
def test_gateway_proxies_through_backstop():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from backstop.gateway import make_gateway_app

    cfg = BackstopConfig(default_max_output_tokens=1)
    captured = {}

    def handler(request):
        captured["model"] = json.loads(request.content).get("model")
        return httpx.Response(200, json={"ok": True, "usage": {"total_tokens": 2}})

    mock = httpx.MockTransport(handler)
    app = make_gateway_app("https://api.openai.com/v1", 1000, cfg)
    from backstop.transports import AsyncBackstopTransport

    orig = AsyncBackstopTransport.__init__

    def patched(self, state, transport=None, **kw):
        orig(self, state, mock, **kw)

    AsyncBackstopTransport.__init__ = patched
    try:
        client = TestClient(app)
        resp = client.post(
            "/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        assert captured.get("model") == "gpt-4o"
    finally:
        AsyncBackstopTransport.__init__ = orig
