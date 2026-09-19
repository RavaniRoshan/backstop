---
format: 1920x1080
duration: 85s
message: "Stop agent loops from burning your budget — in-process token budgets for OpenAI and Anthropic"
arc: Hook → Problem → Solution → Code → Demo → Proof → Comparison → CTA
audience: Python developers running AI agents
music: none
mode: autonomous
---

## Frame 1 — The Loop

- scene: Terminal window with agent loop burning tokens unchecked
- duration: 8.046s
- poster: 4.0s
- transition_in: cut
- status: animated
- voiceover: "Two A.M. Your agent is still calling. Step after step — token after token. Nothing in your code can stop it."
- src: compositions/frames/01-looping.html

Dark canvas. A terminal window fades in (center, 70% width). Prompt `$` with blinking cursor. Auto-types: `python agent_loop.py`. Enter. Output streams: `Step 0: calling... ✓`, `Step 1: calling... ✓`, `Step 2: calling...` — accelerating. Counter in top-right corner of terminal: `TOKENS: 50 → 100 → 150 → 200 → 250` in danger red. Faint red danger-glow behind terminal.

## Frame 2 — The Code

- scene: VS Code editor showing the unconstrained agent loop
- duration: 9.064s
- poster: 4.5s
- transition_in: crossfade
- status: animated
- voiceover: "This is the loop that bills you. Ten iterations. No budget. No ceiling. Two hundred fifty tokens gone — and the SDK never even flinched."
- src: compositions/frames/02-code.html

Code editor window replaces terminal. Shows `agent_loop_guard.py` from `examples/agent_loop_guard.py`. Syntax-highlighted Python. The `for step in range(10):` loop is highlighted with a subtle box glow. Label below: `10 iterations · 250 tokens · $0 guardrail` in danger red.

## Frame 3 — The Install

- scene: Terminal running pip install beside architecture flow diagram
- duration: 12.8s
- poster: 5.0s
- transition_in: crossfade
- status: animated
- voiceover: "Backstop stops it. One line. Backstop dot wrap takes your existing client, sets a token budget, and enforces it before the request leaves your process. No proxy. No network hop."
- src: compositions/frames/03-install.html

Split view: left 55% terminal with `$ pip install "backstop-ai"` typed and installed. Right 45% is architecture diagram: `SDK client → BackstopTransport → budget check → original transport → provider`. The `budget check` node pulses volt green.

## Frame 4 — The Wrap

- scene: Code editor showing Backstop.wrap integration lines
- duration: 10.475s
- poster: 5.0s
- transition_in: crossfade
- status: animated
- voiceover: "Import Backstop. Wrap the client. Set the ceiling at one hundred twenty tokens. That's it. The rest of your code doesn't change — the SDK still works the way you wrote it."
- src: compositions/frames/04-wrap.html

Code editor full width. Shows real wrap code from `examples/agent_loop_guard.py`: `client = Backstop.wrap(raw_client, budget=120, ...)`. Sequentially highlights wrap call and budget ceiling. Badge: `✓ CHECKED BEFORE DISPATCH` in volt green with subtle glow.

## Frame 5 — The Demo

- scene: Terminal executing guarded loop and raising BudgetExceededError
- duration: 10.841s
- poster: 7.0s
- transition_in: crossfade
- status: animated
- voiceover: "Run the loop. Step zero — completed. Step one — completed. Step two — blocked. Budget Exceeded Error, raised clean. The loop is dead. Your wallet is fine."
- src: compositions/frames/05-run.html

Terminal window. Auto-types `python agent_loop_guard.py`. Enter. Output streams: Step 0 completed ✓, Step 1 completed ✓, Step 2 BLOCKED ⛔ BudgetExceededError raised. Loop stopped after 2 calls. Sharp push-in on "blocked". Volt glow pulse.

## Frame 6 — The Proof

- scene: Keyless verification test showing 2 allowed and 8 blocked
- duration: 12.774s
- poster: 6.5s
- transition_in: crossfade
- status: animated
- voiceover: "Don't trust me. Run backstop verify. Zero keys. Zero network. Eight checks pass in two seconds. Two allowed, eight blocked, two thousand tokens saved. Verified — offline."
- src: compositions/frames/06-verify.html

Terminal types `backstop verify`. Real verify output appears: offline mock transport, 0 network, 0 keys. Metrics table: 2 allowed, 8 blocked, count-up to 2,000 tokens saved. Full-width `VERIFIED` status bar in volt green.

## Frame 7 — The Comparison

- scene: Side-by-side card comparing unprotected vs wrapped metrics
- duration: 12.565s
- poster: 6.0s
- transition_in: crossfade
- status: animated
- voiceover: "Side by side: unprotected — ten calls, two fifty tokens, no guardrail. Wrapped — three calls, seventy-five tokens, seventy percent reduction. Same code. One wrap call."
- src: compositions/frames/07-compare.html

Two-column comparison card. Left `UNPROTECTED` (danger red): 10 calls, 0 blocked, 250 tokens. Right `WRAPPED` (volt green): 3 completed, 7 blocked, 75 tokens consumed. Delta pulses `-70% REDUCTION`. Bottom rule: `Same code. One wrap call.`

## Frame 8 — CTA

- scene: Logo lockup with pip install command and copy interaction
- duration: 8.124s
- poster: 4.0s
- transition_in: crossfade
- status: animated
- voiceover: "Pip install backstop dash A.I. The repo is open. The proof runs offline. Stop the loop before it bills you."
- src: compositions/frames/08-cta.html

Clean dark canvas. Backstop logo at center top. Command: `pip install "backstop-ai"` in JetBrains Mono 36px volt green. GitHub URL: `github.com/RavaniRoshan/backstop`. Tagline: `Stop agent loops from burning your budget.` Cursor clicks command, select-sweep animates, pill morphs to `✓ Copied`. Holds for 4+ seconds.
