"""The 2026-08-19 sweep: user-visible backend correctness (stage 4) and
delivery infrastructure / test gaps (stage 5).

This file is now MIXED, and which is which is readable off the markers. A test
still carrying `xfail(strict=True)` pins an OPEN finding: it drives the real
code, asserts the behaviour that code SHOULD have, and fails against what it
does today — the marker is what keeps CI green while the finding is open, and
what turns the build red the moment it is fixed without being ticked off. A test
with no marker is a closed finding's regression test and must stay green.

**Both stage-4 findings here are closed** (the consent form's default button,
and `/book/<token>/`). Each was widened before it was fixed and then run against
a plausible half-fix to confirm the widened pin still caught one — for the
consent form that half-fix was "autofocus Connect but leave Cancel first in tree
order", which does not change the default button and which the pin refuses. What
remains open is stage 5: the release workflow's token scope, and setup.sh's
password escaping.

The test-gap findings are the exception, and they split two ways, exactly as
test_backlog_stage5.py describes: a gap is closed by a test EXISTING, so the
test is written and run, and then it is kept as whatever it turned out to be.
Three of them (the confidential-client credential check, the shape of a 204,
the won't-do write path) cover behaviour that is already correct — no gap hid a
bug there, only coverage was missing, so they carry no marker and must stay
green like any other test. The fourth (busy_intervals across a DST transition)
found two live defects the gap had been hiding, and is pinned like the rest.

Run just this file with `pytest tests/test_backlog_aug19_stage45.py -rxX`, or
the whole executable backlog with `pytest -m backlog -rxX`.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tasksd import scheduling
from tasksd.app import create_app
from tasksd.db import store
from tests.conftest import api_settings

pytestmark = [pytest.mark.backlog, pytest.mark.stage4, pytest.mark.stage5]

REPO = pathlib.Path(__file__).resolve().parents[2]

ISSUER = "https://tasks.example.test"
MCP_URL = f"{ISSUER}/mcp"
CALLBACK = "https://claude.ai/api/mcp/auth_callback"
PASSWORD = "testpass123"          # api_settings' auth_password
TZ = ZoneInfo("America/Chicago")


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ── a consent-screen app with no CalDAV server behind it ────────────────────

class _StubService:
    """Enough TaskService for the OAuth endpoints: they only ever touch the
    SQLite side, through `oauth()`."""

    def __init__(self) -> None:
        self._conn = store.connect(":memory:")
        store.init_db(self._conn)
        self._lock = threading.RLock()

    def oauth(self, fn, *a, **kw):
        with self._lock:
            return fn(self._conn, *a, **kw)


@pytest.fixture
def oauth_app(tmp_path):
    settings = dataclasses.replace(
        api_settings(str(tmp_path / "aug19.db")), mcp_enabled=True, public_url=ISSUER)
    app = create_app(settings)
    app.state.service = _StubService()
    return TestClient(app)


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(uuid.uuid4().bytes * 2).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _register(client, **over) -> dict:
    body = {"client_name": "Claude", "redirect_uris": [CALLBACK],
            "token_endpoint_auth_method": "none", **over}
    r = client.post("/oauth/register", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _consent_page(client, reg, challenge, *, scope="mcp:read"):
    params = {"response_type": "code", "client_id": reg["client_id"],
              "redirect_uri": CALLBACK, "code_challenge": challenge,
              "code_challenge_method": "S256", "state": "xyz",
              "scope": scope, "resource": MCP_URL}
    page = client.get("/oauth/authorize", params=params)
    assert page.status_code == 200, page.text
    return page.text


def _approve(client, reg, challenge, *, scope="mcp:read") -> str:
    """The consent screen, approved the way test_mcp.py's `_authorize` does.
    Returns the authorization code."""
    page = _consent_page(client, reg, challenge, scope=scope)
    signed = re.search(r'name="request" value="([^"]+)"', page).group(1)
    r = client.post("/oauth/authorize", data={
        "request": signed, "action": "approve", "grant": "full",
        "username": "admin", "password": PASSWORD}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return parse_qs(urlsplit(r.headers["location"]).query)["code"][0]


# ── AUDIT: "Cancel" is the consent form's default button ────────────────────

_FORM = re.compile(r"<form\b.*?</form>", re.I | re.S)
_CONTROL = re.compile(r"<(button|input)\b([^>]*)>", re.I)
_ATTR = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')


def _submit_controls(page: str) -> list[dict[str, str]]:
    """Every SUBMIT control in the consent form, in tree order.

    Separate from `_implicit_submission` because two different questions are
    being asked of the same markup: which control the browser activates on
    Enter, and whether a control exists at all that can produce a given action.
    """
    form = _FORM.search(page)
    assert form, "the consent page has no <form> to submit"
    out: list[dict[str, str]] = []
    for m in _CONTROL.finditer(form.group(0)):
        tag, raw = m.group(1).lower(), m.group(2)
        attrs = dict(_ATTR.findall(raw))
        kind = (attrs.get("type") or ("submit" if tag == "button" else "text")).lower()
        if kind in ("submit", "image"):
            out.append(attrs)
    return out


def _rendered_action_order(page: str) -> list[str]:
    """The action buttons in the order a SIGHTED user sees them, left to right.

    Tree order is not screen order here: `.actions` is
    `display: flex; flex-direction: row-reverse`, deliberately, so that Connect
    can be first in the DOM (and so win HTML's implicit submission) while Cancel
    stays on the left where it has always been. Both halves are load-bearing and
    only one of them is in the markup, so this reads the stylesheet too.
    """
    values = [a.get("value", "") for a in _submit_controls(page)]
    block = re.search(r"\.actions\s*\{([^}]*)\}", page, re.I)
    assert block, "the consent page has no .actions rule"
    if re.search(r"flex-direction\s*:\s*row-reverse", block.group(1), re.I):
        values.reverse()
    return values


def _implicit_submission(page: str) -> dict[str, str]:
    """What the browser POSTs when the user presses Enter in a text field.

    HTML's implicit submission activates the form's *default button* — the
    first submit button in tree order — and sends its name/value along with the
    fields. `<button>` defaults to type=submit; an `<input>` does not.
    """
    form = _FORM.search(page)
    assert form, "the consent page has no <form> to submit"
    body = form.group(0)

    data: dict[str, str] = {"username": "admin", "password": PASSWORD}
    default: dict[str, str] | None = None
    for m in _CONTROL.finditer(body):
        tag, raw = m.group(1).lower(), m.group(2)
        attrs = dict(_ATTR.findall(raw))
        kind = (attrs.get("type") or ("submit" if tag == "button" else "text")).lower()
        if kind in ("submit", "image"):
            if default is None:
                default = attrs
        elif tag == "input" and attrs.get("name"):
            if kind == "hidden":
                data[attrs["name"]] = attrs.get("value", "")
            elif kind == "radio" and re.search(r"\bchecked\b", raw, re.I):
                data[attrs["name"]] = attrs.get("value", "")
    if default and default.get("name"):
        data[default["name"]] = default.get("value", "")
    return data


def _submit(client, page: str, **over):
    """Press Enter in the consent form, optionally overriding a field."""
    data = _implicit_submission(page)
    data.update(over)
    return client.post("/oauth/authorize", data=data, follow_redirects=False)


def _redirect_query(r) -> dict[str, list[str]]:
    return parse_qs(urlsplit(r.headers.get("location", "")).query)


def _exchange_code(client, reg, verifier: str, code: str):
    return client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": CALLBACK, "client_id": reg["client_id"],
        "code_verifier": verifier, "resource": MCP_URL})


def test_pressing_enter_on_the_consent_form_connects_rather_than_declining(oauth_app):
    """The consent screen is this app's most important password form, and its
    username field is `autofocus`. Type the username, Tab, type the password,
    press Enter — the ordinary way anybody fills in two fields — and the browser
    activates the form's default button, which is the FIRST submit button in
    tree order. `_consent_page` emits Cancel first, so Enter POSTs
    `action=deny`; `authorize_submit` short-circuits before the password is even
    looked at and 303s back to the connector with
    `error=access_denied&error_description=the+request+was+declined`.

    The user has just typed their password into a form that told the client they
    refused it, and the browser has already navigated to the client's callback,
    so there is nothing to correct in place — the whole flow restarts from the
    client. Nor can script rescue it: the page ships
    `default-src 'none'; style-src 'unsafe-inline'`.

    This drives the real page and then submits it the way the browser would,
    rather than asserting where any particular button sits: put Connect first,
    make Cancel a link or a `type="button"`, reverse the row with CSS — any of
    those passes. What must not happen is that Enter declines.
    """
    reg = _register(oauth_app)

    # -- the read-only request: no grant radios on the page at all --
    verifier, challenge = _pkce()
    page = _consent_page(oauth_app, reg, challenge)
    r = _submit(oauth_app, page)
    query = _redirect_query(r)

    assert query.get("error") != ["access_denied"], (
        "pressing Enter after typing the password declined the connection: "
        f"{r.status_code} -> {r.headers.get('location')}"
    )
    assert query.get("code"), (
        "the form's default submission did not authorize the client: "
        f"{r.status_code} -> {r.headers.get('location') or r.text[:200]}"
    )

    # -- the read+write request, where the page also carries the grant radios --
    # A different page: `read_only_choice` inserts two <input type="radio">
    # controls ahead of the username field, and the default button is still
    # whichever submit button comes first. Enter must approve here too, and it
    # must grant what the CHECKED radio says rather than something narrower or
    # wider.
    verifier, challenge = _pkce()
    page = _consent_page(oauth_app, reg, challenge, scope="mcp:read mcp:write")
    assert 'name="grant"' in page, (
        "the read+write consent page did not render the grant choice, so this "
        "case is not exercising the branch it was written for"
    )
    r = _submit(oauth_app, page)
    query = _redirect_query(r)
    assert query.get("code"), (
        "the default submission did not authorize a read+write request: "
        f"{r.status_code} -> {r.headers.get('location') or r.text[:200]}"
    )
    tok = _exchange_code(oauth_app, reg, verifier, query["code"][0])
    assert tok.status_code == 200, tok.text
    assert "mcp:write" in tok.json()["scope"].split(), (
        "'Full access' was checked and Enter granted something narrower: "
        f"{tok.json()['scope']!r}"
    )

    # -- and the read-only choice survives the default submission --
    # Reached the way a person reaches it: pick Read-only, mistype the password,
    # and the re-rendered page carries the choice back with `read` checked.
    # Pressing Enter on THAT page must approve, and must approve read-only.
    verifier, challenge = _pkce()
    page = _consent_page(oauth_app, reg, challenge, scope="mcp:read mcp:write")
    retry = _submit(oauth_app, page, grant="read", password="not-the-password")
    assert retry.status_code == 401, retry.text
    assert 'value="read" checked' in retry.text, (
        "the retry page did not carry the read-only choice back, so this case "
        "cannot tell whether Enter honoured it"
    )
    r = _submit(oauth_app, retry.text)
    query = _redirect_query(r)
    assert query.get("code"), (
        "the default submission on the retry page did not authorize: "
        f"{r.status_code} -> {r.headers.get('location') or r.text[:200]}"
    )
    tok = _exchange_code(oauth_app, reg, verifier, query["code"][0])
    assert tok.status_code == 200, tok.text
    assert "mcp:write" not in tok.json()["scope"].split(), (
        "'Read-only' was checked and Enter granted write anyway: "
        f"{tok.json()['scope']!r}"
    )

    # -- control: the user must still be ABLE to decline, and to find Cancel --
    #
    # WIDENED after an adversarial review walked two different repairs past the
    # version of this that hand-wrote `action=deny`. Both left a broken screen:
    #
    #   * `<button type="button" … value="deny">` — Connect becomes the default
    #     button, so the pin above passes, and Cancel is INERT. This page ships
    #     `default-src 'none'`, so no script can wire it up; the user cannot
    #     decline at all and the client is left hanging with no `access_denied`.
    #   * deleting `flex-direction: row-reverse` — the pin above still passes,
    #     and Connect now RENDERS where Cancel used to be. Anyone declining by
    #     muscle memory grants the token instead.
    #
    # So the decline is derived from the page rather than assumed, and the
    # rendered order is asserted rather than only the tree order.
    _, challenge = _pkce()
    page = _consent_page(oauth_app, reg, challenge)

    controls = _submit_controls(page)
    assert [c.get("value") for c in controls][:1] == ["approve"], (
        "the form's first submit control is not Connect, so Enter will not "
        f"connect: {[c.get('value') for c in controls]}"
    )
    denies = [c for c in controls if c.get("value") == "deny"]
    assert denies, (
        "no SUBMIT control on the consent form can produce a decline — Cancel "
        "cannot be pressed, and the page's CSP forbids a script that would fix it"
    )
    assert _rendered_action_order(page) == ["deny", "approve"], (
        "Connect no longer renders on the right where it has always been; a "
        "user declining by muscle memory would grant the token: "
        f"{_rendered_action_order(page)}"
    )

    # …and the control the page really offers does really decline.
    declined = _submit(oauth_app, page, action=denies[0].get("value", "deny"))
    assert _redirect_query(declined).get("error") == ["access_denied"], (
        "pressing Cancel no longer declines: "
        f"{declined.status_code} -> {declined.headers.get('location')}"
    )


# ── AUDIT: /book/<token>/ 404s ──────────────────────────────────────────────

def test_a_booking_link_serves_the_spa_with_or_without_a_trailing_slash(tmp_path):
    """`@app.get("/book/{token}")` is registered in the bare spelling only, and
    `StaticFiles` mounted at "/" returns a FULL match for every path — so
    Starlette hands `/book/<token>/` to the mount inside its route loop and
    FastAPI's `redirect_slashes` fallback, which only runs when the loop found
    nothing, never executes. The mount looks for a file called `book/<token>`,
    does not find one, and raises a bare JSON 404.

    app.py already documents this hazard 25 lines earlier — the RFC 6764 routes
    register their trailing-slash spellings explicitly "because the SPA mount at
    '/' swallows unmatched paths". The booking route did not get the same
    treatment, while the SPA router deliberately accepts the slash
    (frontend/src/main.tsx matches `/^\\/book\\/([A-Za-z0-9_-]+)\\/?$/`).

    So an anonymous visitor who requests the owner's published link with the
    trailing slash a path that looks like a folder invites — typed by hand, or
    rewritten by a mail client — gets `{"detail":"Not Found"}`, which reads
    exactly like the "this link is no longer available" case. They do not book
    and the owner never hears about it.

    Redirects are followed, so answering the slash with a 308 to the bare
    spelling passes this just as well as registering the second route.
    """
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text(
        '<!doctype html><html><head><title>Smylte</title></head>'
        '<body><div id="root"></div></body></html>', encoding="utf-8")
    settings = dataclasses.replace(
        api_settings(str(tmp_path / "book.db")), static_dir=str(static))
    client = TestClient(create_app(settings))

    for path in ("/book/Ab3-_x9Q", "/book/Ab3-_x9Q/"):
        r = client.get(path)
        assert r.status_code == 200, (
            f"GET {path} -> {r.status_code} {r.headers.get('content-type')} "
            f"{r.text[:120]!r}"
        )
        assert "text/html" in r.headers.get("content-type", ""), (
            f"GET {path} did not serve the SPA shell: "
            f"{r.headers.get('content-type')}"
        )
        assert 'id="root"' in r.text

        # NOT asserted here: that HEAD answers too. It does not — FastAPI's
        # APIRoute, unlike Starlette's Route, does not derive HEAD from GET, so
        # `HEAD /book/<token>` 404s today on BOTH spellings while GET serves the
        # shell. That is a real inconsistency and a separate finding; pinning it
        # here would make this pin drive a fix wider than the finding it names.

    # -- controls: the repair is the second spelling, not a catch-all --
    # A route that swallowed everything under /book/ would serve the shell for
    # a path no booking link can produce, and the SPA's own matcher
    # (frontend/src/main.tsx) refuses it, so the visitor would get a blank page
    # instead of a 404.
    deeper = client.get("/book/Ab3-_x9Q/extra")
    assert deeper.status_code == 404, (
        f"GET /book/<token>/extra -> {deeper.status_code}; the fix widened the "
        f"route rather than registering the trailing-slash spelling"
    )
    missing = client.get("/nope")
    assert missing.status_code == 404, (
        f"GET /nope -> {missing.status_code}; an unrelated path stopped 404ing"
    )


# ── AUDIT: shutdown closes the DB and DAV client under a running sweep ──────

@pytest.mark.radicale
# ── AUDIT: shutdown tears down the service under a running sweep ───────────
#
# DELIBERATELY NOT PINNED. The finding is real and stands in docs/AUDIT.md: the
# lifespan cancels the asyncio future while the worker thread carries on, so
# `svc.close()` runs against a live sweep and the next slice's
# `store.has_collection` — outside the per-collection try/except — raises
# sqlite3.ProgrammingError.
#
# It reproduces on demand in isolation (swap the service's RLock for one that
# yields on release and `close()` reliably wins the gap between two slices:
# sweep:start -> close:enter -> close:done -> sweep:RAISED ProgrammingError).
# It does NOT reproduce reliably once other tests in this file have run: three
# consecutive whole-file runs gave xfail / XPASS / xfail. Under `strict=True`
# an XPASS is a red build, so pinning this would hand CI a coin flip — the
# opposite of what the harness is for, and worse than leaving it unpinned.
#
# What a real pin needs is a seam this code does not have: a hook between two
# slices of `sync_all`, so the teardown can be ordered against the sweep instead
# of raced with it. Whoever fixes the finding should add that seam and pin it
# then. Per docs/STAGES.md, "a constraint that weakens the tests deserves the
# same scrutiny as a finding" — this note is that constraint written down, not
# an excuse to skip it.


# ── AUDIT: desktop-release.yml grants contents: write to every job ──────────

def _contents_permission(perms) -> str | None:
    """GitHub's effective `contents` permission from a `permissions:` value."""
    if perms is None:
        return None
    if isinstance(perms, str):
        return {"write-all": "write", "read-all": "read"}.get(perms)
    return perms.get("contents")


# Every workflow that runs third-party install or build code. `ci.yml` is here
# because the finding names it — "ci.yml's separate `permissions` gap means the
# same npm postinstall reaches a token on every PR run too" — and a fix applied
# to desktop-release.yml alone leaves that gap wide open.
_WORKFLOWS = ("desktop-release.yml", "ci.yml")

_INSTALLS = re.compile(r"\bnpm (ci|install)\b|\bdotnet (publish|build|restore|test)\b")


def _third_party_jobs(wf: dict) -> dict[str, dict]:
    """The jobs whose steps run dependency code, found by what they RUN.

    By what they run rather than by name, because a job called `lint` that grew
    an `npm ci` is exactly as exposed as one called `build`.
    """
    out = {}
    for name, job in (wf.get("jobs") or {}).items():
        runs = " ".join(str(s.get("run") or "") for s in (job.get("steps") or []))
        if _INSTALLS.search(runs):
            out[name] = job
    return out


def test_the_build_jobs_hold_no_write_token():
    """`permissions: contents: write` is declared at workflow scope, so it
    applies to every job rather than to `release`, the only one that publishes.
    `actions/checkout@v4` defaults `persist-credentials: true` and writes
    `http.extraheader: AUTHORIZATION: basic <x-access-token:$GITHUB_TOKEN>` into
    `$GITHUB_WORKSPACE/.git/config`; the very next step in `web` is `npm ci`,
    which runs install lifecycle scripts for the whole dependency tree (216
    entries in frontend/package-lock.json, and no `.npmrc` sets ignore-scripts).
    `client` does the same through `dotnet publish` -> NuGet restore, with
    `Microsoft.Web.WebView2` floating on `1.0.*`.

    So one compromised transitive dev-dependency reads that config, decodes the
    header, and holds a token that can push to `main` — which the Pi autopulls
    on a one-minute cron — and replace `smylte-web.zip` on `desktop-latest`,
    which every installed desktop client downloads and executes on next launch
    with no signature or digest check (Updater.cs).

    **Structural of necessity, and the only pin here that is.** There is no
    harness that can execute a GitHub Actions workflow from this suite, so what
    it asserts is GitHub's own effective-permission rule — a job's own
    `permissions:` replaces the workflow's — applied to whichever jobs run
    third-party dependency code. Moving the grant onto `release`, or adding
    `permissions: contents: read` to the build jobs, both pass.

    WIDENED on two counts, both of which a fix could otherwise walk straight
    past:

    * **Both workflows.** This drove only `desktop-release.yml`, and the
      finding's evidence names `ci.yml` as carrying the same exposure on every
      PR run. Fixing one file passed.
    * **Silence is not a read grant.** `ci.yml` declares no `permissions:` at
      all, at either scope — so its token is whatever the REPOSITORY default
      happens to be, which this file cannot see and an admin can change without
      a commit. An undeclared permission therefore fails here rather than
      passing: the effective grant has to be written down in the workflow to be
      worth asserting at all. Without this the whole `ci.yml` half is vacuous,
      since `None != "write"` is true today.
    """
    # PyYAML rides in with uvicorn[standard]; skip rather than fake a pin if
    # it ever stops doing so — an ImportError is not this finding's failure.
    yaml = pytest.importorskip("yaml")

    checked: list[str] = []
    for filename in _WORKFLOWS:
        wf = yaml.safe_load(_read(f".github/workflows/{filename}"))
        top = wf.get("permissions")
        jobs = _third_party_jobs(wf)
        assert jobs, f"no job in {filename} installs dependencies any more?"

        for name, job in jobs.items():
            checked.append(f"{filename}:{name}")
            declared = job["permissions"] if "permissions" in job else top
            assert declared is not None, (
                f"job {name!r} in {filename} runs third-party install/build "
                f"code and declares no `permissions:` at either scope, so its "
                f"token is whatever the repository default is set to — a "
                f"setting no reviewer of this file can see"
            )
            assert _contents_permission(declared) != "write", (
                f"job {name!r} in {filename} runs third-party install/build "
                f"code with contents: write in scope — checkout leaves the "
                f"token in .git/config, so an npm postinstall can publish "
                f"releases"
            )
    assert len(checked) >= 4, f"only checked {checked}"


def test_the_release_job_can_still_publish():
    """Control, and the one that stops the fix going too far.

    `contents: write` is not gratuitous — `release` calls `gh release upload`
    and `gh release edit`, and without the grant the whole desktop update path
    silently stops shipping. A repair that set `contents: read` at workflow
    scope and moved nothing onto the job would satisfy the pin above completely
    while breaking every release, and nothing else in this suite would notice.

    Asserted through the same effective-permission rule, so it holds however the
    grant is spelled.
    """
    yaml = pytest.importorskip("yaml")
    wf = yaml.safe_load(_read(".github/workflows/desktop-release.yml"))
    release = (wf.get("jobs") or {}).get("release")
    assert release is not None, "the release job is gone"

    declared = release["permissions"] if "permissions" in release else wf.get("permissions")
    assert _contents_permission(declared) == "write", (
        "the release job cannot write contents, so `gh release upload` will "
        "403 and no desktop build can ever ship again"
    )
    # …and it must not have become a job that installs dependencies, which is
    # what would make the grant dangerous again.
    assert "release" not in _third_party_jobs(wf), (
        "the release job now runs dependency install code while holding "
        "contents: write — the finding, moved rather than fixed"
    )


# ── AUDIT: setup.sh writes the Radicale password unescaped ──────────────────

def _parse_systemd_env(text: str) -> dict[str, str]:
    """systemd's `EnvironmentFile=` parser, as a state machine.

    Mirrors `parse_env_file_internal` in systemd's src/basic/env-file.c, which
    is what actually reads /etc/tasks/tasks.env — NOT the shell. Three
    characters carry meaning there that a `KEY=value` heredoc does not account
    for: right after `=` a quote opens a quoted section, and a backslash escapes
    the next character and disappears. An unterminated quote is not an error: at
    EOF whatever accumulated is pushed, silently.
    """
    out: dict[str, str] = {}
    key = val = ""
    state = "ws"
    for c in text:
        if state == "ws":
            if c in "\n\r \t":
                continue
            if c == "#":
                state = "comment"
            else:
                key, state = c, "var"
        elif state == "comment":
            if c in "\n\r":
                state = "ws"
        elif state == "var":
            if c in "\n\r":
                key, state = "", "ws"
            elif c == "=":
                val, state = "", "pre"
            else:
                key += c
        elif state == "pre":                       # the char right after '='
            if c in "\n\r":
                out[key], state = "", "ws"
            elif c == "'":
                state = "sq"
            elif c == '"':
                state = "dq"
            elif c == "\\":
                state = "vesc"
            elif c in " \t":
                continue
            else:
                val, state = c, "value"
        elif state == "value":
            if c in "\n\r":
                out[key], state = val.rstrip(" \t"), "ws"
            elif c == "\\":
                state = "vesc"
            else:
                val += c
        elif state == "vesc":
            state = "value"
            if c not in "\n\r":                    # a newline is a continuation
                val += c
        elif state == "sq":
            state = "value" if c == "'" else ("sqesc" if c == "\\" else "sq")
            if state == "sq" and c not in ("'", "\\"):
                val += c
        elif state == "sqesc":
            val, state = val + c, "sq"
        elif state == "dq":
            state = "value" if c == '"' else ("dqesc" if c == "\\" else "dq")
            if state == "dq" and c not in ('"', "\\"):
                val += c
        elif state == "dqesc":
            val, state = val + c, "dq"
    if state in ("pre", "value", "vesc"):
        out[key] = val.rstrip(" \t")
    elif state in ("sq", "sqesc", "dq", "dqesc"):
        out[key] = val                             # unterminated quote, no error
    return out


def _run_setup_sh(password: str, root: pathlib.Path, *, username: str = "",
                  expect_refusal: bool = False) -> pathlib.Path | None:
    """Run deploy/setup.sh for real, answering its prompts, with every path it
    touches redirected into `root` and every system command stubbed.

    The script itself is unmodified apart from those redirections — the env file
    below is the one it writes, produced by whatever quoting it does, so a fix
    that adds a helper anywhere in the script is picked up automatically.
    """
    bin_dir, etc = root / "bin", root / "etc"
    bin_dir.mkdir(parents=True)
    (etc / "systemd").mkdir(parents=True)
    (root / "usrbin").mkdir()

    fake_py = root / "hash-password"
    fake_py.write_text("#!/bin/sh\necho 'scrypt$16384$8$1$fake$fake'\n")
    fake_py.chmod(0o755)

    stubs = {
        # `install -d` has to really make the directory; nothing else may run.
        "install": '#!/bin/sh\nfor a in "$@"; do last=$a; done\n'
                   'case " $* " in *" -d "*) mkdir -p "$last";; esac\nexit 0\n',
        "systemctl": "#!/bin/sh\nexit 0\n",
        "chown": "#!/bin/sh\nexit 0\n",
        "chmod": "#!/bin/sh\nexit 0\n",
        "id": "#!/bin/sh\necho 0\n",
        "sudo": '#!/bin/sh\nwhile [ "$1" = "-u" ]; do shift 2; done\nexec "$@"\n',
    }
    for name, body in stubs.items():
        p = bin_dir / name
        p.write_text(body)
        p.chmod(0o755)

    script = _read("deploy/setup.sh")
    script = re.sub(r"^PY=.*$", f"PY={fake_py}", script, flags=re.M)
    script = script.replace("/etc/tasks", str(etc / "tasks"))
    script = script.replace("/etc/systemd/system", str(etc / "systemd"))
    script = script.replace("/usr/local/bin", str(root / "usrbin"))
    script = script.replace("/home/$USER_NAME/tasks", str(REPO))
    sh = root / "setup.sh"
    sh.write_text(script)

    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    # stdin: the Radicale password, then the app username (empty takes the
    # default). `username` is driven because `TASKS_AUTH_USER` is the SECOND
    # value the heredoc interpolates from a prompt and carries exactly the same
    # exposure — a fix applied to the password alone leaves it open.
    proc = subprocess.run(["bash", str(sh)], input=f"{password}\n{username}\n",
                          text=True, capture_output=True, timeout=120, env=env)
    envfile = etc / "tasks" / "tasks.env"
    if expect_refusal:
        assert proc.returncode != 0, (
            f"setup.sh accepted input it should have refused (rc=0): "
            f"{proc.stdout[-400:]}"
        )
        assert not envfile.is_file(), (
            "setup.sh refused but wrote an env file anyway — re-running the "
            "script will now see it and leave the broken file in place"
        )
        return None
    assert proc.returncode == 0 and envfile.is_file(), (
        f"the sandboxed setup.sh did not write an env file (rc={proc.returncode}): "
        f"{proc.stdout[-400:]} {proc.stderr[-400:]}"
    )
    return envfile


def test_setup_sh_writes_a_password_systemd_reads_back_unchanged():
    """setup.sh interpolates `$RADPW`, read from an interactive prompt, straight
    into a `KEY=value` line of /etc/tasks/tasks.env. The bash side is safe — an
    expansion result is not rescanned — but systemd's `EnvironmentFile=` parser
    is not the shell, and it is the one that reads this file.

    Password `pi\\home2024` is stored as `pihome2024`: the service starts, the
    app logs in, and every CalDAV call 401s. The UI shows an empty account and
    "calendar server unavailable", and re-running setup.sh repairs nothing
    because it sees an existing env file and leaves it alone.

    A password that BEGINS with a quote is worse. `"tunnel-otter-9` puts the
    parser into DOUBLE_QUOTE_VALUE at the first character of the value and it
    swallows the remaining lines of the file into that one value — no error, no
    warning — so TASKS_AUTH_PASSWORD_HASH, TASKS_SESSION_SECRET and
    TASKS_HOOK_SECRET are never set at all and the app refuses to start.

    The script already reasons about this file being corrupted by a bad prompt
    (it guards `$HASH` for exactly that), so the gap is in which values got the
    care, not in whether anyone thought about it.

    This runs the real script and parses the real file it writes, so it does not
    care HOW the values are quoted — only that systemd hands back what was
    typed.
    """
    # WIDENED to drive `TASKS_AUTH_USER` as well. The heredoc interpolates TWO
    # prompt-read values and the finding names both; escaping only the password
    # leaves the username carrying the identical defect, and the username is the
    # one an installer is more likely to paste something odd into.
    hostile = {
        "backslash": r"pi\home2024",
        "leading double quote": '"tunnel-otter-9',
        "leading single quote": "'otter-tunnel-9",
        "trailing backslash": "otter2024\\",
        "embedded double quote": 'ott"er-9',
    }
    for label, password in hostile.items():
        root = pathlib.Path(tempfile.mkdtemp(prefix="aug19-setup-"))
        # The same hostile string in the username slot, so one loop drives both
        # interpolations and a one-sided repair cannot pass.
        user = f"ni{password}ck".replace("\n", "")
        try:
            envfile = _run_setup_sh(password, root, username=user)
            parsed = _parse_systemd_env(envfile.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(root, ignore_errors=True)

        assert parsed.get("RADICALE_PASSWORD") == password, (
            f"{label}: systemd reads RADICALE_PASSWORD as "
            f"{parsed.get('RADICALE_PASSWORD')!r}, not the password that was "
            f"typed ({password!r}) — every CalDAV call would 401"
        )
        assert parsed.get("TASKS_AUTH_USER") == user, (
            f"{label}: systemd reads TASKS_AUTH_USER as "
            f"{parsed.get('TASKS_AUTH_USER')!r}, not the username that was "
            f"typed ({user!r}) — nobody can log in to the app at all"
        )
        for key in ("TASKS_AUTH_PASSWORD_HASH", "TASKS_SESSION_SECRET",
                    "TASKS_HOOK_SECRET"):
            assert parsed.get(key), (
                f"{label}: {key} is missing from the parsed env file — the "
                f"password swallowed the rest of it"
            )


def test_setup_sh_refuses_an_empty_radicale_password():
    """The finding's third failure scenario, and the one no amount of quoting
    fixes: pressing Enter at the password prompt writes `RADICALE_PASSWORD=`
    and the install is permanently 401 against Radicale.

    `$HASH` two lines above already gets this exact guard, with a comment
    explaining why — "a mismatched/aborted prompt would write an empty
    TASKS_AUTH_PASSWORD_HASH and the service would refuse to start". `$RADPW`
    got none, and its failure is quieter: the service starts fine and every
    CalDAV call fails.

    Refusing has to mean writing NO file. Line 20 short-circuits on an existing
    env file — "leaving it untouched (delete it to regenerate)" — so a refusal
    that still wrote something would make re-running the script a no-op, which
    is the trap the whole finding is about.
    """
    root = pathlib.Path(tempfile.mkdtemp(prefix="aug19-setup-empty-"))
    try:
        _run_setup_sh("", root, expect_refusal=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_setup_sh_still_writes_an_ordinary_install_unchanged():
    """Control, and the one that stops the fix going too far.

    The over-correction that matters here is the GUARD, not the quoting. A
    `[ -n "$RADPW" ]` where `[ -z ... ]` was meant refuses every valid password
    and accepts the empty one — an installer that cannot install, which is worse
    than the bug. Verified: that inversion fails this test and the empty-password
    test together.

    The quoting is harder to overdo than it looks, and this control deliberately
    does not claim otherwise. systemd STRIPS the surrounding quotes by design, so
    both `"hunter2"` and `'hunter2'` read back as `hunter2` — neither spelling is
    a defect on an ordinary value, and only the escaping inside them decides
    whether a hostile one survives. That is the pin's job, not this one's.
    Single-quoting without escaping, for instance, passes here and is caught
    above by the leading-single-quote case.

    So what this asserts is the narrow thing it can: an ordinary password and an
    ordinary username round-trip byte-for-byte, and every other key in the file
    — none of which the fix should have touched — still parses.
    """
    root = pathlib.Path(tempfile.mkdtemp(prefix="aug19-setup-ok-"))
    try:
        envfile = _run_setup_sh("hunter2", root, username="nick")
        parsed = _parse_systemd_env(envfile.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    assert parsed.get("RADICALE_PASSWORD") == "hunter2", (
        f"an ordinary password did not survive: "
        f"{parsed.get('RADICALE_PASSWORD')!r}"
    )
    assert parsed.get("TASKS_AUTH_USER") == "nick", (
        f"an ordinary username did not survive: {parsed.get('TASKS_AUTH_USER')!r}"
    )
    # The rest of the file is untouched by the fix and must stay that way.
    assert parsed.get("RADICALE_URL") == "http://127.0.0.1:5232"
    assert parsed.get("TASKS_AUTH_ENABLED") == "true"
    assert parsed.get("TASKS_SESSION_TTL") == "604800"
    assert parsed.get("TASKS_COOKIE_SECURE") == "true"
    for key in ("TASKS_AUTH_PASSWORD_HASH", "TASKS_SESSION_SECRET",
                "TASKS_HOOK_SECRET", "TASKS_DB", "TASKS_STATIC"):
        assert parsed.get(key), f"{key} is missing from an ordinary install"


# ── AUDIT (test gap): the confidential-client path has no coverage ──────────

def test_a_confidential_client_authenticates_with_its_secret_and_only_that(oauth_app):
    """Closing a test gap, and it turned out to be a gap in coverage only: the
    behaviour below is already correct, so this is an ordinary test with no
    xfail marker — the same shape test_backlog_stage5.py uses for a gap that hid
    nothing.

    `authorization_server_metadata` advertises `client_secret_post` and
    `client_secret_basic` at the token and revocation endpoints, so a client
    reading the metadata may pick either — but every existing test registers
    `token_endpoint_auth_method: "none"` and sends nothing but a client_id.
    `_basic_auth`'s base64/`split(":", 1)`/`unquote` decoding, the
    `client_secret_hash` branch of `_authenticate_client` and `register`'s
    secret minting were exercised by nothing at all. That is the credential
    check on an internet-facing token endpoint: an inverted branch, a
    `secret or ''`, or `_basic_auth` returning None where it should refuse would
    all have been silent.

    Pinned as five outcomes, which is what a regression would have to break:
    the right secret works over Basic and over the form, a wrong secret and a
    missing secret are both 401 invalid_client, and a public client is still
    allowed to send the empty `client_secret=` that real clients send while a
    non-empty one is refused.
    """
    def _basic(client_id: str, secret: str) -> dict[str, str]:
        raw = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
        return {"Authorization": f"Basic {raw}"}

    def _exchange(reg, *, headers=None, **form_over):
        verifier, challenge = _pkce()
        code = _approve(oauth_app, reg, challenge)
        form = {"grant_type": "authorization_code", "code": code,
                "redirect_uri": CALLBACK, "client_id": reg["client_id"],
                "code_verifier": verifier, "resource": MCP_URL}
        form.update(form_over)
        form = {k: v for k, v in form.items() if v is not None}
        return oauth_app.post("/oauth/token", data=form, headers=headers or {})

    # -- client_secret_basic --
    conf = _register(oauth_app, token_endpoint_auth_method="client_secret_basic")
    secret = conf.get("client_secret")
    assert secret, "a confidential registration must return a secret exactly once"
    assert conf["token_endpoint_auth_method"] == "client_secret_basic"

    ok = _exchange(conf, headers=_basic(conf["client_id"], secret), client_id=None)
    assert ok.status_code == 200, ok.text
    assert ok.json()["access_token"]

    bad = _exchange(conf, headers=_basic(conf["client_id"], "nope"), client_id=None)
    assert bad.status_code == 401, bad.text
    assert bad.json()["error"] == "invalid_client"

    # A confidential client that presents no credential at all is not the same
    # as a public one, and must not be treated as one.
    naked = _exchange(conf)
    assert naked.status_code == 401, naked.text
    assert naked.json()["error"] == "invalid_client"

    # -- client_secret_post --
    post_client = _register(oauth_app, token_endpoint_auth_method="client_secret_post")
    posted = _exchange(post_client, client_secret=post_client["client_secret"])
    assert posted.status_code == 200, posted.text
    assert posted.json()["access_token"]

    wrong = _exchange(post_client, client_secret="nope")
    assert wrong.status_code == 401 and wrong.json()["error"] == "invalid_client"

    # -- public clients --
    public = _register(oauth_app)
    assert "client_secret" not in public
    blank = _exchange(public, client_secret="")
    assert blank.status_code == 200, (
        "a public client sending an empty client_secret — which real clients do "
        f"— must still be able to exchange its code: {blank.text}"
    )
    impostor = _exchange(public, client_secret="invented")
    assert impostor.status_code == 401, impostor.text
    assert impostor.json()["error"] == "invalid_client"


# ── AUDIT (test gap): busy_intervals is never driven across a DST change ────

def _ev(**kw) -> dict:
    base = {"start": None, "end": None, "duration": None, "status": None,
            "start_is_date": False, "all_day": False}
    base.update(kw)
    return base


def _abs(dt):
    return dt.astimezone(timezone.utc)


def test_busy_intervals_hold_their_absolute_length_across_a_dst_change():
    """The DST battery in test_scheduling.py covers slot GENERATION four ways,
    but every DST fixture in that file is an `Interval` built by hand, so
    `busy_intervals` — the function that turns untrusted foreign iCalendar into
    the conflict set behind the only unauthenticated write path in the app — is
    only ever driven on 2026-07-13, an ordinary July Monday. The one busy
    fixture on a transition day sits entirely inside the first pass of the
    repeated hour and never crosses 07:00Z.

    Writing the missing cases found two live defects, which is why this one
    keeps its marker:

    * **The `end > start` guard** (scheduling.py:148) compares two datetimes
      that share one ZoneInfo object, and CPython compares those on their naive
      fields — the property `_u` exists in this very module to prevent. A real
      06:30Z-07:00Z event on 2026-11-01 is 01:30 CDT to 01:00 CST, so the guard
      reads it as ending before it starts and drops it. The owner's appointment
      vanishes from the busy set and an anonymous visitor can book over it.
    * **The DURATION branch** (scheduling.py:145) adds the timedelta to the
      aware start, which adds to the naive fields and re-derives the offset, so
      a PT2H commitment starting 07:30Z on 2026-03-08 comes back an hour short.

    Asserted as absolute (UTC) length, not as wall-clock endpoints, so any fix
    that keeps the real duration passes.

    **Closed by the Stage 3 fixes for those two defects** (findings 18 and 29),
    not by a change of its own — which is the point of a test-gap finding: the
    gap is shut when the case exists AND passes. Worth noting that the stage
    boundaries were not watertight here. This was filed as a Stage 5 test gap
    and the two defects it uncovered were filed as Stage 3 bugs; they are one
    piece of work, and it was the missing test that found them.
    """
    fall_back = scheduling.busy_intervals(
        [_ev(start="2026-11-01T06:30:00+00:00", end="2026-11-01T07:00:00+00:00")], TZ)
    assert len(fall_back) == 1, (
        "a real 30-minute event spanning the fall-back transition disappeared "
        f"from the busy set: {fall_back!r}"
    )
    assert _abs(fall_back[0].end) - _abs(fall_back[0].start) == timedelta(minutes=30)

    spring_forward = scheduling.busy_intervals(
        [_ev(start="2026-03-08T07:30:00+00:00", duration="PT2H")], TZ)
    assert len(spring_forward) == 1, spring_forward
    assert _abs(spring_forward[0].end) - _abs(spring_forward[0].start) == timedelta(hours=2), (
        "a DURATION event spanning the spring-forward transition came back "
        f"{_abs(spring_forward[0].end) - _abs(spring_forward[0].start)} long, "
        "not the PT2H the calendar says"
    )


# ── AUDIT (test gap): nothing observes a 204 beyond its status code ─────────

def _drive_asgi(app, method: str, path: str, cookies) -> list[dict]:
    """One request straight into the ASGI app, capturing what it sends.

    TestClient bypasses the protocol layer — which is precisely why app.py's own
    comment says "the suite is green either way" — so the messages the app emits
    are collected here rather than inferred from an httpx Response.
    """
    cookie = "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "client": ("127.0.0.1", 4321), "server": ("testserver", 80),
        "headers": [(b"host", b"testserver"), (b"cookie", cookie)],
    }
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


@pytest.mark.radicale
def test_a_204_delete_carries_no_body_and_no_content_type(client):
    """Closing a test gap, and the behaviour is already right — so this carries
    no marker and must stay green.

    docs/AUDIT.md closed "every DELETE route sends a body on a 204", and the fix
    is `return Response(status_code=204)`. The comment above it says outright
    that "TestClient bypasses the protocol layer, which is why the suite is
    green either way", and that is exactly true: all eleven 204 assertions in
    the suite check `status_code == 204` and nothing else, so the fix has been
    guarded by a comment. Revert that line to `return None` and every test still
    passes while the response grows a `content-type: application/json` on a
    bodiless status — and, on the FastAPI/Starlette version the finding was
    filed against, a `null` body, which is what tore down the keep-alive socket
    on every delete. requirements.txt pins only `fastapi>=0.115`, so which
    serialization a 204 gets is decided by whatever pip resolves that day.

    Asserted twice over: through TestClient, and by driving the ASGI app
    directly so the `http.response.start` message itself is examined — the blind
    spot the source comment names.
    """
    lid = client.post("/api/lists", json={"name": f"L-{uuid.uuid4().hex[:8]}"}).json()["id"]
    doomed = client.post(f"/api/lists/{lid}/tasks", json={"summary": "delete me"}).json()

    r = client.delete(f"/api/lists/{lid}/tasks/{doomed['uid']}")
    assert r.status_code == 204
    assert r.content == b"", f"a 204 carried a body: {r.content!r}"
    assert "content-type" not in r.headers, (
        f"a 204 declared a content type: {r.headers.get('content-type')!r}")
    assert "content-length" not in r.headers

    # ...and at the protocol layer, where the damage actually happened.
    second = client.post(f"/api/lists/{lid}/tasks", json={"summary": "delete me too"}).json()
    sent = _drive_asgi(client.app, "DELETE",
                       f"/api/lists/{lid}/tasks/{second['uid']}", client.cookies)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert start["status"] == 204, (start, body)
    assert body == b"", f"the ASGI app sent a body with its 204: {body!r}"
    assert "content-type" not in headers, headers
    assert "content-length" not in headers, headers

    client.delete(f"/api/lists/{lid}")


# ── AUDIT (test gap): the won't-do write path is exercised by nothing ───────

@pytest.mark.radicale
def test_cancelling_a_task_is_wont_do_and_not_done(client):
    """Closing a test gap; the behaviour is already correct, so no marker.

    `POST /api/lists/{id}/tasks/{uid}/cancel` and `TaskService.cancel_task`
    write `STATUS:CANCELLED`, and nothing called either. The only thing that
    looked like coverage was the comment `# complete + won't-do` in
    test_api.py, above a block that exercises `/complete` and
    `/complete?done=false` and nothing else — the comment was the entire reason
    the path read as covered.

    `cancelled` is a first-class field of the Task DTO that
    `list_tasks(include_done=False)` filters on and that the SPA's
    "View completed" pane keys off, yet no test ever produced a task carrying
    it. Change `cancel_task` to write COMPLETED, or drop `d["cancelled"]` from
    that filter, and the whole suite stays green while "won't do" becomes
    indistinguishable from "done" to every other CalDAV client — or a cancelled
    task never leaves the open list.
    """
    lid = client.post("/api/lists", json={"name": f"L-{uuid.uuid4().hex[:8]}"}).json()["id"]
    t = client.post(f"/api/lists/{lid}/tasks", json={"summary": "skip it"}).json()

    r = client.post(f"/api/lists/{lid}/tasks/{t['uid']}/cancel")
    assert r.status_code == 200, r.text
    cancelled = r.json()
    assert cancelled["cancelled"] is True and cancelled["completed"] is False
    assert cancelled["status"] == "CANCELLED"

    open_uids = {x["uid"] for x in client.get(
        f"/api/lists/{lid}/tasks", params={"include_done": False}).json()}
    assert t["uid"] not in open_uids, "a won't-do task is still in the open list"
    all_uids = {x["uid"] for x in client.get(f"/api/lists/{lid}/tasks").json()}
    assert t["uid"] in all_uids, "a won't-do task must be kept for the record"

    assert client.post(f"/api/lists/{lid}/tasks/no-such-uid/cancel").status_code == 404

    client.delete(f"/api/lists/{lid}")


@pytest.mark.radicale
def test_the_cancel_tool_needs_write_access_and_marks_the_task_wont_do(_scratch_up, tmp_path):
    """The connector half of the same gap: `smylte_cancel_task` is called by no
    test either, including — like every write tool — the question of whether a
    read-only grant can reach it. Also already correct, so no marker.
    """
    settings = dataclasses.replace(
        api_settings(str(tmp_path / "cancel-mcp.db")), mcp_enabled=True, public_url=ISSUER)
    with TestClient(create_app(settings)) as mcp:
        def _token_for(scope: str) -> str:
            reg = _register(mcp)
            verifier, challenge = _pkce()
            code = _approve(mcp, reg, challenge, scope=scope)
            r = mcp.post("/oauth/token", data={
                "grant_type": "authorization_code", "code": code,
                "redirect_uri": CALLBACK, "client_id": reg["client_id"],
                "code_verifier": verifier, "resource": MCP_URL})
            assert r.status_code == 200, r.text
            return r.json()["access_token"]

        def _rpc(token: str, name: str, args: dict) -> dict:
            r = mcp.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                       "params": {"name": name, "arguments": args}},
                         headers={"Authorization": f"Bearer {token}",
                                  "MCP-Protocol-Version": "2025-06-18"})
            assert r.status_code == 200, r.text
            return r.json()

        def _ok(token: str, name: str, args: dict) -> dict:
            out = _rpc(token, name, args)
            assert "error" not in out, out
            assert out["result"]["isError"] is False, out["result"]
            return out["result"]["structuredContent"]

        write = _token_for("mcp:read mcp:write")
        read_only = _token_for("mcp:read")

        list_id = _ok(write, "smylte_create_list", {"name": f"L-{uuid.uuid4().hex[:8]}"})["id"]
        try:
            uid = _ok(write, "smylte_create_task",
                      {"list_id": list_id, "summary": "skip it"})["uid"]

            # A refusal may be a JSON-RPC error (the call could not be made) or
            # a result carrying isError (it was made and did not work) — either
            # is a refusal; what matters is that the task is untouched.
            refused = _rpc(read_only, "smylte_cancel_task",
                           {"list_id": list_id, "uid": uid})
            declined = ("error" in refused
                        or refused["result"].get("isError") is True)
            assert declined, f"a read-only connection cancelled a task: {refused}"
            still_open = _ok(read_only, "smylte_get_task",
                             {"list_id": list_id, "uid": uid})
            assert still_open["cancelled"] is False

            done = _ok(write, "smylte_cancel_task", {"list_id": list_id, "uid": uid})
            assert done["cancelled"] is True and done["completed"] is False
            assert done["status"] == "CANCELLED"
        finally:
            _ok(write, "smylte_delete_list", {"list_id": list_id})
