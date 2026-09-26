"""Major end-to-end demo — the flagship GIF for the marketing site.

Persona: a backend architect at a ~500-person AI company who has just been sent
a six-figure provider invoice and cannot answer "which team spent it".

Storyline, mapped onto the normative 8-phase grid:
  1 cold open    the command is already typed
  2 submit       run it
  3 stream       read the repo, wrap a client, turn on the ledger
  4 ledger       attribution, the spend event, price resolution
  5 aggregate    build the chargeback, hit a real error, shadow the detector
  6 honesty      an unpriced model, the delivery/loss report
  7 dense        export, join revenue, margin, loss accounting
  8 settle       totals and the unattributed share as the end card

Every number on screen is either a real repo fact or a plausible scenario
figure. Nothing is invented to look better than it is - the unpriced row and the
unattributed row are the point of the demo.
"""

from render import Phase, Row

OUT_NAME = "major-end-to-end.gif"


def R(kind, text, dot="", indent=0, pill=""):
    return Row(kind=kind, text=text, dot=dot, indent=indent, pill=pill)


BRIEF = {
    # ---- window chrome + header -------------------------------------------
    "window_title": "Chargeback",
    "product": "backstop",
    "version": "v0.6.0",
    "model": "gpt-4o + claude-sonnet-4",
    "path": "~/acme/payments-agent",
    "branch": "feat/ledger",
    "command": "backstop ledger demo --group-by team,feature",
    "command_hint": "ledger demo",
    "submitted": False,

    # ---- beats -----------------------------------------------------------
    "phases": [
        # 1. cold open (frames 0-2)
        Phase(
            rows=[
                R("dim", "1,967 requests since midnight"),
                R("dim", "invoice closed. nobody can attribute it."),
            ],
            status="/ledger demo",
        ),

        # 2. submit (frames 3-20)
        Phase(
            rows=[
                R("action", "Run", "run", 0, "->|"),
                R("dim", "offline. no key, no network."),
            ],
            status="Thinking on (tab to toggle)",
        ),

        # 3. thinking / stream begins (frames 21-74)
        Phase(
            rows=[
                R("running", "Reading the repo... (esc to interrupt)", "run", 0, "<-"),
                R("dim", "Next: wrap, price, group"),
                R("action", "Read(pyproject.toml)", "ok"),
                R("dim", "backstop-ai 0.6.0, MIT"),
                R("action", "Read(docs/ledger.md)", "ok"),
                R("dim", "1 flag turns the ledger on"),
                R("action", "Wrap(OpenAI())", "ok"),
                R("dim", "client = Backstop.wrap(c, ledger_enabled=True)"),
                R("thought", "Thought for 2s", "", 0),
            ],
            scroll_at={6: 1},
        ),

        # 4. the ledger builds (frames 75-143)
        Phase(
            rows=[
                R("action", "Scope(attribution)", "ok"),
                R("dim", 'team=payments feature=checkout-v2'),
                R("action", "Emit(SpendEvent v1.0)", "ok"),
                R("dim", "18 fields, 13 attribution dims"),
                R("action", "Price(gpt-4o)", "ok"),
                R("dim", "in 2.50 / out 10.00 per Mtok"),
                R("action", "Price(cache_read)", "ok"),
                R("dim", "cached tokens billed at 1.25/1.00"),
                R("action", "Price(claude-sonnet-4)", "ok"),
                R("dim", "in 3.00 / out 15.00 per Mtok"),
                R("thought", "Decimal end to end. no floats.", "", 0),
            ],
            scroll_at={8: 1},
        ),

        # 5. aggregate + a real failure (frames 144-195)
        Phase(
            rows=[
                R("running", "Grouping by team,feature... ", "run"),
                R("action", "Group(payments/checkout-v2)", "ok"),
                R("dim", "388 req  $26.21"),
                R("action", "Group(support/triage)", "ok"),
                R("dim", "240 req  $1.76"),
                R("error", "Bash(csv --validate)"),
                R("dim", "Error: unquoted comma in cost_centre"),
                R("action", "Fix(writer=csv, quoting=minimal)", "ok"),
                R("dim", "RFC 4180, CRLF, money as 2dp strings"),
            ],
            scroll_at={6: 1},
        ),

        # 6. the honest part (frames 196-252)
        Phase(
            rows=[
                R("action", "Price(vendor-preview-2027)", "err"),
                R("dim", "not in the rate card -> cost = None"),
                R("action", "Count(unpriced_requests)", "ok"),
                R("dim", "34 requests, 1.73% of traffic"),
                R("thought", "never guess a price. show the gap.", "", 0),
                R("action", "Report(delivery)", "ok"),
                R("dim", "submitted 1967  written 1967"),
                R("dim", "dropped 0  errors 0  lost 0"),
            ],
            scroll_at={6: 1},
        ),

        # 7. dense resolution (frames 253-340)
        Phase(
            rows=[
                R("action", "Export(chargeback.csv)", "ok"),
                R("dim", "7 groups, stable column order"),
                R("action", "Join(revenue.csv)", "ok"),
                R("dim", "same group keys, visible (none)"),
                R("action", "Margin(payments/checkout-v2)", "ok"),
                R("dim", "revenue 148,230.00  margin 148,203.79"),
                R("action", "Detect(velocity, drift, retry)", "ok"),
                R("dim", "shadow on: signals recorded, nothing killed"),
                R("action", "Report(unattributed)", "ok"),
                R("dim", "69 requests declared no team"),
                R("thought", "the row a pivot table drops.", "", 0),
            ],
            scroll_at={8: 1},
        ),

        # 8. settle + end card (frames 341-413)
        Phase(
            rows=[
                R("action", "Total(1967 requests)", "ok"),
                R("dim", "10,789,110 in     684,660 out"),
                R("action", "Total(34.56 USD)", "ok"),
                R("dim", "1.54 unattributed = 4.45%"),
                R("action", "Settled", "ok"),
                R("dim", "no proxy. no egress. no guessing."),
            ],
            scroll_at={4: 1},
        ),
    ],
}
