# 06 — 90-day plan

Branch `feat/ledger-foundation`. Head at time of writing `39cb7f9`. Suite:
**1214 passed, 9 skipped**, measured just now.

**Every day estimate in this document is a HYPOTHESIS.** None of them is a
measurement. They are anchored on two measured facts — the Python ledger half is
6,350 lines and the detection half is 1,165 (`wc -l`), and the build that
produced them took 81 commits — and on the assumption stated in §0.2. If the
assumption is wrong, every number in §3 is wrong with it, and the weeks are
re-orderable in a way the effort figures are not.

---

# 0. Two facts that change the plan as written

## 0.1 0.6.0 is already published. The build plan's first instruction is wrong as written.

`docs/planning/_build-plan.md:381` says `06` "must start with publishing a
corrected release to PyPI, since 0.6.0 already shipped", and
`_build-plan.md:145-147` (Task 2) records that the original instruction was
"start with publish to PyPI" — which is what had to be corrected.

Measured, not asserted:

| | evidence |
|---|---|
| `backstop-ai==0.6.0` is on PyPI | `CHANGELOG.md:21-26`: "`twine upload` put 0.6.0 on PyPI; a clean virtualenv then resolved `backstop-ai[anthropic]` to 0.6.0, with `backstop doctor` and `backstop verify` both succeeding" |
| the `v0.6.0` GitHub Release exists and carries the wheel and sdist | `CHANGELOG.md:23-24`; `git tag` shows `v0.6.0` |
| `backstop-ai@0.6.0` is on npm | `CHANGELOG.md:24-25`; `PLAN.md:968-970` records `npm publish --access public` → `+ backstop-ai@0.6.0` |
| the current tree is unreleased work | `CHANGELOG.md:25-26`: "Work after this tag is unreleased and lands under `## [Unreleased]` below" |
| the release pipeline exists and triggers on a tag | `.github/workflows/ci.yml:6` `tags: ['v*']`, `:76-89` creates the release and publishes to PyPI |
| a recorded past failure of that pipeline | `PLAN.md:957`: the tag push ran no workflow because `ci.yml` only listened on `branches: [main]`; fixed in `bfa58c0` and "the next version tag exercises the fixed path" |

**So the first week is not "publish to PyPI". The first week is "fix the P0
defects and publish 0.6.1",** because what is on PyPI today is a build with
three new user-visible surfaces, no changelog entry for any of them, and a
silently dead default secret provider. Publishing 0.6.1 with those in it would
be publishing the same problem with a higher version number.

## 0.2 The capacity assumption, stated so it can be wrong

**One person, part-time, 13 weeks.** The plan below is sized at **2.1 days per
week average** — **27.0 days of work** across 13 weeks, which is roughly 17 hours
a week. Against a 2.5-day-per-week assumption that is **83% loaded** — roughly
five and a half days of slack across the whole quarter, none of it in week 1.

If the actual availability is 1 day a week, cut in this order: A10 and A11 (the
two documentation-truthfulness items — see the note on A10 about the cheaper
option), then B9/B10 (the budget policy), then C9 (the LangGraph demo). If it
is 4 days a week, the cut list becomes the *add* list and §4 names what to add.

## 0.3 Most of group (a) and a large part of group (b) are already done

The build that produced this branch already did the credibility work and most of
the ledger work. Those items are marked **DONE** with their commit SHAs, taken
from `git log --oneline` and not invented. The remaining weeks are spent on what
is not done.

---

# 1. Group (a) — credibility: make the existing repo look as good as it is

## 1.1 DONE — correctness defects found and fixed

81 commits, `c65e8b1..39cb7f9`. Suite **246 passed / 8 skipped → 1214 passed /
9 skipped**; 59 files, +19,072 / −274; 10 new test files; 868 test cases in
them (`00-current-state-audit.md:18-24`).

| # | the defect a user saw | fix | regression test |
|---|---|---|---|
| D1 | `backstop verify --live --provider anthropic` transmitted the **OpenAI** key to `api.anthropic.com` | `44d2ec6` | `test_live_probe_never_sends_the_other_providers_key` |
| D1a | …and the CLI layer had no coverage of it | `8be8151` | `test_cli_verify_live_never_sends_the_other_providers_key` |
| D1b | Anthropic probe used `Bearer` where Anthropic expects `x-api-key` | `2a083c1` | `test_live_probe_uses_x_api_key_for_anthropic` |
| D1c | `--base-url` sent the provider key to any host, silently | `87ac722` | `test_custom_base_url_warns_before_sending_the_credential` |
| D2 | one `queue_timeout` **permanently wedged** that priority forever | `50bcbe1`, `724ea7b` | `test_sync_timeout_does_not_wedge_the_priority_queue` + `test_discarded_ticket_wakes_the_survivor_queued_behind_it` |
| D3 | after one 503, **every later request** was rejected `CircuitBreakerOpenError` | `3ddcf4b`, `d38744c` | `test_successful_stream_releases_the_half_open_probe` + the async twin |
| D4 | `rate_limiter`, `agent_guard`, `shadow_policy` were **not enforced at all for async clients** | `cbb57db` | `test_async_agent_guard_denies_request` (+2) |
| D5 | a synchronous Redis round trip on the event loop, every request | `2bf9a0f`, `0a8e3d3` | `test_async_transport_reconciles_through_the_async_backend_path` |
| D6 | every pre-admission denial **permanently consumed budget** (`remaining` 950/900/850) | `53c8925` | `test_sync_pre_admission_denial_releases_the_reservation` (+async) |
| D7 | every virtual-key request published the **global** budget gauge | `eb9f7e3` | `test_the_budget_gauge_reports_the_virtual_key_tenant_not_the_global` |
| D8 | `backstop doctor` exited 1 with `ModuleNotFoundError: No module named 'httpx2'` on a base install | `4b284bb` | `test_doctor_exits_zero_without_httpx2` (+2) |
| D9 | `--offline` was inert — the user got a live `GET /v1/models` with their credential anyway | `5923d3c` | `test_cli_verify_rejects_live_and_offline_together` (+2 controls) |
| D10 | an example docstring claimed requests are "shed"; nothing is shed | `88f66dd` | proved comment-only by AST comparison |
| D11 | `CloseReport.lost` reported **0** for a ledger that lost all 50 events | `03ef263` | 5 in `test_ledger_sink.py` |
| D12 | a process-global `decimal` context with `prec=6` made `compute_cost` raise on **every** event; the ledger recorded **zero** events with no explanation | `d74f0e7`, `a9218af` | 11 tests across 4 files; "not one expected number in the suite changed" |
| D13 | every OpenAI prompt-cache request was charged the full input rate | `d291fef` | 8 tests; measured **3.091418 → 2.591418**, 14.3% lower |
| D14 | the unattributed share was printed beside different dollars (4.46% vs 4.45%) | `cdd51e8` | 2 tests asserting the disclosure is *necessary* |
| D15 | a `Decimal` dollar printed as six-place money showed a **wrong digit** | `d51c157` | 1 in `test_detection.py` |
| D16 | `estimated_requests` and `unpriced_requests` counted different populations | `8d32ede` | 2 in `test_ledger_export.py` |
| D17 | two docstrings told the caller to increment a `price_unknown` counter that exists nowhere | `ddaba66` | 2, one of which lints the package for the same class of claim |
| D18 | the detection key count grew with the request count | `c156d58` | 11 tests, incl. 5,000 requests / 5,000 keys → 64 keys, 4,936 evictions |
| D19 | a detection-only deployment allocated a 10,000-slot ring nothing could write to | `45d0a9f` | 1 in `test_ledger_state.py` |
| D20 | `state.ledger` had no close, no `atexit`, no context manager | `24c0773` | 7 tests asserted on `threading.enumerate` |
| D21 | a telemetry latency histogram swallowed detection magnitudes | `ae1c39f` | 9 in `test_detection_observability.py` |
| D22 | detection thresholds were frozen and the signals went nowhere | `4871f8b`, `ae1c39f` | a 9-row reachability table + 9 observability tests |
| D23 | endpoint normalisation was not idempotent; a JSONL line was not byte-stable | `a228fcf` | 27 adversarial endpoints |
| D24 | `Attribution` fields were unvalidated; `Attribution(team=1)` raised a bare `AttributeError` | `f42e8fd` | 13 fields x 5 bad values |
| D25 | an async generator or coroutine escaped attribution | `aa8d22a` | 8 tests |
| D26 | `ledger.py` and `ledger/` would have shadowed each other on import | `195224b` | `test_ledger_schema.py` re-exports |

## 1.2 DONE — the truthfulness pass

| claim corrected | commit |
|---|---|
| the false "0.6.0 is unreleased" banner, in `README.md`, `CHANGELOG.md`, `docs/install.md`, `docs/compatibility.md`, `install.sh`, `llms.txt` | `121261a`, `3aa91b7` |
| the enforcement and transport claims: five priorities reduced to three, "shed" removed, "not a proxy" / "no key management" qualified, `httpx` **or** `httpx2`, SDK retries disabled | `a4c8b30` |
| the unreproducible `0.09 ms` table, replaced with committed numbers and their conditions | `61f2650` |
| what the CI matrix proves and what it does not | `9c8c37a` |
| the benchmark scenario counts stopped being called deterministic (eight runs disproved it) | `138ca36` |
| the behavioural summary an agent installer reads first | `0b919d7` |
| both http families named, the gateway added, the control plane marked roadmap | `a500259` |

Also: `d291fef`, `d74f0e7`, `a9218af` above; `cf98ffc` cut the per-event
construction cost 16.08 → 12.13 us; `39cb7f9` took one lock instead of two for
the recent-signals read.

## 1.3 OPEN — the P0 items that gate the 0.6.1 release

| id | item | days (**HYPOTHESIS**) | depends on | definition of done — verifiable |
|---|---|:-:|---|---|
| **A1** | **The default secret provider is silently dead.** `config.py:44` is a frozen dataclass and `config.py:366-370` does `self.secret_provider = SecretProviderChain(...)` inside a bare `except Exception: pass`. The assignment raises `FrozenInstanceError` and the `except` swallows it. Measured: `BackstopConfig(virtual_keys={'vk-1':'tenant_1'}).secret_provider` is `None`, and end to end with `BACKSTOP_API_KEY_VK_1` exported the `Authorization` header came out **unchanged**. A deployment that configures virtual keys believes it has per-key credentials and does not | **0.5** | — | `BackstopConfig(virtual_keys={'vk-1':'t1'}).secret_provider` is not `None`; a test constructs it and asserts the type; a no-`virtual_keys` config still yields `None`; the existing `test_verify.py` key-leak tests still pass; `ruff check src tests` still reports exactly 32 findings |
| **A2** | **`CHANGELOG.md` `## [Unreleased]` has no ledger or detection entry.** Three new user-visible commands and two new packages ship unannounced. Global Constraint 8 is unsatisfied | **0.5** | — | every command in `backstop --help` that is new appears in `## [Unreleased]` under Added; every behaviour change from `00-current-state-audit.md` B1 appears under Fixed with the observable symptom; a reviewer who has not read the code can follow the migration impact |
| **A3** | **`docs/ledger.md` does not exist.** The build plan gates it on Task 7 (`_build-plan.md:162`), which has landed | **0.75** | A2 | the file exists; every command in it runs keyless and offline; every number in it is either copied from a command in this repo or labelled as not reproducible |
| **A4** | **`README.md` has no mention of the ledger, the price catalog or the detector.** All three are user-visible and shipped (open item O24) | **0.5** | A3 | the README names `backstop ledger demo\|show\|export`; the "What It Does Not Do" section is **not** weakened (Global Constraint 4) and gains one line that detection is report-only and cannot block; every snippet in the new section runs |
| **A5** | `docs/install.md:182-198, 213-215` still documents the `doctor` and `--offline` defects that `4b284bb` and `5923d3c` fixed (O22); `TODO.md` shows tasks 4-8 unchecked (O23) | **0.25** | — | `grep -n "httpx2" docs/install.md` returns no claim of a failure; the task checkboxes match `git log` |
| **A6** | **Publish 0.6.1.** Bump `pyproject.toml:7` and `ts/backstop/package.json:3`; tag `v0.6.1`; let `ci.yml` build, `twine check`, create the Release and publish to PyPI | **0.5** | A1-A5 | `pip install backstop-ai==0.6.1` in a clean venv succeeds; `backstop doctor`, `backstop verify`, `backstop demo` and `backstop ledger demo` all exit 0 with `env -i` and no key; `unzip -l` on the downloaded wheel shows `backstop/ledger/*.py` and `backstop/detection/*.py` (this closes O16, which is currently an *argument* about hatchling's recursive inclusion, not a measurement); the GitHub Release carries the wheel and the sdist |

## 1.4 OPEN — the credibility items after the release

| id | item | days (**HYPOTHESIS**) | depends on | definition of done |
|---|---|:-:|---|---|
| **A7** | **A lint gate.** 32 pre-existing ruff findings, measured just now, and CI has no lint step (O7). Do not fix all 32 — that is a separate change with its own review. Add a **ratchet**: the count is asserted not to increase, with a `# noqa`-free baseline file | **0.5** | A6 | `ruff check src tests` in CI fails when the finding count rises above 32; the workflow prints the count; a deliberately-introduced finding fails the build (proved by running it once) |
| **A8** | **A wheel-content assertion** in the `build` job, so "does the wheel actually contain `backstop/ledger/`" is a fact CI checks on every tag rather than an argument in a planning document (O16) | **0.25** | A6 | the job fails if `backstop/ledger/schema.py` or `backstop/detection/detector.py` is absent from the built wheel; it runs on every tag |
| **A9** | **CI coverage for the four extras.** `redis`, `otel`, `fastapi`, `tokenizers` are never installed by `ci.yml:39`, so the distributed-budget, OTel, gateway and tiktoken paths get **no** automated coverage (O19). Add one matrix leg installing all four | **0.75** | A6 | `ci.yml` installs `.[test,metrics,anthropic,redis,otel,fastapi,tokenizers]` on at least one combination; the 9 currently-skipped tests that skip for a missing package no longer skip on that leg; no existing test is weakened to make it pass |
| **A10** | **Wire hierarchical budgets to the transport, or delete the README claim.** `src/backstop/hierarchical.py` is 167 correct, tested lines whose only non-test consumer is `verify.py`, and `README.md:192` still lists "Hierarchical budgets \| Parent budget caps all child agents" under *What It Enforces* (O2, A2.1) | **1.5** for the wiring; **0.25** to delete the README row | A6 | either a test proves a wrapped request is denied when the parent cap is exhausted, or the README row is removed. Not both. This is a truthfulness item, not a feature item, and the 1.5 d figure prices the *wiring* option only |
| **A11** | **The four audit sinks and `CanaryRouter` are dead code with a live documentation surface.** 212 lines of sink, 4 tests, zero product path (O3, O4); `log_json` / `log_sink` validate and then do nothing (O5) | **0.75** | A6 | each of the six is either reachable from `BackstopConfig` with a test that reaches it through `wrap()`, or is documented as unreached in `docs/compatibility.md`. Same rule as A10 |
| **A12** | **Python 3.10 is asserted, not run, locally.** Only 3.12.3 exists in this environment (O17); compatibility rests on an AST scan plus CI | **0.25** | A6 | one local run of the suite under 3.10, or an explicit note in `docs/sdk-matrix.md` that 3.10 support rests on CI only |

**Group (a) remaining total: 7.0 days** (A1-A6 = 3.0; A7-A12 = 4.0).

---

# 2. Group (b) — architecture: unlock the ledger

## 2.1 DONE

| capability | commit(s) | size |
|---|---|---|
| the immutable spend event schema (18 fields) | `3daa170`, plus `f797d12, 403761e, dbb4874, 74daf87, 0d7afca, 0ee8435, 32db2b5, 222d221, b03e0a0, cb95f8b, e28091e, 4a43634, a228fcf, f42e8fd, aa8d22a, 644cbb7` | `ledger/schema.py` 596 lines |
| the ambient attribution context | `c3c0be8` | `ledger/context.py` 217 lines |
| the price catalog: 45 bundled entries, 3-tier precedence, `Decimal` money at 6 dp | `a9d5136`, `6370114`, `7c58eac`, plus `d74f0e7`, `ddaba66` | `pricing_catalog.py` 1,061 lines |
| ledger sinks + the bounded non-blocking writer | `ddaf9d1`, `271edef`, `afe9366`, plus `03ef263`, `24c0773` | `ledger/sink.py` 732 lines |
| transport wiring, sync and async, four submission points | `f92d021`, `4275d5f`, `5b84013`, `0ea1fdd`, `980fda3`, `8d32ede`, `cdd51e8` | `transports.py:195, 231` |
| the chargeback export and the `backstop ledger` CLI | `83affb7`, `81c1677`, `e1eb1e8`, `a8bbf52`, `12b11c0` | `ledger/export.py` 1,753 lines + `ledger/demo.py` 582 lines |
| the runaway-spend detector, report-only, shadow default | `492d8ce`, `beee968`, `4871f8b`, `ae1c39f`, `c156d58`, `d51c157` | `detection/` 1,165 lines |

## 2.2 The load-bearing measured cost, which the remaining items are about

| path | figure | source |
|---|---:|---|
| ledger **off** (the default) | **+3 to +5 us p50, ~+2-3%**; p95 and p99 deltas inside the noise | `task-6-report.md:322-334` |
| ledger **on** | **+130.0 us p50, +253.4 us p95, +335.1 us p99** | `task-6-report.md:348-353` |
| where the 130 us goes | `SpendEvent()` 50.5, `compute_cost` 24.2, GIL lost waking the drain thread **~35-40**, `submit` 3.7, `detector.observe` +36.5 | `task-6-report.md:363-376` |
| in-situ vs tight-loop | the same function measures **3-5x** higher in situ | `task-6-report.md:378-386` |

The ruling on record (`progress.md:100-108`): the ledger-ON cost is **accepted
and documented, not optimised away**, because Global Constraint 2 protects the
*default* path and the default path stays sub-millisecond. B5 below is the one
item that reopens part of that, and it is scoped to the single largest line item
only.

## 2.3 OPEN, ordered

| id | item | days (**HYPOTHESIS**) | depends on | definition of done — verifiable | why now |
|---|---|:-:|---|---|---|
| **B1** | **Cross-process aggregation.** `ledger_path` is one NDJSON file per `BackstopState`. Forty services is forty tables and no total, which is R9's `not survivable` case. Accept many paths or a glob in `backstop ledger show/export`, teach `read_ledger` a list, aggregate `delivery_report` | **1.5** | A6 | `backstop ledger export --path a.jsonl --path b.jsonl` emits one table whose `total_usd` equals the sum of two separate exports to 6 dp; a missing path is named and exits non-zero; the loss counters aggregate and are never reported as zero when unknown; 8 new tests | the highest ratio of product value to effort on this list. 2 days and it is the difference between usable and unusable for any multi-service deployment |
| **B2** | **A test that the merge is the sum** — the specific failure mode is a dedup or a double-count across files | **0.5** | B1 | a test with two files containing the **same** `event_id` asserts the documented behaviour (dedup or double-count), and the behaviour is documented on `read_ledger` | a merge that silently double-counts is worse than no merge |
| **B3** | **Streaming: the second event at stream close** (O12). Every streaming request is recorded `estimated=True` at stream setup, so **every streaming deployment's chargeback is a floor, not a measurement**. `setup_streaming`'s reconcile callback already has the accumulated bytes | **1.5** | A6 | a streamed request produces 2 events: the setup event and a close event carrying the real split; `request_count` in a chargeback counts the **request**, not the event, so a stream is one row; a test asserts both; `estimated=True` falls to zero for streamed requests that report usage | for a chat-heavy product this is most of the traffic, and a floor is not a number finance signs |
| **B4** | **Batch the drain-thread wake-up** (O10). ~35-40 us of the 130 us p50 is GIL time lost to `condition.notify()` per submit, and it is the largest single line item | **1.5** | A6 | the notify is edge-triggered or time-batched; `submit` remains non-blocking and the "a stalled sink does not block the request" tests still pass with the same 500 ms bound; **the ledger-ON p50 is re-measured with the same 14-run alternating protocol and the new number is published** in `docs/benchmarks.md` and in `02-ledger-architecture.md` | a re-measurement is part of the definition of done, not a follow-up. An optimisation with no published before/after is a rumour |
| **B5** | **`provider_map`.** `provider` comes from the request host (`transports.py:53-72`), and Backstop prices only `openai` and `anthropic`. Azure OpenAI, Bedrock, gateways and self-hosted vLLM therefore record a real event with **no cost** — "this is honest, and it is a visible product gap" (`task-6-report.md:417-422`). A `provider_map: dict[str, str]` of host prefix/suffix → catalog provider closes it | **1.0** | A6 | `BackstopConfig(provider_map={"mygateway.corp": "openai"})` prices a request to that host from the catalog; an unmapped host still records `provider="unknown"` and is still unpriced; the map is validated in `__post_init__` so a bad value fails at `wrap()`; 6 tests | the single largest *coverage* hole, and M2 in `01-north-star.md` is computed from exactly this |
| **B6** | **The time series** (M1 in [05](05-expansion-roadmap.md) §4.2). `Period`, `_next_day` and `_next_month` already exist at `export.py:231, 310, 317` and nothing uses them for a series | **1.0** | B1 | `backstop ledger export --series day` emits one row per period with the same 13 columns plus the period key; a month boundary is handled by the existing `_next_month`; a test pins a three-day series and one month boundary | a chargeback is a point in time and a finance review is a movement |
| **B7** | **The second Anthropic cache-write tier** (O11). The schema has one `cache_write_per_mtok_usd` and Anthropic publishes two (5-minute and 1-hour TTL). The bundled card carries the 5-minute tier, so a 1-hour-TTL deployment under-counts cache writes **and `priced_components` cannot reveal it**, because the entry *does* carry a write rate | **1.5** | A6 | the schema carries both tiers with the TTL in the key; `compute_cost` selects by the TTL the event carries; an existing `1.0` JSONL line still loads (the wire contract is not broken); `priced_components` now names `cache_write_1h` when that tier is unpriced | it is a silent under-count today, which is the worst failure class in this codebase |
| **B8** | **The `1.0` wire compatibility story for B7** — this is a schema change to a persisted format and it needs its own decision, test and note, not a drive-by | **0.5** | B7 | every `schema_version` in the tree is enumerated; a `1.0` line reloads to the 5-minute tier; a `1.1` line with both tiers round-trips; a note in `CHANGELOG.md` states the version bump and the migration | |
| **B9** | **Budget policy as a finance-owned artefact** (M4). Today a budget is `BackstopConfig(budget=…)` in a deployment's config: an engineer's number, in code, with no author, no approver, no effective date, no history, and no way to change it without a deploy. A budget nobody approved and cannot audit is not a control | **1.5** | B6 | a versioned policy document: scope (attribution key glob), amount, period, `author`, `approver`, `created_at`, `effective_from`, `policy_hash`; a CLI to sign and to verify it with the existing HMAC chain (`audit.py:20-22`); a test that a policy signed by one author and approved by another reloads and a tampered amount fails verification | the largest gap between "an engineer's guardrail" and "a finance control", and it is the reason the two-buyer split in `01-north-star.md` might be real |
| **B10** | **The approval workflow on top of B9** — the audit trail half | **0.5** | B9 | every policy change emits an `AuditLog` record chained to the previous one; `verify()` replays the chain across a policy history; a test breaks one record and asserts the chain fails | |
| **B11** | **`observe` closes the ledger for a long-lived process.** The `atexit` hook covers only interpreter exit (O14); `BackstopTransport.close()` deliberately does not, because a wrapped client outlives any one request, and "nothing yet reminds it" (`task-8-report.md:712-717`) | **0.5** | A6 | `Backstop.close(client)` is called by the `harness.py` runner and by the `gateway.py` lifespan; a test asserts a completed run leaves no live session in the dashboard registry | documentation is not a reminder, and this is the one place a reminder is cheap |
| **B12** | **Parked admission defects** (O6), four of them, explicitly parked by ruling at `progress.md:56-61`: the dual `threading.Condition` / `asyncio.Condition` race; the starvation path sleeping past `starvation_after_seconds` when `queue_timeout=None`; `KeyError` on an out-of-set provider in `_PROVIDER_BASE_URL`; a degenerate `--base-url` raising before its own guard | **0.5** | A6 | each of the four has a `docs/compatibility.md` line naming the limitation, with the code reference. **Fixing** them is 1.0 d, not 0.5, and is the first item on the add list in §4 | 0.5 days for four known rough edges is a good trade, and leaving them unmentioned is the part that is not acceptable |

**Group (b) remaining total: 12.0 days.**

---

# 3. Group (c) — distribution

## 3.1 The TypeScript fork, decided in week 9

The measured position is in [05](05-expansion-roadmap.md) §1.1 and R10 in
[07](07-risks-and-killshots.md): a published, same-named, same-versioned package
with 5 priorities against Python's 3, a budget bypass that does not exist in
Python, no Anthropic, no metrics, no OTel, no Redis, no hierarchy, no ledger, no
detector, and no CI — plus one latent `ReferenceError` that a CI job would find
in a minute.

| id | item | days (**HYPOTHESIS**) | depends on | definition of done |
|---|---|:-:|---|---|
| **C1** | **Design partners.** Recruit 2; get one to run 0.6.1 with `ledger_enabled` and real attribution on real traffic for a full provider billing period. This is the item that makes every metric in §5 measurable and it is the reason it is in week 2 and not week 13 | **0.5** | A6 | one named partner has `ledger_enabled=True`, a `ledger_path`, and non-empty `team` / `feature` on real calls; they will send the provider's invoice when it arrives |
| **C2** | **The fork decision, executed.** Deprecate the current package's parity claim in both READMEs and both package descriptions; give the TS package a distinct version line (`0.6.0-py.0`); state in the Python README that the npm package is a partial port and which version it tracks | **0.5** | A6 | neither README claims parity; the npm `description` field does not; the TS README's existing "this is a scaffold" line (`ts/backstop/README.md:52-55`) is now consistent with the npm description |
| **C3** | **CI for the TypeScript package.** `npm test` and `npm run typecheck` do not run in CI today | **0.75** | C2 | a CI leg runs `npm ci && npm run typecheck && npm test`; the existing 2 test files, 244 lines, pass; the `require` in ESM defect in `audit.ts:34` is fixed by that job and the fix is a regression test |
| **C4** | **A generated field-compatibility test** that fails when the two config surfaces diverge. R10's counter-move (b), and the specific thing that would have caught the 5-priorities divergence | **0.75** | C3 | a generated file lists every `BackstopConfig` field on both sides; CI fails if a field is added to one and not the other; a deliberately-added Python-only field fails the build (proved by running it once) |
| **C5** | **TypeScript: transport interception.** Replace the `create` monkey-patch with a `fetch`/undici implementation passed to the OpenAI client constructor — a supported configuration option | **1.5** | C4 | `wrap()` installs a fetch implementation; a request made through any other client method is still mediated; the `create` patch is gone; the two test files are updated rather than skipped |
| **C6** | **TypeScript: reconcile the semantics.** The priority set becomes Python's 3 and the `critical`/`high` budget bypass is **removed** | **0.5** | C5 | `types.ts` declares 3 priorities; a test asserts `high` does not bypass the ceiling; the Python `test_ledger_transport.py` budget-ceiling assertions have TypeScript twins |
| **C8** | **LangGraph, level 2.** Per-node attribution and per-node budget through the existing `ContextVar` seam (`ledger/context.py`), not by re-implementing the transport | **1.5** | A6 | a graph with 3 nodes records 3 ledger rows with distinct `Attribution`; a node whose declared budget is exceeded raises `BudgetExceededError` from that node; a test drives a 50-node fan-out |
| **C9** | **The LangGraph demo and its test** | **0.5** | C8 | `examples/langgraph_budget.py` runs with `# KEYLESS`; a screenshot-producing run exists; the test asserts per-node attribution rather than a single unattributed row |
| **C10** | **CrewAI, level 2.** Per-task attribution and per-task budget | **1.0** | C8 | a 2-agent crew records per-task rows; the same test shape as C8 |
| **C12** | **The shadow-tuning playbook, written from real data.** §4.4 of [04](04-detection-design.md) is a procedure. Running it once against a partner's real traffic is what turns it into a document | **0.5** | C1, A6 | the playbook exists; it cites real observed magnitudes and the threshold they imply; a reader can execute it without reading the detector's source |

| **C7** | *TypeScript: the ledger — the same 18-field `SpendEvent`, a JSONL sink, money as a fixed-point integer.* **2.0 d, deferred** | C6 | **DEFERRED out of these 90 days.** It is the single largest item here, and R10's counter-move (b) is explicit that converging the fork "is a real project". Weeks 9 and 10 make the fork honest and make it intercept the transport; the ledger wire format on the TS side is a separate piece of work with its own maintainer. See §4 |
| **C11** | *`backstop serve` promoted to a supported mode — the 117-line gateway, behind the `fastapi` extra, which is the only real answer for coding-agent harnesses.* **1.5 d, deferred** | A9 | **DEFERRED out of these 90 days.** It depends on A9's all-extras CI leg landing first, and it is a *mode* rather than a capability. Play A in [05](05-expansion-roadmap.md) §3.4 is worth doing properly rather than in a leftover week. See §4 |

**Group (c) remaining total: 8.0 days** — C1-C6, C8, C9, C10 and C12.

---

# 4. The 13 weeks

Every day figure is a **HYPOTHESIS**. Every DoD is verifiable. The dependency
column names the item id, not a person.

| week | group | items | days | the week's deliverable, stated as a check |
|:-:|---|---|:-:|---|
| **1** | **(a)** | A1, A2, A3, A4, A6 | **2.75** | `backstop-ai==0.6.1` on PyPI; a clean venv runs `doctor`, `verify`, `demo`, `ledger demo` at exit 0; the wheel contains `backstop/ledger/`; the `## [Unreleased]` section describes the whole build |
| **2** | **(a)** + **(c)** | A5, A7, A8, A9, C1 | **2.25** | CI has a lint ratchet, a wheel-content assertion and an all-extras leg; `docs/install.md` and `TODO.md` match the code; one design partner is running the ledger on real traffic |
| **3** | **(b)** | B1, B2 | **2.0** | two ledgers, one chargeback, and the totals reconcile to 6 dp; the duplicate-`event_id` behaviour is documented and pinned |
| **4** | **(b)** + **(a)** | B3, A12 | **1.75** | a streamed request produces a real token split, and a chargeback row counts it once; 3.10 is either run locally or documented as CI-only |
| **5** | **(b)** + **(a)** | B4, A11 | **2.25** | the ledger-ON p50 is re-measured with the published protocol and the new number is in `docs/benchmarks.md`; the six dead-code items are each reachable or documented |
| **6** | **(b)** | B5, B6 | **2.0** | a non-OpenAI/non-Anthropic deployment gets a priced chargeback; the export has a `--series` |
| **7** | **(b)** | B7, B8 | **2.0** | both Anthropic cache-write tiers price correctly and a `1.0` line still loads |
| **8** | **(b)** | B9, B10 | **2.0** | a signed, approved, chained budget policy exists and a tampered one fails verification |
| **9** | **(c)** | C2, C3, C4 | **2.0** | neither README claims parity; `npm test` runs in CI; a Python-only config field fails the build |
| **10** | **(c)** | C5, C6 | **2.0** | the TS package intercepts the transport and its priorities are Python's three |
| **11** | **(c)** | C8, C9 | **2.0** | a LangGraph fan-out is attributed per node |
| **12** | **(c)** + **(b)** | C10, C12, B11 | **2.0** | a CrewAI crew is attributed per task; the shadow-tuning playbook is written from a partner's real observed magnitudes; the runner and the gateway close their ledgers |
| **13** | **(a)** + **(b)** | A10, B12, plus the 0.6.2 tag | **2.0** | hierarchical budgets are either enforced on a wrapped request or removed from `README.md:192`; the four parked admission defects are named in `docs/compatibility.md`; `v0.6.2` is tagged and published |
| | | **total** | **27.0** | 13 weeks at ~2.1 days/week, against a stated part-time budget of ~32.5 days — **83% loaded** |

### Deliberately not in these 90 days

| not doing it | why | effort if it were (**HYPOTHESIS**) |
|---|---|---:|
| **C7 — TypeScript ledger parity** | 2.0 d is the largest single item on the list and it is a *separate project*, which is exactly what R10's counter-move (b) says: "(b) is a real project". Weeks 9 and 10 make the fork honest and make it intercept the transport; the ledger wire format on the TS side is a different piece of work with its own maintainer. [05](05-expansion-roadmap.md) §1.2 argues the ledger is the thing worth converging on — and argues it as a project, not a fortnight | 2.0 d, plus a maintainer |
| **C11 — promoting `backstop serve` to a supported mode** | it depends on A9's all-extras CI leg landing first, and it is a *mode* rather than a capability. The coding-agent answer in [05](05-expansion-roadmap.md) §3.4 is play A, and play A is worth doing properly rather than in a leftover week | 1.5 d |
| Go, Rust or Java ports | the order and its reasoning are in [05](05-expansion-roadmap.md) §1.2; none of them should start before a second language exists in the ledger | 6-15 d each |
| auto-kill | the five requirements it needs are in [04](04-detection-design.md) §3.3 and **none of them is designed** | not estimable |
| cost per completed task | the five dependencies are in [04](04-detection-design.md) §5.4; the first is a task identifier on the record, which is a schema decision | 15-25 d |
| the shared Rust core | a shared core is only worth building once a second language has a ledger implementation to share | 20-30 d |
| a finance dashboard | [05](05-expansion-roadmap.md) §6.2 argues against it and §6.3 says what would falsify that | — |
| forecasting (M2) | needs B6 and a defensible conditioning set; [05](05-expansion-roadmap.md) §5.2 | 10-15 d |
| the cross-customer benchmark | three open HYPOTHESISes in `01-north-star.md` (legal, technical, trust) and the trust one is the blocker | — |
| a docs site | `PLAN.md:940` item 7. Real, low, and not a credibility item this cycle | 2-3 d |

### The add list, if there is more than 2.5 days a week

In this order, because each one is either an un-done promise or a measured debt:

| add | days | why it is above the ones below it |
|---|---:|---|
| **B12-fix** — actually fix the four parked admission defects rather than document them | +0.5 | they are parked by ruling, not by decision, and a documented limitation is a smaller claim than a fixed one |
| **C7** — the TypeScript ledger wire parity | 2.0 | the single most valuable thing for the fork's credibility after weeks 9 and 10 |
| **C11** — promote `backstop serve` | 1.5 | the coding-agent market is unreachable without it ([05](05-expansion-roadmap.md) §3) |
| **M3** — margin per feature as a surface rather than a join | 5-8 | the fastest path from "cost report" to "chargeback" ([05](05-expansion-roadmap.md) §4.2) |
| **M2** — forecasting | 10-15 | needs B6 first, and a defensible conditioning set ([05](05-expansion-roadmap.md) §5) |

---

# 5. The three metrics, and when each first becomes measurable

Verbatim from [01-north-star.md](01-north-star.md), with the date each could
first be read. **All three dates are HYPOTHESISES** and all three are gated on
C1 — on a design partner actually running the ledger on real traffic — because
**this repository has no traffic of its own** and none of the three is computable
from synthetic data.

### M1 — Ledger-to-invoice variance

> `abs(ledger total - provider invoice total) / invoice total`, per provider,
> per month, reported alongside `unpriced_requests` and `estimated_requests`,
> never alone.

**First measurable: week 5-9, and only for a partner who adopted in week 1-2.**
It needs three things and none of them is code: a ledger running for a **full
provider billing period**, the provider's invoice in a readable form, and the
ledger total for the same window. If a partner adopts in week 2, the earliest
period boundary is the end of that calendar month, so week 5 or week 9
depending on the day. **It is not measurable inside 90 days on our own
traffic**, because there is none.

**What would make it move:** B5 (`provider_map`) and B7 (the cache-write tier)
are the two items that change the number, and both change it in the direction of
*closing a gap*, which is the point.

**The trap, stated in advance:** M1 can be made to look better by guessing a
price, and the metric is designed to punish exactly that. Read it next to
`unpriced_requests` and `estimated_requests` or do not read it.

### M2 — Spend coverage

> The share of requests that appear as a **priced, measured, attributed** row:
> `1 - |unattributed ∪ unpriced ∪ estimated| / total`, per group per period,
> reported next to a separate per-component gap.

**First measurable: week 3, on one partner, one period — and it is measurable
today on the demo window.** `01-north-star.md:126` computes 0.9476 on the
demo's 1,967 synthetic events. That is a **smoke test of the metric's
arithmetic, not a measurement of it**, and the two must never be quoted as the
same kind of number.

The real number needs only a partner with the ledger on and real attribution —
no billing period, no invoice. So M2 is the **earliest** of the three and it is
the one to instrument from week 2.

**What would make it move:** B5 is the largest single lever (every
non-OpenAI/non-Anthropic request is currently unpriced by construction), and
B3 is the second (every streaming request is currently `estimated=True`).
Attribution discipline on the customer's side is the third, and it is the only
one Backstop cannot do for them.

**The trap:** the gap is a **union, not a sum** (`01-north-star.md:126`), because
the three sets are not guaranteed disjoint. A coverage number computed by adding
them would reward a customer for making their own report harder to read.

### M3 — Ledger-attached revenue

> ARR from accounts where a finance-side owner has accepted at least one
> chargeback row into a budget or a reconciliation process, counted from signed
> invoices.

**First measurable: not inside 90 days, unless a partner commits in week 1.**
It needs a signed invoice, and a signed invoice needs a finance-side owner to
have accepted a number. The 90-day plan cannot buy that. What *is* measurable
inside 90 days is the **leading indicator**, and it should be tracked from week
1 whatever happens:

| leading indicator | target at day 90 (**HYPOTHESIS**) | why it is the right one |
|---|---|---|
| partners who ran the ledger for a full billing period | 1 | the shortest path to a signed invoice |
| partners whose finance owner has **seen** the export | 1 | a number nobody looked at cannot be accepted |
| partners who ran a second period with it | 0-1 | re-use is the signal that it is not a one-off curiosity |

**The only thing that would make M3 measurable faster** is a partner whose
finance team is already blocked on exactly the problem `backstop ledger demo`
solves, rather than a partner who liked the demo. C1 is written to find that
partner in week 2 rather than a friendly one in week 12.

---

# 6. What would make this plan wrong

| if this is true | then |
|---|---|
| the actual availability is 1 day a week, not 2.5 | cut C7, B7, B8, C9 in that order (stated in §0.2); the release and the partner still happen |
| no design partner adopts by week 4 | M2 and M1 are not measurable in 90 days, and the honest report is "we shipped a ledger and nobody ran it on real traffic". That is a **product** finding, not a plan failure, and it belongs in [07](07-risks-and-killshots.md) |
| the TypeScript fork turns out to have real users | C2 (deprecate) is wrong and C5-C7 (converge) is too small; the npm package needs its own project and its own maintainer |
| B4's re-measurement shows the notify was not the cost | the 35-40 us was measured (`task-6-report.md:374`) but the fix may not recover it; publish the new number either way, including if it is worse |
| a harness exposes a blocking plugin hook | play B in [05](05-expansion-roadmap.md) §3.4 stops being advisory, and the coding-agent market opens up without a proxy |
| the user decides on the sibling project in favour of "two products" | B9/B10 (budget policy) belongs to the sibling, not here, and 1.0 d comes off this plan and the finance surface here shrinks to M1, M3 and M6 |

**The one commitment this plan makes that is not a hypothesis about the world:**
0.6.1 ships in week 1, with the changelog, the ledger doc, the README section
and the dead secret provider fixed. Everything else in these 13 weeks is
adjustable. That one is not, because 0.6.0 is on PyPI and npm right now and the
tree that produced 1,214 tests is not what anyone installed.
