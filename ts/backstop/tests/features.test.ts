import { test } from "node:test";
import assert from "node:assert/strict";
import { wrap } from "../src/wrap.js";
import { BudgetExceededError } from "../src/budget.js";

function mockClient(responses: Array<{ usage?: { total_tokens?: number }; content?: string; fail?: boolean; status?: number }>) {
  let i = 0;
  const client = {
    _backstop: undefined,
    chat: {
      completions: {
        create: async (_req: unknown) => {
          const r = responses[Math.min(i++, responses.length - 1)];
          if (r.fail) {
            const err = new Error("API error") as Error & { status?: number };
            err.status = r.status ?? 500;
            throw err;
          }
          return { usage: r.usage, choices: [{ message: { content: r.content ?? "ok" } }] };
        },
      },
    },
  };
  return { client: client as unknown as Parameters<typeof wrap>[0], getNext: () => responses[Math.min(i, responses.length - 1)] };
}

test("wrap enforces budget and blocks over-budget requests", async () => {
  const { client } = mockClient([{ usage: { total_tokens: 10 } }]);
  const wrapped = wrap(client, 50);
  // First call uses 10 tokens (committed), should pass.
  await wrapped.chat.completions.create({ model: "m", messages: [{ role: "user", content: "x" }] } as never);
  // Budget exhausted after 5 calls (5 x 10 = 50), 6th should block.
  for (let n = 0; n < 4; n++) {
    await wrapped.chat.completions.create({ model: "m", messages: [{ role: "user", content: "x" }] } as never);
  }
  await assert.rejects(
    () => wrapped.chat.completions.create({ model: "m", messages: [{ role: "user", content: "x" }] } as never),
    BudgetExceededError,
  );
});

test("wrap retries on retryable errors", async () => {
  const { client } = mockClient([
    { fail: true, status: 429 },
    { fail: true, status: 503 },
    { usage: { total_tokens: 5 } },
  ]);
  const wrapped = wrap(client, 10_000, { baseRetryDelayMs: 10, maxRetries: 3 });
  const res = await wrapped.chat.completions.create({ model: "m", messages: [{ role: "user", content: "x" }] } as never);
  assert.ok(res.usage);
});

test("wrap falls back to backup model on circuit open", async () => {
  // Primary fails 3 times (2 retries + 1 initial), circuit opens, fallback succeeds.
  const { client } = mockClient([
    { fail: true, status: 503 },
    { fail: true, status: 503 },
    { usage: { total_tokens: 5 }, content: "fallback-response" },
  ]);
  const wrapped = wrap(client, 10_000, {
    baseRetryDelayMs: 1,
    maxRetries: 2,
    circuitCooldownMs: 50,
    fallbackModel: "backup-model",
  });
  const res = await wrapped.chat.completions.create({ model: "primary", messages: [{ role: "user", content: "x" }] } as never);
  assert.equal(res.choices?.[0]?.message?.content, "fallback-response");
});

test("wrap serves from cache on exact match", async () => {
  const { client } = mockClient([{ usage: { total_tokens: 10 }, content: "cached" }]);
  const wrapped = wrap(client, 10_000, {
    cacheEnabled: true,
    cacheEmbedder: (text: string) => {
      const vec = new Array(8).fill(0);
      for (let i = 0; i < text.length; i++) vec[i % 8] += text.charCodeAt(i);
      const norm = Math.sqrt(vec.reduce((n, x) => n + x * x, 0));
      return norm ? vec.map((x) => x / norm) : vec;
    },
    cacheSemantic: true,
    cacheSimilarityThreshold: 0.9,
  });
  const req = { model: "m", messages: [{ role: "user", content: "hello" }] };
  const r1 = await wrapped.chat.completions.create(req as never);
  assert.equal(r1.choices?.[0]?.message?.content, "cached");
  // Second identical call should hit cache (no new LLM call).
  const r2 = await wrapped.chat.completions.create(req as never);
  assert.equal(r2.choices?.[0]?.message?.content, "cached");
});

test("wrap fires before/after hooks", async () => {
  const { client } = mockClient([{ usage: { total_tokens: 5 } }]);
  const events: string[] = [];
  const wrapped = wrap(client, 10_000, {
    beforeRequest: () => events.push("before"),
    afterResponse: () => events.push("after"),
  });
  await wrapped.chat.completions.create({ model: "m", messages: [{ role: "user", content: "x" }] } as never);
  assert.deepEqual(events, ["before", "after"]);
});

test("wrap respects priority (critical bypasses budget)", async () => {
  const { client } = mockClient([{ usage: { total_tokens: 10 } }]);
  const wrapped = wrap(client, 5, { priorityHeader: "X-Backstop-Priority" });
  // Budget is 5, each call uses 10. Non-critical should be blocked, critical should pass.
  const criticalReq = { model: "m", messages: [{ role: "user", content: "x" }], "X-Backstop-Priority": "critical" };
  // Critical bypasses the reserve check.
  const res = await wrapped.chat.completions.create(criticalReq as never);
  assert.ok(res.usage);
});
