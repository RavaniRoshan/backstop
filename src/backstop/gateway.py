"""Optional gateway / sidecar mode (Deep Research P2#10).

Backstop's enforcement lives in ``wrap()`` for in-process SDKs. For non-Python
services, multi-language fleets, or to make policy *non-bypassable*, run Backstop
as an OpenAI-compatible reverse proxy. The same policy engine (budget, circuit,
fallback, quotas, audit) wraps every forwarded request. FastAPI is an optional
extra: ``pip install "backstop[fastapi]"``.

Note: this module intentionally omits ``from __future__ import annotations`` so
the ``Request`` annotation resolves to the lazily-imported FastAPI class at
function-definition time (otherwise FastAPI would mis-bind it as a query param).
"""
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Max request body size accepted by the gateway (1 MB). Prevents a client
# from forcing Backstop to cache or forward multi-megabyte payloads.
_MAX_BODY_BYTES = 1 * 1024 * 1024

# Default ceiling on how long a single upstream call may take. Without it a
# hung provider holds the gateway request open indefinitely; one slow
# provider should not be able to exhaust the worker's concurrency.
_DEFAULT_UPSTREAM_TIMEOUT = 60.0

# RFC 7230 section 6.1 hop-by-hop headers are meaningful only for the single
# connection that carried them, so a proxy must not pass them on. Content
# headers are stripped too: they describe the body as it arrived on the
# inbound connection, not as httpx re-serialises it outbound (or as the
# client will read the response back).
_HOP_BY_HOP = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
})
_STRIP_REQUEST = _HOP_BY_HOP | {"host", "content-length", "content-encoding"}
_STRIP_RESPONSE = _HOP_BY_HOP | {"content-length", "content-encoding"}


def make_gateway_app(
    target_base_url: str,
    budget: int | None,
    config: Any = None,
    api_keys: set[str] | None = None,
    rate_limit_per_key: int | None = None,
    upstream_timeout: float = _DEFAULT_UPSTREAM_TIMEOUT,
) -> Any:
    """Build a FastAPI app that proxies requests through Backstop.

    Parameters
    ----------
    target_base_url:
        Upstream provider base URL, e.g. ``https://api.openai.com/v1``.
    budget:
        Token budget for the gateway. ``None`` means unlimited.
    config:
        Optional :class:`BackstopConfig` overrides.
    api_keys:
        If set, only requests presenting one of these keys in the
        ``Authorization: Bearer <key>`` header are allowed. ``None`` disables
        auth (open proxy — only for trusted networks).
    rate_limit_per_key:
        If set, each API key is limited to this many requests per minute.
        Requires ``api_keys`` to be configured.
    """
    from fastapi import FastAPI, Request, Response
    from fastapi.responses import JSONResponse

    from backstop.limiter import TokenBucketLimiter
    from backstop.state import BackstopState
    from backstop.transports import AsyncBackstopTransport

    state = BackstopState.create(budget, config)
    app = FastAPI(title="Backstop Gateway")

    # Per-key rate limiters: key -> TokenBucketLimiter
    limiters: dict[str, TokenBucketLimiter] = {}
    if rate_limit_per_key and api_keys:
        for key in api_keys:
            limiters[key] = TokenBucketLimiter(
                capacity=rate_limit_per_key, refill_per_sec=rate_limit_per_key / 60.0,
            )

    if api_keys is not None:

        def _authorized(request: Request) -> str | None:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                key = auth[7:].strip()
                if key in api_keys:
                    return key
            return None

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    async def proxy(request: Request, path: str):
        # --- Auth ---
        # Bound before the branch: the rate-limit check below reads it, and
        # with auth disabled this handler never assigns it.
        key: str | None = None
        if api_keys is not None:
            key = _authorized(request)
            if key is None:
                return JSONResponse(
                    {"error": "unauthorized: valid Bearer token required"}, status_code=401,
                )

        # --- Rate limit ---
        if key is not None and key in limiters:
            if not limiters[key].allow():
                return JSONResponse(
                    {"error": "rate limit exceeded"}, status_code=429,
                )

        # --- Path guard: reject traversal before touching the body ---
        if ".." in path:
            return JSONResponse({"error": "invalid path"}, status_code=400)

        # --- Body size guard ---
        # The declared length is checked first so an oversized body is
        # refused without being buffered; the buffered length is then
        # re-checked, because a client may lie about or omit Content-Length.
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > _MAX_BODY_BYTES:
            return JSONResponse(
                {"error": f"request body exceeds {_MAX_BODY_BYTES} bytes"}, status_code=413,
            )
        body = await request.body()
        if len(body) > _MAX_BODY_BYTES:
            return JSONResponse(
                {"error": f"request body exceeds {_MAX_BODY_BYTES} bytes"}, status_code=413,
            )

        url = target_base_url.rstrip("/") + "/" + path
        headers = {
            k: v for k, v in request.headers.items() if k.lower() not in _STRIP_REQUEST
        }
        # httpx carries the per-request deadline in the request extensions
        # rather than on the transport, and only when every phase is stated.
        deadline = httpx.Timeout(upstream_timeout)
        req = httpx.Request(
            request.method, url, content=body, headers=headers,
            extensions={"timeout": {
                "connect": deadline.connect,
                "read": deadline.read,
                "write": deadline.write,
                "pool": deadline.pool,
            }},
        )
        transport = AsyncBackstopTransport(state, httpx.AsyncHTTPTransport())
        try:
            resp = await transport.handle_async_request(req)
        except Exception:
            # The detail stays in the log. A reverse proxy echoing an
            # exception string to the client hands out internal hostnames,
            # URLs and file paths.
            logger.exception("gateway upstream call failed: %s %s", request.method, url)
            return JSONResponse(
                {"error": "upstream request failed"}, status_code=502,
            )
        try:
            content = await resp.aread()
        except Exception:
            logger.exception("gateway upstream body read failed: %s %s", request.method, url)
            return JSONResponse({"error": "upstream request failed"}, status_code=502)
        return Response(
            content=content,
            status_code=resp.status_code,
            headers={
                k: v for k, v in resp.headers.items() if k.lower() not in _STRIP_RESPONSE
            },
        )

    return app
