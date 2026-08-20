# Audit backlog

Open findings from the adversarial audit sweeps — one deep finder per subsystem,
then two independent verifiers per finding whose job is to *refute* it. Everything
here **survived verification**: a verifier tried to knock it down and could not.
Nothing here is a style nit — each one carries a concrete trigger. Each sweep's own
counts are in its section heading below.

What is *not* in this file: the issues already fixed on this branch (all six HIGHs
plus nine others), and the four the owner has scheduled for the current pass
(logout invalidation, booking links outliving their calendar, the Start-time slot,
and task-edit dirty-tracking).

Severity is the verifiers' rating. `minor` marks a fix that is a few
obviously-correct lines needing no design decision — a reasonable place to start.

### Reading a reference

Each finding is anchored as `` `path:line` (`symbol`) ``. **The symbol is the
anchor; the line is a convenience.** A line number is only true of one commit,
and these have already gone stale twice — the 2026-08-07 refs were written
against that day's tree, then the 2026-08-14 merge moved most of them, and the
2026-08-16 remediation branch moved them again. Every open finding's reference
was re-derived against this commit by locating the symbol it describes, not by
diff arithmetic. If a line drifts again, search the symbol.

Two findings were partly overtaken by that same drift and carry a note saying so
in place of a clean anchor. They are deliberately left open rather than ticked:
nobody re-verified them, and "the code moved" is not the same as "the bug is
gone". Re-scope them before working them.

The 2026-08-19 references were written against this commit and have not drifted yet.

Ticked findings keep their original references, which point into the tree as it
was when they were filed. They are history, not navigation.

**28 open** from the 2026-08-19 sweep, plus **7** still open of the 10 filed by
the Stage 3 adversarial review and **1** from its follow-up (both below), immediately below; every older
finding is closed. The 2026-08-07 backlog is closed, and so are both findings the
remediation filed against itself (the missing CSP — issue #57 — and the unbounded
`_count_consumed` walk, below). The
evidence stays here — a ticked box records what the bug was and why it mattered,
and the issues that link into these sections still resolve.

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

<!-- Newest first: the 2026-08-17 remediation finding, then the 2026-08-16
     sweep, then 2026-08-07, then the 2026-07 sweep, fully ticked. -->

## Sweep — 2026-08-19

A fourth adversarial sweep (22 subsystem finders, two independent verifiers per
finding, ~220 agents). 100 raw findings, **69 survived verification**, 30 were
refuted — a 30% refutation rate. Grounded against every section below, so nothing
here repeats an earlier sweep: the repo began this one with zero open findings.

Three of the 69 are the same defect seen at a different layer, so they are filed
once and the backlog counts **66**. Every one of the ten HIGHs was reproduced by
hand with a runnable probe against a live Radicale 3.7.4 before being written down.

**36 open, 44 closed** — the seven crash paths went first, as **Stage 1**
(`docs/STAGES.md`), and **Stage 2** is closing on top of them; their pins are
ordinary regression tests now and must stay green. The rest are still pinned by a test that asserts the corrected behaviour
and fails today — see `docs/STAGES.md` for the stage plan and the
finding-to-pin map. Run `pytest -m backlog -rxX` and `npx vitest run backlog` for
the itemised state.

One pattern is worth naming because it accounts for five of them and is why three
prior sweeps missed them: **the code's own comment asserts a safety property the
code does not deliver.** `_u()` in `scheduling.py` documents "Every comparison in
this module must go through here" and the guard ten lines above it does not.
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

#### [ ] A failed events fetch permanently records the month as "asked", so the calendar grid stays blank or stale with no retry path

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

**Pinned by** `2026-08-19 — the calendar grid > re-requests a month whose first fetch failed` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [ ] An SSE reconnect that 401s retries forever, so a session that lapses while the tab is idle is never detected

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

**Pinned by** `aug19 stage 4b — an SSE reconnect that 401s > discovers a session that lapsed while the tab was idle` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

#### [ ] The login form's two labels are not associated with their inputs, so both fields are unlabelled — the one form in the app that gets this wrong

`frontend/src/components/Login.tsx:34` · **low** · rendering · `minor` · stage 4

`<label className="label">Username</label>` and `<label className="label">Password</label>` are siblings of their inputs with no `htmlFor`, no `id`, and no `aria-label`, and they do not wrap the inputs. Both controls therefore have no accessible name: a screen reader announces "edit text, blank" and "password edit, blank", and clicking either label does not focus its field. Every other form in the app pairs them correctly — TaskModal.tsx:137,153 (`htmlFor="task-title"` / `"task-notes"`), CalendarView.tsx:876-925 (eight `htmlFor`/`id` pairs), TabsSection.tsx:58, AppearancePanel.tsx:270 — so this is an isolated miss on the only page an unauthenticated visitor ever sees. Login.test.tsx works around it rather than catching it: it reaches the fields with `screen.getAllByRole('textbox')[0]` and `document.querySelector('input[type="password"]')` instead of `getByLabelText`, which is exactly the query that would fail today.

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

**Pinned by** `aug19 stage 4b — the login form > gives both fields an accessible name` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

#### [ ] loadKey encodes list ORDER, so a sidebar drag-reorder refetches every task in the account and discards the fetch already in flight

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

#### [ ] Test gap: the confidential-client path — client_secret_basic/post, the Basic header parser and the secret comparison — has zero coverage despite being advertised in the AS metadata

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

#### [ ] desktop-release.yml grants `contents: write` at workflow scope, so `npm ci` and NuGet restore in the build jobs run with the release-publishing token on disk

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

**Pinned by** `test_the_desktop_release_build_jobs_hold_no_write_token` in `backend/tests/test_backlog_aug19_stage45.py`.

#### [ ] setup.sh writes the typed Radicale password into a systemd EnvironmentFile without escaping, and systemd's parser eats backslashes and treats a leading quote as an unterminated string that swallows every remaining secret

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

#### [ ] Shape, density and type tokens are stored per light/dark map, so corner radius, text size, gutter, row height, label case, tracking and all three fonts silently revert on every theme flip

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

**Pinned by** `2026-08-19 — appearance > keeps a shape token when the theme flips to dark` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [ ] isColor accepts hex literals CSS rejects (5 and 7 digits) and non-color functions like calc(), so a mistyped color is stored, synced and applied while the editor reports it valid

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

**Pinned by** `2026-08-19 — appearance > refuses hex lengths CSS does not have, and functions that are not colours` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [ ] The archived-calendars settings section renders "Loading…" forever when its fetch fails — the sibling section right next to it guards this and it does not

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

**Pinned by** `aug19 stage 4b — archived calendars > stops saying "Loading…" once the fetch has failed` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

#### [ ] The theme rename row is never closed when the active theme changes, so switching themes with it open and pressing Save renames the theme you switched TO with the old theme's name

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

**Pinned by** `aug19 stage 4b — the theme rename bar > never renames the theme the user switched to with the old name` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

### Calendar view

#### [ ] The resize grip on an event that runs past the six-week window truncates the span when released on its own cell

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

**Pinned by** `2026-08-19 — the calendar grid > does not truncate a window-clipped span dropped where its grip is drawn` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [ ] endFromDuration returns the string "NaN-NaN-NaNTNaN:NaN" instead of null when the duration overflows Date, so an unrelated edit is rejected by the server

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

**Pinned by** `2026-08-19 — the calendar grid > sends no fabricated end for a DURATION that overflows the calendar` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [ ] Ticking "all day" on a timed event that ends at midnight adds a day the grid never showed

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

**Pinned by** `2026-08-19 — the calendar grid > keeps a midnight-ending event on its one day when it is made all-day` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [ ] The duplicate-React-key fix landed on one of the five sites named; task chips, mobile dots, the mobile agenda and DayPopover still key on the bare id/uid

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

**Pinned by** `aug19 stage 4b — chip, dot, agenda and popover identity > gives every task chip and every popover row a key unique per collection` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

### Home & scheduling views

#### [ ] The Home mini calendar never refetches on an SSE change, so its dots go stale while every other module on the same dashboard updates

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

**Pinned by** `2026-08-19 — the Home mini calendar > repaints when the account changes under an open dashboard` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [ ] A rejected booking-link save leaves the editor permanently disabled — the in-flight guard is set but never cleared, and the whole form is unrecoverable

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

**Pinned by** `2026-08-19 — the booking-link editor > comes back to life when the save is rejected` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [ ] The availability editor lets the owner build overlapping weekly windows the server rejects with a 422, and silently deletes any window whose end precedes its start

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

**Pinned by** `2026-08-19 — the booking-link editor > never submits a week the server will refuse, and never drops a range` in `frontend/src/backlog.aug19.stage4a.test.tsx`.

#### [ ] packDown can stack modules past MAX_ROWS, producing a y the server's `le=200` rejects — the whole settings PUT 422s and the arrangement is never saved

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

**Pinned by** `aug19 stage 4b — the dashboard grid > never emits a module below the row the server accepts` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

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

#### [ ] Tasks pane rows key on the bare UID, so a task copied into a second list produces duplicate React keys and deleting one copy erases both rows

`frontend/src/components/TasksView.tsx:442` · **low** · rendering · `minor` · stage 4

Every row in the Tasks view keys on `t.uid` (list view at 416/442/456, day columns at 642/649/658), and `data.tsx`'s mutations identify a task the same way (`patchLocal`/`settle` at 222-225 map every task whose `uid` matches; `remove` at 382 filters by uid; `dropOnDay` at TasksView.tsx:159 resolves the drag with `tasks.find(x => x.uid === dragUid)`). The tasks array is the merged multi-list set and the backend keys items on `(collection_href, uid)`, so two lists can legitimately hold the same UID. AUDIT closed this exact identity bug for the calendar's event chips ("Calendar chips key on the bare UID…", CalendarView.tsx) and noted HomeView already keys defensively with `${t.list}:${t.uid}` — the tasks pane was never covered and still keys on the bare uid (as do CalendarView's task chips at 548/614/652).

<details><summary>Evidence</summary>

```
TasksView.tsx:442 `<TaskGroup key={t.uid} …>`; data.tsx:382 `setTasks((ts) => ts.filter((x) => x.uid !== t.uid))`.

Reproduced against the real component (vitest): two lists l1 'Work' and l2 'Home', each returning `task({uid: 'shared', list: <id>})`. On first paint React logs "Warning: Encountered two children with the same key". Clicking `del` on the Work row calls `api.deleteTask('l1','shared')` — correct on the wire — but the local filter drops BOTH rows, so the Home task disappears from the pane although it still exists on the server, and only a full refetch brings it back. Likewise `toggle` ticks both rows locally while completing only one, and a drag in the day view can resolve the wrong copy.
```

</details>

**Suggested fix.** Key rows on `${t.list}:${t.uid}` in TasksView (416, 442, 456, 642, 649, 658) as HomeView already does, and scope the provider's optimistic mutations to `(list, uid)` rather than uid alone (data.tsx patchLocal/settle/settleCreate/remove).

**Pinned by** `aug19 stage 4b — the tasks pane and one uid in two lists > deletes only the copy whose row was clicked` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

#### [ ] The Completed pane hides a completed RELATED-TO ring entirely, though the list view has explicit code to render one

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

**Pinned by** `aug19 stage 4b — the Completed pane and a RELATED-TO ring > shows a completed ring another client authored` in `frontend/src/backlog.aug19.stage4b.test.tsx`.

#### [ ] TaskModal — the app's most-used dialog — has no Escape handler, breaking the modal contract every other dialog in the app keeps

`frontend/src/components/TaskModal.tsx:121` · **low** · rendering · `minor` · stage 4

TaskModal (the single-task create/edit form, opened from the Tasks list, the day columns and the calendar's task chips) registers no keydown listener anywhere, so Escape does nothing. Every other dialog in the app does: AddMultipleModal.tsx:280, AppearancePanel.tsx:49, DayPopover.tsx:85, SettingsMenu.tsx:105 and SchedulingView.tsx:243 — whose comment states it outright ("The modal contract every other dialog here keeps (see TabsModal): Escape …"). AUDIT filed and fixed exactly this against the booking-link editor, listing the modals that honour it ("Tabs/Appearance/Connections/Archived/Add-multiple") without noticing TaskModal is not among them; backlog.stage4.test.tsx asserts Escape for the booking editor and only the scrim behaviour for TaskModal.

<details><summary>Evidence</summary>

```
TaskModal.tsx has exactly one keyboard handler — `onKeyDown` on the title input, which only handles Enter (line 140) — and no `window.addEventListener('keydown', …)`. `grep -n Escape frontend/src/components/TaskModal.tsx` returns nothing.

Failure: the user clicks a task row, the dialog opens, they press Escape to back out (the gesture every other dialog in this app answers). Nothing happens; the only ways out are the ✕ button or a press-and-release both landing on the scrim. With `aria-modal="true"` and no focus trap either, a keyboard or screen-reader user has no keyboard route out of the dialog at all.
```

</details>

**Suggested fix.** Add the same effect the other modals use: `useEffect(() => { const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey) }, [onClose])`, and add a regression test beside the two scrim tests in backlog.stage4.test.tsx.

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

#### [ ] Shutdown tears down the SQLite connection and DAV client under a still-running sync sweep

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

**Not pinned.** A behavioural pin for this one is a coin flip: it reproduces in isolation but XPASSes once the rest of its file has run, and a flaky `strict=True` marker is a random red build. The constraint, and what a real pin would need (a hook between two slices of `sync_all`), is recorded in `docs/STAGES.md` and at the finding's place in `backend/tests/test_backlog_aug19_stage45.py`.

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

#### [ ] setup.ts's matchMedia stub hardcodes the desktop breakpoint, so CalendarView's and HomeView's entire mobile renders are never exercised

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

#### [ ] No test observes anything about a 204 beyond its status code, and the source comment states the suite is green either way

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

#### [ ] The won't-do write route and its MCP twin have no behavioural test at all — only a comment in test_api.py claims otherwise

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
is a pre-existing bug of the same family and is open.

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

#### [ ] apply_occurrence_override seeds a covered-but-not-anchoring slot from the master, losing the range override's time and location

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

The seven below are **open**. They are filed rather than fixed because each is its
own change with its own risk, and the lesson of that same review is that a fix
written in a hurry to close a review comment is how three of the four regressions
above got in. Nothing here is pinned yet.

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

#### [ ] The nominal/exact DURATION split is defeated one layer up: the cached column is icalendar's re-serialization

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

#### [ ] MERGED_SETTINGS omits the two security-relevant settings and the one its own evidence excused

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

#### [ ] reconcileReplay fires on the ordinary create path and its stated invariant is backwards

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

#### [ ] _intrinsic_order matches order.ts only when the server timezone equals the browser's

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

#### [ ] _desynchronizing falsely refuses Google Calendar's "every weekday"

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

#### [ ] The refresh-token scope check runs after the single-use consumption, burning the grant on a bad scope

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

#### [ ] list_oauth_grants now understates a grant's live capability, deterministically

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

## Filed during remediation — 2026-08-20

#### [ ] HEAD on a booking link 404s while GET serves the SPA, so a link checker reports the owner's published link dead

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

