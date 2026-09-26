"""Fleet SLO — a 10x spike and a provider 429 storm, and a 2-second p99 that has
to survive both.

Persona: the platform / SRE lead at an ~800-person company (Series C) running an
agent fleet. At 09:12 traffic went up 10x and the provider started returning 429s.
The fleet had no ceiling of its own, so every worker tried to call the provider at
once, the p99 left the 2.0s SLO, and the queue in front of the provider was the
only thing limiting it.

Storyline, mapped onto the normative 8-phase grid:
  1 cold open    10x, a 429 storm, and a 2.0s p99 SLO
  2 submit       run it
  3 stream       read the fleet, set the AIMD ceiling
  4 admit        three priorities, one gate, starvation protection
  5 trip         a real CircuitBreakerOpenError from the storm
  6 honest       it queues, it does not shed; queue_timeout is your bound
  7 dense        AIMD halving, quota-aware clamp, the queue that held the SLO
  8 settle       protected, and failed fast rather than hammered

Real repo facts on screen: the three `Priority` values and the absence of a
`normal`, the `X-Backstop-Priority` header, `starvation_after_seconds`,
`queue_timeout`, `initial/max_concurrency` and the AIMD step, `quota_aware`,
`circuit_failure_threshold` / `circuit_cooldown_seconds` / the half-open probe,
`queue_wait` split from provider latency, and the `error-storm` harness counts
(50 attempted, 12 provider calls, 8 successes, 42 circuit-blocked, final
concurrency limit 4 — reproduced on this tree, and the figures the README
records). The p99, the queue depth and the latency split are this fleet's
scenario.
"""

from render import Phase, Row

OUT_NAME = "agent-fleet-slo.gif"


def R(kind, text, dot="", indent=0, pill=""):
    return Row(kind=kind, text=text, dot=dot, indent=indent, pill=pill)


BRIEF = {
    # ---- window chrome + header -------------------------------------------
    "window_title": "Fleet SLO",
    "product": "backstop",
    "version": "v0.6.0",
    "model": "claude-sonnet-4",
    "path": "~/kestrel/agent-fleet",
    "branch": "feat/slo-guardrails",
    "command": "backstop harness --scenario error-storm",
    "command_hint": "harness",
    "submitted": False,

    # ---- beats -----------------------------------------------------------
    "phases": [
        # 1. cold open (frames 0-2)
        Phase(
            rows=[
                R("dim", "09:12: 10x traffic, provider 429 storm"),
                R("dim", "p99 SLO is 2.0s. the fleet is queueing."),
            ],
            status="/harness",
        ),

        # 2. submit (frames 3-20)
        Phase(
            rows=[
                R("action", "Run", "run", 0, "->|"),
                R("dim", "local mock provider at a 60% error rate"),
            ],
            status="Thinking on (tab to toggle)",
        ),

        # 3. thinking / stream begins (frames 21-74)
        Phase(
            rows=[
                R("running", "Reading fleet config... (esc to interrupt)", "run", 0, "<-"),
                R("dim", "Next: priority, AIMD, breaker"),
                R("action", "Read(services/agent/runner.py)", "ok"),
                R("dim", "8 workers, no ceiling of their own"),
                R("action", "initial_concurrency=8, max=64", "ok"),
                R("dim", "AIMD: +1 on success, x0.5 on pressure"),
                R("action", "aimd_adjustment_interval=5.0", "ok"),
                R("dim", "at most one step per 5s, either way"),
                R("thought", "the fleet had no ceiling at all.", "", 0),
            ],
            scroll_at={6: 1},
        ),

        # 4. priority admission (frames 75-143)
        Phase(
            rows=[
                R("action", "Priority: critical|default|background", "ok"),
                R("dim", "three levels. there is no 'normal'."),
                R("action", "Header(X-Backstop-Priority)", "ok"),
                R("dim", "read per request, inside the transport"),
                R("action", "Gate.acquire(critical)", "ok"),
                R("dim", "takes the next freed slot, always"),
                R("action", "Gate.acquire(background)", "ok"),
                R("dim", "waits its turn. it is NOT discarded."),
                R("action", "starvation_after_seconds=1.0", "ok"),
                R("dim", "oldest ticket wins, even behind critical"),
                R("thought", "a priority queue, not a shedder.", "", 0),
            ],
            scroll_at={8: 1},
        ),

        # 5. the storm trips it (frames 144-195)
        Phase(
            rows=[
                R("running", "Harness: error-storm, 60% provider errors", "run"),
                R("action", "Harness(error-storm)", "ok"),
                R("dim", "50 attempted  12 provider calls"),
                R("error", "CircuitBreakerOpenError"),
                R("dim", "429s -> fail fast, not a retry storm"),
                R("action", "circuit_failure_threshold=0.20", "ok"),
                R("dim", "20% failures in a 60s window opens it"),
                R("action", "OPEN -> 30s cooldown -> one probe", "ok"),
                R("dim", "half-open takes one request, then decides"),
            ],
            scroll_at={6: 1},
        ),

        # 6. the honest part (frames 196-252)
        Phase(
            rows=[
                R("action", "It queues. it does not shed.", "err", 0, "<-"),
                R("dim", "no waiter is cancelled or discarded"),
                R("action", "queue_timeout defaults to None", "err"),
                R("dim", "so by default a waiter can wait forever"),
                R("action", "Set queue_timeout=2.0", "ok"),
                R("dim", "then a waiter gets an error, not silence"),
                R("action", "Latency: queue wait vs provider", "ok"),
                R("dim", "total - queue_wait = provider_latency_ms"),
            ],
            scroll_at={6: 1},
        ),

        # 7. dense resolution (frames 253-340)
        Phase(
            rows=[
                R("action", "AIMD limit 8 -> 4", "ok"),
                R("dim", "0.5x a step, floored at min_concurrency=1"),
                R("action", "quota_aware=True, the default", "ok"),
                R("dim", "reads x-ratelimit-*, clamps before 429"),
                R("action", "Queue depth 12", "ok"),
                R("dim", "8 background  4 default  0 critical"),
                R("action", "p99 1.9s against a 2.0s SLO", "ok"),
                R("dim", "queue wait 0.41s  provider 1.49s"),
                R("thought", "the SLO held because it queued.", "", 0),
            ],
            scroll_at={8: 1},
        ),

        # 8. settle + end card (frames 341-413)
        Phase(
            rows=[
                R("action", "Protected(2.0s SLO)", "ok"),
                R("dim", "p99 1.9s  queue wait 0.41s"),
                R("action", "42 failed fast, 0 hammered", "ok"),
                R("dim", "12 provider calls for 50 requests"),
                R("action", "Settled", "ok"),
                R("dim", "queued, not shed. starved, not lost."),
            ],
        ),
    ],
}
