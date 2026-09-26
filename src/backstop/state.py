from __future__ import annotations

from dataclasses import dataclass, field

from .admission import PriorityGate
from .aimd import AIMDController
from .audit import AuditLog
from .budget import Budget
from .circuit import CircuitBreaker
from .config import BackstopConfig
from .detection import RunawayDetector
from .ledger import BoundedWriter, JsonlSink, MemorySink, NullSink
from .metrics import disable_otel, enable_otel
from .pricing_catalog import PriceCatalog
from .quotas import QuotaMonitor
from .state_backends import BudgetBackend, build_backend
from .telemetry import get_registry


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

    def circuit_for(self, tenant_id: str | None) -> CircuitBreaker:
        if not self.config.per_tenant_circuit or tenant_id is None:
            return self.circuit
        existing = self._circuits.get(tenant_id)
        if existing is not None:
            return existing
        breaker = CircuitBreaker(self.config)
        self._circuits[tenant_id] = breaker
        return breaker

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
        state = cls(
            config=resolved,
            budget=budget_obj,
            aimd=aimd,
            gate=PriorityGate(resolved, aimd),
            circuit=CircuitBreaker(resolved),
            audit=audit,
            quota=quota,
            ledger=ledger,
            detector=RunawayDetector(resolved.detection_config),
            prices=prices,
        )
        # Registering here (rather than in wrap()) keeps the built-in dashboard
        # aware of gateway, harness and demo sessions too. The reference it holds
        # is weak, so a garbage-collected client leaves the registry on its own.
        get_registry().register(state)
        return state


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
