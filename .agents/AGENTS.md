### Documentation Discipline
- **Source of Truth**: Always rely on the explicit statements in source documents (like `README.md` or `plan.md`) over summarized memory notes. If a document explicitly states something (e.g., "Not an MCP tool"), do not allow summaries to drift and claim the opposite. Apply strict discipline to internal documentation consistency.

### Backstop Architecture Constraints
- **What Backstop Is**: A transport-layer budget, concurrency, and circuit-breaker wrapper around a single client. It is protocol-agnostic and works with any SDK client using `httpx`/`requests`.
- **What Backstop Is NOT**: It is **not** an MCP tool. It does **not** consume application-layer signals (like a "disagreement signal").
- **Integration Model**: Backstop sits underneath applications (like the wedge tool) as infrastructure. In multi-agent scenarios, isolation applies to the conversation/context layer, while each agent instance is simply wrapped in its own transport-layer Backstop session.

### Secrets & Credentials — ABSOLUTE RULES (NEVER, NEVER, NEVER)
- **NEVER commit, hardcode, or paste any secret into the repository.** This includes: API keys, tokens, passwords, private keys, OAuth client secrets, webhook signatures, `.env` files, and any `Authorization: Bearer …` / `x-api-key: …` values.
- **NEVER commit environment variables or `.env` files** (or anything containing them, e.g. `.env.example` with a real value). Use `.env.example` with empty placeholders only.
- **Always reference secrets via environment variables or placeholders** (e.g. `${FIRECRAWL_API_KEY}`, `<your-key-here>`), never the literal value.
- **Before every commit, grep the staged diff for secrets.** If a real secret is present, do NOT commit — strip it, use a placeholder, and rotate the leaked credential immediately.
- Treat any detected exposure (e.g. GitGuardian) as urgent: rotate the credential first, then remove it from the working tree AND git history (git filter-repo / BFG), then force-push.
