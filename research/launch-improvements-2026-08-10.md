# Backstop Launch Improvements — Deep Research (7 Capabilities)

**Date:** 2026-08-10
**Depth:** deep (plan a major build)
**Scope:** Best-in-class solutions for the 7 launch-blocking improvements identified from the B2B onboarding flow (Maya persona): (1) `backstop verify`, (2) shadow mode, (3) budget-exhaustion webhooks, (4) hierarchical budgets, (5) audit log → structured sinks, (6) convergence metrics in Prometheus, (7) secret provider as default + supply-chain trust.
**Goal (user):** Make Backstop *the best in its class* with a 100× gap vs competitors — researched, not bluffed — then a plan, no implementation yet.

---

## 1. Executive Summary

We ran 7 parallel deep-research subagents (each 6+ searches, 5+ full source fetches, GitHub-issue mining, community-sentiment sampling) followed by one adversarial verification pass that surfaced **39 issues** (2 genuine cross-subagent contradictions, 1 factual error, 1 piece of unsourced legal reasoning, plus overstatements and unverified issue-IDs). Every correction is folded into this report.

**Headline conclusions:**
- A `backstop verify` one-command proof runner is the single highest-leverage change — it collapses install → trust into ~30s and directly attacks the industry-wide "claims without proof" gap. Pattern is well-established (`pnpm doctor`, `dotnet doctor`, LiteLLM `/health`).
- Shadow mode (enabled≠enforced) is the correct rollout primitive and is industry-standard (Envoy `filter_enabled`/`filter_enforced`, OPA/K8s dry-run). Apply it to every enforcement decision.
- Budget webhooks should warn *before* the cap via tiered thresholds + a **forecast projection** (the "N calls remaining" alert is genuinely novel and would be a Backstop differentiator). Copy LiteLLM's beta-ish event shape but normalize it.
- Hierarchical budgets: invert the semantic — **recursive usage charged to all ancestors, validated on every allocation** (YTsaurus model), with `most-restrictive-wins` as the default and `allow_children_limit_overcommit` opt-in. Pre-reservation is feasible only with bounded `max_tokens`; otherwise accept one-request overshoot.
- Audit logs: ship via **OTel/Vector → S3 (Iceberg) / BigQuery** with WORM Object Lock; keep the existing hash-chained local audit as the source of truth and add a CloudEvents envelope. Compliance claims need counsel, not blog reasoning.
- Metrics: use the **OTel Collector → `prometheusremotewrite`** path (Pushgateway is a trap for this workload), with low-cardinality outcome labels and native histograms only if the backend supports PRW 2.0.
- Secrets: make provider-aware resolution the default using the **AWS/Google "credential chain"** pattern (env stays as last-resort fallback, never first), and harden the installer with checksum + Sigstore cosign + SLSA L2 + SBOM — learning from PyPI's PGP failure and the ESLint/XZ incidents.

**The 100× gap thesis:** No competitor ships *reproducible, real-provider proof* of cost reduction, *hierarchical* budget isolation, *forecast-based* pre-cap alerts, or a one-command `verify`. Backstop already has in-process enforcement with sub-ms overhead and a working Wedge proof tool. Adding these 7 capabilities turns a "10× better" claim into a category of its own — provided each claim is backed by a `verify`/`proofs/` command that anyone can re-run.

---

## 2. Background & Key Terms

| Term | Meaning |
|---|---|
| `backstop verify` | Proposed one-command CLI that runs proof checks against the user's real provider and prints pass/fail |
| Shadow mode / dry-run | Enforcement decisions computed + recorded but never acted on (enabled ≠ enforced) |
| Webhook | HTTP POST to a user endpoint on an event (budget threshold, projection) |
| Hierarchical budget | Tree (team→service→agent); child usage counts against all ancestors |
| Object Lock (WORM) | S3 immutability: Compliance (no one can shorten) / Governance (bypassable with permission) |
| CloudEvents | CNCF event envelope standard (sink-agnostic) |
| Pushgateway | Prometheus cache for batch-job metrics (caution: SPOF, never forgets series) |
| Credential chain | Ordered provider-resolution (env → file → IMDS → OIDC) stopping at first success |
| SLSA / Sigstore | Supply-chain provenance levels / keyless signing + Rekor transparency log |

---

## 3. Findings by Sub-Question

### SQ1 — One-command `backstop verify` proof runner
**Confidence: high** (multiple primary sources agree; medium only on aggregate-run-time budgeting which no source addresses).

- Checks use a small status vocabulary `pass`/`warn`/`fail`/`skip`, each with a human-readable message + a `fix` (pnpm, wp-cli, Vendure, Aspire). *(src: pnpm.io/cli/doctor; github.com/wp-cli/doctor-command; vendurehq docs)*
- `--json` output should be a first-class, stable contract: per-check `{title, status, detail, fix, durationMs}` (pnpm) and a `{passed, warnings, failed}` summary (Aspire). **Correction (verifier #3):** the exact pnpm schema/fields are stated with more specificity than the source supports — treat as *our proposed* schema informed by pnpm/Aspire, not a verbatim quote.
- Exit `0` = all pass; `--strict` escalates `warn`→`fail` for CI (pnpm/Aspire/Vendure). Stdout = data, stderr = diagnostics (stripe-cli#1554).
- Live checks need **explicit, per-check timeouts** (pnpm 15s registry ping; `AbortSignal.timeout(5000)`; ralph-tui default 30s, configurable to 2min).
- **Cheap liveness vs real smoke (correction #5):** present both tiers. `GET /models`-style liveness by default; real end-to-end calls behind `--live`. LiteLLM's own docs push `/health/readiness`/`liveness` precisely because `/health` costs tokens — the researcher cherry-picked the pro-smoke half.
- **Key validation (correction #4):** `GET /models` is *common* (gptme, Home Assistant), not a "standard", and only proves key existence — **not** scope, model entitlement, quota, or org routing. A passing check + failing completion is the exact false-confidence mode SQ1 warns about. Need per-provider workarounds (Kiln posts to a nonexistent model since `/v1/models` is public).
- Distinguish transport/network vs invalid-credentials vs scope errors (gh#12891 misreported DNS-block as "invalid token"; librefang#201 added a connectivity check).
- **False failures are corrosive (correction #7):** restated as a design *heuristic*, not a measured "#1". Live third-party checks should be gated behind `--live` and excluded from default CI (mcp-use#1608 removed them because key rotation/quota/region redden branches). **Correction #6:** this is *not* a disagreement with Vendure-designs-for-CI — different check classes; resolved rule: deterministic local checks in CI, live checks interactive.
- Never print secrets (gh masks `gho_****`; dbt redacts even verbose). Offline/`--live` gating (pnpm `--offline`).
- **Open questions:** ideal aggregate ~30s budget (only per-check timeouts documented; no tool documents total-run budgeting or parallel check execution); retry-once-before-fail policy; verify *through* the wrapped SDK vs raw HTTP.

### SQ2 — Shadow mode / dry-run (log-only enforcement)
**Confidence: high** on mechanism + counter shapes; medium on "can you trust shadow enough to flip."

- **The canonical two-axis model:** Envoy's **local rate limit filter** has `filter_enabled` (decision computed) vs `filter_enforced` (decision acted on); shadow = enabled 100% / enforced 0%. kgateway publishes `enabled`/`ok`/`rate_limited` (would-block) / `enforced` (0 in shadow). **Correction #8:** name the filter — this is the *local rate limit* filter; RBAC uses `shadow_rules`, global RL differs.
- **Correction #9:** Envoy Gateway `RateLimitRule.shadowMode` is supported **for Global Rate Limits only** — if we assume shadow works for per-route/local limits, that's wrong.
- Istio authz dry-run (`istio.io/dry-run`) emits debug log + Prometheus counter `authz_dry_run_result="denied"` + Zipkin tags. K8s `--dry-run=server` runs the full admission chain without persisting; Pod Security Admission ships `enforce`/`audit`/`warn`; Gatekeeper records `status.violations` with `enforcementAction: dryrun` + 60s periodic audit.
- LLM-gateway analogues: LiteLLM **soft budgets** alert without blocking; guardrail `monitor_mode: true` logs-but-doesn't-block; `mock_response`. Bedrock AgentCore `LOG_ONLY` policy still emits OTel span attributes.
- **Gradual rollout:** ramp `percentEnabled` then `percentEnforced`; phase ladder `shadow → log_only → enforce_new → enforce_all`; env-var kill switch (`RATE_LIMIT_ENABLED=false` instant rollback, Traceroot#941); flag can only *raise* to enforced, hard kill-switch wins (latitude-llm#4067); PostHog shipped shadow then enforce.
- **Known pitfalls (GitHub):** Gatekeeper#379 dry-run produced no logs/metrics initially (stale — likely resolved; drop or date-stamp). Gatekeeper#3569 audit-scope gap (durable). Envoy#42737 shadowed decisions not distinguishable in gateway filter metrics (need dedicated `shadow_*` counters). k8s VAP audit-only bindings overwrote a shared annotation → lock contention (#140001) — *recording* shadow outcomes can itself cost.
- **Contradiction resolved (#11 ↔ SQ4):** SQ2 documented LiteLLM pre-reserving budget against `max_tokens` (#27509); SQ4 claimed "no system pre-reserves in-flight cost." Reconciled: pre-reservation is feasible **only with a bounded `max_tokens`** (that's what the LiteLLM bug was about — naïvely pinning full headroom false-blocked concurrent requests). Unbounded requests force post-hoc settlement.
- **Correction #10:** the qwen-code#8469 claim "shadow is an upper bound, not an estimate" is a **single reviewer comment on one PR** and is probably wrong as stated (enforcement changes client behaviour → 429→retry storms or abandonment, so shadow counts can be *below* real stops too). Demote to a caveat, not a finding.

### SQ3 — Budget-exhaustion alerts & webhooks
**Confidence: high** (gateway docs fetched in full); medium on "N calls remaining" novelty (untested by any vendor).

- **Threshold tiers warn before the cap:** LiteLLM emits `budget_crossed` (blocked), `threshold_crossed` (85/95%), and `projected_limit_exceeded` (with `projected_exceeded_date`/`projected_spend`). **Correction #13:** LiteLLM's budget-webhook section is literally headed **"[BETA]"** ("spec might change") and internally inconsistent (example emits `projected_exceeded_data`, spec says `projected_exceeded_date`). Clone the *shape*, normalize the field, add the beta caveat.
- Portkey `usage_limits[].alert_threshold` below `credit_limit` — workspace keeps running until the full limit (portkey docs). TrueFoundry milestone thresholds (75/90/100) via email/Slack.
- **Correction #14:** the "Microsoft agent-governance-toolkit" 50/75/90/95 + 85% throttle + 95% kill-switch is a **Microsoft-published sample repo**, not a supported product — attribute accordingly, drop the vendor halo.
- **Forecast is the stronger tier:** AWS Budgets `ACTUAL` vs `FORECASTED` (via SNS); Cloudflare projected-monthly-spend alerts; LiteLLM already ships `projected_spend`/`projected_exceeded_date`. **Caveat:** forecasts fail on sparse history (AWS Cost Explorer returns "unable to produce a meaningful forecast"). **The "Agent A will exhaust in ~5 calls" projection is novel** — no vendor ships a calls-remaining forecast; backs it with burn-rate math, not just threshold.
- **OpenAI/Anthropic native alerts (correction #15):** OpenAI spend alerts are threshold-email only, no webhook (undated single-vendor negative on a fast-changing surface — date-stamp or drop). Helicone: threshold + time window + min-request-count to avoid false positives.
- **Webhook delivery quality — split spec vs convention (#16):** **Spec (Standard Webhooks / Svix):** HMAC-SHA256 (or ed25519) + `webhook-id` idempotency + at-least-once. **Convention:** retry 5xx/408/429 with exponential backoff+jitter (not 4xx), 5–10 attempts, ~5s timeout, DLQ for exhausted retries (Svix glossary). Sign with `hmac.compare_digest` on raw body bytes. Alert send must **never block** the user request (LangWatch#1941, fire-and-forget).
- **Alert-fatigue — reframe as a matrix (#17), not a disagreement:** dedup key × window × reset-on-cycle. LiteLLM `budget_alert_ttl` (86400s) per instance; Requesty once-per-threshold-crossing-per-billing-cycle; MLflow once-per-window; digest mode (LiteLLM) for high-frequency (in-memory, non-durable — caveat). Escalation by severity: email → Slack → PagerDuty by $ amount.
- **Real failure modes (GitHub):** LiteLLM#27398 one alert per active key (dedup keyed on request token, not team); #35800 virtual-key soft-budget alerts silently never fired + dedup stamped *before* async POST confirmed → lost; LangWatch#3917 cooldown dedup race-prone under concurrency; multica#6610 notification storm from 14 ungoverned keys. **Implication for Backstop:** dedup keyed on `(tenant, threshold)` with an atomic in-flight marker; do not "send then mark".

### SQ4 — Hierarchical budgets (team→service→agent)
**Confidence: medium-high** core semantics (primary docs + GH issues); medium on AWS/Azure/GCP/Vantage (index excerpts only).

- **Canonical semantic (HNC):** sum of sub-namespace usage ≤ parent HRQ; "most restrictive quota always applies" — child cannot override ancestor. **Verifier #18:** the exact quotation should be confirmed in the HNC HRQ docs or un-quoted (reads paraphrased).
- **Best reference (YTsaurus):** child quota ≤ parent (induction over ancestors); sum-of-children ≤ parent by default; opt-in `allow_children_limit_overcommit` relaxes *only* the sum, never the child≤parent rule; **recursive usage charged to the account AND all ancestors**; **validate every ancestor on every allocation** ("if an increase causes the account or any ancestor to run out of quota, an error is generated"). Async tracking means strict non-exceedance isn't 100% guaranteed — note this.
- **K8s ResourceQuota:** admission-time pre-check (403) + continuous accounting. Capsule/Rancher replicate at tenant/project level ("hard quota never crossed for the tenant").
- **Envoy ratelimit:** nested descriptors → every child request matches the parent descriptor → parent caps the sum by construction. Per-rule `shadow_mode`. **Trust-boundary reframe (#19):** Envoy's `replaces` (child can raise inherited limit) is fine *where the parent authors the child's config* (single-team gateway); for multi-tenant namespace hierarchies use `most-restrictive-wins`. Not an unresolvable conflict — a scope decision.
- **LiteLLM real bugs (copy these as test cases):** org_max_budget retrieved but never checked in auth (PR#17334, parent cap silently unenforced); team check `>` vs `>=` off-by-one (PR#28051); null-fallback skipped enforcement when member had no budget row (PR#26204); semantics flip-flopped v1.94 both levels vs v1.95 key-owner budget dropped (docs). Redis counters reseed stale after TTL → under-report.
- **Reservation reconciliation (#11):** bounded `max_tokens` → pre-reserve headroom (LiteLLM#27509 shows the failure mode when you pin *all* remaining headroom). Unbounded → post-hoc settlement, one-request overshoot (Kong ai-rate-limiting cost reflected on next request; Stripe pure post-hoc). **No system guarantees zero overshoot on cost** — adopt a documented one-request overshoot policy.
- **Other systems:** Stripe = post-hoc settlement not enforcement; Azure budgets don't cascade the EA hierarchy; GCP quota preferences independently configured (no parent-headroom aggregation); AWS Budgets = reactive alert + deny-SCP (not per-request gate); Terraform Cloud Sentinel blocks on estimated plan cost; Vantage/CloudZero = allocation/visibility, not enforcement. **None are low-overhead in-process** — but Envoy local_ratelimit token buckets, HNC controller, and Go `x/time/rate` hierarchies *are* in-process precedents (verifier #2 corrects SQ4's "no in-process precedent" claim — delete it).
- **Verifier #20:** drop the "~13% cloud overrun / 69% IT leaders" vendor stats — they're 2023 general-cloud, not LLM, zero evidential value here.

### SQ5 — Audit logs → structured sinks
**Confidence: medium** (verifier flagged the subagent used pre-training recall, NOT re-fetched canonical docs, for several items — see limitations).

- **Integrity models (two camps):**
  - *Consumer-verifiable hashing:* AWS CloudTrail hourly SHA-256 digest files, RSA-signed, chainable (each digest includes prior hash); validation optional per trail; key history must be retained; gap breaks continuity; covers **S3-delivered** files only (verifier #26 scope). W3C **Notary** (verifier #25: a Community Group / draft note, *not* a W3C Recommendation — relabel). Schneier & Kelsey 1999 hash-chaining is the canonical construction.
  - *Platform-enforced immutability:* Google Cloud audit logs system-owned, append-only, no user write/delete (integrity by platform, no per-event sigs); Azure RBAC + retention/immutability. **Disagreement (real):** hashing camp assumes storage may be compromised by an insider; platform camp asserts the platform can't be. The GCP model breaks if the platform itself is the attacker.
- **NIST SP 800-53 AU-9 / ISO 27002 8.15–8.16** recommend cryptographic protection of audit info (citable).
- **OpenSearch audit logs:** rich categories, 3 storage backends (internal/remote/S3), **no native hash chaining** — integrity via Object Lock + access control.
- **Event schema:** CloudEvents v1.0.2 envelope `{id, source, type, specversion, data, subject, time}`; OTel logs data model `{Timestamp, SeverityText/Number, Body, Attributes, TraceId/SpanId}`; ECS field normalization. **Limitation:** these three + Vector/Fluent Bit/Filebeat/Athena/Object Lock/SOC2/GDPR were *not re-fetched* — treat as design inputs to confirm, not quoted spec.
- **Shipping pipelines:** Vector (end-to-end acks, disk buffer, **at-least-once, ordering per-partition only**), Fluent Bit (`Retry_Limit`, disk-backed), Filebeat (registry offsets, at-least-once). S3 sink → each batch one object; duplicates unless keyed by stable batch id. BigQuery: streaming ≈ seconds but per-row cost; **batch loads free** but hourly latency; Storage Write API commit-based exactly-once.
- **S3 queryability:** Athena Hive `dt=YYYY/MM/DD` partitioning (cost ∝ bytes scanned); Iceberg native in Athena (hidden partitioning); **Object Lock**: Governance (bypassable with `s3:BypassGovernanceRetention`) vs **Compliance (no one — including root — can shorten before retain-until)**; retention can be *extended*; + legal holds (verifier #22 qualifiers).
- **PII:** Vector Redact (regex field-level), Fluent Bit `modify`, tokenization/hashing (joinable without plaintext).
- **Compliance (verifier #23/#24):** SOC 2 TSC states no explicit retention period; "~1 year" is informal practice, no citation. **GDPR:** the claim "document legitimate interest, bounded retention" is *wrong* legal reasoning — "legitimate interest" (Art 6(1)(f)) is a lawful *basis*, not an erasure exemption; relevant carve-outs are Art 17(3)(b) legal obligation / 17(3)(e) legal claims. **Remove the prescription; state the tension and route to counsel.**

### SQ6 — Convergence metrics → Prometheus/Grafana
**Confidence: high** (primary docs/specs fetched in full); medium only where version-sensitive.

- **Pushgateway — corrected (#27/#28):** the docs say *"Usually, the only valid use case … is for capturing the outcome of a service-level batch job"* — a recommendation, not a restriction; and such metrics **should not carry a machine/instance label** (the operative constraint for a CLI tool, which is naturally per-machine). The "Prow uses it at scale" point is *not* counter-evidence — it's the sanctioned case that also eats the stale-series management cost. Prometheus Operator + actions-runner-controller ADR explicitly advise against it (SPOF/bottleneck, loses `up`).
- **Sanctioned path for Wedge:** CLI emits **OTLP → OTel Collector (batch+retry) → `prometheusremotewrite` → Mimir/Cortex/Grafana Cloud**. Keep low-cardinality *outcome* labels (CONVERGED/PARTIAL/DIVERGED, budget delta); keep task/run IDs out of metric attributes (OTel cardinality default 2,000 combos/stream → overflow).
- **Histograms (#29 — resolved, not a disagreement):** current Prometheus recommends **native histograms** over classic/summaries, BUT maturity depends on the backend: classic remote-write (PRW 1.0) doesn't carry native histograms — you need **PRW 2.0**. Dash0's "experimental" note reflects a release-flag state. **Decision: emit classic histograms or OTel exponential histograms (convert to native on ingest) and don't assume the user's Prometheus accepts native histograms.**
- **OTel GenAI semconv (Development stability):** `gen_ai.client.token.usage` (Histogram, buckets 1..67M), `gen_ai.client.operation.duration` (doubling 0.01→81.92s), `gen_ai.invoke_agent.duration/inference_calls/tool_calls`. Pin the semconv version + SDK language (issue#101 may flip token.usage to Counter).
- **Exemplars (#30 — untangled):** `prometheus_client` supports on Counter/Histogram with `trace_id`; server `--enable-feature=exemplar-storage`; Grafana renders as stars → Tempo/Jaeger. The collector-contrib#5192 (missing exemplar support) and opentelemetry-python PR#4178 are *different artifacts* — don't fuse causality.
- **CI-health pattern:** success-rate-per-window `sum(rate(x{status="success"}[5m]))/sum(rate(x[5m]))`; flaky ranked by time wasted. No direct precedent for *agent-convergence* metrics — CI success-rate-over-window is the closest template. **Langfuse (#31):** "one widely-used option" for agent quality over time (traces + sessions + scores), not "the standard".

### SQ7 — Secret provider as default + supply-chain trust
**Confidence: high** on chain pattern + incidents; medium where Single-source.

- **Credential chain (the pattern to copy):** AWS SDK searches ordered sources, first-wins, auto-renewal (env → shared file → SSO → container → IMDS → process). Google ADC: `GOOGLE_APPLICATION_CREDENTIALS` (pointer to file, *not* the secret) → well-known file → metadata server; order "not related to relative merit"; SA key files "a security risk, not recommended".
- **False dichotomy dissolved (#33):** "env-first (AWS) vs env-last (security writers)" is not a real disagreement — both camps agree: prefer short-lived provider-native credentials, keep env as *fallback*. Backstop should: try provider(s) → fall back to env **last**, and *warn* when env is used.
- **Provider patterns:** Vault Agent (auto-auth + token renewal, renders secrets to files); 1Password `op run` (op:// refs into child env only, masks output by default); Doppler **`--mount` named pipe** ("the only secure method" — **verifier #39: vendor marketing, attribute as such**; the LD_PRELOAD "hijack vector" claim is garbled — LD_PRELOAD is library injection, not "env names read programmatically"; fix or cut); SOPS (encrypted-at-rest, decrypted via KMS/age).
- **Why env is the wrong *default* carrier:** readable via `ps -eww <pid>`, `/proc/<pid>/environ`, inherited by all children, captured in crash logs (PagerDuty scrubbing), docker image history; "secret zero" bootstrap problem. Fix: provider-native fetch + GitHub Actions OIDC short-lived per-job tokens for CI/bootstrap.
- **Supply chain:** SLSA L0–L3 (L1 provenance, L2 signed from hosted build, L3 hardened — user steps can't touch signing keys); Sigstore keyless (Fulcio certs + Rekor log); "signatures useless if nobody verifies".
- **PyPI PGP — corrected (#34/#35):** ~50k signatures from **1,069 unique keys**; ~30% of *keys* undiscoverable, **36% of *keys*** (not signatures) meaningfully verifiable; "worse than useless" is a *third-party* audit (yossarian.net), not PyPI's phrasing; PyPI **stopped accepting new PGP signatures** but still serves existing ones. Successor = **attestations (PEP 740, 2024)**, a *separate* feature from OIDC Trusted Publishers (2023) — don't fuse into one causal arrow.
- **Incidents (durable, checkable):** ESLint 2018 (compromised maintainer → malicious `eslint-scope`, `.npmrc` token exfil); XZ Utils 2024 (backdoor only in release tarballs, ~2yr social engineering; OpenSSF "may not be isolated").
- **Installer hardening:** exact-version URLs + `checksums.txt` + `cosign verify-blob` + SLSA L2 + SBOM (CISA); document signer identity (SOPS pipeline precedent). **Lockfile correction (#36):** lockfiles give integrity *pinning*, not provenance attestation; pip doesn't verify PyPI attestations by default; npm provenance only checked via `npm audit signatures` (the corpus's own "verify or useless" point). **Delete unverified stats (#37/#38):** "73k GitHub issues" search-hit (non-reproducible) and "2026 audit ~448 critical findings" (single secondary source, no methodology) — argue the threat model on the durable, checkable point (idontplaydarts 2016 server-side detection swaps payloads on pipes).

---

## 4. Analysis & Discussion

### Patterns across all 7
1. **Two-axis enable/enforce** (SQ2) is the universal rollout primitive — reuse it for *every* new enforcement feature (budgets, circuits, rate limits, agent guards).
2. **Tiered thresholds + forecast** (SQ3) beats static caps; warn-before-block is table stakes, *projection* is the differentiator.
3. **Recursive ancestor validation** (SQ4) is the only correct hierarchical model — every competitor that skipped it shipped a parent-bypass bug (LiteLLM #17334).
4. **OTel, not bespoke** (SQ5/SQ6) — emit standard signals, let users route to their sink (S3/BigQuery/Grafana). Avoid Pushgateway.
5. **Credential chain, env-last** (SQ7) — security by default without breaking the happy path.
6. **Verify-or-useless** (SQ7) applies to *all* of this: every claim must have a re-runnable `backstop verify` / `proofs/` command. That is the 100× gap.

### Where Backstop is already ahead
In-process enforcement, sub-ms overhead, working Wedge proof tool, hash-chained audit, semantic cache — none of the competitors combine these with *reproducible proof*.

### Where the research was weak (carried as limitations)
- SQ5's canonical-doc claims (CloudEvents/OTel/Vector/Athena/Object Lock/SOC2/GDPR) were not re-fetched → confirm before any spec-level decision.
- ~40 GitHub issue/PR IDs across subagents were not re-verified → resolve URLs before citing in design docs.
- Reddit sentiment was 403-blocked throughout → HN + issue trackers only.
- Several "no vendor ships X" negatives are absence-of-evidence, restated as "not found in surveyed systems".

---

## 5. Conclusions & Implications

1. All 7 improvements are **feasible and well-precedented**; none require novel research.
2. The highest-leverage sequencing: **SQ1 (`verify`) + SQ2 (shadow)** first (they make everything else *trustworthy*), then **SQ3 (webhooks) + SQ4 (hierarchical)** (the cost-control depth), then **SQ5/SQ6 (audit+metrics)** (compliance/observability), then **SQ7 (secrets+supply-chain)** (the trust scar).
3. The 100× gap is achievable *only* if each feature ships with a `verify`/`proofs` command — proof is the product, not a footnote.

---

## 6. Recommendations — Implementation Plan (DO NOT IMPLEMENT YET)

> This is the plan the user asked for. No code changes. Each item lists: what to build, the research-backed design, effort, and the proof command it must ship with.

### Phase A — Trust foundation (Days 1–2, HIGH leverage, LOW–MED effort)
**A1. `backstop verify` command** (`src/backstop/cli.py`)
- Checks: `config` (valid), `provider_auth` (cheap `GET /models` *and* a `--live` real completion through the **wrapped** client), `budget_block` (run a tiny agent loop at a tiny budget, assert it blocks), `isolation` (Wedge: 2 runners, exhaust one, assert other continues), `overhead` (real vs direct p50/p99), `cache_hit` (near-dup prompts).
- Output: `pass`/`warn`/`fail`/`skip` + per-check `fix`; `--json` stable schema; exit `0`, `--strict` escalates warn; stdout=data, stderr=diag; per-check timeouts (5–30s); `--offline` skips live. **Never print secrets** (mask like `gho_****`).
- Proof it ships with: `backstop verify` itself.

**A2. Shadow mode** (`BackstopConfig(shadow=True)` + `ShadowCollector`)
- Two-axis: `filter_enabled` always on; `filter_enforced` off in shadow. Record `would_block`/`would_open_circuit`/`would_throttle` counters + structured log lines (Envoy `enabled`/`ok`/`rate_limited`/`enforced` shape). Stateful (evolve counters like Envoy Gateway shadowMode) so predictions are accurate. Rollout: `RATE_LIMIT_SHADOW` env + kill-switch.
- Proof: `backstop verify --shadow` shows would-block counts == would-be-enforced.

### Phase B — Cost-control depth (Days 3–4, HIGH impact, MED effort)
**B1. Budget webhooks** (`notifications.py` + `WebhookSink`)
- Events: `threshold_crossed` (configurable tiers, default 85/95), `budget_crossed` (block), `projected_exceeded` (**novel**: compute calls-remaining from burn-rate, emit `projected_exceeded_date`/`calls_remaining`). Dedup key `(tenant, threshold)` + atomic in-flight marker (learn from LiteLLM#35800). Fire-and-forget (never block request).
- Delivery: Standard Webhooks shape — HMAC-SHA256 on raw body, `webhook-id` idempotency, retry 5xx/408/429 w/ backoff+jitter, DLQ. **Normalize LiteLLM's beta field names.**
- Proof: `proofs/proof_budget_webhook.py` (starts a local webhook receiver, exhausts budget, asserts 85%→95%→block events arrive in order).

**B2. Hierarchical budgets** (`hierarchical.py` + `TenantBudget` tree)
- Model: recursive usage charged to node + all ancestors; validate every ancestor on every allocation; `most-restrictive-wins` default; opt-in `allow_children_limit_overcommit` (relaxes sum only). Bounded `max_tokens` → pre-reserve (cap headroom to avoid LiteLLM#27509); unbounded → accept 1-request overshoot (documented). Test cases = LiteLLM#17334/#28051/#26204.
- Proof: `proofs/proof_hierarchical.py` (parent cap survives child exhaustion; parent-exhausted blocks child even with child slack).

### Phase C — Compliance & observability (Days 5–6, MED effort)
**C1. Audit → structured sinks** (`audit.py` + `CloudEventsAuditSink`)
- Keep hash-chained local audit as source of truth; wrap each record in a **CloudEvents** envelope; sinks: OTel/Vector → **S3 (Iceberg, Object Lock Compliance) / BigQuery (batch load)**. PII redaction transform (field-level + tokenization) *before* emit. **Route GDPR/WORM retention to counsel** — do not self-prescribe.
- Proof: `proofs/proof_audit_sink.py` (emit N events → assert queryable in a local Iceberg/Athena fixture or BigQuery emulator; assert hash-chain verifies).

**C2. Convergence metrics** (`wedge/metrics.py` + OTel exporter)
- CLI emits OTLP → OTel Collector → `prometheusremotewrite` (PRW 2.0 target). Low-cardinality outcome labels; emit classic *or* OTel exponential histograms (don't assume native-histogram support). Exemplars carry `run_id`/`trace_id`. Grafana dashboard template: weekly convergence-rate + would-block (shadow) panels.
- Proof: `proofs/proof_wedge_metrics.py` (run 10 tasks × 3 runners → assert CONVERGED/PARTIAL/DIVERGED distribution exported + queryable).

### Phase D — Supply-chain trust (Days 6–7, MED–HIGH effort)
**D1. Secret provider as default** (`secrets.py`)
- `resolve_credentials()` = ordered chain: configured provider(s) → env **last** (warn when used). Wire into transport at call time (not just wrap time). Support Vault/Doppler/1Password/SOPS-GCP-KMS. Keep `SecretProvider` interface, make it the *first* thing tried.
- Proof: `backstop verify --secrets` (asserts resolution via provider, masks output).

**D2. Installer hardening** (`install.sh` + release pipeline)
- Exact-version URLs + `checksums.txt` (verify *before* exec, never raw `curl|sh`); `cosign verify-blob`; SLSA **L2** provenance from hosted build; **SBOM** (syft/cyclonedx); document signer identity in README. Pip/npm packages get lockfile pinning + attestation verification step in CI.
- Proof: release CI job that re-verifies checksum + cosign + attestation on the published artifact.

### Cross-cutting
- Every Phase item ships with a `verify`/`proofs` command → this *is* the 100× gap.
- Re-verify the ~40 GitHub issue IDs and the SQ5 canonical-doc claims before locking the design doc.

---

## 7. Disagreements & Open Questions

**Genuine contradictions (resolved in §3):**
- SQ2↔SQ4 budget pre-reservation (resolved: bounded `max_tokens` only).
- SQ6 Pushgateway "avoid" vs "Prow uses it" (resolved: sanctioned batch-job case, stale-series burden accepted).

**Stated limitations (research weaknesses):**
- SQ5 canonical docs not re-fetched (CloudEvents/OTel/Vector/Athena/Object Lock/SOC2/GDPR) — confirm before spec-level decisions.
- ~40 GitHub issue/PR IDs unverified — resolve URLs before citing.
- Reddit sentiment blocked (HN + issues only).
- "No vendor ships X" negatives are absence-of-evidence.
- Legal/GDPR prescription removed — route to counsel.

**Open questions for implementation:**
- Aggregate ~30s budget + parallel check execution for `verify` (no tool documents this).
- Retry-once-before-fail policy for flaky live checks.
- Native-histogram backend support on target Prometheus (PRW 1.0 vs 2.0).
- GenAI semconv version pinning (Development stability, may flip token.usage to Counter).
- "N calls remaining" forecast accuracy on sparse history (fallback behavior needed).
- GDPR erasure vs WORM reconciliation (counsel).

---

## 8. Full Source List

**SQ1** — pnpm.io/cli/doctor · github.com/wp-cli/doctor-command · vendurehq docs (cli) · microsoft/aspire.dev aspire-doctor · github.com/cli/cli#12891 · github.com/stripe/stripe-cli#1554 · github.com/gptme/gptme#931 · github.com/kiln-ai/kiln#1618 · docs.litellm.ai/docs/proxy/health · github.com/librefang/librefang#201 · github.com/mcp-use/mcp-use#1608 · github.com/homebrew/brew#6017,#234 · news.ycombinator.com/item?id=8411257,8783711,44627116,42252276 · ralph-tui.com/docs/cli/doctor

**SQ2** — kgateway.dev/docs/envoy/security/ratelimit/local · github.com/envoyproxy/envoy#45172 · github.com/envoyproxy/gateway extension_types.md · istio.io/docs/tasks/security/authorization/authz-dry-run · kubernetes.io/blog/2019/01/14 (dry-run), 2021/12/09 (PSA) · kubernetes.io/blog/2019/08/06 (Gatekeeper) · github.com/open-policy-agent/gatekeeper#379,#3569 · docs.litellm.ai/docs/proxy/guardrails, /tutorials/mock_completion · docs.aws.amazon.com/bedrock-agentcore · github.com/traceroot-ai/traceroot#941 · github.com/latitude-dev/latitude-llm#4067 · github.com/posthog/posthog#55868 · github.com/qwenlm/qwen-code#8469 · launchdarkly.com/blog

**SQ3** — docs.litellm.ai/docs/proxy/alerting · portkey.ai/docs (workspace budget) · truefoundry.com/docs/ai-gateway/budgetlimiting · github.com/mlflow/mlflow budget-alerts · docs.helicone.ai/features/alerts · github.com/berriai/litellm#27398,#35800,#32011 · github.com/langwatch/langwatch#1941,#3917 · github.com/multica-ai/multica#6610 · github.com/standard-webhooks/standard-webhooks · svix.com/resources/webhook-university · github.com/microsoft/agent-governance-toolkit (sample repo)

**SQ4** — github.com/kubernetes-sigs/hierarchical-namespaces (HRQ) · ytsaurus.tech/docs/storage/accounts · kubernetes.io/docs/concepts/policy/resource-quotas · projectcapsule.dev/docs · github.com/envoyproxy/ratelimit · github.com/berriai/litellm#17334,#28051,#26204 · www.truefoundry.com/finops · zuplo.com/docs · docs.litellm.ai/docs/proxy/users · github.com/helicone/helicone#5504

**SQ5** — docs.aws.amazon.com/awscloudtrail (log-file-validation) · cloud.google.com/logging/docs/audit · learn.microsoft.com/azure/azure-monitor/logs/log-storage-security · w3c.github.io/notary/spec · docs.opensearch.org/latest/security/audit-logs · cloudevents.io/spec · opentelemetry.io/docs/specs/otel/logs/data-model · vector.dev/docs · docs.fluentbit.io · cloud.google.com/bigquery/docs/streaming · docs.aws.amazon.com/athena/partitions · docs.aws.amazon.com/AmazonS3/object-lock · nvlpubs.nist.gov/NIST.SP.800-53r5 · iso.org/27002

**SQ6** — prometheus.io/docs/practices/pushing, /practices/histograms · github.com/prometheus/pushgateway#19 · prometheus-operator.dev/docs · github.com/actions/actions-runner-controller ADR · opentelemetry.io/docs/concepts/signals/metrics · github.com/open-telemetry/semantic-conventions-genai gen-ai-metrics · github.com/open-telemetry/opentelemetry-collector-contrib#5192 · grafana.com/docs/exemplars · github.com/prometheus/client_python exemplars · langfuse.com/docs

**SQ7** — docs.aws.amazon.com/sdkref/standardized-credentials · cloud.google.com/docs/authentication/application-default-credentials · developer.hashicorp.com/vault/docs/agent (archived) · developer.1password.com/docs/cli/run · docs.doppler.com/docs/accessing-secrets · github.com/getsops/sops · 12factor.net/config · docs.github.com/actions/security-for-github-actions/openid-connect · slsa.dev/spec/v1.0/levels · docs.sigstore.dev · docs.npmjs.com (provenance, registry signatures) · blog.pypi.org/2023-05-23-removing-pgp · docs.pypi.org/trusted-publishers · eslint.org/blog/2018/07/postmortem · en.wikipedia.org/wiki/XZ_Utils_backdoor · www.cisa.gov/sbom · go.dev/ref/mod · idontplaydarts.com/2016/04/detecting-curl-pipe-bash

---

*End of report. This is research + plan only — no implementation performed. Awaiting user go-ahead to execute the Phase A–D plan.*
