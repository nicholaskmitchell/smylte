"""`titledates.strip_dates`: a date phrase leaves the title only when the
extraction carries the same date elsewhere."""
from __future__ import annotations

import time
from datetime import date

import pytest

from smylted.mail.titledates import strip_dates

ANCHOR = date(2026, 10, 12)         # a Monday

# (title, ISO dates the extraction carries, expected title or None for unchanged)
CASES = [
    ("RSVP by Nov 1st", ["2026-11-01"], "RSVP"),
    ("RSVP to Emil's party by Nov 1st", ["2026-11-01"], "RSVP to Emil's party"),
    ("RSVP by Nov 1st for Sam's wedding", ["2026-11-01"], "RSVP for Sam's wedding"),
    ("Submit Essay 3 (due Oct 20)", ["2026-10-20"], "Submit Essay 3"),
    ("Submit Essay 3 (due Oct 20, worth 10%)", ["2026-10-20"], "Submit Essay 3 (worth 10%)"),
    ("Submit Essay 3 due Oct 20 at 11:59pm", ["2026-10-20"], "Submit Essay 3"),
    ("Pay invoice PH-77102 by 10 October 2026", ["2026-10-10"], "Pay invoice PH-77102"),
    ("Parent evening, Thursday 8 October, 19:00", ["2026-10-08"], "Parent evening"),
    ("Read chapters 1-3 before Tuesday's lecture", ["2026-10-13"], None),
    ("Comment on Nov 1 draft", ["2026-11-01"], None),
    ("Call Sam on Monday", ["2026-10-19"], "Call Sam"),
    ("Book table for Saturday", ["2026-10-17"], None),
    ("Nov 1: RSVP to party", ["2026-11-01"], "RSVP to party"),
    ("Due Friday: Essay 3", ["2026-10-16"], "Essay 3"),
    ("Unterschrift bis 2. Oktober abgeben", ["2026-10-02"], "Unterschrift abgeben"),
    ("Zählerstand bis 10.10.2026 melden", ["2026-10-10"], "Zählerstand melden"),
    ("Elternabend am 08.10.2026", ["2026-10-08"], "Elternabend"),
    ("Elternabend Klasse 3b - Do, 08.10.2026, 19:30 Uhr", ["2026-10-08"], "Elternabend Klasse 3b"),
    ("Zahnarzt am Di, 13.10.", ["2026-10-13"], "Zahnarzt"),
    ("Return the drill by Friday", ["2026-10-16"], "Return the drill"),
    ("Return the drill by Friday", ["2026-11-20"], None),
    ("Pay rent for November", ["2026-11-01"], None),
    ("Plan Mother's Day brunch on May 10", ["2027-05-10"], "Plan Mother's Day brunch"),
    ("Finish slides by 4pm", ["2026-10-12"], None),
    ("Water plants 10-17 Oct", ["2026-10-10"], None),
    ("Reply to Dan by tomorrow morning", ["2026-10-13"], "Reply to Dan"),
    ("Submit form by end of week", ["2026-10-16"], "Submit form"),
    ("Bring cake on Sat", ["2026-10-17"], "Bring cake"),
    ("Take Ben to school tomorrow", ["2026-10-13"], "Take Ben to school"),
    ("Sign SOW for Acme by Oct 23, 2026", ["2026-10-23"], "Sign SOW for Acme"),
    ("Sign SOW for Acme by Oct 23, 2027", ["2026-10-23"], None),
    ("Pay EUR 45 deposit to Felix by Wed 7 Oct", ["2026-10-07"], "Pay EUR 45 deposit to Felix"),
    ("Return books by the 15th", ["2026-10-15"], "Return books"),
    ("Mark attendance on 3/4", ["2027-03-04"], "Mark attendance"),
    ("Q3 report – due 30.09.", ["2026-09-30"], "Q3 report"),
    ("Meet at 8 am Friday", ["2026-10-16"], None),
    ("Buy TV on Black Friday", ["2026-11-27"], None),
    ("Dentist appointment - Tue 6 Oct 10:30", ["2026-10-06"], "Dentist appointment"),
    ("Mia dental appointment (Wed 7 Oct, 15:30)", ["2026-10-07"], "Mia dental appointment"),
    ("Book flights by 15 Oct for the Nov 1 trip", ["2026-10-15"], "Book flights for the Nov 1 trip"),
    ("Submit abstract by Oct. 20th, 2026 at 5 p.m.", ["2026-10-20"], "Submit abstract"),
    ("Wahlunterlagen bis spätestens 23.10. einreichen", ["2026-10-23"], "Wahlunterlagen einreichen"),
    ("Arrive by 9.30 am", ["2026-10-13"], None),
    ("Be at the gate by 7.45 pm on Friday", ["2026-10-16"], "Be at the gate"),
    ("Increase prices by 2.5% by Nov 1", ["2026-11-01"], "Increase prices by 2.5%"),
    ("Cut AWS costs by 1.5 percent by Oct 30", ["2026-10-30"], "Cut AWS costs by 1.5 percent"),
    ("Update API clients before 2.0 release by Nov 1", ["2026-11-01"], "Update API clients before 2.0 release"),
    ("Migrate off Node before 18.20 EOL by Oct 30", ["2026-10-30"], "Migrate off Node before 18.20 EOL"),
    ("Defer payment until the 4th quarter", ["2026-11-04"], None),
    ("Meet by the 2nd floor elevator on Friday", ["2026-10-16"], "Meet by the 2nd floor elevator"),
    ("Pay fee (by Oct 20, EUR 45)", ["2026-10-20"], "Pay fee (EUR 45)"),
    ("Practice test – SAT", ["2026-10-17"], None),
    ("Study plan: SAT", ["2026-10-17"], None),
    ("Prep course (SAT)", ["2026-10-17"], None),
    ("Plan next week", ["2026-10-19"], None),
    ("Finish by 11:59 pm on Oct 20", ["2026-10-20"], "Finish"),
    ("Do not deposit the check before Oct 20", ["2026-10-20"], None),
    ("Email May by Friday", ["2026-10-16"], "Email May"),
    ("Thank May on Monday", ["2026-10-19"], "Thank May"),
    ("Monday.com onboarding call", ["2026-10-19"], None),
    ("RSVP by May", ["2027-05-01"], None),
    ("Version 2.0 release", ["2026-10-12"], None),
    ("Take medicine 3.5 mg", ["2026-10-12"], None),
    ("Order 2/3 of supplies", ["2027-02-03"], None),
    ("Sign up by 5 people", ["2026-10-12"], None),
    ("Upgrade to Windows 11 by 2025", ["2026-10-12"], None),
    ("Ben morgen früh zur Schule bringen", ["2026-10-13"], None),
    ("Rückmeldung bis Freitag geben", ["2026-10-16"], "Rückmeldung geben"),
    ("Kuchen bis morgen früh backen", ["2026-10-13"], "Kuchen backen"),
    ("Steuererklärung bis Ende der Woche", ["2026-10-16"], "Steuererklärung"),
    ("Call bank today", ["2026-10-12"], "Call bank"),
    ("RSVP", ["2026-11-01"], None),
    ("by Friday", ["2026-10-16"], None),
    ("Submit Essay 3 by Oct 20th.", ["2026-10-20"], "Submit Essay 3."),
    ("RSVP to Emil's party by Nov 1st!", ["2026-11-01"], "RSVP to Emil's party!"),
    ("Pay invoice by 10/20/2026.", ["2026-10-20"], "Pay invoice."),
    ("Submit by Friday?", ["2026-10-16"], "Submit?"),
    ("Return books by the 15th of November", ["2026-10-15"], None),
    ("Return books by the 15th of November", ["2026-11-15"], "Return books"),
    ("Register for Leaders of Tomorrow", ["2026-10-14"], None),
    ("Watch The Day After Tomorrow", ["2026-10-13"], None),
    ("Sag Oma Guten Morgen", ["2026-10-13"], None),
    ("Bring the snack list for tomorrow", ["2026-10-13"], "Bring the snack list"),
    ("Prepare for tomorrow", ["2026-10-13"], "Prepare"),
    ("Plan for tonight", ["2026-10-12"], "Plan"),
    ("Kuchen für morgen", ["2026-10-13"], "Kuchen"),
    ("Tomorrow: dentist", ["2026-10-13"], "Dentist"),
    ("Friday: submit essay", ["2026-10-16"], "Submit essay"),
    ("Call bank today.", ["2026-10-12"], "Call bank."),
    ("Call Mom on Sunday.", ["2026-10-18"], "Call Mom."),
    ("Essay (worth 10%, due Oct 20)", ["2026-10-20"], "Essay (worth 10%)"),
    ("Mark 3 essays", ["2026-10-13"], None),
    ("Leaders of Tomorrow.", ["2026-10-13"], None),
    ("Friday: eBay listing", ["2026-10-16"], "eBay listing"),
    ("Tomorrow: iPhone pickup", ["2026-10-13"], "iPhone pickup"),
    ("Start diet from tomorrow", ["2026-10-13"], None),
    ("Neue Busroute ab morgen", ["2026-10-13"], None),
    ("Call the day after tomorrow", ["2026-10-14"], None),
    ("Bring cake on Sat.", ["2026-10-17"], "Bring cake"),
]


@pytest.mark.parametrize("title,dates,expected", CASES)
def test_strip_dates(title, dates, expected):
    got = strip_dates(title, [date.fromisoformat(d) for d in dates], ANCHOR)
    assert got == (title if expected is None else expected)


def test_no_dates_leaves_the_title_unchanged():
    assert strip_dates("RSVP by Nov 1st", [], ANCHOR) == "RSVP by Nov 1st"
    assert strip_dates("RSVP by Nov 1st", [None, None], ANCHOR) == "RSVP by Nov 1st"
    assert strip_dates("Submit the essay", [date(2026, 10, 20)], ANCHOR) == "Submit the essay"


def test_date_ish_input_is_fast():
    tokens = "by Oct 1 the 1st on Friday , - ( ) 10.10. at 5pm bis am due tomorrow x".split()
    dates = [date(2026, 10, 16), date(2026, 10, 1)]
    start = time.perf_counter()
    for i in range(1000):
        text = " ".join(tokens[(i + j) % len(tokens)] for j in range(60))[:200]
        strip_dates(text, dates, ANCHOR)
    assert time.perf_counter() - start < 5
