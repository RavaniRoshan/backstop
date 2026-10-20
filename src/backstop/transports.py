from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import httpx

from ._httpcompat import HTTPX, _HttpCompat
from .budget import Reservation
from .circuit import CircuitBreaker
from .config import BackstopConfig, Priority
from .exceptions import (
    BudgetExceededError,
    CircuitBreakerOpenError,
    LatencyBudgetExceededError,
)
from .extract import RequestMetadata, _json_body, request_metadata, response_usage
from .hooks import AfterResponseHook, BeforeRequestHook
from .latency import _LatencyTracker, extract_backstop_headers
from .ledger import (
    ReservationTicket as LedgerReservation,
)
from .ledger import (
    SpendEvent,
    current_attribution,
    get_current_tenant,
    get_ledger,
)
from .metrics import get_metrics
from .policy import DOWNGRADE, Policy, build_policy
from .pricing_catalog import compute_cost
from .quotas import has_ratelimit_headers
from .retry import backoff_delay, is_retryable_status
from .state import BackstopState
from .streaming import async_setup_streaming, is_streaming, setup_streaming

RetrySleep = Callable[[float], None]
AsyncRetrySleep = Callable[[float], Awaitable[None]]

#: URL hosts that name a provider the bundled price catalog prices. Matched as a
#: domain suffix, so ``api.openai.com`` and a regional or proxied OpenAI host
#: under the same domain both resolve.
_PROVIDER_HOSTS = (("openai.com", "openai"), ("anthropic.com", "anthropic"))

#: The provider recorded for a request to a host Backstop does not recognise —
#: Azure OpenAI, Bedrock, a gateway, a self-hosted vLLM. Deliberately not a
#: guess: an invented provider produces a chargeback row that looks authoritative
#: and is wrong, and the honest row is an unpriced one an operator can see. A
#: deployment on such a host can still get a price by filing an entry for
#: ``"unknown"`` in its own ``price_catalog_path``.

#: Recorded as the model when neither the request body nor the response named
#: one. ``SpendEvent`` refuses an empty model, and "unknown" is a fact a
#: chargeback can be filtered on; a plausible-looking guess is not.
UNKNOWN_MODEL = "unknown"


#: The provider recorded for a request whose host named neither of the two
#: providers the catalog prices. It is a real answer — the request went
#: somewhere — and it means the event is *unpriced*, because the catalog is
#: keyed by (provider, model) and the provider is what it does not know.
UNKNOWN_PROVIDER = "unknown"


def _provider_for_host(host: str) -> str:
    """Return the price catalog's provider name for ``host``, or ``unknown``.

    Domain-suffix match, so a custom ``base_url`` on the provider's own domain
    resolves the same as the default one. The port is already excluded by httpx's
    ``URL.host``.
    """
    lowered = host.lower()
    for domain, provider in _PROVIDER_HOSTS:
        if lowered == domain or lowered.endswith("." + domain):
            return provider
    return UNKNOWN_PROVIDER


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


def _build_fallback_request(
    request: httpx.Request,
    model: str,
    base_url: str | None,
    *,
    compat: _HttpCompat | None = None,
) -> httpx.Request | None:
    """Clone ``request`` pointing at a fallback target.

    Rewrites the request body's ``model`` to ``model`` and, when ``base_url`` is
    set, repoints the URL. Returns ``None`` when the request body isn't JSON.
    """
    compat = compat or HTTPX
    body = _json_body(request)
    if not isinstance(body, dict):
        return None
    new_body = dict(body)
    new_body["model"] = model
    new_content = json.dumps(new_body).encode("utf-8")

    headers = request.headers.copy()
    headers["content-length"] = str(len(new_content))
    if base_url:
        base = base_url.rstrip("/")
        path = request.url.raw_path.decode("ascii", "replace")
        try:
            url = compat.URL(base + path)
        except Exception:
            return None
    else:
        url = request.url
    return compat.Request(request.method, url, content=new_content, headers=headers)


def _build_cached_response(
    content: bytes,
    usage: int,
    headers: dict[str, str] | None,
    *,
    compat: _HttpCompat | None = None,
) -> httpx.Response:
    compat = compat or HTTPX
    clean_headers = {
        k: v
        for k, v in (headers or {}).items()
        if k.lower() not in _REPLAY_STRIP_HEADERS
    }
    return compat.Response(
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
    actual_usd: Decimal | None = None,
) -> None:
    """Settle a reservation against what the request actually cost.

    ``actual_usd`` is the exact cost the ledger priced. ``None`` means there
    is no measurement — the model could not be priced, or the ledger is off —
    and the estimate stands.
    """
    if reservation is None:
        if downgraded and tenant_budget is not None and usage is not None and success:
            tenant_budget.commit(
                LedgerReservation(getattr(tenant_budget, "tenant_id", ""), 0), usage, actual_usd
            )
        return
    if isinstance(reservation, LedgerReservation) and tenant_budget is not None:
        tenant_budget.commit(reservation, usage if success else 0, actual_usd)
    elif isinstance(reservation, Reservation):
        global_budget.reconcile(reservation, usage, success=success, actual_usd=actual_usd)


async def _areconcile(
    tenant_budget: object | None,
    global_budget: object,
    reservation: Reservation | LedgerReservation | None,
    usage: int | None,
    *,
    success: bool,
    downgraded: bool = False,
    actual_usd: Decimal | None = None,
) -> None:
    """Async twin of :func:`_reconcile`.

    Goes through ``Budget.areconcile`` so the commit runs on the await path
    rather than inline on the event loop. A shared backend still holds a
    synchronous client, so its ``acommit`` moves the call to a worker thread via
    ``asyncio.to_thread``; the in-memory backend commits in place.
    """
    if reservation is None:
        if downgraded and tenant_budget is not None and usage is not None and success:
            tenant_budget.commit(
                LedgerReservation(getattr(tenant_budget, "tenant_id", ""), 0), usage, actual_usd
            )
        return
    if isinstance(reservation, LedgerReservation) and tenant_budget is not None:
        tenant_budget.commit(reservation, usage if success else 0, actual_usd)
    elif isinstance(reservation, Reservation):
        await global_budget.areconcile(
            reservation, usage, success=success, actual_usd=actual_usd
        )


def _record_spend_if_enabled(
    state: BackstopState,
    request: httpx.Request,
    *,
    body: object,
    meta: "RequestMetadata",
    response: httpx.Response,
    tracker: _LatencyTracker,
    success: bool,
    usage: object,
    outcome: str | None = None,
) -> "Decimal | None":
    """The one line the ledger costs on the request path.

    Both transports call exactly this, and with the ledger and the detector both
    off — the default — this is the entire cost: one attribute load, one truth
    test, one function call. Nothing is built, nothing is read from the response,
    no catalog is touched, and no queue is offered an event.
    """
    config = state.config
    if not (config.ledger_enabled or config.detection_enabled):
        return None
    return _record_spend(
        state,
        request,
        body=body,
        priority=meta.priority,
        estimated_tokens=meta.estimated_tokens,
        response=response,
        created_at=tracker.created_at,
        retries=tracker.retry_count,
        outcome=outcome or ("success" if success else "error"),
        usage=usage,
    )


def _record_spend(
    state: BackstopState,
    request: httpx.Request,
    *,
    body: object,
    priority: Priority,
    estimated_tokens: int,
    response: httpx.Response,
    created_at: float,
    retries: int,
    outcome: str,
    usage: object,
) -> "Decimal | None":
    """Build, price, observe and submit one spend event. Never raises, never blocks.

    The whole ledger integration is this function plus the call site's
    ``config.ledger_enabled or config.detection_enabled`` test. With both off —
    the default — the test is all that runs, and the request path is untouched.

    **Nothing here may fail a request.** The body is wrapped in one ``except``,
    and the failure is counted on ``state.ledger_errors`` rather than dropped: a
    ledger that has quietly stopped working looks exactly like a healthy one.

    **Nothing here may block.** The only I/O — the writer's queue — is
    :meth:`~backstop.ledger.sink.BoundedWriter.submit`, which takes one short
    lock, appends to a bounded deque and returns, moving the sink's own work onto
    a background thread. No file is opened, no socket is touched, and no lock a
    sink could hold is taken on this path.

    Field provenance, because a chargeback is only as good as where its numbers
    came from:

    ``provider``
        The request URL's host, matched against the two providers the bundled
        price catalog prices. A host that names neither is recorded as
        ``"unknown"`` and therefore unpriced — see :data:`UNKNOWN_PROVIDER`.
    ``model``
        The model the *response* reported, which is a measurement of what was
        actually billed — a dated snapshot rather than the family name asked for.
        A streaming response has no parsed body yet, so it uses the model the
        request asked for. Neither recoverable means ``"unknown"``. Never
        invented. See :data:`UNKNOWN_MODEL`.
    ``input_tokens`` / ``output_tokens`` / ``cache_read_tokens`` / ``cache_write_tokens``
        The provider's own split. When the provider published only an aggregate,
        or nothing at all, the record is flagged ``estimated=True`` and carries
        the total it does know rather than a fabricated split — see below.
    ``endpoint``
        The full request URL, which ``SpendEvent`` normalises: no query string,
        no fragment, no ``user:pass@``, and a credential-shaped query parameter
        recorded as ``?<redacted>``. A path alone would not identify which
        provider a durable ledger row belongs to.
    ``request_id``
        ``x-request-id`` (OpenAI) or ``request-id`` (Anthropic) off the response
        when the provider sent one, so a chargeback row joins to a provider
        dashboard.
    ``latency_ms``
        Wall clock since the request entered the transport, read here. The
        tracker has not been closed at this point, so this is a slightly later
        and slightly larger figure than ``_backstop_meta.total_latency_ms``.

    **On a missing split.** Two provider shapes do not report one: a body with
    only an aggregate ``total_tokens``, and a body with no usage at all. In both
    cases the event records the magnitude it does know — the reported total, or
    ``estimated_tokens``, which is the local floor ``chars_per_token`` produced —
    as ``input_tokens``, with ``output_tokens`` left at zero and
    ``estimated=True``. That is a deliberate, visible understatement rather than
    a confident wrong split: an ``estimated`` row is countable and filterable in
    the export, and it errs toward under-charging, which is the safe direction
    for a floor. A streaming request always takes this path, because at stream
    setup the body has not been read and no usage exists yet.

    This is one module-level function rather than two methods because the sync and
    async transports are near-duplicates by design and both call it. They are not
    merged.
    """
    try:
        provider = _provider_for_host(request.url.host)
        input_tokens, output_tokens, cache_read, cache_write, estimated = _tokens_for(
            usage, estimated_tokens
        )
        event = SpendEvent(
            provider=provider,
            model=_model_for(usage, body),
            endpoint=str(request.url),
            priority=priority.value,
            outcome=outcome,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            latency_ms=(time.monotonic() - created_at) * 1000,
            retries=retries,
            estimated=estimated,
            attribution=current_attribution(),
            request_id=_request_id(response),
        )
        if state.prices is not None:
            priced = compute_cost(event, state.prices)
            if priced is not None:
                # Filled in place rather than by constructing a second event.
                # ``dataclasses.replace`` measures 7.0us here against 0.18us for
                # this, and it re-runs ``__post_init__`` — re-validating
                # thirteen fields and re-normalising an endpoint that is already
                # normalised — to set exactly one of them. Nothing has seen the
                # event yet: it is built, priced and filled inside this function,
                # and only then handed to the detector and the writer.
                # ``SpendEvent.__post_init__`` writes its normalised endpoint the
                # same way, for the same reason.
                object.__setattr__(event, "cost", priced)
        # The return value is deliberately not consumed here: a detection
        # signal leaves through the detector's own ``signal_sink``
        # (``backstop.state.DetectionSignalSink``), which reports it to the
        # metric surface from outside the detector's lock. Iterating the list on
        # this path would put a per-signal loop and a metric dispatch on the
        # request path to learn nothing this does not already record.
        state.detector.observe(event)
        if state.config.ledger_enabled:
            state.ledger.submit(event)
        # The exact cost, for the caller to settle a dollar reservation
        # against. ``None`` when the model could not be priced — a visible
        # hole, not a zero.
        breakdown = getattr(event, "cost", None)
        return None if breakdown is None else breakdown.total_usd
    except Exception:
        state.ledger_errors += 1
        return None


def _model_for(usage: object, body: object) -> str:
    """The model that was actually served: the response's, else the request's.

    The response's own ``model`` is preferred because it names the build that was
    billed — a dated snapshot rather than the family name the caller asked for.
    A streaming response has no parsed body at stream setup, so the request's
    ``model`` is what it uses. Neither being recoverable means ``"unknown"``, not
    a guess.
    """
    reported = getattr(usage, "model", None)
    if isinstance(reported, str) and reported:
        return reported
    if isinstance(body, dict):
        asked = body.get("model")
        if isinstance(asked, str) and asked:
            return asked
    return UNKNOWN_MODEL


def _tokens_for(
    usage: object, estimated_tokens: int
) -> tuple[int, int, int, int, bool]:
    """Map a :class:`~backstop.extract.TokenUsage` (or its absence) onto an event.

    Returns ``(input, output, cache_read, cache_write, estimated)``. The second
    element of the pair is ``True`` whenever the numbers are not a provider
    measurement of the split, which is the case for a missing usage, an
    aggregate-only usage, and every streaming request.
    """
    split = getattr(usage, "split", False)
    if usage is not None and split:
        return (
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_tokens,
            usage.cache_write_tokens,
            False,
        )
    if usage is not None:
        # An aggregate with no split beside it. The total is a measurement; where
        # it came from is not, so the whole magnitude lands on input and the
        # record is flagged.
        return (usage.total, 0, 0, 0, True)
    # No usage at all: the local floor, which is what the reservation was made
    # from. Recorded so the request is visible in the chargeback as an estimate
    # rather than absent from it as though it were free.
    return (max(0, estimated_tokens), 0, 0, 0, True)


def _request_id(response: httpx.Response) -> str | None:
    """The provider's own id for this request, when it sent one.

    OpenAI calls it ``x-request-id`` and Anthropic ``request-id``; both are read
    so a chargeback row joins to a provider dashboard without the caller having
    to know which provider they are on.
    """
    try:
        headers = response.headers
        value = headers.get("x-request-id") or headers.get("request-id")
    except Exception:
        return None
    return value if isinstance(value, str) and value else None


def _build_alerts(config) -> object | None:
    """Build a BudgetAlertManager from config, or None when unconfigured."""
    if not config.webhook_endpoints:
        return None
    from .notifications import BudgetAlertManager

    return BudgetAlertManager(
        endpoints=list(config.webhook_endpoints),
        secret=config.webhook_secret,
        tiers=list(config.alert_tiers) if config.alert_tiers else None,
        dedup_ttl=config.alert_dedup_ttl,
        project_horizon_calls=config.alert_project_horizon_calls,
    )


def _dispatch_alert(alerts, tenant_id: str | None, used: float, limit: float) -> None:
    """Fire-and-forget budget alert so the request path is never blocked."""
    if alerts is None or limit <= 0:
        return
    try:
        import threading

        threading.Thread(
            target=alerts.observe, args=(tenant_id or "", used, limit), daemon=True
        ).start()
    except Exception:
        pass


class BackstopTransport:
    """In-process transport guard.

    Deliberately inherits from nothing. A transport is a duck-typed interface
    (`handle_request`) in `httpx`, in `httpx2` and in every provider SDK we wrap,
    and each of those bases is a *different class* - so subclassing one of them
    means the class is wrong for the other family. It also cannot be pinned
    reliably: an installed SDK (`anthropic` 0.116.0) rebinds
    `httpx.BaseTransport` to its own class at import time, so by the time this
    module is evaluated the name may already refer to something else, depending
    entirely on what the user's application imported first. The behavioural
    interface is what matters and it is verified by test.

    `httpx.Client` additionally requires the context-manager protocol on its
    transport, so those two methods delegate to the wrapped inner transport.
    """

    def __enter__(self) -> "BackstopTransport":
        self._transport.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> object:
        return self._transport.__exit__(*exc_info)

    def __init__(
        self,
        state: BackstopState,
        transport: Any | None = None,
        *,
        sleep: RetrySleep | None = None,
        compat: _HttpCompat | None = None,
    ) -> None:
        self.state = state
        self._compat = compat or HTTPX
        self._transport = transport or self._compat.HTTPTransport()
        self._sleep = sleep or time.sleep
        self._metrics = get_metrics()
        # The decisions live in the Policy, so the sync and async transports
        # cannot drift apart on them. See `backstop.policy`.
        self._policy: Policy = build_policy(state, compat=self._compat, config=state.config)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        tracker = _LatencyTracker()
        reservation: Reservation | LedgerReservation | None = None
        admitted = False

        # Decoded once. The metadata needs the body and the request path
        # needs it again, and decoding it twice meant two full JSON parses
        # per request.
        body = _json_body(request)
        meta = request_metadata(request, self.state.config, body=body)
        streaming = is_streaming(body) if body is not None else False

        if body is not None and not streaming:
            cached = self._policy.cache_get(body)
            if cached is not None:
                content, usage, headers, semantic = cached
                self._policy.note_cache_hit(semantic)
                tracker.completed_at = time.monotonic()
                response = _build_cached_response(content, usage, headers, compat=self._compat)
                backstop_meta = tracker.build_meta(
                    estimated_tokens=meta.estimated_tokens,
                    actual_tokens=usage,
                    circuit_state=self.state.circuit.state.value,
                    endpoint=meta.endpoint,
                )
                setattr(response, "_backstop_meta", backstop_meta)
                return response

        hook_metadata = extract_backstop_headers(request)
        tenant_id = get_current_tenant()
        if self.state.config.virtual_keys is not None:
            vk = request.headers.get(self.state.config.virtual_key_header)
            if vk is not None:
                tid = self.state.config.tenant_for_key(vk)
                if tid is not None:
                    tenant_id = tid
        self._policy.resolve_secret(request)
        tenant_budget: object | None = None
        if tenant_id is not None:
            ledger = get_ledger()
            tenant_budget = ledger.get(tenant_id) if ledger else None
        circuit = self.state.circuit_for(tenant_id)

        usd_estimate = self._dollar_estimate(meta, body, tenant_budget)
        downgraded = False
        try:
            reservation = self._reserve(tenant_budget, meta.estimated_tokens, usd_estimate)
        except BudgetExceededError:
            action = self._policy.budget_exhausted(
                meta, tenant_budget, body, request, tenant_id
            )
            if action == DOWNGRADE:
                downgraded = True
                meta = request_metadata(request, self.state.config, body=body)
                usd_estimate = self._dollar_estimate(meta, body, tenant_budget)
                try:
                    reservation = self._reserve(
                        tenant_budget, meta.estimated_tokens, usd_estimate
                    )
                except BudgetExceededError:
                    # The cheaper model did not fit either. The request still
                    # proceeds, without a reservation.
                    reservation = None
            else:
                # Shadow mode: observe, never block.
                reservation = None

        try:
            self._policy.pre_admit_checks(request, meta, tenant_id)
        except Exception:
            # The reservation was taken before admission ran. A denial here has to
            # hand it back, or every rejected request permanently drains budget.
            _reconcile(tenant_budget, self.state.budget, reservation, 0, success=False)
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
            self._policy.observe_queue(wait, meta.priority, tenant_budget, tenant_id, circuit)
            # In shadow mode an open circuit is observed, not enforced.
            self._policy.circuit_admits(circuit, tenant_id)
            tracker.request_sent_at = time.monotonic()

            if self.state.config.compress is not None and isinstance(body, dict):
                try:
                    compressed = self.state.config.compress(body, body.get("model", ""))
                    if isinstance(compressed, dict):
                        new_content = json.dumps(compressed).encode("utf-8")
                        object.__setattr__(request, "_content", new_content)
                        request.headers["content-length"] = str(len(new_content))
                except Exception:
                    pass

            response = self._send_with_retries(request, meta.endpoint, deadline, circuit)
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
                # Record at dispatch, not at consumption: the point is to release
                # the half-open probe, not to measure stream lifetime. Skipping
                # this left a circuit that had gone half-open stuck in half-open,
                # so every later request was rejected with CircuitBreakerOpenError.
                self._policy.record_outcome(response.status_code, success=success, circuit=circuit)
                usage = None
                # The stream has not been read, so there is no provider usage to
                # record; the event says so rather than claiming a measurement.
                # Recorded here, beside the circuit outcome, for the same reason
                # the outcome is: at dispatch, not at consumption.
                _record_spend_if_enabled(
                    self.state,
                    request,
                    body=body,
                    meta=meta,
                    response=response,
                    tracker=tracker,
                    success=success,
                    usage=None,
                )
            else:
                response.read()
                tracker.first_byte_at = tracker.request_sent_at
                # Read once, used twice. ``usage`` is the total the budget
                # reconciles against — the number ``response_usage_tokens`` has
                # always returned for this response — and ``usage_split`` is the
                # same read's parts, which the ledger bills at different rates.
                # Reading the body a second time for the ledger would cost
                # another full JSON decode per request for no new information.
                usage_split = response_usage(response)
                usage = None if usage_split is None else usage_split.total
                success = response.status_code < 400
                if self.state.quota is not None and has_ratelimit_headers(response.headers):
                    self.state.quota.ingest(dict(response.headers))
                    self.state.quota.adjust(self.state.aimd)
                # The spend record runs first, so its exact cost is available
                # to settle the dollar reservation against. Both read the same
                # response, so the ledger and the budget never disagree about
                # what a request cost.
                actual_usd = _record_spend_if_enabled(
                    self.state,
                    request,
                    body=body,
                    meta=meta,
                    response=response,
                    tracker=tracker,
                    success=success,
                    usage=usage_split,
                )
                _reconcile(
                    tenant_budget,
                    self.state.budget,
                    reservation,
                    usage,
                    success=success,
                    downgraded=downgraded,
                    actual_usd=actual_usd,
                )
                self._policy.record_outcome(response.status_code, success=success, circuit=circuit)
                self._policy.alert_on_spend(tenant_id, tenant_budget)
                if body is not None and usage is not None:
                    self._policy.cache_set(body, response.content, usage, dict(response.headers))
                self._policy.maybe_forecast_enforce()

            tracker.completed_at = time.monotonic()
            outcome = "success" if success else "error"
            self._policy.observe_request(meta.endpoint, meta.priority, tracker.created_at, outcome)

            backstop_meta = tracker.build_meta(
                estimated_tokens=meta.estimated_tokens,
                actual_tokens=usage,
                circuit_state=circuit.state.value,
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
            fallback = self._try_fallback(
                request, meta, reservation, tenant_budget, tracker, hook_metadata, circuit,
                tenant_id=tenant_id,
            )
            if fallback is not None:
                self._policy.audit("fallback", "circuit_open", meta, tenant_id=tenant_id)
                return fallback
            tracker.completed_at = time.monotonic()
            _reconcile(tenant_budget, self.state.budget, reservation, 0, success=False)
            self._policy.observe_request(meta.endpoint, meta.priority, tracker.created_at, "circuit_open")
            self._policy.audit("deny", "circuit_open", meta, tenant_id=tenant_id)
            raise
        except Exception:
            tracker.completed_at = time.monotonic()
            _reconcile(tenant_budget, self.state.budget, reservation, 0, success=False)
            self._policy.record_outcome(599, success=False, circuit=circuit)
            self._policy.observe_request(meta.endpoint, meta.priority, tracker.created_at, "exception")
            raise
        finally:
            if admitted:
                self.state.gate.release()
                self._policy.observe_gauges(circuit, tenant_budget, tenant_id)

    @property
    def shadow_collector(self) -> object | None:
        """The collector the ``would_*`` shadow counters are recorded in.

        ``None`` when shadow mode is off. Exposed so a caller — the ``verify``
        runner, a dashboard — can read the counters, or supply its own, without
        reaching into a private attribute.
        """
        return self._policy.shadow

    @shadow_collector.setter
    def shadow_collector(self, collector: object | None) -> None:
        self._policy.shadow = collector

    @property
    def alerts(self) -> object | None:
        """The budget alert manager this transport fires alerts from."""
        return self._policy.alerts

    @alerts.setter
    def alerts(self, manager: object | None) -> None:
        self._policy.alerts = manager

    def _dollar_estimate(
        self, meta: RequestMetadata, body: object, tenant_budget: object | None
    ) -> Decimal:
        """What this request is expected to cost, when a dollar ceiling is in force.

        Zero when there is no dollar ceiling: the token ceiling alone does
        not need a price, and a process that has not asked for a dollar
        ceiling should not pay for a price lookup on every request.

        When there *is* a dollar ceiling, the model has to be priceable —
        a ceiling with an unpriced hole in it is not a ceiling — so
        :meth:`Policy.require_price` refuses the request if it is not.
        """
        if self.state.config.budget_usd is None:
            if tenant_budget is None or getattr(tenant_budget, "limit_usd", None) is None:
                return Decimal("0.000000")
        model = body.get("model") if isinstance(body, dict) else None
        if not isinstance(model, str) or not model:
            return Decimal("0.000000")
        self._policy.require_price(model)
        return self._policy.estimate_usd(meta, model) or Decimal("0.000000")

    def _reserve(
        self, tenant_budget: object | None, tokens: int, usd: Decimal = Decimal("0.000000")
    ) -> object:
        """Hold the request's budget.

        The caller does this, not the Policy, because reserving may be
        asynchronous — the async transport has to await a shared Redis budget
        rather than block the event loop on it.

        Both ceilings are checked: the token one and, when there is one, the
        dollar one.
        """
        if tenant_budget is not None:
            return tenant_budget.reserve(tokens, usd)
        return self.state.budget.reserve(tokens, usd)

    def close(self) -> None:
        self._transport.close()

    def _try_fallback(
        self,
        request: httpx.Request,
        meta: object,
        reservation: object,
        tenant_budget: object,
        tracker: object,
        hook_metadata: dict,
        circuit: CircuitBreaker | None = None,
        tenant_id: str | None = None,
    ) -> httpx.Response | None:
        """Attempt the configured fallback chain when the circuit is open.

        Walks ``config.fallback_targets`` (priority-aware) in order, returning
        the first successful response. Returns ``None`` when no target succeeds
        so the caller can re-raise the original ``CircuitBreakerOpenError``.
        """
        targets = self._policy.fallback_targets(getattr(meta, "priority", None))
        if not targets:
            return None
        for target in targets:
            fb_request = _build_fallback_request(
                request, target["model"], target.get("base_url"), compat=self._compat
            )
            if fb_request is None:
                continue
            try:
                response = self._transport.handle_request(fb_request)
                response.read()
            except Exception:
                self._metrics.call("fallback_attempts")
                continue
            usage_split = response_usage(response)
            usage = None if usage_split is None else usage_split.total
            success = response.status_code < 400
            # The spend record runs first, so its exact cost settles the
            # dollar reservation.
            actual_usd = _record_spend_if_enabled(
                self.state,
                fb_request,
                body=_json_body(fb_request),
                meta=meta,
                response=response,
                tracker=tracker,
                success=success,
                usage=usage_split,
                outcome="fallback",
            )
            _reconcile(
                tenant_budget,
                self.state.budget,
                reservation,
                usage,
                success=success,
                actual_usd=actual_usd,
            )
            self._policy.record_outcome(response.status_code, success=success, circuit=circuit)
            # A fallback that succeeded is a request that cost money, so it is
            # billed as its own event with outcome "fallback" — the reason
            # ``SpendEvent`` declares that outcome at all. Recorded above,
            # because this is the only place the fallback's own model and
            # usage exist.
            self._policy.alert_on_spend(tenant_id, tenant_budget)
            tracker.completed_at = time.monotonic()
            self._policy.observe_request(meta.endpoint, meta.priority, tracker.created_at, "fallback")
            backstop_meta = tracker.build_meta(
                estimated_tokens=meta.estimated_tokens,
                actual_tokens=usage,
                circuit_state=(circuit or self.state.circuit).state.value,
                endpoint=meta.endpoint,
                metadata=hook_metadata,
            )
            setattr(response, "_backstop_meta", backstop_meta)
            return response
        return None

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
        self, request: httpx.Request, endpoint: str, deadline: float | None, circuit: CircuitBreaker | None = None
    ) -> httpx.Response:
        self._retry_count = 0
        last_response: httpx.Response | None = None
        for attempt in range(self.state.config.retry_max_attempts):
            if _deadline_exceeded(deadline):
                raise LatencyBudgetExceededError("request_timeout exceeded during retries")

            try:
                response = self._transport.handle_request(request)
            except (self._compat.TimeoutException, self._compat.TransportError):
                self._retry_count += 1
                self._policy.after_attempt(success=False, pressure=True, circuit=circuit)
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
            self._policy.after_attempt(success=False, pressure=True, circuit=circuit)
            self._metrics.call("retry_attempts", endpoint)
            self._sleep(backoff_delay(attempt, self.state.config))

        assert last_response is not None
        return last_response

class AsyncBackstopTransport:
    """Async twin of :class:`BackstopTransport`; duck-typed for the same reasons.

    `httpx.AsyncClient` additionally requires the async context-manager
    protocol on its transport, so these two are implemented by delegating to the
    wrapped inner transport. `httpx.AsyncBaseTransport` is not subclassed,
    because for an httpx2-based SDK it is a different class entirely and its
    identity is not stable across a process that has imported an SDK.
    """

    async def __aenter__(self) -> "AsyncBackstopTransport":
        await self._transport.__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> object:
        return await self._transport.__aexit__(*exc_info)
    def __init__(
        self,
        state: BackstopState,
        transport: Any | None = None,
        *,
        sleep: AsyncRetrySleep | None = None,
        compat: _HttpCompat | None = None,
    ) -> None:
        self.state = state
        self._compat = compat or HTTPX
        self._transport = transport or self._compat.AsyncHTTPTransport()
        self._sleep = sleep or asyncio.sleep
        self._metrics = get_metrics()
        # The decisions live in the Policy, so the sync and async transports
        # cannot drift apart on them. See `backstop.policy`.
        self._policy: Policy = build_policy(state, compat=self._compat, config=state.config)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        tracker = _LatencyTracker()
        reservation: Reservation | LedgerReservation | None = None
        admitted = False

        # Decoded once. The metadata needs the body and the request path
        # needs it again, and decoding it twice meant two full JSON parses
        # per request.
        body = _json_body(request)
        meta = request_metadata(request, self.state.config, body=body)
        streaming = is_streaming(body) if body is not None else False

        if body is not None and not streaming:
            cached = self._policy.cache_get(body)
            if cached is not None:
                content, usage, headers, semantic = cached
                self._policy.note_cache_hit(semantic)
                tracker.completed_at = time.monotonic()
                response = _build_cached_response(content, usage, headers, compat=self._compat)
                backstop_meta = tracker.build_meta(
                    estimated_tokens=meta.estimated_tokens,
                    actual_tokens=usage,
                    circuit_state=self.state.circuit.state.value,
                    endpoint=meta.endpoint,
                )
                setattr(response, "_backstop_meta", backstop_meta)
                return response

        hook_metadata = extract_backstop_headers(request)
        tenant_id = get_current_tenant()
        if self.state.config.virtual_keys is not None:
            vk = request.headers.get(self.state.config.virtual_key_header)
            if vk is not None:
                tid = self.state.config.tenant_for_key(vk)
                if tid is not None:
                    tenant_id = tid
        self._policy.resolve_secret(request)
        tenant_budget: object | None = None
        if tenant_id is not None:
            ledger = get_ledger()
            tenant_budget = ledger.get(tenant_id) if ledger else None
        circuit = self.state.circuit_for(tenant_id)

        usd_estimate = self._dollar_estimate(meta, body, tenant_budget)
        downgraded = False
        try:
            reservation = await self._areserve(
                tenant_budget, meta.estimated_tokens, usd_estimate
            )
        except BudgetExceededError:
            action = self._policy.budget_exhausted(
                meta, tenant_budget, body, request, tenant_id
            )
            if action == DOWNGRADE:
                downgraded = True
                meta = request_metadata(request, self.state.config, body=body)
                usd_estimate = self._dollar_estimate(meta, body, tenant_budget)
                try:
                    reservation = await self._areserve(
                        tenant_budget, meta.estimated_tokens, usd_estimate
                    )
                except BudgetExceededError:
                    # The cheaper model did not fit either. The request still
                    # proceeds, without a reservation.
                    reservation = None
            else:
                # Shadow mode: observe, never block.
                reservation = None

        try:
            self._policy.pre_admit_checks(request, meta, tenant_id)
        except Exception:
            # Async twin of the sync branch: a pre-admission denial has to hand
            # the reservation back, or every rejected request permanently drains
            # budget.
            await _areconcile(tenant_budget, self.state.budget, reservation, 0, success=False)
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
            self._policy.observe_queue(wait, meta.priority, tenant_budget, tenant_id, circuit)
            # In shadow mode an open circuit is observed, not enforced.
            self._policy.circuit_admits(circuit, tenant_id)
            tracker.request_sent_at = time.monotonic()

            if self.state.config.compress is not None and isinstance(body, dict):
                try:
                    compressed = self.state.config.compress(body, body.get("model", ""))
                    if isinstance(compressed, dict):
                        new_content = json.dumps(compressed).encode("utf-8")
                        object.__setattr__(request, "_content", new_content)
                        request.headers["content-length"] = str(len(new_content))
                except Exception:
                    pass

            response = await self._asend_with_retries(request, meta.endpoint, deadline, circuit)
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
                # Async twin of the sync branch: record at dispatch so the
                # half-open probe is released by a stream that set up cleanly.
                self._policy.record_outcome(response.status_code, success=success, circuit=circuit)
                usage = None
                # Async twin of the sync branch: recorded at dispatch beside the
                # circuit outcome, with no provider usage available because the
                # stream has not been read.
                _record_spend_if_enabled(
                    self.state,
                    request,
                    body=body,
                    meta=meta,
                    response=response,
                    tracker=tracker,
                    success=success,
                    usage=None,
                )
            else:
                await response.aread()
                tracker.first_byte_at = tracker.request_sent_at
                # Async twin of the sync branch: one read, both consumers.
                usage_split = response_usage(response)
                usage = None if usage_split is None else usage_split.total
                success = response.status_code < 400
                if self.state.quota is not None and has_ratelimit_headers(response.headers):
                    self.state.quota.ingest(dict(response.headers))
                    self.state.quota.adjust(self.state.aimd)
                # The spend record runs first, so its exact cost is available
                # to settle the dollar reservation against. Both read the same
                # response, so the ledger and the budget never disagree about
                # what a request cost.
                actual_usd = _record_spend_if_enabled(
                    self.state,
                    request,
                    body=body,
                    meta=meta,
                    response=response,
                    tracker=tracker,
                    success=success,
                    usage=usage_split,
                )
                await _areconcile(
                    tenant_budget,
                    self.state.budget,
                    reservation,
                    usage,
                    success=success,
                    downgraded=downgraded,
                    actual_usd=actual_usd,
                )
                self._policy.record_outcome(response.status_code, success=success, circuit=circuit)
                self._policy.alert_on_spend(tenant_id, tenant_budget)
                if body is not None and usage is not None:
                    self._policy.cache_set(body, response.content, usage, dict(response.headers))
                self._policy.maybe_forecast_enforce()

            tracker.completed_at = time.monotonic()
            outcome = "success" if success else "error"
            self._policy.observe_request(meta.endpoint, meta.priority, tracker.created_at, outcome)

            backstop_meta = tracker.build_meta(
                estimated_tokens=meta.estimated_tokens,
                actual_tokens=usage,
                circuit_state=circuit.state.value,
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
            fallback = await self._try_fallback(
                request, meta, reservation, tenant_budget, tracker, hook_metadata, circuit,
                tenant_id=tenant_id,
            )
            if fallback is not None:
                self._policy.audit("fallback", "circuit_open", meta, tenant_id=tenant_id)
                return fallback
            tracker.completed_at = time.monotonic()
            await _areconcile(tenant_budget, self.state.budget, reservation, 0, success=False)
            self._policy.observe_request(
                meta.endpoint, meta.priority, tracker.created_at, "circuit_open"
            )
            self._policy.audit("deny", "circuit_open", meta, tenant_id=tenant_id)
            raise
        except Exception:
            tracker.completed_at = time.monotonic()
            await _areconcile(tenant_budget, self.state.budget, reservation, 0, success=False)
            self._policy.record_outcome(599, success=False, circuit=circuit)
            self._policy.observe_request(meta.endpoint, meta.priority, tracker.created_at, "exception")
            raise
        finally:
            if admitted:
                await self.state.gate.arelease()
                self._policy.observe_gauges(circuit, tenant_budget, tenant_id)

    @property
    def shadow_collector(self) -> object | None:
        """The collector the ``would_*`` shadow counters are recorded in.

        The async twin of :attr:`BackstopTransport.shadow_collector`.
        """
        return self._policy.shadow

    @shadow_collector.setter
    def shadow_collector(self, collector: object | None) -> None:
        self._policy.shadow = collector

    @property
    def alerts(self) -> object | None:
        """The budget alert manager this transport fires alerts from."""
        return self._policy.alerts

    @alerts.setter
    def alerts(self, manager: object | None) -> None:
        self._policy.alerts = manager

    def _dollar_estimate(
        self, meta: RequestMetadata, body: object, tenant_budget: object | None
    ) -> Decimal:
        """What this request is expected to cost, when a dollar ceiling is in force.

        Zero when there is no dollar ceiling: the token ceiling alone does
        not need a price, and a process that has not asked for a dollar
        ceiling should not pay for a price lookup on every request.

        When there *is* a dollar ceiling, the model has to be priceable —
        a ceiling with an unpriced hole in it is not a ceiling — so
        :meth:`Policy.require_price` refuses the request if it is not.
        """
        if self.state.config.budget_usd is None:
            if tenant_budget is None or getattr(tenant_budget, "limit_usd", None) is None:
                return Decimal("0.000000")
        model = body.get("model") if isinstance(body, dict) else None
        if not isinstance(model, str) or not model:
            return Decimal("0.000000")
        self._policy.require_price(model)
        return self._policy.estimate_usd(meta, model) or Decimal("0.000000")

    async def _areserve(
        self, tenant_budget: object | None, tokens: int, usd: Decimal = Decimal("0.000000")
    ) -> object:
        """Hold the request's budget, awaiting a shared one.

        The async twin of :meth:`BackstopTransport._reserve`. A shared Redis
        budget has to be awaited: reserving it synchronously on the event loop
        blocks every other task in the loop for the length of the round trip.
        """
        if tenant_budget is not None:
            return tenant_budget.reserve(tokens, usd)
        return await self.state.budget.areserve(tokens, usd)

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def _try_fallback(
        self,
        request: httpx.Request,
        meta: object,
        reservation: object,
        tenant_budget: object,
        tracker: object,
        hook_metadata: dict,
        circuit: CircuitBreaker | None = None,
        tenant_id: str | None = None,
    ) -> httpx.Response | None:
        targets = self._policy.fallback_targets(getattr(meta, "priority", None))
        if not targets:
            return None
        for target in targets:
            fb_request = _build_fallback_request(
                request, target["model"], target.get("base_url"), compat=self._compat
            )
            if fb_request is None:
                continue
            try:
                response = await self._transport.handle_async_request(fb_request)
                await response.aread()
            except Exception:
                self._metrics.call("fallback_attempts")
                continue
            usage_split = response_usage(response)
            usage = None if usage_split is None else usage_split.total
            success = response.status_code < 400
            # Async twin of the sync branch: the spend record runs first, so
            # its exact cost settles the dollar reservation.
            actual_usd = _record_spend_if_enabled(
                self.state,
                fb_request,
                body=_json_body(fb_request),
                meta=meta,
                response=response,
                tracker=tracker,
                success=success,
                usage=usage_split,
                outcome="fallback",
            )
            await _areconcile(
                tenant_budget,
                self.state.budget,
                reservation,
                usage,
                success=success,
                actual_usd=actual_usd,
            )
            self._policy.record_outcome(response.status_code, success=success, circuit=circuit)
            self._policy.alert_on_spend(tenant_id, tenant_budget)
            tracker.completed_at = time.monotonic()
            self._policy.observe_request(meta.endpoint, meta.priority, tracker.created_at, "fallback")
            backstop_meta = tracker.build_meta(
                estimated_tokens=meta.estimated_tokens,
                actual_tokens=usage,
                circuit_state=(circuit or self.state.circuit).state.value,
                endpoint=meta.endpoint,
                metadata=hook_metadata,
            )
            setattr(response, "_backstop_meta", backstop_meta)
            return response
        return None

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
        self, request: httpx.Request, endpoint: str, deadline: float | None, circuit: CircuitBreaker | None = None
    ) -> httpx.Response:
        self._retry_count = 0
        last_response: httpx.Response | None = None
        for attempt in range(self.state.config.retry_max_attempts):
            if _deadline_exceeded(deadline):
                raise LatencyBudgetExceededError("request_timeout exceeded during retries")

            try:
                response = await self._transport.handle_async_request(request)
            except (self._compat.TimeoutException, self._compat.TransportError):
                self._retry_count += 1
                self._policy.after_attempt(success=False, pressure=True, circuit=circuit)
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
            self._policy.after_attempt(success=False, pressure=True, circuit=circuit)
            self._metrics.call("retry_attempts", endpoint)
            await self._sleep(backoff_delay(attempt, self.state.config))

        assert last_response is not None
        return last_response
