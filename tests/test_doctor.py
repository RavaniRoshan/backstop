"""`backstop doctor` must pass on a base install.

`httpx2` is not a declared dependency: it only arrives transitively with very
new OpenAI/Anthropic SDKs. Its absence is a fact about the environment, not a
broken install, so doctor must report it and still exit 0.

A note on how the missing-`httpx2` case is exercised, because the obvious
approach is wrong. An earlier version of this file reloaded
`backstop._httpcompat` with `sys.modules["httpx2"] = None` and asserted in a
docstring that only `cli` would notice. That is false: the Anthropic wrap path
resolves the HTTP family through the same module, so on a machine with an
httpx2-based Anthropic SDK the reload broke a working install. Worse, the state
it simulated cannot exist in reality - an SDK that requires `httpx2` cannot be
installed without `httpx2`. So it tested an impossible world and passed locally
only because the local Anthropic happened to be httpx-based.

The subprocess test below is the honest version: it blocks `httpx2` at import
time in a child interpreter, so nothing is shared with this process, and it only
asserts what must hold in that state - doctor reports the absence, does not
crash, and does not blame the user.
"""
from __future__ import annotations

import gc
import subprocess
import sys
import textwrap

import pytest

from backstop.cli import main
from backstop.telemetry import get_registry

# Blocks `import httpx2` for the whole child interpreter, before backstop loads.
_BLOCK_HTTPX2 = textwrap.dedent(
    """
    import sys

    class _Block:
        def find_module(self, name, path=None):
            return self if name == "httpx2" else None

        def find_spec(self, name, path=None, target=None):
            if name == "httpx2":
                raise ImportError("httpx2 blocked for this test")
            return None

        def load_module(self, name):
            raise ImportError("httpx2 blocked for this test")

    sys.meta_path.insert(0, _Block())
    sys.modules.pop("httpx2", None)
    """
)


@pytest.fixture(autouse=True)
def clean_registry():
    get_registry().reset()
    gc.collect()
    yield
    get_registry().reset()
    gc.collect()


def test_doctor_exits_zero_in_this_environment(capsys):
    """The contract that actually matters, with no simulation at all.

    Whatever SDKs are installed, doctor must exit 0 when they wrap. This is the
    test that was missing, and its absence is why a broken test could sit green
    locally and red on CI.
    """
    code = main(["doctor"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "Doctor check failed" not in out
    assert "environment looks healthy" in out


def test_doctor_reports_httpx2_when_present(capsys):
    """Guards the present-`httpx2` branch so it cannot be silently dropped."""
    import backstop._httpcompat as httpcompat

    if httpcompat.HTTPX2 is None:
        pytest.skip("httpx2 not installed in this environment")
    main(["doctor"])
    out = capsys.readouterr().out
    assert "httpx2 MockTransport works" in out
    assert "compat_for detected httpx2 family: httpx2" in out


def test_doctor_survives_a_missing_httpx2():
    """Run doctor in a child interpreter where `httpx2` cannot be imported.

    Asserts only what holds in that state: the absence is reported, the run
    completes, and nothing blames the user. It deliberately does NOT assert that
    every provider wraps - if an installed SDK needs `httpx2`, that provider
    cannot wrap here, and pretending otherwise is what broke this test before.
    """
    code = (
        _BLOCK_HTTPX2
        + textwrap.dedent(
            """
            import sys
            from backstop.cli import main
            sys.exit(main(["doctor"]))
            """
        )
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = r.stdout + r.stderr
    assert "Traceback" not in out, out
    assert "not allowed" not in out, out
    assert "httpx2" in out, out
    # doctor must not report a usage/permission problem for a missing optional
    # dependency; an unsupported provider is reported as such, separately
    assert "environment looks healthy" in out or "not supported" in out, out
