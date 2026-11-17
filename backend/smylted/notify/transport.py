"""The transport-neutral pieces the scheduler and any sender share.

`clip` holds every message to one cap, and `SendResult` is the outcome a sender
hands back in the form the delivery ledger stores. Neither knows which service
carries the message; the sender (`signal.py`) does.
"""
from __future__ import annotations

from dataclasses import dataclass

# The cap we hold every message to; a notification near it is a report. Søren
# *refuses* a longer message, which is right for a tool — the agent sees the
# refusal and rewrites. Unattended, a refusal is a dropped alert, so we clip
# instead and say so in the text. The real defence is upstream: a notification
# that approaches this is a report, and a report should be a headline plus where
# the detail lives.
MAX_MESSAGE_CHARS = 4096
_CLIP_MARKER = "\n… (clipped)"


def clip(text: str) -> str:
    """Cut `text` to MAX_MESSAGE_CHARS, on a line break where possible."""
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    budget = MAX_MESSAGE_CHARS - len(_CLIP_MARKER)
    head = text[:budget]
    # Prefer the last line break in the final fifth, so we cut between thoughts
    # rather than mid-word; fall back to a hard cut if there is none.
    cut = head.rfind("\n", int(budget * 0.8))
    if cut > 0:
        head = head[:cut]
    return head + _CLIP_MARKER


@dataclass(frozen=True)
class SendResult:
    """What happened, in the form the delivery ledger stores.

    `permanent` is the field the scheduler acts on: a request the transport
    refuses as malformed or unauthorised will fail identically forever, and
    retrying it every minute turns a misconfiguration into a rate-limit ban.
    """
    ok: bool
    message_id: int | None = None
    error: str | None = None          # already redacted; safe to log and store
    attempts: int = 0
    permanent: bool = False
    status: int | None = None         # the last response's HTTP status; None if none came
