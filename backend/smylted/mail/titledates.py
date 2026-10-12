"""Take dates out of a suggestion's title when the suggestion already has them.

The owner wants the deadline in the due field, not "RSVP by Nov 1st" as the
title. The extraction prompt says so, and this is the backstop for a model that
writes one anyway: `strip_dates` removes a deadline or date phrase ("by Nov
1st", "(due Oct 20)", ", Thursday 8 October, 19:00", "bis 2. Oktober", "Nov 1:")
from a title, English or German.

It removes a phrase only when the phrase names a date the extraction also
carries (its due, or its event's start or end), so a title never loses a date
that is nowhere else, and a phrase that merely looks like a date stays: "by
2.5%", "before 2.0 release", "SAT prep", "the 4th quarter". Calendar dates are
compared by day and month (and year when the phrase has one); weekdays and words
like "tomorrow" or "end of week" are compared against the sent date. A title
with a negation is left alone, because "do not deposit the check" is a different
task from "do not deposit the check before Oct 20", and so is a title that would
end up with fewer than three letters. Times go with the date they follow; a bare
time ("by 4pm") stays.

The patterns are bounded and anchored, and the input is a title `llm._title`
has already collapsed and cut to 200 characters: a few milliseconds at worst.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import date

_MONTHS = {
    "jan": 1, "january": 1, "januar": 1, "feb": 2, "february": 2, "februar": 2,
    "mar": 3, "march": 3, "märz": 3, "maerz": 3, "apr": 4, "april": 4, "may": 5, "mai": 5,
    "jun": 6, "june": 6, "juni": 6, "jul": 7, "july": 7, "juli": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "okt": 10, "oktober": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12, "dez": 12, "dezember": 12,
}
_WEEKDAYS = {
    "mon": 0, "monday": 0, "montag": 0, "tue": 1, "tues": 1, "tuesday": 1, "dienstag": 1,
    "wed": 2, "wednesday": 2, "mittwoch": 2, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "donnerstag": 3, "fri": 4, "friday": 4, "freitag": 4, "sat": 5, "saturday": 5, "samstag": 5,
    "sonnabend": 5, "sun": 6, "sunday": 6, "sonntag": 6,
}
_DAY_WORDS = {"today": 0, "tonight": 0, "heute": 0, "tomorrow": 1, "morgen": 1, "übermorgen": 2}



def _alt(words: Iterable[str]) -> str:
    return "|".join(sorted((re.escape(w) for w in words), key=len, reverse=True))

_MONTH = rf"(?:{_alt(_MONTHS)})\.?"
_WEEKDAY = rf"(?:{_alt(_WEEKDAYS)})\.?"
_WD_PREFIX = rf"(?:{_WEEKDAY}|(?:mo|di|mi|do|fr|sa|so)\.?)"
_DAY = r"\d{1,2}(?!\d)(?:st|nd|rd|th|\.)?"
_YEAR = r"(?:,?\s*\d{4})?"
# A numeric date needs a second separator: "30.09.", "8.10.2026", "10/20", "10/20/26".
# "9.30" and "2.5" are a time and a number, never a date.
_NUMERIC = r"\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.(?:\d{2,4})?|\d{1,2}/\d{1,2}(?:/\d{2,4})?"
_CAL = (rf"(?:{_MONTH}\s*{_DAY}{_YEAR}|{_DAY}\s*(?:of\s+)?{_MONTH}{_YEAR}|{_NUMERIC}"
        r"|the\s+\d{1,2}(?:st|nd|rd|th)(?=\s*(?:$|[,;:)\]]|of\b|at\b|um\b)))")
_RELATIVE = (rf"(?:{_alt(_DAY_WORDS)}|eod|eow|end\s+of\s+(?:the\s+|this\s+|next\s+)?(?:day|week|month)"
             r"|ende\s+(?:der|dieser|nächster)\s+woche"
             rf"|(?:this|next|nächste[nrs]?|diese[nrs]?)\s+(?:week|month|woche|monat|{_WEEKDAY}))")
_PART = r"(?:\s+(?:morning|afternoon|evening|night|früh|vormittag|nachmittag|abend))?"
_DATE = rf"(?:(?:(?:the\s+)?(?:{_WD_PREFIX},?\s*)?{_CAL}|{_RELATIVE}|{_WEEKDAY}){_PART})"
_TIME_CORE = (r"(?:\d{1,2}(?:[:.]\d{2})?\s*(?:[ap]\.?m\.?)|\d{1,2}:\d{2}(?:\s*uhr)?|\d{1,2}\s*uhr"
              r"|noon|midnight)")
_TIME = rf"(?:,?\s*(?:at\s+|um\s+|@\s*)?{_TIME_CORE})?"
_TRIGGER = (r"(?:no\s+later\s+than|due(?:\s+(?:by|on|date))?|deadline:?|by|before|until|till"
            r"|bis(?:\s+spätestens)?(?:\s+zum)?|spätestens(?:\s+(?:am|bis|zum))?|fällig(?:\s+(?:am|bis))?)")
_END = r"(?![\w'’%])"
_SEP = r"(?:\s*[,;:]\s*|\s+[–—-]\s+)"
_PHRASE = rf"{_DATE}{_TIME}"
_PHRASE_AFTER_TRIGGER = rf"(?:{_TIME_CORE},?\s+(?:on\s+|am\s+)?)?{_PHRASE}"

_I = re.I
_BRACKETED = re.compile(rf"\s*[(\[]\s*(?:{_TRIGGER}\s+)?(?P<d>{_PHRASE_AFTER_TRIGGER})\s*[)\]]", _I)
_TRIGGERED = re.compile(rf"(?:{_SEP})?\s*\b{_TRIGGER}\s+(?P<d>{_PHRASE_AFTER_TRIGGER}){_END}", _I)
_TRAILING = re.compile(
    rf"(?:{_SEP}(?:(?:on|am)\s+)?|\s+on\s+|\s+am\s+(?=(?:{_WD_PREFIX},?\s*)?\d))"
    rf"(?P<d>{_PHRASE}){_END}\s*[.!?]?\s*$"
    rf"|\s+(?:(?:for|für)\s+)?(?P<r>{_alt(_DAY_WORDS)}){_PART}{_TIME}\s*[.!?]?\s*$", _I)
_LEADING = re.compile(rf"^\s*(?:{_TRIGGER}\s+)?(?P<d>{_PHRASE})(?P<r>)\s*[:–—-]\s+", _I)
# A full stop that ends a date or time rather than the title.
_DATE_DOT = re.compile(r"(?:\d|\b[ap]\.?m|\b[^\W\d_]{2,4})\.$", _I)
_NEGATION = re.compile(r"\b(?:not|never|nicht|nie|kein\w*)\b|n['’]t\b", _I)

_ISO_P = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DOT_P = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})?")
_SLASH_P = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?")
_MD_P = re.compile(rf"({_alt(_MONTHS)})\.?\s*(\d{{1,2}})(?![\d:])(?:st|nd|rd|th|\.)?(?:,?\s*(\d{{4}}))?", _I)
_DM_P = re.compile(rf"(?<![\d:.])(\d{{1,2}})(?:st|nd|rd|th|\.)?\s*(?:of\s+)?({_alt(_MONTHS)})\.?(?:,?\s*(\d{{4}}))?", _I)
# "the 15th" alone; "the 15th of November" is a day and a month, read by _DM_P.
_NTH_P = re.compile(rf"the\s+(\d{{1,2}})(?:st|nd|rd|th)(?!\s*(?:of\s+)?(?:{_alt(_MONTHS)}))", _I)
_WD_P = re.compile(rf"\b({_alt(_WEEKDAYS)})\b\.?", _I)
_DAYWORD_P = re.compile(rf"\b({_alt(_DAY_WORDS)})\b", _I)


def _year_ok(text: str | None, day: date) -> bool:
    if not text:
        return True
    year = int(text)
    return (year + 2000 if year < 100 else year) == day.year


def _means(phrase: str, targets: list[date], anchor: date) -> bool:
    """Does `phrase` name one of `targets`? Calendar dates by day and month (and
    year if given); weekdays and relative words within two weeks of `anchor`."""
    def any_md(month: int, day: int, year: str | None) -> bool:
        return any(t.month == month and t.day == day and _year_ok(year, t) for t in targets)

    if any(t.isoformat() == m.group(0) for m in _ISO_P.finditer(phrase) for t in targets):
        return True
    calendar = False
    for m in _DOT_P.finditer(phrase):
        calendar = True
        if any_md(int(m.group(2)), int(m.group(1)), m.group(3)):
            return True
    for m in _SLASH_P.finditer(phrase):
        calendar = True
        a, b = int(m.group(1)), int(m.group(2))
        if any_md(a, b, m.group(3)) or any_md(b, a, m.group(3)):
            return True
    for m in _MD_P.finditer(phrase):
        calendar = True
        if any_md(_MONTHS.get(m.group(1).casefold(), 0), int(m.group(2)), m.group(3)):
            return True
    for m in _DM_P.finditer(phrase):
        calendar = True
        if any_md(_MONTHS.get(m.group(2).casefold(), 0), int(m.group(1)), m.group(3)):
            return True
    for m in _NTH_P.finditer(phrase):
        calendar = True
        if any(t.day == int(m.group(1)) for t in targets):
            return True
    if calendar or _ISO_P.search(phrase):
        return False
    near = [t for t in targets if 0 <= (t - anchor).days <= 14]
    m = _DAYWORD_P.search(phrase)
    if m:
        ahead = _DAY_WORDS.get(m.group(1).casefold(), 0)
        return any(abs((t - anchor).days - ahead) <= 1 for t in targets)
    m = _WD_P.search(phrase)
    if m:
        word = m.group(1)
        if word.isupper() and len(word) <= 3:          # "SAT" is a test, not a Saturday
            return False
        return any(t.weekday() == _WEEKDAYS.get(word.casefold(), -1) for t in near)
    # "end of the week", "next month", "Ende der Woche": a span, not a day.
    days = 45 if re.search(r"month|monat", phrase, _I) else 14
    return any(0 <= (t - anchor).days <= days for t in targets)


def strip_dates(title: str, dates: Iterable[date | None], anchor: date) -> str:
    """`title` without the deadline or date phrases that name one of `dates`.

    A phrase goes only when it names a date the extraction also carries, so a
    title never loses a date that is nowhere else, and "by 2.5%" or "SAT prep"
    stay. A title with a negation is left alone ("do not deposit before Oct 20"
    is a different task without its date), and so is one that would end with
    fewer than three letters.
    """
    targets = [d for d in dates if d is not None]
    if not targets or _NEGATION.search(title):
        return title

    def cut(gap: str) -> Callable[[re.Match], str]:
        def replace(m: re.Match) -> str:
            phrase = m.group("d")
            if phrase is None:
                # A bare day word ends the title: "tomorrow" is a date,
                # "Leaders of Tomorrow" a name.
                phrase = m.group("r")
                if not phrase.islower():
                    return m.group(0)
            return gap if _means(phrase, targets, anchor) else m.group(0)
        return replace

    out = _LEADING.sub(cut(""), title)
    if out != title:
        out = out[:1].upper() + out[1:]       # "Friday: submit essay" -> "Submit essay"
    out = _BRACKETED.sub(cut(" "), out)
    out = _TRIGGERED.sub(cut(" "), out)
    out = _TRAILING.sub(cut(""), out)
    out = re.sub(r"([(\[])\s*[,;:]\s*", r"\1", out)
    out = re.sub(r"\s+([,;:.!?)\]])", r"\1", out)
    out = re.sub(r"\s+", " ", out).strip(" ,;:–—-")
    # The cut may take the title's closing mark with it ("on Sunday.", where
    # "Sunday." reads as an abbreviation): give it back, unless the full stop
    # belonged to the date itself ("30.09.", "Oct.", "5 p.m.").
    end = title.rstrip()[-1:]
    keep = end in ("!", "?") or (end == "." and not _DATE_DOT.search(title.rstrip()))
    if keep and not out.endswith(end):
        out += end
    if out == title.strip():
        return title
    return out if len(re.findall(r"[^\W\d_]", out)) >= 3 else title
