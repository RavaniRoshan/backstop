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

## Known size characteristic

A 414-frame, 1.54-megapixel, full-canvas composite GIF with a scrolling text
ledger costs roughly 20-24MB with this pipeline. Measured alternatives:

| Wallpaper treatment | KB/frame | Total |
|---|---:|---:|
| smooth gradient (shipped) | 55.3 | 23.4MB |
| posterised to 16 colours | 51.3 | 21.7MB |
| flat colour | 46.8 | 19.8MB |

Palette width barely matters (256 -> 32 colours is 15.7 -> 13.5MB): the cost is
LZW entropy over 1.54M pixels per frame, not colour count. The file size target
of 10-12MB in the skill brief is not reachable for a text-dense full-frame
capture; the reference achieves 26.5KB/frame against our ~55KB/frame because its
on-screen text is sparser.
