# Marketing site, round two — motion, integrations, and the wiring diagram

**Date:** 2026-10-21
**Scope:** the marketing page in `site/` (`pages/index.astro`).
**Status:** design approved; executed by `docs/superpowers/plans/2026-10-21-marketing-motion-integrations.md`

## What this round adds

1. **Movement.** Transitions and scroll-triggered reveals across the marketing
   page, using the `motion` library (Framer Motion's framework-free successor)
   — not React.
2. **The integrations story.** What Backstop actually connects to, said in
   plain words, with a comparison matrix over the inference stack.
3. **The wiring diagram.** A hand-drawn SVG artefact in the hero: the agents on
   the left, Backstop in the middle, the two endpoint shapes on the right, with
   the connections animated and every mark the real one.

## The facts the integrations section is built on

Read out of the code, not out of the marketing:

* Backstop has **two native surfaces**: the OpenAI and Anthropic **Python SDKs,
  in process** (`Backstop.wrap()`), and `backstop serve`, an **OpenAI-compatible
  reverse proxy** for fleets that are not Python.
* `wrap()` preserves whatever `base_url` the SDK client was built with
  (`wrapper.py:257-312`, `:394-396`), and the enforcement engine is
  provider-agnostic (`transports.py:515+`). So **any OpenAI-compatible server
  is a valid target** and the guardrail still applies to it — vLLM, SGLang, TGI,
  llama.cpp, Ollama, LM Studio, DeepInfRA, Together, Groq, Fireworks,
  OpenRouter, and the OpenAI-compatible gateways of Bedrock, Azure and Vertex.
  The explore agent verified this empirically against a local server: the
  request reached the local endpoint and the second call was blocked.
* What is **not** provider-agnostic is **pricing**. The bundled catalogue holds
  OpenAI and Anthropic models only (`pricing_catalog.py:241-291`). On any other
  host the ledger records the event as `provider="unknown"` and leaves it
  unpriced, and a **dollar** budget then **refuses** an unpriced model
  (`policy.py:183-213`) unless the deployment files its own catalogue entry or
  sets `budget_usd_unpriced_policy="allow"`.
* Only two domains are recognised for pricing: `openai.com` and `anthropic.com`
  (`transports.py:44-80`).
* The framework adapters are **attribution bridges, not enforcement**: LangChain
  and LlamaIndex are implemented (`adapters/__init__.py:36-72`), CrewAI and
  AutoGen are mentioned only.
* `backstop serve` buffers the whole response before handing it back, so a
  streaming upstream is not streamed to the client (`gateway.py:179-190`), and a
  guardrail denial at the gateway surfaces as a **502** (`gateway.py:169-178`).

The section is written from those facts. It does not claim a named integration
that the code does not have.

## The story, in plain words

> **Backstop does not care who serves the model. It cares who is spending.**
>
> Your agent talks to Backstop. Backstop decides whether that call is allowed,
> and then forwards it to whatever is serving the model — a hosted API, your
> own GPU box, or a gateway in between. The limit does not change with the
> provider. The price list does.

## The wiring diagram

The hero artefact. Three columns, drawn in SVG:

* **Left — the agents.** The things that make the calls: Claude Code, Cursor,
  GitHub Copilot, OpenAI Codex, Google Antigravity, Cline, Windsurf, Zed.
* **Middle — Backstop.** The brand's own gauge mark, with the three limits
  named on it: budget, breaker, concurrency.
* **Right — the endpoint shapes.** Two marks, OpenAI and Anthropic, labelled
  with the two shapes every inference server eventually speaks:
  *OpenAI-compatible* and *Anthropic-compatible*. A third, generic node reads
  "any OpenAI-compatible server", because that is the honest claim.

The connections are animated: they draw in on load, and a slow pulse travels
along each one. Hovering an agent highlights its own wire. With
`prefers-reduced-motion` the diagram renders static, fully drawn.

Every mark is the real one: fetched from the Iconify collections (which carry
the Simple Icons, Logos, Devicon and VS Code sets) at build time and committed
to `site/assets/logos/`, then compiled into a typed module. Nothing is fetched
at runtime, and the site still makes zero outbound requests.

## The matrix

A comparison over the inference stack, in the shape a reader scans: which
servers speak which shape, and what Backstop gives you on top of each. The
cells that differ between the two shapes — **pricing** — are the point of the
table, and they say so.

## Motion

`motion` (the `motion` package — Framer Motion's framework-free build, ~18 kB)
rather than `framer-motion` + React: the page ships no framework today, and
adding React to a static marketing page to move twelve elements would be a
regression in everything except the animation.

What moves: the hero's entrance, the section reveals, the numbers counting up,
the terminal typing itself, the FAQ, the matrix's row reveal, and the diagram's
wires. Every one of them respects `prefers-reduced-motion` and does nothing
without JavaScript.
