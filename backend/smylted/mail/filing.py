"""Which of the owner's lists a suggested task goes in, and its title without the class.

The owner keeps a list per class, team or project ("DC Psychology", "German
IV", "Yearbook") and names tasks the way the class does ("4.2 - Anxiety
Disorders"), so a suggestion that says "Complete assignment 4.2 for DC
Psychology" in the default list is two corrections they have to make by hand.
The extraction names the item's group (the class as the email names it) and
picks one of the owner's lists; `route` turns that into a list, and
`tidy_title` takes the class back out of a title that still carries it.

`route` decides in this order, first match wins:

1. a list whose name is the group, once both are normalised (case, spacing and
   punctuation ignored: "Dc Trigonometry" is "DC Trigonometry") — if exactly
   one list matches;
2. where the owner filed this group last time (`memory`, learned at approval
   from a list the owner chose on the card) — if that list still exists;
3. the model's pick — it sees the list names and can map "math" to "DC
   Trigonometry", which no string rule can;
4. the one list whose name the group is, plus a course number, level or a
   word for its members ("Personal Finance 614", "Yearbook Staff") — and
   nothing looser, so a short list name ("Home", "Work", "German IV") does not
   swallow a group that merely starts with the word ("Home and School
   Association", "German Club").

An exact name beats memory because a list made for the class after the owner
filed it elsewhere is the better answer; memory beats the model because it is
the owner's own correction. Nothing matching means no list: the suggestion
goes to the default list, as before.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

_NON_ALNUM = re.compile(r"[\W_]+")
_OPEN = "\"“„«"
_CLOSE = "\"”“»"
# The long form the owner objected to: a verb, perhaps "the"/"assignment" and
# a quoted name, then perhaps the class ('Complete assignment "4.2" for DC
# Psychology'), or the same unquoted ("Submit ... permission slip for German IV").
_VERB = r"(?:complete|submit|finish|do|turn\s+in|work\s+on|prepare\s+for|study\s+for|fill\s+out)"
_QUOTED = re.compile(
    r"^" + _VERB + r"\s+(?:the\s+)?(?:assignment\s+)?[" + _OPEN + r"](?P<name>.{3,}?)[" + _CLOSE + r"]"
    r"(?:\s+assignment)?(?P<rest>(?:\s+(?:for|in)\s.*)?)$", re.I)
_LEADING_VERB = re.compile(r"^" + _VERB + r"\s+(?:the\s+)?(?:assignment\s+)?(?=\S)", re.I)
# What may follow a list's name in a group that is still that class: a course
# number or level ("614", "2", "IV", "3b") or a word for the people in it.
_SUFFIX = re.compile(r"^(?:\d+[a-z]?|[ivx]+|staff|team|class|course|crew|squad)$")


def normalize(name: str | None) -> str:
    """`name` casefolded, with every run of punctuation and spaces one space."""
    return _NON_ALNUM.sub(" ", (name or "").casefold()).strip()


def _extends(group: str, name: str) -> bool:
    """Is `group` the list `name` plus one course number, level or "staff"?"""
    return bool(name) and group.startswith(name + " ") and bool(_SUFFIX.match(group[len(name) + 1:]))


def route(group: str, picked: str, lists: Sequence[tuple[str, str]],
          memory: Mapping[str, str]) -> tuple[str | None, str]:
    """The slug of the list for an item, and how it was chosen.

    `lists` is the owner's task lists as (slug, name); `picked` is the name
    the model chose ("" for none); `memory` maps a normalised group to a slug.
    Returns (None, "") when nothing fits.
    """
    g = normalize(group)
    slugs = {slug for slug, _ in lists}
    if g:
        same = [slug for slug, name in lists if normalize(name) == g]
        if len(same) == 1:
            return same[0], "name"
        remembered = memory.get(g)
        if remembered in slugs:
            return remembered, "remembered"
    if picked:
        chosen = [slug for slug, name in lists if name == picked]
        if len(chosen) == 1:
            return chosen[0], "model"
    if g:
        inside = [slug for slug, name in lists if _extends(g, normalize(name))]
        if len(inside) == 1:
            return inside[0], "contains"
    return None, ""


def _letters(text: str) -> int:
    return len(re.findall(r"[^\W\d_]", text))


def tidy_title(title: str, names: Iterable[str]) -> str:
    """`title` without a class name the list already carries.

    For each of `names` (the group and the routed list's name, with a course
    number allowed after it), this takes out a trailing "for <name>" and a
    leading "<name>:" — and, only when the title starts with a verb the owner
    drops (complete, submit, prepare for ...), that verb and a trailing
    "in <name>" too, and the quotes round a quoted name:
    'Complete assignment "4.2 - Anxiety Disorders" for DC Psychology' becomes
    "4.2 - Anxiety Disorders". A plain "in <name>" stays ("Careers in
    Forensics" is an assignment's name), and so does a leading subject word
    ("German Letter"): the prompt asks the model to drop that, and a rule
    here could not tell the two apart. A result with fewer than three letters
    keeps the original. Call it for coursework tasks only: for other mail the
    group is often what the task is about ("Send photo and bio for the Youth
    Voice Award").
    """
    out = title.strip()
    verb_led = bool(_LEADING_VERB.match(out))
    m = _QUOTED.match(out)
    if m:
        out = (m.group("name").strip() + m.group("rest")).strip()
    elif verb_led:
        out = out[_LEADING_VERB.match(out).end():]
        out = re.sub(r"[" + _OPEN + r"](.+?)[" + _CLOSE + r"]", r"\1", out)
    preps = "for|in" if verb_led else "for"
    for name in sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True):
        words = r"\s+".join(re.escape(w) for w in name.split())
        out = re.sub(rf"\s+(?:{preps})\s+(?:the\s+)?{words}(?:\s+class)?(?:\s+\d+[A-Za-z]?)?\s*$",
                     "", out, flags=re.I)
        lead = re.match(rf"^{words}(?:\s+\d+[A-Za-z]?)?\s*[:–—-]\s+(?=\S)", out, flags=re.I)
        if lead:
            out = out[lead.end():]
    out = out.strip(" ,;:–—-")
    if out[:1] in _OPEN and out[-1:] in _CLOSE and len(out) > 2:
        out = out[1:-1].strip()
    if out and out != title.strip() and out[0].islower() and out.split(" ", 1)[0].islower():
        out = out[0].upper() + out[1:]
    return out if _letters(out) >= 3 else title
