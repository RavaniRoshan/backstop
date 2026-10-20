from __future__ import annotations

import subprocess
from pathlib import Path

import backstop

repo_root = next(
    parent
    for parent in Path(__file__).resolve().parents
    if parent.joinpath("pyproject.toml").is_file() or parent.joinpath(".git").exists()
)


def test_install_sh_syntax_valid():
    result = subprocess.run(
        ["bash", "-n", repo_root.joinpath("install.sh")], capture_output=True, text=True
    )
    assert result.returncode == 0, f"install.sh syntax error: {result.stderr}"


def test_install_sh_has_checksum_block():
    with open(repo_root.joinpath("install.sh"), "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "BACKSTOP_SHA_URL" in content
    assert "sha256sum" in content or "shasum" in content
    assert "BACKSTOP_SKIP_CHECKSUM" in content


def test_install_sh_has_cosign_step_in_ci():
    with open(repo_root.joinpath(".github/workflows/ci.yml"), "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "cosign" in content
    assert "slsa-framework" in content or "SLSA" in content
    assert "sbom" in content.lower() or "SBOM" in content


def test_install_sh_version_matches_the_package():
    """The installer pins the same version the package reports.

    ``pyproject.toml`` does not carry a version of its own any more — the
    build reads it out of ``src/backstop/__init__.py`` — so the comparison is
    against the package's own version rather than against a second copy of the
    number in the project table.
    """
    with open(repo_root.joinpath("install.sh"), "r", encoding="utf-8") as fh:
        content = fh.read()
    import re

    install_version_match = re.search(r'BACKSTOP_VERSION="([^"]+)"', content)
    assert install_version_match, "BACKSTOP_VERSION not found in install.sh"
    assert install_version_match.group(1) == backstop.__version__
