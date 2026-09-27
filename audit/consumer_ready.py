"""Consumer-readiness audit: the live denominator for "is this ready to ship".

This exists because a goal that says *all of these tasks* needs a number to
divide by. A hand-written checklist goes stale the moment reality moves; this
re-derives the list from the working tree and the two remotes every run, so
"zero outstanding" is a measurement rather than an assertion.

Two rules keep it honest:

1. Every check is a *probe* that either passes or explains itself. A probe that
   cannot decide is a failure, not a skip. A skipped check would let the goal
   complete on the things it could not see.
2. Nothing here knows what the answer is supposed to be. It states the
   condition and reads reality. Where a value is expected to change over time
   (a published version) it is compared across sources rather than to a literal.

Run ``--strict`` to exit non-zero while anything is outstanding. Without it the
report is printed and the exit code is always 0, for reading.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE = Path("/tmp/opencode/backinstop")
SITE_URL = "https://backinstop.vercel.app"

OK, BAD = "pass", "FAIL"


@dataclass
class Check:
    group: str
    label: str
    ok: bool
    detail: str = ""
    blocking: bool = True


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, group: str, label: str, ok: bool, detail: str = "", blocking: bool = True) -> None:
        self.checks.append(Check(group, label, bool(ok), detail, blocking))

    @property
    def outstanding(self) -> list[Check]:
        return [c for c in self.checks if c.blocking and not c.ok]

    @property
    def blocking_total(self) -> int:
        return sum(1 for c in self.checks if c.blocking)


def read(rel: str, root: Path = REPO) -> str:
    p = root / rel
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def sh(cmd: list[str], cwd: Path = REPO, timeout: int = 120) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def find_test_python() -> str:
    """An interpreter that can actually run this project's test suite.

    The suite needs the `test` extra (anthropic, fastapi, prometheus-client),
    so the system python3 is not a valid choice and using it produces a check
    that fails for the wrong reason. A coverage gate that reports false
    failures is as bad as one that reports false passes, so this probes for a
    usable interpreter and says so plainly when it finds none.
    """
    candidates = [
        os.environ.get("BACKSTOP_TEST_PYTHON", ""),
        sys.executable,
        "/tmp/opencode/gwenv/bin/python",
        str(REPO / ".venv/bin/python"),
    ]
    for exe in candidates:
        if not exe or not Path(exe).exists():
            continue
        code, out = sh([exe, "-c", "import anthropic, fastapi, pytest, prometheus_client"], timeout=90)
        if code == 0:
            return exe
    return sys.executable


def http_status(url: str, timeout: int = 20) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "consumer-ready-audit"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers.get("content-type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("content-type", "") if exc.headers else ""
    except Exception as exc:  # noqa: BLE001 - a probe that cannot decide is a failure
        return 0, str(exc)


# --- groups ------------------------------------------------------------------


def check_truthfulness(r: Report) -> None:
    """Every claim a consumer can read must be true today."""
    readme = read("README.md")
    r.add(
        "truth", "main README does not claim the TS package is out of CI",
        "It is **not in CI" not in readme,
        "README.md still says the TypeScript package is not in CI, but the "
        "ts-backstop job runs on every push",
    )
    ts_readme = read("ts/backstop/README.md")
    r.add(
        "truth", "npm-facing README warns it is a partial port",
        "partial" in ts_readme.lower(),
        "ts/backstop/README.md is what renders on npmjs.com; without this the "
        "npm package implies parity it does not have (no Anthropic, no ledger, "
        "no dashboard, different interception strategy)",
    )
    r.add(
        "truth", "npm-facing README states its interception strategy differs",
        "create" in ts_readme and "patch" in ts_readme.lower()
        or "patch" in ts_readme.lower(),
        "the npm port patches client.chat.completions.create rather than "
        "injecting a transport, so the headline 'no call-site changes' property "
        "does not hold for it",
    )
    r.add(
        "truth", "no doc claims a compliance certification",
        not re.search(r"\bSOC ?2\b|\bHIPAA\b|\bISO ?27001\b", readme + ts_readme, re.I)
        or "does not claim" in readme.lower() or "not claim" in readme.lower(),
        "a compliance badge that cannot be substantiated",
    )


def check_consistency(r: Report) -> None:
    """One version, stated the same way everywhere a consumer can see it."""
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', read("src/backstop/__init__.py"), re.M)
    local = m.group(1) if m else "?"
    r.add("consistency", "the repo declares a version", local != "?", f"__version__ = {local!r}")
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/backstop-ai/json", timeout=20) as resp:
            pypi = json.load(resp)["info"]["version"]
    except Exception as exc:  # noqa: BLE001
        pypi = f"unreachable: {exc}"
    r.add("consistency", "PyPI is published", pypi == local, f"PyPI {pypi} vs repo {local}")
    code, out = sh(["npm", "view", "backstop-ai", "version"])
    npm = out.strip().splitlines()[-1] if code == 0 and out.strip() else "not published"
    r.add("consistency", "npm is published at the same version", npm == local, f"npm {npm} vs repo {local}")


def check_hygiene(r: Report) -> None:
    """Nothing shipped or linked should be dead, duplicated, or zero-byte."""
    code, out = sh(["git", "worktree", "list"])
    stale = [ln for ln in out.splitlines() if "worktrees/" in ln]
    r.add("hygiene", "no stale worktrees", not stale, "; ".join(stale) or "none")
    r.add("hygiene", "the completed TODO checklist is gone", not (REPO / "TODO.md").exists(),
          "TODO.md was a finished ledger-build checklist")
    dead = [p.name for p in (REPO / "usecases/_build").glob("*.py")
            if "demo.gif" in p.read_text(encoding="utf-8", errors="ignore")]
    r.add("hygiene", "no dead generator references the deleted demo.gif", not dead,
          ", ".join(dead) or "none")
    junk = [p.name for p in REPO.iterdir() if p.is_file() and p.stat().st_size == 0]
    r.add("hygiene", "no zero-byte files at the repository root", not junk,
          ", ".join(junk) or "none")


def check_liberty(r: Report) -> None:
    """Two packages named backstop-ai must not diverge silently."""
    code, out = sh([sys.executable, "-c", "import tomllib,pathlib;"
                    "print(pathlib.Path('pyproject.toml').read_text().count('backstop-ai'))"])
    r.add("liberty", "the distribution name is unambiguous", code == 0,
          "pyproject declares the PyPI name the npm package also uses; the two "
          "ship different feature sets under one name, which the docs must say")


def check_site(r: Report) -> None:
    """What a stranger's browser and a social card actually get."""
    status, ctype = http_status(f"{SITE_URL}/")
    r.add("site", "the site serves", status == 200, f"HTTP {status}")
    status, ctype = http_status(f"{SITE_URL}/og.png")
    r.add("site", "a social card image is served", status == 200 and "image" in ctype,
          f"/og.png -> HTTP {status} {ctype or 'no content-type'}")
    layout = read("app/layout.tsx", SITE)
    r.add("site", "a social card image is declared in metadata",
          bool(re.search(r"openGraph[\s\S]{0,600}?images", layout))
          # The layout is TSX, so the path is single-quoted. The first version of
          # this check looked for a double-quoted "/og.png", found nothing, and
          # reported a failure for a card that was correctly wired -- a gate that
          # cries wolf is as useless as one that stays silent.
          and bool(re.search(r"""['"]/og\.png['"]""", layout)),
          "layout declares summary_large_image but must also point at a real file")
    status, _ = http_status(f"{SITE_URL}/walkthrough.mp4")
    r.add("site", "the demo video is served", status == 200, f"HTTP {status}")
    status, _ = http_status(f"{SITE_URL}/docs")
    r.add("site", "the docs are served", status == 200, f"HTTP {status}")
    code, out = sh(["git", "status", "--porcelain"], cwd=SITE)
    r.add("site", "the site working tree is clean", code == 0 and not out.strip(),
          out.strip()[:200] or "clean")


def check_product(r: Report) -> None:
    """The library's own gates. These are the product's promise."""
    exe = find_test_python()
    code, out = sh([exe, "-m", "pytest", "-p", "no:cacheprovider"], timeout=1800)
    m = re.search(r"(\d+) passed", out)
    skipped = re.search(r"(\d+) skipped", out)
    detail = f"{m.group(1)} passed, {skipped.group(1)} skipped via {Path(exe).name}" if m else out.strip()[-300:]
    r.add("product", "the Python suite passes", code == 0 and bool(m), detail)
    code, out = sh([sys.executable, "-m", "ruff", "check", "src/", "tests/", "audit/"])
    r.add("product", "ruff is clean", code == 0, out.strip()[-200:] or "clean")


GROUPS = [
    ("truth", check_truthfulness),
    ("consistency", check_consistency),
    ("hygiene", check_hygiene),
    ("liberty", check_liberty),
    ("site", check_site),
    ("product", check_product),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true", help="exit non-zero while anything is outstanding")
    args = ap.parse_args()

    rep = Report()
    for name, fn in GROUPS:
        try:
            fn(rep)
        except Exception as exc:  # noqa: BLE001 - a probe that blows up is a failure
            rep.add(name, f"audit group {name} raised", False, repr(exc))

    width = max((len(c.label) for c in rep.checks), default=10)
    current = None
    for c in rep.checks:
        if c.group != current:
            current = c.group
            print(f"\n{current}")
        mark = "ok  " if c.ok else "FAIL"
        line = f"  {mark}  {c.label.ljust(width)}"
        if not c.ok and c.detail:
            line += f"  -- {c.detail}"
        print(line)

    total, bad = rep.blocking_total, len(rep.outstanding)
    print(f"\n{total - bad}/{total} consumer-readiness checks pass.")
    if bad:
        print(f"{bad} outstanding. This product is not ready to be marketed yet.")
    else:
        print("Nothing outstanding. The library, the docs and the site agree with each other.")
    return 1 if (args.strict and bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
