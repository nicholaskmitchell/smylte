"""The load-bearing suite (spec §8): round-trip fidelity via golden files.

Uses the independent canonicalizer to judge — never letting `icalendar` grade its
own output. If any of these fail, no UI work should proceed.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from tasksd.ical import TaskEdit, apply_changes, build_new, extract_from_raw, parse_calendar
from tasksd.ical import canonical as C
from tasksd.ical.edit import (
    EventEdit,
    apply_event_changes,
    apply_occurrence_override,
    exclude_occurrence,
    shift_series,
    split_series,
)

CORPUS = sorted((Path(__file__).parent / "corpus").glob("*.ics"))
CORPUS_IDS = [p.name for p in CORPUS]

# Split by component, because the two write paths are different code. Judged from
# the bytes rather than the filename so dropping a real capture in here is all it
# takes to widen the suite — which is what corpus/README.md promises.
TODO_CORPUS = [p for p in CORPUS if "BEGIN:VTODO" in p.read_text(encoding="utf-8")]
EVENT_CORPUS = [p for p in CORPUS if "BEGIN:VEVENT" in p.read_text(encoding="utf-8")]
TODO_IDS = [p.name for p in TODO_CORPUS]
EVENT_IDS = [p.name for p in EVENT_CORPUS]


def test_the_corpus_is_not_empty():
    """A parametrize over an empty list collects ZERO cases and reports green.
    This is the load-bearing suite; an emptied or renamed-away corpus has to fail
    rather than pass vacuously."""
    assert TODO_CORPUS, "no VTODO golden files — the fidelity suite asserts nothing"
    assert EVENT_CORPUS, "no VEVENT golden files — every event write path is ungraded"


# Properties apply_changes() deliberately writes; excluded when asserting that
# everything ELSE survived (invariant #2).
TOUCHED = frozenset(
    {"SUMMARY", "STATUS", "COMPLETED", "PERCENT-COMPLETE", "LAST-MODIFIED", "DTSTAMP", "SEQUENCE"}
)

# The event write paths reshape the recurrence set by design, so a signature
# comparison has to exclude the properties that ARE the edit. Everything else —
# ATTENDEE and its parameters, ORGANIZER's quoted CN, VALARM, CATEGORIES, URL,
# CLASS, TRANSP, the X-properties, the VTIMEZONE — must survive untouched.
SPAN = frozenset({"DTSTART", "DTEND", "DURATION"})
RECURRENCE = frozenset({"RRULE", "RDATE", "EXDATE", "RECURRENCE-ID", "UID"})


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", CORPUS, ids=CORPUS_IDS)
def test_icalendar_read_write_preserves_everything(path: Path):
    """Parse -> re-serialize with no changes: canonical form is identical."""
    original = _read(path)
    reserialized = parse_calendar(original).to_ical().decode("utf-8")
    assert C.signature(C.parse(original)) == C.signature(C.parse(reserialized)), (
        f"{path.name}: icalendar altered the component on a no-op round-trip"
    )


@pytest.mark.parametrize("path", TODO_CORPUS, ids=TODO_IDS)
def test_edit_preserves_foreign_data(path: Path):
    """Editing only SUMMARY+STATUS must leave every foreign property, parameter,
    and subcomponent intact (invariant #2)."""
    original = _read(path)
    edited = apply_changes(
        original, TaskEdit(summary="edited by test", status="COMPLETED")
    ).decode("utf-8")
    sig_before = C.signature(C.parse(original), drop=TOUCHED)
    sig_after = C.signature(C.parse(edited), drop=TOUCHED)
    assert sig_before == sig_after, f"{path.name}: an edit dropped/altered foreign data"


@pytest.mark.parametrize("path", TODO_CORPUS, ids=TODO_IDS)
def test_edit_actually_applied(path: Path):
    original = _read(path)
    edited = apply_changes(
        original, TaskEdit(summary="edited by test", status="COMPLETED")
    ).decode("utf-8")
    tf = extract_from_raw(edited)
    assert tf is not None
    assert tf.summary == "edited by test"
    assert tf.status == "COMPLETED"
    assert tf.percent_complete == 100
    assert tf.completed is not None


def test_value_duration_param_survives_edit():
    """icalendar keeps VALARM TRIGGER;VALUE=DURATION where vobject drops it —
    proves the read/write path is strictly better than the vobject alternative."""
    tb = _read(Path(__file__).parent / "corpus" / "thunderbird.ics")
    edited = apply_changes(tb, TaskEdit(summary="x")).decode("utf-8")
    triggers = [
        p for (comp, p), _ in C.flatten(C.parse(edited)).items()
        if comp == "VALARM" and p[0] == "TRIGGER"
    ]
    assert triggers, "VALARM TRIGGER vanished"
    assert any(dict(params).get("VALUE") == "DURATION" for (_, params, _) in triggers), (
        "VALUE=DURATION parameter was dropped on edit"
    )


def test_uid_is_stable_join_key():
    """UID, not href, is the join key (invariant #4): editing never changes it."""
    tb = _read(Path(__file__).parent / "corpus" / "thunderbird.ics")
    before = extract_from_raw(tb).uid
    after = extract_from_raw(apply_changes(tb, TaskEdit(summary="x"))).uid
    assert before == after == "tb-0002@thunderbird"


def test_extract_fields_tasks_org():
    tf = extract_from_raw(_read(Path(__file__).parent / "corpus" / "tasks_org.ics"))
    assert tf is not None
    assert tf.uid == "8b2f-tasks-org-0001"
    assert tf.due_is_date is True and tf.due == "2026-07-03"
    assert tf.categories == ["home", "errands/weekly"]
    assert tf.related_parent == "8b2f-tasks-org-parent"
    assert tf.priority == 5


def test_edit_recurring_task_targets_master_not_override():
    # A foreign client may serialize a RECURRENCE-ID override BEFORE the master
    # (valid ordering); the edit must land on the master — the read side
    # (find_component) already skips overrides, so writing to one makes the
    # edit invisible and corrupts the override.
    raw = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//foreign//EN\r\n"
        "BEGIN:VTODO\r\nUID:rt@x\r\nRECURRENCE-ID:20260113T090000Z\r\n"
        "DTSTART:20260113T090000Z\r\nSUMMARY:Override copy\r\nEND:VTODO\r\n"
        "BEGIN:VTODO\r\nUID:rt@x\r\nDTSTART:20260106T090000Z\r\n"
        "RRULE:FREQ=WEEKLY\r\nSUMMARY:Master\r\nEND:VTODO\r\n"
        "END:VCALENDAR\r\n"
    ).encode()
    edited = apply_changes(raw, TaskEdit(summary="Edited"))
    cal = parse_calendar(edited)
    by_kind = {("override" if "RECURRENCE-ID" in c else "master"): str(c.get("SUMMARY"))
               for c in cal.walk("VTODO")}
    assert by_kind == {"master": "Edited", "override": "Override copy"}
    # And the read path agrees the edit took (same component the cache indexes).
    assert extract_from_raw(edited).summary == "Edited"


# ── repointing the parent leaves every other relation alone ──────────────────
# Re-parenting is how a subtask written against a uid that never existed gets
# repaired. A VTODO may carry several RELATED-TO values, and only the PARENT one
# is ours to touch (invariant #2) — dropping a foreign CHILD or SIBLING link
# while fixing our own mistake would trade one corruption for another.

_MANY_RELATIONS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//foreign//EN\r\n"
    "BEGIN:VTODO\r\nUID:kid@x\r\nSUMMARY:Book flight\r\n"
    "RELATED-TO;RELTYPE=PARENT:old-parent\r\n"
    "RELATED-TO;RELTYPE=CHILD:some-child\r\n"
    "RELATED-TO;RELTYPE=SIBLING:some-sibling\r\n"
    "END:VTODO\r\nEND:VCALENDAR\r\n"
).encode()


def _relations(raw: bytes) -> set[tuple[str, str]]:
    todo = next(iter(parse_calendar(raw).walk("VTODO")))
    rel = todo.get("RELATED-TO")
    if rel is None:
        return set()
    return {
        (str(dict(getattr(r, "params", {}) or {}).get("RELTYPE", "PARENT")).upper(), str(r))
        for r in (rel if isinstance(rel, list) else [rel])
    }


def test_reparent_replaces_only_the_parent_relation():
    edited = apply_changes(_MANY_RELATIONS, TaskEdit(related_parent="new-parent@tasksd"))
    assert _relations(edited) == {
        ("PARENT", "new-parent@tasksd"),
        ("CHILD", "some-child"),
        ("SIBLING", "some-sibling"),
    }
    # The read side, which is what the cache indexes, agrees.
    assert extract_from_raw(edited).related_parent == "new-parent@tasksd"


def test_unparent_drops_only_the_parent_relation():
    edited = apply_changes(_MANY_RELATIONS, TaskEdit(related_parent=None))
    assert _relations(edited) == {("CHILD", "some-child"), ("SIBLING", "some-sibling")}
    assert extract_from_raw(edited).related_parent is None


def test_reparent_replaces_a_bare_related_to():
    # RFC 5545 defaults RELTYPE to PARENT, so a bare RELATED-TO *is* the parent
    # link — the same reading the extractor uses. Leaving it in place alongside
    # the new one would give the task two parents.
    raw = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//foreign//EN\r\n"
        "BEGIN:VTODO\r\nUID:kid@x\r\nSUMMARY:Book flight\r\n"
        "RELATED-TO:bare-old\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
    ).encode()
    edited = apply_changes(raw, TaskEdit(related_parent="new@tasksd"))
    assert _relations(edited) == {("PARENT", "new@tasksd")}


def test_an_unrelated_edit_leaves_the_parent_alone():
    # related_parent is UNSET on an ordinary rename, so RELATED-TO is untouched.
    edited = apply_changes(_MANY_RELATIONS, TaskEdit(summary="Renamed"))
    assert _relations(edited) == {
        ("PARENT", "old-parent"),
        ("CHILD", "some-child"),
        ("SIBLING", "some-sibling"),
    }


def test_build_new_is_wellformed():
    raw = build_new("new-uid-123", summary="Call mom", edit=TaskEdit(priority=1))
    tf = extract_from_raw(raw)
    assert tf is not None
    assert tf.uid == "new-uid-123"
    assert tf.summary == "Call mom"
    assert tf.status == "NEEDS-ACTION"
    assert tf.priority == 1


# ── a zone-anchored DUE keeps its zone across an edit ────────────────────────
# The API serves DUE;TZID=Europe/Berlin as an ISO string with a numeric offset,
# which is all a browser can send back. Writing that offset verbatim makes
# icalendar fabricate TZID="UTC+02:00" — a zone no other client resolves — and
# sending the viewer's naive wall clock instead drops the TZID altogether and
# silently moves the deadline.

_BERLIN_DUE = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//foreign//EN\r\n"
    "BEGIN:VTODO\r\nUID:tz@x\r\nSUMMARY:Pay rent\r\n"
    "DUE;TZID=Europe/Berlin:20260810T093000\r\n"
    "END:VTODO\r\nEND:VCALENDAR\r\n"
).encode()


def _due_lines(raw: bytes) -> list[str]:
    return [ln for ln in raw.decode().split("\r\n") if ln.startswith("DUE")]


def test_editing_a_zoned_due_keeps_its_tzid():
    # The viewer is in New York, sees 03:30, and moves it to 04:30 — sent as the
    # instant that names, which is 10:30 in the series' own zone.
    edited = apply_changes(
        _BERLIN_DUE, TaskEdit(due=datetime.fromisoformat("2026-08-10T04:30:00-04:00")))
    assert _due_lines(edited) == ["DUE;TZID=Europe/Berlin:20260810T103000"]


def test_editing_a_zoned_due_never_fabricates_a_numeric_tzid():
    edited = apply_changes(
        _BERLIN_DUE, TaskEdit(due=datetime.fromisoformat("2026-08-10T04:30:00-04:00")))
    assert b'TZID="UTC' not in edited


def test_a_floating_due_stays_floating():
    """The app's own writes are floating local; nothing should anchor them."""
    raw = _BERLIN_DUE.replace(b"DUE;TZID=Europe/Berlin:20260810T093000", b"DUE:20260810T093000")
    edited = apply_changes(raw, TaskEdit(due=datetime(2026, 8, 10, 10, 30)))
    assert _due_lines(edited) == ["DUE:20260810T103000"]


def test_an_all_day_due_stays_a_bare_date():
    raw = _BERLIN_DUE.replace(b"DUE;TZID=Europe/Berlin:20260810T093000", b"DUE;VALUE=DATE:20260810")
    edited = apply_changes(raw, TaskEdit(due=date(2026, 8, 12)))
    assert _due_lines(edited) == ["DUE;VALUE=DATE:20260812"]


def test_clearing_a_zoned_due_still_clears_it():
    assert _due_lines(apply_changes(_BERLIN_DUE, TaskEdit(due=None))) == []


def test_a_zoned_dtstart_keeps_its_tzid_too():
    raw = _BERLIN_DUE.replace(b"DUE;TZID=", b"DTSTART;TZID=")
    edited = apply_changes(
        raw, TaskEdit(dtstart=datetime.fromisoformat("2026-08-10T04:30:00-04:00")))
    assert [ln for ln in edited.decode().split("\r\n") if ln.startswith("DTSTART")] == [
        "DTSTART;TZID=Europe/Berlin:20260810T103000"
    ]


# ── VEVENT: the event write paths, graded by the canonicalizer ──────────────
#
# The gap this closes: test_fidelity was driven entirely off `corpus/*.ics`, and
# every file in it was VTODO-only. So invariant #2 ("an edit must leave every
# foreign property, parameter and subcomponent intact") was checked with the
# independent canonicalizer for the TASK path and for nothing else — while the
# event write surface is the one with by far the most closed findings in
# docs/AUDIT.md, several of which were exactly "an edit merged, relabelled or
# dropped property lines". The only substitute was two ad-hoc
# `assert b"X-FOREIGN-KEEP" in …` lines, and `split_series` — which mints a
# brand-new resource under a fresh UID, and is the most invasive of the six — had
# no foreign-data assertion anywhere in the suite.
#
# `signature` is order-independent and counts parameters, so it catches a
# reordered ATTENDEE list, a dropped `;CN="Doe, Jane"`, a VALARM that lost its
# X-WR-ALARMUID, and a VTIMEZONE the writer forgot to carry.

ANCHOR = "2026-07-20T14:00:00-05:00"          # the third occurrence; also the override
LATER = "2026-07-27T14:00:00-05:00"           # the fourth, with no override on it


def _events(text: str):
    """Every VEVENT in the tree, as canonical components."""
    out = []
    for cal in C.parse(text).children:
        out.extend(c for c in cal.children if c.name == "VEVENT")
    return out


def _foreign_bag(text: str, drop: frozenset[str]):
    """What the resource carries, minus the properties an edit is allowed to
    change. Compared as a multiset so nothing can hide by moving."""
    return C.flatten(C.parse(text), drop=drop)


@pytest.mark.parametrize("path", EVENT_CORPUS, ids=EVENT_IDS)
def test_event_read_write_preserves_everything(path: Path):
    """Parse -> re-serialize with no changes, for the event path."""
    original = _read(path)
    reserialized = parse_calendar(original).to_ical().decode("utf-8")
    assert C.signature(C.parse(original)) == C.signature(C.parse(reserialized)), (
        f"{path.name}: icalendar altered the component on a no-op round-trip")


@pytest.mark.parametrize("path", EVENT_CORPUS, ids=EVENT_IDS)
def test_editing_the_whole_series_preserves_foreign_data(path: Path):
    """`apply_event_changes` — the "all events" path."""
    original = _read(path)
    edited = apply_event_changes(
        original, EventEdit(summary="edited by test")).decode("utf-8")
    drop = TOUCHED | {"LAST-MODIFIED", "DTSTAMP", "SEQUENCE"}
    assert C.signature(C.parse(original), drop=drop) == C.signature(C.parse(edited), drop=drop), (
        f"{path.name}: editing the series dropped or altered foreign data")


@pytest.mark.parametrize("path", EVENT_CORPUS, ids=EVENT_IDS)
def test_overriding_one_occurrence_preserves_the_rest(path: Path):
    """`apply_occurrence_override` — "this event". It ADDS a component, so the
    master and every pre-existing override must come through unchanged."""
    original = _read(path)
    edited = apply_occurrence_override(
        original, LATER, EventEdit(summary="just this one")).decode("utf-8")
    drop = TOUCHED | {"LAST-MODIFIED", "DTSTAMP", "SEQUENCE"}
    before, after = _foreign_bag(original, drop), _foreign_bag(edited, drop)
    missing = before - after
    assert not missing, f"{path.name}: overriding one occurrence lost {sorted(missing)[:6]}"
    assert len(_events(edited)) == len(_events(original)) + 1


@pytest.mark.parametrize("path", EVENT_CORPUS, ids=EVENT_IDS)
def test_excluding_one_occurrence_preserves_everything_else(path: Path):
    """`exclude_occurrence` — "delete this event". Only EXDATE may change."""
    original = _read(path)
    edited = exclude_occurrence(original, LATER).decode("utf-8")
    drop = frozenset({"EXDATE", "LAST-MODIFIED", "DTSTAMP", "SEQUENCE"})
    before, after = _foreign_bag(original, drop), _foreign_bag(edited, drop)
    assert not (before - after), (
        f"{path.name}: excluding one occurrence lost {sorted(before - after)[:6]}")


@pytest.mark.parametrize("path", EVENT_CORPUS, ids=EVENT_IDS)
def test_shifting_a_series_preserves_foreign_data(path: Path):
    """`shift_series` — dragging the whole series. Times move; nothing else may."""
    original = _read(path)
    # Anchored on an occurrence, as the SPA does: the offset applied to one
    # instance moves the whole series by it.
    edited = shift_series(
        original, LATER,
        EventEdit(dtstart=datetime(2026, 7, 27, 16, 0))).decode("utf-8")
    drop = SPAN | RECURRENCE | {"LAST-MODIFIED", "DTSTAMP", "SEQUENCE"}
    before, after = _foreign_bag(original, drop), _foreign_bag(edited, drop)
    assert not (before - after), (
        f"{path.name}: shifting the series lost {sorted(before - after)[:6]}")


@pytest.mark.parametrize("path", EVENT_CORPUS, ids=EVENT_IDS)
def test_splitting_a_series_carries_foreign_data_into_both_halves(path: Path):
    """`split_series` — "this and following", and the one that most needed this.

    It mints a brand-new resource under a fresh UID, so anything it drops from
    the tail is gone permanently: no resync restores a UID the server has never
    seen. Nothing in the suite asserted any of it. Both halves are checked,
    because a fix that carried the head and rebuilt the tail would pass a
    one-sided test."""
    original = _read(path)
    head, tail = split_series(original, ANCHOR, EventEdit())
    drop = SPAN | RECURRENCE | {"LAST-MODIFIED", "DTSTAMP", "SEQUENCE", "CREATED"}
    before = _foreign_bag(original, drop)

    # The master's own foreign properties, which BOTH halves must still carry.
    master_only = C.Counter({
        k: v for k, v in before.items()
        if k[0] == "VEVENT" and k[1][0] in {
            "ORGANIZER", "ATTENDEE", "CATEGORIES", "URL", "CLASS", "TRANSP",
            "X-MOZ-GENERATION", "X-MOZ-LASTACK", "X-FOREIGN-KEEP", "LOCATION",
        }
    })
    assert master_only, "the corpus file carries no foreign properties to check"

    for label, half in (("head", head), ("tail", tail)):
        assert half is not None, f"{path.name}: no {label}"
        got = _foreign_bag(half.decode("utf-8"), drop)
        # Every foreign KIND the original carried is still present somewhere in
        # this half. Counts are not compared: a split legitimately changes how
        # many override components each half holds.
        kinds_before = {k[1][0] for k in master_only}
        kinds_after = {k[1][0] for k in got if k[0] == "VEVENT"}
        assert kinds_before <= kinds_after, (
            f"{path.name}: the {label} lost {sorted(kinds_before - kinds_after)}")
        assert any(k[0] == "VALARM" for k in got), f"{path.name}: the {label} lost its VALARM"
        assert any(k[0] == "VTIMEZONE" for k in got), (
            f"{path.name}: the {label} lost its VTIMEZONE, so its TZID no longer resolves")
