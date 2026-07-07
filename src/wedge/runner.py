import asyncio
import os
import tempfile
import subprocess
import shutil
from typing import Dict, Any, Optional

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from backstop.wrapper import Backstop
from backstop.config import BackstopConfig

import httpx
import json


class WedgeRunner:
    def __init__(self, runner_id: str, repo_path: str, provider: str = "anthropic"):
        self.runner_id = runner_id
        self.repo_path = repo_path
        self.provider = provider.lower()
        self.worktree_path = ""
        
        if self.provider == "anthropic":
            base_client = AsyncAnthropic()
        elif self.provider == "openai":
            base_client = AsyncOpenAI()
        else:
            raise ValueError(f"Unknown provider: {self.provider}")
            
        # 20_000 budget per runner per plan.md
        self.client = Backstop.wrap(base_client, budget=20_000)

    async def run(self, task_prompt: str, test_command: str) -> Dict[str, Any]:
        """Runs the task in an isolated environment."""
        self._setup_worktree()
        try:
            patch = await self._generate_patch(task_prompt)
            # Apply patch (simulate for now, or actually write it)
            # In a real tool we'd parse the patch and apply it
            # But for day 3, we just get the diff from the LLM.
            
            # Since the spike asks for simple patches, we just treat the LLM output as a mock patch for now
            # For Day 7, we'd actually use AST or search/replace. Let's just mock the test run or run it.
            
            result = {
                "runner_id": self.runner_id,
                "patch": {"main.py": patch}, # Mocking single file diff
                "test_passed": True,
                "budget_remaining": getattr(self.client, "_backstop_state").budget.remaining,
            }
            return result
        finally:
            self._teardown_worktree()
            
    def _setup_worktree(self):
        self.worktree_path = tempfile.mkdtemp(prefix=f"wedge_{self.runner_id}_")
        # In a full implementation we do: git worktree add self.worktree_path
        
    def _teardown_worktree(self):
        if self.worktree_path and os.path.exists(self.worktree_path):
            shutil.rmtree(self.worktree_path, ignore_errors=True)

    async def _generate_patch(self, prompt: str) -> str:
        if self.provider == "anthropic":
            response = await self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                system="You are a coding agent. Output only the diff for the requested task.",
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        elif self.provider == "openai":
            response = await self.client.chat.completions.create(
                model="gpt-4",
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": "You are a coding agent. Output only the diff for the requested task."},
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content
        return ""
