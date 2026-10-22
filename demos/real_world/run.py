#!/usr/bin/env python3
"""Run a real-world scenario against a live Backstop dashboard.

Each scenario reproduces a documented production failure at the parameters that
failure actually had, at a scale that fits in a demonstration. The traffic is
simulated — no key, no network, no bill — but the rates, the token counts and
the prices are the real ones, so the dollars on screen are the dollars the
incident cost.

    python demos/real_world/run.py --list
    python demos/real_world/run.py --scenario noisy-neighbour
    python demos/real_world/run.py --all

``--live`` points the same client at the real provider instead of a local
mock, if a key for that provider is in the environment.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

from wsgiref.simple_server import make_server  # noqa: E402

import httpx  # noqa: E402
from catalogue import (  # noqa: E402
    ENDPOINTS,
    KIND_LABEL,
    SCENARIOS,
    SCENARIOS_BY_KEY,
    Endpoint,
    Scenario,
    Tenant,
)

import backstop  # noqa: E402
from backstop import with_budget  # noqa: E402
from backstop.config import BackstopConfig  # noqa: E402
from backstop.dashboard_app import (  # noqa: E402
    Dashboard,
    _QuietHandler,
    _ThreadingWSGIServer,
    make_dashboard_app,
)
from backstop.exceptions import BudgetExceededError  # noqa: E402
from backstop.ledger.budget import TenantBudget, reset_ledger  # noqa: E402
from backstop.ledger.context import attribution  # noqa: E402
from backstop.pricing import register_pricing  # noqa: E402
from backstop.state import BackstopState  # noqa: E402
from backstop.transports import BackstopTransport  # noqa: E402

PRICES_PATH = HERE / "prices.json"
OUT_DIR = HERE / "out"


def _paths(scenario_key: str) -> tuple[Path, Path]:
    """The ledger and the audit log for one scenario.

    Per scenario, not shared: two demos running at once — one on port 8787
    and one on another, or a leftover file from the last run — would
    otherwise interleave two scenarios' events in one audit tail, and the
    dashboard would show a stranger's denials.
    """
    directory = OUT_DIR / scenario_key
    return directory / "ledger.jsonl", directory / "audit.jsonl"

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"


def _colour(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if sys.stdout.isatty() else text


# --------------------------------------------------------------------------
# The provider side
# --------------------------------------------------------------------------


class MockProvider:
    """A stand-in for the endpoint, behaving the way the endpoint behaves.

    It answers in the endpoint's own protocol — the OpenAI chat-completions
    shape, or Anthropic's message shape — reports the usage the caller asked
    for, takes the endpoint's own latency, and, when the scenario says the
    endpoint is in trouble, returns the status code the endpoint would
    return. Nothing here talks to a network.
    """

    def __init__(self, endpoint: Endpoint, rng: random.Random) -> None:
        self.endpoint = endpoint
        self.rng = rng
        self.calls = 0
        self.lock = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.calls += 1
        try:
            body = json.loads(request.content or b"{}")
        except ValueError:
            body = {}
        model = body.get("model") or self.endpoint.model
        prompt_tokens = int(body.get("_prompt_tokens") or 0)
        completion_tokens = int(body.get("_completion_tokens") or 0)
        status = int(body.get("_status") or 200)

        if status >= 400:
            return httpx.Response(
                status,
                json={
                    "error": {
                        "type": "rate_limit_error" if status == 429 else "server_error",
                        "message": "mock provider failure",
                    }
                },
            )

        lo, hi = self.endpoint.latency_ms
        time.sleep(self.rng.uniform(lo, hi) / 1000.0)

        if self.endpoint.protocol == "anthropic":
            return httpx.Response(
                200,
                json={
                    "id": f"msg_mock_{self.calls}",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": prompt_tokens,
                        "output_tokens": completion_tokens,
                    },
                },
            )

        return httpx.Response(
            200,
            json={
                "id": f"chatcmpl-mock-{self.calls}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            },
        )


# --------------------------------------------------------------------------
# The traffic side
# --------------------------------------------------------------------------


@dataclass
class Counters:
    sent: int = 0
    ok: int = 0
    denied: int = 0
    provider_errors: int = 0
    tokens: int = 0
    usd: Decimal = Decimal("0.000000")
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, **kwargs: Any) -> None:
        with self.lock:
            for name, value in kwargs.items():
                setattr(self, name, getattr(self, name) + value)


def _drive(
    client: httpx.Client,
    tenant: Tenant,
    scenario: Scenario,
    counters: Counters,
    started_at: float,
    stop_at: float,
    live: bool,
    speed: float,
) -> None:
    """One tenant's traffic.

    A tenant that is in a loop starts healthy and then changes: the rate
    multiplies and, for the ones that trip a context ceiling, the requests
    get longer. The point of the healthy window is that the dashboard has
    something true to show before the failure starts.
    """
    interval = 60.0 / max(tenant.rpm * speed, 0.01)
    next_at = started_at
    was_looping = False
    # When the tenant starts going wrong. The thread has to wake for it, not
    # for the next scheduled request: a tenant whose healthy interval is
    # longer than its healthy window would otherwise never reach its loop.
    phase_change_at = started_at + (tenant.healthy_for_s / max(speed, 0.1))

    while time.monotonic() < stop_at:
        now = time.monotonic()

        # The phase is checked first, every pass, so the moment a tenant
        # starts going wrong it is noticed — rather than at its next
        # scheduled request, which for a slow tenant may never come.
        looping = _is_looping(tenant, now - started_at, speed)
        if looping != was_looping:
            was_looping = looping
            next_at = now  # fire now, not at the next slot

        if now < next_at:
            wake = next_at
            if not was_looping:
                wake = min(wake, phase_change_at)
            time.sleep(max(0.0, min(wake - now, 0.2)))
            continue

        # A tenant in a loop sends faster, not slower.
        next_at = now + (interval / tenant.loop_multiplier if looping else interval)

        tokens_in = tenant.tokens_in
        tokens_out = tenant.tokens_out
        status = 200

        if looping:
            if tenant.behaviour == "storm":
                # The endpoint starts refusing. This is the retry storm's
                # trigger: every workflow retries, and the queue of users
                # pressing refresh multiplies the load again.
                status = 429
            else:
                # A failure that is a change of shape: the request gets
                # longer, not just more frequent.
                tokens_in = tenant.tokens_in_loop or tenant.tokens_in
                tokens_out = tenant.tokens_out_loop or tenant.tokens_out

        payload = _payload(scenario, tokens_in, tokens_out, status, live)

        counters.add(sent=1)
        try:
            # The tenant is what the budget is checked against, and what the
            # ledger records. Both come from the request's context, which is
            # how a real application identifies the caller.
            with with_budget(tenant.name), attribution(
                team=tenant.team,
                tenant=tenant.name,
                feature=scenario.endpoint.label.lower().replace(" ", "-"),
                environment="demo",
            ):
                response = client.post(_path(scenario), json=payload)
        except BudgetExceededError:
            counters.add(denied=1)
            continue
        except Exception:  # noqa: BLE001 - the demo reports every failure
            counters.add(provider_errors=1)
            continue

        if response.status_code == 200:
            counters.add(ok=1, tokens=tokens_in + tokens_out)
        else:
            counters.add(provider_errors=1)


def _path(scenario: Scenario) -> str:
    """The path this endpoint's protocol puts the request on."""
    if scenario.endpoint.protocol == "anthropic":
        return "/v1/messages"
    return "/chat/completions"


def _payload(
    scenario: Scenario,
    tokens_in: int,
    tokens_out: int,
    status: int,
    live: bool,
) -> dict[str, Any]:
    """The request body, in the endpoint's own protocol.

    In live mode the body is exactly what an operator would send — the
    underscore-prefixed fields are the mock's way of being told what usage to
    report, and a real provider would reject them.
    """
    endpoint = scenario.endpoint
    # The prompt is as long as the prompt it claims to carry, so Backstop's
    # own token estimate is the real one rather than a rounding of a
    # placeholder.
    prompt = "x" * max(1, tokens_in * 4)
    if endpoint.protocol == "anthropic":
        payload: dict[str, Any] = {
            "model": endpoint.model,
            "max_tokens": tokens_out,
            "messages": [{"role": "user", "content": prompt}],
        }
    else:
        payload = {
            "model": endpoint.model,
            "messages": [{"role": "user", "content": prompt}],
        }
    if not live:
        payload["_prompt_tokens"] = tokens_in
        payload["_completion_tokens"] = tokens_out
        payload["_status"] = status
    return payload


def _is_looping(tenant: Tenant, elapsed: float, speed: float = 1.0) -> bool:
    """Whether this tenant has started going wrong yet.

    The healthy window is compressed with the rest of the scenario, so a fast
    run is the same run, quicker — the same number of calls still happens
    before the failure starts.
    """
    if tenant.behaviour == "normal":
        return False
    return elapsed >= (tenant.healthy_for_s / max(speed, 0.1))


# --------------------------------------------------------------------------
# The dashboard
# --------------------------------------------------------------------------


class DashboardServer:
    """A dashboard on a fixed port, restarted between scenarios.

    It is restarted rather than reused because the cost model is a property of
    the dashboard, and each scenario spends against a different model at a
    different rate. The URL does not change.
    """

    def __init__(self, host: str, port: int, title: str, theme: str = "auto") -> None:
        self.host = host
        self.port = port
        self.title = title
        self.theme = theme
        self.dashboard: Dashboard | None = None
        self.server: Any = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def start(self, cost_model: str, audit: str) -> None:
        self.dashboard = Dashboard(
            mode="live",
            cost_model=cost_model,
            audit=audit,
            interval=1.0,
            title=self.title,
            theme=self.theme,
        )
        app = make_dashboard_app(self.dashboard)
        # The port is rebound between scenarios, and a socket that was just
        # closed can still be in TIME_WAIT — so the *same* port is retried
        # first, and only a port that is genuinely taken (by another demo, or
        # by something else on the machine) moves on to the next one. The URL
        # is meant to stay the same for the whole run.
        last: OSError | None = None
        bound = False
        for port_attempt in range(5):
            candidate = (self.port + port_attempt) if self.port else 0
            for _ in range(8):
                try:
                    self.server = make_server(
                        self.host,
                        candidate,
                        app,
                        server_class=_ThreadingWSGIServer,
                        handler_class=_QuietHandler,
                    )
                    bound = True
                    break
                except OSError as exc:
                    last = exc
                    if not self.port:
                        raise
                    time.sleep(0.25)
            if bound:
                break
        if not bound:
            raise OSError(
                f"could not bind the dashboard to {self.host}:{self.port}: {last}"
            )
        # Port 0 means "any free port"; the OS picks one and the URL has to
        # be read back, because that is the port the browser has to use.
        self.port = int(self.server.server_address[1])
        self.dashboard.start()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.dashboard is not None:
            self.dashboard.stop()
            self.dashboard = None


# --------------------------------------------------------------------------
# Prices
# --------------------------------------------------------------------------


def _load_prices() -> dict[tuple[str, str], dict[str, str]]:
    document = json.loads(PRICES_PATH.read_text(encoding="utf-8"))
    return {
        (entry["provider"], entry["model"]): entry for entry in document["entries"]
    }


def _register_estimator_price(model: str, entry: dict[str, str] | None) -> None:
    """Teach the dashboard's estimator about a model the bundled catalog lacks.

    The dashboard's dollar figure is a lower bound computed from a token
    count and one model's rate, so it needs the model in its own table.
    """
    if entry is None:
        return
    register_pricing(
        model,
        {
            "input_cost_per_1k": float(Decimal(entry["input_per_mtok_usd"])) / 1000.0,
            "output_cost_per_1k": float(Decimal(entry["output_per_mtok_usd"])) / 1000.0,
        },
    )


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def _money(amount: Decimal) -> str:
    return f"${amount:.6f}".rstrip("0").rstrip(".") if amount else "$0"


def _rule(char: str = "─") -> str:
    return _colour(char * 78, DIM)


def _banner(scenario: Scenario) -> None:
    endpoint = scenario.endpoint
    print()
    print(_rule("━"))
    print(
        f"{_colour('▶ ', CYAN)}{_colour(scenario.title, BOLD)}"
        f"  {_colour(f'({scenario.key})', DIM)}"
    )
    print(_rule())
    print(f"  {_colour('kind', DIM)}      {KIND_LABEL[scenario.kind]} · {endpoint.label}")
    print(f"  {_colour('endpoint', DIM)}  {endpoint.base_url}")
    print(f"  {_colour('model', DIM)}     {endpoint.model}")
    print(f"  {_colour('price', DIM)}     "
          f"${endpoint.input_per_mtok_usd}/1M in · ${endpoint.output_per_mtok_usd}/1M out")
    print()
    for line in _wrap(scenario.incident, 74):
        print(f"  {_colour(line, DIM)}")
    print()
    print(f"  {_colour('real', DIM)}      {scenario.real_rate}")
    print(f"  {_colour('real', DIM)}      {scenario.real_spend}")
    print(f"  {_colour('demo', DIM)}      {scenario.scale} · {scenario.duration_s:.0f}s")
    print()
    for show in scenario.shows:
        print(f"  {_colour('▸ shows', YELLOW)}  {show}")
    print()


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def _run_scenario(
    scenario: Scenario,
    server: DashboardServer,
    live: bool,
    speed: float,
    verbose: bool,
    duration_override: float | None = None,
) -> None:
    _banner(scenario)

    endpoint = scenario.endpoint
    prices = _load_prices()
    entry = prices.get(("unknown", endpoint.model))
    _register_estimator_price(endpoint.model, entry)

    # A fresh ledger and a fresh set of tenant budgets, so one scenario never
    # inherits another's state.
    reset_ledger()
    ledger_path, audit_path = _paths(scenario.key)
    for path in (ledger_path, audit_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)

    # Only the capped tenants get a bucket of their own. Everyone else
    # spends against the shared pool, which is what the platform's own
    # budget tile shows.
    backstop.budgets.register(
        {
            tenant.name: TenantBudget(
                tenant_id=tenant.name,
                limit_tokens=tenant.limit_tokens,
                limit_usd=Decimal(tenant.limit_usd) if tenant.limit_usd else None,
            )
            for tenant in scenario.tenants
            if tenant.capped
        }
    )

    config = BackstopConfig(
        budget_usd=Decimal(scenario.budget_usd) if scenario.budget_usd else None,
        ledger_enabled=True,
        ledger_path=str(ledger_path),
        price_catalog_path=str(PRICES_PATH),
        audit_enabled=True,
        audit_sink=str(audit_path),
        audit_hmac_key="backstop-demo",
        detection_enabled=True,
        detection_shadow=False,
        initial_concurrency=scenario.initial_concurrency,
        max_concurrency=scenario.max_concurrency,
        aimd_adjustment_interval=0.5,
        circuit_failure_threshold=scenario.circuit_failure_threshold,
        circuit_window_seconds=scenario.circuit_window_seconds,
        circuit_cooldown_seconds=scenario.circuit_cooldown_seconds,
        circuit_min_requests=5,
        retry_max_attempts=scenario.retry_max_attempts,
        default_max_output_tokens=1024,
    )

    state = BackstopState.create(scenario.budget_tokens, config)
    rng = random.Random(f"{scenario.key}:provider")

    if live:
        key = os.environ.get(endpoint.api_key_env or "", "")
        if not key:
            print(
                f"  {_colour('!', YELLOW)} no {endpoint.api_key_env} in the "
                f"environment — falling back to the mock provider."
            )
            live = False

    provider = MockProvider(endpoint, rng)
    transport = (
        httpx.HTTPTransport()
        if live
        else httpx.MockTransport(provider.handler)
    )
    client = httpx.Client(
        transport=BackstopTransport(state, transport),
        base_url=endpoint.base_url,
        timeout=30.0,
    )

    server.stop()
    server.start(cost_model=endpoint.model, audit=str(audit_path))

    counters = Counters()
    duration = (duration_override or scenario.duration_s) / max(speed, 0.1)
    started_at = time.monotonic()
    stop_at = started_at + duration

    threads = [
        threading.Thread(
            target=_drive,
            args=(client, tenant, scenario, counters, started_at, stop_at, live, speed),
            daemon=True,
        )
        for tenant in scenario.tenants
    ]
    for thread in threads:
        thread.start()

    print(f"  {_colour('dashboard', BOLD)}  {server.url}")
    print(f"  {_colour('ledger', DIM)}      {ledger_path}")
    print(f"  {_colour('running', DIM)}      {duration:.0f}s — Ctrl-C to stop\n")

    ticker = time.monotonic()
    while time.monotonic() < stop_at:
        time.sleep(1.0)
        if verbose and time.monotonic() - ticker >= 5.0:
            ticker = time.monotonic()
            with counters.lock:
                print(
                    f"    {_colour('…', DIM)} sent {counters.sent} · ok {counters.ok} · "
                    f"denied {counters.denied} · provider errors {counters.provider_errors}"
                )

    for thread in threads:
        thread.join(timeout=5.0)
    client.close()
    state.close()

    _report(scenario, counters, state)


def _report(scenario: Scenario, counters: Counters, state: Any = None) -> None:
    from backstop.ledger.export import read_ledger

    ledger_path, _audit_path = _paths(scenario.key)

    per_tenant: dict[str, dict[str, Any]] = {}
    total_usd = Decimal("0.000000")
    total_tokens = 0
    unpriced = 0

    try:
        read = read_ledger(ledger_path)
    except FileNotFoundError:
        read = None
    if read is not None:
        for event in read.events:
            tenant = event.attribution.tenant or "—"
            row = per_tenant.setdefault(
                tenant, {"calls": 0, "tokens": 0, "usd": Decimal("0.000000")}
            )
            row["calls"] += 1
            row["tokens"] += event.input_tokens + event.output_tokens
            total_tokens += event.input_tokens + event.output_tokens
            if event.cost is None:
                unpriced += 1
                continue
            row["usd"] += event.cost.total_usd
            total_usd += event.cost.total_usd

    print(_rule())
    print(f"  {_colour('result', BOLD)}")
    print()
    for tenant in scenario.tenants:
        row = per_tenant.get(tenant.name, {"calls": 0, "tokens": 0, "usd": Decimal("0")})
        print(
            f"    {tenant.label:<34} {row['calls']:>5} calls  "
            f"{row['tokens']:>9,} tok  {_money(row['usd']):>12}"
        )
    print()
    print(
        f"    {_colour('totals', DIM)}"
        f"{'':<36} {counters.sent:>5} sent  {total_tokens:>9,} tok  "
        f"{_money(total_usd):>12}"
    )
    if counters.denied:
        print(
            f"    {_colour('denied by the guardrail', RED)}"
            f"{'':<23} {counters.denied:>5} requests"
        )
    if counters.provider_errors:
        print(
            f"    {_colour('provider errors', YELLOW)}"
            f"{'':<30} {counters.provider_errors:>5} requests"
        )
    if state is not None:
        try:
            circuit_state = state.circuit.state
            # The state is an enum; its value is the word the dashboard shows.
            name = getattr(circuit_state, "value", circuit_state)
            print(
                f"    {_colour('circuit breaker', DIM)}"
                f"{'':<29} {name}"
            )
        except Exception:  # noqa: BLE001 - the report never breaks the run
            pass
    if unpriced:
        print(
            f"    {_colour('unpriced', YELLOW)}"
            f"{'':<34} {unpriced:>5} requests — no price filed for that model"
        )

    # Two tenants on one budget, one over-retrieving and one not: what the
    # same money bought.
    for tenant in scenario.tenants:
        if not tenant.fixed_version_of:
            continue
        broken = per_tenant.get(tenant.fixed_version_of)
        fixed = per_tenant.get(tenant.name)
        if not broken or not fixed or not broken["calls"] or not fixed["calls"]:
            continue
        broken_per_call = broken["usd"] / broken["calls"]
        fixed_per_call = fixed["usd"] / fixed["calls"]
        if not fixed_per_call:
            continue
        print()
        print(
            f"  {_colour('the same money', YELLOW)}  "
            f"{_money(broken['usd'])} bought {broken['calls']} answers from the "
            f"over-retrieving bot; {_money(fixed['usd'])} bought {fixed['calls']} "
            f"from the fixed one."
        )
        print(
            f"  {'':<27}  One call costs "
            f"{broken_per_call / fixed_per_call:.2f}× as much "
            f"({_money(broken_per_call)} against {_money(fixed_per_call)})."
        )

    # The number the instructor is here for: what the failure would have cost
    # with nothing in the way.
    looped = [t for t in scenario.tenants if t.behaviour != "normal"]
    for tenant in looped:
        row = per_tenant.get(tenant.name)
        if not row or not row["calls"]:
            continue
        per_call = row["usd"] / row["calls"]
        # The same window, the same runaway rate, and no cap to stop it.
        window_minutes = scenario.duration_s / 60.0
        runaway_rpm = tenant.rpm * tenant.loop_multiplier
        would_calls = int(runaway_rpm * window_minutes)
        would_spend = per_call * would_calls
        prevented = would_spend - row["usd"]
        print()
        print(
            f"  {_colour('without the guardrail', YELLOW)}  "
            f"{tenant.label} would have made {would_calls:,} calls in this window "
            f"and spent {_money(would_spend)}; it made {row['calls']:,} and spent "
            f"{_money(row['usd'])}."
        )
        if prevented > 0:
            print(f"  {'':<27}  {_money(prevented)} of it never happened.")

    print()
    print(f"  {_colour(scenario.headline, GREEN)}")
    print()


# --------------------------------------------------------------------------
# The catalogue listing
# --------------------------------------------------------------------------


def _list() -> None:
    print()
    print(f"{_colour('Scenarios', BOLD)}")
    print(_rule())
    for scenario in SCENARIOS:
        print(f"  {_colour(scenario.key, CYAN):<24} {scenario.title}")
        print(
            f"  {'':<24} {KIND_LABEL[scenario.kind]} · {scenario.endpoint.label}"
            f"  {_colour(scenario.source_url, DIM)}"
        )
    print()
    print(f"{_colour('The four kinds of server', BOLD)}")
    print(_rule())
    for kind in ("provider", "self-hosted", "managed", "gateway"):
        rows = [e for e in ENDPOINTS.values() if e.kind == kind]
        print(f"  {_colour(KIND_LABEL[kind], BOLD)}")
        for endpoint in rows:
            print(
                f"    {endpoint.label:<28} {endpoint.base_url}"
            )
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a real-world scenario against a live Backstop dashboard. "
            "The traffic is simulated; the rates, the token counts and the "
            "prices are the real ones."
        )
    )
    parser.add_argument(
        "--scenario", "-s", default=None,
        help="run one scenario by key (see --list)",
    )
    parser.add_argument(
        "--all", "-a", action="store_true", help="run every scenario in order",
    )
    parser.add_argument("--list", "-l", action="store_true", help="list scenarios and endpoints")
    parser.add_argument(
        "--live", action="store_true",
        help="call the real provider instead of the mock, if its key is set",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--speed", type=float, default=1.0,
        help="divide the scenario's duration by this (2.0 runs it twice as fast)",
    )
    parser.add_argument(
        "--theme", default="auto", choices=("auto", "dark", "light"),
        help="the dashboard's theme",
    )
    parser.add_argument(
        "--duration", type=float, default=None,
        help="override the scenario's duration in seconds",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    if args.list:
        _list()
        return 0

    if args.scenario:
        if args.scenario not in SCENARIOS_BY_KEY:
            print(f"unknown scenario: {args.scenario}", file=sys.stderr)
            _list()
            return 2
        chosen = [SCENARIOS_BY_KEY[args.scenario]]
    elif args.all:
        chosen = list(SCENARIOS)
    else:
        chosen = [SCENARIOS_BY_KEY["noisy-neighbour"]]

    server = DashboardServer(
        args.host, args.port, "Backstop — real-world scenarios", theme=args.theme
    )
    print()
    print(f"{_colour('Backstop · real-world scenarios', BOLD)}")
    print(
        _colour(
            f"  {len(chosen)} scenario(s) · dashboard on {server.url}", DIM
        )
    )
    print(
        _colour(
            "  Traffic is simulated. The rates, the token counts and the prices "
            "are the real ones.", DIM
        )
    )

    try:
        for scenario in chosen:
            _run_scenario(
                scenario, server, args.live, args.speed, args.verbose,
                duration_override=args.duration,
            )
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
