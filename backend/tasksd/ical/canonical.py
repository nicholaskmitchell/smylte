"""An independent iCalendar content-line parser, used to *judge* round-trip
fidelity without letting the library under test grade its own work.

It implements just enough of RFC 5545 line handling — unfolding, quoted-parameter
splitting, BEGIN/END nesting — to build a normalized component tree and derive
order-independent signatures and property multisets for comparison.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

# A normalized property: (NAME, sorted ((paramname, paramvalue) ...), value).
Prop = tuple[str, tuple[tuple[str, str], ...], str]


def unfold(text: str) -> list[str]:
    """Normalize line endings and unfold RFC 5545 continuation lines."""
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    for line in raw:
        if lines and line[:1] in (" ", "\t"):
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return [ln for ln in lines if ln]


def _split_semicolons(head: str) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    in_quote = False
    for ch in head:
        if ch == '"':
            in_quote = not in_quote
            cur.append(ch)
        elif ch == ";" and not in_quote:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _unquote(v: str) -> str:
    return v[1:-1] if len(v) >= 2 and v[0] == '"' and v[-1] == '"' else v


def split_line(line: str) -> tuple[str, tuple[tuple[str, str], ...], str]:
    """'DUE;VALUE=DATE:20260101' -> ('DUE', (('VALUE','DATE'),), '20260101')."""
    in_quote = False
    colon = -1
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        elif ch == ":" and not in_quote:
            colon = i
            break
    if colon == -1:
        return line.upper(), (), ""
    parts = _split_semicolons(line[:colon])
    name = parts[0].upper()
    params: list[tuple[str, str]] = []
    for p in parts[1:]:
        k, sep, v = p.partition("=")
        params.append((k.upper(), _unquote(v) if sep else ""))
    return name, tuple(sorted(params)), line[colon + 1 :]


@dataclass
class Comp:
    name: str
    props: list[Prop] = field(default_factory=list)
    children: list["Comp"] = field(default_factory=list)


# Properties whose value is an unordered set of ';'-separated parts (RFC 5545
# §3.3.10). Reordering these is semantically identical, so we canonicalize by
# sorting the parts before comparison — otherwise a serializer that reorders
# RRULE parts looks like a fidelity loss when it is not.
_UNORDERED_VALUE = frozenset({"RRULE", "EXRULE"})


def _norm_value(name: str, value: str) -> str:
    if name in _UNORDERED_VALUE and ";" in value:
        return ";".join(sorted(value.split(";")))
    return value


def parse(text: str) -> Comp:
    """Parse into a component tree. The synthetic ROOT holds the VCALENDAR(s)."""
    root = Comp("ROOT")
    stack = [root]
    for ln in unfold(text):
        name, params, value = split_line(ln)
        if name == "BEGIN":
            child = Comp(value.upper())
            stack[-1].children.append(child)
            stack.append(child)
        elif name == "END":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1].props.append((name, params, _norm_value(name, value)))
    return root


def signature(comp: Comp, *, drop: frozenset[str] = frozenset()) -> tuple:
    """Order-independent signature. Two components with the same signature carry
    the same properties, parameters, and subcomponents regardless of ordering.
    Property names in ``drop`` are ignored (e.g. the field we deliberately changed)."""
    props = Counter(p for p in comp.props if p[0] not in drop)
    kids = Counter(signature(c, drop=drop) for c in comp.children)
    return (comp.name, frozenset(props.items()), frozenset(kids.items()))


def flatten(comp: Comp, *, drop: frozenset[str] = frozenset()) -> Counter:
    """Multiset of (component_name, prop) over the whole tree — for diffing what
    a round-trip lost or added."""
    bag: Counter = Counter()
    for p in comp.props:
        if p[0] not in drop:
            bag[(comp.name, p)] += 1
    for child in comp.children:
        bag.update(flatten(child, drop=drop))
    return bag
