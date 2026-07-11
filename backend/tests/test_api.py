"""HTTP API integration tests against scratch Radicale (spec §8), through the real
FastAPI app with username/password auth ON."""
from __future__ import annotations

import uuid

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
    reopened = client.post(f"/api/lists/{lid}/tasks/{t['uid']}/complete?done=false").json()
    assert not reopened["completed"]

    # delete
    assert client.delete(f"/api/lists/{lid}/tasks/{sub['uid']}").status_code == 204
    remaining = {x["uid"] for x in client.get(f"/api/lists/{lid}/tasks").json()}
    assert sub["uid"] not in remaining


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

    moved = client.patch(f"/api/calendars/{cid}/events/{ev['uid']}",
                         json={"start": "2026-07-10T16:00:00", "summary": "Meeting (moved)"}).json()
    assert moved["summary"] == "Meeting (moved)" and moved["start"] == "2026-07-10T16:00:00"

    assert client.delete(f"/api/calendars/{cid}/events/{hol['uid']}").status_code == 204
    after = {e["summary"] for e in client.get(f"/api/calendars/{cid}/events",
             params={"start": "2026-07-01", "end": "2026-08-01"}).json()}
    assert after == {"Meeting (moved)"}


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


def test_settings_sync(client):
    r = client.put("/api/settings", json={"theme": "dark"})
    assert r.status_code == 200 and r.json().get("theme") == "dark"
    assert client.get("/api/settings").json().get("theme") == "dark"
    # Merge, not replace: a second key coexists.
    client.put("/api/settings", json={"theme": "light"})
    assert client.get("/api/settings").json().get("theme") == "light"


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


def test_search_operator_characters_do_not_crash(client):
    for q in ['"unbalanced', "NEAR(", "(((", 'x"y', "a AND", "*", "-"]:
        r = client.get("/api/search", params={"q": q})
        assert r.status_code == 200, (q, r.text)


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
