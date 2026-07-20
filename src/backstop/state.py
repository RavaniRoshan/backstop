from __future__ import annotations

from dataclasses import dataclass, field

from .admission import PriorityGate
from .aimd import AIMDController
from .audit import AuditLog
from .budget import Budget
from .circuit import CircuitBreaker
from .config import BackstopConfig
from .metrics import disable_otel, enable_otel
from .quotas import QuotaMonitor
from .state_backends import BudgetBackend, build_backend


@dataclass
class BackstopState:
    config: BackstopConfig
    budget: Budget
    aimd: AIMDController
    gate: PriorityGate
    circuit: CircuitBreaker
    audit: AuditLog | None = None
    quota: QuotaMonitor | None = None
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
        return cls(
            config=resolved,
            budget=budget_obj,
            aimd=aimd,
            gate=PriorityGate(resolved, aimd),
            circuit=CircuitBreaker(resolved),
            audit=audit,
            quota=quota,
        )
