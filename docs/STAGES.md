# Staged remediation of the audit backlog

`docs/AUDIT.md` is the evidence. This file is the plan for closing those
findings, and the map from a finding to the test that pins it.

Two sweeps have been staged this way. The **2026-08-19** backlog is open and is
the live plan; the **2026-08-16** one below it is closed and kept as the record
of how the harness behaved in practice — its "Two strengths of pin" and
"Ordering" notes are the reason the new pins are shaped the way they are.

# Sweep — 2026-08-19 · the open backlog

`docs/AUDIT.md` is the evidence. This is the plan for closing it.

**17 open, 65 closed.** Stages 1, 2 and 3 are done; stage 4 is done and
stage 5 has not started. Of the 17 still open:

| where it came from | open |
|---|---|
| the sweep itself (stage 5) | 7 |
| filed by the adversarial review of Stage 3 | 7 |
| filed by that review's own follow-up | 1 |
| filed during remediation (see `docs/AUDIT.md`) | 5 |

6 of the 7 remaining sweep findings are pinned — 2 as `xfail(strict=True)` /
`it.fails` and 4 as ordinary passing tests (see "Test gaps that were only gaps" below); the
unpinned one is finding 62. None of the review's 8 is pinned yet. The review's
other 3, the ones Stage 3 itself caused, are closed — along with 3 more the
follow-up found in those very fixes. See `## Filed during the Stage 3 adversarial review` in
`docs/AUDIT.md`. One is deliberately **not** pinned; see
"The one that is not pinned" below. The harness
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

### The one that is not pinned

Finding 62 (shutdown tearing the service down under a running sweep) has **no
pin**. It reproduces on demand in isolation — swap the service's `RLock` for one
that yields on release and `close()` reliably wins the gap between two slices —
but not once the rest of its file has run: three consecutive whole-file runs gave
xfail / XPASS / xfail. Under `strict=True` an XPASS is a red build, so pinning it
would hand CI a coin flip, which is worse than leaving it open and visible.

What a real pin needs is a seam this code does not have: a hook between two
slices of `sync_all`, so teardown can be *ordered* against the sweep rather than
raced with it. Whoever fixes the finding should add that seam and pin it then.
The reasoning is repeated in full at the finding's place in
`backend/tests/test_backlog_aug19_stage45.py`.

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
and three needed a control. Two lessons, and neither is the one the review
predicted.

**A pin does not catch an over-correction.** Widening makes a pin detect the BUG
more reliably; it cannot make it detect a fix that goes too far, because a pin
only ever asserts that one thing is now right. What catches that is a test
asserting something ELSE is still right — and those never appear in a count of
pins. Three of the eight rows above are controls.

**Widening pays where the finding names several sites.** #57, #39 and #48 were
each caught only by a case added during widening, and in #39's and #48's the
ORIGINAL pin passed against the half-fix. That is the review's criticism landing
exactly as it described it.

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

## Stage 5 — Delivery infrastructure & test gaps ⬜ OPEN

8 findings · 3 medium, 5 low · **1 closed, 7 open**

One is already closed: **64** (no test drives `busy_intervals` across a DST transition) was shut by the Stage 3 fixes for the two defects that writing its missing case uncovered — see Stage 3 above.

The pipeline that ships the code and the tests that watch it. Closing these is what stops the next sweep finding the same class again.

| # | Finding | Where | Sev | Pin |
|---|---|---|---|---|
| 59 | desktop-release.yml grants `contents: write` at workflow scope, so `npm ci` and NuGet restore in the build j… | `.github/workflows/desktop-release.yml:22` | medium | `test_the_desktop_release_build_jobs_hold_no_write_token` |
| 60 | setup.sh writes the typed Radicale password into a systemd EnvironmentFile without escaping, and systemd's p… | `deploy/setup.sh:44` | medium | `test_setup_sh_writes_a_password_systemd_reads_back_unchanged` |
| 61 | setup.ts's matchMedia stub hardcodes the desktop breakpoint, so CalendarView's and HomeView's entire mobile … | `frontend/src/test/setup.ts:5` | medium | `renders the mobile calendar and the mobile dashboard` |
| 62 | Shutdown tears down the SQLite connection and DAV client under a still-running sync sweep | `backend/tasksd/app.py:774` | low | _not pinned — see below_ |
| 63 | Test gap: the confidential-client path — client_secret_basic/post, the Basic header parser and the secret co… | `backend/tasksd/mcp/oauth.py:417` | low | `test_a_confidential_client_authenticates_with_its_secret_and_only_that` |
| 64 ✅ | Test gap: no test drives busy_intervals across a DST transition at all, which is why two real slot-math defe… | `backend/tests/test_scheduling.py:77` | low | `test_busy_intervals_hold_their_absolute_length_across_a_dst_change` |
| 65 | No test observes anything about a 204 beyond its status code, and the source comment states the suite is gre… | `backend/tests/test_api.py:76` | low | `test_a_204_delete_carries_no_body_and_no_content_type` |
| 66 | The won't-do write route and its MCP twin have no behavioural test at all — only a comment in test_api.py cl… | `backend/tests/test_api.py:69` | low | `test_cancelling_a_task_is_wont_do_and_not_done + test_the_cancel_tool_needs_write_access_and_marks_the_task_wont_do` |

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
cd frontend && npx vitest run backlog              # the SPA pins
```

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
