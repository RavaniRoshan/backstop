"""Immutable spend event schema for the Backstop ledger.

One :class:`SpendEvent` is produced per completed provider request. It is the
only shape the ledger stores, exports, and prices, so its wire form
(:meth:`SpendEvent.to_dict` / :meth:`SpendEvent.from_dict`) is a contract: the
JSONL sink in a later task writes it one object per line and reads it back.

Records are frozen. Nothing in the ledger mutates an event; a correction is a
new event, which is why the endpoint is normalised once during construction and
never again. :class:`Attribution` is frozen for the same reason plus one more —
it is used as a dict key for per-attribution aggregation.

``SpendEvent.cost`` is owned by :mod:`backstop.pricing_catalog`. The class is
forward-declared under ``TYPE_CHECKING`` so this module stays import-cycle
free, and :func:`resolve_cost_type` is the one named place that reaches for it
at runtime.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

if TYPE_CHECKING:
    from ..pricing_catalog import CostBreakdown

__all__ = [
    "EVENT_ID_RE",
    "OCCURRED_AT_RE",
    "OUTCOMES",
    "PRIORITIES",
    "SCHEMA_VERSION",
    "SECRET_QUERY_RE",
    "UNKNOWN_ENDPOINT",
    "Attribution",
    "SpendEvent",
    "cost_from_dict",
    "cost_to_dict",
    "new_event_id",
    "normalize_endpoint",
    "resolve_cost_type",
    "utc_now",
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


def _is_set(value: str | None) -> bool:
    """A field is set when it carries a non-blank string; ``""`` and spaces are not.

    ``isspace`` rather than ``strip`` on purpose: a merge asks this of every
    field of both records on every scope entry, and ``strip`` allocates.
    """
    return value is not None and value != "" and not value.isspace()


def utc_now() -> str:
    """Return the current UTC instant as ``2026-09-25T14:03:11.123456Z``.

    ``isoformat`` is used rather than ``strftime`` because it is both faster and
    stricter: it always pads the year to four digits and always emits exactly six
    fractional digits, whatever the locale.
    """
    return (
        datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="microseconds")
        + "Z"
    )


#: The four RFC 4122 variant nibbles: the top two variant bits are always 10.
_VARIANT_NIBBLES = "89ab"


def new_event_id() -> str:
    """Return a fresh version 4 event id as 32 lowercase hex characters.

    ``uuid4().hex`` spends most of its time building the ``UUID`` object, and the
    ledger only ever wants the hex form. RFC 4122 section 4.4 defines a version 4
    id as 128 random bits with the version nibble set to ``4`` and the variant
    bits set to ``10``, which is what this writes straight into random bytes —
    the same distribution, in a third less time.
    """
    digits = os.urandom(16).hex()
    variant = _VARIANT_NIBBLES[int(digits[16], 16) & 0b11]
    return f"{digits[:12]}4{digits[13:16]}{variant}{digits[17:]}"


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

#: Stands in for an endpoint that normalises away to nothing, e.g. ``"?"``.
UNKNOWN_ENDPOINT = "unknown"


def _query_marker(query: str) -> str:
    """Return the query to keep: the redaction marker if one is warranted, else ``""``.

    A query that is already the marker keeps it. That is what makes
    :func:`normalize_endpoint` idempotent, which the wire round trip depends on:
    re-normalising a stored endpoint must not quietly drop the record that a
    credential was present, because a ledger line is read and written again.
    """
    if query == REDACTED_QUERY:
        return REDACTED_QUERY
    pairs = parse_qsl(query, keep_blank_values=True)
    if any(SECRET_QUERY_RE.search(name) for name, _ in pairs):
        return REDACTED_QUERY
    return ""


def normalize_endpoint(raw: str) -> str:
    """Return the record-safe form of a request endpoint.

    The ledger is a durable, long-lived file, so a caller that hands over a URL
    with a query string, a fragment, or ``user:pass@`` in it must not have those
    written down: an API key in a query string would otherwise land in the
    JSONL line and in every ``repr`` of the event. The query string and the
    fragment are dropped, the userinfo is dropped from the authority, and a
    credential-shaped query parameter is recorded as ``?<redacted>`` rather than
    the credential itself.

    The result is idempotent — normalising a stored endpoint returns it
    unchanged, redaction marker included — and never blank: an input that
    normalises away to nothing, such as ``"?"`` or ``"#frag"``, becomes
    :data:`UNKNOWN_ENDPOINT` rather than an empty field the validator would have
    rejected.
    """
    if "?" not in raw and "#" not in raw and "@" not in raw:
        normalised = raw
    else:
        try:
            parts = urlsplit(raw)
        except ValueError:
            normalised = _normalize_endpoint_textually(raw)
        else:
            normalised = urlunsplit((
                parts.scheme,
                parts.netloc.rsplit("@", 1)[-1],
                parts.path,
                _query_marker(parts.query),
                "",
            ))
    return normalised if normalised.strip() else UNKNOWN_ENDPOINT


def _normalize_endpoint_textually(raw: str) -> str:
    """Fallback for a URL ``urlsplit`` refuses, e.g. an unbracketed IPv6 host."""
    without_fragment, _, _fragment = raw.partition("#")
    without_query, _, query = without_fragment.partition("?")
    scheme, separator, authority_and_path = without_query.partition("://")
    if not separator:
        authority_and_path = without_query
    authority, slash, path = authority_and_path.partition("/")
    head = f"{scheme}://" if separator else ""
    marker = _query_marker(query)
    kept = f"?{marker}" if marker else ""
    return f"{head}{authority.rsplit('@', 1)[-1]}{slash}{path}{kept}"


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

    def __post_init__(self) -> None:
        for name in _ATTRIBUTION_FIELDS:
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise TypeError(
                    f"attribution field {name!r} must be a string or None, got "
                    f"{type(value).__name__} {value!r}"
                )

    def merge(self, override: "Attribution") -> "Attribution":
        """Return a new ``Attribution`` where ``override``'s set fields win.

        ``self`` is the base and is never mutated. A field is *set* when it is a
        non-blank string: ``None`` and an empty or all-whitespace string both
        mean unset, so an environment variable that arrived empty cannot erase
        the value an outer scope set. An unset field in ``override`` inherits
        the base value, so nesting scopes accumulate rather than replace.
        """
        merged: dict[str, str] = {}
        for name in _ATTRIBUTION_FIELDS:
            incoming = getattr(override, name)
            base = getattr(self, name)
            if _is_set(incoming):
                merged[name] = incoming
            elif _is_set(base):
                merged[name] = base
        return Attribution(**merged)

    def keys(self) -> dict[str, str]:
        """Return only the set fields, as ``{name: value}``.

        ``Attribution`` also answers ``keys()``, ``__iter__``, ``__contains__``
        and ``__getitem__``, so a record reads like the mapping this method
        implies: ``dict(record)``, ``"team" in record`` and ``fn(**record)`` all
        do the obvious thing over the set fields.
        """
        return {
            name: value
            for name in _ATTRIBUTION_FIELDS
            if _is_set(value := getattr(self, name))
        }

    def to_dict(self) -> dict[str, str | None]:
        """Return every field, set or not, in declaration order."""
        return {name: getattr(self, name) for name in _ATTRIBUTION_FIELDS}

    def __iter__(self) -> Iterator[str]:
        """Iterate the set field names, as a mapping would."""
        return iter(self.keys())

    def __contains__(self, name: object) -> bool:
        """Report whether a field is set, as ``"team" in record`` reads."""
        return name in self.keys()

    def __getitem__(self, name: str) -> str | None:
        """Return a set field's value, or ``None`` when it is not set.

        An unknown field name is a ``KeyError``; a known but unset one reads as
        ``None``, so ``in``, ``keys()`` and ``[]`` agree on what is set.
        """
        if name not in self.__dataclass_fields__:
            raise KeyError(name)
        value = getattr(self, name)
        return value if _is_set(value) else None

    @classmethod
    def from_fields(cls, **values: str | None) -> "Attribution":
        """Build an ``Attribution`` from keyword fields.

        Type hints cannot describe keyword arguments, so an unknown name is
        rejected here with the legal names, and the field types are checked by
        ``__post_init__``. A wrong field raises ``TypeError`` rather than being
        silently dropped from the ledger.
        """
        unknown = sorted(set(values) - set(cls.__dataclass_fields__))
        if unknown:
            raise TypeError(
                f"unknown attribution field(s) {unknown}; valid fields are "
                f"{sorted(cls.__dataclass_fields__)}"
            )
        return cls(**values)


def resolve_cost_type() -> type:
    """Return the concrete ``CostBreakdown``.

    This was a forward reference while the price catalog was pending: it
    returned ``None`` and the wire form of a cost was carried through as a plain
    mapping. The catalog has landed, so this now imports the real class and
    :func:`cost_from_dict` rebuilds it. The function survives as the one named
    place in this module that reaches for the price catalog, so the dependency
    stays a single line and the import stays out of module scope.
    """
    from ..pricing_catalog import CostBreakdown

    return CostBreakdown


def cost_to_dict(cost: Any) -> dict[str, Any]:
    """Serialise a cost, refusing anything that is not cost-shaped.

    Cost-shaped means a mapping, or a value whose ``to_dict()`` returns one.
    Money is expected to have already been rendered for the wire; this module
    never quantises or converts it. The previous behaviour accepted any object
    with a ``to_dict()`` on the way out while the way back in demanded the
    concrete class, so a record could be written that could not be read.
    """
    if isinstance(cost, dict):
        return dict(cost)
    to_dict = getattr(cost, "to_dict", None)
    if not callable(to_dict):
        raise TypeError(
            "cost must be a mapping, or expose to_dict() returning a mapping, got "
            f"{type(cost).__name__}"
        )
    payload = to_dict()
    if not isinstance(payload, dict):
        raise TypeError(
            f"cost.to_dict() must return a mapping, got {type(payload).__name__}"
        )
    return payload


def cost_from_dict(payload: Any) -> Any:
    """Rebuild a cost from its wire form, the exact inverse of :func:`cost_to_dict`.

    :func:`resolve_cost_type` names the class, so a stored line reloads as the
    real :class:`~backstop.pricing_catalog.CostBreakdown` rather than as a
    mapping — ``Decimal`` amounts in, ``Decimal`` amounts out, and the record
    compares equal to the one that was written.
    """
    if not isinstance(payload, dict):
        raise TypeError(f"cost must be a mapping, got {type(payload).__name__}")
    return resolve_cost_type().from_dict(payload)


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
    event_id: str = field(default_factory=new_event_id)
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
            "cost": None if self.cost is None else cost_to_dict(self.cost),
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SpendEvent":
        """Rebuild an event from :meth:`to_dict` output, running validation again.

        The payload must carry exactly the declared fields. An undeclared key is
        an error rather than a field to ignore, and a missing one is an error
        rather than a default: a typo in a persisted line, or a truncated one,
        would otherwise reload as plausible-looking data.
        """
        if not isinstance(payload, dict):
            raise TypeError(f"payload must be a mapping, got {type(payload).__name__}")
        declared = set(cls.__dataclass_fields__)
        present = set(payload)
        unknown = sorted(present - declared)
        if unknown:
            raise ValueError(
                f"unknown SpendEvent field(s) {unknown}; the schema declares "
                f"{sorted(declared)}"
            )
        missing = sorted(declared - present)
        if missing:
            raise ValueError(
                f"missing SpendEvent field(s) {missing}; every recorded line "
                f"carries all {len(declared)} fields"
            )
        attribution_payload = payload["attribution"] or {}
        if not isinstance(attribution_payload, dict):
            raise TypeError(
                "attribution must be a mapping, got "
                f"{type(attribution_payload).__name__}"
            )
        cost_payload = payload["cost"]
        cost: "CostBreakdown | None" = None
        if cost_payload is not None:
            cost = cost_from_dict(cost_payload)
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


#: The attribution field names, precomputed: ``dataclasses.fields`` rebuilds a
#: tuple on every call, and these run on every scope entry and every merge.
_ATTRIBUTION_FIELDS = tuple(Attribution.__dataclass_fields__)
