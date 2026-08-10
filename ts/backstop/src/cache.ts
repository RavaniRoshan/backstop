import type { ChatCompletionRequest, Usage } from "./types.js";

function cosine(a: number[], b: number[]): number {
  if (!a.length || !b.length) return 0;
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na += a[i] * a[i];
    nb += b[i] * b[i];
  }
  na = Math.sqrt(na);
  nb = Math.sqrt(nb);
  if (na === 0 || nb === 0) return 0;
  return dot / (na * nb);
}

function makeKey(body: ChatCompletionRequest): string {
  const messages = JSON.stringify(body.messages ?? "");
  return `${body.model}:${messages}`;
}

interface CacheEntry {
  content: string;
  usage: number;
  embedding: number[] | null;
}

/**
 * Response cache with exact + semantic (near-duplicate) matching.
 * Mirrors the Python ResponseCache.
 */
export class ResponseCache {
  private maxEntries: number;
  private ttlMs: number;
  private embed: ((text: string) => number[] | Promise<number[]>) | null;
  private threshold: number;
  private cache = new Map<string, { at: number; entry: CacheEntry }>();
  private embeddings = new Map<string, number[]>();

  constructor(opts: {
    maxEntries: number;
    ttlMs: number;
    embed: ((text: string) => number[] | Promise<number[]>) | null;
    threshold: number;
  }) {
    this.maxEntries = opts.maxEntries;
    this.ttlMs = opts.ttlMs;
    this.embed = opts.embed;
    this.threshold = opts.threshold;
  }

  async get(body: ChatCompletionRequest): Promise<{ content: string; usage: number; semantic: boolean } | null> {
    const key = makeKey(body);
    const hit = this.cache.get(key);
    if (hit) {
      if (Date.now() - hit.at > this.ttlMs) {
        this.cache.delete(key);
      } else {
        return { content: hit.entry.content, usage: hit.entry.usage, semantic: false };
      }
    }
    if (!this.embed) return null;
    return this.semanticGet(body);
  }

  private async semanticGet(body: ChatCompletionRequest): Promise<{ content: string; usage: number; semantic: boolean } | null> {
    if (!this.embed) return null;
    const text = `${body.model}:${JSON.stringify(body.messages ?? "")}`;
    const qEmb = await this.embed(text);
    let bestKey: string | null = null;
    let bestScore = this.threshold;
    let now = Date.now();
    for (const [k, v] of this.cache) {
      if (now - v.at > this.ttlMs) {
        this.cache.delete(k);
        this.embeddings.delete(k);
        continue;
      }
      const emb = this.embeddings.get(k);
      if (!emb) continue;
      const score = cosine(qEmb, emb);
      if (score >= bestScore) {
        bestScore = score;
        bestKey = k;
      }
    }
    if (!bestKey) return null;
    const entry = this.cache.get(bestKey)!.entry;
    return { content: entry.content, usage: entry.usage, semantic: true };
  }

  async set(body: ChatCompletionRequest, content: string, usage: number): Promise<void> {
    const key = makeKey(body);
    const entry: CacheEntry = { content, usage, embedding: null };
    if (this.cache.size >= this.maxEntries) {
      const first = this.cache.keys().next().value;
      if (first) {
        this.cache.delete(first);
        this.embeddings.delete(first);
      }
    }
    this.cache.set(key, { at: Date.now(), entry });
    if (this.embed) {
      try {
        const text = `${body.model}:${JSON.stringify(body.messages ?? "")}`;
        const emb = await this.embed(text);
        entry.embedding = emb;
        this.embeddings.set(key, emb);
      } catch {
        // ignore embed failures
      }
    }
  }

  clear(): void {
    this.cache.clear();
    this.embeddings.clear();
  }

  get size(): number {
    return this.cache.size;
  }
}
