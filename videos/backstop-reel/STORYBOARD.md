---
format: 1080x1920
duration: 15s
message: "Stop agent loops from burning your budget — in-process token budgets for OpenAI and Anthropic"
arc: Hook → Solution → Demo → Proof → CTA
audience: Python developers running AI agents
music: none
mode: autonomous
---

## Frame 1 — Hook

- scene: Kinetic counter showing 250 tokens burned in 10 seconds
- duration: 4.415s
- poster: 1.5s
- transition_in: cut
- status: animated
- voiceover: "Your agent loop just burned two hundred fifty tokens. In ten seconds."
- src: compositions/frames/01-hook.html

Full-bleed dark canvas. Large kinetic text (top 40%): `250 TOKENS BURNED` in danger red (Inter 800 64px), `IN 10 SECONDS` in ink 32px. Fast counter runs 0→250. Terminal card below showing unchecked steps scrolling up.

## Frame 2 — The Fix

- scene: Full-bleed code card showing Backstop.wrap one-liner
- duration: 5.224s
- poster: 1.7s
- transition_in: crossfade
- status: animated
- voiceover: "One wrap call stops it. Backstop dot wrap — in-process budget, no proxy."
- src: compositions/frames/02-reveal.html

Full-bleed code card with syntax-highlighted Python: `client = Backstop.wrap(client, budget=120)`. `Backstop.wrap` highlighted in volt green. Label: `ONE LINE. IN-PROCESS. NO PROXY.`

## Frame 3 — Blocked

- scene: Terminal card showing call blocked with 7 blocked metric
- duration: 4.754s
- poster: 1.5s
- transition_in: crossfade
- status: animated
- voiceover: "Run it. Three calls pass. Seven blocked. Seventy percent saved."
- src: compositions/frames/03-blocked.html

Terminal card with real output: Step 0 completed ✓, Step 1 completed ✓, Step 2 BLOCKED ⛔. Large number lockup below terminal: `7 BLOCKED` in volt green, `−70%` badge.

## Frame 4 — Verified

- scene: Verification card with checks and full-width VERIFIED badge
- duration: 5.825s
- poster: 1.5s
- transition_in: crossfade
- status: animated
- voiceover: "Backstop verify. Zero keys. Zero network. Verified offline."
- src: compositions/frames/04-proof.html

Clean card: `$ backstop verify`. Three check rows: `✓ 2 allowed`, `✓ 8 blocked`, `✓ 2,000 tokens saved`. Full-width `VERIFIED` volt badge at bottom.

## Frame 5 — CTA

- scene: Backstop logo and pip install command holding for 2.5s
- duration: 4.415s
- poster: 1.2s
- transition_in: crossfade
- status: animated
- voiceover: "Pip install backstop dash A.I. Stop the loop."
- src: compositions/frames/05-cta.html

Backstop logo at top. `pip install "backstop-ai"` in volt green monospace 28px. `github.com/RavaniRoshan/backstop`. Holds cleanly to video end.
