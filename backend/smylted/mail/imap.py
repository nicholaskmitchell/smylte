"""Read mail from Proton Mail Bridge (or any IMAP server) without changing it.

The pipeline only ever needs five things from a mailbox: the folder list, a
folder's UIDVALIDITY, the UIDs newer than a cursor, the raw bytes of a message,
and one header of the newest message (for the connection test). `MailSource`
is that surface and nothing more, so the pipeline's tests can run against an
in-memory fake and this module is the only code that speaks IMAP.

Choices worth knowing about:

- **Stdlib `imaplib`, synchronous.** `imapclient` and `aioimaplib` were the
  alternatives. Both are another dependency on the path that holds the Bridge
  password, and the async one would put a second threading discipline in a
  process whose outbound I/O is synchronous code reached through
  `asyncio.to_thread` (see `notify/telegram.py`). `imaplib` is clumsy but
  small, and the clumsiness stays inside this file.

- **Read-only, always.** Folders are opened with EXAMINE (`readonly=True`) and
  bodies are fetched with `BODY.PEEK[]`, never `BODY[]`. A plain `BODY[]`
  fetch sets `\\Seen`, and Bridge syncs that flag to every other client: the
  owner would watch mail turn read in Thunderbird because Smylte looked at it.
  Nothing here sends STORE, EXPUNGE, COPY or APPEND.

- **Certificates.** Bridge listens on loopback with a self-signed certificate,
  so the system CA store cannot vouch for it. Three modes:
  `system` (normal verification, for a real provider), `pinned` (no chain or
  hostname check, but the SHA-256 of the certificate the server presents must
  equal the one the owner exported from Bridge — compared after the handshake
  and BEFORE the password is sent), and `insecure_localhost` (no check at
  all, refused unless the host is a loopback literal or `localhost`, and
  logged once per process). When `system` fails on a self-signed certificate
  the error carries the fingerprint the server presented, read by a second,
  unverified connection that never logs in — so the owner can compare it with
  what Bridge shows instead of guessing why TLS failed.

- **Errors.** Everything that leaves this module is a `MailConnectError` with
  a `kind` ("config", "network", "tls", "auth", "protocol") and a message that
  has been through `redact`. The password appears in exactly one place, the
  `login` call; a server that echoes it back in a NO response is the reason
  the login error is redacted and raised `from None`.

- **Folder names.** IMAP sends names in modified UTF-7 (RFC 3501 §5.1.3) and
  `imaplib` does not decode them, so `encode_mutf7`/`decode_mutf7` live here.
  `FolderInfo.raw` keeps the wire form for EXAMINE; `FolderInfo.name` is what
  the owner sees and types into the folder list.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import imaplib
import logging
import re
import ssl
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from .redact import redact, redact_exc
from .settings import is_loopback_host

log = logging.getLogger("smylted.mail")

TLS_MODES = ("starttls", "ssl")
CERT_MODES = ("system", "pinned", "insecure_localhost")

# UIDs per FETCH command. Large enough that a backfill is not a round trip per
# message, small enough that one response stays a modest amount of memory.
FETCH_BATCH = 25

# IMAP dates use English month abbreviations whatever the process locale is,
# so they come from this table rather than strftime("%b").
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_LIST_LINE = re.compile(
    r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.*)$',
    re.I | re.S,
)
_LITERAL = re.compile(r"^\{\d+\+?\}$")
_UID = re.compile(rb"\bUID (\d+)", re.I)
_SIZE = re.compile(rb"\bRFC822\.SIZE (\d+)", re.I)
_INTERNALDATE = re.compile(
    rb'\bINTERNALDATE "(?P<day>[ \d]?\d)-(?P<mon>[A-Za-z]{3})-(?P<year>\d{4}) '
    rb'(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2}) (?P<zs>[-+])(?P<zh>\d{2})(?P<zm>\d{2})"',
    re.I,
)
_PEM_BLOCK = re.compile(
    r"-----BEGIN CERTIFICATE-----(?P<body>[A-Za-z0-9+/=\s]+?)-----END CERTIFICATE-----"
)


# --- data --------------------------------------------------------------------

@dataclass(frozen=True)
class FolderInfo:
    name: str                       # decoded display name (UTF-8)
    raw: str                        # wire name (modified UTF-7), used for EXAMINE
    flags: frozenset[str]           # lower-cased attributes, e.g. {"\\hasnochildren", "\\sent"}
    delimiter: str | None


@dataclass(frozen=True)
class FolderState:
    uidvalidity: int
    uidnext: int | None
    exists: int | None


@dataclass(frozen=True)
class FetchedMessage:
    uid: int
    raw: bytes | None               # None when larger than max_bytes (not fetched)
    size: int
    internaldate: datetime | None   # aware


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    username: str
    tls: str                        # "starttls" | "ssl"
    cert_mode: str                  # "system" | "pinned" | "insecure_localhost"
    pinned_cert_pem: str = ""
    timeout: float = 30.0


class MailConnectError(Exception):
    """A mail-server failure the owner can act on, with a redacted message.

    `kind` says what to fix: "config" (a setting), "network" (reachability),
    "tls" (certificate or encryption), "auth" (username/password), "protocol"
    (the server said something unexpected). `fingerprint` is the SHA-256 of
    the certificate the server presented, when that is what went wrong."""

    def __init__(self, message: str, *, kind: str, fingerprint: str | None = None):
        super().__init__(redact(message))
        self.kind = kind
        self.fingerprint = fingerprint


class MailSource(Protocol):
    def list_folders(self) -> list[FolderInfo]: ...
    def select(self, folder: FolderInfo) -> FolderState: ...
    def search_uids(self, *, after_uid: int | None = None, since: date | None = None) -> list[int]: ...
    def fetch(self, uids: Sequence[int], *, max_bytes: int) -> Iterator[FetchedMessage]: ...
    def fetch_header_fields(self, uid: int, fields: Sequence[str]) -> bytes: ...
    def close(self) -> None: ...


# --- certificates ------------------------------------------------------------

def cert_fingerprint_der(der: bytes) -> str:
    """SHA-256 of a DER certificate as upper-case `AB:CD:…` — the form Bridge
    and browsers show, so the owner can compare it by eye."""
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def cert_fingerprint_pem(pem: str) -> str:
    """Fingerprint of the first certificate in `pem`; ValueError if there is none."""
    m = _PEM_BLOCK.search(pem or "")
    if not m:
        raise ValueError("no PEM certificate found")
    try:
        der = base64.b64decode("".join(m.group("body").split()), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("the PEM certificate is not valid base64") from None
    if not der:
        raise ValueError("the PEM certificate is empty")
    return cert_fingerprint_der(der)


def _unverified_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def build_ssl_context(cfg: ImapConfig) -> ssl.SSLContext:
    """The client TLS context for `cfg.cert_mode`."""
    if cfg.cert_mode == "system":
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        return ctx
    if cfg.cert_mode in ("pinned", "insecure_localhost"):
        # Pinned: chain and hostname checks are replaced by an exact SHA-256
        # comparison of the presented certificate, done in `connect` right
        # after the handshake and BEFORE any credential is sent. That is what
        # pinning means, and it is stronger than trusting the self-signed
        # certificate as a CA: there is no hostname to match on a tunnel or an
        # IP literal, and no expiry date to surprise anyone a year from now.
        # insecure_localhost uses the same context and skips the comparison.
        return _unverified_context()
    raise MailConnectError("unknown TLS setting", kind="config")


def _shutdown(imap: imaplib.IMAP4 | None) -> None:
    if imap is None:
        return
    try:
        imap.shutdown()
    except Exception:  # noqa: BLE001 — closing a socket that may already be gone
        pass


def _open(cfg: ImapConfig, ctx: ssl.SSLContext) -> imaplib.IMAP4:
    """Connect and finish the TLS handshake; nothing is authenticated yet."""
    if cfg.tls == "ssl":
        return imaplib.IMAP4_SSL(cfg.host, cfg.port, ssl_context=ctx, timeout=cfg.timeout)
    imap = imaplib.IMAP4(cfg.host, cfg.port, timeout=cfg.timeout)
    try:
        imap.starttls(ssl_context=ctx)
    except imaplib.IMAP4.error:
        _shutdown(imap)
        raise MailConnectError(
            "the server does not offer STARTTLS; check the port and TLS setting", kind="tls"
        ) from None
    except BaseException:
        _shutdown(imap)
        raise
    return imap


def probe_fingerprint(cfg: ImapConfig) -> str | None:
    """The SHA-256 of the certificate the server presents, or None.

    Connects WITHOUT verification, reads the certificate, and closes. It never
    logs in, so it is safe to run against a server nobody has vouched for: the
    only thing it learns is what it reports."""
    imap = None
    try:
        if cfg.tls == "ssl":
            imap = imaplib.IMAP4_SSL(cfg.host, cfg.port, ssl_context=_unverified_context(),
                                     timeout=cfg.timeout)
        else:
            imap = imaplib.IMAP4(cfg.host, cfg.port, timeout=cfg.timeout)
            imap.starttls(ssl_context=_unverified_context())
        der = imap.sock.getpeercert(binary_form=True)
        return cert_fingerprint_der(der) if der else None
    except Exception as exc:  # noqa: BLE001 — a probe that fails just has nothing to add
        log.debug("mail: certificate probe of %s:%s failed: %s", cfg.host, cfg.port, redact_exc(exc))
        return None
    finally:
        _shutdown(imap)


# --- connect -----------------------------------------------------------------

_insecure_warned = False


def connect(cfg: ImapConfig, password: str) -> ImapMailSource:
    """Open, secure, check and authenticate an IMAP connection.

    Every configuration problem is reported before a socket is opened, and
    every certificate problem before the password is sent."""
    global _insecure_warned
    if cfg.tls not in TLS_MODES or cfg.cert_mode not in CERT_MODES:
        raise MailConnectError("unknown TLS setting", kind="config")
    if cfg.cert_mode == "insecure_localhost" and not is_loopback_host(cfg.host):
        raise MailConnectError(
            "certificate checks can only be switched off for a loopback host "
            "(127.0.0.1, ::1 or localhost); pin Bridge's certificate instead",
            kind="config",
        )
    want = None
    if cfg.cert_mode == "pinned":
        try:
            want = cert_fingerprint_pem(cfg.pinned_cert_pem)
        except ValueError:
            raise MailConnectError(
                "no pinned certificate is saved: paste the certificate exported from Bridge",
                kind="config",
            ) from None
    if not cfg.username or not password:
        raise MailConnectError("the IMAP username and password must both be set", kind="config")

    ctx = build_ssl_context(cfg)
    imap = None
    try:
        try:
            imap = _open(cfg, ctx)
        except ssl.SSLCertVerificationError as exc:
            fp = probe_fingerprint(cfg)
            raise MailConnectError(
                f"the server's TLS certificate could not be verified "
                f"({exc.verify_message or exc.reason}). Proton Mail Bridge uses a self-signed "
                f"certificate: export it from Bridge and choose 'Pinned certificate'."
                + (f" The server presented SHA-256 {fp}." if fp else ""),
                kind="tls", fingerprint=fp,
            ) from None
        except ssl.SSLError as exc:
            raise MailConnectError(f"TLS handshake failed ({redact_exc(exc)})", kind="tls") from None
        except OSError as exc:      # after the ssl clauses: SSLError is an OSError
            raise MailConnectError(
                f"could not reach {cfg.host}:{cfg.port} ({redact_exc(exc)})", kind="network"
            ) from None

        if want is not None:
            der = imap.sock.getpeercert(binary_form=True)
            if not der:
                raise MailConnectError("the server presented no TLS certificate", kind="tls")
            got = cert_fingerprint_der(der)
            if got != want:
                raise MailConnectError(
                    f"the server's certificate does not match the pinned one: the server "
                    f"presented SHA-256 {got}, the pinned certificate is {want}. If Bridge "
                    f"regenerated its certificate, export it again.",
                    kind="tls", fingerprint=got,
                )
        elif cfg.cert_mode == "insecure_localhost" and not _insecure_warned:
            _insecure_warned = True
            log.warning("mail: IMAP certificate checks are OFF for %s (insecure_localhost)", cfg.host)

        try:
            imap.login(cfg.username, password)
        except imaplib.IMAP4.error as exc:
            arg = exc.args[0] if exc.args else ""
            text = arg.decode("utf-8", "replace") if isinstance(arg, bytes) else str(arg)
            raise MailConnectError(
                f"the IMAP server rejected the login for {cfg.username!r}: {redact(text)}",
                kind="auth",
            ) from None
    except MailConnectError:
        _shutdown(imap)
        raise
    except Exception as exc:  # noqa: BLE001 — anything else is the server misbehaving
        _shutdown(imap)
        raise MailConnectError(redact_exc(exc), kind="protocol") from None
    return ImapMailSource(imap)


# --- the source --------------------------------------------------------------

@contextmanager
def _converted() -> Iterator[None]:
    """Turn what imaplib and the socket raise into MailConnectError."""
    try:
        yield
    except MailConnectError:
        raise
    except imaplib.IMAP4.error as exc:
        raise MailConnectError(redact_exc(exc), kind="protocol") from None
    except OSError as exc:
        raise MailConnectError(f"the IMAP connection failed ({redact_exc(exc)})",
                               kind="network") from None


def _imap_date(d: date) -> str:
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year:04d}"


def _parse_internaldate(line: bytes) -> datetime | None:
    m = _INTERNALDATE.search(line)
    if not m:
        return None
    try:
        month = [x.lower() for x in _MONTHS].index(m["mon"].decode("ascii").lower()) + 1
        offset = timedelta(hours=int(m["zh"]), minutes=int(m["zm"]))
        if m["zs"] == b"-":
            offset = -offset
        return datetime(int(m["year"]), month, int(m["day"].strip()), int(m["h"]),
                        int(m["m"]), int(m["s"]), tzinfo=timezone(offset))
    except ValueError:
        return None


def _first_int(pattern: re.Pattern[bytes], line: bytes) -> int | None:
    m = pattern.search(line)
    return int(m.group(1)) if m else None


def _literals_by_uid(data: list) -> dict[int, bytes]:
    """Map UID → literal from a FETCH response. imaplib hands back the line up
    to a literal and the literal as a tuple, then the rest of the line as bytes;
    the UID is usually before the literal but a server may put it after."""
    out: dict[int, bytes] = {}
    pending: bytes | None = None
    for item in data or ():
        if isinstance(item, tuple) and len(item) >= 2:
            uid = _first_int(_UID, bytes(item[0]))
            if uid is not None:
                out[uid] = bytes(item[1])
                pending = None
            else:
                pending = bytes(item[1])
        elif isinstance(item, bytes) and pending is not None:
            uid = _first_int(_UID, item)
            if uid is not None:
                out[uid] = pending
            pending = None
    return out


class ImapMailSource:
    """`MailSource` over one authenticated `imaplib` connection. Not thread-safe:
    one run owns it from `connect` to `close`."""

    def __init__(self, imap: imaplib.IMAP4):
        self._imap = imap
        self._closed = False

    def list_folders(self) -> list[FolderInfo]:
        with _converted():
            typ, data = self._imap.list()
        if typ != "OK":
            raise MailConnectError("the server refused to list folders", kind="protocol")
        return parse_list_response(data)

    def select(self, folder: FolderInfo) -> FolderState:
        with _converted():
            typ, data = self._imap.select(quote_mailbox(folder.raw), readonly=True)
            if typ != "OK":
                raise MailConnectError(f"could not open folder {folder.name!r}", kind="protocol")
            uidvalidity = self._response_int("UIDVALIDITY")
            uidnext = self._response_int("UIDNEXT")
        if uidvalidity is None:
            raise MailConnectError("the server did not report UIDVALIDITY", kind="protocol")
        exists = None
        if data and isinstance(data[-1], bytes) and data[-1].strip().isdigit():
            exists = int(data[-1])
        return FolderState(uidvalidity=uidvalidity, uidnext=uidnext, exists=exists)

    def _response_int(self, code: str) -> int | None:
        _, values = self._imap.response(code)
        for v in reversed(values or ()):
            if isinstance(v, bytes) and v.strip().isdigit():
                return int(v)
        return None

    def search_uids(self, *, after_uid: int | None = None, since: date | None = None) -> list[int]:
        criteria: list[str] = []
        if since is not None:
            criteria += ["SINCE", _imap_date(since)]
        if after_uid is not None:
            criteria += ["UID", f"{after_uid + 1}:*"]
        if not criteria:
            criteria = ["ALL"]
        with _converted():
            typ, data = self._imap.uid("SEARCH", *criteria)
        if typ != "OK":
            raise MailConnectError("the server refused a search", kind="protocol")
        uids: set[int] = set()
        for line in data or ():
            if isinstance(line, bytes):
                uids.update(int(t) for t in line.split() if t.isdigit())
        if after_uid is not None:
            # `n:*` always includes the highest UID, even when it is below n.
            uids = {u for u in uids if u > after_uid}
        return sorted(uids)

    def fetch(self, uids: Sequence[int], *, max_bytes: int) -> Iterator[FetchedMessage]:
        """Yield every UID still on the server, ascending. Sizes come first so a
        message over `max_bytes` is never downloaded; bodies use BODY.PEEK so
        nothing is marked read."""
        ordered = sorted(set(int(u) for u in uids))
        for i in range(0, len(ordered), FETCH_BATCH):
            batch = ordered[i:i + FETCH_BATCH]
            with _converted():
                meta = self._fetch_meta(batch)
                small = [u for u in batch if u in meta
                         and (meta[u][0] is None or meta[u][0] <= max_bytes)]
                bodies: dict[int, bytes] = {}
                if small:
                    typ, data = self._imap.uid("FETCH", ",".join(map(str, small)), "(UID BODY.PEEK[])")
                    if typ != "OK":
                        raise MailConnectError("the server refused to send messages", kind="protocol")
                    bodies = _literals_by_uid(data)
            for uid in batch:
                if uid not in meta:
                    continue                    # deleted since the search
                size, internaldate = meta[uid]
                if size is not None and size > max_bytes:
                    yield FetchedMessage(uid=uid, raw=None, size=size, internaldate=internaldate)
                    continue
                raw = bodies.get(uid)
                if raw is None:
                    continue                    # deleted between the two fetches
                if size is None:
                    # The server did not say how big it was; enforce the cap now.
                    size = len(raw)
                    if size > max_bytes:
                        raw = None
                yield FetchedMessage(uid=uid, raw=raw, size=size, internaldate=internaldate)

    def _fetch_meta(self, batch: list[int]) -> dict[int, tuple[int | None, datetime | None]]:
        typ, data = self._imap.uid("FETCH", ",".join(map(str, batch)), "(UID RFC822.SIZE INTERNALDATE)")
        if typ != "OK":
            raise MailConnectError("the server refused to describe messages", kind="protocol")
        out: dict[int, tuple[int | None, datetime | None]] = {}
        for item in data or ():
            line = item[0] if isinstance(item, tuple) else item
            if not isinstance(line, bytes):
                continue
            uid = _first_int(_UID, line)
            if uid is not None:
                out[uid] = (_first_int(_SIZE, line), _parse_internaldate(line))
        return out

    def fetch_header_fields(self, uid: int, fields: Sequence[str]) -> bytes:
        with _converted():
            typ, data = self._imap.uid(
                "FETCH", str(int(uid)), f"(BODY.PEEK[HEADER.FIELDS ({' '.join(fields)})])"
            )
        if typ != "OK":
            raise MailConnectError("the server refused to send message headers", kind="protocol")
        for item in data or ():
            if isinstance(item, tuple) and len(item) >= 2:
                return bytes(item[1])
        return b""

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._imap.logout()
        except Exception:  # noqa: BLE001 — the server may already be gone
            pass
        _shutdown(self._imap)


# --- folder names ------------------------------------------------------------

def encode_mutf7(s: str) -> str:
    """Modified UTF-7 (RFC 3501 §5.1.3): printable ASCII stands for itself,
    `&` becomes `&-`, and every other run is `&` + base64 of its UTF-16BE with
    `,` for `/` and no padding + `-`."""
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            b64 = base64.b64encode("".join(run).encode("utf-16-be")).decode("ascii")
            out.append("&" + b64.rstrip("=").replace("/", ",") + "-")
            run.clear()

    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            run.append(ch)
    flush()
    return "".join(out)


def decode_mutf7(s: str) -> str:
    """Inverse of `encode_mutf7`; ValueError on a malformed shift sequence."""
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch != "&":
            out.append(ch)
            i += 1
            continue
        end = s.find("-", i + 1)
        if end < 0:
            raise ValueError("unterminated modified UTF-7 sequence")
        chunk = s[i + 1:end]
        if not chunk:
            out.append("&")
        else:
            b64 = chunk.replace(",", "/")
            b64 += "=" * (-len(b64) % 4)
            try:
                out.append(base64.b64decode(b64, validate=True).decode("utf-16-be"))
            except (binascii.Error, UnicodeDecodeError, ValueError):
                raise ValueError("malformed modified UTF-7 sequence") from None
        i = end + 1
    return "".join(out)


def quote_mailbox(raw: str) -> str:
    """`raw` as an IMAP quoted string (imaplib does not quote arguments)."""
    return '"' + raw.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unquote(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s[1:-1])


def parse_list_response(data: list) -> list[FolderInfo]:
    """FolderInfo for every LIST line that parses; the rest are skipped.

    imaplib gives each line as bytes, or as a `(line, literal)` tuple when the
    server sent the name as a literal (followed by the empty rest of the line,
    which does not parse and is skipped)."""
    out: list[FolderInfo] = []
    for item in data or ():
        literal: str | None = None
        if isinstance(item, tuple) and len(item) >= 2:
            line, lit = item[0], item[1]
            literal = lit.decode("utf-8", "replace") if isinstance(lit, bytes) else str(lit)
        else:
            line = item
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        if not isinstance(line, str):
            continue
        m = _LIST_LINE.match(line.strip())
        if not m:
            continue
        name = m.group("name").strip()
        if literal is not None and _LITERAL.match(name):
            raw = literal
        elif len(name) >= 2 and name.startswith('"') and name.endswith('"'):
            raw = _unquote(name)
        elif name and not _LITERAL.match(name) and " " not in name:
            raw = name
        else:
            continue
        delim_text = m.group("delim")
        delimiter = None if delim_text.upper() == "NIL" else _unquote(delim_text)
        try:
            display = decode_mutf7(raw)
        except ValueError:
            display = raw           # better a folder with an odd name than no folder
        out.append(FolderInfo(
            name=display,
            raw=raw,
            flags=frozenset(f.lower() for f in m.group("flags").split()),
            delimiter=delimiter,
        ))
    return out
