# Audit backlog

Open findings from the adversarial audit sweep (13 subsystem finders on Opus, two
independent verifiers per finding, 81 raw findings). Everything here **survived
verification**: a verifier tried to refute it and could not. Nothing here is a
style nit — each one carries a concrete trigger.

What is *not* in this file: the issues already fixed on this branch (all six HIGHs
plus nine others), and the four the owner has scheduled for the current pass
(logout invalidation, booking links outliving their calendar, the Start-time slot,
and task-edit dirty-tracking).

Severity is the verifiers' rating. `minor` marks a fix that is a few
obviously-correct lines needing no design decision — a reasonable place to start.

**0 open.** Every finding from the sweep is fixed and covered by a test. The
evidence stays here — a ticked box records what the bug was and why it
mattered, and the issues that link into these sections still resolve.

## iCalendar read + edit path

### [x] "Repeat until <date>" writes a DATE-valued UNTIL onto a timed series, dropping the last occurrence the user asked for

`backend/tasksd/ical/edit.py:61` · **medium** · bug

`rrule_from_spec` puts the caller's `until` into the rule verbatim. The UI's "Repeat
until" field is `<input type="date">`, and `app._rrule_from_repeat` -> `_parse_datelike`
turns it into a `date`, so a timed event gets `RRULE:...;UNTIL=20260302` while DTSTART
is a DATE-TIME. RFC 5545 3.3.10 requires UNTIL's value type to match DTSTART (and
requires UTC when DTSTART is not floating); expanders read the DATE as midnight, so the
occurrence ON the chosen day is dropped.

<details><summary>Evidence</summary>

```
rrule_from_spec('weekly', until=date(2026,3,2)) with build_new_event(dtstart=2026-02-02 09:00) produces:
  DTSTART:20260202T090000
  RRULE:FREQ=WEEKLY;UNTIL=20260302
expand_occurrences(raw, 2026-01-01, 2026-04-01) -> ['2026-02-02T09:00','2026-02-09T09:00','2026-02-16T09:00','2026-02-23T09:00'] — the 2026-03-02 09:00 occurrence the user explicitly asked to repeat *until* is missing, because UNTIL is read as 2026-03-02T00:00.
```

</details>

**Suggested fix.** Coerce UNTIL to DTSTART's value type: when the series start is a datetime, expand a
supplied `date` to end-of-day in the series' zone (or UTC 23:59:59Z) before writing it;
keep a bare DATE only for all-day series. Add a test asserting the UNTIL day's
occurrence is included.

### [x] _shift_datelike drops property parameters — RECURRENCE-ID;RANGE=THISANDFUTURE silently becomes a single-instance override

`backend/tasksd/ical/edit.py:454` · **medium** · bug · `minor`

`_shift_datelike` deletes the property and re-adds only its value, so every parameter
other than the TZID icalendar re-derives from tzinfo is lost. The one that carries
meaning is `RANGE=THISANDFUTURE` on RECURRENCE-ID (RFC 5545 3.2.13, written by Apple
Calendar and others): it means "this override applies to this and all later
occurrences". After a whole-series reschedule the parameter is gone, so the override
collapses to a single instance and every later occurrence silently reverts to the
master's values. This is exactly the kind of silent semantic loss invariant #2 exists to
prevent, and the fidelity suite never exercises the VEVENT paths so nothing catches it.

<details><summary>Evidence</summary>

```
Input override component:
  RECURRENCE-ID;RANGE=THISANDFUTURE;TZID=America/New_York:20260108T090000
  DTSTART;TZID=America/New_York:20260108T110000
After shift_series(raw, '2026-01-08T09:00:00-05:00', EventEdit(dtstart=2026-01-08 12:00)) the component is:
  RECURRENCE-ID;TZID=America/New_York:20260108T100000   <-- RANGE=THISANDFUTURE gone
Same loss applies to any X- parameter or VALUE parameter a foreign client attached to DTSTART/DTEND/RECURRENCE-ID.
```

</details>

**Suggested fix.** Preserve the original property's `params` across the rewrite: capture `prop.params`
before `_replace`, then `event.add(key, old + delta, parameters={k: v for k, v in
params.items() if k.upper() != 'TZID'})` (let icalendar re-derive TZID from tzinfo).

### [x] RDATE;VALUE=PERIOD makes shift_series and split_series raise TypeError (500 on any series edit)

`backend/tasksd/ical/edit.py:463` · **medium** · bug · `minor`

`_shift_datelist` assumes `entry.dt` is a date/datetime, but for a PERIOD value
icalendar's vDDDTypes.dt is a `(start, end)` tuple. `_partition_datelist` ->
`_at_or_after` has the same assumption. RDATE;VALUE=PERIOD is legal RFC 5545 and arrives
from foreign clients / anyone writing to the shared collection, so a perfectly ordinary
"move the series" or "this & following" on such an event 500s and the user can never
edit that event again.

<details><summary>Evidence</summary>

```
raw = VEVENT with DTSTART:20260101T090000Z, RRULE:FREQ=WEEKLY, RDATE;VALUE=PERIOD:20260210T090000Z/20260210T110000Z.
E.shift_series(raw, '2026-01-01T09:00:00+00:00', EventEdit(dtstart=...)) ->
  File edit.py line 463, in _shift_datelist: values = [entry.dt + delta ...]
  TypeError: can only concatenate tuple (not "datetime.timedelta") to tuple
E.split_series(raw, '2026-01-08T09:00:00+00:00', EventEdit()) ->
  File edit.py line 350, in _at_or_after: return da >= db
  TypeError: '>=' not supported between instances of 'tuple' and 'datetime.date'
```

</details>

**Suggested fix.** Handle the tuple form in both helpers: shift both ends of a period (`(s+delta,
e+delta)`) and compare a period against the anchor using its start.

### [x] Shifting/partitioning EXDATE or RDATE merges several property lines into one and relabels them with a single TZID, corrupting the excluded instants

`backend/tasksd/ical/edit.py:466` · **medium** · bug

`_shift_datelist` (and `_partition_datelist`, same pattern at line 606-608) flattens
every EXDATE/RDATE property line into one Python list and re-adds it as a SINGLE
property. icalendar derives one TZID parameter for the whole property (it takes the last
entry's zone) but serializes each value in its own local wall time, so entries that came
from a different zone get relabelled with the wrong TZID — a different instant. Mixed
EXDATE zones are ordinary in a shared collection (a UTC-written EXDATE next to a TZID-
written one, or exclusions written before/after the user changed the event's zone).

<details><summary>Evidence</summary>

```
Master DTSTART;TZID=America/New_York:20260105T090000, RRULE:FREQ=WEEKLY, EXDATE;TZID=America/New_York:20260112T090000, EXDATE;TZID=Europe/Paris:20260119T150000.
shift_series(raw, '2026-01-05T09:00:00-05:00', EventEdit(dtstart=2026-01-05 10:00, dtend=11:00)) emits:
  EXDATE;TZID=Europe/Paris:20260112T100000,20260119T160000
Parsed EXDATE instants BEFORE: ['2026-01-12T14:00:00+00:00', '2026-01-19T14:00:00+00:00']; AFTER: ['2026-01-12T09:00:00+00:00', '2026-01-19T15:00:00+00:00'] — the first exclusion moved 6 hours off (it should be 15:00Z) and no longer identifies the occurrence for any other CalDAV client.
With a UTC EXDATE next to a TZID one the output is also invalid iCalendar: `EXDATE;TZID=America/New_York:20260119T150000Z,20260126T100000` (RFC 5545 3.2.19 forbids TZID on a UTC value).
```

</details>

**Suggested fix.** Rebuild EXDATE/RDATE per source property line — group values by (tzinfo, value type) and
emit one property per group — instead of `_replace(key)` followed by a single
`event.add(key, values)`.

### [x] RECURRENCE-ID;RANGE=THISANDFUTURE makes several occurrences share one recurrence_id, so the SPA renders duplicate React keys and per-occurrence edit/delete hits the wrong instance

`backend/tasksd/ical/recur.py:115` · **medium** · bug

`_occurrence` derives the instance anchor straight from the expanded component's
RECURRENCE-ID: `anchor = (_iso(rid)[0] if rid is not None else start) or start or ""`.
For a `RECURRENCE-ID;RANGE=THISANDFUTURE` override (RFC 5545 §3.2.13, written by Apple
Calendar and Thunderbird for "this and all future events"), `recurring_ical_events`
correctly applies the override to the anchor slot *and every later slot* — but every one
of those components carries the *same* RECURRENCE-ID value. So `expand_occurrences`
returns N distinct occurrences all with an identical `recurrence_id`.
`service._occurrence_dto` then builds `id = f"{uid}::{occ.recurrence_id}"`, producing N
DTOs with the same `id`. `CalendarView.tsx` renders them with `key={e.id}` (lines
339/349/403/493), and per-occurrence writes address the instance by `recurrence_id`
(`api.ts:275` sets it as a query param; `CalendarView.tsx:166` matches optimistic
updates on `e.id !== `${uid}::${body.recurrence_id}``).

<details><summary>Evidence</summary>

```
recur.py:113-115:
```
    rid = comp.get("RECURRENCE-ID")
    anchor = (_iso(rid)[0] if rid is not None else start) or start or ""
```
Run against pinned deps — master `DTSTART:20260106T090000Z`, `RRULE:FREQ=WEEKLY;COUNT=4`, one override component with `RECURRENCE-ID;RANGE=THISANDFUTURE:20260113T090000Z / DTSTART:20260113T100000Z / SUMMARY:TF`. `expand_occurrences(raw, date(2026,1,1), date(2026,2,10))` returns (recurrence_id, start, summary, is_override):
```
('2026-01-06T09:00:00+00:00', '2026-01-06T09:00:00+00:00', 'Std', False)
('2026-01-13T09:00:00+00:00', '2026-01-13T10:00:00+00:00', 'TF', True)
('2026-01-13T09:00:00+00:00', '2026-01-20T10:00:00+00:00', 'TF', True)   <-- dup anchor
('2026-01-13T09:00:00+00:00', '2026-01-27T10:00:00+00:00', 'TF', True)   <-- dup anchor
```
Failure: three visibly distinct events on Jan 13/20/27 all get `id = uid::2026-01-13T09:00:00+00:00`. React logs duplicate-key warnings and can apply DOM updates to the wrong node; worse, the user clicks the Jan 27 occurrence and chooses "delete this event" -> the server EXDATEs 2026-01-13 and the Jan 27 occurrence stays on the owner's real calendar while an unrelated one disappears. Same for "edit this event", which writes the override onto the Jan 13 slot.
No test in `tests/test_recur.py` covers RANGE=THISANDFUTURE.
```

</details>

**Suggested fix.** Make the anchor unique per rendered instance. Either detect `RANGE=THISANDFUTURE` on the
RECURRENCE-ID param and fall back to the occurrence's own DTSTART for the anchor, or
unconditionally de-duplicate: track seen anchors in `expand_occurrences` and, on
collision, use the instance's own start as the anchor (still exact for the normal
single-slot override case). Add a test asserting `len({o.recurrence_id for o in occs})
== len(occs)`.

### [x] Changing a series' repeat rule leaves stale RECURRENCE-ID overrides behind as phantom events

`backend/tasksd/ical/edit.py:260` · **low** · rendering

`_apply_event_fields` -> `_set_rrule` replaces the master's RRULE but never reconciles
the resource's override components. An override whose RECURRENCE-ID is no longer
produced by the new rule is not part of the recurrence set, yet `recurring_ical_events`
still emits it, so the SPA renders an event that belongs to a schedule the user just
deleted. Reachable from the event modal: open a recurring event that has an edited/moved
occurrence, change Repeat, choose "All events".

<details><summary>Evidence</summary>

```
raw = weekly VEVENT DTSTART:20260202T090000 + override RECURRENCE-ID:20260209T090000 DTSTART:20260209T140000 SUMMARY:special.
apply_event_changes(raw, EventEdit(rrule=rrule_from_spec('monthly'))) then expand 2026-02-01..2026-03-10:
  BEFORE: 2/2 standup, 2/9 14:00 special, 2/16, 2/23, 3/2, 3/9 standup
  AFTER : 2/2 standup, 3/2 standup, **2/9 14:00 special**
The weekly-only 2/9 instance survives as a phantom under a monthly rule.
```

</details>

**Suggested fix.** When `edit.rrule` is applied to a master, drop (or re-anchor) override components whose
RECURRENCE-ID is not generated by the new rule — the behaviour Apple/Google clients
implement — and cover it with a test.

## Sync engine

### [x] Test gap: gc_orphans — the only code path that permanently deletes non-derivable sidecar state — has zero coverage

`backend/tasksd/sync/engine.py:130` · **medium** · test-gap · `minor`

`store.gc_orphans(conn)` is called unconditionally at the end of every `full_resync` and
permanently DELETEs sidecar rows (kanban column, manual sort order, pins,
estimated_minutes) older than 7 days. Per docs/phase0-findings.md the sidecar is
explicitly the one part of SQLite that a resync cannot rebuild — this is the single
irreversible-deletion path in the whole cache layer. `grep -rn 'gc_orphans\|keep_days'
backend/` returns hits only in engine.py:130 and store.py:232-239: no test in
backend/tests ever calls it, asserts its retention boundary, or asserts that a still-
live UID is never swept.

<details><summary>Evidence</summary>

```
engine.py:130:  store.gc_orphans(self.conn)

store.py:232-239:
    def gc_orphans(conn, *, keep_days: int = 7) -> int:
        cur = conn.execute(
            "DELETE FROM sidecar WHERE orphaned_at IS NOT NULL "
            "AND orphaned_at < strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)",
            (f"-{int(keep_days)} days",),
        )

Untested behaviours that would silently regress:
- the ISO-string lexicographic comparison against orphaned_at (a format drift in either strftime call — e.g. dropping the trailing 'Z' or switching to `datetime('now')` — silently makes the predicate match everything or nothing; the 'match everything' direction wipes every orphaned sidecar row on the next full_resync).
- the un-orphan-on-return contract (`upsert_item`, store.py:163-166): test_sync.py::test_delete_and_recreate_same_uid_keeps_sidecar asserts `orphaned_at IS NULL` after the UID returns, but never that GC would have spared it, so a bug that clears `orphaned_at` on the wrong row is invisible.
- the interaction in the finding above: gc_orphans running on a pass where `_upsert_body` skipped resources.

Existing coverage stops at 'the sidecar row survives and is marked orphaned' (test_sync.py:47-58). Nothing exercises the deletion itself.
```

</details>

**Suggested fix.** Add a unit test in test_sync_unit.py (no Radicale needed): seed a sidecar row, backdate
`orphaned_at` to 8 days ago and another to 6 days ago, call `store.gc_orphans(conn)`,
and assert exactly one row was removed and the return count is 1. Add a second case
asserting `gc_orphans` never touches a row with `orphaned_at IS NULL`. Then add an
engine-level test that a full_resync in which one resource was skipped (`stats.skipped >
0`) does not delete sidecar rows.

### [x] A resource corrupted in place leaves a permanent ghost cache row that never converges and 500s on edit

`backend/tasksd/sync/engine.py:144` · **medium** · bug

When a resource that is ALREADY cached is rewritten on the wire into something
`extract_from_raw` cannot handle (parse error, or a VCALENDAR that no longer contains a
VTODO/VEVENT), `_upsert_body` returns False and the old cache row is left completely
untouched — old summary/notes/due/status, old raw_ics, old etag. Because the href is
still present in `wire`, the full_resync sweep never removes it either, so the cache
diverges from the source of truth permanently: the incremental path advances its token
past the change and never revisits it, and every full_resync re-fetches (etag mismatch)
and re-skips forever. The docstring justifies the skip for a *newly seen* poison
resource, but the in-place-corruption case has no recovery at all.

<details><summary>Evidence</summary>

```
engine.py:133-152:

        try:
            fields = ical.extract_from_raw(item.data)
        except Exception as e:
            log.warning("skipping malformed resource %s: %s", item.href, e)
            stats.skipped += 1
            stats.last_error = f"malformed resource {item.href}: {e}"
            return False        # <-- stale row survives; nothing marks it stale
        if fields is None or not fields.uid:
            return False

engine.py:120-127 only deletes rows whose href is absent from `wire`, so the ghost is never swept.

Failure scenario:
1. Task `u` is cached at /cal/x.ics: summary="Pay rent", due=2026-08-01, etag=e1.
2. A CalDAV client sharing the collection (jtx Board / Tasks.org / anyone who can write to the shared collection) overwrites /cal/x.ics in place with a body whose extraction raises — e.g. `PRIORITY:HIGH`, or drops the VTODO entirely leaving only a VJOURNAL (extract() then returns None, engine.py:149).
3. Sync fetches the new body, `_upsert_body` returns False, no row is written, no row is deleted.
4. The SPA keeps listing "Pay rent / due 2026-08-01" indefinitely; the server holds something else.
5. The user opens it and PATCHes it. `_edit` PUTs with the stale etag e1 -> 412 -> re-GETs the corrupt body -> `ical.apply_changes(fresh.data, edit)` raises `ValueError("resource has no VTODO to edit")` (edit.py:152-153). `patch_task` (app.py:728-734) has no ValueError handler, so the user gets an opaque HTTP 500 on a task the UI insists exists.

Only the never-before-seen case is tested (test_sync_unit.py::test_malformed_resource_is_skipped_not_wedging_sync starts from an empty DB); there is no test for a previously-good resource going bad.
```

</details>

**Suggested fix.** Distinguish 'never cached, skip it' from 'cached and now unreadable'. In `_upsert_body`,
on both False paths, if `store.get_item_by_href(collection_href, item.href)` exists,
either (a) update just `etag`/`synced_at` and set a `stale` flag the DTO layer surfaces
as an unreadable item, or (b) drop the cache row and orphan its sidecar so the UI stops
showing data the wire no longer has. Option (a) is preferable — it stops the endless
refetch loop and keeps the sidecar. Either way, also wrap `patch_task`/`patch_event` so
an ical `ValueError` becomes a 409/422 with a readable message rather than a 500.

### [x] A resource that becomes unparseable/non-VTODO leaves a permanently stale cache row that 500s on every edit

`backend/tasksd/sync/engine.py:149` · **medium** · bug

`_upsert_body` returns False (skip) both for parse failures and for `fields is None`
(the resource no longer contains a VTODO/VEVENT), but it never invalidates the row
already in `items` for that href. The cached row keeps the *old* summary/notes/raw_ics
**and the old etag**, and it is not swept by `full_resync` either (its href is still on
the wire), so the divergence is permanent: the app shows content that no longer exists
on the source of truth, and the stale etag makes every write on it fail.

<details><summary>Evidence</summary>

```
Any CalDAV client sharing the collection can rewrite `1.ics` (same UID, so Radicale's `no-uid-conflict` check passes and the PUT is accepted) with a VCALENDAR whose only component is a VJOURNAL — jtx Board writes VJOURNALs, and per the trust model anyone who can write to a shared collection can plant arbitrary text. Verified:

    extract_from_raw(vjournal_body) -> None            # so _upsert_body returns False at engine.py:149-150
    cache still says: Buy milk "1"                     # store.get_item, unchanged, stale etag
    ical.apply_changes(vjournal_body, TaskEdit(status='COMPLETED'))
      -> ValueError: resource has no VTODO to edit

User-visible result: the task "Buy milk" stays in the list forever. Tapping complete (`POST /api/lists/{id}/tasks/{uid}/complete` → `edit_task` → `_edit`) PUTs with the stale etag → 412 → the merge path re-GETs the fresh body and calls `apply_changes` on it → `ValueError`, which `patch_task`/`complete_task` do not catch (only `patch_event` has a ValueError handler, app.py:805) → **500**. The row cannot be edited, completed, or made to disappear; the next full resync re-fetches, fails to parse again, and leaves it in place.
```

</details>

**Suggested fix.** When `_upsert_body` decides a cached href's body is no longer cacheable (parse failure
or `fields is None`), drop the existing cache row for that href
(`store.delete_item_by_href` + `store.orphan_sidecar`) instead of leaving the old
projection, so the item disappears from the UI rather than becoming an unfixable ghost.
Also catch `ValueError` in the task edit routes so the merge path cannot 500.

## SQLite cache

### [x] Deleting a list/calendar never purges its cached items — search and tags keep serving them forever

`backend/tasksd/db/store.py:75` · **medium** · bug

`mark_collection_deleted` only flips `collections.deleted=1`. Nothing ever deletes the
collection's rows from `items`, `categories`, `items_fts`, or `sidecar`, and nothing
orphans the sidecar rows so the 7-day GC can reclaim them. `store.search` (line 381) and
`store.distinct_categories` (line 451) join/scan `items`/`categories` with no
`deleted=0` filter, so the contents of a list the user deleted stay queryable through
`/api/search` and `/api/tags` indefinitely, while `resolve_list` (service.py:168) can no
longer resolve the `list` id those hits carry. The cache also grows without bound: every
deleted list's full `raw_ics` bodies stay on disk for the life of the DB.

<details><summary>Evidence</summary>

```
Reproduced against the real schema:

    store.upsert_collection(conn, CollectionInfo(href='/u/secretlist/', displayname='Secret', components={'VTODO'}))
    store.upsert_item(conn, '/u/secretlist/', Item('/u/secretlist/1.ics', '"1"', raw), fields)   # SUMMARY:confidential thing, CATEGORIES:secrettag
    store.set_sidecar(conn, '/u/secretlist/', 't1@x', kanban_column='doing')
    store.mark_collection_deleted(conn, '/u/secretlist/')   # what DELETE /api/lists/{id} ends up doing

output:
    collections visible: []
    search hits: ['confidential thing']
    tags: ['secrettag']
    count_items: 1
    sidecar orphaned: None

So after `DELETE /api/lists/{id}` succeeds and the list vanishes from `/api/lists`, `GET /api/search?q=confidential` still returns the deleted task (with `"list": "secretlist"`, which `/api/lists/secretlist/...` now 404s), and `GET /api/tags` still advertises its tag. The sidecar row is never orphaned, so `gc_orphans` never reclaims it either.
```

</details>

**Suggested fix.** In `mark_collection_deleted`, also orphan the sidecar rows for that collection and
delete its `items` / `items_fts` / `categories` rows (the cache is disposable by design
— a resync rebuilds it if the collection comes back). At minimum, filter `deleted=0` in
`search`, `distinct_categories` and `count_items` by joining `collections`.

### [x] A NUL byte in the search query escapes the FTS quoting and 500s

`backend/tasksd/db/store.py:379` · **low** · bug · `minor`

`search()` guards against FTS5 operator characters by wrapping each whitespace token in
double quotes, but a NUL byte inside a token truncates the C-string FTS5 parses, leaving
the phrase unterminated. `GET /api/search?q=%00` (the route is `q: str =
Query(min_length=1)`, no charset restriction) raises `sqlite3.OperationalError`, which
has no handler and surfaces as a 500. The suite has
`test_search_operator_characters_do_not_crash` asserting exactly this property for `"`,
`NEAR(`, `(((`, `*`, `-` … but not for control bytes, so the regression is untested.

<details><summary>Evidence</summary>

```
Against the real schema and the exact expression builder from store.py:379:

    q='\x00hi'  ->  match='"\x00hi"*'  ->  OperationalError: unterminated string
    q='hi\x00there' -> same

All other probed inputs ('"', 'AND', '*', '-', '^', '()', '\\', 20 000 terms) return cleanly, so NUL is the one hole in the quoting scheme.
```

</details>

**Suggested fix.** Strip control characters (at minimum `\x00`) from each term in `search()`, e.g.
`t.replace('\x00','')` before quoting and dropping tokens that become empty; add the NUL
case to `test_search_operator_characters_do_not_crash`.

## Scheduling

### [x] DST: slot math uses wall-clock timedelta arithmetic, producing duplicate, negative-length, and over-length bookable slots

`backend/tasksd/scheduling.py:188` · **medium** · bug

`generate_slots` builds candidate slots by adding `timedelta` to ZoneInfo-aware
datetimes (`slot = Interval(s, s + duration)`, `s += duration`), and
`TaskService.book_slot` computes the event end the same way (`end = req +
timedelta(minutes=link["duration_minutes"])`, service.py:733). Python's `aware_dt +
timedelta` is *wall-clock* arithmetic: it adds to the naive fields and re-derives the
UTC offset. Across a DST transition inside an availability window this silently changes
the absolute length of a slot. Three concrete consequences on the only unauthenticated
write path: (1) spring-forward yields a slot whose `end` instant precedes its `start`;
(2) spring-forward yields two distinct slots at the same absolute instant, so the public
page renders duplicate buttons and one of them becomes permanently un-bookable (see
evidence); (3) fall-back yields a slot advertised as N minutes that is actually N+60, so
an unauthenticated booker gets a 90-minute VEVENT on the owner's real calendar for a
30-minute link, and the repeated hour vanishes from availability entirely. Trigger
config is ordinary — an availability window that spans the local transition hour, e.g.
`{"0".."6": ["00:00-23:30"]}` on a DST-observing link timezone.

<details><summary>Evidence</summary>

```
Reproduced against the real module (America/Chicago, 30-min duration, availability `00:00-23:30` every day):

```
$ python3 -c "...generate_slots(availability={d:['00:00-23:30']}, duration_minutes=30, tz=America/Chicago, ...)"
spring-forward (2026-03-08) total 47
  wrong-duration slots: [('2026-03-08T02:30:00-06:00', '2026-03-08T03:00:00-05:00', timedelta(-1, 84600))]   # -30 minutes
  duplicate instants:   ['2026-03-08T08:00:00+00:00', '2026-03-08T08:30:00+00:00']
fall-back (2026-11-01) total 47
  wrong-duration slots: [('2026-11-01T01:30:00-05:00', '2026-11-01T02:00:00-06:00', timedelta(seconds=5400))]  # 90 minutes
```

Fall-back, end to end: the page advertises `{"start":"2026-11-01T01:30:00-05:00","end":"2026-11-01T02:00:00-06:00"}`. POST that `start`; `book_slot` does `req = fromisoformat(start).astimezone(tz)` -> 01:30 CDT (06:30Z), matches a generated slot, then `end = req + timedelta(minutes=30)` -> 02:00 CST = 08:00Z. The VEVENT written to the owner's calendar is DTSTART 06:30Z / DTEND 08:00Z — 90 minutes for a 30-minute link. The 07:00Z and 07:30Z slots (the repeated 01:00-02:00 CST hour) are never offered at all.

Spring-forward duplicate/phantom: instants 08:00Z and 08:30Z are each emitted twice (wall 02:00/03:00 and 02:30/03:30). Both render as the same clock time in the SPA. `_overlaps_any` (scheduling.py:201) short-circuits on `b.start >= slot.end`, and the 02:30 slot has `end` (08:00Z) < `start` (08:30Z), so no busy interval can ever block it; meanwhile `any(s.start == req)` in book_slot compares *wall-clock* fields (both operands share the same ZoneInfo instance, so datetime falls back to naive comparison), so once 08:30Z is booked the surviving duplicate button 409s forever.
```

</details>

**Suggested fix.** Do the stepping and the end-time computation in UTC and convert back only for the
weekday/window lookup: e.g. `s_utc = win.start.astimezone(timezone.utc)`, advance `s_utc
+= duration`, build `Interval(s_utc.astimezone(tz), (s_utc + duration).astimezone(tz))`,
and in `book_slot` use `end = (req.astimezone(timezone.utc) +
timedelta(minutes=link['duration_minutes']))`. That makes every emitted slot exactly
`duration` long in absolute time, collapses the spring-forward duplicates to one
instant, and restores the repeated fall-back hour. Also dedupe emitted slots by UTC
instant as a belt-and-braces guard.

## CalDAV client

### [x] A list name containing a control character crashes the PROPPATCH builder with an unhandled ValueError (500)

`backend/tasksd/dav/xml.py:121` · **low** · bug · `minor`

`build_proppatch` (and `build_mkcalendar` at xml.py:103) assign caller text directly to
`.text` on an lxml element. lxml rejects NUL and C0 control characters at assignment
time with a bare `ValueError` — not a `DavError` — so it bypasses the entire error
taxonomy in `errors.py` and the `DavError`/`ConflictError`/`KeyError` handlers
registered in `app.py:594-621`.  Verified directly: ``` $ python -c "from tasksd.dav
import xml as X; X.build_proppatch({X.DISPLAYNAME: 'a\x0bb'})" ValueError: All strings
must be XML compatible: Unicode or ASCII, no NULL bytes or control characters ``` The
API models do not constrain the charset: `CreateList.name: str` (`app.py:62`) and
`EditList.name: str | None` (`app.py:67`) have no pattern or sanitisation, and
`TaskService.update_collection` passes the name through untouched into
`props[davxml.DISPLAYNAME]` (`tasksd/service.py:301,309`).

<details><summary>Evidence</summary>

```
Code: `backend/tasksd/dav/xml.py:119-121`:
```python
prop = etree.SubElement(etree.SubElement(root, cl(DAV, "set")), PROP)
for name, value in to_set.items():
    etree.SubElement(prop, name).text = value
```

Failure scenario: authenticated owner (or the SPA passing through a name pasted from another CalDAV client) sends `PATCH /api/lists/{id}` with body `{"name": "Work "}` — JSON permits ` `. Route `patch_list` (`app.py:679`) -> `TaskService.update_collection` -> `DavClient.proppatch` -> `X.build_proppatch` raises `ValueError`. No handler matches, so uvicorn returns a 500 with a traceback in the server log instead of a 4xx validation error.
```

</details>

**Suggested fix.** Reject or strip disallowed XML characters where the value enters the builder — e.g. in
`build_proppatch`/`build_mkcalendar`, raise `DavError(f"property {name} contains
characters not representable in XML")` for any value matching
`[\x00-\x08\x0b\x0c\x0e-\x1f]` — and/or add a `pattern`/validator to `CreateList.name`
and `EditList.name` so it fails as a 422.

## Service layer

### [x] Deleting a collection leaves all of its items in the SQLite cache forever (cache/source divergence)

`backend/tasksd/service.py:329` · **medium** · bug

`delete_collection` DELETEs the collection on Radicale and then calls `discover()`,
which only sets `collections.deleted=1` (store.py:75-76). Nothing ever deletes the
collection's rows from `items`, `items_fts`, `categories`, or `sidecar`. The FK
`items.collection_href REFERENCES collections(href) ON DELETE CASCADE` never fires
because the collections row is soft-deleted, never DELETEd. Read paths that are not
scoped by a live collection therefore keep serving entities that no longer exist
anywhere on the wire, and the DB grows without bound.

<details><summary>Evidence</summary>

```
service.py:326-330:
```
    def delete_collection(self, href: str) -> None:
        with self._lock:
            self._dav.delete_collection(href)
            self._engine.discover()   # marks it deleted in the cache
```
`store.search` (store.py:370-387) joins `items_fts` to `items` with no `deleted` filter, and `store.distinct_categories` (store.py:451-459) scans `categories` globally.

Scenario: POST /api/lists -> create list L; POST a task "quarterly-secret" into L; DELETE /api/lists/L (204, and L is gone from GET /api/lists and from Radicale). GET /api/search?q=quarterly still returns the task, with `list` set to the slug of the now-nonexistent collection; GET /api/tags still returns its tags. The rows survive restarts and every full resync, since `sync_all` iterates only non-deleted collections so `full_resync`'s orphan sweep never runs for that href. This directly breaks the stated invariant #1 ("wipe the cache, resync, get identical state"): a fresh DB + resync would NOT reproduce those rows.
```

</details>

**Suggested fix.** On `mark_collection_deleted`, also purge the collection's
`items`/`items_fts`/`categories` rows and orphan its sidecar rows (`orphan_sidecar` per
uid) so the 7-day GC can reclaim them — or hard-DELETE the collections row and let the
existing ON DELETE CASCADE do it. Add a test asserting a deleted list's tasks disappear
from /api/search and /api/tags.

## API routes

### [x] Public booking link can be permanently disabled by anyone who has the link (per-link limiter counts every request, not just failures)

`backend/tasksd/app.py:946` · **medium** · bug

`_throttle` records a "failure" on every request (documented as request-rate semantics),
and the per-link limiter is keyed on the URL token with `max_fails=30, window_s=3600,
lockout_s=1800`. A booking link is meant to be published, so possession of the token is
not a secret — anyone who receives it can spend the link's global budget and keep it
locked out indefinitely, blocking all legitimate bookings.

<details><summary>Evidence</summary>

```
app.py:946 `public_post_link_limiter = RateLimiter(max_fails=30, window_s=3600, lockout_s=1800)`
app.py:948-955:
```python
def _throttle(key, limiter):
    if not limiter.allowed(key): raise HTTPException(429, ...)
    limiter.record_failure(key)   # every request counts
```
app.py:970-971 (before any token/body validation):
```python
_public_throttle(request, public_post_limiter)   # 15/h per client
_throttle(f"link:{token}", public_post_link_limiter)
```

Failure scenario: the owner publishes https://host/book/<token>. A visitor (or a competitor with the link) sends 30 `POST /api/public/booking/<token>/book` requests — the per-client limiter caps them at 15/h, so two source IPs, or two IPv6 /64s from a single VPS, suffice. `link:<token>` locks for 1800 s and every real visitor gets 429 "too many requests". Sustaining exactly 30 requests per 30 minutes (~1/min, within the budget of 2-4 addresses) keeps the link dead permanently, while the owner sees nothing but 429s in the log.
```

</details>

**Suggested fix.** Count only *completed* bookings against the per-link ceiling (call `record_failure` on
the link key after `book_slot` succeeds, not before validation), and/or return the 429
only for the write, not for `GET /api/public/booking/{token}`. Consider a much longer
window with a daily cap instead of a hard lockout, and surface link lockouts to the
owner.

## Backend test gaps

### [x] The DST regression test cannot fail on a negative-duration slot

`backend/tests/test_scheduling.py:188` · **medium** · test-gap · `minor`

`test_dst_spring_forward_is_sane` is the only test guarding slot math across a DST
transition, and its assertion is one-sided: `assert s.end.astimezone(UTC) -
s.start.astimezone(UTC) <= timedelta(hours=1)`. A slot whose end instant *precedes* its
start yields a negative timedelta, which trivially satisfies `<=`. It also never asserts
that the emitted slots are distinct instants or that each is exactly `duration_minutes`
long, so the duplicate-instant and over-length (fall-back) defects are invisible to the
suite. There is no fall-back (autumn) case at all.

<details><summary>Evidence</summary>

```
backend/tests/test_scheduling.py:178-188 runs `generate_slots` over `{'6': ['01:00-04:00']}` with `duration_minutes=60` on 2026-03-08 and only asserts `s.end - s.start <= timedelta(hours=1)`. With the same tz and a 30-minute duration the generator emits `Interval(2026-03-08T02:30:00-06:00, 2026-03-08T03:00:00-05:00)` — a delta of `-0:30:00`, which passes `<= 1h`. Concretely: change nothing in scheduling.py, add `{'6': ['01:00-05:00']}` / `duration_minutes=30` to this test and it still passes despite emitting a backwards interval.
```

</details>

**Suggested fix.** Assert exact equality on the absolute duration (`s.end.astimezone(UTC) -
s.start.astimezone(UTC) == timedelta(minutes=duration)`), assert
`len({s.start.astimezone(UTC) for s in slots}) == len(slots)`, and add a fall-back case
(2026-11-01, America/Chicago, window covering 00:00-05:00) asserting both the exact
duration and that the repeated 07:00Z hour is offered.

### [x] Test gap: the two fail-closed startup invariants and post-logout cookie replay are untested

`backend/tests/test_security.py:126` · **low** · test-gap

`create_app` has two security-critical refusals — `RuntimeError` when `auth_enabled` and
no password is configured (app.py:494-499), and replacing the well-known `"dev-hook-
secret"` with an ephemeral one so `/internal/changed` fails closed (app.py:528-535) —
and neither has a test. Nothing in tests/ constructs a settings object that trips either
path (`grep -rn 'RuntimeError' tests/` returns nothing). There is also no test that a
session cookie stops working after `POST /api/logout`, which is why the non-invalidation
above went unnoticed.

<details><summary>Evidence</summary>

```
app.py:494-499 `raise RuntimeError("auth enabled but no password set...")` and app.py:528-535 `if not hook_secret or hook_secret == "dev-hook-secret": hook_secret = secrets.token_hex(32)` are never exercised. test_security.py:218 only checks the *configured* hook secret (`hook_secret="testhook"` from conftest.py:91); it never checks that the literal default is rejected.

Failure scenario: a refactor that reorders the `password_hash` fallback (e.g. moving the `if not password_hash: raise` above the `TASKS_AUTH_PASSWORD` hashing at app.py:488) or that drops the `== "dev-hook-secret"` comparison makes the app boot with no gate, or makes `/internal/changed` accept the public default secret from any internet client — and the full suite still passes green.
```

</details>

**Suggested fix.** Add three tests: (1) `pytest.raises(RuntimeError)` on
`create_app(replace(api_settings(...), auth_password_hash="", auth_password=""))`; (2)
`create_app(replace(..., hook_secret="dev-hook-secret"))` then assert `POST
/internal/changed` with `X-Tasks-Hook-Secret: dev-hook-secret` returns 403; (3) login,
capture the cookie value, `POST /api/logout`, then re-send the captured cookie to
`/api/me` and assert 401 (this one will fail until session revocation exists).

## Calendar view

### [x] Test gap: CalendarView has no tests at all, including the date math the other findings live in

`frontend/src/components/CalendarView.tsx:33` · **medium** · test-gap

There is no CalendarView.test.tsx — every other non-trivial component in
frontend/src/components has one (TasksView, Sidebar, BookingPage, HomeView,
AppearancePanel, AddMultipleModal, Login). That leaves ~470 lines of security- and
correctness-sensitive logic unverified: `lastDayOf`'s exclusive-DTEND rule,
`shiftIso`/`daysBetween` across DST, `dropOnDay`'s move and resize DTSTART/DTEND
arithmetic, the modal's inclusive-picker to exclusive-DTEND conversion (`endOut = allDay
? shiftYmd(clampedEnd, 1)`), the recurrence scope routing (`this` / `thisandfuture` /
`all`, including the `timeChanged` gate that decides whether an 'all' save shifts the
whole series), the optimistic `applyLocal`/`del` painting, and the hidden/archived
calendar filters. Two of the bugs reported above (midnight-end resize off-by-one, DST
duration loss) are exactly the kind a table-driven test over these pure helpers would
have caught.

<details><summary>Evidence</summary>

```
$ find frontend/src -name '*.test.tsx'
  .../AddMultipleModal.test.tsx  .../AppearancePanel.test.tsx  .../BookingPage.test.tsx
  .../HomeView.test.tsx  .../Login.test.tsx  .../Sidebar.test.tsx  .../TasksView.test.tsx  .../App.test.tsx
(no CalendarView.test.tsx)

Untested behaviour with a concrete wrong-answer today:
  lastDayOf({start:'2026-03-02T20:00', end:'2026-03-03T00:00'}) === '2026-03-02'  (correct, untested)
  dropOnDay resize of that event onto '2026-03-05' -> DTEND '2026-03-05T00:00' (wrong, untested)
```

</details>

**Suggested fix.** Export `lastDayOf`, `shiftIso`, `daysBetween`, and the resize/move body builder from
`dropOnDay` (or lift them into util.ts) and add a table-driven suite: all-day
single/multi-day spans, timed spans ending at midnight, spans crossing the month-grid
edges, DST spring-forward and fall-back drags, and one render test per recurrence scope
asserting the exact `{scope, recurrence_id, start, end}` handed to `api.patchEvent` /
`api.deleteEvent`.

### [x] Rapid month navigation can render the wrong month's events (unordered fetches, no staleness guard)

`frontend/src/components/CalendarView.tsx:116` · **medium** · bug · `minor`

The events effect fires on `[cursor, rev, calsKey]` and does `setEvents(await
fetchEvents())` with no cleanup, AbortController, or generation counter. `fetchEvents`
fans out one request per visible calendar and awaits `Promise.all`, so two clicks on ›
put two multi-request batches in flight; whichever settles last wins. If the earlier
(older-month) batch settles second, the grid is populated with the previous month's
events while the header says the new month. Because `byDay` clips everything to the
current 6-week window, almost none of those events match any rendered day, so the month
renders *empty*. Nothing re-corrects it: the SSE `rev` bump only fires on a server-side
write, so a read-only user is stuck on a blank month until they navigate again.

<details><summary>Evidence</summary>

```
const calsKey = visibleCals.map((c) => c.id).join(',')
useEffect(() => {
  if (!visibleCals.length) { setEvents([]); return }
  guard(async () => setEvents(await fetchEvents()))
}, [cursor, rev, calsKey])

Sequence: user clicks › (fetch A for April starts), clicks › again ~100ms later (fetch B for May starts). B returns in 200ms, A in 900ms. Final state: cursor = May, events = April's. `byDay` keys April dates, the May grid shows no chips, and `reload()` (same unguarded pattern, line 120-122) can lose the same way after a save.
```

</details>

**Suggested fix.** Add a per-run generation guard: `let live = true; guard(async () => { const evs = await
fetchEvents(); if (live) setEvents(evs) }); return () => { live = false }` — and apply
the same guard inside `reload()` (or route reload through a bumped generation counter).

### [x] Resizing a timed event that ends at midnight is off by one day

`frontend/src/components/CalendarView.tsx:247` · **medium** · bug · `minor`

In the resize branch of `dropOnDay`, the new DTEND for a timed event is built as
`${day}T${old time-of-day}`. When the event's existing DTEND is exactly midnight, that
produces an end instant at the *start* of the drop day — which `lastDayOf` then
(correctly) renders as ending the day before. So dragging the grip to day D makes the
event end on D-1, and dragging it to the day immediately after the current last day is
silently a no-op. The all-day branch two lines above handles exclusivity explicitly
(`end = shiftYmd(day, 1)  // DTEND stays exclusive`); the timed branch does not.

<details><summary>Evidence</summary>

```
} else {
  end = `${day}T${toLocalInput(d.ev.end || d.ev.start).slice(11, 16)}`
  if (end <= start) return
}
const oldEnd = d.ev.end && (d.ev.all_day ? d.ev.end.slice(0, 10) : toLocalInput(d.ev.end))
if (end === oldEnd) return

Event DTSTART 2026-03-02T20:00, DTEND 2026-03-03T00:00 (a 20:00-24:00 block, trivially authored in Thunderbird/Apple Calendar).
lastDayOf -> exclusive -> renders only on 2026-03-02, grip on 2026-03-02.
- Drop on 2026-03-03 (extend by one day): end = '2026-03-03T00:00' === oldEnd -> `return`. Nothing happens; the user's drag is silently discarded.
- Drop on 2026-03-05: end = '2026-03-05T00:00' is PATCHed; lastDayOf now yields 2026-03-04. The event ends a day earlier than where it was dropped.
```

</details>

**Suggested fix.** In the timed branch, detect the exclusive-midnight end the same way `lastDayOf` does and
target the day after the drop: when the original end's local time is 00:00, use `end =
${shiftYmd(day,1)}T00:00`. Compare against `oldEnd` after that normalization so a
genuine one-day extension is not swallowed.

### [x] Editing an all-day event's start silently drops a day when the original span crosses a DST spring-forward

`frontend/src/components/CalendarView.tsx:571` · **low** · bug · `minor`

`changeStart` preserves the event's duration in absolute milliseconds (`oldE.getTime() -
oldS.getTime()`) and then formats the result back to a local calendar day with `ymd()`.
For an all-day event the duration is a whole number of *calendar days*, not of
milliseconds: a span containing a spring-forward transition measures 47h instead of 48h,
so re-anchoring it to a date outside that week lands the end one calendar day short. The
event silently loses a day when the user only touched the start field.

<details><summary>Evidence</summary>

```
const shifted = new Date(newS.getTime() + Math.max(0, oldE.getTime() - oldS.getTime()))
setEnd(allDay ? ymd(shifted) : ...)

Verified with TZ=America/New_York:
  all-day event DTSTART 2026-03-07, DTEND 2026-03-10 (covers Mar 7, 8, 9; DST is Mar 8 2026)
  modal shows start 2026-03-07, inclusive end 2026-03-09
  user changes Start to 2026-04-01
  oldE - oldS = 47 hours -> shifted = 2026-04-02T23:00 -> ymd = '2026-04-02'
  saved as Apr 1 - Apr 2 (2 days) instead of Apr 1 - Apr 3 (3 days).
The reverse direction (fall-back, 49h) happens to round correctly, so only spring-forward loses data.
```

</details>

**Suggested fix.** For `allDay`, shift by whole days instead of milliseconds: compute `const n =
daysBetween(oldStartDay, oldEndDay)` and `setEnd(shiftYmd(v, n))`. (`daysBetween` at
line 18 already rounds the DST-skewed millisecond delta to whole days correctly.)

## Tasks view

### [x] A due date, priority or tag the user *edits* still round-trips lossily

`frontend/src/components/TasksView.tsx:729` · **medium** · bug

Partly addressed: the modal now sends only the fields the user touched, so a rename no
longer rewrites anything else. The representations themselves are still lossy, so
editing one of these fields rewrites it through the same funnel:

- **DUE loses its timezone anchor.** `DUE;TZID=Europe/Berlin:20260810T093000` reads back
  as `2026-08-10T09:30:00+02:00`, `toLocalInput` renders it in the *viewer's* wall clock,
  and the save sends a naive string — emitting `DUE:20260810T033000`, floating, with no
  TZID. Fix: resend the original offset and teach `_parse_datelike` to preserve it.
- **PRIORITY is quantised.** The four-way label bucket maps 1-4 to "high" and "high" back
  to 1, so a task carrying `PRIORITY:3` returns as `PRIORITY:1`. Fix: keep the integer and
  only map when the user picks a new label.
- **Tags split on commas.** `CATEGORIES:Home\,Garden` is one category; the comma-joined
  input splits it in two on save. Fix: a chip editor, or a delimiter a category cannot
  contain.

### [x] Retrying a failed bulk create mints a fresh client_id, so a lost response duplicates the task

`frontend/src/components/TasksView.tsx:175` · **medium** · bug

`createMany` generates a new `client_id` for every row on every invocation. The bulk
composer's whole failure story is "the row is kept — press Add to retry"
(AddMultipleModal.tsx:236-246, and the reassuring comment at line 238), and its retry
calls `onSubmit` again, which re-enters `createMany` and mints new ids. Since
`client_id` is precisely the idempotency slug the server derives the CalDAV resource
name from (api.ts:198-203), regenerating it defeats the only protection against a
replayed create — the retry lands as a second, distinct VTODO on the owner's real list.

<details><summary>Evidence</summary>

```
TasksView.tsx:170-181:
```ts
const createMany = async (items, onProgress): Promise<number[]> => {
  const key = loadKey
  const cids = items.map(() => clientId())      // <- fresh ids on every retry
  ...
  const t = await api.createTask(items[i].listId, { ...items[i].body, client_id: cids[i] })
```
and AddMultipleModal.tsx:236-241:
```ts
// Retrying is safe: a failed create never landed, and each attempt mints a fresh client_id.
const badKeys = new Set(bad.map((i) => live[i].key))
```
The comment's premise is false. `api.createTask` rejects on transport failure *and* on any non-2xx (api.ts:212-222), neither of which implies the write did not land. Failure scenario: the user submits 5 rows over the Cloudflare Tunnel; on row 3 the POST reaches the backend, the CalDAV PUT commits, and then the tunnel returns a 502 (or the connection drops) before the response gets back. `fetch` rejects -> row 3 is marked failed and kept in the grid -> the user presses Add -> `createMany` runs with a brand-new `client_id` -> a second VTODO with the same summary is created on the owner's real list. The same happens for a single-shot `create` (line 150) if the user retypes, but the bulk modal actively invites the retry.
```

</details>

**Suggested fix.** Mint the client_id once per row and store it on the `Row` (it already has a stable `key`
— reuse that, or add a `cid` field), then pass it through `items[i]` into `createMany`
so a retry replays the identical id. Keep regenerating only when the user edits the
row's title. Add a test that fails the second create with a non-Auth error, retries, and
asserts the same `client_id` is sent.

### [x] Subtasks vanish from the List view whenever their parent row isn't rendered

`frontend/src/components/TasksView.tsx:269` · **medium** · bug

The List view renders only top-level tasks (`tops`), and a subtask reaches the DOM
exclusively as a child of its own parent's `<TaskGroup>` via `childrenOf(parent.uid)`.
Nothing renders a task whose `parent` is set but whose parent row is not itself being
rendered, so such a task is completely absent from the List view — it cannot be seen,
completed, edited or deleted. `parent` is the raw `RELATED-TO` UID with no existence
check (`backend/tasksd/service.py:232` -> `it["related_parent"]`, `ical/read.py:143`),
and `_children_map` (service.py:189) only groups within one list, so cross-list and
dangling RELATED-TO values are both handed to the client as-is. Meanwhile the sidebar
count still includes them (`service.py:147` counts every non-COMPLETED/CANCELLED VTODO
regardless of parentage), so the badge and the visible rows disagree.

<details><summary>Evidence</summary>

```
TasksView.tsx:268-272:
```ts
const shownTasks = tasks.filter((t) => !hiddenSet.has(t.list))
const tops = shownTasks.filter((t) => !t.parent)
const childrenOf = (uid: string) => shownTasks.filter((t) => t.parent === uid)
const active = tops.filter((t) => !t.completed && !t.cancelled)
const done = tops.filter((t) => t.completed || t.cancelled)
```
and TasksView.tsx:373-385, where `done` is rendered only `{showCompleted && done.length > 0 && ...}`.

Failure scenario (no hostile data needed, default settings): `showCompleted` defaults to `false` (App.tsx:32). Parent "Trip planning" is marked complete (here or in Tasks.org) while its subtask "Book flight" is still NEEDS-ACTION. The parent lands in `done`, which is not rendered because `showCompleted` is false; "Book flight" has `parent` set so it is excluded from `tops`; `childrenOf('trip-uid')` is never called. "Book flight" disappears from the List view entirely, while the sidebar still shows the list's open count including it.

Second scenario (hostile/foreign CalDAV data, in scope per the trust model): another client writes a VTODO with `RELATED-TO:<uid-that-does-not-exist>` (or deletes a parent without cascading). That task is permanently invisible and unreachable in the List view forever.

Note the day-column views behave inconsistently — `openOn`/`doneOn`/`undated` (lines 295-307) filter `shownTasks` without checking `parent`, so the same subtask does render there, as a top-level card, and is counted in the column badge.
```

</details>

**Suggested fix.** Treat a task as top-level when its parent is not among the rendered set, e.g. `const
renderedUids = new Set(shownTasks.map(t => t.uid))` and `const tops =
shownTasks.filter(t => !t.parent || !renderedUids.has(t.parent))`, plus include a
completed parent's open children (or render orphans under a synthetic heading) when
`showCompleted` is off. Add a test covering an open subtask whose parent is completed
with `showCompleted={false}`.

## Home / dashboard

### [x] Mini calendar dots one day too many: exclusive all-day DTEND treated as inclusive

`frontend/src/components/HomeView.tsx:340` · **medium** · rendering · `minor`

`busyDays` walks from the event's start day to `midnight(parseDate(e.end))` inclusive.
For an all-day event the wire `end` is the *exclusive* DTEND (backend serves the raw
DTEND — service.py:415 `"end": it["dtend"]`), and for a timed event ending exactly at
midnight the end instant belongs to the previous day. Both cases dot one day past the
event. CalendarView already gets this right in `lastDayOf()` (CalendarView.tsx:33-42,
which checks `e.end_is_date` and the midnight case); `busyDays` never looks at
`end_is_date` at all.

<details><summary>Evidence</summary>

```
const to = e.end ? parseDate(e.end) : from
...
const tail = midnight(to)
for (let d = head; d <= tail && d <= gridEnd; d = addDays(d, 1)) busy.add(ymd(d))

Verified by running the real function:
  busyDays([ev('2026-08-03','2026-08-04', start_is_date:true, end_is_date:true)], grid)
    -> ['2026-08-03', '2026-08-04']      // a ONE-day all-day event on Aug 3
  busyDays([ev('2026-08-03T20:00:00','2026-08-04T00:00:00')], grid)
    -> ['2026-08-03', '2026-08-04']      // 20:00-24:00 on Aug 3
So a single all-day event (a birthday, a one-day trip) marks the *next* day busy on the Home mini calendar, with no event there.
```

</details>

**Suggested fix.** Compute the last covered day the same way CalendarView.lastDayOf does — treat
`e.end_is_date` (or a datetime end landing exactly on 00:00 local) as exclusive and step
`tail` back one day, floored at the start day. Export/share `lastDayOf` rather than
duplicating the rule in two places.

### [x] Test gap: busyDays has no all-day (exclusive DTEND) case; its helper hardcodes end_is_date:false

`frontend/src/components/HomeView.test.tsx:188` · **low** · test-gap · `minor`

The `busyDays` describe block builds every fixture with `start_is_date: false,
end_is_date: false, all_day: false`, so no test ever exercises the all-day path — which
is exactly the path that is wrong (see the exclusive-DTEND finding). The suite does
cover multi-day spans, no-end events, an end earlier in the day than the start, and a
runaway DTEND, so the omission reads as an oversight rather than a deliberate scope cut.

<details><summary>Evidence</summary>

```
const ev = (start: string | null, end: string | null): CalEvent => ({
  ..., start, start_is_date: false, end, end_is_date: false,
  all_day: false, ... })

Every one of the four busyDays tests calls this helper, so `busyDays([{start:'2026-08-03', end:'2026-08-04', end_is_date:true, ...}], grid)` returning two days is never caught.
```

</details>

**Suggested fix.** Give the helper optional `start_is_date`/`end_is_date`/`all_day` params and add: a one-
day all-day event dots exactly one day; a three-day all-day event (DTEND = day 4) dots
exactly three; a timed event ending 00:00 dots only its own day.

## Frontend, other

### [x] All settings writes swallow every failure, including 401 — an expired session silently discards preference changes and never returns to the login form

`frontend/src/App.tsx:128` · **medium** · bug · `minor`

All nine settings mutators (`changeAppearance`, `changeDashboard`, `changeTasksView`,
`toggleSide`, `changeHiddenCals`, `changeArchivedCals`, `changeHiddenLists`,
`changeTaskGroups`, `changeCollapsedGroups`, `toggleShowCompleted`, `changeTheme`) do
`api.putSettings(...).catch(() => {})`. None routes through `makeGuard`, so an
`AuthError` never reaches `onExpire` and no error ever reaches the toast notifier. The
local state is already committed, so the UI asserts a change that the server rejected.
For `appearance` and `theme` there is at least a localStorage mirror; `dashboard`,
`task_groups`, `hidden_lists`, `collapsed_groups`, `hidden_calendars` and
`archived_calendars` live only server-side, so the change is simply gone on the next
reload.

<details><summary>Evidence</summary>

```
const changeDashboard = useCallback((next: DashboardModule[]) => {
  setDashboard(next)
  api.putSettings({ dashboard: next }).catch(() => { /* stays local if offline */ })
}, [])

Scenario A (expired session): the tab has been open past TASKS_SESSION_TTL (7 days default). The user rearranges the Home dashboard and hides two calendars. Every PUT returns 401; `j()` throws AuthError; the catch eats it. The UI shows the new arrangement, no toast appears, the app never falls back to <Login>, and (combined with the SSE finding above, whose stream the same 401 has already closed) the tab looks perfectly healthy while being completely disconnected. On reload everything is back to the old layout with no explanation.

Scenario B (server-side rejection): dashboard.ts clamps module height to MAX_ROWS = 200 (dashboard.ts:60,74) while the backend model is `h: int = Field(ge=1, le=40)` (app.py:281). A module resized past 40 rows makes the whole PUT 422; the layout renders locally and is silently dropped.
```

</details>

**Suggested fix.** Route these writes through a guard: on AuthError call `onExpire()`/`setAuth('out')`,
otherwise surface the message through the existing toast notifier (and roll the local
state back, or at least mark it unsaved). Also reconcile the dashboard height clamp with
the backend bound (both 40, or both 200).

### [x] Every settings write triggers a full lists+tasks refetch in every open tab, so one appearance-slider drag fires a request storm

`frontend/src/App.tsx:190` · **medium** · bug

`TaskService.update_settings` publishes `{"type": "settings_updated"}` to every SSE
subscriber including the tab that made the write (backend/tasksd/service.py:787). The
client's `subscribe()` filter only excludes `hello`, so any settings event is treated as
a data change and bumps `rev`, which is the refetch trigger for TasksView
(`useEffect(..., [loadKey, rev])` -> `api.lists()` + one `api.tasks()` per list),
CalendarView and `useAllTasks`. UI preferences have nothing to do with task data, so
every one of these refetches is pure waste — and each one replaces the whole tasks array
under whatever optimistic paint is in flight, which is exactly the reconcile race
TasksView's fetch-token guard exists to narrow.

<details><summary>Evidence</summary>

```
// App.tsx
const unsubscribe = subscribe(() => { clearTimeout(timer); timer = setTimeout(() => setRev((r) => r + 1), 250) })
// api.ts:315
if (data.type && data.type !== 'hello') onChange()

Scenario: user opens Appearance and drags the Gutter slider. `RangeControl` is `<input type="range" min={8} max={64} step={1} onChange={(e) => onChange(...)}>` (AppearancePanel.tsx:297-300); React fires onChange on every distinct step, so one drag across the range produces up to 56 `api.putSettings({appearance})` calls (App.tsx:131). Each PUT publishes settings_updated; the 250 ms debounce collapses them to roughly one rev bump per 250 ms of drag, and each bump costs 1 + N HTTP requests (N = number of task lists) in TasksView plus 1 + N more in HomeView if it is mounted. With 8 lists that is ~18 requests every 250 ms for the whole drag, all of them re-reading SQLite, while the user is only picking a gutter width. Toggling the sidebar or flipping the theme has the same 1+N cost.
```

</details>

**Suggested fix.** Give `subscribe` the parsed event type and let App route it: `settings_updated` should
re-run `api.getSettings()` (or be ignored entirely in the originating tab), never bump
`rev`. Independently, debounce the appearance/dashboard PUTs (commit on pointerup /
trailing-edge debounce) so a slider drag is one write, not fifty-six.

### [x] Every appearance control silently does nothing when 24 themes exist and the shipped design is active

`frontend/src/components/AppearancePanel.tsx:46` · **low** · bug · `minor`

`edit()` is the handler behind every token control in the panel. When the shipped
default is active (`active === null`) it must fork a new theme first, and it bails out
with a bare `return` if the theme cap is already reached. No toast, no alert, no
disabled state on the controls — unlike `importTheme`, which does alert on the same
condition (line 106).  The result is a panel that looks fully interactive but is inert:
the color text field accepts typing and shows valid styling, the range sliders move, and
nothing is ever applied or saved. `saveAs` (line 61) has the same silent bail.

<details><summary>Evidence</summary>

```
frontend/src/components/AppearancePanel.tsx:40-56
  const edit = (patch: ThemeTokens) => {
    if (active) { ... return }
    if (themes.length >= MAX_THEMES) return        // <- silent no-op
    const fork: CustomTheme = { id: clientId().slice(0, 16), name: 'Custom', ... }
    onChange({ active: fork.id, themes: [...themes, fork] })
  }

Failure scenario: user has accumulated MAX_THEMES (24) themes and selects
"Smylte (default)" in the theme dropdown. They then drag the Corners slider to 8px.
RangeControl fires onChange -> edit({'--radius': '8px'}) -> active is null and
themes.length === 24 -> return. onChange is never called, no state changes, the slider
snaps back on the next render, and the user gets no explanation. Same for typing a color
and for clicking "Duplicate" (saveAs, line 61).
```

</details>

**Suggested fix.** In both `edit()` and `saveAs()`, surface the cap the way `importTheme` already does,
e.g. `window.alert(\`You can keep ${MAX_THEMES} themes — delete one first.\`)` before
returning, or compute `const atCap = !active && themes.length >= MAX_THEMES` and pass it
down to disable the TokenRow controls with a hint line.

### [x] Booking page reports every load failure as "this link is no longer available", including 429 rate-limits and network blips

`frontend/src/components/BookingPage.tsx:40` · **low** · rendering · `minor`

`load()` catches everything that is not an `AuthError` and sets `phase='notfound'`,
which renders a terminal card reading "This booking link is no longer available. It may
have been turned off or removed. Ask the person who sent it for a fresh link." There is
no retry and no distinction between a genuine 404 and a transient failure. The backend
deliberately returns 429 on this exact endpoint (`public_get_limiter =
RateLimiter(max_fails=120, window_s=300, lockout_s=300)`, app.py:978, and `_throttle`
counts *every* request, not just failures — app.py:994), and a fetch rejection (dropped
connection, tunnel hiccup) hits the same branch. The same path is taken from
`submit()`'s race-recovery, where `await load()` can overwrite the "That time was just
taken" message with the dead-link card.

<details><summary>Evidence</summary>

```
BookingPage.tsx:39-42:
```tsx
} catch (e) {
  if (!(e instanceof AuthError)) setPhase('notfound')
  return null
}
```
`api.publicBookingInfo` (api.ts:294) goes through `j()`, which throws a plain `Error` for any non-2xx except 401 (api.ts:212-222). Trigger: 121 GETs of `/api/public/booking/<token>` from one IPv4 / IPv6-/64 within 5 minutes (a shared office NAT or CGNAT range, or a single visitor reloading) -> 429 -> every visitor behind that address is told for the next 5 minutes that the host's link has been removed and to ask for a new one. Same card on any transient network error at page load, with no way to retry short of a manual reload. `BookingPage.test.tsx:35` only exercises the genuine-404 case, so nothing catches this.
```

</details>

**Suggested fix.** Have `j()` surface the HTTP status (or throw a typed `HttpError`) and in `load()` only
enter `notfound` on a real 404; for 429/5xx/network errors show a distinct "couldn't
load right now" state with a Retry button (and honour `Retry-After`). In `submit()`'s
race branch, don't let a failing `load()` clobber the already-set error message.

### [x] Wrong password shows the raw string "unauthenticated" instead of a friendly message; the Login test asserts an error the client can never produce

`frontend/src/components/Login.tsx:19` · **low** · rendering · `minor`

`j()` intercepts status 401 *before* it reads the response body and throws
`AuthError('unauthenticated')` (api.ts:212), discarding the server's `detail`. The login
endpoint answers a bad password with `HTTPException(401, "invalid credentials")`
(backend/tasksd/app.py:949). Login.tsx only maps the strings 'Unauthorized' and 'invalid
credentials' to the friendly text, so the real message never matches and the raw
internal token is rendered to the user. The test suite hides this: Login.test.tsx mocks
`api.login` rejecting with `new Error('invalid credentials')`, a shape the real api
client cannot produce for a 401 — so the green test is asserting on fiction.

<details><summary>Evidence</summary>

```
// api.ts
if (res.status === 401) throw new AuthError('unauthenticated')
// Login.tsx
const msg = (ex as Error).message
setErr(msg === 'Unauthorized' || msg === 'invalid credentials' ? 'Invalid credentials' : msg)

Input: correct username, wrong password -> POST /api/login -> 401 {"detail":"invalid credentials"} -> AuthError('unauthenticated') -> the login card displays the word "unauthenticated". (The 429 lockout path is fine: 429 is not intercepted, so 'too many attempts, try later' is shown verbatim, and that is the case the tests actually cover.)
```

</details>

**Suggested fix.** Catch `AuthError` explicitly in `submit` and render 'Invalid credentials' for it
(keeping the verbatim branch for 429/5xx), or have `j()` carry the parsed `detail` into
the AuthError message. Then fix Login.test.tsx to reject with `new
AuthError('unauthenticated')` so the test exercises the shape the client actually
throws.

### [x] Editing a list silently strips the alpha byte from a #RRGGBBAA color written by another client

`frontend/src/components/Sidebar.tsx:566` · **low** · bug · `minor`

`EditModal` truncates the incoming color to its RGB prefix for swatch comparison, but
then saves that truncated value. Any save from this modal — including one where the user
only renamed the collection — PROPPATCHes the shortened color back to Radicale,
discarding the alpha byte another client wrote.

<details><summary>Evidence</summary>

```
Sidebar.tsx:564-571:
```ts
const [name, setName] = useState(item.name)
// Wire colors may carry an alpha byte (#RRGGBBAA); compare on the RGB part.
const [color, setColor] = useState<string | null>(item.color ? item.color.slice(0, 7) : null)
...
const save = () => {
  onSave(item.id, { name: name.trim() || item.name, color })
}
```
Failure scenario: Apple Calendar / DAVx5 set `calendar-color` to `#FF9500FF` (their standard format). The owner opens the list's ⋯ menu just to rename it and presses Save. `color` is `'#FF9500'`, so `api.updateList` PROPPATCHes `#FF9500` and the `FF` alpha component is gone from the collection for every other client. The comment shows the truncation was intended for the `color === c` swatch comparison only; it leaked into the write.
```

</details>

**Suggested fix.** Keep the original wire value in a ref and compare on the prefix: `const [color,
setColor] = useState<string | null>(item.color)`, with the swatch check `color?.slice(0,
7) === c`. Only send a changed color when the user actually clicked a swatch or the "no
color" button.

