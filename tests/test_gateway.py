"""Security and behaviour tests for the gateway reverse proxy.

These run against a real local HTTP server rather than a mock transport, because
the defects this file guards against are exactly the ones a mock hides: an
unbound local that never fires until a real request arrives, and a streaming
response whose body is not yet read.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("fastapi", reason="gateway requires the fastapi extra")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from backstop import BackstopConfig  # noqa: E402
from backstop.gateway import _MAX_BODY_BYTES, make_gateway_app  # noqa: E402


class _Upstream(BaseHTTPRequestHandler):
    """Echoes the request back as JSON so assertions can inspect what arrived."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # silence the default stderr logging
        pass

    def _respond(self, payload: dict, status: int = 200, extra: dict | None = None):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        if self.path.startswith("/hang"):
            time.sleep(30)
            return
        if self.path.startswith("/boom"):
            self._respond({"error": "upstream exploded"}, status=500)
            return
        self._respond({
            "method": self.command,
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": body.decode("utf-8", "replace"),
        }, extra={"x-upstream": "yes"})

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _handle


@pytest.fixture(scope="module")
def upstream():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _client(upstream: str, **kwargs) -> TestClient:
    app = make_gateway_app(upstream, 10**6, BackstopConfig(), **kwargs)
    return TestClient(app, raise_server_exceptions=False)


# --- the default configuration must actually serve ----------------------------


def test_the_default_open_configuration_serves_a_request(upstream):
    """Regression: with auth disabled the rate-limit check read an unbound local.

    ``key`` was only assigned inside ``if api_keys is not None``, so the default
    ``serve`` -- the configuration the docs lead with -- raised NameError and
    returned HTTP 500 on every single request.
    """
    with _client(upstream) as client:
        resp = client.get("/v1/models")
    assert resp.status_code == 200, resp.text
    assert resp.json()["path"] == "/v1/models"


def test_the_default_configuration_serves_a_post_with_a_body(upstream):
    with _client(upstream) as client:
        resp = client.post("/v1/chat/completions", json={"model": "gpt-4o"})
    assert resp.status_code == 200, resp.text
    assert json.loads(resp.json()["body"]) == {"model": "gpt-4o"}


def test_a_closed_upstream_returns_502_not_500(upstream):
    """A dead upstream is a gateway problem (502), never a crash (500)."""
    with _client("http://127.0.0.1:1") as client:
        resp = client.get("/v1/models")
    assert resp.status_code == 502


# --- authentication ------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"authorization": "Bearer wrong"},
        {"authorization": "wrong"},
        {"authorization": "Bearer "},
        {"authorization": "Basic k1"},
    ],
    ids=["missing", "wrong-key", "no-scheme", "empty", "wrong-scheme"],
)
def test_a_bad_credential_is_rejected(upstream, headers):
    with _client(upstream, api_keys={"k1", "k2"}) as client:
        resp = client.get("/v1/models", headers=headers)
    assert resp.status_code == 401


def test_a_valid_credential_is_accepted(upstream):
    with _client(upstream, api_keys={"k1", "k2"}) as client:
        assert client.get("/v1/models", headers={"authorization": "Bearer k1"}).status_code == 200
        assert client.get("/v1/models", headers={"authorization": "Bearer k2"}).status_code == 200


def test_the_bearer_scheme_is_matched_case_insensitively(upstream):
    with _client(upstream, api_keys={"k1"}) as client:
        resp = client.get("/v1/models", headers={"authorization": "bearer k1"})
    assert resp.status_code == 200


# --- rate limiting -------------------------------------------------------------


def test_the_rate_limit_is_charged_to_the_key_that_made_the_request(upstream):
    """Two keys, one request each. Neither key may spend the other's budget."""
    with _client(upstream, api_keys={"k1", "k2"}, rate_limit_per_key=1) as client:
        codes = [
            client.get("/v1/models", headers={"authorization": f"Bearer {k}"}).status_code
            for k in ("k1", "k2", "k1", "k2")
        ]
    assert codes == [200, 200, 429, 429]


def test_rate_limiting_survives_a_rejected_key_in_the_mix(upstream):
    """An unauthenticated request must not consume a valid key's budget."""
    with _client(upstream, api_keys={"k1"}, rate_limit_per_key=1) as client:
        assert client.get("/v1/models").status_code == 401
        assert client.get("/v1/models", headers={"authorization": "Bearer nope"}).status_code == 401
        assert client.get("/v1/models", headers={"authorization": "Bearer k1"}).status_code == 200
        assert client.get("/v1/models", headers={"authorization": "Bearer k1"}).status_code == 429


def test_a_rate_limiter_without_keys_configured_does_not_break_the_route(upstream):
    """``rate_limit_per_key`` with auth disabled must not raise on every request."""
    with _client(upstream, rate_limit_per_key=5) as client:
        assert client.get("/v1/models").status_code == 200


# --- request guards ------------------------------------------------------------


def test_an_oversized_body_is_refused(upstream):
    payload = {"model": "gpt-4o", "pad": "x" * (_MAX_BODY_BYTES + 1024)}
    with _client(upstream) as client:
        resp = client.post("/v1/chat/completions", content=json.dumps(payload),
                           headers={"content-type": "application/json"})
    assert resp.status_code == 413
    assert "exceeds" in resp.json()["error"]


def test_an_oversized_declared_length_is_refused_without_buffering(upstream):
    """A lying Content-Length must not get a multi-gigabyte body buffered."""
    with _client(upstream) as client:
        resp = client.post(
            "/v1/chat/completions", content=b"x" * 16,
            headers={"content-length": str(_MAX_BODY_BYTES * 100)},
        )
    assert resp.status_code == 413


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/%2e%2e/etc/passwd",
        "/v1/%2e%2e/%2e%2e%2fsecret",
        "/%2E%2E/admin",
    ],
    ids=["encoded", "encoded-slash", "uppercase"],
)
def test_path_traversal_is_refused(upstream, path):
    # Percent-encoded, because a literal "../" is collapsed by the HTTP client
    # before the request leaves it and would test the client, not the gateway.
    with _client(upstream) as client:
        resp = client.get(path)
    assert resp.status_code == 400
    assert "invalid path" in resp.json()["error"]


# --- header hygiene ------------------------------------------------------------


def test_hop_by_hop_and_content_headers_are_not_forwarded(upstream):
    """Connection-scoped headers must not cross the proxy in either direction."""
    with _client(upstream, api_keys={"k1"}) as client:
        resp = client.get(
            "/v1/models",
            headers={
                "authorization": "Bearer k1",
                "connection": "close",
                "keep-alive": "timeout=5",
                "transfer-encoding": "chunked",
                "upgrade": "websocket",
                "proxy-authorization": "Basic Zm9v",
            },
        )
    assert resp.status_code == 200, resp.text
    seen = resp.json()["headers"]
    for stripped in ("connection", "keep-alive", "upgrade", "proxy-authorization"):
        assert stripped not in seen, f"{stripped} leaked upstream"
    # The client's credential must still reach the provider.
    assert seen["authorization"] == "Bearer k1"


def test_the_inbound_host_header_is_not_forwarded(upstream):
    with _client(upstream) as client:
        resp = client.get("/v1/models", headers={"host": "evil.example.com"})
    assert resp.status_code == 200
    assert resp.json()["headers"]["host"].startswith("127.0.0.1")


def test_the_upstream_response_body_and_status_pass_through(upstream):
    with _client(upstream) as client:
        resp = client.get("/boom")
    assert resp.status_code == 500
    assert resp.json()["error"] == "upstream exploded"


def test_the_client_can_read_the_response_body(upstream):
    """A streaming upstream response must be read before being handed back."""
    with _client(upstream) as client:
        resp = client.get("/v1/models")
    assert resp.json()["method"] == "GET"
    # The upstream's own response header reaches the client.
    assert resp.headers["x-upstream"] == "yes"


# --- information disclosure ----------------------------------------------------


def test_an_upstream_failure_does_not_leak_internals(upstream):
    """The 502 body must not hand the client a hostname, port or traceback."""
    with _client("http://127.0.0.1:1") as client:
        resp = client.get("/v1/models")
    assert resp.status_code == 502
    body = resp.text
    assert "127.0.0.1" not in body
    assert "Traceback" not in body
    assert "ConnectionRefused" not in body
    assert "uvicorn" not in body.lower()
    assert body == '{"error":"upstream request failed"}'


# --- timeouts ------------------------------------------------------------------


def test_a_hung_upstream_is_abandoned_at_the_timeout(upstream):
    with _client(upstream, upstream_timeout=0.75) as client:
        started = time.monotonic()
        resp = client.get("/hang")
        elapsed = time.monotonic() - started
    assert resp.status_code == 502
    assert elapsed < 10, f"the timeout did not fire; waited {elapsed:.1f}s"
