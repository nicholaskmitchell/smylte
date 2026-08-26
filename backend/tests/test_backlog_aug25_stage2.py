"""The 2026-08-25 sweep, stage 2: abuse and resource exhaustion.

Work or storage an adversary — or, twice here, ordinary use — can make unbounded,
and controls that do not cover what they say they cover. Same bucket as the
(closed) stage 2 of the two earlier backlogs, and the same ordering rule: within
the stage, by severity.

**These findings are OPEN.** Unlike test_backlog_stage1.py … stage5.py and their
aug19 successors, every test here is an `xfail(strict=True)` pin: it asserts the
CORRECTED behaviour and fails against the code as it stands. CI stays green while
the bug is open and goes red the moment it is fixed — see docs/STAGES.md for the
harness and why that second half is the point.

Six of the seven are here; the seventh is the desktop client's missing
Content-Security-Policy, pinned in C# beside the path-traversal test that already
covers `LocalServer` headlessly.

Two shapes recur. Three findings are a GUARD IN THE WRONG PLACE: `set_sidecar`
lacks the live-item check that `set_sort_orders` carries and whose own docstring
argues "the guard belongs here, where every door passes"; `tasks.service` opens
the very tree its hardening block exists to close; `RateLimiter` bounds a client
and calls that bounding the guess budget. The other three are work that scales
with an argument the caller chooses — a `kid`, a day range, an address.

Every pin is behavioural: each drives the real store, the real service, the real
MCP adapter or the real login route and asserts what a caller or the database is
left holding, never the shape of the source. Each asserts the *class* of the
corrected answer — "no unreclaimable row", "not one fetch per request", "not once
per day" — rather than a particular repair, because two of these have two
defensible fixes (guard the store or guard the call site; hoist the join or cache
it) and a pin that only accepts the one its author imagined is not a regression
test.

Radicale-free by construction. The service and MCP pins seed `items` directly the
way test_day_plan.py does, the login pin builds the app without entering its
lifespan the way test_loop_blocking.py does, and the Access pins serve a locally
generated RSA key rather than reaching Cloudflare. Run just this file with
`pytest tests/test_backlog_aug25_stage2.py -rxX`.
"""
from __future__ import annotations

import asyncio
import dataclasses
import pathlib
import time
from datetime import date, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from helpers import foreign_raw

from tasksd.access import AccessVerifier
from tasksd.app import create_app
from tasksd.auth import Authenticator
from tasksd.config import Settings
from tasksd.dav.client import CollectionInfo, Item
from tasksd.db import store
from tasksd.ical import extract_from_raw
from tasksd.mcp.api import McpApi
from tasksd.service import TaskService
from tests.conftest import api_settings

pytestmark = [pytest.mark.backlog, pytest.mark.stage2]

LIST_A = "/u/work/"
DAY = "2026-08-21"


def _settings(db: str) -> Settings:
    # A closed port, as test_day_plan.py does: nothing here may reach the wire,
    # and a test that starts trying fails rather than hangs.
    return Settings(
        radicale_url="http://127.0.0.1:1", radicale_user="u", radicale_password="p",
        db_path=db, sync_interval_s=3600, request_timeout_s=1,
        static_dir="/nonexistent", hook_secret="h", auth_enabled=False,
        auth_user="", auth_password_hash="", auth_password="",
        session_secret="", session_ttl_s=60, cookie_secure=False,
        access_required=False, access_team_domain="", access_aud="",
    )


@pytest.fixture
def svc(tmp_path):
    s = TaskService(_settings(str(tmp_path / "s2.db")))
    store.upsert_collection(
        s._conn, CollectionInfo(href=LIST_A, displayname="Work", components={"VTODO"}))
    yield s
    s.close()


def _seed(conn, href: str, uid: str, summary: str = "A task") -> None:
    raw = foreign_raw(uid, summary)
    store.upsert_item(conn, href, Item(f"{href}{uid}.ics", '"1"', raw), extract_from_raw(raw))


def _sidecar_rows(conn) -> list[tuple]:
    return conn.execute(
        "SELECT collection_href, uid, orphaned_at FROM sidecar").fetchall()


# ── AUDIT: store.set_sidecar has no live-item guard, so the day-plan estimate ──
# ── write-through mints sidecar rows gc_orphans can never reclaim ─────────────

@pytest.mark.xfail(strict=True, reason="set_sidecar does a bare INSERT OR IGNORE for "
                                       "any (href, uid), so a uid `items` never held "
                                       "gets a row with orphaned_at NULL that nothing "
                                       "can reclaim")
def test_a_sidecar_is_not_minted_for_an_item_the_cache_does_not_hold(svc):
    """The store-level half, and the one fix that closes every door at once.

    `set_sidecar` (store.py:511) is `INSERT OR IGNORE INTO sidecar
    (collection_href, uid)` with no referential check. `orphan_sidecar` only ever
    UPDATEs rows that exist when a KNOWN item is removed, and `gc_orphans` deletes
    only `orphaned_at IS NOT NULL` — so a row minted for a uid that was already
    gone is permanent, in the one table the codebase repeatedly calls "the one
    part of the DB no resync can rebuild".

    `set_sort_orders` in this same module already carries the guard, as
    `INSERT ... SELECT ... WHERE EXISTS (SELECT 1 FROM items ...)`, and its
    docstring says where it belongs: "The guard belongs here, where every door
    passes." It was written into that function rather than into `set_sidecar`, so
    the third door — the day-plan estimate write-through, added later — still
    passes unguarded.

    Asserted as "no row", not as "raises": refusing loudly and ignoring quietly
    are both defensible repairs and the caller sees neither. What must not survive
    is the row.
    """
    store.set_sidecar(svc._conn, LIST_A, "never-existed", estimated_minutes=45)
    assert _sidecar_rows(svc._conn) == [], (
        "a sidecar row was minted for a uid the cache has never held; nothing "
        "will ever stamp orphaned_at on it, so gc_orphans cannot reach it"
    )


def test_a_sidecar_for_a_live_item_still_lands(svc):
    """The control, and it must stay green.

    A guard that refused everything would satisfy the pin above while deleting
    the feature: the sidecar is where a task's estimate lives, and the ordinary
    case is a task that is very much still there.
    """
    _seed(svc._conn, LIST_A, "alive")
    store.set_sidecar(svc._conn, LIST_A, "alive", estimated_minutes=45)
    rows = _sidecar_rows(svc._conn)
    assert [(r[0], r[1]) for r in rows] == [(LIST_A, "alive")]


# ── AUDIT: PATCH /api/day/{day}/entries/{id} mints an unreclaimable sidecar ────
# ── row when the entry's task no longer exists ────────────────────────────────

@pytest.mark.xfail(strict=True, reason="patch_day_entry write-throughs the estimate to "
                                       "store.set_sidecar for a day_plan row whose uid "
                                       "may already be gone from items, and day entries "
                                       "are designed to outlive their task")
def test_estimating_a_day_entry_whose_task_is_gone_leaves_nothing_behind(svc):
    """The call site, driven through the service the way the route does.

    A day entry is a POINTER and is *designed* to outlive the task it names —
    `_carry_into`'s docstring says so in as many words ("the ENTRY on its own day
    survives all of that (no FK, by design)"). So `row["uid"]` routinely names a
    uid `items` no longer holds, and this path has no existence check.

    The scenario is ordinary, not adversarial: plan "Buy milk" onto tomorrow from
    the Today tab, tick it off in Tasks.org that evening so the VTODO leaves the
    wire, then open Today and type an estimate on the row that is still there.
    Months of planning accumulate rows no resync, no GC and no UI can reach.

    Reproduced against the audit copy — `sidecar rows after estimating the entry:
    [('/u/work/', 'gone@x', 45, None)]`, `gc_orphans reclaims: 0`, `still there: 1`.

    The assertion is the table, not the branch: guarding the store and guarding
    this call site are both correct repairs, and the finding names both.
    """
    _seed(svc._conn, LIST_A, "gone@x", "Buy milk")
    svc.add_day_entry(DAY, entry_id="e1", kind="task", list_id="work", uid="gone@x")

    # Another CalDAV client deletes the task; the sweep removes the item and
    # orphans whatever sidecar it had.
    store.delete_item_by_href(svc._conn, LIST_A, f"{LIST_A}gone@x.ics")
    store.orphan_sidecar(svc._conn, LIST_A, "gone@x")
    assert _sidecar_rows(svc._conn) == [], "precondition: the sidecar starts clean"

    svc.patch_day_entry(DAY, "e1", estimate_minutes=45)

    live = [r for r in _sidecar_rows(svc._conn) if r[2] is None]
    assert live == [], (
        f"estimating an entry whose task is gone left {live} with orphaned_at "
        "NULL — orphan_sidecar will never fire for it and gc_orphans skips it"
    )


def test_estimating_an_entry_whose_task_is_still_there_teaches_the_sidecar(svc):
    """The control. The write-through is the feature: the sidecar is where the
    NEXT entry for this task starts from, so a guard that stopped it entirely
    would satisfy the pin above by removing what it is guarding."""
    _seed(svc._conn, LIST_A, "here", "Still a task")
    svc.add_day_entry(DAY, entry_id="e2", kind="task", list_id="work", uid="here")
    svc.patch_day_entry(DAY, "e2", estimate_minutes=30)

    row = svc._conn.execute(
        "SELECT estimated_minutes FROM sidecar WHERE uid = 'here'").fetchone()
    assert row is not None and row[0] == 30


# ── AUDIT: smylte_review_day over a range re-reads every task of every named ───
# ── list once per day ─────────────────────────────────────────────────────────

@pytest.mark.xfail(strict=True, reason="review_day's range arm calls "
                                       "_entries_with_tasks inside the per-day loop, so "
                                       "the task join is O(days x lists) on a "
                                       "read-scoped tool whose range the model chooses")
def test_a_range_review_reads_each_list_once_not_once_per_day(svc):
    """Counted, never timed.

    The finding's evidence is a clock — 0.06 s for one day, 6.63 s for 180, against
    0.003 s for the HTTP twin that answers the same question — but a wall-clock
    assertion on CI is a flake generator, and the elapsed time is not what the fix
    changes. What changes is how many times the join runs, so that is what this
    counts.

    `_entries_with_tasks` resolves the lists named on ONE day and calls
    `list_tasks(href, include_done=True)` for each: a full `store.get_items` of
    the collection, raw_ics included, under the global service lock, plus a
    `_task_dto` per row — then throws the map away and does it again for the next
    day. `day_range` is bounded at DAY_RANGE_MAX_DAYS = 190.

    Asserted as O(lists) rather than "exactly one call": hoisting the join out of
    the loop, caching it per list, and building it once per range are all correct,
    and they differ in the constant. What none of them does is scale with the
    number of days.
    """
    _seed(svc._conn, LIST_A, "t1", "A planned task")
    days = [(date.fromisoformat(DAY) + timedelta(days=i)).isoformat() for i in range(30)]
    for i, d in enumerate(days):
        svc.add_day_entry(d, entry_id=f"e{i}", kind="task", list_id="work", uid="t1")

    calls: list[str] = []
    real = svc.list_tasks
    svc.list_tasks = lambda href, **kw: (calls.append(href), real(href, **kw))[1]  # type: ignore[method-assign]
    try:
        McpApi(svc).review_day(from_day=days[0], to_day=(
            date.fromisoformat(days[-1]) + timedelta(days=1)).isoformat())
    finally:
        svc.list_tasks = real  # type: ignore[method-assign]

    assert len(calls) <= 4, (
        f"the task join ran {len(calls)} times over {len(days)} planned days "
        f"({len(set(calls))} distinct list(s)) — it scales with the range, and "
        "the range is an argument the calling model chooses"
    )


# ── AUDIT: Cloudflare Access verification does a blocking JWKS fetch on the ────
# ── event loop, and an unknown `kid` forces one per request ───────────────────

def _access_settings(tmp_path) -> Settings:
    # `Settings` is a frozen dataclass, so `replace` rather than assignment —
    # assigning raised FrozenInstanceError, which the xfail marker swallowed and
    # reported as the finding. `--runxfail` is what showed it.
    return dataclasses.replace(
        api_settings(str(tmp_path / "access.db")),
        access_required=True,
        access_team_domain="example.cloudflareaccess.com",
        access_aud="aud-under-test",
    )


@pytest.fixture
def signing_key():
    """A local RSA key. No Cloudflare tenant is involved anywhere in this file —
    the verifier's JWKS client is the only thing that would reach the network and
    every test below stands in for it."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key, *, kid: str, aud: str = "aud-under-test") -> str:
    return jwt.encode(
        {"aud": aud, "iss": "https://example.cloudflareaccess.com",
         "exp": int(time.time()) + 600},
        key, algorithm="RS256", headers={"kid": kid},
    )


@pytest.mark.xfail(strict=True, reason="PyJWT retries the JWKS fetch with refresh=True "
                                       "on a kid it does not know, so an attacker-chosen "
                                       "kid buys one outbound HTTPS round trip per "
                                       "request")
def test_an_unknown_kid_does_not_buy_a_jwks_fetch_per_request(tmp_path, signing_key, monkeypatch):
    """The amplifier: the `kid` is a header field the caller writes.

    `PyJWKClient.get_signing_key_from_jwt` re-fetches when the key set does not
    contain the token's `kid`, and `AccessVerifier` constructs its client with
    PyJWT's defaults. A token signed with anything at all and headed with a fresh
    `kid` therefore costs the server an outbound HTTPS request every time,
    unauthenticated, before any of the app's own limits are reached.

    Counted through a stubbed `fetch_data`, so nothing leaves the machine.
    Asserted as "does not grow with the number of requests" rather than a fixed
    number: a cache with a TTL, a cooldown and a hard cap are all correct fixes
    and they differ in the constant.
    """
    verifier = AccessVerifier(_access_settings(tmp_path))
    fetches = {"n": 0}

    def _fetch(self):                       # noqa: ANN001 — patching PyJWT's own signature
        fetches["n"] += 1
        return {"keys": []}

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", _fetch, raising=True)

    for i in range(10):
        with pytest.raises(Exception):      # noqa: B017 — a 401/403 either way; the cost is the point
            verifier.verify(_token(signing_key, kid=f"rotating-{i}"))

    assert fetches["n"] <= 2, (
        f"10 requests with an unknown kid cost {fetches['n']} JWKS fetches — the "
        "kid is attacker-chosen, so this is one outbound round trip per request"
    )


@pytest.mark.xfail(strict=True, reason="AccessVerifier.verify calls PyJWT's synchronous "
                                       "urlopen from inside async require_auth, so a slow "
                                       "JWKS endpoint freezes the whole event loop")
def test_verifying_an_access_token_does_not_freeze_the_event_loop(tmp_path, signing_key, monkeypatch):
    """The same call, costed against the process rather than the network.

    `require_auth` is `async def` and calls `verify()` directly. PyJWT's default
    JWKS client is `urllib.request.urlopen` with `timeout=30`, so one slow or
    black-holed fetch stalls every other request, `/healthz` included — the same
    total-outage shape `test_loop_blocking.py` was written for on the service
    lock, on a path that runs before any session exists.

    Measured as the worst gap between ticks of a 10 ms ticker while one
    verification is in flight, which is what "the loop kept running" means.
    """
    verifier = AccessVerifier(_access_settings(tmp_path))
    hold = 1.0

    def _slow_fetch(self):                  # noqa: ANN001
        time.sleep(hold)
        return {"keys": []}

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", _slow_fetch, raising=True)

    async def drive() -> float:
        worst = 0.0

        async def tick() -> None:
            nonlocal worst
            last = time.monotonic()
            while True:
                await asyncio.sleep(0.01)
                now = time.monotonic()
                worst = max(worst, now - last)
                last = now

        ticker = asyncio.create_task(tick())
        await asyncio.sleep(0.05)
        try:
            # Awaited if the repair makes it awaitable. Without this the pin
            # would XPASS the moment `verify` became `async def` — it would hand
            # back a coroutine nobody ran, the fetch would never happen, and the
            # loop would tick freely for reasons having nothing to do with the
            # fix. Offloading to a thread and going async are both correct
            # repairs; this measures the work either way.
            result = verifier.verify(_token(signing_key, kid="anything"))
            if asyncio.iscoroutine(result):
                await result
        except Exception:                   # noqa: BLE001 — the verdict is not the point
            pass
        # Yield before cancelling, or the ticker never gets to OBSERVE the gap it
        # just sat through and `worst` stays at its startup value — the test then
        # passes while the loop was frozen for the whole second, which is the
        # opposite of what it claims. Caught by `--runxfail`: it reported this pin
        # as green against unfixed code.
        for _ in range(3):
            await asyncio.sleep(0.02)
        ticker.cancel()
        return worst

    worst = asyncio.run(drive())
    assert worst < hold / 2, (
        f"the loop went {worst:.2f}s without a tick while one Access token was "
        f"verified against a {hold:.0f}s JWKS fetch — every other request, "
        "/healthz included, waited with it"
    )


# ── AUDIT: nothing bounds the total anonymous scrypt work — the login limiter ──
# ── is keyed only on the client /64 ──────────────────────────────────────────

@pytest.mark.xfail(strict=True, reason="the login limiter is keyed per client /64 and "
                                       "nothing bounds the total, so one routed /48 has "
                                       "65536 independent counters and the real ceiling "
                                       "on guesses is CPU")
def test_the_anonymous_guess_budget_is_bounded_across_client_addresses(tmp_path, monkeypatch):
    """Five guesses per fifteen minutes, per key — and the key is the caller's.

    `limiter_key` collapses IPv6 to its /64, which is the right unit for one
    customer and the wrong unit for a budget: a routed /48 is 65 536 of them, each
    with its own fresh counter. `login_hashes = asyncio.Semaphore(4)` bounds
    CONCURRENCY, not rate, so what actually limits guessing is how fast the box
    can compute scrypt — the finding measures ~71/s, ~6.1 M/day.

    `auth.py`'s own comment states the guarantee this breaks: the slow hash plus
    the rate limit make online brute force impractical. True per address.

    Counted as verifications reaching the hash, not as wall-clock guesses per day:
    the 6.1 M figure is a property of the CPU and the fix does not change it. What
    the fix changes is whether the count keeps rising as the attacker changes
    address. A global bucket, a shorter prefix and a work-based budget all satisfy
    this; none of them lets 40 addresses spend 40 budgets.
    """
    hashed = {"n": 0}
    # Patched on the CLASS, before the app exists: `create_app` keeps its
    # `Authenticator` as a closure local and never puts it on `app.state`, so
    # there is no instance to reach afterwards. (Reaching for
    # `app.state.authenticator` raised AttributeError, which the xfail marker
    # reported as the finding — see the module docstring on why every pin here
    # was read back under `--runxfail`.)
    real = Authenticator.check_credentials

    def _counting(self, user: str, password: str) -> bool:
        hashed["n"] += 1
        return real(self, user, password)

    monkeypatch.setattr(Authenticator, "check_credentials", _counting, raising=True)
    app = create_app(api_settings(str(tmp_path / "login.db")))

    transport = httpx.ASGITransport(app=app)
    async def guess() -> None:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            for block in range(40):         # 40 /64s out of one /48's 65536
                for _ in range(5):          # the per-key allowance
                    # `X-Real-IP`, which is what `_client_ip` reads, and only
                    # from a loopback peer — which ASGITransport is. Sending
                    # `x-forwarded-for` instead made every request key on the
                    # same peer, so the limiter stopped them after five and the
                    # pin passed against unfixed code.
                    await c.post("/api/login",
                                 json={"username": "admin", "password": "wrong"},
                                 headers={"X-Real-IP": f"2001:db8:0:{block:x}::1"})
    asyncio.run(guess())

    assert hashed["n"] <= 25, (
        f"{hashed['n']} password hashes were spent by one /48 rotating 40 of its "
        "own /64s — the per-key allowance is 5, so the budget multiplied by the "
        "number of addresses the caller chose to use"
    )


# ── AUDIT: tasks.service grants the app write access to its own interpreter ───
# ── and source tree, contradicting the sandbox's stated invariant ────────────

REPO = pathlib.Path(__file__).resolve().parents[2]


@pytest.mark.xfail(strict=True, reason="ReadWritePaths covers the backend directory, "
                                       "which holds both .venv (the interpreter "
                                       "ExecStart runs) and tasksd (the source), so a "
                                       "write primitive survives every restart")
def test_the_unit_does_not_open_its_own_interpreter_and_source_to_writes():
    """A file assertion, and honest about being one.

    What this can pin is that the unit no longer *names* the tree it runs from.
    What it cannot pin is that systemd then refuses the write — that needs a real
    host, and the finding is recorded in docs/STAGES.md as verifiable only there.

    The unit's own hardening block is what makes this a finding rather than a
    preference: `ProtectSystem=strict`, `ProtectHome=read-only`,
    `NoNewPrivileges`, `PrivateTmp`, and then one `ReadWritePaths=` that reopens
    the interpreter `ExecStart` invokes and the package it imports. A `.pth`
    dropped into site-packages by any write primitive in the internet-reachable
    parse path is executed on the next start, and every line above it is moot.
    """
    unit = (REPO / "deploy" / "tasks.service").read_text(encoding="utf-8")
    rw = [ln.split("=", 1)[1].strip() for ln in unit.splitlines()
          if ln.strip().startswith("ReadWritePaths=")]
    assert rw, "the unit declares no ReadWritePaths at all — has it been renamed?"

    opened = [p for line in rw for p in line.split()
              if pathlib.PurePosixPath(p).name in {"backend", "tasksd", ".venv"}
              or p.rstrip("/").endswith(("/backend", "/tasksd", "/.venv"))]
    assert opened == [], (
        f"ReadWritePaths opens {opened} — that covers .venv (the interpreter "
        "ExecStart runs) and tasksd (the source), so the hardening block above "
        "it does not bound a write primitive in the parse path"
    )
