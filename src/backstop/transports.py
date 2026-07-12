from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable

import httpx

from .budget import Reservation
from .cache import ResponseCache
from .circuit import CircuitState
from .config import BackstopConfig, Priority
from .exceptions import BudgetExceededError, CircuitBreakerOpenError, LatencyBudgetExceededError
from .extract import _json_body, request_metadata, response_usage_tokens
from .hooks import AfterResponseHook, BeforeRequestHook
from .latency import _LatencyTracker, extract_backstop_headers
from .ledger import (
    ReservationTicket as LedgerReservation,
    get_current_tenant,
    get_ledger,
)
from .metrics import get_metrics
from .pricing import get_downgrade_target
from .retry import backoff_delay, is_retryable_status
from .state import BackstopState
from .streaming import async_setup_streaming, is_streaming, setup_streaming

RetrySleep = Callable[[float], None]
AsyncRetrySleep = Callable[[float], Awaitable[None]]


def _deadline_from_config(config: BackstopConfig) -> float | None:
    if config.request_timeout is None:
        return None
    return time.monotonic() + config.request_timeout


def _deadline_exceeded(deadline: float | None) -> bool:
    if deadline is None:
        return False
    return time.monotonic() >= deadline


# Headers that must NOT survive replay: `response.content` is already
# auto-decompressed by httpx, so replaying with `Content-Encoding` set would
# make httpx try to decompress plain bytes again (and crash). `Content-Length`
# / `Transfer-Encoding` likewise describe the wire bytes, not the decoded body.
_REPLAY_STRIP_HEADERS = frozenset(
    {"content-encoding", "content-length", "transfer-encoding"}
)


def _build_cached_response(
    content: bytes,
    usage: int,
    headers: dict[str, str] | None,
) -> httpx.Response:
    clean_headers = {
        k: v
        for k, v in (headers or {}).items()
        if k.lower() not in _REPLAY_STRIP_HEADERS
    }
    return httpx.Response(
        200,
        content=content,
        headers=clean_headers,
    )


def _reconcile(
    tenant_budget: object | None,
    global_budget: object,
    reservation: Reservation | LedgerReservation | None,
    usage: int | None,
    *,
    success: bool,
    downgraded: bool = False,
) -> None:
    if reservation is None:
        if downgraded and tenant_budget is not None and usage is not None and success:
            tenant_budget.commit(LedgerReservation(getattr(tenant_budget, "tenant_id", ""), 0), usage)
        return
    if isinstance(reservation, LedgerReservation) and tenant_budget is not None:
        tenant_budget.commit(reservation, usage if success else 0)
    elif isinstance(reservation, Reservation):
        global_budget.reconcile(reservation, usage, success=success)


class BackstopTransport(httpx.BaseTransport):
    def __init__(
        self,
        state: BackstopState,
        transport: httpx.BaseTransport | None = None,
        *,
        sleep: RetrySleep | None = None,
    ) -> None:
        self.state = state
        self._transport = transport or httpx.HTTPTransport()
        self._sleep = sleep or time.sleep
        self._metrics = get_metrics()
        self._cache = ResponseCache(
            max_entries=state.config.cache_max_entries,
            ttl=state.config.cache_ttl,
        ) if state.config.cache_enabled else None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        tracker = _LatencyTracker()
        meta = request_metadata(request, self.state.config)
        reservation: Reservation | LedgerReservation | None = None
        admitted = False

        body = _json_body(request)
        streaming = is_streaming(body) if body is not None else False

        if self._cache is not None and body is not None and not streaming:
            cached = self._cache.get(body)
            if cached is not None:
                self._metrics.call("cache_hits")
                tracker.completed_at = time.monotonic()
                response = _build_cached_response(cached[0], cached[1], cached[2])
                backstop_meta = tracker.build_meta(
                    estimated_tokens=meta.estimated_tokens,
                    actual_tokens=cached[1],
                    circuit_state=self.state.circuit.state.value,
                    endpoint=meta.endpoint,
                )
                setattr(response, "_backstop_meta", backstop_meta)
                return response

        hook_metadata = extract_backstop_headers(request)
        tenant_id = get_current_tenant()
        tenant_budget: object | None = None
        if tenant_id is not None:
            ledger = get_ledger()
            tenant_budget = ledger.get(tenant_id) if ledger else None

        downgraded = False
        try:
            if tenant_budget is not None:
                reservation = tenant_budget.reserve(meta.estimated_tokens)
            else:
                reservation = self.state.budget.reserve(meta.estimated_tokens)
        except BudgetExceededError:
            if (
                tenant_budget is not None
                and getattr(tenant_budget, "on_exceed", None) == "downgrade"
                and body is not None
            ):
                if self._try_downgrade(request, body):
                    downgraded = True
                    meta = request_metadata(request, self.state.config)
                    try:
                        if tenant_budget is not None:
                            reservation = tenant_budget.reserve(meta.estimated_tokens)
                        else:
                            reservation = self.state.budget.reserve(meta.estimated_tokens)
                    except BudgetExceededError:
                        reservation = None
                else:
                    self._metrics.call("budget_exceeded")
                    if tenant_id:
                        self._metrics.call("tenant_budget_exceeded", tenant_id)
                    raise
            else:
                self._metrics.call("budget_exceeded")
                if tenant_id:
                    self._metrics.call("tenant_budget_exceeded", tenant_id)
                raise

        try:
            if self.state.config.before_request is not None:
                hook = BeforeRequestHook(
                    endpoint=meta.endpoint,
                    priority=meta.priority,
                    estimated_tokens=meta.estimated_tokens,
                    metadata=hook_metadata.copy(),
                )
                self.state.config.before_request(hook)
                hook_metadata = hook.metadata

            deadline = _deadline_from_config(self.state.config)
            wait = self._acquire_gate(meta.priority, deadline)
            admitted = True
            tracker.queue_entered_at = time.monotonic()
            self._observe_queue(wait, meta.priority)
            self.state.circuit.before_request()
            tracker.request_sent_at = time.monotonic()

            response = self._send_with_retries(request, meta.endpoint, deadline)
            tracker.retry_count = self._retry_count

            if streaming:
                success = response.status_code < 400
                setup_streaming(
                    response,
                    self.state,
                    reservation,
                    success=success,
                    tenant_budget=tenant_budget,
                    created_at=tracker.created_at,
                )
                usage = None
            else:
                response.read()
                tracker.first_byte_at = tracker.request_sent_at
                usage = response_usage_tokens(response)
                success = response.status_code < 400
                _reconcile(tenant_budget, self.state.budget, reservation, usage, success=success, downgraded=downgraded)
                self._record_outcome(response.status_code, success=success)
                if self._cache is not None and body is not None and usage is not None:
                    self._cache.set(body, response.content, usage, dict(response.headers))

            tracker.completed_at = time.monotonic()
            outcome = "success" if success else "error"
            self._observe_request(meta.endpoint, meta.priority, tracker.created_at, outcome)

            backstop_meta = tracker.build_meta(
                estimated_tokens=meta.estimated_tokens,
                actual_tokens=usage,
                circuit_state=self.state.circuit.state.value,
                endpoint=meta.endpoint,
                metadata=hook_metadata,
            )
            setattr(response, "_backstop_meta", backstop_meta)

            if self.state.config.after_response is not None:
                try:
                    after_hook = AfterResponseHook(
                        endpoint=meta.endpoint,
                        status_code=response.status_code,
                        actual_tokens=usage,
                        latency_ms=backstop_meta.total_latency_ms,
                        success=success,
                        metadata=hook_metadata,
                    )
                    self.state.config.after_response(after_hook)
                except Exception:
                    pass

            return response
        except CircuitBreakerOpenError:
            tracker.completed_at = time.monotonic()
            _reconcile(tenant_budget, self.state.budget, reservation, 0, success=False)
            self._observe_request(meta.endpoint, meta.priority, tracker.created_at, "circuit_open")
            raise
        except Exception:
            tracker.completed_at = time.monotonic()
            _reconcile(tenant_budget, self.state.budget, reservation, 0, success=False)
            self._record_outcome(599, success=False)
            self._observe_request(meta.endpoint, meta.priority, tracker.created_at, "exception")
            raise
        finally:
            if admitted:
                self.state.gate.release()
                self._observe_gauges()

    def close(self) -> None:
        self._transport.close()

    def _try_downgrade(self, request: httpx.Request, body: dict) -> bool:
        current_model = body.get("model", "")
        if not current_model:
            return False
        cheaper = get_downgrade_target(current_model)
        if cheaper is None:
            return False
        body["model"] = cheaper
        new_content = json.dumps(body).encode("utf-8")
        object.__setattr__(request, "_content", new_content)
        request.headers["content-length"] = str(len(new_content))
        return True

    def _acquire_gate(self, priority: Priority, deadline: float | None) -> float:
        effective: float | None = None
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LatencyBudgetExceededError("request_timeout exceeded before gate acquire")
            qt = self.state.config.queue_timeout
            if qt is not None:
                effective = min(remaining, qt)
            else:
                effective = remaining
        wait = self.state.gate.acquire(priority, timeout=effective)
        return wait

    def _send_with_retries(
        self, request: httpx.Request, endpoint: str, deadline: float | None
    ) -> httpx.Response:
        self._retry_count = 0
        last_response: httpx.Response | None = None
        for attempt in range(self.state.config.retry_max_attempts):
            if _deadline_exceeded(deadline):
                raise LatencyBudgetExceededError("request_timeout exceeded during retries")

            try:
                response = self._transport.handle_request(request)
            except (httpx.TimeoutException, httpx.TransportError):
                self._retry_count += 1
                self._after_attempt(success=False, pressure=True)
                if attempt >= self.state.config.retry_max_attempts - 1:
                    raise
                self._metrics.call("retry_attempts", endpoint)
                self._sleep(backoff_delay(attempt, self.state.config))
                continue

            pressure = is_retryable_status(response.status_code, self.state.config)
            if not pressure or attempt >= self.state.config.retry_max_attempts - 1:
                return response

            self._retry_count += 1
            response.read()
            response.close()
            last_response = response
            self._after_attempt(success=False, pressure=True)
            self._metrics.call("retry_attempts", endpoint)
            self._sleep(backoff_delay(attempt, self.state.config))

        assert last_response is not None
        return last_response

    def _after_attempt(self, *, success: bool, pressure: bool) -> None:
        tripped = self.state.circuit.after_request(success=success)
        if tripped:
            self._metrics.call("circuit_trips")
        if pressure and self.state.aimd.record_pressure():
            self._metrics.call("aimd_changes", "decrease")

    def _record_outcome(self, status_code: int, *, success: bool) -> None:
        tripped = self.state.circuit.after_request(success=success)
        if tripped:
            self._metrics.call("circuit_trips")
        if success:
            if self.state.aimd.record_success():
                self._metrics.call("aimd_changes", "increase")
        elif is_retryable_status(status_code, self.state.config):
            if self.state.aimd.record_pressure():
                self._metrics.call("aimd_changes", "decrease")

    def _observe_queue(self, wait: float, priority: Priority) -> None:
        self._metrics.call("queue_wait", priority.value, method="observe", amount=wait)
        self._observe_gauges()

    def _observe_request(
        self, endpoint: str, priority: Priority, started: float, outcome: str
    ) -> None:
        self._metrics.call("requests", endpoint, priority.value, outcome)
        self._metrics.call(
            "duration", endpoint, priority.value, method="observe", amount=time.monotonic() - started
        )

    def _observe_gauges(self) -> None:
        tenant_id = get_current_tenant()
        if tenant_id is not None:
            tb = get_ledger().get(tenant_id)
            remaining = tb.remaining if tb is not None else None
        else:
            remaining = self.state.budget.remaining
        if remaining is not None:
            self._metrics.call("budget_remaining", method="set", value=remaining)
        self._metrics.call("queue_depth", method="set", value=self.state.gate.depth)
        self._metrics.call("concurrency_active", method="set", value=self.state.gate.active)
        self._metrics.call("concurrency_limit", method="set", value=self.state.aimd.current_limit)
        circuit_value = {
            CircuitState.CLOSED: 0,
            CircuitState.HALF_OPEN: 1,
            CircuitState.OPEN: 2,
        }[self.state.circuit.state]
        self._metrics.call("circuit_state", method="set", value=circuit_value)


class AsyncBackstopTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        state: BackstopState,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        sleep: AsyncRetrySleep | None = None,
    ) -> None:
        self.state = state
        self._transport = transport or httpx.AsyncHTTPTransport()
        self._sleep = sleep or asyncio.sleep
        self._metrics = get_metrics()
        self._cache = ResponseCache(
            max_entries=state.config.cache_max_entries,
            ttl=state.config.cache_ttl,
        ) if state.config.cache_enabled else None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        tracker = _LatencyTracker()
        meta = request_metadata(request, self.state.config)
        reservation: Reservation | LedgerReservation | None = None
        admitted = False

        body = _json_body(request)
        streaming = is_streaming(body) if body is not None else False

        if self._cache is not None and body is not None and not streaming:
            cached = self._cache.get(body)
            if cached is not None:
                self._metrics.call("cache_hits")
                tracker.completed_at = time.monotonic()
                response = _build_cached_response(cached[0], cached[1], cached[2])
                backstop_meta = tracker.build_meta(
                    estimated_tokens=meta.estimated_tokens,
                    actual_tokens=cached[1],
                    circuit_state=self.state.circuit.state.value,
                    endpoint=meta.endpoint,
                )
                setattr(response, "_backstop_meta", backstop_meta)
                return response

        hook_metadata = extract_backstop_headers(request)
        tenant_id = get_current_tenant()
        tenant_budget: object | None = None
        if tenant_id is not None:
            ledger = get_ledger()
            tenant_budget = ledger.get(tenant_id) if ledger else None

        downgraded = False
        try:
            if tenant_budget is not None:
                reservation = tenant_budget.reserve(meta.estimated_tokens)
            else:
                reservation = await self.state.budget.areserve(meta.estimated_tokens)
        except BudgetExceededError:
            if (
                tenant_budget is not None
                and getattr(tenant_budget, "on_exceed", None) == "downgrade"
                and body is not None
            ):
                if self._try_downgrade(request, body):
                    downgraded = True
                    meta = request_metadata(request, self.state.config)
                    try:
                        if tenant_budget is not None:
                            reservation = tenant_budget.reserve(meta.estimated_tokens)
                        else:
                            reservation = await self.state.budget.areserve(meta.estimated_tokens)
                    except BudgetExceededError:
                        reservation = None
                else:
                    self._metrics.call("budget_exceeded")
                    if tenant_id:
                        self._metrics.call("tenant_budget_exceeded", tenant_id)
                    raise
            else:
                self._metrics.call("budget_exceeded")
                if tenant_id:
                    self._metrics.call("tenant_budget_exceeded", tenant_id)
                raise

        try:
            if self.state.config.before_request is not None:
                hook = BeforeRequestHook(
                    endpoint=meta.endpoint,
                    priority=meta.priority,
                    estimated_tokens=meta.estimated_tokens,
                    metadata=hook_metadata.copy(),
                )
                self.state.config.before_request(hook)
                hook_metadata = hook.metadata

            deadline = _deadline_from_config(self.state.config)
            wait = await self._aacquire_gate(meta.priority, deadline)
            admitted = True
            tracker.queue_entered_at = time.monotonic()
            self._observe_queue(wait, meta.priority)
            self.state.circuit.before_request()
            tracker.request_sent_at = time.monotonic()

            response = await self._asend_with_retries(request, meta.endpoint, deadline)
            tracker.retry_count = self._retry_count

            if streaming:
                success = response.status_code < 400
                await async_setup_streaming(
                    response,
                    self.state,
                    reservation,
                    success=success,
                    tenant_budget=tenant_budget,
                    created_at=tracker.created_at,
                )
                usage = None
            else:
                await response.aread()
                tracker.first_byte_at = tracker.request_sent_at
                usage = response_usage_tokens(response)
                success = response.status_code < 400
                _reconcile(tenant_budget, self.state.budget, reservation, usage, success=success, downgraded=downgraded)
                self._record_outcome(response.status_code, success=success)
                if self._cache is not None and body is not None and usage is not None:
                    self._cache.set(body, response.content, usage, dict(response.headers))

            tracker.completed_at = time.monotonic()
            outcome = "success" if success else "error"
            self._observe_request(meta.endpoint, meta.priority, tracker.created_at, outcome)

            backstop_meta = tracker.build_meta(
                estimated_tokens=meta.estimated_tokens,
                actual_tokens=usage,
                circuit_state=self.state.circuit.state.value,
                endpoint=meta.endpoint,
                metadata=hook_metadata,
            )
            setattr(response, "_backstop_meta", backstop_meta)

            if self.state.config.after_response is not None:
                try:
                    after_hook = AfterResponseHook(
                        endpoint=meta.endpoint,
                        status_code=response.status_code,
                        actual_tokens=usage,
                        latency_ms=backstop_meta.total_latency_ms,
                        success=success,
                        metadata=hook_metadata,
                    )
                    self.state.config.after_response(after_hook)
                except Exception:
                    pass

            return response
        except CircuitBreakerOpenError:
            tracker.completed_at = time.monotonic()
            _reconcile(tenant_budget, self.state.budget, reservation, 0, success=False)
            self._observe_request(meta.endpoint, meta.priority, tracker.created_at, "circuit_open")
            raise
        except Exception:
            tracker.completed_at = time.monotonic()
            _reconcile(tenant_budget, self.state.budget, reservation, 0, success=False)
            self._record_outcome(599, success=False)
            self._observe_request(meta.endpoint, meta.priority, tracker.created_at, "exception")
            raise
        finally:
            if admitted:
                await self.state.gate.arelease()
                self._observe_gauges()

    async def aclose(self) -> None:
        await self._transport.aclose()

    def _try_downgrade(self, request: httpx.Request, body: dict) -> bool:
        current_model = body.get("model", "")
        if not current_model:
            return False
        cheaper = get_downgrade_target(current_model)
        if cheaper is None:
            return False
        body["model"] = cheaper
        new_content = json.dumps(body).encode("utf-8")
        object.__setattr__(request, "_content", new_content)
        request.headers["content-length"] = str(len(new_content))
        return True

    async def _aacquire_gate(self, priority: Priority, deadline: float | None) -> float:
        effective: float | None = None
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LatencyBudgetExceededError("request_timeout exceeded before gate acquire")
            qt = self.state.config.queue_timeout
            if qt is not None:
                effective = min(remaining, qt)
            else:
                effective = remaining
        wait = await self.state.gate.aacquire(priority, timeout=effective)
        return wait

    async def _asend_with_retries(
        self, request: httpx.Request, endpoint: str, deadline: float | None
    ) -> httpx.Response:
        self._retry_count = 0
        last_response: httpx.Response | None = None
        for attempt in range(self.state.config.retry_max_attempts):
            if _deadline_exceeded(deadline):
                raise LatencyBudgetExceededError("request_timeout exceeded during retries")

            try:
                response = await self._transport.handle_async_request(request)
            except (httpx.TimeoutException, httpx.TransportError):
                self._retry_count += 1
                self._after_attempt(success=False, pressure=True)
                if attempt >= self.state.config.retry_max_attempts - 1:
                    raise
                self._metrics.call("retry_attempts", endpoint)
                await self._sleep(backoff_delay(attempt, self.state.config))
                continue

            pressure = is_retryable_status(response.status_code, self.state.config)
            if not pressure or attempt >= self.state.config.retry_max_attempts - 1:
                return response

            self._retry_count += 1
            await response.aread()
            await response.aclose()
            last_response = response
            self._after_attempt(success=False, pressure=True)
            self._metrics.call("retry_attempts", endpoint)
            await self._sleep(backoff_delay(attempt, self.state.config))

        assert last_response is not None
        return last_response

    def _after_attempt(self, *, success: bool, pressure: bool) -> None:
        tripped = self.state.circuit.after_request(success=success)
        if tripped:
            self._metrics.call("circuit_trips")
        if pressure and self.state.aimd.record_pressure():
            self._metrics.call("aimd_changes", "decrease")

    def _record_outcome(self, status_code: int, *, success: bool) -> None:
        tripped = self.state.circuit.after_request(success=success)
        if tripped:
            self._metrics.call("circuit_trips")
        if success:
            if self.state.aimd.record_success():
                self._metrics.call("aimd_changes", "increase")
        elif is_retryable_status(status_code, self.state.config):
            if self.state.aimd.record_pressure():
                self._metrics.call("aimd_changes", "decrease")

    def _observe_queue(self, wait: float, priority: Priority) -> None:
        self._metrics.call("queue_wait", priority.value, method="observe", amount=wait)
        self._observe_gauges()

    def _observe_request(
        self, endpoint: str, priority: Priority, started: float, outcome: str
    ) -> None:
        self._metrics.call("requests", endpoint, priority.value, outcome)
        self._metrics.call(
            "duration", endpoint, priority.value, method="observe", amount=time.monotonic() - started
        )

    def _observe_gauges(self) -> None:
        tenant_id = get_current_tenant()
        if tenant_id is not None:
            tb = get_ledger().get(tenant_id)
            remaining = tb.remaining if tb is not None else None
        else:
            remaining = self.state.budget.remaining
        if remaining is not None:
            self._metrics.call("budget_remaining", method="set", value=remaining)
        self._metrics.call("queue_depth", method="set", value=self.state.gate.depth)
        self._metrics.call("concurrency_active", method="set", value=self.state.gate.active)
        self._metrics.call("concurrency_limit", method="set", value=self.state.aimd.current_limit)
        circuit_value = {
            CircuitState.CLOSED: 0,
            CircuitState.HALF_OPEN: 1,
            CircuitState.OPEN: 2,
        }[self.state.circuit.state]
        self._metrics.call("circuit_state", method="set", value=circuit_value)