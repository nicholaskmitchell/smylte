"""The Pi panel client's view key, piece by piece, before the loop uses it.

`firmware/pi_epaper_7in5/panel.py` reads the Pi 5's power key as an input
device, turns its edges into taps and holds, and keeps a budget of the
refreshes the key may ask for. This file holds each of those pieces to its
contract on its own: the settings, the view and screen fetch contract, the
version 2 state file, `_paint()` carrying the state forward, the signal
collector (in a child process, so a real signal never reaches pytest), key
discovery and decoding on a fake sysfs tree and a pipe, the pure Gestures, Ui
and Bucket tables, the power-off request and the screen cache, and the
`--keytest` and `--reset-refresh` commands. Nothing here touches hardware or
imports Waveshare's code.
"""
from __future__ import annotations

import dataclasses
import errno
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import types

import pi_panel_fakes as F
import pytest
import test_firmware_pi_loop as loop
from test_firmware_pi_loop import Clock, FakePanel, Harness, etag, frame, sha

P = F.load_panel()
E = F.load_driver()

# The loop tests' fixtures, for main().
guarded_main = loop.guarded_main
no_driver = loop.no_driver
valid_env = loop.valid_env

GOOD = [("content-type", "application/octet-stream"), ("content-length", "48000"),
        ("etag", '"' + "a" * 32 + '"'), ("x-display-width", "800"),
        ("x-display-height", "480"), ("x-display-stride", "100"),
        ("x-display-format", "mono-hlsb-inverted"), ("x-display-refresh-seconds", "300")]
W0 = 1.7e9


# ── settings ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fn, env, value, expected", [
    ("pwr_pin_from_env", P.PWR_PIN_ENV, None, 18),
    ("pwr_pin_from_env", P.PWR_PIN_ENV, "  ", 18),
    ("pwr_pin_from_env", P.PWR_PIN_ENV, "None", None),
    ("pwr_pin_from_env", P.PWR_PIN_ENV, "NONE", None),
    ("refresh_from_env", P.REFRESH_ENV, None, "fast"),
    ("refresh_from_env", P.REFRESH_ENV, "", "fast"),
    ("refresh_from_env", P.REFRESH_ENV, "fast", "fast"),
    ("refresh_from_env", P.REFRESH_ENV, "full", "full"),
    ("refresh_from_env", P.REFRESH_ENV, "partial", P.ConfigError),
    ("refresh_from_env", P.REFRESH_ENV, "1", P.ConfigError),
    ("idle_from_env", P.IDLE_ENV, None, 0),
    ("idle_from_env", P.IDLE_ENV, "", 0),
    ("idle_from_env", P.IDLE_ENV, "0", 0),
    ("idle_from_env", P.IDLE_ENV, "60", 60),
    ("idle_from_env", P.IDLE_ENV, "86400", 86400),
    ("idle_from_env", P.IDLE_ENV, "59", P.ConfigError),
    ("idle_from_env", P.IDLE_ENV, "86401", P.ConfigError),
    ("idle_from_env", P.IDLE_ENV, "-60", P.ConfigError),
    ("idle_from_env", P.IDLE_ENV, "1e3", P.ConfigError),
    ("idle_from_env", P.IDLE_ENV, "ten", P.ConfigError),
    ("key_from_env", P.KEY_ENV, None, "auto"),
    ("key_from_env", P.KEY_ENV, "", "auto"),
    ("key_from_env", P.KEY_ENV, "auto", "auto"),
    ("key_from_env", P.KEY_ENV, "off", "off"),
    ("key_from_env", P.KEY_ENV, "on", P.ConfigError),
])
def test_the_settings(monkeypatch, fn, env, value, expected):
    if value is None:
        monkeypatch.delenv(env, raising=False)
    else:
        monkeypatch.setenv(env, value)
    if expected is P.ConfigError:
        with pytest.raises(P.ConfigError):
            getattr(P, fn)()
    else:
        assert getattr(P, fn)() == expected


@pytest.mark.parametrize("env, value", [
    (P.REFRESH_ENV, "partial"), (P.IDLE_ENV, "5"), (P.KEY_ENV, "on"),
])
@pytest.mark.parametrize("argv", [[], ["--clear"], ["--selftest"]])
def test_a_bad_new_setting_exits_78_without_touching_hardware(
        valid_env, monkeypatch, no_driver, guarded_main, env, value, argv):
    monkeypatch.setattr(P.os, "geteuid", lambda: 1000)
    monkeypatch.setenv(env, value)
    assert guarded_main(argv) == 78
    assert no_driver == []


def test_power_off_ignores_the_new_settings(monkeypatch, guarded_main):
    monkeypatch.setattr(P.os, "geteuid", lambda: 0)
    monkeypatch.setenv(P.REFRESH_ENV, "partial")
    monkeypatch.setenv(P.PWR_PIN_ENV, "8")
    got = []
    monkeypatch.setattr(P, "open_driver", lambda: types.SimpleNamespace(
        drive_lines_low=got.append))
    assert guarded_main(["--power-off"]) == 0
    assert got == [None]


# ── the fetch contract ───────────────────────────────────────────────────────

@pytest.mark.parametrize("kwargs, tail", [
    ({}, ""),
    ({"mode": "now"}, "&mode=now"),
    ({"tabs": True}, "&tabs=1"),
    ({"screen": "off"}, "&screen=off"),
    ({"mode": "calendar", "tabs": True}, "&mode=calendar&tabs=1"),
    ({"screen": "confirm", "tabs": True, "mode": "habits"},
     "&mode=habits&tabs=1&screen=confirm"),
])
def test_the_request_target(kwargs, tail):
    base = P.PATH_FMT % "tok" + "?" + P.QUERY
    assert P.request_target("tok", **kwargs) == base + tail


VIEW = GOOD + [("x-display-mode", "now"), ("x-display-tab-strip", "440-480")]
SCREEN = GOOD + [("x-display-screen", "confirm")]


def _without(items, name):
    return [(k, v) for k, v in items if k != name]


def _with_strip(value):
    return _without(VIEW, "x-display-tab-strip") + [("x-display-tab-strip", value)]


HEADER_CASES = [
    # A view request.
    ("view", VIEW, {"want_mode": "now", "want_tabs": True}, None),
    ("view-title-case", [(k.title(), v) for k, v in VIEW],
     {"want_mode": "now", "want_tabs": True}, None),
    ("view-no-strip", _without(VIEW, "x-display-tab-strip"),
     {"want_mode": "now", "want_tabs": True}, None),
    ("view-no-tabs", _without(VIEW, "x-display-tab-strip"), {"want_mode": "now"}, None),
    ("mode-missing", _without(VIEW, "x-display-mode"),
     {"want_mode": "now", "want_tabs": True}, "mode"),
    ("mode-wrong", VIEW, {"want_mode": "habits", "want_tabs": True}, "mode"),
    ("mode-twice", VIEW + [("x-display-mode", "now")],
     {"want_mode": "now", "want_tabs": True}, "mode"),
    ("strip-unasked", VIEW, {"want_mode": "now"}, "tab strip"),
    ("strip-twice", VIEW + [("x-display-tab-strip", "440-480")],
     {"want_mode": "now", "want_tabs": True}, "tab strip"),
    ("strip-0-2", _with_strip("0-2"), {"want_mode": "now", "want_tabs": True}, None),
    ("strip-478-480", _with_strip("478-480"),
     {"want_mode": "now", "want_tabs": True}, None),
    *[(f"strip-{bad}", _with_strip(bad), {"want_mode": "now", "want_tabs": True},
       "tab strip")
      for bad in ("440_480", "480-440", "440-440", "0-1", "479-480", "0-481",
                  "12345-2", "-1-5", " 440-480", "440-480 ", "", "a-b", "٤٤٠-٤٨٠")],
    ("view-still-checks-the-rest", _without(VIEW, "etag") + [("etag", "bad")],
     {"want_mode": "now", "want_tabs": True}, "etag"),
    # A screen request.
    ("screen", SCREEN, {"want_screen": "confirm"}, None),
    ("screen-missing", GOOD, {"want_screen": "confirm"}, "screen"),
    ("screen-wrong", SCREEN, {"want_screen": "off"}, "screen"),
    ("screen-twice", SCREEN + [("x-display-screen", "confirm")],
     {"want_screen": "confirm"}, "screen"),
    ("screen-with-mode", SCREEN + [("x-display-mode", "now")],
     {"want_screen": "confirm"}, "screen"),
    ("screen-with-strip", SCREEN + [("x-display-tab-strip", "440-480")],
     {"want_screen": "confirm"}, "screen"),
    # A legacy request ignores the new headers, well formed or not.
    ("legacy", VIEW + [("x-display-mode", "?"), ("x-display-tab-strip", "x"),
                       ("x-display-screen", "?")], {}, None),
]


@pytest.mark.parametrize("items, kwargs, expected",
                         [pytest.param(i, k, e, id=n) for n, i, k, e in HEADER_CASES])
def test_check_headers_holds_each_request_to_its_own_headers(items, kwargs, expected):
    assert P.check_headers(200, items, length=48000, **kwargs) == expected


BODY = bytes(range(256)) * (P.BUF_BYTES // 256) + bytes(P.BUF_BYTES % 256)


def _fetch(script, etag=None, **kw):
    with F.ReplayServer(script) as server:
        result = P.fetch("t" * 43, etag, port=server.port, **kw)
    return result, server


def _target(server) -> str:
    return server.requests[0].decode("latin-1").split("\r\n")[0].split(" ")[1]


def test_a_view_fetch_asks_for_the_view_and_returns_its_strip():
    result, server = _fetch([F.raw_response(200, VIEW, BODY, "OK")], mode="now", tabs=True)
    assert result == P.Frame(BODY, GOOD[2][1], 300, strip=(440, 480), mode="now")
    assert _target(server) == P.request_target("t" * 43, mode="now", tabs=True)
    assert _target(server).endswith("&mode=now&tabs=1")


def test_a_view_fetch_without_a_strip_header_has_no_strip():
    reply = F.raw_response(200, _without(VIEW, "x-display-tab-strip"), BODY, "OK")
    result, _ = _fetch([reply], mode="now", tabs=True)
    assert result == P.Frame(BODY, GOOD[2][1], 300, strip=None, mode="now")


def test_a_view_fetch_of_the_wrong_view_is_refused():
    result, _ = _fetch([F.raw_response(200, VIEW, BODY, "OK")], mode="calendar", tabs=True)
    assert result == P.Refused("mode", 200)


def test_a_screen_fetch_returns_a_frame_with_no_view():
    result, server = _fetch([F.raw_response(200, SCREEN, BODY, "OK")], screen="confirm")
    assert result == P.Frame(BODY, GOOD[2][1], 300)
    assert _target(server).endswith("&screen=confirm")


def test_a_legacy_fetch_ignores_the_view_headers():
    result, server = _fetch([F.raw_response(200, VIEW, BODY, "OK")])
    assert result == P.Frame(BODY, GOOD[2][1], 300)
    assert result.strip is None and result.mode is None
    assert _target(server) == P.request_target("t" * 43)


@pytest.mark.parametrize("status, headers, code", [
    (422, [("x-display-error", "views-off")], "views-off"),
    (422, [], None),
    (422, [("x-display-error", "views-off"), ("x-display-error", "x")], None),
    (400, [("x-display-error", "views-off")], None),
])
def test_a_refusal_carries_the_servers_error_code_only_on_a_422(status, headers, code):
    reply = F.raw_response(status, headers + [("content-length", "0")], b"")
    result, _ = _fetch([reply], mode="now", tabs=True)
    assert result == P.Refused(f"HTTP {status}", status, code=code)


# ── the state file, version 2 ────────────────────────────────────────────────

V2 = {"version": 2, "etag": etag(1), "glass_sha256": sha(frame(1)),
      "painted_end_bt": 1000.0, "painted_wall": W0, "attempt_start_bt": 995.0,
      "complete": True, "view": "now", "fast_count": 3, "off": False,
      "full_end_bt": 800.0, "full_wall": W0 - 200, "quick_disabled": False}


def _raw(d) -> bytes:
    return json.dumps(d).encode()


def test_a_version_1_record_migrates():
    v1 = {"version": 1, "etag": etag(1), "glass_sha256": sha(frame(1)),
          "painted_end_bt": 1000.0, "painted_wall": W0, "attempt_start_bt": 995.0,
          "complete": True}
    assert P.parse_state(_raw(v1)) == P.State(
        etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=1000.0,
        painted_wall=W0, attempt_start_bt=995.0, complete=True, view=None,
        fast_count=P.FULL_EVERY, off=False, full_end_bt=1000.0, full_wall=W0,
        quick_disabled=False)


@pytest.mark.parametrize("v1", [
    {"version": 1, "attempt_start_bt": 995.0, "complete": False},
    {"version": 1, "attempt_start_bt": 995.0, "complete": False,
     "painted_end_bt": 900.0, "painted_wall": W0},
])
def test_an_incomplete_version_1_record_migrates_with_no_full_refresh(v1):
    s = P.parse_state(_raw(v1))
    assert s is not None and s.complete is False
    assert (s.full_end_bt, s.full_wall) == (None, None)
    assert (s.view, s.fast_count, s.off, s.quick_disabled) == (None, P.FULL_EVERY,
                                                               False, False)


def test_a_version_2_record_round_trips(tmp_path):
    s = P.State(etag=etag(7), glass_sha256=sha(frame(7)), painted_end_bt=1234.5,
                painted_wall=W0 + 1234.5, attempt_start_bt=1230.0, complete=True,
                view="calendar", fast_count=1000, off=True, full_end_bt=1000.0,
                full_wall=W0 + 1000.0, quick_disabled=True)
    assert P.save_state(tmp_path, s)
    assert json.loads((tmp_path / P.STATE_FILE).read_bytes())["version"] == 2
    assert P.load_state(tmp_path) == s
    assert P.parse_state(_raw(V2)) is not None


@pytest.mark.parametrize("field, value", [
    ("view", "today"), ("view", "Now"), ("view", 1), ("view", ""),
    ("fast_count", -1), ("fast_count", 1001), ("fast_count", True), ("fast_count", 1.0),
    ("fast_count", "3"), ("fast_count", None),
    ("off", None), ("off", 0), ("off", "false"),
    ("quick_disabled", None), ("quick_disabled", 1),
    ("full_end_bt", -1), ("full_end_bt", 1e11), ("full_end_bt", True),
    ("full_end_bt", "800"), ("full_wall", -5), ("full_wall", 1e12), ("full_wall", False),
])
def test_each_invalid_version_2_field_makes_the_record_unknown(field, value):
    assert P.parse_state(_raw({**V2, field: value})) is None


@pytest.mark.parametrize("field", ["fast_count", "off", "quick_disabled"])
def test_a_version_2_record_missing_a_field_is_unknown(field):
    d = dict(V2)
    del d[field]
    assert P.parse_state(_raw(d)) is None


def test_a_version_2_record_with_a_nan_time_is_unknown():
    assert P.parse_state(_raw(V2).replace(b'"full_end_bt": 800.0',
                                          b'"full_end_bt": NaN')) is None


@pytest.mark.parametrize("version", [0, 3, "2", 2.5, True, None])
def test_an_unknown_version_is_unknown(version):
    assert P.parse_state(_raw({**V2, "version": version})) is None


NOW_BT, NOW_WALL = 100_000.0, W0 + 100_000.0


def test_the_23_hour_repaint_counts_from_the_last_full_refresh():
    # A fast refresh a minute ago does not reset it...
    s = P.State(complete=True, painted_end_bt=NOW_BT - 60, painted_wall=NOW_WALL - 60,
                full_end_bt=NOW_BT - 82_800, full_wall=None)
    assert P.forced_due(s, NOW_BT, NOW_WALL, True) is True
    assert P.force_poll_at(s, NOW_BT, NOW_WALL, True) is None
    # ...and an old fast refresh does not make it due.
    s = P.State(complete=True, painted_end_bt=NOW_BT - 90_000, painted_wall=None,
                full_end_bt=NOW_BT - 1000, full_wall=NOW_WALL - 2000)
    assert P.forced_due(s, NOW_BT, NOW_WALL, True) is False
    assert P.force_poll_at(s, NOW_BT, NOW_WALL, True) == NOW_BT + 82_800 - 2000
    assert P.force_poll_at(s, NOW_BT, NOW_WALL, False) == NOW_BT + 82_800 - 1000


def test_a_complete_record_with_no_full_refresh_counts_as_nothing_painted():
    s = P.State(complete=True, painted_end_bt=NOW_BT - 90_000, painted_wall=W0)
    assert P.forced_due(s, NOW_BT, NOW_WALL, True) is False
    assert P.force_poll_at(s, NOW_BT, NOW_WALL, True) is None
    s = P.State(complete=False, painted_end_bt=1.0, full_end_bt=1.0, full_wall=W0)
    assert P.forced_due(s, NOW_BT, NOW_WALL, True) is False
    assert P.force_poll_at(s, NOW_BT, NOW_WALL, True) is None


@pytest.mark.parametrize("painted, full, want_painted, want_full", [
    (50_000.0, 40_000.0, 0.0, 0.0),
    (500.0, 40_000.0, 500.0, 0.0),
    (50_000.0, 500.0, 0.0, 500.0),
    (50_000.0, None, 0.0, None),
])
def test_an_earlier_boots_times_are_each_rewritten_as_boot_time_zero(
        tmp_path, painted, full, want_painted, want_full):
    assert P.save_state(tmp_path, P.State(
        etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=painted,
        attempt_start_bt=painted - 5, complete=True, full_end_bt=full))
    seen = []

    def responder(n, sent, clock):
        seen.append(P.load_state(tmp_path))
        return P.Gone()

    h = Harness(tmp_path, Clock(1000.0), responder, stop_after=1)
    assert h.run() == 0
    assert (seen[0].painted_end_bt, seen[0].full_end_bt) == (want_painted, want_full)


# ── _paint() ─────────────────────────────────────────────────────────────────

class PartialPanel(FakePanel):
    def __init__(self, clock, peek=None, **kw):
        super().__init__(clock, **kw)
        self.partials = []
        self.peek = peek

    def display(self, frame_):
        if self.peek:
            self.peek()
        super().display(frame_)

    def display_partial(self, old, new):
        if self.peek:
            self.peek()
        self.partials.append((old, new))
        super().display_partial(old, new)


def _deps(tmp_path, clock, panel):
    return P.Deps(state_dir=tmp_path, panel=panel, epd=E, fetch=None,
                  boottime=clock.boottime, walltime=clock.walltime,
                  synced=clock.synced_fn, notify=lambda m: None)


PREV = P.State(etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=500.0,
               painted_wall=W0 + 500.0, attempt_start_bt=495.0, complete=True,
               view="now", fast_count=2, off=True, full_end_bt=400.0,
               full_wall=W0 + 400.0, quick_disabled=True)


@pytest.mark.parametrize("kind, count", [("full", 0), ("fast", 3), ("partial", 3)])
def test_the_write_ahead_record_carries_what_outlives_a_refresh(tmp_path, kind, count):
    clock = Clock(1000.0)
    seen = []
    panel = PartialPanel(clock, peek=lambda: seen.append(P.load_state(tmp_path)))
    d = _deps(tmp_path, clock, panel)
    P._paint(d, PREV, frame(2), etag=etag(2), view="calendar", kind=kind,
             old=frame(1) if kind == "partial" else None)
    assert seen == [P.State(
        etag=None, glass_sha256=None, painted_end_bt=500.0, painted_wall=W0 + 500.0,
        attempt_start_bt=1000.0, complete=False, view=None, fast_count=count,
        off=False, full_end_bt=400.0, full_wall=W0 + 400.0, quick_disabled=True)]


def test_a_full_refresh_records_itself_as_the_last_full_one(tmp_path, caplog):
    clock = Clock(1000.0)
    panel = PartialPanel(clock)
    with caplog.at_level(logging.INFO):
        done, end = P._paint(_deps(tmp_path, clock, panel), PREV, frame(2),
                             etag=etag(2), view="calendar", kind="full", off=True)
    assert panel.modes == ["full"]
    assert panel.names() == ["init", "display", "sleep"]
    assert end == pytest.approx(clock.t)
    assert done == P.State(
        etag=etag(2), glass_sha256=sha(frame(2)), painted_end_bt=end,
        painted_wall=W0 + end, attempt_start_bt=1000.0, complete=True,
        view="calendar", fast_count=0, off=True, full_end_bt=end,
        full_wall=W0 + end, quick_disabled=True)
    assert P.load_state(tmp_path) == done
    assert any(re.fullmatch(r"painted 00000000 \(full\) in \d+\.\d s", r.getMessage())
               for r in caplog.records)


@pytest.mark.parametrize("kind", ["fast", "partial"])
def test_a_fast_or_partial_refresh_counts_and_leaves_the_full_one(tmp_path, kind):
    clock = Clock(1000.0)
    clock.synced = False
    panel = PartialPanel(clock)
    old = frame(1) if kind == "partial" else None
    done, end = P._paint(_deps(tmp_path, clock, panel), PREV, frame(2), etag=None,
                         view=None, kind=kind, old=old)
    assert panel.modes == [kind]
    assert panel.partials == ([(frame(1), frame(2))] if kind == "partial" else [])
    assert done.fast_count == 3
    assert (done.full_end_bt, done.full_wall) == (400.0, W0 + 400.0)
    assert (done.painted_end_bt, done.painted_wall) == (end, None)
    assert (done.etag, done.view, done.off) == (None, None, False)
    assert done.glass_sha256 == sha(frame(2))


def test_fast_count_saturates_at_1000(tmp_path):
    clock = Clock(1000.0)
    prev = P.State(fast_count=1000)
    done, _ = P._paint(_deps(tmp_path, clock, PartialPanel(clock)), prev, frame(2),
                       etag=None, view=None, kind="fast")
    assert done.fast_count == 1000


def test_a_failing_refresh_leaves_the_write_ahead_record(tmp_path):
    clock = Clock(1000.0)
    panel = PartialPanel(clock, fail={"display": E.BusyTimeout("refresh", 60.0)})
    with pytest.raises(E.BusyTimeout):
        P._paint(_deps(tmp_path, clock, panel), PREV, frame(2), etag=etag(2),
                 view="now", kind="fast")
    assert "abort" in panel.names()
    s = P.load_state(tmp_path)
    assert (s.complete, s.attempt_start_bt, s.fast_count) == (False, 1000.0, 3)
    assert (s.etag, s.view, s.glass_sha256) == (None, None, None)


def test_a_partial_without_the_old_bytes_raises_before_anything(tmp_path):
    clock = Clock(1000.0)
    panel = PartialPanel(clock)
    with pytest.raises(ValueError):
        P._paint(_deps(tmp_path, clock, panel), PREV, frame(2), etag=None, view=None,
                 kind="partial")
    assert panel.calls == []
    assert not (tmp_path / P.STATE_FILE).exists()


# ── the signal collector ─────────────────────────────────────────────────────

LOAD = """
import importlib.util, os, select, signal, sys, threading, time
spec = importlib.util.spec_from_file_location("panel_under_test", sys.argv[1])
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)
"""

COLLECTOR_SCRIPT = LOAD + """
signal.pthread_sigmask(signal.SIG_BLOCK, panel.WAIT_SIGNALS)
c = panel.start_collector(panel.WAIT_SIGNALS)
print("alive", c.alive())
threading.Timer(0.1, os.kill, (os.getpid(), signal.SIGUSR1)).start()
threading.Timer(0.2, os.kill, (os.getpid(), signal.SIGTERM)).start()
start = time.monotonic()
spins = 0
while time.monotonic() - start < 0.5:
    spins += 1
print("busy", spins > 0 and time.monotonic() - start >= 0.5)
got = []
deadline = time.monotonic() + 5
while len(got) < 2 and time.monotonic() < deadline:
    ready, _, _ = select.select([c.fd], [], [], deadline - time.monotonic())
    got += c.pop()
print("popped", got)
print("empty", c.pop(), select.select([c.fd], [], [], 0)[0])
"""

UNMASKED_SCRIPT = LOAD + """
c = panel.start_collector(panel.WAIT_SIGNALS)
time.sleep(5)
print("not reached")
"""


def test_the_collector_takes_signals_in_order_without_interrupting_anything():
    """In a child process, so a real SIGTERM can never reach pytest."""
    out = subprocess.run([sys.executable, "-I", "-c", COLLECTOR_SCRIPT, str(F.PANEL_PY)],
                         timeout=20, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    lines = out.stdout.splitlines()
    assert lines == ["alive True", "busy True",
                     f"popped [{int(P.REPAINT_SIGNAL)}, {int(P.signal.SIGTERM)}]",
                     "empty [] []"], out.stdout + out.stderr


def test_the_collector_exits_the_process_if_the_signals_are_not_blocked():
    out = subprocess.run([sys.executable, "-I", "-c", UNMASKED_SCRIPT, str(F.PANEL_PY)],
                         timeout=20, capture_output=True, text=True)
    assert out.returncode == P.EX_FAIL
    assert "not reached" not in out.stdout


# ── the key device ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, value", [
    ("", 0), ("0", 0), ("\n", 0), ("3", 3), ("3\n", 3),
    ("10000000000000 0", 1 << 116),     # the Pi 5's pwr_button: KEY_POWER
    ("1 0 0", 1 << 128),
    ("ffffffffffffffff", (1 << 64) - 1),
    ("1 ffffffffffffffff", (1 << 65) - 1),
])
def test_parse_bitmap(text, value):
    assert P.struct.calcsize("L") == 8      # these words are 64-bit longs
    assert P.parse_bitmap(text) == value


def make_input(root, node="event0", name="pwr_button", ev="3", key="10000000000000 0"):
    dev = root / node / "device"
    (dev / "capabilities").mkdir(parents=True)
    (dev / "name").write_text(name + "\n")
    if ev is not None:
        (dev / "capabilities" / "ev").write_text(ev + "\n")
    if key is not None:
        (dev / "capabilities" / "key").write_text(key + "\n")


@pytest.fixture
def sysfs(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_many_keys_logged", False)
    root = tmp_path / "sys-class-input"
    root.mkdir()
    return root


def test_the_one_pwr_button_is_found(sysfs):
    make_input(sysfs, "event0", name="vc4-hdmi-0", key="1")
    make_input(sysfs, "event3")
    (sysfs / "input3").mkdir()
    assert P.find_key_device(sysfs) == "/dev/input/event3"


@pytest.mark.parametrize("kw", [
    dict(name="pwr_buttons"),
    dict(name="gpio_keys"),
    dict(key="0"),
    dict(key="10000000000000"),         # bit 52, not 116
    dict(ev="1"),                       # no EV_KEY
    dict(ev=None),
    dict(key=None),
    dict(key="zz"),
])
def test_anything_else_is_no_key(sysfs, kw):
    make_input(sysfs, "event0", **kw)
    assert P.find_key_device(sysfs) is None


def test_no_input_devices_is_no_key(sysfs):
    assert P.find_key_device(sysfs) is None
    assert P.find_key_device(sysfs / "missing") is None


def test_an_unreadable_candidate_is_skipped(sysfs):
    make_input(sysfs, "event0", key=None)
    make_input(sysfs, "event1")
    assert P.find_key_device(sysfs) == "/dev/input/event1"


def test_two_pwr_buttons_are_no_key_and_say_so_once(sysfs, caplog):
    make_input(sysfs, "event0")
    make_input(sysfs, "event1")
    with caplog.at_level(logging.ERROR):
        assert P.find_key_device(sysfs) is None
        assert P.find_key_device(sysfs) is None
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1


def ev(t, etype, code, value) -> bytes:
    sec = int(t)
    return P.INPUT_EVENT.pack(sec, round((t - sec) * 1e6), etype, code, value)


def key(t, value) -> bytes:
    return ev(t, P.EV_KEY, P.KEY_POWER, value)


SYN = 0     # SYN_REPORT


def test_decode_events():
    data = (key(100.25, 1) + ev(100.25, P.EV_SYN, SYN, 0)
            + key(100.5, 2) + ev(100.5, P.EV_KEY, 115, 1) + ev(100.5, 4, 4, 1)
            + ev(100.75, P.EV_SYN, P.SYN_DROPPED, 0)
            + key(101.0, 0))
    assert P.decode_events(data) == [P.Key(1, 100.25), P.KeyReset(100.75),
                                     P.Key(0, 101.0)]
    assert P.decode_events(data + key(102.0, 1)[:-1]) == P.decode_events(data)
    assert P.decode_events(b"") == []
    assert P.INPUT_EVENT.size == 24


class FakeCollector:
    def __init__(self):
        self.r, self.w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.items = []

    @property
    def fd(self):
        return self.r

    def send(self, sig):
        self.items.append(int(sig))
        os.write(self.w, b"\0")

    def pop(self):
        try:
            os.read(self.r, 4096)
        except BlockingIOError:
            pass
        out, self.items = self.items, []
        return out

    def alive(self):
        return True

    def close(self):
        os.close(self.r)
        os.close(self.w)


class KeyNode:
    """open_key() for the tests: each open is a fresh pipe; the test writes."""

    def __init__(self, fail=None):
        self.opened = []
        self.writers = []
        self.fail = fail

    def __call__(self, path):
        if self.fail:
            raise self.fail
        r, w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self.opened.append((path, r))
        self.writers.append(w)
        return r

    def write(self, data):
        os.write(self.writers[-1], data)


@pytest.fixture
def events(sysfs):
    clock = Clock(100.0)
    collector = FakeCollector()
    node = KeyNode()

    def make(key_enabled=True, open_key=None):
        return P.Events(collector, sysfs_root=sysfs, open_key=open_key or node,
                        boottime=clock.boottime, key_enabled=key_enabled)
    yield make, clock, collector, node
    collector.close()
    for w in node.writers:
        os.close(w)


def test_signals_and_keys_come_back_in_one_call_signals_first(sysfs, events):
    make, clock, collector, node = events
    make_input(sysfs, "event2")
    e = make()
    assert e.wait(0) == []
    assert e.key_open and node.opened[0][0] == "/dev/input/event2"
    assert e.next_retry() is None
    node.write(key(99.0, 1) + key(99.2, 0))
    collector.send(P.signal.SIGUSR1)
    collector.send(P.signal.SIGTERM)
    assert e.wait(5) == [P.Repaint(), P.Stop(int(P.signal.SIGTERM)), P.Key(1, 99.0),
                         P.Key(0, 99.2)]
    assert e.wait(0) == []


def test_a_wait_with_nothing_pending_times_out_empty(events):
    make, clock, collector, node = events
    e = make()
    t0 = time.monotonic()
    assert e.wait(0.05) == []
    assert time.monotonic() - t0 >= 0.04


@pytest.mark.parametrize("code", [errno.ENODEV, errno.EIO])
def test_a_lost_device_gives_a_key_reset_and_is_looked_for_again(
        sysfs, events, monkeypatch, code):
    make, clock, collector, node = events
    make_input(sysfs, "event2")
    e = make()
    e.wait(0)
    lost_fd = node.opened[0][1]
    real_read = os.read

    def read(fd, n):
        if fd == lost_fd:
            raise OSError(code, os.strerror(code))
        return real_read(fd, n)

    monkeypatch.setattr(P.os, "read", read)
    clock.t = 150.0
    collector.send(P.signal.SIGHUP)
    assert e.wait(0) == [P.Stop(int(P.signal.SIGHUP)), P.KeyReset(150.0)]
    assert not e.key_open
    assert e.next_retry() == 150.0
    with pytest.raises(OSError):
        os.fstat(lost_fd)       # closed
    monkeypatch.setattr(P.os, "read", real_read)
    assert e.wait(0) == []
    assert e.key_open and len(node.opened) == 2


def test_a_missing_key_is_looked_for_every_key_retry_s(sysfs, events, monkeypatch):
    make, clock, collector, node = events
    looks = []
    real = P.find_key_device
    monkeypatch.setattr(P, "find_key_device", lambda root: looks.append(clock.t) or real(root))
    e = make()
    for t in (100.0, 105.0, 109.9, 110.0, 115.0):
        clock.t = t
        assert e.wait(0) == []
    assert looks == [100.0, 110.0]
    assert e.next_retry() == 120.0
    make_input(sysfs, "event5")
    clock.t = 119.0
    e.wait(0)
    assert not e.key_open
    clock.t = 120.0
    e.wait(0)
    assert e.key_open and looks == [100.0, 110.0, 120.0]
    assert e.next_retry() is None


def test_a_key_that_cannot_be_opened_is_absent_and_logged_once(sysfs, events, caplog):
    make, clock, collector, node = events
    make_input(sysfs, "event2")
    failing = KeyNode(fail=OSError(errno.ENOTTY, "Inappropriate ioctl for device"))
    e = make(open_key=failing)
    with caplog.at_level(logging.ERROR):
        e.wait(0)
        clock.t += P.KEY_RETRY_S
        e.wait(0)
    assert not e.key_open
    assert e.next_retry() == clock.t + P.KEY_RETRY_S
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1


def test_with_the_key_off_it_is_never_looked_for(sysfs, events, monkeypatch):
    make, clock, collector, node = events
    make_input(sysfs, "event2")

    def never(root):
        raise AssertionError("looked for the key")

    monkeypatch.setattr(P, "find_key_device", never)
    e = make(key_enabled=False)
    for t in (100.0, 200.0, 10_000.0):
        clock.t = t
        assert e.wait(0) == []
    collector.send(P.signal.SIGTERM)
    assert e.wait(0) == [P.Stop(int(P.signal.SIGTERM))]
    assert not e.key_open and e.next_retry() is None and node.opened == []


def test_open_key_closes_the_node_if_the_clock_cannot_be_set(tmp_path, monkeypatch):
    path = tmp_path / "event0"
    path.write_bytes(b"")
    opened = []
    real_open = os.open

    def spy(p, flags, *a):
        fd = real_open(p, flags, *a)
        opened.append((fd, flags))
        return fd

    monkeypatch.setattr(P.os, "open", spy)
    with pytest.raises(OSError):
        P.open_key(str(path))           # a regular file takes no ioctl
    [(fd, flags)] = opened
    assert flags & os.O_NONBLOCK and flags & os.O_CLOEXEC
    assert flags & os.O_ACCMODE == os.O_RDONLY
    with pytest.raises(OSError):
        os.fstat(fd)


# ── Gestures ─────────────────────────────────────────────────────────────────

def run_gestures(script):
    """[(op, t)] → everything emitted, in order."""
    g = P.Gestures()
    out = []
    for op, t in script:
        if op == "reset":
            g.reset()
        else:
            out += getattr(g, op)(t)
    return out


@pytest.mark.parametrize("script, emitted", [
    ([("press", 0.0), ("release", 0.2)], [("tap", 0.0)]),
    ([("press", 0.0), ("release", 0.6)], [("tap", 0.0)]),
    ([("press", 0.0), ("release", 0.03)], [("tap", 0.0)]),
    ([("press", 0.0), ("release", 0.029)], []),             # noise
    ([("press", 0.0), ("release", 0.8)], []),               # between: nothing
    ([("press", 0.0), ("release", 1.0)], [("hold", 0.0)]),
    ([("press", 0.0), ("release", 1.5)], [("hold", 0.0)]),  # a hold seen late
    ([("press", 0.0), ("poll", 1.0), ("release", 1.5)], [("hold", 0.0)]),
    ([("press", 0.0), ("poll", 0.99), ("release", 1.5)], [("hold", 0.0)]),
    ([("press", 0.0), ("poll", 1.0), ("poll", 2.0), ("poll", 3.0)], [("hold", 0.0)]),
    ([("press", 0.0), ("press", 0.3), ("release", 0.5)], [("tap", 0.0)]),
    ([("release", 0.5)], []),
    ([("press", 0.0), ("release", 0.2), ("release", 0.3)], [("tap", 0.0)]),
    # Four edges read at once, as after a refresh: two taps.
    ([("press", 0.0), ("release", 0.1), ("press", 0.3), ("release", 0.4)],
     [("tap", 0.0), ("tap", 0.3)]),
    ([("press", 0.0), ("reset", 0.1), ("release", 0.2)], []),
])
def test_the_gestures_table(script, emitted):
    assert run_gestures(script) == emitted


def test_pressed_is_down_with_no_hold_yet():
    g = P.Gestures()
    assert not g.pressed and g.next_deadline() is None
    g.press(5.0)
    assert g.pressed and g.next_deadline() == 5.0 + P.HOLD_S
    assert g.poll(5.5) == []
    assert g.poll(6.0) == [("hold", 5.0)]
    assert not g.pressed and g.next_deadline() == 5.0 + P.STUCK_S
    assert g.release(7.0) == []
    assert not g.pressed and g.next_deadline() is None


@pytest.mark.parametrize("polls", [[10.0], [1.0, 10.0], [1.0, 5.0, 12.0]])
def test_a_key_down_for_stuck_s_is_forgotten(polls, caplog):
    g = P.Gestures()
    g.press(0.0)
    out = []
    with caplog.at_level(logging.WARNING):
        for t in polls:
            out += g.poll(t)
    assert out == [("hold", 0.0)]
    assert not g.pressed and not g.down and g.next_deadline() is None
    assert g.release(12.5) == []
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# ── Ui ───────────────────────────────────────────────────────────────────────

def tick(ui, now, gate_open=True, floor_at=0.0):
    return ui.tick(now, gate_open=gate_open, floor_at=floor_at)


def test_taps_cycle_the_views_and_queue_one_page():
    ui = P.Ui(P.TODAY, 0.0, 0)
    assert ui.tap(9.9, 10.0) == [P.Strip("now")]
    assert (ui.page_needed, ui.page_due, ui.last_key) == (True, 10.5, 10.0)
    assert ui.tap(10.1, 10.2) == [P.Strip("calendar")]
    assert ui.page_due == pytest.approx(10.7)
    assert ui.tap(10.3, 10.4) == [P.Strip("habits")]
    assert tick(ui, 10.8) == []
    assert ui.next_deadline(False) == pytest.approx(10.9)
    assert tick(ui, 10.95) == [P.Page("habits")]
    assert ui.page_due is None and ui.page_needed
    assert tick(ui, 11.0) == []         # never re-emitted
    assert ui.next_deadline(False) is None
    ui.painted_view("now")
    assert ui.page_needed
    ui.painted_view("habits")
    assert not ui.page_needed


def test_a_hold_asks_for_the_prompt_and_drops_the_page():
    ui = P.Ui("now", 0.0, 0)
    ui.tap(1.0, 1.1)
    assert ui.hold(2.0, 3.0) == [P.Prompt()]
    assert (ui.mode, ui.page_due, ui.last_key) == ("prompt_pending", None, 3.0)


def test_while_the_prompt_is_drawn_tap_hold_and_tick_are_ignored():
    ui = P.Ui("now", 0.0, 60)
    ui.hold(1.0, 2.0)
    for now in (2.5, 100.0, 1000.0):
        assert ui.tap(now - 0.1, now) == []
        assert ui.hold(now - 1, now) == []
        assert tick(ui, now) == []
        assert ui.mode == "prompt_pending" and ui.view == "now"
    assert ui.next_deadline(False) is None


def test_the_drawn_prompt_arms_for_prompt_s():
    ui = P.Ui("now", 0.0, 0)
    ui.hold(1.0, 2.0)
    assert ui.shown_prompt(4.5) == []
    assert (ui.mode, ui.prompt_shown_bt, ui.prompt_deadline) == ("prompt", 4.5, 14.5)
    assert ui.last_key == 4.5
    assert ui.next_deadline(False) == 14.5
    assert ui.next_deadline(True) is None


@pytest.mark.parametrize("page_needed, due", [(True, 7.0), (False, None)])
def test_a_prompt_that_was_not_drawn_goes_back_to_browse(page_needed, due):
    ui = P.Ui("now", 0.0, 0)
    if page_needed:
        ui.tap(0.5, 0.6)
    ui.hold(1.0, 2.0)
    assert ui.prompt_failed(7.0) == []
    assert (ui.mode, ui.page_due) == ("browse", due)


def _prompt(idle_s=0):
    ui = P.Ui("now", 0.0, idle_s)
    ui.hold(1.0, 2.0)
    ui.shown_prompt(4.5)
    return ui


@pytest.mark.parametrize("press_t, now", [
    (4.5, 4.7), (10.0, 10.2), (14.5, 14.6),
    (14.4, 15.4),       # pressed before the deadline, released after it
])
def test_a_tap_pressed_while_the_prompt_is_armed_confirms(press_t, now):
    ui = _prompt()
    assert ui.tap(press_t, now) == [P.Off()]
    assert ui.mode == "off"
    assert (ui.prompt_shown_bt, ui.prompt_deadline) == (None, None)
    assert ui.next_deadline(False) is None


@pytest.mark.parametrize("press_t, now", [(4.4, 4.6), (3.0, 4.8), (14.51, 14.7)])
def test_a_tap_pressed_outside_the_armed_window_is_ignored(press_t, now):
    ui = _prompt()
    assert ui.tap(press_t, now) == []
    assert ui.mode == "prompt"


def test_a_hold_in_the_prompt_is_ignored():
    ui = _prompt()
    assert ui.hold(5.0, 6.0) == []
    assert ui.mode == "prompt"


def test_the_prompt_times_out_back_to_browse():
    ui = _prompt()
    assert tick(ui, 14.4) == []
    assert tick(ui, 14.5) == [P.Leave("timeout")]
    assert (ui.mode, ui.prompt_shown_bt, ui.prompt_deadline, ui.last_key) == (
        "browse", None, None, 14.5)
    assert tick(ui, 20.0) == []


def test_off_ignores_everything_but_resume():
    ui = _prompt(idle_s=60)
    ui.tap(5.0, 5.2)
    for now in (6.0, 100.0, 1000.0):
        assert ui.tap(now - 0.1, now) == []
        assert ui.hold(now - 1, now) == []
        assert tick(ui, now) == []
        assert ui.shown_prompt(now) == [] and ui.prompt_failed(now) == []
        assert ui.mode == "off"
    assert ui.resume(1001.0) == [P.Leave("resume")]
    assert (ui.mode, ui.last_key) == ("browse", 1001.0)
    assert ui.resume(1002.0) == []


def test_a_failed_power_off_resumes_with_its_reason():
    ui = _prompt()
    ui.tap(5.0, 5.2)
    assert ui.resume(6.0, why="failed") == [P.Leave("failed")]


@pytest.mark.parametrize("page_needed, due", [(True, 30.0), (False, None)])
def test_after_a_leave_repaint_an_owed_page_is_due_at_once(page_needed, due):
    ui = P.Ui("now", 0.0, 0)
    if page_needed:
        ui.tap(0.5, 0.6)
    ui.hold(1.0, 2.0)
    ui.shown_prompt(4.5)
    tick(ui, 14.5)
    assert ui.leave_done(30.0) == []
    assert ui.page_due == due


def test_the_idle_return_needs_browse_no_page_the_gate_and_the_floor():
    ui = P.Ui("calendar", 0.0, 60)
    assert ui.next_deadline(False) == 60.0
    assert tick(ui, 59.9) == []
    assert tick(ui, 60.0, gate_open=False) == []
    assert ui.next_deadline(False) == P.CLOCK_SYNC_GRACE_S
    assert tick(ui, 60.0, floor_at=90.0) == []
    assert ui.next_deadline(False) == 90.0
    assert ui.next_deadline(True) is None
    assert tick(ui, 90.0, floor_at=90.0) == [P.Idle()]
    assert (ui.view, ui.last_key) == (P.TODAY, 90.0)
    assert ui.next_deadline(False) is None
    assert tick(ui, 1000.0) == []       # already on Today


def test_no_idle_return_while_a_page_is_due_or_a_prompt_is_up():
    ui = P.Ui("now", 0.0, 60)
    ui.tap(99.0, 100.0)                 # now calendar, page due at 100.5
    assert ui.next_deadline(False) == 100.5
    # Both are due by 160: the page comes first, and only then the idle return.
    assert tick(ui, 160.0) == [P.Page("calendar")]
    assert ui.next_deadline(False) == 160.0
    assert tick(ui, 160.0) == [P.Idle()]
    ui = P.Ui("now", 0.0, 60)
    ui.hold(1.0, 2.0)
    assert tick(ui, 500.0) == [] and ui.next_deadline(False) is None
    ui.shown_prompt(500.0)
    assert ui.next_deadline(False) == 510.0
    assert tick(ui, 509.0) == []


def test_every_key_event_restarts_the_idle_time():
    ui = P.Ui("now", 0.0, 60)
    ui.hold(10.0, 11.0)
    assert ui.last_key == 11.0
    ui.shown_prompt(13.0)
    assert ui.last_key == 13.0
    assert tick(ui, 23.0) == [P.Leave("timeout")]
    assert ui.last_key == 23.0
    assert tick(ui, 82.9) == []
    assert tick(ui, 83.0) == [P.Idle()]


def test_no_idle_return_when_it_is_off():
    ui = P.Ui("now", 0.0, 0)
    assert tick(ui, 1e6) == [] and ui.next_deadline(False) is None


# ── Ui: updating from the key ────────────────────────────────────────────────

def _offered(idle_s=0):
    """"Shut down?" with the update on offer: held at 1.0, drawn by 4.5,
    armed until 14.5."""
    ui = P.Ui("now", 0.0, idle_s)
    assert ui.hold(1.0, 2.0, offer_update=True) == [P.Prompt("confirm-update")]
    ui.shown_prompt(4.5)
    return ui


def _update_prompt():
    """"Update?", asked for at 6.0 and drawn by 9.0, armed until 19.0."""
    ui = _offered()
    assert ui.hold(5.0, 6.0) == [P.Prompt("update")]
    ui.shown_prompt(9.0)
    return ui


def _updating():
    ui = _update_prompt()
    assert ui.tap(10.0, 10.1) == [P.Update()]
    return ui


def test_a_hold_asks_for_the_prompt_the_offer_names():
    ui = P.Ui("now", 0.0, 0)
    assert ui.hold(2.0, 3.0) == [P.Prompt("confirm")] == [P.Prompt()]
    assert (ui.mode, ui.prompt_kind, ui.confirm_press_t) == ("prompt_pending", "confirm", 2.0)
    ui = P.Ui("now", 0.0, 0)
    ui.tap(1.0, 1.1)
    assert ui.hold(2.0, 3.0, offer_update=True) == [P.Prompt("confirm-update")]
    assert (ui.mode, ui.prompt_kind, ui.confirm_press_t) == (
        "prompt_pending", "confirm-update", 2.0)
    assert (ui.page_due, ui.last_key) == (None, 3.0)


@pytest.mark.parametrize("press_t", [
    1.01,       # just after the first hold's press
    3.0,        # while "Shut down?" was still being drawn
    4.5, 14.5,  # the armed window's edges
])
def test_a_second_hold_on_the_offered_prompt_asks_update(press_t):
    ui = _offered()
    assert ui.hold(press_t, 15.0) == [P.Prompt("update")]
    assert (ui.mode, ui.prompt_kind, ui.last_key) == ("prompt_pending", "update", 15.0)
    # "Shut down?" stays armed until "Update?" replaces it.
    assert (ui.prompt_shown_bt, ui.prompt_deadline) == (4.5, 14.5)


@pytest.mark.parametrize("press_t", [
    1.0,        # the first hold's own press: strictly after it, or nothing
    0.5, 14.51,
])
def test_a_second_hold_outside_its_window_is_ignored(press_t):
    ui = _offered()
    assert ui.hold(press_t, 15.0) == []
    assert (ui.mode, ui.prompt_kind) == ("prompt", "confirm-update")


def test_a_second_hold_on_plain_shut_down_or_on_update_does_nothing():
    ui = _prompt()
    assert ui.prompt_kind == "confirm"
    assert ui.hold(5.0, 6.0) == [] and ui.mode == "prompt"
    ui = _update_prompt()
    assert ui.hold(10.0, 11.0) == []
    assert (ui.mode, ui.prompt_kind) == ("prompt", "update")


def test_update_is_armed_for_prompt_s_from_its_own_draw():
    ui = _update_prompt()
    assert (ui.mode, ui.prompt_shown_bt, ui.prompt_deadline) == ("prompt", 9.0, 19.0)
    assert ui.last_key == 9.0
    assert ui.next_deadline(False) == 19.0


@pytest.mark.parametrize("press_t", [4.5, 14.5])
def test_a_tap_on_the_offered_prompt_still_shuts_down(press_t):
    ui = _offered()
    assert ui.tap(press_t, press_t + 0.1) == [P.Off()]
    assert (ui.mode, ui.prompt_kind, ui.confirm_press_t) == ("off", None, None)


@pytest.mark.parametrize("press_t, now", [(9.0, 9.1), (19.0, 19.1), (18.9, 19.9)])
def test_a_tap_on_update_inside_its_window_starts_updating(press_t, now):
    ui = _update_prompt()
    assert ui.tap(press_t, now) == [P.Update()]
    assert ui.mode == "updating"
    assert (ui.prompt_shown_bt, ui.prompt_deadline, ui.prompt_kind, ui.confirm_press_t) == (
        None, None, None, None)
    assert ui.next_deadline(False) is None


@pytest.mark.parametrize("press_t, now", [(8.99, 9.1), (7.0, 9.2), (19.01, 19.1)])
def test_a_tap_on_update_outside_its_window_is_ignored(press_t, now):
    ui = _update_prompt()
    assert ui.tap(press_t, now) == []
    assert (ui.mode, ui.prompt_kind) == ("prompt", "update")


def test_update_times_out_back_to_browse_and_forgets_both_prompts():
    ui = _update_prompt()
    assert tick(ui, 18.9) == []
    assert tick(ui, 19.0) == [P.Leave("timeout")]
    assert (ui.mode, ui.prompt_kind, ui.confirm_press_t, ui.prompt_deadline) == (
        "browse", None, None, None)


def test_an_update_prompt_that_was_not_drawn_leaves_shut_down_armed():
    ui = _offered()
    ui.hold(5.0, 6.0)
    assert ui.prompt_failed(7.0) == []
    assert (ui.mode, ui.prompt_kind) == ("prompt", "confirm-update")
    assert (ui.prompt_shown_bt, ui.prompt_deadline) == (4.5, 14.5)
    assert ui.hold(8.0, 9.0) == [P.Prompt("update")]     # a hold still asks for it
    ui.prompt_failed(9.5)
    assert ui.tap(10.0, 10.1) == [P.Off()]               # and a tap still shuts down


def test_shut_down_left_armed_by_a_failed_update_prompt_still_times_out():
    ui = _offered()
    ui.hold(5.0, 6.0)
    ui.prompt_failed(7.0)
    assert tick(ui, 14.4) == []
    assert tick(ui, 14.5) == [P.Leave("timeout")]


def test_an_offered_prompt_that_was_not_drawn_goes_back_to_browse():
    ui = P.Ui("now", 0.0, 0)
    ui.hold(1.0, 2.0, offer_update=True)
    assert ui.prompt_failed(3.0) == []
    assert (ui.mode, ui.prompt_kind, ui.confirm_press_t) == ("browse", None, None)


def test_while_updating_only_the_outcome_counts():
    ui = _updating()
    for now in (12.0, 100.0, 5000.0):
        assert ui.tap(now - 0.1, now) == []
        assert ui.hold(now - 1, now) == []
        assert tick(ui, now) == []
        assert ui.shown_prompt(now) == [] and ui.prompt_failed(now) == []
        assert ui.shown_notice(now) == [] and ui.notice_skipped(now) == []
        assert ui.resume(now) == []
        assert ui.mode == "updating"
        assert ui.next_deadline(False) is None
    assert ui.update_done("updated", 5001.0) == [P.Notice("updated")]
    assert (ui.mode, ui.notice_shown_bt, ui.notice_deadline) == ("notice", None, None)
    assert ui.update_done("updated", 5002.0) == []


def test_awaiting_update_is_updating_with_no_page_due():
    ui = P.Ui("now", 0.0, 60)
    ui.tap(1.0, 1.1)
    assert ui.awaiting_update() == []
    assert (ui.mode, ui.page_due) == ("updating", None)
    assert ui.update_done("up-to-date", 2.0) == [P.Notice("up-to-date")]


@pytest.mark.parametrize("make", [lambda: P.Ui("now", 0.0, 0), _prompt, _offered,
                                  _update_prompt])
def test_an_outcome_outside_updating_is_ignored(make):
    ui = make()
    mode = ui.mode
    assert ui.update_done("updated", 30.0) == []
    assert ui.shown_notice(30.0) == [] and ui.notice_skipped(30.0) == []
    assert ui.mode == mode and ui.notice_deadline is None


def _notice():
    ui = _updating()
    ui.update_done("updated", 50.0)
    return ui


def test_a_notice_waits_for_its_draw_before_anything_ends_it():
    ui = _notice()
    assert ui.tap(50.5, 50.6) == []
    assert ui.hold(50.5, 51.0) == []
    assert tick(ui, 1e6) == []
    assert ui.next_deadline(False) is None and ui.mode == "notice"


def test_a_drawn_notice_ends_after_notice_s():
    ui = _notice()
    assert ui.shown_notice(53.0) == []
    assert (ui.notice_shown_bt, ui.notice_deadline, ui.last_key) == (
        53.0, 53.0 + P.NOTICE_S, 53.0)
    assert ui.next_deadline(False) == 53.0 + P.NOTICE_S
    assert ui.next_deadline(True) is None
    assert tick(ui, 53.0 + P.NOTICE_S - 0.1) == []
    assert tick(ui, 53.0 + P.NOTICE_S) == [P.Leave("notice")]
    assert (ui.mode, ui.notice_shown_bt, ui.notice_deadline, ui.last_key) == (
        "browse", None, None, 53.0 + P.NOTICE_S)
    assert tick(ui, 200.0) == []


@pytest.mark.parametrize("press_t, ends", [(52.9, False), (53.0, True), (60.0, True)])
def test_a_tap_pressed_once_the_notice_is_drawn_ends_it(press_t, ends):
    ui = _notice()
    ui.shown_notice(53.0)
    got = ui.tap(press_t, press_t + 0.1)
    if ends:
        assert got == [P.Leave("notice")]
        assert (ui.mode, ui.notice_deadline, ui.last_key) == ("browse", None, press_t + 0.1)
    else:
        assert got == [] and ui.mode == "notice"


def test_a_hold_during_a_notice_does_nothing():
    ui = _notice()
    ui.shown_notice(53.0)
    assert ui.hold(55.0, 56.0) == []
    assert ui.mode == "notice" and ui.notice_deadline == 53.0 + P.NOTICE_S


def test_a_notice_that_cannot_be_drawn_goes_back_at_once():
    ui = _notice()
    assert ui.notice_skipped(51.0) == [P.Leave("notice")]
    assert (ui.mode, ui.last_key, ui.notice_shown_bt) == ("browse", 51.0, None)
    assert ui.notice_skipped(52.0) == []


# ── the key's budget ─────────────────────────────────────────────────────────

def test_the_bucket_refills_one_token_per_key_refill_s_and_keeps_the_rest():
    b = P.Bucket(0, 100.0)
    b.refill(149.9)
    assert b.tokens == 0 and b.next_at(1) == 150.0
    b.refill(150.0)
    assert b.tokens == 1
    b.refill(260.0)                     # two more, and 10 s toward the next
    assert b.tokens == 3
    assert b.next_at(4) == 300.0 and b.next_at(6) == 400.0
    b.refill(300.0)
    assert b.tokens == 4


def test_the_bucket_is_capped_and_a_full_bucket_banks_no_time():
    b = P.Bucket(11, 0.0)
    b.refill(10_000.0)
    assert b.tokens == P.KEY_BURST
    assert b.take()
    assert b.tokens == 11 and b.next_at(12) == 10_050.0
    b.refill(10_049.0)
    assert b.tokens == 11
    b.refill(10_050.0)
    assert b.tokens == 12
    b.give(5)
    assert b.tokens == P.KEY_BURST
    assert P.Bucket(50, 0.0).tokens == P.KEY_BURST


def test_a_bucket_that_stays_full_banks_no_time():
    b = P.Bucket(P.KEY_BURST, 0.0)
    b.refill(10_000.0)
    assert b.take()
    b.refill(10_001.0)
    assert b.tokens == P.KEY_BURST - 1 and b.next_at(P.KEY_BURST) == 10_050.0


def test_take_and_give():
    b = P.Bucket(2, 0.0)
    assert b.take(2) and b.tokens == 0
    assert not b.take() and b.tokens == 0
    b.give()
    assert b.tokens == 1
    assert not b.take(2) and b.tokens == 1
    assert b.next_at(1) == 0.0          # already there
    with pytest.raises(ValueError):
        b.next_at(P.KEY_BURST + 1)


@pytest.mark.parametrize("state, start, tokens", [
    (P.State(), 1000.0, 12),                                        # no record
    # a crash mid-refresh 10 s ago: counted from the attempt, not a full bucket
    (P.State(complete=False, attempt_start_bt=990.0), 1000.0, 0),
    (P.State(complete=True, painted_end_bt=5000.0), 1000.0, 12),    # an earlier boot
    (P.State(complete=True, painted_end_bt=990.0), 1000.0, 0),      # a crash loop
    (P.State(complete=True, painted_end_bt=875.0), 1000.0, 2),
    (P.State(complete=True, painted_end_bt=1000.0), 1000.0, 0),
    (P.State(complete=True, painted_end_bt=0.0), 100_000.0, 12),
])
def test_start_tokens(state, start, tokens):
    assert P.start_tokens(state, start) == tokens


# ── the power-off request and the screen cache ───────────────────────────────

def test_request_poweroff_writes_the_request_once(tmp_path):
    assert P.request_poweroff(str(tmp_path), 1234.5678) == "ok"
    path = tmp_path / P.POWEROFF_NAME
    assert path.read_text() == "1234.568\n"
    assert path.stat().st_mode & 0o777 == 0o600
    assert P.request_poweroff(str(tmp_path), 99.0) == "ok"     # EEXIST
    assert path.read_text() == "1234.568\n"


@pytest.mark.parametrize("which", ["none", "missing", "file", "not-writable"])
def test_request_poweroff_needs_a_writable_run_directory(tmp_path, monkeypatch, which):
    run_dir = {"none": None, "missing": str(tmp_path / "missing"),
               "file": str(tmp_path / "f"), "not-writable": str(tmp_path)}[which]
    (tmp_path / "f").write_text("")
    if which == "not-writable":
        monkeypatch.setattr(P.os, "access", lambda p, mode: False)
    assert P.request_poweroff(run_dir, 1.0) == "failed: no run directory"
    assert not (tmp_path / P.POWEROFF_NAME).exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write a read-only directory")
def test_request_poweroff_in_a_read_only_directory_fails(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o500)
    try:
        assert P.request_poweroff(str(run_dir), 1.0) == "failed: no run directory"
    finally:
        run_dir.chmod(0o700)


def test_request_poweroff_names_any_other_error(tmp_path, monkeypatch):
    def refuse(path, *a):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(P.os, "open", refuse)
    assert P.request_poweroff(str(tmp_path), 1.0) == "failed: EACCES"


def test_clear_poweroff(tmp_path, caplog):
    (tmp_path / P.POWEROFF_NAME).write_text("1.000\n")
    P.clear_poweroff(str(tmp_path))
    assert not (tmp_path / P.POWEROFF_NAME).exists()
    P.clear_poweroff(str(tmp_path))     # already gone
    P.clear_poweroff(None)
    (tmp_path / P.POWEROFF_NAME).mkdir()
    with caplog.at_level(logging.ERROR):
        P.clear_poweroff(str(tmp_path))
    assert any(r.levelno == logging.ERROR for r in caplog.records)


# ── the update request and its result ────────────────────────────────────────

def test_request_update_writes_the_request_once(tmp_path):
    assert P.request_update(str(tmp_path), "413.320") == "ok"
    path = tmp_path / P.UPDATE_NAME
    assert path.read_text() == "413.320\n"
    assert path.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / (P.UPDATE_NAME + ".tmp")).exists()
    assert P.request_update(str(tmp_path), "999.000") == "ok"     # one is already out
    assert path.read_text() == "413.320\n"
    assert not (tmp_path / (P.UPDATE_NAME + ".tmp")).exists()


def test_request_update_links_a_complete_file_into_place(tmp_path, monkeypatch):
    """F6: the path unit starts the updater the moment the name exists, so the
    name must arrive with the id already in it."""
    linked = []
    real_link = os.link

    def link(src, dst, *a, **kw):
        with open(src, "rb") as f:
            linked.append((src, dst, f.read(), os.path.lexists(dst)))
        return real_link(src, dst, *a, **kw)

    monkeypatch.setattr(P.os, "link", link)
    assert P.request_update(str(tmp_path), "413.320") == "ok"
    path = str(tmp_path / P.UPDATE_NAME)
    assert linked == [(path + ".tmp", path, b"413.320\n", False)]
    assert (tmp_path / P.UPDATE_NAME).read_text() == "413.320\n"


@pytest.mark.parametrize("which", ["none", "missing", "file", "not-writable"])
def test_request_update_needs_a_writable_run_directory(tmp_path, monkeypatch, which):
    run_dir = {"none": None, "missing": str(tmp_path / "missing"),
               "file": str(tmp_path / "f"), "not-writable": str(tmp_path)}[which]
    (tmp_path / "f").write_text("")
    if which == "not-writable":
        monkeypatch.setattr(P.os, "access", lambda p, mode: False)
    assert P.request_update(run_dir, "1.000") == "failed: no run directory"
    assert not (tmp_path / P.UPDATE_NAME).exists()


def test_request_update_names_any_other_error_and_leaves_no_temp_file(tmp_path, monkeypatch):
    def refuse(src, dst, *a, **kw):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(P.os, "link", refuse)
    assert P.request_update(str(tmp_path), "1.000") == "failed: EACCES"
    assert sorted(os.listdir(tmp_path)) == []


def test_request_update_never_writes_through_a_symlink(tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("untouched\n")
    (tmp_path / (P.UPDATE_NAME + ".tmp")).symlink_to(target)
    assert P.request_update(str(tmp_path), "1.000") == "failed: ELOOP"
    assert target.read_text() == "untouched\n"
    assert not (tmp_path / P.UPDATE_NAME).exists()


def test_clear_update(tmp_path, caplog):
    (tmp_path / P.UPDATE_NAME).write_text("1.000\n")
    (tmp_path / (P.UPDATE_NAME + ".tmp")).write_text("1.000\n")
    P.clear_update(str(tmp_path))
    assert os.listdir(tmp_path) == []
    P.clear_update(str(tmp_path))       # already gone
    P.clear_update(None)
    (tmp_path / P.UPDATE_NAME).mkdir()
    with caplog.at_level(logging.ERROR):
        P.clear_update(str(tmp_path))
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def _result(tmp_path, raw: bytes) -> str:
    path = tmp_path / "result"
    path.write_bytes(raw)
    return str(path)


@pytest.mark.parametrize("state", ["running", *P.NOTICES])
def test_read_update_result_reads_the_updaters_line(tmp_path, state):
    path = _result(tmp_path, f"413.320 1234567890.125 {state}\n".encode())
    assert P.read_update_result(path) == P.UpdateResult("413.320", 1234567890.125, state)


def test_no_result_is_none_and_says_nothing(tmp_path, caplog):
    with caplog.at_level(logging.DEBUG, logger="smylte-panel"):
        assert P.read_update_result(str(tmp_path / "result")) is None
    assert caplog.records == []


def test_a_result_behind_a_symlink_is_not_read(tmp_path):
    good = _result(tmp_path, b"413.320 420.000 updated\n")
    (tmp_path / "link").symlink_to(good)
    assert P.read_update_result(str(tmp_path / "link")) is None


def test_a_result_that_is_a_fifo_is_not_read_and_does_not_block(tmp_path):
    fifo = tmp_path / "result"
    os.mkfifo(fifo)
    got = []
    t = threading.Thread(target=lambda: got.append(P.read_update_result(str(fifo))),
                         daemon=True)
    t.start()
    t.join(timeout=5)
    assert not t.is_alive(), "read_update_result blocked on a FIFO"
    assert got == [None]


def test_a_result_that_is_a_directory_is_not_read(tmp_path):
    (tmp_path / "result").mkdir()
    assert P.read_update_result(str(tmp_path / "result")) is None


@pytest.mark.parametrize("raw", [
    b"",
    b"413.320 420.000 updated",                     # no newline
    b"413.320 420.000 updated\n" + b" " * 80,       # oversized
    b"413.320 420.000 updated\n\n",
    b"413.320 420.000 updated\r\n",
    b" 413.320 420.000 updated\n",
    b"413.320  420.000 updated\n",
    b"413.32 420.000 updated\n",                    # rid: three decimals
    b"413 420.000 updated\n",
    b"12345678901.320 420.000 updated\n",           # rid: at most ten digits
    b"-13.320 420.000 updated\n",
    b"413.320 420.0 updated\n",                     # at: three decimals
    b"413.320 420 updated\n",
    b"413.320 12345678901.000 updated\n",
    b"413.320 4e2.000 updated\n",
    b"413.320 420.000 done\n",                      # state: one of four
    b"413.320 420.000 Updated\n",
    b"413.320 420.000\n",
    b"413.320\n",
    "٤١٣.٣٢٠ 420.000 updated\n".encode(),           # not ASCII digits
    b"413.320 420.000 updated\xff\n",
])
def test_a_result_that_is_not_exactly_the_updaters_line_is_none(tmp_path, raw):
    assert P.read_update_result(_result(tmp_path, raw)) is None


def test_update_present(tmp_path):
    assert P.update_present(str(tmp_path / "smylte-panel-update.path")) is False
    (tmp_path / "smylte-panel-update.path").write_text("[Path]\n")
    assert P.update_present(str(tmp_path / "smylte-panel-update.path")) is True


def test_a_screen_round_trips_in_its_exact_format(tmp_path):
    body = frame(9)
    assert P.save_screen(tmp_path, "confirm", body)
    raw = (tmp_path / "confirm.bin").read_bytes()
    assert raw == body + b"\n" + hashlib.sha256(body).hexdigest().encode() + b"\n"
    assert (tmp_path / "confirm.bin").stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "confirm.bin.tmp").exists()
    assert P.load_screen(tmp_path, "confirm") == body
    assert P.load_screen(tmp_path, "off") is None


GOOD_SCREEN = frame(9) + b"\n" + hashlib.sha256(frame(9)).hexdigest().encode() + b"\n"


@pytest.mark.parametrize("raw", [
    b"",
    GOOD_SCREEN[:-1],
    GOOD_SCREEN + b"\n",
    frame(8) + GOOD_SCREEN[P.BUF_BYTES:],
    GOOD_SCREEN.replace(b"\n", b" ", 1),
    GOOD_SCREEN[:-1] + b" ",
    GOOD_SCREEN[:P.BUF_BYTES + 1] + GOOD_SCREEN[P.BUF_BYTES + 1:-1].upper() + b"\n",
    GOOD_SCREEN[:-2] + b"\xff\n",
])
def test_a_screen_file_that_is_not_exactly_right_is_no_screen(tmp_path, raw):
    (tmp_path / "off.bin").write_bytes(raw)
    assert P.load_screen(tmp_path, "off") is None


def test_save_screen_reports_a_failure(tmp_path):
    assert P.save_screen(tmp_path / "missing", "off", frame(1)) is False


def test_logind_dropin_present(tmp_path):
    assert P.logind_dropin_present(str(tmp_path / "50-smylte-panel.conf")) is False
    (tmp_path / "50-smylte-panel.conf").write_text("[Login]\n")
    assert P.logind_dropin_present(str(tmp_path / "50-smylte-panel.conf")) is True


# ── --reset-refresh and --keytest ────────────────────────────────────────────

def test_reset_refresh_clears_only_the_batch_guards_verdict(
        valid_env, monkeypatch, no_driver, guarded_main, caplog):
    monkeypatch.setattr(P.os, "geteuid", lambda: 1000)
    state_dir = valid_env.parent / "state"
    assert PREV.quick_disabled is True
    assert P.save_state(state_dir, PREV)
    with caplog.at_level(logging.INFO):
        assert guarded_main(["--reset-refresh"]) == 0
    assert P.load_state(state_dir) == dataclasses.replace(PREV, quick_disabled=False)
    assert no_driver == []


def test_reset_refresh_with_no_state_file_changes_nothing(
        valid_env, monkeypatch, no_driver, guarded_main):
    monkeypatch.setattr(P.os, "geteuid", lambda: 1000)
    assert guarded_main(["--reset-refresh"]) == 0
    assert not (valid_env.parent / "state" / P.STATE_FILE).exists()
    assert no_driver == []


def test_reset_refresh_needs_the_state_directory(
        valid_env, monkeypatch, no_driver, guarded_main):
    monkeypatch.setattr(P.os, "geteuid", lambda: 1000)
    monkeypatch.delenv("STATE_DIRECTORY")
    assert guarded_main(["--reset-refresh"]) == 78
    assert no_driver == []


def test_keytest_prints_what_the_key_does(monkeypatch, no_driver, guarded_main, capsys):
    r, w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    monkeypatch.setattr(P, "find_key_device", lambda root: "/dev/input/event7")
    monkeypatch.setattr(P, "open_key", lambda path: r)
    monkeypatch.setattr(P, "KEYTEST_S", 1.0)

    def press_and_release():
        os.write(w, key(P.boottime(), 1) + ev(P.boottime(), P.EV_SYN, SYN, 0))
        time.sleep(0.2)
        os.write(w, key(P.boottime(), 0) + ev(P.boottime(), P.EV_SYN, SYN, 0))

    t = threading.Thread(target=press_and_release)
    t.start()
    try:
        assert guarded_main(["--keytest"]) == 0
    finally:
        t.join()
        os.close(w)
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("/dev/input/event7")
    assert out[1] == "press"
    assert re.fullmatch(r"release after 0\.[12]\d s → tap", out[2]), out
    assert len(out) == 3
    assert no_driver == []
    with pytest.raises(OSError):
        os.fstat(r)     # closed on the way out


def test_keytest_says_let_go_at_a_hold(monkeypatch, guarded_main, capsys):
    r, w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    monkeypatch.setattr(P, "find_key_device", lambda root: "/dev/input/event7")
    monkeypatch.setattr(P, "open_key", lambda path: r)
    monkeypatch.setattr(P, "KEYTEST_S", 2.0)

    def hold():
        os.write(w, key(P.boottime(), 1))
        time.sleep(P.HOLD_S + 0.2)
        os.write(w, key(P.boottime(), 0))

    t = threading.Thread(target=hold)
    t.start()
    try:
        assert guarded_main(["--keytest"]) == 0
    finally:
        t.join()
        os.close(w)
    out = capsys.readouterr().out.splitlines()
    assert out[1:3] == ["press", "let go now"]
    assert re.fullmatch(r"release after 1\.\d\d s → hold", out[3]), out


def test_keytest_without_a_key_device_says_so(monkeypatch, guarded_main, capsys):
    monkeypatch.setattr(P, "find_key_device", lambda root: None)

    def never(path):
        raise AssertionError("opened a key")

    monkeypatch.setattr(P, "open_key", never)
    assert guarded_main(["--keytest"]) == 1
    assert capsys.readouterr().out == "no pwr_button input device (is gpio_keys loaded?)\n"


def test_the_usage_names_every_command(guarded_main, no_driver, capsys):
    assert guarded_main(["--bogus"]) == 2
    err = capsys.readouterr().err
    for cmd in ("--selftest", "--clear", "--power-off", "--keytest", "--reset-refresh"):
        assert cmd in err


def test_a_crash_mid_refresh_restarts_with_a_nearly_empty_bucket():
    """The write-ahead record of a refresh that never finished is incomplete;
    the bucket must still count from it, or a crash loop would start full."""
    s = P.State(attempt_start_bt=1000.0, complete=False, painted_end_bt=500.0)
    assert P.start_tokens(s, 1000.0 + P.PAINT_MAX_S + 60) == 1
    assert P.start_tokens(s, 1000.0 + 5) == 0


def test_an_unfinished_attempt_from_an_earlier_boot_gives_a_full_bucket():
    s = P.State(attempt_start_bt=50_000.0, complete=False)
    assert P.start_tokens(s, 400.0) == P.KEY_BURST


@pytest.mark.parametrize("raw", ["\u00b2", "1\u00b2", "018x", "123"])
def test_a_pwr_pin_that_is_not_plain_ascii_digits_is_a_config_error(monkeypatch, raw):
    monkeypatch.setenv(P.PWR_PIN_ENV, raw)
    with pytest.raises(P.ConfigError):
        P.pwr_pin_from_env()
