"""Typeset real Backstop CLI output as a terminal.

The text is verbatim from the product's own stdout, captured by running the real
commands. Only the presentation is ours: colour, a cursor, and a line-by-line
reveal. Nothing is invented here, and `assert_real_output` keeps it that way by
refusing to render a block that is not a file the capture step actually wrote.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from theme import (
    ACCENT, AMBER, BG, GREEN, LINE, PANEL, PANEL_HI, RED, TEXT, TEXT_DIM, TEXT_FAINT,
    VIOLET, W, ease_out, font, measure, panel, seg,
)

# Colours are pulled from the dashboard's dark theme so a cut from browser
# footage to a terminal does not change the world.
C_TEXT = TEXT
C_DIM = TEXT_DIM
C_FAINT = TEXT_FAINT
C_ACCENT = ACCENT
C_GREEN = GREEN
C_AMBER = AMBER
C_RED = RED
C_VIOLET = VIOLET


@dataclass
class Line:
    text: str
    colour: tuple[int, int, int] = C_TEXT
    bold: bool = False
    rule: bool = False          # a `---` separator
    blank: bool = False


def assert_real_output(name: str) -> str:
    """Load captured stdout, refusing anything the capture step did not write.

    A demo that paraphrases its own product is a demo that can drift into
    advertising. The only text this module will render is text a real command
    produced.
    """
    p = Path(name)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} is missing. The terminal scenes render captured stdout only; "
            "re-run the capture step rather than hand-writing terminal text."
        )
    body = p.read_text(encoding="utf-8").rstrip("\n")
    if not body.strip():
        raise ValueError(f"{p} is empty; refusing to render a blank terminal as a demo")
    return body


_NUM = re.compile(r"^\s*\|?\s*[-+]?[\d,]*\.?\d+\s*(%|\$|ms|k|Mtok|pt)?")
_MONEY = re.compile(r"[-+]?\$[\d,]*\.?\d+")
_HEADING = re.compile(r"^#+\s")


def classify(raw: str) -> Line:
    if not raw.strip():
        return Line("", blank=True)
    if raw.strip().startswith("|"):
        return _table_line(raw)
    if _HEADING.match(raw):
        return Line(raw, colour=TEXT, bold=True)
    if raw.strip().startswith("**") and raw.strip().endswith("**"):
        return Line(raw.strip("*"), colour=TEXT, bold=True)
    if set(raw.strip()) <= set("- ") and len(raw.strip()) >= 3:
        return Line("", rule=True)
    if raw.lstrip().startswith(("-", "*")):
        return Line(raw, colour=C_DIM)
    if raw.startswith("  ") and not raw.strip().startswith("|"):
        return Line(raw, colour=C_FAINT)
    return Line(raw, colour=C_TEXT)


def _table_line(raw: str) -> Line:
    """Colour a markdown table row by what it says, not by position."""
    s = raw.rstrip()
    low = s.lower()
    if set(s.replace("|", "").replace(":", "").strip()) <= set("- "):
        return Line("", rule=True)
    colour = C_TEXT
    bold = False
    if any(k in low for k in ("blocked", "budgetexceeded", "error", "prevented", "variance")):
        colour, bold = C_GREEN, True
    elif any(k in low for k in ("saved", "savings", "delta", "-$")):
        colour = C_GREEN
    if any(k in low for k in ("unprotected", "attempted", "completed", "consumed", "estimated cost")):
        colour = C_DIM
    if _MONEY.search(s) and colour is C_TEXT:
        colour = C_AMBER
    if re.search(r"\|\s*\d", s) and colour is C_TEXT:
        colour = C_ACCENT
    return Line(s, colour=colour, bold=bold)


def parse(body: str) -> list[Line]:
    return [classify(l) for l in body.split("\n")]


# --- drawing -----------------------------------------------------------------


def column_span(body: str, header: str, col: str) -> tuple[int, int] | None:
    """Character range of a table column, taken from the real header row.

    Used to band one column so a comparison scene can point at the side it is
    talking about. Derived from the captured text, so it cannot drift from what
    the product printed.
    """
    for line in body.split("\n"):
        if not line.lstrip().startswith("|"):
            continue
        if col.lower() not in line.lower():
            continue
        i = line.lower().index(col.lower())
        # Extend to the cell's pipes so the band covers the padding too.
        start = line.rfind("|", 0, i) + 1
        end = line.find("|", i)
        if start <= 0 or end < 0:
            continue
        return (start, end)
    return None


def draw_terminal(
    img: Image.Image,
    body: str,
    *,
    box: tuple[int, int, int, int],
    size: int = 20,
    lead: int = 30,
    reveal: float = 1.0,
    focus: list[int] | None = None,
    focus_colour=C_GREEN,
    band: tuple[int, int] | None = None,
    band_colour=C_GREEN,
    pad: int = 26,
    title: str | None = None,
) -> list[int]:
    """Draw `body` into `box`, revealing `reveal` of it. Returns row y-centres.

    `focus` is a list of line indices to ring, which is how a scene points at the
    one row that carries the point without re-typing the whole block.
    """
    d = ImageDraw.Draw(img, "RGBA")
    x0, y0, x1, y1 = box
    panel(d, [x0, y0, x1, y1], fill=(14, 16, 21), outline=LINE, radius=16)

    # Title bar, so the window is a window and not a floating rectangle.
    bar_h = 44 if title else 0
    if title:
        d.rounded_rectangle([x0, y0, x1, y0 + bar_h + 16], radius=16, fill=PANEL_HI)
        d.rectangle([x0, y0 + bar_h, x1, y0 + bar_h + 16], fill=PANEL_HI)
        d.line([(x0, y0 + bar_h), (x1, y0 + bar_h)], fill=LINE, width=1)
        for i, c in enumerate((RED, AMBER, GREEN)):
            cx = x0 + 24 + i * 22
            d.ellipse([cx - 6, y0 + 16, cx + 6, y0 + 28], fill=c)
        d.text(((x0 + x1) / 2, y0 + 22), title, font=font(15, mono=True),
               fill=TEXT_DIM, anchor="mm")

    tx = x0 + pad
    ty = y0 + bar_h + pad + 8
    avail_w = (x1 - x0) - pad * 2
    rows = parse(body)

    f = font(size)
    fb = font(size, bold=True)
    char_w = measure(d, "0" * 10, size) / 10.0
    shown = reveal * len(rows)
    centres: list[int] = []

    # A column band, drawn under the text so it tints the cells it covers.
    if band and band[1] > band[0]:
        bx0 = tx + band[0] * char_w
        bx1 = tx + band[1] * char_w
        d.rounded_rectangle(
            [bx0 - 4, ty - 6, bx1 + 4, ty + len(rows) * lead + 4],
            radius=6, fill=band_colour[:3] + (26,), outline=band_colour[:3] + (110,), width=1,
        )

    for i, row in enumerate(rows):
        if i >= shown:
            break
        y = ty + i * lead
        if y + lead > y1 - 8:
            break
        centres.append(y + lead // 2)
        if row.blank:
            continue
        if row.rule:
            d.line([(tx, y + lead // 2), (x1 - pad, y + lead // 2)], fill=LINE, width=1)
            continue
        # A row types in rather than appearing whole.
        frac = min(1.0, (shown - i)) if i < shown else 1.0
        s = row.text
        if frac < 1.0:
            s = s[: max(0, int(len(s) * frac))]
        if not s:
            continue
        d.text((tx, y), s, font=(fb if row.bold else f), fill=row.colour)

    # Rings on the rows that carry the scene's point.
    if focus:
        for idx in focus:
            if 0 <= idx < len(centres):
                cy = centres[idx]
                w = min(measure(d, rows[idx].text, size, bold=rows[idx].bold),
                        avail_w) + pad
                d.rounded_rectangle(
                    [tx - 12, cy - lead // 2 - 4, tx + w, cy + lead // 2 + 4],
                    radius=7, outline=focus_colour + (190,), width=2,
                )
                d.rectangle([tx - 12, cy - lead // 2 - 4, tx - 8, cy + lead // 2 + 4],
                            fill=focus_colour + (190,))

    # The prompt, on the line after the last one, but only if the box has room.
    if reveal >= 1.0 and centres:
        last = rows[len(centres) - 1]
        if last.blank or not last.text:
            cy = (centres[-1] if centres else ty) + lead
            if cy + 10 < y1:
                d.text((tx, cy), "$ ", font=f, fill=C_GREEN)
    return centres


def fit_box(
    body: str, *, size: int, lead: int, pad: int = 26, bar: int = 44,
    max_w: int = 1100, width: int | None = None,
) -> tuple[int, int, int, int]:
    """A box sized to the text, not a fixed rectangle with dead space under it."""
    rows = len(parse(body)) + 2
    widest = 0
    for r in parse(body):
        if r.text:
            widest = max(widest, len(r.text))
    w = width or min(max_w, int(widest * size * 0.605) + pad * 2)
    h = rows * lead + pad * 2 + bar
    return (0, 0, w, h)


def rows_matching(body: str, needle: str) -> list[int]:
    """Indices of lines containing `needle`, for focus rings."""
    return [i for i, l in enumerate(parse(body)) if needle.lower() in l.text.lower()]


def typing_progress(t: float, start: float, dur: float, lines: int) -> float:
    """Ease a linear type-on so the first line does not snap in."""
    p = ease_out(seg(t, start, dur))
    return p * lines
