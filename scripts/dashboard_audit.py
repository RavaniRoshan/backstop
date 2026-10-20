#!/usr/bin/env python3
"""Screenshot the built-in dashboard and assert the invariants it must hold.

Development harness, not a test dependency: Playwright and Chromium are not
package dependencies of ``backstop-ai`` and CI does not run this.

    python3 scripts/dashboard_audit.py --out /tmp/shots

Starts ``backstop dashboard --demo`` on a free port, visits every
viewport/theme combination, writes a full-page PNG plus one crop per panel,
and asserts the in-page invariants the design spec lists. Exits non-zero if
any invariant fails.

The harness is the verifier for the dashboard work: it is the thing that has
to pass before a dashboard change is called done.
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

VIEWPORTS = {
    "desktop": (1440, 900),
    "laptop": (1280, 800),
    "tablet": (820, 1180),
    "mobile": (390, 844),
    "narrow": (320, 700),
}
THEMES = ("dark", "light")

CHROMIUM = os.environ.get("DASHBOARD_AUDIT_CHROMIUM", "/snap/bin/chromium")

# Runs inside the page. Returns a list of failure strings; empty means the
# invariants hold. Written as an IIFE so Playwright evaluates it as an
# expression and gets the array back.
INVARIANTS = """
(() => {
  const fails = [];
  const doc = document;

  // 1. Every tile carries a text status token next to its colour.
  doc.querySelectorAll('.tile').forEach((tile) => {
    const status = tile.querySelector('[data-slot="status"]');
    const text = status ? (status.textContent || '').trim() : '';
    if (!text) fails.push('tile ' + tile.id + ' has no status token');
  });

  // 2. The connection state is not colour-only.
  const label = doc.querySelector('#conn-label');
  if (!label || !(label.textContent || '').trim()) {
    fails.push('connection state has no text label');
  }

  // 3. No table cell is clipped without the table being scrollable.
  doc.querySelectorAll('.table-wrap').forEach((wrap) => {
    if (wrap.hidden) return;
    const scrollable = wrap.scrollWidth > wrap.clientWidth + 1;
    if (scrollable) return;
    const box = wrap.getBoundingClientRect();
    wrap.querySelectorAll('tbody td, tbody th').forEach((cell) => {
      const r = cell.getBoundingClientRect();
      if (r.width === 0) return;
      if (r.right > box.right + 1) {
        fails.push('table cell clipped without scroll: ' + (cell.textContent || '').trim());
      }
    });
  });

  // 4. No panel is stretched: a panel's height is its content's height.
  doc.querySelectorAll('.panel').forEach((panel) => {
    const h = panel.getBoundingClientRect().height;
    const kids = Array.from(panel.children).filter((c) => !c.hidden);
    const used = kids.reduce((sum, c) => {
      const r = c.getBoundingClientRect();
      return sum + (r.height || 0);
    }, 0);
    if (!h || !kids.length) return;
    const cs = getComputedStyle(panel);
    const gap = parseFloat(cs.rowGap) || 0;
    const pad = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
    const border = (parseFloat(cs.borderTopWidth) || 0) +
      (parseFloat(cs.borderBottomWidth) || 0);
    const content = used + gap * Math.max(0, kids.length - 1) + pad + border;
    const extra = h - content;
    if (extra > 24 || (h > 0 && extra > h * 0.55)) {
      const title = panel.querySelector('h2');
      fails.push('panel ' + (title ? title.textContent.trim() : '?') +
        ' is stretched: ' + Math.round(h) + 'px tall for ' +
        Math.round(content) + 'px of content');
    }
  });

  // 5. Every y-axis tick label is a round number.
  doc.querySelectorAll('canvas').forEach((canvas) => {
    const labels = canvas.__tickLabels || [];
    labels.forEach((label) => {
      if (!/^-?[0-9]+(\\.[0-9]+)?(k|M|B)?$/.test(label)) {
        fails.push('axis label is not round: ' + label);
      }
    });
  });

  // 6. Every chart canvas has a text alternative.
  doc.querySelectorAll('.chart-wrap canvas').forEach((canvas) => {
    if (!canvas.getAttribute('role')) fails.push('chart canvas has no role');
    if (!(canvas.getAttribute('aria-label') || '').trim()) {
      fails.push('chart canvas has no aria-label');
    }
  });

  // 7. Every tile's sparkline is fed by a real series, so no tile renders an
  //    empty canvas with a void above it.
  doc.querySelectorAll('.tile').forEach((tile) => {
    const canvas = tile.querySelector('canvas.spark');
    if (!canvas) return;
    if (canvas.__hasData !== true) {
      fails.push('tile ' + tile.id + ' has an empty sparkline');
    }
  });

  // 8. No tile has run away: a tile is a number and a sparkline, not a
  //    page. This catches a canvas whose auto height feeds back on itself.
  doc.querySelectorAll('.tile').forEach((tile) => {
    const h = tile.getBoundingClientRect().height;
    if (h > 420) {
      fails.push('tile ' + tile.id + ' is ' + Math.round(h) + 'px tall');
    }
  });

  // 9. Nothing overflows the viewport horizontally.
  if (doc.documentElement.scrollWidth > window.innerWidth + 1) {
    fails.push('horizontal page overflow: ' + doc.documentElement.scrollWidth +
      ' > ' + window.innerWidth);
  }

  return fails;
})()
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for(url: str, timeout: float = 25.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as res:
                if res.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def slugify(text: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")
    return out or "panel"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="output directory for PNGs")
    parser.add_argument("--url", default=None, help="use an already-running dashboard")
    parser.add_argument("--viewports", default=",".join(VIEWPORTS))
    parser.add_argument("--themes", default=",".join(THEMES))
    parser.add_argument("--settle", type=float, default=1.2,
                        help="seconds to wait after the page loads")
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    panels_dir = out / "panels"
    panels_dir.mkdir(parents=True, exist_ok=True)

    proc = None
    url = args.url
    if url is None:
        port = free_port()
        url = "http://127.0.0.1:%d/" % port
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(root / "src"))
        proc = subprocess.Popen(
            [sys.executable, "-m", "backstop", "dashboard", "--port", str(port),
             "--demo", "--runners", "6", "--cost-model", "gpt-4o",
             "--theme", "auto", "--no-browser"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(root),
        )
        if not wait_for(url):
            proc.terminate()
            print("dashboard did not start", file=sys.stderr)
            return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed; this is a development-only harness",
              file=sys.stderr)
        if proc:
            proc.terminate()
        return 2

    failures = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
            for name in args.viewports.split(","):
                name = name.strip()
                if name not in VIEWPORTS:
                    continue
                width, height = VIEWPORTS[name]
                for theme in args.themes.split(","):
                    theme = theme.strip()
                    if theme not in THEMES:
                        continue
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.goto(url, wait_until="load")
                    # Wait for the demo to publish its first sample, so the
                    # screenshots show a live dashboard rather than a loading
                    # state.
                    try:
                        page.wait_for_function(
                            "() => { const el = document.querySelector('#tile-requests .value');"
                            " return el && el.textContent && el.textContent.trim() !== '--'; }",
                            timeout=25000,
                        )
                    except Exception:
                        pass
                    page.evaluate("t => document.documentElement.dataset.theme = t", theme)
                    page.wait_for_timeout(int(args.settle * 1000))
                    page.screenshot(path=str(out / ("%s-%s.png" % (name, theme))),
                                    full_page=True)
                    # The sticky top bar overlaps an element crop, so it is
                    # unpinned for the crops only. The page's CSP forbids
                    # inline styles, so the CSSOM is used instead.
                    page.evaluate(
                        "() => { const bar = document.querySelector('.topbar');"
                        " if (bar) bar.style.position = 'static'; }")
                    for index, panel in enumerate(page.query_selector_all(".panel")):
                        title = panel.query_selector("h2")
                        slug = slugify(title.text_content() if title else "p%d" % index)
                        try:
                            panel.screenshot(
                                path=str(panels_dir / ("%s-%s-%s.png" % (name, theme, slug)))
                            )
                        except Exception:
                            pass
                    tiles = page.query_selector(".tiles")
                    if tiles is not None:
                        try:
                            tiles.screenshot(
                                path=str(panels_dir / ("%s-%s-tiles.png" % (name, theme)))
                            )
                        except Exception:
                            pass
                    for problem in page.evaluate(INVARIANTS):
                        failures.append("[%s-%s] %s" % (name, theme, problem))
                    page.close()
            browser.close()
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    print("shots written to %s" % out)
    if failures:
        print("\nFAILED INVARIANTS:")
        for line in failures:
            print("  -", line)
        return 1
    print("all invariants hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
