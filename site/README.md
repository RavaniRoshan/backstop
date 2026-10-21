# The Backstop site

Two surfaces, one repository:

- `/` — the marketing page, a plain Astro route under `pages/`.
- `/docs` — the documentation, which is the repository's own `docs/*.md`.

There is no second copy of the documentation. `scripts/prepare-content.mjs`
derives the site's content from `../docs` at build time: the leading
`# Title` of each document becomes the page title, the description is written
by hand in that script, and the body is copied through with its links
rewritten for the site. The documents themselves stay as they are, because
they are also read on GitHub.

The site is published at <https://ravaniroshan.github.io/backstop/>, and
`ravaniroshan.github.io/backstop/docs` is the documentation.

## Running it

```bash
npm install
npm run dev      # the content is prepared first, then the dev server runs
npm run build    # static output in dist/
npm run verify   # build, then check every internal link resolves
```

Node 22.19 or newer. The site is static: `dist/` is a folder of files that any
host can serve.

## Deploying it

`.github/workflows/pages.yml` builds the site and publishes it to GitHub Pages.
The repository's Pages setting is already "GitHub Actions" as the build source,
so the workflow is what builds and publishes it; it runs on every push that
touches `site/` or `docs/`, because the documentation on the site is the
repository's own `docs/`.

GitHub serves a project site from a subdirectory, and the base path is not
written down anywhere: `actions/configure-pages` reports where GitHub will
actually serve the site, and the build takes its `SITE_BASE` and its canonical
URL from there. The two cannot drift.

A deployment that lives at the root of a host sets `SITE_BASE` to nothing, and
every link in the site follows the prefix — the framework's own, the marketing
page's, and the ones `prepare-content.mjs` rewrites into the documents.

`.github/workflows/deploy.yml` is the same build, handed to Cloudflare Pages
instead. It needs two repository secrets, `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID`; it does not fire on a push, so run it by hand when
the site should go out to both.

## What is in here

| Path | What it is |
|---|---|
| `blume.config.ts` | The site configuration: title, theme, navigation, deployment |
| `theme.css` | The design tokens, set to the dashboard's palette |
| `pages/` | The marketing pages, as Astro routes |
| `components/` | The marketing components |
| `styles/marketing.css` | The marketing pages' own vocabulary |
| `styles/diagram.css` | The wiring diagram |
| `styles/integrations.css` | The integrations section |
| `styles/dither.css` | The dithered field behind the hero |
| `styles/loader.css` | The loader the page arrives behind |
| `src/scripts/motion.ts` | The page's only moving parts |
| `src/scripts/dither-reveal.ts` | The WebGL field behind the hero |
| `src/scripts/dither-shaders.ts` | Its shader |
| `src/scripts/tiles-loader.ts` | The loader |
| `src/scripts/easing.ts` | The loader's curves |
| `assets/logos/` | The brand marks, committed as SVG |
| `scripts/prepare-content.mjs` | Derives `.content/` from the repository's `docs/` |
| `scripts/prepare-logos.mjs` | Compiles `assets/logos/` into a typed module |
| `scripts/check-links.mjs` | Checks every internal link in the built site |

The documentation pages themselves are rendered by [Blume](https://useblume.dev),
which is a zero-config documentation framework on Astro and Vite. The marketing
pages are plain Astro, mounted beside the docs through Blume's custom-page
support, and share its header, search and theme toggle.

## The brand marks

`assets/logos/*.svg` is the site's mark library, committed to the repository
so the page never fetches anything at runtime. `scripts/prepare-logos.mjs`
compiles them into `src/data/logos.ts` (which is generated, and not committed)
and does two things that the raw SVGs cannot do for themselves:

- **It crops every viewBox to the artwork's own ink.** Most brand SVGs are
  drawn inside a square box with the artwork filling only part of it, so
  rendered at one height they come out at three different sizes. Cropping makes
  one rendered height one optical height for every mark.
- **It normalises a single flat colour to `currentColor`.** A mark exported
  with its colour baked in — the Codex mark is `#111`, which vanishes on a dark
  page — becomes one the page can tint. A mark with more than one colour, a
  gradient or a filter is left exactly as it is.

Both the crops and the monochrome decision are made at build time from the
committed files, so they cannot drift.

## The hero's field

The hero sits on a dithered rendering of the dashboard screenshot, which tears
open into full colour where the cursor sweeps. It is [Originkit](https://originkit.dev)'s
`dither-reveal` component, ported: the component arrives as a React component
that fetches a remote image, and this site has neither React nor a remote
fetch. So the shader is Originkit's, unchanged, and everything around it is
this site's — the image is the one the site already serves, the script is
plain TypeScript, and the field is inverted on the light theme so the same
halftone reads as ink on paper rather than as a dark band.

## The loader

The marketing page arrives behind a loader: a grid of tiles that fills with
the page's own foreground as the load progresses, then shrinks away in a
diagonal sweep to lift. It is [Originkit](https://originkit.dev)'s
`tiles-loader`, ported — the component arrives as a React component with a
fourteen-second default wait, and this site has neither React nor fourteen
seconds to stand between a reader and a page.

The port keeps the component's curve and its sweep, and changes what matters
for a real page:

- **The page is rendered behind the loader the whole time.** The loader is an
  overlay, not a gate, so nothing is held back that is not already loaded.
- **It cannot trap a reader.** A `<noscript>` rule removes it, a failsafe
  lifts it if the driver never runs, and a reader who asked for no motion
  never sees it.
- **It is short.** Under two seconds, and the counter is the component's own
  chunky curve rather than a bar that slides.
- **It is the page's theme.** The tiles are the page's background and
  foreground, so there is no flash of a colour the reader did not choose.

Only the marketing page has one. The documentation has no loader, because a
reader looking for an answer should not be made to wait for a curtain.
