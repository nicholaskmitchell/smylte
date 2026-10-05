"""Authentication-Results: did a server we trust see this sender authenticate?

The allow list ("always read mail from school.org") is only worth having if a
stranger cannot put `From: office@school.org` on a message and inherit the
school's standing. The From header is whatever the sender typed; the evidence
that it is true is what the receiving server recorded when the message
arrived — DMARC, SPF and DKIM verdicts in `Authentication-Results` headers
(RFC 8601). This module reads those headers and turns them into one verdict.

Where the headers come from, and why only some of them count:

- Proton's inbound MTA writes one `Authentication-Results` header per method
  (`arc`, `dkim`, `spf`, `dmarc`), each with the authserv-id
  `mailinNNN.protonmail.ch`. Bridge passes the stored headers through in
  order, so they reach us at the top of the message.
- A sender can write any header it likes, including an
  `Authentication-Results` that says `dmarc=pass`. Only headers whose
  authserv-id is on the trusted list count; the default list is Proton's own
  domain and nothing broader.
- `ARC-Authentication-Results` is never read. ARC records what an earlier hop
  claims to have seen; believing it means believing that hop, and nothing here
  can tell a mailing list we trust from one we do not.

The parser is deliberately forgiving (a header it cannot read is skipped, never
raised on) and the verdict deliberately unforgiving: anything short of a clear,
aligned pass is "not verified", which in the pipeline means "treat as ordinary
mail" — the safe direction.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from . import addresses

DEFAULT_TRUSTED = ("protonmail.ch", "*.protonmail.ch")

_HEADER = "Authentication-Results"
_FOLD = re.compile(r"\r\n[ \t]*|\n[ \t]*|\r[ \t]*")


@dataclass(frozen=True)
class MethodResult:
    method: str                 # lower-case: "dmarc", "spf", "dkim", "arc", ...
    result: str                 # lower-case: "pass", "fail", "none", "softfail", ...
    props: dict[str, str]       # lower-cased keys ("header.from", "smtp.mailfrom", "header.d", ...); values unquoted, case kept


@dataclass(frozen=True)
class AuthResultsHeader:
    authserv_id: str            # lower-case
    results: tuple[MethodResult, ...]


@dataclass(frozen=True)
class Verdict:
    passed: bool
    method: str | None          # "dmarc" | "dkim" | "spf" | None
    reason: str                 # a short sentence for the ledger


def strip_comments(value: str) -> str:
    """`value` without RFC 5322 comments.

    Comments nest and honour backslash escapes; parentheses inside a
    double-quoted string are text, not comments. Each comment becomes one
    space rather than nothing, because a comment is folding whitespace in the
    grammar: `spf=pass(ok)smtp.mailfrom=a.org` is two tokens. An unbalanced
    `(` swallows the rest of the value — a guess at where it should have
    ended would be a guess at what the server meant.
    """
    out: list[str] = []
    depth = 0
    in_quote = False
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        if depth:
            if ch == "\\":
                i += 2
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if not depth:
                    out.append(" ")
            i += 1
            continue
        if in_quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(value[i + 1])
                i += 2
                continue
            if ch == '"':
                in_quote = False
            i += 1
            continue
        if ch == '"':
            in_quote = True
            out.append(ch)
        elif ch == "(":
            depth = 1
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _split_outside_quotes(value: str, sep: str) -> list[str]:
    """Split on `sep`, leaving separators inside double quotes alone."""
    parts: list[str] = []
    cur: list[str] = []
    in_quote = False
    i = 0
    while i < len(value):
        ch = value[i]
        if in_quote and ch == "\\" and i + 1 < len(value):
            cur.append(value[i:i + 2])
            i += 2
            continue
        if ch == '"':
            in_quote = not in_quote
        if ch == sep and not in_quote:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def _tokens(segment: str) -> list[str]:
    """Whitespace-separated tokens; a double-quoted run stays inside its token."""
    out: list[str] = []
    cur: list[str] = []
    in_quote = False
    i = 0
    while i < len(segment):
        ch = segment[i]
        if in_quote and ch == "\\" and i + 1 < len(segment):
            cur.append(segment[i:i + 2])
            i += 2
            continue
        if ch == '"':
            in_quote = not in_quote
        if ch.isspace() and not in_quote:
            if cur:
                out.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
        i += 1
    if cur:
        out.append("".join(cur))
    return out


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return re.sub(r"\\(.)", r"\1", value[1:-1])
    return value


def parse_header(value: str) -> AuthResultsHeader | None:
    """One `Authentication-Results` value, parsed; None when it has no authserv-id.

    A result segment that does not start with `method=result` is skipped
    rather than failing the header: one odd method from a server must not hide
    the dmarc verdict next to it.
    """
    text = strip_comments(_FOLD.sub(" ", value or ""))
    segments = _split_outside_quotes(text, ";")
    head = segments[0].split()
    if not head:
        return None
    authserv_id = head[0].lower()      # a trailing version number is ignored
    results: list[MethodResult] = []
    for segment in segments[1:]:
        seg = segment.strip()
        if not seg or seg.lower() == "none":
            continue
        tokens = _tokens(seg)
        method, eq, result = tokens[0].partition("=")
        method = method.split("/", 1)[0].strip().lower()
        result = _unquote(result.strip()).lower()
        if not eq or not method or not result:
            continue
        props: dict[str, str] = {}
        for token in tokens[1:]:
            key, eq, val = token.partition("=")
            if not eq or not key:
                continue
            props.setdefault(key.lower(), _unquote(val))
        results.append(MethodResult(method, result, props))
    return AuthResultsHeader(authserv_id, tuple(results))


def collect(headers) -> list[AuthResultsHeader]:
    """Every `Authentication-Results` header of `headers`, parsed, topmost first.

    `get_all` matches the whole header name, so `ARC-Authentication-Results`
    never comes back from it — by design (see the module docstring).
    """
    try:
        values = headers.get_all(_HEADER, []) or []
    except Exception:  # noqa: BLE001 — a malformed header block means "no evidence"
        return []
    out: list[AuthResultsHeader] = []
    for v in values:
        try:
            parsed = parse_header(str(v))
        except Exception:  # noqa: BLE001 — one unreadable header is skipped, not fatal
            continue
        if parsed is not None:
            out.append(parsed)
    return out


def trusted_only(parsed: list[AuthResultsHeader], trusted_ids) -> list[AuthResultsHeader]:
    """The headers written by a server on the trusted list.

    The authserv-id is compared as a domain with the sender-pattern rules of
    `addresses`: `protonmail.ch` is that id only, `*.protonmail.ch` its
    subdomains. An id that is not a well-formed domain is never trusted.
    """
    patterns = []
    for p in trusted_ids or ():
        norm = addresses.normalize_pattern(p) if isinstance(p, str) else None
        if norm is not None and "@" not in norm:
            patterns.append(norm)
    out = []
    for h in parsed:
        d = addresses.normalize_domain(h.authserv_id)
        if d is not None and any(addresses.matches("x@" + d, p) for p in patterns):
            out.append(h)
    return out


def authserv_ids(headers) -> list[str]:
    """The distinct authserv-ids of every `Authentication-Results` header, in order."""
    seen: list[str] = []
    for h in collect(headers):
        if h.authserv_id not in seen:
            seen.append(h.authserv_id)
    return seen


def _same_domain(a: str | None, b: str | None) -> bool:
    da = addresses.normalize_domain(a or "")
    return da is not None and da == addresses.normalize_domain(b or "")


def verify_sender(headers, from_addr: str | None, from_count: int,
                  trusted_ids: Iterable[str]) -> Verdict:
    """Did a trusted server authenticate `from_addr`'s domain for this message?

    The rules, in order:

    1. Exactly one From address. With two, "the sender" is ambiguous and DMARC
       itself declines to evaluate the message.
    2. Only `Authentication-Results` headers with a trusted authserv-id count
       (a sender can write any header it likes). None → not verified.
    3. DMARC first, because it is the one result that already answers the
       question asked here: does the From domain's owner vouch for this
       message. It passes only when EVERY trusted dmarc result is `pass` and
       each that names `header.from` names the From domain. Requiring all of
       them means a forged "pass" header carrying a trusted id cannot outvote
       Proton's own non-pass; any `fail` ends it. A pass for a different
       domain than From is refused outright rather than falling back.
    4. Without a DMARC verdict (none, temperror, a mix), an aligned DKIM pass,
       else an aligned SPF pass (every spf result passing, at least one with
       an aligned `smtp.mailfrom`). This is DMARC's own logic, run here
       because a domain without a DMARC record still signs and publishes SPF.

    Residual risk: if Proton ever omitted its own dmarc result, a forged header
    with a trusted id would be believed. That is why the default trust list is
    Proton's domain and nothing broader, and why ARC results are never read.
    """
    if from_count != 1 or not from_addr:
        return Verdict(False, None, "the From header must name exactly one address")
    dom = addresses.domain_of(from_addr)
    hs = trusted_only(collect(headers), trusted_ids)
    if not hs:
        return Verdict(False, None, "no Authentication-Results from a trusted server")

    dmarc = [r for h in hs for r in h.results if r.method == "dmarc"]
    if dmarc:
        def from_ok(r: MethodResult) -> bool:
            hf = r.props.get("header.from")
            return hf is None or _same_domain(hf, dom)

        if all(r.result == "pass" and from_ok(r) for r in dmarc):
            return Verdict(True, "dmarc",
                           f"dmarc=pass header.from={dom} ({hs[0].authserv_id})")
        if any(r.result == "fail" for r in dmarc):
            return Verdict(False, "dmarc", "dmarc=fail")
        if any(r.result == "pass" and not from_ok(r) for r in dmarc):
            return Verdict(False, "dmarc", "dmarc pass is for a different domain than From")

    for h in hs:
        for r in h.results:
            if r.method != "dkim" or r.result != "pass":
                continue
            d = r.props.get("header.d") or r.props.get("header.i", "").rpartition("@")[2]
            if d and addresses.aligned(d, dom):
                return Verdict(True, "dkim",
                               f"dkim=pass header.d={d} aligned with {dom} ({h.authserv_id})")

    spf = [(h, r) for h in hs for r in h.results if r.method == "spf"]
    if spf and all(r.result == "pass" for _, r in spf):
        for h, r in spf:
            mf = r.props.get("smtp.mailfrom", "").rpartition("@")[2]
            if mf and addresses.aligned(mf, dom):
                return Verdict(True, "spf",
                               f"spf=pass smtp.mailfrom={mf} aligned with {dom} ({h.authserv_id})")

    return Verdict(False, None, "no DMARC pass and no SPF or DKIM pass aligned with " + dom)
