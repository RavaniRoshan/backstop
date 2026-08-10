from __future__ import annotations

import json
import os
import tempfile

from backstop.audit_sink import (
    BigQueryAuditSink,
    FileAuditSink,
    S3AuditSink,
    VectorAuditSink,
    cloud_events_envelope,
    mask_pii,
    redact_pii_fields,
)


def test_cloud_events_envelope_has_required_fields():
    rec = {"ts": "2026-01-01T00:00:00Z", "decision": "deny", "reason": "budget_exceeded"}
    env = cloud_events_envelope(rec)
    assert env["specversion"] == "1.0"
    assert env["source"] == "backstop-sdk"
    assert env["type"] == "com.backstop.audit"
    assert env["data"] == rec
    assert "id" in env
    assert "time" in env


def test_pii_redaction_masks_keys_and_emails():
    text = "key sk-ABCDEFGHIJKLMNOPQRSTUVWX and user@example.com"
    out = mask_pii(text)
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in out
    assert "user@example.com" not in out
    assert "***REDACTED***" in out


def test_redact_pii_fields_masked():
    rec = {"api_key": "sk-ABCDEFGHIJKLMNOPQRSTUVWX", "decision": "deny", "model": "gpt-4"}
    out = redact_pii_fields(rec)
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in out["api_key"]
    assert out["decision"] == "deny"
    assert out["model"] == "gpt-4"


def test_file_audit_sink_writes_ndjson_with_envelope():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "audit.jsonl")
        sink = FileAuditSink(path, pii=True)
        sink.emit({"decision": "deny", "api_key": "sk-ABCDEFGHIJKLMNOPQRSTUVWX"})
        sink.close()
        with open(path, "r", encoding="utf-8") as fh:
            lines = [l.strip() for l in fh if l.strip()]
        assert len(lines) == 1
        env = json.loads(lines[0])
        assert env["type"] == "com.backstop.audit"
        assert env["data"]["decision"] == "deny"
        assert "sk-ABCDEFGHIJKLMNOPQRSTUVWX" not in env["data"].get("api_key", "")


def test_s3_sink_noop_without_boto():
    sink = S3AuditSink(bucket="my-bucket")
    sink.emit({"decision": "deny"})  # must not raise


def test_bigquery_sink_noop_without_client():
    sink = BigQueryAuditSink(dataset="ds", table="t", gcs_bucket="b")
    sink.emit({"decision": "deny"})  # must not raise


def test_vector_sink_noop_on_network_failure():
    sink = VectorAuditSink(endpoint="http://127.0.0.1:1/v1/events")
    sink.emit({"decision": "deny"})  # must not raise
