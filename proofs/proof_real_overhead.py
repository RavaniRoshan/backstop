#!/usr/bin/env python3
"""Proof 3: Real-provider overhead measurement.

Measures the latency added by Backstop wrapping vs direct SDK calls
against a real provider. Run:

    export OPENAI_API_KEY=sk-...
    python proofs/proof_real_overhead.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


async def main():
    parser = argparse.ArgumentParser(description="Real-provider overhead measurement")
    parser.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    parser.add_argument("--calls", type=int, default=5)
    args = parser.parse_args()

    print(f"# Real-Provider Overhead Proof ({args.provider})")
    print(f"- Measuring {args.calls} direct vs wrapped calls")
    print()

    if args.provider == "openai":
        from openai import AsyncOpenAI
        from backstop import Backstop, BackstopConfig

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("error: set OPENAI_API_KEY"); sys.exit(1)
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

        direct = AsyncOpenAI(api_key=api_key)
        wrapped = Backstop.wrap(
            AsyncOpenAI(api_key=api_key),
            budget=1_000_000,
            config=BackstopConfig(default_max_output_tokens=16),
        )

        async def direct_call(i):
            t0 = time.perf_counter()
            await direct.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": f"Say 'ok' ({i})"}],
                max_tokens=16,
            )
            return (time.perf_counter() - t0) * 1000

        async def wrapped_call(i):
            t0 = time.perf_counter()
            await wrapped.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": f"Say 'ok' ({i})"}],
                max_tokens=16,
            )
            return (time.perf_counter() - t0) * 1000

    else:
        from anthropic import AsyncAnthropic
        from backstop import Backstop, BackstopConfig

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("error: set ANTHROPIC_API_KEY"); sys.exit(1)
        model = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-20250514")

        direct = AsyncAnthropic(api_key=api_key)
        wrapped = Backstop.wrap(
            AsyncAnthropic(api_key=api_key),
            budget=1_000_000,
            config=BackstopConfig(default_max_output_tokens=16),
        )

        async def direct_call(i):
            t0 = time.perf_counter()
            await direct.messages.create(
                model=model,
                max_tokens=16,
                messages=[{"role": "user", "content": f"Say 'ok' ({i})"}],
            )
            return (time.perf_counter() - t0) * 1000

        async def wrapped_call(i):
            t0 = time.perf_counter()
            await wrapped.messages.create(
                model=model,
                max_tokens=16,
                messages=[{"role": "user", "content": f"Say 'ok' ({i})"}],
            )
            return (time.perf_counter() - t0) * 1000

    print("Direct calls:")
    direct_lats = []
    for i in range(args.calls):
        lat = await direct_call(i)
        direct_lats.append(lat)
        print(f"  call {i + 1}: {lat:.1f} ms")

    print("\nWrapped calls:")
    wrapped_lats = []
    for i in range(args.calls):
        lat = await wrapped_call(i)
        wrapped_lats.append(lat)
        print(f"  call {i + 1}: {lat:.1f} ms")

    d_med = statistics.median(direct_lats)
    w_med = statistics.median(wrapped_lats)
    overhead = w_med - d_med
    pct = (overhead / d_med * 100) if d_med > 0 else 0

    print()
    print(f"- Direct p50: {d_med:.1f} ms")
    print(f"- Wrapped p50: {w_med:.1f} ms")
    print(f"- Overhead: {overhead:.1f} ms ({pct:.1f}%)")
    print()
    print(f"**Result:** Backstop added {overhead:.1f} ms of in-process overhead")
    print(f"per call. A proxy gateway would add a full network round-trip (10-100ms+).")

    await direct.close()
    await wrapped.close()


if __name__ == "__main__":
    asyncio.run(main())
