"""Select the httpx-compatible module each wrapped SDK actually uses.

``openai>=3`` and ``anthropic>=1`` moved to ``httpx2``; older SDK majors use
``httpx``. The two modules expose the same transport API surface but their
objects are mutually incompatible — an SDK rejects an http client built from
the other module, so Backstop must build its transports from the module the
wrapped SDK itself uses.

The module is detected from the wrapped client's own internal HTTP client,
so the choice always matches the SDK in front of us. When ``httpx2`` is not
installed, only the classic ``httpx`` compatibility is available.
"""
from __future__ import annotations

from typing import Any

import httpx

try:  # httpx2 is optional: it arrives as a dependency of modern openai/anthropic SDKs
    import httpx2  # noqa: F401

    _HAS_HTTPX2 = True
except ImportError:  # pragma: no cover - exercised only on httpx-only installs
    httpx2 = None  # type: ignore[assignment]
    _HAS_HTTPX2 = False


class _HttpCompat:
    """Namespace exposing one httpx-compatible module's transport surface."""

    __slots__ = (
        "module",
        "name",
        "Client",
        "AsyncClient",
        "BaseTransport",
        "AsyncBaseTransport",
        "HTTPTransport",
        "AsyncHTTPTransport",
        "Request",
        "Response",
        "URL",
        "Timeout",
        "TimeoutException",
        "TransportError",
        "ConnectError",
        "ReadTimeout",
        "MockTransport",
    )

    def __init__(self, module: Any) -> None:
        self.module = module
        self.name = getattr(module, "__name__", "")
        self.Client = module.Client
        self.AsyncClient = module.AsyncClient
        self.BaseTransport = module.BaseTransport
        self.AsyncBaseTransport = module.AsyncBaseTransport
        self.HTTPTransport = module.HTTPTransport
        self.AsyncHTTPTransport = module.AsyncHTTPTransport
        self.Request = module.Request
        self.Response = module.Response
        self.URL = module.URL
        self.Timeout = module.Timeout
        self.TimeoutException = module.TimeoutException
        self.TransportError = module.TransportError
        self.ConnectError = module.ConnectError
        self.ReadTimeout = module.ReadTimeout
        self.MockTransport = module.MockTransport


HTTPX = _HttpCompat(httpx)
HTTPX2 = _HttpCompat(httpx2) if _HAS_HTTPX2 else None

# Module-level exports default to the classic httpx family: ``httpx`` is an
# unconditional dependency while ``httpx2`` is optional, so this is the only
# default that cannot fail on an httpx-only install. Per-client selection goes
# through :func:`compat_for` instead.
Client = HTTPX.Client
AsyncClient = HTTPX.AsyncClient
BaseTransport = HTTPX.BaseTransport
AsyncBaseTransport = HTTPX.AsyncBaseTransport
HTTPTransport = HTTPX.HTTPTransport
AsyncHTTPTransport = HTTPX.AsyncHTTPTransport
Request = HTTPX.Request
Response = HTTPX.Response
URL = HTTPX.URL
Timeout = HTTPX.Timeout
TimeoutException = HTTPX.TimeoutException
TransportError = HTTPX.TransportError
ConnectError = HTTPX.ConnectError
ReadTimeout = HTTPX.ReadTimeout
MockTransport = getattr(httpx, "MockTransport")


def compat_for(base_client: Any) -> _HttpCompat:
    """Return the compat module matching the SDK's own internal client.

    ``base_client`` is the wrapped SDK client's ``_client`` attribute. Its
    class ``__mro__`` names the module family (``httpx`` vs ``httpx2``) that
    built it, which is the module the SDK will accept back.
    """
    for cls in type(base_client).__mro__:
        root = getattr(cls, "__module__", "").partition(".")[0]
        if root == "httpx2":
            if HTTPX2 is None:
                break
            return HTTPX2
        if root == "httpx":
            return HTTPX
    return HTTPX


def module_root(obj: Any) -> str:
    """Return ``httpx`` or ``httpx2`` for an object, whichever built its type."""
    for cls in type(obj).__mro__:
        root = getattr(cls, "__module__", "").partition(".")[0]
        if root in ("httpx", "httpx2"):
            return root
    return ""
