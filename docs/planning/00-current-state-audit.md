# 00 — Current-state audit

Branch `feat/ledger-foundation`. Base commit `c65e8b1`. Head at time of writing
`39cb7f9`.

This document has two parts. PART A audits the tree **as it stood before this
build** and is grounded in the code at `c65e8b1` and in the task reports under
`.superpowers/sdd/_build-plan/`. PART B records what this build changed, with a
fix commit and a regression test for each change.

Every claim below cites a path and a line number, or a report, or is labelled
HYPOTHESIS. No number in this document was invented.

---

## Baseline

| | value | source |
|---|---|---|
| baseline suite, at `c65e8b1` | **246 passed, 8 skipped** | measured, `git stash`-verified, `.superpowers/sdd/_build-plan/task-1-report.md:253-265`; recorded in `progress.md:5-7` |
| suite at `39cb7f9` | **1214 passed, 9 skipped** in 78.8 s | measured just now, 1223 collected |
| delta | +968 passing, +1 skip, 0 lost, 0 un-skipped | 81 commits, `git diff --stat c65e8b1..HEAD` = 59 files, +19,072 / −274 |
| new test files | 10 | `git diff --name-status c65e8b1..HEAD \| grep '^A' \| grep tests` |
| test cases in those 10 files | 868 | per-file `pytest --collect-only` counts, see below |

Per-file collected counts for the new test modules:

| file | collected |
|---|---:|
| `tests/test_ledger_schema.py` | 348 |
| `tests/test_pricing_catalog.py` | 138 |
| `tests/test_ledger_sink.py` | 45 |
| `tests/test_ledger_export.py` | 51 |
| `tests/test_detection.py` | 210 |
| `tests/test_detection_observability.py` | 10 |
| `tests/test_ledger_transport.py` | 46 |
| `tests/test_ledger_state.py` | 16 |
| `tests/test_admission_gate.py` | 4 (Task 1b) |
| `tests/test_doctor.py` | 4 (Task 1c) |

The remaining ~100 of the 968 are extensions to pre-existing files
(`test_verify.py` +202 lines, `test_streaming_budget.py` +132,
`test_budget.py`, `test_deep_research.py`, `test_config.py` +10,
`test_extract.py` +9, `test_cli.py` +18, `test_telemetry.py` +42).

### The skip list, verbatim

```
SKIPPED [1] tests/test_deep_research.py:489: could not import 'fastapi'
SKIPPED [1] tests/test_doctor.py:79: httpx2 not installed in this environment
SKIPPED [2] tests/test_real_anthropic.py:11,36: set ANTHROPIC_API_KEY
SKIPPED [2] tests/test_real_openai.py:15,28: provider key is not set
SKIPPED [3] tests/test_transport.py:183,206,215: httpx2 not installed
```

So: 4 skips are missing provider keys (by design, opt-in), **2 are missing
optional packages** — `fastapi` (1) and `httpx2` (1 in `test_transport.py`
x3). Those two packages are extras; `.github/workflows/ci.yml` installs only
`.[test,metrics,anthropic]`, so CI never skips them (`docs/sdk-matrix.md:37-41`).
The one extra skip versus baseline is
`tests/test_doctor.py::test_doctor_httpx2_branch_is_not_silently_skipped`, which
skips for the same reason the three pre-existing `httpx2` skips do
(`task-1c-report.md:196-202`).

### Correction: the initial audit reported the wrong baseline

The first pass of this audit reported the baseline as **"254 passed, 6
skipped"**, taken from the build plan's own Definition-of-Done line
(`docs/planning/_build-plan.md:54`) and inferred from a truncated output tail.
That was wrong. The measured baseline in this environment is **246 passed, 8
skipped**, and the two additional skips are `fastapi` and `httpx2` not being
installed here, not a code difference. This is recorded in `progress.md:5-7` and
`task-1-report.md:253-265, 310-313`.

The corrected number is the one that goes in the Definition of Done. An audit
that hides its own errors is not an audit.

---

# PART A — the audit as it stood BEFORE this build

## A1. What was genuinely finished and tested

| area | evidence | verdict |
|---|---|---|
| Transport interception | `src/backstop/transports.py` (1,520 lines today; 1,048 at `c65e8b1`), both sync and async, with the sync/async pair deliberately near-duplicate | finished, tested |
| Budget enforcement | `src/backstop/budget.py`, `src/backstop/ledger.py` (`BudgetLedger`, `TenantBudget`, `ReservationTicket`) | finished, tested |
| Circuit, retry, AIMD, cache, admission, quotas, agent guard, forecasts, metrics, telemetry, dashboard, harness, gateway, real-provider probes | all present at `c65e8b1`, all named in `docs/compatibility.md:71-92` | finished; existence is proven, CI coverage is not (see A2) |
| The one-wrap-call adoption property | `Backstop.wrap(client, budget=...)`, `src/backstop/wrapper.py` | held at `c65e8b1` and still holds (`test_one_wrap_call_still_works_with_the_ledger_off`) |
| `backstop verify` | 8 checks, exits 0, offline, keyless. Confirmed by me just now | finished, 8/8 PASS |
| `backstop demo` | exits 0 | finished |
| CI matrix | 12 combinations + 1 `latest` cross-check row, `ubuntu-latest` only, Python 3.10/3.11/3.12 x openai 2.37.0/3.14.0 x anthropic 0.99.0/1.6.0 (`docs/sdk-matrix.md:19-30`) | finished for what it covers; see A2 for what it does not |
| SDK family detection | `src/backstop/_httpcompat.py` picks `httpx` or `httpx2` from the wrapped client's own HTTP client | finished, correct, already at `c65e8b1` |

## A2. What was stubbed, detached, or claimed-but-missing

Each of these was verified by reading the tree at `c65e8b1` and grepping, not
inferred from a report.

| # | finding | evidence | what it means for a user |
|---|---|---|---|
| A2.1 | **Hierarchical budgets are not wired to the transport.** | `src/backstop/hierarchical.py` (167 lines) defines `HierarchicalBudgetTree`. `grep -c HierarchicalBudgetTree src/backstop/transports.py` = **0**. The only non-test consumer at `c65e8b1` was `src/backstop/verify.py:462` (`:520` today), which constructs the tree and drives it **directly**, never through `Backstop.wrap()`. | `README.md:192` still lists `Hierarchical budgets \| Parent budget caps all child agents` under *What It Enforces*. It is not enforced on any request. The `[PASS] hierarchical budgets` line `backstop verify` prints proves the standalone module's invariant, not that a wrapped request is subject to it. |
| A2.2 | **Four audit sinks are unreachable from the product.** | `src/backstop/audit_sink.py:69,92,136,193` define `FileAuditSink`, `S3AuditSink`, `BigQueryAuditSink`, `VectorAuditSink`. `grep -rn 'S3AuditSink\|BigQueryAuditSink\|VectorAuditSink\|FileAuditSink' src/` matches only their own definitions. Only `tests/test_audit_sink.py:45,60,65,70` constructs them. `BackstopConfig.audit_sink` (`config.py:122`) is a `str \| callable` that `AuditLog` handles directly (`state.py:166`). | 212 lines of sink code, 4 tests, zero product path. A user reading the module docstring ("concrete sinks: local NDJSON, S3, BigQuery, Vector/OTel") would reasonably believe setting it up is a config exercise. |
| A2.3 | **`CanaryRouter` is dead.** | `src/backstop/rollout.py:98` defines `CanaryRouter.route`. The only consumer is `tests/test_deep_research.py:139`. `transports.py:460,1010` import `ShadowCollector` from the same module and never `CanaryRouter`. | A tested class with no request path. `docs/compatibility.md:91` lists `Shadow / canary rollout \| Supported`; the shadow half is real, the canary half is not. |
| A2.4 | **`log_json` / `log_sink` have no consumer.** | `config.py:164-165` declare them; `config.py:288-289` validate them (`log_json requires log_sink`). `grep -rn 'log_json' src/` returns those three lines and nothing else. | Setting `log_json=True` with a valid sink validates and then does nothing. There is no warning and no error. |
| A2.5 | **The default secret provider is silently dead.** | `config.py:44` declares `@dataclass(frozen=True)`. `config.py:366-370` does `if self.secret_provider is None: try: ... self.secret_provider = SecretProviderChain(...) except Exception: pass`. The assignment raises `FrozenInstanceError`; the bare `except Exception: pass` swallows it. | **I measured this.** `BackstopConfig(virtual_keys={'vk-1':'tenant_1'}).secret_provider` is `None`. `transports.py:984` then early-returns from `_resolve_secret` whenever `cfg.secret_provider is None`, so neither `BACKSTOP_API_KEY_VK_1` nor the literal `virtual_keys` mapping ever rewrites `Authorization`. End to end: with `BACKSTOP_API_KEY_VK_1=sk-derived-from-env` exported and the request carrying `Authorization: Bearer placeholder`, the header came out **unchanged**. A deployment that configures virtual keys believes it has per-key credentials and does not. **This build did not fix it** (see the open list in PART B). |
| A2.6 | **The TypeScript port had drifted into a different architecture.** | `ts/backstop/src/types.ts:1` declares `Priority = "critical" \| "high" \| "default" \| "low" \| "bulk"` — **five** values, against Python's three (`config.py:30-32`: `critical`, `default`, `background`). `ts/backstop/src/wrap.ts:108` lets `critical` **and** `high` bypass the budget ceiling outright; Python's budget has no such bypass (`grep -n critical src/backstop/transports.py src/backstop/budget.py` returns nothing in the budget path). Interception is `client.chat.completions.create` patching (`wrap.ts:96`), not transport injection. | 989 lines of TS source against 10,558 lines of Python source at `c65e8b1` (`task-2-report.md:102-106`); today 1,233 against 19,176 including `src/wedge`. It ships on npm under the **same name** as the Python distribution, at the same version `0.6.0` (`ts/backstop/package.json:2-3`). `.github/workflows/ci.yml` is Python-only, so `npm test` runs only by hand. Two test files, 244 lines. A user who `npm install backstop-ai` gets different priority semantics, a budget-bypass rule that does not exist in Python, and no ledger, no detector, no Anthropic. |
| A2.7 | **Tracked dead files, one of them dangerous.** | `git ls-files` shows `src/backstop/wrapper.py.backup`, `src/backstop/wrapper.py.backup2`, `fix_wrapper.py` and a zero-byte `=0.40` (a shell redirect artifact). `fix_wrapper.py:9-20` is a one-shot codemod whose entire purpose is to **remove `max_retries=0`** from `wrapper.py` — the exact opposite of the design `docs/architecture.md:12-19` now documents. | Anyone who runs `python fix_wrapper.py` silently reverts the retry ownership that the whole guardrail argument rests on, and no test would fail loudly. |
| A2.8 | **CI proves much less than the tables implied.** | `.github/workflows/ci.yml` installs `.[test,metrics,anthropic]` only. No lint, no typecheck, no coverage threshold, no TypeScript, no non-ubuntu OS, no `redis`/`otel`/`fastapi`/`tokenizers` extra. `docs/benchmarks.md:36-55` (written in this build) says the benchmark step has no threshold, so overhead tripling does not fail the build. | A green badge is not a performance gate, not a lint gate and not a coverage gate. |

## A3. Correctness defects found before this build

Seven defects. Each is stated with the file and line at `c65e8b1`, the symptom a
user would see, and the status. Sources: `task-1-report.md` (1a-1e plus the
review round I1-I6, M6-M9), `task-1c-report.md` (three CLI/example defects),
`task-6-report.md:278-308` (the gauge bug).

| # | defect | symptom | where at `c65e8b1` | status |
|---|---|---|---|---|
| D1 | **Anthropic live probe sent the OpenAI credential to Anthropic.** | `backstop verify --live --provider anthropic` with both keys set transmitted `OPENAI_API_KEY` in an `Authorization: Bearer` header to `api.anthropic.com`. A key disclosure across a provider boundary, from a command a user runs precisely to check their install. | `cli.py:369` `--api-key-env` default `"OPENAI_API_KEY"`; `verify.py:77` and `:689` same default; `verify.py:546` reads it. | **Fixed** `44d2ec6`, plus the header shape `2a083c1` (it also sent `Bearer` where Anthropic expects `x-api-key` + `anthropic-version`), plus a stderr warning when `--base-url` points off-provider `87ac722`. |
| D2 | **Priority-gate ticket leak on timeout.** | One acquirer that hit `queue_timeout` left its ticket in the priority deque. `_choose_ticket` (`admission.py:127-145`) only ever reads deque heads, so that ticket was reselected forever and **every later acquirer at that priority timed out** — a permanent head-of-line block for that priority. Confirmed with a scratch script: after one timeout, `gate.release()` did not help and a third acquirer also raised. | `admission.py:45-59` (sync), `:66-82` (async): `raise TimeoutError` leaves the ticket in `self._queues[priority]`. | **Fixed** `50bcbe1` (`try/finally` + identity-based `_discard`), then `724ea7b` after review found a survivor queued behind a discarded ticket slept on and never woke. |
| D3 | **Streaming left the circuit breaker in half-open.** | After a 503 opened the circuit, a *successful* stream never released the half-open probe, so the next request was rejected with `CircuitBreakerOpenError` indefinitely. A streaming 503 also never opened the circuit, so the symptom was invisible in the common case. | `transports.py:312-322` (sync streaming branch) never called `_record_outcome`; the async twin at the equivalent branch likewise. Only the non-streaming branch called it (`:332`). | **Fixed** `3ddcf4b`, sync and async, recorded at stream setup, not consumption. |
| D4 | **Async transport skipped pre-admission checks.** | `rate_limiter`, `agent_guard` and `shadow_policy` were **not enforced for async clients at all**. A user with an agent guard on an `AsyncOpenAI` client had no guard. | `_pre_admit_checks` was *defined* at `transports.py:935` (async class) but *called* only at `:274` (sync). | **Fixed** `cbb57db`, one line at the equivalent point in the async path. Side effect: the repo's ruff error count dropped 35 → 33, because the async class import that had been sitting unused in `tests/test_deep_research.py:22` finally had a use. |
| D5 | **Blocking Redis reconcile on the event loop.** | With `shared_budget=True` and the `redis` extra, a synchronous Redis round trip ran on the event loop on every request. The async path called the *sync* reconcile helper. | `Budget.areconcile` existed at `budget.py:73` and was called by **nothing** (`grep -c areconcile src/backstop/transports.py` = 0 at base). The async transport called sync `_reconcile` at `:800,847,852,893`. `state_backends.py:38-42` did `await asyncio.to_thread(self.reserve/commit, ...)` for both reserve and commit, including the pure in-memory backend. | **Fixed** `2bf9a0f` (new `_areconcile`, four call sites, and `InMemoryBudgetBackend.acommit` committing inline), then `0a8e3d3` for the symmetric `areserve` hop. The `to_thread` hop is now confined to `RedisBudgetBackend`, the one place it does real work. |
| D6 | **Pre-admission denial leaked the budget reservation.** | A request denied by `rate_limiter` / `agent_guard` / `shadow_policy` raised *after* the budget had reserved against it, and the reservation was never returned. Every denial permanently consumed budget. Measured: three denials left `reserved=50/100/150` with `remaining` walking down `950/900/850`. | `transports.py:274` calls `_pre_admit_checks` outside the `try` that reconciles; no handler covered it. | **Fixed** `53c8925`, both paths, in Task 1's review round (I2). |
| D7 | **`_observe_gauges` re-read the ContextVar instead of the resolved tenant.** | Every request authenticated by a virtual key published the **global** `budget_remaining` gauge instead of that tenant's. Dashboards and alerts showed a healthy global budget while a tenant was exhausted. | `handle_request` resolved `tenant_id` from the context *or* the `X-Backstop-Key` header (`transports.py:508-512`) and budgeted against it; `_observe_gauges` at `transports.py:576-577` and `:1037-1038` independently re-read `get_current_tenant()`, which only ever knows the ambient case. The failing assertion read `assert 5000 == 850` (`task-6-report.md:296-303`). | **Fixed** `eb9f7e3`: `_observe_gauges(circuit, tenant_id)` and `_observe_queue(wait, priority, tenant_id)` now take the resolved tenant. A no-tenant test pins the unchanged case so the fix cannot quietly become "always report a tenant". |
| D8 | **`backstop doctor` exited 1 on a base install.** | `httpx2` is not a declared dependency (`pyproject.toml:24` declares `httpx>=0.27` only) but `cli.py:189` imported it unconditionally inside the wrap smoke test. On any install resolving to the older SDK family, `doctor` printed `ModuleNotFoundError: No module named 'httpx2'` and returned 1 even though both clients wrapped fine. | `cli.py:189` | **Fixed** `4b284bb`, by branching on the `_httpcompat.HTTPX2` flag the module already computes. No dependency added. |
| D9 | **`backstop verify --offline` was inert.** | A user who explicitly asked for no network still got a live `GET /v1/models` carrying their credential, because argparse accepted `--live --offline` together and the dispatch read only `args.live`. | `cli.py:362-363` declared both as plain flags; `cli.py:480` passed only `live=args.live`. | **Fixed** `5923d3c`, by making them an argparse mutually exclusive group. |
| D10 | **An example claimed behaviour the code does not have.** | `examples/background_priority.py:4` docstring: "Critical requests pass through when background requests are shed under load." Nothing is shed. | `examples/background_priority.py:4` | **Fixed** `88f66dd`, docstring only. Proved comment-only: the executable AST is byte-identical. |

## A4. Table of every README claim that overstated the code

Pre-build README is `git show c65e8b1:README.md`, 262 lines. Line numbers in the
left column are lines of that file. "What the code did" is what I read at
`c65e8b1`.

| # | claim | what the code actually did | fixed in |
|---|---|---|---|
| R1 | `:31` `~0.09 ms p50` in the comparison table; `:214-216` "Measured on a MacBook M1 with openai 3.14 + httpx 0.28" | No artifact in the repo records that host, OS, Python version or SDK version. The one committed snapshot (`docs/benchmark-results-2026-07-20.md`) records 0.07 ms and records no host at all. A plausible, unreproducible number. | `61f2650` |
| R2 | `:81` "> **0.6.0 is unreleased.** Until published on PyPI, install from source" | 0.6.0 was on PyPI, on npm and as the `v0.6.0` GitHub Release (`task-2-report.md:48-53`; the same false banner was in `CHANGELOG.md`, `docs/install.md`, `docs/compatibility.md`, `install.sh` and `llms.txt`). | `121261a`, `3aa91b7` |
| R3 | `:122` "That's the whole integration. No proxy, no call-site changes beyond the wrap." | `backstop serve` ships an OpenAI-compatible reverse proxy (`src/backstop/gateway.py`, 117 lines). The sentence was true of `wrap()` and false of the package. | `a4c8b30` |
| R4 | `:159` `Priority admission \| critical requests pass when normal ones are shed` | There is no `normal` priority — `config.py:30-32` is `critical` / `default` / `background`. And nothing is shed: `admission.py:127-145` `_choose_ticket` **selects** (it reads only `queue[0]`), never cancels or discards. Two false claims in one cell. | `a4c8b30`; the same claim in `examples/background_priority.py` fixed separately in `88f66dd` |
| R5 | `:167` "**Not a proxy.** No network traffic passes through Backstop; requests go directly to the provider." | True of `wrap()`, false of the package (R3). | `a4c8b30` |
| R6 | `:168` "**Not a control plane.** No central server, no key management, no multi-tenant routing." | The first clause is true. The other two are not: `config.py:137-138` `virtual_keys` / `virtual_key_header` map a caller-supplied key to a tenant id, `config.py:155` `secret_provider` resolves keys to provider secrets, and `shared_budget` + the `redis` extra gives cross-replica budgets. | `a4c8b30` |
| R7 | `:225` "All examples in `examples/` that work offline are marked with a `# KEYLESS` header." | Only 2 of 13 files carry the header. `budget_blocking_demo.py` and `prometheus_metrics.py` also run with no key and no network. The table listed 9 files; 13 exist. | `a4c8b30` |
| R8 | architecture section: "replaces the SDK's internal `httpx` transport" and "The SDK's own retry and auth logic runs above the transport" | The family is `httpx` **or** `httpx2` depending on the SDK major (`_httpcompat.py:19-26`). And wrapping sets `max_retries=0`, so Backstop performs the retries, not the SDK (`wrapper.py`; `docs/architecture.md:12-19` now says so). The *auth* part of that sentence was true and was kept. | `a4c8b30` |
| R9 | the `backstop verify` "Expected output" block | It quoted a hand-trimmed subset with no `## Mechanism Checks` section, so it was not a real run of the command. | `a4c8b30` |
| R10 | the first usage snippet caught `BudgetExceededError` with no import | `NameError` on the first `except`. | `a4c8b30` |
| R11 | `docs/benchmarks.md` said the scenario counts "are deterministic and match the snapshot exactly" | Eight runs on one host: `budget-hit` flipped between 16/16/64 and 18/18/62, and `error-storm` reported 12/8/42 against the recorded 15/11/39. The seed fixes the input *sequence*, not the outcome of a wall-clock-timer path. | `138ca36` |
| R12 | `docs/compatibility.md` provider table claimed anthropic `0.99.0, 1.5.0, 1.6.0, latest` and openai `latest` "Verified" | The CI matrix pins 0.99.0 and 1.6.0 only; anthropic `latest` is not tracked at all; 1.5.0 is a developer-machine observation from `tests/test_guardrail_visibility.py`. | `9c8c37a` |
| R13 | `docs/concurrency.md` "they spend ~99% of their time awaiting the model API" | Not measured anywhere in the repo. A precise-sounding unverified number. | `a500259` |
| R14 | `docs/architecture.md` "Control Plane Direction" read as a plan of what exists | It opened with a list that does not exist. It now opens "Nothing in this section exists today". | `a500259` |

### Claims that survived the audit because they were true

Listed so the table above is not read as "everything the README said was false".
`task-2-report.md:415-450` re-verified each of these by running it:

- `Retry + backoff | Configurable exponential backoff with jitter` — real, `retry.py:12-16` returns `random.uniform(0.0, cap)`.
- `docs/architecture.md`'s tenant-budget snippet — all three names exist and the snippet runs.
- `Redis operations use atomic Lua scripts` — real, `state_backends.py:192,196` (`evalsha`).
- `BackstopConfig is immutable after construction` — real, `@dataclass(frozen=True)`, `config.py:44`. (It is also exactly why `config.py:366-370` is broken; see A2.5.)
- `Hierarchical budgets | Parent budget caps all child agents` — the *module* is correct and tested. The claim is wrong only about it being enforced on a request. Recorded in A2.1 rather than here.

---

# PART B — what this build changed

81 commits, `c65e8b1..39cb7f9`.

## B1. Correctness defects, fixed

| defect | symptom a user saw | fix commit | regression test |
|---|---|---|---|
| Anthropic live probe sent the OpenAI key | OpenAI credential transmitted to `api.anthropic.com` | `44d2ec6` | `tests/test_verify.py::test_live_probe_never_sends_the_other_providers_key` — no-network end-to-end, asserts the recorded `(base_url, headers)` pair |
| …and the argparse default had no coverage | same leak, unguarded at the CLI layer | `8be8151` (test-only) | `tests/test_verify.py::test_cli_verify_live_never_sends_the_other_providers_key` |
| Anthropic probe used the wrong auth header | 401 on every live anthropic probe | `2a083c1` | `test_live_probe_uses_x_api_key_for_anthropic`, `test_live_probe_uses_bearer_auth_for_openai` |
| `--base-url` sent the provider key to any host, silently | credential sent to a third-party host with no warning | `87ac722` | `test_custom_base_url_warns_before_sending_the_credential`, `test_default_base_url_does_not_warn` |
| Priority-gate ticket leak on timeout | permanent head-of-line block per priority | `50bcbe1` | `tests/test_admission_gate.py::test_sync_timeout_does_not_wedge_the_priority_queue` (+ async) |
| …and a survivor behind a discarded ticket slept on | a request queued behind a doomed ticket never woke | `724ea7b` | `test_discarded_ticket_wakes_the_survivor_queued_behind_it` (+ async) |
| Streaming left the circuit half-open | after one 503, every later request rejected `CircuitBreakerOpenError` | `3ddcf4b` | `tests/test_streaming_budget.py::test_successful_stream_releases_the_half_open_probe` (+ async) |
| …and a failed stream did not reopen it | a bad stream left the probe cleared | `3ddcf4b` | `test_failed_stream_reopens_the_circuit`, `d38744c` added the async twin |
| Async transport skipped pre-admission checks | `rate_limiter`, `agent_guard`, `shadow_policy` unenforced for async clients | `cbb57db` | `tests/test_deep_research.py::test_async_agent_guard_denies_request`, `..._rate_limiter_...`, `..._shadow_policy_...` |
| Pre-admission denial leaked the reservation | each denial permanently consumed budget (`remaining` 950/900/850) | `53c8925` | `test_sync_pre_admission_denial_releases_the_reservation` (+ async) |
| Blocking Redis reconcile on the event loop | sync Redis I/O on the event loop per request | `2bf9a0f` | `tests/test_budget.py::test_async_transport_reconciles_through_the_async_backend_path`, `test_in_memory_acommit_stays_on_the_event_loop` |
| …and the symmetric `areserve` hop | pure-overhead `to_thread` on the in-memory backend | `0a8e3d3` | `test_in_memory_areserve_stays_on_the_event_loop` |
| `_observe_gauges` reported the global budget for a virtual-key request | dashboards showed a healthy global budget while a tenant was exhausted | `eb9f7e3` | `tests/test_ledger_transport.py::test_the_budget_gauge_reports_the_virtual_key_tenant_not_the_global` (+ async), plus the no-tenant guard |
| `backstop doctor` exited 1 on a base install | `ModuleNotFoundError: httpx2`, exit 1, healthy install | `4b284bb` | `tests/test_doctor.py::test_doctor_exits_zero_without_httpx2` and two more |
| `backstop verify --offline` was inert | explicit "no network" still sent a credential | `5923d3c` | `test_cli_verify_rejects_live_and_offline_together`, plus the two controls |
| An example claimed shedding | a doc claim the code contradicts | `88f66dd` | none, proved comment-only by AST comparison |
| OpenAI's cached prompt tokens were never read | every OpenAI prompt-cache request recorded `cache_read_tokens=0` and was charged the full input rate | `d291fef` | `tests/test_extract.py` (6) + `test_ledger_transport.py` (2); the measured effect on a 1,234,567-token prompt with 400,000 cached is **3.091418 → 2.591418**, 14.3% lower |
| A process-global `decimal` context silently destroyed the ledger | with `prec=6` set by a host app, `compute_cost` raised on *every* event: 200 returned, `ledger_errors` climbing once per request, **zero events recorded**, no explanation. All three `backstop ledger` subcommands died with a bare `InvalidOperation`. | `d74f0e7`, `a9218af` | 4 in `test_pricing_catalog.py`, 1 in `test_ledger_transport.py`, 3 in `test_ledger_export.py`, 3 in `test_cli.py`. The fix installs an explicit 28-digit context named in full (`prec`, `rounding`, `Emin`, `Emax`, `capitals`, `clamp`, `flags`, `traps`). Not one expected number in the suite changed. |
| `CloseReport.lost` said 0 for a ledger that lost everything | 50 events into a `JsonlSink` whose path can never be opened reported `submitted=50 written=50 dropped=0 sink_errors=0 lost=0`, against a docstring promising "events that will never be written" | `03ef263` | 5 in `test_ledger_sink.py`; the reviewer's exact scenario asserting `lost == 50`, `landed == 0`, `sink_reported_errors == 50` |
| The share was printed beside different dollars | `1.54 / 34.56` is 4.46%; the report printed 4.45% (and on a small report, 6.67% against a printed 4.29%) | `cdd51e8` | 2 in `test_ledger_export.py`, asserting the disclosure is *necessary*, not merely present |
| A Decimal dollar printed as six-place money | `cost_velocity_usd_per_min` is floats; rendering it at 6 dp printed a **wrong digit** (0.617283 for 0.617284) | `d51c157` | 1 in `test_detection.py` |
| `estimated_requests` and `unpriced_requests` had different denominators | two honesty columns counting different populations, inviting a reader to add them | `8d32ede` | 2 in `test_ledger_export.py` |
| `price_unknown` was documented as a counter that exists nowhere | two docstrings pointing at a mechanism that was never built | `ddaba66` | 2 in `test_pricing_catalog.py`, one of which walks the package for any docstring promising a counter it does not have |
| The detection key count grew with the request count | unbounded memory for a high-cardinality attribution | `c156d58` | 11 in `test_detection.py`, including 5,000 requests with 5,000 distinct attributions staying at 64 keys with 4,936 counted evictions |
| `state.ledger` was never closed | a file handle and a daemon thread with no release point | `24c0773` | 7 tests asserting on `threading.enumerate`, not on the writer's own flag |
| A detection-only deployment allocated a ring nothing could write to | 10,000 slots, never filled | `45d0a9f` | 1 in `test_ledger_state.py` |
| A telemetry latency histogram swallowed detection magnitudes | a signal's observed value read as request milliseconds | `ae1c39f` | 9 in `tests/test_detection_observability.py` |
| Detection thresholds were frozen; signals went nowhere | six frozen defaults, and a computed signal list nobody received | `4871f8b`, `ae1c39f` | 9-row parametrised reachability table plus 9 observability tests, including one that reads the knobs back off the detector the state actually holds |
| Endpoint normalisation was not idempotent | `from_dict(to_dict(e)) != e` for any endpoint with a query string; a JSONL line was not byte-stable across cycles | `a228fcf` | 27 adversarial endpoints through idempotence and round-trip tests |
| `Attribution` fields were unvalidated | `Attribution(team=1)` constructed, then raised a bare `AttributeError` out of `keys()` | `f42e8fd` | 13 fields x 5 bad values |
| An async generator or a coroutine-returning function escaped attribution | a decorated function's body ran after the scope was restored, so events landed unattributed | `aa8d22a` + Task 3 round 2 | 8 tests, including `inspect.CORO_CLOSED` on the discarded object |
| A `ledger.py` module and a `ledger/` package would have shadowed each other | CPython's `FileFinder` checks directories first, so `from backstop.ledger import TenantBudget` would have raised | `195224b` | `tests/test_ledger_schema.py` re-exports; `grep -rn _budget_ledger src/ tests/` returns nothing |

## B2. What was added

| area | what | where |
|---|---|---|
| Spend event schema | frozen `SpendEvent`, 18 wire fields, 13-field `Attribution`, `merge`, full type + value validation in `__post_init__`, strict wire round trip that refuses both unknown and missing keys | `src/backstop/ledger/schema.py` (596 lines) |
| Attribution context | `attribution(**fields)` context manager, `with_attribution(**fields)` decorator (sync, async, refuses deferred bodies), `current_attribution()`; one `ContextVar`; nesting merges, restores on raise | `src/backstop/ledger/context.py` (217 lines) |
| Price catalog | 45 bundled entries (29 openai, 16 anthropic), 3-tier precedence (override > user > bundled) resolved **layer-major**, 3-tier model-name normalisation, `Decimal` money at exactly 6 dp under an explicit context, `priced_components` as the coverage field, no float ever on the wire | `src/backstop/pricing_catalog.py` (1,061 lines) |
| Sinks | `LedgerSink` protocol, `NullSink`, `MemorySink`, `JsonlSink`, and `BoundedWriter` draining from one named daemon thread | `src/backstop/ledger/sink.py` (732 lines) |
| Chargeback export | `build_chargeback`, 13 columns + group keys, `unpriced_requests` / `estimated_requests` / `unpriced_components`, `revenue_join`, three CSV writers, the JSONL reader with its torn-write and corruption policy, `delivery_report` | `src/backstop/ledger/export.py` (1,753 lines) |
| Deterministic demo | 1,967 synthetic events, fixed day, no clock, byte-identical across runs | `src/backstop/ledger/demo.py` (582 lines) |
| Transport wiring | one function both transports call, gated on `ledger_enabled or detection_enabled`; three insertion points each (streaming, non-streaming, fallback) | `src/backstop/transports.py:195,231` |
| Runaway-spend detection | four detectors, report-only by design, shadow by default, LRU key bound, three instruments | `src/backstop/detection/` (1,165 lines) |
| CLI | `backstop ledger demo \| show \| export` | `src/backstop/cli.py` |
| Truthfulness pass | 12 doc files + `install.sh` + `llms.txt` | commits `121261a` .. `138ca36` |

### Measured cost, quoted from the reports rather than re-measured

| path | figure | source |
|---|---|---|
| Ledger **off** (the default), vs the pre-task tree | **+3 to +5 us p50, about +2 to +3%**; p95 and p99 deltas inside the noise | `task-6-report.md:322-334` (two independent 14-run alternating pairings) |
| Ledger **on** | **+130.0 us p50, +253.4 us p95, +335.1 us p99** — p50 is +84.6% | `task-6-report.md:348-353` |
| Where the 130 us goes | `SpendEvent()` 50.5, `compute_cost` 24.2, `submit` 3.7, GIL lost waking the drain thread ~35-40, `detector.observe` +36.5 (detection on) | `task-6-report.md:363-376` |
| In-situ vs tight-loop | the same function measures **3-5x** higher in situ than in a warmed micro-benchmark | `task-6-report.md:378-386` |
| `submit` against a stalled sink | 0.841 / 0.851 / 1.04 us per submit (min/median/max) over 10,000 submits | `task-5-report.md:167-169` |
| `NullSink.write` vs `MemorySink.write` | 39.5 ns vs 267.9 ns (6.8x) | `task-5-report.md:177-179` |
| `detector.observe` | 0.14 us disabled (the default), 14.0 us enabled and healthy, 25.2 us firing | `task-8-report.md:136-142` |
| `backstop ledger demo` | 1.67-2.07 s wall clock, ~82 MB RSS, 1,967 events, exit 0, no key, no network, byte-identical across runs | measured just now; byte-identity asserted in `tests/test_ledger_export.py` |

**The load-bearing ruling** (`progress.md:100-108`): the ledger-ON cost is
**accepted and documented, not optimised away**. Global Constraint 2 protects
the *default* path, and the default path stays in the sub-millisecond class. The
honest claim is "enforcement is ~0.09 ms; the opt-in ledger is not free and we
publish its cost", never "the ledger is also 0.09 ms".

## B3. The truthfulness pass, in numbers

- 12 documentation files + `install.sh` + `llms.txt` corrected across 8 commits.
- 11 README claims found overstated (R1-R10 plus the expanded example table), 4
  doc claims (R11-R14).
- 1 claim the auditing agent got **wrong mid-task and corrected**: it initially
  wrote that the benchmark scenario counts "are deterministic and match the
  snapshot exactly", reasoning that the seed made them so. Eight runs on one
  host disproved it. That is recorded in `task-2-report.md:452-470` and fixed in
  `138ca36`, and it is the same class of error the task existed to remove.

## B4. Still open at `39cb7f9`

An audit that lists only what was fixed is a press release. These are live.

### Product defects not fixed by this build

| # | finding | evidence | why it was not fixed |
|---|---|---|---|
| O1 | **The default secret provider is still silently dead.** | A2.5. `config.py:44` frozen + `config.py:366-370` bare `except: pass` | It is one line (`object.__setattr__` or drop the default) but it is a pre-existing defect in a frozen dataclass, outside every task's declared surface, and the build plan's Global Constraint 11 forbids unrelated fixes. **It should be Task 1 of the next cycle.** |
| O2 | Hierarchical budgets still not wired to the transport | A2.1 | Pre-existing; not in the plan's scope |
| O3 | The four audit sinks are still unreachable | A2.2 | Pre-existing; `docs/compatibility.md:85` still says "Audit log \| Supported (tamper-evident)", which is true of `AuditLog`, not of `audit_sink.py` |
| O4 | `CanaryRouter` still dead | A2.3 | Pre-existing |
| O5 | `log_json` / `log_sink` still have no consumer | A2.4 | Pre-existing |
| O6 | The dual `threading.Condition` / `asyncio.Condition` race in `admission.py`; the starvation path can sleep past `starvation_after_seconds` when `queue_timeout=None`; `KeyError` on an out-of-set provider in `_PROVIDER_BASE_URL`; a degenerate `--base-url` raising before its own guard | Parked by ruling, `progress.md:56-61`; `task-1-report.md:330-336, 692-698` | Explicitly parked as "reported, not fixed" |
| O7 | 32 pre-existing ruff findings, and CI has no lint step | `task-8-report.md:699`; `docs/sdk-matrix.md:39` | Pre-existing; no lint gate exists to catch a regression |
| O8 | `src/backstop/state_backends.py` has `if TYPE_CHECKING: pass` while annotating `client: Any \| None`; ruff F821; breaks if the future import is removed | `task-1-report.md:346-349` | Pre-existing |
| O9 | `backstop.budgets` goes stale after `reset_ledger()` | `task-3b-report.md:224-228` | Pre-existing; no test exercises it |

### Cost and data-quality debt accepted, with the reasoning

| # | debt | number | ruling |
|---|---|---|---|
| O10 | Ledger-ON p50 cost, unbatched | ~35-40 us of it is GIL time lost waking the drain thread, the single largest line item | `progress.md:109-110`: "should be batched". Not done. |
| O11 | The bundled Anthropic cache-write rate is the 5-minute tier | 1-hour-TTL deployments under-count cache writes, and because the entry *does* carry a write rate, `priced_components` cannot reveal it | `progress.md:111-112`; `task-4-report.md:441-446`. The schema has one `cache_write_per_mtok_usd` field and Anthropic publishes two. |
| O12 | Streaming chargebacks are a floor, not a measurement | every streaming deployment's `total_usd` is a lower bound | `task-6-report.md:423-431`. The upstream fix is a second event at stream close, which would change the event count per stream. Not done. |
| O13 | `detection_max_keys=1024` | a large multi-tenant deployment loses baselines, quietly by design | `task-8-report.md:706-711`: "a judgement call, not a measurement". |
| O14 | The `atexit` hook covers only interpreter exit | a long-lived process that finishes a job must call `Backstop.close(client)` and nothing reminds it to | `task-8-report.md:712-717` |
| O15 | `ledger.py` → `ledger/` needed a shim, resolved by a rename in Task 3b | the shim would have broken four test files and three modules | `task-3-report.md:40-74`, resolved `195224b` |

### Verification not performed

| # | gap | consequence |
|---|---|---|
| O16 | **No wheel was built.** `hatchling` and `build` are not installed in this environment. | That `backstop/ledger/` ships in the wheel rests on `pyproject.toml:59` `packages = ["src/backstop", "src/wedge"]` and hatchling's documented recursive inclusion — an argument, not a measurement. `task-3-report.md:345-349`, `task-3b-report.md:230-235`. |
| O17 | **No Python 3.10 interpreter here** (only 3.12.3). | 3.10 syntax compatibility is established by AST scan plus CI, not by a local run. `task-3-report.md:350-353`. |
| O18 | **The `httpx2`-present branch of `doctor` has never run.** It skips in every environment that installs from `pyproject.toml`. | Correct by inspection; the guard test would catch its removal if run somewhere with `httpx2` present, and no job does. `task-1c-report.md:301-308`. |
| O19 | **The four optional extras get no CI execution**: `redis`, `otel`, `fastapi`, `tokenizers`. | The distributed-budget, OTel, gateway and tiktoken paths have no automated coverage today. `docs/compatibility.md:94-98`. |

### Documentation debt this build created or left

| # | gap |
|---|---|
| O20 | `docs/ledger.md` **does not exist**. The build plan gates it on Task 7 (`_build-plan.md:162`), which has landed. |
| O21 | `CHANGELOG.md` `## [Unreleased]` has **no ledger or detection entry**. Three new user-visible commands ship unannounced. Global Constraint 8 is unsatisfied. `task-7-report.md:519-524` defers it to Task 10; Task 10 has not run. |
| O22 | `docs/install.md:182-198` still documents the `doctor` httpx2 defect that `4b284bb` fixed, and `docs/install.md:213-215` still documents the inert `--offline` flag that `5923d3c` made a usage error. Flagged at `task-1c-report.md:282-299` and ruled to Task 10 (`progress.md:88-89`). The document is now wrong in the direction of understating the product. |
| O23 | `TODO.md` still shows tasks 4-8 unchecked although they shipped. |
| O24 | `README.md` has no mention of the ledger, the price catalog, or the detector. All three are user-visible and shipped. |

---

## Summary

| | before | after |
|---|---|---|
| suite | 246 passed / 8 skipped | 1214 passed / 9 skipped |
| correctness defects found and fixed | — | 27 distinct (B1) |
| user-visible surfaces added | — | 3 CLI commands, 2 packages (`ledger/`, `detection/`), 1 module (`pricing_catalog.py`) |
| dead or detached code | ≥ 6 items (A2) | 5 items still dead (O1-O5) |
| new doc claims that are unreproducible | 14 (A4) | 0 known |
| unverified-by-construction gaps | 4 (A2.8, O19) | 4 (O16-O19) |
