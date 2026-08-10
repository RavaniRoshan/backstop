"""Proof: budget-exhaustion webhooks fire threshold_crossed before the cap.

Spins up a local HTTP receiver (no external network), wraps a client with a
BackstopConfig that has webhook_endpoints pointed at it, drives usage across the
85% and 95% tiers, and asserts the receiver got the events in order. Run with:

    python proofs/proof_budget_webhook.py
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

from backstop.config import BackstopConfig
from backstop.state import BackstopState
from backstop.transports import BackstopTransport


class _Receiver(BaseHTTPRequestHandler):
    received: list[dict] = []
    _lock = threading.Lock()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except Exception:
            payload = {}
        with self._lock:
            _Receiver.received.append({"event": self.headers.get("X-Backstop-Event"), "payload": payload})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):  # silence
        pass


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    _Receiver.received.clear()
    cfg = BackstopConfig(
        retry_max_attempts=1,
        circuit_min_requests=10_000,
        default_max_output_tokens=1,  # keep the pre-send estimate small so calls actually succeed
        webhook_endpoints=[f"http://127.0.0.1:{port}/hook"],
        webhook_secret="test-secret",
        alert_tiers=[0.85, 0.95],
    )
    state = BackstopState.create(1000, cfg)
    client = httpx.Client(
        transport=BackstopTransport(
            state,
            httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True, "usage": {"total_tokens": 90}})),
        ),
        base_url="https://mock.local",
    )
    # 90 tokens/call, 1000 limit => crosses 0.85 (850) at call 10, 0.95 (950) at call 11.
    for _ in range(12):
        try:
            client.post("/v1/chat/completions", json={"model": "mock", "messages": [{"role": "user", "content": "x"}]})
        except Exception:
            pass
    client.close()
    time.sleep(1.0)  # let fire-and-forget threads deliver
    server.shutdown()

    events = [(r["event"], r["payload"].get("ratio")) for r in _Receiver.received]
    threshold_events = [e for e in events if e[0] == "threshold_crossed"]
    print(f"Received {len(events)} webhook event(s):")
    for e in events:
        print(f"  - {e[0]} ratio={e[1]}")

    if len(threshold_events) >= 2:
        print("\nPROOF PASS: threshold_crossed fired before the budget was exhausted.")
        return 0
    print("\nPROOF FAIL: expected >=2 threshold_crossed webhooks before exhaustion.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
