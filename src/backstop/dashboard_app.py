"""Built-in dashboard HTTP app — stdlib-only WSGI.

A single-page operations view over the live state of *this* process: budgets,
AIMD concurrency, circuit state, per-session isolation, enforcement events.

Scope boundary (this is what keeps the README's non-goal honest): the dashboard
does not store, query, or retain anything. It renders state the process already
holds, from a bounded in-memory ring, and dies with the process. There is no
database, no query language, no user accounts, and it never mutates a budget or
a circuit. For retention and fleet-wide queries, export Prometheus/OTel to your own
monitoring stack — that path is unchanged.

Shape mirrors :func:`backstop.metrics.metrics_app`, so it can be mounted in an
existing WSGI/FastAPI app or run standalone behind the threaded stdlib server.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from socketserver import ThreadingMixIn
from typing import Any, Callable
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from .dashboard_ui import APP_CSS, APP_JS, PAGE_HTML
from .telemetry import (
    DEFAULT_SAMPLE_INTERVAL,
    Sampler,
    acquire_dashboard_sink,
    build_snapshot,
    release_dashboard_sink,
)

# Loopback is the only bind that needs no token. Anything else is a deliberate
# act, and the CLI refuses it without --token.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

_SECURITY_HEADERS = (
    (
        "Content-Security-Policy",
        "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    ),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
)


class Dashboard:
    """Owns the sampler (and optional demo workload) for one dashboard server."""

    def __init__(
        self,
        *,
        mode: str = "live",
        cost_model: str | None = None,
        audit: str | None = None,
        interval: float = DEFAULT_SAMPLE_INTERVAL,
        title: str = "Backstop dashboard",
        token: str | None = None,
        demo: Any = None,
        theme: str = "auto",
    ) -> None:
        if mode not in ("live", "demo"):
            raise ValueError(f"mode must be live or demo, got {mode!r}")
        if mode == "live" and demo is not None:
            raise ValueError("live mode cannot use a demo workload")
        if theme not in ("auto", "dark", "light"):
            raise ValueError(f"theme must be auto, dark or light, got {theme!r}")
        if mode == "demo":
            from .dashboard_demo import DemoWorkload

            if demo is None:
                demo = DemoWorkload()
            elif not isinstance(demo, DemoWorkload):
                raise ValueError("demo mode requires an isolated DemoWorkload")
        self.mode = mode
        self.cost_model = cost_model
        self.audit = audit
        self.title = title
        self.token = token
        self.theme = theme
        self.sampler = Sampler(interval)
        self._demo = demo
        self._sink = None
        self._lock = threading.Lock()
        self._started = False

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            if self._demo is not None:
                self._demo.start(interval=self.sampler.interval, cost_model=self.cost_model)
            else:
                self._sink = acquire_dashboard_sink()
                try:
                    self.sampler.start()
                except BaseException:
                    self.sampler.stop()
                    release_dashboard_sink(self._sink)
                    self._sink = None
                    raise
            self._started = True

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            if self._demo is not None:
                self._demo.stop()
            else:
                try:
                    self.sampler.stop()
                finally:
                    release_dashboard_sink(self._sink)
                    self._sink = None
            self._started = False

    def snapshot(self) -> dict[str, Any]:
        if self._demo is not None:
            return self._demo.snapshot()
        return build_snapshot(
            self.sampler, mode=self.mode, cost_model=self.cost_model, audit=self.audit
        )

    def page(self) -> str:
        return (
            PAGE_HTML.replace("__TITLE__", self.title)
            .replace("__MODE__", self.mode)
            .replace("__REFRESH__", str(int(self.sampler.interval * 1000)))
            .replace("__COST_MODEL__", self.cost_model or "")
            .replace("__THEME__", self.theme)
        )


def _respond(
    start_response: Callable,
    status: str,
    body: bytes,
    content_type: str,
    *,
    cache: str = "no-store",
    extra: tuple[tuple[str, str], ...] = (),
) -> list[bytes]:
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", cache),
    ]
    headers.extend(_SECURITY_HEADERS)
    headers.extend(extra)
    start_response(status, headers)
    return [body]


def _authorized(environ: dict[str, Any], token: str) -> bool:
    header = environ.get("HTTP_AUTHORIZATION", "")
    if not header.lower().startswith("bearer "):
        return False
    return hmac.compare_digest(header[7:].strip(), token)


def make_dashboard_app(dashboard: Dashboard) -> Callable:
    """Build the WSGI application for ``dashboard``.

    Routes: ``/`` (page), ``/api/snapshot`` (JSON, ETag-aware), ``/assets/*``,
    ``/healthz``. Every response carries a restrictive CSP with no external
    origins, so the dashboard cannot quietly fetch anything.
    """

    def app(environ: dict[str, Any], start_response: Callable) -> list[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        if method not in ("GET", "HEAD"):
            return _respond(
                start_response,
                "405 Method Not Allowed",
                b"",
                "text/plain; charset=utf-8",
                extra=(("Allow", "GET, HEAD"),),
            )

        if dashboard.token and not _authorized(environ, dashboard.token):
            return _respond(
                start_response,
                "401 Unauthorized",
                b"unauthorized",
                "text/plain; charset=utf-8",
                extra=(("WWW-Authenticate", 'Bearer realm="backstop-dashboard"'),),
            )

        path = environ.get("PATH_INFO", "/") or "/"
        if path in ("/", "/index.html"):
            return _respond(
                start_response,
                "200 OK",
                dashboard.page().encode("utf-8"),
                "text/html; charset=utf-8",
            )
        if path == "/assets/app.css":
            return _respond(
                start_response,
                "200 OK",
                APP_CSS.encode("utf-8"),
                "text/css; charset=utf-8",
                cache="public, max-age=300",
            )
        if path == "/assets/app.js":
            return _respond(
                start_response,
                "200 OK",
                APP_JS.encode("utf-8"),
                "text/javascript; charset=utf-8",
                cache="public, max-age=300",
            )
        if path == "/api/snapshot":
            return _snapshot(environ, start_response, dashboard)
        if path == "/healthz":
            return _health(start_response, dashboard)
        if path == "/favicon.ico":
            return _respond(start_response, "204 No Content", b"", "image/x-icon")
        return _respond(
            start_response, "404 Not Found", b"not found", "text/plain; charset=utf-8"
        )

    app.backstop_dashboard = dashboard  # type: ignore[attr-defined]
    return app


def _snapshot(environ: dict[str, Any], start_response: Callable, dashboard: Dashboard) -> list[bytes]:
    snapshot = dashboard.snapshot()
    payload = json.dumps(snapshot, separators=(",", ":"), default=str).encode("utf-8")
    # The ETag must not cover fields that move on every render even when nothing
    # changed — `generated_at`, `sample_age_s` (both recomputed per request) and
    # `uptime_s` — so a steady snapshot revalidates as 304 instead of forcing
    # every polling browser to re-download every second.
    _volatile = {"generated_at", "sample_age_s", "uptime_s"}
    tag_input = json.dumps(
        {k: v for k, v in snapshot.items() if k not in _volatile},
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    etag = '"' + hashlib.sha256(tag_input).hexdigest()[:32] + '"'
    if_none_match = environ.get("HTTP_IF_NONE_MATCH", "")
    if if_none_match and etag in [tag.strip() for tag in if_none_match.split(",")]:
        headers = [("ETag", etag), ("Cache-Control", "no-store")]
        headers.extend(_SECURITY_HEADERS)
        start_response("304 Not Modified", headers)
        return [b""]
    return _respond(
        start_response,
        "200 OK",
        payload,
        "application/json; charset=utf-8",
        extra=(("ETag", etag),),
    )


def _health(start_response: Callable, dashboard: Dashboard) -> list[bytes]:
    if dashboard._demo is not None:
        body = json.dumps(
            {
                "status": "ok",
                "mode": dashboard.mode,
                "stage": dashboard._demo.stage,
                "requests_driven": dashboard._demo.requests_driven,
                "sample_interval_s": dashboard.sampler.interval,
            }
        ).encode("utf-8")
    else:
        body = json.dumps(
            {
                "status": "ok",
                "mode": dashboard.mode,
                "uptime_s": round(max(0.0, time.time() - dashboard.sampler.started_at), 3),
                "samples": len(dashboard.sampler.series()),
                "sample_interval_s": dashboard.sampler.interval,
            }
        ).encode("utf-8")
    return _respond(start_response, "200 OK", body, "application/json; charset=utf-8")


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    """Threaded so a polling browser's parallel connections cannot serialise."""

    daemon_threads = True
    allow_reuse_address = True


class _QuietHandler(WSGIRequestHandler):
    """Silence per-request logging: the page polls every second by design."""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def serve(
    dashboard: Dashboard,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = False,
) -> None:
    """Serve the dashboard until interrupted. Blocks the calling thread."""
    if host not in _LOOPBACK_HOSTS and not dashboard.token:
        raise ValueError(
            f"refusing to bind {host!r} without a token; pass token=... or use "
            f"{DEFAULT_HOST}, because the dashboard exposes budget and traffic "
            "data to anyone who can reach the port"
        )
    app = make_dashboard_app(dashboard)
    server = None
    try:
        server = make_server(
            host,
            port,
            app,
            server_class=_ThreadingWSGIServer,
            handler_class=_QuietHandler,
        )
        dashboard.start()
        shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        url = f"http://{shown}:{server.server_port}/"
        print(f"Backstop dashboard listening on {url}")
        if dashboard.mode == "demo":
            print("Demo mode: isolated mock process, no API keys and no network calls.")
        if dashboard.token:
            print("Auth required: Authorization: Bearer <token>")
        if open_browser:
            try:
                import webbrowser

                webbrowser.open(url)
            except Exception:  # pragma: no cover - headless environments
                pass
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBackstop dashboard stopped.")
    finally:
        try:
            if server is not None:
                server.server_close()
        finally:
            dashboard.stop()


def dashboard_wsgi_app(
    *,
    demo: bool = False,
    runners: int = 3,
    **kwargs: Any,
) -> Callable:
    """Build, start, and return a mountable WSGI app.

    Use this to attach the dashboard to an existing server::

        app = FastAPI()
        app.mount("/", WSGIMiddleware(dashboard_wsgi_app()))

    In demo mode the mock workload runs in a spawned child process: the parent
    never registers demo sessions or installs a telemetry sink. Stopping the
    returned app (``app.backstop_dashboard.stop()``) therefore leaves any
    application-owned capture untouched.
    """
    workload = None
    if demo:
        from .dashboard_demo import DemoWorkload

        workload = DemoWorkload(runners=runners)
    dashboard = Dashboard(mode="demo" if demo else "live", demo=workload, **kwargs)
    app = make_dashboard_app(dashboard)
    dashboard.start()
    return app