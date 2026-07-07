Good — this changes the integration model. Read your actual plan.md and my last message guessed wrong on one core piece. Correcting that now instead of quietly carrying the error forward.

## What I got wrong last message

I designed the integration as "wedge tool produces a disagreement signal → Backstop consumes it as a backpressure input." That doesn't match what Backstop actually is. Backstop is a **transport-layer budget/concurrency/circuit-breaker wrapper around a single client** (`Backstop.wrap(client, budget=...)`) — it has no concept of "disagreement" and isn't built to consume external signals. It protects LLM calls from runaway cost and provider overload. That's the whole job, deliberately (see its own Non-Goals section — no observability platform, no MCP tool, no caching).

Also: your memory notes describe Backstop as "MCP-churn-resistant." The actual plan says the opposite explicitly — Not an MCP tool — protocol-agnostic. Works with any SDK client that uses httpx/requests under the hood. Worth knowing your own notes drifted from the source doc. Same discipline you asked me to apply to HN stats applies to your own docs too.

## The real integration (correct this time)

Backstop doesn't consume anything from the wedge tool. It sits **underneath** it, as infrastructure:

```
Wedge tool (isolated multi-agent diff CLI)
        │
        ├──► Runner A: Backstop.wrap(Anthropic(), budget=20_000)
        ├──► Runner B: Backstop.wrap(Anthropic(), budget=20_000)
        └──► Runner C: Backstop.wrap(Anthropic(), budget=20_000)
                        │
              (each runner = one Backstop session,
               own budget, own kill-switch —
               isolated CONTEXT, not isolated INFRA)
```

The distinction that matters: **isolation** in your wedge tool thesis means no shared reasoning/conversation history between agents. It does not mean each agent's API calls need separate reliability infrastructure. Backstop's job — budget cap, circuit breaker, concurrency control — operates at the transport layer, below the prompt/context layer entirely. Wrapping each runner in Backstop doesn't compromise the isolation thesis. It protects you from a very real, very on-brand risk: **running 3 parallel agents instead of 1 triples your runaway-cost exposure.** That's not a stretch integration — that's Backstop's exact $47k story, except now with 3x the agents making it 3x more likely.

**One real blocker:** Backstop's MVP explicitly ships OpenAI-only — Anthropic/Gemini SDK wrapping — MVP ships with OpenAI support only; architecture supports adding providers via transport adapter. Your coding agent stack is Claude, not OpenAI. So there's one honest architecture decision to make before Day 1: add a thin Anthropic transport adapter to Backstop, or build the wedge tool on OpenAI for now and port later. I'm defaulting to **add the adapter** — it's a half-day task, it's exactly what Backstop's architecture was built to support, and it's driven by a real internal consumer (the wedge tool) rather than speculative demand. That's the *good* kind of scope expansion — flag it as a deliberate exception, not creep.

**One open question I won't fake an answer to:** the plan doesn't specify whether Backstop's AIMD/circuit-breaker state is shared across multiple `wrap()` calls or scoped per-instance. Running 3 concurrent wrapped clients is exactly the scenario that will force an answer. Treat that as a real finding from Day 4, not something to assume upfront.

## Revised build plan

**Day 0 (half day) — Backstop: Anthropic adapter**
- Mirror the existing OpenAI transport wrapper module for Anthropic's httpx-based client
- Budget guard, circuit breaker, retry logic stay provider-agnostic — only the transport interception point changes
- Verification: `Backstop.wrap(Anthropic(), budget=1_000)` kills after budget exhausted, same as the OpenAI test in Backstop's own Day 1-2 verification

**Day 1 — Scope lock**
- One-pager: task input format, disagreement signal schema, CLI shape
- Narrow task type: single-function implementation against a given test file
- Kill criterion set now: if 3 isolated agents can't run a real task end-to-end with comparable diffs by Day 7, stop

**Day 2 — Isolation harness**
- Git worktrees, each runner gets its own temp dir
- Each runner instantiates its own `Backstop.wrap(Anthropic(), budget=20_000, config=BackstopConfig(...))` — own session, own kill-switch
- No shared conversation history between runners (isolation thesis lives here, not in the Backstop layer)

**Day 3 — Task loader + single-runner path**
- Prove one lane end-to-end: prompt → Backstop-wrapped call → patch → tests run
- Confirm budget decrements correctly per call

**Day 4 — Parallel execution (the real test)**
- Launch 2-3 runners concurrently
- Watch what actually happens to Backstop's AIMD/circuit-breaker state across 3 simultaneous wrapped clients — this is the open question above, resolved empirically
- Timeout/failure handling per runner independent of the others

**Day 5 — Diff engine v1**
- difflib line/hunk comparison across patches, similarity score per file touched
- No AST-level semantic diffing yet — that's v2

**Day 6 — CLI + report**
- `wedge run task.yaml` → terminal summary (converge/partial/diverge) + markdown report with side-by-side diffs
- Surface each runner's Backstop budget usage in the report too — free data, and it's the first real usage evidence for Backstop's own differentiation matrix

**Day 7 — Dogfood + ship**
- Run against 5-10 real small tasks from your own repos
- Push public, README states the thesis as hypothesis not proven result
- Reply into the HN thread, launch normally

## 14-day validation window (unchanged from before)
Same three numbers: stars/forks, real issues/PRs from strangers, any HN reply. Kill criterion and keep criterion both still hold as stated last message.

## Rebrand — sharper answer now that I've seen the real doc

Don't rebrand. Don't even treat this as "combining two products." Your own plan.md already names the slot this belongs in: 5. Sandboxed Agent Execution Environment — item 5 in your own 5-build portfolio roadmap. This wedge tool is a 7-day spike that pulls Build #5 forward and de-scopes it into something testable in two weeks, using Backstop (Build #2) as a dependency. That's it. No new name, no new README-from-scratch, no new positioning to maintain. You already had the taxonomy — use it instead of inventing one.

If the 14-day validation earns it, Build #5 gets promoted in your roadmap with real evidence behind it, and the story becomes "Backstop protects single sessions; the sandboxed execution environment protects multi-agent sessions, and here's the usage data proving both are needed." One coherent narrative, two separate repos, zero rebrand.
