"""Security-focused tests for the public surface.

Two tiers:
  * pure-unit tests of the auth primitives (no server needed) — password
    hashing, session-token integrity;
  * app-level tests through the real FastAPI app (scratch Radicale, like the
    rest of the HTTP suite) — cookie attributes, the auth gate across every
    /api route, lockout behavior, header spoofing, hook gating, and static
    path traversal.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from tasksd.app import create_app
from tasksd.auth import Authenticator, hash_password, verify_password
from tests.conftest import api_settings

SECRET = "s" * 40          # matches api_settings
LOGIN = {"username": "admin", "password": "testpass123"}


# ── password hashing (unit) ──────────────────────────────────────────────────

def test_hash_password_salts_uniquely():
    a, b = hash_password("pw"), hash_password("pw")
    assert a != b                       # fresh salt every time
    assert verify_password("pw", a) and verify_password("pw", b)
    assert not verify_password("PW", a)


@pytest.mark.parametrize("stored", [
    "", "plain$pw", "scrypt$notanumber$8$1$aa$bb", "scrypt$16384$8$1$zz$zz",
    "scrypt$16384$8$1$" + "a" * 32,     # missing hash field
    "md5$16384$8$1$" + "a" * 32 + "$" + "b" * 64,   # wrong scheme
])
def test_verify_password_rejects_malformed_records(stored):
    # A corrupt/legacy hash is a clean False, never an exception (a 500 on the
    # login path would skip lockout accounting).
    assert verify_password("pw", stored) is False


# ── session token integrity (unit) ───────────────────────────────────────────

def _auth(ttl_s: int = 3600) -> Authenticator:
    return Authenticator(user="admin", password_hash=hash_password("pw"),
                         secret=SECRET, ttl_s=ttl_s)


def test_session_rejects_foreign_signature():
    token = Authenticator(user="admin", password_hash=hash_password("pw"),
                          secret="attacker-secret-attacker-secret!", ttl_s=3600).issue_session()
    assert _auth().verify_session(token) is False


def test_session_rejects_alg_none():
    # Classic JWT downgrade: an unsigned token must never verify.
    now = datetime.now(timezone.utc)
    forged = jwt.encode(
        {"sub": "admin", "iat": now, "exp": now + timedelta(hours=1)},
        key=None, algorithm="none",
    )
    assert _auth().verify_session(forged) is False


def test_session_rejects_expired_token():
    assert _auth(ttl_s=-5).verify_session(_auth(ttl_s=-5).issue_session()) is False
    a = _auth()
    assert a.verify_session(a.issue_session()) is True


def test_session_rejects_garbage():
    a = _auth()
    for bad in (None, "", "not.a.jwt", "a" * 4096):
        assert a.verify_session(bad) is False


# ── app-level tests (scratch Radicale, real app) ─────────────────────────────

pytestmark_app = pytest.mark.radicale


@pytest.fixture
def make_app(_scratch_up, tmp_path):
    """Fresh app per test — limiter and session state must not leak across tests."""
    counter = 0

    def _make(**overrides):
        nonlocal counter
        counter += 1
        settings = dataclasses.replace(
            api_settings(str(tmp_path / f"sec{counter}.db")), **overrides
        )
        return create_app(settings)

    return _make


@pytest.mark.radicale
def test_session_cookie_attributes(make_app):
    with TestClient(make_app()) as c:
        r = c.post("/api/login", json=LOGIN)
        assert r.status_code == 200
        cookie = r.headers["set-cookie"]
        assert "tasks_session=" in cookie
        assert "httponly" in cookie.lower()          # JS (XSS) can't read it
        assert "samesite=strict" in cookie.lower()   # cross-site requests won't carry it
        assert "path=/" in cookie.lower()
        assert "max-age=3600" in cookie.lower()
        assert "secure" not in cookie.lower()        # cookie_secure=False in tests


@pytest.mark.radicale
def test_session_cookie_secure_flag_in_prod_posture(make_app):
    with TestClient(make_app(cookie_secure=True)) as c:
        r = c.post("/api/login", json=LOGIN)
        assert "secure" in r.headers["set-cookie"].lower()


@pytest.mark.radicale
def test_every_api_route_requires_auth(make_app):
    """Enumerate the live route table: everything under /api must 401 without a
    session, except the deliberate public endpoints. A new route added without
    the router dependency shows up here immediately."""
    from fastapi.routing import APIRoute

    def walk(routes):
        # include_router may mount the APIRouter lazily (_IncludedRouter) instead
        # of flattening its APIRoutes into app.routes — recurse either way.
        for r in routes:
            if isinstance(r, APIRoute):
                yield r
            elif getattr(r, "original_router", None) is not None:
                yield from walk(r.original_router.routes)
            else:
                yield from walk(getattr(r, "routes", []))

    public = {
        "/api/login", "/api/logout", "/api/me",
        "/api/public/booking/{token}", "/api/public/booking/{token}/book",
    }
    app = make_app()
    checked = 0
    with TestClient(app) as c:
        for route in walk(app.routes):
            if not route.path.startswith("/api") or route.path in public:
                continue
            path = route.path.format(**{p: "x" for p in route.param_convertors})
            for method in route.methods - {"HEAD", "OPTIONS"}:
                r = c.request(method, path)
                assert r.status_code == 401, f"{method} {route.path} -> {r.status_code}"
                checked += 1
    assert checked >= 30      # sanity: the sweep actually swept the API


@pytest.mark.radicale
def test_forged_and_expired_cookies_are_rejected(make_app):
    now = datetime.now(timezone.utc)
    claims = {"sub": "admin", "iat": now, "exp": now + timedelta(hours=1)}
    forged = jwt.encode(claims, "wrong-secret-wrong-secret-wrong!", algorithm="HS256")
    expired = jwt.encode(
        {**claims, "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        SECRET, algorithm="HS256",
    )
    unsigned = jwt.encode(claims, key=None, algorithm="none")
    with TestClient(make_app()) as c:
        for token in (forged, expired, unsigned, "garbage"):
            c.cookies.set("tasks_session", token)
            assert c.get("/api/me").status_code == 401, token
        c.cookies.clear()
        # A genuine login still works (the checks above weren't a broken app).
        assert c.post("/api/login", json=LOGIN).status_code == 200
        assert c.get("/api/me").status_code == 200


@pytest.mark.radicale
def test_login_lockout_and_spoofed_ip_header(make_app):
    """5 failures lock the client out with a 429 + Retry-After. The failures ride
    different X-Real-IP values: the TestClient peer is not loopback, so the
    header must be IGNORED (a remote attacker can't mint fresh limiter keys)."""
    with TestClient(make_app()) as c:
        for i in range(5):
            r = c.post("/api/login", json={"username": "admin", "password": "nope"},
                       headers={"X-Real-IP": f"203.0.113.{i}"})
            assert r.status_code == 401
        r = c.post("/api/login", json=LOGIN, headers={"X-Real-IP": "198.51.100.7"})
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) > 0
        # Correct credentials don't bypass an active lockout either.
        assert c.post("/api/login", json=LOGIN).status_code == 429


@pytest.mark.radicale
def test_login_error_does_not_reveal_which_field_failed(make_app):
    with TestClient(make_app()) as c:
        bad_user = c.post("/api/login", json={"username": "nobody", "password": "testpass123"})
        bad_pass = c.post("/api/login", json={"username": "admin", "password": "wrong"})
        assert bad_user.status_code == bad_pass.status_code == 401
        assert bad_user.json() == bad_pass.json()    # indistinguishable bodies


@pytest.mark.radicale
def test_login_malformed_payloads_are_422_not_500(make_app):
    with TestClient(make_app()) as c:
        for body in ({}, {"username": ["a"], "password": {}}, {"username": None, "password": None}):
            assert c.post("/api/login", json=body).status_code == 422
        r = c.post("/api/login", content=b"not json",
                   headers={"Content-Type": "application/json"})
        assert r.status_code == 422


@pytest.mark.radicale
def test_hook_requires_secret_header(make_app):
    with TestClient(make_app()) as c:
        assert c.post("/internal/changed").status_code == 403
        assert c.post("/internal/changed",
                      headers={"X-Tasks-Hook-Secret": ""}).status_code == 403
        assert c.post("/internal/changed",
                      headers={"X-Tasks-Hook-Secret": "testhook"}).status_code == 202


@pytest.mark.radicale
def test_static_mount_does_not_traverse(make_app, tmp_path):
    """The SPA mount must never serve files outside dist/ — a secret sibling
    file stays unreachable through encoded/plain .. traversal."""
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<html>app</html>")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")

    with TestClient(make_app(static_dir=str(static))) as c:
        assert c.get("/").status_code == 200
        assert c.get("/book/whatever-token").status_code == 200   # SPA deep link
        for path in (
            "/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt",
            "/static/../../secret.txt", "/%2e%2e%2fsecret.txt",
        ):
            r = c.get(path)
            assert "TOP-SECRET" not in r.text, path


@pytest.mark.radicale
def test_public_booking_unknown_token_is_404(make_app):
    with TestClient(make_app()) as c:
        assert c.get("/api/public/booking/no-such-token").status_code == 404
        r = c.post("/api/public/booking/no-such-token/book", json={
            "start": "2026-07-20T10:00:00+00:00", "name": "Eve", "email": "eve@example.com",
        })
        assert r.status_code == 404


@pytest.mark.radicale
def test_502_bodies_never_leak_internals(make_app, monkeypatch):
    # The DavError handler must speak in generic terms; URLs, credentials, and
    # exception internals stay in the log.
    from tasksd.dav.errors import DavError
    from tasksd.service import TaskService

    def boom(self):
        raise DavError("http://127.0.0.1:5233/testuser/secret-collection auth=testpass")

    monkeypatch.setattr(TaskService, "list_lists", boom)
    with TestClient(make_app()) as c:
        c.post("/api/login", json=LOGIN)
        r = c.get("/api/lists")
        assert r.status_code == 502
        assert "5233" not in r.text and "testpass" not in r.text
