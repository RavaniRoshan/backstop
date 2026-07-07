# Backstop Unicorn COSS Metrics

## North Star

Prevented LLM spend risk in production applications.

This should be measured as a combination of blocked over-budget requests, fallback savings, cache savings, and avoided provider-failure impact.

## OSS Adoption Metrics

| Stage | GitHub Stars | Contributors | External Issues/Discussions | Public Examples | Benchmark Proof |
| --- | ---: | ---: | ---: | ---: | --- |
| Phase 0 | 100 | 2 | 5 | 5 | 1 published benchmark |
| Phase 1 | 500 | 5 | 10+ | 8 | Redis and local benchmarks |
| Phase 2 | 1,000 | 10 | 25+ | 10 | Production pilot results |
| Phase 3 | 2,500+ | 25+ | 75+ | 15+ | Multi-SDK benchmarks |

## Commercial Metrics

| Stage | Pilots | Paid Customers | MRR | Case Studies |
| --- | ---: | ---: | ---: | ---: |
| Phase 0 | 0-1 | 0 | $0 | 0 |
| Phase 1 | 3 | 0-1 | $0-$5k | 1 anonymized |
| Phase 2 | 10 | 3 | $10k-$25k | 2 |
| Phase 3 | 25+ | 25+ | $100k+ | 5 |

## Product Performance Metrics

- Local-mode median overhead: below 1 ms where benchmark environment supports that claim.
- Local-mode p95 overhead: documented and reproducible.
- Redis-mode p95 overhead: documented separately from local mode.
- Budget accuracy under concurrency: no overspend beyond documented tolerance.
- Policy sync propagation: target under 60 seconds for control-plane mode.
- Control-plane outage behavior: SDK continues with last valid policy.
- Telemetry payload safety: prompt payloads off by default.

## Enterprise Readiness Metrics

- Security reporting path exists.
- Threat model exists.
- Compatibility matrix exists.
- Release notes are maintained.
- SDK support policy exists.
- Production deployment guide exists.
- At least one external security review before broad enterprise push.

## Growth Metrics

- README conversion: install command and first working example remain visible above the fold.
- Time to first success: under 15 minutes from clean checkout.
- Issue response time: under 48 hours for serious bugs.
- Release cadence: predictable minor releases, not constant breaking changes.
- Community depth: more than one maintainer able to review PRs.

## Sales Qualification Metrics

Good pilot targets should have:

- LLM API spend above $10k per month.
- Multi-tenant AI product or internal platform.
- Concern about runaway spend or provider instability.
- Reluctance to proxy prompts through a third-party service.
- Engineering team able to deploy SDK changes quickly.

## Metrics To Avoid Optimizing Too Early

- Raw PyPI downloads without active users.
- Number of SDK languages before paid demand exists.
- Dashboard feature count.
- Generic observability breadth.
- Marketplace listings before pilot conversion.
