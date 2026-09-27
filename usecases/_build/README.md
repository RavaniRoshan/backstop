# How the demo videos are built

Every video in `usecases/` and the flagship `walkthrough.mp4` is assembled by the
code in [`media/`](./media/). The source of each frame is stated rather than
assumed, because a demo that paraphrases its own product is a demo that drifts
into advertising.

## What is real

**The dashboard frames are screenshots of the product running.** A live
`backstop dashboard --demo` is started, the workload is allowed to drain a real
budget, and Chromium captures the page at scripted seconds:

- full-page frames for the timelapses
- CSS-selector element captures (`article.panel:has(#chart-traffic)` and so on)
  for the panels, so a focus ring lands on the pixels it names instead of on
  coordinates somebody guessed

The per-tenant frame comes from [`media/tenants.py`](./media/tenants.py), which
registers genuine `TenantBudget`s against a real `BackstopState` and drives real
requests through wrapped `openai` clients under `with_budget(...)`. `initech`
really does exhaust its own ceiling at 0 remaining while the other three keep
spending. The `--demo` workload does not register tenants, so its Tenants panel
is permanently empty and a multi-tenant demo built on it would be fiction.

**The terminal frames are verbatim stdout.** Captured by running `backstop demo`,
`backstop ledger demo` and `backstop reconcile --demo`. `terminal.py` refuses to
render any text that a capture did not write — it raises rather than typesetting
a hand-written terminal — so a scene cannot drift into paraphrasing the CLI.

**The motion is ours.** Cuts, focus rings, arrows, column bands, lower-thirds and
caption timing are all composed here. Nothing in a frame is a mock-up of a screen
the product does not have.

## Captions cannot outrun the footage

On-screen figures are interpolated from the same read that took each screenshot
(`figures.json`), so a number can never be quoted for a second the viewer is not
looking at. This caught a real lie during the build: a caption reading "requests/s
falls as prevented/s rises" sat over a frame showing the *end* state, with t=78
figures beside a t=95 chart.

## Rebuilding

The capture step writes to `/tmp/opencode/media/capture` and the compositors read
from there, so the inputs are declared at the top of each file (`CAP`, `DASH`,
`CLI`, `ARC`, `TEN`). In order:

1. Start the dashboard and the tenant harness on their ports.
2. Capture pages and cards with Playwright, writing `figures.json` alongside.
3. `python3 _build/media/flagship.py` — the 132-second walkthrough.
4. `python3 _build/media/usecases.py` — the five per-usecase videos.

Output lands in `/tmp/opencode/media/out`; the committed MP4s and their poster
stills are copied into `usecases/<name>/demo.mp4` and `demo.png`.

## Why MP4 and not GIF

The previous set was five variations on one synthetic terminal canvas, rendered
as 256-colour GIF89a. That format was why they looked broken: a 256-entry palette
dithers badly over a dark UI, and a 12.9MB animated GIF gets resampled into mush
by anything that downsamples it. The resolution was never the problem. H.264 is
full colour, a fraction of the weight, and GitHub renders a poster still plus a
link rather than a downsampled animation.
