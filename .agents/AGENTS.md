### Documentation Discipline
- **Source of Truth**: Always rely on the explicit statements in source documents (like `README.md` or `plan.md`) over summarized memory notes. If a document explicitly states something (e.g., "Not an MCP tool"), do not allow summaries to drift and claim the opposite. Apply strict discipline to internal documentation consistency.

### Backstop Architecture Constraints
- **What Backstop Is**: A transport-layer budget, concurrency, and circuit-breaker wrapper around a single client. It is protocol-agnostic and works with any SDK client using `httpx`/`requests`.
- **What Backstop Is NOT**: It is **not** an MCP tool. It does **not** consume application-layer signals (like a "disagreement signal").
- **Integration Model**: Backstop sits underneath applications (like the wedge tool) as infrastructure. In multi-agent scenarios, isolation applies to the conversation/context layer, while each agent instance is simply wrapped in its own transport-layer Backstop session.
