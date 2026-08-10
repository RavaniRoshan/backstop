from __future__ import annotations

import json
import threading
import time

from backstop.notifications import BudgetAlertManager, WebhookSink


class _FakePost:
    def __init__(self, status=200, fail_times=0):
        self.status = status
        self.fail_times = fail_times
        self.calls = []
        self._lock = threading.Lock()

    def __call__(self, endpoint, body, headers):
        with self._lock:
            self.calls.append((endpoint, body, dict(headers)))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("simulated network error")
        return _Resp(self.status)


class _Resp:
    def __init__(self, status):
        self.status_code = status


def test_webhook_sink_signs_and_posts():
    fake = _FakePost(status=200)
    sink = WebhookSink(["http://example.test/hook"], secret="s3cr3t", http_post=fake)
    sink.send("threshold_crossed", {"tenant_id": "t1", "ratio": 0.9})
    assert len(fake.calls) == 1
    _, body, headers = fake.calls[0]
    assert headers["X-Backstop-Event"] == "threshold_crossed"
    assert headers["Webhook-Signature"].startswith("v1,")
    assert headers["Webhook-Id"]
    # signature must verify against the secret
    import hashlib
    import hmac

    signed = f"{headers['Webhook-Id']}.{headers['Webhook-Timestamp']}.".encode() + body
    expected = "v1," + hmac.new(b"s3cr3t", signed, hashlib.sha256).hexdigest()
    assert headers["Webhook-Signature"] == expected


def test_webhook_sink_retries_then_dlq():
    calls = []
    sink = WebhookSink(
        ["http://example.test/hook"], secret="k", http_post=_FakePost(status=500, fail_times=10),
        dlq=lambda payload, err: calls.append((payload, err)),
    )
    sink.send("budget_crossed", {"x": 1})
    assert len(calls) == 1  # DLQ invoked after exhaustion


def test_alert_tiers_fire_in_order_and_dedup():
    delivered = []
    mgr = BudgetAlertManager(
        endpoints=["http://x/h"], secret="k", tiers=[0.85, 0.95],
        sink=_Recorder(delivered), clock=lambda: 1000.0,
    )
    mgr.observe("team-a", used=900, limit=1000)  # ratio 0.9 -> crosses 0.85 only
    mgr.observe("team-a", used=960, limit=1000)  # 0.96 -> crosses 0.95
    mgr.observe("team-a", used=960, limit=1000)  # dedup: no new event
    types = [d["event"] for d in delivered]
    assert types.count("threshold_crossed") == 2
    assert ("team-a", "threshold_0.85") in mgr.fired_keys()
    assert ("team-a", "threshold_0.95") in mgr.fired_keys()


def test_alert_projected_exceeded_carries_calls_remaining():
    delivered = []
    mgr = BudgetAlertManager(
        endpoints=["http://x/h"], secret="k", project_horizon_calls=5,
        sink=_Recorder(delivered), clock=lambda: 1000.0,
    )
    # 1000 limit, 980 used, 10 tokens/call -> 2 calls remaining <= horizon
    mgr.observe("t1", used=980, limit=1000, burn_per_call=10)
    proj = [d for d in delivered if d["event"] == "projected_exceeded"]
    assert proj, "expected projected_exceeded event"
    assert proj[0]["payload"]["calls_remaining"] == 2


def test_alert_no_endpoints_is_noop():
    mgr = BudgetAlertManager(endpoints=None)
    mgr.observe("t1", used=999, limit=1000)  # must not raise


class _Recorder:
    def __init__(self, sink):
        self.sink = sink

    def send(self, event_type, payload):
        self.sink.append({"event": event_type, "payload": payload})
