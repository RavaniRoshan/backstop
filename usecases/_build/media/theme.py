"""Shared visual language for the Backstop demo videos.

One theme, one set of easing curves, one set of primitives. The point is that
the dashboard footage and the terminal footage are typeset by the same code, so
a cut between them reads as one film rather than two clips stapled together.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
FPS = 30

FONT_DIR = Path("/home/shiva/projects/backstop/usecases/_build")
MONO = FONT_DIR / "JetBrainsMono-Regular.ttf"
MONO_BOLD = FONT_DIR / "JetBrainsMono-Bold.ttf"
MONO_FALLBACK = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
SANS = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
SANS_BOLD = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(size: int, *, bold: bool = False, mono: bool = True) -> ImageFont.FreeTypeFont:
    key = ("b" if bold else "r", size, mono)
    hit = _font_cache.get(key)
    if hit is not None:
        return hit
    if mono:
        for cand in ((MONO_BOLD if bold else MONO), MONO_FALLBACK):
            if cand.exists():
                hit = ImageFont.truetype(str(cand), size)
                break
    if hit is None:
        for cand in ((SANS_BOLD if bold else SANS), MONO_FALLBACK):
            if cand.exists():
                hit = ImageFont.truetype(str(cand), size)
                break
    if hit is None:  # pragma: no cover - a font always exists on a desktop
        hit = ImageFont.load_default()
    _font_cache[key] = hit
    return hit


# Matches the dashboard's own dark theme so a cut between browser footage and
# typeset terminal does not change the colour of the world.
BG = (11, 13, 17)
PANEL = (18, 21, 27)
PANEL_HI = (26, 30, 38)
LINE = (38, 44, 55)
TEXT = (228, 232, 238)
TEXT_DIM = (138, 148, 165)
TEXT_FAINT = (92, 100, 115)
ACCENT = (56, 152, 255)      # the dashboard's chart blue
ACCENT_SOFT = (28, 74, 122)
GREEN = (43, 190, 92)
AMBER = (232, 160, 32)
RED = (232, 74, 74)
VIOLET = (150, 120, 240)


# --- easing ------------------------------------------------------------------


def ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def seg(t: float, start: float, dur: float) -> float:
    """Progress of a sub-animation that begins at `start` and lasts `dur`."""
    if dur <= 0:
        return 0.0
    return max(0.0, min(1.0, (t - start) / dur))


# --- drawing primitives ------------------------------------------------------


def bg(d: ImageDraw.ImageDraw, colour=BG) -> None:
    d.rectangle([0, 0, W, H], fill=colour)


def panel(d: ImageDraw.ImageDraw, box, fill=PANEL, outline=LINE, radius=14, width=1) -> None:
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def text(
    d: ImageDraw.ImageDraw, xy, s, size, fill=TEXT, *, bold=False, mono=True,
    anchor: str | None = None, max_w: int | None = None,
) -> None:
    f = font(size, bold=bold, mono=mono)
    if max_w:
        s = ellipsize(d, s, f, max_w)
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


def ellipsize(d: ImageDraw.ImageDraw, s: str, f, max_w: int) -> str:
    if d.textlength(s, font=f) <= max_w:
        return s
    while s and d.textlength(s + "…", font=f) > max_w:
        s = s[:-1]
    return s + "…"


def measure(d: ImageDraw.ImageDraw, s: str, size, *, bold=False, mono=True) -> int:
    return int(d.textlength(s, font=font(size, bold=bold, mono=mono)))


def wrap(d: ImageDraw.ImageDraw, s: str, size, max_w: int, *, bold=False, mono=False) -> list[str]:
    f = font(size, bold=bold, mono=mono)
    out: list[str] = []
    for para in s.split("\n"):
        words, line = para.split(), ""
        for w in words:
            trial = f"{line} {w}".strip()
            if d.textlength(trial, font=f) <= max_w or not line:
                line = trial
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


def glow_box(
    base: Image.Image, box, *, colour=ACCENT, radius=16, width=3,
    strength=26, spread=10,
) -> Image.Image:
    """A focus ring with real falloff, so it reads as light and not as a border."""
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(box, radius=radius, outline=colour + (255,), width=width)
    layer = layer.filter(ImageFilter.GaussianBlur(spread))
    d2 = ImageDraw.Draw(layer)
    d2.rounded_rectangle(box, radius=radius, outline=colour + (255,), width=width)
    out = base.convert("RGBA")
    out.alpha_composite(layer)
    ring = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(ring).rounded_rectangle(box, radius=radius, outline=colour + (235,), width=width)
    out.alpha_composite(ring)
    return out.convert("RGB")


def dim(base: Image.Image, box, amount: float = 0.55) -> Image.Image:
    """Push a region toward the background so attention goes elsewhere."""
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(base.width, x1), min(base.height, y1)
    if x1 <= x0 or y1 <= y0:
        return base
    region = base.crop((x0, y0, x1, y1)).convert("RGBA")
    veil = Image.new("RGBA", region.size, BG + (int(255 * amount),))
    region.alpha_composite(veil)
    base.paste(region.convert("RGB"), (x0, y0))
    return base


def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale-and-crop to fill, preserving aspect."""
    tw, th = size
    s = max(tw / img.width, th / img.height)
    nw, nh = max(tw, int(img.width * s + 0.5)), max(th, int(img.height * s + 0.5))
    r = img.resize((nw, nh), Image.LANCZOS)
    return r.crop(((nw - tw) // 2, (nh - th) // 2, (nw - tw) // 2 + tw, (nh - th) // 2 + th))


def ken_burns(img: Image.Image, t: float, zoom_from=1.0, zoom_to=1.06,
              pan_x=0.0, pan_y=0.0) -> Image.Image:
    """Slow drift, so a still frame reads as a camera rather than a freeze."""
    z = zoom_from + (zoom_to - zoom_from) * max(0.0, min(1.0, t))
    tw, th = W, H
    s = z * max(tw / img.width, th / img.height)
    nw, nh = int(img.width * s + 0.5), int(img.height * s + 0.5)
    r = img.resize((nw, nh), Image.LANCZOS)
    slack_x, slack_y = max(0, nw - tw), max(0, nh - th)
    cx = slack_x * (0.5 + pan_x * 0.5)
    cy = slack_y * (0.5 + pan_y * 0.5)
    x = int(slack_x * 0.5 + pan_x * slack_x * 0.5)
    y = int(slack_y * 0.5 + pan_y * slack_y * 0.5)
    del cx, cy
    return r.crop((x, y, x + tw, y + th))


def arrow(d: ImageDraw.ImageDraw, start, end, *, colour=ACCENT, width=5, head=18,
          progress=1.0, style="->") -> None:
    """A drawn arrow with a real head. progress < 1 draws it growing."""
    x0, y0 = start
    x1, y1 = end
    if progress <= 0:
        return
    x1 = x0 + (x1 - x0) * progress
    y1 = y0 + (y1 - y0) * progress
    ang = math.atan2(y1 - y0, x1 - x0)
    if style == "->":
        bx, by = x1 - head * math.cos(ang), y1 - head * math.sin(ang)
        d.line([(x0, y0), (bx, by)], fill=colour, width=width)
        d.polygon([
            (x1, y1),
            (x1 - head * math.cos(ang - 0.42), y1 - head * math.sin(ang - 0.42)),
            (x1 - head * math.cos(ang + 0.42), y1 - head * math.sin(ang + 0.42)),
        ], fill=colour)
    else:
        d.line([(x0, y0), (x1, y1)], fill=colour, width=width)


def pulse(width: int, t: float, period: float = 1.6) -> float:
    """0..1..0, for attention that should not strobe."""
    return 0.5 + 0.5 * math.sin(2 * math.pi * ((t / period) % 1.0))


def cursor(d: ImageDraw.ImageDraw, xy, *, size=26, colour=TEXT, blink_t: float = 0.0) -> None:
    x, y = xy
    if blink_t and (blink_t % 1.06) > 0.56:
        return
    d.rectangle([x, y, x + int(size * 0.58), y + size], fill=colour)


def shadowed_text(
    base: Image.Image, xy, s, size, fill=TEXT, *, bold=False, mono=True,
    anchor=None, blur=8, opacity=150,
) -> None:
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(
        xy, s, font=font(size, bold=bold, mono=mono), fill=(0, 0, 0, opacity), anchor=anchor,
    )
    base.paste(Image.alpha_composite(base.convert("RGBA"), layer.filter(ImageFilter.GaussianBlur(blur))).convert("RGB"), (0, 0))
    ImageDraw.Draw(base).text(xy, s, font=font(size, bold=bold, mono=mono), fill=fill, anchor=anchor)
