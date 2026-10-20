"""The product's own documentation must be true.

Backstop is sold on the strength of what it does, and a large part of what it
does is making claims an operator can check: a budget is a hard ceiling, an
audit log is tamper-evident, the install is the version on PyPI. When a
document says something the code no longer does, the document is the part of
the product that is wrong — and the damage is not the sentence, it is the
trust.

Every check here corresponds to a claim that was false at the time this file
was written:

* the published version was 0.6.0 in five documents while 0.7.0 had shipped;
* the README said the TypeScript package "is not in CI" while CI ran it;
* ``llms.txt`` — the file an agent installer reads first — listed eight of
  twelve commands, omitting the entire 0.7.0 money surface;
* ``from backstop.ledger import *`` raised ``AttributeError``;
* ``backstop --version`` exited 2 with a usage error.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from backstop import __version__

REPO = pathlib.Path(__file__).resolve().parent.parent

#: The documents that state which version is published. The changelog is not
#: among them: it is a history, and a history is *supposed* to name old
#: versions.
VERSION_CLAIMING_DOCS = (
    "README.md",
    "llms.txt",
    "docs/install.md",
    "docs/quickstart.md",
    "docs/compatibility.md",
)

#: A released version, as it appears in a "pip install backstop-ai==X.Y.Z" line.
_PINNED = re.compile(r"backstop[-_]ai(?:\[[a-z,]+\])?==(\d+\.\d+\.\d+)")
#: A GitHub release tag, as it appears in "the vX.Y.Z GitHub Release".
_TAG = re.compile(r"\bv(\d+\.\d+\.\d+)\b")


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", VERSION_CLAIMING_DOCS)
def test_no_document_claims_a_version_other_than_the_current_one(rel: str) -> None:
    """A document that tells a user to install a version that is not the release.

    Both the pip pin and the release tag are checked, because a document can
    be half-updated — the install command moved to 0.8.0 while the sentence
    beside it still says "the v0.7.0 GitHub Release".
    """
    text = _read(rel)
    for found in _PINNED.findall(text) + _TAG.findall(text):
        assert found == __version__, (
            f"{rel} names version {found}, but the package is {__version__}. "
            "A document that installs a version that is not the release sends "
            "the reader to a different product than the one they are reading "
            "about."
        )


@pytest.mark.parametrize("rel", VERSION_CLAIMING_DOCS)
def test_every_version_claiming_document_names_the_current_version(rel: str) -> None:
    """Each document that talks about the release must talk about *this* release."""
    assert __version__ in _read(rel), (
        f"{rel} never names the current version {__version__}. It is either "
        "stale or it defers to a link that carries the version."
    )


def test_the_readme_does_not_claim_the_typescript_package_is_outside_ci() -> None:
    """The TypeScript package *is* in CI; saying otherwise is a false claim."""
    readme = _read("README.md")
    assert "not in CI" not in readme
    assert "no CI" not in readme


def test_llms_txt_lists_every_cli_command() -> None:
    """``llms.txt`` is what an agent reads first; it must list the real commands.

    The list is compared against the parser rather than against a second
    hand-maintained copy, so adding a command without adding it here fails
    the build instead of shipping an agent a stale surface.
    """
    from backstop.cli import build_parser

    parser = build_parser()
    actions = [
        action
        for action in parser._actions
        if isinstance(action, type(parser._subparsers._group_actions[0]))
    ]
    commands = set(actions[0].choices) if actions else set()

    llms = _read("llms.txt")
    missing = sorted(command for command in commands if command not in llms)
    assert not missing, (
        f"llms.txt does not mention these commands: {', '.join(missing)}. An "
        "agent that reads llms.txt cannot run a command it was never told "
        "about."
    )


def test_the_star_import_of_the_ledger_package_works() -> None:
    """``from backstop.ledger import *`` must not raise.

    ``__all__`` named a symbol the module did not import, so the star import
    raised ``AttributeError`` — the one import form a user is most likely to
    write, and the one that failed.
    """
    namespace: dict = {}
    exec("from backstop.ledger import *", namespace)  # noqa: S102 - that is the test


def test_the_cli_reports_its_version() -> None:
    """``backstop --version`` must print the version and exit 0.

    It used to exit 2 with a usage error, because the flag did not exist.
    """
    from backstop.cli import main

    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0


def test_every_doc_page_is_linked_from_the_readme() -> None:
    """A doc nobody can find is a doc nobody reads.

    The ``usecases/`` tree, the dashboard page and the Prometheus alert rules
    were all shipped without an inbound link — 1,248 lines of walkthroughs and
    two operational pages that no reader could reach. The README's
    documentation index is now the index, and this keeps it honest.
    """
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    missing = [
        path.name
        for path in sorted((REPO / "docs").glob("*.md"))
        if f"docs/{path.name}" not in readme
    ]
    assert not missing, (
        f"documentation pages with no link from the README: {missing}. A page "
        "nobody can find is a page nobody reads."
    )


def test_no_document_points_at_a_file_that_does_not_exist() -> None:
    """A link to a file that is not there is worse than no link.

    It looks like documentation and sends the reader nowhere.
    """
    import re

    broken: list[str] = []
    pattern = re.compile(r"\[[^\]]+\]\((?!https?://|#)([^)]+)\)")
    for source in sorted((REPO / "docs").glob("*.md")) + [REPO / "README.md"]:
        text = source.read_text(encoding="utf-8")
        for target in pattern.findall(text):
            target = target.split("#", 1)[0]
            if not target:
                continue
            resolved = (source.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{source.relative_to(REPO)} -> {target}")
    assert not broken, "links to files that do not exist:\n" + "\n".join(broken)
