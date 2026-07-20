import { test } from "node:test";
import assert from "node:assert/strict";
import { wrap, BudgetExceededError } from "../src/index.js";
import type { ChatCompletionRequest, ChatCompletionResponse, OpenAILikeClient } from "../src/types.js";

function makeClient(handler: (req: ChatCompletionRequest) => ChatCompletionResponse): OpenAILikeClient {
  return {
    chat: { completions: { create: async (req: ChatCompletionRequest) => handler(req) } },
  };
}

test("enforces budget and reconciles actual usage", async () => {
  const client = wrap(
    makeClient((req) => ({ usage: { prompt_tokens: 5, completion_tokens: 5, total_tokens: 10 } })),
    20,
  );
  const res = await client.chat.completions.create({ model: "m", messages: [{ role: "user", content: "hi" }] });
  assert.equal(res.usage?.total_tokens, 10);
  await assert.rejects(
    () => client.chat.completions.create({ model: "m", messages: [{ role: "user", content: "x".repeat(1000) }] }),
    (e: unknown) => e instanceof BudgetExceededError,
  );
});

test("falls back once the circuit opens", async () => {
  let fellBack = false;
  const client = wrap(
    makeClient((req) => {
      if (req.model === "gpt-4o-mini") {
        fellBack = true;
        return { usage: { total_tokens: 3 } };
      }
      throw Object.assign(new Error("rate limited"), { status: 429 });
    }),
    100,
    { fallbackModel: "gpt-4o-mini", maxRetries: 1, baseRetryDelayMs: 1 },
  );
  const res = await client.chat.completions.create({ model: "gpt-4.1-mini", messages: [{ role: "user", content: "hi" }] });
  assert.equal(fellBack, true);
  assert.equal(res.usage?.total_tokens, 3);
});
