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
        # One lock for the whole record. It used to be taken twice — once to
        # compute the chain hash and again to write the line — so another
        # thread could append a record between the two. The file's order and
        # the chain's order then disagreed, and `verify()`, which replays the
        # chain in file order, failed on a log that had not been tampered
        # with. The hash covers the previous chain value, so computing it and
        # writing the line have to be one indivisible step.
        with self._lock:
            chain = _chain_hash(self._prev, payload, self._key)
            rec["_chain"] = chain
            self._prev = bytes.fromhex(chain)
            line = json.dumps(rec, sort_keys=True, default=str)
            if self._file is not None:
                self._file.write(line + "\n")
                self._file.flush()
            elif self._callable is not None:
                self._callable(line)
        return rec

    def verify(self, lines: list[str] | None = None) -> bool:
        """Replay the chain and report whether every record is intact.

        Returns ``False`` for anything that is not an intact chain, including
        a line that is not valid JSON, is missing its chain field, or carries a
        chain value that is not hex. It used to raise ``KeyError`` or
        ``ValueError`` on those, which is the opposite of what a verification
        function is for: a tampered log is a *failed verification*, and the
        caller has to be able to act on that.
        """
        prev = b""
        source = lines if lines is not None else self._read_lines()
        for line in source:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                payload = json.dumps(
                    {k: v for k, v in rec.items() if k != "_chain"}, sort_keys=True, default=str
                ).encode("utf-8")
                chain = _chain_hash(prev, payload, self._key)
                recorded = rec.get("_chain")
                if not isinstance(recorded, str) or chain != recorded:
                    return False
                prev = bytes.fromhex(recorded)
            except (ValueError, TypeError, KeyError, AttributeError):
                # A line that cannot be parsed, has no chain, or has a chain
                # that is not hex, is a broken chain. That is a failed
                # verification, not an exception for the caller to handle.
                return False
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
