# Round-trip fidelity corpus

Realistic `.ics` fixtures, one per foreign client, used by the load-bearing
fidelity test (spec §8). `test_fidelity.py` splits them by component — read from
the bytes, not the filename — so dropping a real capture in here is all it takes
to widen the suite. Each is hand-authored to mirror the *shape* of what that
client actually emits, deliberately loaded with the properties most likely to be
mangled on a naive round-trip:

| file | stresses |
|---|---|
| `tasks_org.ics` | dmfs `X-DMFS-*`, `RELATED-TO;RELTYPE=PARENT`, nested `CATEGORIES`, escaped `\,`/`\n`, non-ASCII (café), `VALARM` |
| `thunderbird.ics` | `X-MOZ-GENERATION`/`X-MOZ-LASTACK`, a full `VTIMEZONE` subcomponent, `DUE;TZID=…`, alarm-level X-props, non-ASCII (naïve) |
| `jtx_board.ics` | `GEO`, `COLOR`, quoted param with a comma (`ORGANIZER;CN="Doe, Jane"`), `RELATED-TO;RELTYPE=CHILD`, `X-JTX-*` |
| `icloud.ics` | `X-APPLE-SORT-ORDER`, `ATTACH;VALUE=URI`, `VALARM` with `ACKNOWLEDGED`/`UID`/`X-WR-ALARMUID` |
| `thunderbird_event.ics` | **VEVENT.** A recurring series with `VTIMEZONE`, `EXDATE`, `RDATE`, a `RECURRENCE-ID` override, `ORGANIZER;CN="Doe, Jane"`, two `ATTENDEE`s with parameters, `VALARM`, `CLASS`/`TRANSP`/`URL`, `X-MOZ-*` |
| `apple_event.ics` | **VEVENT.** A `FREQ=MONTHLY;BYDAY=2TU` series across a DST boundary in `Europe/London`, override on the **second** occurrence, `EXDATE` on the fourth, `X-APPLE-STRUCTURED-LOCATION` with five parameters and a quoted comma, `ATTACH;VALUE=URI`, `SCHEDULE-STATUS`, `VALARM` with `ACKNOWLEDGED`/`X-WR-ALARMUID`, non-ASCII (Café, Zoë) |

The event file exists because every other file here is VTODO-only, and the
fidelity suite is driven off this directory — so invariant #2 ("an edit must
leave every foreign property, parameter and subcomponent intact") was graded by
the independent canonicalizer for the task path and for nothing else, while the
event write surface is the one with the most closed findings in `docs/AUDIT.md`.
`split_series` in particular mints a new resource under a fresh UID, so anything
it drops is gone permanently — no resync restores a UID the server never saw —
and nothing asserted any of it.

The second event file is here because one was not enough to keep the promise
above. The event tests used to address **hard-coded instants** — one file's third
and fourth occurrences, written into the test module as constants — so dropping a
second capture in did not widen the suite, it broke it: `split_series` refused
the foreign anchor outright, and the other three passed *vacuously*, minting an
override for an instant the series never produces, EXDATE-ing a slot that was
never an occurrence, and shifting the whole series by a delta measured from a
date belonging to another file. The anchors are derived per capture now, through
this codebase's own expander, so a capture whose series it cannot read fails
loudly rather than going silently unaddressed. `apple_event.ics` is deliberately
a different shape in every dimension that derivation depends on — a monthly rule
rather than weekly, a different zone and DST direction, and the override on a
different index — so a derivation that quietly re-found the first file's answers
would not pass.

**These are representative, not captured.** The §6 recurrence investigation
requires *real* device captures (Tasks.org via DAVx⁵, Thunderbird) — when those
are collected, drop them in here to harden the suite further. Apple dropped CalDAV
VTODO in iOS 13, so `icloud.ics` represents a legacy export, included per §8.
