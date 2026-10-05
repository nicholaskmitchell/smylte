"""Deterministic readers that run before the model sees a message.

Some mail already carries its meaning as structured data: a calendar invite
says what, when and where in iCalendar, written by a program. Reading that
needs no model — it is free, exact about time zones, and nothing in the email
can talk it into a different answer. A fast path is a pair of functions: one
says whether the message is its kind of message, the other turns it into
proposals. The pipeline runs them in registry order, and the first that
yields a non-empty list decides the message; nothing reaches Anthropic.

**The extension point.** A per-sender parser (a school portal whose mails
always have the same layout, a booking system that puts the date in a fixed
line) is a `FastPath` whose `matches` checks `msg.from_addr` against a domain
and whose `parse` returns proposals; `register` appends it. Returning `[]`
from `parse` is the normal way to decline: the message then continues to the
model as ordinary mail, so a parser only has to handle the layouts it is sure
of. The alternative — a parser that raises when unsure — would make a format
change at the sender stop that sender's mail from being read at all.

Today every fast path produces calendar events (`EventProposal`), because the
only structured source is `.ics`. A fast path that produces tasks would widen
the return type and the pipeline's staging of it; that is deliberately not
built until there is a parser that needs it.

Note that `matches` reads `msg.from_addr` as the message states it. A
per-sender parser that should only trust authenticated mail must check
`authres.verify_sender` itself; the `.ics` path does not need to, because an
invite only ever becomes a suggestion the owner approves.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from . import ics
from .ics import EventProposal
from .message import ParsedMessage

log = logging.getLogger("smylted.mail")


@dataclass(frozen=True)
class FastPath:
    name: str
    matches: Callable[[ParsedMessage], bool]
    parse: Callable[[ParsedMessage], list[EventProposal]]


ICS = FastPath(
    name="ics",
    matches=lambda m: bool(m.calendars),
    parse=lambda m: [e for a in m.calendars for e in ics.parse_ics(a.data)][:ics.MAX_EVENTS],
)

FAST_PATHS: list[FastPath] = [ICS]


def register(fp: FastPath) -> None:
    """Add a fast path after the existing ones (see the module docstring)."""
    FAST_PATHS.append(fp)


def run(msg: ParsedMessage) -> tuple[str, list[EventProposal]] | None:
    """`(name, proposals)` from the first fast path that has any, else None.

    A fast path that raises is skipped, not fatal: a broken parser must cost
    its own shortcut, never the message, which still goes to the model.
    """
    for fp in list(FAST_PATHS):
        try:
            if not fp.matches(msg):
                continue
            proposals = fp.parse(msg)
        except Exception as exc:  # noqa: BLE001 — see the docstring
            log.warning("mail: fast path %s failed (%s); reading the message normally",
                        fp.name, type(exc).__name__)
            continue
        if proposals:
            return fp.name, list(proposals)
    return None
