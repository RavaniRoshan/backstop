import { test } from "node:test";
import assert from "node:assert/strict";
import { AuditLog } from "../src/audit.js";
import { AIMDController, PriorityGate } from "../src/admission.js";
import { AgentGuard } from "../src/agent.js";
import { ResponseCache } from "../src/cache.js";
import { QuotaMonitor } from "../src/quotas.js";
import { willExhaust, detectSpendAnomaly, projectRemainingSeconds } from "../src/forecast.js";

// --- AuditLog ---

test("audit log is tamper-evident and verifiable", () => {
  const records: string[] = [];
  const log = new AuditLog(records.push.bind(records), "secret");
  log.record("deny", "budget_exceeded", { tenant: "t1", tokens: 12 });
  log.record("fallback", "circuit_open", { model: "gpt-4o-mini" });
  assert.equal(records.length, 2);
  assert.ok(log.verify());
});

test("audit log detects tampering", () => {
  const records: string[] = [];
  const log = new AuditLog(records.push.bind(records), "secret");
  log.record("deny", "budget_exceeded");
  const parsed = JSON.parse(records[0]);
  parsed.reason = "tampered";
  records[0] = JSON.stringify(parsed);
  // Verify against the (tampered) external records.
  assert.equal(log.verify(records), false);
});

// --- AIMD ---

test("AIMD increases under success and decreases under pressure", () => {
  const aimd = new AIMDController({
    initial: 8, min: 1, max: 64, decreaseFactor: 0.5, intervalMs: 0,
  });
  assert.equal(aimd.currentLimit, 8);
  aimd.recordSuccess();
  assert.equal(aimd.currentLimit, 9);
  aimd.recordPressure();
  assert.equal(aimd.currentLimit, 4);
});

test("AIMD respects bounds", () => {
  const aimd = new AIMDController({
    initial: 1, min: 1, max: 64, decreaseFactor: 0.5, intervalMs: 0,
  });
  aimd.recordPressure();
  assert.equal(aimd.currentLimit, 1); // can't go below min
});

// --- PriorityGate ---

test("priority gate admits within concurrency limit", async () => {
  const aimd = new AIMDController({
    initial: 2, min: 1, max: 8, decreaseFactor: 0.5, intervalMs: 0,
  });
  const gate = new PriorityGate(aimd, { starvationMs: 1000, timeoutMs: 100 });
  await gate.acquire("default");
  await gate.acquire("default");
  assert.equal(gate.depth, 0);
  gate.release();
  gate.release();
});

// --- AgentGuard ---

test("agent guard blocks runaway loops", () => {
  const guard = new AgentGuard({ maxCalls: 2, windowMs: 60_000, maxTokens: 100 });
  assert.equal(guard.allow("a", 10), true);
  assert.equal(guard.allow("a", 10), true);
  assert.equal(guard.allow("a", 10), false);
  assert.equal(guard.allow("b", 10), true);
});

test("agent guard enforces token ceiling", () => {
  const guard = new AgentGuard({ maxCalls: 100, windowMs: 60_000, maxTokens: 50 });
  assert.equal(guard.allow("a", 30), true);
  assert.equal(guard.allow("a", 30), false); // 30+30 > 50
});

// --- ResponseCache ---

test("response cache serves exact matches", async () => {
  const embed = (text: string) => {
    const vec = new Array(8).fill(0);
    for (let i = 0; i < text.length; i++) vec[i % 8] += text.charCodeAt(i);
    const norm = Math.sqrt(vec.reduce((n, x) => n + x * x, 0));
    return norm ? vec.map((x) => x / norm) : vec;
  };
  const cache = new ResponseCache({ maxEntries: 256, ttlMs: 60_000, embed, threshold: 0.9 });
  await cache.set({ model: "m", messages: [{ role: "user", content: "hi" }] }, "response", 10);
  const hit = await cache.get({ model: "m", messages: [{ role: "user", content: "hi" }] });
  assert.ok(hit);
  assert.equal(hit!.semantic, false);
  assert.equal(hit!.usage, 10);
});

test("response cache serves near-duplicates semantically", async () => {
  const embed = (text: string) => {
    const vec = new Array(8).fill(0);
    for (let i = 0; i < text.length; i++) vec[i % 8] += text.charCodeAt(i);
    const norm = Math.sqrt(vec.reduce((n, x) => n + x * x, 0));
    return norm ? vec.map((x) => x / norm) : vec;
  };
  const cache = new ResponseCache({ maxEntries: 256, ttlMs: 60_000, embed, threshold: 0.5 });
  await cache.set({ model: "m", messages: [{ role: "user", content: "summarize the report please" }] }, "resp", 10);
  const hit = await cache.get({ model: "m", messages: [{ role: "user", content: "please summarize the report" }] });
  assert.ok(hit);
  assert.equal(hit!.semantic, true);
});

// --- QuotaMonitor ---

test("quota monitor adjusts AIMD on high pressure", () => {
  const aimd = new AIMDController({
    initial: 8, min: 1, max: 64, decreaseFactor: 0.5, intervalMs: 0,
  });
  const mon = new QuotaMonitor(0.85);
  mon.ingest({ "x-ratelimit-limit-requests": "100", "x-ratelimit-remaining-requests": "5" });
  assert.equal(mon.adjust(aimd), true);
  assert.ok(aimd.currentLimit < 8);
});

// --- Forecast ---

test("forecast projects exhaustion correctly", () => {
  assert.equal(willExhaust(800, 10, 1000, 100), true);
  assert.equal(willExhaust(800, 10, 1000, 1), false);
  assert.equal(projectRemainingSeconds(500, 10, 1000), 10);
  assert.equal(detectSpendAnomaly(10, 25, 2), true);
  assert.equal(detectSpendAnomaly(10, 15, 2), false);
});
