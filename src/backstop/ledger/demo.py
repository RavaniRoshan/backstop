"""``backstop ledger demo`` — a priced charge-back, from nothing, offline.

This is the pitch artifact, so its first job is not to look impressive. It is to
be **true**. Every dollar it prints was computed by
:func:`backstop.pricing_catalog.compute_cost` from the bundled rate card and the
token counts below, and the demo says so on its face: the events are synthetic,
the timestamps are fixed, the run is deterministic to the dollar, and the command
made no network call and read no key.

What is *simulated* and what is *computed*, precisely:

===========================  ==================================================
simulated                    computed
===========================  ==================================================
one day of a deployment's    every price, from the bundled rate card
provider traffic: request    every cost, as ``Decimal`` at six decimal places
counts, token counts,        every total, request by request, then row by row
attribution, model mix       the attribution split, the unattributed share
===========================  ==================================================

The one thing that is simulated *and* load-bearing is the absence of a price for
one model. ``vendor-preview-2027`` is not in the rate card, so its requests are
recorded as unpriced and their dollars are missing rather than guessed. That row
is the point: a charge-back tool that quietly filled the hole would be showing a
number nobody could defend, and this one shows the hole.

The events go through the shipped
:class:`~backstop.ledger.sink.BoundedWriter` and
:class:`~backstop.ledger.sink.MemorySink` rather than straight into the
aggregator, so the demo exercises the real plumbing and can report a real
delivery count — including both loss counters, which a file read cannot report.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from ..pricing_catalog import (
    BUNDLED_EFFECTIVE_FROM,
    CostBreakdown,
    PriceCatalog,
    compute_cost,
)
from .export import (
    DEFAULT_GROUP_BY,
    MIXED_PRICE_SOURCE,
    UNATTRIBUTED,
    ChargebackRow,
    ChargebackTotals,
    Period,
    RevenueRow,
    build_chargeback,
    chargeback_totals,
    delivery_report,
    format_delivery,
    render_chargeback_markdown,
    render_revenue_csv,
    revenue_join,
)
from .schema import Attribution, SpendEvent
from .sink import DEFAULT_MEMORY_EVENTS, BoundedWriter, MemorySink

__all__ = [
    "DEMO_DAY",
    "DEMO_PERIOD",
    "LedgerDemoResult",
    "demo_events",
    "demo_revenue",
    "run_demo",
]

#: The UTC day the synthetic traffic happened on. Fixed, not today's date: a demo
#: whose numbers move with the calendar cannot be checked against a note taken
#: last week, and cannot be asserted byte for byte in a test. It is also the day
#: the bundled rate card took effect, so the card demonstrably prices the traffic
#: it is effective for.
DEMO_DAY = "2026-09-26"

#: Midnight UTC on the demo day, the base every synthetic timestamp is offset from.
_BASE = datetime(2026, 9, 26, 0, 0, 0)

#: The window the demo reports on.
DEMO_PERIOD = Period.day(DEMO_DAY)

#: Spacing constant for the synthetic usage spread. Any fixed integer would do; a
#: prime keeps consecutive requests from landing in a visible arithmetic pattern,
#: and it is a constant, so two runs are identical.
_SPREAD = 7919

#: Spacing constant for the synthetic clock. Coprime with the number of seconds
#: in a day, so consecutive requests land minutes apart in the source order and
#: hours apart in the file: every workload's window overlaps every other one's,
#: the way a real deployment's does, instead of each team owning a contiguous
#: block of the day.
_TIME_SPREAD = 40009

_ENDPOINTS = {"openai": "/v1/chat/completions", "anthropic": "/v1/messages"}
_PRIORITIES = ("critical", "default", "background")


@dataclass(frozen=True)
class _Profile:
    """One workload: who spends it, on what, how much, how often.

    The token bounds are inclusive and a request's figure is
    ``low + (index * _SPREAD) % (high - low + 1)`` — a fixed function of the
    request's own index, so the traffic has a shape without being sampled,
    shuffled, or seeded from a clock.
    """

    team: str | None
    feature: str | None
    provider: str
    model: str
    requests: int
    input_tokens: tuple[int, int]
    output_tokens: tuple[int, int]
    cache_read_tokens: tuple[int, int] = (0, 0)
    cache_write_tokens: tuple[int, int] = (0, 0)
    #: Every ``cache_read_every``-th request carries cached tokens; 0 means none.
    cache_read_every: int = 0
    #: Every ``cache_write_every``-th request writes to the cache; 0 means none.
    cache_write_every: int = 0
    #: Every ``estimated_every``-th request had no provider usage report, so
    #: Backstop estimated its tokens. Those dollars are a floor, not a measurement.
    estimated_every: int = 0


#: One day, one deployment, seven workloads. Read this table and you know exactly
#: what the demo shows before it prints anything: how much traffic, which models,
#: which dimensions carry an attribution, and which row is deliberately unpriced.
_PROFILES: tuple[_Profile, ...] = (
    _Profile(
        team="payments",
        feature="checkout-v2",
        provider="openai",
        model="gpt-4o",
        requests=388,
        input_tokens=(6_000, 38_000),
        output_tokens=(120, 1_400),
        cache_read_tokens=(2_000, 24_000),
        cache_read_every=3,
        # gpt-4o publishes no cache-write rate, so these requests are charged zero
        # for their cache write and the export marks the component as a gap.
        cache_write_tokens=(1_000, 8_000),
        cache_write_every=7,
    ),
    _Profile(
        team="payments",
        feature="refunds",
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        requests=96,
        input_tokens=(2_000, 9_000),
        output_tokens=(300, 1_800),
        cache_read_tokens=(0, 3_000),
        cache_read_every=2,
        cache_write_tokens=(0, 2_500),
        cache_write_every=2,
    ),
    _Profile(
        team="support",
        feature="triage",
        provider="openai",
        model="gpt-4.1",
        requests=240,
        input_tokens=(800, 3_500),
        output_tokens=(90, 600),
        cache_read_tokens=(0, 1_200),
        cache_read_every=4,
    ),
    _Profile(
        team="search",
        feature="query-rewrite",
        provider="anthropic",
        model="claude-haiku-4-5",
        requests=1_140,
        input_tokens=(200, 1_100),
        output_tokens=(30, 260),
        cache_read_tokens=(0, 400),
        cache_read_every=2,
        cache_write_tokens=(0, 300),
        cache_write_every=3,
    ),
    _Profile(
        team="search",
        feature="vendor-preview",
        provider="openai",
        # Not in the bundled rate card, on purpose: this is the unpriced row.
        model="vendor-preview-2027",
        requests=34,
        input_tokens=(900, 4_000),
        output_tokens=(100, 500),
    ),
    _Profile(
        team=None,
        feature=None,
        provider="openai",
        model="gpt-4o",
        requests=42,
        input_tokens=(3_000, 12_000),
        output_tokens=(200, 700),
        # No attribution at all: the dollars below belong to nobody.
        estimated_every=5,
    ),
    _Profile(
        team=None,
        feature=None,
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        requests=27,
        input_tokens=(1_500, 5_000),
        output_tokens=(400, 1_200),
    ),
)

#: A finance team's own revenue for the same day, keyed on the same group tuple the
#: charge-back is grouped on. Deliberately incomplete in both directions: one
#: group has revenue and no cost in this window, one has cost and no revenue here.
#: Both appear with a visible ``(none)`` rather than a silent zero.
DEMO_REVENUE: dict[tuple[str, ...], str] = {
    ("payments", "checkout-v2"): "148230.00",
    ("payments", "refunds"): "41200.00",
    ("support", "triage"): "96450.00",
    ("search", "query-rewrite"): "78500.00",
    ("research", "long-context"): "12000.00",
}


def demo_revenue() -> dict[tuple[str, ...], str]:
    """Return the fixed revenue map: decimal strings, keyed on the group tuple.

    Strings because revenue is money and money is a string on this side of the
    join too. :func:`backstop.ledger.export.revenue_join` accepts a ``Decimal``,
    an ``int`` or a decimal string, and refuses a float.
    """
    return dict(DEMO_REVENUE)


def _spread(index: int, bounds: tuple[int, int]) -> int:
    """One token count for request ``index``, from its bounds and nothing else."""
    low, high = bounds
    if high <= low:
        return low
    return low + (index * _SPREAD) % (high - low + 1)


def _event_id(index: int) -> str:
    """A fixed, obviously-derived event id: a hash of the request's index.

    :class:`~backstop.ledger.schema.SpendEvent` requires 32 lowercase hex
    characters, and a real ``uuid4`` would make the demo non-deterministic.
    Deriving the id from the index keeps the same request on the same id across
    runs *and* makes the synthetic nature visible: the id is the hash of a number.
    ``blake2b`` at a 16-byte digest is used rather than a truncated ``sha256``
    because the size is part of the request rather than an accident of slicing.
    """
    return hashlib.blake2b(
        f"backstop-ledger-demo/{index}".encode("utf-8"), digest_size=16
    ).hexdigest()


def demo_events() -> tuple[SpendEvent, ...]:
    """Build the fixed synthetic event set, priced against the bundled catalog.

    Deterministic to the event: same events, same ids, same timestamps, same
    costs, on every machine and every run. No clock is read, no file is opened,
    no key is needed, and the only price source is
    :data:`backstop.pricing_catalog.BUNDLED_PRICES`.

    Each event goes through :func:`backstop.pricing_catalog.compute_cost` one at a
    time, so an event whose model is absent from the rate card comes back with
    ``cost=None`` — the outcome the export has to make visible rather than fill.
    """
    catalog = PriceCatalog()
    events: list[SpendEvent] = []
    index = 0
    for profile in _PROFILES:
        for request in range(profile.requests):
            cached = (
                _spread(request, profile.cache_read_tokens)
                if profile.cache_read_every and request % profile.cache_read_every == 0
                else 0
            )
            written = (
                _spread(request, profile.cache_write_tokens)
                if profile.cache_write_every and request % profile.cache_write_every == 0
                else 0
            )
            estimated = bool(profile.estimated_every and request % profile.estimated_every == 0)
            moment = _BASE + timedelta(
                seconds=(index * _TIME_SPREAD) % 86_400,
                microseconds=(index * 7) % 1_000_000,
            )
            event = SpendEvent(
                event_id=_event_id(index),
                occurred_at=moment.isoformat(timespec="microseconds") + "Z",
                provider=profile.provider,
                model=profile.model,
                endpoint=_ENDPOINTS[profile.provider],
                priority=_PRIORITIES[index % len(_PRIORITIES)],
                outcome="success",
                input_tokens=_spread(request, profile.input_tokens),
                output_tokens=_spread(request, profile.output_tokens),
                cache_read_tokens=cached,
                cache_write_tokens=written,
                latency_ms=float(120 + (index * 13) % 2_400),
                retries=1 if index % 17 == 0 else 0,
                estimated=estimated,
                attribution=Attribution(
                    team=profile.team, feature=profile.feature, environment="prod"
                ),
            )
            cost: CostBreakdown | None = compute_cost(event, catalog)
            events.append(event if cost is None else replace(event, cost=cost))
            index += 1
    return tuple(events)


@dataclass(frozen=True)
class LedgerDemoResult:
    """What the demo computed, in the shape both renderers read.

    A plain data record holding the real row objects rather than a flattened
    copy, so the markdown renderer and the JSON renderer are two views of one
    computation and cannot disagree about a number. ``simulated``,
    ``network_calls`` and ``price_source`` are fields rather than prose printed
    around the table, so a reader of the JSON alone still knows what is real.
    """

    demo_day: str
    period_label: str
    group_by: tuple[str, ...]
    events: int
    priced_events: int
    unpriced_events: int
    catalog_effective_from: str
    price_source: str
    models: tuple[str, ...]
    rows: tuple[ChargebackRow, ...]
    totals: ChargebackTotals
    joined: tuple[RevenueRow, ...]
    revenue_csv: str
    delivery: dict[str, Any]
    simulated: bool
    network_calls: int
    deterministic: bool

    def to_dict(self) -> dict[str, Any]:
        """The JSON form. Money is a string everywhere it appears."""
        return {
            "demo_day": self.demo_day,
            "period_label": self.period_label,
            "group_by": list(self.group_by),
            "events": self.events,
            "priced_events": self.priced_events,
            "unpriced_events": self.unpriced_events,
            "catalog_effective_from": self.catalog_effective_from,
            "price_source": self.price_source,
            "models": list(self.models),
            "rows": [row.to_dict() for row in self.rows],
            "totals": self.totals.to_dict(),
            "revenue_rows": [row.to_dict() for row in self.joined],
            "revenue_csv": self.revenue_csv,
            "delivery": self.delivery,
            "simulated": self.simulated,
            "network_calls": self.network_calls,
            "deterministic": self.deterministic,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_markdown(self) -> str:
        """The whole pitch on one screen, with the caveats printed on it.

        The order is the argument: what it is, what was faked, what was computed,
        the table with its totals line, then the numbers a CFO asks for before
        any fine print, then what this does not show.
        """
        totals = self.totals
        window = (
            f"{totals.first_seen} → {totals.last_seen}"
            if totals.first_seen
            else "empty window"
        )
        table = render_chargeback_markdown(self.rows, totals)
        return "\n".join(
            [
                "# Backstop Ledger — Chargeback",
                "",
                f"- **{self.events} requests** on {self.demo_day} "
                f"({self.period_label}), priced from the bundled rate card effective "
                f"**{self.catalog_effective_from}** (`price_source={self.price_source}`).",
                f"- **Window:** {window}",
                f"- **Grouped by:** {', '.join(self.group_by)}",
                f"- **Models:** {', '.join(self.models)}",
                "- **Mode:** 100% offline. No API key, no network call, no live "
                "provider data, no file. The traffic is synthetic and fixed; every "
                "price and every dollar is computed from the bundled rate card with "
                "`Decimal` arithmetic.",
                "",
                table,
                "",
                "## What a CFO reads first",
                "",
                _teardown(self),
                "",
                "\n".join(self.delivery["lines"]),
                "",
                f"This run lost **{self.delivery['lost']}** of "
                f"{self.delivery['submitted']} events, counted from the live writer. "
                "Both counters matter and neither is written to a ledger file: a "
                "file read reports them as unknown rather than as zero.",
                "",
                "## Joined against your revenue",
                "",
                "Backstop does not become a revenue system. You key your own revenue "
                "on the same group tuple and the join shows the margin — with a "
                "visible `(none)` for any group missing on either side, never a "
                "silent zero. Here two groups are missing on purpose: "
                "`research/long-context` has revenue and no spend in this window, and "
                "`search/vendor-preview` has spend and no revenue here.",
                "",
            ]
            + (
                ["```csv", self.revenue_csv.rstrip("\r\n"), "```"]
                if self.revenue_csv
                else [
                    "_The demo's revenue map is keyed on `team,feature`, so there is "
                    "no join for this grouping. Regrouping your revenue is your call, "
                    "not ours: `revenue_join` takes a map keyed on whatever you "
                    "grouped by._"
                ]
            )
            + [
                "",
                "## Get this out of your own ledger",
                "",
                "```bash",
                "backstop ledger demo                        # this table, offline",
                "backstop ledger show   --path ledger.jsonl   # integrity + chargeback",
                "backstop ledger export --path ledger.jsonl --out chargeback.csv \\",
                "                       --group-by team,feature",
                "```",
                "",
                "### What is not shown here",
                "",
                "- The requests are synthetic, so the *volume* is a scenario. The "
                "*dollars* are exact for that volume under the bundled rate card.",
                f"- The rate card is a snapshot dated {self.catalog_effective_from}. A "
                "negotiated price belongs in a catalog file or a per-call override, "
                "and outranks it.",
                "- One day of one shape is not a trend. Read `unpriced_requests` and "
                "`unpriced_components` before you read the total, and group by "
                "`customer` or `cost_center` if those are how you bill.",
            ]
        )


def _teardown(result: LedgerDemoResult) -> str:
    """The three numbers a CFO asks for, phrased as what they are.

    The unattributed share is stated as a share of *priced* spend, the unpriced
    count is stated as a hole of unknown size rather than as zero, and the
    unpriced component list is stated as a floor rather than as a measurement.
    """
    totals = result.totals
    gap = (
        (
            f"{len(totals.unpriced_components)} token component"
            f"{'' if len(totals.unpriced_components) == 1 else 's'} "
            f"{'carries' if len(totals.unpriced_components) == 1 else 'carry'} no "
            f"published rate in this window "
            f"(`{'`, `'.join(totals.unpriced_components)}`), so the requests that "
            "used it are charged zero for it and every affected row names the gap. "
            "Those lines are a floor, not a measurement."
        )
        if totals.unpriced_components
        else (
            "Every token component in this window has a published rate, so the "
            "totals are measurements rather than floors."
        )
    )
    estimated = (
        f"{totals.estimated_requests} of {totals.request_count} requests carry tokens "
        "Backstop estimated locally because the provider reported no usage, so "
        "their cost is a floor too."
        if totals.estimated_requests
        else "No request in this window rests on an estimated token count."
    )
    return "\n".join(
        (
            f"- **{totals.unattributed_usd} of {totals.total_usd} "
            f"({totals.unattributed_share_pct}%) of priced spend is "
            f"unattributed** — {totals.unattributed_requests} of "
            f"{totals.request_count} requests declared no `team` and no `feature`, so "
            "nobody can be charged for that money. It is one row in the table, "
            f"labelled `{UNATTRIBUTED}`, and it is the row a pivot table drops.",
            f"- **{totals.unpriced_requests} requests "
            f"({totals.unpriced_share_pct}%) have no price at all** — "
            "`vendor-preview-2027` is not in the rate card. Their cost is *absent, "
            "not zero*, so every total above understates real spend by an unknown "
            "amount. A guess would make the number wrong in a way nobody could "
            "detect; this one is wrong in a way everybody can.",
            f"- {gap} {estimated}",
        )
    )


def run_demo(
    group_by: Sequence[str] = DEFAULT_GROUP_BY,
    period: Period | None = DEMO_PERIOD,
) -> LedgerDemoResult:
    """Run the whole thing and return the record both renderers read.

    The events are submitted to a real :class:`~backstop.ledger.sink.BoundedWriter`
    over a real :class:`~backstop.ledger.sink.MemorySink` and the writer is closed
    before anything is aggregated, so the table is built from what the shipped
    plumbing actually held and the delivery counters are read off a live writer. A
    run that lost an event says so in the output rather than quietly printing a
    smaller total.
    """
    names = tuple(group_by)
    events = demo_events()
    writer = BoundedWriter(MemorySink(DEFAULT_MEMORY_EVENTS))
    for event in events:
        writer.submit(event)
    writer.close()
    report = delivery_report(writer)
    retained = writer.sink.events
    rows = build_chargeback(retained, names, period)
    # The revenue map is keyed on the default grouping, because that is the
    # grouping its figures were written for. Joining it onto a different grouping
    # would mean aggregating somebody's revenue for them, which is the one job
    # this module does not do, so the join is simply absent and says so.
    joinable = len(names) == len(next(iter(DEMO_REVENUE))) and names == DEFAULT_GROUP_BY
    joined = revenue_join(rows, demo_revenue()) if joinable else ()
    sources = sorted({event.cost.price_source for event in retained if event.cost})
    priced = sum(1 for event in retained if event.cost is not None)
    return LedgerDemoResult(
        demo_day=DEMO_DAY,
        period_label=(period or Period.all()).label,
        group_by=names,
        events=len(retained),
        priced_events=priced,
        unpriced_events=len(retained) - priced,
        catalog_effective_from=BUNDLED_EFFECTIVE_FROM,
        price_source=sources[0] if len(sources) == 1 else MIXED_PRICE_SOURCE,
        models=tuple(sorted({event.model for event in retained})),
        rows=rows,
        totals=chargeback_totals(rows, names),
        joined=joined,
        revenue_csv=render_revenue_csv(joined, names) if joinable else "",
        delivery={
            "submitted": report.submitted,
            "written": report.written,
            "dropped_events": report.dropped_events,
            "writer_sink_errors": report.writer_sink_errors,
            "sink_sink_errors": report.sink_sink_errors,
            "sink_degraded": report.sink_degraded,
            "lost": report.lost,
            "lines": format_delivery(report),
        },
        simulated=True,
        network_calls=0,
        deterministic=True,
    )
