"""Owner-written rules that decide whether an email becomes a task or an event.

The owner chooses who decides: the model (it already proposes a kind with every
extraction) or these rules. A rule is one line:

    from:*.school.example subject:"parent evening" -> event
    subject:invoice -> task
    model:event has:time -> event
    has:time -event:...        (invalid — unknown field "event", refused on save)

Conditions are `[-]field:value`, all of which must hold (`-` negates one), then
`-> task` or `-> event` (`=>` is accepted too). Fields:

- `from:` a sender pattern — an address, a domain, or `*.domain`, with the
  same meaning as the sender lists (see `addresses`);
- `subject:` / `body:` case-insensitive text, quoted when it has spaces;
- `has:time`, `has:date`, `has:location` — what the extraction found;
- `model:task` / `model:event` — what the model proposed, so a rule can
  refine its answer or hand a case back to it.

Why a small validated language and not scripts: the rules are typed into a
web form, and a settings page that accepts code is a remote-code-execution
surface however carefully it is sandboxed. A declarative line can do nothing
but match, and it is checked when it is saved: a rule that does not parse is
refused with its number, so a typo is found on the settings page rather than
by an email silently filed as the wrong kind. That check is the type safety.

Why rules mode falls back to "task" when nothing matches: the outcome must be
predictable from the rules alone, and a task is the cheaper mistake (it does
not block out time). An owner who wants the model to settle the rest ends
the list with `model:event -> event`.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from . import addresses

FIELDS = ("from", "subject", "body", "has", "model")
HAS_VALUES = ("time", "date", "location")
KINDS = ("task", "event")
MAX_RULES = 100
MAX_CONDITIONS = 10
MAX_RULE_CHARS = 500
MAX_TEXT_CHARS = 200

_ARROWS = ("->", "=>")
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Condition:
    field: str        # one of FIELDS
    value: str        # from: normalized pattern; subject/body: casefolded text; has: one of HAS_VALUES; model: "task"|"event"
    negate: bool


@dataclass(frozen=True)
class KindRule:
    conditions: tuple[Condition, ...]
    kind: str         # "task" | "event"
    source: str       # canonical text


@dataclass(frozen=True)
class KindFacts:
    sender: str | None
    subject: str
    body: str
    model_kind: str   # what the model proposed
    has_time: bool    # event_start carries a time of day
    has_date: bool    # event_start or due present
    has_location: bool


def _tokens(text: str) -> list[str]:
    """Whitespace-separated tokens; a double-quoted run stays inside its token."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        start = i
        while i < n and not text[i].isspace():
            if text[i] == '"':
                i += 1
                while i < n and text[i] != '"':
                    i += 2 if text[i] == "\\" else 1
                if i >= n:
                    raise ValueError("a quoted value is not closed")
            i += 1
        out.append(text[start:i])
    return out


def _value(raw: str, field: str) -> str:
    """The text of a condition's value: one bare word or one quoted phrase."""
    if raw.startswith('"'):
        out: list[str] = []
        i = 1
        while i < len(raw) and raw[i] != '"':
            if raw[i] == "\\" and i + 1 < len(raw) and raw[i + 1] in '"\\':
                i += 1
            out.append(raw[i])
            i += 1
        if i != len(raw) - 1:
            raise ValueError(f'{field}: takes one word or one "quoted phrase"')
        return "".join(out)
    if '"' in raw:
        raise ValueError(f'{field}: takes one word or one "quoted phrase"')
    return raw


def _condition(token: str) -> Condition:
    negate = token.startswith("-")
    body = token[1:] if negate else token
    name, colon, raw = body.partition(":")
    if not colon or not name:
        raise ValueError(f"{token!r} is not a condition (write field:value, e.g. subject:invoice)")
    field = name.lower()
    if field not in FIELDS:
        raise ValueError(f"unknown field {name!r} (use from, subject, body, has or model)")
    value = _value(raw, field)
    if not value.strip():
        raise ValueError(f"{field}: needs a value")
    if field == "from":
        pattern = addresses.normalize_pattern(value)
        if pattern is None:
            raise ValueError(f"{value!r} is not an address, a domain, or *.domain")
        value = pattern
    elif field in ("subject", "body"):
        if len(value) > MAX_TEXT_CHARS:
            raise ValueError(f"{field}: text can be at most {MAX_TEXT_CHARS} characters")
        value = value.casefold()
    elif field == "has":
        value = value.lower()
        if value not in HAS_VALUES:
            raise ValueError("has: takes time, date or location")
    else:
        value = value.lower()
        if value not in KINDS:
            raise ValueError("model: takes task or event")
    return Condition(field, value, negate)


def _canonical(c: Condition) -> str:
    v = c.value
    # Quoted when a bare word could not carry it back through the parser.
    if not v or '"' in v or any(ch.isspace() for ch in v):
        v = '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"{'-' if c.negate else ''}{c.field}:{v}"


def parse_rule(text: str) -> KindRule:
    """One rule line, parsed and canonicalised. ValueError names the problem."""
    line = (text or "").strip()
    if len(line) > MAX_RULE_CHARS:
        raise ValueError(f"a rule can be at most {MAX_RULE_CHARS} characters")
    tokens: list[str] = []
    for tok in _tokens(line):
        if tok[:2] in _ARROWS and len(tok) > 2:      # "->event" written without a space
            tokens.extend((tok[:2], tok[2:]))
        else:
            tokens.append(tok)
    arrows = [i for i, tok in enumerate(tokens) if tok in _ARROWS]
    if len(arrows) != 1 or arrows[0] != len(tokens) - 2:
        raise ValueError('a rule ends with "-> task" or "-> event"')
    kind = tokens[-1].lower()
    if kind not in KINDS:
        raise ValueError(f"{tokens[-1]!r} is not task or event")
    conds = tokens[:-2]
    if not conds:
        raise ValueError("a rule needs at least one condition before ->")
    if len(conds) > MAX_CONDITIONS:
        raise ValueError(f"a rule can have at most {MAX_CONDITIONS} conditions")
    conditions = tuple(_condition(tok) for tok in conds)
    source = " ".join(_canonical(c) for c in conditions) + f" -> {kind}"
    return KindRule(conditions, kind, source)


def _skipped(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def check_rules(lines: Iterable[str]) -> list[str]:
    """The canonical text of every rule; blank lines and `#` comments dropped.

    Raises ValueError("rule N: …"), N counting the non-blank lines from 1, at
    the first line that is not a rule — the whole list is refused, so a saved
    list is always one that `load_rules` reads completely.
    """
    out: list[str] = []
    n = 0
    for line in lines:
        if isinstance(line, str) and not line.strip():
            continue
        n += 1
        if not isinstance(line, str):
            raise ValueError(f"rule {n}: a rule must be text")
        if _skipped(line):
            continue
        if len(out) >= MAX_RULES:
            raise ValueError(f"rule {n}: no more than {MAX_RULES} rules are allowed")
        try:
            out.append(parse_rule(line).source)
        except ValueError as exc:
            raise ValueError(f"rule {n}: {exc}") from None
    return out


def load_rules(lines: Iterable[str]) -> list[KindRule]:
    """The rules among `lines`, skipping any that do not parse. Never raises."""
    out: list[KindRule] = []
    for line in lines or ():
        if not isinstance(line, str) or _skipped(line):
            continue
        try:
            out.append(parse_rule(line))
        except ValueError:
            continue
        if len(out) >= MAX_RULES:
            break
    return out


class _Text:
    """Subject and body casefolded once per decision, with whitespace runs
    collapsed so a phrase still matches where the mail client wrapped it."""

    def __init__(self, facts: KindFacts):
        self.subject = _WS.sub(" ", (facts.subject or "").casefold())
        self.body = _WS.sub(" ", (facts.body or "").casefold())


def _holds(c: Condition, facts: KindFacts, text: _Text) -> bool:
    if c.field == "from":
        return addresses.matches(facts.sender or "", c.value)
    if c.field == "subject":
        return _WS.sub(" ", c.value) in text.subject
    if c.field == "body":
        return _WS.sub(" ", c.value) in text.body
    if c.field == "has":
        return {"time": facts.has_time, "date": facts.has_date,
                "location": facts.has_location}[c.value]
    return facts.model_kind == c.value


def decide(mode: str, rules: Sequence[KindRule], facts: KindFacts) -> tuple[str, str]:
    """`(kind, why)` — the kind for this extraction and a reason for the ledger."""
    if mode == "rules":
        text = _Text(facts)
        for rule in rules:
            if all(_holds(c, facts, text) != c.negate for c in rule.conditions):
                return rule.kind, f"rule: {rule.source}"
        return "task", "no rule matched"
    kind = facts.model_kind if facts.model_kind in KINDS else "task"
    return kind, f"the model chose {kind}"
