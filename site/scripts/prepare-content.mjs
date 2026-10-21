#!/usr/bin/env node
/**
 * Prepare the documentation content for the site.
 *
 * The repository's `docs/*.md` files are written for people reading them on
 * GitHub: each one opens with its own `# Title` heading. Blume's page layout
 * renders the page title itself, so a document that also carries a `# Title`
 * shows the title twice.
 *
 * Rather than edit the repository's docs to suit the site, this script
 * derives the site's content from them: the leading `# Title` becomes the
 * frontmatter title, the first paragraph becomes the description, and the
 * body is copied through untouched. One source of truth, two surfaces.
 *
 * The output is a build artefact: `site/.content/`, which is git-ignored.
 */
import { readdir, readFile, mkdir, writeFile, rm } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const siteRoot = resolve(here, "..");
const docsRoot = resolve(siteRoot, "..", "docs");
const outRoot = join(siteRoot, ".content");

/**
 * One line per document: what it is for, in the reader's words.
 *
 * Written by hand rather than derived, because a derived summary is a
 * truncation of the first paragraph, and a truncated lede reads like a
 * mistake. The page shows this under the title, and it is the page's meta
 * description.
 */
const DESCRIPTIONS = {
  alerts:
    "A webhook when a budget crosses a threshold, so the person who owns the budget hears about it while there is still budget left.",
  architecture:
    "An in-process control layer for the official provider SDKs: budgets, admission control, retries, circuit breaking, caching and metrics, around the transport.",
  "benchmark-results-2026-07-20":
    "A superseded overhead snapshot, kept for history: the date, the seed, the transport and the request count, and not the host.",
  "benchmark-results-2026-10-20":
    "The only committed overhead figures for this project, with the host, the seed, the transport and both payload sizes.",
  benchmarks:
    "How the overhead numbers are measured, what they include, and what they do not.",
  compatibility:
    "Which SDK versions are tested, which are not, and what the matrix does not claim.",
  concurrency:
    "What running in your own process means for the GIL, and where the concurrency ceiling actually is.",
  dashboard:
    "A dependency-free operations dashboard: budgets, concurrency, breaker state, sessions and enforcement events, with no Prometheus.",
  detection:
    "Four detectors that notice a spend pattern before it becomes an invoice: velocity, drift, retry amplification and context growth.",
  frameworks:
    "Backstop sits under the framework, at the transport, so any framework works without knowing Backstop exists.",
  index:
    "Backstop puts budgets, a circuit breaker and concurrency limits on AI agents, in the process that calls them.",
  install: "Every install path: pip, pipx, uv, air-gapped, and from source.",
  ledger:
    "What your traffic actually cost, grouped by whoever is responsible for it, with a charge-back export.",
  quickstart: "Get to a working budget guardrail in under 60 seconds.",
  "sdk-matrix": "Which SDK version combinations CI actually proves, one row at a time.",
  "threat-model": "What Backstop trusts, what it does not, and where its limits are.",
  "usd-budgets":
    "A ceiling in money, priced from the model you actually call, with the arithmetic done in decimals.",
};

/** Split YAML-ish frontmatter off the top of a document. */
function splitFrontmatter(text) {
  const match = /^---\n([\s\S]*?)\n---\n?/.exec(text);
  if (!match) return { frontmatter: {}, body: text };
  const frontmatter = {};
  for (const line of match[1].split("\n")) {
    const separator = line.indexOf(":");
    if (separator === -1) continue;
    const key = line.slice(0, separator).trim();
    let value = line.slice(separator + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (key) frontmatter[key] = value;
  }
  return { frontmatter, body: text.slice(match[0].length) };
}

/** The first `# Title` line, and the body without it. */
function splitTitle(body) {
  const leading = body.length - body.trimStart().length;
  const match = /^#\s+(.+?)\s*\n+/.exec(body.slice(leading));
  if (!match) return { title: null, body };
  return { title: match[1], body: body.slice(leading + match[0].length) };
}

/** The first paragraph, as one line of plain text, and where it ends. */
function firstParagraph(body) {
  const lines = body.split("\n");
  const paragraph = [];
  let end = 0;
  for (const line of lines) {
    if (line.trim() === "") {
      if (paragraph.length) break;
      end += line.length + 1;
      continue;
    }
    if (line.startsWith("```") || line.startsWith("|") || line.startsWith("#")) break;
    paragraph.push(line.trim());
    end += line.length + 1;
  }
  let text = paragraph.join(" ");
  // Markdown links become their text; inline code keeps its backticks.
  text = text.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
  text = text.replace(/\s+/g, " ").trim();
  return { text, end };
}

/**
 * Rewrite the links a document written for GitHub cannot keep.
 *
 * A sibling written as `install.md` works on GitHub and breaks here: the
 * site serves `/docs/install`, and the raw Markdown at `/docs/install.md` is
 * a different page. A link that leaves the docs folder — a source file, an
 * examples directory — points at the repository on GitHub.
 */
// The same base the site is built with: empty for a site at the root of its
// host, a prefix for one that lives in a subdirectory.
const SITE_BASE = (process.env.SITE_BASE ?? "").replace(/\/$/, "");
const DOC_ROUTES = {
  base: `${SITE_BASE}/docs`,
  repo: "https://github.com/RavaniRoshan/backstop",
};

function rewriteLinks(body) {
  return body.replace(/\]\(([^)\s]+)(\s+"[^"]*")?\)/g, (match, target, title) => {
    if (/^(https?:|mailto:|#)/.test(target)) return match;
    const [path, hash] = target.split("#");
    const suffix = hash ? `#${hash}` : "";
    if (/\.mdx?$/.test(path)) {
      const slug = path.replace(/\.mdx?$/, "").replace(/\/index$/, "");
      return `](${DOC_ROUTES.base}/${slug}${suffix}${title ?? ""})`;
    }
    if (path.startsWith("../")) {
      const inRepo = path.replace(/^\.\.\//, "");
      const url = `${DOC_ROUTES.repo}/${inRepo.endsWith("/") ? "tree" : "blob"}/main/${inRepo}`;
      return `](${url}${suffix}${title ?? ""})`;
    }
    return match;
  });
}

function quote(value) {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

async function main() {
  await rm(outRoot, { recursive: true, force: true });
  await mkdir(outRoot, { recursive: true });

  const files = (await readdir(docsRoot)).filter((name) => name.endsWith(".md"));
  const written = [];

  for (const file of files) {
    const raw = await readFile(join(docsRoot, file), "utf8");
    const { frontmatter, body } = splitFrontmatter(raw);
    const { title: heading, body: withoutHeading } = splitTitle(body);
    const slug = file.replace(/\.md$/, "");
    const title = frontmatter.title ?? heading ?? slug;
    const paragraph = firstParagraph(withoutHeading);
    const description = frontmatter.description ?? DESCRIPTIONS[slug] ?? paragraph.text;
    // When the description is the document's own first paragraph, the page
    // would show it twice — once under the title, once in the body. The
    // paragraph is dropped in that case, and kept otherwise, where it is the
    // lede the description introduces.
    const preparedBody =
      paragraph.text && paragraph.text === description
        ? withoutHeading.slice(paragraph.end).replace(/^\n+/, "")
        : withoutHeading;

    const front = [
      "---",
      `title: ${quote(title)}`,
      ...(description ? [`description: ${quote(description)}`] : []),
      "---",
      "",
    ].join("\n");

    const prepared = rewriteLinks(preparedBody.replace(/^\n+/, ""));
    await writeFile(join(outRoot, file), front + "\n" + prepared, "utf8");
    written.push(file);
  }

  console.log(`prepared ${written.length} document(s) in ${outRoot}`);
}

await main();
