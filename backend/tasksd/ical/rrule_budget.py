"""A step budget for dateutil's rrule walk.

The problem this exists for: `dateutil` bounds an RRULE by UNTIL and COUNT, and
both tests live *inside* the yield blocks of `rrule._iter`. The only check on the
outer loop is `year > MAXYEAR`. So a rule that never produces an instance never
reaches either bound and walks to the year-9999 terminus — measured at 3.4-5.5 s
per rule, returning nothing. Neither UNTIL nor COUNT helps:

    FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30                  3.50s -> 0 occurrences
    the same, + UNTIL=20260802T000000                   3.44s -> 0
    the same, + COUNT=5                                 3.45s -> 0

Feb 30 never exists, so nothing is ever generated to test the bound against.

WHY A COST BOUND AND NOT A SATISFIABILITY CHECK. Deciding "can this rule ever
match" is the obvious repair and it does not work: the never-matching family is
much wider than the BYMONTH x BYMONTHDAY pairs it is tempting to enumerate.
`FREQ=DAILY;BYSETPOS=5;BYDAY=MO`, `BYWEEKNO=54`, and
`BYWEEKNO=53;BYMONTH=1;BYDAY=MO` (week 53's Monday is always in December, so it
can never be in January) all defeat such a table and all still cost seconds. And
the check errs both ways — `BYMONTH=4,5;BYMONTHDAY=31` IS satisfiable, on May 31,
so a naive table would refuse a legitimate rule.

Bounding the *cost* instead sidesteps the whole question. Anything that finishes
inside the budget is cheap by construction whether or not it ever matches; a
never-matching rule that happens to be cheap is simply allowed to finish, which
is correct. What it buys is that no rule can be expensive, which is the actual
security property — the read path is reachable unauthenticated through the
public booking page, under the global service lock.

WHERE IT HOOKS. `_iterinfo.rebuild(year, month)` is called once per period for
YEARLY/MONTHLY and once per month rollover for everything shorter, so it fires
unconditionally on a runaway walk and a handful of times on an ordinary one.
Measured overhead on real rules is 0.3-3.6%.

It is a private attribute of a third-party library, which is a real fragility: a
future dateutil that renames it turns this into a silent no-op. Hence the
import-time check below, and `test_the_budget_actually_fires` — a test that the
guard *works*, not merely that this module imports.
"""
from __future__ import annotations

import contextlib
import logging
import threading

from dateutil import rrule as _rrule

log = logging.getLogger("tasksd.ical")


class SearchBudgetExceeded(BaseException):
    """A walk ran past its step budget.

    Deliberately a BaseException, not an Exception. Every layer between the walk
    and the call site catches Exception generously — `service.sync_all`,
    `_upsert_body`, and `recurring_ical_events`' own handlers — and a budget
    signal that gets swallowed mid-walk leaves the walk running, which is the
    bug. This has to reach the `search_budget` block that armed it and be
    converted there, deliberately, into the caller's own vocabulary.
    """


_state = threading.local()


@contextlib.contextmanager
def search_budget(steps: int):
    """Allow `steps` rrule periods inside this block, on this thread.

    Nesting restores the outer budget rather than clearing it, so an inner call
    cannot hand an outer one an unbounded walk. Outside any block the wrapper is
    a no-op, so nothing else in the process is affected by this module existing.
    """
    previous = getattr(_state, "left", None)
    _state.left = int(steps)
    try:
        yield
    finally:
        if previous is None:
            del _state.left
        else:
            _state.left = previous


def _install() -> None:
    """Wrap `_iterinfo.rebuild` once, counting each period against the budget."""
    info = getattr(_rrule, "_iterinfo", None)
    original = getattr(info, "rebuild", None)
    if original is None:
        log.error(
            "dateutil's rrule._iterinfo.rebuild is missing, so recurrence "
            "expansion is UNBOUNDED: a rule that never matches will walk to "
            "year 9999. See tasksd/ical/rrule_budget.py."
        )
        return
    if getattr(original, "_tasksd_budgeted", False):
        return

    def rebuild(self, year, month, *a, **kw):
        left = getattr(_state, "left", None)
        if left is not None:
            if left <= 0:
                raise SearchBudgetExceeded(
                    "the rule searched past its step budget without producing "
                    "an occurrence"
                )
            _state.left = left - 1
        return original(self, year, month, *a, **kw)

    rebuild._tasksd_budgeted = True
    info.rebuild = rebuild


_install()
