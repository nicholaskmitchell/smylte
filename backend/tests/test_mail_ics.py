"""The .ics fast path."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from smylted.mail.ics import MAX_EVENTS, parse_ics


def cal(*events: str, method: str | None = "REQUEST") -> bytes:
    head = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//school.example//EN\r\n"
    if method:
        head += f"METHOD:{method}\r\n"
    body = "".join(f"BEGIN:VEVENT\r\n{e.strip()}\r\nEND:VEVENT\r\n" for e in events)
    return (head + body + "END:VCALENDAR\r\n").encode()


def test_timed_event_with_tzid():
    data = cal("""UID:pe-1@school.example
DTSTAMP:20261005T093000Z
DTSTART;TZID=Europe/Berlin:20261008T180000
DTEND;TZID=Europe/Berlin:20261008T193000
SUMMARY:Parent evening
LOCATION:Main hall
DESCRIPTION:Bring the form.
SEQUENCE:2""")
    (ev,) = parse_ics(data)
    assert ev.uid == "pe-1@school.example"
    assert ev.summary == "Parent evening"
    assert ev.all_day is False
    assert ev.start == datetime(2026, 10, 8, 18, 0, tzinfo=ev.start.tzinfo)
    assert ev.start.utcoffset() == timedelta(hours=2)
    assert ev.end - ev.start == timedelta(hours=1, minutes=30)
    assert ev.location == "Main hall"
    assert ev.description == "Bring the form."
    assert ev.method == "REQUEST"
    assert ev.sequence == 2
    assert ev.rrule is None


def test_all_day_event():
    (ev,) = parse_ics(cal("UID:a@school.example\nDTSTART;VALUE=DATE:20261012\nDTEND;VALUE=DATE:20261013\nSUMMARY:Holiday"))
    assert ev.all_day is True
    assert ev.start == date(2026, 10, 12) and not isinstance(ev.start, datetime)
    assert ev.end == date(2026, 10, 13)


def test_duration_instead_of_dtend():
    (ev,) = parse_ics(cal("DTSTART:20261008T180000Z\nDURATION:PT45M\nSUMMARY:Call"))
    assert ev.end - ev.start == timedelta(minutes=45)
    assert ev.uid is None and ev.sequence == 0


def test_no_end_at_all():
    (ev,) = parse_ics(cal("DTSTART:20261008T180000Z\nSUMMARY:Call"))
    assert ev.end is None


def test_rrule_is_preserved():
    (ev,) = parse_ics(cal("DTSTART:20261005T170000Z\nRRULE:FREQ=WEEKLY;BYDAY=MO\nSUMMARY:Training"))
    assert ev.rrule == "FREQ=WEEKLY;BYDAY=MO"


def test_missing_title_gets_a_placeholder():
    (ev,) = parse_ics(cal("DTSTART:20261005T170000Z", method=None))
    assert ev.summary == "(no title)"
    assert ev.method is None


def test_cancel_method_yields_nothing():
    assert parse_ics(cal("DTSTART:20261005T170000Z\nSUMMARY:x", method="CANCEL")) == []


def test_cancelled_status_recurrence_id_and_missing_dtstart_are_skipped():
    data = cal(
        "DTSTART:20261005T170000Z\nSTATUS:CANCELLED\nSUMMARY:cancelled",
        "DTSTART:20261006T170000Z\nRECURRENCE-ID:20261006T170000Z\nSUMMARY:override",
        "SUMMARY:no start",
        "DTSTART:20261007T170000Z\nSUMMARY:kept",
    )
    assert [e.summary for e in parse_ics(data)] == ["kept"]


def test_garbage_gives_an_empty_list():
    assert parse_ics(b"this is not a calendar") == []
    assert parse_ics(b"") == []
    assert parse_ics(b"\x00\xff\xfe") == []


def test_a_bad_event_does_not_hide_the_good_ones():
    data = cal("DTSTART:garbage\nSUMMARY:bad", "DTSTART:20261007T170000Z\nSUMMARY:good")
    assert [e.summary for e in parse_ics(data)] == ["good"]


def test_events_are_capped():
    events = [f"DTSTART:2026100{i % 9 + 1}T170000Z\nSUMMARY:e{i}" for i in range(MAX_EVENTS + 4)]
    out = parse_ics(cal(*events))
    assert len(out) == MAX_EVENTS
    assert [e.summary for e in out] == [f"e{i}" for i in range(MAX_EVENTS)]
    assert len(parse_ics(cal(*events), max_events=2)) == 2


def test_fields_are_length_capped():
    (ev,) = parse_ics(cal("DTSTART:20261005T170000Z\nSUMMARY:" + "s" * 900 + "\nDESCRIPTION:" + "d" * 5000))
    assert len(ev.summary) == 300 and len(ev.description) == 2000
