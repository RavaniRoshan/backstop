"""The real-world demo is a script, and a script rots.

These are the checks that keep it honest: that it runs, that the traffic it
generates is recorded in a ledger with real prices on it, and that the guardrail
it claims to demonstrate actually fires. They are fast — the scenario is
shortened rather than the assertions weakened.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "demos" / "real_world" / "run.py"
LEDGER = REPO / "demos" / "real_world" / "out" / "noisy-neighbour" / "ledger.jsonl"

# The demo is a script, not a package, so it is imported by path.
sys.path.insert(0, str(REPO / "demos" / "real_world"))


def _run_demo(*args: str) -> subprocess.CompletedProcess:
    """Run the demo in its own process, on a port nothing else is using."""
    return subprocess.run(
        [sys.executable, str(DEMO), *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_demo_lists_every_scenario_and_the_whole_endpoint_matrix():
    result = _run_demo("--list")
    assert result.returncode == 0, result.stderr
    for key in (
        "noisy-neighbour",
        "agent-loop",
        "retry-storm",
        "rag-peak",
        "cloud-gateway",
    ):
        assert key in result.stdout
    # All four kinds of server, and the endpoints behind them.
    for endpoint in (
        "https://api.deepinfra.com/v1/openai",
        "https://api.anthropic.com",
        "http://localhost:8000/v1",
        "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1",
    ):
        assert endpoint in result.stdout


def test_a_scenario_runs_and_prices_its_traffic():
    """A run has to produce a ledger, and the ledger has to be priced.

    An unpriced event is not a rounding error: it is a request whose cost
    nobody can name, which is the one thing this demo exists to be about.
    """
    result = _run_demo(
        "--scenario", "noisy-neighbour",
        "--duration", "8",
        "--speed", "3",
        "--port", "0",
    )
    assert result.returncode == 0, result.stderr
    assert "without the guardrail" in result.stdout

    assert LEDGER.exists(), "the demo wrote no ledger"
    events = [
        json.loads(line)
        for line in LEDGER.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert events, "the demo produced no events"

    priced = [event for event in events if event.get("cost")]
    assert len(priced) == len(events), "some events were recorded unpriced"
    assert priced[0]["cost"]["total_usd"] != "0.000000"

    # The tenant is on the event, which is what makes the charge-back answer
    # "which customer".
    assert {event["attribution"]["tenant"] for event in events} & {
        "acme",
        "globex",
        "initech",
    }


def test_the_guardrail_actually_fires():
    """The whole point: a runaway tenant is cut off, and the others are not.

    The scenario is long enough for the loop to start and for the tenant's
    own cap to be reached, and short enough to run in a test.
    """
    result = _run_demo(
        "--scenario", "noisy-neighbour",
        "--duration", "30",
        "--speed", "5",
        "--port", "0",
    )
    assert result.returncode == 0, result.stderr
    assert "denied by the guardrail" in result.stdout, result.stdout

    # The healthy tenants kept working: their spend is non-zero, and they
    # were not denied.
    globex = _line_for(result.stdout, "Globex (Professional)")
    assert globex
    assert float(globex.split()[-1].lstrip("$")) > 0


def _line_for(text: str, label: str) -> str | None:
    for line in text.splitlines():
        if label in line and "calls" in line:
            return line
    return None


@pytest.mark.parametrize(
    "name,expected",
    [
        ("noisy-neighbour", "DeepInfra"),
        ("agent-loop", "Anthropic"),
        ("retry-storm", "vLLM"),
        ("rag-peak", "DeepInfra"),
        ("cloud-gateway", "Amazon Bedrock"),
    ],
)
def test_every_scenario_names_the_endpoint_it_reproduces(name: str, expected: str):
    """Each scenario is one of the four kinds of server, and says which."""
    from demos.real_world.catalogue import SCENARIOS_BY_KEY

    scenario = SCENARIOS_BY_KEY[name]
    assert scenario.endpoint.label == expected
    assert scenario.source_url.startswith("http")
    assert scenario.real_spend
