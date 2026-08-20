"""Read path: parse a resource with `icalendar` and extract the fields the SQLite
cache indexes, for either a VTODO (task) or a VEVENT (calendar event).

`icalendar` retains unknown properties/params/subcomponents (verified by the
fidelity suite), so parsing here never loses foreign data. Extraction is
deliberately lossy the other way — we pull only the columns the cache queries on.
The full-fidelity source of truth stays in `raw_ics` (invariant #1/#2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from datetime import date, datetime, timedelta, timezone

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
    # The earliest instant this RESOURCE can produce, across every component —
    # the master's DTSTART, any RDATE, and any RECURRENCE-ID override's DTSTART.
    # See `min_instant` below for why the master's DTSTART is not it.
    min_instant: str | None = None


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


# RFC 5545 §3.3.6 splits a DURATION into two kinds of quantity, and the
# distinction is load-bearing on exactly two days a year: "the duration of a week
# or a day depends on its position in the calendar", while an hour, minute or
# second is exact. So P1D across the spring-forward is 23 hours of real time and
# PT24H is 24, and a single timedelta cannot tell you which you were given —
# `vDuration.from_ical` collapses both to `timedelta(days=1)`.
_DURATION_PARTS = re.compile(
    r"(?P<sign>[+-])?P(?:(?P<w>\d+)W)?(?:(?P<d>\d+)D)?"
    r"(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?",
    re.IGNORECASE,
)


def split_duration(raw) -> tuple[timedelta, timedelta] | None:
    """An RFC 5545 DURATION as its (nominal, exact) halves, or None if unparseable.

    Nominal is the weeks/days part, exact the time part. A negative duration
    negates both.
    """
    if raw is None:
        return None
    text = raw.decode() if isinstance(raw, bytes) else str(raw)
    m = _DURATION_PARTS.fullmatch(text.strip())
    if m is None:
        return None
    g = {k: int(v) for k, v in m.groupdict().items() if k != "sign" and v}
    if not g:
        return None
    sign = -1 if m.group("sign") == "-" else 1
    nominal = timedelta(weeks=g.get("w", 0), days=g.get("d", 0))
    exact = timedelta(hours=g.get("h", 0), minutes=g.get("m", 0), seconds=g.get("s", 0))
    return sign * nominal, sign * exact


def advance(value, raw, total: timedelta):
    """`value` moved forward by a DURATION, each half applied as §3.3.6 defines.

    The nominal half is added to the WALL CLOCK — "a day later" means the same
    time tomorrow whatever the clocks did overnight. The exact half is added to
    the INSTANT, because `aware + timedelta` adds to the naive fields and
    re-derives the offset: 02:30 CST + PT30M is 03:00, and on 2026-03-08 that
    03:00 is CDT, half an hour BEFORE the start.

    `total` is the already-parsed timedelta, used when `raw` cannot be split (or
    when `value` is a date, where everything is nominal anyway) so a caller never
    ends up worse off than the plain addition it replaced.
    """
    if not isinstance(value, datetime) or value.tzinfo is None:
        return value + total
    parts = split_duration(raw)
    if parts is None:
        return value + total
    nominal, exact = parts
    out = value + nominal                       # wall clock, then…
    if exact:
        out = (out.astimezone(timezone.utc) + exact).astimezone(value.tzinfo)
    return out


def normalize_offset(dt: datetime) -> datetime:
    """A datetime carrying a bare numeric offset, re-expressed as UTC.

    `fromisoformat("2026-08-10T09:00:00-07:00")` yields a fixed-offset
    `datetime.timezone`, and icalendar serializes one of those as a FABRICATED
    `TZID="UTC-07:00"` — a zone name no CalDAV client can resolve, this app's own
    reader included. The value then reads back FLOATING, so the instant moves by
    the whole offset: a 09:00 Pacific meeting became 09:00 in whatever zone the
    owner authors in, `busy_intervals` placed it there, and the public booking
    page advertised the hour the owner was actually busy while blocking one they
    were free.

    `ical/edit.py::_set_datelike` documents this exact trap and defends against
    it — but only when the property being overwritten is ALREADY zone-aware, so
    it covers neither a create (no old value) nor a PATCH of a floating property,
    which is what all of this app's own writes are. Normalizing here covers all
    three, because every date-bearing field on every route funnels through
    `_parse_datelike`. UTC round-trips losslessly (icalendar emits `...Z`), and
    `_set_datelike` can still re-express a UTC value into an old property's real
    zone. Zero-offset input was already safe by accident: Python maps `+00:00`
    and `Z` to `timezone.utc`.
    """
    if dt.tzinfo is not None and type(dt.tzinfo) is timezone:
        return dt.astimezone(timezone.utc)
    return dt


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
    f.min_instant = _min_instant(cal, f.dtstart)
    return f


def _min_instant(cal: Calendar, dtstart: str | None) -> str | None:
    """The earliest instant any component of this resource can produce.

    `items.dtstart` is the MASTER's DTSTART, and a recurrence set can start
    before it: `recurring_ical_events` applies RECURRENCE-ID overrides, and an
    override carries its own DTSTART. This app creates that shape itself —
    `apply_occurrence_override` deliberately leaves the master rule alone, so
    dragging the first occurrence of a series earlier is enough — and
    Thunderbird's and Apple's "move this occurrence" do the same.

    `get_events_in_range` needs a lower bound it can filter on. Gating on the
    master's DTSTART dropped the moved occurrence; dropping the gate entirely
    made every recurring row on the account a candidate for every window, which
    is a cost an anonymous caller can choose. This is the honest value.

    Compared as an ISO string, like every other date column here, so it orders
    correctly on the leading date and needs no parsing at query time. Mixed
    offsets can misorder by less than a day, which is why the query keeps a
    day of slack around it.
    """
    best = dtstart
    for comp in cal.walk():
        if getattr(comp, "name", "") not in ("VEVENT", "VTODO"):
            continue
        candidates = [comp.get("DTSTART")]
        rdate = comp.get("RDATE")
        for entry in (rdate if isinstance(rdate, list) else [rdate] if rdate else []):
            candidates.extend(getattr(entry, "dts", []) or [])
        for c in candidates:
            if c is None:
                continue
            value = _iso(c)[0]
            if isinstance(value, str) and (best is None or value < best):
                best = value
    return best


def extract_from_raw(raw: bytes | str) -> ItemFields | None:
    return extract(parse_calendar(raw))
