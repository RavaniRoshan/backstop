"""Structured audit sinks (Launch Improvement C1).

Extends the hash-chained ``AuditLog`` with:
* a CloudEvents v1.0.2 envelope over each record (sink-agnostic routing),
* a PII redaction transform applied before emit,
* concrete sinks: local NDJSON file (default), S3 (Iceberg-style dt= layout),
  BigQuery (batch-load via GCS), Vector/OTel (HTTP OTLP).

The hash chain is preserved inside the CloudEvents ``data`` payload so the
local audit remains the source of truth. Sinks are fire-and-forget callables
so they can never break the request path.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

# CloudEvents envelope spec (v1.0.2): id, source, type, specversion, data, time.

_CE_SPEC = "1.0"
_CE_TYPE = "com.backstop.audit"
_CE_SOURCE = "backstop-sdk"
_PII_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|xox[baprs]-[A-Za-z0-9-]+|ghp_[A-Za-z0-9_]{36,}"
    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def mask_pii(text: str) -> str:
    return _PII_RE.sub("***REDACTED***", text)


def redact_pii_fields(record: dict, fields: tuple[str, ...] = ("api_key", "key", "token", "authorization")) -> dict:
    out = dict(record)
    for f in fields:
        if f in out and isinstance(out[f], str):
            out[f] = mask_pii(out[f])
    return out


def cloud_events_envelope(record: dict, source: str = _CE_SOURCE, ce_type: str = _CE_TYPE) -> dict:
    return {
        "specversion": _CE_SPEC,
        "id": record.get("_chain", hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()),
        "source": source,
        "type": ce_type,
        "time": record.get("ts", _now_iso()),
        "data": record,
    }


class AuditSink(ABC):
    @abstractmethod
    def emit(self, record: dict) -> None:
        ...


class FileAuditSink(AuditSink):
    def __init__(self, path: str, pii: bool = True) -> None:
        self._path = path
        self._pii = pii
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._fh = open(path, "a", encoding="utf-8")

    def emit(self, record: dict) -> None:
        payload = redact_pii_fields(record) if self._pii else record
        envelope = cloud_events_envelope(payload)
        line = json.dumps(envelope, sort_keys=True, default=str)
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None


class S3AuditSink(AuditSink):
    """Fire-and-forget S3 sink with Iceberg-style dt=YYYY/MM/DD partitioning.

    Activated only when ``boto3`` is installed and ``s3_bucket`` is set.
    Falls back to a no-op otherwise so the request path is never broken.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "audit",
        pii: bool = True,
        object_lock: bool = False,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix
        self._pii = pii
        self._object_lock = object_lock
        self._boto = None
        try:
            import boto3  # type: ignore

            self._boto = boto3
        except Exception:
            pass

    def emit(self, record: dict) -> None:
        if self._boto is None:
            return
        try:
            payload = redact_pii_fields(record) if self._pii else record
            envelope = cloud_events_envelope(payload)
            ts = envelope.get("time", _now_iso())
            dt = ts[:10].replace("-", "/")
            key = f"{self._prefix}/{dt}/{envelope['id']}.json"
            kwargs: dict[str, Any] = {"Bucket": self._bucket, "Key": key, "Body": json.dumps(envelope).encode()}
            if self._object_lock:
                kwargs["ObjectLockMode"] = "COMPLIANCE"
            s3 = self._boto.client("s3")
            s3.put_object(**kwargs)
        except Exception:
            pass


class BigQueryAuditSink(AuditSink):
    """Batch-load into BigQuery (free via GCS load jobs).

    Activated only when ``google-cloud-bigquery`` + ``google-cloud-storage`` are
    installed and ``gcs_bucket`` is set. Otherwise a no-op.
    """

    def __init__(self, dataset: str, table: str, gcs_bucket: str, pii: bool = True) -> None:
        self._dataset = dataset
        self._table = table
        self._gcs = gcs_bucket
        self._pii = pii
        self._bq = None
        try:
            from google.cloud import bigquery  # type: ignore
            from google.cloud import storage  # type: ignore

            self._bq = bigquery
            self._gcs_client = storage.Client()
        except Exception:
            pass
        self._buffer: list[str] = []
        self._lock = threading.Lock()

    def emit(self, record: dict) -> None:
        if self._bq is None:
            return
        payload = redact_pii_fields(record) if self._pii else record
        envelope = cloud_events_envelope(payload)
        line = json.dumps(envelope, sort_keys=True, default=str)
        with self._lock:
            self._buffer.append(line)
            if len(self._buffer) >= 100:
                self._flush()

    def _flush(self) -> None:
        if not self._buffer or self._bq is None:
            return
        blob_name = f"audit/{time.strftime('%Y%m%d-%H%M%S')}.ndjson"
        try:
            bucket = self._gcs_client.bucket(self._gcs)
            blob = bucket.blob(blob_name)
            blob.upload_from_string("\n".join(self._buffer) + "\n")
            table_ref = f"{self._dataset}.{self._table}"
            job_config = self._bq.LoadJobConfig(source_format=self._bq.SourceFormat.NEWLINE_DELIMITED_JSON, autodetect=True)
            client = self._bq.Client()
            client.load_table_from_uri(f"gs://{self._gcs}/{blob_name}", table_ref, job_config=job_config)
        except Exception:
            pass
        finally:
            self._buffer = []

    def close(self) -> None:
        with self._lock:
            self._flush()


class VectorAuditSink(AuditSink):
    """Send audit events to a Vector/OTel collector over HTTP."""

    def __init__(self, endpoint: str, pii: bool = True, timeout: float = 5.0) -> None:
        self._endpoint = endpoint
        self._pii = pii
        self._timeout = timeout

    def emit(self, record: dict) -> None:
        try:
            payload = redact_pii_fields(record) if self._pii else record
            envelope = cloud_events_envelope(payload)
            body = json.dumps([envelope], default=str).encode()
            headers = {"Content-Type": "application/json"}
            import httpx

            with httpx.Client(timeout=self._timeout) as c:
                c.post(self._endpoint, content=body, headers=headers)
        except Exception:
            pass
