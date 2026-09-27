"""The coverage gate needs a test of its own.

Three times during this work the audit, not the product, was the broken thing:
it ran the suite with an interpreter that lacked the test extra and reported a
product failure; it looked for a double-quoted "/og.png" in a TSX file that uses
single quotes; and it built "content/content/docs/..." out of a citation that
already began with "content". Each one reported a defect that did not exist.

A gate nobody tests is a gate that eventually cries wolf, and a gate that cries
wolf is worse than no gate -- it teaches you to ignore the number. So these
assert the gate's own mechanics: that a probe which cannot decide counts as a
failure, that its file paths resolve, and that it is checking the repository it
thinks it is.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("consumer_ready", ROOT / "audit" / "consumer_ready.py")
assert _spec and _spec.loader
audit = importlib.util.module_from_spec(_spec)
sys.modules["consumer_ready"] = audit
_spec.loader.exec_module(audit)


def test_the_audit_points_at_this_repository():
    assert audit.REPO == ROOT, f"the audit reads {audit.REPO}, not {ROOT}"


def test_the_audit_survives_having_no_site_checkout():
    """This test used to assert the site exists at a hard-coded local path.

    Which is false on CI, on a fresh clone, and on anybody else's machine -- so
    it failed on thirteen CI legs for a reason that had nothing to do with the
    product. The site is a separate repository; a checkout of this one cannot
    contain it, and the audit has to say so rather than crash or pretend.
    """
    if audit.SITE is None:
        assert audit.SITE_URL.startswith("https://"), "the live site URL must always be known"
        return
    assert (audit.SITE / "package.json").exists(), f"no site package.json at {audit.SITE}"


def test_every_probe_group_is_callable_and_wired():
    for name, fn in audit.GROUPS:
        assert callable(fn), name


def test_a_report_counts_a_failed_probe_as_outstanding_not_skipped():
    rep = audit.Report()
    assert rep.blocking_total == 0
    rep.add("g", "passes", True)
    assert rep.outstanding == []
    rep.add("g", "fails", False, "because")
    assert len(rep.outstanding) == 1
    assert rep.blocking_total == 2
    # Non-blocking probes are reported but do not gate completion.
    rep.add("g", "advisory", False, blocking=False)
    assert len(rep.outstanding) == 1
    assert rep.blocking_total == 2


def test_the_test_interpreter_really_can_import_the_test_dependencies():
    """The first version of the gate used the system python3 and reported a
    product failure that was a harness failure. This pins the discovery."""
    import subprocess

    exe = audit.find_test_python()
    out = subprocess.run(
        [exe, "-c", "import anthropic, fastapi, pytest, prometheus_client"],
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, f"{exe} cannot import the test extra:\n{out.stderr}"


def test_the_audit_detects_a_planted_failure():
    """A gate that cannot fail is decoration. Plant one and prove it is seen."""
    rep = audit.Report()
    rep.add("t", "this check is deliberately false", False, "planted")
    assert rep.outstanding, "the audit failed to notice a planted failure"
