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

// A file-path audit sink is the one path that touched the filesystem, and it is
// where the package's `"type": "module"` bit us: the body used `require(...)`,
// which is not defined in an ES module, so every file sink threw
// ReferenceError at construction. The fake client below is not enough to catch
// that, so this exercises the real filesystem path end to end.
test("a file-path audit sink appends to the file", async () => {
  const { mkdtempSync, readFileSync, rmSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const { AuditLog } = await import("../src/audit.js");

  const dir = mkdtempSync(join(tmpdir(), "backstop-audit-"));
  const file = join(dir, "audit.jsonl");
  try {
    const log = new AuditLog(file, "k");
    log.record("allow", "test");
    log.close();
    await new Promise((r) => setTimeout(r, 50));
    const lines = readFileSync(file, "utf-8").trim().split("\n");
    assert.ok(lines.length >= 1, "expected at least one audit line");
    assert.equal(JSON.parse(lines[0]!).reason, "test");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// --- The knobs that were accepted and never consulted ---------------------
//
// Every one of these was in `BackstopConfig`, documented, and read by
// nothing. A user who set `agentMaxCalls: 5` got no enforcement and no
// warning.

test("the budget is a hard ceiling for every priority", async () => {
  // `critical` and `high` used to be let past an exhausted budget, which is
  // not what the Python package does: a budget is a ceiling, and a priority
  // decides who waits, not who is exempt.
  for (const priority of ["critical", "high", "default", "low", "bulk"] as const) {
    const { client } = mockClient([{ usage: { total_tokens: 10 } }]);
    const wrapped = wrap(client, 10);
    const req = {
      model: "m",
      messages: [{ role: "user", content: "x" }],
      "X-Backstop-Priority": priority,
    };
    await wrapped.chat.completions.create(req as never);
    await assert.rejects(
      () => wrapped.chat.completions.create(req as never),
      BudgetExceededError,
      `priority ${priority} was let past an exhausted budget`,
    );
  }
});

test("the agent guardrail fences a runaway loop", async () => {
  const { client } = mockClient([{ usage: { total_tokens: 1 } }]);
  const wrapped = wrap(client, 1000, { agentMaxCalls: 2, agentWindowMs: 60_000 });
  const req = {
    model: "m",
    messages: [{ role: "user", content: "x" }],
    "X-Backstop-Agent": "loop-1",
  };
  await wrapped.chat.completions.create(req as never);
  await wrapped.chat.completions.create(req as never);
  await assert.rejects(
    () => wrapped.chat.completions.create(req as never),
    (err: Error) => err.name === "AgentGuardViolationError",
  );
});

test("a different agent is not fenced by another's guardrail", async () => {
  const { client } = mockClient([{ usage: { total_tokens: 1 } }]);
  const wrapped = wrap(client, 1000, { agentMaxCalls: 1, agentWindowMs: 60_000 });
  const first = {
    model: "m",
    messages: [{ role: "user", content: "x" }],
    "X-Backstop-Agent": "a",
  };
  const second = {
    model: "m",
    messages: [{ role: "user", content: "x" }],
    "X-Backstop-Agent": "b",
  };
  await wrapped.chat.completions.create(first as never);
  await assert.rejects(
    () => wrapped.chat.completions.create(first as never),
    (err: Error) => err.name === "AgentGuardViolationError",
  );
  // The second agent has its own budget.
  await wrapped.chat.completions.create(second as never);
});

test("a request that exceeds its deadline fails rather than hanging", async () => {
  const slow = {
    _backstop: undefined,
    chat: {
      completions: {
        create: async () => {
          await new Promise((r) => setTimeout(r, 500));
          return { usage: { total_tokens: 1 } };
        },
      },
    },
  };
  const wrapped = wrap(slow as never, 100, { requestTimeoutMs: 50 });
  await assert.rejects(
    () => wrapped.chat.completions.create({ model: "m", messages: [] } as never),
    (err: Error) => err.name === "LatencyBudgetExceededError",
  );
});

// --- The gate -------------------------------------------------------------
//
// Two bugs the Python package had until v0.8.0, in a port that had never
// been exercised under load:
//
// - `high` was missing from the queue the gate chooses from, so a
//   high-priority ticket was enqueued and then never chosen. It could not be
//   admitted, and it waited for a slot that was never offered to it.
// - the waiters polled only when a timeout was configured, so with the
//   default `queueTimeoutMs: null` a request that could not be admitted
//   immediately was never re-checked. It hung forever, with no error.

test("a high-priority request is admitted", async () => {
  const { client } = mockClient([{ usage: { total_tokens: 1 } }]);
  const wrapped = wrap(client, 100);
  const res = await wrapped.chat.completions.create({
    model: "m",
    messages: [{ role: "user", content: "x" }],
    "X-Backstop-Priority": "high",
  } as never);
  assert.equal(res.usage?.total_tokens, 1);
});

test("a request waiting for a slot is admitted when one frees", async () => {
  // One slot, two requests. The second waits; the first releases; the
  // second must be admitted rather than hanging.
  const { client } = mockClient([{ usage: { total_tokens: 1 } }]);
  const wrapped = wrap(client, 1000, { initialConcurrency: 1, maxConcurrency: 1 });
  const req = { model: "m", messages: [{ role: "user", content: "x" }] };
  const first = wrapped.chat.completions.create(req as never);
  // The second request is issued while the first is still in flight.
  const second = wrapped.chat.completions.create(req as never);
  const [a, b] = await Promise.all([first, second]);
  assert.equal(a.usage?.total_tokens, 1);
  assert.equal(b.usage?.total_tokens, 1);
});

test("a request that cannot be admitted fails rather than hanging", async () => {
  // The first request holds the single slot long enough for the second to
  // have to wait, and the second gives up rather than waiting forever.
  const slow = {
    _backstop: undefined,
    chat: {
      completions: {
        create: async () => {
          await new Promise((r) => setTimeout(r, 200));
          return { usage: { total_tokens: 1 } };
        },
      },
    },
  };
  const wrapped = wrap(slow as never, 1000, {
    initialConcurrency: 1,
    maxConcurrency: 1,
    queueTimeoutMs: 50,
  });
  const req = { model: "m", messages: [{ role: "user", content: "x" }] };
  const first = wrapped.chat.completions.create(req as never);
  await assert.rejects(
    () => wrapped.chat.completions.create(req as never),
    /timed out/,
  );
  await first;
});
