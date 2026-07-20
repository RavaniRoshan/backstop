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


def make_gateway_app(target_base_url: str, budget: int | None, config: Any = None) -> Any:
    from fastapi import FastAPI, Request, Response

    from backstop.state import BackstopState
    from backstop.transports import AsyncBackstopTransport

    state = BackstopState.create(budget, config)
    app = FastAPI(title="Backstop Gateway")

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    async def proxy(request: Request, path: str):
        url = target_base_url.rstrip("/") + "/" + path
        headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
        body = await request.body()
        req = httpx.Request(request.method, url, content=body, headers=headers)
        transport = AsyncBackstopTransport(state, httpx.AsyncHTTPTransport())
        resp = await transport.handle_async_request(req)
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
        )

    return app
