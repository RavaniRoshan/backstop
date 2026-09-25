"""`backstop doctor` must pass on a base install.

`httpx2` is not a declared dependency: it only arrives transitively with very
new OpenAI/Anthropic SDKs. Its absence is a fact about the environment, not a
broken install, so doctor must report it and still exit 0.
"""
from __future__ import annotations

import gc
import importlib
import sys

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


@pytest.fixture
def without_httpx2(monkeypatch):
    """Rebuild ``_httpcompat`` as if ``httpx2`` were not installed.

    ``None`` in ``sys.modules`` makes ``import httpx2`` raise ``ImportError``,
    which is the real import-time failure. Every other module in the package
    binds its ``_httpcompat`` names with ``from ... import``, so only ``cli``'s
    doctor, which reads the module attributes, sees the rebuilt values.
    """
    import backstop._httpcompat as httpcompat

    monkeypatch.setitem(sys.modules, "httpx2", None)
    importlib.reload(httpcompat)
    assert httpcompat.HTTPX2 is None, "fixture failed to simulate an httpx2-free install"
    yield httpcompat
    monkeypatch.undo()
    importlib.reload(httpcompat)


def test_doctor_exits_zero_without_httpx2(without_httpx2, capsys):
    code = main(["doctor"])
    assert code == 0, capsys.readouterr().out


def test_doctor_reports_httpx_family_when_httpx2_is_absent(without_httpx2, capsys):
    main(["doctor"])
    out = capsys.readouterr().out
    assert "compat_for detected httpx family: httpx" in out
    assert "httpx2 not installed" in out
    assert "not allowed" not in out  # nothing here is a usage error


def test_doctor_still_reports_both_sdk_wraps_without_httpx2(without_httpx2, capsys):
    main(["doctor"])
    out = capsys.readouterr().out
    assert "- [ok] OpenAI client wrapped successfully" in out
    assert "- [ok] Anthropic client wrapped successfully" in out
    assert "- openai: version=" in out
    assert "- anthropic: version=" in out
    assert "environment looks healthy" in out


def test_doctor_httpx2_branch_is_not_silently_skipped(capsys):
    """Without the fixture the doctor must still reach the httpx2 branch.

    Guards the fix: if the branch were dropped, the absent-httpx2 test above
    would still pass while the present-httpx2 path lost its coverage.
    """
    import backstop._httpcompat as httpcompat

    if httpcompat.HTTPX2 is None:
        pytest.skip("httpx2 not installed in this environment")
    main(["doctor"])
    out = capsys.readouterr().out
    assert "httpx2 MockTransport works" in out
    assert "compat_for detected httpx2 family: httpx2" in out
