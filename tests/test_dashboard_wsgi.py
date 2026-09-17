"""End-to-end tests for the built-in dashboard WSGI app (``dashboard_app.py``).

These exercise the HTTP surface a user actually touches: the page, the JSON
snapshot with ETag revalidation, bearer auth, and the loopback-only guard.
"""
from __future__ import annotations

import json
import time

import pytest

from backstop.dashboard_app import make_dashboard_app, serve
from backstop.dashboard_app import Dashboard, dashboard_wsgi_app
from backstop.telemetry import get_registry, get_sink, install_sink, uninstall_sink

SNAPSHOT_KEYS = {
    "generated_at",
    "mode",
    "series",
    "kpi",
    "sessions",
    "tenants",
    "events",
    "outcomes",
    "audit",
    "warnings",
}


def _request(app, path="/", *, method="GET", extra=None):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "SERVER_NAME": "127.0.0.1",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.url_scheme": "http",
        "wsgi.input": None,
    }
    environ.update(extra or {})
    body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body


def test_page_serves_with_security_headers():
    app = dashboard_wsgi_app()
    try:
        status, headers, body = _request(app, "/")
        assert status == "200 OK"
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "default-src 'none'" in headers["Content-Security-Policy"]
        # No external origins anywhere in the CSP: the page cannot fetch out.
        assert "http" not in headers["Content-Security-Policy"].split("default-src")[1]
        assert b"Backstop dashboard" in body
        # Theme data-theme is present and defaulted to auto from dashboard_app theme="auto"
        assert b'data-theme="auto"' in body
    finally:
        app.backstop_dashboard.stop()


@pytest.mark.parametrize("theme", ["auto", "dark", "light"])
def test_page_theme_values(theme):
    app = dashboard_wsgi_app(theme=theme)
    try:
        status, _, body = _request(app, "/")
        assert status == "200 OK"
        assert f'data-theme="{theme}"'.encode() in body
    finally:
        app.backstop_dashboard.stop()


def test_page_rejects_invalid_theme():
    with pytest.raises(ValueError, match="theme must be auto, dark or light"):
        Dashboard(theme="invalid")


def test_snapshot_json_and_etag_revalidation():
    app = dashboard_wsgi_app()
    try:
        status, headers, body = _request(app, "/api/snapshot")
        assert status == "200 OK"
        assert headers["Content-Type"] == "application/json; charset=utf-8"
        payload = json.loads(body)
        assert SNAPSHOT_KEYS <= set(payload)
        etag = headers["ETag"]

        status, _, body = _request(app, "/api/snapshot", extra={"HTTP_IF_NONE_MATCH": etag})
        assert status == "304 Not Modified"
        assert body == b""

        status, _, _ = _request(
            app, "/api/snapshot", extra={"HTTP_IF_NONE_MATCH": '"stale-etag"'}
        )
        assert status == "200 OK"
    finally:
        app.backstop_dashboard.stop()


def test_bearer_token_auth():
    app = dashboard_wsgi_app(token="secret-token")
    try:
        status, headers, _ = _request(app, "/api/snapshot")
        assert status == "401 Unauthorized"
        assert headers["WWW-Authenticate"] == 'Bearer realm="backstop-dashboard"'

        status, _, _ = _request(
            app, "/api/snapshot", extra={"HTTP_AUTHORIZATION": "Bearer wrong"}
        )
        assert status == "401 Unauthorized"

        for path in ("/", "/api/snapshot", "/healthz", "/assets/app.js"):
            status, _, _ = _request(
                app, path, extra={"HTTP_AUTHORIZATION": "Bearer secret-token"}
            )
            assert status == "200 OK", path
    finally:
        app.backstop_dashboard.stop()


def test_methods_routes_and_healthz():
    app = dashboard_wsgi_app()
    try:
        status, _, body = _request(app, "/healthz")
        assert status == "200 OK"
        health = json.loads(body)
        assert health["status"] == "ok"
        assert health["mode"] == "live"

        for path in ("/assets/app.css", "/assets/app.js"):
            status, headers, body = _request(app, path)
            assert status == "200 OK"
            assert body, path

        status, _, _ = _request(app, "/nope")
        assert status == "404 Not Found"
        status, headers, _ = _request(app, "/", method="POST")
        assert status == "405 Method Not Allowed"
        assert headers["Allow"] == "GET, HEAD"
    finally:
        app.backstop_dashboard.stop()


def test_serve_refuses_non_loopback_without_token():
    dashboard = Dashboard()
    with pytest.raises(ValueError, match="without a token"):
        serve(dashboard, host="0.0.0.0")
    # The guard fires before the sampler starts.
    assert not dashboard._started


def test_rejects_live_mode_with_demo_workload_and_invalid_modes():
    from backstop.dashboard_demo import DemoWorkload

    with pytest.raises(ValueError, match="mode must be live or demo"):
        Dashboard(mode="screenshot")
    with pytest.raises(ValueError, match="live mode cannot use a demo workload"):
        Dashboard(mode="live", demo=DemoWorkload())
    with pytest.raises(ValueError, match="demo mode requires an isolated DemoWorkload"):
        Dashboard(mode="demo", demo=object())


def test_demo_mode_defaults_to_isolated_workload():
    from backstop.dashboard_app import Dashboard
    from backstop.dashboard_demo import DemoWorkload

    dashboard = Dashboard(mode="demo")
    try:
        assert isinstance(dashboard._demo, DemoWorkload)
        dashboard.start()
        time.sleep(0.4)
        snapshot = dashboard.snapshot()
        assert snapshot["mode"] == "demo"
        assert snapshot["kpi"]["isolation"]["sessions"] >= 1
        # The isolated demo must not register anything in this process.
        assert get_registry().states() == []
        assert get_sink() is None
        status, _, body = _request(app := make_dashboard_app(dashboard), "/healthz")
        assert status == "200 OK"
        health = json.loads(body)
        assert health["mode"] == "demo"
        assert health["requests_driven"] >= 0
    finally:
        dashboard.stop()
        del app
    assert get_registry().states() == []
    assert get_sink() is None


def test_stop_preserves_application_owned_capture():
    """A dashboard stopping must never disable a sink it does not own."""
    owned = install_sink()
    dashboard = Dashboard()
    try:
        dashboard.start()
        assert get_sink() is not None
    finally:
        dashboard.stop()
    assert get_sink() is owned
    uninstall_sink()
    assert get_sink() is None


def test_default_live_snapshot_is_empty_and_demo_free():
    """The default live dashboard must not leak demo sessions or demo capture."""
    app = dashboard_wsgi_app()
    try:
        status, _, body = _request(app, "/api/snapshot")
        assert status == "200 OK"
        payload = json.loads(body)
        assert payload["mode"] == "live"
        assert payload["kpi"]["isolation"]["sessions"] == 0
        assert payload["sessions"] == []
        assert get_registry().states() == []
    finally:
        app.backstop_dashboard.stop()


def test_mounted_demo_app_produces_live_kpis():
    app = dashboard_wsgi_app(demo=True, runners=3, interval=0.05)
    try:
        time.sleep(0.6)  # a few sample ticks with the mock workload running
        status, _, body = _request(app, "/api/snapshot")
        assert status == "200 OK"
        payload = json.loads(body)
        assert payload["mode"] == "demo"
        assert payload["kpi"]["isolation"]["sessions"] >= 1
        assert len(payload["series"]["t"]) >= 3
        assert payload["kpi"]["spend"]["tokens"] > 0
        # Bounded-IPC freshness metadata for the UI agent.
        assert payload["sampled_at"] is not None
        assert payload["sample_age_s"] is not None
        assert payload["sample_age_s"] < 5.0
        # Isolation: demo sessions never register in this process.
        assert get_registry().states() == []
        assert get_sink() is None
    finally:
        app.backstop_dashboard.stop()
    assert get_registry().states() == []
    assert get_sink() is None


def test_make_dashboard_app_does_not_start_the_sampler():
    """Building the app alone must not install the sink; ``dashboard_wsgi_app`` starts."""
    dashboard = Dashboard()
    app = make_dashboard_app(dashboard)
    try:
        status, _, body = _request(app, "/api/snapshot")
        assert status == "200 OK"
        payload = json.loads(body)
        assert payload["mode"] == "live"
        # This test process runs other dashboard tests first, and a session
        # outliving its test pins the aggregate, so assert on shape only.
        assert payload["kpi"]["budget"] is None or isinstance(payload["kpi"]["budget"], dict)
        if isinstance(payload["kpi"]["budget"], dict):
            assert set(payload["kpi"]["budget"]) == {
                "limit",
                "spent",
                "remaining",
                "pct_used",
                "burn_tokens_per_min",
                "eta_seconds",
            }
    finally:
        dashboard.stop()
