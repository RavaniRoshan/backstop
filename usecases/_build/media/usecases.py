"""One video per usecase, each on the surface where that use case actually lives.

The previous set was five variations on a synthetic terminal canvas, which meant
none of them showed where in the product the thing happens. Each scene here is
built from the surface that owns the story:

  multi-tenant-saas     the Tenants panel, with real per-tenant budgets
  runaway-eval-loop     `backstop demo`, then the dashboard's prevention chart
  agent-fleet-slo       the Sessions panel, per-agent ceilings and concurrency
  audit-and-compliance  `backstop ledger demo`, the record itself
  major-end-to-end      the whole run, drain through guardrail

Every asset is captured from the product running. The motion is ours.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image, ImageDraw

import theme as T
from terminal import assert_real_output, column_span, draw_terminal, rows_matching
from theme import (
    ACCENT, AMBER, BG, FPS, GREEN, H, LINE, PANEL_HI, RED, TEXT, TEXT_DIM,
    TEXT_FAINT, VIOLET, W, arrow, cover, dim, ease_in_out, ease_out, font,
    glow_box, measure, panel, seg, shadowed_text, wrap,
)

CAP = Path("/tmp/opencode/media/capture")
OUT = Path("/tmp/opencode/media/out/usecases")
DASH = CAP / "run"
TEN = CAP / "tenants"
CLI = CAP / "cli"

_cache: dict[str, Image.Image] = {}


def img(path: Path) -> Image.Image:
    hit = _cache.get(str(path))
    if hit is None:
        hit = Image.open(path).convert("RGB")
        _cache[str(path)] = hit
    return hit


def fit(im: Image.Image, width: int) -> tuple[Image.Image, int]:
    h = int(im.height * width / im.width)
    return im.resize((width, h), Image.LANCZOS), h


def heading(img_: Image.Image, kicker: str, title: str, t: float) -> None:
    d = ImageDraw.Draw(img_, "RGBA")
    a = int(255 * ease_out(seg(t, 0.3, 0.7)))
    d.text((120, 128), kicker.upper(), font=font(19, bold=True), fill=ACCENT[:3] + (a,))
    for i, l in enumerate(wrap(ImageDraw.Draw(img_), title, 30, 1180)):
        d.text((120, 176 + i * 42), l, font=font(30, mono=False, bold=True), fill=TEXT[:3] + (a,))


def caption(img_: Image.Image, body: str, t: float, colour=TEXT_DIM) -> None:
    d = ImageDraw.Draw(img_, "RGBA")
    a = int(255 * ease_out(seg(t, 1.2, 0.8)))
    for i, l in enumerate(wrap(ImageDraw.Draw(img_), body, 19, 1300)):
        d.text((120, 902 + i * 30), l, font=font(19, mono=False), fill=colour[:3] + (a,))


# --- multi-tenant-saas -------------------------------------------------------


def s_multitenant(img_: Image.Image, t: float) -> None:
    T.bg(ImageDraw.Draw(img_, "RGBA"))
    heading(img_, "multi-tenant SaaS", "Four customers share one process. Each has its own ceiling.", t)
    panel_img, ph = fit(img(TEN / "tenants.png"), 1240)
    img_.paste(panel_img, (120, 300))
    if ease_out(seg(t, 1.4, 0.8)) > 0:
        img_.paste(glow_box(img_, [110, 290, 120 + 1240, 300 + ph],
                            colour=AMBER, width=3, spread=14), (0, 0))
    d = ImageDraw.Draw(img_, "RGBA")
    # initech is the row at the bottom: 8,000 used, 0 remaining.
    y0 = 300 + int(ph * 0.78)
    y1 = 300 + int(ph * 0.99)
    if ease_out(seg(t, 2.4, 0.8)) > 0:
        img_.paste(glow_box(img_, [110, y0, 120 + 1240, y1], colour=RED, width=3, spread=12), (0, 0))
    d = ImageDraw.Draw(img_, "RGBA")
    na = int(255 * ease_out(seg(t, 3.2, 0.9)))
    # The initech row: the one at 0 remaining.
    y_initech = 300 + int(ph * 0.885)
    arrow(d, (1420, y_initech - 6), (1348, y_initech), colour=RED, width=5, head=18,
          progress=ease_out(seg(t, 3.2, 0.7)))
    d.text((1432, y_initech - 92), "initech", font=font(22, bold=True), fill=RED[:3] + (na,))
    d.text((1432, y_initech - 58), "hit 100% and was cut off", font=font(17), fill=TEXT_DIM[:3] + (na,))
    d.text((1432, y_initech - 4), "acme, globex and hooli", font=font(17, bold=True), fill=GREEN[:3] + (na,))
    for i, l in enumerate(["kept spending from their own", "budgets, unaffected by it."]):
        d.text((1432, y_initech + 28 + i * 26), l, font=font(17), fill=TEXT_DIM[:3] + (na,))
    caption(img_, "Budgets are scoped per tenant with `backstop.with_budget(tenant_id)`. "
                  "One customer's runaway cannot spend another's ceiling, and cannot be "
                  "unbilled to the wrong invoice.", t)


# --- runaway-eval-loop -------------------------------------------------------


def s_runaway(img_: Image.Image, t: float) -> None:
    T.bg(ImageDraw.Draw(img_, "RGBA"))
    body = assert_real_output(CLI / "demo.txt")
    if t < 9.0:
        heading(img_, "runaway eval loop", "The same eight iterations, both ways.", t)
        draw_terminal(img_, body, box=(120, 300, 1180, 860), size=18, lead=27,
                      reveal=min(1.0, ease_out(seg(t, 0.8, 6.0)) * 1.6),
                      band=column_span(body, "", "Wrapped (Backstop)") if t > 2.4 else None,
                      band_colour=GREEN,
                      focus=rows_matching(body, "Calls blocked") if t > 5.0 else None,
                      focus_colour=GREEN, title="backstop demo")
        d = ImageDraw.Draw(img_, "RGBA")
        a = int(255 * ease_out(seg(t, 3.0, 0.9)))
        d.text((1230, 380), "6 of 8 calls", font=font(30, bold=True), fill=GREEN[:3] + (a,))
        d.text((1230, 424), "never left the process.", font=font(19, mono=False), fill=TEXT_DIM[:3] + (a,))
        d.text((1230, 470), "The 7th raised", font=font(17, mono=False), fill=TEXT_DIM[:3] + (a,))
        d.text((1230, 494), "BudgetExceededError.", font=font(17, mono=False), fill=TEXT_DIM[:3] + (a,))
    else:
        p = seg(t, 9.0, 10.0)
        card, ch = fit(img(DASH / "chart-120.png"), 1500)
        img_.paste(card, (210, 250))
        d = ImageDraw.Draw(img_, "RGBA")
        a = int(255 * ease_out(seg(t, 9.6, 0.8)))
        d.text((120, 128), "RUNAWAY EVAL LOOP", font=font(19, bold=True), fill=ACCENT[:3] + (a,))
        d.text((120, 176), "The same wall, live: requests/s at zero.",
               font=font(30, mono=False, bold=True), fill=TEXT[:3] + (a,))
        d.text((210, 250 + ch + 40),
               "Blue is work getting through. Red is work the guardrail stopped.",
               font=font(19, mono=False), fill=TEXT_DIM[:3] + (a,))


# --- agent-fleet-slo ---------------------------------------------------------


def s_fleet(img_: Image.Image, t: float) -> None:
    T.bg(ImageDraw.Draw(img_, "RGBA"))
    heading(img_, "agent fleet SLO", "Many agents, one process, a ceiling each.", t)
    sess, sh = fit(img(TEN / "sessions.png"), 1500)
    img_.paste(sess, (210, 300))
    if ease_out(seg(t, 1.4, 0.8)) > 0:
        img_.paste(glow_box(img_, [200, 290, 210 + 1500, 300 + sh], colour=ACCENT, width=3, spread=14), (0, 0))
    d = ImageDraw.Draw(img_, "RGBA")
    a = int(255 * ease_out(seg(t, 2.4, 0.9)))
    d.text((210, 300 + sh + 44),
           "Per-agent budget isolation, plus the concurrency and circuit state of each session.",
           font=font(20, mono=False), fill=TEXT_DIM[:3] + (a,))
    tiles, th = fit(img(TEN / "tiles.png"), 1500)
    img_.paste(tiles, (210, 300 + sh + 96))
    caption(img_, "An agent that starts looping is stopped on its own budget. The rest of the fleet "
                  "keeps its latency, and Prometheus gauges stay labelled rather than "
                  "last-writer-wins.", t)


# --- audit-and-compliance ----------------------------------------------------


def s_audit(img_: Image.Image, t: float) -> None:
    T.bg(ImageDraw.Draw(img_, "RGBA"))
    body = assert_real_output(CLI / "ledger.txt")
    heading(img_, "audit & compliance", "One immutable row per request, on disk.", t)
    draw_terminal(img_, body, box=(120, 300, 1240, 880), size=15, lead=21,
                  reveal=min(1.0, ease_out(seg(t, 0.7, 7.0)) * 2.1),
                  focus=(rows_matching(body, "TOTAL") or rows_matching(body, "gpt-4o")[:2]) if t > 4 else None,
                  focus_colour=AMBER, title="backstop ledger demo")
    d = ImageDraw.Draw(img_, "RGBA")
    a = int(255 * ease_out(seg(t, 4.0, 0.9)))
    x = 1300
    for i, (h, b_, col) in enumerate([
        ("Frozen and validated.", "A wrong type or value fails at construction, naming the field.", ACCENT),
        ("Exactly 18 fields.", "An unknown key and a missing key are both errors, so a truncated line cannot reload.", GREEN),
        ("A charge-back, not a dashboard.", "Group by team or feature and export the CSV finance can reconcile.", AMBER),
    ]):
        y = 380 + i * 150
        ia = int(255 * ease_out(seg(t, 4.0 + i * 0.5, 0.8)))
        d.ellipse([x, y + 8, x + 10, y + 18], fill=col[:3] + (ia,))
        d.text((x + 26, y), h, font=font(19, mono=False, bold=True), fill=TEXT[:3] + (ia,))
        for j, l in enumerate(wrap(ImageDraw.Draw(img_), b_, 16, 500)):
            d.text((x + 26, y + 30 + j * 25), l, font=font(16, mono=False), fill=TEXT_DIM[:3] + (ia,))


# --- major-end-to-end --------------------------------------------------------


def s_endtoend(img_: Image.Image, t: float) -> None:
    T.bg(ImageDraw.Draw(img_, "RGBA"))
    marks = [3, 21, 40, 55, 63, 71, 78, 92, 110, 120]
    p = seg(t, 0.5, 13.0)
    idx = p * (len(marks) - 1)
    i0 = min(int(idx), len(marks) - 1)
    i1 = min(i0 + 1, len(marks) - 1)
    a = cover(img(DASH / f"page-{marks[i0]:03d}.png"), (W, H))
    b = cover(img(DASH / f"page-{marks[i1]:03d}.png"), (W, H))
    blended = Image.blend(a, b, ease_in_out(idx - i0))
    page = blended.resize((W, int(blended.height * W / blended.width)), Image.LANCZOS)
    if page.height > 880:
        page = page.crop((0, 0, W, 880))
    img_.paste(page, (0, 0))
    d = ImageDraw.Draw(img_, "RGBA")
    # The band, carrying the real figures for the second on screen.
    d.rectangle([0, 880, W, H], fill=(7, 8, 11))
    d.line([(0, 880), (W, 880)], fill=LINE, width=1)
    import json
    fig = {int(r["t"]): r for r in json.loads((DASH / "figures.json").read_text())}
    f0, f1 = fig[marks[i0]], fig[marks[i1]]
    k = ease_in_out(idx - i0)
    def n(v):
        s = str(v).replace("$", "").replace(",", "")
        m = 1000.0 if s.endswith("k") else 1.0
        return float(s.rstrip("k")) * m
    rem = n(f0["remaining"]) * (1 - k) + n(f1["remaining"]) * k
    sp = n(f0["spend"]) * (1 - k) + n(f1["spend"]) * k
    pv = int(n(f0["prevented"]) * (1 - k) + n(f1["prevented"]) * k)
    a2 = int(255 * ease_out(seg(t, 0.3, 0.7)))
    for i, (lab, val, col) in enumerate([
        ("budget remaining", f"{rem/1000:.1f}k", ACCENT),
        ("token spend", f"${sp:.4f}", AMBER),
        ("spend prevented", str(pv), GREEN),
    ]):
        x = 400 + i * 360
        d.text((x, 906), lab.upper(), font=font(14), fill=TEXT_FAINT[:3] + (a2,))
        d.text((x, 940), val, font=font(44, bold=True), fill=col[:3] + (a2,))
    d.text((1520, 930), "one real run of `backstop dashboard --demo`",
           font=font(15), fill=TEXT_FAINT[:3] + (a2,))


VIDEOS = {
    "multi-tenant-saas": (s_multitenant, 13.0),
    "runaway-eval-loop": (s_runaway, 19.0),
    "agent-fleet-slo": (s_fleet, 11.0),
    "audit-and-compliance": (s_audit, 12.0),
    "major-end-to-end": (s_endtoend, 14.0),
}


def render(name: str, fn, duration: float, out: Path) -> Path:
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-an",
         "-c:v", "libx264", "-preset", "slow", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE,
    )
    total = int(duration * FPS)
    frame = Image.new("RGB", (W, H), BG)
    for i in range(total):
        t = i / FPS
        frame = Image.new("RGB", (W, H), BG)
        # `seg` reads 0 before its window, so the tail has to be inverted
        # rather than min'd: taking it raw veiled the entire video to black.
        fade_in = min(1.0, seg(t, 0.0, 0.3))
        fade_out = 1.0 - min(1.0, seg(t, duration - 0.3, 0.3))
        fade = min(fade_in, fade_out)
        fn(frame, t)
        if fade < 1.0:
            veil = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * (1 - fade))))
            frame = Image.alpha_composite(frame.convert("RGBA"), veil).convert("RGB")
        ff.stdin.write(frame.tobytes())
    ff.stdin.close()
    ff.wait()
    return out


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1:] or list(VIDEOS)
    for name in only:
        fn, dur = VIDEOS[name]
        p = render(name, fn, dur, OUT / f"{name}.mp4")
        print(f"  {name:<22} {dur:4.0f}s  {p.stat().st_size/1e6:5.2f}MB", flush=True)
