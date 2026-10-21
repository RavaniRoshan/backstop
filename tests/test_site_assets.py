"""The marketing site's own assets: the brand marks it draws.

The site fetches nothing at runtime, so every mark it draws has to be in the
repository. A diagram that references a mark nobody committed renders a hole.
"""
from __future__ import annotations

import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"
LOGOS = SITE / "assets" / "logos"
PAGES = SITE / "pages"
COMPONENTS = SITE / "components"


def test_every_referenced_logo_is_committed():
    referenced: set[str] = set()
    for page in list(PAGES.rglob("*.astro")) + list(COMPONENTS.rglob("*.astro")):
        text = page.read_text(encoding="utf-8")
        referenced.update(re.findall(r'logo="([a-z0-9-]+)"', text))
    missing = sorted(slug for slug in referenced if not (LOGOS / f"{slug}.svg").exists())
    assert not missing, f"the site draws marks that are not in the repository: {missing}"


def test_every_committed_logo_is_a_real_svg():
    marks = sorted(LOGOS.glob("*.svg"))
    assert marks, "the site has no brand marks committed"
    for svg in marks:
        text = svg.read_text(encoding="utf-8")
        assert text.lstrip().startswith("<svg"), f"{svg.name} is not an SVG"
        assert "viewBox" in text, f"{svg.name} has no viewBox"
        assert len(text) > 120, f"{svg.name} is suspiciously small"
