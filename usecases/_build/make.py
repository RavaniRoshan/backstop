"""Build one demo GIF from a brief module.

    python3 make.py briefs/major-end-to-end.py ../major-end-to-end/demo.gif

A brief module exposes `BRIEF` (a dict) and may expose `OUT_NAME`. Running this
script renders and then validates against the frame/timing contract; it exits
non-zero if any hard gate fails.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import render  # noqa: E402
from gifenc import parse_structure  # noqa: E402

GATES = (
    "frames_ok",
    "size_ok",
    "delay_bins_ok",
    "total_ok",
    "disposal_ok",
    "full_canvas_ok",
    "single_play_ok",
    "gif89a",
)


def load_brief(path: Path) -> dict:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.BRIEF


def optimise_with_gifsicle(path: Path) -> bool:
    """Re-compress with gifsicle's LZW, which is ~23% tighter than ours.

    Only kept if the result STILL passes every hard gate: gifsicle is free to
    merge identical frames or alter disposal, and this project's contract is
    414 discrete full-canvas composites with a specific delay histogram.
    """
    import shutil
    import subprocess

    exe = shutil.which("gifsicle")
    if not exe:
        return False
    tmp = path.with_suffix(".opt.gif")
    r = subprocess.run(
        [exe, "-O2", "--no-warnings", "-o", str(tmp), str(path)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not tmp.exists():
        return False

    before = render.validate(path)
    after = render.validate(tmp)
    gates = ("frames_ok", "size_ok", "delay_bins_ok", "total_ok", "disposal_ok",
             "full_canvas_ok", "single_play_ok", "gif89a")
    if not all(after.get(g) for g in gates):
        tmp.unlink(missing_ok=True)
        return False
    if after["frames"] != before["frames"] or after["mb"] >= before["mb"]:
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(path)
    return True


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    brief_path = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve()

    brief = load_brief(brief_path)
    t0 = time.time()
    print(f"rendering {brief_path.name} -> {out}")
    info = render.render(brief, out, verbose=False)
    print(f"  raw {info['bytes'] / 1e6:.2f} MB", end="")
    if optimise_with_gifsicle(out):
        print(f"  -> optimised {out.stat().st_size / 1e6:.2f} MB", end="")
    took = time.time() - t0

    rep = render.validate(out)
    st = parse_structure(out)
    print(f"  ({took:.0f}s)")
    print(
        f"  {info['frames']} frames  {rep['mb']} MB  "
        f"{rep['total_ms'] / 1000:.1f}s"
    )
    print(
        f"  delays {rep['delay_histogram']}  disposal {rep['disposals']}  "
        f"full-canvas {st['full_canvas']}  loop {st['loop_extension']}"
    )
    failed = [g for g in GATES if not rep.get(g)]
    if failed:
        print("  FAIL:", ", ".join(failed))
        print(json.dumps(rep, indent=2))
        return 1
    print("  PASS all gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
