#!/usr/bin/env node
/**
 * Check every internal link in the built site against the built files.
 *
 * A marketing site and a documentation site fail the same way: a link to a
 * page that does not exist. This walks the output, resolves each internal
 * href, and reports the ones that land nowhere. It is a build-time check, not
 * a test dependency.
 */
import { readdir, readFile, stat } from "node:fs/promises";
import { join, resolve, relative } from "node:path";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dist = resolve(here, "..", "dist");

async function walk(dir) {
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await walk(full)));
    else if (entry.name.endsWith(".html")) out.push(full);
  }
  return out;
}

const exists = async (path) => {
  try {
    await stat(path);
    return true;
  } catch {
    return false;
  }
};

const pages = await walk(dist);
const broken = [];
const seen = new Set();

for (const page of pages) {
  const html = await readFile(page, "utf8");
  for (const match of html.matchAll(/href="([^"]+)"/g)) {
    const href = match[1];
    if (/^(https?:|mailto:|tel:|data:|#)/.test(href)) continue;
    // A `href="..."` inside an inline script is not a link.
    if (/[\s"'`<>]/.test(href)) continue;
    const [path, hash] = href.split("#");
    if (!path) continue;
    const key = path + (hash ?? "");
    if (seen.has(key)) continue;
    seen.add(key);
    const target = path.startsWith("/")
      ? join(dist, path)
      : resolve(dirname(page), path);
    let ok = await exists(target);
    if (!ok && !path.endsWith("/")) ok = await exists(target + "/index.html");
    if (!ok && path.endsWith("/")) ok = await exists(join(target, "index.html"));
    if (!ok) broken.push(`${relative(dist, page)} -> ${href}`);
  }
}

if (broken.length) {
  console.error(`${broken.length} broken link(s):`);
  for (const line of broken) console.error("  " + line);
  process.exit(1);
}
console.log(`checked ${seen.size} internal link(s) across ${pages.length} page(s): all resolve`);
