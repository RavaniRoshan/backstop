---
version: alpha
name: Obsidian Terminal — Frame (video / frame layer)
description: >
  Video-first bespoke design for Backstop product launch. Dark-canvas precision tool aesthetic.
  Near-black ground, one earned electric green accent (volt), one danger red for the problem state.
  Inter for all text (display + body), JetBrains Mono for code/terminal/kickers.
  Grounded windows with layered shadows and bezel highlights. No glow excess.
unit: the frame — 1920×1080 primary; 9:16 documented
principle: dark canvas · earned accent · precision tool · real CLI

colors:
  canvas: "#0C0C0E"
  surface: "#1A1A1F"
  surface-elevated: "#252529"
  ink: "#E8E4DF"
  ink-muted: "#8A8690"
  volt: "#22D67A"
  volt-dim: "rgba(34,214,122,0.10)"
  danger: "#F04438"
  danger-dim: "rgba(240,68,56,0.10)"
  code-bg: "#13131A"

borders: { hairline: "1px solid ink@8%", window-bezel: "inset 0 1px 0 rgba(255,255,255,0.06)" }
shadows: { window: "0 24px 48px rgba(0,0,0,0.4), 0 8px 16px rgba(0,0,0,0.2)", none: "none" }

typography:
  # — reading + chrome ramp —
  body:    { fontFamily: "Inter", cqw: 1.5, weight: 400, lineHeight: 1.5 }
  lead:    { fontFamily: "Inter", cqw: 2.08, weight: 400, lineHeight: 1.5 }
  card-title:{ fontFamily: "Inter", cqw: 2.3, weight: 600, lineHeight: 1.25, tracking: "-0.005em" }
  button:  { fontFamily: "Inter", cqw: 1.46, weight: 600, lineHeight: 1.0 }
  kicker:  { fontFamily: "Inter", cqw: 1.0, weight: 600, tracking: "0.08em", upper: true }
  mono-label:{ fontFamily: "JetBrains Mono", px: 26, cqw: 1.35, weight: 500, tracking: "0.02em" }
  code:    { fontFamily: "JetBrains Mono", cqw: 1.15, weight: 400, lineHeight: 1.6 }
  # — display ramp (Inter 800, sentence case) —
  headline:{ fontFamily: "Inter", cqw: 3.75, weight: 800, lineHeight: 1.08, tracking: "-0.02em" }
  display: { fontFamily: "Inter", cqw: 5.2, weight: 800, lineHeight: 1.04, tracking: "-0.025em" }
  display-cover:{ fontFamily: "Inter", cqw: 6.5, weight: 800, lineHeight: 1.02, tracking: "-0.03em" }
  number-hero:{ fontFamily: "Inter", cqw: 4.5, weight: 700, lineHeight: 0.95 }
  number-unit:{ fontFamily: "JetBrains Mono", cqw: 2.08, weight: 500, lineHeight: 1.0 }

spacing:
  slide-pad: "4.2cqw"   # ~80px @1920
  gap-md: "1.7cqw"
  hairline: "1px"
  radius-sm: "6px"
  radius-md: "10px"
  radius-lg: "12px"
  radius-pill: "9999px"

components:
  terminal-window:
    backgroundColor: "{colors.surface}"
    border: "{borders.window-bezel}"
    rounded: "{spacing.radius-md}"
    shadow: "{shadows.window}"
    titleBar: "32px height, centered title in {colors.ink-muted} 13px Inter 500"
    trafficLights: "#FF5F57 #FEBC2E #28C840, 12px circles, 8px gap, left 12px"
    description: "macOS-style terminal/code window. Grounded with layered shadow + bezel highlight. Title bar + traffic lights only (no menu bar, no dock)."
  code-surface:
    backgroundColor: "{colors.code-bg}"
    textColor: "{colors.ink} (JetBrains Mono); syntax: volt (keywords), #5DB8A6 (strings), #E8A55A (numbers), ink-muted (comments)"
    border: "1px solid rgba(255,255,255,0.06)"
    rounded: "{spacing.radius-md}"
    description: "Interior of a code editor. Slightly blue-shifted dark. Python syntax highlighted."
  comparison-card:
    backgroundColor: "{colors.surface}"
    border: "1px solid rgba(255,255,255,0.06)"
    rounded: "{spacing.radius-lg}"
    shadow: "{shadows.window}"
    description: "Two-column comparison table. Left column header in danger, right in volt."
  number-lockup:
    typography: "{typography.number-hero} figure + {typography.number-unit} unit"
    description: "Hero stat — Inter 700 figure with JetBrains Mono unit."
  volt-badge:
    backgroundColor: "{colors.volt}"
    textColor: "{colors.canvas}"
    rounded: "{spacing.radius-pill}"
    typography: "{typography.button}"
    description: "Success state badge. Appears ONLY when Backstop blocks a call. Volt is earned, not decorative."
  danger-label:
    textColor: "{colors.danger}"
    typography: "{typography.kicker}"
    description: "Problem state label. Unprotected metrics, token burn counts."
---

# Obsidian Terminal — Frame (video / frame layer)

## Overview

Obsidian Terminal is a **precision-tool aesthetic for a developer CLI product** — the visual register
of a clean terminal session on a OLED display. The thesis is three colors: **canvas is the void,
ink is the voice, volt-green is the earned reward** — and danger-red marks the problem being solved.

Two typographic voices: **Inter** carries every headline and body moment at 800/400 weight;
**JetBrains Mono** carries the terminal, code, kickers, and stat units. No serif in this build.

**Key characteristics at frame scale:**

- **Dark canvas ground** — near-black `#0C0C0E` with warm undertone, never pure `#000`.
- **Volt-green is earned** — appears ONLY when Backstop blocks a call or verifies. Never decorative.
- **Grounded windows** — every window has layered shadow (cast + ambient) plus bezel edge highlight.
- **No fake desktop** — windows sit directly on canvas. No wallpaper, no dock, no menu bar.
- **Restrained glows** — max 10% opacity, static only, never breathing/pulsing animations.
- **Authentic CLI** — no GUI buttons in terminals. All interaction is `$` prompt → typed command → output.

## The Frame

### Frame Craft Bar

Eyeball tests gate every frame before any structural check:

- **Squint** — one large Inter display moment dominates at 3–6× its neighbor.
- **Dark ground** — canvas ground, ink text, volt exactly once (or zero times if not earned); danger only in problem frames.
- **Type** — Inter 800 display (sentence case); Inter 400 body; JetBrains Mono code/terminal.

- **Primary:** 1920×1080 (16:9). Display authored in **`cqw`** (`px ÷ 1920 × 100 = cqw`).
- **Safe area:** `slide-pad` ~4.2cqw; kickers sit inside it.

**The container law (load-bearing).** Every frame ground sets `container-type: size`; ALL
frame-relative units are `cqw`/`cqh` against it — never `vw`. Hairlines stay 1px; card radii stay
6/10/12px.

## Colors

**Canvas** (`{colors.canvas}`) is the permanent ground — near-black with warm undertone, carries
a subtle radial gradient vignette (center `#0C0C0E` → edge `#060608`) at 2% opacity.
**Surface** (`{colors.surface}`) is the window/card background — one step up from canvas.
**Surface-elevated** (`{colors.surface-elevated}`) is the active window interior.
**Ink** (`{colors.ink}`) is warm off-white text on dark — never pure `#fff`.
**Ink-muted** (`{colors.ink-muted}`) is secondary text, comments, labels.
**Volt** (`{colors.volt}`) is the earned accent — success, blocked calls, verified status.
**Danger** (`{colors.danger}`) is the problem — runaway loops, unprotected metrics.

**Fixed syntax colors (on code surfaces).** Keywords: volt `#22D67A`; strings: teal `#5DB8A6`;
numbers: amber `#E8A55A`; comments: ink-muted.

## Typography

Single sans + mono system. **Inter** (400/600/700/800) is the only prose face — display headlines
at 800, body at 400, labels at 600. **JetBrains Mono** (400/500/700) carries all code, terminal
output, kickers, and stat units.

- **Legibility floor:** any load-bearing line ≥ **1.4cqw**; mono labels are chrome only.
- **Inter display is sentence case** (NOT title case, NOT uppercase), weight 800.

## Depth & Surface

Grounded windows with cinematic depth:

- **Bezel edge** — `inset 0 1px 0 rgba(255,255,255,0.06)` top highlight on every window.
- **Cast shadow** — `0 24px 48px rgba(0,0,0,0.4)` deep directional.
- **Ambient shadow** — `0 8px 16px rgba(0,0,0,0.2)` soft fill.
- **Window reflection** — very subtle gradient on title bars: `linear-gradient(180deg, rgba(255,255,255,0.03) 0%, transparent 100%)`.

**Ceiling:** no heavy glow, no gradient on content. Glows max 10% opacity, static only.

## Do's and Don'ts

### DO
- Ground every window with layered shadows and bezel highlight.
- Use `$` prompt → typed command → streaming output for all terminal interactions.
- Use stepped CSS timing for code typing reveals.
- Use `step-end` for terminal cursor blinks.
- Prefix all ids/classes per frame (`d1-`, `d2-`, etc.).
- Keep volt-green earned — only on success/blocked/verified states.

### DON'T
- No fake macOS desktop (no wallpaper, no dock, no full menu bar).
- No GUI buttons inside terminals (no "▶ Run" pills).
- No breathing/pulsing glow animations.
- No pure `#000000` or pure `#FFFFFF`.
- No EB Garamond or other serif fonts.
- No CSS `transform` on elements that GSAP also tweens.
- No `left`/`top`/`width`/`height` GSAP tweens — `x`/`y`/`scale`/`opacity` only.
