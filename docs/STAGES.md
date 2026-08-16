# Staged remediation of the audit backlog

`docs/AUDIT.md` is the evidence. This file is the plan for closing those
findings, and the map from a finding to the test that pins it.

**21 open, 19 closed.** Stages 1-3 are done; stages 4 and 5 remain.

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
working, not a false alarm. They are used where the harness a behavioural test
would need does not exist yet:

* the SPA's drag-and-drop and data-provider findings (no such harness — building
  one is itself a Stage 4 item);
* the three C# findings (no dotnet runtime in the unit environment — closing
  "the Windows client ships with zero tests" is what upgrades them).

### Ordering

The stages run cheapest-and-nastiest first. Stage 1 is almost all `minor` fixes
that stop an adversary turning odd input into a 500. Stage 2 bounds work that is
already unbounded. Stage 3 is the dangerous class — nothing raises and the answer
is silently wrong — and needs the most care per fix. Stage 4 is the largest but
each item is contained. Stage 5 unblocks itself: the "no tests" finding is what
turns the structural pins above into real ones.

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

## Stage 4 — User-visible correctness & rendering

12 findings · pinned by `frontend/src/backlog.stage4.test.tsx + backend/tests/test_backlog_stage4.py`

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

## Stage 5 — Delivery infrastructure & test gaps

9 findings · pinned by `backend/tests/test_backlog_stage5.py`

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
