#!/usr/bin/env python3
"""Proof 1: Budget exhaustion prevention.

Demonstrates that Backstop blocks requests before they exceed the budget,
saving real API spend. Run with a real provider key:

    export OPENAI_API_KEY=sk-...
    python proofs/proof_budget_exhaustion.py

    # or
    export ANTHROPIC_API_KEY=sk-ant-...
    python proofs/proof_budget_exhaustion.py --provider anthropic
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backstop import Backstop, BackstopConfig


def parse_args():
    p = argparse.ArgumentParser(description="Budget exhaustion prevention proof")
    p.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    p.add_argument("--budget", type=int, default=500, help="tight token budget")
    p.add_argument("--requests", type=int, default=20, help="how many calls to attempt")
    return p.parse_args()


async def main():
    args = parse_args()
    config = BackstopConfig(default_max_output_tokens=128)

    if args.provider == "openai":
        from openai import AsyncOpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("error: set OPENAI_API_KEY"); sys.exit(1)
        client = Backstop.wrap(
            AsyncOpenAI(api_key=api_key),
            budget=args.budget,
            config=config,
        )
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    else:
        from anthropic import AsyncAnthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("error: set ANTHROPIC_API_KEY"); sys.exit(1)
        client = Backstop.wrap(
            AsyncAnthropic(api_key=api_key),
            budget=args.budget,
            config=config,
        )
        model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-20250514")

    print(f"# Budget Exhaustion Proof ({args.provider})")
    print(f"- Budget: {args.budget} tokens")
    print(f"- Attempting: {args.requests} calls (~{args.requests * 128} tokens needed)")
    print()

    allowed = blocked = 0
    tokens_spent = 0

    for i in range(args.requests):
        try:
            if args.provider == "openai":
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": f"In one sentence, what is request {i} about?"}],
                )
            else:
                resp = await client.messages.create(
                    model=model,
                    max_tokens=128,
                    messages=[{"role": "user", "content": f"In one sentence, what is request {i} about?"}],
                )
            allowed += 1
        except Exception as e:
            blocked += 1
            if blocked == 1:
                print(f"**First block at call {i + 1}:** {e}")

    state = getattr(client, "_backstop_state")
    tokens_spent = state.budget.spent if state.budget.spent else 0
    remaining = state.budget.remaining

    print()
    print(f"- Calls allowed: {allowed}")
    print(f"- Calls blocked: {blocked}")
    print(f"- Tokens spent: {tokens_spent}")
    print(f"- Remaining budget: {remaining}")
    print()
    if blocked > 0:
        saved = (args.requests - allowed) * 128
        print(f"**Result:** Backstop blocked {blocked} calls, preventing ~{saved} tokens")
        print(f"of additional spend. Without the budget cap, all {args.requests} calls")
        print(f"would have proceeded.")
    else:
        print(f"**Result:** All calls were within budget (try lowering --budget).")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
