"""`parse_multistatus` — the one place untrusted wire XML becomes app state.

Audit finding: every sync path funnels through this function (`list_collections`,
`list_etags`, `multiget`, `sync_collection`, `proppatch` all call it), it decides
what counts as a deletion, and nothing tested it directly. The builders on the
other side of the file are covered by the round-trip tests in `test_sync.py`;
the *parser* was covered only by servers behaving well.

Nothing here needs Radicale. These are bytes in, dataclasses out.
"""
from __future__ import annotations

import pytest

from tasksd.dav import xml as X
from tasksd.dav.errors import DavError


def ms(body: str) -> bytes:
    """A multistatus document with the usual namespace declarations."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"'
        ' xmlns:cs="http://calendarserver.org/ns/"'
        ' xmlns:i="http://apple.com/ns/ical/">'
        f'{body}'
        '</d:multistatus>'
    ).encode()


# ── the ordinary case ──────────────────────────────────────────────────────

def test_a_normal_207_yields_hrefs_and_properties():
    parsed = X.parse_multistatus(ms(
        '<d:response>'
        '  <d:href>/dav/user/work/</d:href>'
        '  <d:propstat>'
        '    <d:prop>'
        '      <d:displayname>Work</d:displayname>'
        '      <d:resourcetype><d:collection/><c:calendar/></d:resourcetype>'
        '      <i:calendar-color>#D9480F</i:calendar-color>'
        '    </d:prop>'
        '    <d:status>HTTP/1.1 200 OK</d:status>'
        '  </d:propstat>'
        '</d:response>'
    ))

    assert len(parsed.responses) == 1
    r = parsed.responses[0]
    assert r.href == "/dav/user/work/"
    assert r.status is None                     # no response-level <status>
    assert r.text(X.DISPLAYNAME) == "Work"
    assert r.text(X.CALENDAR_COLOR) == "#D9480F"
    assert r.prop(X.RESOURCETYPE) is not None
    assert r.prop(X.RESOURCETYPE).find(X.CALENDAR) is not None
    assert not r.is_removed


def test_the_sync_token_is_read_off_the_root():
    parsed = X.parse_multistatus(ms('<d:sync-token>http://example.test/ns/sync/42</d:sync-token>'))
    assert parsed.sync_token == "http://example.test/ns/sync/42"
    assert parsed.responses == []


def test_an_empty_multistatus_is_not_an_error():
    # An up-to-date sync-collection REPORT looks exactly like this, and it has to
    # parse rather than throw — otherwise a quiet account breaks the sync loop.
    parsed = X.parse_multistatus(ms(""))
    assert parsed.responses == []
    assert parsed.sync_token is None


# ── the non-200 propstat, which is how servers say "not this one" ──────────

def test_a_property_in_a_404_propstat_is_not_readable():
    # The RFC 4918 shape for "I have this resource but not that property".
    # Reading it anyway would let a 404'd value through as if the server had
    # answered it — `prop()` filtering on 2xx is the whole guard.
    parsed = X.parse_multistatus(ms(
        '<d:response>'
        '  <d:href>/dav/user/work/a.ics</d:href>'
        '  <d:propstat>'
        '    <d:prop><d:getetag>"abc"</d:getetag></d:prop>'
        '    <d:status>HTTP/1.1 200 OK</d:status>'
        '  </d:propstat>'
        '  <d:propstat>'
        '    <d:prop><c:calendar-data/></d:prop>'
        '    <d:status>HTTP/1.1 404 Not Found</d:status>'
        '  </d:propstat>'
        '</d:response>'
    ))

    r = parsed.responses[0]
    assert r.text(X.GETETAG) == '"abc"'         # the 200 half is readable
    assert r.prop(X.CALENDAR_DATA) is None      # the 404 half is not
    assert [ps.status for ps in r.propstats] == [200, 404]


def test_a_404_propstat_marks_the_response_removed():
    # `sync_collection` splits changed from removed on exactly this. A miss here
    # means a deletion made on the phone never lands in the cache.
    parsed = X.parse_multistatus(ms(
        '<d:response>'
        '  <d:href>/dav/user/work/gone.ics</d:href>'
        '  <d:propstat>'
        '    <d:prop><d:getetag/></d:prop>'
        '    <d:status>HTTP/1.1 404 Not Found</d:status>'
        '  </d:propstat>'
        '</d:response>'
    ))
    assert parsed.responses[0].is_removed


def test_a_response_level_status_marks_it_removed():
    # Radicale's shape for a removal: a bare <response> with a status and no
    # propstat at all. The parser must not require a propstat to exist.
    parsed = X.parse_multistatus(ms(
        '<d:response>'
        '  <d:href>/dav/user/work/gone.ics</d:href>'
        '  <d:status>HTTP/1.1 404 Not Found</d:status>'
        '</d:response>'
    ))
    r = parsed.responses[0]
    assert r.propstats == []
    assert r.status == 404
    assert r.is_removed
    assert r.text(X.GETETAG) is None            # asking for a prop must not throw


def test_a_2xx_response_status_is_not_a_removal():
    # The control for the two above: `is_removed` keys on 404 specifically, so a
    # 200 or a 507 must not silently delete a live item from the cache.
    for line in ("HTTP/1.1 200 OK", "HTTP/1.1 507 Insufficient Storage"):
        parsed = X.parse_multistatus(ms(
            f'<d:response><d:href>/x.ics</d:href><d:status>{line}</d:status></d:response>'))
        assert not parsed.responses[0].is_removed


# ── things a server can send that the parser must survive ─────────────────

def test_a_response_with_no_href_is_still_a_response():
    # An empty href rather than a crash: the caller keys a dict on it, and losing
    # the whole document because one entry was malformed is worse.
    parsed = X.parse_multistatus(ms(
        '<d:response><d:propstat><d:prop><d:getetag>"x"</d:getetag></d:prop>'
        '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'))
    assert parsed.responses[0].href == ""


def test_properties_from_an_unknown_namespace_are_kept_under_their_own_name():
    # Clark notation throughout means a vendor extension cannot collide with a
    # DAV: property of the same local name — <x:getetag> is not <d:getetag>.
    parsed = X.parse_multistatus(ms(
        '<d:response><d:href>/x.ics</d:href><d:propstat><d:prop>'
        '<x:getetag xmlns:x="http://vendor.example/ns">not ours</x:getetag>'
        '<d:getetag>"real"</d:getetag>'
        '</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'))

    r = parsed.responses[0]
    assert r.text(X.GETETAG) == '"real"'
    assert r.text("{http://vendor.example/ns}getetag") == "not ours"


def test_a_status_line_without_a_code_parses_as_unknown():
    # `_parse_status_code` scans for the first all-digit token. A server that
    # sends something unparseable must not be read as 404 — that would delete.
    parsed = X.parse_multistatus(ms(
        '<d:response><d:href>/x.ics</d:href><d:status>HTTP/1.1 OK</d:status></d:response>'))
    assert parsed.responses[0].status is None
    assert not parsed.responses[0].is_removed


def test_a_propstat_without_a_status_is_not_treated_as_success():
    # The status defaults to 0, which fails the `200 <= status < 300` test — so a
    # property arrives unreadable rather than trusted-by-default.
    parsed = X.parse_multistatus(ms(
        '<d:response><d:href>/x.ics</d:href><d:propstat>'
        '<d:prop><d:getetag>"x"</d:getetag></d:prop></d:propstat></d:response>'))
    r = parsed.responses[0]
    assert r.propstats[0].status == 0
    assert r.text(X.GETETAG) is None


def test_malformed_xml_stays_inside_the_dav_taxonomy():
    # This pinned XMLSyntaxError, on the rationale that "the callers all sit
    # behind `_request`, which has already required a 207, so this only fires on
    # a server that answered 207 with rubbish". That rationale was false, and
    # the test was doing exactly the job its own comment claimed — noticing when
    # the taxonomy changed. Radicale answers a VALID 207 whose payload carries a
    # character XML cannot represent (one U+FFFE another CalDAV client wrote), so
    # a foreign exception type came out of `multiget` and wedged the collection's
    # sync for good. `parse_multistatus` now refuses in-taxonomy.
    with pytest.raises(DavError):
        X.parse_multistatus(b"<d:multistatus xmlns:d='DAV:'><d:response>")


def test_a_character_xml_cannot_carry_is_refused_in_taxonomy():
    # The shape that actually happens on the wire: well-formed markup whose TEXT
    # holds U+FFFE. lxml refuses the document; the caller must see a DavError.
    body = (
        "<d:multistatus xmlns:d='DAV:'><d:response><d:href>/x.ics</d:href>"
        "<d:propstat><d:prop><d:getetag>￾</d:getetag></d:prop>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
        "</d:multistatus>"
    ).encode()
    with pytest.raises(DavError):
        X.parse_multistatus(body)


def test_an_external_entity_is_not_fetched():
    # The parser reads bytes from the network. lxml does not load external
    # entities by default (no_network, no DTD load); this pins that, because the
    # day it changes an XXE reads /etc/passwd through the sync loop.
    body = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE multistatus ['
        '  <!ENTITY xxe SYSTEM "file:///etc/passwd">'
        ']>'
        '<d:multistatus xmlns:d="DAV:"><d:response>'
        '<d:href>&xxe;</d:href></d:response></d:multistatus>'
    ).encode()
    try:
        parsed = X.parse_multistatus(body)
    except DavError:
        return                                  # refused outright; also fine
    assert "root:" not in parsed.responses[0].href
