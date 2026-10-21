import { defineConfig } from "blume";

/**
 * The site is two halves that share one header, one theme and one footer:
 *
 * - the **docs**, which are the repository's own `docs/*.md` files, rendered
 *   by Blume with no copy and no second source of truth;
 * - the **marketing pages**, which are plain Astro routes under `pages/`.
 *
 * The docs live one directory up on purpose: `docs/` is read by people on
 * GitHub, by the `llms.txt` the CLI ships, and by this site. One folder,
 * three readers.
 */
export default defineConfig({
  title: "Backstop",
  description:
    "Hard limits for AI agents. Budgets, circuit breaking and concurrency control, in-process, with no proxy and no network hop.",

  logo: {
    image: "/mark.svg",
    text: "Backstop",
    href: "/",
  },

  // The docs are mounted under /docs, so the marketing pages own the root.
  basePath: "/docs",

  // The site is built for the root of whatever host serves it. A deployment
  // that lives in a subdirectory — a GitHub Pages project site, say — sets
  // SITE_BASE to that prefix, and every link in the site follows it.
  deployment: {
    site: process.env.SITE_URL ?? "https://ravaniroshan.github.io/backstop",
    base: process.env.SITE_BASE ?? "",
  },

  content: {
    // The repository's docs, not a copy of them.
    root: ".content",
    // The marketing pages are Astro routes beside the docs.
    pages: "pages",
  },

  theme: {
    // The dashboard's own accent, so the site and the product it documents
    // are the same colour.
    accent: { light: "#0b62d0", dark: "#58a6ff" },
    radius: "md",
    mode: "system",
    fonts: {
      display: "inter-tight",
      body: "inter",
      mono: "jetbrains-mono",
    },
  },

  markdown: {
    code: {
      icons: false,
      wrap: false,
    },
  },

  github: {
    owner: "RavaniRoshan",
    repo: "backstop",
    branch: "main",
    // The docs live in the repository root, one level above this project.
    dir: "..",
  },

  lastModified: { type: "git" },

  toc: { minHeadingLevel: 2, maxHeadingLevel: 3 },

  // The sidebar is written by hand: fifteen pages in one flat list is a list,
  // not a structure. These are the four questions a reader actually has.
  navigation: {
    actions: [
      { label: "Guides", href: "/docs/quickstart" },
      { label: "Reference", href: "/docs/compatibility" },
    ],
    sidebar: {
      display: "group",
      items: [
        {
          label: "Get started",
          items: [
            { label: "Overview", href: "/docs" },
            { label: "Quickstart", href: "/docs/quickstart" },
            { label: "Installing Backstop", href: "/docs/install" },
            { label: "The built-in dashboard", href: "/docs/dashboard" },
          ],
        },
        {
          label: "How it works",
          items: [
            { label: "Architecture", href: "/docs/architecture" },
            { label: "Dollar budgets", href: "/docs/usd-budgets" },
            { label: "The spend ledger", href: "/docs/ledger" },
            { label: "Runaway-spend detection", href: "/docs/detection" },
            { label: "Concurrency and scale", href: "/docs/concurrency" },
            { label: "Pointing it at any server", href: "/docs/integrations" },
          ],
        },
        {
          label: "Reference",
          items: [
            { label: "Compatibility matrix", href: "/docs/compatibility" },
            { label: "SDK matrix", href: "/docs/sdk-matrix" },
            { label: "Framework adapters", href: "/docs/frameworks" },
          ],
        },
        {
          label: "Operations",
          items: [
            { label: "Budget alerts", href: "/docs/alerts" },
            { label: "Benchmarks", href: "/docs/benchmarks" },
            { label: "Benchmark results", href: "/docs/benchmark-results-2026-10-20" },
            { label: "Threat model", href: "/docs/threat-model" },
          ],
        },
      ],
    },
  },
});
