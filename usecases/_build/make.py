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
    "single_play_ok",
    "gif89a",
)


def load_brief(path: Path) -> dict:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.BRIEF


def optimise(path: Path) -> tuple[bool, str]:
    """Re-encode with gifsicle -O1, then PROVE the result is lossless.

    gifsicle -O1 drops the redundant pixels from each frame and leaves the rest
    transparent, which is a ~9x size reduction. The contract cares about the
    DECODED composite, not the container, so the only acceptable proof is that
    every frame still decodes to identical pixels.

    -O2 is not usable: it merges frames whose content is identical, which
    collapses the 414-frame timeline to 58. The settle phase is deliberately
    static, so this always happens.
    """
    import shutil
    import subprocess

    exe = shutil.which("gifsicle")
    if not exe:
        return False, "gifsicle not installed"
    ref = path.with_suffix(".full.gif")
    ref.write_bytes(path.read_bytes())
    tmp = path.with_suffix(".opt.gif")
    r = subprocess.run(
        [exe, "-O1", "--no-warnings", "-o", str(tmp), str(path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not tmp.exists():
        ref.unlink(missing_ok=True)
        return False, f"gifsicle failed: {r.stderr.strip()[:120]}"

    rep = render.validate(tmp)
    gates = ("frames_ok", "size_ok", "delay_bins_ok", "total_ok", "disposal_ok",
             "single_play_ok", "gif89a")
    failed = [g for g in gates if not rep.get(g)]
    if failed:
        tmp.unlink(missing_ok=True); ref.unlink(missing_ok=True)
        return False, f"gates failed: {', '.join(failed)}"

    from verify_identical import compare
    ok = compare(ref, tmp) == 0
    ref.unlink(missing_ok=True)
    if not ok:
        tmp.unlink(missing_ok=True)
        return False, "not pixel-identical"
    before = rep["mb"]
    tmp.replace(path)
    return True, f"{before} MB -> {render.validate(path)['mb']} MB, 414/414 frames identical"


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
    raw_mb = info["bytes"] / 1e6
    ok, note = optimise(out)
    took = time.time() - t0

    rep = render.validate(out)
    st = parse_structure(out)
    print(f"  raw {raw_mb:.2f} MB" + (f"  ->  {note}" if ok else f"  (no optim: {note})"))
    print(f"  {info['frames']} frames  {rep['mb']} MB  "
          f"{rep['total_ms'] / 1000:.1f}s  ({took:.0f}s)")
    print(
        f"  delays {rep['delay_histogram']}  disposal {rep['disposals']}  "
        f"loop {st['loop_extension']}"
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
