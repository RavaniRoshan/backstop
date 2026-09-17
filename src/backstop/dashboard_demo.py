"""Deterministic demo workload for the built-in dashboard (``--demo``).

Mirrors the README's Wedge narrative — three isolated sessions, each with its
own budget and circuit breaker — but backed by a mock transport, so a first-time
user can see a live dashboard with no API keys and no network access.

The sessions are held in a list for the lifetime of the workload on purpose: the
session registry is weak, so a session stays visible only while its owner keeps
it alive — exactly like a real ``wrap()``ed client.
"""
from __future__ import annotations

import atexit
import copy
import json
import multiprocessing
import random
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import BackstopConfig
from .harness import DEFAULT_SEED
from .state import BackstopState
from .telemetry import DEFAULT_SAMPLE_INTERVAL
from .transports import BackstopTransport

# One session per "runner", matching the wedge demo's three concurrent agents.
RUNNER_BUDGET = 20_000


@dataclass(frozen=True)
class _Stage:
    """One phase of the scripted workload."""

    name: str
    seconds: float
    error_rate: float
    priority_mix: tuple[str, ...]
    skip_lane: int | None = None


# A fixed rotation: steady traffic, a provider error storm that trips the
# circuit, then sustained budget pressure. Seeded, so the shape is repeatable.
_STAGES = (
    _Stage("steady", 6.0, 0.0, ("default", "default", "background", "critical")),
    # Lane 2 skips this stage so the dashboard shows staggered transitions
    # instead of three identical spikes.
    _Stage("degraded", 6.0, 0.6, ("default", "critical", "background"), skip_lane=2),
    _Stage("pressure", 6.0, 0.15, ("background", "background", "critical")),
)


class _MockProvider:
    """Deterministic mock provider: sleeps, then fails or succeeds on a plan."""

    def __init__(self, rng: random.Random) -> None:
        self.error_rate = 0.0
        self.rng = rng
        self.calls = 0
        self._lock = threading.Lock()
        self._plan = [rng.random() < 0.6 for _ in range(4096)]
        self._index = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.calls += 1
            index = self._index
            self._index += 1
        time.sleep(self.rng.uniform(0.01, 0.06))
        if self.error_rate and self._plan[index % len(self._plan)]:
            return httpx.Response(503, json={"error": {"message": "synthetic overload"}})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_demo",
                "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52},
            },
        )


@dataclass
class _Lane:
    """One isolated runner: its own state, transport, provider and budget."""

    index: int
    state: Any
    client: httpx.Client
    provider: _MockProvider


_MAX_SNAPSHOT_BYTES = 1024 * 1024


def build_empty_demo_snapshot(runners: int, interval: float = DEFAULT_SAMPLE_INTERVAL) -> dict[str, Any]:
    """A valid, empty demo snapshot for the facade before the child publishes.

    Mirrors the shape of ``build_snapshot`` output so the dashboard and UI can
    treat it uniformly: no samples yet, zeroed KPIs, no sessions.
    """
    return {
        "generated_at": None,
        "sampled_at": None,
        "sample_age_s": None,
        "uptime_s": 0.0,
        "mode": "demo",
        "sample_interval_s": interval,
        "window_seconds": 0.0,
        "sinks": {"telemetry": False, "prometheus": False, "cost_model": None},
        "warnings": ["Isolated demo workload is starting; no sample published yet."],
        "kpi": {
            "budget": {"limit": None, "spent": None, "remaining": None,
                       "pct_used": None, "burn_tokens_per_min": 0.0, "eta_seconds": None},
            "spend": {"tokens": None, "usd_lower_bound": None,
                      "prevented_usd_lower_bound": None},
            "prevention": {"total": 0, "budget_blocked": 0, "tenant_blocked": 0,
                           "rate_limited": 0, "circuit_open": 0, "exceptions": 0,
                           "cache_avoided": 0},
            "traffic": {"requests": 0, "provider_calls": 0, "success": 0,
                        "errors": 0, "retries": 0, "rps": 0.0,
                        "provider_efficiency": None},
            "latency": {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0,
                        "includes_provider": True},
            "concurrency": {"active": 0, "capacity": 0, "queued": 0},
            "cache": {"hits": 0, "hit_rate": None},
            "circuit": {"state": "closed", "trips": 0},
            "isolation": {"sessions": 0},
        },
        "series": {"t": [], "requests": [], "rps": [], "prevented": [],
                   "prevented_rps": [], "provider_calls": [], "latency_p95_ms": [],
                   "budget_remaining": [], "burn_tokens_per_min": [],
                   "concurrency_active": []},
        "sessions": [],
        "tenants": [],
        "events": [],
        "outcomes": {},
        "audit": {"path": None, "verified": None, "note": ""},
    }


class DemoWorkload:
    """Parent facade; all synthetic state and capture live in a spawned child."""

    def __init__(self, runners: int = 3, seed: int = DEFAULT_SEED) -> None:
        self.runners = max(1, min(runners, 8))
        self.seed = seed
        self._lock = threading.RLock()
        self._process: Any = None
        self._cache: dict[str, Any] | None = None
        self._buffer: Any = None
        self._size: Any = None
        self._ipc_lock: Any = None
        self._stop: Any = None

    @property
    def requests_driven(self) -> int:
        with self._lock:
            self._read()
            return self._cache["requests_driven"] if self._cache else 0

    @property
    def stage(self) -> str:
        with self._lock:
            self._read()
            return self._cache["stage"] if self._cache else "starting"

    def start(self, *, interval: float = 2.0, cost_model: str | None = None) -> None:
        with self._lock:
            if self._process is not None:
                return
            ctx = multiprocessing.get_context("spawn")
            self._buffer = ctx.RawArray("B", _MAX_SNAPSHOT_BYTES)
            self._size = ctx.RawValue("I", 0)
            self._ipc_lock = ctx.Lock()
            self._stop = ctx.Event()
            ready = ctx.Event()
            self._cache = None
            process = ctx.Process(
                target=_demo_process,
                args=(self.runners, self.seed, interval, cost_model, self._buffer,
                      self._size, self._ipc_lock, self._stop, ready),
                name="backstop-demo",
                daemon=True,
            )
            self._process = process
            try:
                process.start()
                deadline = time.monotonic() + 10.0
                while not ready.wait(0.05):
                    if not process.is_alive() or time.monotonic() >= deadline:
                        raise RuntimeError("isolated demo failed to start")
                self._read()
                if self._cache is None:
                    # Publish an empty-but-valid parent cache immediately, so a
                    # snapshot request racing the first child publish gets an
                    # honest empty payload instead of raising from a read path.
                    self._cache = {
                        "snapshot": build_empty_demo_snapshot(self.runners, interval),
                        "requests_driven": 0,
                        "stage": "starting",
                    }
            except BaseException:
                self.stop()
                raise
            atexit.register(self.stop)

    def _read(self) -> None:
        if self._buffer is None or not self._ipc_lock.acquire(timeout=0.05):
            return
        try:
            payload = bytes(self._buffer[:self._size.value])
        finally:
            self._ipc_lock.release()
        if payload:
            self._cache = json.loads(payload)

    def snapshot(self) -> dict[str, Any]:
        """Latest child snapshot, or an empty one before the first publish."""
        with self._lock:
            self._read()
            if self._cache is None:
                # Not started (or the child died before publishing): serve an
                # honest empty snapshot rather than raise from a read path.
                snapshot = build_empty_demo_snapshot(self.runners)
            else:
                snapshot = copy.deepcopy(self._cache["snapshot"])
        now = time.time()
        snapshot["generated_at"] = round(now, 3)
        sampled_at = snapshot["sampled_at"]
        snapshot["sample_age_s"] = max(0.0, now - sampled_at) if sampled_at is not None else None
        return snapshot

    def stop(self) -> None:
        with self._lock:
            process = self._process
            if process is None:
                return
            self._stop.set()
            if process.pid is not None:
                process.join(timeout=3.0)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1.0)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=1.0)
            self._read()
            process.close()
            self._process = None
            self._buffer = None
            atexit.unregister(self.stop)



def _demo_process(runners, seed, interval, cost_model, buffer, size, lock, stop, ready):
    from .telemetry import Sampler, build_snapshot, install_sink, uninstall_sink

    workload = _DemoWorker(runners, seed)
    sampler = Sampler(interval)
    install_sink()
    try:
        workload.start()
        while not stop.is_set():
            parent = multiprocessing.parent_process()
            if parent is not None and not parent.is_alive():
                break
            sampler.sample_once()
            payload = json.dumps({
                "snapshot": build_snapshot(sampler, mode="demo", cost_model=cost_model),
                "requests_driven": workload.requests_driven,
                "stage": workload.stage,
            }, separators=(",", ":")).encode("utf-8")
            if len(payload) > _MAX_SNAPSHOT_BYTES:
                raise RuntimeError("demo snapshot exceeds IPC capacity")
            if lock.acquire(timeout=0.1):
                try:
                    buffer[:len(payload)] = payload
                    size.value = len(payload)
                finally:
                    lock.release()
                ready.set()
            stop.wait(sampler.interval)
    finally:
        workload.stop()
        uninstall_sink()


class _DemoWorker:
    """Child-only mock clients and their strongly held session states."""

    def __init__(self, runners: int = 3, seed: int = DEFAULT_SEED) -> None:
        self.runners = max(1, min(runners, 8))
        self.seed = seed
        self.stage = "starting"
        self._rng = random.Random(seed)
        self._lanes: list[_Lane] = []
        # Strong references: a session must stay alive to stay visible.
        self._states: list[BackstopState] = []
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._requests = 0
        self._build()

    @property
    def requests_driven(self) -> int:
        with self._lock:
            return self._requests

    def _build(self) -> None:
        for index in range(self.runners):
            state = BackstopState.create(
                RUNNER_BUDGET,
                BackstopConfig(
                    initial_concurrency=4,
                    max_concurrency=16,
                    retry_max_attempts=1,
                    circuit_min_requests=4,
                    circuit_failure_threshold=0.5,
                    circuit_cooldown_seconds=3.0,
                    aimd_adjustment_interval=0.5,
                ),
            )
            provider = _MockProvider(self._rng)
            client = httpx.Client(
                transport=BackstopTransport(state, httpx.MockTransport(provider.handle)),
                base_url="https://mock.openai.local",
                timeout=5.0,
            )
            self._states.append(state)
            self._lanes.append(_Lane(index, state, client, provider))

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for lane in self._lanes:
            thread = threading.Thread(
                target=self._run_lane,
                args=(lane,),
                name=f"backstop-demo-lane-{lane.index}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2.0)
        self._threads.clear()
        for lane in self._lanes:
            lane.client.close()

    def _run_lane(self, lane: _Lane) -> None:
        while not self._stop.is_set():
            for stage in _STAGES:
                if self._stop.is_set():
                    return
                if stage.skip_lane == lane.index:
                    continue
                self.stage = stage.name
                lane.provider.error_rate = stage.error_rate
                deadline = time.monotonic() + stage.seconds
                while not self._stop.is_set() and time.monotonic() < deadline:
                    self._call(lane, stage)
                    self._stop.wait(self._rng.uniform(0.05, 0.25))

    def _call(self, lane: _Lane, stage: _Stage) -> None:
        priority = stage.priority_mix[self._requests % len(stage.priority_mix)]
        try:
            lane.client.post(
                "/v1/chat/completions",
                headers={"X-Backstop-Priority": priority},
                json={"model": "mock", "messages": [{"role": "user", "content": "demo"}]},
            )
        except Exception:
            # Exhausted budgets and open circuits are the point of the demo.
            pass
        with self._lock:
            self._requests += 1