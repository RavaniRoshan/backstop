"""
Per-tenant budget enforcement with FastAPI.

Requires:
  pip install "backstop-ai[fastapi]"
  OPENAI_API_KEY must be set.
"""
from __future__ import annotations

import os
import sys

# Guard: fastapi is an optional dependency
try:
    from fastapi import FastAPI, Header, HTTPException
except ImportError:
    print("Install fastapi to run this example: pip install 'backstop-ai[fastapi]'")
    sys.exit(0)

from openai import OpenAI

from backstop import Backstop, TenantBudget, budgets, with_budget
from backstop.exceptions import BudgetExceededError

if not os.environ.get("OPENAI_API_KEY"):
    print("Set OPENAI_API_KEY to run this example.")
    sys.exit(0)

app = FastAPI()

client = Backstop.wrap(OpenAI(), budget=None)

budgets.register(
    {
        "free": TenantBudget("free", limit_tokens=10_000),
        "pro": TenantBudget("pro", limit_tokens=250_000),
    }
)


@app.post("/summarize")
def summarize(text: str, x_plan: str = Header(default="free")) -> dict[str, str]:
    if x_plan not in {"free", "pro"}:
        raise HTTPException(status_code=400, detail="unknown plan")

    try:
        with with_budget(x_plan):
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": f"Summarize this:\n{text}"}],
                extra_headers={"X-Backstop-Priority": "critical"},
            )
    except BudgetExceededError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    return {"summary": response.choices[0].message.content or ""}
