from __future__ import annotations

import argparse
import datetime as _dt
import decimal
import json
import platform
import sys
import time

import httpx

from .config import BackstopConfig
from .dashboard_app import DEFAULT_HOST, DEFAULT_PORT, Dashboard
from .dashboard_app import serve as serve_dashboard
from .harness import DEFAULT_SEED, run_harness
from .metrics import start_metrics_server
from .real_anthropic import run_real_anthropic_smoke
from .real_openai import run_real_openai_smoke
from .state import BackstopState
from .telemetry import DEFAULT_SAMPLE_INTERVAL
from .transports import BackstopTransport
from .verify import run_verify

SCENARIOS = ["burst", "steady-state", "error-storm", "budget-hit"]


def _group_by_arg(value: str) -> tuple[str, ...]:
    """Parse a ``--group-by`` value into a validated tuple of dimensions.

    A ``type=`` hook on the argument, so an unknown dimension is argparse's usage
    error — a message and exit 2 — rather than a ``ValueError`` traceback out of
    the aggregator three frames later. The message lists the dimensions that do
    exist, because the useful part of a usage error is what to type.
    """
    from .ledger.export import DEFAULT_GROUP_BY
    from .ledger.schema import Attribution

    if not value.strip():
        raise argparse.ArgumentTypeError(
            "--group-by must name at least one dimension; try "
            f"{','.join(DEFAULT_GROUP_BY)}"
        )
    names = tuple(part.strip() for part in value.split(","))
    fields = tuple(Attribution.__dataclass_fields__)
    unknown = [name for name in names if name not in fields]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"--group-by does not know {unknown}; the ledger groups on {list(fields)}"
        )
    if len(set(names)) != len(names):
        raise argparse.ArgumentTypeError(
            f"--group-by names the same dimension twice: {list(names)}"
        )
    return names


def _format_benchmark(results: list) -> str:
    overhead = _measure_overhead()
    lines = [
        "# Backstop Benchmark Results",
        "",
        f"- Date: {_dt.date.today().isoformat()}",
        f"- Seed: `0x{DEFAULT_SEED:08X}` (deterministic)",
        "- Method: local `httpx.MockTransport`; no network; counts are exact and reproducible.",
        "",
        "## Overhead (local mock transport, measured)",
        "",
        "| Metric | Direct | Backstop | Overhead |",
        "| --- | ---: | ---: | ---: |",
        f"| p50 latency | {overhead['direct_p50']:.2f} ms | {overhead['backstop_p50']:.2f} ms | **{overhead['overhead_p50']:.2f} ms** |",
        f"| p95 latency | {overhead['direct_p95']:.2f} ms | {overhead['backstop_p95']:.2f} ms | **{overhead['overhead_p95']:.2f} ms** |",
        f"| p99 latency | {overhead['direct_p99']:.2f} ms | {overhead['backstop_p99']:.2f} ms | **{overhead['overhead_p99']:.2f} ms** |",
        "",
        "> Latency is measured separately from provider latency. See `benchmarks/local_overhead.py`.",
        "",
        "## Scenario results (deterministic, seeded)",
        "",
        "| Scenario | Requests | Provider Calls | Successes | Provider Errors | Budget-Blocked | Circuit-Blocked |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in results:
        lines.append(
            f"| {r.scenario} | {r.requests} | {r.provider_calls} | {r.successes} "
            f"| {r.provider_errors} | {r.blocked_budget} | {r.circuit_blocked} |"
        )
    lines.append("")
    lines.append("## How to reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("backstop benchmark --publish")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _measure_overhead(n: int = 500) -> dict:
    """Measure the control-path overhead of Backstop vs a bare httpx client.

    Returns a dict with direct/backstop p50/p95/p99 and overhead values (ms).
    Uses a no-op mock provider so the measurement reflects only Backstop's
    in-process work, not network latency.
    """
    import statistics
    import time

    def _series(client):
        lats = []
        for i in range(n):
            t0 = time.perf_counter()
            client.post(
                "/v1/chat/completions",
                json={"model": "mock", "messages": [{"role": "user", "content": f"b{i}"}], "max_tokens": 8},
            )
            lats.append((time.perf_counter() - t0) * 1000)
        return sorted(lats)

    def _pct(vals, p):
        idx = round((p / 100) * (len(vals) - 1))
        return vals[idx]

    direct_client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})),
        base_url="https://mock.local",
    )
    direct = _series(direct_client)
    direct_client.close()

    state = BackstopState.create(
        n * 100,
        BackstopConfig(initial_concurrency=64, max_concurrency=64, retry_max_attempts=1, circuit_min_requests=n + 1),
    )
    backstop_client = httpx.Client(
        transport=BackstopTransport(state, httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True, "usage": {"total_tokens": 1}}))),
        base_url="https://mock.local",
    )
    backstop = _series(backstop_client)
    backstop_client.close()

    return {
        "direct_p50": statistics.median(direct),
        "direct_p95": _pct(direct, 95),
        "direct_p99": _pct(direct, 99),
        "backstop_p50": statistics.median(backstop),
        "backstop_p95": _pct(backstop, 95),
        "backstop_p99": _pct(backstop, 99),
        "overhead_p50": statistics.median(backstop) - statistics.median(direct),
        "overhead_p95": _pct(backstop, 95) - _pct(direct, 95),
        "overhead_p99": _pct(backstop, 99) - _pct(direct, 99),
    }


def _run_benchmark(publish: bool) -> int:
    results = [run_harness(s) for s in SCENARIOS]
    markdown = _format_benchmark(results)
    print(markdown)
    if publish:
        from pathlib import Path

        out = Path("docs") / f"benchmark-results-{_dt.date.today().isoformat()}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        print(f"\nPublished benchmark results to {out}")
    return 0


def _version_string() -> str:
    """The version, from the one place it is written.

    ``backstop.__version__`` is the single source: ``pyproject.toml`` reads it
    at build time through hatchling's dynamic version, so a wheel cannot report
    a different number from the package it was built from.

    It is deliberately *not* read from ``importlib.metadata``: that reports the
    version the distribution was *installed* with, which in an editable
    checkout is however old the install was — a source tree at 0.8.0 reporting
    0.6.0 because of a stale ``.dist-info`` is exactly the drift this release
    is removing.
    """
    try:
        from . import __version__

        return str(__version__)
    except Exception:
        return "unknown"


def _run_doctor() -> int:
    print("# Backstop Doctor\n")
    print(f"- Python: {platform.python_version()} ({platform.system()})")

    # The version comes from one place, so `backstop --version` and
    # `backstop doctor` can never disagree.
    try:
        print(f"- Backstop: {_version_string()}")
    except Exception as exc:
        print(f"- Backstop: NOT IMPORTABLE ({exc})")
        return 1

    checks = [
        ("openai SDK", "openai"),
        ("anthropic SDK", "anthropic"),
        ("Prometheus metrics", "prometheus_client"),
        ("Redis shared budget", "redis"),
        ("OpenTelemetry export", "opentelemetry"),
        ("YAML (wedge)", "yaml"),
    ]
    print("\n## Optional dependencies")
    for label, mod in checks:
        try:
            __import__(mod)
            print(f"- [ok] {label}")
        except Exception:
            print(f"- [--] {label} (not installed; related features disabled)")

    print("\n## API keys")
    for env in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        print(f"- {env}: {'set' if __import__('os').getenv(env) else 'not set (live smoke tests will skip)'}")

    print("\n## Wrap smoke test (mock transport)")
    try:
        # Verify the _httpcompat module works
        from . import _httpcompat
        from .config import BackstopConfig
        from .wrapper import Backstop
        print("- [ok] _httpcompat module loaded successfully")

        # Test with httpx mock transport (this is what the actual tests use)
        import httpx
        BackstopState.create(100_000, BackstopConfig(default_max_output_tokens=1))
        mock_transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "mock", "object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": "test"}}]}))
        client = httpx.Client(transport=mock_transport, base_url="https://mock.local")
        print("- [ok] httpx MockTransport works (as used in tests)")

        # Verify compat_for function works
        compat = _httpcompat.compat_for(client)
        print(f"- [ok] compat_for detected httpx family: {compat.name}")

        # httpx2 is optional: it is not a declared dependency and only arrives
        # transitively with openai>=3 / anthropic>=1, so its absence means the
        # SDKs in use are on the httpx family that was just exercised above.
        # Report it and move on; do not fail the install.
        if _httpcompat.HTTPX2 is None:
            print("- [--] httpx2 not installed; the SDKs in use are on the httpx family")
        else:
            httpx2 = _httpcompat.HTTPX2
            httpx2_mock_transport = httpx2.MockTransport(lambda r: httpx2.Response(200, json={"id": "mock", "object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": "test"}}]}))
            httpx2_client = httpx2.Client(transport=httpx2_mock_transport, base_url="https://mock.local")
            print("- [ok] httpx2 MockTransport works (for Anthropic compatibility)")

            compat2 = _httpcompat.compat_for(httpx2_client)
            print(f"- [ok] compat_for detected httpx2 family: {compat2.name}")

    except Exception as exc:
        print(f"- [!!] wrap smoke test failed: {exc}")
        import traceback
        traceback.print_exc()
        return 1

    # Test actual SDK client wrapping (missing from original smoke test)
    print("\n## Actual SDK client wrapping test")
    provider_status = {}

    # OpenAI client wrapping
    try:
        import openai
        openai_client = openai.OpenAI(api_key="dummy-key")
        Backstop.wrap(openai_client, budget=10_000, config=BackstopConfig())
        print("- [ok] OpenAI client wrapped successfully")

        # Report SDK version
        try:
            print(f"- [ok] OpenAI SDK version: {openai.__version__}")
            provider_status['openai'] = {'version': openai.__version__, 'supported': True, 'wrapped': True}
        except Exception:
            print("- [--] OpenAI SDK version: not available")
            provider_status['openai'] = {'version': 'unknown', 'supported': True, 'wrapped': True}

    except Exception as e:
        print(f"- [!!] OpenAI client wrapping failed: {e}")
        provider_status['openai'] = {'version': 'unknown', 'supported': False, 'wrapped': False}
        # 1.3.3: doctor should exit non-zero when a wrap path fails
        print(f"\n- [!!] Wrap path failed for OpenAI: {e}")
        print("\nDoctor check failed: Some provider paths are not supported.")
        return 1

    # Anthropic client wrapping
    try:
        import anthropic
        anthropic_client = anthropic.Anthropic(api_key="dummy-key")
        Backstop.wrap(anthropic_client, budget=10_000, config=BackstopConfig())
        print("- [ok] Anthropic client wrapped successfully")

        # Report SDK version
        try:
            print(f"- [ok] Anthropic SDK version: {anthropic.__version__}")
            provider_status['anthropic'] = {'version': anthropic.__version__, 'supported': True, 'wrapped': True}
        except Exception:
            print("- [--] Anthropic SDK version: not available")
            provider_status['anthropic'] = {'version': 'unknown', 'supported': True, 'wrapped': True}

    except Exception as e:
        print(f"- [!!] Anthropic client wrapping failed: {e}")
        provider_status['anthropic'] = {'version': 'unknown', 'supported': False, 'wrapped': False}
        # 1.3.3: doctor should exit non-zero when a wrap path fails
        print(f"\n- [!!] Wrap path failed for Anthropic: {e}")
        print("\nDoctor check failed: Some provider paths are not supported.")
        return 1

    # Report provider support status (1.3.2)
    print("\n## Provider support status")
    for provider, status in provider_status.items():
        version = status['version']
        supported = "yes" if status['supported'] else "no"
        wrapped = "yes" if status['wrapped'] else "no"
        print(f"- {provider}: version={version}, supported={supported}, wrapped={wrapped}")

    print("\nDoctor complete: environment looks healthy.")
    return 0


#: The command groups, in the order ``backstop --help`` shows them. Each
#: heading is a question the operator is asking: *can I prove it works?*,
#: *what did it cost?*, *how do I run it?*, *does it reach the provider?*
#:
#: argparse has no native support for grouping subcommands, so the help
#: formatter below does it. The grouping is presentation only: every
#: command keeps the name it has always had, and the groups are not
#: namespaces.
COMMAND_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Prove it", ("verify", "demo", "doctor", "benchmark", "harness")),
    ("Money", ("ledger", "reconcile", "budget", "detect", "forecast", "audit")),
    ("Run it", ("serve", "metrics", "dashboard")),
    ("Live check", ("real-openai", "real-anthropic")),
)


class _GroupedHelpFormatter(argparse.HelpFormatter):
    """A help formatter that puts the subcommands under headings.

    The default puts every subcommand in one flat list, in the order they
    were added, which is neither alphabetical nor grouped by what the
    operator is trying to do. Twelve commands in one list is a list nobody
    scans.
    """

    def _format_action(self, action: argparse.Action) -> str:
        # A subparsers action renders its choices as sub-actions. The default
        # renders them as one flat list, in the order they were added; this
        # renders them under the headings above.
        get_subactions = getattr(action, "_get_subactions", None)
        if get_subactions is None:
            return super()._format_action(action)

        by_name: dict[str, str] = {}
        for subaction in get_subactions():
            name = str(getattr(subaction, "metavar", ""))
            by_name[name] = self._heading_for(name)

        parts: list[str] = []
        # The groups in the order they are declared, so the help reads in the
        # order an operator works in rather than the order the commands
        # happen to be registered.
        for heading, commands in COMMAND_GROUPS:
            group = [
                subaction
                for subaction in get_subactions()
                if str(getattr(subaction, "metavar", "")) in commands
            ]
            if not group:
                continue
            parts.append(f"{' ' * self._current_indent}{heading}:\n")
            self._indent()
            try:
                for subaction in group:
                    parts.append(self._format_action(subaction))
            finally:
                self._dedent()
        # Anything the groups do not name still has to be listed, or the help
        # would hide a command that works.
        others = [
            subaction
            for subaction in get_subactions()
            if by_name.get(str(getattr(subaction, "metavar", ""))) == "Other commands"
        ]
        if others:
            parts.append(f"{' ' * self._current_indent}Other commands:\n")
            self._indent()
            try:
                for subaction in others:
                    parts.append(self._format_action(subaction))
            finally:
                self._dedent()
        return self._join_parts(parts)

    @staticmethod
    def _heading_for(command: str) -> str:
        for heading, commands in COMMAND_GROUPS:
            if command in commands:
                return heading
        return "Other commands"


# ---------------------------------------------------------------------------
# budget, detect, forecast, audit
# ---------------------------------------------------------------------------


def _parse_timestamp(value: str) -> "_dt.datetime | None":
    """Parse an RFC 3339 timestamp, or ``None`` if it is not one.

    ``datetime.fromisoformat`` only learned to read the "Z" suffix in Python
    3.11, and this package supports 3.10 — so the suffix is normalised
    first. Every other RFC 3339 shape the ledger writes is already
    accepted.
    """
    if not isinstance(value, str):
        return None
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _exact_money(amount: decimal.Decimal) -> str:
    """Render an amount at the ledger's own precision.

    The ledger's :func:`~backstop.ledger.export.money` rounds to cents,
    which is right for a charge-back CSV and wrong for a budget report: a
    spend of $0.003 rendered as "$0.00" says nothing happened, and a ceiling
    of $0.0020 rendered the same way looks like the same number as a spend
    of $0.0030. These reports are about headroom, and headroom can be
    fractions of a cent.
    """
    if isinstance(amount, bool) or not isinstance(amount, decimal.Decimal):
        raise TypeError(f"amount must be a Decimal, got {type(amount).__name__}")
    return f"{amount:.6f}"


def _read_ledger_events(path: str) -> tuple[list, object] | None:
    """Read a ledger file, or report why it could not be read.

    Returns ``(events, read)``, or ``None`` after reporting the failure. A
    corrupt line is a failure and never a skipped line: a report over a
    ledger with a hole in the middle is not a report.
    """
    from .ledger import export as ledger_export

    try:
        read = ledger_export.read_ledger(path)
    except ledger_export.LedgerCorruptionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None
    except OSError as exc:
        print(f"error: cannot read ledger {path!r}: {exc}", file=sys.stderr)
        return None
    return list(read.events), read


def _run_budget(args: argparse.Namespace) -> int:
    """``backstop budget`` — where the spend stands against a ceiling.

    The question this answers is the one a token budget cannot: *how much of
    the money have we spent, and how much is left?* It reads the ledger the
    deployment already writes, so it works from a file rather than from a
    running process, and it needs no key and no network.
    """
    from .ledger import export as ledger_export

    loaded = _read_ledger_events(args.ledger)
    if loaded is None:
        return 1
    events, read = loaded
    try:
        rows = ledger_export.build_chargeback(
            events, tuple(args.group_by), ledger_export.Period.all()
        )
        totals = ledger_export.chargeback_totals(rows, tuple(args.group_by))
    except decimal.DecimalException as exc:
        return _decimal_failure(args, exc)

    ceiling = args.usd
    spent = totals.unrounded_total_usd
    if ceiling is not None:
        remaining = max(decimal.Decimal("0"), ceiling - spent)
        exceeded = spent > ceiling
    else:
        remaining = None
        exceeded = False

    if args.json:
        payload = json.loads(ledger_export.render_chargeback_json(list(rows), totals))
        payload["file"] = read.to_dict()
        payload["ceiling_usd"] = None if ceiling is None else str(ceiling)
        payload["remaining_usd"] = None if remaining is None else str(remaining)
        payload["exceeded"] = exceeded
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("# Backstop Budget\n")
    print(f"- Ledger: {args.ledger}")
    print(f"- Events: {len(events)}")
    print(f"- Spend: {_exact_money(spent)} {totals.currency}")
    if ceiling is not None:
        print(f"- Ceiling: {_exact_money(ceiling)} {totals.currency}")
        print(
            f"- Remaining: {_exact_money(remaining)} {totals.currency}"
            + ("  ** OVER CEILING **" if exceeded else "")
        )
    else:
        print("- Ceiling: (none given — pass --usd to see the headroom)")
    print(f"- Unpriced requests: {totals.unpriced_requests}")
    print()
    print("| Group | Requests | Total USD |")
    print("|---|---:|---:|")
    for row in list(rows)[: max(args.limit, 0) or None]:
        label = ", ".join(str(v) for v in row.keys) if row.keys else "(unattributed)"
        print(f"| {label} | {row.request_count} | {_exact_money(row.total_usd)} |")
    return 0


def _run_detect(args: argparse.Namespace) -> int:
    """``backstop detect`` — the runaway-spend signals, over a ledger file.

    The four detectors the transport runs live — velocity, drift, retry
    amplification and context growth — are run here over the same events, so
    a deployment can see what it *would* have been told before it is told.
    """
    from .detection import DetectionConfig, RunawayDetector

    loaded = _read_ledger_events(args.ledger)
    if loaded is None:
        return 1
    events, _read = loaded
    config = DetectionConfig(
        enabled=True,
        shadow=True,
        window_size=args.window,
        min_samples=args.min_samples,
    )
    detector = RunawayDetector(config)
    signals: list = []
    for event in events:
        signals.extend(detector.observe(event))

    if args.json:
        print(
            json.dumps(
                {
                    "events": len(events),
                    "signals": [
                        {
                            "kind": s.kind,
                            "severity": s.severity,
                            "observed": str(s.observed),
                            "threshold": str(s.threshold),
                            "detail": s.detail,
                        }
                        for s in signals
                    ],
                    "counts": detector.counts(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print("# Backstop Runaway-Spend Detection\n")
    print(f"- Ledger: {args.ledger}")
    print(f"- Events: {len(events)}")
    print(f"- Signals: {len(signals)}")
    print()
    if not signals:
        print("No signals. Either the spend is normal, or there is not enough of it yet.")
        return 0
    print("| Kind | Severity | Observed | Threshold | Detail |")
    print("|---|---|---:|---:|---|")
    for signal in signals:
        print(
            f"| {signal.kind} | {signal.severity} | {signal.observed} | "
            f"{signal.threshold} | {signal.detail} |"
        )
    return 0


def _run_forecast(args: argparse.Namespace) -> int:
    """``backstop forecast`` — when the budget runs out, at the measured rate.

    The burn rate is measured from the ledger's own timestamps: the first and
    last event, and what was spent between them. What it projects is
    exhaustion, not spend — a rate of spending says nothing about what the
    next month will cost.
    """
    from .ledger import export as ledger_export

    loaded = _read_ledger_events(args.ledger)
    if loaded is None:
        return 1
    events, _read = loaded
    if len(events) < 2:
        print(
            "Not enough events to measure a burn rate (need at least two).",
            file=sys.stderr,
        )
        return 1

    stamps = []
    for event in events:
        parsed = _parse_timestamp(event.occurred_at)
        if parsed is not None:
            stamps.append(parsed)
    if len(stamps) < 2:
        print("Not enough events with usable timestamps.", file=sys.stderr)
        return 1
    stamps.sort()
    window = max((stamps[-1] - stamps[0]).total_seconds(), 1e-9)

    try:
        rows = ledger_export.build_chargeback(
            events, tuple(args.group_by), ledger_export.Period.all()
        )
        totals = ledger_export.chargeback_totals(rows, tuple(args.group_by))
    except decimal.DecimalException as exc:
        return _decimal_failure(args, exc)

    spent = totals.unrounded_total_usd
    # The division is in Decimal, like every other amount; the rate is a
    # rate rather than an amount, and is a float for the projection.
    rate_per_min = float(
        (spent / decimal.Decimal(str(window))) * decimal.Decimal(60)
    )
    ceiling = args.usd
    if ceiling is None:
        seconds_remaining = None
        will_exhaust = None
    else:
        remaining = max(decimal.Decimal("0"), ceiling - spent)
        if rate_per_min > 0:
            seconds_remaining = float(
                remaining / decimal.Decimal(str(rate_per_min / 60.0))
            )
            will_exhaust = seconds_remaining <= args.horizon
        else:
            seconds_remaining = float("inf")
            will_exhaust = False

    if args.json:
        print(
            json.dumps(
                {
                    "events": len(events),
                    "window_seconds": window,
                    "spent_usd": str(spent),
                    "rate_usd_per_minute": str(rate_per_min),
                    "ceiling_usd": None if ceiling is None else str(ceiling),
                    "projected_remaining_seconds": seconds_remaining,
                    "will_exhaust_within_horizon": will_exhaust,
                    "horizon_seconds": args.horizon,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print("# Backstop Forecast\n")
    print(f"- Ledger: {args.ledger}")
    print(f"- Events: {len(events)} over {window:.3f}s")
    print(f"- Spend: {_exact_money(spent)} {totals.currency}")
    print(f"- Burn rate: {rate_per_min:.6f} {totals.currency}/min")
    if ceiling is None:
        print("- Ceiling: (none given — pass --usd to project exhaustion)")
    else:
        print(f"- Ceiling: {_exact_money(ceiling)} {totals.currency}")
        if seconds_remaining == float("inf"):
            print("- Projected exhaustion: never, at this rate")
        else:
            minutes = seconds_remaining / 60.0
            print(f"- Projected exhaustion: in {minutes:.1f} min")
            if will_exhaust:
                print(
                    f"  ** within the {args.horizon:.0f}s horizon — "
                    "tighten the budget or the concurrency limit **"
                )
    return 0


def _run_audit(args: argparse.Namespace) -> int:
    """``backstop audit`` — verify the tamper-evident audit chain.

    The chain is an HMAC over each record plus the previous record's chain
    value, so a modified record breaks it. Verifying is the whole point of
    writing it down, and it is a command because "is the audit log still
    intact" is a question somebody has to be able to answer.
    """
    from .audit import AuditLog

    path = args.path
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError as exc:
        print(f"error: cannot read audit log {path!r}: {exc}", file=sys.stderr)
        return 1

    key = args.hmac_key.encode("utf-8") if args.hmac_key else b""
    log = AuditLog.__new__(AuditLog)
    log._key = key
    log._prev = b""
    log._lock = __import__("threading").Lock()
    log._file = None
    log._callable = None
    intact = log.verify(lines)

    if args.json:
        print(
            json.dumps(
                {
                    "path": path,
                    "records": len([line for line in lines if line.strip()]),
                    "intact": intact,
                    "hmac_key_supplied": bool(args.hmac_key),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print("# Backstop Audit\n")
        print(f"- Log: {path}")
        print(f"- Records: {len([line for line in lines if line.strip()])}")
        print(f"- Chain intact: {'yes' if intact else 'NO'}")
        if not intact and not args.hmac_key:
            print(
                "  (no --hmac-key given, so the chain was checked without its key)"
            )
    return 0 if intact else 1


def build_parser() -> argparse.ArgumentParser:
    """Build the ``backstop`` argument parser.

    Split out from :func:`main` so the command surface is a value a test can
    inspect: ``llms.txt`` lists the commands an agent may run, and the only
    way to keep that list honest is to compare it against the parser rather
    than against a hand-maintained copy of it.
    """
    # Imported here rather than at module scope: every other subcommand in this
    # dispatcher works without the ledger, and an operator running `backstop
    # doctor` should not pay for importing the export module. The ledger commands
    # need three names and the validation the parser shares, so they are pulled in
    # once, here, where they are used.
    from .ledger.export import DEFAULT_GROUP_BY as DEFAULT_LEDGER_GROUP_BY

    parser = argparse.ArgumentParser(
        prog="backstop",
        description="In-process token budget, circuit breaking and concurrency control.",
        epilog=(
            "Start here: `backstop verify` proves the install in thirty seconds, "
            "with no key and no network. `backstop --help` groups the commands "
            "by what you are trying to do."
        ),
        formatter_class=_GroupedHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=_version_string(),
        help="print the installed version and exit",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    harness = subparsers.add_parser("harness", help="run a local mock-provider load scenario")
    harness.add_argument(
        "--scenario",
        choices=["burst", "steady-state", "error-storm", "budget-hit"],
        required=True,
    )
    harness.add_argument("--seed", type=int, default=DEFAULT_SEED)
    harness.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    benchmark = subparsers.add_parser(
        "benchmark", help="run the deterministic benchmark suite"
    )
    benchmark.add_argument(
        "--publish", action="store_true", help="write results to docs/benchmark-results-<date>.md"
    )
    benchmark.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    subparsers.add_parser("doctor", help="validate the Backstop install")

    serve = subparsers.add_parser(
        "serve", help="run Backstop as an OpenAI-compatible gateway/sidecar (needs fastapi)"
    )
    serve.add_argument("--target", required=True, help="upstream base URL, e.g. https://api.openai.com/v1")
    serve.add_argument("--budget", type=int, default=100_000, help="token budget for the gateway")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument(
        "--api-keys",
        help="comma-separated set of allowed Bearer tokens (auth disabled if omitted)",
        default=None,
    )
    serve.add_argument(
        "--rate-limit", type=int, default=None,
        help="max requests per minute per API key (requires --api-keys)",
    )
    serve.add_argument(
        "--config-json",
        help="optional BackstopConfig overrides as a JSON object",
        default=None,
    )

    metrics = subparsers.add_parser("metrics", help="start a Prometheus metrics server")
    metrics.add_argument("--port", type=int, default=9090)

    dashboard = subparsers.add_parser(
        "dashboard",
        help="serve the built-in dashboard for this process",
    )
    dashboard.add_argument("--port", type=int, default=DEFAULT_PORT)
    dashboard.add_argument("--host", default=DEFAULT_HOST, help="bind address (non-loopback requires --token)")
    dashboard.add_argument(
        "--refresh",
        type=float,
        default=None,
        help="sample interval in seconds (default: 1.0 in demo mode, else 2.0)",
    )
    dashboard.add_argument(
        "--cost-model",
        help="model whose input rate converts tokens into a USD lower bound, e.g. gpt-4o",
    )
    dashboard.add_argument(
        "--audit",
        help="path to an audit JSONL sink; enables the enforcement event stream",
    )
    dashboard.add_argument(
        "--demo",
        action="store_true",
        help="run a deterministic mock workload so the dashboard is live with no API keys",
    )
    dashboard.add_argument("--runners", type=int, default=3, help="demo runner count (default 3)")
    dashboard.add_argument(
        "--token",
        help="require this bearer token; mandatory when --host is not loopback",
    )
    dashboard.add_argument(
        "--theme",
        choices=("auto", "dark", "light"),
        default="auto",
        help="initial colour theme: auto follows the OS (default), or force dark/light",
    )
    dashboard.add_argument("--no-browser", action="store_true", help="do not open a browser")

    verify = subparsers.add_parser(
        "verify", help="run reproducible proof checks against this install (collapse install -> trust)"
    )
    # --live and --offline are opposites, so argparse owns the conflict: the
    # runner only reads --live, and a user who asked for no network must not
    # get a request either way.
    verify_network = verify.add_mutually_exclusive_group()
    verify_network.add_argument("--live", action="store_true", help="also probe the real provider (GET /models)")
    verify_network.add_argument("--offline", action="store_true", help="never touch the network (default)")
    verify.add_argument("--strict", action="store_true", help="treat warnings as failures (for CI)")
    verify.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    verify.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    verify.add_argument("--model", help="unused for auth probe; documented for future live completion")
    verify.add_argument("--base-url", help="override provider base URL for the live probe")
    verify.add_argument(
        "--api-key-env",
        default=None,
        help="env var holding the provider key (default: OPENAI_API_KEY for "
        "--provider openai, ANTHROPIC_API_KEY for --provider anthropic)",
    )
    verify.add_argument("--timeout", type=float, default=30.0, help="per-check timeout for live probes")

    demo = subparsers.add_parser(
        "demo", help="run a side-by-side comparison of an unprotected vs wrapped runaway loop"
    )
    demo.add_argument("--calls", type=int, default=10, help="number of loop iterations to simulate (default: 10)")
    demo.add_argument("--budget", type=int, default=75, help="token budget for the wrapped client (default: 75)")
    demo.add_argument("--provider", choices=["openai", "anthropic"], default="openai", help="client SDK to simulate (default: openai)")
    demo.add_argument("--model", help="model identifier for pricing and requests")
    demo.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    demo.add_argument("--strict", action="store_true", help="exit non-zero if the guardrail fails to block")

    real = subparsers.add_parser("real-openai", help="run a tiny real OpenAI API smoke test")
    real.add_argument("--model", help="model to use; defaults to OPENAI_MODEL or gpt-4.1-mini")
    real.add_argument("--base-url", help="override API base URL; defaults to OPENAI_BASE_URL")
    real.add_argument("--api", choices=["responses", "chat"], default="responses")
    real.add_argument("--budget", type=int, default=1_000)
    real.add_argument("--async-client", action="store_true", help="use AsyncOpenAI")
    real.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    real_anthropic = subparsers.add_parser(
        "real-anthropic", help="run a tiny real Anthropic API smoke test"
    )
    real_anthropic.add_argument(
        "--model", help="model to use; defaults to ANTHROPIC_MODEL or claude-sonnet-4-20250514"
    )
    real_anthropic.add_argument("--base-url", help="override API base URL; defaults to ANTHROPIC_BASE_URL")
    real_anthropic.add_argument("--budget", type=int, default=1_000)
    real_anthropic.add_argument("--async-client", action="store_true", help="use AsyncAnthropic")
    real_anthropic.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    ledger = subparsers.add_parser(
        "ledger", help="inspect and export the priced spend ledger"
    )
    ledger_commands = ledger.add_subparsers(dest="ledger_command", required=True)

    ledger_demo = ledger_commands.add_parser(
        "demo", help="print a priced chargeback table from fixed, offline events"
    )
    ledger_demo.add_argument(
        "--group-by", type=_group_by_arg, default=DEFAULT_LEDGER_GROUP_BY,
        help="comma-separated attribution dimensions (default: team,feature)",
    )
    ledger_demo.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    ledger_show = ledger_commands.add_parser(
        "show", help="report a JSONL ledger's integrity and chargeback"
    )
    ledger_show.add_argument("--path", required=True, help="path to a JSONL ledger file")
    ledger_show.add_argument(
        "--limit", type=int, default=20,
        help="maximum rows to print; 0 for every row (default: 20)",
    )
    ledger_show.add_argument(
        "--group-by", type=_group_by_arg, default=DEFAULT_LEDGER_GROUP_BY,
        help="comma-separated attribution dimensions (default: team,feature)",
    )
    ledger_show.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    ledger_export = ledger_commands.add_parser(
        "export", help="write a chargeback CSV from a JSONL ledger"
    )
    ledger_export.add_argument("--path", required=True, help="path to a JSONL ledger file")
    ledger_export.add_argument("--out", required=True, help="path of the CSV to write")
    ledger_export.add_argument(
        "--group-by", type=_group_by_arg, default=DEFAULT_LEDGER_GROUP_BY,
        help="comma-separated attribution dimensions (default: team,feature)",
    )
    ledger_export.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    budget = subparsers.add_parser(
        "budget",
        help="show spend against a ceiling (token or dollar), from a ledger file",
    )
    budget.add_argument(
        "--ledger", required=True, help="path to a JSONL ledger file"
    )
    budget.add_argument(
        "--usd",
        type=decimal.Decimal,
        default=None,
        help="the ceiling in dollars; without it the report shows the spend alone",
    )
    budget.add_argument(
        "--group-by",
        type=_group_by_arg,
        default=("team", "feature"),
        help="comma-separated dimensions to group by (default: team,feature)",
    )
    budget.add_argument("--limit", type=int, default=0, help="rows to show; 0 for all")
    budget.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    detect = subparsers.add_parser(
        "detect",
        help="run the runaway-spend detectors over a ledger file",
    )
    detect.add_argument("--ledger", required=True, help="path to a JSONL ledger file")
    detect.add_argument(
        "--window", type=int, default=64, help="events per attribution key to consider"
    )
    detect.add_argument(
        "--min-samples", type=int, default=8, help="samples a key needs before it can signal"
    )
    detect.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    forecast = subparsers.add_parser(
        "forecast",
        help="project budget exhaustion from the burn rate a ledger measured",
    )
    forecast.add_argument("--ledger", required=True, help="path to a JSONL ledger file")
    forecast.add_argument(
        "--usd", type=decimal.Decimal, default=None, help="the ceiling in dollars"
    )
    forecast.add_argument(
        "--horizon",
        type=float,
        default=3600.0,
        help="seconds ahead to flag exhaustion against (default: 3600)",
    )
    forecast.add_argument(
        "--group-by",
        type=_group_by_arg,
        default=("team", "feature"),
        help="comma-separated dimensions to group by (default: team,feature)",
    )
    forecast.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    audit = subparsers.add_parser(
        "audit",
        help="verify the tamper-evident audit chain",
    )
    audit.add_argument("--path", required=True, help="path to a JSONL audit log")
    audit.add_argument(
        "--hmac-key",
        default=None,
        help="the audit_hmac_key the chain was written with; without it the "
        "chain is checked without its key, which verifies the structure and "
        "not the signature",
    )
    audit.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")

    reconcile = subparsers.add_parser(
        "reconcile", help="reconcile the priced ledger against a provider statement file"
    )
    reconcile_demo = reconcile.add_mutually_exclusive_group(required=True)
    reconcile_demo.add_argument(
        "--demo",
        action="store_true",
        help="reconcile fixed, offline, synthetic events against a synthetic statement "
        "(no key, no network, no file)",
    )
    reconcile_demo.add_argument(
        "--ledger", help="path to a JSONL ledger file to reconcile"
    )
    reconcile.add_argument(
        "--invoice", help="path to the provider statement (.csv or .json); required with --ledger"
    )
    reconcile.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    reconcile.add_argument(
        "--tolerance-usd",
        type=decimal.Decimal,
        default=None,
        help="per-model-row dollar tolerance (default 0.01; see DEFAULT_TOLERANCE_USD)",
    )
    reconcile.add_argument(
        "--tolerance-pct",
        type=decimal.Decimal,
        default=None,
        help="per-model-row percentage tolerance (default 0.5; the looser of the two wins)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "budget":
        return _run_budget(args)

    if args.command == "detect":
        return _run_detect(args)

    if args.command == "forecast":
        return _run_forecast(args)

    if args.command == "audit":
        return _run_audit(args)

    if args.command == "reconcile" and args.ledger and not args.invoice:
        # A usage error, and exit 2, rather than a run that reconciles the ledger
        # against nothing and prints a clean-looking zero: there is no statement
        # file here to check the money on, and a report over an empty comparison
        # reads exactly like a report over a clean one.
        parser.error(
            "--ledger also needs --invoice: there is nothing to reconcile the ledger "
            "against without a statement file"
        )

    if args.command == "harness":
        result = run_harness(args.scenario, seed=args.seed)
        print(result_to_json(result) if args.json else result.to_markdown())
        return 0

    if args.command == "benchmark":
        if args.json:
            results = [run_harness(s).__dict__ for s in SCENARIOS]
            print(json.dumps(results, indent=2, sort_keys=True))
        else:
            _run_benchmark(publish=args.publish)
        return 0

    if args.command == "doctor":
        return _run_doctor()

    if args.command == "serve":
        try:
            import uvicorn
        except Exception:
            print("error: 'serve' requires the fastapi extra: pip install \"backstop[fastapi]\"")
            return 1
        from .config import BackstopConfig
        from .gateway import make_gateway_app

        config = BackstopConfig()
        if args.config_json:
            overrides = json.loads(args.config_json)
            config = BackstopConfig(**overrides)
        api_keys = set(args.api_keys.split(",")) if args.api_keys else None
        app = make_gateway_app(
            args.target, args.budget, config,
            api_keys=api_keys, rate_limit_per_key=args.rate_limit,
        )
        print(f"Backstop gateway listening on {args.host}:{args.port} -> {args.target}")
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    if args.command == "metrics":
        start_metrics_server(args.port)
        print(f"Backstop metrics listening on :{args.port}")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    if args.command == "dashboard":
        workload = None
        if args.demo:
            from .dashboard_demo import DemoWorkload

            workload = DemoWorkload(runners=args.runners)
        interval = args.refresh or (1.0 if args.demo else DEFAULT_SAMPLE_INTERVAL)
        panel = Dashboard(
            mode="demo" if args.demo else "live",
            cost_model=args.cost_model,
            audit=args.audit,
            interval=interval,
            token=args.token,
            demo=workload,
            theme=args.theme,
        )
        try:
            serve_dashboard(
                panel,
                host=args.host,
                port=args.port,
                open_browser=not args.no_browser,
            )
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        return 0

    if args.command == "verify":
        return run_verify(
            live=args.live,
            strict=args.strict,
            json_output=args.json,
            timeout=args.timeout,
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
        )

    if args.command == "demo":
        from .demo import run_demo

        result = run_demo(
            calls=args.calls,
            budget=args.budget,
            provider=args.provider,
            model=args.model,
            strict=args.strict,
        )
        if args.json:
            print(result.to_json())
        else:
            print(result.to_markdown())
        if result.error_message:
            print(f"error: {result.error_message}")
            return 1
        return 0 if (result.success or not args.strict) else 1

    if args.command == "ledger":
        return _run_ledger(args)

    if args.command == "reconcile":
        return _run_reconcile(args)

    if args.command == "real-openai":
        try:
            result = run_real_openai_smoke(
                model=args.model,
                base_url=args.base_url,
                api=args.api,
                budget=args.budget,
                async_client=args.async_client,
            )
            print(json.dumps(result.__dict__, indent=2, sort_keys=True) if args.json else result.to_markdown())
            return 0
        except RuntimeError as e:
            print(f"error: {e}")
            return 1

    if args.command == "real-anthropic":
        try:
            result = run_real_anthropic_smoke(
                model=args.model,
                base_url=args.base_url,
                budget=args.budget,
                async_client=args.async_client,
            )
            print(json.dumps(result.__dict__, indent=2, sort_keys=True) if args.json else result.to_markdown())
            return 0
        except RuntimeError as e:
            print(f"error: {e}")
            return 1

    return 2


def _run_ledger(args: argparse.Namespace) -> int:
    """Dispatch ``backstop ledger demo|show|export``.

    Three subcommands, no framework. The work is in
    :mod:`backstop.ledger.export` and :mod:`backstop.ledger.demo`; what is left
    here is the part a CLI owns: argument plumbing, a readable summary, and an
    exit code.

    Exit codes carry meaning. ``0`` means the report is complete: every line in
    the file was read, and any loss is a torn final line that is *named* in the
    output. ``1`` means the report would be wrong or absent — a file that will not
    open, a corrupt line, which raises :class:`LedgerCorruptionError` naming the
    line and is never skipped, or an amount too large to total. Silently dropping
    a line to produce a plausible total is the one outcome this refuses.
    """
    from .ledger import export as ledger_export
    from .ledger.demo import run_demo as run_ledger_demo

    if args.ledger_command == "demo":
        try:
            result = run_ledger_demo(group_by=tuple(args.group_by))
        except decimal.DecimalException as exc:
            return _decimal_failure(args, exc)
        print(result.to_json() if args.json else result.to_markdown())
        return 0

    try:
        read = ledger_export.read_ledger(args.path)
    except ledger_export.LedgerCorruptionError as exc:
        # stderr, and exit 1: a charge-back over a ledger with a hole in the middle
        # is not a charge-back. The message names the line, so the operator can go
        # and look at it.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: cannot read ledger {args.path!r}: {exc}", file=sys.stderr)
        return 1

    try:
        rows = ledger_export.build_chargeback(
            read.events, tuple(args.group_by), ledger_export.Period.all()
        )
        totals = ledger_export.chargeback_totals(rows, tuple(args.group_by))
    except decimal.DecimalException as exc:
        return _decimal_failure(args, exc)

    if args.ledger_command == "show":
        try:
            shown = list(rows) if args.limit == 0 else list(rows)[: max(args.limit, 0)]
            if args.json:
                payload = json.loads(
                    ledger_export.render_chargeback_json(shown, totals)
                )
                payload["file"] = read.to_dict()
                payload["rows_total"] = len(rows)
                payload["limit"] = args.limit
                # Both loss counters, as null rather than as 0: a JSONL line
                # records an event, never a counter, so the file cannot answer
                # this and a reader of the JSON deserves the same sentence a
                # reader of the table gets.
                payload["delivery"] = {
                    "dropped_events": None,
                    "sink_errors": None,
                    "note": ledger_export.FILE_DELIVERY_NOTE,
                }
                print(json.dumps(payload, indent=2, sort_keys=True))
                return 0
            print(_ledger_show_markdown(read, shown, totals, len(rows)))
        except decimal.DecimalException as exc:
            return _decimal_failure(args, exc)
        return 0

    try:
        # Every money rendering happens before the file is opened, so a decimal
        # failure cannot leave a written report behind a command that failed:
        # a half-finished export is a charge-back somebody will pivot.
        summary = (
            f"wrote {len(rows)} row(s) to {args.out} from {len(read.events)} event(s) "
            f"in {args.path} — {ledger_export.money(totals.total_usd)} "
            f"{totals.currency} total, {totals.unpriced_requests} unpriced, "
            f"{ledger_export.money(totals.unattributed_usd)} unattributed"
        )
        rendered = None if not args.json else ledger_export.render_chargeback_json(rows, totals)
        written = ledger_export.write_chargeback_csv(
            rows, args.out, group_by=tuple(args.group_by)
        )
    except decimal.DecimalException as exc:
        return _decimal_failure(args, exc)
    if args.json:
        payload = json.loads(rendered)
        payload["file"] = read.to_dict()
        payload["out"] = str(args.out)
        payload["rows_written"] = written
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(summary)
    return 0


def _decimal_failure(
    args: argparse.Namespace,
    exc: BaseException,
    *,
    command: str | None = None,
    path: str | None = None,
) -> int:
    """Report a decimal arithmetic failure as a diagnosis, not a traceback.

    A ``decimal`` context is process-global, and money that cannot be
    represented at the ledger's own 28 digits raises
    :class:`decimal.InvalidOperation` out of ``quantize``. Left alone that
    reaches the operator as ``decimal.InvalidOperation`` with no indication of
    which command failed, on which file, or what to do about it.

    The message names the command, the file, the ambient context and the usual
    cause, and goes to stderr with exit ``1`` — the same "the report would be
    wrong or absent" code a corrupt line gets, because it is the same class of
    outcome. The ambient context is printed because it is the first thing worth
    ruling out and it is the one thing the operator cannot see from the output.

    ``command`` and ``path`` let a caller outside the ``ledger`` subcommand reuse
    the same diagnosis; the ``ledger`` calls take their own two names from the
    namespace, as they always did.
    """
    context = decimal.getcontext()
    where = path if path is not None else getattr(args, "path", None)
    label = f"backstop ledger {args.ledger_command}" if command is None else command
    print(
        f"error: {label} could not total "
        f"{where!r}: {type(exc).__name__}: {exc} "
        f"(ambient decimal context: prec={context.prec}, Emax={context.Emax}). "
        "The ledger's own money arithmetic runs at prec=28 regardless of that "
        "context, so the usual cause is an amount with too many digits to "
        "quantise — check the cost and revenue figures in the file for an "
        "extreme magnitude.",
        file=sys.stderr,
    )
    return 1


def _run_reconcile(args: argparse.Namespace) -> int:
    """Dispatch ``backstop reconcile --demo | --ledger FILE --invoice FILE``.

    Two modes, no framework. The arithmetic is in
    :mod:`backstop.ledger.reconcile`; what is left here is argument plumbing, the
    two tolerance overrides, a readable report, and an exit code.

    Exit codes carry meaning, and they are the ledger's: ``0`` means the
    reconciliation ran and printed a report — **whatever the report says**. A
    variance is a finding, not a failure, and a command that exited non-zero on a
    variance would train an operator to ignore it. ``1`` means there is no report
    to read: a ledger that will not open, a corrupt line, a statement that does not
    parse, an unreadable path, or an amount too large to total. Nothing is
    reconciled silently past one of those, because a reconciliation over a file that
    failed to parse is the one output this command must never produce.
    """
    from pathlib import Path

    from .ledger import export as ledger_export
    from .ledger import reconcile as ledger_reconcile

    tolerance_usd = (
        args.tolerance_usd
        if args.tolerance_usd is not None
        else ledger_reconcile.DEFAULT_TOLERANCE_USD
    )
    tolerance_pct = (
        args.tolerance_pct
        if args.tolerance_pct is not None
        else ledger_reconcile.DEFAULT_TOLERANCE_PCT
    )

    if args.demo:
        try:
            result = ledger_reconcile.run_demo()
        except decimal.DecimalException as exc:
            return _decimal_failure(
                args, exc, command="backstop reconcile --demo", path="the synthetic statement"
            )
        print(result.to_json() if args.json else result.to_markdown())
        return 0

    try:
        read = ledger_export.read_ledger(args.ledger)
    except ledger_export.LedgerCorruptionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: cannot read ledger {args.ledger!r}: {exc}", file=sys.stderr)
        return 1

    suffix = Path(args.invoice).suffix.lower()
    parser_for = {".csv": ledger_reconcile.parse_invoice_csv, ".json": ledger_reconcile.parse_invoice_json}
    read_invoice = parser_for.get(suffix)
    if read_invoice is None:
        print(
            f"error: cannot tell what kind of statement {args.invoice!r} is: expected a "
            f".csv or a .json, got {suffix or '(no extension)'}. Backstop parses a "
            "statement FILE and does not guess a format.",
            file=sys.stderr,
        )
        return 1
    try:
        invoice = read_invoice(args.invoice)
    except (ValueError, TypeError) as exc:
        # A statement that does not parse is refused, never read as zeros. The
        # message names the row and the field, and a report over a file that failed
        # to parse would look exactly like a report over a clean one.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: cannot read statement {args.invoice!r}: {exc}", file=sys.stderr)
        return 1

    # One statement is one provider's, and so is one reconciliation: comparing
    # OpenAI's statement against Anthropic's traffic would report models as unbilled
    # that are billed on the other statement, which is a false variance.
    events = [event for event in read.events if event.provider == invoice.provider]
    skipped = len(read.events) - len(events)
    try:
        variance = ledger_reconcile.reconcile_invoice(
            events, invoice, tolerance_usd=tolerance_usd, tolerance_pct=tolerance_pct
        )
        budget = ledger_reconcile.measure_error_budget(
            events, (invoice,), tolerance_usd=tolerance_usd, tolerance_pct=tolerance_pct
        )
    except decimal.DecimalException as exc:
        return _decimal_failure(
            args, exc, command="backstop reconcile", path=args.invoice
        )

    if args.json:
        payload = variance.to_dict()
        payload["error_budget"] = budget.to_dict()
        payload["ledger"] = read.to_dict()
        payload["invoice"] = invoice.to_dict()
        payload["events_skipped_other_provider"] = skipped
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    lines = [
        f"# Ledger vs statement — {variance.provider}, {variance.period}",
        "",
        f"- **ledger file:** `{args.ledger}`",
        f"- **statement file:** `{invoice.source}`",
    ]
    if skipped:
        lines.append(
            f"- **{skipped} event(s) in the ledger name another provider** and were not "
            f"reconciled against this `{invoice.provider}` statement. Reconcile the "
            "providers separately."
        )
    lines.extend(["", "## Ledger file integrity", ""])
    lines.extend(ledger_export.format_file_delivery(read))
    lines.extend(
        [
            "",
            "## Reconciliation",
            "",
            variance.to_markdown_body(),
            budget.to_markdown(),
        ]
    )
    print("\n".join(lines))
    return 0


def _ledger_show_markdown(read, shown, totals, rows_total: int) -> str:
    """The ``ledger show`` report: the file's integrity, then its chargeback.

    The integrity report comes first and unconditionally. A reader who only looks
    at the total still cannot miss that a line was lost, because the sentence
    about it is the first thing on the screen.
    """
    from .ledger import export as ledger_export

    lines = [
        f"# Ledger: {read.path}",
        "",
        f"- events: **{len(read.events)}** from {read.lines_seen} line(s), "
        f"{read.bytes_read} bytes",
        f"- window: {totals.first_seen or '(no events)'} → "
        f"{totals.last_seen or '(no events)'}",
        "",
    ]
    lines.extend(ledger_export.format_file_delivery(read))
    lines.extend(
        [
            "",
            "## Chargeback",
            "",
            ledger_export.render_chargeback_markdown(shown, totals),
        ]
    )
    if len(shown) < rows_total:
        lines.extend(
            [
                "",
                f"_{rows_total - len(shown)} further row(s) not shown; `--limit 0` "
                "prints all, and `backstop ledger export` writes every row. The "
                f"totals line and the teardown below cover all {rows_total} rows of "
                "the file, not only the ones printed here._",
            ]
        )
    lines.extend(["", "## What a CFO reads first", "", totals.to_markdown()])
    return "\n".join(lines)


def result_to_json(result) -> str:
    return json.dumps(result.__dict__, indent=2, sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())
