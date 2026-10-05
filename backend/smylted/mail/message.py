"""Turn the raw bytes IMAP hands over into the few facts the pipeline reads.

Everything downstream — the ledger key, the thread id, the sender checks, the
text the model sees — comes from `parse_message`, so it is built to never raise:
a message that cannot be read becomes a `ParsedMessage` with empty fields, which
the pipeline then discards for having nothing in it, rather than an exception
that stalls the folder on the same UID every poll.

**Two parses.** The message is parsed twice. `policy.default` gives the MIME
walk, charset-aware `get_content()` and `get_filename()`, but it raises on some
malformed headers at access time. `policy.compat32` never does — it hands back
the raw string — so headers are read from a compat32 copy and decoded by hand
(`decode_header`, with the raw text as the fallback). That compat32 copy is what
`ParsedMessage.headers` holds, and later stages read `Authentication-Results`
from it with `get_all`. The cost is parsing a few kilobytes twice.

**What Proton Bridge does to headers** (checked in its source, `pkg/message/
build.go`, `toMessageHeader(msg.ParsedHeaders)`): Bridge rebuilds each message
from the headers Proton stored, so the original headers pass through in their
original order — `Authentication-Results` included, which is why the sender
check can read what Proton's inbound MTA wrote. Two Bridge habits matter here.
When a message arrived without a `Message-ID`, Bridge invents
`<id@protonmail.internalid>`; and it appends its own
`<id@protonmail.internalid>` to `References`. That second one would make every
new conversation look like a reply to a message nobody has seen, with a thread
id unique to that message, and a real reply chain would never share a root with
its first message. So `references` and `in_reply_to` drop every id ending in
`INTERNAL_ID_SUFFIX`, and a message with no other reference is the root of its
own thread: `thread_id` falls back to its ledger key. The synthesised
Message-ID is kept as the `message_id`: it is stable for that message, which is
all the ledger needs from it.

**Ledger key.** `mid:<Message-ID>` when the message has one, because that is the
identity every other client agrees on and it survives a move between folders.
Otherwise a hash of sender, date, subject and the whitespace-normalised body:
two fetches of the same message give the same key, an edited draft does not.
The hash is a fallback, not the plan; it exists so a message with no Message-ID
is processed once instead of every poll.

**Quotes.** A reply carries the whole conversation underneath the new text, and
the model would extract the old requests again as if they were new. HTML mail
marks its quotes with structure (Gmail, Apple Mail, Thunderbird, Outlook, Proton
each use a different convention), so `html_to_text` removes those containers by
name; `strip_quotes` does the same for plain text by its line patterns, which
is less reliable and therefore stricter about what counts as a cut line. A
forwarded-message marker is deliberately not a cut point: a note-to-self
forward is *about* the forwarded content.

Only Outlook-style header blocks cut everything after them. An "On … wrote:"
attribution does not: the `>` lines are the quote, and a reply written below
the quote or between its pieces is exactly the new text. Cutting at the
attribution, the obvious rule, dropped every bottom-posted reply whole. Outlook
writes the same header block above a forward as above a reply, so a forward
prefix in the subject (`FW:`, `Fwd:`, `WG:`, …) switches the cut off, as does a
cut that would leave nothing; the cost is a forward that also carries a reply
chain reaching the model whole, which beats an empty body.

**Calendar parts** (`text/calendar`, `application/ics`, `*.ics`) are collected
whether inline or attached and are never body text: the `.ics` fast path reads
them, and pasting iCalendar syntax into the prompt would only hand the model
more text it can be told things in.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.policy import compat32
from email.policy import default as default_policy
from email.utils import getaddresses, parsedate_to_datetime

from smylted.mail import addresses

log = logging.getLogger("smylted.mail")

INTERNAL_ID_SUFFIX = "@protonmail.internalid"
MAX_TEXT_CHARS = 1_000_000
MAX_CALENDAR_PARTS = 5
MAX_CALENDAR_BYTES = 1_000_000
MAX_SUBJECT_CHARS = 500
MAX_ID_LEN = 998                      # RFC 5322 line length limit

_CALENDAR_TYPES = frozenset({"text/calendar", "application/ics"})
_DECODE_ERRORS = (LookupError, UnicodeError, ValueError, AssertionError, KeyError)


@dataclass(frozen=True)
class Attachment:
    filename: str | None
    content_type: str
    data: bytes


@dataclass(frozen=True)
class ParsedMessage:
    message_id: str | None
    from_name: str
    from_addr: str | None
    from_count: int
    to: tuple[str, ...]
    cc: tuple[str, ...]
    subject: str
    date: datetime | None
    references: tuple[str, ...]
    in_reply_to: str | None
    headers: Message                    # compat32 parse, for get/get_all lookups
    text: str
    html_used: bool
    calendars: tuple[Attachment, ...]


# --- header helpers ---------------------------------------------------------

def _unescape(s: str) -> str:
    """Undo `surrogateescape`: compat32 returns undecodable header bytes as lone
    surrogates, which break `json`/SQLite later. Re-read them as UTF-8."""
    try:
        return s.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    except UnicodeError:
        return s.encode("utf-8", "replace").decode("utf-8", "replace")


def _raw(value: object) -> str:
    return _unescape(str(value))


def _decoded(value: object) -> str:
    """A header value as text: encoded words decoded, folds unfolded; the raw
    string when the encoded words are broken."""
    s = _raw(value)
    try:
        s = str(make_header(decode_header(s)))
    except Exception:                    # broken word, unknown charset, ...
        pass
    return re.sub(r"\r?\n[ \t]", " ", s)


def _values(headers: Message, name: str) -> list[str]:
    """Every value of header `name`, as text.

    Read from `raw_items()`, not `get_all()`: for a value with raw 8-bit bytes
    (`Subject: Rückmeldung` sent as UTF-8, which RFC 6532 allows and many
    clients do) compat32's `get_all` returns a `Header` whose `str()` has
    already replaced every such byte with U+FFFD. `raw_items()` gives the
    surrogate-escaped string, which `_unescape` reads back as UTF-8.
    """
    key = name.lower()
    try:
        return [_raw(v) for k, v in headers.raw_items() if k.lower() == key]
    except Exception:
        pass
    try:
        return [_raw(v) for v in headers.get_all(name, [])]
    except Exception:
        return []


def _first(headers: Message, name: str) -> str | None:
    vals = _values(headers, name)
    return vals[0] if vals else None


def header_value(msg: ParsedMessage, name: str) -> str | None:
    """The first value of header `name`, decoded to text, or None."""
    vals = _values(msg.headers, name)
    return _decoded(vals[0]) if vals else None


def normalize_message_id(value: str | None) -> str | None:
    """The id without angle brackets, or None when it is not usable as a key."""
    if not value:
        return None
    m = re.search(r"<([^<>]*)>", value)
    if m:
        candidate = m.group(1)
    else:
        parts = value.split()
        candidate = parts[0] if parts else ""
    candidate = candidate.strip()
    if (not candidate or len(candidate) > MAX_ID_LEN
            or re.search(r"[\s<>]", candidate)):
        return None
    return candidate


def parse_id_list(value: str | None) -> list[str]:
    """Every message id in a References / In-Reply-To value, in order, once."""
    if not value:
        return []
    raw_ids = re.findall(r"<([^<>\s]*)>", value)
    if not raw_ids:
        raw_ids = [t for t in value.split() if "@" in t]
    out: list[str] = []
    for r in raw_ids:
        mid = normalize_message_id(r)
        if mid is not None and mid not in out:
            out.append(mid)
    return out


def _is_internal(mid: str) -> bool:
    return mid.lower().endswith(INTERNAL_ID_SUFFIX)


def _address_list(headers: Message, name: str) -> tuple[str, ...]:
    out: list[str] = []
    try:
        parsed = addresses.parse_address_list(_values(headers, name))
    except Exception:                    # e.g. RecursionError on nested comments
        return ()
    for _, addr in parsed:
        if addr not in out:
            out.append(addr)
    return tuple(out)


def _parse_date(headers: Message) -> datetime | None:
    raw = _first(headers, "Date")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# --- body -------------------------------------------------------------------

def _part_text(part: Message) -> str:
    """The decoded text of one text part; never raises."""
    try:
        return part.get_content()
    except _DECODE_ERRORS:
        pass
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        return ""
    if not isinstance(payload, (bytes, bytearray)):
        return ""
    try:
        return bytes(payload).decode(part.get_content_charset() or "utf-8", errors="replace")
    except (LookupError, UnicodeError):
        return bytes(payload).decode("utf-8", errors="replace")


def _extract_body(root: Message | None, *,
                  keep_forwarded: bool = False) -> tuple[str, bool, tuple[Attachment, ...]]:
    plain: str | None = None
    html: str | None = None
    calendars: list[Attachment] = []
    if root is not None:
        try:
            for part in root.walk():
                try:
                    if part.is_multipart():
                        continue
                    ctype = part.get_content_type()
                    filename = part.get_filename()
                    if (ctype in _CALENDAR_TYPES
                            or (filename and filename.lower().endswith(".ics"))):
                        if len(calendars) < MAX_CALENDAR_PARTS:
                            data = part.get_payload(decode=True)
                            if isinstance(data, (bytes, bytearray)) and len(data) <= MAX_CALENDAR_BYTES:
                                calendars.append(Attachment(filename, ctype, bytes(data)))
                        continue
                    if part.get_content_disposition() == "attachment":
                        continue
                    if ctype == "text/plain" and plain is None:
                        plain = _part_text(part)
                    elif ctype == "text/html" and html is None:
                        html = _part_text(part)
                except Exception as exc:
                    log.debug("mail: a message part could not be read (%s)", type(exc).__name__)
        except Exception as exc:
            log.debug("mail: the message structure could not be walked (%s)", type(exc).__name__)

    html_used = False
    if plain is not None and (len(plain.strip()) >= 20 or html is None):
        text = plain
    elif html is not None:
        text = html_to_text(html, keep_forwarded=keep_forwarded)
        html_used = True
    else:
        text = ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text[:MAX_TEXT_CHARS], html_used, tuple(calendars)


def parse_message(raw: bytes) -> ParsedMessage:
    """Parse one RFC 5322 message. Never raises, whatever the bytes are."""
    try:
        headers = message_from_bytes(raw, policy=compat32)
    except Exception:
        headers = Message()
    try:
        root = message_from_bytes(raw, policy=default_policy)
    except Exception:
        root = None

    from_values = _values(headers, "From")
    try:
        # The count includes entries that are not valid addresses: a second,
        # malformed From must still make the header "not exactly one address".
        from_count = sum(1 for _, a in getaddresses(from_values) if a.strip())
        from_list = addresses.parse_address_list(from_values)
    except Exception:
        # The stdlib address parser recurses once per nested comment, so a
        # From of six hundred "(" raises RecursionError. No address is the
        # answer that keeps the message out of every sender list.
        from_count, from_list = 0, []
    from_name = _decoded(from_list[0][0]) if from_list else ""
    from_name = re.sub(r"\s+", " ", from_name).strip()
    from_addr = from_list[0][1] if from_list else None

    subject_raw = _first(headers, "Subject")
    subject = re.sub(r"\s+", " ", _decoded(subject_raw)).strip()[:MAX_SUBJECT_CHARS] if subject_raw else ""

    references = tuple(i for i in parse_id_list(_first(headers, "References")) if not _is_internal(i))
    in_reply_to = next((i for i in parse_id_list(_first(headers, "In-Reply-To"))
                        if not _is_internal(i)), None)

    text, html_used, calendars = _extract_body(root, keep_forwarded=_is_forward(subject))
    return ParsedMessage(
        message_id=normalize_message_id(_first(headers, "Message-ID")),
        from_name=from_name,
        from_addr=from_addr,
        from_count=from_count,
        to=_address_list(headers, "To"),
        cc=_address_list(headers, "Cc"),
        subject=subject,
        date=_parse_date(headers),
        references=references,
        in_reply_to=in_reply_to,
        headers=headers,
        text=text,
        html_used=html_used,
        calendars=calendars,
    )


# --- HTML -> text -----------------------------------------------------------

_DROP_TAGS = ("script", "style", "head", "title", "noscript", "template")
_QUOTE_CLASSES = ("gmail_quote", "gmail_attr", "yahoo_quoted", "moz-cite-prefix", "protonmail_quote")
_QUOTE_XPATH = " | ".join((
    "//blockquote[@type='cite']",
    "//*[@id='mail-editor-reference-message-container']",
    "//*[" + " or ".join(
        f"contains(concat(' ', normalize-space(@class), ' '), ' {c} ')" for c in _QUOTE_CLASSES
    ) + "]",
))
_OUTLOOK_XPATH = "//*[@id='divRplyFwdMsg' or @id='appendonsend']"
_BLOCK_TAGS = frozenset(
    "p div li tr h1 h2 h3 h4 h5 h6 table ul ol blockquote pre section article header footer".split()
)


class _Writer:
    """Accumulates text, remembering the last character so that block
    boundaries do not pile up blank lines and runs of spaces collapse."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.last = "\n"

    def text(self, s: str, pre: bool = False) -> None:
        if not pre:
            s = re.sub(r"[ \t\r\n\f]+", " ", s)
            if self.last in ("\n", " "):
                s = s.lstrip(" ")
        if s:
            self.parts.append(s)
            self.last = s[-1]

    def newline(self) -> None:
        if self.last != "\n":
            self.parts.append("\n")
            self.last = "\n"

    def hard_newline(self) -> None:
        self.parts.append("\n")
        self.last = "\n"


def _walk(el, w: _Writer, pre: bool) -> None:
    tag = el.tag
    if isinstance(tag, str):
        tag = tag.lower()
        inner_pre = pre or tag == "pre"
        if tag == "br":
            w.hard_newline()
        else:
            block = tag in _BLOCK_TAGS
            if block:
                w.newline()
            if tag == "li":
                w.text("- ")
            if el.text:
                w.text(el.text, inner_pre)
            for child in el:
                _walk(child, w, inner_pre)
            if tag == "a":
                href = (el.get("href") or "").strip()
                if re.match(r"https?://", href, re.IGNORECASE):
                    shown = el.text_content().strip()
                    if href.rstrip("/") != shown.rstrip("/"):
                        w.text(f" ({href})")
            elif tag in ("td", "th"):
                w.text(" ")
            if block:
                w.newline()
    # Comments and processing instructions carry no text, but their tail does.
    if el.tail:
        w.text(el.tail, pre)


def _tidy(text: str) -> str:
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.replace("\r\n", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _drop_outlook_reply(root) -> None:
    for el in root.xpath(_OUTLOOK_XPATH):
        if el.getparent() is None:
            continue
        # Outlook's reply header starts the quoted conversation; everything
        # after it in the same container is the old message.
        nxt = el.getnext()
        while nxt is not None:
            nxt.drop_tree()
            nxt = el.getnext()
        el.tail = None
        prev = el.getprevious()
        if prev is not None and isinstance(prev.tag, str) and prev.tag.lower() == "hr":
            prev.drop_tree()
        el.drop_tree()


def _render(root) -> str:
    w = _Writer()
    _walk(root, w, False)
    return _tidy("".join(w.parts))


def html_to_text(html: str, *, keep_forwarded: bool = False) -> str:
    """Readable text of an HTML mail, without the quoted conversation.

    Outlook writes the same `divRplyFwdMsg` header block above a forwarded
    message as above a quoted reply, so the markup cannot tell them apart.
    `keep_forwarded` (the subject says it is a forward) keeps that block and
    everything after it, because a forward is *about* the forwarded message.
    And when removing it would leave no text at all — a forward with nothing
    written above it — the forwarded message is what there is to read, so it
    is kept.

    Falls back to stripping tags with a regex if lxml cannot make a tree of it.
    """
    try:
        import lxml.html
        parser = lxml.html.HTMLParser(remove_comments=True, no_network=True,
                                      recover=True, encoding="utf-8")
        # Bytes, not str: lxml refuses a str that declares its own encoding.
        root = lxml.html.document_fromstring(html.encode("utf-8", "replace"), parser=parser)
        for el in list(root.iter(*_DROP_TAGS)):
            if el.getparent() is not None:
                el.drop_tree()
        for el in root.xpath(_QUOTE_XPATH):
            if el.getparent() is not None:
                el.drop_tree()
        if keep_forwarded or not root.xpath(_OUTLOOK_XPATH):
            return _render(root)
        whole = _render(root)
        _drop_outlook_reply(root)
        return _render(root) or whole
    except Exception as exc:
        log.debug("mail: html could not be parsed, stripping tags (%s)", type(exc).__name__)
        return _tidy(re.sub(r"<[^>]+>", " ", html))


# --- plain-text quotes ------------------------------------------------------

_ON_WROTE = re.compile(r"^\s*On\b.{0,300}\bwrote:\s*$")
_AM_SCHRIEB = re.compile(r"^\s*Am\b.{0,300}\bschrieb\b.{0,300}:\s*$")
_ORIGINAL = re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE)
_URSPRUENGLICH = re.compile(r"^\s*-{2,}\s*Ursprüngliche Nachricht\s*-{2,}\s*$", re.IGNORECASE)
_UNDERSCORES = re.compile(r"^\s*_{10,}\s*$")
_FROM_LINE = re.compile(r"^\s*(?:From|Von):")
_FROM_HEADER = re.compile(r"^\s*(?:From|Von):\s*\S")
_SENT_HEADER = re.compile(r"^\s*(?:Sent|Date|Gesendet|Datum):\s")
_TO_HEADER = re.compile(r"^\s*(?:To|Subject|An|Betreff):\s")
_FORWARD_MARKER = re.compile(
    r"^\s*(?:-{2,}\s*(?:Forwarded message|Weitergeleitete Nachricht)\s*-{2,}|Begin forwarded message:)\s*$",
    re.IGNORECASE,
)


_FORWARD_SUBJECT = re.compile(r"^\s*(?:fwd?|wg|tr|rv)\s*:", re.IGNORECASE)


def _is_forward(subject: str) -> bool:
    """Does the subject start with a forward prefix (Fwd, FW, WG, TR, RV)?"""
    return bool(_FORWARD_SUBJECT.match(subject or ""))


def _attribution_length(lines: list[str], i: int) -> int:
    """How many lines from `i` on are a reply attribution ("On … wrote:",
    possibly wrapped onto a second line, or "Am … schrieb …:"); 0 if none."""
    if any(rx.match(lines[i]) for rx in (_ON_WROTE, _AM_SCHRIEB)):
        return 1
    if i + 1 < len(lines):
        joined = lines[i].rstrip() + " " + lines[i + 1].strip()
        if any(rx.match(joined) for rx in (_ON_WROTE, _AM_SCHRIEB)):
            return 2
    return 0


def _cut_index(lines: list[str]) -> int:
    """The first line of an Outlook-style quoted message, or len(lines)."""
    n = len(lines)
    for i, line in enumerate(lines):
        if _ORIGINAL.match(line) or _URSPRUENGLICH.match(line):
            return i
        if _UNDERSCORES.match(line):
            # Bounded: a body of nothing but underscore lines must not make
            # each one scan the rest of the message.
            following = [ln for ln in lines[i + 1:i + 9] if ln.strip()][:3]
            if any(_FROM_LINE.match(ln) for ln in following):
                return i
        if _FROM_HEADER.match(line):
            window = lines[i + 1:i + 6]
            if any(_SENT_HEADER.match(ln) for ln in window) and any(_TO_HEADER.match(ln) for ln in window):
                # The header block a forward writes under its marker is the
                # content being forwarded, not a quoted reply.
                before = next((ln for ln in reversed(lines[:i]) if ln.strip()), "")
                if not _FORWARD_MARKER.match(before):
                    return i
    return n


def strip_quotes(text: str, *, subject: str = "") -> str:
    """What the sender wrote, without the conversation quoted beneath it.

    Two kinds of marker, treated differently:

    - An attribution ("On … wrote:", "Am … schrieb …:") introduces `>`-quoted
      lines, and the sender's own text may come after the quote (bottom
      posting) or between its pieces (inline answers). So only the
      attribution line itself is removed; the `>` lines go with every other
      `>` line, and the unquoted text around them stays.
    - An Outlook-style header block ("-----Original Message-----", underscores
      then From:, a From:/Sent:/To: block) quotes without `>`, so everything
      from it on is cut. Not when `subject` marks a forward — the same block
      then introduces the content being passed on — and not when the cut
      would leave nothing, which is a memo that starts with From:/Date: lines
      or a forward with nothing written above it.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    without_attribution: list[str] = []
    i = 0
    while i < len(lines):
        skip = _attribution_length(lines, i)
        if skip:
            i += skip
            continue
        without_attribution.append(lines[i])
        i += 1
    lines = without_attribution
    cut = _cut_index(lines)
    if not _is_forward(subject) and any(ln.strip() for ln in lines[:cut]):
        lines = lines[:cut]
    kept = [ln.rstrip() for ln in lines if not ln.lstrip().startswith(">")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def normalize_body(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


# --- identity ---------------------------------------------------------------

def ledger_key(msg: ParsedMessage) -> str:
    if msg.message_id:
        return "mid:" + msg.message_id
    payload = json.dumps(
        [msg.from_addr or "", msg.date.isoformat() if msg.date else "",
         msg.subject, normalize_body(msg.text)],
        ensure_ascii=False,
    )
    return "hash:" + hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()


def thread_id(msg: ParsedMessage) -> str:
    """The id of the conversation: its root's Message-ID when a reference names
    one, so a thread root's own id equals the ids of all its replies."""
    refs: Sequence[str] = msg.references
    if refs:
        return "mid:" + refs[0]
    if msg.in_reply_to:
        return "mid:" + msg.in_reply_to
    return ledger_key(msg)
