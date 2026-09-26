"""Prove two GIFs decode to identical pixels, frame for frame.

Used to justify shipping a cropped-subframe encoding: the container differs, the
decoded image must not.
"""
import sys
from pathlib import Path
from PIL import Image, ImageChops


def compare(a: Path, b: Path) -> int:
    ia, ib = Image.open(a), Image.open(b)
    na, nb = getattr(ia, "n_frames", 1), getattr(ib, "n_frames", 1)
    if na != nb:
        print(f"  FAIL frame count {na} vs {nb}")
        return 1
    if ia.size != ib.size:
        print(f"  FAIL size {ia.size} vs {ib.size}")
        return 1
    bad = 0
    worst = 0
    for i in range(na):
        ia.seek(i); ib.seek(i)
        fa, fb = ia.convert("RGB"), ib.convert("RGB")
        if fa.size != fb.size:
            print(f"  FAIL frame {i} composite size {fa.size} vs {fb.size}")
            return 1
        diff = ImageChops.difference(fa, fb)
        bbox = diff.getbbox()
        if bbox:
            bad += 1
            px = sum(1 for p in diff.getdata() if p != (0, 0, 0))
            worst = max(worst, px)
            if bad <= 3:
                print(f"  frame {i} differs at {bbox} ({px} px)")
    if bad:
        print(f"  FAIL {bad}/{na} frames differ (worst {worst} px)")
        return 1
    print(f"  OK {na}/{na} frames pixel-identical, {ia.size[0]}x{ia.size[1]}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    print(f"comparing {Path(sys.argv[1]).name} vs {Path(sys.argv[2]).name}")
    raise SystemExit(compare(Path(sys.argv[1]), Path(sys.argv[2])))
