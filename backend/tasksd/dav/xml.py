"""XML request builders and multistatus parsing for CalDAV, via lxml.

We keep this hand-rolled (not the `caldav` library) precisely so the write path
has raw control over etags and request bodies — invariant #2. Names are handled
in Clark notation (``{namespace}local``) throughout.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

from .errors import DavError, MalformedResponse

# --- namespaces ---------------------------------------------------------------
DAV = "DAV:"
CALDAV = "urn:ietf:params:xml:ns:caldav"
CS = "http://calendarserver.org/ns/"          # getctag, calendar sharing
ICAL = "http://apple.com/ns/ical/"            # calendar-color, calendar-order

_PREFIXES = {"d": DAV, "c": CALDAV, "cs": CS, "i": ICAL}


def cl(ns: str, local: str) -> str:
    """Clark-notation name: cl(DAV, 'prop') -> '{DAV:}prop'."""
    return f"{{{ns}}}{local}"


# Frequently used names.
PROPFIND = cl(DAV, "propfind")
PROP = cl(DAV, "prop")
PROPSTAT = cl(DAV, "propstat")
RESPONSE = cl(DAV, "response")
STATUS = cl(DAV, "status")
HREF = cl(DAV, "href")
GETETAG = cl(DAV, "getetag")
RESOURCETYPE = cl(DAV, "resourcetype")
DISPLAYNAME = cl(DAV, "displayname")
SYNC_TOKEN = cl(DAV, "sync-token")
SYNC_COLLECTION = cl(DAV, "sync-collection")
SYNC_LEVEL = cl(DAV, "sync-level")

CALENDAR = cl(CALDAV, "calendar")
CALENDAR_DATA = cl(CALDAV, "calendar-data")
CALENDAR_MULTIGET = cl(CALDAV, "calendar-multiget")
MKCALENDAR = cl(CALDAV, "mkcalendar")
SUPPORTED_COMPONENT_SET = cl(CALDAV, "supported-calendar-component-set")
COMP = cl(CALDAV, "comp")
CALENDAR_DESCRIPTION = cl(CALDAV, "calendar-description")
CALENDAR_COLOR = cl(ICAL, "calendar-color")
CALENDAR_ORDER = cl(ICAL, "calendar-order")
PROPERTYUPDATE = cl(DAV, "propertyupdate")


def _tostring(el: etree._Element) -> bytes:
    return etree.tostring(el, xml_declaration=True, encoding="utf-8")


def _root(tag: str) -> etree._Element:
    return etree.Element(tag, nsmap=_PREFIXES)


def build_propfind(props: list[str]) -> bytes:
    root = _root(PROPFIND)
    prop = etree.SubElement(root, PROP)
    for name in props:
        etree.SubElement(prop, name)
    return _tostring(root)


def build_sync_collection(sync_token: str | None, props: list[str], level: str = "1") -> bytes:
    root = _root(SYNC_COLLECTION)
    # An empty <sync-token/> requests an initial (full) sync per RFC 6578.
    etree.SubElement(root, SYNC_TOKEN).text = sync_token or ""
    etree.SubElement(root, SYNC_LEVEL).text = level
    prop = etree.SubElement(root, PROP)
    for name in props:
        etree.SubElement(prop, name)
    return _tostring(root)


def build_calendar_multiget(hrefs: list[str], props: list[str]) -> bytes:
    root = _root(CALENDAR_MULTIGET)
    prop = etree.SubElement(root, PROP)
    for name in props:
        etree.SubElement(prop, name)
    for href in hrefs:
        etree.SubElement(root, HREF).text = href
    return _tostring(root)


def build_mkcalendar(
    displayname: str,
    components: list[str],
    *,
    description: str | None = None,
    color: str | None = None,
) -> bytes:
    """MKCALENDAR body. ``supported-calendar-component-set`` is set HERE and only
    here — it is protected and cannot be PROPPATCHed later (invariant #8)."""
    root = _root(MKCALENDAR)
    prop = etree.SubElement(etree.SubElement(root, cl(DAV, "set")), PROP)
    _text(etree.SubElement(prop, DISPLAYNAME), displayname)
    comp_set = etree.SubElement(prop, SUPPORTED_COMPONENT_SET)
    for comp in components:
        etree.SubElement(comp_set, COMP).set("name", comp)
    if description is not None:
        _text(etree.SubElement(prop, CALENDAR_DESCRIPTION), description)
    if color is not None:
        _text(etree.SubElement(prop, CALENDAR_COLOR), color)
    return _tostring(root)


# Characters lxml refuses at assignment time. It raises a bare ValueError, which
# is outside the DavError taxonomy the app's handlers know about, so a name
# carrying one escaped every handler and surfaced as a 500 with a traceback.
# Everything XML 1.0 cannot carry (§2.2 Char): the C0 controls except tab, LF and
# CR; the surrogate range, which additionally fails UTF-8 encoding outright with
# a UnicodeEncodeError rather than anything lxml would raise; and the two
# noncharacters at the end of the BMP, which lxml refuses with a bare ValueError.
# None of those three exception types is in the DAV taxonomy, so an unguarded one
# surfaced as a 500 from a list rename.
#
# Exported because this rule has to hold in three places at once — the HTTP edge
# (app.CollectionName), the MCP tool schemas, and this backstop. It was
# previously duplicated by hand, so widening it in one place silently drifted the
# others: the SPA would accept a name the DAV layer then rejected, turning what
# should be a 422 into a failed write.
#
# Two spellings, because two regex engines have to enforce it and only one of
# them can express the surrogate range:
#
#   XML_SAFE_PATTERN         full set. For Python's `re` — the MCP tool schemas
#                            (validated by mcp/validate.py) and the backstop below.
#   XML_SAFE_PATTERN_SCALAR  same, minus the surrogates. For pydantic, which
#                            compiles with Rust's regex crate; a surrogate is not
#                            a Unicode scalar value, so Rust cannot name one and
#                            the pattern fails to build at import time.
#
# Dropping them there costs nothing: pydantic rejects a lone surrogate at string
# conversion (`string_unicode`) before any pattern runs, for the same underlying
# reason. Verified, not assumed — see test_backlog_stage1.
_C0 = r"\x00-\x08\x0b\x0c\x0e-\x1f"       # C0 controls except tab, LF, CR
_SURROGATES = r"\ud800-\udfff"            # also unencodable as UTF-8
# The two characters below are LITERAL U+FFFE and U+FFFF, and invisible in most
# editors. They cannot be written as `￾￿` escapes: that spelling is
# Python's, and `XML_SAFE_PATTERN_SCALAR` is compiled by Rust's regex crate,
# which spells the same thing `\u{FFFE}`. A literal is the one form both engines
# read identically.
_NONCHARS = "￾￿"                # lxml refuses these with a bare ValueError

XML_FORBIDDEN_CLASS = _C0 + _SURROGATES + _NONCHARS
XML_SAFE_PATTERN = rf"^[^{XML_FORBIDDEN_CLASS}]*$"
XML_SAFE_PATTERN_SCALAR = rf"^[^{_C0}{_NONCHARS}]*$"

# The shape a collection color may take, on the way IN as well as out.
#
# `calendar-color` is an Apple dead property, so anything with write access to a
# shared collection can PROPPATCH it to arbitrary text and Radicale stores that
# verbatim (trust model: hostile data from Radicale is adversary #2). The write
# path always validated it; the read path took it as raw text, stored it, and
# handed it to the SPA, which writes it straight into the CSSOM as an inline
# declaration. `background: url(https://evil.example/x.png)` on a rendered 3-5px
# dot fetches the URL — a beacon that fires whenever the owner opens the
# Calendar tab or the Home mini-calendar.
#
# It lives here, beside the property name it belongs to, because the same shape
# has to hold on both paths and this file is already where a validator shared
# across layers goes (see XML_SAFE_PATTERN_SCALAR above, whose comment records
# what three hand-written copies cost last time).
COLOR_PATTERN = r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$"
_COLOR_RE = re.compile(COLOR_PATTERN)


def clean_color(value: str | None) -> str | None:
    """A collection color if it is one, else None. Never raises."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v if _COLOR_RE.match(v) else None

_XML_FORBIDDEN = re.compile(f"[{XML_FORBIDDEN_CLASS}]")


def _text(el, value: str) -> None:
    """Assign element text, refusing what XML cannot carry.

    Callers should reject this at the edge (the API models do, as a 422); this is
    the backstop, so no path can turn a stray control byte into an unhandled
    crash deep in the DAV client."""
    if _XML_FORBIDDEN.search(value):
        raise DavError("value contains characters that cannot be represented in XML")
    el.text = value


def build_proppatch(props: dict[str, str | None]) -> bytes:
    """PROPPATCH body. A ``None`` value removes the property, anything else
    sets it (RFC 4918 <set>/<remove> inside one <propertyupdate>)."""
    root = _root(PROPERTYUPDATE)
    to_set = {k: v for k, v in props.items() if v is not None}
    to_remove = [k for k, v in props.items() if v is None]
    if to_set:
        prop = etree.SubElement(etree.SubElement(root, cl(DAV, "set")), PROP)
        for name, value in to_set.items():
            _text(etree.SubElement(prop, name), value)
    if to_remove:
        prop = etree.SubElement(etree.SubElement(root, cl(DAV, "remove")), PROP)
        for name in to_remove:
            etree.SubElement(prop, name)
    return _tostring(root)


# --- multistatus parsing ------------------------------------------------------

def _parse_status_code(status_line: str | None) -> int | None:
    """'HTTP/1.1 404 Not Found' -> 404."""
    if not status_line:
        return None
    for token in status_line.split():
        if token.isdigit():
            return int(token)
    return None


@dataclass
class PropStat:
    status: int
    props: dict[str, etree._Element]


@dataclass
class Response:
    href: str
    status: int | None                # response-level <status> (used for removals)
    propstats: list[PropStat]

    def prop(self, clark: str) -> etree._Element | None:
        """The element for a property found in a 2xx propstat, else None."""
        for ps in self.propstats:
            if 200 <= ps.status < 300 and clark in ps.props:
                return ps.props[clark]
        return None

    def text(self, clark: str) -> str | None:
        el = self.prop(clark)
        return el.text if el is not None else None

    @property
    def is_removed(self) -> bool:
        """A sync-collection removal: 404 at the response or propstat level."""
        if self.status == 404:
            return True
        return any(ps.status == 404 for ps in self.propstats)


@dataclass
class MultiStatus:
    responses: list[Response]
    sync_token: str | None


# Explicit rather than lxml's defaults, so the two guarantees this parser needs
# are stated where they can be read. `resolve_entities=False` + `no_network=True`
# are what stop an XXE reading /etc/passwd through the sync loop (pinned by
# test_an_external_entity_is_not_fetched); `recover=False` is deliberate — this
# parses bytes from adversary #2, and silently accepting the readable half of a
# truncated response is worse than refusing the response.
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, recover=False)


def parse_multistatus(data: bytes) -> MultiStatus:
    # Inside the taxonomy, for the same reason client.py wraps httpx.HTTPError:
    # callers (and the API's 502 mapping) see one error type. Radicale copies an
    # item's iCalendar bytes into <C:calendar-data> with stdlib ElementTree,
    # which validates no characters, so one U+FFFE another client wrote produces
    # a well-formed-looking 207 that lxml refuses — and an XMLSyntaxError out of
    # here landed past every place built to contain a bad resource.
    try:
        root = etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as e:
        raise MalformedResponse(f"unparseable multistatus: {e}") from e
    responses: list[Response] = []
    for resp in root.findall(RESPONSE):
        href = resp.findtext(HREF) or ""
        resp_status = _parse_status_code(resp.findtext(STATUS))
        propstats: list[PropStat] = []
        for ps in resp.findall(PROPSTAT):
            status = _parse_status_code(ps.findtext(STATUS)) or 0
            props: dict[str, etree._Element] = {}
            prop_el = ps.find(PROP)
            if prop_el is not None:
                for child in prop_el:
                    props[child.tag] = child
            propstats.append(PropStat(status=status, props=props))
        responses.append(Response(href=href, status=resp_status, propstats=propstats))
    return MultiStatus(responses=responses, sync_token=root.findtext(SYNC_TOKEN))
