"""End-to-end smoke of the Calendar (VEVENT) path through the authenticated API.

Run: backend/.venv/bin/python -m dev.smoke_calendar   (cwd=backend/, PYTHONPATH=.)
"""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient

from tasksd.app import create_app
from tasksd.config import Settings


def _settings(db_path: str) -> Settings:
    return Settings(
        radicale_url="http://127.0.0.1:5233", radicale_user="testuser",
        radicale_password="testpass", db_path=db_path, sync_interval_s=3600,
        request_timeout_s=30, static_dir="/nonexistent", hook_secret="hook",
        auth_enabled=True, auth_user="admin", auth_password_hash="",
        auth_password="testpass123", session_secret="x" * 40, session_ttl_s=3600,
        cookie_secure=False, access_required=False, access_team_domain="", access_aud="",
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as d:
        with TestClient(create_app(_settings(os.path.join(d, "t.db")))) as c:
            c.post("/api/login", json={"username": "admin", "password": "testpass123"})

            cal = c.post("/api/calendars", json={"name": "Personal"}).json()
            print("created calendar:", cal["name"], "| is_calendar:", cal["is_calendar"],
                  "| is_task_list:", cal["is_task_list"])
            cid = cal["id"]

            ev = c.post(f"/api/calendars/{cid}/events", json={
                "summary": "Team meeting", "start": "2026-07-10T14:00:00",
                "end": "2026-07-10T15:00:00", "location": "Zoom", "tags": ["work"],
            }).json()
            print("created timed event:", ev["summary"], ev["start"], "->", ev["end"],
                  "| all_day:", ev["all_day"], "| loc:", ev["location"])

            hol = c.post(f"/api/calendars/{cid}/events", json={
                "summary": "Holiday", "start": "2026-07-12", "all_day": True,
            }).json()
            print("created all-day event:", hol["summary"], hol["start"], "| all_day:", hol["all_day"])

            rec = c.post(f"/api/calendars/{cid}/events", json={
                "summary": "Standup", "start": "2026-07-06T09:00:00",
                "end": "2026-07-06T09:15:00", "repeat": "weekly",
            }).json()
            print("created recurring event:", rec["summary"], "| is_recurring:", rec["is_recurring"])

            month = c.get(f"/api/calendars/{cid}/events",
                          params={"start": "2026-07-01", "end": "2026-08-01"}).json()
            print("events in July:", sorted((e["summary"], e["start"]) for e in month))

            # The weekly series expands across a month that starts weeks after the
            # first occurrence (the recurrence fix).
            aug = c.get(f"/api/calendars/{cid}/events",
                        params={"start": "2026-08-01", "end": "2026-09-01"}).json()
            print("August 'Standup' occurrences:",
                  sorted(e["start"] for e in aug if e["summary"] == "Standup"))

            # Edit just one occurrence ("this event").
            second = sorted((e for e in month if e["summary"] == "Standup"),
                            key=lambda e: e["start"])[1]
            c.patch(f"/api/calendars/{cid}/events/{rec['uid']}", json={
                "summary": "Standup (1:1)", "start": "2026-07-13T10:00:00",
                "end": "2026-07-13T10:30:00", "recurrence_id": second["recurrence_id"],
                "scope": "this",
            })
            july2 = c.get(f"/api/calendars/{cid}/events",
                          params={"start": "2026-07-01", "end": "2026-08-01"}).json()
            print("after per-occurrence edit:",
                  sorted((e["summary"], e["start"]) for e in july2 if "Standup" in (e["summary"] or "")))

            moved = c.patch(f"/api/calendars/{cid}/events/{ev['uid']}",
                            json={"start": "2026-07-10T16:00:00", "end": "2026-07-10T17:00:00",
                                  "summary": "Team meeting (moved)"}).json()
            print("edited event:", moved["summary"], moved["start"], "->", moved["end"])

            c.delete(f"/api/calendars/{cid}/events/{hol['uid']}")
            after = c.get(f"/api/calendars/{cid}/events",
                          params={"start": "2026-07-01", "end": "2026-08-01"}).json()
            print("after deleting Holiday:", sorted(e["summary"] for e in after))

            # calendars vs task lists are separate tabs
            print("calendars:", [x["name"] for x in c.get("/api/calendars").json()])
            print("task lists:", [x["name"] for x in c.get("/api/lists").json()])


if __name__ == "__main__":
    main()
