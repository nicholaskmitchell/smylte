"""Email addresses, and the three-shape patterns the sender lists are written in.

Every comparison the pipeline makes about WHO sent a message goes through this
module, so there is exactly one answer to "is this the same address". It is
deliberately small and deliberately strict:

- An address is compared case-insensitively, whole. RFC 5321 lets the local
  part be case-sensitive, and no mail system anyone uses in 2026 exercises
  that; the alternative is a self-address list that misses `Nicholas@…`.
- A pattern is one of three shapes and nothing else: an exact address
  (`office@school.org`), a bare domain (`school.org` — that domain only), or a
  subdomain wildcard (`*.school.org` — every subdomain, NOT the apex). A bare
  domain does not quietly cover its subdomains because the two are different
  senders: `school.org` is the school, `newsletter.school.org` may be a vendor
  the school gave a subdomain to. Writing both is one more line; un-allowing a
  vendor that a broad pattern let through is a surprise found in the inbox.
- Nothing here resolves DNS or consults the Public Suffix List. `aligned` is
  therefore an approximation of DMARC's relaxed alignment, and it errs toward
  "not aligned" (see its docstring), which in the one place it is used means
  "treat as ordinary mail" — the safe direction.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from email.utils import getaddresses

import idna

# One DNS label, after IDNA: letters, digits, hyphens, not starting or ending
# with a hyphen. Underscores are refused — they do not occur in mail domains.
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
# A local part as the pipeline will meet it. Deliberately permissive (quoted
# local parts and odd punctuation exist in the wild), but no whitespace, no
# angle brackets and no second "@".
_LOCAL = re.compile(r"^[^\s<>@\"(),;:\\\[\]]{1,64}$")

_NOREPLY = re.compile(
    r"^(?:.*[._+-])?"
    r"(?:no[._-]?reply|do[._-]?not[._-]?reply|donotreply)"
    r"(?:[._+-].*)?$"
)
_DAEMON = re.compile(r"^(?:mailer[._-]?daemon|postmaster|bounces?)$")


def normalize_domain(domain: str) -> str | None:
    """`domain`, lower-cased, IDNA-encoded and without a trailing dot — or None.

    IDNA so that `bücher.example` written in Settings and `xn--bcher-kva.example`
    in a header compare equal; refusal rather than a best guess, because a
    pattern that silently matches nothing is the least debuggable outcome.

    UTS 46 non-transitional (IDNA 2008), from the `idna` package, not the
    stdlib codec: that one is IDNA 2003, which maps `ß` to `ss`, so
    `straße.de` would compare equal to `strasse.de` — a different registrant
    — and it accepts unassigned code points. An all-ASCII domain skips the
    encoder: `idna` refuses ASCII labels such as `ab--cd` that DNS and mail
    accept, and an ASCII domain has nothing to encode.
    """
    d = (domain or "").strip().rstrip(".").lower()
    if not d or len(d) > 253:
        return None
    if not d.isascii():
        try:
            d = idna.encode(d, uts46=True, transitional=False).decode("ascii")
        except (idna.IDNAError, UnicodeError):
            return None
    labels = d.split(".")
    if len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        return None
    return d


def normalize_address(addr: str | None) -> str | None:
    """`local@domain`, lower-cased with the domain IDNA-encoded, or None.

    Accepts the forms a user pastes or a header carries — surrounding
    whitespace, one pair of angle brackets — and refuses anything that is not
    exactly one address.
    """
    a = (addr or "").strip()
    if a.startswith("<") and a.endswith(">"):
        a = a[1:-1].strip()
    if a.count("@") != 1:
        return None
    local, _, domain = a.rpartition("@")
    local = local.lower()
    if not _LOCAL.match(local):
        return None
    d = normalize_domain(domain)
    if d is None:
        return None
    return f"{local}@{d}"


def domain_of(addr: str) -> str:
    """The domain half of a normalized address (or of a bare domain)."""
    return addr.rpartition("@")[2]


def parse_address_list(values: Iterable[str]) -> list[tuple[str, str]]:
    """`(display_name, normalized_address)` for every valid address in `values`.

    `values` is the list of raw header values (a header may repeat). Invalid
    entries are dropped rather than raised: a malformed Cc must not stop the
    message from being read, it just cannot count as anyone.
    """
    out: list[tuple[str, str]] = []
    for name, raw in getaddresses([v for v in values if isinstance(v, str)]):
        norm = normalize_address(raw)
        if norm is not None:
            out.append((name.strip(), norm))
    return out


def normalize_pattern(pattern: str) -> str | None:
    """The canonical form of one sender pattern, or None when it is not one.

    `office@school.org`, `school.org` and `*.school.org` are the three shapes.
    """
    p = (pattern or "").strip()
    if not p:
        return None
    if "@" in p:
        return normalize_address(p)
    if p.startswith("*."):
        d = normalize_domain(p[2:])
        return None if d is None else f"*.{d}"
    return normalize_domain(p)


def valid_pattern(pattern: str) -> bool:
    return normalize_pattern(pattern) is not None


def matches(addr: str, pattern: str) -> bool:
    """Does the normalized address `addr` match the normalized `pattern`?"""
    if not addr or not pattern:
        return False
    if "@" in pattern:
        return addr == pattern
    domain = domain_of(addr)
    if pattern.startswith("*."):
        return domain.endswith(pattern[1:])        # ".school.org" — strict subdomains
    return domain == pattern


def matches_any(addr: str | None, patterns: Iterable[str]) -> str | None:
    """The first pattern `addr` matches, or None."""
    if not addr:
        return None
    for p in patterns:
        if matches(addr, p):
            return p
    return None


def _without_plus_tag(addr: str) -> str:
    local, _, domain = addr.rpartition("@")
    base = local.split("+", 1)[0]
    return f"{base}@{domain}" if base else addr


def is_self(addr: str | None, self_addresses: Iterable[str]) -> bool:
    """Is `addr` one of the owner's addresses?

    Exact, plus one allowance: a `+tag` sub-address of a self address is the
    owner too (`me+school@proton.me` delivers to `me@proton.me`, and Proton,
    Fastmail and Gmail all support it). Nothing broader — "every address at my
    domain" is a statement the owner can make by listing them.
    """
    if not addr:
        return False
    own = set(self_addresses)
    return addr in own or _without_plus_tag(addr) in own


def noreply_local_part(addr: str | None) -> bool:
    """A no-reply-style sender: `noreply@`, `no-reply@`, `do-not-reply@`,
    `notifications-noreply@`, `mailer-daemon@`, `bounce@` and kin."""
    if not addr:
        return False
    local = addr.rpartition("@")[0]
    return bool(_NOREPLY.match(local) or _DAEMON.match(local))


def aligned(a: str | None, b: str | None) -> bool:
    """Approximate DMARC relaxed alignment between two domains.

    True when the domains are equal or one is a subdomain of the other
    (`bounce.school.org` / `school.org`). Real relaxed alignment compares
    organizational domains via the Public Suffix List, under which two sibling
    subdomains (`a.school.org`, `b.school.org`) also align; this does not, and
    that is the conservative miss: an unaligned verdict sends the message down
    the ordinary-mail path, it never lets one through.
    """
    da = normalize_domain(a or "")
    db = normalize_domain(b or "")
    if da is None or db is None:
        return False
    return da == db or da.endswith("." + db) or db.endswith("." + da)
