from __future__ import annotations

from typing import Any, TypeVar

import httpx

from .config import BackstopConfig
from .exceptions import UnsupportedClientError
from .metrics import metrics_app, start_metrics_server
from .state import BackstopState
from .transports import AsyncBackstopTransport, BackstopTransport

T = TypeVar("T")

_SUPPORTED_OPENAI = frozenset({"OpenAI", "AsyncOpenAI"})
_SUPPORTED_ANTHROPIC = frozenset({"Anthropic", "AsyncAnthropic"})  # fmt: skip


class Backstop:
    @staticmethod
    def wrap(client: T, budget: int | None = 50_000, config: BackstopConfig | None = None) -> T:
        existing = getattr(client, "_backstop_state", None)
        if existing is not None:
            return client

        cls = client.__class__
        provider = _detect_provider(cls)
        if not provider:
            raise UnsupportedClientError(
                "Backstop v1 supports openai.OpenAI, openai.AsyncOpenAI, "
                "anthropic.Anthropic, and anthropic.AsyncAnthropic clients only"
            )

        state = BackstopState.create(budget, config)
        if provider == "anthropic":
            if cls.__name__ == "AsyncAnthropic":
                wrapped_http_client = _build_async_anthropic_http_client(client, state)
            else:
                wrapped_http_client = _build_sync_anthropic_http_client(client, state)
            wrapped = _clone_anthropic_client(client, wrapped_http_client)
        else:
            if cls.__name__ == "AsyncOpenAI":
                wrapped_http_client = _build_async_http_client(client, state)
            else:
                wrapped_http_client = _build_sync_http_client(client, state)
            wrapped = _clone_openai_client(client, wrapped_http_client)

        setattr(wrapped, "_backstop_state", state)
        return wrapped

    start_metrics_server = staticmethod(start_metrics_server)
    metrics_app = staticmethod(metrics_app)


def _detect_provider(cls: type) -> str:
    module = getattr(cls, "__module__", "")
    name = getattr(cls, "__name__", "")
    if module.startswith("openai") and name in _SUPPORTED_OPENAI:
        return "openai"
    if module.startswith("anthropic") and name in _SUPPORTED_ANTHROPIC:
        return "anthropic"
    return ""


def _clone_openai_client(client: Any, http_client: httpx.Client | httpx.AsyncClient) -> Any:
    if hasattr(client, "with_options"):
        for kwargs in (
            {"http_client": http_client, "max_retries": 0},
            {"http_client": http_client},
        ):
            try:
                return client.with_options(**kwargs)
            except TypeError:
                continue

    kwargs: dict[str, Any] = {"http_client": http_client}
    for attr in (
        "api_key",
        "organization",
        "project",
        "base_url",
        "timeout",
        "max_retries",
        "default_headers",
        "default_query",
    ):
        if hasattr(client, attr):
            kwargs[attr] = getattr(client, attr)
    try:
        kwargs["max_retries"] = 0
        return client.__class__(**kwargs)
    except TypeError:
        kwargs.pop("max_retries", None)
        try:
            return client.__class__(**kwargs)
        except Exception as exc:
            raise UnsupportedClientError(
                "could not rebuild OpenAI client with a Backstop http_client"
            ) from exc


def _clone_anthropic_client(client: Any, http_client: httpx.Client | httpx.AsyncClient) -> Any:
    if hasattr(client, "copy"):
        for kwargs in (
            {"http_client": http_client, "max_retries": 0},
            {"http_client": http_client},
        ):
            try:
                return client.copy(**kwargs)
            except TypeError:
                continue

    kwargs: dict[str, Any] = {"http_client": http_client}
    for attr in (
        "api_key",
        "base_url",
        "timeout",
        "max_retries",
        "default_headers",
        "default_query",
    ):
        if hasattr(client, attr):
            kwargs[attr] = getattr(client, attr)
    try:
        kwargs["max_retries"] = 0
        return client.__class__(**kwargs)
    except TypeError:
        kwargs.pop("max_retries", None)
        try:
            return client.__class__(**kwargs)
        except Exception as exc:
            raise UnsupportedClientError(
                "could not rebuild Anthropic client with a Backstop http_client"
            ) from exc


def _build_sync_anthropic_http_client(client: Any, state: BackstopState) -> httpx.Client:
    base = getattr(client, "_client", None)
    underlying = _sync_transport_from(base)
    return httpx.Client(
        transport=BackstopTransport(state, underlying),
        timeout=_timeout_from(base),
        base_url=_base_url_from(base),
    )


def _build_async_anthropic_http_client(client: Any, state: BackstopState) -> httpx.AsyncClient:
    base = getattr(client, "_client", None)
    underlying = _async_transport_from(base)
    return httpx.AsyncClient(
        transport=AsyncBackstopTransport(state, underlying),
        timeout=_timeout_from(base),
        base_url=_base_url_from(base),
    )


def _build_sync_http_client(client: Any, state: BackstopState) -> httpx.Client:
    base = getattr(client, "_client", None)
    underlying = _sync_transport_from(base)
    return httpx.Client(
        transport=BackstopTransport(state, underlying),
        timeout=_timeout_from(base),
        base_url=_base_url_from(base),
    )


def _build_async_http_client(client: Any, state: BackstopState) -> httpx.AsyncClient:
    base = getattr(client, "_client", None)
    underlying = _async_transport_from(base)
    return httpx.AsyncClient(
        transport=AsyncBackstopTransport(state, underlying),
        timeout=_timeout_from(base),
        base_url=_base_url_from(base),
    )


def _sync_transport_from(base: Any) -> httpx.BaseTransport:
    transport = getattr(base, "_transport", None)
    if isinstance(transport, httpx.BaseTransport):
        return transport
    return httpx.HTTPTransport()


def _async_transport_from(base: Any) -> httpx.AsyncBaseTransport:
    transport = getattr(base, "_transport", None)
    if isinstance(transport, httpx.AsyncBaseTransport):
        return transport
    return httpx.AsyncHTTPTransport()


def _timeout_from(base: Any) -> httpx.Timeout:
    timeout = getattr(base, "timeout", None)
    if isinstance(timeout, httpx.Timeout):
        return timeout
    return httpx.Timeout(60.0)


def _base_url_from(base: Any) -> str:
    base_url = getattr(base, "base_url", None)
    return str(base_url) if base_url is not None else ""

