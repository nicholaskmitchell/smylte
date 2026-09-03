"""HTTP API integration tests against scratch Radicale (spec §8), through the real
FastAPI app with username/password auth ON."""
from __future__ import annotations

import time
import uuid
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from tasksd.app import create_app
from tests.conftest import api_settings

pytestmark = pytest.mark.radicale


def _list(client) -> dict:
    r = client.post("/api/lists", json={"name": f"L-{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    return r.json()


def _cal(client) -> dict:
    r = client.post("/api/calendars", json={"name": f"C-{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    return r.json()


def test_auth_gate(_scratch_up, tmp_path):
    app = create_app(api_settings(str(tmp_path / "auth.db")))
    with TestClient(app) as c:
        assert c.get("/api/me").status_code == 401
        assert c.get("/api/lists").status_code == 401
        assert c.post("/api/login", json={"username": "admin", "password": "nope"}).status_code == 401
        r = c.post("/api/login", json={"username": "admin", "password": "testpass123"})
        assert r.status_code == 200 and "tasks_session" in r.cookies
        assert c.get("/api/me").json()["user"] == "admin"
        c.post("/api/logout")
        assert c.get("/api/lists").status_code == 401


def test_list_is_task_list_only(client):
    lst = _list(client)
    assert lst["is_task_list"] and not lst["is_calendar"]
    ids = {x["id"] for x in client.get("/api/lists").json()}
    assert lst["id"] in ids


def test_task_crud_and_subtasks(client):
    lst = _list(client)
    lid = lst["id"]
    t = client.post(f"/api/lists/{lid}/tasks", json={
        "summary": "call mom", "priority": "high", "due": "2026-07-15", "tags": ["family"],
    }).json()
    assert t["priority_label"] == "high" and t["due"] == "2026-07-15" and t["tags"] == ["family"]

    # edit
    t2 = client.patch(f"/api/lists/{lid}/tasks/{t['uid']}", json={"summary": "call mum"}).json()
    assert t2["summary"] == "call mum"

    # subtask + derived percent
    sub = client.post(f"/api/lists/{lid}/tasks", json={"summary": "buy card", "parent": t["uid"]}).json()
    assert sub["parent"] == t["uid"]
    client.post(f"/api/lists/{lid}/tasks/{sub['uid']}/complete")
    parent = client.get(f"/api/lists/{lid}/tasks/{t['uid']}").json()
    assert parent["child_count"] == 1 and parent["derived_percent"] == 100

    # complete + won't-do
    done = client.post(f"/api/lists/{lid}/tasks/{t['uid']}/complete").json()
    assert done["completed"] and done["percent_complete"] == 100
    # The COMPLETED property, round-tripped through real Radicale rather than
    # inferred: `edit.py` writes it, `read.py` parses it back and the DTO carries
    # it. It was cached but never served, so every "recently completed" view had
    # to guess from the due date instead.
    assert done["completed_at"], "completing a task must record when"
    reopened = client.post(f"/api/lists/{lid}/tasks/{t['uid']}/complete?done=false").json()
    assert not reopened["completed"]
    # Reopening clears the stamp (edit.py's `_replace` with no re-add), so a task
    # cannot come back carrying the instant it was finished the last time.
    assert reopened["completed_at"] is None

    # delete
    assert client.delete(f"/api/lists/{lid}/tasks/{sub['uid']}").status_code == 204
    remaining = {x["uid"] for x in client.get(f"/api/lists/{lid}/tasks").json()}
    assert sub["uid"] not in remaining


def test_client_id_determines_uid(client):
    """The uid a create lands on is `{client_id}@tasksd`, and nothing else.

    The web client mints the same string up front (`uidFor` in api.ts) so a row
    whose create is still in flight already wears the identity it will keep —
    which is what lets a subtask added in that window write a RELATED-TO that
    resolves. That prediction is only legitimate while this holds, so pin it
    here rather than leaving it an implementation detail of the sync engine.
    """
    lid = _list(client)["id"]
    cid = uuid.uuid4().hex
    t = client.post(f"/api/lists/{lid}/tasks",
                    json={"summary": "trip", "client_id": cid}).json()
    assert t["uid"] == f"{cid}@tasksd"

    # …and the same slug names an event's uid, which the calendar view predicts
    # the same way.
    ecid = uuid.uuid4().hex
    cal = _cal(client)
    e = client.post(f"/api/calendars/{cal['id']}/events",
                    json={"summary": "lunch", "start": "2026-07-15", "all_day": True,
                          "client_id": ecid}).json()
    assert e["uid"] == f"{ecid}@tasksd"


def test_create_rejects_a_parent_that_names_nothing(client):
    """RELATED-TO is written verbatim, so an unresolvable parent is an orphan
    persisted to the collection — not something a refetch repairs. Refuse it."""
    lid = _list(client)["id"]
    cid = uuid.uuid4().hex
    # The exact shape of the old bug: the client_id, where the uid belongs.
    r = client.post(f"/api/lists/{lid}/tasks", json={"summary": "sub", "parent": cid})
    assert r.status_code == 422, r.text
    assert not client.get(f"/api/lists/{lid}/tasks").json()

    # The derived uid is accepted, and counts against its parent.
    parent = client.post(f"/api/lists/{lid}/tasks",
                         json={"summary": "trip", "client_id": cid}).json()
    sub = client.post(f"/api/lists/{lid}/tasks",
                      json={"summary": "sub", "parent": parent["uid"]})
    assert sub.status_code == 201, sub.text
    assert client.get(f"/api/lists/{lid}/tasks/{parent['uid']}").json()["child_count"] == 1


def test_patch_reparents_a_task(client):
    """Repointing a subtask is what repairs one written against a bad parent."""
    lid = _list(client)["id"]
    a = client.post(f"/api/lists/{lid}/tasks", json={"summary": "trip"}).json()
    b = client.post(f"/api/lists/{lid}/tasks", json={"summary": "errands"}).json()
    sub = client.post(f"/api/lists/{lid}/tasks",
                      json={"summary": "book flight", "parent": a["uid"]}).json()

    moved = client.patch(f"/api/lists/{lid}/tasks/{sub['uid']}",
                         json={"parent": b["uid"]})
    assert moved.status_code == 200, moved.text
    assert moved.json()["parent"] == b["uid"]
    assert client.get(f"/api/lists/{lid}/tasks/{a['uid']}").json()["child_count"] == 0
    assert client.get(f"/api/lists/{lid}/tasks/{b['uid']}").json()["child_count"] == 1

    # An explicit null unparents; a parent naming nothing, or itself, is refused.
    assert client.patch(f"/api/lists/{lid}/tasks/{sub['uid']}",
                        json={"parent": None}).json()["parent"] is None
    assert client.patch(f"/api/lists/{lid}/tasks/{sub['uid']}",
                        json={"parent": "ghost@tasksd"}).status_code == 422
    assert client.patch(f"/api/lists/{lid}/tasks/{sub['uid']}",
                        json={"parent": sub["uid"]}).status_code == 422


def test_settings_carry_collapsed_task_trees(client):
    """Subtasks nest arbitrarily deep, so which trees are folded away has to
    follow the account like every other UI preference — the alternative is a
    large tree unfolding itself on every device, every load."""
    r = client.put("/api/settings", json={"collapsed_tasks": ["a@tasksd", "b@tasksd"]})
    assert r.status_code == 200, r.text
    assert r.json()["collapsed_tasks"] == ["a@tasksd", "b@tasksd"]
    assert client.get("/api/settings").json()["collapsed_tasks"] == ["a@tasksd", "b@tasksd"]
    # Empty is a real value (everything expanded), not an omission.
    assert client.put("/api/settings", json={"collapsed_tasks": []}).json()["collapsed_tasks"] == []


def test_session_length_is_a_setting(client):
    """The session length moved from a deploy-time env var to a setting."""
    day, week, month = 24 * 3600, 7 * 24 * 3600, 30 * 24 * 3600
    never = 10 * 365 * 24 * 3600
    for ttl in (day, week, month, never):
        r = client.put("/api/settings", json={"session_ttl_s": ttl})
        assert r.status_code == 200, r.text
        assert r.json()["session_ttl_s"] == ttl
    assert client.get("/api/settings").json()["session_ttl_s"] == never


def test_session_length_is_an_allowlist(client):
    """Not a range. This decides how long a login survives and is reachable
    through a settings PUT, so anything but the offered values is refused —
    a bounds check would still let a hand-edited blob ask for a century."""
    for bad in (1, 0, -1, 10**9, 3600, "week", 604800.5, True):
        r = client.put("/api/settings", json={"session_ttl_s": bad})
        assert r.status_code == 422, f"{bad!r} was accepted: {r.text}"
    # …and a refused write leaves the stored value alone.
    client.put("/api/settings", json={"session_ttl_s": 7 * 24 * 3600})
    client.put("/api/settings", json={"session_ttl_s": 99})
    assert client.get("/api/settings").json()["session_ttl_s"] == 7 * 24 * 3600
    # An explicit null is not a bad value: it clears the choice and hands the
    # question back to the deployment's own TASKS_SESSION_TTL.
    assert client.put("/api/settings", json={"session_ttl_s": None}).status_code == 200


def test_focus_settings_round_trip_and_are_bounded(client):
    """The eight keys the Focus surface reads. Ints carry bounds because an
    unbounded one reaches SQLite as an OverflowError — a 500 — and because the
    floors mean something: a zero-length interval ends before it begins. And a
    refused write leaves the stored value alone, like every other 422 here."""
    ok = {
        "focus_interval_minutes": 50, "focus_break_minutes": 10,
        "focus_long_break_minutes": 30, "focus_long_break_every": 0,
        "focus_auto_continue": True, "focus_cap_default": True,
        "focus_chime": False, "focus_notify": True,
    }
    r = client.put("/api/settings", json=ok)
    assert r.status_code == 200, r.text
    for key, value in ok.items():
        assert r.json()[key] == value
    for key, bad in (
        ("focus_interval_minutes", 0), ("focus_interval_minutes", 181),
        ("focus_break_minutes", 61), ("focus_long_break_minutes", 0),
        ("focus_long_break_every", -1), ("focus_long_break_every", 13),
        # Not "yes": pydantic reads yes/no/on/off (and 0/1) as booleans, the same
        # leniency every other bool setting here has. A word it does not know is
        # the refusal this test is after.
        ("focus_chime", "maybe"),
    ):
        r = client.put("/api/settings", json={key: bad})
        assert r.status_code == 422, f"{key}={bad!r} was accepted: {r.text}"
    assert client.get("/api/settings").json()["focus_interval_minutes"] == 50


def test_shortening_the_session_ends_the_one_already_open(_scratch_up, tmp_path):
    """The point of the setting, and the part a stateless token makes awkward.

    The `exp` in a JWT cannot be moved once issued, so "log me out sooner" would
    otherwise mean "…starting with your next sign-in", leaving the session you
    were worried about running for its original week. The server judges a token
    against the length in force instead, so shortening bites at once — here, and
    on every other device holding a cookie.
    """
    day, month = 24 * 3600, 30 * 24 * 3600
    app = create_app(api_settings(str(tmp_path / "ttl.db")))
    with TestClient(app) as c:
        assert c.post("/api/login",
                      json={"username": "admin", "password": "testpass123"}).status_code == 200
        c.put("/api/settings", json={"session_ttl_s": month})
        # Re-issued under the long setting, then aged past a short one.
        c.post("/api/login", json={"username": "admin", "password": "testpass123"})
        assert c.get("/api/me").status_code == 200

        c.put("/api/settings", json={"session_ttl_s": day})
        # Still inside a day, so the same cookie is still good.
        assert c.get("/api/me").status_code == 200

        with mock.patch("tasksd.auth.time.time", return_value=time.time() + day + 60):
            assert c.get("/api/me").status_code == 401
        # …and it comes back once the setting is long again, because the token's
        # own exp still has a month to run. Lengthening is the direction that
        # cannot be applied retroactively; this is the one that can.
        assert c.get("/api/me").status_code == 200


def test_search_and_tags(client):
    lst = _list(client)
    token = uuid.uuid4().hex[:10]
    client.post(f"/api/lists/{lst['id']}/tasks", json={"summary": f"xyz {token}", "tags": [token]})
    hits = client.get("/api/search", params={"q": token}).json()
    assert any(token in (h["summary"] or "") for h in hits)
    assert token in client.get("/api/tags").json()


def test_calendar_event_crud(client):
    cal = _cal(client)
    assert cal["is_calendar"] and not cal["is_task_list"]
    cid = cal["id"]

    ev = client.post(f"/api/calendars/{cid}/events", json={
        "summary": "Meeting", "start": "2026-07-10T14:00:00", "end": "2026-07-10T15:00:00",
        "location": "Zoom", "tags": ["work"],
    }).json()
    assert not ev["all_day"] and ev["location"] == "Zoom"

    hol = client.post(f"/api/calendars/{cid}/events", json={
        "summary": "Holiday", "start": "2026-07-12", "all_day": True,
    }).json()
    assert hol["all_day"] and hol["start"] == "2026-07-12"

    month = client.get(f"/api/calendars/{cid}/events",
                       params={"start": "2026-07-01", "end": "2026-08-01"}).json()
    assert {e["summary"] for e in month} == {"Meeting", "Holiday"}

    # BOTH ends, and the end is asserted. This sent `start` alone and checked
    # only `summary` and `start` — so it passed while the server answered 200
    # with DTSTART 16:00 beside an untouched DTEND of 15:00, an event ending an
    # hour before it began. Measured against the pre-guard tree, which is how
    # this surfaced: the span guard refused the move, and the test that was
    # supposed to be protecting this path had never looked at the half that
    # broke. The SPA always sends both ends; the guard requires them for a move
    # that crosses the old end, and lets a one-end move inside the span through.
    moved = client.patch(f"/api/calendars/{cid}/events/{ev['uid']}", json={
        "start": "2026-07-10T16:00:00", "end": "2026-07-10T17:00:00",
        "summary": "Meeting (moved)",
    }).json()
    assert moved["summary"] == "Meeting (moved)"
    assert (moved["start"], moved["end"]) == ("2026-07-10T16:00:00", "2026-07-10T17:00:00")

    assert client.delete(f"/api/calendars/{cid}/events/{hol['uid']}").status_code == 204
    after = {e["summary"] for e in client.get(f"/api/calendars/{cid}/events",
             params={"start": "2026-07-01", "end": "2026-08-01"}).json()}
    assert after == {"Meeting (moved)"}


def test_event_busy_round_trips(client):
    """TRANSP over HTTP: what Apple Calendar calls Busy/Free.

    The field is tri-state on the wire and the two ends of that matter
    differently — an omitted key must leave the property exactly as its author
    wrote it (a rename must not un-mark an event someone marked Free in another
    client), and an explicit value must reach the VEVENT."""
    cid = _cal(client)["id"]

    # Omitted on create: no opinion, and an absent TRANSP is OPAQUE.
    ev = client.post(f"/api/calendars/{cid}/events", json={
        "summary": "Meeting", "start": "2026-07-10T14:00:00", "end": "2026-07-10T15:00:00",
    }).json()
    assert ev["busy"] is True

    hold = client.post(f"/api/calendars/{cid}/events", json={
        "summary": "Hold", "start": "2026-07-10T16:00:00", "end": "2026-07-10T17:00:00",
        "busy": False,
    }).json()
    assert hold["busy"] is False

    # A patch that does not mention it leaves it alone…
    renamed = client.patch(f"/api/calendars/{cid}/events/{hold['uid']}",
                           json={"summary": "Hold (renamed)"}).json()
    assert renamed["summary"] == "Hold (renamed)" and renamed["busy"] is False

    # …and one that does, changes it.
    back = client.patch(f"/api/calendars/{cid}/events/{hold['uid']}",
                        json={"busy": True}).json()
    assert back["busy"] is True

    # It survives the read path the calendar grid uses, not just the write's echo.
    month = {e["summary"]: e["busy"] for e in _events(client, cid)}
    assert month == {"Meeting": True, "Hold (renamed)": True}


def _events(client, cid, start="2026-07-01", end="2026-08-01"):
    return client.get(f"/api/calendars/{cid}/events", params={"start": start, "end": end}).json()


def test_move_event_between_calendars(client):
    src, dst = _cal(client), _cal(client)
    ev = client.post(f"/api/calendars/{src['id']}/events", json={
        "summary": "Movable", "start": "2026-07-10T14:00:00", "end": "2026-07-10T15:00:00",
    }).json()

    moved = client.post(f"/api/calendars/{src['id']}/events/{ev['uid']}/move",
                        json={"calendar": dst["id"]})
    assert moved.status_code == 200, moved.text
    assert moved.json()["uid"] == ev["uid"]
    assert not _events(client, src["id"])
    assert [e["summary"] for e in _events(client, dst["id"])] == ["Movable"]

    # A recurring series moves whole — rule and overrides ride along.
    rec = client.post(f"/api/calendars/{dst['id']}/events", json={
        "summary": "Weekly", "start": "2026-07-06T09:00:00", "end": "2026-07-06T09:30:00",
        "repeat": "weekly",
    }).json()
    occ2 = sorted((e for e in _events(client, dst["id"]) if e["summary"] == "Weekly"),
                  key=lambda e: e["start"])[1]
    client.patch(f"/api/calendars/{dst['id']}/events/{rec['uid']}", json={
        "summary": "Weekly (moved)", "start": "2026-07-14T10:00:00", "end": "2026-07-14T10:30:00",
        "recurrence_id": occ2["recurrence_id"], "scope": "this",
    })
    client.post(f"/api/calendars/{dst['id']}/events/{rec['uid']}/move",
                json={"calendar": src["id"]})
    weekly = [e for e in _events(client, src["id"]) if e["uid"] == rec["uid"]]
    assert len(weekly) == 4
    assert any(e["summary"] == "Weekly (moved)" and e["start"].startswith("2026-07-14T10:00")
               for e in weekly)
    assert not any(e["uid"] == rec["uid"] for e in _events(client, dst["id"]))

    # Unknown destination -> 404; the event stays put.
    r = client.post(f"/api/calendars/{src['id']}/events/{rec['uid']}/move",
                    json={"calendar": "nope"})
    assert r.status_code == 404
    assert any(e["uid"] == rec["uid"] for e in _events(client, src["id"]))


def test_recurring_event_authoring_and_expansion(client):
    cid = _cal(client)["id"]
    ev = client.post(f"/api/calendars/{cid}/events", json={
        "summary": "Standup", "start": "2026-07-06T09:00:00", "end": "2026-07-06T09:15:00",
        "repeat": "weekly",
    }).json()
    assert ev["is_recurring"] and ev["has_rrule"]
    # A month starting weeks AFTER the first occurrence still lists every instance
    # (the bug we fixed: a past master used to vanish).
    aug = [e for e in _events(client, cid, "2026-08-01", "2026-09-01") if e["summary"] == "Standup"]
    assert len(aug) >= 4
    assert all(e["is_recurring"] for e in aug)
    assert len({e["id"] for e in aug}) == len(aug)      # distinct per-occurrence ids
    assert {e["uid"] for e in aug} == {ev["uid"]}       # all share the base resource


def test_recurring_per_occurrence_edit_and_delete(client):
    cid = _cal(client)["id"]
    ev = client.post(f"/api/calendars/{cid}/events", json={
        "summary": "Sync", "start": "2026-07-06T09:00:00", "end": "2026-07-06T09:30:00",
        "repeat": "weekly",
    }).json()
    uid = ev["uid"]
    occ = sorted((e for e in _events(client, cid) if e["summary"] == "Sync"), key=lambda e: e["start"])
    assert len(occ) >= 4
    base_count = len(occ)

    # "This event": move + rename only the 2nd occurrence.
    client.patch(f"/api/calendars/{cid}/events/{uid}", json={
        "summary": "Sync (moved)", "start": "2026-07-14T11:00:00", "end": "2026-07-14T11:30:00",
        "recurrence_id": occ[1]["recurrence_id"], "scope": "this",
    })
    after = _events(client, cid)
    moved = [e for e in after if e["summary"] == "Sync (moved)"]
    assert len(moved) == 1 and moved[0]["start"].startswith("2026-07-14T11:00")
    assert sum(1 for e in after if e["summary"] == "Sync") == base_count - 1

    # "This event" delete: punch a hole at the first occurrence.
    client.request("DELETE", f"/api/calendars/{cid}/events/{uid}",
                   params={"recurrence_id": occ[0]["recurrence_id"], "scope": "this"})
    assert not any(e["start"].startswith("2026-07-06") for e in _events(client, cid))

    # "All events": delete the whole series.
    assert client.delete(f"/api/calendars/{cid}/events/{uid}").status_code == 204
    assert [e for e in _events(client, cid) if e["uid"] == uid] == []


def test_recurring_this_and_following(client):
    cid = _cal(client)["id"]
    ev = client.post(f"/api/calendars/{cid}/events", json={
        "summary": "Class", "start": "2026-07-06T18:00:00", "end": "2026-07-06T19:00:00",
        "repeat": "weekly",
    }).json()
    uid = ev["uid"]
    occ = sorted((e for e in _events(client, cid) if e["summary"] == "Class"), key=lambda e: e["start"])
    split_at = occ[2]["recurrence_id"]   # 3rd occurrence onward

    client.patch(f"/api/calendars/{cid}/events/{uid}", json={
        "summary": "Class (new room)", "start": occ[2]["start"], "end": occ[2]["end"],
        "recurrence_id": split_at, "scope": "thisandfuture",
    })
    after = _events(client, cid)
    old = sorted(e["start"] for e in after if e["summary"] == "Class")
    new = sorted(e["start"] for e in after if e["summary"] == "Class (new room)")
    assert len(old) == 2 and len(new) >= 2          # head keeps the first two; tail continues
    assert max(old) < min(new)                       # clean split at the boundary
    # Head and tail are distinct resources.
    assert len({e["uid"] for e in after if e["summary"].startswith("Class")}) == 2


def test_deleting_this_and_following_from_the_first_occurrence_removes_the_resource(client):
    """The head is bounded with `UNTIL = anchor - 1s`; at the FIRST occurrence
    that precedes its own DTSTART, so the head generates nothing. It was PUT
    anyway, leaving a VEVENT on Radicale and a cache row that expand to zero
    occurrences forever — `events_in_range` never emits it, so nothing could
    render or delete it again. The server answered 204 and the SPA cleared the
    rows while the resource was still there. This is the natural way to remove a
    whole series from an occurrence chip, so it is not an exotic path."""
    cid = _cal(client)["id"]
    ev = client.post(f"/api/calendars/{cid}/events", json={
        "summary": "Gone", "start": "2026-07-06T18:00:00", "end": "2026-07-06T19:00:00",
        "repeat": "weekly",
    }).json()
    uid = ev["uid"]
    occ = sorted((e for e in _events(client, cid) if e["summary"] == "Gone"),
                 key=lambda e: e["start"])
    assert len(occ) >= 2

    r = client.request("DELETE", f"/api/calendars/{cid}/events/{uid}", params={
        "recurrence_id": occ[0]["recurrence_id"], "scope": "thisandfuture",
    })
    assert r.status_code == 204

    # Gone from the projection…
    assert [e for e in _events(client, cid) if e["summary"] == "Gone"] == []
    # …and gone from the wire, not left as an unreachable husk. A resync would
    # bring a surviving resource straight back.
    assert client.post("/api/sync").status_code == 200
    assert [e for e in _events(client, cid) if e["summary"] == "Gone"] == []
    assert client.get(f"/api/calendars/{cid}/events/{uid}").status_code == 404


def test_settings_sync(client):
    r = client.put("/api/settings", json={"theme": "dark"})
    assert r.status_code == 200 and r.json().get("theme") == "dark"
    assert client.get("/api/settings").json().get("theme") == "dark"
    # Merge, not replace: a second key coexists.
    client.put("/api/settings", json={"theme": "light"})
    assert client.get("/api/settings").json().get("theme") == "light"


def test_settings_archived_calendars_sync(client):
    # The SettingsPatch field must survive the HTTP round-trip — a store-level
    # test wouldn't catch a missing/renamed field on the model (it's key-agnostic).
    r = client.put("/api/settings", json={"archived_calendars": ["a", "b"]})
    assert r.status_code == 200 and r.json().get("archived_calendars") == ["a", "b"]
    assert client.get("/api/settings").json().get("archived_calendars") == ["a", "b"]
    # An empty list is a real value (everything restored), not an omission.
    client.put("/api/settings", json={"archived_calendars": []})
    assert client.get("/api/settings").json().get("archived_calendars") == []


def test_settings_tabs_sync(client):
    # The tab strip's three keys must survive the HTTP round-trip via
    # SettingsPatch — a store-level test is key-agnostic and wouldn't catch a
    # missing or renamed field on the model.
    r = client.put("/api/settings", json={
        "tab_order": ["calendar", "home", "tasks", "scheduling"],
        "start_tab": "last",
        "last_tab": "calendar",
    })
    assert r.status_code == 200
    body = client.get("/api/settings").json()
    assert body.get("tab_order") == ["calendar", "home", "tasks", "scheduling"]
    assert body.get("start_tab") == "last"
    assert body.get("last_tab") == "calendar"
    # A tab that doesn't exist is rejected rather than stored for the client to
    # trip over. "last" is only meaningful as a start, never as a remembered tab.
    assert client.put("/api/settings", json={"start_tab": "gantt"}).status_code == 422
    assert client.put("/api/settings", json={"tab_order": ["gantt"]}).status_code == 422
    assert client.put("/api/settings", json={"last_tab": "last"}).status_code == 422


def test_settings_show_completed_sync(client):
    # The boolean must survive the HTTP round-trip via SettingsPatch, and False
    # has to persist (only an omitted/None key is "unset" — see the store merge).
    r = client.put("/api/settings", json={"show_completed_tasks": True})
    assert r.status_code == 200 and r.json().get("show_completed_tasks") is True
    assert client.get("/api/settings").json().get("show_completed_tasks") is True
    client.put("/api/settings", json={"show_completed_tasks": False})
    assert client.get("/api/settings").json().get("show_completed_tasks") is False


def test_settings_time_format_sync(client):
    # Only the two clocks are accepted — the blob is hand-editable, and an
    # unknown token would reach a formatter on every client that read it.
    r = client.put("/api/settings", json={"time_format": "24h"})
    assert r.status_code == 200 and r.json().get("time_format") == "24h"
    assert client.get("/api/settings").json().get("time_format") == "24h"
    assert client.put("/api/settings", json={"time_format": "12h"}).status_code == 200
    assert client.get("/api/settings").json().get("time_format") == "12h"
    assert client.put("/api/settings", json={"time_format": "H:mm"}).status_code == 422


def test_settings_language_sync(client):
    # Only the languages the app has a catalogue for. The blob is hand-editable
    # and an unknown tag would reach `Intl.PluralRules` and `toLocaleDateString`
    # on every client that read it, so it is refused here rather than defended
    # against on the way back out.
    r = client.put("/api/settings", json={"language": "de"})
    assert r.status_code == 200 and r.json().get("language") == "de"
    assert client.get("/api/settings").json().get("language") == "de"
    assert client.put("/api/settings", json={"language": "en"}).status_code == 200
    assert client.get("/api/settings").json().get("language") == "en"
    assert client.put("/api/settings", json={"language": "fr"}).status_code == 422
    assert client.put("/api/settings", json={"language": "de-AT"}).status_code == 422


def test_settings_language_does_not_reach_anything_stored(client):
    # It is a DISPLAY setting. The server is not translated, reads this nowhere,
    # and nothing an account has named changes because of it — which is the
    # promise the settings hint makes to the user in as many words.
    client.put("/api/settings", json={"language": "de"})
    lists = client.get("/api/lists").json()
    assert lists, "the fixture account has at least one list to be sure about"
    before = [l["name"] for l in lists]
    assert [l["name"] for l in client.get("/api/lists").json()] == before


def test_settings_home_timezone_sync(client):
    # The zone the account authors floating times in. Validated on the way in
    # because it is fed to ZoneInfo on the public booking path, and the blob is
    # hand-editable.
    assert "home_timezone" not in client.get("/api/settings").json()
    r = client.put("/api/settings", json={"home_timezone": "America/New_York"})
    assert r.status_code == 200 and r.json()["home_timezone"] == "America/New_York"
    assert client.get("/api/settings").json()["home_timezone"] == "America/New_York"
    # Empty string clears it back to "use the link's own zone".
    assert client.put("/api/settings", json={"home_timezone": ""}).status_code == 200
    assert client.get("/api/settings").json()["home_timezone"] == ""
    assert client.put("/api/settings", json={"home_timezone": "Mars/Olympus"}).status_code == 422
    assert client.put("/api/settings", json={"home_timezone": "../../etc"}).status_code == 422


def test_settings_calendar_tasks_sync(client):
    # An allowlist, not a hidden set: absent means no task lists are drawn on
    # the calendar, so the empty default has to survive the round trip as
    # "none" rather than being read as "unset, therefore all".
    assert "calendar_task_lists" not in client.get("/api/settings").json()
    r = client.put("/api/settings", json={"calendar_task_lists": ["a", "b"]})
    assert r.status_code == 200 and r.json()["calendar_task_lists"] == ["a", "b"]
    assert client.get("/api/settings").json()["calendar_task_lists"] == ["a", "b"]
    # Empty is a real value that clears the set (the store merge only skips None).
    assert client.put("/api/settings", json={"calendar_task_lists": []}).json()[
        "calendar_task_lists"] == []

    r = client.put("/api/settings", json={"calendar_show_done_tasks": True})
    assert r.status_code == 200 and r.json()["calendar_show_done_tasks"] is True
    client.put("/api/settings", json={"calendar_show_done_tasks": False})
    assert client.get("/api/settings").json()["calendar_show_done_tasks"] is False


def test_settings_calendar_fit_sync(client):
    # Absent means the shape the grid has always had: rows that grow to their
    # busiest day. Only the two the client knows how to draw are accepted — an
    # unknown one would reach the grid as a class nothing styles.
    assert "calendar_fit" not in client.get("/api/settings").json()
    r = client.put("/api/settings", json={"calendar_fit": "fixed"})
    assert r.status_code == 200 and r.json()["calendar_fit"] == "fixed"
    assert client.get("/api/settings").json()["calendar_fit"] == "fixed"
    assert client.put("/api/settings", json={"calendar_fit": "dynamic"}).json()[
        "calendar_fit"] == "dynamic"
    assert client.put("/api/settings", json={"calendar_fit": "squeeze"}).status_code == 422


def test_settings_task_grouping_sync(client):
    # hidden_lists, task_groups, and collapsed_groups must survive the HTTP
    # round-trip — the model has to accept and re-emit each key (a store test
    # is key-agnostic and wouldn't catch a missing/renamed SettingsPatch field).
    groups = [{"id": "g1", "name": "Work", "lists": ["l1", "l2"]}]
    r = client.put("/api/settings", json={
        "hidden_lists": ["l3"], "task_groups": groups, "collapsed_groups": ["g1"],
    })
    assert r.status_code == 200
    body = r.json()
    assert body.get("hidden_lists") == ["l3"]
    assert body.get("task_groups") == groups
    assert body.get("collapsed_groups") == ["g1"]
    got = client.get("/api/settings").json()
    assert got.get("task_groups") == groups
    # A malformed group (missing the required name) is rejected, not stored.
    assert client.put("/api/settings", json={
        "task_groups": [{"id": "x", "lists": []}]}).status_code == 422
    # Empty arrays are real values (grouping cleared), not omissions.
    client.put("/api/settings", json={"task_groups": [], "hidden_lists": []})
    after = client.get("/api/settings").json()
    assert after.get("task_groups") == [] and after.get("hidden_lists") == []


def test_task_list_field_matches_list_id(client):
    # The combined "All lists" view maps each task back to its list by this id
    # (for color + visibility), so a task's `list` must equal its List.id — not
    # the raw collection href. resolve_list still accepts either form for writes.
    lst = _list(client)
    lid = lst["id"]
    created = client.post(f"/api/lists/{lid}/tasks", json={"summary": "anchor"}).json()
    assert created["list"] == lid
    fetched = client.get(f"/api/lists/{lid}/tasks").json()
    assert fetched and all(t["list"] == lid for t in fetched)
    client.delete(f"/api/lists/{lid}")


def test_tabs_are_separated(client):
    lst = _list(client)
    cal = _cal(client)
    list_ids = {x["id"] for x in client.get("/api/lists").json()}
    cal_ids = {x["id"] for x in client.get("/api/calendars").json()}
    assert cal["id"] not in list_ids   # a VEVENT calendar never shows under Tasks
    assert lst["id"] not in cal_ids    # a VTODO list never shows under Calendar


def test_list_management(client):
    lst = _list(client)
    lid = lst["id"]

    # rename + recolor ride PROPPATCH → visible on re-list (wire is truth)
    r = client.patch(f"/api/lists/{lid}", json={"name": "Renamed", "color": "#FF9500"})
    assert r.status_code == 200, r.text
    got = next(x for x in client.get("/api/lists").json() if x["id"] == lid)
    assert got["name"] == "Renamed" and got["color"] == "#FF9500"

    # clearing the color is an explicit null
    cleared = client.patch(f"/api/lists/{lid}", json={"color": None}).json()
    assert cleared["color"] is None

    # bad colors are rejected before touching the wire
    assert client.patch(f"/api/lists/{lid}", json={"color": "tomato"}).status_code == 422

    # delete removes it from the wire and from /api/lists
    assert client.delete(f"/api/lists/{lid}").status_code == 204
    assert lid not in {x["id"] for x in client.get("/api/lists").json()}


def test_list_reorder(client):
    a, b, c = _list(client), _list(client), _list(client)
    ids = [x["id"] for x in client.get("/api/lists").json()]
    want = [c["id"], a["id"], b["id"]] + [i for i in ids if i not in {a["id"], b["id"], c["id"]}]
    r = client.post("/api/lists/reorder", json={"ids": want})
    assert r.status_code == 200, r.text
    after = [x["id"] for x in client.get("/api/lists").json()]
    assert after == want
    for lst in (a, b, c):
        client.delete(f"/api/lists/{lst['id']}")


def test_create_with_color(client):
    r = client.post("/api/calendars", json={"name": f"C-{uuid.uuid4().hex[:8]}",
                                            "color": "#2ECC71FF"})
    assert r.status_code == 201, r.text
    cal = r.json()
    assert cal["color"] == "#2ECC71FF"
    client.delete(f"/api/calendars/{cal['id']}")


def test_hook_endpoint_gate(client):
    assert client.post("/internal/changed", headers={"X-Tasks-Hook-Secret": "wrong"}).status_code == 403
    assert client.post("/internal/changed", headers={"X-Tasks-Hook-Secret": "testhook"}).status_code == 202


# ── error mapping: domain exceptions and bad input must not surface as 500s ──

def test_unknown_uid_is_404(client):
    lid = _list(client)["id"]
    assert client.patch(f"/api/lists/{lid}/tasks/no-such-uid",
                        json={"summary": "x"}).status_code == 404
    assert client.post(f"/api/lists/{lid}/tasks/no-such-uid/complete").status_code == 404
    cid = _cal(client)["id"]
    assert client.patch(f"/api/calendars/{cid}/events/no-such-uid",
                        json={"summary": "x"}).status_code == 404


def test_invalid_input_is_422(client):
    lid = _list(client)["id"]
    cid = _cal(client)["id"]
    assert client.post(f"/api/lists/{lid}/tasks",
                       json={"summary": "x", "due": "not-a-date"}).status_code == 422
    assert client.post(f"/api/calendars/{cid}/events",
                       json={"summary": "x", "start": "2026-13-99"}).status_code == 422
    assert client.get(f"/api/calendars/{cid}/events",
                      params={"start": "garbage", "end": "2026-08-01"}).status_code == 422
    assert client.post(f"/api/calendars/{cid}/events", json={
        "summary": "x", "start": "2026-07-01T09:00:00", "repeat": "fortnightly",
    }).status_code == 422
    assert client.request("DELETE", f"/api/calendars/{cid}/events/whatever",
                          params={"scope": "everything"}).status_code == 422
    assert client.put("/api/settings", json={"theme": "blue"}).status_code == 422
    # An empty/whitespace start is "unset" to the parser but unbuildable as a
    # DTSTART, so it used to reach icalendar and 500 rather than 422.
    for blank in ("", "   "):
        assert client.post(f"/api/calendars/{cid}/events",
                           json={"summary": "x", "start": blank}).status_code == 422
    # A cleared end still means "no DTEND", not a bad request.
    assert client.post(f"/api/calendars/{cid}/events", json={
        "summary": "x", "start": "2026-07-01T09:00:00", "end": "",
    }).status_code == 201


def test_per_occurrence_scope_requires_a_valid_anchor(client):
    """`scope=this` dispatches on a truthy recurrence_id, so a missing one used
    to fall through to the whole-resource branch and delete the entire series,
    and a non-ISO one escaped as a 500 from deep in the edit path."""
    cid = _cal(client)["id"]
    ev = client.post(f"/api/calendars/{cid}/events", json={
        "summary": "Standup", "start": "2026-07-06T09:00:00", "end": "2026-07-06T09:15:00",
        "repeat": "weekly",
    }).json()
    uid = ev["uid"]
    for scope in ("this", "thisandfuture"):
        for bad in (None, "", "   ", "garbage", "2026-13-45", "not-a-date"):
            params = {"scope": scope}
            if bad is not None:
                params["recurrence_id"] = bad
            r = client.request("DELETE", f"/api/calendars/{cid}/events/{uid}", params=params)
            assert r.status_code == 422, (scope, bad, r.status_code)
            r = client.patch(f"/api/calendars/{cid}/events/{uid}",
                             json={"summary": "x", "scope": scope,
                                   **({} if bad is None else {"recurrence_id": bad})})
            assert r.status_code == 422, (scope, bad, r.status_code)
    # The series is untouched by every rejected request.
    assert client.get(f"/api/calendars/{cid}/events/{uid}").status_code == 200


def test_search_operator_characters_do_not_crash(client):
    # A NUL truncates the C string FTS5 parses, so the closing quote the operator
    # guard adds was never seen — the one input the quoting scheme was supposed
    # to make safe was the one that 500'd.
    for q in ['"unbalanced', "NEAR(", "(((", 'x"y', "a AND", "*", "-",
              "\x00", "\x00hi", "hi\x00there", "\x07\x1f"]:
        r = client.get("/api/search", params={"q": q})
        assert r.status_code == 200, (q, r.text)


def test_deleting_a_list_removes_its_tasks_from_search_and_tags(client):
    """The list vanishes from /api/lists, but its contents used to stay in the
    cache forever — queryable through /api/search with a list id that no longer
    resolves, and still advertising their tags."""
    token = uuid.uuid4().hex[:10]
    doomed, kept = _list(client), _list(client)
    # FTS matches prefixes, so the token leads each summary.
    client.post(f"/api/lists/{doomed['id']}/tasks",
                json={"summary": f"{token} gone", "tags": [f"{token}gonetag"]})
    client.post(f"/api/lists/{kept['id']}/tasks",
                json={"summary": f"{token} stays", "tags": [f"{token}stakes"]})
    assert len(client.get("/api/search", params={"q": token}).json()) == 2

    assert client.delete(f"/api/lists/{doomed['id']}").status_code == 204

    hits = client.get("/api/search", params={"q": token}).json()
    assert [h["summary"] for h in hits] == [f"{token} stays"]
    tags = client.get("/api/tags").json()
    assert f"{token}gonetag" not in tags and f"{token}stakes" in tags


def test_search_matches_prefixes(client):
    lst = _list(client)
    token = uuid.uuid4().hex[:10]
    client.post(f"/api/lists/{lst['id']}/tasks", json={"summary": f"pfx{token} report"})
    hits = client.get("/api/search", params={"q": f"pfx{token[:5]}"}).json()
    assert any(f"pfx{token}" in (h["summary"] or "") for h in hits)


def test_edit_conflict_is_409(client, monkeypatch):
    from tasksd.service import TaskService
    from tasksd.sync.engine import ConflictError

    lid = _list(client)["id"]
    t = client.post(f"/api/lists/{lid}/tasks", json={"summary": "contested"}).json()

    def boom(self, href, uid, edit):
        raise ConflictError(f"edit conflict on {uid}: retry the change")

    monkeypatch.setattr(TaskService, "edit_task", boom)
    r = client.patch(f"/api/lists/{lid}/tasks/{t['uid']}", json={"summary": "x"})
    assert r.status_code == 409
    assert "conflict" in r.json()["detail"]


def test_transport_error_is_dav_error():
    from tasksd.dav import DavClient
    from tasksd.dav.errors import DavError

    c = DavClient("http://127.0.0.1:9", "u", "p", timeout=1)   # nothing listens here
    with pytest.raises(DavError):
        c.options()
    c.close()


def test_dav_outage_is_502(client, monkeypatch):
    from tasksd.dav.errors import DavError
    from tasksd.service import TaskService

    def boom(self):
        raise DavError("connection refused")

    monkeypatch.setattr(TaskService, "list_lists", boom)
    r = client.get("/api/lists")
    assert r.status_code == 502
    assert "connection refused" not in r.json()["detail"]   # internals stay internal


# ── idempotent creates: replaying a create with the same client_id is safe ───

def test_create_task_replay_is_idempotent(client):
    lid = _list(client)["id"]
    body = {"summary": "only once", "client_id": uuid.uuid4().hex}
    r1 = client.post(f"/api/lists/{lid}/tasks", json=body)
    r2 = client.post(f"/api/lists/{lid}/tasks", json=body)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["uid"] == r2.json()["uid"]
    tasks = client.get(f"/api/lists/{lid}/tasks").json()
    assert sum(1 for t in tasks if t["summary"] == "only once") == 1
    client.delete(f"/api/lists/{lid}")


def test_create_event_replay_is_idempotent(client):
    cid = _cal(client)["id"]
    body = {"summary": "standup", "start": "2026-07-13T09:00", "end": "2026-07-13T09:15",
            "client_id": uuid.uuid4().hex}
    r1 = client.post(f"/api/calendars/{cid}/events", json=body)
    r2 = client.post(f"/api/calendars/{cid}/events", json=body)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["uid"] == r2.json()["uid"]
    evs = client.get(f"/api/calendars/{cid}/events?start=2026-07-12&end=2026-07-14").json()
    assert sum(1 for e in evs if e["summary"] == "standup") == 1
    client.delete(f"/api/calendars/{cid}")


def test_create_bad_client_id_is_422(client):
    lid = _list(client)["id"]
    for bad in ("Not Hex!", "short", "A" * 32, "x" * 200):
        r = client.post(f"/api/lists/{lid}/tasks", json={"summary": "x", "client_id": bad})
        assert r.status_code == 422, bad
    client.delete(f"/api/lists/{lid}")


# ── appearance + dashboard (custom UI) ──────────────────────────────────────


def test_settings_appearance_sync(client):
    theme = {
        "id": "t1",
        "name": "Midnight",
        "base": "dark",
        "light": {"--accent": "#ff0000"},
        "dark": {"--accent": "oklch(0.72 0.16 45)", "--radius": "6px"},
    }
    r = client.put("/api/settings", json={"appearance": {"active": "t1", "themes": [theme]}})
    assert r.status_code == 200
    got = client.get("/api/settings").json()["appearance"]
    assert got["active"] == "t1"
    assert got["themes"][0]["dark"] == theme["dark"]


def test_settings_appearance_default_is_absence_not_a_theme(client):
    # "Reset to Smylte" stores active=None. The shipped design is never written
    # as a theme, which is what makes it impossible to edit away.
    client.put("/api/settings", json={"appearance": {"active": "t1", "themes": []}})
    body = client.get("/api/settings").json()["appearance"]
    assert body["active"] == "t1" and body["themes"] == []


def test_settings_appearance_rejects_unknown_tokens(client):
    # Filtered, not 422: a theme authored against a newer token set should still
    # import the parts this build understands.
    r = client.put("/api/settings", json={"appearance": {"themes": [
        {"id": "t1", "name": "x", "light": {"--accent": "#ff0000", "--not-a-token": "red"}}
    ]}})
    assert r.status_code == 200
    assert r.json()["appearance"]["themes"][0]["light"] == {"--accent": "#ff0000"}


def test_settings_appearance_strips_css_injection(client):
    # The stored blob is read back by a pre-paint script that writes it straight
    # into the CSSOM, so a url() beacon or a property break-out must never land.
    hostile = {
        "--bg": "url(https://evil.example/beacon.png)",
        "--fg": "red; background: url(//evil)",
        "--paper": "red}html{display:none",
        "--accent": "@import 'evil.css'",
        "--warn": "expression(alert(1))",
        "--ok": "x" * 200,
    }
    r = client.put("/api/settings", json={"appearance": {"themes": [
        {"id": "t1", "name": "x", "light": hostile}
    ]}})
    assert r.status_code == 200
    assert r.json()["appearance"]["themes"][0]["light"] == {}


def test_settings_appearance_caps_theme_count(client):
    many = [{"id": f"t{i}", "name": f"n{i}"} for i in range(30)]
    r = client.put("/api/settings", json={"appearance": {"themes": many}})
    assert r.status_code == 422


def test_settings_dashboard_sync(client):
    layout = [
        {"id": "m1", "kind": "today", "x": 0, "y": 0, "w": 4, "h": 6},
        {"id": "m2", "kind": "mini_calendar", "x": 4, "y": 0, "w": 8, "h": 6},
    ]
    r = client.put("/api/settings", json={"dashboard": layout})
    assert r.status_code == 200 and r.json()["dashboard"] == layout
    assert client.get("/api/settings").json()["dashboard"] == layout
    # An empty list is a real value (back to the stock arrangement).
    client.put("/api/settings", json={"dashboard": []})
    assert client.get("/api/settings").json()["dashboard"] == []


def test_settings_dashboard_takes_every_kind_the_client_ships(client):
    # `kind` is an allowlist and the whole PUT is validated at once, so a kind
    # the client can place and the server has not heard of does not degrade to a
    # missing card — it 422s the write and takes the theme, the tab order and
    # everything else in the same body down with it. The list is mirrored in
    # dashboard.ts; `dashboard.test.ts` reads this file back out and fails when
    # the two part. This is the same claim from the other side.
    kinds = [
        "today", "day_plan", "overdue", "upcoming", "mini_calendar",
        "completed", "booking_links", "bookings", "quick_add",
    ]
    layout = [
        {"id": f"m{i}", "kind": k, "x": 0, "y": i, "w": 4, "h": 1}
        for i, k in enumerate(kinds)
    ]
    r = client.put("/api/settings", json={"dashboard": layout})
    assert r.status_code == 200, r.text
    assert client.get("/api/settings").json()["dashboard"] == layout


def test_settings_dashboard_rejects_bad_geometry(client):
    for bad in (
        {"id": "m1", "kind": "today", "x": 99, "y": 0, "w": 4, "h": 6},    # off-grid
        {"id": "m1", "kind": "today", "x": 0, "y": 0, "w": 0, "h": 6},     # zero width
        {"id": "m1", "kind": "today", "x": 0, "y": 0, "w": 4, "h": 999},   # absurd height
        {"id": "m1", "kind": "nonsense", "x": 0, "y": 0, "w": 4, "h": 6},  # unknown module
        {"id": "", "kind": "today", "x": 0, "y": 0, "w": 4, "h": 6},       # empty id
    ):
        assert client.put("/api/settings", json={"dashboard": [bad]}).status_code == 422


def test_settings_dashboard_caps_module_count(client):
    many = [
        {"id": f"m{i}", "kind": "today", "x": 0, "y": i, "w": 4, "h": 1}
        for i in range(50)
    ]
    assert client.put("/api/settings", json={"dashboard": many}).status_code == 422


def test_required_window_bounds_and_non_finite_sidecar_are_422(client):
    """Two shapes that reached past validation and 500ed in the service. The
    sidecar one persisted: a stored Infinity is legal to json.loads and illegal
    to json.dumps, so every later read of that whole list failed — and the
    sidecar is the one thing a cache drop cannot rebuild."""
    cid = _cal(client)["id"]
    lid = _list(client)["id"]
    for start, end in (("", "2026-08-01"), ("   ", "2026-08-01"), ("2026-07-01", "")):
        r = client.get(f"/api/calendars/{cid}/events", params={"start": start, "end": end})
        assert r.status_code == 422, (start, end, r.status_code)

    t = client.post(f"/api/lists/{lid}/tasks", json={"summary": "sc"}).json()
    for literal in ("NaN", "Infinity", "-Infinity"):
        r = client.put(f"/api/lists/{lid}/tasks/{t['uid']}/sidecar",
                       content=f'{{"sort_order": {literal}}}',
                       headers={"Content-Type": "application/json"})
        assert r.status_code == 422, (literal, r.status_code)
        # And the list is still readable — rendering the 422 must not blow up
        # either, which it did while the handler echoed the offending value back.
        assert client.get(f"/api/lists/{lid}/tasks").status_code == 200


def test_a_sidecar_put_for_an_unknown_task_is_a_404_and_writes_nothing(client):
    """The only write route that did not check the item exists. It answered 200
    with a body of `null` (every sibling 404s the same uid) and left a sidecar
    row with orphaned_at IS NULL — which nothing ever sets, because
    orphan_sidecar only fires when a *known* item is deleted, so gc_orphans
    could never reclaim it. Sidecar rows are the one thing a resync cannot
    rebuild, which made them permanent."""
    lid = _list(client)["id"]
    svc = client.app.state.service

    def sidecar_rows() -> int:
        with svc._lock:
            return svc._conn.execute("SELECT count(*) FROM sidecar").fetchone()[0]

    before = sidecar_rows()
    r = client.put(f"/api/lists/{lid}/tasks/no-such-uid/sidecar", json={"sort_order": 1.0})
    assert r.status_code == 404
    assert sidecar_rows() == before


def test_task_manual_reorder(client):
    # Manual order spans lists: the tasks pane is always the merged view, so a
    # position only means something if it is comparable between collections.
    a, b = _list(client), _list(client)
    mk = lambda lid, s: client.post(f"/api/lists/{lid}/tasks", json={"summary": s}).json()
    one = mk(a["id"], "one")
    two = mk(b["id"], "two")
    three = mk(a["id"], "three")

    # Until something is dragged every task is unplaced, and stays that way for
    # anything another CalDAV client creates — the sidecar is not on the wire.
    assert all(t["sort_order"] is None for t in client.get(f"/api/lists/{a['id']}/tasks").json())

    order = [
        {"list": b["id"], "uid": two["uid"]},
        {"list": a["id"], "uid": three["uid"]},
        {"list": a["id"], "uid": one["uid"]},
    ]
    assert client.post("/api/tasks/reorder", json={"items": order}).status_code == 200

    got = {t["uid"]: t["sort_order"] for t in client.get(f"/api/lists/{a['id']}/tasks").json()}
    got |= {t["uid"]: t["sort_order"] for t in client.get(f"/api/lists/{b['id']}/tasks").json()}
    assert got[two["uid"]] == 1 and got[three["uid"]] == 2 and got[one["uid"]] == 3

    # The list endpoint hands them back in that order too, so a direct API
    # reader sees what the app shows.
    assert [t["uid"] for t in client.get(f"/api/lists/{a['id']}/tasks").json()] \
        == [three["uid"], one["uid"]]

    # A reorder is one event, not one per task: nothing's iCalendar data
    # changed, and N events would make every other tab refetch N times.
    assert client.post("/api/tasks/reorder", json={"items": list(reversed(order))}).status_code == 200
    got2 = {t["uid"]: t["sort_order"] for t in client.get(f"/api/lists/{a['id']}/tasks").json()}
    assert got2[one["uid"]] == 1 and got2[three["uid"]] == 2


def test_task_reorder_rejects_a_bad_body(client):
    lst = _list(client)
    t = client.post(f"/api/lists/{lst['id']}/tasks", json={"summary": "solo"}).json()

    # An unknown list is a 404 for the whole request — a reorder never half-lands.
    r = client.post("/api/tasks/reorder", json={
        "items": [{"list": lst["id"], "uid": t["uid"]}, {"list": "nope", "uid": "x"}]})
    assert r.status_code == 404
    assert client.get(f"/api/lists/{lst['id']}/tasks").json()[0]["sort_order"] is None

    # A uid twice would take two positions with the last winning, silently
    # moving something the user never dragged.
    dup = {"list": lst["id"], "uid": t["uid"]}
    assert client.post("/api/tasks/reorder", json={"items": [dup, dup]}).status_code == 422

    # An empty order is a no-op, not an error: it is what an account with no
    # tasks at all would send.
    assert client.post("/api/tasks/reorder", json={"items": []}).status_code == 200
