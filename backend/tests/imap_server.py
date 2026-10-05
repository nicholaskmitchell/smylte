"""A minimal IMAP4rev1 server for tests — a test double, not an IMAP server.

It speaks just enough of the protocol for `smylted.mail.imap` to be exercised
over a real socket with real TLS: the greeting, CAPABILITY, STARTTLS, LOGIN,
LIST, SELECT/EXAMINE, UID SEARCH, UID FETCH, NOOP and LOGOUT. Anything else is
answered `BAD`. It parses only the argument shapes that client sends, keeps
everything in memory, and trusts its input; do not point anything else at it.

What it is for is what a fake `MailSource` cannot show: that the pin is
checked before the password goes out, that only EXAMINE and BODY.PEEK are
used, and that a server echoing the password back does not leak it. So it
records every command line it receives (`server.commands`) and every message a
non-PEEK fetch would have marked `\\Seen` (`server.seen`).

Mailbox names are given as they go on the wire (modified UTF-7, e.g.
"Entw&APw-rfe"), so the client's decoding is tested against fixed bytes rather
than against its own encoder.
"""
from __future__ import annotations

import contextlib
import ipaddress
import os
import re
import socket
import socketserver
import ssl
import tempfile
import threading
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\([^)]*\)|\S+')


def make_self_signed_cert(common_name: str = "127.0.0.1") -> tuple[str, str]:
    """A fresh EC P-256 certificate for 127.0.0.1/localhost, valid one year,
    the shape Bridge generates. Returns (cert_pem, key_pem)."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.DNSName("localhost"),
        ]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    return cert_pem, key_pem


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return re.sub(r"\\(.)", r"\1", token[1:-1])
    return token


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _internaldate(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    off = int(dt.utcoffset().total_seconds() // 60)
    sign = "-" if off < 0 else "+"
    off = abs(off)
    return (f"{dt.day:02d}-{_MONTHS[dt.month - 1]}-{dt.year:04d} "
            f"{dt:%H:%M:%S} {sign}{off // 60:02d}{off % 60:02d}")


def _parse_date(s: str):
    day, mon, year = s.split("-")
    return datetime(int(year), _MONTHS.index(mon.capitalize()) + 1, int(day)).date()


def _uid_set(spec: str, uids: list[int]) -> set[int]:
    """UIDs named by a sequence set; `*` is the highest UID, and `a:b` is the
    same range as `b:a` (so `n:*` always includes the highest UID)."""
    top = max(uids, default=0)
    out: set[int] = set()
    for part in spec.split(","):
        lo, _, hi = part.partition(":")
        a = top if lo == "*" else int(lo)
        b = a if not hi else (top if hi == "*" else int(hi))
        a, b = min(a, b), max(a, b)
        out.update(u for u in uids if a <= u <= b)
    return out


def _header_fields(raw: bytes, fields: list[str]) -> bytes:
    """The named header fields (with continuation lines) plus the blank line."""
    head = raw.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]
    wanted = {f.lower().encode() for f in fields}
    out: list[bytes] = []
    keep = False
    for line in head.splitlines():
        if line[:1] in (b" ", b"\t"):
            if keep:
                out.append(line)
            continue
        keep = line.split(b":", 1)[0].strip().lower() in wanted
        if keep:
            out.append(line)
    return b"".join(x + b"\r\n" for x in out) + b"\r\n"


class _Handler(socketserver.BaseRequestHandler):
    def setup(self):
        self.sock = self.request
        self.sock.settimeout(10)
        self.tls = False
        self.user = None
        self.box = None

    def finish(self):
        # The TLS-wrapped socket is a new object; socketserver only closes the original.
        for f in (getattr(self, "rfile", None), self.sock):
            with contextlib.suppress(OSError):
                if f is not None:
                    f.close()

    def send(self, data: bytes | str) -> None:
        self.sock.sendall(data.encode() if isinstance(data, str) else data)

    def handle(self):
        srv: ImapTestServer = self.server
        try:
            if srv.tls_mode == "ssl":
                self.sock = srv.ssl_context.wrap_socket(self.sock, server_side=True)
                self.tls = True
            self.rfile = self.sock.makefile("rb")
            self.send("* OK test IMAP server ready\r\n")
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                text = line.decode("utf-8", "replace").rstrip("\r\n")
                srv.commands.append(text)
                if self.dispatch(text) == "close":
                    return
        except (OSError, ValueError):
            return          # client went away, or a failed TLS handshake — both expected

    def capabilities(self) -> str:
        caps = "IMAP4rev1"
        if self.server.tls_mode == "starttls" and not self.tls:
            caps += " STARTTLS"
        return caps

    def dispatch(self, text: str):
        srv: ImapTestServer = self.server
        tag, _, rest = text.partition(" ")
        verb, _, args = rest.partition(" ")
        verb = verb.upper()
        if verb == "UID":
            sub, _, args = args.partition(" ")
            verb = "UID " + sub.upper()
        toks = _TOKEN.findall(args)
        if verb == "CAPABILITY":
            self.send(f"* CAPABILITY {self.capabilities()}\r\n{tag} OK CAPABILITY completed\r\n")
        elif verb == "NOOP":
            self.send(f"{tag} OK NOOP completed\r\n")
        elif verb == "LOGOUT":
            self.send(f"* BYE logging out\r\n{tag} OK LOGOUT completed\r\n")
            return "close"
        elif verb == "STARTTLS":
            if srv.tls_mode != "starttls" or self.tls:
                self.send(f"{tag} BAD STARTTLS not available\r\n")
                return None
            self.send(f"{tag} OK Begin TLS negotiation now\r\n")
            self.sock = srv.ssl_context.wrap_socket(self.sock, server_side=True)
            self.rfile = self.sock.makefile("rb")
            self.tls = True
        elif verb == "LOGIN" and len(toks) == 2:
            user, password = _unquote(toks[0]), _unquote(toks[1])
            if user == srv.user and password == srv.password:
                self.user = user
                self.send(f"{tag} OK LOGIN completed\r\n")
            elif srv.echo_password_on_failure:
                self.send(f'{tag} NO [AUTHENTICATIONFAILED] bad password "{password}"\r\n')
            else:
                self.send(f"{tag} NO [AUTHENTICATIONFAILED] Authentication failed\r\n")
        elif self.user is None:
            self.send(f"{tag} BAD command unknown or not allowed now\r\n")
        elif verb == "LIST":
            for name, box in srv.mailboxes.items():
                flags = " ".join(["\\HasNoChildren", *box.get("flags", [])])
                self.send(f'* LIST ({flags}) "/" {_quote(name)}\r\n')
            self.send(f"{tag} OK LIST completed\r\n")
        elif verb in ("SELECT", "EXAMINE") and len(toks) == 1:
            name = _unquote(toks[0])
            box = srv.mailboxes.get(name)
            if box is None:
                self.send(f"{tag} NO no such mailbox\r\n")
                return None
            self.box = name
            uids = sorted(box.get("messages", {}))
            self.send(f"* {len(uids)} EXISTS\r\n"
                      f"* OK [UIDVALIDITY {box['uidvalidity']}] UIDs valid\r\n"
                      f"* OK [UIDNEXT {max(uids, default=0) + 1}] Predicted next UID\r\n"
                      f"{tag} OK [READ-ONLY] {verb} completed\r\n")
        elif verb == "UID SEARCH" and self.box is not None:
            self.uid_search(tag, toks)
        elif verb == "UID FETCH" and self.box is not None and " " in args:
            spec, items = args.split(" ", 1)     # items may nest parentheses
            self.uid_fetch(tag, spec, items)
        else:
            self.send(f"{tag} BAD command unknown or not allowed now\r\n")
        return None

    def uid_search(self, tag: str, toks: list[str]) -> None:
        messages = self.server.mailboxes[self.box].get("messages", {})
        uids = sorted(messages)
        hits = set(uids)
        i = 0
        while i < len(toks):
            key = toks[i].upper()
            if key == "ALL":
                i += 1
            elif key == "UID" and i + 1 < len(toks):
                hits &= _uid_set(toks[i + 1], uids)
                i += 2
            elif key == "SINCE" and i + 1 < len(toks):
                since = _parse_date(_unquote(toks[i + 1]))
                hits &= {u for u in uids if messages[u][1].date() >= since}
                i += 2
            else:
                self.send(f"{tag} BAD unsupported search key\r\n")
                return
        self.send(f"* SEARCH {' '.join(map(str, sorted(hits)))}".rstrip() + "\r\n")
        self.send(f"{tag} OK SEARCH completed\r\n")

    def uid_fetch(self, tag: str, spec: str, items: str) -> None:
        messages = self.server.mailboxes[self.box].get("messages", {})
        uids = sorted(messages)
        upper = items.upper()
        header = re.search(r"BODY\.PEEK\[HEADER\.FIELDS \(([^)]*)\)\]", items, re.I)
        for uid in sorted(_uid_set(spec, uids)):
            seq = uids.index(uid) + 1
            raw, when = messages[uid]
            if header:
                fields = header.group(1).split()
                block = _header_fields(raw, fields)
                self.send(f"* {seq} FETCH (UID {uid} BODY[HEADER.FIELDS ({' '.join(fields)})] "
                          f"{{{len(block)}}}\r\n".encode() + block + b")\r\n")
            elif "BODY.PEEK[]" in upper or "BODY[]" in upper:
                if "BODY[]" in upper:
                    self.server.seen.setdefault(self.box, set()).add(uid)
                self.send(f"* {seq} FETCH (UID {uid} BODY[] {{{len(raw)}}}\r\n".encode()
                          + raw + b")\r\n")
            else:
                self.send(f'* {seq} FETCH (UID {uid} RFC822.SIZE {len(raw)} '
                          f'INTERNALDATE "{_internaldate(when)}")\r\n')
        self.send(f"{tag} OK FETCH completed\r\n")


class ImapTestServer(socketserver.ThreadingTCPServer):
    """Unpacks as `(host, port)`; `.commands` and `.seen` are what tests assert on."""

    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, *, mailboxes, user, password, tls_mode, ssl_context,
                 echo_password_on_failure=False):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.mailboxes = mailboxes
        self.user = user
        self.password = password
        self.tls_mode = tls_mode
        self.ssl_context = ssl_context
        self.echo_password_on_failure = echo_password_on_failure
        self.commands: list[str] = []
        self.seen: dict[str, set[int]] = {}

    @property
    def host(self) -> str:
        return self.server_address[0]

    @property
    def port(self) -> int:
        return self.server_address[1]

    def __iter__(self):
        return iter((self.host, self.port))

    def handle_error(self, request, client_address):
        pass                # tests read failures from the client side


@contextlib.contextmanager
def run_server(*, mailboxes, user, password, tls_mode, cert_pem, key_pem,
               echo_password_on_failure=False):
    """Serve on 127.0.0.1:<free port> in a daemon thread for the `with` block.

    `tls_mode`: "starttls", "ssl" (TLS from the first byte) or "none_offered"
    (plain, no STARTTLS capability). Yields the server, which unpacks as
    `(host, port)`."""
    with tempfile.TemporaryDirectory() as tmp:
        cert_file = os.path.join(tmp, "cert.pem")
        key_file = os.path.join(tmp, "key.pem")
        with open(cert_file, "w") as f:
            f.write(cert_pem)
        with open(key_file, "w") as f:
            f.write(key_pem)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_file, key_file)
    server = ImapTestServer(mailboxes=mailboxes, user=user, password=password,
                            tls_mode=tls_mode, ssl_context=ctx,
                            echo_password_on_failure=echo_password_on_failure)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def free_port() -> int:
    """A port nothing is listening on (bound, then released)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
