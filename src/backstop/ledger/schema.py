"""Immutable spend event schema for the Backstop ledger.

One :class:`SpendEvent` is produced per completed provider request. It is the
only shape the ledger stores, exports, and prices, so its wire form
(:meth:`SpendEvent.to_dict` / :meth:`SpendEvent.from_dict`) is a contract: the
JSONL sink in a later task writes it one object per line and reads it back.

Records are frozen. Nothing in the ledger mutates an event; a correction is a
new event. :class:`Attribution` is frozen for the same reason plus one more —
it is used as a dict key for per-attribution aggregation.

``SpendEvent.cost`` is owned by the price catalog task and is deliberately left
unpriced (``None``) until that task lands. It is forward-declared under
``TYPE_CHECKING`` so this module stays import-cycle free.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from uuid import uuid4

if TYPE_CHECKING:
    from ..pricing_catalog import CostBreakdown

__all__ = [
    "OUTCOMES",
    "PRIORITIES",
    "SCHEMA_VERSION",
    "Attribution",
    "SpendEvent",
]

SCHEMA_VERSION = "1.0"
PRIORITIES: tuple[str, ...] = ("critical", "default", "background")
OUTCOMES: tuple[str, ...] = (
    "success",
    "error",
    "circuit_open",
    "budget_denied",
    "queue_timeout",
    "fallback",
)

#: ``occurred_at`` wire form: RFC 3339 UTC with exactly six fractional digits.
OCCURRED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")

#: ``event_id`` wire form: ``uuid4().hex``, 32 lowercase hex characters.
EVENT_ID_RE = re.compile(r"^[0-9a-f]{32}$")

_COUNT_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "retries",
)


def utc_now() -> str:
    """Return the current UTC instant as ``2026-09-25T14:03:11.123456Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


#: Query parameter names that carry a credential. Their values are never stored.
#: Matched as a word inside the name, so a vendor prefix such as ``x-api-key``
#: counts, and ``monkey=1`` does not.
SECRET_QUERY_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:api[-_]?key|access[-_]?key|access[-_]?token|authorization"
    r"|password|passwd|secret|signature|token|auth|key|sig)(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)

#: Stands in for a dropped query string that carried a credential.
REDACTED_QUERY = "<redacted>"


def normalize_endpoint(raw: str) -> str:
    """Return the record-safe form of a request endpoint.

    The ledger is a durable, long-lived file, so a caller that hands over a URL
    with a query string, a fragment, or ``user:pass@`` in it must not have
    those written down: an API key in a query string would otherwise land in
    the JSONL line and in every ``repr`` of the event. The query string and the
    fragment are dropped entirely, the userinfo is dropped from the authority,
    and the fact that a credential was present is recorded as
    ``?<redacted>`` rather than the credential itself.
    """
    if "?" not in raw and "#" not in raw and "@" not in raw:
        return raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return _normalize_endpoint_textually(raw)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    query = REDACTED_QUERY if any(SECRET_QUERY_RE.search(name) for name, _ in pairs) else ""
    return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, query, ""))


def _normalize_endpoint_textually(raw: str) -> str:
    """Fallback for a URL ``urlsplit`` refuses, e.g. an unbracketed IPv6 host."""
    without_fragment = raw.split("#", 1)[0]
    authority_and_path = without_fragment.split("?", 1)[0]
    scheme, separator, rest = authority_and_path.partition("://")
    if not separator:
        return authority_and_path
    authority, slash, path = rest.partition("/")
    return f"{scheme}://{authority.rsplit('@', 1)[-1]}{slash}{path}"


@dataclass(frozen=True)
class Attribution:
    """The charge-back dimensions attached to a call site.

    Every field is optional and defaults to ``None``, so an un-attributed
    request is a valid, all-``None`` ``Attribution`` and no call site has to be
    rewritten. Being frozen makes it hashable, so it can key a dict of
    per-attribution totals.
    """

    team: str | None = None
    agent: str | None = None
    session: str | None = None
    task: str | None = None
    feature: str | None = None
    surface: str | None = None
    customer: str | None = None
    tenant: str | None = None
    environment: str | None = None
    repo: str | None = None
    cost_center: str | None = None
    gl_code: str | None = None
    currency: str | None = None

    def merge(self, override: "Attribution") -> "Attribution":
        """Return a new ``Attribution`` where ``override``'s set fields win.

        ``self`` is the base and is never mutated. An unset (``None``) field in
        ``override`` inherits the base value, so nesting scopes accumulate
        rather than replace.
        """
        merged: dict[str, str] = {}
        for spec in fields(self):
            incoming = getattr(override, spec.name)
            base = getattr(self, spec.name)
            if incoming is not None:
                merged[spec.name] = incoming
            elif base is not None:
                merged[spec.name] = base
        return Attribution(**merged)

    def keys(self) -> dict[str, str]:
        """Return only the fields that are set, as ``{name: value}``."""
        return {
            spec.name: value
            for spec in fields(self)
            if (value := getattr(self, spec.name)) is not None
        }

    def to_dict(self) -> dict[str, str | None]:
        """Return every field, set or not, in declaration order."""
        return {spec.name: getattr(self, spec.name) for spec in fields(self)}

    @classmethod
    def from_fields(cls, **values: str | None) -> "Attribution":
        """Build an ``Attribution`` from keyword fields.

        Type hints cannot describe keyword arguments, so the two ways a call
        site can get this wrong are rejected explicitly here: an unknown name
        and a non-string value both raise ``TypeError`` rather than being
        silently dropped from the ledger.
        """
        known = frozenset(cls.__dataclass_fields__)
        unknown = sorted(set(values) - known)
        if unknown:
            raise TypeError(
                f"unknown attribution field(s) {unknown}; valid fields are {sorted(known)}"
            )
        for name, value in values.items():
            if value is not None and not isinstance(value, str):
                raise TypeError(
                    f"attribution field {name!r} must be a string or None, "
                    f"got {type(value).__name__}"
                )
        return cls(**values)


def _cost_payload(cost: Any) -> Any:
    """Convert an attached cost to a plain mapping.

    ``CostBreakdown`` belongs to the price catalog task, so it is reached
    structurally: ``to_dict()`` is the contract, with a dataclass-field
    fallback for anything that only exposes fields. Money values are expected
    to have already been rendered for the wire — this module never quantises or
    converts them.
    """
    to_dict = getattr(cost, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if is_dataclass(cost) and not isinstance(cost, type):
        return {spec.name: getattr(cost, spec.name) for spec in fields(cost)}
    raise TypeError(
        f"cost of type {type(cost).__name__} is not serialisable; "
        "it must expose to_dict() or be a dataclass"
    )


@dataclass(frozen=True)
class SpendEvent:
    """One record of a single provider request, ready to be priced.

    Token counts are what the provider reported, or what Backstop estimated
    locally when the provider reported none — ``estimated`` distinguishes the
    two, because an estimated record is a floor, not a measurement. ``cost``
    stays ``None`` when no price is known: a missing price is visible in the
    ledger rather than filled with a guess.
    """

    provider: str
    model: str
    endpoint: str
    priority: str
    outcome: str
    input_tokens: int
    output_tokens: int
    estimated: bool
    attribution: Attribution
    event_id: str = field(default_factory=lambda: uuid4().hex)
    occurred_at: str = field(default_factory=utc_now)
    schema_version: str = SCHEMA_VERSION
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: float = 0.0
    retries: int = 0
    cost: "CostBreakdown | None" = None
    request_id: str | None = None

    def __post_init__(self) -> None:
        # The transport builds one of these per request, so every check below is
        # O(fields) and runs against a pattern compiled once at import.
        for name in _COUNT_FIELDS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    f"{name} must be an int, got {type(value).__name__} {value!r}"
                )
            if value < 0:
                raise ValueError(f"{name} must be >= 0, got {value}")
        latency = self.latency_ms
        if isinstance(latency, bool) or not isinstance(latency, (int, float)):
            raise TypeError(
                f"latency_ms must be a number, got {type(latency).__name__} {latency!r}"
            )
        if not isfinite(latency):
            raise TypeError(f"latency_ms must be a finite number, got {latency!r}")
        if latency < 0:
            raise ValueError(f"latency_ms must be >= 0.0, got {latency}")
        for name in ("provider", "model", "endpoint"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(
                    f"{name} must be a str, got {type(value).__name__} {value!r}"
                )
            if not value.strip():
                raise ValueError(f"{name} must be non-empty, got {value!r}")
        if not isinstance(self.estimated, bool):
            raise TypeError(
                f"estimated must be a bool, got {type(self.estimated).__name__} "
                f"{self.estimated!r}"
            )
        if not isinstance(self.attribution, Attribution):
            raise TypeError(
                "attribution must be an Attribution, got "
                f"{type(self.attribution).__name__} {self.attribution!r}"
            )
        if not isinstance(self.priority, str):
            raise TypeError(
                f"priority must be a str, got {type(self.priority).__name__} "
                f"{self.priority!r}"
            )
        if self.priority not in PRIORITIES:
            raise ValueError(
                f"priority must be one of {list(PRIORITIES)}, got {self.priority!r}"
            )
        if not isinstance(self.outcome, str):
            raise TypeError(
                f"outcome must be a str, got {type(self.outcome).__name__} {self.outcome!r}"
            )
        if self.outcome not in OUTCOMES:
            raise ValueError(
                f"outcome must be one of {list(OUTCOMES)}, got {self.outcome!r}"
            )
        if not isinstance(self.request_id, str) and self.request_id is not None:
            raise TypeError(
                "request_id must be a str or None, got "
                f"{type(self.request_id).__name__} {self.request_id!r}"
            )
        if not isinstance(self.event_id, str):
            raise TypeError(
                f"event_id must be a str, got {type(self.event_id).__name__} {self.event_id!r}"
            )
        if not EVENT_ID_RE.match(self.event_id):
            raise ValueError(
                f"event_id must be 32 lowercase hex characters, got {self.event_id!r}"
            )
        if not isinstance(self.occurred_at, str):
            raise TypeError(
                "occurred_at must be a str, got "
                f"{type(self.occurred_at).__name__} {self.occurred_at!r}"
            )
        if not OCCURRED_AT_RE.match(self.occurred_at):
            raise ValueError(
                f"occurred_at must be RFC 3339 UTC with microseconds, got "
                f"{self.occurred_at!r}"
            )
        if not isinstance(self.schema_version, str):
            raise TypeError(
                "schema_version must be a str, got "
                f"{type(self.schema_version).__name__} {self.schema_version!r}"
            )
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {SCHEMA_VERSION!r}, got {self.schema_version!r}"
            )
        # A frozen dataclass refuses assignment, so the normalised endpoint is
        # written exactly once, here; the record is immutable from this point on
        # and equals what the caller handed in only when it was already clean.
        object.__setattr__(self, "endpoint", normalize_endpoint(self.endpoint))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping in schema order.

        The key order is the record's column order, so a sink writes stable
        lines and a reader can diff them.
        """
        return {
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "schema_version": self.schema_version,
            "provider": self.provider,
            "model": self.model,
            "endpoint": self.endpoint,
            "priority": self.priority,
            "outcome": self.outcome,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "latency_ms": self.latency_ms,
            "retries": self.retries,
            "estimated": self.estimated,
            "attribution": self.attribution.to_dict(),
            "cost": None if self.cost is None else _cost_payload(self.cost),
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SpendEvent":
        """Rebuild an event from :meth:`to_dict` output, running validation again."""
        attribution_payload = payload.get("attribution") or {}
        cost_payload = payload.get("cost")
        cost: "CostBreakdown | None" = None
        if cost_payload is not None:
            from ..pricing_catalog import CostBreakdown

            cost = CostBreakdown.from_dict(cost_payload)
        return cls(
            event_id=payload["event_id"],
            occurred_at=payload["occurred_at"],
            schema_version=payload["schema_version"],
            provider=payload["provider"],
            model=payload["model"],
            endpoint=payload["endpoint"],
            priority=payload["priority"],
            outcome=payload["outcome"],
            input_tokens=payload["input_tokens"],
            output_tokens=payload["output_tokens"],
            cache_read_tokens=payload["cache_read_tokens"],
            cache_write_tokens=payload["cache_write_tokens"],
            latency_ms=payload["latency_ms"],
            retries=payload["retries"],
            estimated=payload["estimated"],
            attribution=Attribution.from_fields(**attribution_payload),
            cost=cost,
            request_id=payload["request_id"],
        )
