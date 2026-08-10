#!/usr/bin/env python3
"""Proof 2: Multi-agent budget isolation.

Demonstrates that each Backstop.wrap() session enforces an independent
budget — exhausting one agent's cap does not block another. Run with real keys:

    export OPENAI_API_KEY=sk-...
    python proofs/proof_multi_agent_isolation.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backstop import Backstop, BackstopConfig


async def run_agent(agent_id: str, budget: int, calls: int, provider: str) -> dict:
    config = BackstopConfig(default_max_output_tokens=64)

    if provider == "openai":
        from openai import AsyncOpenAI
        client = Backstop.wrap(
            AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"]),
            budget=budget,
            config=config,
        )
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    else:
        from anthropic import AsyncAnthropic
        client = Backstop.wrap(
            AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"]),
            budget=budget,
            config=config,
        )
        model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-20250514")

    allowed = blocked = 0
    for i in range(calls):
        try:
            if provider == "openai":
                await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": f"Agent {agent_id}, call {i}: hello"}],
                )
            else:
                await client.messages.create(
                    model=model,
                    max_tokens=64,
                    messages=[{"role": "user", "content": f"Agent {agent_id}, call {i}: hello"}],
                )
            allowed += 1
        except Exception:
            blocked += 1

    state = getattr(client, "_backstop_state")
    await client.close()
    return {
        "agent_id": agent_id,
        "allowed": allowed,
        "blocked": blocked,
        "spent": state.budget.spent,
        "remaining": state.budget.remaining,
    }


async def main():
    parser = argparse.ArgumentParser(description="Multi-agent isolation proof")
    parser.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    args = parser.parse_args()

    print(f"# Multi-Agent Budget Isolation Proof ({args.provider})")
    print()

    results = await asyncio.gather(
        run_agent("A (tight budget)", budget=300, calls=10, provider=args.provider),
        run_agent("B (generous budget)", budget=5000, calls=10, provider=args.provider),
    )

    for r in results:
        print(f"- **{r['agent_id']}**: {r['allowed']} allowed, {r['blocked']} blocked, "
              f"{r['spent']} tokens spent, {r['remaining']} remaining")

    print()
    tight = results[0]
    generous = results[1]
    if tight["blocked"] > 0 and generous["blocked"] == 0:
        print("**Result:** Agent A's budget was exhausted and blocked, while Agent B")
        print("continued independently. Per-agent isolation confirmed.")
    else:
        print(f"**Result:** A blocked={tight['blocked']}, B blocked={generous['blocked']}")
        print("(Adjust budgets to see isolation: give A a tight cap, B a generous one.)")


if __name__ == "__main__":
    asyncio.run(main())
