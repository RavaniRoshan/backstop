# Backstop Unicorn COSS Assumptions

## Locked Defaults

- First customer wedge: AI SaaS teams.
- License strategy: MIT OSS core.
- Business model: open-core hybrid SaaS and self-hosted enterprise control plane.
- Data-plane default: local in-process SDK.
- Commercial mode: opt-in policy sync and telemetry.
- First SDK: Python.
- Second SDK: TypeScript.
- First distributed backend: Redis.
- First observability standard: OpenTelemetry.

## Product Assumptions

- Customers care more about preventing surprise LLM spend than generic LLM observability.
- Local-first request enforcement is a meaningful differentiator against proxy gateways.
- Enterprises will accept optional shared state when they need distributed budget enforcement.
- Prompt payload privacy is central to differentiation and must remain protected by default.
- Control-plane outages must not break application traffic.

## Technical Assumptions

- Python SDK compatibility remains maintainable across current OpenAI and Anthropic clients.
- Redis is sufficient for the first distributed budget and policy-backed pilot use cases.
- Policy sync can be implemented safely with signed bundles and local fallback.
- OpenTelemetry is the right integration layer before building many vendor-specific exporters.
- Benchmarks must distinguish Backstop overhead from provider latency.

## Commercial Assumptions

- PyPI extras are adoption packaging, not a serious monetization model.
- Paid value comes from centralized policy, auditability, reporting, compliance, support, and distributed enforcement.
- Early pilots should be high-touch and engineering-led.
- Public case studies and benchmark proof matter more than broad feature count.
- Multi-language expansion should follow customer pull, not investor optics.

## Constraints

- Do not build a proxy-first product unless customer evidence invalidates the local-first wedge.
- Do not send prompt payloads to the control plane by default.
- Do not require the hosted control plane for the OSS SDK to be useful.
- Do not add broad enterprise features before distributed state and policy sync are proven.
- Do not make SDK behavior differ silently across languages.

## Open Questions

- Exact paid packaging: per-seat, usage-based, or hybrid.
- Whether Redis should be bundled as OSS or partially reserved for enterprise.
- Whether self-hosted control plane should be available before or after hosted SaaS.
- Which framework integrations create the fastest adoption: FastAPI, LangChain, LlamaIndex, Celery, or Django.
- Whether TypeScript should wrap SDK transports directly or use a lighter middleware pattern.
