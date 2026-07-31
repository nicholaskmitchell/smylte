"""RFC 6764 discovery — the routes that let path-blind DAV clients connect.

Raw CalDAV is published under `/dav`, but Apple's client (macOS/iOS) has no
field for a path: you give it a host, and it probes the root for a redirect.
These tests pin that probe sequence.

No Radicale needed: the app is built but its lifespan is never entered (no
`with`), so nothing here touches the network or the cache.
"""
from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from tasksd.app import create_app
from tasksd.config import normalize_dav_url
from tests.conftest import api_settings

WELL_KNOWN = ["/.well-known/caldav", "/.well-known/carddav"]


@pytest.fixture(scope="module")
def anon(tmp_path_factory):
    """An UNAUTHENTICATED client: discovery happens before any login, and the
    credentials a DAV client holds are Radicale's, not this app's."""
    db = tmp_path_factory.mktemp("discovery") / "d.db"
    return TestClient(create_app(api_settings(str(db))))


@pytest.mark.parametrize("path", WELL_KNOWN)
@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "PROPFIND", "REPORT"])
def test_well_known_redirects_to_the_dav_base(anon, path, method):
    # Apple sends PROPFIND here; others GET or OPTIONS first. Every verb a
    # client might open discovery with has to land on the same redirect.
    r = anon.request(method, path, follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "/dav/"


@pytest.mark.parametrize("path", [p + "/" for p in WELL_KNOWN])
def test_well_known_trailing_slash_also_redirects(anon, path):
    # The SPA mount at "/" matches everything, so Starlette's redirect_slashes
    # never fires — the trailing-slash spellings are registered explicitly.
    r = anon.request("PROPFIND", path, follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "/dav/"


@pytest.mark.parametrize("method", ["OPTIONS", "PROPFIND", "PROPPATCH", "REPORT"])
def test_root_dav_verbs_redirect_to_the_dav_base(anon, method):
    # The fallback probe: a client that skips well-known and asks the root for
    # DAV:current-user-principal. Without this it hits the SPA and gets a 405.
    r = anon.request(method, "/", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "/dav/"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_root_browser_traffic_is_untouched(anon, method):
    # The whole point of matching on method: the web app still owns "/".
    r = anon.request(method, "/", follow_redirects=False)
    assert r.status_code != 301


def test_discovery_does_not_leak_the_api(anon):
    # Discovery is open by necessity; it must not become a hole around the auth
    # gate. Everything else stays gated.
    assert anon.get("/api/lists", follow_redirects=False).status_code == 401
    # And nothing under .well-known other than the two DAV services answers.
    assert anon.get("/.well-known/acme-challenge/x").status_code != 301


def test_root_verbs_survive_the_spa_mount(tmp_path):
    # The real deployment mounts StaticFiles at "/", which matches every path.
    # Routing has to keep preferring the DAV route on a DAV verb (Starlette
    # takes the first FULL match, and it is registered ahead of the mount) while
    # GET still falls through to the built frontend. api_settings points at a
    # nonexistent static_dir, so the other tests never exercise this.
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>smylte</title>")
    settings = dataclasses.replace(
        api_settings(str(tmp_path / "d.db")), static_dir=str(static)
    )
    c = TestClient(create_app(settings))

    r = c.request("PROPFIND", "/", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "/dav/"

    r = c.request("PROPFIND", "/.well-known/caldav", follow_redirects=False)
    assert r.status_code == 301

    spa = c.get("/", follow_redirects=False)
    assert spa.status_code == 200
    assert "smylte" in spa.text


def test_dav_base_is_configurable(tmp_path):
    # DAV on its own host (dav.example.com) is the other way to make Apple work;
    # discovery then has to point off-origin.
    settings = dataclasses.replace(
        api_settings(str(tmp_path / "d.db")),
        dav_public_url=normalize_dav_url("https://dav.example.com"),
    )
    c = TestClient(create_app(settings))
    r = c.request("PROPFIND", "/.well-known/caldav", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "https://dav.example.com/"


@pytest.mark.parametrize("raw, expect", [
    ("", "/dav/"),
    ("/dav", "/dav/"),
    ("/dav/", "/dav/"),
    ("dav", "/dav/"),
    ("  /caldav  ", "/caldav/"),
    ("https://dav.example.com", "https://dav.example.com/"),
    ("https://dav.example.com/remote.php/dav", "https://dav.example.com/remote.php/dav/"),
])
def test_normalize_dav_url(raw, expect):
    # The redirect target is a collection context path: always trailing-slashed,
    # and a bare path always rooted (a relative Location would resolve wrong).
    assert normalize_dav_url(raw) == expect
