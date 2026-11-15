# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicholas K. Mitchell
#
# Smylte desk panel: a Raspberry Pi 5 that runs the Smylte server AND drives a
# Waveshare 7.5" e-Paper V2 panel on its own SPI header. It fetches the
# server's one-bit frame over loopback and paints it, no more often than the
# glass can take.
#
# WHY THIS DIRECTORY IS MIT AND NOT AGPL. The server is AGPL-3.0; this client
# only speaks to it over HTTP, as any panel on the network would, and imports
# nothing from it. Keeping it MIT means someone can copy it onto their own box
# without taking on the server's licence. No Waveshare code runs here: the
# driver beside this file (epd7in5_v2.py) is this repo's, sends the command
# bytes of Waveshare's MIT-licensed epd7in5_V2.py, and carries their notice.
# python3-libgpiod (LGPL-2.1-or-later) and python3-spidev (MIT) are imported
# from Raspberry Pi OS's own packages, not shipped.
#
# Tested shape: Pi 5, Pico-ePaper-7.5 module (Pico removed) jumpered to SPI0,
# Raspberry Pi OS Lite 64-bit 2026-10-06 (Debian 13), /usr/bin/python3 3.13.
# NOT YET RUN ON HARDWARE — CI checks it against the server and against
# Waveshare's driver byte for byte, but no glass has seen it.
#
# What it guarantees, and how:
#
#   * At least 180 s between refreshes, across restarts, crash loops and
#     reboots. Waveshare's spec: "Each update must be at least 180 s apart". The
#     time of the last refresh is kept on CLOCK_BOOTTIME in a state file, and a
#     refresh is recorded BEFORE it starts, so a crash halfway through still
#     counts. See floor_ok_at().
#   * A stop never interrupts a refresh. SIGTERM/SIGINT/SIGHUP are blocked and
#     only collected while waiting, with sigtimedwait(). A stop that arrives
#     mid-refresh is honoured as soon as the panel is in deep sleep.
#   * The panel is in deep sleep between refreshes, and unpowered whenever this
#     process is not running: close() on every exit, and the unit's
#     ExecStopPost (`--power-off`) after a kill. The Pi 5's GPIO block keeps an
#     output's level after the process dies, so the second one is not optional.
#   * Nothing off-contract reaches the glass. A frame is painted only when every
#     header says it is exactly the 800×480 inverted bitmap this panel takes,
#     and the body is exactly 48,000 bytes.
#   * A refresh at least once every 23 hours, because the spec asks for one a
#     day against ghosting, even if the server's frame has not changed.
#
# Run by deploy/smylte-panel.service. Install and update with
# `sudo deploy/panel-setup.sh`; firmware/README.md has the wiring and the rest.
#
#   panel.py               the service: fetch, compare, paint, forever
#   panel.py --selftest    power the controller up and down; no refresh
#   panel.py --clear       paint white (for storage), respecting the floor
#   panel.py --power-off   drive RST/DC/PWR low; for ExecStopPost

import dataclasses
import hashlib
import http.client
import importlib.util
import json
import logging
import math
import os
import pathlib
import re
import signal
import socket
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
log = logging.getLogger("smylte-panel")

# ── the contract with the server ─────────────────────────────────────────────
# Each of these is checked against the server itself in
# backend/tests/test_firmware_pi_contract.py, so neither side can drift alone.
HOST = "127.0.0.1"      # smylted/__main__.py binds here; numeric, so no DNS
PORT = 8080
WIDTH = 800
HEIGHT = 480
STRIDE = 100            # ceil(WIDTH / 8)
BUF_BYTES = STRIDE * HEIGHT
PATH_FMT = "/api/public/display/%s.bin"
# invert=1 because this driver, like Waveshare's Pi driver, takes 1 = black.
# The panel ends up receiving exactly the bytes the Pico sent from the plain
# `.bin` (the Pico driver inverts on its side). w/h state the panel's own size,
# so clearing the size in Settings cannot turn every fetch into a 422.
QUERY = "invert=1&w=800&h=480"
EXPECT_FORMAT = "mono-hlsb-inverted"
EXPECT_MEDIA = "application/octet-stream"
REQUIRED_HEADERS = (
    "content-type", "content-length", "etag", "x-display-width",
    "x-display-height", "x-display-stride", "x-display-format",
    "x-display-refresh-seconds",
)
USER_AGENT = "smylte-panel/1"

# ── the glass ────────────────────────────────────────────────────────────────
MIN_REFRESH_S = 180         # Waveshare: never sooner. Not configurable.
MAX_REFRESH_S = 86_400
FORCE_REPAINT_S = 82_800    # 23 h: repaint even an unchanged frame
PAINT_MAX_S = 90            # >= the driver's PAINT_WORST_S (checked in CI)

# ── the network ──────────────────────────────────────────────────────────────
SOCKET_TIMEOUT_S = 10       # per connect/recv
FETCH_DEADLINE_S = 20       # whole body
ERROR_RETRY_S = 60          # server down, 5xx, reset, timeout
GONE_RETRY_S = 900          # 404 (token rotated, display disabled or deleted),
                            # or a response this client refuses
THROTTLE_MIN_S = 60
THROTTLE_MAX_S = 3600
THROTTLE_DEFAULT_S = 300

# ── the box ──────────────────────────────────────────────────────────────────
# A Pi 5 has no RTC battery unless one is fitted, so after a power cut its
# clock is wrong until NTP answers, and the server on this same box would
# render the wrong day. So the first fetch waits for systemd-timesyncd's flag,
# or this many seconds of uptime if the box is offline.
CLOCK_SYNC_FILE = "/run/systemd/timesync/synchronized"
CLOCK_SYNC_GRACE_S = 300
CLOCK_CHECK_S = 5
PING_SLICE_S = 15           # longest wait between watchdog pings (WatchdogSec=60)
CREDENTIAL = "display-token"    # LoadCredential= name in the unit
TOKEN_MAX_BYTES = 512
STATE_FILE = "state.json"
STATE_MAX_BYTES = 4096
STATE_VERSION = 1
# Only for an e-Paper Driver HAT Rev2.3 or later, which switches the panel's
# power on BCM18. The Pico module has no such pin. Set it in
# /etc/default/smylte-panel (SMYLTE_PANEL_PWR_PIN=18): the unit reads that file
# as its EnvironmentFile, and panel-setup.sh hands the same file to its
# --selftest and --clear runs and to its own --power-off.
PWR_PIN_ENV = "SMYLTE_PANEL_PWR_PIN"

EX_OK = 0
EX_FAIL = 1         # restartable: hardware, panel, anything unexpected
EX_USAGE = 2
EX_CONFIG = 78      # EX_CONFIG: the unit's RestartPreventExitStatus

# secrets.token_urlsafe(32) is 43 characters; allow some room either way.
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{22,128}")
# A strong quoted ETag of printable ASCII, no quote, no space. The server's is
# '"' + 32 hex + '"'.
ETAG_RE = re.compile(r'"[\x21\x23-\x7e]{1,128}"')
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REFRESH_RE = re.compile(r"[0-9]{1,9}")
RETRY_RE = re.compile(r"[0-9]{1,6}")

STOP_SIGNALS = frozenset({signal.SIGTERM, signal.SIGINT, signal.SIGHUP})
REPAINT_SIGNAL = signal.SIGUSR1     # forget the glass; repaint when allowed
WAIT_SIGNALS = STOP_SIGNALS | {REPAINT_SIGNAL}

WHITE = bytes(BUF_BYTES)            # 1 = black, so all zeros is white paper
WHITE_SHA256 = hashlib.sha256(WHITE).hexdigest()


class ConfigError(Exception):
    """Something only the owner can fix. Exits 78, which stops restarts."""


# ── what a fetch can come back as ────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class Frame:
    body: bytes
    etag: str
    refresh_s: int


@dataclasses.dataclass(frozen=True)
class NotModified:
    etag: str
    refresh_s: int


@dataclasses.dataclass(frozen=True)
class Gone:
    pass


@dataclasses.dataclass(frozen=True)
class Throttled:
    retry_s: int


@dataclasses.dataclass(frozen=True)
class Refused:
    reason: str
    status: int | None = None


@dataclasses.dataclass(frozen=True)
class Transient:
    reason: str


# ── pure pieces ──────────────────────────────────────────────────────────────

def load_token(cred_dir: str | None) -> str:
    """The display token from systemd's credential directory.

    Never logged, never in the environment or on the command line. Exactly one
    trailing newline is allowed, because `echo token > file` writes one.
    """
    if not cred_dir:
        raise ConfigError(
            "no $CREDENTIALS_DIRECTORY — run this under smylte-panel.service, "
            f"which loads the token as credential {CREDENTIAL!r}")
    path = pathlib.Path(cred_dir) / CREDENTIAL
    try:
        with open(path, "rb") as f:
            raw = f.read(TOKEN_MAX_BYTES + 1)
    except OSError as e:
        raise ConfigError(
            f"cannot read credential {CREDENTIAL!r} ({e.strerror}) — "
            "run `sudo deploy/panel-setup.sh --rotate-token`") from None
    if len(raw) > TOKEN_MAX_BYTES:
        raise ConfigError(f"credential {CREDENTIAL!r} is too long to be a "
                          "display token")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise ConfigError(f"credential {CREDENTIAL!r} is not ASCII") from None
    if text.endswith("\n"):
        text = text[:-1]
    if TOKEN_RE.fullmatch(text):
        return text
    if not text:
        hint = "it is empty"
    elif "/" in text or ":" in text or "." in text:
        hint = ("it looks like a URL — store only the token, the part after "
                "/display/ and before .bin")
    else:
        hint = "a display token is 22–128 characters of A–Z, a–z, 0–9, _ and -"
    raise ConfigError(f"credential {CREDENTIAL!r} is not a display token: "
                      f"{hint} — run `sudo deploy/panel-setup.sh --rotate-token`")


def request_target(token: str) -> str:
    return PATH_FMT % token + "?" + QUERY


def check_headers(status: int, items, *, chunked: bool = False,
                  length: int | None = None) -> str | None:
    """None if a 200's headers describe exactly this panel's frame, else the
    name of the first check that failed.

    `items` is the response's (name, value) pairs, so a header sent twice is
    seen twice: two Content-Lengths are how a body gets smuggled past a check
    of one. Everything is decided before the body is read.
    """
    if status != 200:
        return f"status-{status}"
    seen: dict[str, list[str]] = {}
    for name, value in items:
        seen.setdefault(name.lower(), []).append(value)
    for name in REQUIRED_HEADERS:
        if len(seen.get(name, ())) != 1:
            return f"header-{name}"

    def one(name):
        return seen[name][0]

    if "transfer-encoding" in seen or chunked:
        return "transfer-encoding"
    encodings = seen.get("content-encoding")
    if encodings is not None and (len(encodings) != 1
                                  or encodings[0].lower() != "identity"):
        return "content-encoding"
    if one("content-type") != EXPECT_MEDIA:
        return "content-type"
    if one("content-length") != str(BUF_BYTES) or length != BUF_BYTES:
        return "content-length"
    if one("x-display-format") != EXPECT_FORMAT:
        return "x-display-format"
    if one("x-display-width") != str(WIDTH):
        return "x-display-width"
    if one("x-display-height") != str(HEIGHT):
        return "x-display-height"
    if one("x-display-stride") != str(STRIDE):
        return "x-display-stride"
    if not ETAG_RE.fullmatch(one("etag")):
        return "etag"
    return None


def clamp_refresh(value: str | None) -> int:
    """The server's advised interval, held to [180 s, 24 h]. 180 if unreadable."""
    if value is None or not REFRESH_RE.fullmatch(value):
        return MIN_REFRESH_S
    return min(MAX_REFRESH_S, max(MIN_REFRESH_S, int(value)))


def parse_retry_after(value: str | None) -> int:
    """A 429's Retry-After in seconds, held to [60 s, 1 h]; 300 if unreadable."""
    if value is None or not RETRY_RE.fullmatch(value):
        return THROTTLE_DEFAULT_S
    return min(THROTTLE_MAX_S, max(THROTTLE_MIN_S, int(value)))


@dataclasses.dataclass
class State:
    """What is on the glass, and when it got there. Kept in $STATE_DIRECTORY.

    Times ending `_bt` are CLOCK_BOOTTIME seconds: they never jump with NTP,
    and they restart from zero at boot, which floor_ok_at() accounts for.
    `complete` is false from the moment a refresh starts until it has ended.
    """
    etag: str | None = None
    glass_sha256: str | None = None
    painted_end_bt: float | None = None
    painted_wall: float | None = None
    attempt_start_bt: float | None = None
    complete: bool = False


def _time_field(v, limit: float) -> bool:
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)
                         and math.isfinite(v) and 0 <= v <= limit)


def parse_state(raw: bytes) -> State | None:
    """A State from the file's bytes, or None if anything about it is off."""
    if len(raw) > STATE_MAX_BYTES:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return None
    s = State(
        etag=data.get("etag"),
        glass_sha256=data.get("glass_sha256"),
        painted_end_bt=data.get("painted_end_bt"),
        painted_wall=data.get("painted_wall"),
        attempt_start_bt=data.get("attempt_start_bt"),
        complete=data.get("complete"),
    )
    if not isinstance(s.complete, bool):
        return None
    if s.etag is not None and not (isinstance(s.etag, str)
                                   and ETAG_RE.fullmatch(s.etag)):
        return None
    if s.glass_sha256 is not None and not (isinstance(s.glass_sha256, str)
                                           and SHA256_RE.fullmatch(s.glass_sha256)):
        return None
    if not (_time_field(s.painted_end_bt, 1e10) and _time_field(s.attempt_start_bt, 1e10)
            and _time_field(s.painted_wall, 1e11)):
        return None
    if s.complete and s.painted_end_bt is None:
        return None
    return s


def load_state(state_dir: pathlib.Path) -> State:
    """The saved state, or an empty one ("unknown") if missing or invalid.

    Unknown is safe: floor_ok_at() then waits the full floor from now.
    """
    path = state_dir / STATE_FILE
    try:
        with open(path, "rb") as f:
            raw = f.read(STATE_MAX_BYTES + 1)
    except FileNotFoundError:
        return State()
    except OSError as e:
        log.warning("cannot read %s (%s); treating the glass as unknown",
                    path, e.strerror)
        return State()
    s = parse_state(raw)
    if s is None:
        log.warning("%s is invalid; treating the glass as unknown", path)
        return State()
    return s


def save_state(state_dir: pathlib.Path, s: State) -> bool:
    """Write atomically and durably: temp file, fsync, rename, fsync the dir."""
    path = state_dir / STATE_FILE
    tmp = state_dir / (STATE_FILE + ".tmp")
    data = json.dumps({"version": STATE_VERSION, **dataclasses.asdict(s)},
                      sort_keys=True).encode("utf-8")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC,
                     0o600)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
        dfd = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
        return True
    except OSError as e:
        log.error("cannot write %s: %s", path, e)
        return False


def floor_ok_at(s: State, start_bt: float) -> float:
    """The earliest CLOCK_BOOTTIME at which a refresh is allowed, for a process
    that started at `start_bt` and found `s` on disk.

    The rule is a LOWER BOUND on the real time since the last refresh ended,
    and it must hold even though boot time restarts from zero at every boot:

      * A refresh that ended at `t` with t <= start_bt may be from this boot or
        an earlier one. Either way the real time since then is at least
        (now - t), so waiting until t + 180 is enough. (After a reboot it is
        more than enough, which only costs a few minutes.)
      * A time LATER than start_bt cannot be from this boot, so it is from an
        earlier one, and the real time since it is at least `now`. So 180 s of
        this boot's uptime is enough.
      * A refresh that started but never recorded its end ended no later than
        attempt_start + PAINT_MAX_S, and no later than start_bt, because the
        process doing it is gone before this one starts.
      * No record at all means unknown: wait the full floor from now.
    """
    if s.complete and s.painted_end_bt is not None:
        ended = s.painted_end_bt
    elif s.attempt_start_bt is not None:
        if s.attempt_start_bt <= start_bt:
            ended = min(s.attempt_start_bt + PAINT_MAX_S, start_bt)
        else:
            ended = s.attempt_start_bt
    else:
        return start_bt + MIN_REFRESH_S
    if ended > start_bt:
        return float(MIN_REFRESH_S)
    return ended + MIN_REFRESH_S


def forced_due(s: State, now_bt: float, now_wall: float, synced: bool) -> bool:
    """True once the glass has shown the same picture for 23 hours.

    Each test is a lower bound on the real time since the paint, as in
    floor_ok_at(): a paint time later than `now_bt` is from an earlier boot, so
    at least `now_bt` has passed since it.
    """
    if not s.complete or s.painted_end_bt is None:
        return False
    if s.painted_end_bt <= now_bt and now_bt - s.painted_end_bt >= FORCE_REPAINT_S:
        return True
    if s.painted_end_bt > now_bt and now_bt >= FORCE_REPAINT_S:
        return True
    return (synced and s.painted_wall is not None
            and now_wall - s.painted_wall >= FORCE_REPAINT_S)


def force_poll_at(s: State, now_bt: float, now_wall: float,
                  synced: bool) -> float | None:
    """The CLOCK_BOOTTIME by which to fetch so the 23-hour repaint is on time.

    None when nothing is painted, or when the repaint is already due by any of
    forced_due()'s bounds: then the next fetch is forced whenever it comes, and
    pulling it earlier would only defeat the retry backoff. The boot-time bound
    alone is late after a reboot (it cannot see the time the box was down), so
    the wall clock bounds it too once it is synced. run() records a paint time
    later than its own start, which must be from an earlier boot, as boot time
    0, so without a wall clock that one is due by 23 h of this boot's uptime.
    An earlier boot's paint at or before run()'s start cannot be told from this
    boot's, and is due 23 h after it.
    """
    if not s.complete or s.painted_end_bt is None:
        return None
    if forced_due(s, now_bt, now_wall, synced):
        return None
    at = []
    if s.painted_end_bt <= now_bt:
        if s.painted_end_bt + FORCE_REPAINT_S > now_bt:
            at.append(s.painted_end_bt + FORCE_REPAINT_S)
    elif FORCE_REPAINT_S > now_bt:
        at.append(float(FORCE_REPAINT_S))
    if synced and s.painted_wall is not None:
        left = s.painted_wall + FORCE_REPAINT_S - now_wall
        if left > 0:
            at.append(now_bt + left)
    return min(at) if at else None


# ── I/O ──────────────────────────────────────────────────────────────────────

def _single(items, name: str) -> str | None:
    values = [v for k, v in items if k.lower() == name]
    return values[0] if len(values) == 1 else None


def _read_body(resp, deadline: float, clock, tick) -> bytes | None:
    """Up to BUF_BYTES of body, or None if the deadline passed first."""
    buf = bytearray()
    while len(buf) < BUF_BYTES:
        if clock() > deadline:
            return None
        chunk = resp.read(min(16_384, BUF_BYTES - len(buf)))
        if not chunk:
            break
        buf += chunk
        tick()
    return bytes(buf)


def fetch(token: str, etag: str | None, *, host: str = HOST, port: int = PORT,
          timeout: float = SOCKET_TIMEOUT_S, deadline_s: float = FETCH_DEADLINE_S,
          clock=time.monotonic, tick=lambda: None):
    """One GET of this panel's frame. Never raises; returns a result class.

    Plain HTTP to a numeric loopback address: no DNS, no proxy (http.client
    never reads the proxy variables) and no redirects. Never sends X-Real-IP;
    the server trusts that header from loopback, and this client has no
    business choosing which address its fetches are counted against.
    """
    headers = {
        "Accept-Encoding": "identity",
        "Connection": "close",
        "User-Agent": USER_AGENT,
    }
    if etag is not None:
        headers["If-None-Match"] = etag
    start = clock()
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        conn.request("GET", request_target(token), headers=headers)
        resp = conn.getresponse()
        items = resp.getheaders()
        status = resp.status
        if status == 200:
            bad = check_headers(status, items, chunked=bool(resp.chunked),
                                length=resp.length)
            if bad:
                return Refused(bad, status)
            body = _read_body(resp, start + deadline_s, clock, tick)
            if body is None:
                return Transient(f"body took longer than {deadline_s:g} s")
            if len(body) != BUF_BYTES:
                return Transient(f"body ended at {len(body)} of {BUF_BYTES} bytes")
            return Frame(body, _single(items, "etag"),
                         clamp_refresh(_single(items, "x-display-refresh-seconds")))
        if status == 304:
            got = _single(items, "etag")
            if etag is None or got != etag:
                return Refused("304-etag", status)
            return NotModified(etag,
                               clamp_refresh(_single(items, "x-display-refresh-seconds")))
        if status == 404:
            return Gone()
        if status == 429:
            return Throttled(parse_retry_after(_single(items, "retry-after")))
        if status >= 500:
            return Transient(f"HTTP {status}")
        return Refused(f"HTTP {status}", status)
    except (OSError, http.client.HTTPException) as e:
        return Transient(type(e).__name__ + (f": {e}" if str(e) else ""))
    finally:
        conn.close()


def sd_notify(message: str) -> bool:
    """Tell systemd something (READY=1, WATCHDOG=1, STATUS=…). Never raises."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX,
                           socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as s:
            s.connect(addr)
            s.sendall(message.encode("utf-8"))
        return True
    except OSError:
        return False


def wait_for_signal(timeout: float) -> int | None:
    """Sleep up to `timeout` s; return a pending WAIT_SIGNALS signal, or None.

    Only works with those signals blocked (main() blocks them first), which is
    the point: a signal can only ever be taken here, never in the middle of a
    refresh.
    """
    info = signal.sigtimedwait(WAIT_SIGNALS, max(0.0, timeout))
    return None if info is None else info.si_signo


def boottime() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def clock_synced() -> bool:
    return os.path.exists(CLOCK_SYNC_FILE)


def _hm(wall: float) -> str:
    return time.strftime("%H:%M", time.localtime(wall))


@dataclasses.dataclass
class Deps:
    """Everything run() touches, so CI can run the real loop on fakes."""
    state_dir: pathlib.Path
    panel: object
    epd: object                 # the driver module, for its exception classes
    fetch: object               # (etag | None) -> result
    wait: object = wait_for_signal
    boottime: object = boottime
    walltime: object = time.time
    synced: object = clock_synced
    notify: object = sd_notify


def _showing(s: State) -> str:
    """The STATUS line for a healthy panel: what is on the glass."""
    if s.etag:
        what = s.etag[1:9]
    elif s.glass_sha256 == WHITE_SHA256:
        what = "white"
    else:
        what = "the last frame"
    since = f" since {_hm(s.painted_wall)}" if s.painted_wall is not None else ""
    return f"showing {what}{since}"


class _Problems:
    """Log each problem once when it starts, and once when it clears, and keep
    systemd's STATUS line saying either what is wrong or what is on the glass."""

    def __init__(self, notify):
        self.current = None
        self._message = ""
        self._notify = notify
        self._sent = None

    def set(self, key: str, message: str) -> None:
        if key == self.current:
            return
        log.warning("%s", message)
        self._notify(f"STATUS={message}; the glass keeps its last frame")
        self.current = key
        self._message = message
        self._sent = None

    def ok(self, showing: str) -> None:
        """The server answered and the glass is what it should be."""
        if self.current is not None:
            log.info("recovered from: %s", self._message)
            self.current = None
            self._message = ""
        if showing != self._sent:
            self._notify(f"STATUS={showing}")
            self._sent = showing


def _failed_in(panel) -> str:
    """Where a refresh failed. abort() leaves `phase` at "off", so the driver
    keeps the phase it was in when abort() began."""
    return getattr(panel, "aborted_in", None) or getattr(panel, "phase", "?")


def _drain(d: Deps) -> int | None:
    """Collect every signal already pending; return a stop signal if any."""
    stop = None
    while True:
        sig = d.wait(0)
        if sig is None:
            return stop
        if sig in STOP_SIGNALS:
            stop = sig


def _paint(d: Deps, frame: bytes, *, etag: str | None) -> tuple[State | None, float]:
    """Write-ahead, then init/display/sleep. Returns (new state, end time).

    (None, 0) means the write-ahead record could not be saved and nothing was
    sent to the panel. A panel failure raises after abort() has powered the
    panel down.
    """
    start = d.boottime()
    attempt = State(attempt_start_bt=start, complete=False)
    if not save_state(d.state_dir, attempt):
        return None, 0.0
    try:
        d.panel.init()
        d.panel.display(frame)
        d.panel.sleep()
    except BaseException as e:
        d.panel.abort(busy_stuck=isinstance(e, d.epd.BusyTimeout))
        raise
    end = d.boottime()
    synced = d.synced()
    done = State(etag=etag, glass_sha256=hashlib.sha256(frame).hexdigest(),
                 painted_end_bt=end,
                 painted_wall=d.walltime() if synced else None,
                 attempt_start_bt=start, complete=True)
    if not save_state(d.state_dir, done):
        log.error("refreshed, but could not record it — a restart will wait "
                  "the full floor before the next refresh")
    log.info("painted %s in %.1f s", etag[1:9] if etag else "white", end - start)
    return done, end


def run(d: Deps) -> int:
    """The service loop. Returns an exit code; never returns mid-refresh."""
    state = load_state(d.state_dir)
    start = d.boottime()
    if state.complete and state.painted_end_bt is not None \
            and state.painted_end_bt > start:
        # A paint time later than this process's start is from an earlier
        # boot, so at least this boot's uptime has passed since it. Record it
        # as boot time 0, which stays a true lower bound as uptime grows and
        # across a restart later in this boot. (Compared each time instead,
        # the paint would pass for this boot's once uptime overtook it.) Only
        # a paint time later than this start can be told from this boot's:
        # without a synced clock, one at or before it is due 23 h after it.
        state = dataclasses.replace(state, painted_end_bt=0.0)
        unsaved = not save_state(d.state_dir, state)
    else:
        unsaved = False     # retried after each fetch until it is on disk
    floor_at = floor_ok_at(state, start)
    next_poll = start
    problems = _Problems(d.notify)
    gate_logged = False
    healthy = False         # the last fetch was a 304, a dedupe or a paint
    cap_synced = False      # whether the 23-hour cap last saw a synced clock
    force_next = False      # a healthy answer left the 23-hour repaint due
    if floor_at > start:
        log.info("first refresh allowed in %d s (the 180 s floor is kept across "
                 "restarts)", math.ceil(floor_at - start))

    while True:
        now = d.boottime()
        gate_open = now >= CLOCK_SYNC_GRACE_S or d.synced()
        due = max(next_poll, floor_at)
        if not gate_open or now < due:
            if not gate_open and not gate_logged:
                log.info("waiting for the clock to sync (or %d s of uptime) "
                         "before the first fetch", CLOCK_SYNC_GRACE_S)
                gate_logged = True
            timeout = CLOCK_CHECK_S if not gate_open else min(PING_SLICE_S, due - now)
            sig = d.wait(timeout)
            d.notify("WATCHDOG=1")
            if sig in STOP_SIGNALS:
                log.info("stopping on signal %d", sig)
                return EX_OK
            if sig == REPAINT_SIGNAL:
                log.info("repaint requested; it happens at the next allowed time")
                state = dataclasses.replace(state, etag=None, glass_sha256=None)
                next_poll = d.boottime()
            elif healthy and not cap_synced and d.synced():
                # The clock synced after the next fetch was scheduled without
                # it. Ask now, once, so the wall-clock bound on the 23-hour
                # repaint applies, or a repaint it says is overdue happens.
                # Never after a failure: that would cut its backoff short.
                log.info("clock synced; checking the 23-hour repaint against it")
                cap_synced = True
                next_poll = d.boottime()
            continue

        # The sync flag is read once per fetch: a sync that lands during the
        # fetch is then picked up by the wait branch, not lost in between.
        synced = d.synced()
        forced = force_next or forced_due(state, now, d.walltime(), synced)
        force_next = False
        result = d.fetch(None if forced else state.etag)
        now = d.boottime()
        healthy = False

        if isinstance(result, Frame):
            sha = hashlib.sha256(result.body).hexdigest()
            if sha == state.glass_sha256 and not forced:
                # Same picture under a new ETag (or a server that ignored
                # If-None-Match): remember the tag, leave the glass alone.
                if result.etag != state.etag:
                    state = dataclasses.replace(state, etag=result.etag)
                    save_state(d.state_dir, state)
                problems.ok(_showing(state))
                next_poll = now + result.refresh_s
                healthy = True
            else:
                if _drain(d) is not None:
                    log.info("stopping before the refresh it would have started")
                    return EX_OK
                if d.boottime() < floor_at:     # cannot happen; belt and braces
                    log.error("refusing to refresh %.0f s inside the floor",
                              floor_at - d.boottime())
                    next_poll = floor_at
                    continue
                try:
                    done, end = _paint(d, result.body, etag=result.etag)
                except Exception as e:
                    phase = _failed_in(d.panel)
                    if isinstance(e, d.epd.PanelError):
                        log.error("refresh failed during %s: %s", phase, e)
                    else:
                        log.critical("refresh failed during %s", phase,
                                     exc_info=True)
                    return EX_FAIL
                if done is None:
                    problems.set("state", "could not record the refresh before "
                                          "starting it, so it was not started "
                                          "(the floor would not survive a "
                                          f"crash); retrying every {ERROR_RETRY_S} s")
                    next_poll = now + ERROR_RETRY_S
                    continue
                state = done
                floor_at = end + MIN_REFRESH_S
                next_poll = end + result.refresh_s
                problems.ok(_showing(state))
                healthy = True
        elif isinstance(result, NotModified):
            problems.ok(_showing(state))
            next_poll = now + result.refresh_s
            healthy = True
        elif isinstance(result, Gone):
            problems.set("gone", "the server does not know this display (404): "
                                 "token rotated, or display disabled or deleted "
                                 "— `sudo deploy/panel-setup.sh --rotate-token` "
                                 "after a rotation")
            next_poll = now + GONE_RETRY_S
        elif isinstance(result, Throttled):
            problems.set("throttled", f"throttled by the server (429); next "
                                      f"try in {result.retry_s} s")
            next_poll = now + result.retry_s
        elif isinstance(result, Refused):
            problems.set(f"refused:{result.reason}",
                         f"refused the server's response ({result.reason}) — "
                         "server and client disagree about the frame")
            next_poll = now + GONE_RETRY_S
        else:
            reason = getattr(result, "reason", repr(result))
            problems.set("transient", f"server not answering ({reason})")
            next_poll = now + ERROR_RETRY_S

        if unsaved:
            unsaved = not save_state(d.state_dir, state)

        # Keep the 23-hour repaint on time even if the server advises 24 h,
        # and across a reboot, but only after a healthy answer: a failure's
        # backoff is never cut short, and a forced fetch follows it anyway.
        # The clocks are read again, since the fetch (or paint) took time.
        cap_synced = synced
        if healthy:
            bt, wall = d.boottime(), d.walltime()
            if forced_due(state, bt, wall, cap_synced):
                # It came due during the fetch: fetch again now, forced.
                force_next = True
                next_poll = bt
            else:
                force_at = force_poll_at(state, bt, wall, cap_synced)
                if force_at is not None:
                    next_poll = min(next_poll, force_at)


def clear(d: Deps) -> int:
    """Paint white, for storage, once the floor allows. Records it in state."""
    state = load_state(d.state_dir)
    floor_at = floor_ok_at(state, d.boottime())
    if d.boottime() < floor_at:
        log.info("clearing in %d s (the 180 s floor)",
                 math.ceil(floor_at - d.boottime()))
    while d.boottime() < floor_at:
        sig = d.wait(min(PING_SLICE_S, floor_at - d.boottime()))
        if sig in STOP_SIGNALS:
            return EX_OK
    try:
        done, _ = _paint(d, WHITE, etag=None)
    except Exception as e:
        log.error("clear failed during %s: %s", _failed_in(d.panel), e)
        return EX_FAIL
    if done is None:
        log.error("could not record the refresh before starting it; not cleared")
        return EX_FAIL
    log.info("cleared to white")
    return EX_OK


# ── start-up ─────────────────────────────────────────────────────────────────

class _Formatter(logging.Formatter):
    """Journal priorities, and the token cut to four characters, whatever logs."""

    _PRIORITY = {logging.CRITICAL: 2, logging.ERROR: 3, logging.WARNING: 4,
                 logging.INFO: 6, logging.DEBUG: 7}

    def __init__(self, journal: bool):
        super().__init__("%(message)s" if journal
                         else "%(asctime)s %(levelname)s %(message)s")
        self.journal = journal
        self.token: str | None = None

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if self.token:
            text = text.replace(self.token, self.token[:4] + "…")
        if self.journal:
            pri = self._PRIORITY.get(record.levelno, 6)
            text = "\n".join(f"<{pri}>{line}" for line in text.splitlines())
        return text


def setup_logging() -> _Formatter:
    fmt = _Formatter(journal=bool(os.environ.get("JOURNAL_STREAM")))
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    return fmt


def pwr_pin_from_env() -> int | None:
    raw = os.environ.get(PWR_PIN_ENV, "").strip()
    if not raw or raw.lower() == "none":
        return None
    reserved = {17, 24, 25, 7, 8, 9, 10, 11}    # RST, BUSY, DC, SPI0
    if not raw.isdigit() or not 2 <= int(raw) <= 27 or int(raw) in reserved:
        raise ConfigError(f"{PWR_PIN_ENV}={raw!r} is not a free BCM pin")
    return int(raw)


def state_dir_from_env() -> pathlib.Path:
    raw = os.environ.get("STATE_DIRECTORY", "")
    if not raw:
        raise ConfigError("no $STATE_DIRECTORY — run under the unit, which sets "
                          "StateDirectory=smylte-panel")
    return pathlib.Path(raw.split(":")[0])


def open_driver():
    """The driver beside this file. Loaded by path because `python3 -I` leaves
    the script's own directory off sys.path."""
    spec = importlib.util.spec_from_file_location(
        "smylte_panel_epd", HERE / "epd7in5_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def code_id() -> str:
    """Short hash of this file and the driver, logged at start, so a stale
    installed copy shows in the journal (panel-setup.sh --status compares)."""
    h = hashlib.sha256()
    for name in ("panel.py", "epd7in5_v2.py"):
        try:
            h.update((HERE / name).read_bytes())
        except OSError:
            h.update(b"?")
    return h.hexdigest()[:8]


USAGE = "usage: panel.py [--selftest | --clear | --power-off]"


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    mode = args[0] if args else "run"
    if len(args) > 1 or mode not in ("run", "--selftest", "--clear", "--power-off"):
        print(USAGE, file=sys.stderr)
        return EX_USAGE

    if mode == "--power-off":
        # First, and as root or not: this runs after a kill, and its only job
        # is to leave the panel unpowered. A bad PWR setting must not stop it.
        setup_logging()
        try:
            pwr = pwr_pin_from_env()
        except ConfigError as e:
            log.warning("%s; driving RST and DC only", e)
            pwr = None
        try:
            open_driver().drive_lines_low(pwr)
        except Exception as e:
            log.warning("power-off: %s", e)
        return EX_OK

    # Before anything else can take a signal: from here on, stops are only
    # ever collected by wait_for_signal().
    signal.pthread_sigmask(signal.SIG_BLOCK, WAIT_SIGNALS)
    fmt = setup_logging()

    if os.geteuid() == 0:
        log.critical("refusing to run as root — use smylte-panel.service, which "
                     "runs it as a dynamic user with only the gpio and spi groups")
        return EX_CONFIG
    try:
        pwr = pwr_pin_from_env()
        token = load_token(os.environ.get("CREDENTIALS_DIRECTORY")) \
            if mode == "run" else None
        state_dir = state_dir_from_env() if mode in ("run", "--clear") else None
    except ConfigError as e:
        log.critical("%s", e)
        return EX_CONFIG
    fmt.token = token

    epd = None
    try:
        epd = open_driver()
        lines, spi_factory, chip = epd.open_hardware(pwr)
    except Exception as e:
        if epd is not None and isinstance(e, epd.HardwareMissing):
            log.error("hardware: %s", e)
        else:
            log.error("hardware: unexpected %s: %s", type(e).__name__, e)
        return EX_FAIL

    last_ping = [0.0]

    def tick():
        # The driver calls this on every 20 ms BUSY poll; systemd needs a ping
        # within WatchdogSec, not fifty a second.
        now = time.monotonic()
        if now - last_ping[0] >= 1.0:
            last_ping[0] = now
            sd_notify("WATCHDOG=1")

    panel = epd.Panel(lines, spi_factory, pwr_pin=pwr, tick=tick)
    try:
        log.info("ready: %s, spidev%d.%d at %d Hz, PWR %s, code %s", chip,
                 epd.SPI_BUS, epd.SPI_DEVICE, epd.SPI_HZ,
                 "none" if pwr is None else f"BCM{pwr}", code_id())
        if mode == "--selftest":
            try:
                panel.init()
                panel.sleep()
            except Exception as e:
                panel.abort(busy_stuck=isinstance(e, epd.BusyTimeout))
                log.error("self-test failed during %s: %s", _failed_in(panel), e)
                return EX_FAIL
            log.info("self-test passed: the controller powered up and down "
                     "(no refresh)")
            return EX_OK
        assert state_dir is not None
        if mode == "--clear":
            return clear(Deps(state_dir=state_dir, panel=panel, epd=epd,
                              fetch=None))

        def do_fetch(etag):
            return fetch(token, etag, tick=tick)

        sd_notify("READY=1\nSTATUS=ready; waiting for the first allowed refresh")
        return run(Deps(state_dir=state_dir, panel=panel, epd=epd,
                        fetch=do_fetch))
    except Exception:
        log.critical("unexpected failure", exc_info=True)
        return EX_FAIL
    finally:
        panel.close()


if __name__ == "__main__":
    sys.exit(main())
