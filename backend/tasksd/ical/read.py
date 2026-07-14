"""Read path: parse a resource with `icalendar` and extract the fields the SQLite
cache indexes, for either a VTODO (task) or a VEVENT (calendar event).

`icalendar` retains unknown properties/params/subcomponents (verified by the
fidelity suite), so parsing here never loses foreign data. Extraction is
deliberately lossy the other way — we pull only the columns the cache queries on.
The full-fidelity source of truth stays in `raw_ics` (invariant #1/#2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from icalendar import Calendar

# Components we cache (tasks + calendar events). VJOURNAL is ignored.
CACHED_COMPONENTS = ("VTODO", "VEVENT")


@dataclass
class ItemFields:
    uid: str
    component: str = "VTODO"                  # VTODO | VEVENT
    summary: str | None = None
    description: str | None = None
    status: str | None = None
    priority: int | None = None               # VTODO
    percent_complete: int | None = None       # VTODO
    completed: str | None = None              # VTODO
    due: str | None = None                    # VTODO
    due_is_date: bool = False
    dtstart: str | None = None                # both
    dtstart_is_date: bool = False
    dtend: str | None = None                  # VEVENT
    dtend_is_date: bool = False
    duration: str | None = None               # VEVENT
    categories: list[str] = field(default_factory=list)
    related_parent: str | None = None         # RELATED-TO;RELTYPE=PARENT (UID join key)
    created: str | None = None
    last_modified: str | None = None
    sequence: int | None = None
    has_rrule: bool = False
    location: str | None = None


# Back-compat alias: Phase 0 named this TaskFields.
TaskFields = ItemFields


def parse_calendar(raw: bytes | str) -> Calendar:
    return Calendar.from_ical(raw)


def find_component(cal: Calendar):
    """Return (component, name) for the series *master* — the first VTODO/VEVENT
    that has no RECURRENCE-ID. A recurring resource carries the master plus zero or
    more override components (each with a RECURRENCE-ID, RFC 4791); the cache
    columns must reflect the master, not an override. Falls back to the first
    component of that type if every instance is an override (malformed, but safe).
    Returns (None, None) when neither component type is present."""
    for name in CACHED_COMPONENTS:
        comps = list(cal.walk(name))
        if not comps:
            continue
        for comp in comps:
            if "RECURRENCE-ID" not in comp:
                return comp, name
        return comps[0], name
    return None, None


def find_vtodo(cal: Calendar):
    for comp in cal.walk("VTODO"):
        return comp
    return None


def _iso(value) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    dt = value.dt if hasattr(value, "dt") else value
    if isinstance(dt, datetime):
        return dt.isoformat(), False
    if isinstance(dt, date):
        return dt.isoformat(), True
    return str(dt), False


def _text(comp, key: str) -> str | None:
    v = comp.get(key)
    return None if v is None else str(v)


def _int(comp, key: str) -> int | None:
    v = comp.get(key)
    return None if v is None else int(v)


def _categories(cats) -> list[str]:
    if cats is None:
        return []
    out: list[str] = []
    for c in cats if isinstance(cats, list) else [cats]:
        if hasattr(c, "cats"):
            out.extend(str(x) for x in c.cats)
        else:
            out.extend(s.strip() for s in str(c).split(",") if s.strip())
    return out


def _related_parent(comp) -> str | None:
    rel = comp.get("RELATED-TO")
    if rel is None:
        return None
    for r in rel if isinstance(rel, list) else [rel]:
        # RFC 5545: RELATED-TO defaults to RELTYPE=PARENT when absent.
        reltype = str(getattr(r, "params", {}).get("RELTYPE", "PARENT")).upper()
        if reltype == "PARENT":
            return str(r)
    return None


def extract(cal: Calendar) -> ItemFields | None:
    comp, name = find_component(cal)
    if comp is None:
        return None
    f = ItemFields(uid=_text(comp, "UID") or "", component=name)
    f.summary = _text(comp, "SUMMARY")
    f.description = _text(comp, "DESCRIPTION")
    f.status = _text(comp, "STATUS") or None
    f.location = _text(comp, "LOCATION")
    f.sequence = _int(comp, "SEQUENCE")
    if "DTSTART" in comp:
        f.dtstart, f.dtstart_is_date = _iso(comp.get("DTSTART"))
    if "CREATED" in comp:
        f.created = _iso(comp.get("CREATED"))[0]
    if "LAST-MODIFIED" in comp:
        f.last_modified = _iso(comp.get("LAST-MODIFIED"))[0]
    # "Has a recurrence set" — RRULE or RDATE. Drives whether the read path
    # expands the resource into occurrences (recur.expand_occurrences).
    f.has_rrule = ("RRULE" in comp) or ("RDATE" in comp)
    f.categories = _categories(comp.get("CATEGORIES"))
    f.related_parent = _related_parent(comp)
    if name == "VTODO":
        f.priority = _int(comp, "PRIORITY")
        f.percent_complete = _int(comp, "PERCENT-COMPLETE")
        if "COMPLETED" in comp:
            f.completed = _iso(comp.get("COMPLETED"))[0]
        if "DUE" in comp:
            f.due, f.due_is_date = _iso(comp.get("DUE"))
    else:  # VEVENT
        if "DTEND" in comp:
            f.dtend, f.dtend_is_date = _iso(comp.get("DTEND"))
        if "DURATION" in comp:
            # str() on a parsed vDDDTypes yields its repr, not the RFC 5545 form;
            # busy/interval math re-parses this column, so store canonical text.
            f.duration = comp.get("DURATION").to_ical().decode()
    return f


def extract_from_raw(raw: bytes | str) -> ItemFields | None:
    return extract(parse_calendar(raw))
