"""Tamper-evident audit log (Deep Research P2#8).

Every enforcement decision (deny / fallback / downgrade / cache_hit) is appended
as a JSON record whose integrity is chained: each record carries an HMAC of its
own payload plus the previous record's chain hash. `verify()` replays the chain
and detects any tampering. This is the enterprise "escape hatch" that makes
in-process enforcement audit-ready and closes the supply-chain / audit gap the
research flagged (e.g. the March-2026 LiteLLM incident class).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from typing import Any, Callable


def _chain_hash(prev: bytes, payload: bytes, key: bytes) -> str:
    mac = hmac.new(key, prev + payload, hashlib.sha256).hexdigest()
    return hashlib.sha256((prev.hex() + mac).encode()).hexdigest()


class AuditLog:
    def __init__(self, sink: str | Callable[[str], None], hmac_key: str | None = None) -> None:
        self._key = (hmac_key or "").encode("utf-8")
        self._prev = b""
        self._lock = threading.Lock()
        self._file = open(sink, "a", encoding="utf-8") if isinstance(sink, str) else None
        self._callable = sink if callable(sink) else None

    def record(self, decision: str, reason: str, **fields: Any) -> dict:
        rec = {"ts": time.time(), "decision": decision, "reason": reason}
        if fields:
            rec.update(fields)
        payload = json.dumps(rec, sort_keys=True, default=str).encode("utf-8")
        with self._lock:
            chain = _chain_hash(self._prev, payload, self._key)
            rec["_chain"] = chain
            self._prev = bytes.fromhex(chain)
        line = json.dumps(rec, sort_keys=True, default=str)
        with self._lock:
            if self._file is not None:
                self._file.write(line + "\n")
                self._file.flush()
            elif self._callable is not None:
                self._callable(line)
        return rec

    def verify(self, lines: list[str] | None = None) -> bool:
        prev = b""
        source = lines if lines is not None else self._read_lines()
        for line in source:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            payload = json.dumps(
                {k: v for k, v in rec.items() if k != "_chain"}, sort_keys=True, default=str
            ).encode("utf-8")
            chain = _chain_hash(prev, payload, self._key)
            if chain != rec.get("_chain"):
                return False
            prev = bytes.fromhex(rec["_chain"])
        return True

    def _read_lines(self) -> list[str]:
        if self._file is None:
            return []
        path = self._file.name
        self._file.flush()
        with open(path, "r", encoding="utf-8") as fh:
            return fh.readlines()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
