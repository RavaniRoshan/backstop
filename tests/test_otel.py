from __future__ import annotations

from backstop.otel import OtelMetrics


def test_exemplar_tracking_noop_when_disabled():
    m = OtelMetrics()
    assert not m.enabled
    m.record_exemplar("requests", "abc123")
    assert m.exemplar_for("requests") == "abc123"


def test_exemplar_tracking_set_and_get():
    m = OtelMetrics()
    m.record_exemplar("budget_exceeded", "trace-1")
    assert m.exemplar_for("budget_exceeded") == "trace-1"
    assert m.exemplar_for("cache_hits") is None


def test_exemplar_overwrite():
    m = OtelMetrics()
    m.record_exemplar("requests", "trace-a")
    m.record_exemplar("requests", "trace-b")
    assert m.exemplar_for("requests") == "trace-b"


def test_exemplar_thread_safety():
    import threading

    m = OtelMetrics()
    errors = []

    def writer(tid):
        try:
            for i in range(100):
                m.record_exemplar("requests", f"trace-{tid}-{i}")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_call_noop_when_disabled():
    m = OtelMetrics()
    m.call("requests", "api", "high", "deny")
    m.call("duration", "api", "high", amount=0.1)
    m.call("budget_exceeded")


def test_call_no_crash_on_unknown_metric():
    m = OtelMetrics()
    m.call("nonexistent_metric_xyz")
