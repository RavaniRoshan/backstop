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
import tomllib

import backstop

ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


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
