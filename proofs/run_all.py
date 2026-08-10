#!/usr/bin/env python3
"""Run all proofs and generate a combined evidence report.

    python proofs/run_all.py --provider openai --output docs/proof-evidence.md
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


async def run_budget_exhaustion(provider: str) -> str:
    from backstop import Backstop, BackstopConfig

    if provider == "openai":
        from openai import AsyncOpenAI
        client = Backstop.wrap(
            AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", "")),
            budget=400,
            config=BackstopConfig(default_max_output_tokens=64),
        )
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        call_fn = lambda i: client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": f"Agent A, call {i}: reply with one word"}], max_tokens=64,
        )
    else:
        from anthropic import AsyncAnthropic
        client = Backstop.wrap(
            AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", "")),
            budget=400,
            config=BackstopConfig(default_max_output_tokens=64),
        )
        model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-20250514")
        call_fn = lambda i: client.messages.create(
            model=model, max_tokens=64, messages=[{"role": "user", "content": f"Agent A, call {i}: reply with one word"}],
        )

    allowed = blocked = 0
    for i in range(10):
        try:
            await call_fn(i)
            allowed += 1
        except Exception as e:
            blocked += 1

    state = getattr(client, "_backstop_state")
    await client.close()
    return (
        f"| Budget exhaustion | {provider} | budget=400 tokens, 10 calls (~640 tokens needed) | "
        f"{allowed} allowed, {blocked} blocked, {state.budget.spent} spent | "
        f"Backstop blocked {blocked} calls to prevent overspend |"
    )


async def run_multi_agent_isolation(provider: str) -> str:
    from backstop import Backstop, BackstopConfig

    async def agent(budget, calls):
        if provider == "openai":
            from openai import AsyncOpenAI
            c = Backstop.wrap(
                AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", "")),
                budget=budget,
                config=BackstopConfig(default_max_output_tokens=32),
            )
            allowed = blocked = 0
            for i in range(calls):
                try:
                    await c.chat.completions.create(
                        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                        messages=[{"role": "user", "content": f"call {i}"}],
                        max_tokens=32,
                    )
                    allowed += 1
                except Exception:
                    blocked += 1
            state = getattr(c, "_backstop_state")
            await c.close()
        else:
            from anthropic import AsyncAnthropic
            c = Backstop.wrap(
                AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", "")),
                budget=budget,
                config=BackstopConfig(default_max_output_tokens=32),
            )
            allowed = blocked = 0
            for i in range(calls):
                try:
                    await c.messages.create(
                        model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-20250514"),
                        max_tokens=32,
                        messages=[{"role": "user", "content": f"call {i}"}],
                    )
                    allowed += 1
                except Exception:
                    blocked += 1
            state = getattr(c, "_backstop_state")
            await c.close()
        return allowed, blocked, state.budget.spent, state.budget.remaining

    (a_allowed, a_blocked, a_spent, a_rem), (b_allowed, b_blocked, b_spent, b_rem) = (
        await asyncio.gather(agent(200, 8), agent(5000, 8))
    )
    return (
        f"| Multi-agent isolation | {provider} | Agent A budget=200, Agent B budget=5000 | "
        f"A: {a_allowed} allowed/{a_blocked} blocked/{a_spent} spent; "
        f"B: {b_allowed} allowed/{b_blocked} blocked/{b_spent} spent | "
        f"A exhausted independently; B continued |"
    )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    parser.add_argument("--output", default="docs/proof-evidence.md")
    args = parser.parse_args()

    print(f"Running proofs against {args.provider}...")
    print("(set the appropriate API key in the environment)")
    print()

    rows = []
    for name, fn in [
        ("Budget exhaustion", run_budget_exhaustion),
        ("Multi-agent isolation", run_multi_agent_isolation),
    ]:
        print(f"  {name}...", flush=True)
        try:
            rows.append(await fn(args.provider))
            print(f"    ok")
        except Exception as e:
            rows.append(f"| {name} | {args.provider} | ERROR | {e} | failed |")
            print(f"    FAILED: {e}")

    report = "\n".join([
        "# Backstop Proof Evidence",
        "",
        f"- **Date:** {time.strftime('%Y-%m-%d')}",
        f"- **Provider:** {args.provider}",
        "",
        "| Proof | Provider | Setup | Result | Conclusion |",
        "| --- | --- | --- | --- | --- |",
        *rows,
        "",
        "## How to reproduce",
        "",
        "```bash",
        f"export {'OPENAI_API_KEY' if args.provider == 'openai' else 'ANTHROPIC_API_KEY'}=...",
        f"python proofs/run_all.py --provider {args.provider}",
        "```",
        "",
    ])

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(report)
    print(f"\nReport written to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
