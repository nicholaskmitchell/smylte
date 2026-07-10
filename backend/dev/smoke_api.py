"""End-to-end smoke of the authenticated HTTP API against scratch Radicale.

Boots the real FastAPI app (with username/password auth ON) via TestClient, which
drives the lifespan (bootstrap sync) too. Exercises login, list/task CRUD,
subtasks + derived percent, completion, search, and that logout revokes access.

Run: backend/.venv/bin/python -m dev.smoke_api   (cwd=backend/, PYTHONPATH=.)
"""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient

from tasksd.app import create_app
from tasksd.config import Settings


def _settings(db_path: str) -> Settings:
    return Settings(
        radicale_url="http://127.0.0.1:5233",
        radicale_user="testuser",
        radicale_password="testpass",
        db_path=db_path,
        sync_interval_s=3600,
        request_timeout_s=30,
        static_dir="/nonexistent",
        hook_secret="hook",
        auth_enabled=True,
        auth_user="admin",
        auth_password_hash="",
        auth_password="testpass123",
        session_secret="smoke-secret",
        session_ttl_s=3600,
        cookie_secure=False,          # TestClient speaks http
        access_required=False,
        access_team_domain="",
        access_aud="",
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as d:
        app = create_app(_settings(os.path.join(d, "t.db")))
        with TestClient(app) as c:
            print("GET /api/me (no session):", c.get("/api/me").status_code, "(expect 401)")
            print("GET /api/lists (no session):", c.get("/api/lists").status_code, "(expect 401)")
            print("login (wrong pw):", c.post("/api/login",
                  json={"username": "admin", "password": "nope"}).status_code, "(expect 401)")

            r = c.post("/api/login", json={"username": "admin", "password": "testpass123"})
            print("login (correct):", r.status_code, "| session cookie set:",
                  "tasks_session" in r.cookies)
            print("GET /api/me:", c.get("/api/me").json())

            lst = c.post("/api/lists", json={"name": "Smoke List"}).json()
            print("created list:", lst["id"], "| is_task_list:", lst["is_task_list"])
            lid = lst["id"]

            task = c.post(f"/api/lists/{lid}/tasks", json={
                "summary": "call mom", "priority": "high",
                "due": "2026-07-15", "tags": ["family", "calls"], "notes": "about the trip",
            }).json()
            print("created task:", task["summary"], "| pri:", task["priority_label"],
                  "| due:", task["due"], "| tags:", task["tags"])

            sub = c.post(f"/api/lists/{lid}/tasks",
                         json={"summary": "buy a card", "parent": task["uid"]}).json()
            print("subtask parent link ok:", sub["parent"] == task["uid"])

            c.post(f"/api/lists/{lid}/tasks/{sub['uid']}/complete")
            parent = c.get(f"/api/lists/{lid}/tasks/{task['uid']}").json()
            print("parent derived_percent (1/1 child done):", parent["derived_percent"],
                  "| child_count:", parent["child_count"])

            done = c.post(f"/api/lists/{lid}/tasks/{task['uid']}/complete").json()
            print("completed:", done["completed"], "| status:", done["status"],
                  "| percent:", done["percent_complete"])

            print("search 'mom':", [t["summary"] for t in
                  c.get("/api/search", params={"q": "mom"}).json()])
            print("tags:", c.get("/api/tags").json())

            # Prove it round-tripped to Radicale: wipe the cache DB conceptually by
            # forcing a manual full sync and re-reading.
            print("manual sync:", c.post("/api/sync").json())
            after = c.get(f"/api/lists/{lid}/tasks").json()
            print("tasks in list after sync:", sorted(t["summary"] for t in after))

            c.post("/api/logout")
            print("GET /api/lists after logout:", c.get("/api/lists").status_code, "(expect 401)")


if __name__ == "__main__":
    main()
