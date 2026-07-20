from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any


_HYPERPARAMS = frozenset({
    "temperature", "top_p", "max_tokens", "max_output_tokens", "max_completion_tokens",
    "n", "stop", "frequency_penalty", "presence_penalty", "seed", "logit_bias",
})

Embedder = Callable[[str], "list[float]"]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class ResponseCache:
    def __init__(
        self,
        max_entries: int = 256,
        ttl: float = 60.0,
        embed: Embedder | None = None,
        similarity_threshold: float = 0.95,
    ) -> None:
        self._max = max_entries
        self._ttl = ttl
        self._embed = embed
        self._sim = similarity_threshold
        # key -> (stored_at, content, usage, headers)
        self._cache: OrderedDict[str, tuple[float, bytes, int, dict[str, str]]] = OrderedDict()
        # key -> embedding (only when ``embed`` is provided)
        self._embeddings: dict[str, list[float]] = {}
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

    def get(self, body: dict[str, Any]) -> tuple[bytes, int, dict[str, str] | None, bool] | None:
        """Return ``(content, usage, headers, semantic_hit)`` or ``None``.

        Exact match is the fast path. On an exact miss, when an embedder is
        configured, a near-duplicate prompt (cosine >= ``similarity_threshold``)
        is returned and flagged as a semantic hit.
        """
        key = self._make_key(body)
        with self._lock:
            if key in self._cache:
                stored_at, content, usage, headers = self._cache[key]
                if time.monotonic() - stored_at > self._ttl:
                    self._evict(key)
                else:
                    self._cache.move_to_end(key)
                    return content, usage, headers, False
            if self._embed is None:
                return None
            return self._semantic_get(body)

    def _semantic_get(self, body: dict[str, Any]) -> tuple[bytes, int, dict[str, str] | None, bool] | None:
        text = self._embed_text(body)
        try:
            q_emb = self._embed(text)
        except Exception:
            return None
        best_key: str | None = None
        best_score = self._sim
        now = time.monotonic()
        expired: list[str] = []
        for k, (stored_at, content, usage, headers) in self._cache.items():
            if now - stored_at > self._ttl:
                expired.append(k)
                continue
            emb = self._embeddings.get(k)
            if emb is None:
                continue
            score = _cosine(q_emb, emb)
            if score >= best_score:
                best_score = score
                best_key = k
                best_value = (content, usage, headers)
        for k in expired:
            self._evict(k)
        if best_key is None:
            return None
        self._cache.move_to_end(best_key)
        return best_value[0], best_value[1], best_value[2], True

    def _embed_text(self, body: dict[str, Any]) -> str:
        messages = self._messages_from_body(body)
        data = json.dumps(messages, sort_keys=True) if messages else ""
        return f"{self._model_from_body(body)}:{data}"

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
            if self._embed is not None:
                try:
                    self._embeddings[key] = self._embed(self._embed_text(body))
                except Exception:
                    self._embeddings.pop(key, None)

    def _evict(self, key: str) -> None:
        self._cache.pop(key, None)
        self._embeddings.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._embeddings.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)
