"""Reference-fidelity demo.gif compositor.

Reproduces the frame/timing/geometry contract measured from the reference
`demo.gif` in the demo-gif skill:

  * 1552x992 canvas, design coordinates are already @2x
  * 414 full-canvas composite frames, disposal=1
  * delay map: 100ms base, 400ms at frames 2 and 13, 200ms at 74/189/195/252
  * total 42.4s, GIF89a, 256-colour global palette, NO netscape loop extension
  * rounded macOS window (light chrome + teal app body) over a blurred wallpaper
  * discrete whole-row streaming + instantaneous whole-row scroll jumps
  * transient dark pill overlays, 1-2 frames each
  * static block cursor, no typing animation, no fades, no easing

A "brief" is a plain dict (see `brief.py` for the schema helpers). This module
only knows how to draw one; it makes no editorial decisions.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# canvas + normative frame plan
# --------------------------------------------------------------------------

# The reference is DESIGNED at 776x496 and exported at 1552x992 with a nearest
# upscale ("text stays chunky"). That is not cosmetic: rendering antialiased text
# at 2x triples the glyph pixel count and floods the palette with intermediate
# greys, which roughly doubles the LZW cost of every frame. Designing at 1x and
# upscaling is both more faithful and ~2x smaller.
DESIGN_W, DESIGN_H = 776, 496
CANVAS_W, CANVAS_H = 1552, 992
EXPORT_SCALE = 2
TOTAL_FRAMES = 414

# 8-phase beat grid, from the reference storyboard. Order and extents are
# normative; only the nouns change.
PHASES = [
    (0, 2),  # 1. cold open          3 frames
    (3, 20),  # 2. submit            18
    (21, 74),  # 3. thinking/stream  54
    (75, 143),  # 4. audit ledger     69
    (144, 195),  # 5. coverage run     52
    (196, 252),  # 6. baseline+install 57
    (253, 340),  # 7. dense resolution 88
    (341, 413),  # 8. settle + end card 73
]

# delay in centiseconds: 100ms base, 400ms at the two early beats, 200ms at the
# four mid/late beats.
DELAY_CS = [10] * TOTAL_FRAMES
for _i in (2, 13):
    DELAY_CS[_i] = 40
for _i in (74, 189, 195, 252):
    DELAY_CS[_i] = 20

# --------------------------------------------------------------------------
# palette (exact tokens)
# --------------------------------------------------------------------------

BG = (0x00, 0x2B, 0x36)
DIVIDER = (0x1E, 0x4A, 0x54)
CHROME_BG = (0xF5, 0xF2, 0xF5)
CHROME_EDGE = (0xA1, 0xAF, 0xB2)
CHROME_TEXT = (0x3A, 0x3F, 0x45)
DOT_RED = (0xFB, 0x60, 0x5B)
DOT_YELLOW = (0xFE, 0xBC, 0x2F)
DOT_GREEN = (0x27, 0xC8, 0x40)

CORAL = (0xE6, 0x6F, 0x4D)
HEADER_TITLE = (0x63, 0x79, 0x80)
DIM_HEADER = (0x3E, 0x5A, 0x63)

PROMPT = (0x8A, 0x9E, 0xA4)
CURSOR = (0x83, 0x94, 0x9B)
PROMPT_HILITE = (0x2A, 0x3F, 0x45)

ACTION = (0xE8, 0xEE, 0xF0)
DETAIL = (0x42, 0x5F, 0x66)
THOUGHT = (0x5A, 0x75, 0x7D)
RUNNING = (0xE0, 0x97, 0x4E)
ERROR = (0xC8, 0x5A, 0x54)
STATUS_GREEN = (0x3F, 0xA3, 0x4D)
PAREN = (0x8A, 0x3B, 0x3B)

PILL_BG = (0x14, 0x18, 0x1D)
PILL_GLYPH = (0xFF, 0xFF, 0xFF)

# status dot per row kind
DOT_OF = {
    "ok": STATUS_GREEN,
    "warn": CORAL,
    "hot": CORAL,
    "err": ERROR,
    "run": RUNNING,
}

FONT_DIR = Path.home() / ".fonts"
FONT_REGULAR = FONT_DIR / "JetBrainsMono-Regular.ttf"
FONT_FALLBACK = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")


def _font(size: int) -> ImageFont.FreeTypeFont:
    path = FONT_REGULAR if FONT_REGULAR.exists() else FONT_FALLBACK
    return ImageFont.truetype(str(path), size)


# --------------------------------------------------------------------------
# geometry (measured from the reference decode, @2x)
# --------------------------------------------------------------------------

CHROME_X0, CHROME_X1 = 22, 751
CHROME_Y0, CHROME_Y1 = 25, 54
APP_X0, APP_X1 = 22, 751
APP_Y0, APP_Y1 = 55, 475
CORNER_R = 8

DOT_CY, DOT_R = 37, 5
DOT_CX = (33, 54, 75)

HEADER_TOP = 74
ICON_X0, ICON_Y0 = 22, 80
ICON_W, ICON_H = 70, 47
ICON_TEXT_X = 102

PROMPT_RULE_TOP = 161
PROMPT_RULE_BOT = 199
PROMPT_TEXT_Y = 167
PROMPT_X = 40

STATUS_Y = 204
BODY_TOP = 233
ROW_PITCH = 18
BODY_X = 31
BODY_TEXT_X = 42
SUB_TEXT_X = 62

PILL_W, PILL_H, PILL_R = 175, 80, 24
PILL_CX = DESIGN_W // 2
PILL_TOP = 371

VISIBLE_ROWS = 13


# --------------------------------------------------------------------------
# wallpaper: low-res colour field upscaled bicubic == cheap, stable blur
# --------------------------------------------------------------------------

_WALLPAPER_CACHE: Image.Image | None = None


def _wallpaper() -> Image.Image:
    """Smooth two-axis gradient: warm orange/magenta upper-left into deep blue
    right, with a pale band along the top. Built per-pixel so there is no
    upscale streaking; blurred once to match the reference's bokeh."""
    global _WALLPAPER_CACHE
    if _WALLPAPER_CACHE is not None:
        return _WALLPAPER_CACHE

    import numpy as np

    w, h = DESIGN_W, DESIGN_H
    xs = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]
    ys = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]

    # horizontal blend warm -> cool, eased so the warm third stays saturated
    t = np.clip((xs - 0.18) / 0.72, 0.0, 1.0) ** 0.85
    warm = np.array([0xF3, 0x95, 0x5E], dtype=np.float32)
    mid = np.array([0xB4, 0x74, 0xA8], dtype=np.float32)
    cool = np.array([0x0A, 0x46, 0xA8], dtype=np.float32)

    rgb = np.empty((h, w, 3), dtype=np.float32)
    left = t < 0.42
    f1 = (t / 0.42)
    rgb[..., :] = np.where(left[..., None], warm + (mid - warm) * f1[..., None], 0.0)
    right = ~left
    f2 = np.clip((t - 0.42) / 0.58, 0.0, 1.0)
    rgb[..., :] = np.where(right[..., None], mid + (cool - mid) * f2[..., None], rgb)

    # vertical: pale/bright along the very top, deepening downward
    v = np.clip(ys / 0.55, 0.0, 1.0) ** 0.7
    top = np.array([0xFF, 0xD9, 0xB0], dtype=np.float32)
    rgb = rgb * (1.0 - 0.30 * v[..., None]) + top * (0.30 * v[..., None])

    # a soft magenta bloom lower-left, matching the reference's second colour
    bx = np.exp(-(((xs - 0.16) / 0.34) ** 2))
    by = np.exp(-(((ys - 0.80) / 0.40) ** 2))
    bloom = (bx * by)[..., None] * np.array([0.50, 0.12, 0.30], dtype=np.float32)
    rgb = np.clip(rgb + bloom * 90.0, 0, 255)

    im = Image.fromarray(rgb.astype("uint8"), "RGB")
    im = im.filter(__import__("PIL.ImageFilter", fromlist=["ImageFilter"]).GaussianBlur(9))
    # A light posterise tames 24-bit gradient noise without visible banding.
    # Measured: palette width barely moves the file size on a text-dense brief,
    # so there is no reason to band the background hard.
    im = im.quantize(colors=64, method=Image.MEDIANCUT, dither=Image.Dither.NONE)
    _WALLPAPER_CACHE = im.convert("RGB")
    return _WALLPAPER_CACHE


# --------------------------------------------------------------------------
# pixel robot sprite (coral), authored at 1x and chunk-scaled
# --------------------------------------------------------------------------

_ROBOT = [
    ".......oo.........",
    "....oooooooooo...",
    "...o############o.",
    "...o#k########k#o.",
    "...o#k########k#o.",
    "...o############o.",
    "....oooooooooo...",
    ".oooooooooooooooo.",
    "o################o",
    "o################o",
    "o##########oooooo",
    "..oo..........oo.",
]


_ROBOT_CACHE: Image.Image | None = None


def _robot(px: int = 1) -> Image.Image:
    """Rasterise the ASCII sprite at `px` pixels per cell."""
    rows, cols = len(_ROBOT), len(_ROBOT[0])
    im = Image.new("RGBA", (cols * px, rows * px), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for y, row in enumerate(_ROBOT):
        for x, ch in enumerate(row):
            if ch not in ("o", "#", "k"):
                continue
            colour = (0, 0, 0) if ch == "k" else CORAL
            d.rectangle(
                [x * px, y * px, (x + 1) * px - 1, (y + 1) * px - 1], fill=colour
            )
    return im


def _robot_scaled() -> Image.Image:
    """Chunk-scaled pixel robot, sized to the measured header icon box."""
    global _ROBOT_CACHE
    if _ROBOT_CACHE is None:
        sprite = _robot(1)
        # fit the 16x18 sprite into ICON_W x ICON_H with integer scaling only,
        # so the pixels stay square and crisp
        scale = max(1, min(ICON_W // sprite.width, ICON_H // sprite.height))
        big = sprite.resize(
            (sprite.width * scale, sprite.height * scale), Image.NEAREST
        )
        _ROBOT_CACHE = big
    return _ROBOT_CACHE


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------


@dataclass
class Row:
    kind: str  # action | dim | thought | running | error | thinking | rule | blank
    text: str
    dot: str = ""  # ok | warn | hot | err | run
    indent: int = 0
    pill: str = ""  # glyph shown for 1 frame when this row appears

    def render_key(self) -> str:
        return f"{self.kind}|{self.dot}|{self.indent}|{self.pill}|{self.text}"


@dataclass
class Phase:
    rows: list[Row] = field(default_factory=list)
    scroll_at: dict[int, int] = field(default_factory=dict)  # row index -> rows to drop
    status: str = ""


_PALETTE_CACHE: Image.Image | None = None

# every colour the UI can draw with, so the quantiser never spends palette slots
# on gradient noise and starves the text
_TOKENS = [
    BG, DIVIDER, CHROME_BG, CHROME_EDGE, CHROME_TEXT,
    DOT_RED, DOT_YELLOW, DOT_GREEN, CORAL, HEADER_TITLE, DIM_HEADER,
    PROMPT, CURSOR, PROMPT_HILITE, ACTION, DETAIL, THOUGHT, RUNNING, ERROR,
    STATUS_GREEN, PAREN, PILL_BG, PILL_GLYPH, (0, 0, 0),
]


def _palette(wallpaper_levels: int = 26) -> Image.Image:
    """Fixed 256-entry global palette: design tokens first, then a small ramp
    for the wallpaper. A limited ramp is what keeps a smooth blurred gradient
    from eating the whole table (and the file size with it)."""
    global _PALETTE_CACHE
    if _PALETTE_CACHE is not None:
        return _PALETTE_CACHE

    cols: list[tuple[int, int, int]] = list(_TOKENS)

    # sample the wallpaper along its gradient and build a coarse ramp
    wp = _wallpaper()
    small = wp.resize((64, 40), Image.BOX)
    px = small.load()
    seen: list[tuple[int, int, int]] = []
    for y in range(40):
        for x in range(64):
            c = px[x, y]
            if c not in seen:
                seen.append(c)
    # spread the sample across the available slots
    room = 256 - len(cols)
    step = max(1, len(seen) // room)
    cols.extend(seen[::step][:room])

    pal = Image.new("P", (1, 1))
    flat: list[int] = []
    for c in cols:
        flat.extend(c)
    flat.extend([0] * (768 - len(flat)))
    pal.putpalette(flat)
    _PALETTE_CACHE = pal
    return pal


# --------------------------------------------------------------------------
# composer
# --------------------------------------------------------------------------


def _text(d: ImageDraw.ImageDraw, xy, s, font, fill, bold=False, max_w=None):
    if max_w and s:
        while s and d.textlength(s, font=font) > max_w:
            s = s[:-1]
    d.text(xy, s, font=font, fill=fill)
    return s


def _round_rect(d, box, r, fill):
    d.rounded_rectangle(box, radius=r, fill=fill)


def _draw_frame(brief: dict, rows: list[Row], scroll: int, step: int,
                status_right: str, prompt_highlight: bool,
                pill: str | None, show_cursor: bool = False) -> Image.Image:
    im = _wallpaper().copy()
    d = ImageDraw.Draw(im)

    # ---- window: light chrome strip + teal app body, one rounded silhouette
    sil = Image.new("L", (DESIGN_W, DESIGN_H), 0)
    sd = ImageDraw.Draw(sil)
    sd.rounded_rectangle([CHROME_X0, CHROME_Y0, CHROME_X1, CHROME_Y1 + CORNER_R * 3],
                         radius=CORNER_R, fill=255)
    sd.rectangle([CHROME_X0, CHROME_Y1 - 2, CHROME_X1, APP_Y1 - CORNER_R], fill=255)
    sd.rounded_rectangle([APP_X0, APP_Y1 - CORNER_R * 2, APP_X1, APP_Y1],
                         radius=CORNER_R, fill=255)
    body = Image.new("RGB", (DESIGN_W, DESIGN_H), CHROME_BG)
    bd = ImageDraw.Draw(body)
    bd.rectangle([APP_X0, APP_Y1 - CORNER_R * 2, APP_X1, APP_Y1], fill=BG)
    im.paste(body, (0, 0), sil)

    # chrome details
    for cx, col in zip(DOT_CX, (DOT_RED, DOT_YELLOW, DOT_GREEN)):
        d.ellipse([cx - DOT_R, DOT_CY - DOT_R, cx + DOT_R, DOT_CY + DOT_R], fill=col)
    f_title = _font(13)
    title = brief["window_title"]
    # clamp the title so it can never run into the right-hand step label
    step_txt = f"--#{step}"
    f_step = _font(12)
    step_w = d.textlength(step_txt, font=f_step)
    avail = (CHROME_X1 - step_w - 30) - (CHROME_X0 + 90)
    while title and d.textlength(title, font=f_title) > avail:
        title = title[:-1]
    d.text((DESIGN_W // 2, DOT_CY), title, font=f_title, fill=CHROME_TEXT, anchor="mm")
    d.text((CHROME_X1 - 11, DOT_CY), step_txt, font=f_step, fill=CHROME_TEXT, anchor="rm")
    d.rectangle([CHROME_X0, CHROME_Y1 - 1, CHROME_X1, CHROME_Y1], fill=CHROME_EDGE)

    # ---- app body
    d = ImageDraw.Draw(im)
    d.rectangle([APP_X0, APP_Y0, APP_X1, APP_Y1], fill=BG)

    # header: robot + identity
    robot = _robot_scaled()
    im.paste(robot, (ICON_X0, ICON_Y0), robot)
    f_hdr = _font(15)
    f_meta = _font(12)
    x = ICON_TEXT_X
    d.text((x, HEADER_TOP + 4), brief["product"], font=f_hdr, fill=HEADER_TITLE)
    d.text((x + d.textlength(brief["product"], font=f_hdr) + 8, HEADER_TOP + 8),
           brief["version"], font=f_meta, fill=DIM_HEADER)
    d.text((x, HEADER_TOP + 30), brief["model"], font=f_meta, fill=DIM_HEADER)
    d.text((x, HEADER_TOP + 54), brief["path"], font=f_meta, fill=DIM_HEADER)

    # prompt block
    d.rectangle([APP_X0, PROMPT_RULE_TOP, APP_X1, PROMPT_RULE_TOP + 1], fill=DIVIDER)
    d.rectangle([APP_X0, PROMPT_RULE_BOT, APP_X1, PROMPT_RULE_BOT + 1], fill=DIVIDER)
    f_prompt = _font(15)
    cmd = brief["command"]
    tw = int(d.textlength(cmd, font=f_prompt))
    if prompt_highlight:
        d.rectangle([PROMPT_X + 17, PROMPT_TEXT_Y - 3, PROMPT_X + 22 + tw + 6,
                     PROMPT_TEXT_Y + 17], fill=PROMPT_HILITE)
    d.text((PROMPT_X, PROMPT_TEXT_Y), ">", font=f_prompt, fill=PROMPT)
    d.text((PROMPT_X + 22, PROMPT_TEXT_Y), cmd, font=f_prompt, fill=PROMPT)
    if show_cursor:
        d.rectangle([PROMPT_X + 25 + tw, PROMPT_TEXT_Y + 1,
                     PROMPT_X + 34 + tw, PROMPT_TEXT_Y + 19], fill=CURSOR)

    # status bar
    f_st = _font(12)
    d.text((BODY_X, STATUS_Y), "branch ", font=f_st, fill=DETAIL)
    d.text((BODY_X + int(d.textlength("branch ", font=f_st)), STATUS_Y),
           f"({brief['branch']})", font=f_st, fill=PAREN)
    d.text((APP_X1 - 24, STATUS_Y), status_right, font=f_st, fill=DETAIL, anchor="ra")

    # body rows
    f_body = _font(14)
    f_sub = _font(12)
    f_think = _font(13)
    visible = rows[scroll:scroll + VISIBLE_ROWS]
    for i, row in enumerate(visible):
        y = BODY_TOP + i * ROW_PITCH
        if y > APP_Y1 + ROW_PITCH:
            break
        if row.kind == "rule":
            d.rectangle([BODY_X, y + 14, APP_X1 - 24, y + 15], fill=DIVIDER)
            continue
        if row.kind == "blank":
            continue
        if row.dot:
            col = DOT_OF.get(row.dot, STATUS_GREEN)
            glyph = {"ok": "o", "warn": "*", "hot": "+", "err": "x", "run": "*"}[row.dot]
            d.text((BODY_X, y), glyph, font=f_body, fill=col)
        tx = BODY_TEXT_X + row.indent
        if row.kind == "action":
            _text(d, (tx, y), row.text, f_body, ACTION,
                  max_w=APP_X1 - 40 - tx)
        elif row.kind == "dim":
            _text(d, (tx, y), row.text, f_sub, DETAIL, max_w=APP_X1 - 40 - tx)
        elif row.kind == "thought":
            _text(d, (tx, y), row.text, f_think, THOUGHT, max_w=APP_X1 - 40 - tx)
        elif row.kind == "running":
            _text(d, (tx, y), row.text, f_body, RUNNING,
                  max_w=APP_X1 - 40 - tx)
        elif row.kind == "error":
            _text(d, (tx, y), row.text, f_body, ERROR,
                  max_w=APP_X1 - 40 - tx)

    # pill overlay
    if pill:
        x0 = PILL_CX - PILL_W // 2
        y0 = PILL_TOP
        _round_rect(d, [x0, y0, x0 + PILL_W, y0 + PILL_H], PILL_R, PILL_BG)
        d.text((PILL_CX, y0 + PILL_H // 2), pill, font=_font(32), fill=PILL_GLYPH,
               anchor="mm")

    # NOTE: returned at 1x on purpose. The render loop quantises HERE and then
    # upscales, so each 2x2 block is a single palette entry. Quantising after the
    # upscale keeps 4x the antialiased greys and roughly doubles the file.
    return im


# --------------------------------------------------------------------------
# timeline
# --------------------------------------------------------------------------


def _phase_rows(phase: Phase) -> list[Row]:
    return phase.rows


def build_timeline(brief: dict) -> list[dict]:
    """Return one dict per frame describing what to draw.

    Rows ACCUMULATE across every phase, so the body reads as one continuous
    scrolling ledger: content streams in, the window holds the newest
    `VISIBLE_ROWS` bands, and `scroll` advances in whole-row jumps. The step
    counter is cumulative so it tracks content beats across the whole run.
    """
    phases = brief["phases"]
    frames: list[dict] = []
    ledger: list[Row] = []
    step = 0

    # ---- phase 1: cold open. Static, prompt complete, cursor visible.
    p1 = phases[0]
    ledger = list(p1.rows)
    for _f in range(PHASES[0][0], PHASES[0][1] + 1):
        frames.append({"rows": ledger, "scroll": 0, "step": 0,
                       "status": p1.status or f"/{brief['command_hint']}",
                       "hl": False, "pill": None, "cursor": True})

    # ---- phase 2: submit. Prompt highlight, fresh `>` row, status flips,
    # and a beat pause before the first pill.
    p2 = phases[1]
    start, end = PHASES[1]
    span = end - start + 1
    reveal = max(1, int(span * 0.35))
    for k, _f in enumerate(range(start, end + 1)):
        want = min(len(p2.rows), max(1, int((k + 1) * len(p2.rows) / span)))
        base = list(ledger)
        shown = base + p2.rows[:want]
        frames.append({
            "rows": shown,
            "scroll": max(0, len(shown) - VISIBLE_ROWS),
            "step": 1 + len(shown),
            "status": p2.status or "Thinking on (tab to toggle)",
            "hl": True,
            "pill": p2.rows[0].pill if k == 0 else None,
            "cursor": False,
        })

    # ---- phases 3..7: stream, accumulating onto the same ledger
    for pi in range(2, 7):
        p = phases[pi]
        start, end = PHASES[pi]
        span = end - start + 1
        n_rows = len(p.rows)
        prior = len(ledger)
        cursor = 0
        for k, _f in enumerate(range(start, end + 1)):
            want = int(round((k + 1) * n_rows / span))
            want = min(n_rows, max(cursor, want))
            newly = [r for r in p.rows[cursor:want] if r.pill]
            pill = newly[0].pill if newly else None
            total = prior + want
            extra = p.scroll_at.get(want, 0)
            frames.append({
                "rows": ledger + p.rows[:want],
                "scroll": max(0, total - VISIBLE_ROWS) + extra,
                "step": 1 + total,
                "status": p.status or f"/{brief['command_hint']}",
                "hl": True,
                "pill": pill,
                "cursor": False,
            })
            cursor = want
        ledger = ledger + p.rows

    # ---- phase 8: settle. No new rows; the ledger rests as the end card.
    p8 = phases[7]
    final_rows = p8.rows if p8.rows else ledger
    start, end = PHASES[7]
    for _f in range(start, end + 1):
        frames.append({
            "rows": final_rows,
            "scroll": max(0, len(final_rows) - VISIBLE_ROWS),
            "step": 1 + len(final_rows),
            "status": p8.status or frames[-1]["status"],
            "hl": True,
            "pill": None,
            "cursor": False,
        })

    assert len(frames) == TOTAL_FRAMES, f"built {len(frames)} frames, need {TOTAL_FRAMES}"
    return frames


# --------------------------------------------------------------------------
# encode
# --------------------------------------------------------------------------


def render(brief: dict, out_path: Path, verbose: bool = True) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    timeline = build_timeline(brief)

    # ---- pass 1: build the global table from the DENSEST frame.
    # Deriving it from frame 0 (a near-empty cold open) starves the table of text
    # colours and makes every later frame quantise to noise, which inflates the
    # file badly. The densest frame is the one that needs the most slots.
    densest = max(timeline, key=lambda s: (len(s["rows"]), s["step"]))
    probe = _draw_frame(brief, densest["rows"], densest["scroll"], densest["step"],
                        densest["status"], densest["hl"], None, False)
    pal_src = probe.convert("RGB").quantize(colors=256, method=Image.MEDIANCUT)
    del probe


    # ---- pass 2: draw + quantize every frame against that one table
    cache: dict[str, Image.Image] = {}
    quant_frames: list[Image.Image] = []
    durations: list[int] = []

    for i, spec in enumerate(timeline):
        im = _draw_frame(
            brief,
            spec["rows"],
            spec["scroll"],
            spec["step"],
            spec["status"],
            spec["hl"],
            spec["pill"],
            spec["cursor"],
        )
        key = f"{i}|{len(spec['rows'])}|{spec['scroll']}|{spec['step']}|{spec['status']}|{spec['hl']}|{spec['pill']}|{spec['cursor']}"
        q = cache.get(key)
        if q is None:
            small = im.convert("RGB").quantize(palette=pal_src, dither=Image.Dither.NONE)
            q = small.resize((CANVAS_W, CANVAS_H), Image.NEAREST)
            cache[key] = q
        quant_frames.append(q)
        durations.append(DELAY_CS[i] * 10)
        if verbose and i % 60 == 0:
            print(f"  frame {i}/{TOTAL_FRAMES}  unique={len(cache)}")

    from gifenc import write_gif

    info = write_gif(out_path, quant_frames, durations, disposal=1)
    info["unique_drawn"] = len(cache)
    return info


# --------------------------------------------------------------------------
# validator
# --------------------------------------------------------------------------


def validate(path: Path, expect_frames: int = TOTAL_FRAMES) -> dict:
    """Decode and measure. Frame count and timing are hard gates; file size is
    reported, not gated, because it tracks how much detail a brief contains."""
    from gifenc import validate_gif

    m = validate_gif(path)
    hist = m["delay_histogram"]
    # expected: 100ms x408, 400ms x2, 200ms x4 (+/-2 on the 100ms bin)
    bins_ok = (
        abs(hist.get(100, 0) - 408) <= 2
        and hist.get(400, 0) == 2
        and hist.get(200, 0) == 4
    )
    return {
        "frames": m["frames"],
        "frames_expected": expect_frames,
        "frames_ok": abs(m["frames"] - expect_frames) <= 4,
        "size": m["size"],
        "size_ok": m["size"] == [CANVAS_W, CANVAS_H],
        "delay_histogram": hist,
        "delay_bins_ok": bins_ok,
        "total_ms": m["total_ms"],
        "total_ok": abs(m["total_ms"] - 42400) <= 500,
        "disposals": m["disposals"],
        "disposal_ok": m["all_disposal_1"],
        "full_canvas_ok": m["full_canvas"],
        "loops": m["loops"],
        "single_play_ok": not m["loops"],
        "gif89a": m["gif89a"],
        "mb": m["mb"],
        "bytes": m["bytes"],
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Render a demo GIF from a brief JSON file")
    ap.add_argument("brief", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    brief = json.loads(a.brief.read_text())
    info = render(brief, a.out, verbose=not a.quiet)
    print("rendered:", info)
    rep = validate(a.out)
    print(json.dumps(rep, indent=2))
    if not rep["PASS"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
