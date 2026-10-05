"""Email → suggested tasks.

Reads the owner's mail over IMAP (Proton Mail Bridge, in practice), finds the
messages that ask them to do something or invite them to something, and stages
each as a SUGGESTION — a task, an update to a task they already have, or a
calendar event — that becomes real only when they approve it. Nothing in this
package writes a task on its own: the model it calls has no tool that touches
Smylte, and the only writes the pipeline makes are to its own sidecar tables.

The modules, in the order a message meets them:

    imap.py       the IMAP connection: TLS with a pinned certificate, read-only
                  EXAMINE, BODY.PEEK — nothing is marked read for Thunderbird
    message.py    RFC 822 → text, quoted replies stripped, ledger key and
                  thread identity
    addresses.py  one answer to "is this the same sender", and the three
                  pattern shapes the allow/deny lists use
    authres.py    whether Proton's own Authentication-Results vouch for From
    fastpaths.py  deterministic parsers that skip the model (.ics today)
    llm.py        the one extraction call and the one dedup call
    kindrules.py  task or event: the model's call, or the owner's rules
    pipeline.py   the stages, the ledger and the scan loop (start here)
    review.py     approve and reject — the only path to a real task
    secrets.py    the write-only Anthropic key and Bridge password
    redact.py     keeps both out of every log line and error
    settings.py   the configuration, as stored and as validated
    routes.py     the Settings and Suggested endpoints
"""
