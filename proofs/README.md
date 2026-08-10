# Proofs

Runnable evidence that Backstop's claims hold. Each script demonstrates a
specific claim with real providers (or offline mocks where noted).

## Budget exhaustion prevention

```bash
export OPENAI_API_KEY=sk-...
python proofs/proof_budget_exhaustion.py
```

Shows Backstop blocking requests once the budget is exhausted, preventing
overspend. Without the cap, all calls proceed.

## Multi-agent isolation

```bash
export OPENAI_API_KEY=sk-...
python proofs/proof_multi_agent_isolation.py
```

Runs two agents concurrently with different budgets. Exhausting Agent A's cap
does not block Agent B.

## Real-provider overhead

```bash
export OPENAI_API_KEY=sk-...
python proofs/proof_real_overhead.py
```

Measures direct vs wrapped latency against a real provider. Backstop adds
sub-ms overhead; a proxy adds a full network round-trip.

## Semantic cache savings

```bash
python proofs/proof_semantic_cache.py           # offline mock (no key needed)
python proofs/proof_semantic_cache.py --live    # real provider
```

Demonstrates near-duplicate prompt detection and cache hits.
