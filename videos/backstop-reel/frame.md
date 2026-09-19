---
version: alpha
name: Obsidian Terminal — Frame (9:16 vertical reel)
description: >
  Vertical adaptation of the Obsidian Terminal design system for 15-second reel.
  Same palette and typography, adapted for 1080×1920 full-bleed vertical layouts.
  Content fills top 83% of canvas. Large readable text. Full-width cards.
unit: the frame — 1080×1920 (9:16 vertical)
principle: dark canvas · earned accent · full-bleed vertical · real CLI

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
shadows: { card: "0 16px 32px rgba(0,0,0,0.35), 0 4px 12px rgba(0,0,0,0.2)", none: "none" }

typography:
  body:    { fontFamily: "Inter", cqw: 2.2, weight: 400, lineHeight: 1.5 }
  lead:    { fontFamily: "Inter", cqw: 3.0, weight: 400, lineHeight: 1.4 }
  card-title:{ fontFamily: "Inter", cqw: 3.5, weight: 600, lineHeight: 1.2 }
  kicker:  { fontFamily: "Inter", cqw: 1.3, weight: 600, tracking: "0.08em", upper: true }
  code:    { fontFamily: "JetBrains Mono", cqw: 1.85, weight: 400, lineHeight: 1.5 }
  headline:{ fontFamily: "Inter", cqw: 5.9, weight: 800, lineHeight: 1.06, tracking: "-0.02em" }
  display: { fontFamily: "Inter", cqw: 8.0, weight: 800, lineHeight: 1.02, tracking: "-0.025em" }
  number-hero:{ fontFamily: "Inter", cqw: 5.2, weight: 700, lineHeight: 0.95 }
  number-unit:{ fontFamily: "JetBrains Mono", cqw: 3.0, weight: 500, lineHeight: 1.0 }

spacing:
  slide-pad: "5.5cqw"
  gap-md: "2.5cqw"
  hairline: "1px"
  radius-sm: "6px"
  radius-md: "10px"
  radius-lg: "14px"
  radius-pill: "9999px"

components:
  code-card:
    backgroundColor: "{colors.surface}"
    border: "1px solid rgba(255,255,255,0.06)"
    rounded: "{spacing.radius-lg}"
    shadow: "{shadows.card}"
    description: "Full-width code card. Shows syntax-highlighted Python. No title bar needed at this scale."
  terminal-card:
    backgroundColor: "{colors.surface}"
    border: "1px solid rgba(255,255,255,0.06)"
    rounded: "{spacing.radius-lg}"
    shadow: "{shadows.card}"
    description: "Full-width terminal output card. Shows CLI output with step status."
  number-lockup:
    typography: "{typography.number-hero} figure + {typography.number-unit} unit"
    description: "Hero stat for vertical — large Inter figure with JetBrains Mono unit."
  volt-badge:
    backgroundColor: "{colors.volt}"
    textColor: "{colors.canvas}"
    rounded: "{spacing.radius-pill}"
    description: "Full-width VERIFIED badge. Appears only on success states."
---

# Obsidian Terminal — Frame (9:16 vertical reel)

## Overview

Vertical adaptation of the dark-canvas Obsidian Terminal aesthetic. The same three-color system
(canvas void / ink voice / volt reward) scaled for full-bleed 9:16 vertical consumption.

**Key characteristics at vertical scale:**

- **Full-bleed cards** — content fills the full width of the canvas, top-aligned.
- **Content fills top 83%** — bottom 17% is reserved for the caption keep-out zone.
- **Larger type** — everything scaled up for thumb-scroll viewing distance.
- **No windows** — no title bars, no traffic lights. Cards sit directly on canvas.
- **No cursor** — 15 seconds is too short for cursor choreography.

## Do's and Don'ts

### DO
- Fill the vertical canvas with purposeful hierarchy.
- Use large readable text (minimum 1.3cqw).
- Use full-width cards with generous padding.
- Keep volt-green earned — only on success states.

### DON'T
- No floating small elements in white/dark space.
- No fake macOS chrome.
- No content in the bottom 17% caption zone.
- No breathing/pulsing glow animations.
