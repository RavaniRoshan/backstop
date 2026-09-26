"""Runaway eval loop — the loud blowup AND the quiet regression, which need two
different mechanisms.

Persona: an AI/ML engineer iterating prompts and running eval loops, at a
company of any size. Two separate failures, and they are not the same failure:

  * 02:40, a recursive agent loop kept calling the model until the credit card
    noticed. One hard token ceiling, enforced before dispatch, ends it.
  * A prompt edit silently tripled cost per task. Nothing blew up, nothing
    alerted, and nobody noticed for thirteen days. That one is a ratio, and a
    ratio needs a baseline and a window.

Storyline, mapped onto the normative 8-phase grid:
  1 cold open    the loud one and the quiet one
  2 submit       run it
  3 stream       wrap the eval loop, turn the ledger on
  4 ceiling      the hard cap, reserved pre-dispatch from an estimate
  5 regress      tokens per task, 3.0x, thirteen days late
  6 honest       a signal cannot stop a request, in either mode
  7 dense        the two signals, per key, and the export that found them
  8 settle       one ceiling, one soft signal

Real repo facts on screen: `Backstop.wrap(client, budget=...)`, the pre-dispatch
estimate (`chars_per_token=4.0` plus `default_max_output_tokens=1024`),
`auto_token_count`, `BudgetExceededError` subclassing `OpenAIError`, the
`backstop demo` figures (10 calls attempted, 3 served, 7 blocked, 250 -> 75
tokens), the four detectors and what each one compares, `detection_shadow=True`
by default, `BACKSTOP_DETECTION_SHADOW`, `detection_max_keys=1024` LRU, and the
`observed` / `threshold` pair on a `DetectionSignal`. The $612, the 4,100 and
12,300 tok/task figures and the thirteen days are this team's scenario.
"""

from render import Phase, Row

OUT_NAME = "runaway-eval-loop.gif"


def R(kind, text, dot="", indent=0, pill=""):
    return Row(kind=kind, text=text, dot=dot, indent=indent, pill=pill)


BRIEF = {
    # ---- window chrome + header -------------------------------------------
    "window_title": "Eval loop",
    "product": "backstop",
    "version": "v0.6.0",
    "model": "gpt-4o",
    "path": "~/pinned/eval-harness",
    "branch": "exp/prompt-v9",
    "command": "backstop demo",
    "command_hint": "demo",
    "submitted": False,

    # ---- beats -----------------------------------------------------------
    "phases": [
        # 1. cold open (frames 0-2)
        Phase(
            rows=[
                R("dim", "02:40: recursive loop, 8 hours, $612"),
                R("dim", "and a prompt edit that tripled cost/task"),
            ],
            status="/demo",
        ),

        # 2. submit (frames 3-20)
        Phase(
            rows=[
                R("action", "Run", "run", 0, "->|"),
                R("dim", "offline mock transport. no key needed."),
            ],
            status="Thinking on (tab to toggle)",
        ),

        # 3. thinking / stream begins (frames 21-74)
        Phase(
            rows=[
                R("running", "Reading eval/runner.py... (esc to interrupt)", "run", 0, "<-"),
                R("dim", "Next: ceiling, detect, shadow"),
                R("action", "Read(eval/runner.py)", "ok"),
                R("dim", "while not converged: call the model"),
                R("action", "Backstop.wrap(client, budget=50_000)", "ok"),
                R("dim", "one wrap call. no call-site edits."),
                R("action", "Read(prompts/v8.md)", "ok"),
                R("dim", "1,200 rows x 6 turns, no ceiling"),
                R("action", "ledger_enabled=True, ledger_path=...", "ok"),
                R("thought", "the loop had no stopping condition.", "", 0),
            ],
            scroll_at={6: 1},
        ),

        # 4. the hard ceiling (frames 75-143)
        Phase(
            rows=[
                R("action", "Reserve(ceiling=50,000 tokens)", "ok"),
                R("dim", "taken before dispatch, from an estimate"),
                R("action", "estimate = chars/4 + max_out", "ok"),
                R("dim", "default_max_output_tokens=1024"),
                R("action", "auto_token_count=True", "ok"),
                R("dim", "tiktoken when installed, else chars/4"),
                R("action", "BudgetExceededError", "ok"),
                R("dim", "subclasses OpenAIError: your except works"),
                R("action", "10 calls served, 7 blocked", "ok"),
                R("dim", "250 -> 75 tokens, 0 calls for the 7"),
                R("thought", "the loud blowup ends at a number.", "", 0),
            ],
            scroll_at={8: 1},
        ),

        # 5. the quiet one (frames 144-195)
        Phase(
            rows=[
                R("running", "Tokens per task, 14 days of evals", "run"),
                R("action", "v8 baseline: 4,100 tok/task", "ok"),
                R("dim", "mean over 900 evals, the older half"),
                R("action", "v9 landed: 12,300 tok/task", "err"),
                R("dim", "x3.00. no alert fired for 13 days."),
                R("error", "Detect(drift)"),
                R("dim", "recent half vs older half of the window"),
                R("action", "Detect(velocity)", "ok"),
                R("dim", "priced dollars per minute, same window"),
                R("action", "Detect(context_growth)", "ok"),
                R("dim", "this request vs the rest of the window"),
            ],
            scroll_at={6: 1},
        ),

        # 6. the honest part (frames 196-252)
        Phase(
            rows=[
                R("action", "A signal cannot stop a request", "err", 0, "<-"),
                R("dim", "no code path in the detector does"),
                R("action", "Not in enforcing mode either", "err"),
                R("dim", "what a record is worth is the caller's call"),
                R("action", "detection_shadow=True by default", "ok"),
                R("dim", "signals filed in a bounded ring, per key"),
                R("action", "13 days of shadow, then tune", "ok"),
                R("dim", "every threshold is a BackstopConfig field"),
            ],
            scroll_at={6: 1},
        ),

        # 7. dense resolution (frames 253-340)
        Phase(
            rows=[
                R("action", "Signal(drift, severity=warning)", "ok"),
                R("dim", "observed 93,100  threshold 61,500"),
                R("action", "Signal(context_growth, critical)", "ok"),
                R("dim", "200,000 input against a 20,000 median"),
                R("action", "Key(agent=refund-bot)", "ok"),
                R("dim", "a window per key, LRU-capped at 1,024"),
                R("action", "Export(--group-by agent,experiment)", "ok"),
                R("dim", "the silent regression, per experiment"),
                R("thought", "the quiet tripling is the dearer one.", "", 0),
            ],
            scroll_at={8: 1},
        ),

        # 8. settle + end card (frames 341-413)
        Phase(
            rows=[
                R("action", "Two problems, two mechanisms", "ok"),
                R("dim", "one hard ceiling  one soft signal"),
                R("action", "Loud: 7 of 10 calls blocked", "ok"),
                R("dim", "before dispatch, not after the invoice"),
                R("action", "Silent: drift 3.0x, 13 days late", "ok"),
                R("dim", "shadow first, enforce once it is tuned"),
                R("action", "Settled", "ok"),
                R("dim", "the ceiling stops. the signal explains."),
            ],
        ),
    ],
}
