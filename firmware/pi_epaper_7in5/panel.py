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
#     only collected by one thread, and the loop reads them only between
#     refreshes (see Collector). A stop that arrives
#     mid-refresh is honoured as soon as the panel is in deep sleep.
#   * The panel is in deep sleep between refreshes, and unpowered whenever this
#     process is not running: close() on every exit, and the unit's
#     ExecStopPost (`--power-off`) after a kill. The Pi 5's GPIO block keeps an
#     output's level after the process dies, so the second one is not optional.
#   * Nothing off-contract reaches the glass. A frame is painted only when every
#     header says it is exactly the 800×480 inverted bitmap this panel takes,
#     and the body is exactly 48,000 bytes.
#   * A refresh at least once every 23 hours, because the spec asks for one a
#     day against ghosting, even if the server's frame has not changed: never
#     later than 23 hours after this process started, and by the wall clock
#     when the last refresh recorded a synced one and the clock is synced now
#     (give or take the floor and one PING_SLICE_S to notice a sync). Like any
#     refresh it needs its write-ahead record, so none starts while the state
#     file cannot be written.
#
# Run by deploy/smylte-panel.service. Install and update with
# `sudo deploy/panel-setup.sh`; firmware/README.md has the wiring and the rest.
#
#   panel.py               the service: fetch, compare, paint, forever
#   panel.py --selftest    power the controller up and down; no refresh
#   panel.py --clear       paint white (for storage), respecting the floor
#   panel.py --power-off   drive RST/DC/PWR low; for ExecStopPost
#   panel.py --keytest     print what the key's presses would do, for 30 s
#   panel.py --reset-refresh   turn fast and partial refresh back on

import collections
import dataclasses
import errno
import fcntl
import hashlib
import http.client
import importlib.util
import json
import logging
import math
import os
import pathlib
import re
import select
import signal
import socket
import struct
import sys
import threading
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
# The desk key's views, in the order a tap cycles them: Today, Now, Calendar.
# These are the server's `mode` values (`?mode=`, X-Display-Mode).
VIEWS = ("habits", "now", "calendar")
TODAY = "habits"            # the view a wake or the idle return shows
SCREENS = ("confirm", "off")    # the server's `?screen=` values

# ── the glass ────────────────────────────────────────────────────────────────
MIN_REFRESH_S = 180         # Waveshare: never sooner. Not configurable.
MAX_REFRESH_S = 86_400
FORCE_REPAINT_S = 82_800    # 23 h: repaint even an unchanged frame
PAINT_MAX_S = 90            # >= the driver's PAINT_WORST_S (checked in CI)
FULL_EVERY = 5              # a full refresh after this many fast or partial ones
# A panel from before Waveshare's 2023 batch takes far longer than this for a
# partial or a fast refresh; past these, quick refresh is turned off for good.
QUICK_PARTIAL_MAX_S = 1.0
QUICK_FAST_MAX_S = 3.0

# ── the network ──────────────────────────────────────────────────────────────
SOCKET_TIMEOUT_S = 10       # per connect/recv
FETCH_DEADLINE_S = 20       # whole body
ERROR_RETRY_S = 60          # server down, 5xx, reset, timeout
GONE_RETRY_S = 900          # 404 (token rotated, display disabled or deleted),
                            # or a response this client refuses
THROTTLE_MIN_S = 60
THROTTLE_MAX_S = 3600
THROTTLE_DEFAULT_S = 300
STARTUP_RETRY_S = 5         # a Transient before the first paint retries this soon,
STARTUP_WINDOW_S = 600      # for at most this long into the process's life
BG_GAP_S = 2                # background fetches: at least this far apart,
BG_RETRY_S = 60             # a failed item no sooner than this again,
SCREEN_REVALIDATE_S = 3600  # and the cached screens refetched this often
VIEWS_RECHECK_S = 900       # while the server will not switch views, ask again

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
STATE_VERSION = 2           # version 1 files are migrated; see parse_state()
# 18 is the Driver HAT's power switch; harmless on the Pico module, where
# GPIO18 is unconnected. `none` turns it off. Set in /etc/default/smylte-panel:
# the unit reads that file as its EnvironmentFile, and panel-setup.sh hands the
# same file to its --selftest and --clear runs and to its own --power-off.
PWR_PIN_ENV = "SMYLTE_PANEL_PWR_PIN"
REFRESH_ENV = "SMYLTE_PANEL_REFRESH"        # fast (default) | full
IDLE_ENV = "SMYLTE_PANEL_IDLE_RETURN_S"     # 0 (default, off) | 60–86400
KEY_ENV = "SMYLTE_PANEL_KEY"                # auto (default) | off

# The key: the Pi 5's power button, read as an input device. logind is told to
# leave it alone by this drop-in, which panel-setup.sh installs.
LOGIND_DROPIN = "/etc/systemd/logind.conf.d/50-smylte-panel.conf"
SYSFS_INPUT = "/sys/class/input"
KEY_DEVICE_NAME = "pwr_button"      # the Pi 5 firmware's gpio-keys node
EV_SYN = 0                          # <linux/input-event-codes.h>
EV_KEY = 1
SYN_DROPPED = 3
KEY_POWER = 116
EVIOCSCLOCKID = 0x400445A0          # _IOW('E', 0xa0, int): event times' clock
INPUT_EVENT = struct.Struct("llHHi")    # 24 bytes on aarch64 and x86_64
KEY_RETRY_S = 10                    # look for a missing key device this often
# Gestures, from the key's own event times.
DEBOUNCE_S = 0.03       # a release sooner than this is noise
TAP_MAX_S = 0.6         # a release by this is a tap
HOLD_S = 1.0            # held this long is a hold
STUCK_S = 10            # held this long is a stuck key: forget the press
COALESCE_S = 0.5        # the page follows once no tap has come for this long
PROMPT_S = 10           # the "Shut down?" screen waits this long for a tap
# The key's budget of exempt refreshes: a burst, refilled one at a time.
KEY_BURST = 12
KEY_REFILL_S = 50
HOLD_EMPTY_GAP_S = 60   # an empty bucket still allows a hold this long after a prompt
POWEROFF_NAME = "poweroff"      # the request file in $RUNTIME_DIRECTORY
POWEROFF_GRACE_S = 120          # how long a request waits for the stop
KEYTEST_S = 30                  # how long --keytest listens

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
    strip: tuple[int, int] | None = None    # the tab strip's rows [y0, y1)
    mode: str | None = None                 # the view, for a view request


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
    code: str | None = None     # a 422's X-Display-Error, e.g. "views-off"


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


def request_target(token: str, *, mode: str | None = None, tabs: bool = False,
                   screen: str | None = None) -> str:
    target = PATH_FMT % token + "?" + QUERY
    if mode:
        target += "&mode=" + mode
    if tabs:
        target += "&tabs=1"
    if screen:
        target += "&screen=" + screen
    return target


TAB_STRIP_RE = re.compile(r"([0-9]{1,4})-([0-9]{1,4})")


def parse_tab_strip(value: str) -> tuple[int, int] | None:
    """X-Display-Tab-Strip's half-open rows, or None if it is not two rows of
    this panel at least 2 apart."""
    m = TAB_STRIP_RE.fullmatch(value)
    if m is None:
        return None
    y0, y1 = int(m.group(1)), int(m.group(2))
    if not (0 <= y0 < y1 <= HEIGHT and y1 - y0 >= 2):
        return None
    return y0, y1


def check_headers(status: int, items, *, chunked: bool = False,
                  length: int | None = None, want_mode: str | None = None,
                  want_screen: str | None = None,
                  want_tabs: bool = False) -> str | None:
    """None if a 200's headers describe exactly this panel's frame, else the
    name of the first check that failed.

    `items` is the response's (name, value) pairs, so a header sent twice is
    seen twice: two Content-Lengths are how a body gets smuggled past a check
    of one. Everything is decided before the body is read.

    A view request (`want_mode`) needs X-Display-Mode to name that view, and
    may have an X-Display-Tab-Strip, once and well formed, only if it asked for
    tabs. A screen request needs X-Display-Screen to name it, and no view
    headers. A legacy request (neither) ignores all three.
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
    if want_mode is not None:
        if seen.get("x-display-mode") != [want_mode]:
            return "mode"
        strips = seen.get("x-display-tab-strip", [])
        if want_tabs:
            if len(strips) > 1 or (strips and parse_tab_strip(strips[0]) is None):
                return "tab strip"
        elif strips:
            return "tab strip"
    elif want_screen is not None:
        if seen.get("x-display-screen") != [want_screen]:
            return "screen"
        if "x-display-mode" in seen or "x-display-tab-strip" in seen:
            return "screen"
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
    `painted_*` is the last refresh of any kind (the floor's), `full_*` the
    last full one (the 23-hour repaint's). `view` is the view whose whole
    frame is on the glass, if one is; `fast_count` counts the fast and partial
    refreshes since the last full one; `off` says the off screen is on the
    glass; `quick_disabled` is the batch guard's verdict.
    """
    etag: str | None = None
    glass_sha256: str | None = None
    painted_end_bt: float | None = None
    painted_wall: float | None = None
    attempt_start_bt: float | None = None
    complete: bool = False
    view: str | None = None
    fast_count: int = 0
    off: bool = False
    full_end_bt: float | None = None
    full_wall: float | None = None
    quick_disabled: bool = False


def _time_field(v, limit: float) -> bool:
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)
                         and math.isfinite(v) and 0 <= v <= limit)


def parse_state(raw: bytes) -> State | None:
    """A State from the file's bytes, or None if anything about it is off.

    A version 1 file (no view, no refresh kinds) is migrated: no view, a full
    refresh due next (fast_count = FULL_EVERY), and its last refresh taken as
    the last full one, since version 1 only ever refreshed in full.
    """
    if len(raw) > STATE_MAX_BYTES:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    if isinstance(version, bool) or version not in (1, STATE_VERSION):
        return None
    s = State(
        etag=data.get("etag"),
        glass_sha256=data.get("glass_sha256"),
        painted_end_bt=data.get("painted_end_bt"),
        painted_wall=data.get("painted_wall"),
        attempt_start_bt=data.get("attempt_start_bt"),
        complete=data.get("complete"),
    )
    if version == STATE_VERSION:
        s = dataclasses.replace(
            s, view=data.get("view"), fast_count=data.get("fast_count"),
            off=data.get("off"), full_end_bt=data.get("full_end_bt"),
            full_wall=data.get("full_wall"),
            quick_disabled=data.get("quick_disabled"))
        if s.view is not None and s.view not in VIEWS:
            return None
        if not (isinstance(s.fast_count, int) and not isinstance(s.fast_count, bool)
                and 0 <= s.fast_count <= 1000):
            return None
        if not (isinstance(s.off, bool) and isinstance(s.quick_disabled, bool)):
            return None
        if not (_time_field(s.full_end_bt, 1e10) and _time_field(s.full_wall, 1e11)):
            return None
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
    if version == 1:
        done = s.complete
        s = dataclasses.replace(
            s, view=None, fast_count=FULL_EVERY, off=False,
            full_end_bt=s.painted_end_bt if done else None,
            full_wall=s.painted_wall if done else None, quick_disabled=False)
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
    """True once 23 hours have passed since the last FULL refresh.

    Fast and partial refreshes do not count: only a full one clears the glass
    of ghosting. Each test is a lower bound on the real time since that
    refresh, as in floor_ok_at(): a time later than `now_bt` is from an earlier
    boot, so at least `now_bt` has passed since it.
    """
    if not s.complete or s.full_end_bt is None:
        return False
    if s.full_end_bt <= now_bt and now_bt - s.full_end_bt >= FORCE_REPAINT_S:
        return True
    if s.full_end_bt > now_bt and now_bt >= FORCE_REPAINT_S:
        return True
    return (synced and s.full_wall is not None
            and now_wall - s.full_wall >= FORCE_REPAINT_S)


def force_poll_at(s: State, now_bt: float, now_wall: float,
                  synced: bool) -> float | None:
    """The CLOCK_BOOTTIME by which to fetch so the 23-hour repaint is on time.

    The 23 hours are measured from the last FULL refresh (full_end_bt and
    full_wall). None when no full refresh is recorded, or when the repaint is
    already due by any of forced_due()'s bounds: then the next fetch is forced
    whenever it comes, and pulling it earlier would only defeat the retry
    backoff. The boot-time bound alone is late after a reboot (it cannot see
    the time the box was down), so the wall clock bounds it too once it is
    synced, if the refresh recorded a wall time (the clock was synced when it
    ended). run() records a time later than its own start, which must be from
    an earlier boot, as boot time 0, so without a wall clock that one is due by
    23 h of this boot's uptime. An earlier boot's refresh at or before run()'s
    start cannot be told from this boot's, and is due 23 h after it.
    """
    if not s.complete or s.full_end_bt is None:
        return None
    if forced_due(s, now_bt, now_wall, synced):
        return None
    at = []
    if s.full_end_bt <= now_bt:
        if s.full_end_bt + FORCE_REPAINT_S > now_bt:
            at.append(s.full_end_bt + FORCE_REPAINT_S)
    elif FORCE_REPAINT_S > now_bt:
        at.append(float(FORCE_REPAINT_S))
    if synced and s.full_wall is not None:
        left = s.full_wall + FORCE_REPAINT_S - now_wall
        if left > 0:
            at.append(now_bt + left)
    return min(at) if at else None


def parse_bitmap(text: str) -> int:
    """A sysfs capability bitmap ("10000000000000 0") as one int, bit n for bit n.

    The kernel prints it as hex words of the C long's width, most significant
    first, separated by spaces, without zero padding.
    """
    width = struct.calcsize("L") * 8
    value = 0
    for word in text.split():
        value = (value << width) | int(word, 16)
    return value


# ── what Events.wait() returns ───────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class Stop:
    sig: int


@dataclasses.dataclass(frozen=True)
class Repaint:
    pass


@dataclasses.dataclass(frozen=True)
class Key:
    value: int      # 1 pressed, 0 released
    t: float        # the kernel's time of the edge, on CLOCK_BOOTTIME


@dataclasses.dataclass(frozen=True)
class KeyReset:
    t: float        # events were lost, or the device went away or came back


Item = Stop | Repaint | Key | KeyReset


def decode_events(data: bytes) -> list[Item]:
    """The power key's edges and SYN_DROPPED from whole input_event records.

    Autorepeat (value 2) and every other event is dropped, and so is a
    trailing part of a record.
    """
    out: list[Item] = []
    for off in range(0, len(data) - INPUT_EVENT.size + 1, INPUT_EVENT.size):
        sec, usec, etype, code, value = INPUT_EVENT.unpack_from(data, off)
        t = sec + usec / 1e6
        if etype == EV_KEY and code == KEY_POWER and value in (0, 1):
            out.append(Key(value, t))
        elif etype == EV_SYN and code == SYN_DROPPED:
            out.append(KeyReset(t))
    return out


# ── the key's gestures and what they do ──────────────────────────────────────

class Gestures:
    """Taps and holds from the key's edges. Pure: every time is a parameter.

    A release decides a tap (DEBOUNCE_S to TAP_MAX_S) or a hold (HOLD_S or
    longer, if poll() has not already seen it); poll() sees a hold while the
    key is still down, and forgets a press held STUCK_S. Each gesture comes
    back as (kind, press_t).
    """

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.down = False
        self.press_t: float | None = None
        self.hold_emitted = False

    @property
    def pressed(self) -> bool:
        """Down, and no hold seen yet: no fetch and no paint starts meanwhile."""
        return self.down and not self.hold_emitted

    def press(self, t: float) -> list:
        if not self.down:
            self.down, self.press_t, self.hold_emitted = True, t, False
        return []

    def release(self, t: float) -> list:
        if not self.down:
            return []
        dt, press_t, held = t - self.press_t, self.press_t, self.hold_emitted
        self.down = False
        if dt < DEBOUNCE_S:
            return []
        if dt <= TAP_MAX_S:
            return [("tap", press_t)]
        if dt >= HOLD_S and not held:
            return [("hold", press_t)]
        return []

    def poll(self, now: float) -> list:
        out = []
        if self.down and not self.hold_emitted and now - self.press_t >= HOLD_S:
            self.hold_emitted = True
            out.append(("hold", self.press_t))
        if self.down and now - self.press_t >= STUCK_S:
            log.warning("key: down for %d s; taking it as stuck", STUCK_S)
            self.reset()
        return out

    def next_deadline(self) -> float | None:
        if not self.down:
            return None
        return self.press_t + (STUCK_S if self.hold_emitted else HOLD_S)


@dataclasses.dataclass(frozen=True)
class Strip:
    view: str


@dataclasses.dataclass(frozen=True)
class Page:
    view: str


@dataclasses.dataclass(frozen=True)
class Prompt:
    pass


@dataclasses.dataclass(frozen=True)
class Off:
    pass


@dataclasses.dataclass(frozen=True)
class Leave:
    why: str        # "timeout", "resume" or "failed"


@dataclasses.dataclass(frozen=True)
class Idle:
    pass


class Ui:
    """The view the key has chosen, and the shutdown prompt. Pure: it knows
    nothing of tokens or the network, and every time is a parameter.

    `mode` is browse, prompt_pending (the prompt is being drawn), prompt (it is
    drawn and armed) or off. Every method returns one-shot actions, never
    re-emitted. `page_needed` says a tap moved the tab since the last
    whole-view paint; `page_due` is when that page is to be fetched.
    """

    def __init__(self, view: str, start: float, idle_s: float):
        self.view = view
        self.mode = "browse"
        self.page_due: float | None = None
        self.page_needed = False
        self.prompt_shown_bt: float | None = None
        self.prompt_deadline: float | None = None
        self.last_key = start
        self.idle_s = idle_s
        # The earliest the idle return can happen: the floor, and the clock
        # gate while it is closed. Kept from the last tick() for next_deadline().
        self._idle_not_before: float | None = None

    def _leave_prompt(self) -> None:
        self.prompt_shown_bt = self.prompt_deadline = None

    def tap(self, press_t: float, now: float) -> list:
        if self.mode == "browse":
            self.view = VIEWS[(VIEWS.index(self.view) + 1) % len(VIEWS)]
            self.page_needed = True
            self.page_due = now + COALESCE_S
            self.last_key = now
            return [Strip(self.view)]
        if self.mode == "prompt":
            # The press decides, however late the release came.
            if self.prompt_shown_bt <= press_t <= self.prompt_deadline:
                self.mode = "off"
                self._leave_prompt()
                return [Off()]
        return []

    def hold(self, press_t: float, now: float) -> list:
        if self.mode == "browse":
            self.mode = "prompt_pending"
            self.page_due = None
            self.last_key = now
            return [Prompt()]
        return []

    def shown_prompt(self, end_bt: float) -> list:
        if self.mode == "prompt_pending":
            self.mode = "prompt"
            self.prompt_shown_bt = end_bt
            self.prompt_deadline = end_bt + PROMPT_S
            self.last_key = end_bt
        return []

    def prompt_failed(self, now: float) -> list:
        if self.mode == "prompt_pending":
            self.mode = "browse"
            if self.page_needed:
                self.page_due = now
        return []

    def tick(self, now: float, *, gate_open: bool, floor_at: float) -> list:
        self._idle_not_before = max(floor_at,
                                    0.0 if gate_open else float(CLOCK_SYNC_GRACE_S))
        if self.mode == "prompt" and now >= self.prompt_deadline:
            self.mode = "browse"
            self._leave_prompt()
            self.last_key = now
            return [Leave("timeout")]
        if self.mode != "browse":
            return []
        if self.page_due is not None and now >= self.page_due:
            self.page_due = None
            return [Page(self.view)]
        if (self.idle_s > 0 and self.view != TODAY and self.page_due is None
                and now - self.last_key >= self.idle_s and gate_open
                and now >= floor_at):
            self.view = TODAY
            self.last_key = now
            return [Idle()]
        return []

    def painted_view(self, v: str) -> list:
        if v == self.view:
            self.page_needed = False
        return []

    def leave_done(self, now: float) -> list:
        """After a Leave's repaint: a page a tap still owes is fetched now."""
        if self.mode == "browse" and self.page_needed:
            self.page_due = now
        return []

    def resume(self, now: float, *, why: str = "resume") -> list:
        if self.mode == "off":
            self.mode = "browse"
            self.last_key = now
            return [Leave(why)]
        return []

    def _idle_deadline(self) -> float | None:
        if not (self.idle_s > 0 and self.view != TODAY and self.mode == "browse"
                and self.page_due is None):
            return None
        at = self.last_key + self.idle_s
        if self._idle_not_before is not None:
            at = max(at, self._idle_not_before)
        return at

    def next_deadline(self, pressed: bool) -> float | None:
        """When tick() next has something to do; None while the key is down."""
        if pressed:
            return None
        times = [t for t in (self.page_due,
                             self.prompt_deadline if self.mode == "prompt" else None,
                             self._idle_deadline()) if t is not None]
        return min(times) if times else None


class Bucket:
    """The key's budget of floor-exempt refreshes: KEY_BURST tokens, one more
    each KEY_REFILL_S, never above KEY_BURST. Pure: every time is a parameter."""

    def __init__(self, tokens: int, now: float):
        self.tokens = min(KEY_BURST, tokens)
        self.last = now

    def refill(self, now: float) -> None:
        if self.tokens >= KEY_BURST:
            self.last = now     # a full bucket banks no time
            return
        n = int((now - self.last) // KEY_REFILL_S)
        if n <= 0:
            return
        self.tokens = min(KEY_BURST, self.tokens + n)
        self.last = now if self.tokens >= KEY_BURST else self.last + n * KEY_REFILL_S

    def take(self, n: int = 1) -> bool:
        if self.tokens < n:
            return False
        self.tokens -= n
        return True

    def give(self, n: int = 1) -> None:
        self.tokens = min(KEY_BURST, self.tokens + n)

    def next_at(self, n: int) -> float:
        """The CLOCK_BOOTTIME at which the bucket holds n tokens (n <= KEY_BURST)."""
        if n > KEY_BURST:
            raise ValueError(f"the bucket never holds {n} tokens")
        if self.tokens >= n:
            return self.last
        return self.last + (n - self.tokens) * KEY_REFILL_S


def start_tokens(s: State, start: float) -> int:
    """The bucket at process start, from the state as loaded: full after a
    reboot or with no record, else what a bucket emptied at the last refresh
    would have refilled to, so a crash loop starts nearly empty.

    "The last refresh" is the same lower bound floor_ok_at() uses: a
    completed paint's end, or for an attempt that never recorded its end
    (a crash mid-refresh, the very case this guards) the latest it can have
    ended. A time later than `start` is from an earlier boot.
    """
    if s.complete and s.painted_end_bt is not None:
        ended = s.painted_end_bt
    elif s.attempt_start_bt is not None:
        if s.attempt_start_bt > start:
            return KEY_BURST
        ended = min(s.attempt_start_bt + PAINT_MAX_S, start)
    else:
        return KEY_BURST
    if ended > start:
        return KEY_BURST
    return min(KEY_BURST, int((start - ended) // KEY_REFILL_S))


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


def fetch(token: str, etag: str | None, *, mode: str | None = None,
          tabs: bool = False, screen: str | None = None, host: str = HOST,
          port: int = PORT, timeout: float = SOCKET_TIMEOUT_S,
          deadline_s: float = FETCH_DEADLINE_S, clock=time.monotonic,
          tick=lambda: None):
    """One GET of this panel's frame. Never raises; returns a result class.

    With `mode` it is that view (with the tab strip if `tabs`); with `screen`
    it is that static screen; with neither it is the display's stored view, as
    a legacy client asks. check_headers() holds each to its own headers.

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
        conn.request("GET", request_target(token, mode=mode, tabs=tabs,
                                            screen=screen), headers=headers)
        resp = conn.getresponse()
        items = resp.getheaders()
        status = resp.status
        if status == 200:
            bad = check_headers(status, items, chunked=bool(resp.chunked),
                                length=resp.length, want_mode=mode,
                                want_screen=screen, want_tabs=tabs)
            if bad:
                return Refused(bad, status)
            body = _read_body(resp, start + deadline_s, clock, tick)
            if body is None:
                return Transient(f"body took longer than {deadline_s:g} s")
            if len(body) != BUF_BYTES:
                return Transient(f"body ended at {len(body)} of {BUF_BYTES} bytes")
            strip = None
            if mode is not None and tabs:
                value = _single(items, "x-display-tab-strip")
                strip = None if value is None else parse_tab_strip(value)
            return Frame(body, _single(items, "etag"),
                         clamp_refresh(_single(items, "x-display-refresh-seconds")),
                         strip=strip,
                         mode=_single(items, "x-display-mode") if mode is not None
                         else None)
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
        if status == 422:
            return Refused(f"HTTP {status}", status,
                           code=_single(items, "x-display-error"))
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


def boottime() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def clock_synced() -> bool:
    return os.path.exists(CLOCK_SYNC_FILE)


def _hm(wall: float) -> str:
    return time.strftime("%H:%M", time.localtime(wall))


class Collector:
    """The one place signals are taken: a thread that sigwait()s for them and
    hands them over through a deque, with a byte down a pipe so the loop can
    select() on signals and the key together.

    main() must block the signals first, in every thread, which is what makes
    sigwait() the only taker; the thread checks, and exits the process if not.
    """

    def __init__(self, sigset):
        self._r, self._w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self._items: collections.deque[int] = collections.deque()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, args=(sigset,),
                                        name="smylte-panel-signals", daemon=True)
        self._thread.start()

    def _run(self, sigset) -> None:
        if not set(sigset) <= set(signal.pthread_sigmask(signal.SIG_BLOCK, [])):
            # A signal that is not blocked would be delivered, not collected:
            # SIGTERM's default action would kill a refresh halfway.
            os._exit(EX_FAIL)
        while True:
            sig = signal.sigwait(sigset)
            with self._lock:
                self._items.append(int(sig))
            try:
                os.write(self._w, b"\0")
            except BlockingIOError:
                pass        # the pipe is full, so the loop is woken anyway

    @property
    def fd(self) -> int:
        return self._r

    def pop(self) -> list[int]:
        """Every signal collected so far, in order."""
        # The pipe is emptied BEFORE the deque is taken: a signal that lands
        # in between then leaves its byte in the pipe, and the next select()
        # wakes for it. The other way round could eat its byte and leave it
        # in the deque with nothing to wake the loop.
        while True:
            try:
                if not os.read(self._r, 4096):
                    break
            except BlockingIOError:
                break
        with self._lock:
            items = list(self._items)
            self._items.clear()
        return items

    def alive(self) -> bool:
        return self._thread.is_alive()


def start_collector(sigset) -> Collector:
    return Collector(sigset)


_many_keys_logged = False


def find_key_device(root: pathlib.Path) -> str | None:
    """/dev/input/eventN of the one input device that is the power key, or None.

    It is the one named KEY_DEVICE_NAME with EV_KEY events and KEY_POWER among
    its keys. None if there is none or more than one; a candidate that cannot
    be read is skipped.
    """
    global _many_keys_logged
    found = []
    for node in sorted(root.glob("event*")):
        dev = node / "device"
        try:
            name = (dev / "name").read_text(encoding="utf-8", errors="replace")
            if name.strip() != KEY_DEVICE_NAME:
                continue
            caps = dev / "capabilities"
            ev = parse_bitmap((caps / "ev").read_text(encoding="ascii"))
            keys = parse_bitmap((caps / "key").read_text(encoding="ascii"))
        except (OSError, ValueError):
            continue
        if ev >> EV_KEY & 1 and keys >> KEY_POWER & 1:
            found.append(node.name)
    if len(found) == 1:
        return "/dev/input/" + found[0]
    if len(found) > 1 and not _many_keys_logged:
        log.error("key: %d input devices are %r (%s); using none of them",
                  len(found), KEY_DEVICE_NAME, ", ".join(found))
        _many_keys_logged = True
    return None


def open_key(path: str) -> int:
    """The key's event node, non-blocking, with event times on CLOCK_BOOTTIME."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        fcntl.ioctl(fd, EVIOCSCLOCKID, struct.pack("i", time.CLOCK_BOOTTIME))
    except OSError:
        os.close(fd)
        raise
    return fd


class Events:
    """Everything the loop waits for: the collector's signals and the key.

    It finds and opens the key itself, again every KEY_RETRY_S while there is
    none, and never with key_enabled False.
    """

    def __init__(self, collector, *, sysfs_root, open_key, boottime, key_enabled):
        self.collector = collector
        self._sysfs_root = sysfs_root
        self._open_key = open_key
        self._boottime = boottime
        self.key_enabled = key_enabled
        self._fd: int | None = None
        self._retry_at = boottime()
        self._open_failed_logged = False

    @property
    def key_open(self) -> bool:
        return self._fd is not None

    def next_retry(self) -> float | None:
        return self._retry_at if self.key_enabled and self._fd is None else None

    def alive(self) -> bool:
        """Whether signals are still being collected."""
        return self.collector.alive()

    def _discover(self) -> None:
        now = self._boottime()
        if not (self.key_enabled and self._fd is None and now >= self._retry_at):
            return
        path = find_key_device(self._sysfs_root)
        if path is not None:
            try:
                self._fd = self._open_key(path)
            except OSError as e:
                if not self._open_failed_logged:
                    log.error("key: cannot open %s: %s", path, e)
                    self._open_failed_logged = True
            else:
                log.info("key: %s", path)
        if self._fd is None:
            self._retry_at = now + KEY_RETRY_S

    def wait(self, timeout: float) -> list[Item]:
        """Up to `timeout` s for anything; then everything pending, signals
        first. 0 polls."""
        self._discover()
        fds = [self.collector.fd] + ([self._fd] if self._fd is not None else [])
        select.select(fds, [], [], max(0.0, timeout))
        out: list[Item] = [Repaint() if s == REPAINT_SIGNAL else Stop(s)
                           for s in self.collector.pop()]
        if self._fd is not None:
            data = b""
            try:
                while True:
                    chunk = os.read(self._fd, INPUT_EVENT.size * 64)
                    if not chunk:
                        break
                    data += chunk
            except BlockingIOError:
                pass
            except OSError as e:
                if e.errno not in (errno.ENODEV, errno.EIO):
                    raise
                log.warning("key: the device went away (%s)", e.strerror)
                os.close(self._fd)
                self._fd = None
                now = self._boottime()
                self._retry_at = now
                out.extend(decode_events(data))
                out.append(KeyReset(now))
                return out
            out.extend(decode_events(data))
        return out


def request_poweroff(run_dir: str | None, start_bt: float) -> str:
    """Ask the power-off units to shut the box down: "ok", or why not."""
    if run_dir is None or not (os.path.isdir(run_dir) and os.access(run_dir, os.W_OK)):
        return "failed: no run directory"
    path = os.path.join(run_dir, POWEROFF_NAME)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC, 0o600)
        try:
            os.write(fd, f"{start_bt:.3f}\n".encode("ascii"))
        finally:
            os.close(fd)
    except FileExistsError:
        return "ok"
    except OSError as e:
        return "failed: " + errno.errorcode.get(e.errno, str(e.errno))
    return "ok"


def clear_poweroff(run_dir: str | None) -> None:
    if run_dir is None:
        return
    path = os.path.join(run_dir, POWEROFF_NAME)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.error("cannot remove %s: %s", path, e)


def load_screen(state_dir: pathlib.Path, kind: str) -> bytes | None:
    """A cached screen: its frame, if the file is the frame, a newline, the
    frame's sha256 in hex and a newline. Anything else is no screen."""
    size = BUF_BYTES + 1 + 64 + 1
    path = state_dir / f"{kind}.bin"
    try:
        with open(path, "rb") as f:
            raw = f.read(size + 1)
    except FileNotFoundError:
        return None
    except OSError as e:
        log.warning("cannot read %s (%s); fetching it again", path, e.strerror)
        return None
    if len(raw) != size or raw[BUF_BYTES:BUF_BYTES + 1] != b"\n" or raw[-1:] != b"\n":
        return None
    frame, digest = raw[:BUF_BYTES], raw[BUF_BYTES + 1:-1]
    if not SHA256_RE.fullmatch(digest.decode("ascii", errors="replace")):
        return None
    if digest.decode("ascii") != hashlib.sha256(frame).hexdigest():
        return None
    return frame


def save_screen(state_dir: pathlib.Path, kind: str, frame: bytes) -> bool:
    """Write atomically and durably: temp file, fsync, rename, fsync the dir."""
    path = state_dir / f"{kind}.bin"
    tmp = state_dir / f"{kind}.bin.tmp"
    data = frame + b"\n" + hashlib.sha256(frame).hexdigest().encode("ascii") + b"\n"
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


def logind_dropin_present(path: str = LOGIND_DROPIN) -> bool:
    """Whether logind has been told to leave the power key to this service."""
    return os.path.exists(path)


@dataclasses.dataclass
class Deps:
    """Everything run() touches, so CI can run the real loop on fakes."""
    state_dir: pathlib.Path
    panel: object
    epd: object                 # the driver module, for its exception classes
    fetch: object               # (etag | None, *, mode=, tabs=, screen=) -> result
    # .wait(timeout) -> [Item], .next_retry(), .key_open and .alive(): Events
    events: object = None
    boottime: object = boottime
    walltime: object = time.time
    synced: object = clock_synced
    notify: object = sd_notify
    request_poweroff: object = lambda: "failed: no run directory"   # () -> "ok" | why not
    clear_poweroff: object = lambda: None
    refresh: str = "fast"       # SMYLTE_PANEL_REFRESH
    idle_s: int = 0             # SMYLTE_PANEL_IDLE_RETURN_S
    key: str = "auto"           # SMYLTE_PANEL_KEY
    holds_ok: bool = True       # False when $RUNTIME_DIRECTORY is unusable
    logind_present: bool | None = None  # the logind drop-in; None is unknown


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


def _paint(d: Deps, prev: State, frame: bytes, *, etag: str | None,
           view: str | None, kind: str, off: bool = False,
           old: bytes | None = None) -> tuple[State | None, float]:
    """Write-ahead, then init/display/sleep. Returns (new state, end time).

    `kind` is "full", "fast" or "partial"; a partial needs `old`, the bytes on
    the glass. Every field of `prev` that outlives one refresh is carried
    forward: the last refresh and the last full one, and the batch guard's
    verdict. fast_count is counted in the write-ahead record, as if the
    refresh will complete, so a crash cannot hide one.

    (None, 0) means the write-ahead record could not be saved and nothing was
    sent to the panel. A panel failure raises after abort() has powered the
    panel down.
    """
    if kind == "partial" and old is None:
        raise ValueError("a partial refresh needs the bytes on the glass")
    start = d.boottime()
    attempt = dataclasses.replace(
        prev, attempt_start_bt=start, complete=False, etag=None, view=None,
        glass_sha256=None, off=False,
        fast_count=0 if kind == "full" else min(prev.fast_count + 1, 1000))
    if not save_state(d.state_dir, attempt):
        return None, 0.0
    try:
        d.panel.init(kind)
        if kind == "partial":
            d.panel.display_partial(old, frame)
        else:
            d.panel.display(frame)
        d.panel.sleep()
    except BaseException as e:
        d.panel.abort(busy_stuck=isinstance(e, d.epd.BusyTimeout))
        raise
    end = d.boottime()
    synced = d.synced()
    wall = d.walltime() if synced else None
    done = dataclasses.replace(
        attempt, complete=True, painted_end_bt=end, painted_wall=wall,
        etag=etag, view=view, glass_sha256=hashlib.sha256(frame).hexdigest(),
        off=off)
    if kind == "full":
        done = dataclasses.replace(done, full_end_bt=end, full_wall=wall)
    if not save_state(d.state_dir, done):
        log.error("refreshed, but could not record it — a restart will wait "
                  "the full floor before the next refresh")
    log.info("painted %s (%s) in %.1f s", etag[1:9] if etag else "white", kind,
             end - start)
    return done, end


class _PanelFailed(Exception):
    """A refresh failed and abort() has powered the panel down; logged."""


# What a view fetch's refusal says about this server and this display.
VIEWS_OFF_TOO_OLD = "smylted is too old for the desk key — update it"
VIEWS_OFF_SETTING = "turn on Desk key for this display in Settings → Displays"

_STOP, _FAIL, _REQUEUED = "stop", "fail", "requeued"


def _views_off_reason(result) -> str | None:
    """Why the server will not switch views, if `result` says it will not."""
    if isinstance(result, Refused):
        if result.code == "views-off":
            return VIEWS_OFF_SETTING
        if result.reason == "mode":
            return VIEWS_OFF_TOO_OLD
    return None


class _Runner:
    """run()'s state and its loop (design §4.8).

    Each iteration: take in what has happened (signals, the key's edges), let
    Gestures and Ui turn it into actions, run the actions (strips, pages, the
    prompt, the off screen, the way back), then the routine fetch and paint,
    then at most one background fetch, then wait. The routine branch keeps the
    service's old logic: the floor, the 23-hour repaint and the backoffs. Key
    refreshes are exempt from the floor and paid for from the key's budget.
    """

    def __init__(self, d: Deps):
        self.d = d
        loaded = load_state(d.state_dir)
        start = self.start = d.boottime()
        # From the state AS LOADED, before the rewrite below: a wake is a
        # start whose glass shows the off screen from an earlier boot.
        self.wake = bool(loaded.complete and loaded.off
                         and loaded.painted_end_bt is not None
                         and loaded.painted_end_bt > start)
        tokens = start_tokens(loaded, start)
        # A paint time later than this process's start is from an earlier boot, so
        # at least this boot's uptime has passed since it. Record it as boot time
        # 0, which stays a true lower bound as uptime grows and across a restart
        # later in this boot. (Compared each time instead, the paint would pass for
        # this boot's once uptime overtook it.) Only a paint time later than this
        # start can be told from this boot's: without a synced clock, one at or
        # before it is due 23 h after it. The last refresh and the last full one
        # are each rewritten on their own.
        state = rewritten = loaded
        if state.complete and state.painted_end_bt is not None \
                and state.painted_end_bt > start:
            rewritten = dataclasses.replace(rewritten, painted_end_bt=0.0)
        if state.full_end_bt is not None and state.full_end_bt > start:
            rewritten = dataclasses.replace(rewritten, full_end_bt=0.0)
        if rewritten is not state:
            state = rewritten
            self.unsaved = not save_state(d.state_dir, state)
        else:
            self.unsaved = False    # retried after each fetch until it is on disk
        self.state = state
        self.floor_at = floor_ok_at(state, start)
        self.screens: dict[str, bytes] = {}
        for kind in SCREENS:
            frame = load_screen(d.state_dir, kind)
            if frame is not None:
                self.screens[kind] = frame
        self.screen_fetched_at = {kind: start for kind in self.screens}
        d.clear_poweroff()      # a request left by an earlier process
        # The first VIEW paint of this process skips the floor once after a
        # wake, or when the glass shows a screen (the prompt or the off screen)
        # that a stop or a crash left there. Prompts and leaves do not use it.
        on_screen = bool(state.complete and state.glass_sha256 is not None
                         and any(hashlib.sha256(f).hexdigest() == state.glass_sha256
                                 for f in self.screens.values()))
        self.exempt_first_view = self.wake or on_screen
        self.next_poll = start
        self.bucket = Bucket(tokens, start)
        self.ui = Ui(state.view if state.view in VIEWS and not self.wake else TODAY,
                     start, d.idle_s)
        self.gestures = Gestures()
        self.actions: collections.deque = collections.deque()
        self.problems = _Problems(d.notify)
        # The glass as this process last drew it, and its tab strip's rows.
        self.glass: bytes | None = None
        self.glass_strip: tuple[int, int] | None = None
        # The glass and its record from before the prompt: (bytes, view, etag,
        # strip rows), repainted on the way back.
        self.pre_prompt: tuple | None = None
        self.strip_cache: dict[str, tuple[tuple[int, int], bytes]] = {}
        self.views = d.key == "auto"
        self.views_reason: str | None = None    # why not, for the STATUS line
        self.views_off_at: float | None = None
        self.last_fetch_ok = False      # the last view fetch was a Frame or a 304
        self.first_fetch_ok = False
        self.painted_any = False        # any refresh by this process
        self.view_painted = False       # a whole view frame painted by this process
        # A view fetch of this process found the glass already showing it (a 304,
        # or the same picture). With view_painted, it is what lets taps in: the
        # rule exists so no tap paints before the clock gate has opened, and a
        # routine view fetch has passed the gate as surely as a paint has. Without
        # it, a restart onto an unchanged page left the key dead until the page
        # next changed, which could be hours.
        self.view_seen = False
        # Notices that must outlast the next healthy answer: the STATUS line
        # carries them after "showing …", like the desk-key-off reason.
        self.notes: list[str] = []
        self.healthy = False    # the last routine fetch was a 304, a dedupe or a paint
        self.cap_synced = False # whether the 23-hour cap last saw a synced clock
        self.force_next = False # a healthy answer left the 23-hour repaint due
        self.gate_logged = False
        self.fetched = False            # this iteration fetched
        self.last_fetch_t = -math.inf
        self.last_ping = start
        self.bg_retry: dict[tuple[str, str], float] = {}
        self.resting = False
        self.last_prompt_end: float | None = None
        self.grace_end: float | None = None
        self.off_paint_failed = False
        self.stop_pending = False       # a stop came while an Off was queued
        if self.floor_at > start and not self.exempt_first_view:
            log.info("first refresh allowed in %d s (the 180 s floor is kept across "
                     "restarts)", math.ceil(self.floor_at - start))
        if self.wake:
            log.info("woken from the off screen: Today is drawn as soon as the "
                     "server answers")
        if d.key == "auto" and not d.holds_ok:
            self.notes.append("holding the key does nothing: "
                              "$RUNTIME_DIRECTORY is not a writable directory")
        if d.key == "auto" and d.logind_present is False:
            self.notes.append("logind still powers off on a press — re-run panel-setup.sh")
        elif d.key == "off" and d.logind_present:
            self.notes.append("the key does nothing — re-run panel-setup.sh")
        for note in self.notes:
            log.warning("%s", note)
        if self.notes:
            d.notify("STATUS=" + " · ".join(self.notes))

    # ── helpers ─────────────────────────────────────────────────────────────

    def _gate_open(self, now: float) -> bool:
        return now >= CLOCK_SYNC_GRACE_S or self.d.synced()

    def _due(self) -> float:
        if self.exempt_first_view:
            return self.next_poll
        return max(self.next_poll, self.floor_at)

    def _routine_eligible(self) -> bool:
        return (self.ui.mode == "browse" and not self.actions
                and self.ui.page_due is None and not self.gestures.pressed)

    def _tokens(self, now: float) -> int:
        self.bucket.refill(now)
        return self.bucket.tokens

    def _take(self, now: float) -> None:
        self.bucket.refill(now)
        self.bucket.take()

    def _healthy_line(self) -> str:
        line = _showing(self.state)
        if not self.views and self.views_reason:
            line += f" · desk key off: {self.views_reason}"
        if self.state.quick_disabled:
            line += " · fast refresh is off (see firmware/README.md)"
        for note in self.notes:
            line += f" · {note}"
        return line

    @property
    def view_ready(self) -> bool:
        """Taps may change the view: a view frame is known to be on the glass."""
        return self.view_painted or self.view_seen

    def _fetch(self, etag: str | None, **kw):
        result = self.d.fetch(etag, **kw)
        self.fetched = True
        now = self.d.boottime()
        self.last_fetch_t = now
        if now - self.last_ping >= 1.0:
            self.d.notify("WATCHDOG=1")
            self.last_ping = now
        return result

    def _kind(self, purpose: str) -> str:
        """full or fast, in §4.5's order of precedence."""
        if self.d.refresh == "full" or self.state.quick_disabled:
            return "full"
        if purpose == "prompt":
            return "fast"
        if purpose in ("off", "forced") or not self.painted_any:
            return "full"
        return "full" if self.state.fast_count >= FULL_EVERY else "fast"

    def _strip_ok(self, view: str) -> bool:
        cached = self.strip_cache.get(view)
        return (self.d.refresh == "fast" and not self.state.quick_disabled
                and self.state.fast_count + 1 < FULL_EVERY
                and self.glass is not None and self.last_fetch_ok and self.views
                and cached is not None and self.glass_strip is not None
                and cached[0] == self.glass_strip)

    def _cache_strip(self, view: str, frame: Frame) -> None:
        if frame.strip is None:
            return
        y0, y1 = frame.strip
        rows = frame.body[y0 * STRIDE:y1 * STRIDE]
        cached = self.strip_cache.get(view)
        if cached is not None and cached[1] != rows:
            self.strip_cache = {}       # the strip changed (language?): all of it
        self.strip_cache[view] = (frame.strip, rows)

    def _view_result(self, result, view: str) -> bool:
        """Book a view fetch's result. True if it turned the views off."""
        if isinstance(result, (Frame, NotModified)):
            self.last_fetch_ok = True
            self.first_fetch_ok = True
            if not self.views:
                log.info("the server switches views again: the desk key is on")
                self.views = True
                self.views_reason = None
            if isinstance(result, Frame):
                self._cache_strip(view, result)
            return False
        self.last_fetch_ok = False
        reason = _views_off_reason(result)
        if reason is None:
            return False
        if self.views:
            log.warning("desk key off: %s", reason)
            self.views_off_at = self.d.boottime()
        self.views = False
        self.views_reason = reason
        return True

    def _failure(self, result, now: float, flipped: bool) -> float:
        """Say what went wrong with a fetch; the routine backoff it earns."""
        if flipped:
            return 0.0      # not a problem: the legacy fetch follows at once
        if isinstance(result, Gone):
            self.problems.set("gone", "the server does not know this display (404): "
                                      "token rotated, or display disabled or deleted "
                                      "— `sudo deploy/panel-setup.sh --rotate-token` "
                                      "after a rotation")
            return GONE_RETRY_S
        if isinstance(result, Throttled):
            self.problems.set("throttled", f"throttled by the server (429); next "
                                           f"try in {result.retry_s} s")
            return result.retry_s
        if isinstance(result, Refused):
            self.problems.set(f"refused:{result.reason}",
                              f"refused the server's response ({result.reason}) — "
                              "server and client disagree about the frame")
            return GONE_RETRY_S
        reason = getattr(result, "reason", repr(result))
        if self.wake and not self.view_painted and now - self.start >= STARTUP_WINDOW_S:
            self.problems.set("waking", "waking: the server is not answering")
        else:
            self.problems.set("transient", f"server not answering ({reason})")
        if not self.painted_any and now - self.start < STARTUP_WINDOW_S:
            return STARTUP_RETRY_S
        return ERROR_RETRY_S

    def _draw(self, frame: bytes, *, purpose: str, kind: str, etag: str | None,
              view: str | None, off: bool = False, old: bytes | None = None,
              strip: tuple[int, int] | None = None) -> float | None:
        """One refresh: its end time, or None if the write-ahead record could
        not be saved and nothing was sent to the panel. A panel failure is
        logged and raised as _PanelFailed."""
        try:
            done, end = _paint(self.d, self.state, frame, etag=etag, view=view,
                               kind=kind, off=off, old=old)
        except Exception as e:
            phase = _failed_in(self.d.panel)
            if isinstance(e, self.d.epd.PanelError):
                log.error("refresh failed during %s: %s", phase, e)
            else:
                log.critical("refresh failed during %s", phase, exc_info=True)
            raise _PanelFailed(purpose) from e
        if done is None:
            self.problems.set("state", "could not record the refresh before "
                                       "starting it, so it was not started "
                                       "(the floor would not survive a "
                                       f"crash); retrying every {ERROR_RETRY_S} s")
            return None
        self.state = done
        self.floor_at = end + MIN_REFRESH_S
        self.glass, self.glass_strip = frame, strip
        self.painted_any = True
        last = getattr(self.d.panel, "last_refresh_s", None)
        if isinstance(last, (int, float)) and not isinstance(last, bool) and (
                (kind == "partial" and last > QUICK_PARTIAL_MAX_S)
                or (kind == "fast" and last > QUICK_FAST_MAX_S)):
            # The batch guard: a panel this slow at quick refreshes is an old
            # batch, and quick refreshes would harm it.
            self.state = dataclasses.replace(self.state, quick_disabled=True)
            save_state(self.d.state_dir, self.state)
            self.problems.set("quick", "fast refresh is off: this panel looks like a "
                                       "pre-2023 batch; see firmware/README.md")
        return end

    def _viewed(self) -> None:
        """A whole view frame is on the glass, painted by this process."""
        self.view_painted = True
        self.exempt_first_view = False

    # ── taking in events ────────────────────────────────────────────────────

    def _ingest(self, items, now: float, current=None) -> bool:
        """Take in waited-for items. True if a stop means run() must return."""
        for item in items:
            if isinstance(item, Stop):
                if isinstance(current, Off) or any(isinstance(a, Off) for a in self.actions):
                    # The confirmed power-off is still drawn and requested.
                    if not self.stop_pending:
                        log.info("stopping on signal %d once the power-off is "
                                 "requested", item.sig)
                    self.stop_pending = True
                    continue
                log.info("stopping on signal %d", item.sig)
                return True
            if isinstance(item, Repaint):
                log.info("repaint requested; it happens at the next allowed time")
                self.state = dataclasses.replace(self.state, etag=None, glass_sha256=None,
                                                 fast_count=FULL_EVERY)
                self.next_poll = self.d.boottime()
                self.glass = self.glass_strip = self.pre_prompt = None
                self.strip_cache = {}
            elif isinstance(item, Key):
                if item.value == 1:
                    self.gestures.press(item.t)
                else:
                    for gesture in self.gestures.release(item.t):
                        self._gesture(gesture, now)
            elif isinstance(item, KeyReset):
                self.gestures.reset()
        return False

    def _gesture(self, gesture, now: float) -> None:
        """Filter a tap or a hold (§4.8 step 2), then hand it to Ui."""
        kind, press_t = gesture
        if kind == "tap" and self.ui.mode == "browse":
            if not (self.views and self.view_ready and self._tokens(now) >= 2):
                if self.views and self.view_ready:
                    self.resting = True
                    self.problems.set("resting", "key resting; try again in "
                                      f"{math.ceil(self.bucket.next_at(2) - now)} s")
                return
        elif kind == "hold" and self.ui.mode == "browse":
            if not self.d.holds_ok:
                return
            if "confirm" not in self.screens:
                self.problems.set("no-confirm", "no confirm screen yet")
                return
            if self._tokens(now) >= 1:
                self.bucket.take()
            elif self.last_prompt_end is not None \
                    and now - self.last_prompt_end < HOLD_EMPTY_GAP_S:
                log.info("key: hold ignored; the key is resting")
                return
        self.actions.extend(getattr(self.ui, kind)(press_t, now))

    def _drain(self, current):
        """Before a paint: take in what is pending. _STOP if a stop must end
        run() first, _REQUEUED if the key went down (the action waits at the
        head of the queue), else None."""
        items = self.d.events.wait(0)
        if self._ingest(items, self.d.boottime(), current=current) \
                or (self.stop_pending and not isinstance(current, Off)):
            log.info("stopping before the refresh it would have started")
            return _STOP
        if self.gestures.pressed:
            self.actions.appendleft(current)
            return _REQUEUED
        return None

    # ── actions (§4.8 step 4) ───────────────────────────────────────────────

    def _collapse(self) -> None:
        """Consecutive strips collapse to the last; a strip or a page queued
        before a prompt is dropped. Prompt, Off and Leave are never dropped."""
        acts = list(self.actions)
        last_prompt = max((i for i, a in enumerate(acts) if isinstance(a, Prompt)),
                          default=-1)
        out: list = []
        for i, a in enumerate(acts):
            if isinstance(a, (Strip, Page)) and i < last_prompt:
                continue
            if isinstance(a, Strip) and out and isinstance(out[-1], Strip):
                out[-1] = a
                continue
            out.append(a)
        self.actions = collections.deque(out)

    def _run_actions(self) -> int | None:
        while True:
            self._collapse()
            if not self.actions or self.gestures.pressed:
                return None
            action = self.actions.popleft()
            r = getattr(self, "_do_" + type(action).__name__.lower())(action)
            if r == _STOP:
                return EX_OK
            if r == _FAIL:
                return EX_FAIL
            if r == _REQUEUED:
                return None

    def _do_strip(self, action: Strip):
        view = action.view
        if not (self._strip_ok(view) and self._tokens(self.d.boottime()) >= 1):
            return None
        r = self._drain(action)
        if r:
            return r
        if not self._strip_ok(view):    # USR1 forgot the glass meanwhile
            return None
        y0, y1 = self.glass_strip
        new = self.glass[:y0 * STRIDE] + self.strip_cache[view][1] + self.glass[y1 * STRIDE:]
        end = self._draw(new, purpose="strip", kind="partial", etag=None, view=None,
                         old=self.glass, strip=self.glass_strip)
        if end is not None:
            self._take(end)
        return None

    def _do_page(self, action: Page):
        view = action.view
        result = self._fetch(None, mode=view, tabs=True)
        flipped = self._view_result(result, view)
        now = self.d.boottime()
        if not isinstance(result, Frame):
            # No retry here: the routine branch fetches ui.view on its own
            # schedule, unconditionally, since the record's view is not it.
            backoff = self._failure(result, now, flipped)
            if isinstance(result, Throttled):
                self.next_poll = now + result.retry_s
            else:
                self.next_poll = min(self.next_poll, now + backoff)
            return None
        if self.glass is not None and result.body == self.glass:
            if (self.state.view, self.state.etag) != (view, result.etag):
                self.state = dataclasses.replace(self.state, view=view, etag=result.etag)
                save_state(self.d.state_dir, self.state)
            self.ui.painted_view(view)
            return None
        r = self._drain(action)
        if r:
            return r
        if self.ui.view != view:
            return None     # another tap moved on: its own page follows
        now = self.d.boottime()
        if self._tokens(now) < 1:
            self.next_poll = min(self.next_poll, now)   # the routine draws it
            return None
        end = self._draw(result.body, purpose="page", kind=self._kind("page"),
                         etag=result.etag, view=view, strip=result.strip)
        if end is not None:
            self._take(end)
            self.ui.painted_view(view)
            self._viewed()
        return None

    def _do_prompt(self, action: Prompt):
        self.pre_prompt = ((self.glass, self.state.view, self.state.etag, self.glass_strip)
                           if self.glass is not None else None)
        r = self._drain(action)
        if r:
            return r
        end = self._draw(self.screens["confirm"], purpose="prompt",
                         kind=self._kind("prompt"), etag=None, view=None)
        if end is None:
            self.actions.extend(self.ui.prompt_failed(self.d.boottime()))
            return None
        self.ui.shown_prompt(end)
        self.last_prompt_end = end
        return None

    def _do_off(self, action: Off):
        r = self._drain(action)
        if r:
            return r
        failed = False
        if "off" in self.screens:
            try:
                self._draw(self.screens["off"], purpose="off", kind=self._kind("off"),
                           etag=None, view=None, off=True)
            except _PanelFailed:
                failed = True       # powered off anyway; the panel is broken
        else:
            log.warning("no off screen yet; powering off with the glass as it is")
        result = self.d.request_poweroff()
        now = self.d.boottime()
        if result != "ok":
            log.error("could not request the power-off: %s", result)
            self.problems.set("poweroff", f"could not power off: {result}")
            if failed:
                return _FAIL
            self.actions.extend(self.ui.resume(now, why="failed"))
        else:
            log.info("power-off requested")
            self.grace_end = now + POWEROFF_GRACE_S
            self.off_paint_failed = failed
        if self.stop_pending:
            log.info("stopping: the power-off is requested")
            return _STOP
        return None

    def _do_leave(self, action: Leave):
        r = self._drain(action)
        if r:
            return r
        pre = self.pre_prompt
        if pre is not None:
            frame, view, etag, strip = pre
            self._draw(frame, purpose="leave", kind=self._kind("leave"), etag=etag,
                       view=view, strip=strip)
        else:
            # Nothing to go back to: white, so the glass never shows a prompt
            # that is no longer armed, until the routine fetch can draw.
            self._draw(WHITE, purpose="leave", kind="full", etag=None, view=None)
            self.next_poll = self.d.boottime()
        self.pre_prompt = None
        if pre is not None and pre[1] is not None:
            self.ui.painted_view(pre[1])
        self.ui.leave_done(self.d.boottime())
        return None

    def _do_idle(self, action: Idle):
        self.next_poll = self.d.boottime()
        return None

    def _grace_expired(self, now: float) -> int | None:
        self.grace_end = None
        self.d.clear_poweroff()
        if self.off_paint_failed:
            log.error("nothing acted on the power-off request within %d s, and the "
                      "off screen could not be drawn", POWEROFF_GRACE_S)
            return EX_FAIL
        log.error("nothing acted on the power-off request within %d s",
                  POWEROFF_GRACE_S)
        self.problems.set("poweroff", "could not power off: nothing acted on the "
                                      f"request within {POWEROFF_GRACE_S} s")
        self.actions.extend(self.ui.resume(now))
        return None

    # ── the routine branch (§4.8 step 5) ────────────────────────────────────

    def _routine(self) -> int | None:
        d = self.d
        now = d.boottime()
        if not (self._routine_eligible() and self._gate_open(now) and now >= self._due()):
            return None
        # The sync flag is read once per fetch: a sync that lands during the
        # fetch is then picked up by the next iteration, not lost in between.
        synced = d.synced()
        forced = self.force_next or forced_due(self.state, now, d.walltime(), synced)
        self.force_next = False
        view = self.ui.view
        recheck = (not self.views and d.key == "auto" and self.views_off_at is not None
                   and now - self.views_off_at >= VIEWS_RECHECK_S)
        if self.views or recheck:
            if recheck:
                log.info("asking the server for the desk key's views again")
                self.views_off_at = now
            sent = self.state.etag if self.state.view == view and not forced else None
            result = self._fetch(sent, mode=view, tabs=True)
            flipped = self._view_result(result, view)
            shown = view
        else:
            sent = self.state.etag if self.state.view is None and not forced else None
            result = self._fetch(sent)
            flipped, shown = False, None
            if isinstance(result, (Frame, NotModified)):
                self.first_fetch_ok = True
        now = d.boottime()
        self.healthy = False

        if isinstance(result, Frame):
            sha = hashlib.sha256(result.body).hexdigest()
            if sha == self.state.glass_sha256 and not forced:
                # Same picture under a new ETag (or a server that ignored
                # If-None-Match): remember the tag, leave the glass alone.
                if (result.etag, shown) != (self.state.etag, self.state.view):
                    self.state = dataclasses.replace(self.state, etag=result.etag,
                                                     view=shown)
                    save_state(d.state_dir, self.state)
                if shown:
                    self.view_seen = True
                self.problems.ok(self._healthy_line())
                self.next_poll = now + result.refresh_s
                self.healthy = True
            else:
                if self._ingest(d.events.wait(0), d.boottime()):
                    log.info("stopping before the refresh it would have started")
                    return EX_OK
                if self.gestures.pressed or self.actions:
                    return None     # the key first; next_poll as it was
                if not self.exempt_first_view and d.boottime() < self.floor_at:
                    # cannot happen; belt and braces
                    log.error("refusing to refresh %.0f s inside the floor",
                              self.floor_at - d.boottime())
                    self.next_poll = self.floor_at
                    return None
                end = self._draw(result.body, purpose="routine",
                                 kind=self._kind("forced" if forced else "routine"),
                                 etag=result.etag, view=shown,
                                 strip=result.strip if shown else None)
                if end is None:
                    self.next_poll = now + ERROR_RETRY_S
                    return None
                if shown:
                    self.ui.painted_view(shown)
                self._viewed()
                self.next_poll = end + result.refresh_s
                self.problems.ok(self._healthy_line())
                self.healthy = True
        elif isinstance(result, NotModified):
            if shown:
                self.view_seen = True
            self.problems.ok(self._healthy_line())
            self.next_poll = now + result.refresh_s
            self.healthy = True
        else:
            self.next_poll = now + self._failure(result, now, flipped)

        if self.unsaved:
            self.unsaved = not save_state(d.state_dir, self.state)

        # Keep the 23-hour repaint on time even if the server advises 24 h,
        # and across a reboot, but only after a healthy answer: a failure's
        # backoff is never cut short, and a forced fetch follows it anyway.
        # The clocks are read again, since the fetch (or paint) took time.
        self.cap_synced = synced
        if self.healthy:
            bt, wall = d.boottime(), d.walltime()
            if forced_due(self.state, bt, wall, self.cap_synced):
                # It came due during the fetch: fetch again now, forced.
                self.force_next = True
                self.next_poll = bt
            else:
                force_at = force_poll_at(self.state, bt, wall, self.cap_synced)
                if force_at is not None:
                    self.next_poll = min(self.next_poll, force_at)
        return None

    # ── background fetches (§4.8 step 6) ────────────────────────────────────

    def _bg_items(self, now: float) -> list[tuple[str, str]]:
        """What is worth fetching in the background, in order: missing
        screens, the strips of views not cached yet, stale screens."""
        if self.d.key != "auto":
            return []
        items = [("screen", k) for k in SCREENS if k not in self.screens
                 and (self.painted_any or self.first_fetch_ok)]
        # Only while the glass has a strip: with none (rotated 90/270) no strip
        # is ever drawn, so there is nothing to prefetch for.
        if self.view_painted and self.views and self.glass_strip is not None:
            items += [("view", v) for v in VIEWS if v not in self.strip_cache]
        if self.painted_any:
            items += [("screen", k) for k in SCREENS if k in self.screens
                      and now - self.screen_fetched_at[k] >= SCREEN_REVALIDATE_S]
        return [it for it in items if self.bg_retry.get(it, -math.inf) <= now]

    def _background(self) -> None:
        d = self.d
        if self.fetched or not (self.ui.mode == "browse" and not self.actions
                                and not self.gestures.pressed
                                and self.ui.page_due is None):
            return
        now = d.boottime()
        if now - self.last_fetch_t < BG_GAP_S:
            return
        items = self._bg_items(now)
        if not items:
            return
        item = items[0]
        kind, name = item
        if kind == "screen":
            result = self._fetch(None, screen=name)
            if isinstance(result, Frame):
                self.screens[name] = result.body
                self.screen_fetched_at[name] = d.boottime()
                save_screen(d.state_dir, name, result.body)
                return
        else:
            result = self._fetch(None, mode=name, tabs=True)
            self._view_result(result, name)
            if isinstance(result, Frame):
                return
        self.bg_retry[item] = d.boottime() + BG_RETRY_S

    # ── the loop ────────────────────────────────────────────────────────────

    def _timeout(self, now: float) -> float:
        """How long the wait may be (§4.8 step 7)."""
        pressed = self.gestures.pressed
        terms = [float(PING_SLICE_S)]
        if self.actions and not pressed:
            terms.append(0.0)
        if not self._gate_open(now):
            if not self.gate_logged:
                log.info("waiting for the clock to sync (or %d s of uptime) "
                         "before the first fetch", CLOCK_SYNC_GRACE_S)
                self.gate_logged = True
            terms.append(float(CLOCK_CHECK_S))
        elif self._routine_eligible():
            terms.append(self._due() - now)
        for at in (self.ui.next_deadline(pressed), self.gestures.next_deadline(),
                   self.d.events.next_retry(), self.grace_end):
            if at is not None:
                terms.append(at - now)
        if self.painted_any and self._bg_items(now):
            terms.append(float(BG_GAP_S))
        if self.resting:
            terms.append(self.bucket.next_at(2) - now)
        return max(0.0, min(terms))

    def run(self) -> int:
        try:
            return self._loop()
        except _PanelFailed:
            return EX_FAIL

    def _loop(self) -> int:
        d = self.d
        items: list = []
        while True:
            now = d.boottime()
            self.fetched = False
            # 2. Everything that happened, then the late clock sync.
            if self._ingest(items + d.events.wait(0), now):
                return EX_OK
            if self.healthy and not self.cap_synced and d.synced():
                # The clock synced after the next fetch was scheduled without
                # it. Ask now, once, so the wall-clock bound on the 23-hour
                # repaint applies, or a repaint it says is overdue happens.
                # Never after a failure: that would cut its backoff short.
                log.info("clock synced; checking the 23-hour repaint against it")
                self.cap_synced = True
                self.next_poll = now
            # 3. Gestures and Ui.
            for gesture in self.gestures.poll(now):
                self._gesture(gesture, now)
            if self.ui.mode == "off" and self.grace_end is not None \
                    and now >= self.grace_end:
                code = self._grace_expired(now)
                if code is not None:
                    return code
            if not self.gestures.pressed:
                self.actions.extend(self.ui.tick(now, gate_open=self._gate_open(now),
                                                 floor_at=self.floor_at))
            # 4-6. Actions, the routine fetch, a background fetch.
            code = self._run_actions()
            if code is not None:
                return code
            code = self._routine()
            if code is not None:
                return code
            self._background()
            # 7. Wait.
            now = d.boottime()
            if self.resting and self._tokens(now) >= 2:
                self.resting = False
                if self.problems.current == "resting":
                    self.problems.ok(self._healthy_line())
            timeout = self._timeout(now)
            items = d.events.wait(timeout)
            if timeout > 0:
                d.notify("WATCHDOG=1")
                self.last_ping = d.boottime()
            if not d.events.alive():
                log.critical("signals are no longer being collected")
                return EX_FAIL


def run(d: Deps) -> int:
    """The service loop. Returns an exit code; never returns mid-refresh."""
    return _Runner(d).run()


def clear(d: Deps) -> int:
    """Paint white, for storage, once the floor allows. Records it in state."""
    state = load_state(d.state_dir)
    floor_at = floor_ok_at(state, d.boottime())
    if d.boottime() < floor_at:
        log.info("clearing in %d s (the 180 s floor)",
                 math.ceil(floor_at - d.boottime()))
    while d.boottime() < floor_at:
        items = d.events.wait(min(PING_SLICE_S, floor_at - d.boottime()))
        if any(isinstance(item, Stop) for item in items):
            return EX_OK
    try:
        done, _ = _paint(d, state, WHITE, etag=None, view=None, kind="full",
                         off=False)
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
    if not raw:
        return 18
    if raw.lower() == "none":
        return None
    reserved = {17, 24, 25, 7, 8, 9, 10, 11}    # RST, BUSY, DC, SPI0
    # ASCII digits only: str.isdigit() also accepts "²", which int() refuses.
    if not re.fullmatch(r"[0-9]{1,2}", raw) or not 2 <= int(raw) <= 27 \
            or int(raw) in reserved:
        raise ConfigError(f"{PWR_PIN_ENV}={raw!r} is not a free BCM pin")
    return int(raw)


def refresh_from_env() -> str:
    """fast (partial and fast refreshes allowed) or full (every refresh full)."""
    raw = os.environ.get(REFRESH_ENV, "").strip()
    if not raw:
        return "fast"
    if raw not in ("fast", "full"):
        raise ConfigError(f"{REFRESH_ENV}={raw!r} is not fast or full")
    return raw


IDLE_RE = re.compile(r"[0-9]{1,5}")


def idle_from_env() -> int:
    """Seconds with no key before the glass goes back to Today; 0 is never."""
    raw = os.environ.get(IDLE_ENV, "").strip()
    if not raw:
        return 0
    if IDLE_RE.fullmatch(raw) and (int(raw) == 0 or 60 <= int(raw) <= 86_400):
        return int(raw)
    raise ConfigError(f"{IDLE_ENV}={raw!r} is not 0 or a number of seconds "
                      "from 60 to 86400")


def key_from_env() -> str:
    """auto (use the key if there is one) or off (never open it)."""
    raw = os.environ.get(KEY_ENV, "").strip()
    if not raw:
        return "auto"
    if raw not in ("auto", "off"):
        raise ConfigError(f"{KEY_ENV}={raw!r} is not auto or off")
    return raw


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


def keytest() -> int:
    """Print what the key does for KEYTEST_S seconds. Touches no panel or GPIO."""
    path = find_key_device(pathlib.Path(SYSFS_INPUT))
    if path is None:
        print("no pwr_button input device (is gpio_keys loaded?)", flush=True)
        return EX_FAIL
    try:
        fd = open_key(path)
    except OSError as e:
        print(f"cannot open {path}: {e.strerror}", flush=True)
        return EX_FAIL
    g = Gestures()
    end = boottime() + KEYTEST_S
    print(f"{path}: press the key; listening for {KEYTEST_S} s", flush=True)
    try:
        while True:
            now = boottime()
            if now >= end:
                break
            deadline = g.next_deadline()
            select.select([fd], [], [],
                          max(0.0, min(end, deadline if deadline is not None else end)
                              - now))
            data = b""
            try:
                while True:
                    chunk = os.read(fd, INPUT_EVENT.size * 64)
                    if not chunk:
                        break
                    data += chunk
            except BlockingIOError:
                pass
            except OSError as e:
                if e.errno not in (errno.ENODEV, errno.EIO):
                    raise
                print(f"the key device went away ({e.strerror})", flush=True)
                return EX_FAIL
            for item in decode_events(data):
                if isinstance(item, KeyReset):
                    g.reset()
                elif item.value == 1:
                    if not g.down:
                        print("press", flush=True)
                    g.press(item.t)
                elif not g.down:
                    print("release with no press seen → ignored", flush=True)
                else:
                    dt, held = item.t - g.press_t, g.hold_emitted
                    got = g.release(item.t)
                    if got:
                        verdict = got[0][0]
                    elif held:
                        verdict = "hold"
                    elif dt < DEBOUNCE_S:
                        verdict = "noise"
                    else:
                        verdict = "ignored"
                    print(f"release after {dt:.2f} s → {verdict}", flush=True)
            for kind, _ in g.poll(boottime()):
                if kind == "hold":
                    print("let go now", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        os.close(fd)
    return EX_OK


def reset_refresh(state_dir: pathlib.Path) -> int:
    """Clear the batch guard's verdict, so fast and partial refreshes resume."""
    if not (state_dir / STATE_FILE).exists():
        log.info("no state file in %s; quick refresh is not disabled", state_dir)
        return EX_OK
    s = load_state(state_dir)
    if not save_state(state_dir, dataclasses.replace(s, quick_disabled=False)):
        return EX_FAIL
    log.info("quick refresh re-enabled")
    return EX_OK


USAGE = ("usage: panel.py [--selftest | --clear | --power-off | --keytest | "
         "--reset-refresh]")


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    mode = args[0] if args else "run"
    if len(args) > 1 or mode not in ("run", "--selftest", "--clear", "--power-off",
                                     "--keytest", "--reset-refresh"):
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

    if mode == "--keytest":
        # Before the signals are blocked, so Ctrl-C ends it. It reads the key
        # and nothing else: no panel, no GPIO, no state.
        setup_logging()
        return keytest()

    # Before anything else can take a signal: from here on, stops are only
    # ever collected by the Collector's thread, which run and --clear start.
    signal.pthread_sigmask(signal.SIG_BLOCK, WAIT_SIGNALS)
    start_bt = boottime()
    fmt = setup_logging()

    if os.geteuid() == 0:
        log.critical("refusing to run as root — use smylte-panel.service, which "
                     "runs it as a dynamic user with only the gpio and spi groups")
        return EX_CONFIG
    try:
        pwr = pwr_pin_from_env()
        token = load_token(os.environ.get("CREDENTIALS_DIRECTORY")) \
            if mode == "run" else None
        state_dir = state_dir_from_env() \
            if mode in ("run", "--clear", "--reset-refresh") else None
        # Read now, so a bad value stops the unit before the hardware is touched.
        refresh = refresh_from_env()
        idle = idle_from_env()
        key = key_from_env()
    except ConfigError as e:
        log.critical("%s", e)
        return EX_CONFIG
    fmt.token = token
    if mode == "--reset-refresh":
        return reset_refresh(state_dir)

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
        collector = start_collector(WAIT_SIGNALS)
        if mode == "--clear":
            # Holds and the key mean nothing here: stops only.
            return clear(Deps(state_dir=state_dir, panel=panel, epd=epd, fetch=None,
                              events=Events(collector, sysfs_root=pathlib.Path(SYSFS_INPUT),
                                            open_key=open_key, boottime=boottime,
                                            key_enabled=False)))

        def do_fetch(etag, *, mode=None, tabs=False, screen=None):
            return fetch(token, etag, mode=mode, tabs=tabs, screen=screen, tick=tick)

        # Where a power-off request goes ($RUNTIME_DIRECTORY, RuntimeDirectory=).
        raw = os.environ.get("RUNTIME_DIRECTORY", "")
        run_dir = raw.split(":")[0] if raw else None
        holds_ok = run_dir is not None and os.path.isdir(run_dir) \
            and os.access(run_dir, os.W_OK)
        events = Events(collector, sysfs_root=pathlib.Path(SYSFS_INPUT),
                        open_key=open_key, boottime=boottime,
                        key_enabled=(key == "auto"))
        sd_notify("READY=1\nSTATUS=ready; waiting for the first allowed refresh")
        return run(Deps(state_dir=state_dir, panel=panel, epd=epd, fetch=do_fetch,
                        events=events,
                        request_poweroff=lambda: request_poweroff(run_dir, start_bt),
                        clear_poweroff=lambda: clear_poweroff(run_dir),
                        refresh=refresh, idle_s=idle, key=key, holds_ok=holds_ok,
                        logind_present=logind_dropin_present()))
    except Exception:
        log.critical("unexpected failure", exc_info=True)
        return EX_FAIL
    finally:
        panel.close()


if __name__ == "__main__":
    sys.exit(main())
