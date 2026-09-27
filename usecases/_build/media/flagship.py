"""The flagship Backstop walkthrough: one continuous take, real surfaces only.

Every frame of footage here comes from the product actually running:
  - the dashboard shots are Chromium screenshots of `backstop dashboard --demo`,
    taken as the real workload drains a real budget;
  - the terminal shots are verbatim stdout of the real commands, captured by
    running them;
  - the code slide is the real documented call.

Nothing is a mock-up of the product. The motion is ours; the content is not.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image, ImageDraw

import theme as T
from terminal import (
    C_TEXT, assert_real_output, column_span, draw_terminal, rows_matching,
)
from theme import (
    ACCENT, ACCENT_SOFT, AMBER, BG, FPS, GREEN, H, LINE, PANEL, PANEL_HI, RED,
    TEXT, TEXT_DIM, TEXT_FAINT, VIOLET, W, arrow, cover, dim, ease_in_out,
    ease_out, ease_out_back, font, glow_box, ken_burns, measure, panel, seg,
    shadowed_text, text, wrap,
)

CAP = Path("/tmp/opencode/media/capture")
OUT = Path("/tmp/opencode/media/out")
DASH = CAP / "dash"
PARTS = CAP / "parts"
ARC = CAP / "run"
CLI = CAP / "cli"

DURATION = 132.0

# The narrative, with the real figures the capture actually recorded.
BUDGET_START = "63.2k"
SPEND_START = "$0.0421"


class Timeline:
    def __init__(self) -> None:
        self.marks: list[tuple[float, str, str]] = []

    def add(self, t: float, kind: str, label: str) -> None:
        self.marks.append((t, kind, label))

    def active(self, t: float) -> tuple[str, str] | None:
        cur = None
        for mt, kind, label in self.marks:
            if t >= mt:
                cur = (kind, label)
            else:
                break
        return cur

    def index_of(self, t: float) -> int:
        n = 0
        for mt, _, _ in self.marks:
            if t >= mt:
                n += 1
        return n - 1


TL = Timeline()
TL.add(0.0, "title", "Cold open")
TL.add(9.0, "terminal", "The same loop, unwrapped")
TL.add(23.0, "code", "One call")
TL.add(34.0, "terminal", "The same loop, wrapped")
TL.add(50.0, "dashboard", "Watch the budget drain")
TL.add(72.0, "guardrail", "The guardrail fires")
TL.add(88.0, "sessions", "Per-agent ceilings")
TL.add(99.0, "money", "What it cost")
TL.add(112.0, "reconcile", "Audit the money")
TL.add(126.0, "close", "The honest limits")


def chapter_title(img: Image.Image, t: float, kind: str, label: str) -> None:
    """A persistent lower-third so a viewer always knows where they are."""
    d = ImageDraw.Draw(img, "RGBA")
    n = TL.index_of(t)
    p = ease_out(seg(t, TL.marks[n][0], 0.5))
    if p <= 0:
        return
    x = int(70 - (1 - p) * 40)
    a = int(255 * p)
    d.rounded_rectangle([x - 18, H - 122, x + 30, H - 74], radius=7, fill=ACCENT + (a,))
    d.text((x, H - 98), f"{n + 1:02d}", font=font(15, bold=True), fill=(8, 12, 18), anchor="lm")
    d.text((x + 46, H - 98), label, font=font(19), fill=TEXT_DIM, anchor="lm")
    rule_w = int(300 * p)
    d.line([(x + 46, H - 72), (x + 46 + rule_w, H - 72)], fill=LINE, width=1)


# --- scene 1: cold open ------------------------------------------------------


def scene_title(img: Image.Image, t: float) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    T.bg(d)
    # A slow ember behind the type, so the opening frame is alive.
    p = seg(t, 0.0, 9.0)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W / 2 - 620, H / 2 - 420, W / 2 + 620, H / 2 + 420], fill=ACCENT_SOFT + (int(52 * (1 - p * 0.7)),))
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow.filter(T.ImageFilter.GaussianBlur(150))).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    # Draw once. A second pass with a zero-alpha ink was darkening the headline
    # to near-invisible rather than being a no-op, so it is simply gone.
    ta = int(255 * ease_out(seg(t, 0.7, 1.5)))
    shadowed_text(img, (W / 2, 372), "An AI feature is about to spend money.",
                  38, TEXT, bold=True, mono=False, anchor="mm")
    d = ImageDraw.Draw(img, "RGBA")
    d.text((W / 2, 374), "An AI feature is about to spend money.",
           font=font(38, mono=False, bold=True), fill=TEXT[:3] + (ta,), anchor="mm")

    sub_p = ease_out(seg(t, 1.9, 1.4))
    y2 = 432
    lines = ["No ceiling. No per-agent limit. No record of what it cost.",
             "One bad loop and the bill is the alert."]
    for i, l in enumerate(lines):
        a = int(255 * ease_out(seg(t, 1.9 + i * 0.42, 1.1)))
        d.text((W / 2, y2 + i * 40), l, font=font(23, mono=False),
               fill=TEXT_DIM[:3] + (a,), anchor="mm")

    # The three capabilities, arriving one at a time.
    caps = [("a ceiling", ACCENT), ("a per-agent limit", VIOLET), ("a receipt", GREEN)]
    for i, (label, col) in enumerate(caps):
        p_i = ease_out_back(seg(t, 3.6 + i * 0.55, 0.9))
        if p_i <= 0:
            continue
        cx = W / 2 + (i - 1) * 400
        cy = 590
        a = int(255 * min(1, p_i * 1.4))
        w = measure(d, label, 21, mono=False) + 56
        d.rounded_rectangle([cx - w / 2, cy - 24 + (1 - p_i) * 26, cx + w / 2, cy + 24 + (1 - p_i) * 26],
                            radius=12, fill=PANEL_HI, outline=col + (a,), width=2)
        d.ellipse([cx - w / 2 + 18, cy - 5, cx - w / 2 + 28, cy + 5], fill=col + (a,))
        d.text((cx + 14, cy), label, font=font(21, mono=False), fill=col + (a,), anchor="mm")

    wp = ease_out(seg(t, 5.6, 1.2))
    if wp > 0:
        shadowed_text(img, (W / 2, 720), "backstop", 64, TEXT, bold=True, mono=True, anchor="mm")
        d2 = ImageDraw.Draw(img, "RGBA")
        a = int(255 * wp)
        d2.text((W / 2, 774), "in-process guardrails for LLM spend", font=font(23, mono=False),
                fill=TEXT_DIM[:3] + (a,), anchor="mm")


# --- scene 2: the unwrapped loop ---------------------------------------------


def stat_column(d: ImageDraw.ImageDraw, x: int, y: int, rows: list[tuple[str, str, tuple]],
                t: float, t0: float, note: list[str] | None = None) -> None:
    """Label above, value below, on a pitch that actually fits a 44px numeral."""
    pitch = 118
    for i, (label, value, col) in enumerate(rows):
        yy = y + i * pitch
        ia = int(255 * ease_out(seg(t, t0 + i * 0.45, 0.8)))
        if ia <= 0:
            continue
        a = min(255, ia)
        d.text((x, yy), label.upper(), font=font(14), fill=TEXT_FAINT[:3] + (a,))
        d.text((x, yy + 26), value, font=font(46, bold=True), fill=col[:3] + (a,))
        d.line([(x, yy + 90), (x + 300, yy + 90)], fill=LINE + (int(120 * ia),), width=1)
    if note:
        na = int(255 * ease_out(seg(t, t0 + 1.6, 1.0)))
        yy = y + len(rows) * pitch + 14
        for i, l in enumerate(note):
            d.text((x, yy + i * 32), l, font=font(18, mono=False), fill=TEXT_DIM[:3] + (na,))


def scene_unwrapped(img: Image.Image, t: float) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    T.bg(d)
    body = assert_real_output(CLI / "demo.txt")
    # Band the Unprotected column only. The table prints both, so the scene has
    # to say which side it is about rather than leaving the viewer to guess.
    draw_terminal(
        img, body,
        box=(120, 120, 1080, 860), size=18, lead=27,
        reveal=ease_out(seg(t, 0.4, 8.0)) * 8,
        band=column_span(body, "", "Unprotected") if t > 2.0 else None,
        band_colour=AMBER, title="backstop demo — the Unprotected column",
    )
    px, py = 1160, 300
    a = int(255 * ease_out(seg(t, 3.0, 1.0)))
    d.text((px, py), "Same loop.", font=font(26, mono=False, bold=True), fill=TEXT[:3] + (a,))
    d.text((px, py + 42), "No ceiling on it.", font=font(26, mono=False, bold=True), fill=TEXT[:3] + (a,))
    stat_column(d, px, py + 130, [
        ("calls attempted", "8", AMBER),
        ("tokens consumed", "200", AMBER),
        ("calls blocked", "0", RED),
    ], t, 4.4, ["It ran to the end of the loop", "and then it billed you."])


# --- scene 3: the one call ---------------------------------------------------


def scene_code(img: Image.Image, t: float) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    T.bg(d)
    a = int(255 * ease_out(seg(t, 0.2, 0.8)))
    d.text((W / 2, 150), "One call.", font=font(40, mono=False, bold=True), fill=TEXT[:3] + (a,), anchor="mm")
    d.text((W / 2, 200), "In-process, before the request is dispatched.",
           font=font(21, mono=False), fill=TEXT_DIM[:3] + (a,), anchor="mm")

    code = [
        ("from openai import OpenAI", C_TEXT, False),
        ("import backstop", C_TEXT, False),
        ("", C_TEXT, False),
        ("client = OpenAI()", C_TEXT, False),
        ("", C_TEXT, False),
        ("client = backstop.wrap(", ACCENT, True),
        ("    client,", C_TEXT, False),
        ("    budget=60,                      # tokens", C_TEXT, False),
        ("    per_agent=True,                 # a ceiling each", C_TEXT, False),
        (")", ACCENT, True),
    ]
    cx, cy = 430, 300
    lead = 46
    panel(d, [cx - 60, cy - 52, cx + 1000, cy + len(code) * lead + 30],
          fill=(14, 16, 21), outline=LINE, radius=16)
    for i, (s, col, bold) in enumerate(code):
        p_i = ease_out(seg(t, 1.0 + i * 0.16, 0.5))
        if p_i <= 0:
            continue
        aa = int(255 * min(1, p_i * 1.6))
        d.text((cx, cy + i * lead), s[: max(0, int(len(s) * p_i))],
               font=font(24, bold=bold), fill=col[:3] + (aa,))

    notes = [
        ("No proxy.", "The SDK object is returned, not replaced."),
        ("No network hop.", "The budget is checked in your process, in-process."),
        ("No new runtime.", "Still the same client, same call, same model."),
    ]
    for i, (head, body_t) in enumerate(notes):
        yy = 350 + i * 108
        p_i = ease_out(seg(t, 3.4 + i * 0.5, 0.8))
        if p_i <= 0:
            continue
        aa = int(255 * p_i)
        x = 1180
        d.ellipse([x, yy + 6, x + 10, yy + 16], fill=GREEN[:3] + (aa,))
        d.text((x + 28, yy), head, font=font(20, mono=False, bold=True), fill=TEXT[:3] + (aa,))
        d.text((x + 28, yy + 32), body_t, font=font(17, mono=False), fill=TEXT_DIM[:3] + (aa,))


# --- scene 4: the wrapped loop ----------------------------------------------


def scene_wrapped(img: Image.Image, t: float) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    T.bg(d)
    body = assert_real_output(CLI / "demo.txt")
    focus = (
        rows_matching(body, "Calls blocked")
        + rows_matching(body, "Tokens consumed")
        + rows_matching(body, "Guardrail exception")
    )
    draw_terminal(
        img, body,
        box=(120, 120, 1080, 860), size=18, lead=27,
        reveal=min(1.0, ease_out(seg(t, 0.4, 9.0)) * 1.6),
        band=column_span(body, "", "Wrapped (Backstop)") if t > 2.0 else None,
        band_colour=GREEN, focus=focus if t > 6.0 else None,
        focus_colour=GREEN, title="backstop demo — the Wrapped column",
    )
    px, py = 1160, 300
    stat_column(d, px, py, [
        ("calls completed", "2", TEXT),
        ("calls blocked", "6", GREEN),
        ("tokens consumed", "50", AMBER),
    ], t, 4.0, ["-75% tokens. 6 calls never left the process.", "The 7th raised BudgetExceededError."])



# --- dashboard scenes --------------------------------------------------------

_shot_cache: dict[str, Image.Image] = {}
_part_cache: dict[str, Image.Image] = {}
_arc_cache: dict[str, Image.Image] = {}


def _arc(name: str) -> Image.Image:
    """A capture from the single run, pre-scaled to the frame."""
    hit = _arc_cache.get(name)
    if hit is None:
        img = Image.open(ARC / f"{name}.png").convert("RGB")
        if name.startswith("page-"):
            img = cover(img, (W, H))
        _arc_cache[name] = img
    return hit


def _figures() -> dict[int, dict]:
    import json
    raw = json.loads((ARC / "figures.json").read_text())
    return {int(r["t"]): r for r in raw}


FIG = _figures()


def _part(name: str) -> Image.Image:
    """A dashboard card, captured by CSS selector, so its bounds are exact."""
    hit = _part_cache.get(name)
    if hit is None:
        hit = Image.open(PARTS / f"{name}.png").convert("RGB")
        _part_cache[name] = hit
    return hit


def _fit(img: Image.Image, width: int) -> tuple[Image.Image, int]:
    h = int(img.height * width / img.width)
    return img.resize((width, h), Image.LANCZOS), h


def _load(name: str) -> Image.Image:
    """Decode a dashboard PNG once. Re-decoding per frame cost 80 minutes."""
    hit = _shot_cache.get(name)
    if hit is None:
        hit = cover(Image.open(DASH / name).convert("RGB"), (W, H))
        _shot_cache[name] = hit
    return hit


def _kpi_cards(img: Image.Image, t: float, base, spend, prevented) -> None:
    """The three numbers that carry the story, restated outside the footage.

    Accepts raw numbers so a timelapse can interpolate them; the formatting
    happens here so no caller can pass a float where a label was expected.
    """
    base_s = base if isinstance(base, str) else _fmt_rem(base)
    spend_s = spend if isinstance(spend, str) else _fmt_spend(spend)
    prev_s = str(int(prevented))
    d = ImageDraw.Draw(img, "RGBA")
    band = 210
    y = H - band + 26
    d.rectangle([0, H - band, W, H], fill=(7, 8, 11))
    d.line([(0, H - band), (W, H - band)], fill=LINE, width=1)
    for i, (label, value, col) in enumerate([
        ("budget remaining", base_s, ACCENT),
        ("token spend", spend_s, AMBER),
        ("spend prevented", prev_s, GREEN),
    ]):
        x = 400 + i * 360
        p = ease_out(seg(t, i * 0.5, 0.7))
        if p <= 0:
            continue
        a = int(255 * min(1, p * 1.5))
        d.text((x, y + 12), label.upper(), font=font(14), fill=TEXT_FAINT[:3] + (a,))
        d.text((x, y + 44), value, font=font(46, bold=True), fill=col[:3] + (a,))


def scene_dashboard(img: Image.Image, t: float) -> None:
    """The real dashboard draining a real budget, as one continuous run."""
    marks = [3, 21, 40, 55, 63, 71, 78]
    p = T.seg(t, 0.0, 21.0)
    idx = p * (len(marks) - 1)
    i0 = min(int(idx), len(marks) - 1)
    i1 = min(i0 + 1, len(marks) - 1)
    blend = Image.blend(_arc(f"page-{marks[i0]:03d}"), _arc(f"page-{marks[i1]:03d}"),
                        ease_in_out(idx - i0))
    # Scale to the frame width, then crop to the space above the caption band.
    # A 1600x1000 page at 1920 wide is 1200 tall, so keeping the whole thing
    # would push the throughput chart out of frame; the top slice is the part
    # carrying the KPI row and both charts.
    band_h = 210
    view_h = H - band_h
    page = blend.resize((W, int(blend.height * W / blend.width)), Image.LANCZOS)
    if page.height > view_h:
        page = page.crop((0, 0, W, view_h))
    img.paste(page, (0, 0))

    # Figures from the read that took each frame, interpolated along the same
    # index, so the strip can never quote a second the viewer is not looking at.
    f0, f1 = FIG[marks[i0]], FIG[marks[i1]]
    k = ease_in_out(idx - i0)
    def mix(a, b):
        return round(a * (1 - k) + b * k, 1) if isinstance(a, (int, float)) else a
    _kpi_cards(img, t, mix(_num(f0["remaining"]), _num(f1["remaining"])),
               mix(_num(f0["spend"]), _num(f1["spend"])),
               int(mix(_num(f0["prevented"]), _num(f1["prevented"]))))

    # The caption sits in the strip's spare right-hand space, not over the
    # dashboard's own KPI row, which is the part the viewer is meant to read.
    d = ImageDraw.Draw(img, "RGBA")
    a2 = int(255 * ease_out(seg(t, 0.5, 1.0)))
    d.text((1520, H - 210 + 44), "`backstop dashboard --demo`",
           font=font(16), fill=TEXT_DIM[:3] + (a2,))
    d.text((1520, H - 210 + 72), "one real run, sampled as it happened",
           font=font(14), fill=TEXT_FAINT[:3] + (a2,))


def _num(v):
    """'67.7k' -> 67700, so the strip can interpolate instead of snapping."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("$", "").replace(",", "").strip()
    mult = 1000.0 if s.endswith("k") else 1.0
    try:
        return float(s.rstrip("k")) * mult
    except ValueError:
        return 0.0


def _fmt_rem(v):
    n = _num(v)
    return f"{n/1000:.1f}k".replace(".0k", "k") if n >= 1000 else f"{n:,.0f}"


def _fmt_spend(v):
    n = _num(v)
    return f"${n:.4f}"


def scene_guardrail(img: Image.Image, t: float) -> None:
    """The crossover, then the aftermath. Both are real captured cards.

    Two beats rather than one long move: the crossover is a moment, and
    inventing a smoothly travelling arrow across a timelapse would put the
    pointer somewhere the footage never was.
    """
    dim(img, (0, 0, W, H), 0.72)
    beat2 = ease_in_out(seg(t, 7.0, 4.0))

    # Beat A: t=92, where the crossover is inside the rolling window.
    a, ah = _fit(_arc("chart-084"), 1180)
    # Beat B: t=118, where the loop is fully throttled.
    b, bh = _fit(_arc("chart-120"), 1180)
    card = Image.blend(a, b, beat2)
    ch = ah
    cx, cy = 120, 250

    d0 = ImageDraw.Draw(img, "RGBA")
    d0.rounded_rectangle([cx - 12, cy - 12, cx + card.width + 12, cy + card.height + 12],
                         radius=14, fill=(9, 11, 15), outline=LINE, width=1)
    img.paste(card, (cx, cy))
    if ease_out(seg(t, 0.8, 0.7)) > 0:
        img.paste(glow_box(img, [cx - 10, cy - 10, cx + card.width + 10, cy + card.height + 10],
                           colour=GREEN, width=3, spread=14), (0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    # Beat A caption -> beat B caption, crossfaded, so the text never lies
    # about which frame is on screen.
    cap_a, cap_b = 1.0 - beat2, beat2
    if cap_a > 0.01:
        aa = int(255 * ease_out(seg(t, 0.4, 0.9)) * cap_a)
        d.text((cx, 168), "requests/s falls as prevented/s rises",
               font=font(27, bold=True), fill=TEXT[:3] + (aa,))
        d.text((cx, 208), "the guardrail is not reporting a number — it is stopping the call",
               font=font(18), fill=TEXT_DIM[:3] + (aa,))
    if cap_b > 0.01:
        ab = int(255 * beat2)
        d.text((cx, 168), "the loop is stopped",
               font=font(27, bold=True), fill=TEXT[:3] + (ab,))
        d.text((cx, 208), "requests/s at zero, prevented/s steady — nothing is being spent",
               font=font(18), fill=TEXT_DIM[:3] + (ab,))

    # The crossover in beat A, at the position it actually sits in that card.
    pa = int(255 * ease_out(seg(t, 2.2, 0.9)) * cap_a)
    if pa > 2:
        kx = cx + int(card.width * 0.845)
        ky = cy + int(ch * 0.66)
        arrow(d, (kx + 210, ky + 96), (kx, ky), colour=GREEN, width=5, head=20,
              progress=ease_out(seg(t, 2.2, 0.7)) * cap_a)
        d.text((kx - 40, ky + 112), "the budget wall — every further call is refused",
               font=font(19, bold=True), fill=GREEN[:3] + (pa,))

    # The figures come from the same read that took the screenshot, so the
    # numbers and the frame can never be from two different seconds.
    f_a, f_b = FIG[84], FIG[120]
    _kpi_cards(img, t,
               _num(f_a["remaining"]) * (1 - beat2) + _num(f_b["remaining"]) * beat2,
               _num(f_a["spend"]) * (1 - beat2) + _num(f_b["spend"]) * beat2,
               int(_num(f_a["prevented"]) * (1 - beat2) + _num(f_b["prevented"]) * beat2))


def scene_sessions(img: Image.Image, t: float) -> None:
    """Per-agent isolation: the sessions table, each agent on its own ceiling."""
    T.bg(ImageDraw.Draw(img, "RGBA"))
    card, ch = _fit(_arc("sessions-120"), 1660)
    cx, cy = 130, 360
    img.paste(card, (cx, cy))

    d = ImageDraw.Draw(img, "RGBA")
    a = int(255 * ease_out(seg(t, 0.6, 0.9)))
    d.text((cx, 190), "PER-AGENT BUDGET ISOLATION", font=font(20, bold=True), fill=ACCENT[:3] + (a,))
    d.text((cx, 232), "One runaway agent cannot spend another agent's ceiling.",
           font=font(26, mono=False), fill=TEXT[:3] + (a,))

    # Ring the Remaining column by its measured position inside the crop. The
    # band must exist before the arrow that references it, not inside `if`.
    bx0 = cx + int(card.width * 0.455)
    bx1 = cx + int(card.width * 0.565)
    by0 = cy + int(card.height * 0.30)
    by1 = cy + int(card.height * 0.94)
    if ease_out(seg(t, 2.0, 0.9)) > 0:
        img.paste(glow_box(img, [bx0, by0, bx1, by1], colour=AMBER, width=3, spread=12), (0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    na = int(255 * ease_out(seg(t, 3.0, 0.9)))
    arrow(d, (bx0 + (bx1 - bx0) / 2, by0 - 74), (bx0 + (bx1 - bx0) / 2, by0 - 16),
          colour=AMBER, width=5, head=18, progress=ease_out(seg(t, 3.0, 0.6)))
    d.text((cx, cy + ch + 46), "every agent stops at 1,020 — its own ceiling, not the shared one",
           font=font(21, bold=True), fill=AMBER[:3] + (na,))


# --- money scenes ------------------------------------------------------------


def scene_money(img: Image.Image, t: float) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    T.bg(d)
    body = assert_real_output(CLI / "ledger.txt")
    draw_terminal(
        img, body,
        box=(120, 70, 1180, 960), size=16, lead=23,
        reveal=min(1.0, ease_out(seg(t, 0.3, 9.0)) * 1.9),
        focus=rows_matching(body, "TOTAL") or rows_matching(body, "gpt-4o")[:2],
        focus_colour=AMBER, title="backstop ledger demo",
    )
    px, py = 1240, 230
    a = int(255 * ease_out(seg(t, 3.0, 1.0)))
    d.text((px, py), "A ledger, not a dashboard.", font=font(23, mono=False, bold=True), fill=TEXT[:3] + (a,))
    d.text((px, py + 38), "One immutable row per request:", font=font(18, mono=False), fill=TEXT_DIM[:3] + (a,))
    for i, f in enumerate([
        "model, tokens, latency, retries",
        "your attribution, and a Decimal cost",
        "written to a file you own",
    ]):
        d.text((px + 18, py + 84 + i * 34), "· " + f, font=font(17, mono=False), fill=TEXT_DIM[:3] + (a,))
    ba = int(255 * ease_out(seg(t, 6.4, 1.0)))
    panel(d, [px, py + 220, px + 560, py + 380], fill=PANEL_HI, outline=LINE, radius=14)
    d.text((px + 26, py + 244), "CHARGE-BACK", font=font(14), fill=TEXT_FAINT[:3] + (ba,))
    d.text((px + 26, py + 286), "per team, per feature,", font=font(19, mono=False), fill=TEXT[:3] + (ba,))
    d.text((px + 26, py + 316), "exported as CSV", font=font(19, mono=False), fill=TEXT[:3] + (ba,))


def scene_reconcile(img: Image.Image, t: float) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    T.bg(d)
    body = assert_real_output(CLI / "reconcile.txt")
    # The variance block, not the preamble: find the per-model table.
    focus = rows_matching(body, "variance") + rows_matching(body, "unpriced")
    draw_terminal(
        img, body,
        box=(120, 70, 1180, 960), size=15, lead=21,
        reveal=min(1.0, ease_out(seg(t, 0.3, 8.0)) * 2.4),
        focus=focus[:3] if t > 5.0 else None,
        focus_colour=VIOLET, title="backstop reconcile --demo",
    )
    px, py = 1240, 200
    a = int(255 * ease_out(seg(t, 3.2, 1.0)))
    d.text((px, py), "But is the ledger right?", font=font(23, mono=False, bold=True), fill=TEXT[:3] + (a,))
    d.text((px, py + 40), "Reconcile it against the statement", font=font(18, mono=False), fill=TEXT_DIM[:3] + (a,))
    d.text((px, py + 66), "the provider actually sent.", font=font(18, mono=False), fill=TEXT_DIM[:3] + (a,))
    for i, (h, bdy, col) in enumerate([
        ("Never guesses a price.", "A model with no rate is reported unpriced, not defaulted.", VIOLET),
        ("Never nets a gap away.", "Billed-but-unrecorded is its own row, not an offset.", AMBER),
        ("States its own error budget.", "Measured over the statements you gave it, and says so.", GREEN),
    ]):
        yy = py + 128 + i * 122
        ia = int(255 * ease_out(seg(t, 5.0 + i * 0.55, 0.8)))
        d.ellipse([px, yy + 8, px + 10, yy + 18], fill=col[:3] + (ia,))
        d.text((px + 28, yy), h, font=font(19, mono=False, bold=True), fill=TEXT[:3] + (ia,))
        for j, l in enumerate(wrap(ImageDraw.Draw(img), bdy, 16, 480)):
            d.text((px + 28, yy + 32 + j * 26), l, font=font(16, mono=False), fill=TEXT_DIM[:3] + (ia,))


# --- close -------------------------------------------------------------------


def scene_close(img: Image.Image, t: float) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    T.bg(d)
    p = ease_out(seg(t, 0.2, 1.0))
    shadowed_text(img, (W / 2, 190), "What it is not", 40, TEXT, bold=True, mono=False, anchor="mm")
    items = [
        ("Not a proxy.", "in-process, or a sidecar only if you want one"),
        ("Not a cloud control plane.", "no server, nothing uploaded"),
        ("Not exact.", "a dated rate card, and it says so per row"),
        ("Not new runtime.", "one call, same SDK, same model"),
    ]
    for i, (h, bdy) in enumerate(items):
        yy = 300 + i * 78
        ia = int(255 * ease_out(seg(t, 0.8 + i * 0.4, 0.8)))
        d.text((W / 2, yy), h, font=font(22, mono=False, bold=True), fill=TEXT[:3] + (ia,), anchor="mm")
        d.text((W / 2, yy + 32), bdy, font=font(17, mono=False), fill=TEXT_DIM[:3] + (ia,), anchor="mm")
    fa = int(255 * ease_out(seg(t, 2.8, 1.2)))
    shadowed_text(img, (W / 2, 700), "backstop", 60, TEXT, bold=True, mono=True, anchor="mm")
    d2 = ImageDraw.Draw(img, "RGBA")
    d2.text((W / 2, 758), "pip install backstop", font=font(22), fill=ACCENT[:3] + (fa,), anchor="mm")
    d2.text((W / 2, 800), "MIT licensed · the ledger and its limits are in docs/ledger.md",
            font=font(16, mono=False), fill=TEXT_FAINT[:3] + (fa,), anchor="mm")


# --- compositor --------------------------------------------------------------

SCENES = [
    (0.0, 9.0, scene_title),
    (9.0, 23.0, scene_unwrapped),
    (23.0, 34.0, scene_code),
    (34.0, 50.0, scene_wrapped),
    (50.0, 72.0, scene_dashboard),
    (72.0, 88.0, scene_guardrail),
    (88.0, 99.0, scene_sessions),
    (99.0, 112.0, scene_money),
    (112.0, 126.0, scene_reconcile),
    (126.0, DURATION, scene_close),
]


def render(out: Path | None = None, duration: float = DURATION) -> Path:
    out = out or (OUT / "backstop-walkthrough.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    total = int(duration * FPS)
    ff = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
            "-i", "-", "-an",
            "-c:v", "libx264", "-preset", "slow", "-crf", "19",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out),
        ],
        stdin=subprocess.PIPE,
    )
    for m in (3, 21, 40, 55, 63, 71, 78):
        _arc(f"page-{m:03d}")
    for n in ("chart-084", "chart-120", "sessions-120", "tiles-120"):
        _arc(n)
    print(f"  decoded {len(_arc_cache)} captures from one run", flush=True)

    frame = Image.new("RGB", (W, H), BG)
    for n in range(total):
        t = n / FPS
        for start, end, fn in SCENES:
            if start <= t < end:
                # A cut, with a brief dip to black so the splice is deliberate.
                # fade_in rises over the first frames, fade_out falls over the
                # last. Both must be clamped: `seg` reads 0 before its window,
                # which would otherwise black out the entire scene.
                fade_in = min(1.0, seg(t, start, 0.16))
                fade_out = 1.0 - min(1.0, seg(t, end - 0.16, 0.16))
                cut = min(fade_in, fade_out)
                frame = Image.new("RGB", (W, H), BG)
                fn(frame, t - start)
                if cut < 1.0:
                    d = ImageDraw.Draw(frame, "RGBA")
                    veil = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * (1 - cut))))
                    frame = Image.alpha_composite(frame.convert("RGBA"), veil).convert("RGB")
                break
        act = TL.active(t)
        if act:
            chapter_title(frame, t, *act)
        ff.stdin.write(frame.tobytes())
        if n % (FPS * 10) == 0:
            print(f"  {t:6.1f}s / {duration:.0f}s  {act[1] if act else '-'}", flush=True)
    ff.stdin.close()
    ff.wait()
    return out


if __name__ == "__main__":
    p = render()
    print("wrote", p, f"{p.stat().st_size / 1e6:.1f}MB")
