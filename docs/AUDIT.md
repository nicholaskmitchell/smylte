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

**41 open**, all from the 2026-08-07 sweep below. The first sweep's findings are
all fixed and ticked; the evidence stays here — a ticked box records what the bug
was and why it mattered, and the issues that link into these sections still
resolve.

<!-- The 2026-08-07 sweep is filed first; the 2026-07 sweep follows, fully ticked. -->

## Sweep — 2026-08-07

A second adversarial sweep (12 subsystem finders, two independent verifiers per
finding). 59 raw findings, **45 survived verification**, 14 were refuted. Merged
in are 4 findings from a first, mis-configured pass whose `args` never reached
the workflow, so it ran a single whole-repo finder instead of twelve — those are
filed under *Cross-cutting*.

Every HIGH here was additionally re-verified by hand with a runnable probe before
anything was changed. **8 fixed** in this pass (ticked below, each with a
regression test); the rest are open.


### HTTP API surface

#### [ ] Unauthenticated request bodies are buffered whole before any length bound or rate limiter runs — a single anonymous POST /api/login can exhaust memory

`backend/tasksd/app.py:988` · **high** · security

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

#### [ ] PUT .../tasks/{uid}/sidecar answers 200 null for an unknown uid and writes a sidecar row gc_orphans can never reclaim

`backend/tasksd/app.py:798` · **low** · bug · `minor`

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

#### [ ] Test gap: the SSE endpoint /api/events has no backend test at all, including its per-connection cleanup

`backend/tasksd/app.py:954` · **low** · test-gap

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

#### [ ] Logout does not close an already-open SSE stream — a revoked session keeps receiving live change events forever

`backend/tasksd/app.py:963` · **medium** · security · `minor`

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

#### [ ] Changing the app password (or username) does not invalidate existing sessions, and there is no sign-out-everywhere

`backend/tasksd/auth.py:199` · **medium** · security

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

#### [ ] Idempotent booking replays spend the per-link budget without landing a booking, restoring the link-lockout DoS the ceiling was rewritten to close

`backend/tasksd/service.py:729` · **medium** · security

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

#### [ ] bootstrap() has no per-collection error handling, so one unreachable or vanished collection aborts application startup entirely

`backend/tasksd/service.py:107` · **medium** · bug

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

#### [ ] shift_series moves a UTC UNTIL by the wall-clock delta, so dragging a zone-aware bounded series across a DST edge silently deletes its last occurrence(s)

`backend/tasksd/ical/edit.py:707` · **medium** · bug

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

#### [ ] Deleting one occurrence destroys a RANGE=THISANDFUTURE override, silently reverting every later occurrence to the master

`backend/tasksd/ical/edit.py:586` · **medium** · bug · `minor`

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

#### [ ] split_series lacks the all-day <-> timed guard shift_series has, so toggling "all day" and saving "This and following" is an unhandled TypeError (500)

`backend/tasksd/ical/edit.py:936` · **medium** · bug · `minor`

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

#### [ ] _event_duration subtracts DTEND-DTSTART with no tolerance for mixed value types or awareness, so one malformed foreign event becomes permanently uneditable (500)

`backend/tasksd/ical/edit.py:515` · **low** · bug

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

#### [ ] "This and following" on the FIRST occurrence writes a head whose UNTIL precedes its own DTSTART, leaving an undeletable empty resource behind forever

`backend/tasksd/ical/edit.py:874` · **low** · bug

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

#### [ ] expand_occurrences silently truncates at max_occurrences=750, so a rule the guard explicitly permits loses ~12 days off the end of the calendar grid and makes the public booking page advertise slots that 409

`backend/tasksd/ical/recur.py:235` · **medium** · bug

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

#### [ ] _thisandfuture_shifts crashes with TypeError on a RANGE=THISANDFUTURE override whose RECURRENCE-ID and DTSTART differ in tz-awareness, wiping every occurrence of the series from the calendar

`backend/tasksd/ical/recur.py:103` · **low** · bug · `minor`

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

#### [ ] gc_orphans is global while the guard that gates it is per-collection, so one clean collection permanently deletes the sidecar state another collection's poison resource was protecting

`backend/tasksd/sync/engine.py:157` · **medium** · bug · `minor`

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

#### [ ] Every upsert_item does a full scan of items_fts, making a full resync O(n²) — thousands of items freeze the whole API for tens of seconds under the global service lock

`backend/tasksd/db/store.py:222` · **medium** · bug

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

#### [ ] A list or calendar created or deleted by another CalDAV client is never pushed to the SPA — the sidebar keeps a list the server has already purged

`backend/tasksd/service.py:131` · **low** · rendering · `minor`

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

#### [ ] Idempotent replay of a booking POST spends the per-link ceiling, so anyone holding the published URL can lock the link out permanently

`backend/tasksd/app.py:1120` · **medium** · security

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

#### [ ] The per-link booking ceiling is a check-then-act: concurrent POSTs all pass the gate before any of them charges, so the 30/hour cap never engages

`backend/tasksd/app.py:1096` · **medium** · security

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

#### [ ] The public booking POST mints a fresh client_id on every attempt, so a lost response turns one booking into two and tells the visitor their own slot "was just taken"

`frontend/src/components/BookingPage.tsx:87` · **medium** · bug

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

#### [ ] A dense recurring series stops blocking bookings past 750 occurrences, so the public page advertises the owner's busy hours as free

`backend/tasksd/service.py:646` · **medium** · bug

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

#### [ ] Floating (naive) event times are read in the link's timezone, so a link whose timezone differs from where events were authored silently double-books the owner

`backend/tasksd/scheduling.py:87` · **medium** · bug

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

#### [ ] On the DST fall-back day the public page renders two identical slot buttons an hour apart, so the visitor can book the wrong hour with no way to tell

`frontend/src/components/BookingPage.tsx:214` · **low** · rendering

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

#### [ ] Dragging a zone-anchored event in the calendar rewrites DTSTART/DTEND as floating local wall time, destroying the TZID another CalDAV client wrote

`frontend/src/calendar.ts:25` · **high** · bug

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

#### [ ] useAllTasks never clears `loading` when a fetch fails, so the Home dashboard's task modules render permanently blank with no retry

`frontend/src/hooks.ts:46` · **medium** · bug · `minor`

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

#### [ ] A failed logout still shows the login form, leaving a live session and a valid cookie behind (and raises an unhandled rejection)

`frontend/src/App.tsx:314` · **medium** · security

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

#### [ ] A 422 from the API renders as the literal string "[object Object]", because FastAPI's validation detail is a list

`frontend/src/api.ts:233` · **low** · rendering · `minor`

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

#### [ ] bucketByDay sorts each day's events by raw ISO string, so a zone-anchored event lands in the wrong slot — and can be pushed out of the cell entirely

`frontend/src/calendar.ts:94` · **low** · rendering · `minor`

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

#### [ ] Test gap: hooks.ts has no test file, so useAllTasks' documented staleness guard and its loading contract are entirely unverified

`frontend/src/hooks.ts:37` · **low** · test-gap · `minor`

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

#### [ ] "View completed" renders a completed subtask twice — once as a top-level row and again nested under its parent

`frontend/src/components/TasksView.tsx:333` · **medium** · rendering · `minor`

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

#### [ ] A multi-line paste retitles a bulk row but keeps its client_id, so retrying after a lost response silently discards the new title

`frontend/src/components/AddMultipleModal.tsx:349` · **medium** · bug · `minor`

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

#### [ ] Turning Tags into a shared property silently drops the tag already typed into a row (array compared by reference)

`frontend/src/components/AddMultipleModal.tsx:381` · **medium** · bug · `minor`

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

#### [ ] Test gap: day-column drag-to-reschedule has no coverage at all, though it writes a DUE to a real CalDAV resource

`frontend/src/components/TasksView.tsx:276` · **medium** · test-gap

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

#### [ ] A failed list delete restores the list but permanently loses its group membership

`frontend/src/components/Sidebar.tsx:124` · **low** · bug · `minor`

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

#### [ ] The merged all-lists pane does an O(n²) scan per render (childrenOf) plus an O(n·m) lookup per row

`frontend/src/components/TasksView.tsx:295` · **low** · bug · `minor`

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

#### [ ] Collection colors from the wire are unvalidated and go straight into the CSSOM — url() in calendar-color is a live remote-fetch beacon

`frontend/src/components/HomeView.tsx:342` · **medium** · security

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

#### [ ] HomeView's calendar fetch has no staleness guard, so an older batch settling last leaves the mini calendar showing a stale month

`frontend/src/components/HomeView.tsx:121` · **low** · bug · `minor`

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

#### [ ] Moving an event into a hidden calendar makes it vanish from the grid with no feedback; only the create path un-hides

`frontend/src/components/CalendarView.tsx:176` · **low** · rendering · `minor`

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

#### [ ] calendar-color read off the wire is never validated and lands in the CSSOM, so a foreign CalDAV client can plant a url() beacon

`backend/tasksd/dav/client.py:152` · **medium** · security

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

#### [ ] The Appearance editor's color text field overrides the mobile 16px input floor, reintroducing iOS Safari's zoom-on-focus

`frontend/src/styles/app.css:858` · **low** · rendering · `minor`

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

#### [ ] Saving a DURATION-only event collapses it to zero length (silently destroys its span, and it stops blocking bookings)

`frontend/src/components/CalendarView.tsx:432` · **medium** · bug

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

