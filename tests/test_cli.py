from __future__ import annotations

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


def test_cli_ledger_requires_a_subcommand(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["ledger"])
    assert caught.value.code == 2
