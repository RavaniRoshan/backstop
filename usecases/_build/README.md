# demo.gif build pipeline

Renders the terminal demo GIFs in this directory tree, reproducing the frame /
timing / geometry contract of the reference `demo.gif` in the `demo-gif` skill.

## Contract (all hard-gated by `make.py`)

| Property | Value |
|---|---|
| Canvas | 1552x992 (designed at 776x496, exported with a nearest upscale) |
| Frames | 414 full-canvas composites |
| Disposal | 1 on every frame |
| Delays | 100ms x408, 400ms x2, 200ms x4 |
| Runtime | 42.4s |
| Loop | none — plays once (no NETSCAPE extension) |
| Format | GIF89a, 256-colour global palette |

Hard constraints that are also honoured: no fades, no easing, no cursor blink,
no per-character typing animation, discrete whole-row scroll jumps, transient
pill overlays of 1-2 frames, and a dim completed ledger with green `o` /
coral `*`,`+`,`-` status dots.

## Usage

```bash
python3 _build/make.py _build/briefs/<name>.py ../<slug>/demo.gif
```

`make.py` exits non-zero if any gate fails.

## Why the encoder is hand-written

PIL's GIF writer silently merges byte-identical consecutive frames and sums their
durations, which collapsed 414 frames into 36. `gifenc.py` emits one graphic
control extension and one full-canvas image descriptor per frame and never
merges. `gifsicle -O2` is also unusable: it merges frames to save 90% of the
file, which violates the frame contract (414 -> 55 images).

## Why the composition is designed at 1x

The reference is designed at 776x496 and exported at 1552x992 ("text stays
chunky"). Rendering antialiased text directly at 2x roughly doubled the LZW cost
of every frame. Quantising at 1x and then upscaling with NEAREST is both more
faithful and smaller.

## Size optimisation (shipped)

`gifsicle -O1` re-encodes each frame keeping only the pixels that changed and
leaving the rest to the previous frame. Measured on the flagship:

| | before | after |
|---|---:|---:|
| major-end-to-end | 23.47 MB | **2.42 MB** |
| multi-tenant-saas | 24.69 MB | **2.72 MB** |
| agent-fleet-slo | 24.23 MB | **2.46 MB** |
| runaway-eval-loop | 23.78 MB | **2.46 MB** |
| audit-and-compliance | 25.63 MB | **2.84 MB** |
| **total** | **117 MB** | **12.9 MB** |

This is only trusted because it is **proved, not assumed**: `optimise()` keeps a
copy of the full-canvas render and `verify_identical.py` decodes both files and
compares all 414 frames pixel for pixel. If a single pixel differs, or if any
frame/timing gate regresses, the optimised file is discarded and the
full-canvas one is kept. The check is part of the build, not a one-off.

`-O2` is not usable: it merges frames whose content is identical, collapsing the
414-frame timeline to 58. The settle phase is deliberately static, so this always
happens.

## Why the container is not byte-identical

The optimised files store cropped frame rectangles. The contract that matters is
the DECODED composite, and the reference `demo.gif` contains the same kind of
patch rectangles from its screen recorder. The decoded image is identical, which
is what `verify_identical.py` asserts. If you need literal full-canvas
rectangles, skip the optimise step - the renderer still emits them.
