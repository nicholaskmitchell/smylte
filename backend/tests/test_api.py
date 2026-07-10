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
