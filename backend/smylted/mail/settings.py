"""The mail configuration: its shape, its defaults, and the checks on every field.

Stored as one JSON object in `meta` under `mail_settings`, written by the
settings route and read by the pipeline. The two halves are deliberately
asymmetric:

- The `check_*` validators are strict and raise a sentence naming the bad
  entry. They guard the route, where the owner is looking at the form and
  can fix a typo.
- `load` is tolerant and never raises. It guards the pipeline, which runs
  unattended: a stored value that a later version considers invalid (or a
  hand-edited database) must cost that one field its value, not stop mail
  from being read. Each bad field falls back to its default, each bad list
  entry is dropped.

The folder rules live here too because they are configuration in effect:
`is_hard_excluded` names the folders that are never read whatever the owner
selects (Sent, Drafts, All Mail, Spam, Trash — reading them would turn the
owner's own mail, or duplicates, or junk, into suggestions), and
`folder_selected` is the one place a configured name is compared with a
server's.

No secret lives in this configuration. The IMAP password and the API keys
are in the secret store; the pinned certificate and the Anthropic workspace id
are public by nature.
"""
from __future__ import annotations

import dataclasses
import hashlib
import ipaddress
import math
import re
import ssl
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from . import addresses, kindrules
from .authres import DEFAULT_TRUSTED

MAIL_SETTINGS_KEY = "mail_settings"
MAIL_STATUS_KEY = "mail_status"
SECRETS_MARKER_KEY = "secrets_backend"
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_JEV_MODEL = "jev-latest"

HARD_EXCLUDED_FLAGS = frozenset({"\\sent", "\\drafts", "\\all", "\\junk", "\\trash"})
HARD_EXCLUDED_NAMES = frozenset({"sent", "sent items", "sent mail", "sent messages", "drafts",
    "all mail", "spam", "junk", "junk e-mail", "junk email", "trash", "deleted items",
    "deleted messages", "bin"})

IMAP_TLS_MODES = ("starttls", "ssl")
IMAP_CERT_MODES = ("system", "pinned", "insecure_localhost")
KIND_DECIDERS = ("model", "jev", "rules")
DEDUP_DECIDERS = ("model", "jev")

MAX_FOLDERS = 50
MAX_FOLDER_CHARS = 200
MAX_ADDRESSES = 100
MAX_PATTERNS = 500
MAX_AUTHSERV = 20
MAX_PEM_CHARS = 20000
MAX_SLUG_CHARS = 200

_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]*$")
_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_PEM_BLOCK = re.compile(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S)
_PEM_ERROR = ("that is not a PEM certificate (export it from Bridge: "
              "Settings → Advanced → Export TLS certificates)")


@dataclass(frozen=True)
class MailConfig:
    enabled: bool = False
    model: str = DEFAULT_MODEL
    imap_host: str = "127.0.0.1"
    imap_port: int = 1143
    imap_username: str = ""
    imap_tls: str = "starttls"                  # "starttls" | "ssl"
    imap_cert_mode: str = "system"              # "system" | "pinned" | "insecure_localhost"
    imap_pinned_cert: str = ""                  # PEM text (public, not a secret)
    folders: tuple[str, ...] = ("INBOX",)
    self_addresses: tuple[str, ...] = ()
    always_parse: tuple[str, ...] = ()
    never_parse: tuple[str, ...] = ()
    capture_notes_to_self: bool = True
    poll_minutes: int = 5                       # 1..1440
    body_max_chars: int = 8000                  # 500..100000
    backfill_days: int = 7                      # 0..90
    task_list: str | None = None                # list id (slug) or None → first list at approval
    event_calendar: str | None = None           # calendar id (slug) or None → first calendar
    trusted_authserv_ids: tuple[str, ...] = DEFAULT_TRUSTED
    auto_accept_min_confidence: float | None = None   # hook; None = disabled (the default)
    # "jev" in either decider means "Jev when a TypeSafe key is set, else the
    # model": the key's presence is the owner's opt-in to sending text there.
    kind_decider: str = "jev"                   # "model" | "jev" | "rules" (see kindrules, jev)
    kind_rules: tuple[str, ...] = ()            # canonical rule texts
    dedup_decider: str = "jev"                  # "model" | "jev" (Claude when Jev is unsure)
    jev_model: str = DEFAULT_JEV_MODEL          # TypeSafe model for either decider
    anthropic_workspace_id: str = ""            # only for keys not scoped to a workspace
    # Server-maintained, never in `public()` or the settings patch: the
    # `connection_binding` the stored IMAP password was saved (or, for an env
    # password, the service started) under. See `password_binding_ok`.
    imap_password_binding: str = ""


FIELDS: tuple[str, ...] = tuple(f.name for f in dataclasses.fields(MailConfig))

# The settings that decide where the IMAP password is sent and as whom.
BOUND_FIELDS: tuple[str, ...] = ("imap_host", "imap_port", "imap_tls", "imap_cert_mode",
                                 "imap_pinned_cert", "imap_username")
PASSWORD_BINDING_MESSAGE = (
    "the Bridge password was saved for different server settings (host, port, encryption, "
    "certificate or username); enter it again. A password from SMYLTE_MAIL_IMAP_PASSWORD "
    "is bound at startup: restart the service after changing the server.")
_BINDING = re.compile(r"^[0-9a-f]{64}$")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# --- validators: strict, for the settings route ------------------------------

def check_model(v: str) -> str:
    m = (v or "").strip()
    if not (1 <= len(m) <= 100) or not _MODEL.match(m):
        raise ValueError("model must be a model id such as claude-haiku-4-5")
    return m


def check_workspace_id(v: str) -> str:
    # An id, not a secret: it names the workspace a key without one bills to,
    # and is sent as the anthropic-workspace-id header (see llm.LlmClient).
    w = (v or "").strip()
    if w and not _WORKSPACE_ID.match(w):
        raise ValueError("workspace id must look like wrkspc_…")
    return w


def check_host(v: str) -> str:
    h = (v or "").strip()
    if h.startswith("[") and h.endswith("]"):
        try:
            return str(ipaddress.IPv6Address(h[1:-1]))
        except ValueError:
            raise ValueError("host must be a hostname or IP address") from None
    if (not (1 <= len(h) <= 253) or "/" in h or "@" in h
            or any(ch.isspace() for ch in h)):
        raise ValueError("host must be a hostname or IP address")
    return h


def check_username(v: str) -> str:
    u = (v or "").strip()
    if len(u) > 320 or "\r" in u or "\n" in u:
        raise ValueError("the IMAP username must be one line of at most 320 characters")
    return u


def _folder(entry: str) -> str:
    f = entry.strip()
    if len(f) > MAX_FOLDER_CHARS or "\r" in f or "\n" in f:
        raise ValueError(f"{entry!r} is not a folder name (one line, at most "
                         f"{MAX_FOLDER_CHARS} characters)")
    # RFC 3501: INBOX is case-insensitive, so every spelling is the one folder.
    return "INBOX" if f.upper() == "INBOX" else f


def _address(entry: str) -> str:
    a = addresses.normalize_address(entry)
    if a is None:
        raise ValueError(f"{entry!r} is not an email address")
    return a


def _pattern(entry: str) -> str:
    p = addresses.normalize_pattern(entry)
    if p is None:
        raise ValueError(f"{entry!r} is not an address, a domain, or *.domain")
    return p


def _authserv(entry: str) -> str:
    p = addresses.normalize_pattern(entry)
    if p is None or "@" in p:
        raise ValueError(f"{entry!r} is not a server name or *.domain")
    return p


def _check_list(values: Iterable[str], one: Callable[[str], str], limit: int,
                too_many: str) -> list[str]:
    """Each non-blank entry through `one`, deduplicated in order, at most `limit`."""
    out: list[str] = []
    for entry in values:
        if not isinstance(entry, str):
            raise ValueError(f"{entry!r} is not text")
        if not entry.strip():
            continue
        norm = one(entry)
        if norm not in out:
            out.append(norm)
    if len(out) > limit:
        raise ValueError(too_many)
    return out


def check_folders(values: list[str]) -> list[str]:
    # An empty list is allowed: it means "scan nothing", not "scan INBOX".
    return _check_list(values, _folder, MAX_FOLDERS,
                       f"at most {MAX_FOLDERS} folders can be scanned")


def check_addresses(values: list[str]) -> list[str]:
    return _check_list(values, _address, MAX_ADDRESSES,
                       f"at most {MAX_ADDRESSES} addresses can be listed")


def check_patterns(values: list[str]) -> list[str]:
    return _check_list(values, _pattern, MAX_PATTERNS,
                       f"at most {MAX_PATTERNS} sender patterns can be listed")


def check_authserv_patterns(values: list[str]) -> list[str]:
    return _check_list(values, _authserv, MAX_AUTHSERV,
                       f"at most {MAX_AUTHSERV} trusted servers can be listed")


def check_kind_rules(values: list[str]) -> list[str]:
    return kindrules.check_rules(values)


def _pem_der(pem: str) -> tuple[str, bytes]:
    """The one certificate block in `pem` and its DER bytes; ValueError otherwise."""
    blocks = _PEM_BLOCK.findall(pem)
    if len(blocks) != 1:
        raise ValueError(_PEM_ERROR)
    block = blocks[0].replace("\r\n", "\n").replace("\r", "\n")
    try:
        from cryptography import x509

        der = ssl.PEM_cert_to_DER_cert(block)
        x509.load_der_x509_certificate(der)
    except Exception:  # noqa: BLE001 — base64, ASN.1 and import failures all mean "not a cert"
        raise ValueError(_PEM_ERROR) from None
    return block, der


def check_pem(v: str) -> str:
    p = (v or "").strip()
    if not p:
        return ""
    if len(p) > MAX_PEM_CHARS:
        raise ValueError(_PEM_ERROR)
    # Only the certificate block is kept: a key pasted along with it is dropped.
    block, _ = _pem_der(p)
    return block + "\n"


def pem_fingerprint(pem: str) -> str | None:
    """SHA-256 of the certificate's DER as `AB:CD:…`, or None for no/invalid PEM."""
    try:
        _, der = _pem_der(pem or "")
    except ValueError:
        return None
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def connection_binding(cfg: MailConfig) -> str:
    """A digest of the `BOUND_FIELDS` of `cfg`: which server the password goes to.

    The password is bound to the server it was entered for so that a changed
    host, port, encryption, certificate or username cannot carry the stored
    password to somewhere the owner never typed it for — a session that can
    edit the settings could otherwise point them at its own server and press
    "Test". The certificate enters as its fingerprint, so re-pasting the same
    certificate with different line breaks is not a change.
    """
    parts = [cfg.imap_host.lower(), str(cfg.imap_port), cfg.imap_tls, cfg.imap_cert_mode,
             pem_fingerprint(cfg.imap_pinned_cert) or "", cfg.imap_username]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def password_binding_ok(cfg: MailConfig) -> bool:
    """Was the IMAP password saved (or bound at startup) for `cfg`'s server settings?"""
    return bool(cfg.imap_password_binding) and cfg.imap_password_binding == connection_binding(cfg)


# --- tolerant load, for the pipeline -----------------------------------------

def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _tolerant(values: object, one: Callable[[str], str], limit: int) -> tuple[str, ...] | None:
    """`values` with bad entries dropped, deduplicated, capped; None when not a list."""
    if not isinstance(values, (list, tuple)):
        return None
    out: list[str] = []
    for entry in values:
        if not isinstance(entry, str) or not entry.strip():
            continue
        try:
            norm = one(entry)
        except ValueError:
            continue
        if norm not in out:
            out.append(norm)
        if len(out) >= limit:
            break
    return tuple(out)


def _rule(entry: str) -> str:
    rules = kindrules.check_rules([entry])
    if not rules:                    # a comment line: nothing to keep
        raise ValueError("not a rule")
    return rules[0]


def _slug(v: object) -> str | None:
    if isinstance(v, str) and v.strip() and len(v.strip()) <= MAX_SLUG_CHARS:
        return v.strip()
    return None


def load(stored: Mapping | None) -> MailConfig:
    """A MailConfig from the stored JSON. Never raises; see the module docstring."""
    if not isinstance(stored, Mapping):
        return MailConfig()
    d = MailConfig()
    vals: dict[str, object] = {}

    def text(key: str, check: Callable[[str], str]) -> None:
        v = stored.get(key)
        if isinstance(v, str):
            try:
                vals[key] = check(v)
            except ValueError:
                pass

    def choice(key: str, allowed: tuple[str, ...]) -> None:
        if stored.get(key) in allowed:
            vals[key] = stored[key]

    def integer(key: str, lo: int, hi: int) -> None:
        v = stored.get(key)
        if _is_int(v) and lo <= v <= hi:
            vals[key] = v

    def flag(key: str) -> None:
        if isinstance(stored.get(key), bool):
            vals[key] = stored[key]

    def listing(key: str, one: Callable[[str], str], limit: int) -> None:
        v = _tolerant(stored.get(key), one, limit)
        if v is not None:
            vals[key] = v

    flag("enabled")
    text("model", check_model)
    text("imap_host", check_host)
    integer("imap_port", 1, 65535)
    text("imap_username", check_username)
    choice("imap_tls", IMAP_TLS_MODES)
    choice("imap_cert_mode", IMAP_CERT_MODES)
    text("imap_pinned_cert", check_pem)
    listing("folders", _folder, MAX_FOLDERS)
    listing("self_addresses", _address, MAX_ADDRESSES)
    listing("always_parse", _pattern, MAX_PATTERNS)
    listing("never_parse", _pattern, MAX_PATTERNS)
    flag("capture_notes_to_self")
    integer("poll_minutes", 1, 1440)
    integer("body_max_chars", 500, 100000)
    integer("backfill_days", 0, 90)
    if "task_list" in stored:
        vals["task_list"] = _slug(stored["task_list"])
    if "event_calendar" in stored:
        vals["event_calendar"] = _slug(stored["event_calendar"])
    listing("trusted_authserv_ids", _authserv, MAX_AUTHSERV)
    conf = stored.get("auto_accept_min_confidence")
    if ((_is_int(conf) or isinstance(conf, float))
            and math.isfinite(conf) and 0 <= conf <= 1):
        vals["auto_accept_min_confidence"] = float(conf)
    choice("kind_decider", KIND_DECIDERS)
    listing("kind_rules", _rule, kindrules.MAX_RULES)
    choice("dedup_decider", DEDUP_DECIDERS)
    text("jev_model", check_model)
    text("anthropic_workspace_id", check_workspace_id)
    binding = stored.get("imap_password_binding")
    if isinstance(binding, str) and _BINDING.match(binding):
        vals["imap_password_binding"] = binding
    return dataclasses.replace(d, **vals)


def public(cfg: MailConfig) -> dict:
    """`cfg` as a JSON-ready dict (tuples become lists), without the
    server-maintained password binding."""
    return {k: list(v) if isinstance(v, tuple) else v
            for k, v in dataclasses.asdict(cfg).items() if k != "imap_password_binding"}


# --- folders and hosts ---------------------------------------------------------

def is_hard_excluded(name: str, flags: Iterable[str] = (), delimiter: str | None = None) -> bool:
    """Is `name` a folder that is never read, whatever the owner selected?

    The special-use flag (RFC 6154) is the reliable signal; the names catch
    servers that do not send one. The leaf is tested so `[Gmail]/Sent Mail`
    is caught, and the whole name so a server whose delimiter we were not told
    still matches a top-level `Sent Items`.
    """
    if any(isinstance(f, str) and f.lower() in HARD_EXCLUDED_FLAGS for f in flags or ()):
        return True
    n = name or ""
    leaf = n.split(delimiter)[-1] if delimiter else n.split("/")[-1]
    return (leaf.strip().lower() in HARD_EXCLUDED_NAMES
            or n.strip().lower() in HARD_EXCLUDED_NAMES)


def folder_selected(name: str, configured: Iterable[str]) -> bool:
    """Is `name` among `configured`? INBOX compares case-insensitively (RFC 3501),
    every other name exactly — `Labels/X` and `labels/x` are different folders."""
    inbox = (name or "").upper() == "INBOX"
    for c in configured or ():
        if c == name or (inbox and isinstance(c, str) and c.upper() == "INBOX"):
            return True
    return False


def is_loopback_host(host: str) -> bool:
    """`localhost` or a loopback IP literal. A name that would need DNS is not
    loopback here: what it resolves to can change after the setting is saved."""
    h = (host or "").strip()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    if h.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False
