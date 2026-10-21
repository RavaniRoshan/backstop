# Marketing Site, Round Two — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add movement, an honest integrations story, and an animated wiring diagram to the Backstop marketing page, using the real brand marks and no new runtime frameworks.

**Architecture:** Three new pieces in `site/`: a committed library of real brand SVGs compiled into a typed module by a build script, a hand-drawn SVG wiring diagram in the hero, and a comparison matrix over the inference stack. Movement comes from the `motion` package — Framer Motion's framework-free build — loaded once as a module script, so the page still ships no framework.

**Tech Stack:** Astro, the `motion` package (vanilla), hand-written SVG, `iconify` collections fetched at build time and committed.

**Spec:** `docs/superpowers/specs/2026-10-21-marketing-motion-integrations-design.md`

## Global Constraints

- The site makes **zero outbound requests** at runtime. Fonts are self-hosted; brand marks are committed to the repository, never fetched in the browser.
- The site ships **no client framework**. `motion` is the framework-free build of Framer Motion; `framer-motion` with React is not used.
- Every claim about an integration must be true of the code. Backstop's native surfaces are the OpenAI and Anthropic **Python SDKs in process** and `backstop serve`; any OpenAI-compatible server is a valid *target*; **pricing** is OpenAI- and Anthropic-only unless the deployment files its own catalogue entry.
- Brand marks are the real ones. A mark that cannot be fetched is left out of the diagrams and named in text, never drawn as a fake.
- Every animation respects `prefers-reduced-motion`, and the page is complete and readable with no JavaScript at all.
- The site is built for the root of whatever host serves it; `SITE_BASE` sets a subdirectory prefix.
- Test command: `python3 -m pytest -q` from the repository root. Site check: `cd site && npm run verify` (build + link check).

---

### Task 1: The brand-mark library

**Files:**
- Create: `site/assets/logos/*.svg` — the fetched marks, committed
- Create: `site/scripts/prepare-logos.mjs` — compiles them into a typed module
- Create: `site/src/data/logos.ts` — generated; git-ignored
- Modify: `site/package.json` — the `prepare` script also runs the logo step
- Test: `tests/test_site_assets.py` — the marks the site references exist

**Interfaces:**
- Consumes: the SVGs under `site/assets/logos/`
- Produces: `site/src/data/logos.ts` exporting `logos: Record<string, Logo>` where
  `Logo = { slug: string; title: string; viewBox: string; body: string; monochrome: boolean }`.
  `body` is the SVG's inner markup, safe to inject with `set:html`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_site_assets.py`:

```python
"""The marketing site's own assets: the brand marks it draws.

The site fetches nothing at runtime, so every mark it draws has to be in the
repository. A diagram that references a mark nobody committed renders a hole.
"""
from __future__ import annotations

import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"
LOGOS = SITE / "assets" / "logos"
PAGES = SITE / "pages"


def test_every_referenced_logo_is_committed():
    referenced: set[str] = set()
    for page in PAGES.rglob("*.astro"):
        text = page.read_text(encoding="utf-8")
        referenced.update(re.findall(r'logo="([a-z0-9-]+)"', text))
    missing = sorted(slug for slug in referenced if not (LOGOS / f"{slug}.svg").exists())
    assert not missing, f"the site draws marks that are not in the repository: {missing}"


def test_every_committed_logo_is_a_real_svg():
    for svg in sorted(LOGOS.glob("*.svg")):
        text = svg.read_text(encoding="utf-8")
        assert text.lstrip().startswith("<svg"), f"{svg.name} is not an SVG"
        assert "viewBox" in text, f"{svg.name} has no viewBox"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_site_assets.py -q`
Expected: FAIL — `site/assets/logos/` does not exist.

- [ ] **Step 3: Commit the marks**

Copy the fetched marks into `site/assets/logos/`, named by slug:

```bash
mkdir -p site/assets/logos
cp /tmp/logos/*.svg site/assets/logos/
```

The set is the 29 marks the build needs: `openai`, `anthropic`, `claude`,
`claude-code`, `cursor`, `copilot`, `codex`, `antigravity`, `cline`,
`windsurf`, `zed`, `vllm`, `ollama`, `lmstudio`, `groq`, `together`,
`deepinfra`, `huggingface`, `mistral`, `nvidia`, `openrouter`, `replicate`,
`cohere`, `baseten`, `google`, `docker`, `kubernetes`, `redis`, `postgres`.

- [ ] **Step 4: Write the compiler**

Create `site/scripts/prepare-logos.mjs`:

```javascript
#!/usr/bin/env node
/**
 * Compile the committed brand marks into a typed module.
 *
 * The marks are fetched once, committed, and compiled here into plain data:
 * a slug, a title, a viewBox and the inner SVG markup. The components draw
 * them with `set:html`, so a mark can be tinted, sized and animated like any
 * other part of the diagram.
 */
import { readdir, readFile, mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const logoDir = resolve(here, "..", "assets", "logos");
const outFile = resolve(here, "..", "src", "data", "logos.ts");

const TITLES = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  claude: "Claude",
  "claude-code": "Claude Code",
  cursor: "Cursor",
  copilot: "GitHub Copilot",
  codex: "Codex",
  antigravity: "Antigravity",
  cline: "Cline",
  windsurf: "Windsurf",
  zed: "Zed",
  vllm: "vLLM",
  ollama: "Ollama",
  lmstudio: "LM Studio",
  groq: "Groq",
  together: "Together AI",
  deepinfra: "DeepInfra",
  huggingface: "Hugging Face",
  mistral: "Mistral",
  nvidia: "NVIDIA",
  openrouter: "OpenRouter",
  replicate: "Replicate",
  cohere: "Cohere",
  baseten: "Baseten",
  google: "Google",
  docker: "Docker",
  kubernetes: "Kubernetes",
  redis: "Redis",
  postgres: "PostgreSQL",
};

const files = (await readdir(logoDir)).filter((name) => name.endsWith(".svg")).sort();
const entries = [];

for (const file of files) {
  const slug = file.replace(/\.svg$/, "");
  const svg = await readFile(join(logoDir, file), "utf8");
  const viewBox = /viewBox="([^"]+)"/.exec(svg)?.[1] ?? "0 0 24 24";
  const body = svg.replace(/^[\s\S]*?<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "").trim();
  const fills = new Set(
    [...svg.matchAll(/(?:fill|stroke)="([^"]+)"/g)].map((m) => m[1]),
  );
  const coloured = [...fills].some((c) => c !== "none" && c !== "currentColor");
  const monochrome = !coloured && !svg.includes("<filter");
  entries.push(
    `  ${JSON.stringify(slug)}: {\n` +
      `    slug: ${JSON.stringify(slug)},\n` +
      `    title: ${JSON.stringify(TITLES[slug] ?? slug)},\n` +
      `    viewBox: ${JSON.stringify(viewBox)},\n` +
      `    monochrome: ${monochrome},\n` +
      `    body: ${JSON.stringify(body)},\n` +
      `  },`,
  );
}

const module = `// Generated by scripts/prepare-logos.mjs. Do not edit.\n` +
  `//\n` +
  `// The brand marks the marketing page draws, compiled from the committed SVGs\n` +
  `// in assets/logos/ so nothing is fetched at runtime.\n\n` +
  `export interface Logo {\n` +
  `  slug: string;\n` +
  `  title: string;\n` +
  `  viewBox: string;\n` +
  `  monochrome: boolean;\n` +
  `  body: string;\n` +
  `}\n\n` +
  `export const logos: Record<string, Logo> = {\n${entries.join("\n")}\n};\n`;

await mkdir(dirname(outFile), { recursive: true });
await writeFile(outFile, module, "utf8");
console.log(`compiled ${entries.length} logo(s) into src/data/logos.ts`);
```

- [ ] **Step 5: Wire it into the build**

In `site/package.json`:

```json
{
  "scripts": {
    "prepare": "node scripts/prepare-content.mjs && node scripts/prepare-logos.mjs",
    ...
  }
}
```

Add `site/src/data/` to `site/.gitignore` — the module is generated.

- [ ] **Step 6: Run the test and the build**

Run: `python3 -m pytest tests/test_site_assets.py -q && cd site && npm run prepare`
Expected: the test passes; the compiler prints `compiled 29 logo(s)`.

- [ ] **Step 7: Commit**

```bash
git add site/assets/logos site/scripts/prepare-logos.mjs site/package.json site/.gitignore tests/test_site_assets.py
git commit -m "feat(site): the real brand marks, compiled from committed SVGs"
```

---

### Task 2: The wiring diagram

**Files:**
- Create: `site/components/WiringDiagram.astro`
- Create: `site/styles/diagram.css`
- Modify: `site/pages/index.astro` — mount the diagram in the hero
- Test: `tests/test_site_assets.py` — the diagram names marks that exist

**Interfaces:**
- Consumes: `logos` from `src/data/logos.ts`
- Produces: `WiringDiagram.astro`, a component that renders the whole artefact
  with no props (the agent list and the endpoint list live inside it).

- [ ] **Step 1: Add the failing test**

Append to `tests/test_site_assets.py`:

```python
def test_the_diagram_draws_only_marks_that_exist():
    text = (SITE / "components" / "WiringDiagram.astro").read_text(encoding="utf-8")
    referenced = set(re.findall(r'logo="([a-z0-9-]+)"', text))
    missing = sorted(slug for slug in referenced if not (LOGOS / f"{slug}.svg").exists())
    assert not missing, f"the diagram draws marks that are not in the repository: {missing}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_site_assets.py -q`
Expected: FAIL — `site/components/WiringDiagram.astro` does not exist.

- [ ] **Step 3: Write the diagram**

`site/components/WiringDiagram.astro` renders one SVG with three columns:

- **left** — the agents, each a mark in a 44px tile: `claude-code`, `cursor`,
  `copilot`, `codex`, `antigravity`, `cline`, `windsurf`, `zed`.
- **middle** — the Backstop gauge (the brand mark from
  `docs/assets/backstop-logo.svg`, redrawn as a simple dial) with the three
  limits under it: budget, breaker, concurrency.
- **right** — the two endpoint shapes: the OpenAI mark labelled
  *OpenAI-compatible*, the Anthropic mark labelled *Anthropic-compatible*, and
  a generic node labelled *any OpenAI-compatible server*.

The wires are `<path>` elements in one `<g class="wires">` with a
`stroke-dasharray` animation that draws them in, and a second group of
`<circle>` pulses that travel along the same paths with `offset-path`.

```astro
---
import { logos } from "../data/logos";
---

<figure class="diagram" aria-labelledby="diagram-caption">
  <svg viewBox="0 0 960 420" role="img" aria-labelledby="diagram-caption">
    ...
  </svg>
  <figcaption id="diagram-caption">
    Every agent on the left talks to Backstop. Backstop decides whether the
    call is allowed, then forwards it to whatever is serving the model.
  </figcaption>
</figure>
```

Each mark is drawn by a small helper in the same file:

```astro
---
function Mark({ slug, size = 40 }: { slug: string; size?: number }) {
  const logo = logos[slug];
  if (!logo) return null;
  return (
    <svg
      class={`mark${logo.monochrome ? " mono" : ""}`}
      viewBox={logo.viewBox}
      width={size}
      height={size}
      role="img"
      aria-label={logo.title}
      set:html={logo.body}
    />
  );
}
---
```

- [ ] **Step 4: Style it**

`site/styles/diagram.css` holds the layout, the wire animation and the
reduced-motion fallback:

```css
.diagram svg { width: 100%; height: auto; display: block; }
.diagram .wire { fill: none; stroke: var(--blume-border); stroke-width: 1.5; }
.diagram .wire-live { stroke: var(--blume-accent); opacity: 0.55; }
@media (prefers-reduced-motion: reduce) {
  .diagram .wire { stroke-dasharray: none !important; }
  .diagram .pulse { display: none; }
}
```

- [ ] **Step 5: Mount it in the hero**

In `site/pages/index.astro`, import the component and place it directly under
the hero's copy.

- [ ] **Step 6: Run the test and build**

Run: `python3 -m pytest tests/test_site_assets.py -q && cd site && npm run build`
Expected: PASS; the build renders 23+ pages.

- [ ] **Step 7: Commit**

```bash
git add site/components/WiringDiagram.astro site/styles/diagram.css site/pages/index.astro tests/test_site_assets.py
git commit -m "feat(site): the wiring diagram"
```

---

### Task 3: The integrations section

**Files:**
- Create: `site/components/IntegrationsMatrix.astro`
- Create: `docs/integrations.md` — the same story as a documentation page
- Modify: `site/pages/index.astro` — the section
- Modify: `site/blume.config.ts` — the sidebar gains the new page
- Test: `tests/test_site_assets.py`

**Interfaces:**
- Consumes: `logos` from `src/data/logos.ts`
- Produces: `IntegrationsMatrix.astro`, a table with three columns — *server*,
  *what you speak*, *what Backstop adds* — and a caption that names the
  pricing caveat.

- [ ] **Step 1: Write the section**

The matrix rows, in the order an operator would meet them:

| Server | Speaks | Backstop adds |
|---|---|---|
| OpenAI, Anthropic | their own APIs | budgets, breaker, concurrency, priced from the bundled catalogue |
| vLLM, SGLang, TGI, llama.cpp, Ollama, LM Studio | OpenAI-compatible | budgets, breaker, concurrency; price it yourself |
| DeepInfRA, Together, Groq, Fireworks, OpenRouter, Replicate, Baseten, Cohere, Mistral, NVIDIA | OpenAI-compatible | budgets, breaker, concurrency; price it yourself |
| Bedrock, Azure OpenAI, Vertex | OpenAI-compatible gateways | budgets, breaker, concurrency; price it yourself |

The caveat line under the table, in the page's own words:

> Everything above enforces the same three limits. The only thing that changes
> is the price list: OpenAI and Anthropic models are priced from the catalogue
> that ships with Backstop, and anything else is unpriced until you file a
> price for it — because a dollar ceiling with no price is a guess, and a guess
> is not a limit.

- [ ] **Step 2: Write the documentation page**

`docs/integrations.md` covers the same ground with the commands: pointing
`OpenAI(base_url=...)` at a local server, and `backstop serve --target
https://api.deepinfra.com/v1/openai`.

- [ ] **Step 3: Add it to the sidebar**

In `site/blume.config.ts`, add a "Deploying against any OpenAI-compatible
server" entry to the "How it works" group.

- [ ] **Step 4: Run the checks**

Run: `python3 -m pytest -q && cd site && npm run verify`
Expected: the suite passes; the link check finds the new page.

- [ ] **Step 5: Commit**

```bash
git add site/components/IntegrationsMatrix.astro site/pages/index.astro site/blume.config.ts docs/integrations.md tests/test_site_assets.py
git commit -m "feat(site): the integrations section, from what the code supports"
```

---

### Task 4: Motion across the page

**Files:**
- Create: `site/src/scripts/motion.ts` — the one module that moves things
- Modify: `site/pages/index.astro` — the data attributes the script targets
- Modify: `site/package.json` — the `motion` dependency

**Interfaces:**
- Consumes: the `motion` package (`animate`, `inView`, `stagger`)
- Produces: `site/src/scripts/motion.ts`, imported once by the marketing page

- [ ] **Step 1: Add the dependency**

```bash
cd site && npm install motion --no-audit --no-fund
```

- [ ] **Step 2: Write the motion script**

```typescript
import { animate, inView, stagger } from "motion";

const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Reveal an element when it scrolls into view. */
function reveal(selector: string, distance = 14) {
  const targets = document.querySelectorAll<HTMLElement>(selector);
  if (!targets.length) return;
  if (reduced) {
    targets.forEach((el) => el.setAttribute("data-revealed", ""));
    return;
  }
  inView(
    targets,
    (entry) => {
      animate(
        entry.target as HTMLElement,
        { opacity: [0, 1], transform: [`translateY(${distance}px)`, "translateY(0px)"] },
        { duration: 0.5, ease: [0.32, 0.72, 0, 1] },
      );
    },
    { amount: 0.25 },
  );
}

/** Count a number up to the value it carries. */
function countUp(el: HTMLElement) {
  const target = Number(el.dataset.count ?? "0");
  if (!target || reduced) {
    el.textContent = el.dataset.count ?? el.textContent;
    return;
  }
  const controls = animate(0, target, {
    duration: 0.9,
    ease: [0.32, 0.72, 0, 1],
    onUpdate: (value) => {
      el.textContent = String(Math.round(value));
    },
  });
  return controls;
}
```

The script also drives the diagram's wires and the terminal's typed output, and
it removes the `data-reveal` attribute once an element has been revealed, so a
second pass does not re-hide it.

- [ ] **Step 3: Mark the elements**

In `site/pages/index.astro`, add `data-reveal` to the sections, `data-count` to
the numbers that should count up, and `data-type` to the terminal's body.

- [ ] **Step 4: Import the script**

```astro
<script>
  import "../src/scripts/motion";
</script>
```

- [ ] **Step 5: Build and look**

Run: `cd site && npm run build`, then screenshot the page and watch: the hero
enters, the sections reveal on scroll, the numbers count up, the terminal
types, and the diagram's wires draw in.

- [ ] **Step 6: Commit**

```bash
git add site/src/scripts/motion.ts site/pages/index.astro site/package.json site/package-lock.json
git commit -m "feat(site): motion across the page"
```

---

### Task 5: Verification

**Files:**
- Modify: `site/README.md` — what the page now does
- Modify: `CHANGELOG.md` — the entry

- [ ] **Step 1: Build, link-check, and test**

Run: `cd site && npm run verify && cd .. && python3 -m pytest -q`
Expected: the link check passes, the suite passes.

- [ ] **Step 2: Screenshot the page**

Run: `python3 scripts/…` — the site audit harness from the dashboard work, or a
Playwright pass over `http://127.0.0.1:<port>/` at 1440×900 and 390×844 in both
themes. Read the screenshots: the diagram is not cut off, the matrix fits, and
no value is truncated.

- [ ] **Step 3: Update the docs**

`site/README.md` gains a line about the diagram and the integrations section;
`CHANGELOG.md` gains the entry.

- [ ] **Step 4: Deploy**

The `Deploy the site` workflow publishes on a push to `main` ✓.
