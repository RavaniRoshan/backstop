from __future__ import annotations

import subprocess


def test_install_sh_syntax_valid():
    result = subprocess.run(["bash", "-n", "install.sh"], capture_output=True, text=True)
    assert result.returncode == 0, f"install.sh syntax error: {result.stderr}"


def test_install_sh_has_checksum_block():
    with open("install.sh", "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "BACKSTOP_SHA_URL" in content
    assert "sha256sum" in content or "shasum" in content
    assert "BACKSTOP_SKIP_CHECKSUM" in content


def test_install_sh_has_cosign_step_in_ci():
    with open(".github/workflows/ci.yml", "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "cosign" in content
    assert "slsa-framework" in content or "SLSA" in content
    assert "sbom" in content.lower() or "SBOM" in content


def test_install_sh_version_matches_pyproject():
    with open("install.sh", "r", encoding="utf-8") as fh:
        content = fh.read()
    with open("pyproject.toml", "r", encoding="utf-8") as fh:
        import re

        pyproject = fh.read()
    version_match = re.search(r'version\s*=\s*"([^"]+)"', pyproject)
    assert version_match, "version not found in pyproject.toml"
    pyproject_version = version_match.group(1)
    install_version_match = re.search(r'BACKSTOP_VERSION="([^"]+)"', content)
    assert install_version_match, "BACKSTOP_VERSION not found in install.sh"
    assert install_version_match.group(1) == pyproject_version
