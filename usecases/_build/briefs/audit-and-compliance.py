"""Audit and compliance — two signatures, and neither of them is a dashboard.

Persona: a security & compliance engineer at a ~1200-person regulated fintech.
Two blockers, from two different departments, neither of which a cost report
answers:

  * Finance will not sign off on AI spend they cannot reconcile to a GL code.
  * Legal will not approve prompts leaving the host, and will not approve an
    enforcement decision they cannot audit after the fact.

Storyline, mapped onto the normative 8-phase grid:
  1 cold open    finance will not sign; legal will not approve
  2 submit       run it
  3 stream       turn on the chained audit log, keep the key in a secret store
  4 chain        HMAC over each payload plus the previous record's chain
  5 egress       where the bytes go, and what is not in the record
  6 honest       the log is tamper-evident, not tamper-proof, and cannot
                 reconcile an invoice for you
  7 dense        the GL tie, and the row finance must be told about
  8 settle       prove the spend, admit the gaps

Real repo facts on screen: `audit_enabled` / `audit_sink` / `audit_hmac_key`, the
`chain = SHA256(HMAC[key](prev + payload))` construction in
`src/backstop/audit.py`, `AuditLog.verify()` replaying the chain, the exact
decision / reason pairs the transport records (`deny` with `budget_exceeded`,
`circuit_open`, `rate_limited` or `agent_guardrail`; `fallback`; `downgrade`),
the 18 `SpendEvent` fields with no content field, `Backstop.wrap()` adding no
network hop, the endpoint normalisation, the RFC 4180 / CRLF / 2dp-string CSV,
the 13 legal `--group-by` dimensions with an unknown one rejected as an argparse
error, `(unattributed)` never rendering blank, and the absence of a totals row.
The 1,265 requests, the GL codes and the dollar figures are this firm's
scenario.
"""

from render import Phase, Row

OUT_NAME = "audit-and-compliance.gif"


def R(kind, text, dot="", indent=0, pill=""):
    return Row(kind=kind, text=text, dot=dot, indent=indent, pill=pill)


BRIEF = {
    # ---- window chrome + header -------------------------------------------
    "window_title": "Audit",
    "product": "backstop",
    "version": "v0.6.0",
    "model": "gpt-4.1",
    "path": "~/meridian/core-llm",
    "branch": "feat/audit-chain",
    "command": "backstop ledger export --path ledger.jsonl --out chargeback.csv",
    "command_hint": "ledger export",
    "submitted": False,

    # ---- beats -----------------------------------------------------------
    "phases": [
        # 1. cold open (frames 0-2)
        Phase(
            rows=[
                R("dim", "finance will not sign off on AI spend"),
                R("dim", "legal will not approve prompts leaving us"),
            ],
            status="/ledger export",
        ),

        # 2. submit (frames 3-20)
        Phase(
            rows=[
                R("action", "Run", "run", 0, "->|"),
                R("dim", "reads your own file. no key, no network."),
            ],
            status="Thinking on (tab to toggle)",
        ),

        # 3. thinking / stream begins (frames 21-74)
        Phase(
            rows=[
                R("running", "Wrapping the client... (esc to interrupt)", "run", 0, "<-"),
                R("dim", "Next: chain, egress, export"),
                R("action", "Read(app/llm/client.py)", "ok"),
                R("dim", "one construction site, 40 call sites"),
                R("action", "audit_enabled=True", "ok"),
                R("dim", "audit_sink='audit.jsonl' + audit_hmac_key"),
                R("action", "the key lives in a secret store", "ok"),
                R("dim", "the key is never written to the log"),
                R("thought", "a log nobody can quietly edit.", "", 0),
            ],
            scroll_at={6: 1},
        ),

        # 4. the chain (frames 75-143)
        Phase(
            rows=[
                R("action", "Record(deny, budget_exceeded)", "ok"),
                R("dim", "ts, decision, reason, tenant_id, model"),
                R("action", "chain = SHA256(HMAC[k](prev + body))", "ok"),
                R("dim", "prev is the previous record's chain hash"),
                R("action", "Record(fallback)", "ok"),
                R("dim", "every decision is chained the same way"),
                R("action", "Record(downgrade | rate_limited)", "ok"),
                R("dim", "agent_guardrail denials land here too"),
                R("action", "AuditLog.verify(lines)", "ok"),
                R("dim", "replays the chain, returns one bool"),
                R("thought", "tamper-evident, not tamper-proof.", "", 0),
            ],
            scroll_at={8: 1},
        ),

        # 5. egress (frames 144-195)
        Phase(
            rows=[
                R("running", "Tracing every outbound byte...", "run"),
                R("action", "The SDK's own transport still sends", "ok"),
                R("dim", "backstop wraps it, it does not replace it"),
                R("action", "Egress: api.openai.com, nothing else", "ok", 0, "<-"),
                R("error", "Prompt text is not a SpendEvent field"),
                R("dim", "18 fields, every one a measurement"),
                R("action", "No proxy, no relay, no key forwarding", "ok"),
                R("dim", "backstop serve is a different, opt-in mode"),
                R("action", "Endpoint normalised before storage", "ok"),
                R("dim", "no query string, no fragment, no user:pass@"),
            ],
            scroll_at={6: 1},
        ),

        # 6. the honest part (frames 196-252)
        Phase(
            rows=[
                R("action", "ts is a wall clock, not an anchor", "err"),
                R("dim", "no external time source is consulted"),
                R("action", "Anyone with the key can re-chain it", "err"),
                R("dim", "the chain proves order, not authorship"),
                R("action", "Retention is your filesystem", "err"),
                R("dim", "one file per process, no rotation, no query"),
                R("action", "Ledger-to-invoice variance: not built", "err"),
                R("dim", "show reads our file. not your invoice."),
                R("action", "Reconcile it by hand, for now", "ok"),
                R("dim", "that gap is documented, not hidden"),
            ],
            scroll_at={6: 1},
        ),

        # 7. dense resolution (frames 253-340)
        Phase(
            rows=[
                R("action", "Export(chargeback.csv)", "ok"),
                R("dim", "RFC 4180, CRLF, money as 2dp strings"),
                R("action", "--group-by gl_code", "ok"),
                R("dim", "13 legal dimensions, unknown is exit 2"),
                R("action", "Row(gl_code=6420, team=payments)", "ok"),
                R("dim", "1,204 req  8.9M tok  233.71 USD"),
                R("action", "Row(gl_code=(unattributed))", "err"),
                R("dim", "61 req  14.02 USD, nobody to charge"),
                R("action", "No totals row in the CSV", "ok"),
                R("dim", "a SUM() over that table double counts"),
            ],
            scroll_at={8: 1},
        ),

        # 8. settle + end card (frames 341-413)
        Phase(
            rows=[
                R("action", "Reconciled(1,265 requests)", "ok"),
                R("dim", "1,204 attributed  61 unattributed"),
                R("action", "Chain intact: verify() -> True", "ok"),
                R("dim", "2,190 decisions, 0 unchained"),
                R("action", "Settled", "ok"),
                R("dim", "prove the spend. admit the gaps."),
            ],
        ),
    ],
}
