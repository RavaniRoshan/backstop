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
from typing import Any

import httpx

# Max request body size accepted by the gateway (1 MB). Prevents a client
# from forcing Backstop to cache or forward multi-megabyte payloads.
_MAX_BODY_BYTES = 1 * 1024 * 1024


def make_gateway_app(
    target_base_url: str,
    budget: int | None,
    config: Any = None,
    api_keys: set[str] | None = None,
    rate_limit_per_key: int | None = None,
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
        if api_keys is not None:
            key = _authorized(request)
            if key is None:
                return JSONResponse(
                    {"error": "unauthorized: valid Bearer token required"}, status_code=401,
                )

        # --- Rate limit ---
        if key and key in limiters:
            if not limiters[key].allow():
                return JSONResponse(
                    {"error": "rate limit exceeded"}, status_code=429,
                )

        # --- Body size guard ---
        body = await request.body()
        if len(body) > _MAX_BODY_BYTES:
            return JSONResponse(
                {"error": f"request body exceeds {_MAX_BODY_BYTES} bytes"}, status_code=413,
            )

        # --- Path guard: reject paths with '..' ---
        if ".." in path:
            return JSONResponse({"error": "invalid path"}, status_code=400)

        url = target_base_url.rstrip("/") + "/" + path
        headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
        req = httpx.Request(request.method, url, content=body, headers=headers)
        transport = AsyncBackstopTransport(state, httpx.AsyncHTTPTransport())
        try:
            resp = await transport.handle_async_request(req)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
        )

    return app
