from __future__ import annotations

import difflib
import re
from typing import Dict, List, Any


_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _looks_like_diff(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("@@") and " @@" in stripped:
            return True
        if len(line) >= 1 and line[0] in "+-" and not stripped.startswith(("--- ", "+++ ")):
            return True
    return False


def _extract_resulting_code(patch: str) -> str:
    """Reconstruct the post-patch source from a unified diff.

    Keeps context (`` ``) and added (``+``) lines, drops removed (``-``)
    lines and hunk headers. Free text (non-diff) is returned verbatim.
    """
    if not _looks_like_diff(patch):
        return patch
    out: List[str] = []
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            out.append(line[1:])
        elif line.startswith(" "):
            out.append(line[1:])
        # skip removed lines and headers
    return "\n".join(out)


def _tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall(text)


def _norm_text(text: str) -> str:
    """Format-normalize text: collapse whitespace and drop spacing around
    punctuation so reformatting alone does not change the comparison."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*([()\[\]{}:,;])\s*", r"\1", text)
    return text


def _code_similarity(a: str, b: str) -> float:
    """Identifier-aware similarity: token Dice + normalized char-sequence ratio.

    Whitespace/format-immune: identifiers are spacing-independent and the
    sequence term is computed on whitespace/punctuation-normalized text.
    """
    ta, tb = _tokens(a), _tokens(b)
    sa, sb = set(ta), set(tb)
    if not sa and not sb:
        return 1.0
    inter = len(sa & sb)
    dice = (2 * inter / (len(sa) + len(sb))) if (sa or sb) else 1.0
    seq = difflib.SequenceMatcher(None, _norm_text(a), _norm_text(b)).ratio()
    return 0.5 * dice + 0.5 * seq


def semantic_similarity(patch1: str, patch2: str) -> float:
    """Similarity that ignores whitespace/formatting and pure removals.

    For unified diffs this compares the *resulting* code semantically (with an
    identifier Dice term). For plain text it degrades gracefully to a
    whitespace-normalized character/sequence ratio so callers that don't pass
    real diffs still get a sane number.
    """
    if not patch1 and not patch2:
        return 1.0
    if _looks_like_diff(patch1) or _looks_like_diff(patch2):
        return _code_similarity(_extract_resulting_code(patch1), _extract_resulting_code(patch2))
    return difflib.SequenceMatcher(None, _norm_text(patch1), _norm_text(patch2)).ratio()


def compute_similarity(patch1: str, patch2: str) -> float:
    """Public similarity entry point (semantic; see :func:`semantic_similarity`)."""
    return semantic_similarity(patch1, patch2)


def compare_patches(patches: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Compares patches from multiple runners.
    Expects patches to be a list of dicts, where each dict maps filename -> patch string.
    Returns a per-file convergence report using semantic similarity.
    """
    if not patches:
        return {}

    all_files = set()
    for p in patches:
        all_files.update(p.keys())

    results = {}
    for filename in all_files:
        file_patches = [p.get(filename, "") for p in patches]

        similarities = []
        for i in range(len(file_patches)):
            for j in range(i + 1, len(file_patches)):
                sim = compute_similarity(file_patches[i], file_patches[j])
                similarities.append(sim)

        avg_sim = sum(similarities) / len(similarities) if similarities else 1.0

        if avg_sim == 1.0:
            status = "converged"
        elif avg_sim > 0.8:
            status = "partial"
        else:
            status = "diverged"

        results[filename] = {
            "average_similarity": avg_sim,
            "semantic_similarity": avg_sim,
            "status": status,
            "patches": file_patches,
        }

    return results
