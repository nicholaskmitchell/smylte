# Staged remediation of the audit backlog

`docs/AUDIT.md` is the evidence. This file is the plan for closing those
findings, and the map from a finding to the test that pins it.

Three sweeps have been staged this way. The **2026-08-25** one is at the top and
is OPEN. The **2026-08-19** and **2026-08-16** backlogs under it are both closed
and kept as the record of how the harness behaved in practice — the latter's "Two
strengths of pin" and "Ordering" notes are the reason the later pins are shaped
the way they are.

The **2026-08-25** sweep at the top IS a live worklist: stages 4 and 5 still carry
`xfail(strict=True)` / `it.fails` pins against open findings. Stages 2 and 3 are
closed within it — their markers are gone and their tests are ordinary regression
tests — and their sections are kept in place, with what remediation taught
appended to each. Everything from `# Sweep — 2026-08-19` down is history: no
marker remains in either of those, and every pin named there is an ordinary test
that must stay green.

# Sweep — 2026-08-25 · OPEN

34 findings survived verification. **All five stages are staged; STAGES 2 AND 3
ARE CLOSED** — 19 fixed, 15 of the sweep's own still open, plus one NEW finding
opened by stage 3's remediation (`AUDIT.md`, marked `· found in remediation`).
The rest carry an executable pin, one is deliberately unpinned with its reason
written down (stage 4, the WinForms dock order), and stage 5's two test gaps came
out as ordinary passing tests because their subjects were correct. This section
is the live worklist — the only one in this file — and everything below it is
history.

Same five buckets and the same sorting criteria as the two closed sweeps: a
finding lands in a stage by what its failure *does*, lower stage winning a tie,
severity ordering within. Restated under "The sorting criteria" further down; it
has not changed.

**Stage 1 is empty**, and that is a result rather than an omission. The sweep's
eight HIGHs are all closed already, and nothing left puts untrusted input into an
unhandled exception. The 34 were 16 medium and 18 low; the 15 of them still open
are 6 medium and 9 low.

| stage | findings | pins |
|---|---|---|
| 1 | 0 | — |
| 2 ✅ | 7 · **closed** | `backend/tests/test_backlog_aug25_stage2.py`, `desktop/Smylte.Desktop.Tests/LocalServerTests.cs` |
| 3 ✅ | 12 · **closed** | `backend/tests/test_backlog_aug25_stage3.py`, `frontend/src/backlog.aug25.stage3.test.tsx` |
| 4 | 13 | `frontend/src/backlog.aug25.stage4.test.tsx`, `frontend/src/backlog.aug25.stage4.browser.test.tsx` |
| 5 | 2 | `backend/tests/test_backlog_aug25_stage5.py` (no markers — see below) |

## Stage 2 — Abuse & resource exhaustion ✅ DONE

7 findings · 1 medium, 6 low · **closed** · `backend/tests/test_backlog_aug25_stage2.py`,
`desktop/Smylte.Desktop.Tests/LocalServerTests.cs`

All seven are fixed and ticked in `docs/AUDIT.md`; every marker is gone and those
tests are ordinary regression tests that must stay green. Six commits, one per
fix, except findings 4 and 5 which were always one fix in two places. **One needs
a hand on the server** — see "The one that does not land by merging" below.

Work or storage an adversary — or, twice here, ordinary use — can make unbounded,
and controls that do not cover what they say they cover.

Two shapes recur. Three are **a guard in the wrong place**: `set_sidecar` lacks
the live-item check `set_sort_orders` carries, whose own docstring argues "the
guard belongs here, where every door passes"; `tasks.service` opens the very tree
its hardening block exists to close; `RateLimiter` bounds a client and is treated
as bounding the guess budget. The other three are **work that scales with an
argument the caller chooses** — a `kid`, a day range, an address.

| # | Finding | Where | Sev | Pin |
|---|---|---|---|---|
| 1 | smylte_review_day over a range re-reads every task of every named list once per day — 6.6 s under the service… | `backend/tasksd/mcp/api.py:1313` | medium | `test_a_range_review_reads_each_list_once_not_once_per_day` |
| 2 | Cloudflare Access verification does a blocking JWKS fetch on the event loop, and an unknown `kid` forces one… | `backend/tasksd/access.py:31` | low | `test_an_unknown_kid_does_not_buy_a_jwks_fetch_per_request` + `…_does_not_freeze_the_event_loop` |
| 3 | Nothing bounds the total anonymous scrypt work: the login limiter is keyed only on the client /64, so a single… | `backend/tasksd/app.py:1711` | low | `test_the_anonymous_guess_budget_is_bounded_across_client_addresses` |
| 4 | PATCH /api/day/{day}/entries/{id} mints an unreclaimable sidecar row when the entry's task no longer exists… | `backend/tasksd/service.py:2321` | low | `test_estimating_a_day_entry_whose_task_is_gone_leaves_nothing_behind` |
| 5 | store.set_sidecar has no live-item guard, so the day-plan estimate write-through mints sidecar rows gc_orphans… | `backend/tasksd/db/store.py:511` | low | `test_a_sidecar_is_not_minted_for_an_item_the_cache_does_not_hold` |
| 6 | tasks.service grants the app write access to its own interpreter and source tree, contradicting the sandbox's… | `deploy/tasks.service:29` | low | `test_the_unit_does_not_open_its_own_interpreter_and_source_to_writes` |
| 7 | The desktop client serves the SPA with no Content-Security-Policy — the whole policy is a response header the… | `desktop/Smylte.Desktop/LocalServer.cs:230` | low | `LocalServerCspTests.TheDocumentStillCarriesNoPolicy` (see below) |

Findings 4 and 5 are one defect at two depths and one fix in `set_sidecar` closes
both, so they are pinned together and should be reviewed together. Each carries a
CONTROL beside it — an ordinary passing test that the live case still works —
because the obvious over-correction here is a guard that refuses everything, and
that would satisfy both pins by deleting the feature.

### What `--runxfail` caught, and why the step is not optional

`strict=True` catches a pin that unexpectedly PASSES. Nothing catches a pin that
fails for the WRONG reason, and in a green run the two are indistinguishable.
Every pin in this stage was therefore re-run under `--runxfail` and every
traceback read. **Four of the seven were wrong on the first pass:**

* two xfailed on a `TypeError` from an incomplete `Settings(...)` — the fixture
  never built, so the finding was never exercised and the marker reported success;
* the two Access pins xfailed on `FrozenInstanceError`, because `Settings` is a
  frozen dataclass and the fixture assigned to it;
* and once those were fixed, two pins *passed against unfixed code*: the
  loop-blocking one cancelled its ticker before the ticker could observe the gap
  it had just sat through, and the scrypt one sent `x-forwarded-for` where
  `_client_ip` reads `X-Real-IP`, so all 200 requests keyed on one address and the
  limiter stopped them at five.

Only after that do the numbers match the findings: 31 joins over 30 days, 10 JWKS
fetches for 10 requests, a 1.01 s loop freeze, and **200 password hashes spent by
one /48 rotating 40 of its own /64s** — the multiplication the finding describes,
observed rather than argued.

### The one that could not be an xfail

xunit has no `xfail`, and a `Skip` is the wrong shape: it stays skipped after the
fix lands, green and silent, which is precisely the half of the harness this file
exists to defend. So finding 7 is pinned as two paired methods —
`TheDocumentStillCarriesNoPolicy`, live, asserting the DEFECT and going red the
moment a policy is emitted, and `TheDocumentCarriesAPolicy`, skipped, holding the
assertion actually worth keeping. Un-skipping the second and deleting the first is
the whole of the ritual, and the first one's failure message says so.

Verified both ways: the live test fails for the right reason when un-skipped
(a real HTTP round trip against a started `LocalServer`, missing header — not a
connection error), and the alarm was confirmed by adding a CSP header to
`ServeStatic` and watching it go red.

Unlike every other test in `LocalServerTests.cs`, this one has to `Start()` the
server. The rest are pure path arithmetic over `Resolve`; the header set is only
observable on a response.

### What remediation taught, and what it cost

**A pin that counts is not a pin that checks.** The `review_day` pin counts calls
to `list_tasks`, which is the right assertion for the finding — the defect is
`O(days × lists)` — and it is satisfied by a hoist that builds the WRONG map and
answers `task: null` for every row. So a control went in beside it asserting that
the range arm and the single-day arm give the same answer, bucket for bucket.
**Its first draft spanned one day and passed a deliberately wrong hoist**
(index built from the first day's lists), because with one plan there is nothing
to get wrong. It now spans two days naming DIFFERENT lists. Every fix in this
stage was subsequently run against two or three hand-written wrong versions of
itself; two of the seven controls were widened as a result.

**The obvious reading of a suggested fix was wrong twice, in opposite ways.**

* For the Access `kid`, the audit says "cache negative kids for a short
  interval". A per-kid cache is exactly what that describes and it buys *nothing*
  — `kid` is a header field the caller writes, so the attacker never repeats one.
  Measured with the cache in place: still one fetch per request across ten
  distinct kids, and the pin stayed red. The bound had to go on the FETCH, not on
  the kid.
* For the login budget, the audit offers "a global token bucket **or** a global
  failure counter with its own lockout". The second is a denial of service in its
  own right: a global counter has no key to exempt the owner by, so an attacker
  who burns it locks the account holder out for the window. The bucket also had
  to REFUND a verified password, or the owner exhausts it by using the app —
  which is what the new control asserts, and what nothing in the suite covered.

**Two tests were edited as part of a fix, and both are on the record.**

* `AccessVerifier.verify` became `async def`, so eight synchronous call sites
  across two files were wrapped in `asyncio.run(...)`. Every assertion is
  unchanged; only the call is. That is an API-shape change rather than a pin
  edit, and the loop-blocking pin anticipated it in as many words ("offloading to
  a thread and going async are both correct repairs").
* The systemd pin's ANTI-VACUITY GUARD was widened. It read `assert rw` — "the
  unit declares no ReadWritePaths at all, has it been renamed?" — a fair question
  while the answer was a `ReadWritePaths` line, and the wrong one the moment the
  correct fix removed it: `StateDirectory=tasks` makes the directive unnecessary,
  so a unit with none was about to be indistinguishable from a unit that had lost
  its writable path entirely. It now accepts either. **The assertion that detects
  the finding was not touched**, and the distinction is the one worth keeping:
  weakening the assertion is pin-fixing, correcting a guard that mis-modelled the
  fix space is not.

**Docker was unavailable, and 240 tests skip without it.** Seven of the nine
`review_day` tests and both login-lockout tests are `@pytest.mark.radicale`, so
the two changes with the widest blast radius had almost no local coverage. Rather
than defer to CI, their contracts were driven in-process against a real
`TaskService` and a real `create_app` before each landed — the uniform `task` key
on every kind, an unplanned day in a range carrying no entries, read-only-ness,
five wrong passwords still locking out, sixty concurrent guesses still evaluating
exactly five. Two probes, thrown away after. Worth repeating in stages 3-5, which
touch the same suites.

**One duplication was closed that no behavioural test could reach.** The desktop
client cannot borrow the backend's policy at runtime, so it builds its own — and
each suite only ever compared its own side. `test_the_desktop_client_builds_the_
same_policy` reads `LocalServer.cs` and compares the directive sets. It is a
source-shape assertion, which `test_backlog_stage5.py`'s header disowns as a
SUBSTITUTE for a behavioural one; it is not a substitute here, it is the only
reader that sees both sides.

### The one that does not land by merging

Finding 6 moves the SQLite cache to `/var/lib/tasks/tasks.db`, granted by
`StateDirectory=tasks`. `setup.sh` will not rewrite an `/etc/tasks/tasks.env`
that already exists, so **an install made before this change still points
`TASKS_DB` at a path the narrowed sandbox no longer grants, and the service will
fail to open its cache.** `docs/DEPLOY.md` carries the one-time migration: stop,
move `tasks.db` and its `-wal`/`-shm` sidecars, rewrite `TASKS_DB`, start. Move
the file rather than letting a fresh one appear — it holds the sidecar-class
tables a resync cannot rebuild.

`setup.sh` deliberately gained no `install -d` for the new directory. systemd
creates it, and a new absolute path in that script would escape the four literals
`test_backlog_aug19_stage45.py`'s harness redirects and really create
`/var/lib/tasks` on whatever machine ran the suite. Checked after the change that
it does not.

And what the file assertion still cannot say: that systemd then REFUSES the
write. That needs a real host, and it stays recorded here as verifiable only
there — as does the WinForms dock order in stage 4, for the same class of reason.

## Stage 3 — Silent data corruption ✅ DONE

12 findings · 9 medium, 3 low · **closed** · `backend/tests/test_backlog_aug25_stage3.py`,
`frontend/src/backlog.aug25.stage3.test.tsx`

All twelve are fixed and ticked in `docs/AUDIT.md`; every `xfail`/`it.fails`
marker is gone and those tests are ordinary regression tests that must stay
green. Ten commits, grouped by file, each carrying the pin it closes, the control
that stops the obvious over-correction, and the extra tests its mutation pass
demanded. **One NEW finding was opened by this stage's own verification** and is
recorded rather than fixed — see "What remediation taught" below.

Nothing raises, nothing is logged, and the answer is quietly wrong. Both closed
sweeps call this the dangerous stage, and `backlog.aug19.stage3.test.tsx`'s header
names the theme these twelve keep: *state that overwrites or discards the user's
real data without saying so*.

Two shapes recur. Six are **a whole-array or first-match answer to a question
about one row**: a booking-link rollback that restores a snapshot of every link,
a reorder that re-finds the dragged row by bare uid across the merged
multi-list array, a tag field that re-splits a joined string on every save. The
other six are **a write that half-happened**: a pointer gesture the platform
aborted committed as if released, a task authored and then re-authored when only
the day write failed, a move whose copy landed and whose delete did not.

| # | Finding | Where | Sev | Pin |
|---|---|---|---|---|
| 1 | A time-only drag skips the desynchronization check entirely, so a BYHOUR/BYMINUTE rule moves only… | `backend/tasksd/ical/edit.py:1294` | medium | `test_a_time_only_drag_of_a_time_pinned_series_neither_desynchronizes_it_nor_gains_an_occurrence` |
| 2 | smylte_list_tasks' due filters resolve in the server's timezone while its ordering was fixed to… | `backend/tasksd/mcp/api.py:453` | medium | `test_the_due_filters_file_a_deadline_on_the_day_the_owner_sees` |
| 3 | A failed booking-link toggle rolls back a whole-array snapshot, reverting a concurrent toggle… | `frontend/src/components/SchedulingView.tsx:83` | medium | `a failed booking-link toggle > rolls back only the link that failed` |
| 4 | A cancelled pointer gesture COMMITS the half-finished dashboard drag instead of discarding it | `frontend/src/components/HomeView.tsx:265` | medium | `an aborted dashboard drag > discards a gesture the platform cancelled` |
| 5 | Drag-to-reorder resolves the dragged row by bare uid, so with one UID in two lists the wrong row… | `frontend/src/data.tsx:588` | medium | `reordering with one uid in two lists > moves the row the user dragged, …` |
| 6 | Any save from the event editor splits a CATEGORIES value containing a comma into two tags | `frontend/src/components/CalendarView.tsx:907` | medium | `the event editor > keeps a category containing a comma whole across an unrelated save` |
| 7 | endFromDuration treats P1D/P1W as exact milliseconds, so a DAVx5 DURATION-only event gains an hour… | `frontend/src/calendar.ts:72` | medium | `the event editor > seeds and saves a nominal DURATION at the same wall clock` |
| 8 | Retrying the add box after a failed day-entry POST creates a second real task on the CalDAV list | `frontend/src/components/TodayView.tsx:1236` | medium | `the Today add box > does not author a second task when the retry follows a failed day write` |
| 9 | Escape discards an unsaved reflection (and an unsaved capacity) because both commit only on blur | `frontend/src/components/ShutdownRitual.tsx:316` | medium | `the shutdown ritual > keeps a reflection the owner closed with Escape` |
| 10 | move_event has no replay tolerance: a failure between the destination PUT and the source DELETE… | `backend/tasksd/sync/engine.py:442` | low | `test_a_move_whose_delete_reply_was_lost_can_still_be_completed` |
| 11 | Changing a repeating event's cadence and then picking "This event" silently discards it and… | `frontend/src/components/CalendarView.tsx:934` | low | `the event editor > never drops a cadence change on the floor` |
| 12 | A line pinned to "task" that the parser read nothing in writes its untrimmed text as the VTODO… | `frontend/src/components/TodayView.tsx:1240` | low | `the Today add box > trims the summary of a line the parser read nothing in` |

SPA pin names are abbreviated: each is prefixed `2026-08-25 — ` in the file.
The `Where` column carries the line as it stands NOW; several of AUDIT.md's own
anchors are a few lines off, having been taken against the audit copy, and each
pin's `reason` string names the current one.

**Placement note.** Finding 9 (Escape discards the reflection) is stage 3 rather
than stage 4 even though it looks like a dialog bug, because aug19's stage-3 SPA
theme is exactly the sentence above: the user typed prose into the app's one
free-text field, whose own hint promises "Kept with the day", and it is gone.

**Seven of the sixteen tests are CONTROLS**, and one of them earned its place
during this stage rather than in principle — see below. Every pin here has an
over-correction that would satisfy it by deleting the feature: refuse every
reschedule, stop sending `tags`, stop rolling anything back, latch the create.
The controls are the half that says the feature still works.

### What `--runxfail` and the `it.fails` flip caught this time

The step is not optional and stage 2's note says why. This stage it caught two
things, one in each half.

**The control caught an over-correction, in a fix simulation rather than in
review.** Each backend pin was re-run against a *simulated* fix to confirm it
goes `XPASS(strict)` — red — when the bug is closed. The obvious simulation for
finding 1 was "refuse whenever the rule carries `BYHOUR`/`BYMINUTE`/`BYSECOND`",
which flips the pin correctly **and fails the control**: a DAY-only drag of
`FREQ=WEEKLY;BYDAY=MO;BYHOUR=9` desynchronizes nothing and must still rotate. The
refusal has to be conditional on the TIME OF DAY having changed, which is what the
audit's suggested fix says and what a pin alone would not have held anyone to.

**One SPA pin was failing on a harness fault that looked exactly like the
defect.** `data.tsx` fans out with `lists.map((l) => api.tasks(l.id))` and
concatenates, so `m.tasks.mockResolvedValue([...])` answers EVERY list with the
same rows and the pane renders each task twice. Finding 5 is the only test in the
tree with two lists, so no other suite has ever met this; flipped from `it.fails`
to `it`, it read *"Found multiple elements with the text: A home copy"* — a query
error, three assertions before the one that matters. Green, it was
indistinguishable from a real pin. The fixture now answers per list.

Two smaller notes from the same pass:

* **jsdom does not fire `blur` on unmount**, which the plan had flagged as the
  one thing that might force finding 9 onto the browser tier. It agrees with
  Chrome and Safari here, so the pin stays in the jsdom file. Decided by running
  it, not by reasoning about jsdom.
* **jsdom implements no pointer capture at all.** `HomeView.onPointerDown` calls
  `setPointerCapture` unconditionally, so without a stub the handler throws
  before any drag starts and BOTH dashboard tests report "nothing was committed"
  — which is finding 4's own passing condition. vitest reports the `TypeError` as
  an unhandled error rather than a failure, so the pin would have been green and
  worthless. The `clientWidth` stub has the same shape and the same danger, which
  is why the control beside that pin is written FIRST and is load-bearing: it is
  the only thing that proves the harness can produce a drag preview at all.

### One half of a finding deliberately left unpinned

Finding 2 names two skews: the `due_before`/`due_after` bounds, and `overdue_only`
against `datetime.now()`. Only the first is pinned.

The second is left out on purpose, and the reason is the rule this file keeps
about naming a class rather than a repair. Whether a date-only deadline is
"overdue" depends on how it resolves to an instant — midnight or end of day — and
under the audit's own suggested fix (resolve the bound in `home_timezone`) a
date-only task due today in Chicago is still `due < now` once Chicago's midnight
has passed. So the fix does not necessarily change the answer, and any pin would
be pinning one design decision. Driving it at all also needs a frozen wall clock
this suite has no library for. Whoever fixes the filters should settle the
question explicitly and write the test that follows from the decision.

**Settled during remediation, as that last sentence asks.** The MCP filter now
follows the app's OWN rule rather than inventing a third: `util.ts::isOverdue`
says an all-day item is not overdue until its whole day has passed, and
`service._due_day` resolves a deadline in `home_timezone`. `_due_parts` returns a
deadline as `(due_at, overdue_at)`, and for a date-only value `overdue_at` is the
start of the NEXT calendar day in that zone — both rules at once.

Adopting the day rule is what made it testable, which is the part worth keeping.
Under the "midnight" reading, whether today's date-only task is overdue depends on
what hour the test runs, so there was nothing to assert and the "frozen wall
clock" problem above was real. Under this one, today's is never overdue and
yesterday's always is, at any hour — so the test needs no clock at all.

### What remediation taught, and what it cost

**A mutation pass found something in nine of the twelve.** Every fix was run
against two to five hand-written wrong versions of itself before its commit. What
survived was not usually a wrong fix — it was a *second manifestation the pin
could not see*, and each one became a test:

* **`reorder`'s TARGET lookup.** Keying only the DRAGGED row on `taskKey` passes
  the pin and the second manifestation both, because in each the duplicated uid's
  first occurrence IS the row being dropped on. The test now drops onto the LATER
  copy.
* **A DURATION's two halves have an ORDER.** Nominal-then-exact and
  exact-then-nominal agree everywhere except one shape: `P1DT2H` starting an hour
  before spring-forward is 03:00 the next day one way and 04:00 the other. Five of
  six table rows passed the swapped version.
* **`CapacityStep`.** The reflection is pinned; the capacity is named in the
  finding's prose and is not. Fixing only the pinned one closes the finding and
  leaves "until 6pm" typed and Escaped exactly as lost.
* **The retry ref's SCOPE.** Remembering a failed line's client_id is the fix;
  remembering it for the NEXT line, or past the retry that succeeded, are two new
  bugs, and both survived until they had tests.
* **A CSS assertion that was reading its own comment.** The `touch-action` test
  matched the raw stylesheet, and the comment above the rule names both selectors
  and says "scoped to `.arranging`" — so a mutation that dropped the scoping
  passed. It strips comments first now. This is the same shape as stage 2's
  vacuous pin, in a different disguise: **a test that greps source text can be
  satisfied by prose.**

**The pin's accepted alternative was the unsafe one, once.** The move-replay pin
says a rollback on any delete failure and replay tolerance "both reach the same
place", and for the case it drives they do. They do not in general: a transport
error is a lost REPLY as often as a lost request, so rolling back there deletes
the one remaining copy and the event is gone from BOTH calendars. That mutation
passed the pin AND its control. A duplicate is recoverable; a deletion is not.

**Verifying a fix's premise found a new bug, and it was three bugs.** The cadence
fix is only correct if the backend's `split_series` really re-rules the tail, so
that was driven in-process before relying on it. It does — and it also writes the
tail's DTSTART as a FLOATING time, dropping the TZID even with a `VTIMEZONE`
present. Recorded as an open finding first and fixed next, in its own commit
after this stage closed; driving the other two anchor consumers before fixing it
showed the same defect in both, each failing differently:
`apply_occurrence_override` wrote a floating RECURRENCE-ID, which stops matching
the instance the rule generates so "edit this one" renders as a DUPLICATE, and
`exclude_occurrence` wrote a floating EXDATE, which excludes nothing so a deleted
occurrence comes back. A UTC series lost its zone too.

All three read their anchor from `_anchor_from_iso`, which had an arm for an
AWARE ISO and none for the naive one the read path actually emits — **a guard as
wide as the set it enumerates**, which is the pattern this whole sweep's header
names. Its own docstring explained the arm that was there.

**Two decisions where the shape of the fix mattered more than the fix.**

* `durationMs`'s return shape was the open question, and the answer was neither
  option the plan listed. `splitDuration` is now the one parser and returns
  `{nominalDays, exactMs}`; `durationMs` is a thin wrapper over it. One parser, so
  the overflow and refusal behaviour its own tests pin cannot drift — and no edit
  to a closed finding's control.
* "This event" cannot carry a cadence change, and the plan said to DISABLE the
  Repeat select while that button is on screen. It cannot: the scope prompt
  REPLACES the form, so a disabled control is not visible to disable, and the
  pin's own refusal branch — dialog still open, Repeat still reading "weekly" —
  would be unsatisfiable. The refusal sends the user back to the form with the
  change still in it instead, and the prompt warns before they choose.

**One deliberate test edit**, recorded in AUDIT.md beside its finding:
`backlog.stage4.test.tsx` calls `d.reorder` directly and now passes two rows
instead of two uid strings, because the signature widened. Only the argument
shape changed. The `TagInput` conversion needed one more — the control types into
a chip control rather than rewriting a comma-joined string — which is the
affordance the finding's own suggested fix asks for.

## Stage 4 — User-visible correctness & rendering

13 findings · 5 medium, 8 low · **OPEN** · `frontend/src/backlog.aug25.stage4.test.tsx`,
`frontend/src/backlog.aug25.stage4.browser.test.tsx`

Something on screen is wrong, missing, or unreachable — and unlike stage 3 the
user can SEE it, which is the only reason it sorts lower.

Two shapes recur, and both are about a failure the app cannot tell from an
absence. **Three turn a fetch failure into a confident lie**: one bad list
empties every task pane and each one then says "Nothing to do here.", a 502 on
`/api/me` hands the owner a sign-in card, a failed day read shows a blank day
that swallows the next write. The disk mirror, which exists exactly so those
cases still have something to show, is itself cleared on mount. **Three are an
affordance that is not there**: an indicator pointing at the wrong gap, a month
grid no keyboard can reach, a stale alert standing over a fresh choice.

| # | Finding | Where | Sev | Pin |
|---|---|---|---|---|
| 1 | One failing task list blanks the whole account's tasks — every pane then says "Nothing to do here."… | `frontend/src/data.tsx:217` | medium | `one task list that will not load > still shows the lists that answered` |
| 2 | The calendar's disk mirror is wiped on every cold boot: the logout-clear effect also fires on mount… | `frontend/src/data.tsx:776` | medium | `the disk mirror on a cold boot > survives a mount that happens before /api/me has answered` |
| 3 | Boot treats "can't reach the server" as "signed out": a network drop or a 502 on /api/me hands the… | `frontend/src/App.tsx:179` | medium | `booting with the server unreachable > does not hand the owner a sign-in card` |
| 4 | The Today tab's drop indicator draws above the target on a downward drag, but the row lands below it | `frontend/src/components/TodayView.tsx:1761` | medium | `the Today tab > points at the gap the row will actually land in` |
| 5 | A failed day read leaves the Today tab blank with no error, no empty state and no retry | `frontend/src/components/TodayView.tsx:646` | medium | `the Today tab > says the day could not be read, and does not swallow the next add` |
| 6 | "That time was just taken" stays on screen after the visitor does what it told them to do | `frontend/src/components/BookingPage.tsx:288` | low | `the booking page after a taken slot > clears the warning once the visitor picks another slot` |
| 7 | The archived-calendar agenda's negative margins are sized for a .modal but it renders inside the… | `frontend/src/styles/app.css:691` | low | **browser** · `the archived-calendar agenda on a phone > stays inside the sheet that actually contains it` |
| 8 | The mobile-only hover rules on the sidebar bar leave the "View completed" toggle stuck in its… | `frontend/src/styles/app.css:838` | low | **browser** · `the phone-only hover rules > are all guarded by a hover-capability query` |
| 9 | Removing the last Home module puts the five stock modules back on the board | `frontend/src/components/HomeView.tsx:52` | low | `clearing the dashboard > does not put five modules back when the last one is removed` |
| 10 | The whole month grid is keyboard-inoperable: day cells and event chips are unfocusable divs | `frontend/src/components/CalendarView.tsx:636` | low | `reaching the month grid from a keyboard > exposes the event chip and the day cell as operable controls` |
| 11 | Shutdown step 2 reports "Everything on today is done" after the owner MOVED everything to tomorrow | `frontend/src/components/ShutdownRitual.tsx:82` | low | `the shutdown ritual, step two > does not call a day that was postponed a day that was finished` |
| 12 | The Today row's ✕, estimate and + are ~16–19px tap targets on the phone-primary surface | `frontend/src/styles/app.css:1715` | low | **browser** · `the Today row on a phone > gives every control a 44px tap box` |
| 13 | The update notice is docked at the wrong end of the z-order, so it covers the top 36 px of the app | `desktop/Smylte.Desktop/MainForm.cs:49` | low | *none — see below* |

SPA pin names are abbreviated: each is prefixed `2026-08-25 — ` in its file. The
`Where` column carries the line as it stands now, which for several of these is a
few lines off AUDIT.md's own anchor.

**Eight of the twenty-two tests are CONTROLS.** Every pin here has an
over-correction that would satisfy it by deleting the feature: stop signing out
on any failure and a genuinely lapsed session stares at an empty shell; delete
the clear-on-logout effect and the next account sees the last one's calendars;
drop the negative margins and the agenda stops bleeding in the one parent it is
supposed to.

### Three findings on the browser tier, and one of them is not a measurement

The tier from `bcf38cf` earns its keep here. The archived-agenda overflow is
exactly the class of defect its header describes: measured at 390×844, the
settings sheet's `.set-body` has `clientWidth` 362 against `scrollWidth` 380 —
eighteen pixels of sideways scroll — and `.agenda-ev` starts at x = −4 against a
sheet edge at x = 0, so the 2px `--ev-c` rule that says which calendar the
preview belongs to is painted outside the sheet and clipped. Nothing that reads
app.css as text can see any of that. The tap targets are the same story with
numbers: `.check` 21×21, `.today-est` 42×34, `.today-drop` 27.2×28,
`.today-plus` 29×31.

**The hover-latch pin is the exception, and it says so in its own docstring.**
Headless Chromium reports `hover: hover` and `pointer: fine`, so `:hover`
behaves correctly there and no amount of hovering reproduces a touch latch. What
the browser CAN answer — and what the fix actually changes — is whether the
declaration is fenced off from devices that have no hover, so the pin walks the
CSSOM (the rules a browser really built, not a regex over source text) for any
`:hover` nested under a `max-width` query and not under a hover query. Swept
rather than enumerated, and measured: today it finds exactly one, and it is the
finding's own `.side-mobile-add:hover, .side-mobile-completed:hover`.

**44px, not 40.** The tap-target pin asserts the accessibility guideline rather
than the finding's own suggested `min-height: 40px`, and sweeps `.today-row
button` rather than the three selectors the finding names — this stylesheet's
recurring failure is a guard only as wide as the set it enumerates, and the
closed sibling finding above this one was itself a rule that named three classes
and reached none of them. Accepted cost, decided rather than discovered: a Today
row goes from ~53px to ~62px, so roughly 13 rows fit an 844px phone instead of
16.

The harness those two files share (`viewport`, `mount`, `box`) moved to
`src/test/browser-measure.ts` when the second one arrived. The two lines worth
not duplicating are the order of `mount` and `document.fonts.ready`, and the
`requestAnimationFrame` after it.

### The one with no pin

Finding 13 — the update notice docked at the wrong end of the z-order — ships
**unpinned**, following finding 62's precedent rather than quietly dropping it.

WinForms lays docked children out in reverse child-index order: the highest index
is laid out first and takes the outer edge, and a `DockStyle.Fill` child claims
the whole remaining rectangle without shrinking it for children laid out after
it. `MainForm` sets the opposite arrangement, so `_web` is sized to the full
client rectangle and `_notice` is then placed in the top 36px ON TOP of it —
covering the SPA's header row and swallowing clicks in that band.

Asserting the outcome needs a Windows host with a realised control tree and a
message loop, which CI does not have. The only CI-reachable pin is a
`SetChildIndex` source-shape assertion, and `test_backlog_stage5.py`'s own header
explicitly disowns that shape as a substitute: it would go green the day the
indices were written in the right order and say nothing about whether the strip
displaces the web view. A pin that cannot fail for the right reason is worse than
none, because it reads as coverage.

So: verify by hand on Windows. Publish a newer version so `ClientOutdated` is
true, and check the SPA's header row is pushed DOWN rather than covered. The same
inversion is inside the strip — `BuildNotice` adds the Fill label last, so the
two Right-docked buttons paint over its right end — and one fix should carry
both.

### What the `it.fails` flip caught this time

Stage 3's note says the flip is not optional. This stage it caught a pin that was
**vacuous for a reason that had nothing to do with its finding**.

The disk-mirror pin writes a calendar to the mirror and asserts the provider
still holds it after a mount with `enabled: false`. But `cache.ts` keys every
entry on the account name and `write` NO-OPS without one — and the shared
`beforeEach` calls `setCacheUser('')` to keep every other suite cold. So nothing
was ever mirrored, the probe read `NONE` for the ordinary reason, and it would
have gone on reading `NONE` after the fix. Green, it was indistinguishable from a
real pin. It now names a user and carries an anti-vacuity guard —
`readCachedCalendars()` must come back non-empty — before the render it is
actually about.

Two smaller ones from the same pass. `.dash-mod .label` also matches labels
inside a module BODY, so the dashboard pin reported twelve modules where there
were five; the selector is now the header's own label. And the failed-day-read
pin asserted its two halves in sequence, so the second never ran while the first
was red — a fix to only one of them would have read as complete. Both halves are
now one object assertion, which is the shape the month-grid pin already used.

## Stage 5 — Delivery infrastructure & test gaps

2 findings · 1 medium, 1 low · **OPEN** · `backend/tests/test_backlog_aug25_stage5.py`

Both are the same shape: a control that exists, works, and has nothing holding it
in place.

| # | Finding | Where | Sev | Test |
|---|---|---|---|---|
| 1 | Test gap: no test exercises `buffer_minutes` across a DST transition — reverting `pad()` to wall-clock arithmetic passes the entire backend suite | `backend/tasksd/scheduling.py:239` | medium | `test_a_buffer_is_real_time_on_both_sides_of_a_transition`, `test_the_buffer_a_spring_forward_slot_list_actually_honours` |
| 2 | Test gap: `AccessVerifier` and the whole `access_required` posture have zero coverage, including the third fail-closed startup refusal | `backend/tasksd/access.py:32` | low | twelve tests, from the off-path no-op to `test_a_jwks_outage_fails_closed` |

### Neither is a pin, and that is the result rather than an omission

**Both subjects turned out CORRECT**, so both are ordinary passing tests with no
marker — `xfail(strict=True)` over correct code XPASSes and reds the build the
moment it runs. This is the rule the aug19 sweep established the hard way (three
of its four gaps came out ordinary; the fourth found two live defects), and it is
why the plan for this stage was *write both, run both, THEN classify* rather than
deciding in advance.

So `test_backlog_aug25_stage5.py` is the one file in this sweep with no markers,
sitting beside three that carry them. Its findings stay OPEN in AUDIT.md with a
`**Covered by**` note rather than a `**Pinned by**` one: the gap itself is
filled, and the entry is ticked when the sweep is reviewed like the other 32.

### Every one confirmed against the regression it exists to catch

A test written over correct code and never seen red is a claim, not evidence —
which is precisely the criticism finding 1 makes of the existing DST battery. So
all eighteen were run against four mutations, each applied alone and reverted:

| mutation | what it stands for | what fails |
|---|---|---|
| `pad` → `Interval(iv.start - b, iv.end + b)` | the audit's own mutation, which passes the entire rest of the suite | both transition cases and the slot list |
| `verify` → `except PyJWKClientConnectionError: return` | the sympathetic "don't lock people out during a Cloudflare outage" change | `test_a_jwks_outage_fails_closed`, and nothing else |
| the `access_required` guard in `create_app` disabled | the third fail-closed startup refusal being dropped in a refactor | all three startup cases |
| `decode(…, options={"verify_aud": False, "verify_iss": False})` | a verifier that checks the signature alone | the wrong-audience and wrong-issuer cases |

The second row is the one worth reading twice. Access fails closed today only
because `except Exception` happens to catch `PyJWKClientConnectionError` along
with everything else; one sympathetic early `return` turns the edge gate into a
no-op for the duration of an outage, and before this file `pytest -q` had nothing
to say about it.

Two implementation notes, both about comparing times:

* The `pad` assertions compare **instants**, not local values. Every datetime in
  the scheduling tests shares one `ZoneInfo` object and CPython short-circuits
  `==` to a naive field comparison when `self.tzinfo is other.tzinfo`, so a local
  comparison cannot tell the two versions of `pad` apart at all. That is the same
  trap the closed fall-back findings were about, one function over.
* The ordinary-day case in the same battery is not padding: it is what makes a
  failure on the two transition days attributable to the transition rather than
  to the shape of the test. A week after the spring forward the zone is CDT all
  day and the two versions of `pad` agree, which is the point.

# Sweep — 2026-08-19 · closed

`docs/AUDIT.md` is the evidence. This is the plan for closing it.

**0 open, 85 closed.** ✅ **The sweep is closed.** All five stages are done, and
so are the seven findings the Stage 3 and Stage 4 adversarial reviews filed and
never staged.

### What the closing reviews established — and the number that did not improve

Two adversarial reviews ran over the whole stage, as Stage 4 had: one on the
correctness of the fixes, one writing plausible-but-wrong fixes to see how many
the suite would accept.

**The wrong-fix reviewer got 16 through — up from 14 at Stage 4.** The diff
reviewer found four regressions this stage introduced, three of them material.
Both numbers are worse than last time, on a stage that was supposed to be
smaller and safer. That is the honest headline.

Three things are worth carrying forward.

**Every regression was in shared machinery, not in the finding's own code.**
`allSettled` fixed the month and broke the disk-mirror fallback, because
`eventsFor` tests presence and `[]` is truthy. The banner replaced a toast that
also covered a page nobody thought about. Re-keying the pane stopped at the drag
paths. The pattern is not carelessness in the fix; it is that a fix to a shared
seam changes every caller, and the finding only names one.

**Two of the four were fixes to fixes — and one had a paragraph justifying it.**
`find_free_time`'s note argued at length that UTC has no transitions, which is
true, and stopped one line before `_as_dt` converts back to local, which is
where they are. A written rationale is not evidence; it is a claim with more
words. The reviews falsified five such notes, and the corrections are in place
rather than the notes being quietly deleted.

**The pin holes were nearly all one shape: a filter that no longer matches.**
`_INSTALLS` had no `pip`, so three jobs were exempt. The Escape table was a
hand-written list. The 204 pin drove one route of four. `_third_party_jobs` was
a denylist used as a control. The stub answered every query the same. In each
case the assertion was right and its REACH was wrong — which is invisible from
inside, because everything it does reach passes. Where possible the reach is now
derived from the code (importers of `useEscape`, handlers mentioning 204, jobs in
the workflow) rather than enumerated by hand.

**The process mistake, recorded because it cost something.** Both reviews were
run concurrently against one working tree and interfered — the diff reviewer saw
the other's mutations appear and vanish, and a stop-hook fired asking for the
in-flight wrong fixes to be committed. They should have been serialised, or given
separate worktrees. It did surface one genuine finding by accident (the
`SettingsMenu` binding), which is luck, not method.

One of the 85 is closed as a DECISION rather than a fix: `_desynchronizing`'s
refusal of a `FREQ=DAILY;BYDAY=…` drag stays, because the entry's premise was
false (the drag never worked; the 422 was the improvement) and the one attempt
that shipped destroyed user data. It is handed off as
[#63](https://github.com/nicholaskmitchell/smylte/issues/63) with the whole
record, and two tests hold the line — one pinning the refusal, one pinning the
OUTCOME any future fix must satisfy.

The sweep opened at 36/44. Stage 4 closed 28 — its own 21 plus the 7 the Stage 3
adversarial review had left open — remediation FILED 5 more along the way, and
the closing review REOPENED one (D5, `_desynchronizing`), so the open count fell
by 22 rather than 28. Those 14 were then closed in turn, taking the sweep to 0.
Where they had come from:

| where it came from | count |
|---|---|
| the sweep itself (all stage 5) | 7 |
| filed by the adversarial review of Stage 3 | 0 |
| filed by that review's own follow-up | 1 |
| REOPENED by the Stage 4 review (D5) | 1 |
| filed during remediation (see `docs/AUDIT.md`) | 5 |

The five filed during remediation are worth naming, because four of the five were
found by writing a test rather than by reading code: `HEAD /book/<token>` 404ing
(found by asserting it in a pin and watching it fail on the spelling that already
worked), `TasksView`'s uid-keyed maps, the `useEscape` consolidation, one failing
calendar blanking a whole month, and `find_free_time`'s DST-unsafe end
arithmetic. Closing a finding properly is itself a way of finding the next one.

All 7 of those remaining sweep findings are closed, and their pins — which
included 2 written as `xfail(strict=True)` / `it.fails` — are ordinary passing
tests now (see "Test gaps that were only gaps" below). **All 7 of the review's
findings are closed**, each pinned first, as is the 8th from that review's own
follow-up. The review's other 3, the ones Stage 3 itself caused, are closed —
along with 3 more the follow-up found in those very fixes. See `## Filed during the Stage 3 adversarial review` in
`docs/AUDIT.md`. One is deliberately **not** pinned; see
"The one that was not pinned" below. The harness
described under *Stage 0* further down still applies unchanged; these pins live in
their own files so the closed 2026-08-16 stages stay closed:

| stage | pins |
|---|---|
| 1 | `backend/tests/test_backlog_aug19_stage1.py` |
| 2 | `backend/tests/test_backlog_aug19_stage2.py` |
| 3 | `backend/tests/test_backlog_aug19_stage3_ical.py`, `..._stage3_core.py`, `frontend/src/backlog.aug19.stage3.test.tsx` |
| 4 | `backend/tests/test_backlog_aug19_stage45.py`, `frontend/src/backlog.aug19.stage4a.test.tsx`, `...stage4b.test.tsx` |
| 5 | `backend/tests/test_backlog_aug19_stage45.py`, `frontend/src/backlog.aug19.stage4b.test.tsx` |

### The sorting criteria

Same five buckets as the 2026-08-16 plan, and the same ordering rule —
**cheapest-and-nastiest first**. A finding lands in a stage by what its failure
*does*, not by which file it is in:

1. does untrusted input reach an unhandled exception? → **Stage 1**
2. can an adversary make the work or the storage unbounded, or bypass a control? → **Stage 2**
3. does it return a wrong answer without raising? → **Stage 3**
4. can the user see it is wrong? → **Stage 4**
5. is it in the pipeline, or in the tests themselves? → **Stage 5**

Where a finding qualifies for two, the lower stage wins: a crash that also
corrupts is a crash first. Within a stage, rows are ordered by severity.

### Test gaps that were only gaps

Four findings were `test-gap`s whose subject turned out to be *correct* — the
coverage was missing, the behaviour was not broken. Those are committed as
ORDINARY PASSING TESTS, not pins. Marking a passing test `xfail(strict=True)`
would XPASS and break the build, which is the opposite of what the harness is for.
This mirrors `test_backlog_stage5.py`, which already handles the same case.

### The one that was not pinned — and what pinning it in the end taught

Finding 62 (shutdown tearing the service down under a running sweep) shipped
with **no pin**, and the note here said why: it reproduces on demand in
isolation — swap the service's `RLock` for one that yields on release and
`close()` reliably wins the gap between two slices — but not once the rest of
its file has run. Three consecutive whole-file runs gave xfail / XPASS / xfail,
and under `strict=True` an XPASS is a red build, so pinning it would have handed
CI a coin flip. The note asked whoever fixed it to add a seam — a hook between
two slices of `sync_all` — and pin it then.

**Stage 5 closed it without the seam, and the reason generalises.** Everything
above is about pinning the RACE: whether `close()` happens to win a particular
gap. That is genuinely non-deterministic and no amount of care makes it a good
test. But the FIX's invariant is not a race — *a closed service must not touch
its connection, whenever it was closed* — and that is ordinary, deterministic
and easy to assert. Two pins do, both failing against the old code every time.

The mid-sweep case still needed teardown to land between two slices, and got
there by making the ENGINE's `sync` call `close()` on the first collection: a
stub in the test, not a hook in the service. That is the transferable part —
**when a race is hard to pin, look for the invariant the fix establishes, and
for a seam that already exists in the collaborators rather than one the
production code has to grow.** The race itself is still unpinned, and that
remains recorded rather than quietly dropped: nothing proves the interleaving
impossible, only that it is now harmless.

## Stage 1 — Crash paths ✅ DONE

7 findings · closed · `backend/tests/test_backlog_aug19_stage1.py`, with the read-side contract updated in `backend/tests/test_dav_xml.py` and the multiget fallback covered in `backend/tests/test_sync.py`

Untrusted input reaching an unhandled exception — a 500 where a 4xx was owed. Cheapest to fix, nastiest to leave: each one is an adversary turning odd input into a stack trace, and two of them commit a write before they crash.

All seven are fixed and ticked in `docs/AUDIT.md`; the xfail markers are gone and
those tests are now ordinary regression tests that must stay green.

Four things surfaced while fixing them, all wider than the findings as filed:

* **Findings 1 and 3 were one defect, and fixing either alone would have been
  worse than neither.** 3 let the app WRITE a U+FFFE; 1 was what happened when
  it read one back. Fix only 1 and the app still poisons its own collections;
  fix only 3 and it is still defenceless against the four other CalDAV clients
  sharing those collections. The sharpest way in was also not the one filed:
  `PublicBook.name` and `.notes` reach the booked event's SUMMARY and
  DESCRIPTION, so a stranger holding a booking link could wedge a collection.
  The same hole existed on the MCP schemas, which the finding did not mention.
* **The taxonomy wrap alone does not fix finding 1.** Turning the
  `XMLSyntaxError` into a `DavError` satisfies the pin, but `sync_all` swallows
  a `DavError` into `sync_state.last_error` — a column with writers and no
  readers anywhere in the repo — and the token never advances, so the collection
  stays wedged and silent. What actually closes it is `_multiget` refetching a
  failed batch one href at a time over GET, which parses no XML: the poisoned
  resource then costs one resource and reaches `_upsert_body`'s existing
  malformed-resource path. A pin that a partial fix satisfies is worth knowing
  about.
* **Two of the seven were fixed wrongly the first time, and their pins passed
  anyway.** `PublicBook.email` was left unguarded on the assumption that
  `_EMAIL_RE` bounded it — it forbids only `@` and whitespace, so the anonymous
  poisoning path the finding is about stayed open while the pin went green. And
  finding 5's first fix saturated the *input* before the arithmetic, which
  survives only a delta smaller than the guard: the pin drove a one-day drag, so
  a fix that broke at thirty days passed. Both pins have been widened (a
  year-long drag; all three booking fields), but the lesson is about the harness
  rather than the bugs — a pin is only as good as the range of inputs it drives,
  and "the pin passes" is not "the finding is closed". Neither was caught by the
  suite; both were caught by re-reading the landed diff against the finding.
* **A bounded UNTIL saturates rather than refuses.** Answering 422 for a
  far-future UNTIL would have been the tidier-looking repair and the wrong one:
  the foreign `UNTIL=99991231T235959Z` series that provoked the finding would
  have stayed exactly as uneditable, just with a nicer status code. Saturating
  at the rule-writing choke point keeps the series editable, and the route's new
  `except OverflowError` is only the backstop.

| # | Finding | Where | Sev | Pin |
|---|---|---|---|---|
| 1 | One U+FFFE/U+FFFF anywhere in a calendar item permanently and silently kills that collection's sync (XMLSynt… | `backend/tasksd/dav/xml.py:264` | high | `test_a_body_xml_cannot_carry_stays_inside_the_dav_taxonomy` |
| 2 | A JSON-RPC `id` of NaN/Infinity is echoed straight into JSONResponse, which refuses to serialize it — unhand… | `backend/tasksd/mcp/routes.py:489` | high | `test_a_non_finite_jsonrpc_id_gets_an_answer_not_a_500` |
| 3 | summary/notes/location/description reach Radicale with no character guard, so the app can write a value its … | `backend/tasksd/app.py:145` | medium | `test_a_task_summary_cannot_carry_what_the_read_path_cannot_parse` |
| 4 | PATCH /api/scheduling/links/{token} with an explicit null 500s and leaves a half-applied update behind | `backend/tasksd/app.py:1161` | medium | `test_a_null_booking_link_field_is_refused_not_a_half_applied_500` |
| 5 | A far-future UNTIL (repeat-until 9999-12-31, or a foreign UNTIL=99991231T235959Z) raises OverflowError — an … | `backend/tasksd/ical/edit.py:813` | medium | `test_a_boundary_until_answers_the_client_instead_of_overflowing` |
| 6 | smylte_delete_event skips the recurrence_id ISO check the HTTP DELETE route performs, so a space instead of … | `backend/tasksd/mcp/api.py:492` | medium | `test_a_malformed_recurrence_id_names_the_argument_not_the_server` |
| 7 | The body-limit middleware's 413 is dead code on every FastAPI route — FastAPI swallows _BodyTooLarge and ans… | `backend/tasksd/limits.py:73` | low | `test_a_chunked_oversized_body_is_a_413_through_the_real_app` |

## Stage 2 — Abuse & resource exhaustion ✅ DONE

7 findings (6 from the sweep + 1 filed during remediation) · closed · `backend/tests/test_backlog_aug19_stage2.py`, with the revocation contract also recorded in `docs/DEPLOY.md`

Work an adversary can make unbounded, plus the one missing security control. Everything here is reachable without credentials or survives the credential change that was supposed to stop it.

All seven are fixed and ticked in `docs/AUDIT.md`; the xfail markers are gone and
those tests are now ordinary regression tests that must stay green.

Three of the seven — 8, 11, and the one that fixing 8 uncovered — are the same
defect. All three are the
same defect (`tasksd/ical/rrule_budget.py` is the shared fix) and two things
about it are worth carrying forward:

* **The fix `docs/AUDIT.md` prescribed for 8 does not work, and was measured not
  to before anything was written.** It proposed re-emitting each RRULE with
  `UNTIL = window_end`. dateutil tests UNTIL and COUNT *inside* the yield blocks
  of `rrule._iter`, so a rule that never yields never reaches either:
  `FREQ=DAILY;BYMONTH=2;BYMONTHDAY=30` costs 3.50 s bare, 3.44 s with UNTIL and
  3.45 s with COUNT, all returning nothing. A suggested fix in the audit is a
  lead, not an instruction.
* **A satisfiability check is the obvious repair and it is wrong in both
  directions.** `BYSETPOS=5;BYDAY=MO`, `BYWEEKNO=54` and
  `BYWEEKNO=53;BYMONTH=1;BYDAY=MO` all defeat any BYMONTH × BYMONTHDAY table and
  still cost seconds; meanwhile `BYMONTH=4,5;BYMONTHDAY=31` **is** satisfiable
  (May 31), so a table would refuse a legitimate rule. Bounding the *cost*
  sidesteps the question: anything that finishes inside the budget is cheap by
  construction, whether or not it ever matches.

Finding 12 was filed as one validator and was five. Every `^…$` pattern in the
backend used with `.match()` had the same gap — Python's `$` also matches just
before a trailing newline — and three of them (`_EMAIL_RE`, `parse_duration`,
`clean_color`) were saved only by a caller happening to `.strip()` first, which
is an accident rather than a property of the validator. All five now use
`fullmatch`; `XML_SAFE_PATTERN` was checked and is genuinely fine, because a
NEGATED class cannot leave `$` sitting before a newline, and there is now a test
saying so rather than a comment. The second half of that finding — the CalDAV
href in a 409 body handed to an anonymous booker — is fixed at the raise site in
`_put_new`, so it is closed for every caller and not only for the route the
finding reached it through.

Finding 9 had the widest blast radius of anything in this stage, because the
control it adds runs on every MCP request: get it wrong and it signs every client
out on every restart, which looks exactly like the security control working. Two
details carry that risk, and each now has a test of its own. The fingerprint is
taken over the CONFIGURED credential, not the derived hash — scrypt salts
randomly, so on the dev plaintext path the hash differs every boot. And the check
in `_grant_refresh` runs BEFORE `use_refresh_token`: a refresh token is
single-use, so checking after would burn the use on a request already being
refused, and the client's next legitimate attempt would read as a replay —
killing the family and reporting a token theft that never happened. That one was
verified by moving the check and watching the test fail with exactly that
message.

Finding 13's fix has a second exclusion the finding did not ask for. Evicting
the least-recently-used token-less clients is the obvious repair; live
authorization CODES have to be excluded too, because eviction has no idleness
requirement — that is the point of it — so a registration burst timed against a
consent screen would otherwise break the flow the owner was in the middle of.

**Finding 14's first fix introduced a worse bug than the one it closed.** Gating
the settings writes on "the read succeeded" also blocks a gesture racing the
initial load — a millisecond window turned into a silently dropped preference and
a confusing toast, and four existing App tests said so immediately. The gate has
to be on "the read FAILED", which is what the finding is actually about. And the
flag has to be a ref: half the `change*` callbacks are `useCallback(..., [])`, so
they capture the first `saveSettings` for the life of the app and a value read
out of that closure is the one from before the read ever finished.

And one thing about the harness, following Stage 1's "a pin is only as good as
the inputs it drives": pin 11 was **widened before the fix landed**, with a third
override at a near anchor placed after the two far-future ones. With the
instance-count tier neutralised in-process, a budget-only fix keeps that override
— the bug — and the widened pin catches it. That is Stage 1's lesson applied
rather than re-learned, and it was applied three more times in this stage: each
widened pin here was run against a deliberately half-correct version of its own
fix (evict-anything for 13, check-after-use for 9, budget-only for 11) and
watched to fail. A pin that has never failed is a hypothesis.

| # | Finding | Where | Sev | Pin |
|---|---|---|---|---|
| 8 ✅ | A never-matching RRULE makes expansion iterate to year 9999 — both pathology guards score it "safe" because … | `backend/tasksd/ical/recur.py:178` | high | `test_a_rule_that_can_never_match_is_expanded_promptly` |
| 9 ✅ | Rotating the app password (and even TASKS_SESSION_SECRET) does not revoke any MCP OAuth grant — the document… | `backend/tasksd/mcp/oauth.py:551` | high | `test_rotating_the_credentials_ends_an_mcp_grant_too` |
| 10 ✅ | service.search rebuilds the whole collection's children map once per result row, so one uncapped FTS query b… | `backend/tasksd/service.py:331` | medium | `test_searching_a_large_list_is_not_quadratic_in_the_lists_size` |
| 11 ✅ | _reconcile_overrides probes each override with an unbounded dateutil walk — one repeat change burns minutes … | `backend/tasksd/ical/edit.py:427` | medium | `test_changing_the_repeat_is_prompt_with_a_far_future_override` |
| 12 ✅ | _check_client_id's regex accepts a trailing newline, so an anonymous booking POST answers 409 with the owner… | `backend/tasksd/app.py:157` | medium | `test_a_client_id_with_a_trailing_newline_is_refused` |
| 13 ✅ | MAX_CLIENTS refuses new registrations instead of evicting stale ones, so anonymous registrants can lock the … | `backend/tasksd/mcp/oauth.py:208` | low | `test_a_table_full_of_junk_clients_does_not_lock_the_owner_out` |
| — ✅ | _count_consumed's walk is unbounded for the same reason UNTIL is, so "this and following" on a never-matchi… | `backend/tasksd/ical/edit.py:1117` | medium | `test_splitting_a_series_on_a_never_matching_rule_is_prompt` |

The last row was filed during remediation, not by the sweep; it is under
`## Filed during remediation — 2026-08-20` in `docs/AUDIT.md` and is not counted
in that sweep's 66.

## Stage 3 — Silent data corruption ✅ DONE

24 findings · closed · `backend/tests/test_backlog_aug19_stage3_core.py`, `..._stage3_ical.py`, `frontend/src/backlog.aug19.stage3.test.tsx`

Nothing raises and the answer is silently wrong. The dangerous class, and the largest — it needed the most care per fix because the failure leaves no trace and several of these corrupt data another CalDAV client authored.

All 24 are fixed and ticked in `docs/AUDIT.md`; the xfail / `it.fails` markers are
gone and those tests are ordinary regression tests that must stay green. Finding
64 (Stage 5) went with them.

**Then three adversarial reviewers were run over the finished diff** — one on the
correctness of each fix, one on whether each pin actually catches its bug (revert
the fix, run the pin, then try a plausible half-fix), one on the trust model.
They reproduced 14 findings with runnable probes. Four were regressions
introduced BY this stage, fixed in `d325ef9`; ten are filed open. That is a 17%
regression rate on 24 fixes, and it is the most useful number this stage
produced.

**The three findings Stage 3 itself caused are now closed**, pinned before they
were fixed. Two things came out of doing it that way:

* **The pin caught a mistake reading would not have.** `recurring_ical_events`
  stamps a RECURRENCE-ID on EVERY instance it emits, including the ones a plain
  series generates — so keying the authored-length lookup on the emitted value
  matched nothing and the fix silently did not work. `override_anchors`, already
  in scope, is what tells an authored override from a generated instance.
* **Running each pin against a half-fix earned its keep immediately.** Pin A
  passed against a fix that skipped slots other overrides claim but not EXDATE'd
  ones — half of what "the next occurrence" means. It was widened before the
  marker came off. Two of the three half-fixes were caught first time; the one
  that was not is the one that mattered.
* **A design review of the three fixes found four more, one of them a blocker
  the whole suite was green over.** The exact-duration repair read the master's
  length for any instance no *authored override* claimed — and an
  `RDATE;VALUE=PERIOD` block is neither, so a four-hour commitment came back as
  thirty minutes on an ordinary January day, releasing three and a half hours to
  the booking page. Same failure the narrowing exists to prevent, different door.
  What fixed it was narrowing the trigger to the DST artifact's own SIGNATURE —
  the emitted pair states the authored length in wall clock and delivers
  something else in real time — which fails closed for every family nobody
  enumerated, instead of enumerating families.

  The review also caught the RFC citation being backwards. §3.8.5.3 says a
  DTEND-authored recurrence carries the same EXACT duration to every instance,
  which argues for repairing the case the code deliberately leaves alone —
  applying it literally is what caused the original regression. The real argument
  is §3.3.6 and it is about information: a DURATION carries the nominal/exact
  distinction in its bytes and a DTEND does not, so wall-clock preservation is
  the only non-destructive reading of a DTEND. A plausible citation is not a
  correct one.

Three things to carry forward:

* **A widened pin can encode a WRONG contract, and then it drives a wrong fix.**
  Pin 26 was widened to assert every instance holds its authored duration. That
  is not true of a DTEND-authored recurrence — RFC 5545 §3.8.5.3 carries the
  exact duration, and the master's own occurrence is the bytes the author wrote —
  and the pin drove a `_repair_span` that rewrote authored spans, turning a
  9-hour overnight shift into 8 and releasing the last hour to the public booking
  page. Widening is not free. A pin asserts a contract, and the contract has to
  be right before the range is wide.
* **Every backend pin in this stage got controls; not one frontend pin did.**
  All five frontend markers were dropped with the bodies byte-identical to their
  pre-fix versions, and four of the ten open findings are "the pin drives one of
  the N cases its own evidence names". A frontend pin needs the same
  parametrisation a backend one gets.
* **Closing a finding can open a bigger one.** Admitting every recurring row
  genuinely fixed finding 20, and made an unauthenticated request cost 9.13 s
  under the global lock. The check for "does this fix cost something the finding
  did not" is not the same check as "does this fix work".

Three are done — 18, 26 and 29, which are one defect at three sites: a duration
or a comparison evaluated on WALL CLOCK where it needed the instant. Two things
came out of it.

**Finding 64 went with them, and it was never really a Stage 5 finding.** It was
filed as a test gap — "nothing drives `busy_intervals` across a DST transition at
all" — and writing the missing case is what found 18 and 29 in the first place.
Its pin asserts exactly those two behaviours, so fixing them closed it, with no
change of its own. The stage boundaries are a sorting aid, not a partition.

**Finding 22 was in the Python port of order.ts as well as in order.ts.** The
map that gives each task one effective position was keyed on the bare uid, and
the backend keys items on `(collection_href, uid)` — so a VTODO copied between
lists in another client is two tasks with one key, and the unplaced twin
overwrote the placed one's position. `mcp/api` had inherited it from the same
source an hour earlier. Both now key on `(list, uid)`, and the cross-check corpus
was regenerated with duplicate uids in 40% of its cases: with the old keying it
drops to 300/402, so the corpus discriminates rather than merely agreeing.

**Finding 17's fix was cross-checked by running the other implementation.**
`mcp/api._display_order` claimed to mirror `frontend/src/order.ts` "key for key",
and it reproduced the wrong one of the two comparators that file exports —
`compareTasks`, whose own docstring says it is NOT how a list is ordered. Porting
`sortTasks` instead is not a comparator swap: order.ts explains that the pairwise
form is not transitive across the placed/unplaced boundary, so the port had to be
the effective-position algorithm. To know it landed, order.ts was RUN over 402
generated task sets and the outputs compared. The first attempt matched 396: the
six misses were all one thing — `localeCompare` treats case as a tertiary
difference and sorts lowercase first, which neither Python's `<` nor `casefold`
does. With `_title_key` it is 402/402, and eight of those cases are pinned as a
table because CI has no node. Two implementations of one rule in two languages
cannot be kept honest by reading them side by side.

**Findings 27 and 31 were one defect at two layers**, and they closed together
because both `_href` resolvers go through `service.resolve_list`. That is worth
noticing for the sorting rather than the fix: the sweep filed the HTTP symptom
and the MCP symptom as separate findings, in stages that would have been worked
weeks apart, and whoever took the second one would have found it already fixed.

**Two of the four edit-path fixes were wrong on the first attempt, and the
widened pins are what said so.** Finding 15's audit entry prescribes adding a
plain single-slot override beside the RANGE=THISANDFUTURE one and leaving the
range component in place. Doing exactly that leaves two components claiming one
RECURRENCE-ID value, which no reader can rank — the expansion still applied the
range override's values to every later occurrence, and the pin stayed red in a
way that looked like the original bug. What works is re-homing: the range
override MOVES to the next occurrence, keeping its RANGE and shifting its
DTSTART by the same step, so every RECURRENCE-ID value appears exactly once. And
the detached instance has to carry the range override's own times across, or
"rename this one" silently rescheduled it back to the master's hour.

**The obvious repair would have traded one wrong answer for another.** Adding the
whole DURATION to the instant fixes `PT2H` and breaks `P1D`: RFC 5545 §3.3.6
makes weeks and days NOMINAL ("the same time tomorrow", 23 real hours across the
spring-forward) and hours/minutes/seconds EXACT, and `vDuration.from_ical`
collapses `P1D` and `PT24H` to one `timedelta` — only the raw string tells them
apart. `ical.read.advance` applies each half as the RFC defines it, and pin 29
now drives the nominal cases too, so that shortcut fails the build. Both this and
the "clamp a backwards end to its start" shortcut were run and watched to fail
before the real fix landed.

| # | Finding | Where | Sev | Pin |
|---|---|---|---|---|
| 14 ✅ | A failed GET /api/settings is swallowed silently, and the next preference gesture overwrites the account's s… | `frontend/src/App.tsx:203` | high | `does not write a defaults-derived preference back over the account` |
| 15 ✅ | "This event" on the first slot of a RANGE=THISANDFUTURE override rewrites every later occurrence | `backend/tasksd/ical/edit.py:642` | high | `test_editing_the_slot_a_this_and_future_override_anchors_leaves_later_ones_alone` |
| 16 ✅ | Dragging a foreign MONTHLY/YEARLY series deletes the dragged occurrence and moves nothing else | `backend/tasksd/ical/edit.py:829` | high | `test_dragging_a_monthly_series_moves_it_instead_of_desynchronizing_the_rule` |
| 17 ✅ | smylte_list_tasks implements the comparator order.ts documents as wrong, so after one drag every newly-creat… | `backend/tasksd/mcp/api.py:133` | high | `test_a_task_created_after_a_drag_is_not_sunk_below_the_whole_account` |
| 18 ✅ | busy_intervals drops any event crossing the DST fall-back transition, so an anonymous POST double-books the … | `backend/tasksd/scheduling.py:148` | high | `test_a_meeting_across_the_fall_back_transition_still_blocks_its_slot` |
| 19 ✅ | split_event's 412 recovery always fails with a 409 and strands a duplicate recurring series on the server | `backend/tasksd/sync/engine.py:435` | high | `test_a_contended_this_and_following_split_leaves_no_duplicate_series` |
| 20 ✅ | get_events_in_range gates on the master's DTSTART, so a RECURRENCE-ID override moved earlier than the series… | `backend/tasksd/db/store.py:661` | medium | `test_an_occurrence_moved_before_its_series_start_is_still_in_the_window` |
| 21 ✅ | Logout does not clear the in-memory data mirror, so the calendar keeps painting the previous session's event… | `frontend/src/data.tsx:505` | medium | `does not paint the previous session’s events to the next one` |
| 22 ✅ | sortTasks keys its effective-position map by bare uid, so one task copied into a second list silently rewrit… | `frontend/src/order.ts:128` | medium | `keeps a dragged row where it was dropped when a copy shares its uid` |
| 23 ✅ | Folding one subtask tree silently deletes the folded state of every tree that is not currently rendered — an… | `frontend/src/components/TasksView.tsx:297` | medium | `keeps a hidden list’s folded trees when another tree is folded` |
| 24 ✅ | A zone-offset datetime accepted by _parse_datelike is written as TZID="UTC±HH:MM" and read back as floating … | `backend/tasksd/app.py:531` | medium | `test_an_event_created_with_a_zone_offset_keeps_the_instant_it_names` |
| 25 ✅ | split_series never checks that the anchor is an occurrence, so "this and following" duplicates a non-recurri… | `backend/tasksd/ical/edit.py:1084` | medium | `test_this_and_following_on_a_non_repeating_event_does_not_duplicate_it` |
| 26 ✅ | Recurrence expansion emits occurrences whose end precedes their start on the DST spring-forward (and 3x-long… | `backend/tasksd/ical/recur.py:234` | medium | `test_every_expanded_occurrence_across_spring_forward_blocks_real_time` |
| 27 ✅ | Every task tool accepts a calendar id and every calendar tool accepts a task-list id, so smylte_delete_list … | `backend/tasksd/mcp/api.py:176` | medium | `test_a_calendar_id_is_refused_by_the_task_tools` |
| 28 ✅ | A refresh that narrows scope without repeating `offline_access` returns no refresh token, and the client's R… | `backend/tasksd/mcp/oauth.py:516` | medium | `test_narrowing_scope_on_refresh_does_not_end_the_grant` |
| 29 ✅ | busy_intervals derives a DURATION-only event's end by wall-clock addition, so across a DST transition it blo… | `backend/tasksd/scheduling.py:145` | medium | `test_a_duration_only_event_blocks_its_authored_length_across_a_transition` |
| 30 ✅ | The booking ledger row is written after the CalDAV PUT, so a failure in between makes the visitor's own retr… | `backend/tasksd/service.py:919` | medium | `test_a_booking_retried_after_a_failed_write_is_not_a_conflict_with_itself` |
| 31 ✅ | resolve_list ignores the collection's component set, so a task can be written into a VEVENT-only calendar (a… | `backend/tasksd/service.py:210` | medium | `test_a_task_cannot_be_written_into_an_event_only_calendar` |
| 32 ✅ | list_oauth_grants reads `scope` as a bare column in a multi-aggregate GROUP BY, so the connections screen ca… | `backend/tasksd/db/store.py:983` | low | `test_a_grants_scope_does_not_depend_on_row_order` |
| 33 ✅ | A bulk row corrected in any field except its title replays the old client_id, so the correction is silently … | `frontend/src/components/AddMultipleModal.tsx:298` | low | `does not close reporting success on a correction the server drops` |
| 34 ✅ | POST /api/tasks/reorder writes permanent, unreclaimable sidecar rows for uids that do not exist | `backend/tasksd/app.py:1042` | low | `test_a_reorder_naming_an_unknown_uid_writes_no_sidecar_row` |
| 35 ✅ | Disconnecting a connector is not idempotent: a retry after a lost response 404s and the SPA puts the revoked… | `backend/tasksd/mcp/routes.py:410` | low | `test_disconnecting_a_connection_twice_is_not_an_error` |
| 36 ✅ | A JSON-RPC request (with an id) whose method starts with `notifications/` gets no reply at all, so the clien… | `backend/tasksd/mcp/server.py:114` | low | `test_a_notification_method_sent_with_an_id_gets_a_reply` |
| 37 ✅ | move_event maps Radicale's 409 no-uid-conflict to "calendar server unavailable" (502) instead of the conflic… | `backend/tasksd/sync/engine.py:349` | low | `test_a_move_into_a_calendar_holding_that_uid_is_a_conflict_not_an_outage` |

## Stage 4 — User-visible correctness & rendering ✅ DONE

21 findings · 8 medium, 13 low · ✅ **ALL 21 CLOSED**

Closed in eight commits: **38**, **45** (the two backend paths a stranger
reaches), **41**, **42**, **54** (the provider's fetch identity), **40**, **49**,
**50** (calendar date math), **51**, **56** (one uid, two collections), **57**
(the Completed pane's ring), **39**, **46**, **48** (appearance), **43**, **44**
(the booking-link editor), and **47**, **52**, **53**, **55**, **58** (dialogs,
forms, bounds).
Every pin was widened before its fix and then run against a plausible half-fix.

**Three half-fixes so far, and not one was caught by its own pin.** In each case
the thing that failed was a control:

| finding | plausible half-fix | what caught it |
|---|---|---|
| 54 | sort the effect dependency, leave the commit guard | `keeps a task fetch that was in flight when the order changed` — green today, load-bearing only after the fix |
| 40 | refuse every drop on a clipped event | `still resizes a window-clipped span dropped on an earlier cell` |
| 50 | subtract a day whenever "all day" is ticked | two long-standing tests in `CalendarView.test.tsx` |
| 51/56 | fix the keys, leave the mutations on the bare uid | its own pins |
| 57 | the one-hop ring test | the three-node widening |
| 39 | split the patch in `edit()` only | the `onClear` and `resetMode` widenings — not the original pin, and not the two that drive the other control kinds |
| 46 | tighten the hex regex only | its own pin |
| 48 | reset `renaming` inside `selectTheme` only | the Duplicate widening |
| 43 | clear `saving` in a `finally`, `save()` returning true | its own pins |
| 44 | validate the overlap, keep `daysToAvail`'s silent filter | `never drops a range the user typed backwards` — the assertion the `if (sent)` hatch had made unreachable |
| 47 | repair `ArchivedCalendarsSection`, not its sibling | the `ArchivedEvents` widening |
| 52 | probe the session, ignore the answer | its own pin |
| 53 | `htmlFor` with no matching id | its own pin |
| 55 | clamp in `sanitizeLayout` only | the editing-operations widening |
| 58 | bind the handler to the modal element | the document/window widening |

Thirteen half-fix checks over the stage. **Every one was caught**, but only six
by the pin the finding shipped with: four needed a case added during widening,
and three needed a control.

**The closing review then found 8 more, all caused by this stage** — recorded
under `## Filed during the Stage 4 adversarial review` in `docs/AUDIT.md`, all
closed, and one of them (D5) REVERTED with its finding reopened because the
audit's suggested fix turned out not to work at all. That is 8 self-inflicted
defects in 28 fixes, against Stage 3's 4-in-24. **The rate did not improve, and
the half-fix discipline caught none of them** — a half-fix probes the repair you
thought of, and every one of these was somewhere the repair was not.

What did catch them was three adversarial readers with different briefs, running
their own probes. That is the technique that has now worked twice; the pin
harness is what stops a closed finding reopening, not what finds the next one.

**And a category worth naming.** Two of the three high-severity ones were fixes
whose shape was *stop refusing*: #45's Enter-approves, D5's allow-the-drag, and
the OAuth scope reorder all made something that used to say no start saying yes.
When a fix removes a refusal, ask what the refusal was protecting — the finding
does not always know, and D5's did not.

Two more lessons, and neither is the one the Stage 3 review predicted.

**A pin does not catch an over-correction.** Widening makes a pin detect the BUG
more reliably; it cannot make it detect a fix that goes too far, because a pin
only ever asserts that one thing is now right. What catches that is a test
asserting something ELSE is still right — and those never appear in a count of
pins. Three of the eight rows above are controls.

**Widening pays where the finding names several sites.** #57, #39 and #48 were
each caught only by a case added during widening, and in #39's and #48's the
ORIGINAL pin passed against the half-fix. That is the review's criticism landing
exactly as it described it.

### The pin-quality review — a second reviewer, aimed at the TESTS

The closing review above read the diff for defects. A separate one then attacked
the pins themselves: it wrote 20 plausible-but-wrong fixes and counted how many
the suite accepted. **Fourteen got through.**

That is the real correction to the line above. "Thirteen half-fix checks, every
one caught" was true — of the thirteen half-fixes *I* thought of. A different
reader thinking of different wrong fixes got past two thirds of them. A half-fix
check measures the pin against the author's imagination, and reports back the
author's imagination.

Nothing the fourteen found was a product bug: the shipped code was right in every
case. They were **test holes**, which is worse in one specific way — each is a
finding marked closed that would reopen without failing anything. The four
shapes, in order of how often they recurred:

* **The pin tests the wrong layer.** #45's pins hand-wrote their own POST body,
  so they exercised the ROUTE and never the consent PAGE the finding is about.
  D4's pin called `_in_display_order` directly, so shipping the `zone` parameter
  and never passing it at the `list_tasks` call site passed everything.
* **The pin asks whether something happened, not whether it is right.** Both #44
  pins asked only that SOMETHING was submitted, so a repair pass that reverses a
  backwards range and merges overlapping ones satisfied them — and published a
  booking link advertising the middle of the owner's working day.
* **The assertion is evaluated after the state it names is gone.** #47's control
  ended `await findByText('Old work')`, which WAITS: the transient "No archived
  calendars." had already been repainted by the time the negative assertion ran.
  `useState(true)` passed a control whose docstring says it cannot.
* **The pin asserts a proxy for the property.** #51/56 counted React
  duplicate-key warnings, and `key={i}` is unique among siblings — so the index
  raised none while reinstating exactly the positional identity the finding is
  about.

And two that are neither: **a fix wired into only some of the sites its own note
names** (#48's Import path, #39's read-side repair, D1's per-VEVENT key, D2's
`home_timezone`), and **`docs/AUDIT.md` prose making claims the tests do not
support** — five of them, now corrected in place rather than quietly dropped.

The remedies are all the same move: **drive the real thing**. The page, not the
route. The call site, not the helper. Equality with what was typed, not presence.
The in-flight tick, not the settled one. Node identity, not the warning count.

**The transferable rule.** Where a pin cannot catch an over-correction and a
control can (the lesson above), a half-fix check cannot catch a pin that never
asked the right question — only a reader who did not write it can. Both reviews
now sit in the loop for the same reason: **the author is the wrong person to
measure their own coverage, and the suite passing is not evidence that it would
have failed.**

One contract was superseded rather than added to: `backlog.stage4.test.tsx` had
pinned `var(--x)` as a valid colour, and #46 makes a `var()` naming a non-colour
token invalid. Changing a green test to match new code is normally the
anti-pattern; here the older control encoded an assumption the newer finding
overturns, and the alternative was a validator that admits a value which blanks
the token. Recorded in `docs/AUDIT.md` under #46, not applied quietly.

Widening #38 also surfaced a new finding: `HEAD /book/<token>` 404s on **both**
spellings, because FastAPI's `APIRoute` does not derive HEAD from GET the way
Starlette's `Route` does. That assertion was removed from the pin rather than
kept — it is a real defect but not the one #38 names, and leaving it in would
have made the pin drive a wider fix than its own evidence supports. It is filed
under `## Filed during remediation` in `docs/AUDIT.md`.

The user can see it is wrong. Contained, mostly small, and the stage where a fix is easiest to verify by looking at it.

| # | Finding | Where | Sev | Pin |
|---|---|---|---|---|
| 38 ✅ | `/book/<token>/` (trailing slash) 404s — the SPA mount swallows it before redirect_slashes can act, though m… | `backend/tasksd/app.py:1489` | medium | `test_a_booking_link_serves_the_spa_with_or_without_a_trailing_slash` |
| 39 ✅ | Shape, density and type tokens are stored per light/dark map, so corner radius, text size, gutter, row heigh… | `frontend/src/components/AppearancePanel.tsx:69` | medium | `keeps a shape token when the theme flips to dark` |
| 40 ✅ | The resize grip on an event that runs past the six-week window truncates the span when released on its own c… | `frontend/src/components/CalendarView.tsx:556` | medium | `does not truncate a window-clipped span dropped where its grip is drawn` |
| 41 ✅ | A failed events fetch permanently records the month as "asked", so the calendar grid stays blank or stale wi… | `frontend/src/data.tsx:576` | medium | `re-requests a month whose first fetch failed` |
| 42 ✅ | The Home mini calendar never refetches on an SSE change, so its dots go stale while every other module on th… | `frontend/src/components/HomeView.tsx:141` | medium | `repaints when the account changes under an open dashboard` |
| 43 ✅ | A rejected booking-link save leaves the editor permanently disabled — the in-flight guard is set but never c… | `frontend/src/components/SchedulingView.tsx:225` | medium | `comes back to life when the save is rejected` |
| 44 ✅ | The availability editor lets the owner build overlapping weekly windows the server rejects with a 422, and s… | `frontend/src/components/SchedulingView.tsx:178` | medium | `never submits a week the server will refuse, and never drops a range` |
| 45 ✅ | On the consent screen "Cancel" is the form's default button, so pressing Enter after typing the password dec… | `backend/tasksd/mcp/routes.py:638` | medium | `test_pressing_enter_on_the_consent_form_connects_rather_than_declining` |
| 46 ✅ | isColor accepts hex literals CSS rejects (5 and 7 digits) and non-color functions like calc(), so a mistyped… | `frontend/src/appearance.ts:324` | low | `refuses hex lengths CSS does not have, and functions that are not colours` |
| 47 ✅ | The archived-calendars settings section renders "Loading…" forever when its fetch fails — the sibling sectio… | `frontend/src/components/ArchivedCalendarsSection.tsx:39` | low | `stops saying "Loading…" once the fetch has failed` |
| 48 ✅ | The theme rename row is never closed when the active theme changes, so switching themes with it open and pre… | `frontend/src/components/AppearancePanel.tsx:45` | low | `never renames the theme the user switched to with the old name` |
| 49 ✅ | endFromDuration returns the string "NaN-NaN-NaNTNaN:NaN" instead of null when the duration overflows Date, s… | `frontend/src/calendar.ts:70` | low | `sends no fabricated end for a DURATION that overflows the calendar` |
| 50 ✅ | Ticking "all day" on a timed event that ends at midnight adds a day the grid never showed | `frontend/src/components/CalendarView.tsx:777` | low | `keeps a midnight-ending event on its one day when it is made all-day` |
| 51 ✅ | The duplicate-React-key fix landed on one of the five sites named; task chips, mobile dots, the mobile agend… | `frontend/src/components/CalendarView.tsx:614` | low | `gives every task chip and every popover row a key unique per collection` |
| 52 ✅ | An SSE reconnect that 401s retries forever, so a session that lapses while the tab is idle is never detected | `frontend/src/api.ts:475` | low | `discovers a session that lapsed while the tab was idle` |
| 53 ✅ | The login form's two labels are not associated with their inputs, so both fields are unlabelled — the one fo… | `frontend/src/components/Login.tsx:34` | low | `gives both fields an accessible name` |
| 54 ✅ | loadKey encodes list ORDER, so a sidebar drag-reorder refetches every task in the account and discards the f… | `frontend/src/data.tsx:180` | low | `does not refetch every task in the account when only the order changed` |
| 55 ✅ | packDown can stack modules past MAX_ROWS, producing a y the server's `le=200` rejects — the whole settings P… | `frontend/src/dashboard.ts:93` | low | `never emits a module below the row the server accepts` |
| 56 ✅ | Tasks pane rows key on the bare UID, so a task copied into a second list produces duplicate React keys and d… | `frontend/src/components/TasksView.tsx:442` | low | `deletes only the copy whose row was clicked` |
| 57 ✅ | The Completed pane hides a completed RELATED-TO ring entirely, though the list view has explicit code to ren… | `frontend/src/components/TasksView.tsx:334` | low | `shows a completed ring another client authored` |
| 58 ✅ | TaskModal — the app's most-used dialog — has no Escape handler, breaking the modal contract every other dial… | `frontend/src/components/TaskModal.tsx:121` | low | `closes on Escape, like every other dialog in the app` |

## Stage 5 — Delivery infrastructure & test gaps ✅ DONE

8 findings · 3 medium, 5 low · **8 closed, 0 open** ✅

One is already closed: **64** (no test drives `busy_intervals` across a DST transition) was shut by the Stage 3 fixes for the two defects that writing its missing case uncovered — see Stage 3 above.

The pipeline that ships the code and the tests that watch it. Closing these is what stops the next sweep finding the same class again.

| # | Finding | Where | Sev | Pin |
|---|---|---|---|---|
| 59 ✅ | desktop-release.yml grants `contents: write` at workflow scope, so `npm ci` and NuGet restore in the build j… | `.github/workflows/desktop-release.yml:22` | medium | `test_the_build_jobs_hold_no_write_token` |
| 60 ✅ | setup.sh writes the typed Radicale password into a systemd EnvironmentFile without escaping, and systemd's p… | `deploy/setup.sh:44` | medium | `test_setup_sh_writes_a_password_systemd_reads_back_unchanged` |
| 61 ✅ | setup.ts's matchMedia stub hardcodes the desktop breakpoint, so CalendarView's and HomeView's entire mobile … | `frontend/src/test/setup.ts:5` | medium | `renders the mobile calendar and the mobile dashboard` |
| 62 ✅ | Shutdown tears down the SQLite connection and DAV client under a still-running sync sweep | `backend/tasksd/app.py:774` | low | `test_a_closed_service_does_not_sweep_against_a_dead_connection` + `…_closing_between_two_slices…` |
| 63 ✅ | Test gap: the confidential-client path — client_secret_basic/post, the Basic header parser and the secret co… | `backend/tasksd/mcp/oauth.py:417` | low | `test_a_confidential_client_authenticates_with_its_secret_and_only_that` |
| 64 ✅ | Test gap: no test drives busy_intervals across a DST transition at all, which is why two real slot-math defe… | `backend/tests/test_scheduling.py:77` | low | `test_busy_intervals_hold_their_absolute_length_across_a_dst_change` |
| 65 ✅ | No test observes anything about a 204 beyond its status code, and the source comment states the suite is gre… | `backend/tests/test_api.py:76` | low | `test_a_204_delete_carries_no_body_and_no_content_type` |
| 66 ✅ | The won't-do write route and its MCP twin have no behavioural test at all — only a comment in test_api.py cl… | `backend/tests/test_api.py:69` | low | `test_cancelling_a_task_is_wont_do_and_not_done + test_the_cancel_tool_needs_write_access_and_marks_the_task_wont_do` |

# Sweep — 2026-08-16 · closed

**0 open, 40 closed.** Every stage below is done; these are ordinary
regression tests now and must stay green.

## Stage 0 — the harness (done)

Stage 0 built the executable backlog rather than fixing anything. Every open
finding now has a test that **asserts the corrected behaviour and fails today**:

* backend — `pytest.mark.xfail(strict=True)`
* frontend — vitest's `it.fails`

Both mean the same thing in CI:

| state | test | build |
|---|---|---|
| finding still open | fails as expected (XFAIL) | **green** |
| finding fixed | now passes (XPASS) | **red**, until it is reclassified |

That second row is the point. A green build no longer means "no known bugs", it
means "every known bug is exactly as known". Nobody can fix a finding without
being told to tick it off in `docs/AUDIT.md` and drop the marker, and nobody can
quietly regress a fixed one either.

Run a stage on its own:

```
cd backend  && python -m pytest -m stage3          # one stage
cd backend  && python -m pytest -m backlog -rxX    # the whole backlog, itemised
cd frontend && npx vitest run backlog              # the SPA pins, BOTH projects
cd frontend && npm run test:browser                # the layout tier on its own
```

That third line now spans two vitest projects and launches Chromium for the
second of them: since `bcf38cf` the SPA has a `browser` project alongside `unit`,
and the 2026-08-25 stage 4 put three pins in it. `npm test` is the unit project
alone (`vitest run --project unit`), so a backlog pin in a `*.browser.test.tsx`
file is NOT covered by it — CI runs both, in separate steps.

### Two strengths of pin

**Behavioural** pins drive the real code and assert the real result. Most of
stages 1–3 and 5 are these.

**Structural** pins read the source and assert the shape that causes the defect
— an `onClick` scrim, a `key` built from a non-unique id, a missing `concurrency`
key. They pin the *cause*, not the *symptom*, so a fix shaped differently from
the one anticipated will XPASS and need reclassifying. That is the harness
working, not a false alarm. They were used where the harness a behavioural test
would need did not exist yet — and **both claims of that kind turned out to be
false**, which is worth keeping on the record:

* ~~the SPA's drag-and-drop and data-provider findings (no such harness — building
  one is itself a Stage 4 item)~~ — **wrong.** The harness existed all along in
  `TasksView.test.tsx`; Stage 4 converted every one of those pins to a
  behavioural test.
* ~~the three C# findings (no dotnet runtime in the unit environment)~~ —
  **also wrong.** There is no preinstalled SDK, but it installs, and
  `LocalServer.cs` and `Updater.cs` have no WinForms dependency between them (the
  single apparent match was `Cache-Control` catching a `Control\b` grep). Stage 5
  built `desktop/Smylte.Desktop.Tests` — plain `net8.0`, *linking* those sources
  rather than referencing the WinForms project — and it runs on any runner. The
  structural pins were deleted rather than kept alongside it.

The pattern in both: "no harness exists" was asserted from a quick look and then
inherited by every later stage without being re-checked. A constraint that
weakens the tests deserves the same scrutiny as a finding.

### Ordering

The stages run cheapest-and-nastiest first. Stage 1 is almost all `minor` fixes
that stop an adversary turning odd input into a 500. Stage 2 bounds work that is
already unbounded. Stage 3 is the dangerous class — nothing raises and the answer
is silently wrong — and needs the most care per fix. Stage 4 is the largest but
each item is contained. Stage 5 unblocked itself: closing the "no tests" finding
is what turned the C# pins above into real ones.

## Stage 1 — Crash paths ✅ DONE

7 findings · closed · `backend/tests/test_backlog_stage1.py`

All seven are fixed and ticked in `docs/AUDIT.md`; the xfail markers are gone and
those tests are now ordinary regression tests that must stay green.

Two things surfaced while fixing them, both wider than the findings as filed:

* The `compare_digest` crash had **three** instances, not one. Beyond the filed
  `oauth.py:606`, the same TypeError was reachable at the token endpoint via
  `redirect_uri`, and via a stored `code_challenge` that was length-checked but
  never charset-checked. All three now compare bytes, and the PKCE challenge is
  charset-validated at authorize so junk is never stored.
* Findings #30 and #36 were **one rule kept in three places** — `dav/xml.py`,
  `app.py`, and missing from `mcp/tools.py`. They are now one exported constant.
  It needs two spellings: pydantic compiles with Rust's regex crate, which cannot
  name a surrogate (not a Unicode scalar value), so `XML_SAFE_PATTERN_SCALAR`
  omits that range — pydantic rejects a lone surrogate at string conversion
  anyway, which was verified rather than assumed.

| # | Finding | Where | Sev |
|---|---|---|---|
| 1 | hmac.compare_digest on attacker-controlled redirect_uri raises TypeError on non-ASCII → uncaught 500 | `backend/tasksd/mcp/oauth.py:606` | medium |
| 7 | _at_or_after compares aware vs naive datetimes directly, so one floating EXDATE/RDATE/RECURRENCE-ID makes ever… | `backend/tasksd/ical/edit.py:534` | medium |
| 23 | Non-string `scope` in a dynamic client registration crashes with a 500 instead of a 400 | `backend/tasksd/mcp/oauth.py:207` | low |
| 26 | Deeply nested JSON at POST /mcp raises RecursionError, which the parse guard does not catch — the request 500s… | `backend/tasksd/mcp/routes.py:405` | low |
| 30 | Collection-name schemas omit the control-character guard the HTTP model carries, so a stray \x0b answers "the … | `backend/tasksd/mcp/tools.py:174` | low |
| 31 | smylte_find_free_time raises an unhandled OverflowError on a range that ends on the last representable day | `backend/tasksd/mcp/api.py:481` | low |
| 36 | The XML-safety backstop added for control characters misses lone surrogates and U+FFFE/U+FFFF, so a list name … | `backend/tasksd/dav/xml.py:127` | low |

## Stage 2 — Abuse & resource exhaustion ✅ DONE

5 findings · closed · `backend/tests/test_backlog_stage2.py`

All five are fixed and ticked in `docs/AUDIT.md`. Two notes worth keeping:

* **The consent-decline fix is a limiter SPLIT, not a refund.** Refunding the
  password budget on a decline (`record_success`) would clear the counter
  outright, letting an attacker alternate guess/deny and never lock out —
  registration is open, so minting the signed blobs to do that is free. Instead
  the endpoint now has two limiters: a generous one charged per POST (bounding
  the unauthenticated body read), and the 8-per-15-min password budget charged
  only when a password is actually verified. Verified both ways: eight declines
  no longer lock the owner out, and eight wrong passwords still do.
* **The scrypt semaphore is shared with `/api/login`, not duplicated**, because
  the budget being protected is the process's memory. Measured peak is 4, and a
  login still completes (~0.5 s) while twelve consent hashes are in flight.

| # | Finding | Where | Sev |
|---|---|---|---|
| 2 | A JSON-RPC batch is unbounded: one 1 MB POST /mcp becomes thousands of serialized service calls and a multi-gi… | `backend/tasksd/mcp/server.py:228` | medium |
| 25 | Choosing "Read-only" on a write-only authorization request mints a token with an empty scope | `backend/tasksd/mcp/routes.py:255` | low |
| 28 | Cancelling the consent screen burns the password-guess budget, so eight declines lock the owner out of connect… | `backend/tasksd/mcp/routes.py:234` | low |
| 33 | POST /oauth/authorize runs the same scrypt hash as /api/login without the `login_hashes` semaphore that exists… | `backend/tasksd/mcp/routes.py:259` | low |
| 34 | _list_dto materialises every item row — raw_ics included — from every collection just to compute four counts, … | `backend/tasksd/service.py:145` | low |

## Stage 3 — Silent data corruption ✅ DONE

7 findings · closed · `backend/tests/test_backlog_stage3.py`

All seven are fixed and ticked in `docs/AUDIT.md`. Three things worth keeping:

* **A THISANDFUTURE override before a split is FOLDED into the tail's master**,
  properties and time offset both, rather than carried across as a component. The
  tail is a new resource with a new UID, so an override whose RECURRENCE-ID names
  a slot back in the head would replace nothing and render as a duplicate. The
  offset is what keeps the tail at the time the user actually sees; without it
  the values survive but every occurrence jumps back to the master's hour.
* **`store.tx` replaced `with self._conn:`**, which managed nothing under
  `isolation_level=None` — sqlite3's context manager only commits a transaction
  it opened itself. The helper moved out of `sync/engine.py` because every writer
  needs it, not just sync.
* **The slot cap is a runaway backstop, not a page size.** It is now derived from
  what the schema permits (180 days x 288 slots) and logs a warning if it ever
  engages, so a truncation is visible rather than inferred from a page that looks
  like a busy owner.

| # | Finding | Where | Sev |
|---|---|---|---|
| 3 | Every write tool reports "the calendar server may be unreachable" for an unknown uid — the ToolError guards in… | `backend/tasksd/mcp/api.py:257` | medium |
| 4 | smylte_delete_task and smylte_delete_event confirm `{"deleted": uid}` for a uid that does not exist or lives i… | `backend/tasksd/mcp/tools.py:325` | medium |
| 5 | smylte_list_tasks across all lists is concatenated per-list and never sorted, so `limit` returns an arbitrary … | `backend/tasksd/mcp/api.py:168` | medium |
| 6 | generate_slots' default max_slots=1000 silently truncates the public page — the tail of a long horizon renders… | `backend/tasksd/service.py:715` | medium |
| 8 | _reconcile_overrides builds a dateutil probe with a naive DTSTART but a UTC UNTIL, so changing "Repeat until" … | `backend/tasksd/ical/edit.py:393` | medium |
| 9 | split_series drops a RANGE=THISANDFUTURE override that starts before the split point, so every occurrence in t… | `backend/tasksd/ical/edit.py:932` | medium |
| 11 | reorder_tasks' `with self._conn:` opens no transaction (isolation_level=None), so set_sort_orders' documented … | `backend/tasksd/service.py:403` | medium |

## Stage 4 — User-visible correctness & rendering ✅ DONE

12 findings · closed · `frontend/src/backlog.stage4.test.tsx` +
`backend/tests/test_backlog_stage4.py`, with behavioural coverage also added to
`TasksView.test.tsx`, `CalendarView.test.tsx` and `order.test.ts`.

Three things worth keeping:

* **Every pin here is behavioural now.** Ten were structural only because of a
  wrong assumption — recorded below — that the drag/data-provider harness did not
  exist. It does. That mistake was not free: six of those pins failed to
  recognise their own fix, because the fix used a different helper name, CSS
  class or approach than the pin had guessed.
* **New tasks interleave by due date instead of sinking.** A drag renumbers the
  whole account (the server model intends that), so afterwards a null position
  means "created since the last drag". `sortTasks` now assigns an *effective
  position* in a pre-pass rather than comparing pairwise — a pairwise version
  would be non-transitive (P1 < P2 < U < P1) and `Array.sort` on an inconsistent
  comparator is implementation-defined. Placed rows keep their exact order; a new
  task lands before the first placed row it precedes, which preserves the manual
  order rather than re-sorting everything by due.
* **`listsOk` is separate from `listsLoaded`.** The latter means "the attempt
  finished", which the spinner and the task fetch both want; only the former
  means the server answered, and only it may gate anything destructive.

| # | Finding | Where | Sev |
|---|---|---|---|
| 12 | The events staleness guard is global, not per window: a superseded month is dropped but still recorded as fetc… | `frontend/src/data.tsx:533` | medium |
| 13 | Drop indicator draws above the target row, but a downward drag inserts below it | `frontend/src/components/TasksView.tsx:518` | medium |
| 14 | One drag assigns a manual position to every task on the account, so every task created afterwards sorts to the… | `frontend/src/data.tsx:457` | medium |
| 15 | A failed GET /api/lists still marks the lists "loaded", so list-scoped settings are pruned against the stale d… | `frontend/src/components/TasksView.tsx:91` | medium |
| 16 | A drag started inside the inline "add subtask" field reorders the parent task | `frontend/src/components/TasksView.tsx:521` | medium |
| 17 | TaskModal's scrim is an onClick handler, so a text drag-select released outside the modal closes it and discar… | `frontend/src/components/TaskModal.tsx:118` | medium |
| 18 | The booking-link editor has no in-flight guard, so a double-click (or a second Enter) on "Create link" publish… | `frontend/src/components/SchedulingView.tsx:348` | medium |
| 24 | After a mistyped password the consent screen forgets which application it is for *(also reported independently as a second finding)* | `backend/tasksd/mcp/routes.py:266` | low |
| 37 | A failed drag-reorder rolls back a whole-array snapshot, discarding any write that landed while it was in flig… | `frontend/src/data.tsx:465` | low |
| 38 | Calendar chips key on the bare UID, so the same UID in two collections yields duplicate React keys | `frontend/src/components/CalendarView.tsx:470` | low |
| 39 | The booking-link editor breaks the modal contract every other modal keeps: no Escape, no dialog role, and an o… | `frontend/src/components/SchedulingView.tsx:235` | low |
| 40 | The appearance validator accepts any 3–20 letter word as a color, so a misspelled or invented color name is st… | `frontend/src/appearance.ts:289` | low |

## Stage 5 — Delivery infrastructure & test gaps ✅ DONE

9 findings · closed · `backend/tests/test_backlog_stage5.py`,
`backend/tests/test_dav_xml.py`, additions to `backend/tests/test_mcp.py`, and a
new C# suite in `desktop/Smylte.Desktop.Tests/`.

Four things worth keeping:

* **The Windows client has real tests now, and they run everywhere.**
  `Smylte.Desktop.Tests` targets plain `net8.0` and *links* `LocalServer.cs`,
  `Updater.cs` and `Settings.cs` instead of referencing the app: a
  `ProjectReference` to a `net8.0-windows` WinForms project drags in a Desktop
  runtime pack that has no Linux build, so the suite could have been compiled but
  never run off a Windows runner. The trade is deliberate and recorded in the
  project file — if either covered file takes a Windows-only dependency this
  project stops compiling, which is the right failure for two files whose whole
  claim is that they are portable logic. `ci.yml`'s desktop job now runs it.
* **Both updater fixes are behind seams, not inline try/catch.**
  `SwapOrKeepLocalAsync` takes the swap as a delegate and `HaveLocalBuild` folds
  the recovery into the probe that consumes it. That is what lets the guards be
  tested without a GitHub round-trip, and the ordering property — recovery must
  happen *before* anything reads `haveLocal` — becomes a test rather than a
  comment. Both were mutation-checked: breaking either guard fails a test.
* **The MCP event scopes are covered against a real server.** `scope` decides
  whether an edit touches one occurrence or rewrites a series, and it was the
  most destructive argument the connector exposes with no test at all. The new
  tests live in `test_mcp.py`, which is `radicale`-marked: they run in CI against
  the scratch Radicale, and skip when there is no server to talk to.
* **`parse_multistatus` is pinned including what it does with hostile input.**
  A 404 propstat is a deletion and an unparseable status line is *not* — getting
  that backwards silently deletes cached items. External entities are pinned as
  not fetched, because the day that changes an XXE reads local files through the
  sync loop.

| # | Finding | Where | Sev |
|---|---|---|---|
| 10 | Test gap: parse_multistatus and the whole PROPFIND/REPORT response-parsing path — the only code turning untrus… | `backend/tasksd/dav/xml.py:198` | medium |
| 19 | Any failure during the update download kills startup even though a complete installed build is sitting on disk | `desktop/Smylte.Desktop/Updater.cs:75` | medium |
| 20 | An update interrupted between the two directory moves strands the only working build in web.old, and nothing e… | `desktop/Smylte.Desktop/Updater.cs:207` | medium |
| 21 | setup.sh runs `python -m tasksd` without changing into the backend directory, so the documented install aborts… | `deploy/setup.sh:31` | medium |
| 22 | Test gap: the entire Windows client ships with zero tests — CI only compiles it, leaving the proxy's path-trav… | `desktop/Smylte.Desktop/LocalServer.cs:257` | medium |
| 29 | No test sends a JSON-RPC batch, so the entire batch-framing path in run_batch is uncovered | `backend/tests/test_mcp.py:259` | low |
| 32 | No MCP-level test exercises any event write tool or any recurrence scope | `backend/tests/test_mcp.py:208` | low |
| 35 | Test gap: the DST slot battery never supplies busy intervals or a `now` inside the transition, and no test dri… | `backend/tests/test_scheduling.py:181` | low |
| 41 | desktop-release.yml has no concurrency group, so an older build can clobber a newer one on the rolling release | `.github/workflows/desktop-release.yml:10` | low |

## After the backlog

The harness stays. Every pin above is now an ordinary test that must stay green,
so a regression on any of these 40 findings fails CI the same way the original
defect would have. `python -m pytest -m backlog -rxX` still prints the itemised
state, and it should report no xfails and no XPASSes: a new `xfail(strict=True)`
appearing there means somebody has filed and pinned a new finding, which is
exactly what it is for.

What was deliberately **not** closed by this work: the 41 findings in
`docs/AUDIT.md` from the 2026-08-07 sweep. They predated it and none of them
were re-verified here, so they were neither fixed nor confirmed still-live.

They have since been closed on their own, cluster by cluster against issues
#42–#48 — one commit each, every fix carrying a regression test confirmed to
fail against the pre-fix code. Four of the 41 had been partly overtaken by
main's 2026-08-14 merge and were re-scoped before being worked rather than
ticked on sight; each carries a note in `docs/AUDIT.md` saying what actually
survived. Those tests are ordinary regression tests now, like the pins above.
