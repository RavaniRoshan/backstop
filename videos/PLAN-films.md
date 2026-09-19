# PLAN-films.md — Backstop Video Production Plan

> **Status:** AWAITING APPROVAL — do not execute until approved.
> **Scope:** Two videos from zero. (A) 16:9 landscape film ~85s. (B) 9:16 vertical reel ~15s.
> **Project dirs:** `videos/backstop-film/` and `videos/backstop-reel/`

---

## Table of Contents

1. [Lessons from the Rejected Videos](#1-lessons-from-the-rejected-videos)
2. [Art Direction](#2-art-direction)
3. [Script A — Landscape Film (~85s)](#3-script-a--landscape-film-85s)
4. [Script B — Vertical Reel (~15s)](#4-script-b--vertical-reel-15s)
5. [Storyboard A — Film](#5-storyboard-a--film)
6. [Storyboard B — Reel](#6-storyboard-b--reel)
7. [Cursor & Camera Choreography](#7-cursor--camera-choreography)
8. [Music / Voice / Caption Plan](#8-music--voice--caption-plan)
9. [Ralph Rubric (10-Point)](#9-ralph-rubric-10-point)
10. [Risk Notes](#10-risk-notes)
11. [Execution Flow](#11-execution-flow)

---

## 1. Lessons from the Rejected Videos

Every failure from the old `backstop-demo/` and `backstop-reels/` dirs is catalogued here as a mandatory fix. Each item has a concrete prescription that the new build must follow.

| # | Failure | Root Cause | Prescription |
|---|---------|-----------|-------------|
| 1 | **Flat, dull color scheme** | Scraped GitHub Primer blues/grays onto a "Code Editorial" preset; called `#0969DA` "coral" | Build a bespoke dark-canvas palette from zero (see §2). No preset remixing of someone else's brand colors. |
| 2 | **Flat-sticker windows** | No shadows, no bezel, radial-gradient wallpaper looked pasted-on | Ground every window with layered `box-shadow` (bezel edge + cast shadow + ambient), apply a rich dark gradient + vignette background — never a raw color. |
| 3 | **Fake macOS desktop** | Built a simulated wallpaper, menu bar with clock/battery, left-aligned dock with cartoon icons | No fake desktop simulation. Product surfaces (terminal, code editor) sit directly on a refined dark canvas. If macOS chrome is needed, it's minimal: traffic lights + title bar only. Dock solved separately (see §10). |
| 4 | **GUI buttons inside terminals** | Added "▶ Run loop" pills inside a zsh prompt | All terminal interaction is authentic CLI: `$` prompt → typed command with blinking cursor → Enter → streaming output. Zero GUI elements in terminal. |
| 5 | **Script/DOM desync** | Voice script was revised but HTML still showed old text; on-screen said "Your agent won't stop" while voice said "Two in the morning" | Single source of truth: `SCRIPT.md` drives voice AND informs all on-screen text. Every frame's key text must be checked against the script line it accompanies. |
| 6 | **Duration mismatches** | Sub-composition `data-duration` differed from `index.html` host durations by up to 1.9s; caused blank frames and cut-off animations | Enforce `data-duration` parity: sub-comp duration = host duration exactly. `sync-durations` output is final — no hand-editing. |
| 7 | **Blank final frame (Reels)** | Frame 5 internal clips ended at 3.051s but host gave 3.553s | Every frame's internal GSAP timeline must fill its full host duration. Final hold state persists to end. |
| 8 | **White void (Reels)** | Set `cream: "#ffffff"`, content occupied 15% of 9:16 canvas | Full-bleed layouts for vertical. Content fills top 83% with deliberate hierarchy. Background is never `#fff`. |
| 9 | **Inter called a serif** | Frame.md claimed "Inter is a warm old-style serif" — copy-paste error | Accurate font descriptions. Inter = humanist sans. EB Garamond = old-style serif. |
| 10 | **Blind SHIP verdict** | PROGRESS.md declared SHIP without checking rendered snapshots | Ralph loop: extract frames from MP4, critique against 10-point rubric, log every finding. Never SHIP with unchecked snapshots. |
| 11 | **Zoom clipping** | Camera zoom (`scale: 1.55`) sliced off menu bar, traffic lights, sidebar text | All zoom targets must be self-contained layers. Zoom wrapper clips to content area only — never zoom the full desktop chrome. |
| 12 | **Triple pill collision** | Badge, step caption, and karaoke subtitle all stacked in bottom 30% | Bottom 17% = caption keep-out. Maximum one overlay element above captions at any time. |
| 13 | **Robotic VO script** | Generic "AI-explains-AI" copy with no hook, no stakes, no rhythm | Campaign-grade copy (see §3, §4). Hook in 3s with scene + stakes. Zero AI-tells. |

---

## 2. Art Direction

### 2.1 Palette — "Obsidian Terminal"

Inspired by Linear/Raycast launch films: deep dark canvas, one electric accent, cinematic contrast. NOT the old GitHub-blue-on-gray.

| Token | Hex | Role | Justification |
|-------|-----|------|--------------|
| `canvas` | `#0C0C0E` | Background, full-bleed ground | Near-black with warm undertone — avoids dead `#000` while giving cinematic depth for glow effects. |
| `surface` | `#1A1A1F` | Window/card backgrounds, terminal chrome | One step up from canvas — creates layered depth without looking pasted-on. |
| `surface-elevated` | `#252529` | Active code editor, focused terminal | Third depth level — the surface the viewer's eye lands on. |
| `ink` | `#E8E4DF` | Primary text, headings | Warm off-white — softer than pure `#fff`, reads as paper-on-dark. |
| `ink-muted` | `#8A8690` | Secondary text, labels, comments | Purple-tinted gray for code comments and supporting text. |
| `volt` | `#22D67A` | Primary accent — success states, the "guardrail caught it" moment | Electric green — signals safety/protection without being GitHub-green. Earned: appears only when Backstop blocks a call. |
| `volt-glow` | `#22D67A` at 15% opacity | Glow halos behind success moments | Sparingly used radial glow behind key numbers. |
| `danger` | `#F04438` | The runaway loop, error states, "unprotected" column | Red that says "your money is burning" — creates visceral contrast with volt-green. |
| `danger-glow` | `#F04438` at 12% opacity | Subtle glow behind the "before" state | Used once in the comparison frame. |
| `code-bg` | `#13131A` | Code block interior | Slightly blue-shifted dark — reads as "this is a code surface." |

### 2.2 Typography

| Role | Font | Weight | Size (film / reel) | Notes |
|------|------|--------|-------------------|-------|
| Display headline | **Inter** | 800 | 72px / 64px | Clean, authoritative, not decorative. |
| Body / narrative text | **Inter** | 400 | 28px / 24px | Readable at video resolution. |
| Code / terminal | **JetBrains Mono** | 400 | 22px / 20px | Monospace for all code and CLI output. |
| Code bold / keywords | **JetBrains Mono** | 700 | 22px / 20px | Python keywords, emphasis in terminal. |
| Numbers / metrics | **Inter** | 700 | 48px / 40px | Large, clean numbers for stats. |
| Kicker / label | **Inter** | 600 | 16px / 14px | ALL-CAPS letter-spacing: 0.08em for micro-labels. |

**Font files to stage** (copy from old `assets/fonts/` before deletion):
- `Inter-400.woff2`, `Inter-700.woff2`
- `JetBrainsMono-400.woff2`, `JetBrainsMono-700.woff2`

> No EB Garamond in this build — the serif doesn't serve a CLI developer product. No Mona Sans (ships no files). All `@font-face` declarations use local woff2 files only.

### 2.3 Lighting & Depth

Every window and surface is grounded with:

1. **Bezel edge**: 1px `inset 0 1px 0 rgba(255,255,255,0.06)` top highlight — simulates aluminum edge catching light.
2. **Cast shadow**: `0 24px 48px rgba(0,0,0,0.4)` — deep, directional, angled slightly down-right.
3. **Ambient shadow**: `0 8px 16px rgba(0,0,0,0.2)` — soft fill shadow.
4. **Background depth**: Canvas is not flat `#0C0C0E` — it carries a subtle radial gradient vignette:
   - Center: `#0C0C0E` → Edge: `#060608`
   - Plus a very faint noise texture overlay at 3% opacity.
5. **Window reflections**: Extremely subtle gradient on window title bars: `linear-gradient(180deg, rgba(255,255,255,0.03) 0%, transparent 100%)`.

### 2.4 macOS Chrome Rules

When a terminal or code editor window appears:

- **Title bar**: 32px height, `surface` background, centered filename/title in `ink-muted` 13px Inter 500.
- **Traffic lights**: Left-aligned at 12px from left edge, vertically centered in title bar. Three circles: `#FF5F57` (close), `#FEBC2E` (minimize), `#28C840` (maximize). 12px diameter, 8px gap.
- **No menu bar**: We are NOT simulating a full macOS desktop. The window IS the frame.
- **No dock**: Dock is omitted entirely from the Film. The Reel has no dock either — full-bleed cards.
- **Window corners**: `border-radius: 10px` with `overflow: hidden`.

### 2.5 Decorative Elements (Background Layer)

Per scene, ambient elements are strictly restrained. Overusing glow reads as "cheap AI" to developers.

- **Accent glow (Restrained)**: A single, extremely faint `volt-glow` or `danger-glow` behind the active window. Max 10% opacity. No breathing scale animations—keep it static.
- **Grid lines**: Faint `rgba(255,255,255,0.02)` grid pattern at 80px spacing — creates depth without distraction.
- **Gradient streak**: Very subtle diagonal light sweep across the canvas at 2% opacity.

The canvas must feel like a precision tool, not a neon cyberpunk ad.

---

## 3. Script A — Landscape Film (~85s)

**Voice direction:** HeyGen Edmund (male, Firm & Measured). Direct like a trailer narrator: deliberate pace, pauses before numbers land, drops pitch on the payoff lines. NOT a reader — a performer. Emphasis marks: **bold** = louder/slower, *italic* = softer/contemplative, `[pause 0.5s]` = held silence.

**Target: ~210 words at 2.5 w/s = 84s**

---

**Line 1** (0.0–8.0s) — Hook + stakes
> *Two A.M.* [pause 0.3s] Your agent is still calling. [pause 0.2s] Step after step — token after token. **Nothing in your code can stop it.**

**Line 2** (8.0–17.5s) — The problem, made concrete
> This is the loop that bills you. Ten iterations. No budget. No ceiling. Two hundred fifty tokens gone — and the SDK never even flinched.

**Line 3** (17.5–28.0s) — The product entrance
> Backstop stops it. One line. `Backstop dot wrap` takes your existing client, sets a token budget, and enforces it **before the request leaves your process.** No proxy. No network hop.

**Line 4** (28.0–38.0s) — The code, walked through
> Import Backstop. Wrap the client. Set the ceiling at one hundred twenty tokens. That's it. The rest of your code doesn't change — the SDK still works the way you wrote it.

**Line 5** (38.0–52.0s) — The demo, live
> Run the loop. Step zero — completed. Step one — completed. Step two — [pause 0.3s] **blocked.** Budget Exceeded Error, raised clean. The loop is dead. Your wallet is fine.

**Line 6** (52.0–65.0s) — The proof
> Don't trust me. Run `backstop verify`. [pause 0.2s] Zero keys. Zero network. Eight checks pass in two seconds. Two allowed, eight blocked, **two thousand tokens saved.** Verified — offline.

**Line 7** (65.0–77.0s) — The comparison
> Side by side: unprotected — ten calls, two fifty tokens, no guardrail. Wrapped — three calls, seventy-five tokens, **seventy percent reduction.** Same code. One wrap call.

**Line 8** (77.0–85.0s) — CTA
> `pip install backstop dash A.I.` [pause 0.3s] The repo is open. The proof runs offline. **Stop the loop before it bills you.**

**Word count: ~207 words. At 2.5 w/s = ~83s.**

---

## 4. Script B — Vertical Reel (~15s)

**Voice direction:** Same Edmund voice, but faster, punchier. Trailer energy compressed into 15s. Every word earns its place.

**Target: ~37 words at 2.5 w/s = ~15s**

---

**Line 1** (0.0–3.0s) — Hook
> Your agent loop just burned two hundred fifty tokens. [pause 0.2s] In ten seconds.

**Line 2** (3.0–6.5s) — The fix
> One wrap call stops it. `Backstop dot wrap` — in-process budget, no proxy.

**Line 3** (6.5–9.5s) — The proof
> Run it. Three calls pass. Seven **blocked.** Seventy percent saved.

**Line 4** (9.5–12.5s) — The verification
> `backstop verify.` Zero keys. Zero network. **Verified offline.**

**Line 5** (12.5–15.0s) — CTA
> `pip install backstop dash A.I.` Stop the loop.

**Word count: ~52 words. At ~3.5 w/s = ~15s (faster pacing for Reels).**

---

## 5. Storyboard A — Film

> **Format:** 1920×1080 16:9 | **Duration:** ~85s | **Frames:** 8

### Frame 01 — "The Loop" (0.0–8.0s)

| Property | Value |
|----------|-------|
| **Beat** | Hook — scene + stakes |
| **VO line** | Line 1 |
| **On screen** | Dark canvas. A terminal window fades in (center, 70% width). Prompt `$` with blinking cursor. Auto-types: `python agent_loop.py`. Enter. Output streams: `Step 0: calling... ✓`, `Step 1: calling... ✓`, `Step 2: calling...` — the steps keep coming, accelerating. A counter in the top-right corner of the terminal: `TOKENS: 50 → 100 → 150 → 200 → 250` counting up in `danger` red, each increment faster. |
| **Camera** | Static — no zoom. Let the terminal own the frame. |
| **Cursor** | macOS arrow appears at 6s, drifts toward terminal but doesn't click — helpless observer. |
| **Decoratives** | Faint red `danger-glow` pulses behind the terminal, breathing with each token increment. Grid lines on canvas. |
| **Transition out** | Slow fade to black over 0.3s. |
| **Why** | Opens with a specific scene (2 AM, loop running) — not abstract. The accelerating counter creates visceral stakes. |

### Frame 02 — "The Code" (8.0–17.5s)

| Property | Value |
|----------|-------|
| **Beat** | Problem deepened, then product entrance |
| **VO line** | Line 2 |
| **On screen** | Code editor window replaces terminal (same position, crossfade). Shows `agent_loop_guard.py` — the REAL code from `examples/agent_loop_guard.py`. Syntax-highlighted Python. The `for step in range(10):` loop is visible. Highlight the loop with a subtle box glow. A small label appears: `10 iterations · 250 tokens · $0 guardrail` in `danger` red, positioned below the code block. |
| **Camera** | Slow push-in (scale 1.0→1.1 over 9.5s) — draws viewer into the code. |
| **Cursor** | Resting on the `range(10)` — 1s hold, then moves to the loop body. |
| **Decoratives** | Faint code-line numbers in `ink-muted`. Red glow behind the "no guardrail" label. |
| **Transition out** | Code editor slides left, new content slides in from right (0.4s). |
| **Why** | Shows the actual product code — not a generic illustration. The viewer sees the real vulnerability. |

### Frame 03 — "The Install" (17.5–28.0s)

| Property | Value |
|----------|-------|
| **Beat** | Product entrance — the fix |
| **VO line** | Line 3 |
| **On screen** | Split: left 55% is a terminal with `$ pip install "backstop-ai"` typed, then output streaming (Collecting backstop-ai, Installing..., Successfully installed backstop-ai-0.6.0). Right 45% is a diagram: `SDK client → BackstopTransport → budget check → original transport → provider` — the real architecture from README, rendered as a clean horizontal flow with arrows. The `budget check` node pulses `volt` green. |
| **Camera** | Static — information-dense frame, no movement needed. |
| **Cursor** | Lands on terminal, 1s rest, then the install command auto-types. |
| **Decoratives** | Subtle `volt-glow` radiates outward from the architecture diagram's center node when "before the request leaves your process" is spoken. |
| **Transition out** | Whole frame fades, replaced by frame 04. |
| **Why** | "One line" claim proven immediately with the real install + real architecture. Not abstract — the viewer sees the pipeline. |

### Frame 04 — "The Wrap" (28.0–38.0s)

| Property | Value |
|----------|-------|
| **Beat** | The integration — walked through |
| **VO line** | Line 4 |
| **On screen** | Code editor, full width (80%). Shows the REAL wrap code from examples/agent_loop_guard.py, lines 53–57:```python client = Backstop.wrap(raw_client, budget=120, config=BackstopConfig(default_max_output_tokens=30, retry_max_attempts=1))```Each line highlights sequentially as the VO walks through it. `Backstop.wrap` gets a `volt` green highlight box when spoken. `budget=120` gets an underline animation when "one hundred twenty tokens" is spoken. A small badge fades in below the code: `✓ CHECKED BEFORE DISPATCH` in `volt` green with a subtle glow. |
| **Camera** | Gentle push-in (1.0→1.08) focused on the wrap call. |
| **Cursor** | Pixel-exact on `Backstop.wrap(` at 29s. 1s rest. Moves to `budget=120` at 33s. 1s rest. |
| **Decoratives** | Grid lines fade to 1% during code focus. Single `volt-glow` behind the badge. |
| **Transition out** | Code editor morphs into terminal (title bar text changes, content crossfades 0.3s). |
| **Why** | The viewer sees the EXACT code they'd write. Three highlighted lines. That's the entire integration. |

### Frame 05 — "The Demo" (38.0–52.0s)

| Property | Value |
|----------|-------|
| **Beat** | Live proof — the loop runs and gets stopped |
| **VO line** | Line 5 |
| **On screen** | Terminal window (full width 80%). Prompt. Cursor auto-types `python agent_loop_guard.py`. Enter. Output streams line by line, matching the REAL output:```Step 0: completed — 'step output' ✓Step 1: completed — 'step output' ✓Step 2: BLOCKED — BudgetExceededError raised ⛔Loop stopped after 2 calls. No further spend possible.```Steps 0–1 appear in `ink` (normal). Step 2 appears in `volt` green with a flash. The `BudgetExceededError` text gets a highlight box in `volt`. A large `⛔ → ✓` icon transition plays center-right when "blocked" is spoken — red circle morphs to green check. |
| **Camera** | Static until "blocked" — then a sharp 0.2s push-in (1.0→1.15) on the BLOCKED line. Holds zoomed. |
| **Cursor** | Resting on the command line initially. No interaction during output — this is the computer responding. |
| **Decoratives** | At "blocked" — `volt-glow` radiates outward from the terminal in a single pulse. Canvas grid shifts from red-tinted to green-tinted. |
| **Transition out** | Terminal slides up slightly, new terminal slides in from below (0.3s). |
| **Why** | This is THE moment — the product delivering its promise in real-time. The push-in camera on "blocked" makes it visceral. Real CLI output, not a simulation. |

### Frame 06 — "The Proof" (52.0–65.0s)

| Property | Value |
|----------|-------|
| **Beat** | Verification — don't trust me |
| **VO line** | Line 6 |
| **On screen** | Terminal. Types `backstop verify`. Output streams — the REAL verify output (verbatim from README):```# Backstop Verify — 30-Second Keyless Proof Mode: offline (100% local mock transport, zero network, zero API keys)```Then the metrics table appears row by row:```Allowed calls: 2Blocked calls: 8Tokens saved: 2,000Status: VERIFIED```Each row animates in with a `volt` green check appearing left of it. The `2,000` number does a count-up animation from 0. The `VERIFIED` status gets a full-width `volt` highlight bar. |
| **Camera** | Slow pull-back (1.15→1.0) — revealing the full proof after the zoomed-in demo. |
| **Cursor** | Lands on prompt, 1s rest, types `backstop verify`. Then no cursor during output. |
| **Decoratives** | Each metric row's check mark leaves a lingering `volt-glow` dot. When VERIFIED appears, a brief full-canvas `volt-glow` pulse. |
| **Transition out** | Crossfade (0.4s). |
| **Why** | "Don't trust me" — then proves it with zero keys. The count-up on 2,000 tokens saved is the payoff number. |

### Frame 07 — "The Comparison" (65.0–77.0s)

| Property | Value |
|----------|-------|
| **Beat** | Side-by-side proof |
| **VO line** | Line 7 |
| **On screen** | Two-column comparison card (centered, 85% width). Left column header: `UNPROTECTED` in `danger` red. Right column header: `WRAPPED` in `volt` green. Three metric rows animate in sequentially:```Calls completed: 10 → 3Calls blocked: 0 → 7Tokens consumed: 250 → 75```Each row has left number in `danger`, right number in `volt`. The delta column (`-70%`) pulses when "seventy percent reduction" is spoken. A bottom bar: `Same code. One wrap call.` in `ink` with a thin `volt` underline. |
| **Camera** | Static — let the numbers speak. |
| **Cursor** | Not present — this is a data frame, not an interaction frame. |
| **Decoratives** | `danger-glow` behind left column, `volt-glow` behind right column. Both subtle. |
| **Transition out** | Comparison card scales down slightly and fades (0.3s). |
| **Why** | Concrete specifics. The viewer sees the exact numbers from `backstop demo`. The seventy-percent delta is the shareable stat. |

### Frame 08 — "CTA" (77.0–85.0s)

| Property | Value |
|----------|-------|
| **Beat** | Close — CTA in plain language |
| **VO line** | Line 8 |
| **On screen** | Clean dark canvas. Center: `pip install "backstop-ai"` in `JetBrains Mono` 36px, `volt` green, with a subtle glow. Below it: `github.com/RavaniRoshan/backstop` in `ink-muted` 20px. Above the install line: the Backstop logo (`assets/backstop-logo.svg`) at comfortable size. Below the GitHub URL: tagline `Stop agent loops from burning your budget.` in `ink` 24px Inter 400. Hold for 4+ seconds — this is the frame a viewer screenshots. |
| **Camera** | Static — logo lockup. |
| **Cursor** | macOS arrow appears, lands on the install command, 1s rest, click ripple. The command text briefly highlights as if "copied" — a green check `✓ Copied` pill fades in right of the command for 1.5s. |
| **Decoratives** | Very subtle `volt-glow` behind the logo. Grid lines at 1% opacity. |
| **Transition out** | None — hold to black. |
| **Why** | "The quickstart lives in the repo" — the viewer sees it. Copy animation sells "you could do this right now." |

---

## 6. Storyboard B — Reel

> **Format:** 1080×1920 9:16 | **Duration:** ~15s | **Frames:** 5

### Frame 01 — "Hook" (0.0–3.0s)

| Property | Value |
|----------|-------|
| **VO line** | Line 1 |
| **On screen** | Full-bleed dark canvas. Large kinetic text (top 40%): `250 TOKENS BURNED` in `danger` red, 64px Inter 800. Below it: `IN 10 SECONDS` in `ink` 32px. A token counter runs from 0→250 in `danger` red (top-right corner, monospace). Below the text block: a compact terminal snippet showing `Step 9: calling... ✓` with the last 3 steps visible, scrolling up. |
| **Camera** | Static — text impact. |
| **Why** | Opens with a number that shocks in the very first 1,000 milliseconds. Developers instantly recognize terminal output; product is visible before 3s. |

### Frame 02 — "The Fix" (3.0–6.5s)

| Property | Value |
|----------|-------|
| **VO line** | Line 2 |
| **On screen** | Code card (full-width, rounded corners, 60% of vertical space). Shows:```python client = Backstop.wrap(client, budget=120)```in syntax-highlighted Python. `Backstop.wrap` highlighted in `volt` green. Below the code card: `ONE LINE. IN-PROCESS. NO PROXY.` in Inter 700, 20px, `ink`, letter-spaced. |
| **Camera** | Gentle scale-up (0.95→1.0) — card "arrives" with presence. |
| **Why** | The entire integration in one glance. Vertical-native layout fills the frame. |

### Frame 03 — "Blocked" (6.5–9.5s)

| Property | Value |
|----------|-------|
| **VO line** | Line 3 |
| **On screen** | Terminal card (full-width). Output:```Step 0: completed ✓Step 1: completed ✓Step 2: BLOCKED ⛔```The BLOCKED line flashes `volt` green. Large number lockup below terminal: `7 BLOCKED` in `volt` 56px / `−70%` in `volt` 40px. |
| **Camera** | Sharp push-in (1.0→1.1) on "blocked" — 0.15s. |
| **Why** | The product moment. Seven blocked in volt-green = the visual takeaway. |

### Frame 04 — "Verified" (9.5–12.5s)

| Property | Value |
|----------|-------|
| **VO line** | Line 4 |
| **On screen** | Clean card. Top: `$ backstop verify` in monospace. Below: three-row mini-table:```✓ 2 allowed✓ 8 blocked✓ 2,000 tokens saved```Each check in `volt` green. Bottom: large `VERIFIED` badge — full-width `volt` green bar with white text. |
| **Camera** | Static. |
| **Why** | Proof. The VERIFIED badge is the trust signal. |

### Frame 05 — "CTA" (12.5–15.0s)

| Property | Value |
|----------|-------|
| **VO line** | Line 5 |
| **On screen** | Backstop logo (centered, top third). Below: `pip install "backstop-ai"` in `volt` green monospace 28px. Below: `github.com/RavaniRoshan/backstop` in `ink-muted` 16px. Hold 2.5s — screenshottable. |
| **Camera** | Static — lockup. |
| **Why** | Plain-language CTA. No "learn more" — the install command IS the CTA. |

---

## 7. Cursor & Camera Choreography

### Typing & Code Reveal Rules (Mandatory)

1. **Typing Rhythm**: Never use smooth CSS fades or linear width reveals for code typing. Code must appear character-by-character using stepped timing functions (e.g., CSS `steps(n)`).
2. **Terminal Cursors**: Terminal cursors must blink using a `step-end` timing function (instant toggle between 0 and 100 opacity). Smooth fading cursors destroy terminal authenticity.
3. **Staggered Delays**: When auto-typing commands, use staggered, uneven delays between words or lines to accurately simulate human typing cadence.

### Cursor Rules (Both Videos)

1. **Appearance**: macOS arrow cursor — black fill, white 1px stroke outline. SVG asset, not an emoji.
2. **Pixel-exact targeting**: Cursor tip lands exactly on the target element (the first character of a command, the function name, the button center).
3. **1-second rest before every click**: Cursor arrives → holds 1.0s motionless → click ripple animates (concentric ring in `volt` at 50% opacity, expanding + fading over 0.3s).
4. **Movement easing**: `power2.inOut` — smooth deceleration into each target.
5. **Movement speed**: ~400px/s — deliberate, not frantic.
6. **Cursor presence schedule** (Film):
   - Frame 01: Appears at 6s, drifts helplessly toward terminal. No click.
   - Frame 02: On `range(10)` at 10s, moves to loop body at 14s.
   - Frame 03: On terminal prompt, types install command.
   - Frame 04: On `Backstop.wrap(` at 29s, on `budget=120` at 33s.
   - Frame 05: On command prompt for `python agent_loop_guard.py`. No cursor during output.
   - Frame 06: On prompt for `backstop verify`. No cursor during output.
   - Frame 07: No cursor — data visualization frame.
   - Frame 08: On install command. Click ripple → "✓ Copied" pill.
7. **Cursor presence schedule** (Reel): No cursor. 15s is too short for cursor choreography — all animations are automatic.

### Camera Rules

1. **Push-in**: `scale` tween on a wrapper div inside the clip — never on the clip element itself.
2. **Max zoom**: 1.15x — beyond this, text becomes unreadable at 1080p.
3. **Zoom wrapper**: Self-contained. Only the content area zooms — window chrome (traffic lights, title bar) stays at 1.0x by being on a separate layer.
4. **Lateral movement**: Use `x`/`y` GSAP transforms only. Never `left`/`top`.
5. **Easing**: `power2.inOut` for push-ins, `power2.out` for pull-backs.

### Copy Animation (Film Frame 08 — "Copied")

1. Cursor lands on install command text (1s rest).
2. Click ripple animates.
3. A select-sweep highlight (blue selection) animates left→right across the command text (0.3s).
4. A small pill appears right of the command: first shows `📋 Copy` (0.2s), then morphs to `✓ Copied` in `volt` green (0.3s).
5. The pill fades out after 1.5s.

---

## 8. Music / Voice / Caption Plan

### Voice

| Property | Value |
|----------|-------|
| Provider | HeyGen TTS |
| Voice | Edmund — `0e2ff5b962084420879e076a2345d13f` (male, Firm & Measured, English) |
| Direction | Trailer narrator, not a reader. Drops pitch on payoff lines. Pauses before numbers. |
| Auth | `npx hyperframes auth refresh` before every audio run. Check `npx hyperframes auth status` first. |

**Word budget per line** (±2 words enforced):

| Film Line | Words | Duration | Words/sec |
|-----------|-------|----------|-----------|
| 1 | 26 | 8.0s | 3.25 |
| 2 | 25 | 9.5s | 2.63 |
| 3 | 30 | 10.5s | 2.86 |
| 4 | 30 | 10.0s | 3.00 |
| 5 | 29 | 14.0s | 2.07 |
| 6 | 27 | 13.0s | 2.08 |
| 7 | 28 | 12.0s | 2.33 |
| 8 | 20 | 8.0s | 2.50 |

### Music (BGM)

| Property | Film | Reel |
|----------|------|------|
| Mood query | `none` | `none` |
| Volume | N/A | N/A |
| Ducking | N/A | N/A |
| Rule | **Zero background music.** | **Zero background music.** |

**Rationale:** The developer community (YC/HN) actively despises background music on technical demos, viewing it as distracting "marketing slickness." The audio track will be Voiceover + Silence. The script `audio.mjs` will be passed `music: none` in the storyboard frontmatter.

### Captions

| Property | Value |
|----------|-------|
| Source | `compositions/captions.html` (generated by `captions.mjs build`) |
| Skin | `.hyperframes/caption-skin.html` (from frame preset, branded to palette) |
| Position | Bottom-center, inside the bottom 17% keep-out zone |
| Style | Semi-transparent dark pill (`rgba(12,12,14,0.85)`), `ink` text, Inter 400 22px |
| Word timing | Karaoke-style from HeyGen word alignments |
| Track | Single `data-track-kind="captions"` track — all caption groups on one `data-track-index` |

### SFX

**No `audio.mjs fetch-sfx`** — this command previously zeroed `audio_meta.json`. Zero SFX in this build. The music bed + voice + visual motion are sufficient.

---

## 9. Ralph Rubric (10-Point)

After every render, extract frames from the MP4, critique against this rubric. Score each criterion PASS/FAIL with evidence. Fix all FAILs, re-render, re-verify.

| # | Criterion | PASS Condition | Inspection Method |
|---|-----------|---------------|-------------------|
| **R1** | **Hook** | Viewer can identify the product's purpose within 3 seconds. First frame shows a real product surface (terminal with running code), not a logo or abstract. | Snapshot at t=1s, t=3s. Is a terminal visible? Is the stakes-text legible? |
| **R2** | **Specificity** | Every number on screen matches the REAL CLI output verbatim. `3 completed`, `7 blocked`, `250→75 tokens`, `2,000 saved`, `−70%`. No invented metrics. | Cross-reference each number against README `backstop demo` and `backstop verify` output. |
| **R3** | **Realism** | Windows look grounded — shadows, bezels, no flat stickers. Terminal interactions are authentic CLI (prompt → type → output). No GUI buttons in terminals. | Snapshot each window frame. Check for box-shadow. Check for any pill/button inside terminal chrome. |
| **R4** | **Cursor** | macOS arrow (black fill, white stroke). Tip lands pixel-exact on target. 1s rest before every click. Click ripple visible. No cursor in data-only frames (Frame 07). | Snapshot at each cursor rest point. Measure tip position against target element. |
| **R5** | **Copy Integrity** | On-screen text complements (never contradicts) the VO. No frame shows text that says something different from what the voice is saying at that moment. | Play through with VO. At each frame boundary, read on-screen text aloud alongside the VO line. Any contradiction = FAIL. |
| **R6** | **AI-Tell Audit** | Zero instances of: "imagine", "what if", "unlock", "seamless", "delve", "dive in", "buckle up", "in the realm of", triple rhetorical questions, "whether you're a seasoned..." | Full-text search of SCRIPT.md and all on-screen text in composition HTML files. |
| **R7** | **Muted Story** | The video tells the complete story with sound OFF (text overlays, visual sequence, numbers). A viewer on mute understands: problem → fix → proof → CTA. | Watch the contact sheet (snapshot at 8 evenly-spaced times). Can you reconstruct the narrative from stills alone? |
| **R8** | **Holds & Timing** | No blank frames. No premature clip unmount. CTA frame holds for ≥3s. Every frame's internal timeline fills its full `data-duration`. | Snapshot at final frame minus 0.5s AND exact final frame. Both must show content (not black/white). Check every sub-comp `data-duration` = host `data-duration`. |
| **R9** | **Captions** | Captions are present, readable, within the bottom 17% band, don't collide with any other UI element. No content in the caption keep-out zone. | Snapshot when captions are most full (longest word group). Check vertical position. Check for overlap with any badge/pill/label. |
| **R10** | **Pacing** | Something new appears every ~8s (Product Hunt convention). No single frame exceeds 14s without a visual change. Transitions are ≤0.4s. | Time each frame. Count visual changes per frame. Any 8s stretch with zero new elements = FAIL. |

### Ralph Loop Protocol

```
ROUND = 0
repeat:
    ROUND += 1
    render MP4
    extract contact sheet + per-frame snapshots
    score R1–R10 (PASS/FAIL + evidence)
    log round to videos/PROGRESS.md
    if all PASS:
        if ROUND >= 2:  # minimum two rounds
            SHIP
        else:
            re-render with no changes to confirm determinism
    else:
        fix each FAIL
        continue
```

---

## 10. Risk Notes

### 10.1 Dock-vs-Captions Collision

**Decision:** No dock. Neither video shows a macOS dock.

Rationale: The dock was the source of multiple layout bugs in the old build (collision with caption band, cartoon icons distracting from product). Backstop is a CLI tool — there is no reason to simulate a macOS desktop. Terminal and code editor windows sit directly on the dark canvas. This eliminates the collision entirely and passes `npx hyperframes check` because there's nothing in the caption keep-out zone except captions.

### 10.2 Zoom-vs-Chrome

**Decision:** Zoom wrappers are self-contained content layers inside windows.

Implementation: Each window has two layers:
- **Chrome layer** (traffic lights, title bar) — never zoomed, never translated.
- **Content layer** (code, terminal output) — this is what the camera push-in targets.

The GSAP `scale` tween targets `.content-wrapper` inside the window, never the window itself. This prevents the zoom-clipping bug from the old build where traffic lights and sidebar text got sliced off.

### 10.3 Font File Path

Font files currently live in `videos/backstop-demo/assets/fonts/` and `videos/backstop-reels/assets/fonts/`. Both directories will be deleted. Before deletion, copy the needed woff2 files to a temp location, then stage them into the new project `assets/fonts/` dirs.

Files to preserve:
- `Inter-400.woff2`, `Inter-700.woff2`
- `JetBrainsMono-400.woff2`, `JetBrainsMono-700.woff2`

### 10.4 HeyGen Auth Expiry

OAuth token expires ~hourly. Before every `audio.mjs` invocation:
1. `npx hyperframes auth status` — check if signed in.
2. `npx hyperframes auth refresh` — refresh the token.
3. If refresh fails, surface the blocker and wait for user sign-in.

### 10.5 GSAP Rules (Mandatory)

- Transforms only: `x`, `y`, `scale`, `opacity`, `rotation`. Never `left`/`top`/`width`/`height`.
- `fromTo` with `immediateRender: false` on repeated targets.
- One paused timeline per frame: `window.__timelines[compositionId] = tl`.
- Full-bleed grounds on `class="clip"` layers, never `#root`.
- Prefix all ids/classes per frame: `d1-` for frame 01, `d2-` for frame 02, etc.
- No `repeat: -1` — finite counts only.
- No CSS `transform` on elements that GSAP also tweens (causes `gsap_css_transform_conflict` lint error).

### 10.6 Caption Track Structure

- All captions live on ONE track: single sub-composition host with one `data-track-index`, marked `data-track-kind="captions"`.
- Captions source: `compositions/captions.html` (generated by `captions.mjs build`).
- Never one row per caption group.
- One clip per `data-track-index` lane (assembler errors on overlap).

### 10.7 Skills Invocation Path

Skill scripts live under a symlinked path. Invoke them via `/home/shiva/.claude/skills/...` (NOT `/home/shiva/.config/...`), or scripts with a main-guard exit silently with code 0.

---

## 11. Execution Flow

The exact file-by-file sequence a second agent could resume from.

### Phase 0: Cleanup & Font Rescue

```bash
# 1. Copy fonts to temp before deletion
mkdir -p /tmp/backstop-fonts
cp videos/backstop-demo/assets/fonts/Inter-400.woff2 /tmp/backstop-fonts/
cp videos/backstop-demo/assets/fonts/Inter-700.woff2 /tmp/backstop-fonts/
cp videos/backstop-demo/assets/fonts/JetBrainsMono-400.woff2 /tmp/backstop-fonts/
cp videos/backstop-demo/assets/fonts/JetBrainsMono-700.woff2 /tmp/backstop-fonts/

# 2. Copy logo
cp videos/backstop-demo/assets/backstop-logo.svg /tmp/backstop-fonts/

# 3. Delete old directories
rm -rf videos/backstop-demo/
rm -rf videos/backstop-reels/
```

### Phase 1: Initialize Projects

```bash
# Film (landscape)
npx hyperframes init "videos/backstop-film" --non-interactive --example=blank --skill=product-launch-video

# Reel (vertical)
npx hyperframes init "videos/backstop-reel" --non-interactive --example=blank --skill=product-launch-video
```

### Phase 2: Write BRIEF.md (Both Projects)

Create `videos/backstop-film/BRIEF.md` and `videos/backstop-reel/BRIEF.md` with:
- Product: Backstop, `pip install "backstop-ai"`, GitHub `RavaniRoshan/backstop`
- Format: `1920x1080` / `1080x1920`
- Duration: `~85s` / `~15s`
- Voice: HeyGen Edmund, male, Firm & Measured
- Music: `none`
- Tone: raw, authentic, developer-focused (no marketing slickness)
- Flow: narrated product launch

### Phase 3: Auth Check

```bash
npx hyperframes auth status
# If signed in → proceed
# If not → npx hyperframes auth refresh
```

### Phase 4: Capture & Design (Both Projects)

```bash
# Capture the GitHub page (optional — we have full README content)
npx hyperframes capture "https://github.com/RavaniRoshan/backstop" -o ./capture --json

# Stage fonts
mkdir -p assets/fonts/
cp /tmp/backstop-fonts/Inter-400.woff2 assets/fonts/
cp /tmp/backstop-fonts/Inter-700.woff2 assets/fonts/
cp /tmp/backstop-fonts/JetBrainsMono-400.woff2 assets/fonts/
cp /tmp/backstop-fonts/JetBrainsMono-700.woff2 assets/fonts/
cp /tmp/backstop-fonts/backstop-logo.svg assets/

# Write frame.md (custom, not preset-remixed — per art direction §2)
# Write capture/extracted/tokens.json with our palette
```

### Phase 5: Storyboard & Script

For each project:
1. Write `SCRIPT.md` (from §3 or §4 of this plan)
2. Write `STORYBOARD.md` (from §5 or §6 of this plan)
3. Verify word counts per line ±2 of budget

### Phase 6: Audio

```bash
# Film
npx hyperframes auth refresh
node <SKILL_DIR>/scripts/audio.mjs \
  --script ./SCRIPT.md \
  --storyboard ./STORYBOARD.md \
  --hyperframes . \
  --out ./audio_meta.json \
  --provider heygen \
  --voice 0e2ff5b962084420879e076a2345d13f &

# Wait for audio, then sync durations
node <SKILL_DIR>/scripts/audio.mjs sync-durations \
  --audio-meta ./audio_meta.json \
  --storyboard ./STORYBOARD.md

# NO fetch-sfx — banned command
```

### Phase 7: Visual Design

Edit `STORYBOARD.md` in place with time-coded shot sequences per frame (from §5 or §6). Add `## Video direction` block.

```bash
# Stage named assets
node <SKILL_DIR>/scripts/stage-assets.mjs --storyboard ./STORYBOARD.md --hyperframes .
```

### Phase 8: Build Frames

```bash
# Generate frame packets
node <SKILL_DIR>/scripts/frame-packets.mjs \
  --project "." \
  --storyboard "./STORYBOARD.md"

# Dispatch one sub-agent per frame (parallel)
# Each writes: compositions/frames/NN-*.html

# Build captions
node <SKILL_DIR>/scripts/captions.mjs build \
  --storyboard ./STORYBOARD.md \
  --audio-meta ./audio_meta.json \
  --hyperframes . \
  --out ./caption_groups.json &

# Assemble index
node <SKILL_DIR>/scripts/assemble-index.mjs \
  --storyboard ./STORYBOARD.md \
  --hyperframes .
```

### Phase 9: Finalize & Verify

```bash
# Inject transitions
node <SKILL_DIR>/scripts/transitions.mjs inject \
  --storyboard ./STORYBOARD.md --hyperframes .

node <SKILL_DIR>/scripts/transitions.mjs verify \
  --storyboard ./STORYBOARD.md --index ./index.html

# Lint & check
npx hyperframes lint
npx hyperframes check

# Snapshot contact sheets
npx hyperframes snapshot --at <frame-midpoints-and-cuts>
```

### Phase 10: Ralph Loop (Both Videos)

```
for each video:
    render MP4
    extract frames
    score R1–R10
    log to videos/PROGRESS.md
    fix FAILs
    repeat until all PASS (min 2 rounds)
```

```bash
# Render
npx hyperframes render --skill=product-launch-video --quality high --output renders/video.mp4
```

### Phase 11: PROGRESS.md

Create `videos/PROGRESS.md` with `[ ]/[~]/[x]/[=]/[!]` markings:

```markdown
# Video Production Progress

## Film (backstop-film)
- [ ] Phase 0: Cleanup & font rescue
- [ ] Phase 1: Init project
- [ ] Phase 2: BRIEF.md
- [ ] Phase 3: Auth check
- [ ] Phase 4: Capture & design
- [ ] Phase 5: Storyboard & script
- [ ] Phase 6: Audio (VO + BGM)
- [ ] Phase 7: Visual design
- [ ] Phase 8: Build frames
- [ ] Phase 9: Finalize & verify
- [ ] Phase 10: Ralph loop R1
- [ ] Phase 10: Ralph loop R2+

## Reel (backstop-reel)
- [ ] Phase 0: (shared with Film)
- [ ] Phase 1: Init project
- [ ] Phase 2: BRIEF.md
- [ ] Phase 3: Auth check
- [ ] Phase 4: Capture & design
- [ ] Phase 5: Storyboard & script
- [ ] Phase 6: Audio (VO + BGM)
- [ ] Phase 7: Visual design
- [ ] Phase 8: Build frames
- [ ] Phase 9: Finalize & verify
- [ ] Phase 10: Ralph loop R1
- [ ] Phase 10: Ralph loop R2+

## Session Log
(entries added during execution)
```

---

## Appendix A: Files Created Per Project

| Path | Created at | Purpose |
|------|-----------|---------|
| `hyperframes.json` | Phase 1 | Project config |
| `BRIEF.md` | Phase 2 | Locked brief |
| `frame.md` | Phase 4 | Design system (custom, not preset) |
| `capture/extracted/tokens.json` | Phase 4 | Brand tokens |
| `assets/fonts/*.woff2` | Phase 4 | Font files |
| `assets/backstop-logo.svg` | Phase 4 | Logo |
| `SCRIPT.md` | Phase 5 | Voice script |
| `STORYBOARD.md` | Phase 5 → Phase 7 | Storyboard (enriched in Phase 7) |
| `audio_meta.json` | Phase 6 | Audio timings |
| `assets/voice/*.wav` | Phase 6 | VO audio |
| `assets/bgm/track.mp3` | Phase 6 | Background music |
| `.hyperframes/frame-packets/*.md` | Phase 8 | Frame build specs |
| `compositions/frames/NN-*.html` | Phase 8 | Frame HTML |
| `compositions/captions.html` | Phase 8 | Caption track |
| `index.html` | Phase 8 | Assembled composition |
| `caption_groups.json` | Phase 8 | Caption timings |
| `snapshots/contact-sheet.jpg` | Phase 9 | Visual verification |
| `renders/video.mp4` | Phase 10 | Final output |

## Appendix B: Commands Quick Reference

| Command | When | Notes |
|---------|------|-------|
| `npx hyperframes init` | Phase 1 | `--non-interactive --example=blank --skill=product-launch-video` |
| `npx hyperframes auth status` | Phase 3 | Exits 1 if not signed in — NOT an error |
| `npx hyperframes auth refresh` | Phase 3, Phase 6 | Refresh before every audio run |
| `npx hyperframes capture` | Phase 4 | Optional — we have README content |
| `npx hyperframes lint` | Phase 9 | Must pass with 0 errors |
| `npx hyperframes check` | Phase 9 | Must pass with 0 findings |
| `npx hyperframes snapshot` | Phase 9, Phase 10 | Extract frames for Ralph loop |
| `npx hyperframes preview --background` | Phase 10 | User review before render |
| `npx hyperframes render` | Phase 10 | `--quality high --output renders/video.mp4` |

---

> **⏸ STOP HERE — awaiting approval before execution.**
