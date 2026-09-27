from __future__ import annotations

import decimal
import gc
import json
import socket
from pathlib import Path

import pytest

from backstop.cli import main
from backstop.telemetry import get_registry


@pytest.fixture(autouse=True)
def clean_registry():
    get_registry().reset()
    gc.collect()
    yield
    get_registry().reset()
    gc.collect()


def test_cli_verify_default(capsys):
    code = main(["verify"])
    assert code == 0
    out = capsys.readouterr().out
    assert "# Backstop Verify — 30-Second Keyless Proof" in out
    assert "| Allowed calls | 2 |" in out
    assert "| Blocked calls | 8 |" in out
    assert "Status: VERIFIED (real wrap enforcement active)" in out


def test_cli_verify_strict(capsys):
    code = main(["verify", "--strict"])
    assert code == 0


def test_cli_verify_json(capsys):
    code = main(["verify", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "proof" in data
    assert "summary" in data
    assert "checks" in data
    assert data["proof"]["allowed_calls"] == 2
    assert data["proof"]["blocked_calls"] == 8
    assert data["proof"]["tokens_saved"] == 2000


def test_cli_verify_zero_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = main(["verify"])
    assert code == 0


def test_cli_demo_default(capsys):
    code = main(["demo"])
    assert code == 0
    out = capsys.readouterr().out
    assert "# Backstop Demo: Runaway Loop Guardrail Comparison" in out
    assert "| Calls completed | 10 | 3 | -7 (-70.0%) |" in out
    assert "| Calls blocked | 0 | 7 | +7 (blocked in-process) |" in out
    assert "BudgetExceededError" in out
    # Verify no ANSI noise
    assert "\x1b[" not in out


def test_cli_demo_strict(capsys):
    code = main(["demo", "--strict"])
    assert code == 0


def test_cli_demo_json(capsys):
    code = main(["demo", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["scenario"] == "runaway_agent_loop"
    assert data["guardrail_enforced"] is True
    assert data["delta_calls_saved"] == 7
    assert data["delta_tokens_saved"] == 175
    assert data["wrapped"]["calls_completed"] == 3
    assert data["wrapped"]["calls_blocked"] == 7


def test_cli_demo_provider_anthropic(capsys):
    code = main(["demo", "--provider", "anthropic"])
    assert code == 0
    out = capsys.readouterr().out
    assert "anthropic" in out
    assert "| Calls completed | 10 | 3 | -7 (-70.0%) |" in out


def test_cli_demo_zero_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code = main(["demo"])
    assert code == 0


# --------------------------------------------------------------------------
# backstop ledger
# --------------------------------------------------------------------------


@pytest.fixture
def ledger_file(tmp_path: Path) -> Path:
    """A JSONL ledger with one priced event and one unpriced, written by the sink."""
    from backstop.ledger import Attribution, PriceCatalog, SpendEvent, compute_cost
    from backstop.ledger.sink import JsonlSink

    catalog = PriceCatalog()
    sink = JsonlSink(tmp_path / "ledger.jsonl")
    for index, (model, team, feature, tokens) in enumerate(
        (
            ("gpt-4o", "payments", "checkout-v2", 10_000),
            ("gpt-4o", "payments", "checkout-v2", 20_000),
            ("mystery-v1", "payments", "checkout-v2", 5_000),
            ("gpt-4o", None, None, 4_000),
        )
    ):
        event = SpendEvent(
            event_id=f"{index:032x}",
            occurred_at=f"2026-09-26T0{index}:00:00.000000Z",
            provider="openai",
            model=model,
            endpoint="/v1/chat/completions",
            priority="default",
            outcome="success",
            input_tokens=tokens,
            output_tokens=100,
            estimated=False,
            attribution=Attribution(team=team, feature=feature),
        )
        cost = compute_cost(event, catalog)
        from dataclasses import replace

        sink.write(event if cost is None else replace(event, cost=cost))
    sink.close()
    return tmp_path / "ledger.jsonl"


def test_cli_ledger_demo_exits_zero_and_prints_a_chargeback(capsys):
    code = main(["ledger", "demo"])
    assert code == 0
    out = capsys.readouterr().out
    assert "# Backstop Ledger — Chargeback" in out
    assert "| team | feature | request_count |" in out
    assert "| **Total** | all |" in out
    assert "of priced spend is" in out
    assert "**lost (dropped + writer errors + sink errors): 0**" in out
    assert "\x1b[" not in out


def test_cli_ledger_demo_json_parses_and_carries_no_ansi(capsys):
    code = main(["ledger", "demo", "--json"])
    assert code == 0
    out = capsys.readouterr().out
    assert "\x1b[" not in out
    payload = json.loads(out)
    assert payload["simulated"] is True
    assert payload["network_calls"] == 0
    assert payload["totals"]["total_usd"] == "34.56"
    assert isinstance(payload["rows"][0]["total_usd"], str)
    assert payload["delivery"]["lost"] == 0
    assert payload["delivery"]["sink_sink_errors"] == 0


def test_cli_ledger_demo_is_byte_identical_across_two_runs(capsys):
    assert main(["ledger", "demo"]) == 0
    first = capsys.readouterr().out
    assert main(["ledger", "demo"]) == 0
    second = capsys.readouterr().out
    assert first.encode("utf-8") == second.encode("utf-8")
    assert first != ""


def test_cli_ledger_demo_needs_no_key_and_makes_no_network_call(capsys, monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)

    def refuse(*args, **kwargs):
        raise AssertionError("backstop ledger demo must not touch the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert main(["ledger", "demo"]) == 0
    assert "# Backstop Ledger — Chargeback" in capsys.readouterr().out


def test_cli_ledger_demo_group_by_changes_the_table(capsys):
    assert main(["ledger", "demo", "--group-by", "team,customer"]) == 0
    out = capsys.readouterr().out
    assert "| team | customer | request_count |" in out
    assert "**Grouped by:** team, customer" in out


def test_cli_ledger_show_reports_a_clean_file(capsys, ledger_file):
    code = main(["ledger", "show", "--path", str(ledger_file)])
    assert code == 0
    out = capsys.readouterr().out
    assert f"# Ledger: {ledger_file}" in out
    assert "- events: **4** from 4 line(s)" in out
    assert "torn final line: none" in out
    assert "| payments | checkout-v2 | 3 |" in out
    assert "## What a CFO reads first" in out
    assert "\x1b[" not in out


def test_cli_ledger_show_surfaces_both_loss_counters_as_unknown(capsys, ledger_file):
    assert main(["ledger", "show", "--path", str(ledger_file)]) == 0
    out = capsys.readouterr().out
    assert "dropped_events: unknown" in out
    assert "sink_errors: unknown" in out
    assert "not derivable from the file" in out
    # Not reported as zero: a zero would be a claim about a process we cannot see.
    assert "dropped_events: 0" not in out
    assert "sink_errors: 0" not in out


def test_cli_ledger_show_reads_the_rest_of_a_torn_ledger_and_says_so(capsys, ledger_file):
    complete = ledger_file.read_text(encoding="utf-8")
    torn = ledger_file.with_name("torn.jsonl")
    torn.write_text(complete[: -200], encoding="utf-8")
    code = main(["ledger", "show", "--path", str(torn)])
    assert code == 0
    out = capsys.readouterr().out
    assert "torn final line: line 4" in out
    assert "is LOST and is not counted" in out
    assert "- events: **3** from 4 line(s)" in out
    # The three readable events are still in the table, and the lost one is gone
    # from it rather than counted at zero: it was the unattributed event.
    assert "| payments | checkout-v2 | 3 |" in out
    assert "(unattributed)" not in out


def test_cli_ledger_show_fails_loudly_on_a_corrupt_non_final_line(capsys, ledger_file):
    lines = ledger_file.read_text(encoding="utf-8").splitlines(True)
    lines[1] = "{ this is not a ledger line\n"
    corrupt = ledger_file.with_name("corrupt.jsonl")
    corrupt.write_text("".join(lines), encoding="utf-8")
    code = main(["ledger", "show", "--path", str(corrupt)])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "line 2 is corrupt" in captured.err
    assert str(corrupt) in captured.err


def test_cli_ledger_show_json_parses_and_carries_no_ansi(capsys, ledger_file):
    assert main(["ledger", "show", "--path", str(ledger_file), "--json"]) == 0
    out = capsys.readouterr().out
    assert "\x1b[" not in out
    payload = json.loads(out)
    assert payload["file"]["events"] == 4
    assert payload["file"]["torn_write"] is None
    assert payload["rows_total"] == 2
    assert payload["totals"]["unpriced_requests"] == 1
    assert payload["totals"]["unattributed_requests"] == 1
    assert isinstance(payload["rows"][0]["total_usd"], str)
    # Both loss counters present and explicitly null rather than zero.
    assert payload["delivery"]["dropped_events"] is None
    assert payload["delivery"]["sink_errors"] is None
    assert "never a counter" in payload["delivery"]["note"]


def test_cli_ledger_show_json_reports_a_torn_write(capsys, ledger_file):
    complete = ledger_file.read_text(encoding="utf-8")
    torn = ledger_file.with_name("torn.jsonl")
    torn.write_text(complete[:-1], encoding="utf-8")
    assert main(["ledger", "show", "--path", str(torn), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["file"]["events"] == 4
    assert payload["file"]["torn_write"]["included"] is True
    assert payload["file"]["torn_write"]["line_number"] == 4


def test_cli_ledger_show_limit_caps_the_rows(capsys, ledger_file):
    assert main(["ledger", "show", "--path", str(ledger_file), "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "1 further row(s) not shown" in out
    assert main(["ledger", "show", "--path", str(ledger_file), "--limit", "0"]) == 0
    assert "further row(s) not shown" not in capsys.readouterr().out


def test_cli_ledger_show_on_a_missing_file_is_an_error_not_a_traceback(capsys, tmp_path):
    code = main(["ledger", "show", "--path", str(tmp_path / "nope.jsonl")])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot read ledger" in captured.err


def test_cli_ledger_export_writes_a_csv(capsys, ledger_file, tmp_path):
    out_path = tmp_path / "reports" / "chargeback.csv"
    code = main(
        [
            "ledger",
            "export",
            "--path",
            str(ledger_file),
            "--out",
            str(out_path),
            "--group-by",
            "team,feature",
        ]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "wrote 2 row(s)" in printed
    assert str(out_path) in printed
    assert "1 unpriced" in printed
    text = out_path.read_bytes().decode("utf-8")
    lines = text.split("\r\n")
    assert lines[0].startswith("team,feature,request_count,input_tokens,output_tokens")
    assert "unpriced_requests" in lines[0]
    assert lines[1].split(",")[0] == "payments"
    assert lines[-1] == ""  # the trailing terminator, and nothing after it
    # The unpriced request is counted in the file, not dropped with its row.
    assert lines[1].split(",")[10] == "1"
    assert "(unattributed),(unattributed)" in text


def test_cli_ledger_export_json_parses_and_carries_no_ansi(capsys, ledger_file, tmp_path):
    code = main(
        [
            "ledger",
            "export",
            "--path",
            str(ledger_file),
            "--out",
            str(tmp_path / "cb.csv"),
            "--json",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "\x1b[" not in out
    payload = json.loads(out)
    assert payload["rows_written"] == 2
    assert payload["out"].endswith("cb.csv")
    assert payload["file"]["events"] == 4
    assert isinstance(payload["totals"]["total_usd"], str)
    assert payload["group_by"] == ["team", "feature"]


def test_cli_ledger_export_refuses_a_corrupt_file_rather_than_writing_a_short_one(
    capsys, ledger_file, tmp_path
):
    lines = ledger_file.read_text(encoding="utf-8").splitlines(True)
    lines[1] = "garbage\n"
    corrupt = ledger_file.with_name("corrupt.jsonl")
    corrupt.write_text("".join(lines), encoding="utf-8")
    target = tmp_path / "should-not-exist.csv"
    code = main(["ledger", "export", "--path", str(corrupt), "--out", str(target)])
    assert code == 1
    assert "line 2 is corrupt" in capsys.readouterr().err
    assert not target.exists()


@pytest.mark.parametrize("value", ["team,bogus", "nope", "team,team", "", " "])
def test_cli_ledger_bad_group_by_is_a_usage_error(value, capsys, ledger_file, tmp_path):
    for argv in (
        ["ledger", "export", "--path", str(ledger_file), "--out", str(tmp_path / "x.csv")],
        ["ledger", "show", "--path", str(ledger_file)],
        ["ledger", "demo"],
    ):
        with pytest.raises(SystemExit) as caught:
            main(argv + ["--group-by", value])
        assert caught.value.code == 2
    assert capsys.readouterr().out == ""


@pytest.fixture
def absurd_ledger(tmp_path: Path) -> Path:
    """A ledger whose one event carries a cost with more digits than money has.

    Written by hand rather than produced, because no provider and no rate card
    produces it: the point is that the reader accepts a syntactically valid
    ``total_usd`` it cannot total, and that the operator gets a diagnosis rather
    than a ``decimal.InvalidOperation`` traceback.
    """
    path = tmp_path / "absurd.jsonl"
    huge = "1" * 27 + ".890123"
    line = {
        "event_id": "0" * 32,
        "occurred_at": "2026-09-26T01:00:00.000000Z",
        "schema_version": "1.0",
        "provider": "openai",
        "model": "gpt-4o",
        "endpoint": "/v1/chat/completions",
        "priority": "default",
        "outcome": "success",
        "input_tokens": 10_000,
        "output_tokens": 100,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "latency_ms": 12.0,
        "retries": 0,
        "estimated": False,
        "attribution": {"team": "payments", "feature": None, "environment": None},
        "request_id": None,
        "cost": {
            "input_usd": huge,
            "output_usd": "0.001000",
            "cache_read_usd": "0.000000",
            "cache_write_usd": "0.000000",
            "total_usd": huge,
            "currency": "USD",
            "price_source": "bundled",
            "estimated_tokens": False,
            "priced_components": ["input", "output", "cache_read", "cache_write"],
        },
    }
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")
    return path


def test_cli_ledger_show_diagnoses_a_decimal_failure_instead_of_tracing_back(
    capsys, absurd_ledger
):
    """The last resort: the money is too big to total, and it says so.

    A ``quantize`` at 28 significant digits cannot represent a 33-digit amount,
    so the arithmetic raises. Left alone that reached the operator as a bare
    ``decimal.InvalidOperation`` with no command, no file and no cause.
    """
    code = main(["ledger", "show", "--path", str(absurd_ledger)])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "backstop ledger show could not total" in captured.err
    assert str(absurd_ledger) in captured.err
    assert "InvalidOperation" in captured.err
    # The ambient context is named because it is the first thing to rule out and
    # the one thing the operator cannot see from the output.
    assert f"prec={decimal.getcontext().prec}" in captured.err
    assert "too many digits to quantise" in captured.err
    assert "Traceback" not in captured.err


def test_cli_ledger_export_diagnoses_a_decimal_failure_and_writes_nothing(
    capsys, absurd_ledger, tmp_path
):
    target = tmp_path / "should-not-exist.csv"
    code = main(["ledger", "export", "--path", str(absurd_ledger), "--out", str(target)])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "backstop ledger export could not total" in captured.err
    assert "InvalidOperation" in captured.err
    # A report that cannot be totalled is not written: a half-written CSV is a
    # charge-back somebody will pivot.
    assert not target.exists()


def test_cli_ledger_demo_diagnoses_a_decimal_failure(monkeypatch, capsys):
    """The demo path too, for the same reason: one guard, three subcommands."""

    def explode(*args, **kwargs):
        raise decimal.InvalidOperation("quantize")

    monkeypatch.setattr("backstop.ledger.demo.build_chargeback", explode)
    code = main(["ledger", "demo"])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "backstop ledger demo could not total" in captured.err
    assert "InvalidOperation" in captured.err


def test_cli_ledger_requires_a_subcommand(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["ledger"])
    assert caught.value.code == 2


# --------------------------------------------------------------------------
# backstop reconcile
# --------------------------------------------------------------------------


@pytest.fixture
def reconcile_ledger(tmp_path: Path) -> Path:
    """A JSONL ledger with two priced models, written through the ledger's own sink.

    1,000,000 input tokens on gpt-4o is 2.500000 at the bundled $2.50/Mtok and
    2,000,000 on gpt-4.1 is 4.000000 at $2.00/Mtok. The figures below are those, and
    the test asserts the report's variance against them rather than re-deriving it.
    """
    from dataclasses import replace

    from backstop.ledger import Attribution, PriceCatalog, SpendEvent, compute_cost
    from backstop.ledger.sink import JsonlSink

    catalog = PriceCatalog()
    sink = JsonlSink(tmp_path / "ledger.jsonl")
    for index, (model, tokens) in enumerate((("gpt-4o", 1_000_000), ("gpt-4.1", 2_000_000))):
        event = SpendEvent(
            event_id=f"{index:032x}",
            occurred_at=f"2026-09-26T0{index}:00:00.000000Z",
            provider="openai",
            model=model,
            endpoint="/v1/chat/completions",
            priority="default",
            outcome="success",
            input_tokens=tokens,
            output_tokens=0,
            estimated=False,
            attribution=Attribution(team="payments", feature="checkout-v2"),
        )
        cost = compute_cost(event, catalog)
        sink.write(replace(event, cost=cost))
    sink.close()
    return tmp_path / "ledger.jsonl"


@pytest.fixture
def reconcile_statement(tmp_path: Path) -> Path:
    """A statement that bills gpt-4o a quarter of a dollar more than the ledger priced
    it, and gpt-4.1 exactly what the ledger priced it."""
    path = tmp_path / "openai.csv"
    path.write_text(
        "date,model,input_uncached_tokens,output_tokens,cost_usd\n"
        "2026-09-26,gpt-4o,1000000,0,2.750000\n"
        "2026-09-26,gpt-4.1,2000000,0,4.000000\n",
        encoding="utf-8",
    )
    return path


def test_cli_reconcile_demo_exits_zero_and_prints_a_variance_table(capsys):
    code = main(["reconcile", "--demo"])
    assert code == 0
    out = capsys.readouterr().out
    assert "# Backstop Reconciliation" in out
    assert "| provider | model | status | ledger_usd | invoice_usd | variance_usd |" in out
    assert "## Error budget, measured over these inputs" in out
    assert "\x1b[" not in out


def test_cli_reconcile_demo_reports_a_variance_and_a_match_not_a_clean_sheet(capsys):
    """A demo where everything reconciles teaches nothing about what the tool is
    for, so the synthetic statement is declared to disagree in five ways."""
    code = main(["reconcile", "--demo"])
    assert code == 0
    out = capsys.readouterr().out
    assert "matched" in out
    assert "variance" in out
    assert "missing_from_ledger" in out
    assert "missing_from_invoice" in out
    assert "every row below differs" in out


def test_cli_reconcile_demo_says_it_is_not_a_real_invoice(capsys):
    assert main(["reconcile", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "not** a reconciliation against a real" in out
    assert "has never run one" in out
    assert "verification against a real statement" in out


def test_cli_reconcile_demo_is_byte_identical_across_two_runs(capsys):
    assert main(["reconcile", "--demo"]) == 0
    first = capsys.readouterr().out
    assert main(["reconcile", "--demo"]) == 0
    second = capsys.readouterr().out
    assert first.encode("utf-8") == second.encode("utf-8")
    assert first != ""


def test_cli_reconcile_demo_needs_no_key_and_makes_no_network_call(capsys, monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)

    def refuse(*args, **kwargs):
        raise AssertionError("backstop reconcile --demo must not touch the network")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert main(["reconcile", "--demo"]) == 0
    assert "# Backstop Reconciliation" in capsys.readouterr().out


def test_cli_reconcile_demo_json_carries_the_counts_and_the_budget(capsys):
    code = main(["reconcile", "--demo", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["simulated"] is True
    assert payload["network_calls"] == 0
    assert payload["deterministic"] is True
    assert len(payload["reconciliations"]) == 2
    counts = payload["reconciliations"][0]["counts"]
    assert counts["events"] > 0
    assert counts["invoice_lines"] > 0
    assert counts["models"] > 0
    assert "empirical figure" in payload["error_budgets"][0]["note"]
    # Every money field is a string, so nothing downstream can re-round it.
    for reconciliation in payload["reconciliations"]:
        for row in reconciliation["rows"]:
            assert isinstance(row["variance_usd"], str)
            assert isinstance(row["ledger_usd"], str)


def test_cli_reconcile_reads_a_ledger_and_a_statement(capsys, reconcile_ledger, reconcile_statement):
    code = main(
        [
            "reconcile",
            "--ledger",
            str(reconcile_ledger),
            "--invoice",
            str(reconcile_statement),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "# Ledger vs statement — openai, 2026-09-26" in out
    assert f"**ledger file:** `{reconcile_ledger}`" in out
    assert "## Ledger file integrity" in out
    # The two loss counters a file read cannot answer are stated as unknown, beside
    # the reconciliation rather than buried in it.
    assert "dropped_events: unknown" in out
    assert "sink_errors: unknown" in out
    assert "## Reconciliation" in out
    # gpt-4o's exact signed variance: 2.500000 priced against 2.750000 charged.
    assert "-0.250000 USD" in out
    assert "| openai | gpt-4o | variance | 2.50 | 2.75 | -0.25 |" in out
    # gpt-4.1 reconciles exactly, so the tool can say so.
    assert "| openai | gpt-4.1 | matched | 4.00 | 4.00 | 0.00 |" in out
    assert "## Error budget, measured over these inputs" in out


def test_cli_reconcile_json_carries_the_file_reports_and_the_budget(
    capsys, reconcile_ledger, reconcile_statement
):
    code = main(
        [
            "reconcile",
            "--ledger",
            str(reconcile_ledger),
            "--invoice",
            str(reconcile_statement),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider"] == "openai"
    assert payload["counts"]["events"] == 2
    assert payload["counts"]["invoice_lines"] == 2
    assert payload["counts"]["reconciled_models"] == 1
    assert payload["totals"]["variance_usd"] == "-0.250000"
    assert payload["error_budget"]["worst_model"] == "gpt-4o"
    assert payload["error_budget"]["observed_abs_variance_usd"] == "0.250000"
    # The ledger's own integrity report travels with the reconciliation, and the
    # markdown above it states the two loss counters as unknown rather than as zero.
    assert payload["ledger"]["events"] == 2
    assert payload["ledger"]["lines_seen"] == 2
    assert payload["ledger"]["torn_write"] is None
    assert payload["invoice"]["lines"][0]["charged_usd"] == "2.750000"
    assert payload["scope"].startswith("This reconciles the ledger against a statement FILE")


def test_cli_reconcile_reports_the_rows_it_skipped_because_they_name_another_provider(
    capsys, reconcile_ledger, reconcile_statement
):
    """A statement is one provider's, so the other provider's traffic is not silently
    dropped and not silently reconciled against it either."""
    code = main(
        ["reconcile", "--ledger", str(reconcile_ledger), "--invoice", str(reconcile_statement)]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "0 event(s) in the ledger name another provider" not in out

    other = reconcile_statement.with_name("other.csv")
    other.write_text(
        "date,model,uncached_input_tokens,output_tokens,cache_read_input_tokens,cost_usd\n"
        "2026-09-26,claude-opus-5,100000,0,0,0.500000\n",
        encoding="utf-8",
    )
    assert main(["reconcile", "--ledger", str(reconcile_ledger), "--invoice", str(other)]) == 0
    out = capsys.readouterr().out
    assert "2 event(s) in the ledger name another provider" in out
    assert "claude-opus-5" in out
    assert "missing_from_ledger" in out


def test_cli_reconcile_tolerance_flags_are_parameters_and_never_floats(
    capsys, reconcile_ledger, reconcile_statement
):
    """argparse's ``type=`` hands the string to ``Decimal``, so a tolerance typed on a
    command line is exact rather than a binary float."""
    code = main(
        [
            "reconcile",
            "--ledger",
            str(reconcile_ledger),
            "--invoice",
            str(reconcile_statement),
            "--tolerance-usd",
            "0",
            "--tolerance-pct",
            "0",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tolerance_usd"] == "0"
    assert payload["tolerance_pct"] == "0"
    # gpt-4.1 matched exactly, so a zero tolerance does not change it; gpt-4o is
    # still a variance at a quarter of a dollar.
    assert payload["counts"]["reconciled_models"] == 1


def test_cli_reconcile_reads_a_json_statement_too(capsys, reconcile_ledger, tmp_path):
    statement = tmp_path / "openai.json"
    statement.write_text(
        json.dumps(
            {
                "provider": "openai",
                "period": "2026-09-26",
                "lines": [
                    {
                        "date": "2026-09-26",
                        "model": "gpt-4o",
                        "input_uncached_tokens": "1000000",
                        "output_tokens": "0",
                        "cost_usd": "2.500000",
                    },
                    {
                        "date": "2026-09-26",
                        "model": "gpt-4.1",
                        "input_uncached_tokens": "2000000",
                        "output_tokens": "0",
                        "cost_usd": "4.000000",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    code = main(["reconcile", "--ledger", str(reconcile_ledger), "--invoice", str(statement)])
    assert code == 0
    out = capsys.readouterr().out
    assert "| openai | gpt-4o | matched | 2.50 | 2.50 | 0.00 |" in out
    assert "| openai | gpt-4.1 | matched | 4.00 | 4.00 | 0.00 |" in out


def test_cli_reconcile_refuses_a_statement_it_cannot_parse(capsys, reconcile_ledger, tmp_path):
    """A statement with no charged-amount column would reconcile as 0.00 against a
    ledger and look perfect. It raises, names the field, and exits 1."""
    statement = tmp_path / "no-cost.csv"
    statement.write_text(
        "date,model,input_uncached_tokens,output_tokens\n2026-09-26,gpt-4o,1000000,0\n",
        encoding="utf-8",
    )
    code = main(["reconcile", "--ledger", str(reconcile_ledger), "--invoice", str(statement)])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "'charged_usd'" in captured.err
    assert "refuses it rather than reporting zeros" in captured.err


def test_cli_reconcile_refuses_a_statement_format_it_does_not_read(
    capsys, reconcile_ledger, tmp_path
):
    statement = tmp_path / "statement.xml"
    statement.write_text("<statement/>", encoding="utf-8")
    code = main(["reconcile", "--ledger", str(reconcile_ledger), "--invoice", str(statement)])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "expected a .csv or a .json" in captured.err


def test_cli_reconcile_fails_on_a_corrupt_ledger_without_printing_a_report(
    capsys, reconcile_ledger, reconcile_statement
):
    lines = reconcile_ledger.read_text(encoding="utf-8").splitlines(True)
    corrupt = reconcile_ledger.with_name("corrupt.jsonl")
    corrupt.write_text("".join([lines[0], "{not json}\n", lines[1]]), encoding="utf-8")
    code = main(["reconcile", "--ledger", str(corrupt), "--invoice", str(reconcile_statement)])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "line 2" in captured.err


def test_cli_reconcile_fails_on_a_missing_ledger_file(capsys, tmp_path, reconcile_statement):
    code = main(
        [
            "reconcile",
            "--ledger",
            str(tmp_path / "nope.jsonl"),
            "--invoice",
            str(reconcile_statement),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot read ledger" in captured.err


def test_cli_reconcile_diagnoses_a_decimal_failure(monkeypatch, capsys, reconcile_ledger, reconcile_statement):
    def explode(*args, **kwargs):
        raise decimal.InvalidOperation("quantize")

    monkeypatch.setattr("backstop.ledger.reconcile.measure_error_budget", explode)
    code = main(["reconcile", "--ledger", str(reconcile_ledger), "--invoice", str(reconcile_statement)])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "backstop reconcile could not total" in captured.err
    assert "InvalidOperation" in captured.err


def test_cli_reconcile_demo_diagnoses_a_decimal_failure(monkeypatch, capsys):
    def explode(*args, **kwargs):
        raise decimal.InvalidOperation("quantize")

    monkeypatch.setattr("backstop.ledger.reconcile.run_demo", explode)
    code = main(["reconcile", "--demo"])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "backstop reconcile --demo could not total" in captured.err


def test_cli_reconcile_needs_a_mode(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["reconcile"])
    assert caught.value.code == 2
    assert "--demo" in capsys.readouterr().err


def test_cli_reconcile_ledger_without_an_invoice_is_a_usage_error(capsys, reconcile_ledger):
    """There is nothing to reconcile against, and a report over an empty comparison
    reads exactly like a report over a clean one."""
    with pytest.raises(SystemExit) as caught:
        main(["reconcile", "--ledger", str(reconcile_ledger)])
    assert caught.value.code == 2
    assert "--ledger also needs --invoice" in capsys.readouterr().err
