from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from .budget import Reservation
from .circuit import CircuitState
from .config import Priority
from .exceptions import BudgetExceededError, CircuitBreakerOpenError
from .extract import request_metadata, response_usage_tokens
from .metrics import get_metrics
from .retry import backoff_delay, is_retryable_status
from .state import BackstopState

RetrySleep = Callable[[float], None]
AsyncRetrySleep = Callable[[float], Awaitable[None]]


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

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        meta = request_metadata(request, self.state.config)
        started = time.monotonic()
        reservation: Reservation | None = None
        wait = 0.0
        admitted = False

        try:
            reservation = self.state.budget.reserve(meta.estimated_tokens)
        except BudgetExceededError:
            self._metrics.call("budget_exceeded")
            raise

        try:
            wait = self.state.gate.acquire(meta.priority)
            admitted = True
            self._observe_queue(wait, meta.priority)
            self.state.circuit.before_request()
            response = self._send_with_retries(request, meta.endpoint)
            response.read()
            usage = response_usage_tokens(response)
            success = response.status_code < 400
            self.state.budget.reconcile(reservation, usage, success=success)
            self._record_outcome(response.status_code, success=success)
            self._observe_request(meta.endpoint, meta.priority, started, "success" if success else "error")
            return response
        except CircuitBreakerOpenError:
            self.state.budget.reconcile(reservation, 0, success=False)
            self._observe_request(meta.endpoint, meta.priority, started, "circuit_open")
            raise
        except Exception:
            if reservation is not None:
                self.state.budget.reconcile(reservation, 0, success=False)
            self._record_outcome(599, success=False)
            self._observe_request(meta.endpoint, meta.priority, started, "exception")
            raise
        finally:
            if admitted:
                self.state.gate.release()
                self._observe_gauges()

    def close(self) -> None:
        self._transport.close()

    def _send_with_retries(self, request: httpx.Request, endpoint: str) -> httpx.Response:
        last_response: httpx.Response | None = None
        for attempt in range(self.state.config.retry_max_attempts):
            try:
                response = self._transport.handle_request(request)
            except (httpx.TimeoutException, httpx.TransportError):
                pressure = True
                self._after_attempt(success=False, pressure=pressure)
                if attempt >= self.state.config.retry_max_attempts - 1:
                    raise
                self._metrics.call("retry_attempts", endpoint)
                self._sleep(backoff_delay(attempt, self.state.config))
                continue

            pressure = is_retryable_status(response.status_code, self.state.config)
            if not pressure or attempt >= self.state.config.retry_max_attempts - 1:
                return response

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

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        meta = request_metadata(request, self.state.config)
        started = time.monotonic()
        reservation: Reservation | None = None
        admitted = False

        try:
            reservation = await self.state.budget.areserve(meta.estimated_tokens)
        except BudgetExceededError:
            self._metrics.call("budget_exceeded")
            raise

        try:
            wait = await self.state.gate.aacquire(meta.priority)
            admitted = True
            self._observe_queue(wait, meta.priority)
            self.state.circuit.before_request()
            response = await self._send_with_retries(request, meta.endpoint)
            await response.aread()
            usage = response_usage_tokens(response)
            success = response.status_code < 400
            await self.state.budget.areconcile(reservation, usage, success=success)
            self._record_outcome(response.status_code, success=success)
            self._observe_request(meta.endpoint, meta.priority, started, "success" if success else "error")
            return response
        except CircuitBreakerOpenError:
            await self.state.budget.areconcile(reservation, 0, success=False)
            self._observe_request(meta.endpoint, meta.priority, started, "circuit_open")
            raise
        except Exception:
            if reservation is not None:
                await self.state.budget.areconcile(reservation, 0, success=False)
            self._record_outcome(599, success=False)
            self._observe_request(meta.endpoint, meta.priority, started, "exception")
            raise
        finally:
            if admitted:
                await self.state.gate.arelease()
                self._observe_gauges()

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def _send_with_retries(self, request: httpx.Request, endpoint: str) -> httpx.Response:
        last_response: httpx.Response | None = None
        for attempt in range(self.state.config.retry_max_attempts):
            try:
                response = await self._transport.handle_async_request(request)
            except (httpx.TimeoutException, httpx.TransportError):
                self._after_attempt(success=False, pressure=True)
                if attempt >= self.state.config.retry_max_attempts - 1:
                    raise
                self._metrics.call("retry_attempts", endpoint)
                await self._sleep(backoff_delay(attempt, self.state.config))
                continue

            pressure = is_retryable_status(response.status_code, self.state.config)
            if not pressure or attempt >= self.state.config.retry_max_attempts - 1:
                return response

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

