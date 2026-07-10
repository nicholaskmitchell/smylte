# Round-trip fidelity corpus

Realistic VTODO `.ics` fixtures, one per foreign client, used by the load-bearing
fidelity test (spec §8). Each is hand-authored to mirror the *shape* of what that
client actually emits, deliberately loaded with the properties most likely to be
mangled on a naive round-trip:

| file | stresses |
|---|---|
| `tasks_org.ics` | dmfs `X-DMFS-*`, `RELATED-TO;RELTYPE=PARENT`, nested `CATEGORIES`, escaped `\,`/`\n`, non-ASCII (café), `VALARM` |
| `thunderbird.ics` | `X-MOZ-GENERATION`/`X-MOZ-LASTACK`, a full `VTIMEZONE` subcomponent, `DUE;TZID=…`, alarm-level X-props, non-ASCII (naïve) |
| `jtx_board.ics` | `GEO`, `COLOR`, quoted param with a comma (`ORGANIZER;CN="Doe, Jane"`), `RELATED-TO;RELTYPE=CHILD`, `X-JTX-*` |
| `icloud.ics` | `X-APPLE-SORT-ORDER`, `ATTACH;VALUE=URI`, `VALARM` with `ACKNOWLEDGED`/`UID`/`X-WR-ALARMUID` |

**These are representative, not captured.** The §6 recurrence investigation
requires *real* device captures (Tasks.org via DAVx⁵, Thunderbird) — when those
are collected, drop them in here to harden the suite further. Apple dropped CalDAV
VTODO in iOS 13, so `icloud.ics` represents a legacy export, included per §8.
