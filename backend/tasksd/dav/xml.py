"""XML request builders and multistatus parsing for CalDAV, via lxml.

We keep this hand-rolled (not the `caldav` library) precisely so the write path
has raw control over etags and request bodies — invariant #2. Names are handled
in Clark notation (``{namespace}local``) throughout.
"""
from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

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
    etree.SubElement(prop, DISPLAYNAME).text = displayname
    comp_set = etree.SubElement(prop, SUPPORTED_COMPONENT_SET)
    for comp in components:
        etree.SubElement(comp_set, COMP).set("name", comp)
    if description is not None:
        etree.SubElement(prop, CALENDAR_DESCRIPTION).text = description
    if color is not None:
        etree.SubElement(prop, CALENDAR_COLOR).text = color
    return _tostring(root)


def build_proppatch(props: dict[str, str | None]) -> bytes:
    """PROPPATCH body. A ``None`` value removes the property, anything else
    sets it (RFC 4918 <set>/<remove> inside one <propertyupdate>)."""
    root = _root(PROPERTYUPDATE)
    to_set = {k: v for k, v in props.items() if v is not None}
    to_remove = [k for k, v in props.items() if v is None]
    if to_set:
        prop = etree.SubElement(etree.SubElement(root, cl(DAV, "set")), PROP)
        for name, value in to_set.items():
            etree.SubElement(prop, name).text = value
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


def parse_multistatus(data: bytes) -> MultiStatus:
    root = etree.fromstring(data)
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
