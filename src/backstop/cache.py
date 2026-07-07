from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from typing import Any


_HYPERPARAMS = frozenset({
    "temperature", "top_p", "max_tokens", "max_output_tokens", "max_completion_tokens",
    "n", "stop", "frequency_penalty", "presence_penalty", "seed", "logit_bias",
})


class ResponseCache:
    def __init__(self, max_entries: int = 256, ttl: float = 60.0) -> None:
        self._max = max_entries
        self._ttl = ttl
        self._cache: OrderedDict[str, tuple[float, bytes, int, dict[str, str]]] = OrderedDict()
        self._lock = threading.Lock()

    def _model_from_body(self, body: dict[str, Any]) -> str:
        return str(body.get("model", "unknown"))

    def _messages_from_body(self, body: dict[str, Any]) -> list | dict | None:
        for key in ("messages", "input", "prompt"):
            value = body.get(key)
            if value is not None:
                return value
        return None

    def _hyperparams_from_body(self, body: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in sorted(_HYPERPARAMS):
            if key in body:
                parts.append(f"{key}={json.dumps(body[key], sort_keys=True)}")
        return ",".join(parts)

    def _make_key(self, body: dict[str, Any]) -> str:
        model = self._model_from_body(body)
        messages = self._messages_from_body(body)
        data = json.dumps(messages, sort_keys=True) if messages else ""
        hyper = self._hyperparams_from_body(body)
        if hyper:
            return f"{model}:{data}:{hyper}"
        return f"{model}:{data}"

    def get(self, body: dict[str, Any]) -> tuple[bytes, int, dict[str, str] | None] | None:
        key = self._make_key(body)
        with self._lock:
            if key not in self._cache:
                return None
            stored_at, content, usage, headers = self._cache[key]
            if time.monotonic() - stored_at > self._ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return content, usage, headers

    def set(self, body: dict[str, Any], content: bytes, usage: int, headers: dict[str, str] | None = None) -> None:
        key = self._make_key(body)
        stored_headers: dict[str, str] = {}
        if headers is not None:
            for k, v in headers.items():
                if k.lower() in {"content-type", "content-encoding", "x-request-id"} or k.lower().startswith("x-"):
                    stored_headers[k] = v
        with self._lock:
            while len(self._cache) >= self._max:
                self._cache.popitem(last=False)
            self._cache[key] = (time.monotonic(), content, usage, stored_headers)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)
