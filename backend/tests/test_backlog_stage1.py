"""Stage 1 of the audit backlog: crash paths.

Untrusted input reaching an unhandled exception. These share one shape — a value
an adversary (or merely an odd foreign CalDAV client) controls reaches an
exception type that is outside the taxonomy the handlers were built around, so
it escapes as a 500 instead of the 400/422 the caller could act on.

HOW THESE TESTS WORK. Each one asserts the CORRECT behaviour and is marked
`xfail(strict=True)`, so:

  * while the bug is open  -> the test fails -> xfail -> CI stays green;
  * the moment it is fixed -> the test passes -> XPASS -> strict xfail FAILS the
    build, so nobody can fix a finding without being told to tick it off in
    docs/AUDIT.md and drop the marker.

That is the point of the harness: the backlog is executable, and it cannot go
stale in either direction. Run just this stage with `pytest -m stage1`.

Each test names its finding so it can be traced back to docs/AUDIT.md.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from tasksd.dav import xml as X
from tasksd.dav.errors import DavError
from tasksd.ical.edit import _at_or_after
from tasksd.mcp import oauth as O
from tasksd.mcp.server import parse_body

pytestmark = [pytest.mark.backlog, pytest.mark.stage1]

XFAIL = dict(strict=True)


# ── AUDIT: hmac.compare_digest on attacker-controlled redirect_uri ──────────

@pytest.mark.xfail(reason="AUDIT open: oauth.py:606 non-ASCII redirect_uri", **XFAIL)
def test_a_non_ascii_redirect_uri_is_refused_not_a_crash():
    """`hmac.compare_digest` refuses non-ASCII str outright. The redirect_uri is
    attacker-chosen and reaches it on the unauthenticated /oauth/authorize path,
    so one non-ASCII byte is an uncaught TypeError -> 500 rather than the
    "redirect_uri is not registered" the client should get."""
    try:
        allowed = O._redirect_allowed("https://exämple.test/cb",
                                      ["https://example.test/cb"])
    except TypeError as exc:                       # the bug, today
        pytest.fail(f"non-ASCII redirect_uri raised instead of being refused: {exc}")
    assert allowed is False


# ── AUDIT: non-string `scope` in dynamic client registration ────────────────

@pytest.mark.xfail(reason="AUDIT open: oauth.py:207 non-string scope", **XFAIL)
def test_a_non_string_scope_in_registration_is_a_400_not_a_500():
    """/oauth/register is open by design (the MCP spec wants zero-setup connect),
    so its body is wholly attacker-controlled. `scope_set` calls `.split()` on
    whatever arrives; a JSON list or number is an AttributeError, not the
    OAuthError the route knows how to render."""
    from tasksd.db import store

    conn = store.connect(":memory:")
    store.init_db(conn)
    srv = O.OAuthServer(issuer="https://t.test", mcp_url="https://t.test/mcp",
                        secret="s" * 40, verify_password=lambda u, p: False)

    for bad in ([{"scope": ["mcp:read"]}, {"scope": 7}, {"scope": {"a": 1}}]):
        body = {"redirect_uris": ["https://c.test/cb"], **bad}
        with pytest.raises(O.OAuthError):
            srv.register(conn, body)


# ── AUDIT: deeply nested JSON at POST /mcp ─────────────────────────────────

@pytest.mark.xfail(reason="AUDIT open: routes.py:405 RecursionError on nested JSON", **XFAIL)
def test_deeply_nested_json_is_a_parse_error_not_a_recursion_crash():
    """The transport guards `parse_body` with `except (ValueError,
    UnicodeDecodeError)` and answers -32700. `json.loads` raises RecursionError
    on deep nesting, which is neither, so a bearer-holding client turns a 1 MB
    body into a 500."""
    raw = (b"[" * 100_000) + (b"]" * 100_000)
    with pytest.raises((ValueError, UnicodeDecodeError)):
        parse_body(raw)


# ── AUDIT: collection-name schemas omit the control-character guard ─────────

@pytest.mark.xfail(reason="AUDIT open: tools.py:174 no control-char guard", **XFAIL)
def test_mcp_collection_name_schemas_reject_control_characters():
    """The HTTP model bounds this with a pattern (app.py `CollectionName`)
    precisely because a control byte reaches lxml and raises a bare ValueError
    deep in the DAV client. The MCP tool schemas describe the same field and
    carry no such guard, so the same byte answers "the calendar server may be
    unreachable"."""
    from tasksd.mcp.tools import build_tools

    tools = build_tools(object())
    named = [t for t in tools.values()
             if "name" in (t.schema.get("properties") or {})]
    assert named, "no tool takes a collection name — has the table been renamed?"

    for t in named:
        pattern = (t.schema["properties"]["name"] or {}).get("pattern")
        assert pattern, f"{t.name}: collection name has no pattern bound"
        import re as _re
        assert not _re.match(pattern, "List\x0b"), (
            f"{t.name}: pattern {pattern!r} admits a vertical-tab control char"
        )


# ── AUDIT: smylte_find_free_time on the last representable day ─────────────

@pytest.mark.xfail(reason="AUDIT open: api.py:481 OverflowError at date.max", **XFAIL)
def test_find_free_time_at_the_end_of_time_is_an_error_not_an_overflow():
    """The day cursor advances with `day += timedelta(days=1)` while the loop
    condition tests the *combined* datetime, so a range whose end falls inside
    the last representable day steps past `date.max` and raises OverflowError —
    outside every handler, from an argument the calling model chooses.

    Driven through the real method with the event lookup stubbed out, so the day
    cursor is the only thing under test.
    """
    from tasksd.mcp.api import McpApi, ToolError

    api = McpApi(object())
    api.list_events = lambda *a, **kw: []

    try:
        api.find_free_time("9999-12-30", "9999-12-31T23:59")
    except ToolError:
        pass                       # a clean, actionable refusal is fine
    except OverflowError as exc:
        pytest.fail(f"the day cursor walked off date.max unguarded: {exc}")


# ── AUDIT: _at_or_after compares aware against naive ───────────────────────

@pytest.mark.xfail(reason="AUDIT open: edit.py:534 aware/naive comparison", **XFAIL)
@pytest.mark.parametrize("a, anchor", [
    (datetime(2026, 1, 1, 9, 0), datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)),
    (datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc), datetime(2026, 1, 1, 9, 0)),
])
def test_splitting_a_series_survives_a_floating_date_list_entry(a, anchor):
    """`_as_utc` returns a naive datetime unchanged, so one floating (TZID-less)
    EXDATE / RDATE / RECURRENCE-ID makes every "this and following" edit or
    delete a 500. The sibling `_same_instant` already carries the awareness
    guard (edit.py:511-515); this one does not — and a floating entry is exactly
    what a foreign CalDAV client writes."""
    assert isinstance(_at_or_after(a, anchor), bool)


# ── AUDIT: the XML backstop misses lone surrogates and U+FFFE/U+FFFF ───────

@pytest.mark.xfail(reason="AUDIT open: xml.py:127 incomplete XML guard", **XFAIL)
@pytest.mark.parametrize("label, ch", [
    ("lone surrogate", "\ud800"),
    ("U+FFFE", "￾"),
    ("U+FFFF", "￿"),
])
def test_every_xml_incompatible_character_raises_a_DavError(label, ch):
    """`_XML_FORBIDDEN` covers the C0 controls but not the other codepoints XML
    cannot carry. Those reach lxml, which raises UnicodeEncodeError or a bare
    ValueError — neither in the DAV taxonomy — so a list name renamed by another
    client is an unhandled 500 instead of a clean DavError."""
    with pytest.raises(DavError):
        X.build_proppatch({X.DISPLAYNAME: f"List{ch}"})
