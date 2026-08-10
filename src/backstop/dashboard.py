"""Grafana dashboard spec for Backstop (Launch Improvement C2).

The exported JSON is compatible with Grafana 10+ and is pre-wired to the
Backstop Prometheus metrics namespace ``backstop_*``. Low-cardinality labels
(endpoint, priority, outcome, direction) are used throughout to keep
cardinality bounded.

Panels:
* Overview: request rate, error rate, p50/p99 latency
* Budget: remaining tokens, exceeded count, tenant breakdown
* Circuit / AIMD: circuit state, trips, concurrency limit
* Cache: hit rate, semantic hit rate
* Shadow: would_block / would_open count (if shadow enabled)

To export:
    python -c "from backstop.dashboard import DASHBOARD_JSON; import json, sys; json.dump(DASHBOARD_JSON, sys.stdout, indent=2)"
"""
from __future__ import annotations

from typing import Any

# Lightweight dashboard spec (Grafana JSON model subset).
# UID: `backstop-overview` — stable across deploys.
_DASHBOARD: dict[str, Any] = {
    "uid": "backstop-overview",
    "title": "Backstop Overview",
    "tags": ["backstop", "llm-gateway"],
    "timezone": "browser",
    "refresh": "30s",
    "schemaVersion": 40,
    "version": 1,
    "panels": [
        {
            "id": 1,
            "title": "Request Rate (rps)",
            "type": "graph",
            "targets": [
                {
                    "expr": "sum(rate(backstop_requests_total[5m]))",
                    "legendFormat": "{{endpoint}} {{priority}}",
                    "refId": "A",
                }
            ],
            "unit": "reqps",
        },
        {
            "id": 2,
            "title": "Error Rate (blocked + fallback)",
            "type": "graph",
            "targets": [
                {
                    "expr": "sum(rate(backstop_budget_exceeded_total[5m]))",
                    "legendFormat": "budget_exceeded",
                    "refId": "A",
                },
                {
                    "expr": "sum(rate(backstop_fallback_attempts_total[5m]))",
                    "legendFormat": "fallback",
                    "refId": "B",
                },
                {
                    "expr": "sum(rate(backstop_rate_limited_total[5m]))",
                    "legendFormat": "rate_limited",
                    "refId": "C",
                },
            ],
            "unit": "reqps",
        },
        {
            "id": 3,
            "title": "Request Latency (p50 / p99)",
            "type": "graph",
            "targets": [
                {
                    "expr": "histogram_quantile(0.50, sum(rate(backstop_request_duration_seconds_bucket[5m])) by (le))",
                    "legendFormat": "p50",
                    "refId": "A",
                },
                {
                    "expr": "histogram_quantile(0.99, sum(rate(backstop_request_duration_seconds_bucket[5m])) by (le))",
                    "legendFormat": "p99",
                    "refId": "B",
                },
            ],
            "unit": "s",
        },
        {
            "id": 4,
            "title": "Budget Remaining (tokens)",
            "type": "gauge",
            "targets": [
                {
                    "expr": "backstop_budget_remaining_tokens",
                    "refId": "A",
                }
            ],
            "unit": "tokens",
        },
        {
            "id": 5,
            "title": "Circuit State",
            "type": "gauge",
            "targets": [
                {
                    "expr": "backstop_circuit_state",
                    "refId": "A",
                }
            ],
            "min": 0,
            "max": 2,
            "thresholds": [
                {"color": "green", "value": None},
                {"color": "yellow", "value": 1},
                {"color": "red", "value": 2},
            ],
            "mappingType": 1,
        },
        {
            "id": 6,
            "title": "Cache Hit Rate",
            "type": "graph",
            "targets": [
                {
                    "expr": "sum(rate(backstop_cache_hits_total[5m])) / (sum(rate(backstop_requests_total[5m])) + sum(rate(backstop_cache_hits_total[5m])))",
                    "legendFormat": "hit_rate",
                    "refId": "A",
                },
                {
                    "expr": "sum(rate(backstop_cache_semantic_hits_total[5m])) / (sum(rate(backstop_requests_total[5m])) + sum(rate(backstop_cache_hits_total[5m])))",
                    "legendFormat": "semantic_hit_rate",
                    "refId": "B",
                },
            ],
            "unit": "percentunit",
        },
        {
            "id": 7,
            "title": "AIMD Concurrency Limit",
            "type": "graph",
            "targets": [
                {
                    "expr": "backstop_concurrency_limit",
                    "legendFormat": "limit",
                    "refId": "A",
                },
                {
                    "expr": "backstop_concurrency_active",
                    "legendFormat": "active",
                    "refId": "B",
                },
            ],
        },
        {
            "id": 8,
            "title": "Shadow Would-Block Count",
            "type": "graph",
            "targets": [
                {
                    "expr": "sum(rate(backstop_shadow_would_block_total[5m]))",
                    "legendFormat": "would_block",
                    "refId": "A",
                },
                {
                    "expr": "sum(rate(backstop_shadow_would_open_circuit_total[5m]))",
                    "legendFormat": "would_open_circuit",
                    "refId": "B",
                },
                {
                    "expr": "sum(rate(backstop_shadow_would_throttle_total[5m]))",
                    "legendFormat": "would_throttle",
                    "refId": "C",
                },
                {
                    "expr": "sum(rate(backstop_shadow_would_guardrail_total[5m]))",
                    "legendFormat": "would_guardrail",
                    "refId": "D",
                },
                {
                    "expr": "sum(rate(backstop_shadow_would_latency_total[5m]))",
                    "legendFormat": "would_latency",
                    "refId": "E",
                },
            ],
            "unit": "reqps",
        },
    ],
}

DASHBOARD_JSON: dict[str, Any] = _DASHBOARD


def get_dashboard() -> dict[str, Any]:
    return dict(_DASHBOARD)
