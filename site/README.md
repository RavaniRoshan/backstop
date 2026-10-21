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

The site is published at <https://backstop-b5g.pages.dev>, and
`backstop-b5g.pages.dev/docs` is the documentation.

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

`.github/workflows/deploy.yml` builds the site and hands it to Cloudflare
Pages. It needs two repository secrets, `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID`; the workflow checks for them before it builds, so a
missing one fails in seconds with a named error instead of after two builds.

The site is built for the root of whatever host serves it. A deployment that
lives in a subdirectory sets `SITE_BASE` to that prefix, and every link in the
site follows it — the framework's own, the marketing page's, and the ones
`prepare-content.mjs` rewrites into the documents.

## What is in here

| Path | What it is |
|---|---|
| `blume.config.ts` | The site configuration: title, theme, navigation, deployment |
| `theme.css` | The design tokens, set to the dashboard's palette |
| `pages/` | The marketing pages, as Astro routes |
| `components/` | The marketing components |
| `styles/marketing.css` | The marketing pages' own vocabulary |
| `scripts/prepare-content.mjs` | Derives `.content/` from the repository's `docs/` |
| `scripts/check-links.mjs` | Checks every internal link in the built site |

The documentation pages themselves are rendered by [Blume](https://useblume.dev),
which is a zero-config documentation framework on Astro and Vite. The marketing
pages are plain Astro, mounted beside the docs through Blume's custom-page
support, and share its header, search and theme toggle.
