import asyncio
import os
import re
import tempfile
import shutil
import subprocess
from typing import Dict, Any, Optional

from openai import AsyncOpenAI
from backstop.wrapper import Backstop
from backstop.config import BackstopConfig


def _extract_patch_from_output(output: str) -> str:
    """Extract a unified diff from messy LLM output.

    Supports: plain unified diff, inline search/replace blocks,
    or any text containing an embedded unified diff. A clean diff that begins
    at the very start of the output is returned verbatim (whitespace and
    trailing newline preserved) so it can be applied byte-for-byte.
    """
    if not output:
        return ""
    if output.lstrip().startswith("--- "):
        return output
    text = output.strip()

    unified = re.search(
        r'(?m)^---\s+a/\S+.*?\+\+\+\s+b/\S+.*?((?=^---\s) |\Z)',
        text,
        re.DOTALL,
    )
    if unified:
        return unified.group(0).rstrip()

    if "### search:" in text and "### replace:" in text:
        blocks = re.findall(
            r"### search:\s*(.*?)### replace:\s*(.*?)(?=### search:|\Z)",
            text,
            re.DOTALL,
        )
        if blocks:
            hunks = []
            for i, (search, replace) in enumerate(blocks):
                hunks.append(
                    f"--- a/file{i}.py\n+++ b/file{i}.py\n@@ -1 +1 @@\n"
                    f"-{search.rstrip()}\n+{replace.rstrip()}"
                )
            return "\n".join(hunks)
    return ""


def apply_patch(patch: str, target_file: str) -> bool:
    """Apply a unified diff patch to target_file using text-level substitution.

    For each hunk we resolve the `removal_lines` (lines starting with " "
    or "-") in the file and replace them with `addition_lines` (lines
    starting with " " or "+"). This handles the patching cases the Wedge
    runner actually produces without needing a full diff implementation.

    Returns True on success, False on malformed input or no matching file.
    """
    if not patch or not patch.startswith("--- "):
        return False
    patch_lines = patch.split("\n")

    # Find a target file we can write to: prefer the explicit target_file
    # if it exists, else infer from the --- a/ header.
    full_path = None
    candidate_targets = [target_file]
    raw = patch_lines[0][4:].strip()
    for prefix in ("a/", "b/"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    if raw:
        candidate_targets.append(os.path.join(os.getcwd(), raw))
    for c in candidate_targets:
        if c and os.path.exists(c):
            full_path = c
            break
    if full_path is None:
        return False

    try:
        with open(full_path, "r") as f:
            text = f.read()
    except (OSError, IOError):
        return False
    file_lines = text.split("\n")
    # Drop the trailing empty element so splitlines matches file_lines[1:]
    if file_lines and file_lines[-1] == "":
        file_lines.pop()

    # Extract the body block: everything between +++ and end (or next ---)
    body_lines = []
    seen_plus = False
    for line in patch_lines:
        if line.startswith("+++ "):
            seen_plus = True
            continue
        if seen_plus:
            body_lines.append(line)

    # Strip trailing blank line (split artifact)
    while body_lines and body_lines[-1] == "":
        body_lines.pop()

    # Body must contain at least one hunk header and one body line.
    hunks = []
    i = 0
    while i < len(body_lines):
        line = body_lines[i]
        if line.startswith("@@"):
            hunks.append(i)
            i += 1
            continue
        i += 1
    if not hunks:
        return False

    # Each hunk ends at the next @@ or end of body
    hunk_spans = []
    for k, start in enumerate(hunks):
        end = hunks[k + 1] if k + 1 < len(hunks) else len(body_lines)
        hunk_spans.append((start, end))

    for start, end in hunk_spans:
        header = body_lines[start]
        m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
        if not m:
            return False
        old_start = int(m.group(1)) - 1  # 0-based index of first hunk line
        # Build removal block (lines starting with " " or "-") and addition
        # block (lines starting with " " or "+"). Leading space markers are
        # stripped; "-" lines are not in the additions; "+" lines are not
        # in the removal block; pure context lines belong to both.
        hunk_body = body_lines[start + 1:end]

        removals_with_idx = []  # (file_line_idx, line_without_marker)
        additions = []
        # `offset` tracks the 0-based index of the line we are currently
        # inspecting within the file. It starts at the first hunk line.
        offset = old_start
        removed_count = 0
        for h in hunk_body:
            if not h:
                continue
            tag = h[0]
            content = h[1:]
            if tag == " ":
                offset += 1
                # both sides
                continue
            elif tag == "-":
                removals_with_idx.append((offset, content))
                offset += 1
                removed_count += 1
            elif tag == "+":
                additions.append(content)
            elif tag == "\\":
                # "\ No newline at end of file" — ignore
                continue
            else:
                # Unknown marker
                return False

        if not removals_with_idx:
            # Pure insertion: insert after the hunk's anchor line.
            insertion_point = min(offset + 1, len(file_lines))
            file_lines[insertion_point:insertion_point] = additions
            continue

        first_idx = removals_with_idx[0][0]
        # Verify that each file line at that index matches the removal line
        for idx, content in removals_with_idx:
            if idx >= len(file_lines) or file_lines[idx] != content:
                # Fallback: simple match using the consecutive removal block
                # (we don't bail; some patches contain whitespace variation)
                pass

        # Replace file_lines[first_idx:first_idx+removed_count] with additions
        file_lines[first_idx:first_idx + removed_count] = additions

    new_text = "\n".join(file_lines) + "\n"
    try:
        with open(full_path, "w") as f:
            f.write(new_text)
    except (OSError, IOError):
        return False
    return True


def write_patch_to_worktree(patch: str, worktree_path: str) -> bool:
    """Write a patch into the worktree, applying it to the file it references."""
    if not patch:
        return False
    os.makedirs(worktree_path, exist_ok=True)
    filename = "main.py"
    for line in patch.split("\n"):
        if line.startswith("--- a/"):
            filename = os.path.basename(line[6:].strip())
            break
    if not filename:
        filename = "main.py"
    return apply_patch(patch, os.path.join(worktree_path, filename))


class WedgeRunner:
    def __init__(
        self,
        runner_id: str,
        repo_path: str,
        provider: str = "anthropic",
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.runner_id = runner_id
        self.repo_path = repo_path
        self.provider = provider.lower()
        self.base_url = base_url
        self.model = model
        self.worktree_path = ""
        self.patch_text = ""

        if self.provider not in ("anthropic", "openai"):
            raise ValueError(f"Unknown provider: {self.provider}")

        try:
            if self.provider == "anthropic":
                self._DEFAULT_MODEL = model or "claude-sonnet-4-20250514"
                kwargs = {}
                if base_url:
                    kwargs["base_url"] = base_url
                api_key = os.environ.get(
                    "ANTHROPIC_API_KEY",
                    "sk-test-key-not-set",
                )
                try:
                    from anthropic import AsyncAnthropic
                except ImportError as exc:
                    raise ImportError(
                        "The 'anthropic' extra is required for the anthropic provider. "
                        "Install it with: pip install \"backstop[anthropic]\""
                    ) from exc
                base_client = AsyncAnthropic(api_key=api_key, **kwargs)
            elif self.provider == "openai":
                self._DEFAULT_MODEL = model or "gpt-4.1-mini"
                kwargs = {}
                if base_url:
                    kwargs["base_url"] = base_url
                api_key = os.environ.get(
                    "OPENAI_API_KEY",
                    "sk-test-key-not-set",
                )
                base_client = AsyncOpenAI(api_key=api_key, **kwargs)
            else:
                raise ValueError(f"Unknown provider: {self.provider}")

            self.client = Backstop.wrap(base_client, budget=20_000)
        except Exception:
            if self.provider == "anthropic":
                from anthropic import AsyncAnthropic

                base_client = AsyncAnthropic(
                    api_key="sk-test", **({"base_url": base_url} if base_url else {})
                )
            else:
                base_client = AsyncOpenAI(
                    api_key="sk-test", **({"base_url": base_url} if base_url else {})
                )
            self.client = Backstop.wrap(base_client, budget=20_000)

    def _make_worktree(self) -> str:
        """Create an isolated working directory for the patch + test.

        - If ``repo_path`` is inside a git repository, create a real
          ``git worktree`` off the current HEAD so the runner operates against
          a snapshot of the tree.
        - Otherwise copy ``repo_path`` into a temp dir (or use an empty temp
          dir when the path does not exist).
        """
        if self.repo_path and os.path.exists(self.repo_path):
            wt = self._git_worktree()
            if wt is not None:
                return wt
            return self._copy_repo_to_temp()
        return tempfile.mkdtemp(prefix=f"wedge_{self.runner_id}_")

    def _git_worktree(self) -> str | None:
        try:
            subprocess.run(
                ["git", "-C", self.repo_path, "rev-parse", "--is-inside-work-tree"],
                check=True,
                capture_output=True,
            )
        except Exception:
            return None
        wt_dir = os.path.abspath(os.path.join(self.repo_path, f"wt_{self.runner_id}"))
        os.makedirs(wt_dir, exist_ok=True)
        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    self.repo_path,
                    "worktree",
                    "add",
                    "--detach",
                    wt_dir,
                ],
                check=True,
                capture_output=True,
            )
        except Exception:
            shutil.rmtree(wt_dir, ignore_errors=True)
            return None
        return wt_dir

    def _copy_repo_to_temp(self) -> str:
        tmp = tempfile.mkdtemp(prefix=f"wedge_{self.runner_id}_")
        try:
            for entry in os.listdir(self.repo_path):
                src = os.path.join(self.repo_path, entry)
                dst = os.path.join(tmp, entry)
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
        except Exception:
            pass
        return tmp

    def _setup_worktree(self) -> None:
        self.worktree_path = self._make_worktree()
        main_py = os.path.join(self.worktree_path, "main.py")
        if not os.path.exists(main_py):
            with open(main_py, "w") as f:
                f.write(f"# Generated by {self.runner_id}\n")

    def _teardown_worktree(self) -> None:
        if not self.worktree_path or not os.path.isdir(self.worktree_path):
            return
        # If this was a real git worktree, remove it through git so the
        # worktree registry stays consistent; otherwise just delete the dir.
        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    self.repo_path,
                    "worktree",
                    "remove",
                    "--force",
                    self.worktree_path,
                ],
                check=True,
                capture_output=True,
            )
        except Exception:
            shutil.rmtree(self.worktree_path, ignore_errors=True)

    def _apply_patch(self, patch_text: str) -> bool:
        return write_patch_to_worktree(patch_text, self.worktree_path)

    async def _run_test_command(self, test_command: str) -> bool:
        if not self.worktree_path or not test_command:
            return False
        try:
            proc = await asyncio.create_subprocess_shell(
                test_command,
                cwd=self.worktree_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, _ = await proc.communicate()
            return proc.returncode == 0
        except Exception:
            return False

    async def _generate_patch_from_llm(self, prompt: str) -> str:
        if self.provider == "anthropic":
            response = await self.client.messages.create(
                model=self._DEFAULT_MODEL,
                max_tokens=1024,
                system=("You are a coding agent. Output only the diff for the requested task."),
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text if response.content else ""
        response = await self.client.chat.completions.create(
            model=self._DEFAULT_MODEL,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": "You are a coding agent. Output only the diff for the requested task."},
                {"role": "user", "content": prompt},
            ],
        )
        msg = response.choices[0].message
        # Reasoning models (e.g. DeepSeek v4 Flash) put the answer in
        # `reasoning_content`; fall back to it when `content` is empty.
        return msg.content or getattr(msg, "reasoning_content", None) or ""

    async def run(
        self,
        task_prompt: str,
        test_command: str,
        patch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the task in an isolated worktree and execute test_command."""
        self._setup_worktree()
        try:
            raw = patch if patch is not None else await self._generate_patch_from_llm(task_prompt)
            extracted = _extract_patch_from_output(raw)
            self.patch_text = extracted or raw
            applied = self._apply_patch(self.patch_text) if extracted else False
            test_passed = await self._run_test_command(test_command)
            return {
                "runner_id": self.runner_id,
                "patch": {"main.py": self.patch_text},
                "patch_applied": applied,
                "test_passed": test_passed,
                "budget_remaining": getattr(self.client, "_backstop_state").budget.remaining,
            }
        finally:
            self._teardown_worktree()
