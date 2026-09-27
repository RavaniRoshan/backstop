"""The version lives in four files, and it has drifted.

``pyproject.toml`` is what PyPI gets, ``backstop.__version__`` is what
``backstop doctor`` prints, ``ts/backstop/package.json`` is what npm gets, and
``install.sh`` pins it for the shell installer. Nothing in the build enforces
that they agree, so a release can ship a wheel whose metadata says 0.7.0 while
``backstop.__version__`` reports 0.6.0 -- and the npm package can fall
arbitrarily far behind, because publishing it is a separate manual step nobody
is reminded of.

Both have happened. The npm package sat at 0.5.0 in its own lockfile through a
0.6.0 release. This asserts all four agree, that the CHANGELOG has a section
for the current version, and that the licence text ships rather than merely
being declared.

``tests/test_installer.py`` also compares install.sh against pyproject. That
overlap is deliberate rather than redundant: it caught the install.sh miss
during this release before this file existed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import backstop

ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    """Read ``[project] version`` by pattern, not by parsing TOML.

    ``tomllib`` is stdlib from 3.11 and this package supports 3.10, so importing
    it broke collection on the two oldest interpreters in the matrix. A regex is
    the wrong tool for TOML in general and the right one here: the assertion is
    only that the four version strings agree, and `twine check` is what actually
    validates the built metadata.
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m, "no version in pyproject.toml"
    return m.group(1)


def _installer_version() -> str:
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    m = re.search(r'^BACKSTOP_VERSION="([^"]+)"', text, re.M)
    assert m, "install.sh has no BACKSTOP_VERSION"
    return m.group(1)


def _npm_version() -> str:
    data = json.loads((ROOT / "ts" / "backstop" / "package.json").read_text(encoding="utf-8"))
    return str(data["version"])


def test_the_package_reports_the_version_pyproject_declares():
    assert backstop.__version__ == _pyproject_version()


def test_the_npm_package_is_the_same_version_as_the_python_one():
    assert _npm_version() == _pyproject_version()


def test_the_installer_pins_the_same_version():
    assert _installer_version() == _pyproject_version()


def test_the_version_is_a_plain_three_part_number():
    """A dirty version silently becomes part of the published filename."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", backstop.__version__), backstop.__version__


def test_the_changelog_has_a_section_for_the_current_version():
    """A release with no CHANGELOG section is a release nobody can read later."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = backstop.__version__
    # Released sections are headed `## 0.6.0` or `## v0.5.0 — ...`, and the
    # pending one is `## [Unreleased]`, so accept either spelling of the number.
    assert re.search(rf"^##\s+\[?v?{re.escape(version)}\]?", changelog, re.M), (
        f"CHANGELOG.md has no section for {version}"
    )


@pytest.mark.parametrize("rel", ["CHANGELOG.md", "README.md"])
def test_the_sdist_will_contain_this_file(rel):
    """These are the files a reader needs and a build backend will not add."""
    assert (ROOT / rel).exists(), f"{rel} is missing from the repository root"


def test_the_licence_text_is_present_not_just_declared():
    """`license = { text = "MIT" }` is a claim; MIT also requires the text.

    The repository carries it as LICENSE.txt, which is conventional, so this
    accepts either spelling rather than renaming a file to satisfy a test.
    """
    found = [p for p in ROOT.glob("LICENSE*") if p.is_file()]
    assert found, "no LICENSE file, so the declared MIT licence ships no text"


def test_the_cache_write_tier_caveat_reaches_every_human_reading_a_chargeback():
    """A wrong number that looks complete is the worst failure class in the ledger.

    The bundled card prices Anthropic's 5-minute cache-write tier, so a
    deployment on the 1-hour TTL under-counts that component by 37.5% while every
    row still lists `cache_write` among its priced components. The event record
    cannot reveal it, because the ledger never observes the request's
    cache_control -- so the caveat has to travel with the figure instead.

    "Human-facing" is load-bearing. The markdown report carries it, and so does
    `doctor`. The CSV deliberately does not: RFC 4180 has no comment syntax, the
    module's documented contract is minimal quoting, and a leading non-data row
    breaks every naive `read_csv`. Prose inside a file somebody pivots would be a
    second wrong thing, so the file stays data and the console carries the words.
    """
    from backstop.ledger.demo import demo_events
    from backstop.ledger.export import (
        build_chargeback,
        chargeback_caveats,
        render_chargeback_csv,
        render_chargeback_markdown,
    )

    caveat = chargeback_caveats()
    assert caveat, "the charge-back caveats went empty"
    assert "5-minute" in caveat[0]
    assert "1-hour" in caveat[0]
    # Quantified, not merely flagged: a reader must be able to size the risk.
    assert "37.5%" in caveat[0]

    rows = build_chargeback(demo_events())
    assert caveat[0] in render_chargeback_markdown(rows)

    # The CSV is pure data: a header row, and nothing above it.
    csv_text = render_chargeback_csv(rows)
    assert csv_text.splitlines()[0].startswith("team,")
    assert "CAVEAT" not in csv_text.splitlines()[0]


def test_doctor_prints_the_cache_write_tier_caveat(capsys):
    """doctor is the one command a user is guaranteed to run before quoting a
    number, so the limitation belongs there rather than only in the docs."""
    from backstop.cli import main

    main(["doctor"])
    out = capsys.readouterr().out
    assert "5-minute tier" in out, "doctor no longer states the cache-write tier"
    assert "1-hour" in out


def test_writing_a_chargeback_csv_states_the_caveat_on_the_console(capsys, tmp_path):
    """The CSV is data; the console is where a human reads the caveat.

    An earlier attempt put a `# CAVEAT:` comment row at the top of the CSV. It
    satisfied the warning and broke the file: RFC 4180 has no comment syntax,
    the module's documented contract is minimal quoting, and a leading non-data
    row makes every naive `read_csv` fail. So the caveat goes to stdout and into
    the --json payload, and the file stays exactly the data finance pivots.
    """
    import json as _json

    from backstop.cli import main
    from backstop.ledger.demo import demo_events
    from backstop.ledger.sink import JsonlSink

    ledger = tmp_path / "ledger.jsonl"
    sink = JsonlSink(str(ledger))
    for event in demo_events():
        sink.write(event)
    sink.flush()
    sink.close()

    out_csv = tmp_path / "chargeback.csv"
    assert main(["ledger", "export", "--path", str(ledger), "--out", str(out_csv)]) == 0
    printed = capsys.readouterr().out
    assert "5-minute tier" in printed, "the export command did not state the caveat"

    # And the file itself is still pure data: a header, and no comment row.
    body = out_csv.read_text(encoding="utf-8")
    assert not body.lstrip().startswith("#")
    assert body.splitlines()[0].startswith("team,")

    # The machine-readable path carries it as a field rather than a comment.
    out_json = tmp_path / "chargeback.json"
    assert main(["ledger", "export", "--path", str(ledger),
                 "--out", str(out_json), "--json"]) == 0
    payload = _json.loads(capsys.readouterr().out)
    assert payload["caveats"], "the JSON export dropped the caveats"
    assert "5-minute tier" in payload["caveats"][0]


def test_only_publishing_jobs_may_mint_an_oidc_token():
    """`id-token: write` is a real capability, not a checkbox.

    Both publish jobs -- PyPI and npm -- need it to exchange the workflow
    identity for a short-lived token. No other job does, and a token any job can
    mint is a token any compromised dependency in that job can use to publish.
    Asserting the grant is not spread means widening it later is a deliberate act
    rather than a copy-paste.
    """
    import re

    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    granted = set()
    current = None
    for line in workflow.splitlines():
        job = re.match(r"^  ([a-z-]+):$", line)
        if job:
            current = job.group(1)
        elif current and "id-token: write" in line:
            granted.add(current)

    assert granted == {"build", "npm-publish"}, (
        f"id-token: write is granted to {sorted(granted)}; only the PyPI and npm "
        "publish jobs should hold it"
    )


def test_the_npm_publish_job_documents_the_trusted_publisher_setup():
    """The one manual step, recorded where whoever hits E403 will look.

    npm will not accept the workflow until the package names it as a trusted
    publisher, and that can only be done in npm's UI. The job says so in a
    comment; this asserts the comment is still there, so it cannot be deleted as
    clutter while the failure it explains is still live.
    """
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Trusted Publisher" in workflow
    assert "ts/backstop/package.json" in workflow
    assert "E403" in workflow
