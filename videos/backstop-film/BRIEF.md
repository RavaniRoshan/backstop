---
workflow: product-launch-video
flow: automation
storyboard: yes
message: "Stop agent loops from burning your budget - in-process token budgets for OpenAI and Anthropic"
destination: product-hunt
aspect: 1920x1080
language: en
length: 85s
angle: product-demo
voice: edmund
audience: Python developers running AI agents
---

## Intent

Rebuild from zero: a cinematic product launch film for Backstop, a Python
transport-layer budget guardrail for OpenAI/Anthropic SDKs. Show a runaway
agent loop, then stop it with one wrap call. Raw, authentic, developer-focused.
No marketing slickness. Every number on screen is real CLI output.

## Assets

- /tmp/backstop-fonts/backstop-logo.svg — brand logo; CTA frame lockup.
- /tmp/backstop-fonts/Inter-400.woff2 — body/headline font.
- /tmp/backstop-fonts/Inter-700.woff2 — bold variant.
- /tmp/backstop-fonts/JetBrainsMono-400.woff2 — code/terminal font.
- /tmp/backstop-fonts/JetBrainsMono-700.woff2 — code bold variant.

## Customizations

- Count-up animation on the "2,000 tokens saved" number in the verify frame.
- Count-up animation on the token counter (0→250) in the hook frame.
- Select-sweep → copied pill animation on the install command in the CTA frame.
- Stepped CSS typing animation for all terminal commands (no smooth fades).
- Terminal cursor blinks via step-end (instant toggle).
- music: none — zero background music per deep research findings.

## Notes

- Product: `pip install "backstop-ai"`, GitHub `RavaniRoshan/backstop`, MIT license.
- Real CLI outputs to replay verbatim: `backstop demo` (10 attempted, 3 completed, 7 blocked, 250→75 tokens, -70%) and `backstop verify` (2 allowed, 8 blocked, 2,000 tokens saved, VERIFIED).
- Real code from `examples/agent_loop_guard.py` (Backstop.wrap with budget=120).
- No fake macOS desktop (no wallpaper, no dock, no menu bar). Windows sit directly on dark canvas.
- No GUI buttons inside terminals. All terminal interaction is authentic CLI.
- No AI-tells: no "imagine", "what if", "unlock", "seamless", "delve".
- Voice: HeyGen Edmund (Firm & Measured), directed like a trailer narrator.
- Palette: "Obsidian Terminal" — deep dark canvas #0C0C0E, volt green #22D67A (earned), danger red #F04438.
- Glows extremely restrained (max 10% opacity, no breathing animations).
