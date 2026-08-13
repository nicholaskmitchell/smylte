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

CORPUS = sorted((Path(__file__).parent / "corpus").glob("*.ics"))
CORPUS_IDS = [p.name for p in CORPUS]

# Properties apply_changes() deliberately writes; excluded when asserting that
# everything ELSE survived (invariant #2).
TOUCHED = frozenset(
    {"SUMMARY", "STATUS", "COMPLETED", "PERCENT-COMPLETE", "LAST-MODIFIED", "DTSTAMP", "SEQUENCE"}
)


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


@pytest.mark.parametrize("path", CORPUS, ids=CORPUS_IDS)
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


@pytest.mark.parametrize("path", CORPUS, ids=CORPUS_IDS)
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
