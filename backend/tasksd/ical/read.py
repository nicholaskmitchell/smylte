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


_DURATION_LINE = re.compile(r"^DURATION[;:]", re.I)
_RECURRENCE_LINE = re.compile(r"^RECURRENCE-ID[;:]", re.I)


def unfold(raw: bytes | str) -> list[str]:
    """The ICS content lines, with RFC 5545 §3.1 folding undone.

    A line beginning with a space or tab continues the one before it, and the
    single leading whitespace character is what was inserted by the folder.

    Each logical line is accumulated in a LIST and joined once. The obvious
    `out[-1] += line[1:]` is quadratic — the list holds a reference at concat
    time, so CPython's in-place append optimisation cannot apply and every
    continuation copies the whole accumulated string. That is not academic here:
    this runs inside `expand_occurrences`, which the public booking page reaches
    for every event calendar, uncached, under the service's global lock. Measured
    on a 4 MB resource, the quadratic version cost 16 s against the icalendar
    parser's 0.27 s.
    """
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    out: list[str] = []
    parts: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and parts:
            parts.append(line[1:])
        else:
            if parts:
                out.append("".join(parts))
            parts = [line]
    if parts:
        out.append("".join(parts))
    return out


def _value_of(line: str) -> str | None:
    """The value half of a content line, with any parameters stripped.

    Not `line.split(":", 1)[1]`: a parameter value may itself contain a colon
    when it is quoted (RFC 5545 §3.2), and `DURATION;X-A=a:b:PT8H` is a real
    shape Evolution emits. The name ends at the first `;` or `:` outside quotes,
    and the VALUE begins after the first unquoted `:`.
    """
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted
        elif ch == ":" and not quoted:
            return line[i + 1:].strip()
    return None


def wire_durations(raw: bytes | str) -> dict[str | None, str]:
    """Each VEVENT's DURATION exactly as it arrived, keyed by RECURRENCE-ID value.

    WHY THIS EXISTS AT ALL. icalendar parses a DURATION into a `timedelta`, and
    `timedelta` normalizes: `PT24H` becomes `timedelta(days=1)`, which
    `to_ical()` re-serializes as `P1D`. Those two are NOT interchangeable —
    §3.3.6 makes the time part exact and the day part nominal, which is the whole
    distinction `split_duration` and `advance` exist to preserve — so reading the
    duration back off the parsed component destroys the only evidence of which
    was authored, one layer above the code that cares.

    The effect was measurable: a `PT24H` block across the spring-forward blocked
    23 real hours instead of 24, releasing an hour to the public booking page,
    and `_exact_durations` classified the same event as nominal and left the
    expansion alone.

    Keyed on the RECURRENCE-ID's raw value rather than a parsed instant: this
    runs before any parsing and only has to line up with itself.

    SUBCOMPONENTS ARE SKIPPED WHOLE, and that is the sharp edge. A VALARM lives
    INSIDE a VEVENT and carries its own DURATION — the repeat interval beside
    `REPEAT:`, which Apple Calendar and DAVx5 write for any repeating alarm.
    A scan that tracked only `BEGIN/END:VEVENT` read that as the event's, and
    since producers put VALARM last it was the value that survived: a two-hour
    appointment cached as five minutes, with the rest offered to anonymous
    visitors on the public booking page. Depth is tracked, and only lines at the
    VEVENT's own level are read.

    A resource with two VEVENTs and no RECURRENCE-ID on either is malformed but
    accepted upstream; `find_component` takes the FIRST, so this does too rather
    than letting the second overwrite it.
    """
    out: dict[str | None, str] = {}
    depth = 0                       # nesting below the VEVENT we are inside
    in_vevent = False
    duration: str | None = None
    rid: str | None = None
    for line in unfold(raw):
        upper = line.upper()
        if upper.startswith("BEGIN:"):
            if not in_vevent:
                if upper.startswith("BEGIN:VEVENT"):
                    in_vevent, depth, duration, rid = True, 0, None, None
            else:
                depth += 1          # a subcomponent: everything in it is not ours
            continue
        if upper.startswith("END:"):
            if in_vevent:
                if depth:
                    depth -= 1
                else:
                    if duration is not None and rid not in out:
                        out[rid] = duration
                    in_vevent = False
            continue
        if in_vevent and not depth:
            if _DURATION_LINE.match(line):
                duration = _value_of(line)
            elif _RECURRENCE_LINE.match(line):
                rid = _value_of(line)
    return out


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
    """An integer property, or None — and None for anything SQLite cannot hold.

    Python's ints are unbounded; SQLite's INTEGER is signed 64-bit. Every value
    here is bound into a column by `store.upsert_item`, so `SEQUENCE:1e20`
    (which any CalDAV client can PUT, and which Radicale's own parser
    round-trips happily) raised OverflowError at the bind — not ValueError, so
    the sync engine's malformed-resource guard did not catch it, and not
    something `patch_event` maps either.

    The blast radius was the whole collection: the bind aborted the transaction,
    the sync token was never advanced, and the next pass re-fetched the same
    poison href with the same old token and failed identically. One resource
    from one client froze every change from every client, permanently.

    Same rule and the same reason as the `calendar-order` clamp in
    `dav/client.py`. RFC 5545 gives SEQUENCE no upper bound in practice, but a
    value this large is not a sequence number anyone meant — no hint at all
    beats a hint that stops the sync.
    """
    v = comp.get(key)
    if v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if -(2**63) <= n < 2**63 else None


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


def extract(cal: Calendar, *, wire: dict[str | None, str] | None = None) -> ItemFields | None:
    """`wire` is `wire_durations(raw)` when the caller still has the bytes — the
    only place the authored DURATION text survives. Optional so a caller holding
    only a parsed Calendar still works, at the cost of the nominal/exact
    distinction for durations of a day or more."""
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
            # The WIRE text when we have it, and `to_ical()` only as a fallback.
            # `str()` on a parsed vDDDTypes yields its repr, so this column has
            # always needed a deliberate serialization — but `to_ical()` round
            # trips through a normalized `timedelta`, which turns `PT24H` into
            # `P1D` and silently changes what the value MEANS (see
            # `wire_durations`). busy/interval math re-parses this column, so the
            # loss landed on the booking page's busy set.
            rid = comp.get("RECURRENCE-ID")
            key = str(rid.to_ical().decode()) if rid is not None else None
            # Only when it PARSES. The wire text is attacker-influenced — it
            # comes from whatever client wrote the resource — and a value
            # icalendar rejected must not reach this column just because a
            # hand-written scan found it. Anything unparseable falls back to the
            # library's own reading, which is what shipped before.
            authored = (wire or {}).get(key)
            if authored is None or split_duration(authored) is None:
                authored = comp.get("DURATION").to_ical().decode()
            # …and None when NEITHER reading parses. Storing a string
            # `busy_intervals` cannot re-parse is worse than storing nothing:
            # it drops the interval inside a bare `except: continue`, so the
            # event leaves the busy set entirely and the public booking page
            # offers the whole of it. Predates this column carrying wire text —
            # `to_ical()` returns the same garbage for a malformed line — but it
            # is one line to close here.
            f.duration = authored if split_duration(authored) is not None else None
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
    return extract(parse_calendar(raw), wire=wire_durations(raw))
