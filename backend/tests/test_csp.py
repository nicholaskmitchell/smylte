"""The Content-Security-Policy (tasksd/csp.py).

The policy is the bound over everything the field-level guards do not name. It
is also the kind of control that fails silently in both directions: too loose
and it protects nothing while looking like it does; too strict and the app is a
blank page. So the assertions here are about the SHAPE of the policy as much as
its presence.

No Radicale: the app is built without entering its lifespan and a stub stands in
on `app.state.service`, the pattern from test_loop_blocking.py.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from tasksd.app import create_app
from tasksd.csp import build_policy, inline_script_hashes, policy_for_index
from tests.conftest import api_settings

HEADER = "content-security-policy"
REPORT_HEADER = "content-security-policy-report-only"


class _StubService:
    """Enough for the routes these tests touch."""

    def __init__(self) -> None:
        self._lock = threading.RLock()


def _app(tmp_path, **overrides):
    settings = dataclasses.replace(api_settings(str(tmp_path / "csp.db")), **overrides)
    app = create_app(settings)
    app.state.service = _StubService()      # lifespan never runs, so wire it here
    return app


def _sha256(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def _static_dir(tmp_path, html: str) -> str:
    d = tmp_path / "static"
    d.mkdir()
    (d / "index.html").write_text(html, encoding="utf-8")
    return str(d)


# ── hashing ─────────────────────────────────────────────────────────────────

def test_inline_scripts_are_hashed_and_src_scripts_are_not():
    """A `src=` script needs no hash — `'self'` covers it. Only a script with a
    BODY has anything to hash, and getting this backwards means the app's own
    pre-paint script is blocked and nothing paints."""
    body = "\n  var x = 1\n"
    html = (
        "<!doctype html><html><head>"
        f"<script>{body}</script>"
        '<script type="module" src="/assets/index-abc.js"></script>'
        "</head><body></body></html>"
    )
    assert inline_script_hashes(html) == [_sha256(body)]


def test_a_page_with_no_inline_script_yields_no_hash():
    assert inline_script_hashes("<html><body>nothing</body></html>") == []


def test_every_inline_script_is_hashed():
    html = "<script>one</script><script defer>two</script>"
    assert inline_script_hashes(html) == [_sha256("one"), _sha256("two")]


# ── the shape of the policy ─────────────────────────────────────────────────

def test_the_policy_locks_down_the_obvious_sinks():
    p = build_policy([])
    for directive in (
        "default-src 'self'", "base-uri 'none'", "object-src 'none'",
        "frame-ancestors 'none'", "form-action 'self'", "connect-src 'self'",
    ):
        assert directive in p, directive


def test_script_src_never_gains_unsafe_inline():
    """It would be IGNORED while a hash is present (CSP3) and honoured the
    moment the hash went away — silently turning a real policy into a
    decorative one. The regression this pins is somebody 'fixing' a blocked
    script by adding the keyword instead of the hash."""
    script_src = _directive(build_policy([_sha256("x")]), "script-src")
    assert "'unsafe-inline'" not in script_src
    assert "'unsafe-eval'" not in script_src
    assert "'self'" in script_src


def test_style_src_keeps_unsafe_inline_and_never_gains_a_hash():
    """The SPA cannot live without `'unsafe-inline'` for styles: every calendar
    and list color is an inline style, and the MCP consent screen is a `<style>`
    block. Adding ANY hash or nonce to this directive makes browsers ignore the
    keyword — which blanks the app. Pinned because it looks like a tightening."""
    style_src = _directive(build_policy([]), "style-src")
    assert "'unsafe-inline'" in style_src
    assert "sha256-" not in style_src
    assert "nonce-" not in style_src


def test_the_google_fonts_hosts_are_allowed_where_they_are_needed():
    """13 of the 24 Appearance font choices load a stylesheet from
    fonts.googleapis.com at runtime (`appearance.ts ensureFont`), and that
    stylesheet pulls woff2 from fonts.gstatic.com. Both are needed, in
    different directives, or the picker silently falls back."""
    p = build_policy([])
    assert "https://fonts.googleapis.com" in _directive(p, "style-src")
    assert "https://fonts.gstatic.com" in _directive(p, "font-src")
    # …and nowhere else: a third-party host in script-src would be a real hole.
    assert "fonts.google" not in _directive(p, "script-src")
    assert "fonts.g" not in _directive(p, "connect-src")


def _directive(policy: str, name: str) -> str:
    for part in policy.split(";"):
        part = part.strip()
        if part.split(" ")[0] == name:
            return part
    raise AssertionError(f"{name} missing from {policy!r}")


# ── the header, end to end ──────────────────────────────────────────────────

def test_the_header_carries_the_hash_of_the_index_that_is_actually_served(tmp_path):
    """The drift-proof assertion.

    The hash is derived from the file on disk rather than written down, so this
    builds a static dir with a KNOWN inline script and checks that script's hash
    comes back on the wire. It proves the whole derivation without needing a
    vite build — which no test can have, since CI runs `npm test` before
    `npm run build`."""
    body = "\n  window.__theme = 'dark'\n"
    static = _static_dir(tmp_path, f"<!doctype html><html><head><script>{body}</script>"
                                   "</head><body></body></html>")
    with TestClient(_app(tmp_path, static_dir=static)) as c:
        r = c.get("/book/anything")
        assert r.status_code == 200
        assert _sha256(body) in r.headers[HEADER]


def test_the_policy_is_on_api_responses_too(tmp_path):
    """Not just HTML. One header on a JSON body costs nothing and means no
    route — present or future — quietly escapes the policy."""
    with TestClient(_app(tmp_path)) as c:
        r = c.get("/api/me")
        assert r.status_code in (200, 401)
        assert "default-src 'self'" in r.headers[HEADER]


def test_a_deployment_with_no_built_frontend_still_gets_a_policy(tmp_path):
    """api_settings points static_dir at /nonexistent. The API and the MCP pages
    are still worth bounding; there is simply no script hash to add."""
    with TestClient(_app(tmp_path)) as c:
        policy = c.get("/api/me").headers[HEADER]
    assert "sha256-" not in policy
    assert "default-src 'self'" in policy


def test_only_one_policy_header_is_ever_set(tmp_path):
    """Browsers enforce the INTERSECTION of every policy on a response, so a
    duplicate is indistinguishable from a deliberate tightening and produces a
    policy no file describes."""
    with TestClient(_app(tmp_path)) as c:
        r = c.get("/api/me")
    assert len(r.headers.get_list(HEADER)) == 1


# ── the escape hatch ────────────────────────────────────────────────────────

def test_report_only_mode_blocks_nothing(tmp_path):
    with TestClient(_app(tmp_path, csp_mode="report-only")) as c:
        r = c.get("/api/me")
    assert HEADER not in r.headers
    assert "default-src 'self'" in r.headers[REPORT_HEADER]


def test_off_sets_no_header_at_all(tmp_path):
    """The escape hatch has to actually escape: a policy that turns out to block
    something real must be removable from /etc/tasks/tasks.env, without a code
    change or a frontend redeploy."""
    with TestClient(_app(tmp_path, csp_mode="off")) as c:
        r = c.get("/api/me")
    assert HEADER not in r.headers
    assert REPORT_HEADER not in r.headers


def test_an_unrecognised_mode_enforces_rather_than_failing_open(tmp_path):
    """This is a security control, so a typo in the env file must not quietly
    disable it — the same posture config._bool takes for auth_enabled."""
    with TestClient(_app(tmp_path, csp_mode="yes-please")) as c:
        r = c.get("/api/me")
    assert "default-src 'self'" in r.headers[HEADER]


# ── the real frontend ───────────────────────────────────────────────────────

def test_the_shipped_index_html_yields_exactly_one_script_hash():
    """Read from the other side of the repo, the way appearance.test.ts reads
    index.html from the frontend side.

    If someone adds a second inline script the derivation still covers it (the
    hash is computed at runtime), so this is not a correctness guard — it is a
    prompt. A new inline script in the shell is a thing to have thought about,
    and this test is where the thinking gets recorded."""
    index = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    hashes = inline_script_hashes(index.read_text(encoding="utf-8"))
    assert len(hashes) == 1, hashes
    assert hashes[0] in policy_for_index(index.read_text(encoding="utf-8"))
