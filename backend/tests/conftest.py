"""Fixtures for the Radicale-integration tests. Everything runs against the
SCRATCH server on :5233 (spec §8) — never production. Tests are skipped if it is
not reachable, so the pure-Python suites (fidelity) still run anywhere."""
from __future__ import annotations

import os
import uuid

import pytest

from tasksd.db import connect, init_db
from tasksd.sync import SyncEngine

SCRATCH_URL = os.environ.get("SCRATCH_RADICALE", "http://127.0.0.1:5233")
USER = os.environ.get("SCRATCH_USER", "testuser")
PASSWORD = os.environ.get("SCRATCH_PASSWORD", "testpass")
# Host path to the scratch storage, used only by the .Radicale.cache-drop test.
SCRATCH_STORAGE = os.environ.get(
    "SCRATCH_STORAGE", os.path.expanduser("~/tasks/scratch/data/collections")
)


def _make_dav():
    from tasksd.dav import DavClient

    return DavClient(SCRATCH_URL, USER, PASSWORD)


@pytest.fixture(scope="session")
def _scratch_up():
    try:
        c = _make_dav()
        c.options()
        c.close()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"scratch Radicale unreachable on {SCRATCH_URL}: {e}")


@pytest.fixture
def dav(_scratch_up):
    c = _make_dav()
    yield c
    c.close()


@pytest.fixture
def new_dav(_scratch_up):
    """A factory for additional independent clients (concurrency tests)."""
    clients = []

    def _factory():
        c = _make_dav()
        clients.append(c)
        return c

    yield _factory
    for c in clients:
        c.close()


@pytest.fixture
def collection(dav):
    ci = dav.create_task_collection(f"test-{uuid.uuid4().hex[:8]}", components=("VTODO",))
    yield ci
    try:
        dav.delete_collection(ci.href)
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def db(tmp_path):
    conn = connect(str(tmp_path / "tasks.db"))
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def engine(dav, db):
    return SyncEngine(dav, db)


def api_settings(db_path: str):
    """Settings for the HTTP layer against scratch, auth ON with a test password."""
    from tasksd.config import Settings

    return Settings(
        radicale_url=SCRATCH_URL, radicale_user=USER, radicale_password=PASSWORD,
        db_path=db_path, sync_interval_s=3600, request_timeout_s=30, static_dir="/nonexistent",
        hook_secret="testhook", auth_enabled=True, auth_user="admin", auth_password_hash="",
        auth_password="testpass123", session_secret="s" * 40, session_ttl_s=3600,
        cookie_secure=False, access_required=False, access_team_domain="", access_aud="",
    )


@pytest.fixture(scope="session")
def client(_scratch_up, tmp_path_factory):
    from fastapi.testclient import TestClient

    from tasksd.app import create_app

    db = tmp_path_factory.mktemp("api") / "api.db"
    app = create_app(api_settings(str(db)))
    with TestClient(app) as c:
        r = c.post("/api/login", json={"username": "admin", "password": "testpass123"})
        assert r.status_code == 200
        yield c
