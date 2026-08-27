"""Stage 1 of the audit backlog: crash paths.

Untrusted input reaching an unhandled exception. These share one shape — a value
an adversary (or merely an odd foreign CalDAV client) controls reaches an
exception type that is outside the taxonomy the handlers were built around, so
it escapes as a 500 instead of the 400/422 the caller could act on.

**Stage 1 is CLOSED.** These began as `xfail(strict=True)` pins, each failing
against the code as it stood. The seven findings are fixed and ticked in
docs/AUDIT.md, so the markers are gone and these are now ordinary regression
tests: they must stay green.

The docstrings deliberately keep the past tense and the original evidence — a
closed finding's value is the record of what the bug was and why it mattered, and
that is what stops it being reintroduced. Run just this stage with
`pytest -m stage1`.

The harness itself is described in docs/STAGES.md; the still-open stages use the
same shape.
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

# ── AUDIT: hmac.compare_digest on attacker-controlled redirect_uri ──────────

def test_a_non_ascii_redirect_uri_is_refused_not_a_crash():
    """`hmac.compare_digest` refuses non-ASCII str outright. The redirect_uri is
    attacker-chosen and reaches it on the unauthenticated /oauth/authorize path,
    so one non-ASCII byte WAS an uncaught TypeError -> 500 rather than the
    "redirect_uri is not registered" the client should get. Fixed by comparing
    bytes, the pattern auth.py:204 and app.py:1316 already used."""
    try:
        allowed = O._redirect_allowed("https://exämple.test/cb",
                                      ["https://example.test/cb"])
    except TypeError as exc:
        pytest.fail(f"non-ASCII redirect_uri raised instead of being refused: {exc}")
    assert allowed is False


# ── AUDIT: non-string `scope` in dynamic client registration ────────────────

def test_a_non_string_scope_in_registration_is_a_400_not_a_500():
    """/oauth/register is open by design (the MCP spec wants zero-setup connect),
    so its body is wholly attacker-controlled. `scope_set` calls `.split()` on
    whatever arrives; a JSON list or number WAS an AttributeError, not the
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

def test_deeply_nested_json_is_a_parse_error_not_a_recursion_crash():
    """The transport guards `parse_body` with `except (ValueError,
    UnicodeDecodeError)` and answers -32700. `json.loads` raises RecursionError
    on deep nesting, which is neither, so a bearer-holding client turned a 1 MB
    body into a 500. `parse_body` now normalises it to ValueError."""
    raw = (b"[" * 100_000) + (b"]" * 100_000)
    with pytest.raises((ValueError, UnicodeDecodeError)):
        parse_body(raw)


# ── AUDIT: collection-name schemas omit the control-character guard ─────────

def test_mcp_collection_name_schemas_reject_control_characters():
    """The HTTP model bounds this with a pattern (app.py `CollectionName`)
    precisely because a control byte reaches lxml and raises a bare ValueError
    deep in the DAV client. The MCP tool schemas described the same field and
    carried no such guard, so the same byte answered "the calendar server may be
    unreachable". Both now share `XML_SAFE_PATTERN` from dav/xml.py."""
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

def test_find_free_time_at_the_end_of_time_is_an_error_not_an_overflow():
    """The day cursor advances with `day += timedelta(days=1)` while the loop
    condition tests the *combined* datetime, so a range whose end fell inside
    the last representable day stepped past `date.max` and raised OverflowError —
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

_NAIVE_9 = datetime(2026, 1, 1, 9, 0)
_AWARE_9 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
_NAIVE_8 = datetime(2026, 1, 1, 8, 0)
_AWARE_8 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("a, anchor, expected", [
    # The original crash: one side floating, one side aware, equal wall clock.
    (_NAIVE_9, _AWARE_9, True),
    (_AWARE_9, _NAIVE_9, True),
    # ... and the same mix where the ORDERING is what is being asked, in both
    # directions. Without these the pin passed on a branch returning a constant.
    (_NAIVE_8, _AWARE_9, False),
    (_NAIVE_9, _AWARE_8, True),
    (_AWARE_8, _NAIVE_9, False),
    (_AWARE_9, _NAIVE_8, True),
    # Same-awareness pairs, so a "fix" that only ever answers the mixed case
    # cannot pass either.
    (_AWARE_8, _AWARE_9, False),
    (_NAIVE_9, _NAIVE_8, True),
])
def test_splitting_a_series_survives_a_floating_date_list_entry(a, anchor, expected):
    """`_as_utc` returns a naive datetime unchanged, so one floating (TZID-less)
    EXDATE / RDATE / RECURRENCE-ID made every "this and following" edit or
    delete a 500 — and a floating entry is exactly what a foreign CalDAV client
    writes. Fixed by mirroring the awareness guard the sibling `_same_instant`
    already carried.

    The ANSWER is asserted, not the type. `isinstance(..., bool)` did catch the
    original TypeError, but it accepted any boolean, and both original cases were
    the equal-instant one — so a later "we cannot compare these" tidy-up
    returning a constant `False` would have passed. That value decides where a
    series is cut: it gates `_drop_overrides` and the slot walk in
    `ical/edit.py`, so getting it wrong leaves an EXDATE on the head and strips
    it from the tail, silently resurrecting a deleted occurrence in every
    instance of the new series."""
    assert _at_or_after(a, anchor) is expected


# ── AUDIT: the XML backstop misses lone surrogates and U+FFFE/U+FFFF ───────

@pytest.mark.parametrize("label, ch", [
    ("lone surrogate", "\ud800"),
    ("U+FFFE", "￾"),
    ("U+FFFF", "￿"),
])
def test_every_xml_incompatible_character_raises_a_DavError(label, ch):
    """`_XML_FORBIDDEN` covers the C0 controls but not the other codepoints XML
    cannot carry. Those reached lxml, which raises UnicodeEncodeError or a bare
    ValueError — neither in the DAV taxonomy — so a list name renamed by another
    client was an unhandled 500 instead of a clean DavError."""
    with pytest.raises(DavError):
        X.build_proppatch({X.DISPLAYNAME: f"List{ch}"})
