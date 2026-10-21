#!/usr/bin/env node
/**
 * Compile the committed brand marks into a typed module.
 *
 * The marks are fetched once, committed, and compiled here into plain data:
 * a slug, a title, a viewBox and the inner SVG markup. The components draw
 * them with `set:html`, so a mark can be tinted, sized and animated like any
 * other part of the diagram, and nothing is fetched at runtime.
 */
import { readdir, readFile, mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const logoDir = resolve(here, "..", "assets", "logos");
const outFile = resolve(here, "..", "src", "data", "logos.ts");

/** The names a reader knows the marks by. */
const TITLES = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  "anthropic-wordmark": "Anthropic",
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
  aws: "Amazon Bedrock",
  azure: "Azure OpenAI",
  vertex: "Google Vertex AI",
  docker: "Docker",
  kubernetes: "Kubernetes",
  redis: "Redis",
  postgres: "PostgreSQL",
};

const files = (await readdir(logoDir)).filter((name) => name.endsWith(".svg")).sort();
const entries = [];

/**
 * The ink bounds of every committed mark, measured in its own user units.
 *
 * Most brand SVGs are drawn inside a square box with the artwork filling only
 * part of it: the AWS mark uses 14 of its 24 units, NVIDIA 16, Mistral 17.
 * Rendered at one height, those marks come out visibly smaller than the ones
 * that fill their box — a logo strip with three sizes in it.
 *
 * Cropping the viewBox to the artwork makes the box *be* the artwork, so one
 * rendered height is one optical height for every mark. The numbers were
 * measured by rendering each committed SVG and asking the browser for the
 * painted bounds; the SVGs are committed, so the numbers cannot drift.
 *
 * Antigravity is left alone: its mark carries a filter whose glow reaches
 * past the viewBox, so cropping to it would cut the glow off.
 */
const VIEWBOX_CROPS = {
  anthropic: "0 0 256 175.78",
  "anthropic-wordmark": "0 0 512 57.49",
  aws: "0 4.82 24 14.35",
  azure: "0 0.66 24 22.69",
  baseten: "0 0 512 111.72",
  claude: "0.01 0 23.98 24",
  "claude-code": "0 4.5 24 15",
  cline: "0.53 0 22.94 24",
  codex: "0 0 256 256",
  cohere: "0 0 511.99 87.78",
  copilot: "0 1.98 24 20.04",
  cursor: "1.47 0 21.06 24",
  deepinfra: "0 0 511.99 87.68",
  docker: "0 3.39 24 17.22",
  google: "0.31 0 23.39 24",
  groq: "0 0 511.99 145.29",
  huggingface: "0 1.13 24 21.74",
  kubernetes: "0.53 0.17 255.42 248.72",
  lmstudio: "0 0 24 24",
  mistral: "0 3.43 24 17.14",
  nvidia: "0 4.06 24 15.87",
  ollama: "0 0 256 338.36",
  openai: "0.16 0 23.67 24",
  openrouter: "0 1.84 24 20.31",
  postgres: "0.3 0.37 255.38 263.3",
  redis: "0 0.59 255.99 218.58",
  replicate: "0 0 24 24",
  together: "0 1 511.99 108.81",
  vertex: "3.87 2.63 16.26 18.65",
  vllm: "0.4 0 23.2 24",
  windsurf: "0 5.06 24 13.87",
  zed: "0 0 128 128",
};

/**
 * A mark that is one flat colour is a monochrome mark that happens to have the
 * colour baked in — the Codex mark is #111, which vanishes on a dark page, and
 * a few wordmarks carry no fill at all and therefore inherit the default
 * black. Rewrite those to currentColor so the page can tint them like any
 * other text. A mark with more than one colour, a gradient or a filter is
 * left exactly as it is: that is what the brand actually looks like.
 */
function normalise(svg, body) {
  if (/<(linearGradient|radialGradient|filter|mask|clipPath)\b/.test(svg)) {
    return { body, monochrome: false };
  }
  const colours = new Set(
    [...svg.matchAll(/fill="([^"]+)"/g)].map((match) => match[1]),
  );
  const paint = [...colours].filter((c) => c !== "none");
  if (paint.length === 0) {
    // No fill anywhere: the default black applies. Make it explicit and tintable.
    const tinted = body.replace(/<(path|g|polygon|rect|circle)\b/, (tag) => `${tag} fill="currentColor"`);
    return { body: tinted, monochrome: true };
  }
  if (paint.length === 1 && paint[0] !== "currentColor") {
    const only = paint[0];
    return {
      body: body.replaceAll(`fill="${only}"`, 'fill="currentColor"'),
      monochrome: true,
    };
  }
  return { body, monochrome: paint.every((c) => c === "currentColor") };
}

/**
 * A mark much wider than it is tall is a wordmark: the brand's name, drawn.
 * It carries its own name, so the page shows it instead of a name beside it.
 */
function isWordmark(viewBox) {
  const parts = viewBox.split(/\s+/).map(Number);
  if (parts.length !== 4 || !parts[2] || !parts[3]) return false;
  return parts[2] / parts[3] > 2.2;
}

for (const file of files) {
  const slug = file.replace(/\.svg$/, "");
  const svg = await readFile(join(logoDir, file), "utf8");
  const source = /viewBox="([^"]+)"/.exec(svg)?.[1] ?? "0 0 24 24";
  const viewBox = VIEWBOX_CROPS[slug] ?? source;
  const raw = svg
    .replace(/^[\s\S]*?<svg[^>]*>/, "")
    .replace(/<\/svg>\s*$/, "")
    .trim();
  const { body, monochrome } = normalise(svg, raw);
  entries.push(
    `  ${JSON.stringify(slug)}: {\n` +
      `    slug: ${JSON.stringify(slug)},\n` +
      `    title: ${JSON.stringify(TITLES[slug] ?? slug)},\n` +
      `    viewBox: ${JSON.stringify(viewBox)},\n` +
      `    monochrome: ${monochrome},\n` +
      `    wordmark: ${isWordmark(viewBox)},\n` +
      `    body: ${JSON.stringify(body)},\n` +
      `  },`,
  );
}

const module =
  `// Generated by scripts/prepare-logos.mjs. Do not edit.\n` +
  `//\n` +
  `// The brand marks the marketing page draws, compiled from the committed SVGs\n` +
  `// in assets/logos/ so that nothing is fetched at runtime.\n\n` +
  `export interface Logo {\n` +
  `  slug: string;\n` +
  `  title: string;\n` +
  `  viewBox: string;\n` +
  `  monochrome: boolean;\n` +
  `  wordmark: boolean;\n` +
  `  body: string;\n` +
  `}\n\n` +
  `export const logos: Record<string, Logo> = {\n${entries.join("\n")}\n};\n`;

await mkdir(dirname(outFile), { recursive: true });
await writeFile(outFile, module, "utf8");
console.log(`compiled ${entries.length} logo(s) into src/data/logos.ts`);
