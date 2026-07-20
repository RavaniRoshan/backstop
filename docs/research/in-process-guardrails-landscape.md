# In-Process / Library-Level LLM Guardrails — Landscape & Recommendations

> Scope: **in-process / library-level** techniques only (Python/TypeScript). No proxy-based solutions.
> Backstop = in-process budget/concurrency/circuit-breaker wrapper around a single LLM client (`Backstop.wrap(client, budget=...)`).
> Angle: cost / token / throughput guardrails (the Backstop axis), not safety/validation guardrails.
> Status: research findings feed a larger synthesis — this is **not** the final synthesis report.

---

## 1. Technique / library findings

### Retry / backoff — `tenacity`
- **Maturity: high.** Current 8.2.x, Apache-2.0, de-facto Python retry standard (PyPI widely adopted).
- Decorator + context-manager + async (`AsyncRetrying`). Stop/wait combinators, exponential backoff + jitter, `retry_if_exception_type`, `retry_if_result`, `before_sleep` logging, `statistics`.
- Generic — not LLM-aware (no built-in token/rate-limit semantics), but trivially wraps OpenAI/Anthropic calls.
- Backstop already overlaps on "retry"; could adopt rather than reimplement.

### Rate limiting — token-bucket / leaky-bucket libs
- **`pyrate-limiter`** (v3.x, MIT): leaky-bucket, multi-rate (hour/day/month), memory/SQLite/Redis backends, async, decorator/context-manager, `BucketFullException` (raise or `delay=True` with `max_delay`). Mature, pluggable backends via `AbstractBucket`.
- **`aiometer`** (smaller/niche): `aiometer.amap(..., max_at_once=N, max_per_second=M)` — combines concurrency cap + rate cap in one async primitive. Lower adoption than pyrate-limiter.
- **`ratelimit`** (older, simple decorator) and custom token-bucket (OneUptime 2026 blog shows in-memory + Redis Lua token bucket with **per-operation `cost`**).
- **Key pattern for Backstop:** variable token cost per request (charge 1 for a read, 50 for an export). OneUptime demonstrates this explicitly; pyrate-limiter charges 1 unit/op but can be extended.

### Semantic / LLM caching — `GPTCache` (+ LangChain/Instructor caches)
- **`GPTCache`** (zilliztech, 8.1k★, pre-1.0 v0.1.44, 2024-08, MIT): semantic cache via embedding + vector store + similarity evaluator; backends SQLite/DuckDB/Postgres/Redis + Milvus/FAISS/Chroma. README warns "under heavy development, API may change." No new API/model support by policy.
- LangChain native `llm_cache` = exact-match only (simpler). `instructor` (2025) ships native `AutoCache`/`RedisCache`; `functools.cache` gave 207,636x speedup on repeats, diskcache/Redis 5–50x.
- **Validated savings:** 50–80% cost at 50–80% hit rate (Instructor benchmarks). GPTCache's "10x cost / 100x latency" is unverified marketing.
- Maturity: caching well-understood; semantic caching powerful but adds embedding cost/latency + staleness trade-offs. **Backstop has no cache layer today.**

### Token estimation / budgeting — `tiktoken` + sliding-window budgeting
- **`tiktoken`** (OpenAI official, Rust core, fast): deterministic BPE counts; `encoding_for_model`, `num_tokens_from_messages` (system + 3/msg overhead). Exact pre-request token counts → enforce context-window and hard token budgets **before** the call.
- **Emerging practice** (Galileo 2026, OpenAI cookbook): allocate budgets across components (30% system / 50% history / 20% buffer), sliding-window truncation, per-agent token budgets, importance-based retention.
- "Speculative/estimated token budgeting" = pre-request tiktoken estimation + DIY budget allocation — **not a single off-the-shelf library.**
- Backstop's "token budgets" feature is the natural home for this.

### Prompt compression — `LLMLingua` / `LongLLMLingua` (Microsoft)
- Coarse (document-level perplexity) + fine-grained (token-level perplexity) compression using a small local model (LLaMA-2-7B).
- LongLLMLingua targets long-context RAG; demo compressed 10k→275 tokens (~38x), same answer; cited ~$28.5 saved/1k samples, up to 20x faster inference. Integrates with LlamaIndex/LangChain.
- Trade-off: requires local compression model (GPU), adds latency, quality-loss risk; best for repeated/RAG contexts, not latency-critical or regulated output.
- Maturity: research-grade but real — a "budget saver" hook for Backstop.

### In-process guardrails landscape (competitive / adjacent)
- **`litellm`** (BerriAI, 53.9k★, Rust core + Python SDK): 100+ LLM routing, retry/fallback, cost tracking, per-project virtual-key budgets, rate limiting, caching, guardrails. Can be used as pure in-process Python SDK (not just proxy). Direct competitor on cost control + routing; budget/virtual-key tracking has known bugs (issue #15223, `model_max_budget` silently broken for routed models — fixed Apr 2026).
- **Safety/validation guardrails** (different axis from Backstop): `guardrails-ai/guardrails` (6.7k★, policy/validation), `NVIDIA/NeMo-Guardrails` (6k★, dialog flows), `laiyer-ai/LLM-Guard` (2.8k★, PII/content filtering).

---

## 2. Source URLs

- https://tenacity.readthedocs.io/en/latest/ — tenacity official docs: retry/backoff API, async, statistics.
- https://github.com/jd/tenacity — tenacity mainline repo (Apache-2.0, current 8.2.x).
- https://github.com/pexip/os-python-pyrate-limiter — pyrate-limiter (leaky-bucket, multi-rate, Redis/SQLite, async).
- https://oneuptime.com/blog/post/2026-01-22-token-bucket-rate-limiting-python/view — 2026 token-bucket tutorial: in-memory + Redis Lua, variable per-op token cost.
- https://stackoverflow.com/questions/48483348/how-to-limit-concurrency-with-python-asyncio — confirms `aiometer.amap(max_at_once, max_per_second)` concurrency+rate primitive.
- https://github.com/zilliztech/GPTCache — GPTCache semantic cache repo (8.1k★, pre-1.0, MIT, embedding+vector similarity).
- https://dev.co/ai/frameworks/gptcache — GPTCache adoption/maturity assessment; warns API instability.
- https://python.useinstructor.com/blog/2023/11/26/python-caching-llm-optimization/ — Instructor native caching + validated functools/diskcache/Redis benchmarks (50–80% cost savings).
- https://galileo.ai/blog/tiktoken-guide-production-ai — tiktoken production token-budgeting patterns (sliding window, per-agent budgets).
- https://developers.openai.com/cookbook/examples/how_to_count_tokens_with_tiktoken — OpenAI official token-counting + `num_tokens_from_messages`.
- https://medium.com/@sahin.samia/prompt-compression-in-large-language-models-llms-making-every-token-count-078a2d1c7e03 — 2025 prompt-compression survey (LLMLingua, 500xCompressor, PCToolkit).
- https://www.youtube.com/watch?v=xLNL6hSCPhc — LLMLingua demo: 10k→275 tokens, ~38x, same answer.
- https://github.com/microsoft/LLMLingua — Microsoft LLMLingua/LongLLMLingua repo.
- https://github.com/BerriAI/litellm — litellm repo (53.9k★, in-process SDK + proxy, cost/budget/routing).
- https://docs.litellm.ai/ — litellm docs: budgets, virtual keys, rate limiting, caching.
- https://github.com/BerriAI/litellm/issues/15223 — litellm `model_max_budget` bug (budget tracking broken for routed models).
- https://github.com/ant-research/awesome-mllm-guardrails — survey of guardrail frameworks (guardrails-ai, NeMo, LLM-Guard) — safety axis, not cost.

---

## 3. Source-quality notes & uncertainty

- **High confidence / primary:** tenacity docs, pyrate-limiter repo, GPTCache repo, tiktoken/OpenAI cookbook, litellm repo+docs, Instructor blog (includes runnable benchmarks). Authoritative.
- **Medium confidence:** OneUptime 2026 blog (solid tutorial, vendor-written), Galileo tiktoken guide (vendor/observability POV but technically sound), Medium prompt-compression survey (secondary, 2025).
- **Lower confidence / caveat:** GPTCache's "10x cost / 100x latency" and LLMLingua's "$28.5/1k, 20x faster" are vendor/marketing or single-demo claims, not independently benchmarked at scale — treat as upper-bound illustrations. GPTCache is pre-1.0 and explicitly API-unstable. `aiometer` evidence is only a StackOverflow usage snippet (small/niche library). litellm budget features have documented correctness bugs.
- **Uncertainty / gap:** "Speculative/estimated token budgeting" is not a single library — it's tiktoken pre-counting + DIY budget allocation; no mature off-the-shelf "token budget" Python lib found. "semi_cache / quick-cache" specific libs returned no primary sources (likely niche/low-adoption) — not worth Backstop adopting directly.

---

## 4. Actionable "10x better" recommendations for Backstop

1. **Pluggable in-process rate limiter (token-bucket, variable cost).** Adopt `pyrate-limiter` (or a thin token-bucket) as a swappable backend; support per-request token *cost* (expensive ops cost more) so Backstop enforces both request and token throughput without a proxy. Closes the gap vs litellm's rate limiting and OneUptime's variable-cost pattern.

2. **Semantic cache layer (optional, pluggable).** Add an opt-in semantic cache (GPTCache-style: local embedding + vector store, or lighter exact+near-duplicate key) behind `wrap()`. Target 50–80% cost at typical hit rates for repeated/RAG traffic; keep disabled by default to avoid staleness/embedding-cost surprises. Biggest cost lever Backstop is missing today.

3. **Pre-request token estimation + hard budget enforcement.** Integrate `tiktoken` (and Anthropic token est.) to compute `num_tokens_from_messages` *before* the call; reject/truncate or route when over a configured budget. Implement sliding-window/component allocation (system/history/buffer) so Backstop's "token budgets" become real and provider-accurate, not post-hoc.

4. **Prompt-compression "budget saver" hook.** Add an opt-in LLMLingua/LongLLMLingua compression stage for long-context/RAG requests when a token budget is tight, with a quality floor and skip-for-latency toggle. Reuses Backstop's budget signal to decide when compression is worth the local-model latency.

5. **Adopt `tenacity`-class retry as the engine, not a reimplementation.** Replace/back Backstop's retry with a tenacity-style policy (exponential backoff + jitter, `retry_if_exception_type` for 429/5xx, `max_delay`, async) plus metrics hooks; expose retry budget as part of the token/priority budget so retries don't blow cost limits.

6. **Unified budget + priority + fallback orchestration (differentiator vs litellm).** Litellm shows budget/routing is hard to get right (model_max_budget bug). Backstop should make **token budget the first-class unit** that drives priority queueing, circuit-breaking, fallback to cheaper model, and metrics — an in-process "cost control plane" proxies can't express per-call. The 10x positioning: proxy-free, single `wrap()`, budget-aware every request.
