"""The load-bearing suite (spec §8): round-trip fidelity via golden files.

Uses the independent canonicalizer to judge — never letting `icalendar` grade its
own output. If any of these fail, no UI work should proceed.
"""
from __future__ import annotations

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


def test_build_new_is_wellformed():
    raw = build_new("new-uid-123", summary="Call mom", edit=TaskEdit(priority=1))
    tf = extract_from_raw(raw)
    assert tf is not None
    assert tf.uid == "new-uid-123"
    assert tf.summary == "Call mom"
    assert tf.status == "NEEDS-ACTION"
    assert tf.priority == 1
