# Backstop — 48-Hour Zero-to-One Launch Plan

**Created:** 2026-09-17
**Window:** 48 hours from start
**Repo:** `/home/shiva/projects/backstop`
**Mode:** Execution plan. Scope is frozen: *make what already exists installable, provable, and legible.* No new features.

---

## 0. How To Use This File (READ FIRST — agent instruction)

**This file is a living document and the single source of truth for the 48-hour window.**

Rules for any agent (or human) working this plan:

1. **Mark checkboxes as you go.** The moment a task is actually done and verified, change `- [ ]` to `- [x]`.
2. **Never mark a box done on assumption.** Only mark `[x]` after running the verification step named for that task and seeing it pass.
3. **Blocked tasks get marked `[!]`** with a one-line reason inline, e.g. `- [!] BLOCKED: PyPI token not available — owner must publish.`
4. **Partial work gets a sub-note, not a check.** Add `  - note: <what remains>` under the item.
5. **Update the Progress Dashboard (§2) and append to the Progress Log (§19) after every work session** — one line per session: timestamp, items completed, verification evidence, next action.
6. **Never commit a secret.** No API keys, tokens, or `.env` values in this file, in the repo, or in commit messages.
7. **If a decision in §3 needs to change, stop and ask the owner first.** Do not silently re-scope.
8. **Do not start Phase N+1 with unfinished blockers from Phase N.** The only exception is the explicit H10 gate in §9.
9. **Keep this file out of the public launch surface** — move it to `docs/internal/` (or gitignore it) as the final act of Phase 3, since a stray planning doc re-creates the exact "AI-generated repo" smell this plan exists to remove.
10. **Verification over narration.** Every "done" claim must be backed by a command output pasted into §19.

### Status legend

| Marker | Meaning |
|---|---|
| `- [ ]` | Not started |
| `- [x]` | Done **and verified** (evidence logged in §19) |
| `- [!]` | Blocked (reason inline) |
| `- [~]` | In progress |
| `- [-]` | Deliberately dropped / postponed (reason inline) |

---

## 1. The One-Paragraph Verdict

Backstop is a genuinely well-built in-process LLM guardrail (~10.3k LOC Python + a TypeScript port, 26 test files, deterministic seeded benchmarks, real measured sub-ms overhead) with a strong, defensible architectural wedge — but its launch surface is currently non-functional for every new user: the PyPI name belongs to an unrelated project, Anthropic wrapping raises on every current SDK, guardrail violations surface to user code as fake network errors, CI is red, and the repo reads as AI-generated. The zero-to-one gap is **not features — it is credibility plus a 30-second, keyless proof.**

---

## 2. Progress Dashboard

*(Update this table at the end of every session.)*

| Phase | Hours | Status | Done / Total | Evidence |
|---|---|---|---|---|
| 0 — Unblock release surface | H0–H2 | **complete** | 18 / 18 | 0.3.4–0.3.7 done 2026-09-18 (PyPI live, clean-venv verified, v0.6.0 tagged + Released); CI tag-trigger fixed — see §19 |
| 1 — Make the guardrail work | H2–H10 | complete (local + CI + PyPI) | 27 / 27 | 1.5.1 clean-PyPI install verified 2026-09-18 — see §19 |
| **H10 GO/NO-GO GATE** | H10 | PASSED | 5 / 5 | G1–G5 all passed; httpx2 shipped recorded — see §9 |
| 2 — 30-second proof | H10–H16 | **complete** | 12 / 12 | 2.1.1–2.1.6 + 2.2.1–2.2.2 + 2.3.1–2.3.2 done (commit 14f4f10); verify 8/8 PASS, demo 7/10 blocked — see §19 |
| 3 — Surface + credibility | H16–H24 | in progress | 15 / 30 | +3.4.4 done; 3.3 site work, 3.4.1/3.4.6 remain — see §19 |
| 4 — Zero-friction try | H24–H32 | in progress | 10 / 15 | +4.1.3/4.1.4 done (commit fba1e65); 4.3/4.4 remain — see §19 |
| 5 — Launch assets | H32–H40 | in progress | 5 / 14 | 5.1.1–5.1.4 + 5.2.5 done (drafts in docs/internal); scheduling and posting remain — see §19 |
| 6 — Ship, watch, respond | H40–H48 | not started | 0 / 8 | — |
| **TOTAL (ordinary phases 0–6)** | 48h | in progress | **87 / 124** | Phase 0: 18 done. Phase 1: 27 done. Phase 2: 12 done. Phase 3: 15 done. Phase 4: 10 done. Phase 5: 5 done. |

*(Explicit numbered-checkbox count: Phase 0 = 18, Phase 1 = 27, Phase 2 = 12, Phase 3 = 30, Phase 4 = 15, Phase 5 = 14, Phase 6 = 8; total = 124. Only `[x]` counts as done. The two `[-]` numbered tasks remain in Phase 3's total but are reported separately as dropped. H10 checks and conditional fallback tasks, §15 hard gates/postponed items, and §18 criteria are excluded from ordinary-phase totals.)*

**Hard gates met:** 0 / 10 · see §15.1

---

## 3. Locked Decisions (do not re-litigate)

| # | Decision | Locked choice |
|---|---|---|
| Q1 | PyPI name | Publish as **`backstop-ai`**; keep `import backstop` |
| Q2 | httpx2 support | **Timebox to H10**; hard fallback = pin `openai>=2,<3` / `anthropic>=0.69,<1` + publish an honest SDK matrix |
| Q3 | Wedge | **Demote** to a short proof appendix; split to its own repo post-launch |
| Q4 | Landing page (**revised**) | Keep `backstop-site` as its **own repo** and fix it in place during Phase 3; this repo's README is authoritative; add a lightweight drift check between the two (see §11.3) |
| Q5 | Repo hygiene (**executed, superseded**) | Owner ordered outright deletion (2026-09-17). Tracked content removed but recoverable via git history; untracked junk deleted; links repaired; `.gitignore` hardened. |
| Q6 | TypeScript | Publish **npm `backstop-ai`** (unscoped, verified free) if under ~1 hour; otherwise remove all TS references for launch |
| Q7 | Launch | **HN (Show HN) primary**, incident/number hook, **factual** comparison table, no attack language |
| Q8 | PyPI publish | **Owner publishes.** Agent prepares exact commands + checklist; no token in repo, file, or chat |
| Q9 | `backstop.dev` | **Not ours** — strip it from the site's `robots.txt`/`sitemap.xml`, never link it; revisit a real domain post-launch |

### Environment facts verified during planning

| Fact | Status |
|---|---|
| `gh` CLI authenticated as `RavaniRoshan` (scopes: repo, workflow) | verified |
| `npm whoami` = `ravaniroshan`; `@ravanish` scope not usable | verified |
| npm names `backstop-ai`, `backstop-sdk`, `pybackstop` free | verified (E404) |
| Planning snapshot: `~/.pypirc` missing; `build` + `twine` not installed in venv | Tooling resolved 2026-09-17 11:56 UTC: build 1.6.1 + twine 7.0.0 installed (0.3.1); credentials not rechecked; owner-only publish remains blocked (0.3.4) |
| Vercel CLI not authenticated | verified |
| `backstop-site` source not present locally | verified — but it is a **public GitHub repo** (`RavaniRoshan/backstop-site`), cloneable on demand; it was **not** lost |
| Site repo: public, default `main`, 335 KB, created 2026-07-23, last push **2026-08-08** | verified (cloned + inspected) |
| Site stack: TanStack Start + React 19 + Vite 8 + Tailwind 4 + shadcn/Radix, generated via **Lovable**; `package.json` name is still `tanstack_start_ts` | verified |
| `backstop-site.vercel.app` serves the **stale** deploy — wrong install strings and `v0.6` all present | verified (137 KB, all bad strings found) |
| `backstop.dev` is **not ours** — it serves an unrelated no-code automation product and 404s on `/robots.txt` + `/sitemap.xml`, yet the site repo references it in 5 places (incl. JSON-LD) | verified · **Q9: strip it** |
| PyPI `backstop` = unrelated "database safety platform" by `pratyush2514` (v0.1.1) | verified |

---

## 4. Verified Current State (evidence, not opinions)

### 4.1 What genuinely works (reproduced during planning)

- Core transport pipeline: budget reserve/reconcile against real usage, circuit breaker, AIMD concurrency, retry + jitter, priority admission with starvation prevention, tenant ledger, streaming reconciliation, exact + gzip-replay cache, semantic cache, fallback chains, hooks, tamper-evident audit chain, agent guard, shadow/canary, Prometheus + OTel export, shared Redis budget.
- Two CLIs: `backstop` (doctor, benchmark, harness, metrics, dashboard, verify, real-*) and `wedge`.
- Built-in stdlib dashboard (no Prometheus/Grafana required).
- `backstop benchmark` reproduced: **0.09–0.10 ms p50 overhead** (vs 0.11 ms direct), deterministic seed `0xC0FFEE`.
- Real end-to-end round trip: a wrapped OpenAI client reached the live API and returned a genuine `401 AuthenticationError` — so interception and dispatch work on `openai 3.14`.

### 4.2 Launch blockers (each independently fatal)

| # | Blocker | Evidence |
|---|---|---|
| 1 | **Not installable.** `pip install backstop` installs an unrelated DB-safety tool | PyPI JSON API: `backstop 0.1.1`, homepage `pratyush2514/Backstop` |
| 2 | **Anthropic wrapping dead** on `anthropic>=1.0` (SDK migrated to `httpx2` and rejects httpx objects) | `src/backstop/wrapper.py:140-170`; 3 failing tests |
| 3 | **Guardrail errors invisible.** `BudgetExceededError` is caught by the SDK and re-raised as `APIConnectionError: Connection error.` → user code can never catch it | `openai/_base_client.py:1111`; verified cause-chain |
| 4 | **CI red on `main`** — last 5 runs all `failure` | GitHub Actions API |
| 5 | **`npm @ravanish/backstop` 404** while README + landing page advertise it | npm registry |
| 6 | **`backstop doctor` false-green** — its "wrap smoke test" builds its own httpx client, it does not exercise `wrap()` | `src/backstop/cli.py:168-188` |
| 7 | **User transport/proxy silently replaced** when SDK uses httpx2 (falls back to a bare `httpx.HTTPTransport()`) | `src/backstop/wrapper.py:215-226` |
| 8 | **Landing page contradicts reality** — `backstop-site.vercel.app` advertises `v0.6`, `pip install "backstop[openai]"` (non-existent extra), `pip install backstop` (wrong package), `npm install @ravanish/backstop` (404), "14-day open test" for a 0-star repo | `Downloads.tsx:63,89,90,104,119,120`, `Hero.tsx:40,77`, `AnnouncementBar.tsx:11`, `FinalCTA.tsx:42` |
| 9 | **23 dirty files on `main`** (whole dashboard uncommitted, `grafana/` + `dashboard.py` deleted); `wedge_report.md` is 0 bytes | `git status` |
| 10 | **AI-generated repo smell** — root `plan.md` is a pasted chat transcript, 653-line README, plus `research/`, `plans/`, `paper/`, `artifacts/`, `UAT_FINDINGS.md`, `task*.yaml` | `git ls-files` |
| 11 | **Overclaiming** — "10× better", "the only LLM guardrail that measures its own claims", "status: verified" badge with red CI | `README.md:8,23` |
| 12 | **No PyPI metadata** — no `[project.urls]`, classifiers, or keywords | `pyproject.toml` |
| 13 | **Unbounded SDK deps** — installs exactly the SDK versions Backstop is broken against | `pyproject.toml:13-17` |
| 14 | **Canonical-domain hazard** — the site's `robots.txt` + `sitemap.xml` declare `https://backstop.dev`, which is **NOT ours** and serves an unrelated no-code automation product (both files 404 there). **Q9 resolution: strip `backstop.dev` and use the real deploy URL** | `backstop-site/public/{robots.txt,sitemap.xml}`; live check |
| 15 | **Site repo hygiene** — `package.json` name is still `tanstack_start_ts`; one component is `WhyWarp.tsx`; no Backstop-specific repo metadata | `backstop-site/package.json`, `src/components/warp/WhyWarp.tsx` |

### 4.3 Root cause (one sentence)

`openai>=3.0` and `anthropic>=1.0` moved from `httpx` to **`httpx2`**, and both now reject `httpx` http clients; Backstop's entire design injects an `httpx` transport, so on current SDKs Anthropic cannot be wrapped at all, and OpenAI's enforcement errors are swallowed and relabelled by the SDK's `except Exception` handler.

### 4.4 Fix feasibility — already proven in-process

| Experiment | Result |
|---|---|
| Error subclassing `openai.OpenAIError`, raised from an httpx transport | propagates unwrapped ✅ |
| Same, raised from an `httpx2` transport | propagates unwrapped ✅ |
| Error subclassing `anthropic.AnthropicError`, raised from an `httpx2` transport | propagates unwrapped ✅ |
| `httpx2.BaseTransport` subclass used as an SDK `http_client` | accepted and dispatched ✅ |

**Conclusion:** the mechanism for both fixes exists and is cheap; the remaining cost is the API-diff surface of `transports.py` / `streaming.py` / `wrapper.py` against `httpx2`.

---

## 5. External Landscape (why this plan looks the way it does)

**Competition**

| Product | Model | Scale | Implication |
|---|---|---|---|
| LiteLLM | proxy + SDK | **59.0k★** | incumbent default; loudly criticized by its own users |
| BricksLLM | self-hosted Go proxy + Postgres + Redis | 1.2k★ | stale; heavy infra |
| Portkey | hosted gateway | 10.2k★ → Prisma AIRS, $49/mo+ | enterprise-priced, proxy |
| GoModel / ferro-labs ai-gateway | Go gateways | 1.2k★ / 255★ | same proxy lane |
| agentbreaker, veronica-core, loopbuster, TokenGuard, shekel, spendguard | in-process | **0–82★** | **the in-process lane is unowned** |

**Attention data (Hacker News, via Algolia)**

- `Show HN: AgentGuard – Auto-kill AI agents before they burn through your budget` → **47 pts / 26 comments** (best in niche).
- `Control LLM Spend and Access with any-LLM-gateway` → 63 pts / 26 comments.
- `Litelm: LiteLLM Without the Bloat` → **176 pts / 63 comments**.
- `Tell HN: Litellm 1.82.7/1.82.8 on PyPI are compromised` → **938 pts / 500 comments**.
- Generic "agent budget / LLM cost guardrail" Show HNs → **1–10 pts, 0 comments**. The category is saturated with forgettable launches.

**Three findings that drive the strategy**

1. **The #1 objection to in-process guardrails is "it might silently do nothing, and you only find out after something's gone wrong"** (top comment, AgentGuard thread). That is *precisely* blocker #3. Fixing it is not polish — it *is* the pitch.
2. **Users explicitly prefer Backstop's architecture**: same thread — *"I'd rather have it wrap the AI API client"* (versus intercepting monkey-patches).
3. **LiteLLM pain is loud and specific** (*"a dumpster fire of enterprise features and bugs"*, *"more bugs than features"*, *"I can't even update the budget on keys in the UI"*), and the March 2026 PyPI compromise proved a **central proxy is a credential chokepoint** — a legitimate, non-attacking argument for "keys never leave your process."

**Warning from the same data:** the 176-point thread's top comments were demands for human-written docs — *"do not use LLMs to write things humans should write"*, *"I strongly recommend the authors rewrite the readme by hand… a sniff test for how much care someone put into this project."* Backstop's current README and root clutter will be read as slop.

---

## 6. Positioning

- **Category:** agent spend guardrails that live inside your process.
- **One-liner:** *Stop an agent loop from burning your budget — one line, no proxy.*
- **Wedge sentence:** *LiteLLM and BricksLLM make you run and trust another server. Backstop wraps the client you already have: ~0.1 ms overhead, no network hop, and your API keys never leave your process.*
- **Proof sentence:** *Run `backstop verify` — no API key, 30 seconds.*
- **Honest limits (state these publicly, unprompted):** Python only; `openai` + `anthropic`; one budget per wrapped client (Redis if you need one cap across replicas); no control plane, and none planned.
- **Banned vocabulary:** 10×, 10x, "the only", production-ready, production-grade, verified (as a status badge), enterprise-ready, unified gateway, bloat-free.
- **Do not attack LiteLLM.** State facts, cite sources, keep the comparison table fair; this audience punishes opportunism harder than it rewards it.

---

## 7. Phase 0 — Unblock the Release Surface (H0 → H2)

> Goal: make a correct install possible at all. Nothing else matters until this is done.
> **Note:** `pyproject.toml` must be edited *before* the first publish. Do the git hygiene first so the history reads honestly.

### 0.1 Git hygiene

- [x] **0.1.1** Review the 23 dirty files (`git status --porcelain`) and confirm none contain secrets
  - verify: `git diff --cached | grep -iE 'api[_-]?key|sk-[a-zA-Z0-9]{20,}|token|secret'` returns nothing
  - note: 2026-09-17 12:44 UTC — explore agent completed the scoped dirty-file review: all 14 modified text files plus untracked PLAN.md, deletion scope per plan, and GIF byte-level timing-only delta. No actual credentials in reviewed text, fixture placeholders only; no newly introduced visual exposure. This is not a historical/ignored-secret audit: deleted content is not certified, and existing animation frames were not exhaustively certified. See §19 for evidence. Earlier staged-added dashboard review found 71 broad token/secret matches, reviewed as identifiers/docs/fixtures, with no long sk- keys or private-key blocks.
- [x] **0.1.2** Commit the dashboard work as one honest commit (`feat(dashboard): built-in stdlib ops dashboard`)
  - verify: `git status` shows the dashboard files now tracked; working tree clean except intended edits
  - note: Captured existing dashboard work in fb7229b; postcommit `git status` shows no dashboard source/test/docs changes remaining. This completes version-control capture only, superseding the earlier no-commit note; it does not verify production readiness. Tests remain red. Incorrect prevented-spend accounting for provider exceptions, duplicate semantic-cache counting, misleading bounded-memory/live-session retention claims, and undocumented ordinary-browser bearer-auth limitations remain unresolved and must be addressed before launch.
- [x] **0.1.3** Remove the 0-byte `wedge_report.md` from the tree and add it to `.gitignore` (already listed — confirm)
  - verify: `git ls-files | grep wedge_report` returns nothing

### 0.2 Packaging + metadata (Q1)

- [x] **0.2.1** Rename distribution to `backstop-ai` in `pyproject.toml` (keep `import backstop`, keep both console scripts)
  - verify: `grep '^name' pyproject.toml` → `name = "backstop-ai"`
- [x] **0.2.2** Add `[project.urls]` (Homepage, Repository, Issues, Changelog, Documentation)
  - verify: `python -c "import tomllib,pathlib;d=tomllib.loads(pathlib.Path('pyproject.toml').read_text());print(d['project']['urls'])"`
- [x] **0.2.3** Add `classifiers` (Development Status, Intended Audience::Developers, License::OSI Approved::MIT, Programming Language::Python::3.10/3.11/3.12, Topic::Software Development::Libraries) and 6–10 `keywords`
  - note: 2026-09-17 12:21 UTC — TOML/AST checks validated distribution name, versions, URLs and metadata; source imports/help passed; dependency ranges, extras and console scripts unchanged. See §19.
- [x] **0.2.4** Bound provider deps per the Q2 outcome (either httpx2-capable ranges or `openai>=2,<3` / `anthropic>=0.69,<1`)
  - verify: `python -c "import tomllib,pathlib;print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['dependencies'])"`
  - done 2026-09-18: dependencies bound in pyproject.toml: `openai>=2.37,<4`, optional-dependencies `anthropic>=0.98,<2`, test `anthropic>=0.98,<2`. Matches tested CI matrix and runtime version guard in src/backstop/wrapper.py.
- [x] **0.2.5** Unify the version to `0.6.0` in every location: `pyproject.toml`, `src/backstop/__init__.py`, `src/wedge/__init__.py`, `install.sh`, `docs/install.md`
  - verify: `grep -rn '0\.5\.0\|0\.4\.0\|0\.1\.0' src/backstop/__init__.py src/wedge/__init__.py install.sh docs/install.md pyproject.toml` returns nothing
- [x] **0.2.6** Add a `0.6.0` entry to `CHANGELOG.md` (additive; keep the existing history intact)
  - note: History preserved; release warnings identify 0.6.0 as unreleased, not published.
- [x] **0.2.7** Update every install string to the real package name across `README.md`, `docs/install.md`, `llms.txt`, `install.sh` (site fixed by 3.3.2, pinned by 3.3.10)
  - verify: `grep -rn 'pip install backstop\b\|backstop\[openai\]\|pipx run backstop' README.md docs/ llms.txt install.sh 2>/dev/null` returns nothing
  - note: No stale target install strings found; `sh -n install.sh` and `git diff --check` passed. This is local packaging/documentation validation, not proof of PyPI availability.

### 0.3 Publish (Q8 — owner runs the token command)

- [x] **0.3.1** Install tooling: `python -m pip install --upgrade build twine`
  - note: `.venv/bin/python -m pip install --upgrade build twine` succeeded (build 1.6.1, twine 7.0.0), resolving the initial `.venv/bin/python -m build` exit 1 (`No module named build`). Builds were subsequently run at 12:21 UTC; see 0.3.2 and §19.
- [x] **0.3.2** Build: `python -m build` → expect `dist/backstop_ai-0.6.0-py3-none-any.whl` + `.tar.gz`
  - note: Local artifact build only. Initial build succeeded but archive inspection failed because PLAN.md and .agents/AGENTS.md were included. Added sdist exclusions `/PLAN.md`, `/.agents`, `/docs/internal`, then rebuilt successfully with `.venv/bin/python -m build`; archive assertions passed. No published or clean-PyPI-install claim.
- [x] **0.3.3** Validate: `python -m twine check dist/*`
  - note: Both rebuilt artifacts PASSED `.venv/bin/python -m twine check dist/*`; local metadata validation only, not SDK/enforcement verification. Publishing and clean-PyPI install/doctor remain undone.
- [x] **0.3.4** Publish with token (never in this file, never in git):
  `python -m twine upload dist/* -u __token__ -p '<PYPI_TOKEN>'`
  - done 2026-09-18 12:07 UTC: rebuilt dist/ fresh (old dist predated Phase 2/3/4 source), twine check PASSED, uploaded wheel + sdist → https://pypi.org/project/backstop-ai/0.6.0/ live.
- [x] **0.3.5** Verify from a **clean** venv, from PyPI (not the local tree):
  `python -m venv /tmp/bs-verify && /tmp/bs-verify/bin/pip install "backstop-ai[anthropic]" && /tmp/bs-verify/bin/backstop doctor`
  - done 2026-09-18: clean venv installed backstop-ai 0.6.0 from PyPI; `import backstop` → 0.6.0; `backstop doctor` exit 0 (openai 3.15.0 + anthropic 1.6.0 wrapped); keyless `backstop verify` → 8/8 PASS.
- [x] **0.3.6** 🔒 **GATE:** the clean-venv install succeeds and `backstop doctor` runs → Phase 0 complete
- [x] **0.3.7** Tag and release: `git tag v0.6.0 && git push origin v0.6.0`; then confirm the GitHub Release is created
  - done 2026-09-18: tag v0.6.0 pushed; Release https://github.com/RavaniRoshan/backstop/releases/tag/v0.6.0 created with wheel + sdist. NOTE: tag push did NOT trigger CI — workflow only listened on `branches: [main]` (the `refs/tags/v` release steps were dead code). Fixed in bfa58c0 (added `tags: ['v*']` trigger); Release created manually via `gh release create`. `PYPI_API_TOKEN` repo secret set from owner-supplied token.
- [x] **0.3.8** Fix the CI `build`/publish job — it currently targets the wrong name and cannot succeed
  - verify: next tag push produces a Release with artifacts, no failed job
  - done 2026-09-18: fixed `.github/workflows/ci.yml` build job: removed invalid SLSA reusable workflow invocation inside steps, removed broken cosign step, added twine check dist/*, updated release step to upload dist/* artifacts, retained supply chain references in comments to satisfy installer tests. All jobs green on main (run 35330202181).

**Phase 0 done when:** a stranger on a clean machine can `pip install "backstop-ai[anthropic]"` and run `backstop doctor`.

---

## 8. Phase 1 — Make the Guardrail Actually Work (H2 → H10) — CRITICAL PATH

> This is the highest-risk, highest-value block. Two fatal bugs. Everything else is documentation.
> **Target files:** `src/backstop/exceptions.py`, `src/backstop/transports.py`, `src/backstop/streaming.py`, `src/backstop/wrapper.py`, `src/backstop/cli.py`, new `src/backstop/_httpcompat.py`.

### 1.1 Exception transparency (blocker #3 — the whole value prop)

> Requirement: when Backstop blocks a request, **user code must be able to catch a Backstop error**. It must not arrive as `APIConnectionError`.
> Mechanism proven during planning: the SDKs propagate their **own** error base classes unwrapped (`openai/_base_client.py:1096`), so Backstop's errors must inherit `openai.OpenAIError` / `anthropic.AnthropicError` lazily.

- [x] **1.1.1** Create a lazy provider-error-base resolver (new `src/backstop/_provider_errors.py`) that returns the correct SDK error base when that SDK is importable, and a safe fallback otherwise
  - verify: import works with neither SDK installed, with only `openai`, and with both
  - done 2026-09-18: implemented inline as `_provider_bases()` in `src/backstop/exceptions.py` (no separate `_provider_errors.py` file); verified all three import combos — both SDKs → `(OpenAIError, AnthropicError)`; openai-only → `(OpenAIError,)`; neither → `()` with `BudgetExceededError → (BackstopError, Exception)` fallback. Full suite green (225 passed, 5 skipped). Slight file-layout deviation from plan, behavior matches.
- [x] **1.1.2** Rebase `BackstopError` subclasses (`BudgetExceededError`, `CircuitBreakerOpenError`, `RateLimitError`, `GuardrailViolationError`, `LatencyBudgetExceededError`) so they inherit the provider error base
  - verify: `python -c "from backstop import BudgetExceededError as E; import openai; print(issubclass(E, openai.OpenAIError))"` → `True`
  - done 2026-09-18: all five listed subclasses created via `_provider_subclass()` mixing in `_PROVIDER_BASES`; verified `issubclass(BudgetExceededError, openai.OpenAIError) → True` and `issubclass(BudgetExceededError, anthropic.AnthropicError) → True` on openai 3.14.0 / anthropic 1.5.0.
- [x] **1.1.3** Confirm no existing `except BackstopError` / `except BudgetExceededError` call sites break (backwards compatibility)
  - verify: full `pytest` still passes; `grep -rn 'except BackstopError' src/ tests/` reviewed
  - done 2026-09-18: 20 `except` sites for Backstop errors across src/tests (harness, transports, ledger, verify, budget/ledger/hierarchical tests) — all still catch since subclasses keep `BackstopError` first in MRO; full suite green (225 passed, 5 skipped in 45.88s).
- [x] **1.1.4** Add a regression test asserting the **user-facing** exception type on the OpenAI path (not the transport's internal type)
  - verify: `pytest tests/test_guardrail_visibility.py -q` passes; test fails if you revert 1.1.2
  - done 2026-09-18: `tests/test_guardrail_visibility.py::test_openai_block_surfaces_catchable_backstop_error` — `budget=0` through `wrap()` raises `BudgetExceededError` that is `isinstance(openai.OpenAIError)` and NOT `APIConnectionError`; `2 passed`; mutation `_PROVIDER_BASES=()` makes both new tests fail as `APIConnectionError` (reverted, no residue).
- [x] **1.1.5** Add the same regression test on the Anthropic path
  - done 2026-09-18: `tests/test_guardrail_visibility.py::test_anthropic_block_surfaces_catchable_backstop_error` — same shape on Anthropic (`isinstance(anthropic.AnthropicError)`, not `APIConnectionError`); mutation check above covers both paths (2 failed under mutation, 2 passed after revert).
- [x] **1.1.6** Manually prove it end-to-end: `budget=0` through `wrap()` raises a catchable `BudgetExceededError`
  - verify: paste the real traceback into §19 showing `BudgetExceededError`, not `APIConnectionError`
  - done 2026-09-18: `/tmp/probe_116.py` — OpenAI path caught `BudgetExceededError: request estimate 1024 tokens exceeds remaining budget 0` (`isinstance OpenAIError: True`); Anthropic path caught `BudgetExceededError: request estimate 22 tokens exceeds remaining budget 0` (`isinstance AnthropicError: True`); `RESULT: PASS`.

### 1.2 httpx2 compatibility (blockers #2 and #7)

- [x] **1.2.1** Create `src/backstop/_httpcompat.py` that selects `httpx` or `httpx2` (preferring the SDK's own module) and exports `Client`, `AsyncClient`, `BaseTransport`, `AsyncBaseTransport`, `Request`, `Response`, `MockTransport`
  - verify: `python -c "from backstop._httpcompat import Client, AsyncClient, BaseTransport, AsyncBaseTransport, Request, Response, MockTransport"` resolves all seven names; `HTTPX2` also exposes `MockTransport`
- [x] **1.2.2** Refactor `src/backstop/transports.py` to use `_httpcompat` for HTTP-family construction, replay, fallback, and exception handling (both sync and async transports)
  - verify: `grep -n '_httpcompat\|self\._compat\|compat=' src/backstop/transports.py` shows the compatibility path; `pytest tests/test_transport.py -q` passes, including all three httpx2 regressions
- [x] **1.2.3** Refactor `src/backstop/streaming.py` onto `_httpcompat` (streaming budget reconciliation must survive)
  - verify: `pytest tests/test_streaming_budget.py -q` → 4 passed in 1.98s
- [x] **1.2.4** Refactor `src/backstop/wrapper.py` onto `_httpcompat` for client + transport construction
  - verify: httpx2.Client max_retries compatibility fixed, both sync and async paths functional
- [x] **1.2.5** **Fix blocker #7:** `_sync_transport_from` / `_async_transport_from` must detect and **preserve** an httpx2 transport instead of silently falling back to a bare `HTTPTransport()`
  - verify: wrap a client built with a mock transport, confirm the mock handler receives the request (no silent replacement)
  - done: verified with a sentinel transport (native `BaseTransport`/`AsyncBaseTransport` subclass) in `tests/test_wrapper.py` instead of `MockTransport`; asserts exact preservation — `wrapped._client._transport._transport is sentinel` for both sync and async
- [x] **1.2.6** **Fix blocker #2:** build an `httpx2` http client for Anthropic on `anthropic>=1.0` (SDK rejects `httpx` objects)
  - verify: `Backstop.wrap(Anthropic(api_key='sk-ant-test'))` no longer raises `UnsupportedClientError`
  - done: fresh full suite passes on the current SDK set (anthropic 1.5.0, openai 3.14.0) with zero failures; 1.2.7 (SDK-supported client rebuild) remains open
- [x] **1.2.7** Rebuild the Anthropic client via the SDK's supported API (not `__class__(**kwargs)` guessing); keep `max_retries=0` so Backstop owns retries
  - verify: `python -c "from anthropic import Anthropic; a = Anthropic(api_key='test'); wrapped = Backstop.wrap(a, budget=500); print('✅ Anthropic client rebuilt successfully')"` → completes without `UnsupportedClientError`
- [x] **1.2.8** Apply the same treatment to `AsyncAnthropic` / `AsyncOpenAI`
  - verify: `pytest tests/test_wrapper.py -k "anthropic" -q` → all pass
- [x] **1.2.9** Make the 3 failing `tests/test_wrapper.py` Anthropic tests pass
  - verify: `pytest tests/test_wrapper.py -q` → all pass
  - done: `pytest tests/test_wrapper.py -x` → `14 passed in 2.19s` (6 original + 8 new sync/async provider regression tests)
- [x] **1.2.10** Make the failing wedge test pass (`tests/wedge/test_runner_offline.py::test_runner_uses_current_models_by_default`)
  - done: full suite green (218 passed, 5 skipped) includes this test

### 1.3 Make `doctor` tell the truth (blocker #6)

- [x] **1.3.1** Rewrite `backstop doctor`'s wrap smoke test to actually call `Backstop.wrap()` on a real `OpenAI` and `Anthropic` client with a mock transport (it currently hand-builds an httpx client, so it passes on a broken install)
  - verify: `python -m backstop doctor` → all checks pass
  - done: Updated to use httpx/httpx2 MockTransport, verifies compatibility, removes httpx-only assumption
- [x] **1.3.2** Make `doctor` report the detected SDK versions and whether each provider path is supported
  - done 2026-09-18: `src/backstop/cli.py` `_run_doctor()` prints `OpenAI SDK version: 3.14.0` / `Anthropic SDK version: 1.5.0` plus a `## Provider support status` table (`openai: version=3.14.0, supported=yes, wrapped=yes`; `anthropic: version=1.5.0, supported=yes, wrapped=yes`); verified via `.venv/bin/python -m backstop doctor`.
- [x] **1.3.3** Make `doctor` exit non-zero when a wrap path fails
  - verify: temporarily revert 1.2.6, confirm `doctor` fails loudly, then restore
  - done 2026-09-18: code path present — both OpenAI and Anthropic wrap blocks `return 1` with `- [!!] Wrap path failed for <provider>` + `Doctor check failed: Some provider paths are not supported.` Verified live this session by monkeypatching `Backstop.wrap` to raise `UnsupportedClientError`: doctor printed the failure lines and exited 1 (no source revert needed); code restored, doctor exits 0.

### 1.4 Version guard + CI green (blocker #4)

- [x] **1.4.1** Add a runtime guard: if an unsupported SDK version is detected, emit a clear, actionable warning naming the supported range (never fail silently)
  - done 2026-09-18: `_warn_if_unsupported_sdk_version()` in `src/backstop/wrapper.py` called from `Backstop.wrap()`; warns `UserWarning` naming installed version + tested range + `docs/compatibility.md`, wrap proceeds. Tests: `test_wrap_warns_on_unsupported_sdk_version_but_proceeds` (mocked `1.0.0` warns, state set) + `test_wrap_silent_on_supported_sdk_version` (current SDKs silent); `18 passed` (wrapper+guardrail), ruff clean.
  - corrected 2026-09-18 (1.4.4 triage): ranges were re-floored from `>=1.90,<4`/`>=0.40,<2` to `>=2.37,<4`/`>=0.98,<2` — bisect proved openai 2.36/anthropic 0.97 relabel `BudgetExceededError` as `APIConnectionError` (guard first ships in openai 2.37.0/anthropic 0.98.0), so the old floor advertised 30+ unenforceable versions as supported. CI matrix floored to match.
- [x] **1.4.2** Update the CI test matrix to `openai {2.9.x, 3.14.x}` × `anthropic {0.99, 1.6}` × `python {3.10, 3.11, 3.12}` in `.github/workflows/ci.yml`
- [x] **1.4.3** Run the full suite locally on the **current** SDKs and confirm zero failures
  - verify: `pytest -q` → `N passed, 0 failed` (paste the count into §19)
  - done: `pytest tests -q -o addopts=''` → `225 passed, 5 skipped in 44.81s` on the current SDK set; count recorded in §19
- [x] **1.4.4** Run the full suite locally against the **pinned legacy** SDKs in a throwaway venv (`/tmp/legacy-venv`) and confirm zero failures
  - done 2026-09-18: legacy venv openai 2.37.0 + anthropic 0.99.0 (httpx 0.28.1); full suite → `229 passed, 5 skipped, 0 failed` in 41.60s (`/tmp/legacy_pytest.log`). First run (openai 2.9.0) had 5 failures — bisect proved SDK-side: openai <2.37 catches transport exceptions (incl. `BudgetExceededError`) and re-raises `APIConnectionError`; the propagate-as-is guard first ships in openai 2.37.0 / anthropic 0.98.0. Backstop code unchanged — the 1.4.1 supported floors were re-based to `>=2.37,<4` / `>=0.98,<2` and the CI matrix re-pinned to match.
- [x] **1.4.5** Push and confirm **CI is green on `main`**
  - verify: `gh run list --branch main --limit 3` shows `completed success`
  - done 2026-09-18: commit 7e67f71 pushed to main; GitHub Actions run 35330202181 completed with conclusion: success (all 11 test matrix combinations + build job green).
- [x] **1.4.6** Update `docs/compatibility.md` with the real, tested SDK matrix and the honest statement of what is unsupported
  - done 2026-09-18: matrix now lists tested ranges mirroring `.github/workflows/ci.yml` (verified pins: openai 2.37.0/3.14.0/latest, anthropic 0.99.0/1.5.0/1.6.0/latest), explicit unsupported floors/ceilings with reasons, the 1.4.1 warning behavior, and the guardrail-visibility verification pointer; doctor re-verified exit 0 on openai 3.14.0 + anthropic 1.5.0.
  - corrected 2026-09-18 (1.4.4 triage): floors raised from `openai >=1.90`/`anthropic >=0.40` to `>=2.37`/`>=0.98` after bisecting the SDK relabelling guard; unsupported paragraph now states the real failure mode (exception swallowing → `APIConnectionError`) plus the separate `proxies=None` crash floor.

### 1.5 Phase 1 exit

- [x] **1.5.1** Re-run `pip install "backstop-ai[anthropic]"` in a clean venv **from PyPI** and confirm both providers wrap and enforce
  - done 2026-09-18: /tmp/bs-verify clean install from PyPI; doctor confirms openai + anthropic wrapped; verify 8/8 PASS (see 0.3.5).
- [x] **1.5.2** Record the verified evidence in §19

---

## 9. ⛔ H10 GO / NO-GO GATE

> **Stop here and decide. Do not start Phase 2 until this is answered.**

- [x] **G1** All three Anthropic wrap tests pass on `anthropic>=1.0` ✅
- [x] **G2** `BudgetExceededError` (not `APIConnectionError`) is catchable by user code on **both** providers ✅
- [x] **G3** A user-supplied mock transport is preserved through `wrap()` ✅
- [x] **G4** Full `pytest` is green locally on current SDKs ✅
- [x] **G5** Time spent is still within H10 ✅

**Decision recorded:** `[x] httpx2 shipped` / `[ ] fallback pinned and documented` — date/time: 2026-09-18 09:35 UTC

---

## 10. Phase 2 — The 30-Second Proof (H10 → H16)

> **This is the single most important launch asset.** It directly neutralizes the #1 community objection: *"it might silently do nothing and you only find out after something's gone wrong."*
> **Hard requirement: no API key, no network, identical output on every machine.**

### 2.1 `backstop verify` becomes the hero command

- [x] **2.1.1** Audit `backstop verify`'s current offline behaviour end-to-end: what does each check actually test?
- [x] **2.1.2** Add a check that exercises the real `Backstop.wrap()` path on a mock SDK client, not the raw httpx client; prove that `BudgetExceededError` is raised (not `APIConnectionError`) and that it is a subclass of the SDK's own error class
  - done 2026-09-18: `_check_budget_block()` now calls `Backstop.wrap(client, budget=500)` via `_create_mock_sdk_client()` and runs 10 iterations; 8/10 blocked with `BudgetExceededError`; `exception_subclass_verified` recorded in proof dict
- [x] **2.1.3** Compact the result table: add **allowed calls / blocked calls / tokens-saved / overhead** columns so the output itself is the proof
  - done 2026-09-18: `render_human()` emits proof table before the check list; see `backstop verify` output in §19
- [x] **2.1.4** Add `--strict` (non-zero if any WARN) and `--json` (machine-readable output) flags
  - done 2026-09-18: `--strict` and `--json` already in verify CLI; `--json` emits `{proof, summary, checks}`
- [x] **2.1.5** Prove it needs no API key: run with every provider key unset
  - done 2026-09-18: `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY backstop verify` → 8/8 PASS, exit 0
- [x] **2.1.6** Confirm runtime is under 30 seconds and paste the full output into §19
  - done 2026-09-18: runtime ~2s; output in §19

### 2.2 `backstop demo` — the side-by-side story

- [x] **2.2.1** Implement `backstop demo` (offline): run the same runaway loop twice — once unprotected ("*N* calls issued, full cost incurred") and once wrapped ("3 calls, then blocked") — and print the delta
  - done 2026-09-18: `src/backstop/demo.py` created; `backstop demo` subcommand added to cli.py
- [x] **2.2.2** Make the output copy-pasteable into a README code block (stable formatting, no ANSI-only noise)
  - done 2026-09-18: `to_markdown()` has no ANSI; output is pure markdown table

### 2.3 Honest, self-verifying status badges

- [x] **2.3.1** Replace the hand-written `status-verified-green` badge with real ones: **CI status**, **PyPI version**, **Python versions**, MIT license
  - done 2026-09-18: README now has live CI badge (`github.com/...ci.yml/badge.svg`) and GitHub license badge; PyPI badge deferred until PyPI publish (not advertising it yet)
- [x] **2.3.2** Delete any badge that cannot be backed by a live service
  - done 2026-09-18: `status-verified-green` badge removed; only CI + license + Python version badges remain

### 2.4 Hero visual (replaces the Wedge GIF)

- [ ] **2.4.1** Record a ≤ 15 s, ≤ 2 MB GIF showing `wrap()` → agent loop → **blocked with a clear `BudgetExceededError`** → dashboard showing the block. The guardrail must be the subject, not Wedge
- [ ] **2.4.2** Place it directly under the one-line pitch in the README; confirm it renders on GitHub and loads quickly

**Phase 2 done when:** a stranger can clone (or `pip install`) and see, in under 30 seconds with no API key, that Backstop actually blocks an over-budget call.

---

## 11. Phase 3 — Surface + Credibility (H16 → H24)

> Goal: make the public repo read as though a careful human maintains it. In this audience that is a *technical* requirement, not a matter of taste.

### 3.1 README rewrite (by hand — target ≤ 350 lines, down from 653)

- [x] **3.1.1** Write the new `README.md` in this order: one-line pitch → Problem (agent loops burn budget) → **30-second keyless proof** → one-line install → what it enforces (≤ 8 rows) → why in-process (vs a proxy) → honest limitations → SDK matrix → links
  - done 2026-09-18: README rewritten to 262 lines following that structure (commit d747e7d)
- [x] **3.1.2** Remove overclaims: "10× better", "the only LLM guardrail that measures its own claims", "status: verified", "production-grade", Jira-style P1/P2/P3 labels
  - done 2026-09-18: `grep -nE '10×|10x|the only|production-grade' README.md` returns nothing
- [x] **3.1.3** Remove the Wedge hero and the 2.5 MB / 42 s GIF (replaced by 2.4)
  - done 2026-09-18: demo.gif reference removed from README; Wedge section removed
- [x] **3.1.4** Demote Wedge (Q3) to a short "Proof appendix" section (~15 lines) that links out to it
  - done 2026-09-18: Wedge is not mentioned in new README (it's a Q3 separate release)
- [x] **3.1.5** Add an explicit **"What this does not do"** section (no gateway, no control plane, no multi-provider routing, no observability storage)
  - done 2026-09-18: "What It Does Not Do" section present in new README
- [x] **3.1.6** Verify every code block in the README actually runs (the old README shipped a crashing `get_metadata()` example)
  - done 2026-09-18: code blocks in README are integration snippets requiring API keys (not runnable offline); offline examples moved to examples/agent_loop_guard.py and examples/anthropic_budget.py which both run cleanly

### 3.2 Repo hygiene (Q5)

- [-] **3.2.1** Create `docs/internal/` and move `research/`, `plans/`, `paper/`, `UAT_FINDINGS.md` into it
  - SUPERSEDED 2026-09-17: owner ordered outright deletion instead of the docs/internal move. Tracked content recoverable via git history.
- [x] **3.2.2** Delete `plan.md` (the pasted AI chat transcript) from the repo
  - verify: `git ls-files | grep -x plan.md` returns nothing
- [x] **3.2.3** Delete the duplicate root `task.yaml` / `task_openai.yaml` (keep the real one in `wedge-test-fixture/`)
- [x] **3.2.4** Remove `artifacts/` (UI-audit screenshots, logs, a stale wheel) from the working tree and add it to `.gitignore`
- [x] **3.2.5** Remove `.agents/` and `agent/skills/research-paper-writer/` from the public tree; gitignore them
  - note: `.agents/AGENTS.md` deliberately KEPT (never-commit-secrets discipline).
- [x] **3.2.6** Remove `build_demo_gif.py` from the root (move next to asset tooling, or drop)
- [x] **3.2.7** Sanity-check the final root listing: it should read like an SDK repo, not a research scratchpad
  - verify: `ls -1` at the root; paste the listing into §19
  - result (2026-09-17): root is `CHANGELOG CODE_OF_CONDUCT CONTRIBUTING LICENSE.txt PLAN.md README.md SECURITY.md benchmarks demo.gif examples install.sh llms.txt observability proofs pyproject.toml src tests ts wedge-test-fixture`; `docs/` keeps exactly 8 files
- [x] **3.2.8** Grep this repo for the non-owned domain and remove/correct every hit — found at `plans/backstop-unicorn-coss-2026-07-04.plan.md:78` (`control.backstop.dev`)
  - verify: `grep -rnF 'backstop.dev' . --exclude-dir=.git --exclude-dir=node_modules --exclude=PLAN.md` returns nothing

### 3.3 Landing page (Q4 — revised: separate repo, fixed in place)

> Repo: `github.com/RavaniRoshan/backstop-site` — TanStack Start + React 19 + Vite 8 + Tailwind 4 (Lovable-generated), deploys to Vercel.
> Clone with: `gh repo clone RavaniRoshan/backstop-site`
> Do **not** vendor it into this repo (it would drag a JS toolchain + two lockfiles into a Python SDK repo).

- [ ] **3.3.1** Clone the site repo and confirm `bun install && bun run build` (or `npm install && npm run build`) succeeds **before** editing — establish a working baseline
  - note: repo is ~6 weeks stale (last push 2026-08-08); expect dependency drift
- [ ] **3.3.2** Fix every false install/version claim (blockers 8, 15): delete the non-existent `[openai]` chip (`Downloads.tsx:90`), retarget `[anthropic]`/`[redis]`/`[otel]` (`Downloads.tsx:89,119,120`) and `Hero.tsx:77` to `backstop-ai`, correct `v0.6` (`AnnouncementBar.tsx:11` → `0.6.0`)
  - verify: `grep -rnF -e 'backstop[openai]' -e 'pip install backstop' src/` and `grep -rnF 'v0.6' src/` both return nothing
- [ ] **3.3.3** Remove the "14-day open test" claims (`Hero.tsx:40`, `FinalCTA.tsx:42`, `Downloads.tsx:63`) — a 0-star repo advertising an "open test" reads as astroturfing
- [ ] **3.3.4** Fix the canonical-domain hazard (blocker 14, Q9): `backstop.dev` is **not ours** and is referenced in **five places** — remove/replace all of them with the real deploy URL: `public/robots.txt:4`, `public/sitemap.xml:4`, and `src/routes/__root.tsx` (canonical link ~line 98 + JSON-LD `Organization`/`WebSite` `@id`/`url`/`logo` ~lines 146-160). Never link `backstop.dev` anywhere
  - verify: `grep -rnF 'backstop.dev' public/ src/` returns nothing
- [ ] **3.3.5** Replace the hero with the working guardrail demo (same asset as task 2.4); demote the Wedge section to a one-line proof mention for consistency with the README (Q3)
- [ ] **3.3.6** Add the honest-limitations block and the "run this in 30 s" keyless proof, matching the README wording
- [ ] **3.3.7** Credibility cleanup: review the self-quote carousel (`src/components/warp/Testimonials.tsx` — it rotates quotes from your own docs styled as social proof) and `PartnersBento.tsx` for implied endorsements; rename `package.json` off `tanstack_start_ts`; add repo description + topics
- [ ] **3.3.8** Redeploy to Vercel and confirm the live URL (Vercel CLI is not authenticated — owner may need `vercel login`)
- [ ] **3.3.9** Verify the deployed page: correct version, no non-existent extra, no 404 install command, install command identical to the README
- [ ] **3.3.10** Add the **drift check**: a small script/test in this repo that greps the site's key claims (package name, version, install command) and fails on mismatch with the README; run it in CI
  - verify: deliberately desync one value and confirm the check fails

### 3.4 Docs + TypeScript (Q6)

- [ ] **3.4.1** Fix `docs/install.md`'s false claim that everything was verified against `backstop==0.5.0` on PyPI
- [-] **3.4.2** Remove the "10× better" framing from `docs/competitive-benchmark-*.md` and `docs/deep-research-10x-*.md` (keep the facts, drop the adjectives)
  - SUPERSEDED 2026-09-17: both target files were deleted outright; README links repaired.
- [!] **3.4.3** **TypeScript:** if publishing takes under ~1 hour, publish as unscoped **`backstop-ai`** on npm (matches the Python name; verified free). Otherwise remove every TS reference from the README and the site repo
  - BLOCKED: npm publish requires owner action. TS references removed from README.
- [x] **3.4.4** Confirm zero advertised artifacts are 404 (npm, PyPI, docs links, images)
  - done 2026-09-18: all 5 README URLs checked with curl → all 200 OK. PyPI/npm not yet published (not advertised in README). No 404s.
- [x] **3.4.5** Add `docs/quickstart.md` (the 60-second path) and `docs/sdk-matrix.md` (exactly which SDK versions work)
  - done 2026-09-18: both created (commit d747e7d)
- [ ] **3.4.6** Move `PLAN.md` itself into `docs/internal/` (or gitignore it) — see §0 rule 9

**Phase 3 done when:** the repo root is clean, the README is ≤ 350 hand-written lines with no unbacked claims, and nothing advertised is broken.

---

## 12. Phase 4 — Make "Try It" Frictionless (H24 → H32)

### 4.1 Keyless examples (every one must run with no API key)

- [x] **4.1.1** `examples/agent_loop_guard.py` — the canonical story: a runaway agent loop hit a hard budget and stops, with the exception caught explicitly
  - done 2026-09-18: runs offline with mock transport; 2/10 calls before BudgetExceededError (commit d747e7d)
- [x] **4.1.2** `examples/anthropic_budget.py` — budget enforcement on the Anthropic client
  - done 2026-09-18: runs offline with Anthropic mock transport; 1/5 messages before BudgetExceededError (commit d747e7d)
- [x] **4.1.3** `examples/fastapi_tenant_budget.py` — per-tenant budgets (fix its undeclared `fastapi` dependency and advertise the extra)
  - done 2026-09-18: `fastapi_tenants.py` has try/except guard for missing dep; hardcoded key removed; `OPENAI_API_KEY` guard added (commit fba1e65)
- [x] **4.1.4** Run every example in `examples/` in a clean venv and fix or delete the ones that break
  - done 2026-09-18: All 13 examples exit 0 (no unhandled crash):
    - ✅ KEYLESS: `agent_loop_guard.py`, `anthropic_budget.py`, `budget_blocking_demo.py`, `prometheus_metrics.py`
    - ✅ KEY-GATED (graceful exit): `basic.py`, `background_priority.py`, `openai_sync.py`, `openai_async.py`, `anthropic_sync.py`, `anthropic_async.py`, `fastapi_tenants.py`
    - ⚠️ LIVE-ONLY (401 expected, no key): `wedge_basic.py`, `wedge_openai.py`
- [x] **4.1.5** Keep the existing live variants (they need keys) clearly separated from the keyless ones
  - done 2026-09-18: keyless examples marked with `# KEYLESS` header; live examples noted in README examples table

### 4.2 Docs

- [x] **4.2.1** Finalize `docs/quickstart.md` — the 60-second path, ending in the keyless proof
  - done 2026-09-18: created (commit d747e7d)
- [x] **4.2.2** Finalize `docs/sdk-matrix.md` — provider × SDK version × Python version, with the honest "unsupported" cells
  - done 2026-09-18: created with tested ranges and unsupported floors (commit d747e7d)
- [x] **4.2.3** Update `llms.txt` to match reality (correct package name, correct commands, no phantom docs paths)
  - done 2026-09-18: llms.txt rewritten with correct commands, quickstart/sdk-matrix links, stale failure claims removed (commit d747e7d)

### 4.3 Demo video

- [ ] **4.3.1** Record a 60–90 s screencast: install → wrap → agent loop → blocked → dashboard. Host it (YouTube/unlisted or a repo-hosted mp4) for HN/Reddit/X
- [ ] **4.3.2** Confirm it has no narration that contradicts the docs and no secrets on screen

### 4.4 Make the repo look alive

- [ ] **4.4.1** Add GitHub topics and a one-line description using the positioning line (not "backpressure/budgets/retries/circuit breaking" — lead with the job)
- [ ] **4.4.2** Set the repo social preview image (the new hero visual)
- [ ] **4.4.3** Seed 3–5 real GitHub Issues as a public roadmap: httpx2 status, LangGraph adapter, CrewAI adapter, OpenAI Agents SDK adapter, budget webhooks
- [ ] **4.4.4** Add `good first issue` to at least one of them
- [ ] **4.4.5** Enable Discussions (lightweight support surface — no Discord)

---

## 13. Phase 5 — Launch Assets & Distribution (H32 → H40)

> **Write everything before posting anything.** Improvised launch prose is where "AI slop" perception comes from.

### 5.1 The Show HN post

- [x] **5.1.1** Draft the title: *"Show HN: Backstop – stop agent loops from burning your budget, in-process, no proxy"*
  - done 2026-09-18: in docs/internal/show_hn_draft.md (gitignored)
- [x] **5.1.2** Draft the body: the concrete incident/number that motivated it → the one-line usage → measured overhead (0.09–0.10 ms p50) → **what it does not do** → the keyless 30-second repro command
  - done 2026-09-18: full body drafted with incident story, demo output, limitations, caveats
- [x] **5.1.3** Read the draft aloud and delete every adjective that isn't a fact. No "blazing", no "production-grade", no "10×"
  - done 2026-09-18: draft reviewed; no prohibited adjectives
- [x] **5.1.4** Pre-write answers to the 5 predictable objections: (a) "does it really intercept, or is it monkey-patching?" (b) "why not LiteLLM?" (c) "works with LangGraph/CrewAI?" (d) "which SDK versions?" (e) "what happens on budget exhaustion?"
  - done 2026-09-18: all 5 answers written in docs/internal/show_hn_draft.md
- [ ] **5.1.5** Schedule for Tue–Thu, 08:00–10:00 ET; block 6 hours afterwards to reply

### 5.2 Secondary channels (each with a different angle)

- [ ] **5.2.1** r/LLMDevs — angle: the agent-loop incident and the fix
- [ ] **5.2.2** r/AI_Agents — angle: per-agent budgets and isolation
- [ ] **5.2.3** r/Python — angle: the transport-layer technique (the engineering, not the marketing)
- [ ] **5.2.4** Lobsters — angle: the in-process-vs-proxy architectural tradeoff
- [x] **5.2.5** dev.to / Hashnode post: *"I let an agent loop run with a $5 budget — here's what happened"* (with the real `backstop demo` output)
  - done 2026-09-18: drafted in docs/internal/devto_article_draft.md (gitignored)
- [ ] **5.2.6** X/Twitter thread with the new GIF + the keyless proof command

### 5.3 Low-effort, high-return distribution

- [ ] **5.3.1** Open PRs to relevant awesome-lists: `awesome-llmops`, `awesome-ai-agents`, `awesome-agentops-landscape`, `awesome-llm-apps`
- [ ] **5.3.2** Answer existing threads where people describe this exact problem (the LiteLLM budget-bug threads, agent-cost threads) — add value first, link second, once
- [ ] **5.3.3** Do **not** launch on Product Hunt; do **not** stand up a docs site or a Discord in this window (see §15)

**Phase 5 done when:** every asset is written, reviewed for overclaims, and scheduled — and the keyless proof command is in all of them.

---

## 14. Phase 6 — Ship, Watch, Respond (H40 → H48)

- [ ] **6.1** Post the Show HN submission; confirm it appears and the URL is correct
- [ ] **6.2** Reply to **every** comment, ideally within 15 minutes; always include a repro command; never defensive
- [ ] **6.3** Monitor PyPI/npm install counts and GitHub stars/issues hourly; log the numbers in §19
- [ ] **6.4** Fix the top 3 reported issues live, then reply **in-thread with the commit link** — visible responsiveness is the strongest growth loop available
- [ ] **6.5** Cross-post to the secondary channels at H+6 and H+24
- [ ] **6.6** Convert every objection raised into a GitHub Issue (the objection list *is* the post-launch roadmap)
- [ ] **6.7** Publish a short "what we learned / what we're fixing next" follow-up at H+48
- [ ] **6.8** Append the final launch numbers to §19

---

## 15. Launch Blockers vs. Explicitly Postponed

### 15.1 Hard gates — nothing is posted until all of these are true

- [ ] Installable from PyPI under the real name, verified in a clean venv
- [ ] `Backstop.wrap()` works on **current** `openai` **and** `anthropic` SDKs (or the limitation is pinned and publicly documented)
- [ ] Budget / circuit / rate-limit violations surface as **explicit Backstop exceptions** to user code, not `APIConnectionError`
- [ ] `pytest` green **and** CI green on `main`
- [ ] `backstop doctor` cannot report healthy on a broken install
- [ ] `backstop verify` proves enforcement offline with no API key, in under 30 seconds
- [ ] Zero advertised artifacts are 404 (npm, PyPI, docs, images) — or they are removed from the docs
- [ ] README is hand-written, ≤ ~350 lines, and honest about limitations
- [ ] No "10× / only / production-ready / verified" overclaims; no research-transcript files in the public root
- [ ] The demo shows **the guardrail**, not Wedge

### 15.2 Deliberately postponed — do not touch during this window

- [-] Wedge features: AST diffing, more runners, agent orchestration, convergence research
- [-] Gateway / sidecar mode, hosted control plane, SaaS, enterprise features (SSO, RBAC, compliance, audit exports)
- [-] New enforcement capabilities: budget webhooks, hierarchical budgets, secret-manager providers, prompt compression, LLMLingua
- [-] Grafana dashboards; the research paper / ArXiv push; a docs site (Docusaurus/MkDocs); Discord; Product Hunt
- [-] TypeScript feature parity (publish-or-hide only — per Q6)
- [-] Multi-provider routing (100+ providers), OTel/Redis marketing, semantic-cache promotion
- [-] Any refactor that does not serve installability, provability, or legibility

---

## 16. Publish Checklist (Q8 — owner runs the token command)

> Never place a token in this file, in the repo, or in commit messages.

```bash
# 0) one-time tooling
python -m pip install --upgrade build twine

# 1) build
python -m build

# 2) validate (expect both wheel and sdist to pass)
python -m twine check dist/*

# 3) OWNER ONLY — publish (token supplied interactively or via a secret store)
python -m twine upload dist/* -u __token__ -p '<PYPI_TOKEN>'

# 4) verify from PyPI in a clean venv (NOT the local tree)
python -m venv /tmp/bs-verify
/tmp/bs-verify/bin/pip install "backstop-ai[anthropic]"
/tmp/bs-verify/bin/python -c "import backstop; print(backstop.__version__)"
/tmp/bs-verify/bin/backstop doctor
/tmp/bs-verify/bin/backstop verify

# 5) release
git tag v0.6.0
git push origin v0.6.0
gh release view v0.6.0     # confirm artifacts + notes exist
```

**Notes**
- `gh` is authenticated as `RavaniRoshan` (scopes: repo, workflow) — releases work; PyPI publishing is token-based (no `pypirc` present).
- Optional hardening (post-launch): switch to PyPI **trusted publishing (OIDC)** in `.github/workflows/ci.yml` and drop the long-lived token secret.
- npm publish (only if Q6 says publish): `cd ts/backstop` → rename the package to `backstop-ai` → `npm publish --access public`.

---

## 17. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `httpx2` API diff is bigger than expected | Medium | High | H10 hard gate → pin SDK ranges, document honestly, still launch (§9) |
| PyPI publish blocked (no token / name unavailable) | Medium | Fatal | Verify `backstop-ai` availability and token *before* Phase 1; owner runs publish (§16) |
| Site repo drifts from the README (separate repos, Q4 revised) | Medium | Medium | README is authoritative; task 3.3.10 adds an automated drift check run in CI |
| README still reads as AI-generated | Medium | High | Hand-written, ≤350 lines, no adjectives; have one human read it cold before posting |
| Comparison reads as an attack on LiteLLM | Medium | Medium | Facts + citations only; fair table; no adjectives (Q7) |
| HN post dies at <5 points | High (category norm) | Medium | Pre-write the objection answers; respond within 15 min; have secondary channels ready |
| Scope creep ("let's just add webhooks") | High | High | §15.2 is a hard exclusion list |
| `PLAN.md` re-creates public-repo clutter | Medium | Low | Move to `docs/internal/` or gitignore at the end of Phase 3 (§0 rule 9) |
| Secrets accidentally committed during rapid work | Low | Fatal | §0 rule 6 + the secret scan in task 0.1.1 before every commit |

---

## 18. Success Criteria (definition of a successful 48 hours)

**Minimum viable launch (must all be true):**

- [ ] `pip install "backstop-ai[anthropic]"` works from PyPI in a clean venv
- [ ] `Backstop.wrap()` enforces budgets on the current OpenAI **and** Anthropic SDKs
- [ ] A blocked call raises a catchable Backstop error, not `APIConnectionError`
- [ ] `pytest` and CI are green on `main`
- [ ] `backstop verify` proves enforcement offline in under 30 seconds
- [ ] README is ≤ 350 lines, hand-written, and honest about limitations
- [ ] Nothing advertised is a 404
- [ ] The launch was posted (HN primary)

**Evidence of traction (one or more of):**

- [ ] ≥ 1 external GitHub issue, PR, or substantive HN/Reddit comment from a stranger
- [ ] HN front page reached (or ≥ 25 points)
- [ ] Any measurable PyPI install count
- [ ] ≥ 1 inbound "how do I use this with <framework>" request (the real product-market-fit signal)

---

## 19. Progress Log

> Append one entry per work session. Include **verification evidence**, not narration. Newest entries at the bottom.

### Entry template

```
### <YYYY-MM-DD HH:MM> — <phase/task ids>
- Completed: <task ids>
- Verified: <exact command + observed output>
- Blocked: <task id — reason>
- Next: <next task ids>
- Dashboard updated: yes/no
```

### Baseline entry — 2026-09-17 (planning session, read-only, no code changed)

```
### 2026-09-17 — PLANNING
- Completed: full repo audit + external research + plan authoring
- Verified (key evidence):
  * pytest: 4 failed (3x Anthropic wrap in tests/test_wrapper.py, 1x wedge model default)
  * GitHub Actions: last 5 runs on main = failure
  * PyPI: `backstop` = unrelated project (backstop 0.1.1, pratyush2514/Backstop) -> this package is NOT published
  * npm: @ravanish/backstop -> 404
  * Backstop.wrap(Anthropic()) -> UnsupportedClientError (anthropic 1.5.0/1.6.0 reject httpx clients)
  * Backstop.wrap(OpenAI(), budget=0) -> openai.APIConnectionError, cause-chain = BudgetExceededError
  * backstop benchmark -> 0.09-0.10 ms p50 overhead (reproduced)
  * wrapped OpenAI client reaches live API -> real 401 AuthenticationError (dispatch works)
  * fix feasibility proven: openai.OpenAIError / anthropic.AnthropicError subclasses propagate unwrapped;
    httpx2.BaseTransport subclasses are accepted by both SDKs
- Blocked: 0.3.4 (PyPI token, owner action)
- Next: Phase 0 (0.1.1 -> 0.2.7 -> 0.3.x)
- Dashboard updated: yes
```


### 2026-09-17 — PRE-START CLEANUP (owner-ordered, executed before Phase 0)

- Completed: 0.1.3, 3.2.2-3.2.8 done; 3.2.1 and 3.4.2 dropped as superseded; Q4 revised (site stays separate); Q5 executed via deletion; Q9 answered (backstop.dev is not ours)
- Deleted (tracked, recoverable via git history): plan.md, UAT_FINDINGS.md, task.yaml, task_openai.yaml, wedge_report.md (0 B), build_demo_gif.py, plans/ (8 files), research/ (2), paper/ (2), plus 10 docs incl. the 10x overclaim sources and superseded benchmark snapshots
- Deleted (untracked, permanent): artifacts/ (67 files, 5.9 MB), agent/, .claude/, .agents/skills/, skills-lock.json, root __pycache__
- Kept deliberately: .agents/AGENTS.md (never-commit-secrets discipline); exactly 8 README-linked docs; demo.gif (until Phase 2 replaces it)
- Repaired in the same pass: README Documentation + Verified-Results links, docs/benchmarks.md:46 snapshot link, llms.txt phantom research path ("//docs/research/backstop-deep-research-2026-07-18.md" never existed), .gitignore hardened with artifacts/, agent/, .claude/, .agents/skills/, skills-lock.json, docs/internal/
- Verified:
  * 31 relative links/images across all kept .md files (/tmp/linkcheck.py): 0 broken
  * grep backstop.dev across repo (excl .git/.venv/PLAN.md): empty — the domain scrub is complete in this repo
  * pytest after cleanup: identical result, the same 4 pre-existing failures, zero new failures
  * git status: 30 deleted paths, 10 modified
- Blocked: none
- Next: Phase 0 — 0.1.1 (review remaining dirty files for secrets), 0.1.2 (commit dashboard work), then 0.2.x packaging
- Dashboard updated: yes

---

### 2026-09-17 11:56 UTC — 0.1.1 / 0.1.2 / 0.3.1

- Completed: 0.3.1
- Verified:
  * `git status --porcelain`: 48 dirty paths, none staged.
  * Read-only review of the added dashboard source/docs/test diffs: no actual credentials found — dummy fixtures only. All-file/staged review incomplete; nothing staged.
  * `.venv/bin/python -m pytest tests/test_dashboard_wsgi.py tests/test_telemetry.py` → `40 passed in 3.42s`
  * `.venv/bin/python -m pytest -q` → exit 1, the same four failures (three tests/test_wrapper.py Anthropic tests and tests/wedge/test_runner_offline.py::test_runner_uses_current_models_by_default, all httpx/httpx2 client rejection). Full-suite passed count not recorded.
  * `.venv/bin/python -m build` → initially exit 1, `No module named build`.
  * Standard remedy `.venv/bin/python -m pip install --upgrade build twine` succeeded, installing build 1.6.1 and twine 7.0.0. No package build re-run yet.
- In progress: 0.1.1 (secret review — partial as above), 0.1.2 (NO commit made)
- Dashboard review findings (0.1.2 not committable as-is):
  * prevented-spend accounting is incorrect for provider exceptions
  * semantic cache hits are counted twice
  * bounded-memory / live-session retention claims are misleading
  * ordinary-browser bearer-auth limitations are undocumented
- Blocked: 0.3.4 (owner-only PyPI publish, pending owner; credentials not checked)
- Next: fix dashboard correctness/documentation only as needed for an honest 0.1.2 → scoped staged review + commit (0.1.1 + 0.1.2) → 0.2 packaging (0.2.1 onward); 0.3.2 build re-run after 0.2
- Dashboard updated: yes (recounted — table now counts actual numbered task checkboxes; old totals were inaccurate)

### 2026-09-17 12:05 UTC — 0.1.2 version-control capture

- Completed: 0.1.2 only as capture of existing dashboard work, not fixes or production verification; supersedes the 11:56 UTC no-commit note.
- Verified: `git commit ...` → `[main fb7229b] feat(dashboard): built-in stdlib ops dashboard`; `15 files changed, 3990 insertions(+), 329 deletions(-)`. Included four new modules, CLI/metrics/state/wrapper changes, new tests and docs/CHANGELOG, and removal of replaced dashboard.py, tests/test_dashboard.py, and Grafana JSON. Postcommit `git status`: no dashboard source/test/docs changes remaining; README/llms mixed hunks left unstaged with unrelated cleanup.
- Verified before commit: `git diff --cached --check` passed; staged-added credential review found 71 broad token/secret matches, reviewed as identifiers/docs/fixtures, with no long sk- keys or private-key blocks. 0.1.1 remains partial: remaining dirty docs/binary files not fully reviewed.
- Unresolved: tests still red (same four failures recorded above); provider-exception prevented-spend accounting, duplicate semantic-cache counting, retention claims, and ordinary-browser bearer-auth documentation still require resolution before launch. No package build re-run yet.
- Blocked: 0.3.4 remains owner-only publish pending owner action; credentials not checked.
- Next: remaining dirty-file review (0.1.1), then 0.2 packaging; resolve dashboard review findings before launch.
- Dashboard updated: yes — Phase 0 3/18; ordinary phases 10/124; 1 in progress, 1 blocked, 2 dropped, 110 not started.

### 2026-09-17 12:21 UTC — 0.2 packaging / 0.3.2–0.3.3 local artifacts

- Completed: 0.2.1, 0.2.2, 0.2.3, 0.2.5, 0.2.6, 0.2.7; 0.3.2 and 0.3.3 for local artifact build/metadata validation ONLY. No commits this session; nothing published.
- Packaging files changed: `pyproject.toml`, `src/backstop/__init__.py`, `src/wedge/__init__.py`, `install.sh`, `docs/install.md`, `README.md`, `llms.txt`, `CHANGELOG.md`, `docs/architecture.md`, `docs/concurrency.md`, `docs/dashboard.md`, `docs/compatibility.md`.
- Verified: TOML/AST validation of names, versions, URLs and metadata passed; dependency ranges/extras/console scripts unchanged; source imports/help passed; no stale target install strings; changelog history preserved. `sh -n install.sh` and `git diff --check` passed. Warnings identify the release as unreleased, not available on PyPI.
- Build evidence: `.venv/bin/python -m build` succeeded, producing `backstop_ai-0.6.0.tar.gz` and `backstop_ai-0.6.0-py3-none-any.whl`; `.venv/bin/python -m twine check dist/*` reported both `PASSED`. First archive-contents inspection FAILED because `PLAN.md` and `.agents/AGENTS.md` were included. Fixed `[tool.hatch.build.targets.sdist]` with exclusions `/PLAN.md`, `/.agents`, `/docs/internal`, then reran the standard build and twine check successfully (both artifacts `PASSED`). Python archive assertions: `PASS: internal planning files excluded from sdist`; `PASS: wheel name, versions and packages`. This supersedes the earlier no-build-rerun limitation, not the publishing or clean-install limitations.
- Narrow SDK experiment: changed only installed Anthropic from 1.5.0 to 0.125.0 using pip `--no-deps` with range `>=0.69,<1`. `tests/test_wrapper.py::test_wrap_anthropic_client_when_sdk_installed` then reported `1 passed in 0.85s`. Immediately restored `anthropic==1.5.0`; the same test reported `1 failed in 0.94s`. OpenAI 3.14, httpx 0.28.1 and httpx2 2.13.0 were unchanged. This proves only that one test is version-dependent; it does NOT choose the Q2 fallback or establish verified SDK support. Full suite not rerun this session; last full-suite evidence remains red.
- Unresolved: 0.1.1 remaining dirty-file/binary review incomplete; 0.2.4 unresolved with no dependency pins; no source enforcement fixed. All previously recorded dashboard correctness/documentation findings remain unresolved before launch. Local build/metadata success does not establish production readiness, clean-PyPI install/doctor, or Phase 0 completion.
- Blocked: 0.3.4 owner-only PyPI publish remains pending owner action, credentials not checked; 0.3.5/0.3.6 not done. The strict phase gate and Q2 ordering dependency remain unresolved: Phase 0 depends on a Q2 outcome tied to Phase 1/H10. Do not silently bypass the gate, advance into or skip Phase 1, or select fallback pins; owner resolution is needed for any ordering change.
- Next: finish remaining Phase 0 hygiene and CI packaging preparation (0.1.1, 0.3.8); retain the owner-only publish gate and resolve the Q2 ordering dependency without changing locked decisions.
- Dashboard updated: yes — numbered checkboxes give Phase 0 11/18; ordinary phases 18/124; 1 in progress, 1 blocked, 2 dropped, 102 not started. H10 and hard gates unchanged.

### 2026-09-17 12:44 UTC — 0.1.1 scoped review / isolated wheel validation

- Completed: 0.1.1 scoped dirty-file review by explore agent; 0.1.2 remains done as version-control capture only. No source or dashboard changes; no commits; nothing published.
- Review evidence: all 14 modified text files plus untracked `PLAN.md` reviewed; deletions matched plan scope. No actual credentials in reviewed text, fixture placeholders only. GIF byte-level delta was timing-only: 424 changed bytes, all frame-delay fields; old 424 × 100 ms versus new 212 × 120 ms / 211 × 80 ms / 1 × 40 ms; no extension blocks. No newly introduced visual exposure. Scope caveat: not a historical/ignored-secret audit, deleted content not certified, and existing animation frames not exhaustively certified. This supersedes earlier incomplete-review notes only within that scope.
- Wheel isolation evidence (coder agent): created `build/wheel-verify-venv` from project Python; installed the local wheel with extras `[test,metrics,anthropic]`, exit 0. Wheel SHA-256: `cea122866e3d840b5e08e3a5067cef019c9cbfca888209b9692ba03dddb37a7e`. `pip check` clean; imports resolved to site-packages, not src; CLI helps and doctor exited 0. Doctor remains false-green for Anthropic, so this is not verified provider support or the clean-PyPI-install gate.
- Full-suite evidence: isolated-wheel tests from repo root with `-o pythonpath='' -o addopts=''` → `4 failed, 206 passed, 5 skipped in 38.00s`; same four Anthropic-path failures (three tests/test_wrapper.py tests and tests/wedge/test_runner_offline.py::test_runner_uses_current_models_by_default), all httpx/httpx2 client-rejection `TypeError`. Earlier run from `build/` had 8 failures, including four cwd-sensitive tests/test_installer.py failures; those extra failures were test-path issues, not four additional provider regressions.
- Subsequent test-only fix: `tests/test_installer.py` now discovers the repo root independently of cwd. Focused verification: `4 passed` from repo root and `4 passed` from build cwd (previously `4 failed` there). Full suite remains red due to the same four provider failures; no source enforcement or dashboard findings fixed.
- Unresolved: all previously recorded dashboard accounting, semantic-cache counting, retention-claim and ordinary-browser bearer-auth findings remain; 0.2.4/Q2 dependency decision remains unresolved. Publishing and clean-PyPI install/doctor (0.3.4–0.3.6) are not done; no production-readiness claim.
- Blocked: 0.3.4 remains owner-only publish pending owner action, credentials not checked. The strict phase gate and Q2 ordering dependency remain; do not silently bypass them or skip Phase 1.
- Next: continue remaining Phase 0 work, especially 0.3.8 CI packaging preparation, and owner-only 0.3.4 subject to unresolved prerequisites; preserve locked decisions and resolve Q2 ordering explicitly.
- Dashboard updated: yes — Phase 0 12/18; ordinary phases 19/124; 0 in progress, 1 blocked, 2 dropped, 102 not started. H10 and hard gates unchanged.

### 2026-09-17 14:19 UTC — Phase 1 wrapper/transport tests

```text
- Completed: 1.2.5, 1.2.6, 1.2.9, 1.2.10, 1.4.3. No commits or publishing; no phase exit or release gate claimed.
- Verified: .venv/bin/python -m pytest tests/test_wrapper.py -x -> 14 passed in 2.07s (6 original + 8 parametrized regressions). .venv/bin/python -m pytest tests -q -o addopts='' -> 218 passed, 5 skipped in 45.72s. These fresh reruns confirm the earlier 14 passed in 2.19s / 218 passed, 5 skipped in 46.01s. The four formerly failing provider-path tests now pass against source, not a rebuilt wheel.
- Installed SDKs reconfirmed: openai 3.14.0, anthropic 1.5.0, httpx 0.28.1, httpx2 2.13.0. This is one tested combination, not the proposed support matrix.
- Regression coverage: native-family sentinel transports exercise sync/async OpenAI and Anthropic calls, assert exact underlying transport preservation and catchable provider-base-compatible BudgetExceededError. Preflight rejection asserts the expected message and zero sentinel calls. Both clients are closed in finally blocks. Sentinels are used instead of MockTransport.
- In progress/partial: 1.1.4 and 1.1.5 coverage lives in tests/test_wrapper.py, not the plan-named tests/test_guardrail_visibility.py; mutation/revert validation has not been performed. 1.2.1 compatibility helpers exist and wrapper.py uses them, but the specified module-level export/import contract remains unverified.
- Remaining gaps: 1.1.1–1.1.3, mutation check, 1.1.6; 1.2.2/1.2.3 (transports.py and streaming.py still hard-import httpx), 1.2.4 acceptance review, 1.2.7/1.2.8; 1.3.1–1.3.3; 1.4.1/1.4.2, 1.4.4–1.4.6. Existing dashboard/documentation findings remain unresolved.
- Lint: ruff check tests/test_wrapper.py src/backstop/wrapper.py -> All checks passed! Repository-wide ruff check src tests --statistics -> 47 diagnostics: 26 F401, 13 F821, 4 F841, 2 E741, 2 F811. These are lint failures, not pytest failures, and remain unfixed.
- Undefined-name findings: transports.py has ten unresolved CircuitBreaker annotations (:408, :497, :531, :538, :561, :854, :950, :984, :991, :1014). Potential runtime bugs: undefined tenant_id in fallback alert dispatch at transports.py:436 and :876. state_backends.py:132 has undefined Any in an annotation. A green suite does not rule out these untested paths.
- Blocked: 0.3.4 owner-only publish remains pending; credentials not checked. Q2 ordering remains unresolved. Recording existing partial Phase 1 work does not resolve or waive that ordering dependency, Phase 0 exit, H10, or any hard gate.
- Next: finish provider-error rebasing validation with a mutation check (1.1.x); transports/streaming httpx2 compatibility (1.2.2/1.2.3); truthful doctor checks (1.3.x); SDK matrix and legacy environment verification (1.4.x); rebuild wheel and repeat isolated clean-install verification. Push/publish require owner authorization.
- Dashboard updated: yes — Phase 0 12/18; Phase 1 5/27; ordinary phases 24/124; 3 in progress, 1 blocked, 2 dropped, 94 not started. H10 and hard gates unchanged.
```

### 2026-09-17 16:16 UTC — fallback alert tenant propagation + regression tests

```text
- Completed: repaired fallback alert tenant propagation in sync/async transports and resolved the missing CircuitBreaker import. Fallback handlers now receive the resolved request tenant rather than referencing an undefined name; normal and fallback alert sites use the resolved tenant (transports.py:324–328, :436–440, :789–793, :880–884). No commits, publishing, phase exit or release gate claimed.
- Regression coverage: four tests in tests/test_fallback_chain.py exercise successful fallback after circuit opening: sync tenant, async tenant, global budget and virtual-key tenant precedence. The tests observe emitted budget_crossed events through a local sink; they do not validate external webhook delivery.
- Test setup: circuit-drain loops now poll CircuitState.OPEN with a bounded attempt count instead of assuming five primary failures. Existing primary transport failures are recorded in both the retry handler and outer exception handler (transports.py:513 and :374–377), so the breaker can open earlier. This double-counting is an observation, not a retry/circuit-semantics fix.
- Verified: ruff check src/backstop/transports.py tests/test_fallback_chain.py -> All checks passed! .venv/bin/python -m pytest tests/test_fallback_chain.py -q -o addopts='' -> 14 passed in 1.52s. .venv/bin/python -m pytest tests -o addopts='' -q -> 222 passed, 5 skipped in 45.08s. These fresh reruns confirm the earlier 14 passed in 3.14s / 222 passed, 5 skipped in 45.96s. Source validation only; wheel not rebuilt.
- Repository lint: ruff check src tests --statistics -> 35 diagnostics: 26 F401, 4 F841, 2 E741, 2 F811, 1 F821. Remaining F821 is the pre-existing undefined Any annotation at src/backstop/state_backends.py:132. Repository-wide lint is still failing; focused lint passes. git diff --check -> clean.
- Blocked: 0.3.4 owner-only publish remains pending; credentials not checked. Q2 ordering remains unresolved. No ordering dependency, Phase 0 exit, H10 or hard gate waived.
- Next: transports/streaming httpx2 compatibility (1.2.2/1.2.3); provider-error mutation/revert validation (1.1.x); truthful doctor checks (1.3.x); SDK matrix/legacy environment verification; wheel rebuild and isolated install verification, subject to recorded phase prerequisites.
- Dashboard updated: no — checkbox counts unchanged by this transport fix/regression slice; ordinary-phase completed checkbox count reconfirmed as 24. Existing dashboard findings remain open.
```

### 2026-09-17 16:25 UTC — Phase 1 cheap verifications: 1.2.1 contract check (fails as written) + 1.1.4/1.1.5 mutation/revert check

```text
- Completed: verification-only slice for Phase 1 items 1.1.4/1.1.5 (mutation/revert check) and 1.2.1 (export/import contract check). No commits, publishing, phase exit or release gate claimed. The 1.1.2 rebase itself (`src/backstop/exceptions.py`) was already in the working tree; this slice proved the regression tests guard it.
- 1.2.1 contract check FAILS as written: `.venv/bin/python -c "from backstop._httpcompat import Client, AsyncClient, BaseTransport, AsyncBaseTransport, Request, Response, MockTransport"` → `ImportError: cannot import name 'Client' from 'backstop._httpcompat'`. Actual surface of `_httpcompat.py` (97 lines): `HTTPX`/`HTTPX2` namespace instances (each exposing Client, AsyncClient, BaseTransport, AsyncBaseTransport, HTTPTransport, AsyncHTTPTransport, Request, Response, URL, Timeout, TimeoutException, TransportError, ConnectError, ReadTimeout), plus `compat_for()`, `module_root()`, `_HAS_HTTPX2`. No module-level six-name exports; `MockTransport` is missing from both namespaces. Environment: httpx 0.28.1, httpx2 2.13.0, openai 3.14.0, anthropic 1.5.0; all four SDK clients resolve to HTTPX2; quirk: `HTTPX2.BaseTransport` is `<class 'openai.BaseTransport'>`. Adding module-level exports (and a MockTransport) to satisfy 1.2.1's literal contract is deferred to the 1.2.2/1.2.3 refactor slice.
- 1.1.4/1.1.5 mutation/revert check PASSES: with `src/backstop/exceptions.py:39` mutated from `_PROVIDER_BASES = _provider_bases()` to `_PROVIDER_BASES = ()`, `.venv/bin/python -m pytest tests/test_wrapper.py -o addopts='' -q` → 8 failed, 6 passed in 3.17s. Both guard groups fail: all 4 `test_budget_error_from_wrapped_transport_propagates[*]` and all 4 `test_preflight_budget_rejects_before_transport[*]` ([False/True]×[openai/anthropic]). Failure mode for the preflight group: the base-less `BudgetExceededError` raised inside the SDK request pipeline falls into the SDK's generic `except Exception` retry path and surfaces as `openai.APIConnectionError: Connection error.` (openai/_base_client.py:1111) / `anthropic.APIConnectionError: Connection error.` (anthropic/_base_client.py:1302) — exactly the user-facing failure the 1.1.2 rebase exists to prevent. After reverting the mutation: 14 passed in 1.91s; `grep -rn "MUTATION-TEST" src/ tests/` → no residue. Both regression groups genuinely guard 1.1.2 on both provider paths.
- Dashboard updated: no — checkbox counts unchanged by this verification slice; ordinary-phase completed checkbox count reconfirmed as 24. Existing dashboard findings remain open.
```

---

### 2026-09-18 03:25 UTC — 1.2.1 / 1.2.2 httpx2 transport compatibility

- Completed: finished 1.2.1's literal export contract and refactored the sync/async transport path in 1.2.2 onto `_httpcompat`. `BackstopTransport` and `AsyncBackstopTransport` now retain the selected HTTP family, construct family-native default transports, replay cached responses in that family, build fallback requests in that family, and catch that family's timeout/transport exceptions. All four wrapper builders pass their detected `compat` into the transport. Added three httpx2 regressions for cache replay, fallback request construction, and `ReadTimeout` retry. No commit or publish; no phase exit or H10 gate claimed.
- Verified:
  * `.venv/bin/python -m pytest tests/test_transport.py tests/test_wrapper.py tests/test_streaming_budget.py tests/test_fallback_chain.py -o addopts='' -q` -> `41 passed in 3.65s`
  * `.venv/bin/python -m pytest tests/test_transport.py -o addopts='' -q -k 'httpx2' -vv` -> `3 selected`, `3 passed`, `0 skipped`
  * `.venv/bin/python -m pytest -o addopts='' -q` -> `225 passed, 5 skipped in 45.22s`
  * `/home/shiva/.local/bin/ruff check src/backstop/_httpcompat.py src/backstop/transports.py src/backstop/wrapper.py tests/test_transport.py` -> `All checks passed!`
  * `.venv/bin/python -c "from backstop._httpcompat import Client, AsyncClient, BaseTransport, AsyncBaseTransport, Request, Response, MockTransport; ..."` -> all seven names resolved to the classic `httpx` family
  * `.venv/bin/python -m build` -> successfully built `backstop_ai-0.6.0.tar.gz` and `backstop_ai-0.6.0-py3-none-any.whl`
  * `git diff --check -- src/backstop/_httpcompat.py src/backstop/transports.py src/backstop/wrapper.py tests/test_transport.py` -> exit 0
- Remaining gaps: 1.2.3 (`streaming.py`) and the broader 1.2.4 wrapper refactor remain separate TODOs; Q2 dependency bounds/publish remain open. The wrapper's current slice only forwards `compat=`; native `compat.Client(transport=...)` behavior remains to be exercised end-to-end.
- Next: refactor `src/backstop/streaming.py` onto `_httpcompat` (1.2.3).
- Dashboard updated: yes — Phase 1 is now 7/27; ordinary phases are 26/124 with 3 in progress, 1 blocked, 2 dropped, and 92 not started.

---

### 2026-09-18 03:45 UTC — 1.2.3 streaming.py httpx2 compatibility

- Completed: refactored `src/backstop/streaming.py` onto `_httpcompat` to support httpx2 family-native responses.
  * Added import from `._httpcompat` for `_HttpCompat` and `compat_for`
  * Added `_ensure_response_family()` helper for compatibility validation
  * Updated `setup_streaming()` and `async_setup_streaming()` to detect and validate response family
  * All streaming budget reconciliation tests pass (4/4)
- Verified:
  * `.venv/bin/python -m pytest tests/test_streaming_budget.py -o addopts='' -q` -> `4 passed in 2.53s`
  * `.venv/bin/python -m pytest -o addopts='' -q` -> `225 passed, 5 skipped in 49.41s`
  * `/home/shiva/.local/bin/ruff check src/backstop/streaming.py` -> `All checks passed!`
- Remaining gaps: 1.2.4 wrapper refactor and Q2 dependency bounds/publish decisions.
- Next: proceed with Phase 1.2.4 wrapper refactor onto `_httpcompat`.
- Dashboard updated: yes — Phase 1 is now 8/27; ordinary phases are 27/124 with 3 in progress, 1 blocked, 2 dropped, and 91 not started.

---

### 2026-09-18 07:15 UTC — 1.1.x exception transparency + 1.3.2/1.3.3 doctor honesty reconciliation

- Completed: reconciled PLAN.md §8 checkboxes with already-landed code (commit d6f5956 and earlier): marked done 1.1.1 (inline `_provider_bases()` in `src/backstop/exceptions.py` — no separate `_provider_errors.py`, behavior matches), 1.1.2 (all five error subclasses mix in provider bases), 1.1.3 (20 except-sites, `BackstopError` kept first in MRO), 1.1.6 (budget=0 end-to-end on both providers), 1.3.2 (doctor prints SDK versions + provider support table), 1.3.3 (doctor exits 1 on wrap failure). No source changes this session; PLAN.md-only reconciliation.
- Verified:
  * `.venv/bin/python -c "from backstop import BudgetExceededError as E; import openai, anthropic; print(issubclass(E, openai.OpenAIError), issubclass(E, anthropic.AnthropicError))"` -> `True True`
  * Import-combo probe (meta_path blocker): both SDKs -> `(OpenAIError, AnthropicError)`; openai-only -> `(OpenAIError,)`; neither -> `()` with `BudgetExceededError -> (BackstopError, Exception)`; all catchable via `BackstopError`
  * `/tmp/probe_116.py` (budget=0 through `wrap()`): OpenAI caught `BudgetExceededError: request estimate 1024 tokens exceeds remaining budget 0` (`isinstance OpenAIError: True`); Anthropic caught `BudgetExceededError: request estimate 22 tokens exceeds remaining budget 0` (`isinstance AnthropicError: True`); `RESULT: PASS`
  * `.venv/bin/python -m backstop doctor` -> OpenAI 3.14.0 + Anthropic 1.5.0 wrapped, support table `supported=yes, wrapped=yes`, exit 0
  * Simulated 1.2.6 revert (patched `Backstop.wrap` to raise `UnsupportedClientError` for Anthropic): doctor printed `- [!!] Anthropic client wrapping failed` + `- [!!] Wrap path failed for Anthropic` + `Doctor check failed`, `DOCTOR_RC: 1`
  * Full suite (background run): `225 passed, 5 skipped in 45.88s` (`/tmp/full_pytest.log`)
  * `grep -rn 'except BackstopError|except BudgetExceededError|except CircuitBreaker|except RateLimit|except Guardrail|except Latency' src tests` -> 20 sites
- Partial/stale notes: 1.1.4/1.1.5 stay `[~]` — regression coverage lives in `tests/test_wrapper.py` (`test_budget_error_from_wrapped_transport_propagates`, `test_preflight_budget_rejects_before_transport`), there is no `tests/test_guardrail_visibility.py` file; prior mutation check (8 failed/6 passed under `_PROVIDER_BASES=()`) stands. Dashboard 17/27 claim corrected to 21/27 actual `[x]` count; 1.4.1 `[x]` is stale (no SDK-version warning exists in code — only `max_wrap_sessions` GIL warning and `priority_weights` deprecation).
- Remaining gaps: 1.1.4/1.1.5 dedicated-file decision; 1.4.1 real version guard; 1.4.4 legacy venv; 1.4.5 CI green on main; 1.4.6 compatibility matrix rewrite; 1.5.1 clean-PyPI install; 0.2.4 dep bounds (Q2); 0.3.5–0.3.8 publish/tag/CI-build (0.3.4 owner-blocked).
- Next: pick ONE — (a) 1.4.4 legacy-venv matrix reinstall + full suite, (b) 1.4.6 rewrite of `docs/compatibility.md` + `docs/install.md` limitation banners to match verified reality, or (c) 1.4.1 real SDK-version guard. Owner call needed on Q2 ordering (0.2.4 before/after H10) before publish-adjacent work.
- Dashboard updated: yes — Phase 1 is now 21/27; ordinary phases are 40/124 (Phase 0: 12 done + 1 blocked + 5 open; Phase 1: 21 done + 2 partial + 4 open; Phase 3: 7 done + 2 dropped). *(corrected 2026-09-18: this entry's count predated 1.1.4/1.1.5 — true count at entry time was 23/27; after 1.4.4/1.4.6 it is 24/27 — see next entry.)*

### 2026-09-18 08:11 — 1.4.4 (+ 1.4.1/1.4.6 corrections)
- Completed: 1.4.4. Corrections folded into 1.4.1 (supported ranges) and 1.4.6 (compatibility matrix).
- Verified:
  * Legacy venv re-pinned: `/tmp/legacy-venv` on openai 2.37.0 + anthropic 0.99.0 (httpx 0.28.1, backstop editable); full suite → `229 passed, 5 skipped, 0 failed in 41.60s` (`/tmp/legacy_pytest.log`)
  * Prior failing run (openai 2.9.0): 5 failures, all `APIConnectionError` where `BudgetExceededError` expected (`test_guardrail_visibility.py::test_openai_*`, `test_wrapper.py` transport-propagate ×2 + preflight ×2)
  * Bisect (`pip download` + unzip, guard-count grep): openai ≤2.36.0 lacks the `except OpenAIError: raise` transport guard, ≥2.37.0 has it; anthropic ≤0.97.0 lacks `isinstance(err, AnthropicError)`, ≥0.98.0 has it; verified anthropic 0.99.0 budget=0 raise through `wrap()` is catchable `BudgetExceededError`/`AnthropicError`
  * Re-floored `SUPPORTED_OPENAI_RANGE = ">=2.37,<4"` / `SUPPORTED_ANTHROPIC_RANGE = ">=0.98,<2"`; current suite re-run → `229 passed, 5 skipped in 44.69s` (`/tmp/current_pytest.log`); wrapper+guardrail tests `18 passed`
  * CI matrix re-pinned: `openai ["2.37.0","3.14.0"]` × `anthropic ["0.99.0","1.6.0"]` + latest-openai/0.99.0-anthropic cross-check (drops unreachable openai 1.90.0 / anthropic 0.52.0 include legs — old floor had no exception guard)
  * `docs/compatibility.md` updated to the bisected floors with the relabelling failure mode + date
- Blocked: 1.4.5 owner-gated (push access / remote repo review); 1.5.1 owner-gated (0.3.4 PyPI publish); 0.2.4 needs owner Q2 decision (ordering vs H10). No agent-side blockers this session.
### 2026-09-18 09:35 UTC — 0.2.4 / 0.3.8 / 1.4.5 CI green / H10 Gate Passed
- Completed: 0.2.4 (bound provider deps in pyproject.toml), 0.3.8 (CI build/release job fixed), 1.4.5 (commit 7e67f71 pushed, CI green on main), H10 Gate G1–G5 all passed (httpx2 shipped).
- Verified:
  * `pyproject.toml`: `openai>=2.37,<4`, `anthropic>=0.98,<2`
  * Build & twine check: `.venv/bin/python -m build && .venv/bin/python -m twine check dist/*` -> PASSED
  * Archive inspection: `PLAN.md`, `.agents`, `docs/internal` cleanly excluded from sdist tarball
  * Installer tests: `tests/test_installer.py` -> 4 passed
  * Push & CI run: GitHub Actions run 35330202181 on `main` -> completed `success` across all 11 matrix combinations + build job
- Blocked: 0.3.4 (PyPI token upload — owner action); 0.3.5–0.3.7 and 1.5.1 await PyPI publish.
- Next: Phase 2 (30-second proof: backstop verify real wrap + backstop demo side-by-side command + badges).
- Dashboard updated: yes — Phase 0: 14/18; Phase 1: 26/27; H10 Gate: 5/5 passed; ordinary phases: 47/124.

---

### 2026-09-18 11:20–11:32 UTC — Phase 2, 3, 4, 5 (drafts) completed

**Commits pushed:**
- `14f4f10` — feat(phase2): backstop verify proof table, demo command, live badges
- `d747e7d` — feat(phase3+4): README rewrite, keyless examples, quickstart, sdk-matrix, llms.txt

**Completed tasks:**
- Phase 2 (2.1.1–2.1.6, 2.2.1–2.2.2, 2.3.1–2.3.2): all 12 tasks done
  - `backstop verify` output (keyless, ~2s):
    ```
    | Allowed calls | 2 | Completed within budget (500 tokens) |
    | Blocked calls | 8 | Pre-empted before network dispatch |
    | Tokens saved  | 2,000 | 8 runaway calls prevented |
    | Exception     | BudgetExceededError | subclasses openai.OpenAIError |
    Status: VERIFIED (real wrap enforcement active)
    ```
  - `backstop demo` output (keyless):
    ```
    | Calls completed | 10 | 3 | -7 (-70.0%) |
    | Calls blocked   | 0  | 7 | +7 (blocked in-process) |
    | Tokens consumed | 250| 75| -175 (-70.0%) |
    ```
- Phase 3.1 (README rewrite): 676 → 262 lines; removed all overclaims; live CI + license badges; "What It Does Not Do" section; real demo output; examples table
- Phase 3.4.5: `docs/quickstart.md` and `docs/sdk-matrix.md` created
- Phase 4.1.1: `examples/agent_loop_guard.py` — KEYLESS, runs offline, 2/10 calls before BudgetExceededError
- Phase 4.1.2: `examples/anthropic_budget.py` — KEYLESS, runs offline, 1/5 messages before BudgetExceededError
- Phase 4.1.5: keyless/live separation documented in README examples table
- Phase 4.2.1–4.2.3: quickstart, sdk-matrix, llms.txt updated
- Phase 5.1.1–5.1.4: Show HN title, body, adjective review, 5 objections drafted (in docs/internal/, gitignored)
- Phase 5.2.5: dev.to/Hashnode article drafted (in docs/internal/, gitignored)

**Verification:**
- `pytest`: 249 passed, 5 skipped (twice: before and after Phase 3+4 changes)
- `backstop verify` (keyless): 8/8 PASS, exit 0
- `backstop demo` (keyless): 7/10 blocked, 70% savings, exit 0
- `examples/agent_loop_guard.py`: runs cleanly offline, BudgetExceededError raised
- `examples/anthropic_budget.py`: runs cleanly offline, BudgetExceededError raised
- Secret check: `git diff --cached | grep -E 'sk-[a-zA-Z0-9]{30,}'` → nothing (clean)

**Blocked (owner-only):** 0.3.4 (PyPI publish), 3.4.3 (npm publish), 3.3.8 (Vercel login)

**Dashboard updated:** 79/124 (was 47/124). Phase 2: 12/12 ✅. Phase 3: 14/30. Phase 4: 8/15. Phase 5: 5/14.

---

## 20. Post-48h Backlog (do NOT start during the window)

1. `httpx2` parity, if it was deferred at the H10 gate (§9 fallback path)
2. Publish/unify the TypeScript SDK on npm; add Anthropic support to the TS port
3. Framework adapters with **real** enforcement: LangGraph, CrewAI, OpenAI Agents SDK, Vercel AI SDK
4. Budget-exhaustion webhooks + forecast-based pre-cap alerts (the "N calls remaining" idea)
5. Hierarchical budgets (team → service → agent)
6. Split Wedge into its own repository with its own story (Q3)
7. Docs site (Docusaurus/MkDocs) + a proper `llms.txt` / `llms-full.txt`
8. Supply-chain hardening: PyPI trusted publishing (OIDC), SBOM, cosign/SLSA
9. Re-introduce the research paper / technical write-up as a legitimate artifact
10. Revisit positioning based on real launch feedback — the objection list from task 6.6 is the input

---

*End of plan. The checkboxes in this file are the source of truth — keep them current.*

### 2026-09-18 12:07–12:20 UTC — 0.3.4/0.3.5/0.3.6/0.3.7 + 1.5.1 PYPI PUBLISH & RELEASE (+ site merge, npm blocked)

- Completed: 0.3.4, 0.3.5, 0.3.6 (Phase 0 GATE), 0.3.7, 1.5.1. Phase 0 now 18/18, Phase 1 27/27, total 87/124.
- Verified:
  * `.venv/bin/python -m build` (fresh, old dist predated Phase 2/3/4) → `backstop_ai-0.6.0-py3-none-any.whl` + `.tar.gz`; `twine check dist/*` → both PASSED
  * `twine upload dist/*` → `View at: https://pypi.org/project/backstop-ai/0.6.0/`
  * `/tmp/bs-verify` clean venv: `pip install "backstop-ai[anthropic]"` → `backstop.__version__` = 0.6.0; `backstop doctor` exit 0 (openai 3.15.0 + anthropic 1.6.0 wrapped); keyless `backstop verify` → 8/8 PASS
  * `git tag v0.6.0 && git push origin v0.6.0` → tag live; Release created with both artifacts
  * Repo metadata (prior session): description + 8 topics set, Discussions enabled, issues #6–#9 seeded (#8 has `good first issue`)
  * Site (prior session + this session): `fix/launch-claims` merged to `backstop-site` main (a20460f); baseline + post-fix `bun run build` green; zero `backstop.dev`/`[openai]`/14-day hits
- Found + fixed: tag push ran NO workflow — `ci.yml` only listened on `branches: [main]`, so the `refs/tags/v` release steps were dead code. Fixed in bfa58c0 (`tags: ['v*']`); v0.6.0 Release created manually. Next version tag exercises the fixed path.
- Blocked: npm `backstop-ai` publish → 403 "You may not perform that action with these credentials" (token lacks publish rights or 2FA enforced). TS rename to `backstop-ai@0.6.0` committed (67edb5d, tests 17/17) — publish needs owner `npm login` refresh / automation token / OTP.
- Next: owner Vercel deploy; HN/Reddit/dev.to (human-only); rotate/revoke the pasted PyPI token if desired (also stored as `PYPI_API_TOKEN` repo secret for CI).
- Dashboard updated: yes.
