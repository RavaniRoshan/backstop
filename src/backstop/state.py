from __future__ import annotations

import atexit
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field

from .admission import PriorityGate
from .aimd import AIMDController
from .audit import AuditLog
from .budget import Budget
from .circuit import CircuitBreaker
from .config import BackstopConfig
from .detection import DetectionSignal, RunawayDetector
from .ledger import Attribution, BoundedWriter, CloseReport, JsonlSink, MemorySink, NullSink
from .metrics import disable_otel, enable_otel, get_metrics
from .pricing_catalog import PriceCatalog
from .quotas import QuotaMonitor
from .state_backends import BudgetBackend, build_backend
from .telemetry import get_registry


class DetectionSignalSink:
    """Where a detection signal goes: the metric surface, and nothing else.

    The detector already takes a ``signal_sink`` and calls ``record`` on it from
    outside its own lock, swallowing whatever it raises (:meth:`RunawayDetector`
    documents both). This is that sink, and it exists because a signal nobody
    receives is a signal nobody can tune against — which is the whole argument
    for the shadow mode. The alternative, reporting each signal at the transport
    call site, would put a per-signal loop and a per-signal metric dispatch on
    the request path; this keeps both where the rest of the enforcement
    telemetry already is, and keeps the hot path to the ``observe`` call it
    already had.

    Two instruments and no more: a counter so a dashboard and an alert can see
    that a key is misbehaving, and a histogram of the observed value so the
    threshold can be set from the distribution of what crossed it rather than
    from a count. **The attribution is not a label** — see the label rule in
    :mod:`backstop.metrics` — so a process watching ten thousand sessions
    produces the same four-by-three series as one watching ten.

    Stateless and shared by every state: the metric surface is a process-wide
    singleton, so a per-session sink would be a copy of nothing.
    """

    __slots__ = ()

    def record(self, signal: DetectionSignal) -> None:
        """Report one signal. Called off the detector's lock; never raises here."""
        metrics = get_metrics()
        metrics.call("detection_signals", signal.kind, signal.severity)
        metrics.call(
            "detection_signal_magnitude",
            signal.kind,
            method="observe",
            amount=float(signal.observed),
        )

    def evicted(self, key: Attribution) -> None:
        """Report that a key left the detector to stay inside its bound.

        The key is accepted and ignored: what makes an eviction worth counting is
        *that* it happened, not which tenant it happened to, and naming the tenant
        here would be the cardinality trap this sink exists to avoid. The detector
        documents why the eviction is visible at all.
        """
        get_metrics().call("detection_evictions")


@dataclass
class BackstopState:
    config: BackstopConfig
    budget: Budget
    aimd: AIMDController
    gate: PriorityGate
    circuit: CircuitBreaker
    audit: AuditLog | None = None
    quota: QuotaMonitor | None = None
    #: Where one spend event goes, and the only thing the transport calls on the
    #: request path. Always a :class:`~backstop.ledger.sink.BoundedWriter`, so
    #: the call site's cost never depends on the sink: with the ledger off it
    #: wraps a :class:`~backstop.ledger.sink.NullSink` and is never called at
    #: all, because the transport gates on ``config.ledger_enabled`` first.
    ledger: BoundedWriter = field(default_factory=lambda: BoundedWriter(NullSink()))
    #: The runaway-spend detector. Constructed unconditionally and inert when
    #: ``config.detection_enabled`` is false, so "off" costs one boolean test
    #: inside ``observe`` rather than a branch at the call site.
    detector: RunawayDetector = field(default_factory=RunawayDetector)
    #: The price list events are billed against, or ``None`` when the ledger and
    #: the detector are both off and nothing will ever ask for a price.
    prices: PriceCatalog | None = None
    #: Spend events the transport could not turn into a record. A diagnostic, not
    #: a lock: incremented without synchronisation from the failure path only,
    #: so a concurrent pair of failures can collapse into one count. Non-zero
    #: means the ledger is losing events for a reason its own counters do not
    #: describe.
    ledger_errors: int = 0
    _circuits: dict = field(default_factory=dict)
    #: The ``atexit`` callback :meth:`close` unregisters, or ``None``. Private
    #: because it is machinery for :meth:`close` rather than state anyone reads;
    #: held so a close can drop the registration instead of leaving a hook that
    #: outlives the state it was made for.
    _atexit_hook: Callable[[], None] | None = None

    def circuit_for(self, tenant_id: str | None) -> CircuitBreaker:
        if not self.config.per_tenant_circuit or tenant_id is None:
            return self.circuit
        existing = self._circuits.get(tenant_id)
        if existing is not None:
            return existing
        breaker = CircuitBreaker(self.config)
        self._circuits[tenant_id] = breaker
        return breaker

    def close(self) -> CloseReport:
        """Close the ledger writer and report what will never be written.

        **The shutdown story for ``ledger_path``.** A durable ledger owns a file
        handle and a daemon drain thread, and a close is the only thing that
        releases either. Every event is flushed as it is written, so nothing is
        lost by *not* closing — but the handle and the thread are, and a user who
        turns the ledger on and then exits should not have to know that.

        The report is the point of the call:
        :attr:`~backstop.ledger.sink.CloseReport.lost` is the number of submitted
        events that will never reach storage, from all three loss buckets, and
        ``undrained`` says whether a stalled sink was abandoned. ``close`` joins
        the drain thread with a bounded timeout, so this cannot hang.

        Idempotent, because shutdown paths run more than once: an explicit close
        and then an ``atexit`` hook, or two ``finally`` blocks. The second call
        returns the first call's report rather than a second, smaller one. The
        ``atexit`` registration is dropped on the way out either way.

        Safe on a state with the ledger off: it closes a writer over a
        :class:`NullSink` and reports zeros, which is the truth rather than a
        placeholder.
        """
        hook, self._atexit_hook = self._atexit_hook, None
        if hook is not None:
            atexit.unregister(hook)
        return self.ledger.close()

    @classmethod
    def create(
        cls,
        budget: int | None,
        config: BackstopConfig | None = None,
        backend: BudgetBackend | None = None,
    ) -> "BackstopState":
        resolved = config or BackstopConfig()
        if resolved.otel_enabled:
            enable_otel(resolved.otel_meter_name)
        else:
            disable_otel()
        aimd = AIMDController(resolved)
        backend = backend or build_backend(
            budget,
            shared=resolved.shared_budget,
            redis_url=resolved.redis_url,
            redis_key=resolved.redis_key,
        )
        budget_obj = Budget(budget, backend=backend)
        audit = AuditLog(resolved.audit_sink, resolved.audit_hmac_key) if resolved.audit_enabled else None
        quota = QuotaMonitor() if resolved.quota_aware else None
        ledger, prices = _build_ledger(resolved)
        signal_sink = DetectionSignalSink()
        state = cls(
            config=resolved,
            budget=budget_obj,
            aimd=aimd,
            gate=PriorityGate(resolved, aimd),
            circuit=CircuitBreaker(resolved),
            audit=audit,
            quota=quota,
            ledger=ledger,
            detector=RunawayDetector(resolved.detection_config, signal_sink=signal_sink),
            prices=prices,
        )
        # Registering here (rather than in wrap()) keeps the built-in dashboard
        # aware of gateway, harness and demo sessions too. The reference it holds
        # is weak, so a garbage-collected client leaves the registry on its own.
        get_registry().register(state)
        if resolved.ledger_enabled:
            _register_exit_close(state)
        return state


def _register_exit_close(state: BackstopState) -> None:
    """Close a live state at interpreter exit, without pinning it.

    Registered only when the ledger is on, because that is the only case where
    there is a file handle and a drain thread to release. The callback holds a
    *weak* reference: registering ``state.close`` directly would keep every
    wrapped session alive for the life of the process, and the dashboard reports
    live sessions from exactly those references — a finished run would go on
    showing up as a running one.

    The closure is per-state rather than a shared function so that
    :meth:`BackstopState.close`'s ``atexit.unregister`` removes this state's hook
    and no other: ``unregister`` drops *every* registration of the callable it is
    given, so a shared hook would take the other sessions' with it.
    """
    reference = weakref.ref(state)

    def close_if_live() -> None:
        live = reference()
        if live is not None:
            live.close()

    state._atexit_hook = close_if_live
    atexit.register(close_if_live)


def _build_ledger(resolved: BackstopConfig) -> tuple[BoundedWriter, PriceCatalog | None]:
    """Return ``(writer, catalog)`` for this configuration.

    The disabled case builds a writer over a :class:`NullSink` and no catalog at
    all, so a process that has not turned the ledger on allocates one deque and
    one condition variable at construction and nothing per request. The price
    catalog is the expensive half — the bundled table is dozens of entries, each
    turned into a keyed tuple — so it is not built until something is going to
    ask for a price.

    With ``ledger_path`` set the writer's sink is a
    :class:`~backstop.ledger.sink.JsonlSink`, which opens its file on the first
    write rather than here, so constructing a state touches no filesystem. With
    no path the sink is a bounded in-memory ring of ``ledger_memory_events``.
    """
    if not (resolved.ledger_enabled or resolved.detection_enabled):
        return BoundedWriter(NullSink()), None
    sink = (
        JsonlSink(resolved.ledger_path)
        if resolved.ledger_path
        else MemorySink(resolved.ledger_memory_events)
    )
    prices = (
        PriceCatalog.from_file(resolved.price_catalog_path)
        if resolved.price_catalog_path
        else PriceCatalog()
    )
    return BoundedWriter(sink), prices
