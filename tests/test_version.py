"""The version lives in one place, and the other places are checked against it.

``src/backstop/__init__.py`` is the single source. ``pyproject.toml`` reads it
at build time through hatchling's dynamic version, so a wheel cannot report a
different number from the package it was built from. Everything *else* that
carries a version — the npm package, the npm lockfile, the shell installer, the
``wedge`` package that ships in the same wheel — is a copy, and a copy drifts.

Both kinds of drift have happened. The npm package sat at 0.5.0 in its own
lockfile through a 0.6.0 release. Five documents told a user to install 0.6.0
after 0.7.0 had shipped. ``src/wedge/__init__.py`` still said 0.6.0 while it
shipped inside the 0.7.0 wheel, and ``tests/test_version.py`` did not look at
it.

So this file asserts two different things, and they are not the same thing:

* the **source** of truth is where it says it is, and the build reads it from
  there;
* every **copy** of the version agrees with it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import backstop

ROOT = Path(__file__).resolve().parent.parent


def _pyproject_text() -> str:
    return (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def _installer_version() -> str:
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    m = re.search(r'^BACKSTOP_VERSION="([^"]+)"', text, re.M)
    assert m, "install.sh has no BACKSTOP_VERSION"
    return m.group(1)


def _npm_version() -> str:
    data = json.loads((ROOT / "ts" / "backstop" / "package.json").read_text(encoding="utf-8"))
    return str(data["version"])


def _npm_lockfile_version() -> str:
    data = json.loads(
        (ROOT / "ts" / "backstop" / "package-lock.json").read_text(encoding="utf-8")
    )
    return str(data["version"])


def _wedge_version() -> str:
    text = (ROOT / "src" / "wedge" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    assert m, "src/wedge/__init__.py has no __version__"
    return m.group(1)


def test_the_build_reads_the_version_from_the_single_source() -> None:
    """``pyproject.toml`` must not carry a second copy of the version.

    A static ``version = "..."`` in the project table is a second place, and
    two places is how a wheel ends up reporting a different number from the
    package it was built from. The build reads the version out of
    ``src/backstop/__init__.py`` instead.
    """
    text = _pyproject_text()
    assert 'dynamic = ["version"]' in text, (
        "pyproject.toml does not declare the version dynamic, so it carries a "
        "second copy of the version string"
    )
    assert '[tool.hatch.version]' in text
    assert 'path = "src/backstop/__init__.py"' in text


def test_the_npm_package_is_the_same_version_as_the_python_one() -> None:
    assert _npm_version() == backstop.__version__


def test_the_npm_lockfile_is_the_same_version_as_the_package_json() -> None:
    """The lockfile names the package's own version, and it drifts separately."""
    assert _npm_lockfile_version() == _npm_version()


def test_the_installer_pins_the_same_version() -> None:
    assert _installer_version() == backstop.__version__


def test_the_wedge_package_is_the_same_version_as_the_python_one() -> None:
    """``wedge`` ships in the same wheel, so it cannot be a different version."""
    assert _wedge_version() == backstop.__version__


def test_the_version_is_a_plain_three_part_number() -> None:
    """A dirty version silently becomes part of the published filename."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", backstop.__version__), backstop.__version__


def test_the_changelog_has_a_section_for_the_current_version() -> None:
    """A release with no CHANGELOG section is a release nobody can read later."""
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = backstop.__version__
    # Released sections are headed `## 0.6.0` or `## v0.5.0 — ...`, and the
    # pending one is `## [Unreleased]`, so accept either spelling of the number.
    assert re.search(rf"^##\s+\[?v?{re.escape(version)}\]?", changelog, re.M), (
        f"CHANGELOG.md has no section for {version}"
    )


@pytest.mark.parametrize("rel", ["CHANGELOG.md", "README.md"])
def test_the_sdist_will_contain_this_file(rel: str) -> None:
    """These are the files a reader needs and a build backend will not add."""
    assert (ROOT / rel).exists(), f"{rel} is missing from the repository root"


def test_the_licence_text_is_present_not_just_declared() -> None:
    """`license = { text = "MIT" }` is a claim; MIT also requires the text.

    The repository carries it as LICENSE.txt, which is conventional, so this
    accepts either spelling rather than renaming a file to satisfy a test.
    """
    found = [p for p in ROOT.glob("LICENSE*") if p.is_file()]
    assert found, "no LICENSE file, so the declared MIT licence ships no text"
