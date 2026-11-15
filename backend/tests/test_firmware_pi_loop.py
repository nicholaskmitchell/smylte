"""The Pi panel client's service loop, held to the promises panel.py makes.

`firmware/pi_epaper_7in5/panel.py` promises the glass at least 180 s between
refreshes, across restarts, crash loops and reboots; a refresh that a stop
never interrupts; a write-ahead record on disk before the panel is touched; a
repaint at least every 23 hours; and a token that never reaches a log. None of
that can be seen on a CI runner with no panel, so this file runs the REAL
`run()`, `clear()` and `main()` on fakes: a scripted fetch, a fake panel whose
calls cost fake time, and a waiter that advances a fake CLOCK_BOOTTIME instead
of sleeping. Nothing here waits for real, touches hardware or the network, or
imports gpiod, spidev or Waveshare's code.

The floor is the one promise a bug would break silently and expensively (the
glass wears out, nothing logs), so it is checked over hundreds of cycles, from
every kind of state file, and at the level of `floor_ok_at()` itself.
"""
from __future__ import annotations

import collections
import contextlib
import dataclasses
import errno
import hashlib
import importlib.util
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import types

import pytest

import pi_panel_fakes as F

P = F.load_panel()
E = F.load_driver()

INIT_COST = 0.2
DISPLAY_COST = 4.0
FAST_COST = 2.5
PARTIAL_COST = 1.0
SLEEP_COST = 0.5
PAINT_COST = INIT_COST + DISPLAY_COST + SLEEP_COST
TOKEN = "Ab" + "c" * 41     # 43 characters, as secrets.token_urlsafe(32)


# ── harness ──────────────────────────────────────────────────────────────────

class Clock:
    """CLOCK_BOOTTIME seconds, and a wall clock that follows it."""

    def __init__(self, t: float = 1000.0, wall_offset: float = 1.7e9):
        self.t = float(t)
        self.wall_offset = wall_offset
        self.synced = True

    def boottime(self) -> float:
        return self.t

    def walltime(self) -> float:
        return self.wall_offset + self.t

    def synced_fn(self) -> bool:
        return self.synced


class FakePanel:
    """Stands in for epd.Panel: records each call, and each call costs time.

    The refresh costs by mode, and the BUSY time each reports as
    `last_refresh_s` (the batch guard's input), are the critique's model's.
    """

    COSTS = {"init": INIT_COST, "display": DISPLAY_COST, "sleep": SLEEP_COST}
    DISPLAY_COSTS = {"full": DISPLAY_COST, "fast": FAST_COST, "partial": PARTIAL_COST}
    REFRESH_S = {"full": 3.9, "fast": 1.6, "partial": 0.4}
    PHASES = {"init": "init", "display": "refresh", "sleep": "power-off"}

    def __init__(self, clock: Clock, fail: dict | None = None,
                 refresh_s: dict | None = None):
        self.clock = clock
        self.fail = dict(fail or {})
        self.refresh_s = {**self.REFRESH_S, **(refresh_s or {})}
        self.calls: list[tuple] = []
        self.modes: list[str] = []
        self.drawn: list[tuple[str, bytes | None, bytes]] = []    # (mode, old, new)
        self.glass: bytes | None = None
        self.last_refresh_s: float | None = None
        self.phase = "idle"
        self.aborted_in = None

    def _step(self, name: str, extra=None, cost=None) -> None:
        if name in self.PHASES:
            self.phase = self.PHASES[name]
        self.calls.append((name, self.clock.t, extra))
        if name in self.fail:
            raise self.fail[name]
        self.clock.t += self.COSTS.get(name, 0.0) if cost is None else cost

    def init(self, mode: str = "full") -> None:
        self.modes.append(mode)
        self._step("init")

    def _refresh(self, old, new) -> None:
        mode = self.modes[-1] if self.modes else "full"
        self._step("display", hashlib.sha256(new).hexdigest(), self.DISPLAY_COSTS[mode])
        self.drawn.append((mode, old, new))
        self.glass = new
        self.last_refresh_s = self.refresh_s[mode]

    def display(self, frame: bytes) -> None:
        self._refresh(None, frame)

    def display_partial(self, old: bytes, new: bytes) -> None:
        self._refresh(old, new)

    def sleep(self) -> None:
        self._step("sleep")

    def abort(self, busy_stuck: bool = False) -> None:
        # As epd.Panel: remember where it failed, then power down to "off".
        self.aborted_in = self.phase
        self._step("abort", busy_stuck)
        self.phase = "off"

    def close(self) -> None:
        self._step("close")

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def paints(self) -> list[tuple[float, float]]:
        """(init_t, sleep_end_t) for each completed init→display→sleep."""
        out = []
        for a, b, c in zip(self.calls, self.calls[1:], self.calls[2:]):
            if (a[0], b[0], c[0]) == ("init", "display", "sleep"):
                out.append((a[1], c[1] + SLEEP_COST))
        return out

    def displayed(self) -> list[str]:
        return [c[2] for c in self.calls if c[0] == "display"]


Fetch = collections.namedtuple("Fetch", "t etag mode tabs screen")
Painted = collections.namedtuple("Painted", "purpose kind t0 t1 frame exempt tokens")


class FakeEvents:
    """Deps.events on the fake clock: scheduled signals and key edges.

    A positive wait advances the clock to the earlier of its timeout and the
    next scheduled item, and returns every item due by then, in time order; a
    wait of 0 returns what is already due and does not advance. A loop that
    keeps waiting 0 with nothing happening in between is spinning, and fails.
    """

    SPIN_LIMIT = 20

    def __init__(self, h: "Harness", keys=(), key_open: bool = False):
        self.h = h
        self.pending: list[tuple[float, int, object]] = []
        self._seq = 0
        for t, value in keys:
            self.schedule(t, P.Key(value, t))
        self.key_open = key_open or bool(keys)
        self.is_alive = True
        self.empty_zero = 0
        self._activity = None

    def schedule(self, t: float, item) -> None:
        self.pending.append((t, self._seq, item))
        self._seq += 1
        self.pending.sort(key=lambda p: (p[0], p[1]))

    def _take_signals(self) -> None:
        # Tests (and responders) append (t, signo) to h.signals at any time.
        while self.h.signals:
            t, signo = self.h.signals.pop(0)
            self.schedule(t, P.Repaint() if signo == signal.SIGUSR1 else P.Stop(signo))

    def _due(self) -> list:
        out = []
        while self.pending and self.pending[0][0] <= self.h.clock.t:
            t, _, item = self.pending.pop(0)
            if callable(item):
                item()          # a test's poke at the runner, at its time
                continue
            if isinstance(item, P.Stop) and self.h.stop_seen is None:
                self.h.stop_seen = t
            out.append(item)
        return out

    def wait(self, timeout: float) -> list:
        h = self.h
        h.waits.append(timeout)
        self._take_signals()
        if timeout > 0:
            h.unwaited = 0
            self._watch_glass(timeout)
            if self.pending and self.pending[0][0] <= h.clock.t + timeout:
                h.clock.t = max(h.clock.t, self.pending[0][0])
            elif h.stop_after is not None and len(h.requests) >= h.stop_after:
                # Only a real wait ends the run: wait(0) is a drain.
                if h.stop_seen is None:
                    h.stop_seen = h.clock.t
                return self._due() + [P.Stop(signal.SIGTERM)]
            else:
                h.clock.t += timeout
        got = self._due()
        activity = (len(h.requests), len(h.panel.calls))
        if timeout > 0 or got or activity != self._activity:
            self.empty_zero = 0
        else:
            self.empty_zero += 1
            assert self.empty_zero <= self.SPIN_LIMIT, (
                f"spinning: {self.empty_zero} empty zero-timeout waits in a row "
                f"at t={h.clock.t}")
        self._activity = activity
        return got

    def _watch_glass(self, timeout: float) -> None:
        """A prompt or the off screen this process drew, still on the glass
        while Ui is back in browse, is stale."""
        r = self.h.runner
        if r is not None and r.ui.mode == "browse" and self.h.panel.glass in SCREEN_FRAMES:
            self.h.stale.append((self.h.clock.t, timeout))

    def next_retry(self):
        return None

    def alive(self) -> bool:
        return self.is_alive


class RecordingRunner(P._Runner):
    """The real runner, with each refresh's purpose recorded for the checks."""

    def __init__(self, d, h: "Harness"):
        self.h = h
        super().__init__(d)

    def _draw(self, frame, *, purpose, kind, **kw):
        t0 = self.d.boottime()
        tokens = self._tokens(t0) if purpose in ("strip", "page") else None
        exempt = self.exempt_first_view
        end = super()._draw(frame, purpose=purpose, kind=kind, **kw)
        if end is not None:
            self.h.painted.append(Painted(purpose, kind, t0, end, frame, exempt, tokens))
        return end


class FakeUpdater:
    """The root updater, as the client sees it: the request it is sent, and
    the result line it leaves.

    `script(now, requests)` is the updater: from the fake time and the
    requests so far, as (t, rid), it gives what the result file holds, an
    UpdateResult, a raw line (str) or None for no file. Each read writes that
    to a real file in the updater's own format and reads it back with the
    client's read_update_result(), so every timeline goes through the real
    reader.
    """

    def __init__(self, clock: Clock, path, script=None, request="ok"):
        self.clock = clock
        self.path = path
        self.script = script or (lambda now, requests: None)
        self.request = request
        self.requests: list[tuple[float, str]] = []
        self.cleared: list[float] = []
        self.reads: list[float] = []

    def request_update(self, rid):
        self.requests.append((self.clock.t, rid))
        return self.request

    def clear_update(self):
        self.cleared.append(self.clock.t)

    def update_result(self):
        self.reads.append(self.clock.t)
        got = self.script(self.clock.t, list(self.requests))
        if got is None:
            self.path.unlink(missing_ok=True)
        else:
            self.path.write_text(got if isinstance(got, str)
                                 else f"{got.rid} {got.at:.3f} {got.state}\n")
        return P.read_update_result(str(self.path))


class Harness:
    """P.Deps on fakes: a scripted fetch and Events that advance the clock.

    `responder(n, sent, clock)` is an old-style responder: a server that knows
    nothing of views. A view or screen fetch to it is refused as an old server
    would be. `server(n, sent, clock, mode, tabs, screen)` answers every fetch.
    The key is off unless a test says otherwise, so the routine loop runs as
    it did before the key existed. `update` is the FakeUpdater's script, and
    `update_request` what its request answers.
    """

    def __init__(self, tmp_path, clock: Clock, responder=None, *, server=None, panel=None,
                 stop_after=None, signals=(), keys=(), key_open=False, poweroff="ok",
                 path_unit=True, update=None, update_request="ok", **deps):
        self.clock = clock
        self.responder = responder
        self.server = server
        self.panel = panel or FakePanel(clock)
        self.stop_after = stop_after
        self.signals = list(signals)
        self.requests: list[Fetch] = []
        self.notes: list[str] = []
        self.unwaited = 0       # fetches since the last real wait
        self.waits: list[float] = []
        self.painted: list[Painted] = []
        self.stale: list[tuple[float, float]] = []
        self.stop_seen: float | None = None
        self.poweroff = poweroff
        self.path_unit = path_unit
        self.poweroffs: list[tuple[float, str]] = []
        self.cleared: list[float] = []
        self.keys = list(keys)
        self.runner = None
        self.events = FakeEvents(self, keys, key_open)
        self.updater = FakeUpdater(clock, tmp_path / "update-result", update, update_request)
        deps.setdefault("key", "off")
        self.deps = P.Deps(state_dir=tmp_path, panel=self.panel, epd=E,
                           fetch=self.fetch, events=self.events,
                           boottime=clock.boottime, walltime=clock.walltime,
                           synced=clock.synced_fn, notify=self.notify,
                           request_poweroff=self.request_poweroff,
                           clear_poweroff=lambda: self.cleared.append(clock.t),
                           request_update=self.updater.request_update,
                           clear_update=self.updater.clear_update,
                           update_result=self.updater.update_result, **deps)

    @property
    def fetches(self) -> list[tuple[float, str | None]]:
        """(t, etag sent) of each fetch, as the tests from before views read."""
        return [(f.t, f.etag) for f in self.requests]

    def fetch(self, etag, *, mode=None, tabs=False, screen=None):
        # A loop that fetches without ever waiting would spin here for ever;
        # fail instead, so a regression turns CI red rather than hanging it.
        self.unwaited += 1
        assert self.unwaited <= 3, "fetched again and again without waiting"
        n = len(self.requests)
        self.requests.append(Fetch(self.clock.t, etag, mode, tabs, screen))
        if self.server is not None:
            return self.server(n, etag, self.clock, mode, tabs, screen)
        if mode is not None or tabs:
            return P.Refused("mode", 200)       # no X-Display-Mode: an old server
        if screen is not None:
            return P.Refused("screen", 200)
        return self.responder(n, etag, self.clock)

    def request_poweroff(self):
        self.poweroffs.append((self.clock.t, self.poweroff))
        if self.poweroff == "ok" and self.path_unit:
            # smylte-panel-poweroff.path starts `systemctl poweroff`, which
            # stops the service a few seconds later.
            self.signals.append((self.clock.t + 3.0, signal.SIGTERM))
        return self.poweroff

    def at(self, t: float, fn) -> None:
        """Call fn() once the fake clock reaches t."""
        self.events.schedule(t, fn)

    def notify(self, msg):
        self.notes.append(msg)

    def statuses(self) -> list[str]:
        return [n for n in self.notes if n.startswith("STATUS=")]

    def run(self) -> int:
        self.runner = RecordingRunner(self.deps, self)
        return self.runner.run()


class LateSync(Clock):
    """A clock whose sync arrives at boot time `at`."""

    def __init__(self, t: float, at: float):
        super().__init__(t)
        self.at = at

    def synced_fn(self) -> bool:
        return self.t >= self.at


def _unsynced_at_boot() -> Clock:
    c = Clock(t=0.0)
    c.synced = False
    return c


TAG = '"deadbeef' + "0" * 24 + '"'      # a strong ETag; [1:9] is "deadbeef"


def frame(n: int) -> bytes:
    return bytes([n % 256]) * P.BUF_BYTES


def etag(n: int) -> str:
    return '"%032x"' % n


# The server's static screens, one distinct frame per kind, as the desk key's
# tests cache and serve them.
CONFIRM = bytes([0xC1]) * P.BUF_BYTES
OFF = bytes([0xC2]) * P.BUF_BYTES
CONFIRM_UPDATE, UPDATE_PROMPT, UPDATING, UPDATED, UP_TO_DATE, UPDATE_FAILED = (
    bytes([0xD0 + i]) * P.BUF_BYTES for i in range(1, 7))
SCREEN_BODIES = dict(zip(P.SCREENS, (CONFIRM, OFF, CONFIRM_UPDATE, UPDATE_PROMPT, UPDATING,
                                     UPDATED, UP_TO_DATE, UPDATE_FAILED), strict=True))
SCREEN_FRAMES = tuple(SCREEN_BODIES.values())
assert len(set(SCREEN_FRAMES)) == len(P.SCREENS)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def new_frames(refresh_s: int = 180):
    """A responder that has a new picture every time it is asked."""
    def responder(n, sent, clock):
        return P.Frame(frame(n), etag(n), refresh_s)
    return responder


def read_state_file(tmp_path) -> dict:
    return json.loads((tmp_path / P.STATE_FILE).read_bytes())


def save(tmp_path, **kwargs) -> None:
    # A complete record that names no full refresh is saved as the version 1
    # client left it, every refresh full: its last refresh is its last full one.
    if kwargs.get("complete"):
        kwargs.setdefault("full_end_bt", kwargs.get("painted_end_bt"))
        kwargs.setdefault("full_wall", kwargs.get("painted_wall"))
    assert P.save_state(tmp_path, P.State(**kwargs))


def init_times(panel: FakePanel) -> list[float]:
    return [c[1] for c in panel.calls if c[0] == "init"]


@contextlib.contextmanager
def restored_mask():
    """Put the signal mask back as it was, draining anything left pending, so
    a blocked SIGTERM cannot be delivered to pytest itself."""
    old = signal.pthread_sigmask(signal.SIG_BLOCK, [])
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_BLOCK, P.WAIT_SIGNALS)
        while signal.sigtimedwait(P.WAIT_SIGNALS, 0):
            pass
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


class _NoCollector:
    """main()'s signal collector, in-process: no thread, so none of pytest's
    signals is ever taken. The tests that reach it replace run()."""

    fd = -1

    def pop(self):
        return []

    def alive(self):
        return True


@pytest.fixture
def guarded_main(monkeypatch):
    """Call P.main() with the root logger and the signal mask restored after:
    main() blocks signals and replaces the root logger's handlers. Its signal
    collector is a stand-in; the real one is tested in a child process."""
    monkeypatch.setattr(P, "start_collector", lambda sigset: _NoCollector())
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level

    def call(argv):
        with restored_mask():
            return P.main(argv)

    try:
        yield call
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)


# ── the floor ────────────────────────────────────────────────────────────────

REFRESH_HEADERS = ["0", "1", "-5", "abc", "1e3", "", "9" * 99]


@pytest.fixture(scope="module", params=REFRESH_HEADERS)
def floor_run(request, tmp_path_factory):
    """500 fetches, each with a new picture, at the interval the header gives."""
    refresh_s = P.clamp_refresh(request.param)
    clock = Clock()
    h = Harness(tmp_path_factory.mktemp("floor"), clock, new_frames(refresh_s),
                stop_after=500)
    code = h.run()
    return code, h


def test_the_floor_holds_over_500_cycles_whatever_the_server_advises(floor_run):
    code, h = floor_run
    assert code == 0
    paints = h.panel.paints()
    assert len(paints) >= 100
    for (_, prev_end), (next_init, _) in zip(paints, paints[1:]):
        # In the form run() itself compares, so float rounding of the fake
        # costs cannot make a kept floor look broken.
        assert next_init >= prev_end + P.MIN_REFRESH_S


def test_no_fetch_happens_before_a_paint_would_be_allowed(floor_run):
    """A fetched frame is never held back waiting for the floor: by the time
    it arrives it may be painted, so the glass never shows a stale one."""
    _, h = floor_run
    paints = h.panel.paints()
    assert paints
    for t, _ in h.fetches:
        ends = [end for _, end in paints if end <= t]
        if ends:
            assert t >= ends[-1] + P.MIN_REFRESH_S


def test_the_floor_holds_across_a_restart_in_the_same_boot(tmp_path):
    clock = Clock(1000.0)

    def first(n, sent, clock):
        if n == 0:
            h1.signals.append((clock.t + PAINT_COST + 1, signal.SIGTERM))
        return P.Frame(frame(n), etag(n), 180)

    h1 = Harness(tmp_path, clock, first)
    assert h1.run() == 0
    [(_, run1_end)] = h1.panel.paints()
    assert clock.t == pytest.approx(run1_end + 1)

    clock.t += 10
    h2 = Harness(tmp_path, clock,
                 lambda n, sent, c: P.Frame(frame(n + 100), etag(n + 100), 180),
                 stop_after=1)
    assert h2.run() == 0
    assert h2.fetches[0][0] >= run1_end + 180
    assert init_times(h2.panel)[0] >= run1_end + 180


def test_the_floor_holds_across_a_reboot(tmp_path):
    """A state file from an earlier boot has boot times larger than this
    boot's: 180 s of this boot's uptime is then enough, and no more is waited."""
    P.save_state(tmp_path, P.State(etag=etag(1), glass_sha256=sha(frame(1)),
                                   painted_end_bt=5000.0, painted_wall=None,
                                   attempt_start_bt=4995.0, complete=True))
    clock = Clock(20.0)
    h = Harness(tmp_path, clock, lambda n, sent, c: P.Frame(frame(2), etag(2), 180),
                stop_after=1)
    assert h.run() == 0
    first_init = init_times(h.panel)[0]
    assert 180.0 <= first_init < 180 + 30


def test_the_floor_holds_when_the_reboot_was_quick(tmp_path):
    P.save_state(tmp_path, P.State(etag=etag(1), glass_sha256=sha(frame(1)),
                                   painted_end_bt=100.0, painted_wall=None,
                                   attempt_start_bt=95.0, complete=True))
    clock = Clock(150.0)
    h = Harness(tmp_path, clock, lambda n, sent, c: P.Frame(frame(2), etag(2), 180),
                stop_after=1)
    assert h.run() == 0
    assert init_times(h.panel)[0] >= 280.0


UNKNOWN_STATES = [
    b"",
    b"{",
    b"[]",
    b'{"version": 1, "complete": true, "painted_end_bt": NaN}',
    b'{"version": 2, "complete": false}',
    b'{"version": 1, "complete": true, "painted_end_bt": null}',
    b'{"version": 1, "complete": false, "attempt_start_bt": -5}',
    b'{"version": 1, "complete": false, "etag": "bad"}',
    b'{"version": 1, "complete": false, "glass_sha256": "zz"}',
    b"{" + b" " * 5000 + b"}",
]


@pytest.mark.parametrize("raw", UNKNOWN_STATES)
def test_an_unknown_state_waits_the_full_floor_from_start(tmp_path, raw):
    assert P.parse_state(raw) is None
    (tmp_path / P.STATE_FILE).write_bytes(raw)
    clock = Clock(1000.0)
    h = Harness(tmp_path, clock, new_frames(), stop_after=1)
    assert h.run() == 0
    assert init_times(h.panel)[0] >= 1180


@pytest.mark.parametrize("state_kwargs, start, expected", [
    ({}, 1000, 1180),
    ({"complete": True, "painted_end_bt": 900}, 1000, 1080),
    ({"complete": True, "painted_end_bt": 5000}, 20, 180),
    # The attempt ended no later than this process started.
    ({"complete": False, "attempt_start_bt": 995}, 1000, 1180),
    # 950 + PAINT_MAX_S = 1040.
    ({"complete": False, "attempt_start_bt": 950}, 1100, 1220),
    ({"complete": False, "attempt_start_bt": 5000}, 20, 180),
    # A crash 10 s into a refresh, restarted at once: the refresh may have
    # ended as late as 1010.
    ({"complete": False, "attempt_start_bt": 1000}, 1010, 1190),
])
def test_the_floor_ok_at_table(state_kwargs, start, expected):
    assert P.floor_ok_at(P.State(**state_kwargs), start) == expected


def test_a_refresh_cut_off_by_a_crash_still_counts(tmp_path):
    save(tmp_path, attempt_start_bt=1000.0, complete=False)
    clock = Clock(1010.0)
    h = Harness(tmp_path, clock, new_frames(), stop_after=1)
    assert h.run() == 0
    assert init_times(h.panel)[0] >= 1190


# ── write-ahead and state ────────────────────────────────────────────────────

def test_the_attempt_is_on_disk_before_the_panel_is_touched(tmp_path):
    seen = []

    class Peeking(FakePanel):
        def display(self, data):
            seen.append(read_state_file(tmp_path))
            super().display(data)

    clock = Clock()
    h = Harness(tmp_path, clock, new_frames(), panel=Peeking(clock), stop_after=1)
    assert h.run() == 0
    [during] = seen
    assert during["complete"] is False
    assert during["etag"] is None
    assert during["glass_sha256"] is None
    assert during["attempt_start_bt"] is not None

    [(_, end)] = h.panel.paints()
    after = read_state_file(tmp_path)
    assert after["complete"] is True
    assert after["etag"] == etag(0)
    assert after["glass_sha256"] == sha(frame(0))
    assert after["painted_end_bt"] == pytest.approx(end)


def test_no_write_ahead_means_no_paint(tmp_path, monkeypatch):
    """Painting without the record would let a crash mid-refresh forget it,
    and the restart would refresh again inside the floor."""
    real = P.save_state
    calls = []

    def flaky(state_dir, s):
        calls.append(s)
        if len(calls) == 1:
            return False
        return real(state_dir, s)

    monkeypatch.setattr(P, "save_state", flaky)
    clock = Clock()
    h = Harness(tmp_path, clock, new_frames(), stop_after=2)
    assert h.run() == 0
    first_fetch, second_fetch = h.fetches[0][0], h.fetches[1][0]
    assert all(t > first_fetch for t in init_times(h.panel))
    assert second_fetch - first_fetch == pytest.approx(P.ERROR_RETRY_S, abs=1)
    [(init_t, _)] = h.panel.paints()
    assert init_t == pytest.approx(second_fetch)
    assert h.panel.displayed() == [sha(frame(1))]


def test_the_state_round_trips(tmp_path):
    s = P.State(etag=etag(7), glass_sha256=sha(frame(7)), painted_end_bt=1234.5,
                painted_wall=1.7e9 + 1234.5, attempt_start_bt=1230.0, complete=True)
    assert P.save_state(tmp_path, s)
    assert P.load_state(tmp_path) == s
    assert (tmp_path / P.STATE_FILE).stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "state.json.tmp").exists()


def test_the_same_picture_under_a_new_etag_is_not_repainted(tmp_path):
    def responder(n, sent, clock):
        return P.Frame(frame(1), etag(1) if n == 0 else etag(2), 180)

    h = Harness(tmp_path, Clock(), responder, stop_after=3)
    assert h.run() == 0
    assert len(h.panel.paints()) == 1
    assert read_state_file(tmp_path)["etag"] == etag(2)


def test_a_304_is_not_repainted_and_polling_keeps_the_advised_interval(tmp_path):
    def responder(n, sent, clock):
        if n == 0:
            return P.Frame(frame(1), etag(1), 300)
        return P.NotModified(sent, 300)

    h = Harness(tmp_path, Clock(), responder, stop_after=4)
    assert h.run() == 0
    [(_, end)] = h.panel.paints()
    after = [t for t, _ in h.fetches[1:]]
    assert len(after) == 3
    for prev, nxt in zip([end] + after, after):
        assert nxt - prev == pytest.approx(300, abs=1)
    assert [sent for _, sent in h.fetches[1:]] == [etag(1)] * 3


# ── forced repaint, USR1, scheduling ─────────────────────────────────────────

def _daily(n, sent, clock):
    if n == 0 or sent is None:
        return P.Frame(frame(1), etag(1), 86400)
    return P.NotModified(sent, 86400)


def _daily_304(n, sent, clock):
    """As _daily, but the first conditional fetch gets a 304, not a dedupe."""
    if sent is None:
        return P.Frame(frame(1), etag(1), 86400)
    return P.NotModified(sent, 86400)


def test_an_unchanged_frame_is_repainted_after_23_hours(tmp_path):
    """Waveshare asks for a refresh a day against ghosting, so the same
    picture is painted again, fetched without If-None-Match to get a body."""
    h = Harness(tmp_path, Clock(), _daily, stop_after=3)
    assert h.run() == 0
    paints = h.panel.paints()
    assert len(paints) >= 2
    first_end = paints[0][1]
    second_init = paints[1][0]
    assert first_end + P.FORCE_REPAINT_S <= second_init <= first_end + P.FORCE_REPAINT_S + 60
    before = [sent for t, sent in h.fetches if t <= second_init]
    assert before[-1] is None
    assert h.panel.displayed()[0] == h.panel.displayed()[1]


def test_usr1_forgets_the_glass_and_repaints_when_allowed(tmp_path):
    def responder(n, sent, clock):
        if n == 0:
            h.signals.append((clock.t + PAINT_COST + 10, signal.SIGUSR1))
        if sent is not None:
            return P.NotModified(sent, 3600)
        return P.Frame(frame(1), etag(1), 3600)

    h = Harness(tmp_path, Clock(), responder, stop_after=3)
    assert h.run() == 0
    paints = h.panel.paints()
    assert len(paints) >= 2
    first_end = paints[0][1]
    signalled = first_end + 10
    after_signal = [sent for t, sent in h.fetches if t >= signalled]
    assert after_signal and after_signal[0] is None
    assert paints[1][0] >= first_end + 180


@pytest.mark.parametrize("result, expected_gap", [
    (P.Transient("x"), P.ERROR_RETRY_S),
    (P.Throttled(120), 120),
    (P.Gone(), P.GONE_RETRY_S),
    (P.Refused("x", 200), P.GONE_RETRY_S),
    (P.NotModified(etag(1), 300), 300),
])
def test_the_next_fetch_is_scheduled_by_the_result(tmp_path, result, expected_gap):
    # A Transient after the first paint: before it, the startup retry applies.
    after_frame = isinstance(result, (P.NotModified, P.Transient))

    def responder(n, sent, clock):
        if after_frame and n == 0:
            return P.Frame(frame(1), etag(1), 180)
        return result

    h = Harness(tmp_path, Clock(), responder, stop_after=3 if after_frame else 2)
    assert h.run() == 0
    i = 1 if after_frame else 0
    if not after_frame:
        assert h.panel.calls == []
    gap = h.fetches[i + 1][0] - h.fetches[i][0]
    assert gap == pytest.approx(expected_gap, abs=1)


def test_each_problem_is_logged_once_and_recovery_once(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="smylte-panel")

    def responder(n, sent, clock):
        if n < 3:
            return P.Transient("x")
        return P.Frame(frame(1), etag(1), 180)

    h = Harness(tmp_path, Clock(), responder, stop_after=5)
    assert h.run() == 0
    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING and "not answering" in r.getMessage()]
    recovered = [r for r in caplog.records
                 if r.levelno == logging.INFO and "recovered from" in r.getMessage()]
    assert len(warnings) == 1
    assert len(recovered) == 1


def test_the_23_hour_cap_overrides_a_24_hour_advice(tmp_path):
    h = Harness(tmp_path, Clock(), _daily, stop_after=2)
    assert h.run() == 0
    first_end = h.panel.paints()[0][1]
    assert h.fetches[1][0] == pytest.approx(first_end + P.FORCE_REPAINT_S, abs=1)


NOW_BT = 100_000.0
NOW_WALL = 1.8e9


EARLY_BT = 1_000.0      # an uptime well under 23 h


@pytest.mark.parametrize("state, now_bt, synced, expected", [
    (P.State(complete=False, attempt_start_bt=1.0), NOW_BT, True, False),
    (P.State(complete=True, painted_end_bt=NOW_BT - 82800,
             full_end_bt=NOW_BT - 82800), NOW_BT, True, True),
    (P.State(complete=True, painted_end_bt=NOW_BT - 82799,
             full_end_bt=NOW_BT - 82799), NOW_BT, True, False),
    # A paint time later than now is from an earlier boot, so at least `now`
    # has passed since it: 23 h of this boot's uptime is enough on its own.
    (P.State(complete=True, painted_end_bt=NOW_BT + 5, painted_wall=None,
             full_end_bt=NOW_BT + 5, full_wall=None),
     NOW_BT, False, True),
    (P.State(complete=True, painted_end_bt=82800 + 5, painted_wall=None,
             full_end_bt=82800 + 5, full_wall=None),
     82800, False, True),
    (P.State(complete=True, painted_end_bt=82799 + 5, painted_wall=None,
             full_end_bt=82799 + 5, full_wall=None),
     82799, False, False),
    # Early in a boot, only the synced wall clock can tell.
    (P.State(complete=True, painted_end_bt=EARLY_BT + 5,
             painted_wall=NOW_WALL - 82800, full_end_bt=EARLY_BT + 5,
             full_wall=NOW_WALL - 82800), EARLY_BT, True, True),
    (P.State(complete=True, painted_end_bt=EARLY_BT + 5,
             painted_wall=NOW_WALL - 82800, full_end_bt=EARLY_BT + 5,
             full_wall=NOW_WALL - 82800), EARLY_BT, False, False),
    (P.State(complete=True, painted_end_bt=EARLY_BT + 5,
             painted_wall=NOW_WALL - 82799, full_end_bt=EARLY_BT + 5,
             full_wall=NOW_WALL - 82799), EARLY_BT, True, False),
    (P.State(complete=True, painted_end_bt=EARLY_BT + 5, painted_wall=None,
             full_end_bt=EARLY_BT + 5, full_wall=None),
     EARLY_BT, True, False),
])
def test_the_forced_due_table(state, now_bt, synced, expected):
    assert P.forced_due(state, now_bt, NOW_WALL, synced) is expected


@pytest.mark.parametrize("state, now_bt, synced, expected", [
    (P.State(complete=False, attempt_start_bt=1.0), 2000.0, True, None),
    (P.State(complete=True, painted_end_bt=1000.0, full_end_bt=1000.0),
     2000.0, False, 83_800.0),
    (P.State(complete=True, painted_end_bt=1000.0, full_end_bt=1000.0),
     83_800.0, False, None),
    (P.State(complete=True, painted_end_bt=500_000.0, full_end_bt=500_000.0),
     1000.0, False, 82_800.0),
    (P.State(complete=True, painted_end_bt=1000.0, painted_wall=NOW_WALL - 82_000,
             full_end_bt=1000.0, full_wall=NOW_WALL - 82_000),
     2000.0, True, 2800.0),
    (P.State(complete=True, painted_end_bt=1000.0, painted_wall=NOW_WALL - 82_000,
             full_end_bt=1000.0, full_wall=NOW_WALL - 82_000),
     2000.0, False, 83_800.0),
    (P.State(complete=True, painted_end_bt=1000.0, painted_wall=NOW_WALL - 90_000,
             full_end_bt=1000.0, full_wall=NOW_WALL - 90_000),
     2000.0, True, None),
], ids=["nothing-painted", "boot-bound", "boot-overdue", "earlier-boot",
        "wall-bound-first", "wall-ignored-unsynced", "wall-overdue"])
def test_the_force_poll_at_table(state, now_bt, synced, expected):
    assert P.force_poll_at(state, now_bt, NOW_WALL, synced) == expected


def test_a_failed_refresh_logs_the_phase_it_failed_in(tmp_path, caplog):
    clock = Clock()
    panel = FakePanel(clock, fail={"display": E.BusyTimeout("refresh", 60.0)})
    h = Harness(tmp_path, clock, new_frames(), panel=panel)
    with caplog.at_level(logging.ERROR):
        assert h.run() == 1
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("refresh failed during refresh") for m in messages), messages
    assert not any("during off" in m for m in messages), messages


@pytest.mark.parametrize("make_clock, responder", [
    (Clock, lambda n, sent, clock: (P.Frame(frame(1), etag(1), 3600) if sent is None
                                    else P.NotModified(sent, 3600))),
    (Clock, lambda n, sent, clock: P.Gone()),
    (Clock, lambda n, sent, clock: P.Throttled(3600)),
    (_unsynced_at_boot, lambda n, sent, clock: P.Gone()),
], ids=["not-modified", "gone", "throttled", "clock-gate"])
def test_every_wait_is_a_short_slice_and_each_one_pings_the_watchdog(tmp_path, make_clock,
                                                                     responder):
    """WatchdogSec=60: a wait longer than that with no ping gets the service
    killed. run() waits in slices of at most PING_SLICE_S and pings after
    each one."""
    h = Harness(tmp_path, make_clock(), responder, stop_after=3)
    assert h.run() == 0
    positive = [t for t in h.waits if t > 0]
    assert positive
    assert max(positive) <= P.PING_SLICE_S
    assert sum(positive) > 4 * P.PING_SLICE_S       # long gaps, covered in slices
    assert h.notes.count("WATCHDOG=1") == len(positive)
    if make_clock is _unsynced_at_boot:
        # the wait for the clock, before the first fetch, pings too
        assert positive.count(P.CLOCK_CHECK_S) >= P.CLOCK_SYNC_GRACE_S // P.CLOCK_CHECK_S


def test_after_a_restart_an_unchanged_frame_still_says_what_is_on_the_glass(tmp_path):
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=10.0,
         painted_wall=1.7e9 + 10.0, attempt_start_bt=5.0, complete=True)
    h = Harness(tmp_path, Clock(), lambda n, sent, clock: P.NotModified(sent, 300),
                stop_after=3)
    assert h.run() == 0
    assert all(sent == etag(1) for _, sent in h.fetches)
    statuses = [n for n in h.notes if n.startswith("STATUS=")]
    assert len(statuses) == 1, statuses        # once, not on every 304
    assert statuses[0].startswith("STATUS=showing " + etag(1)[1:9])


def test_after_a_recovery_the_status_says_what_is_on_the_glass_again(tmp_path):
    def responder(n, sent, clock):
        if n == 0:
            return P.Frame(frame(1), etag(1), 300)
        if n == 1:
            return P.Transient("down")
        return P.NotModified(sent, 300)

    h = Harness(tmp_path, Clock(), responder, stop_after=3)
    assert h.run() == 0
    statuses = [n for n in h.notes if n.startswith("STATUS=")]
    assert any("server not answering" in s for s in statuses), statuses
    assert statuses[-1].startswith("STATUS=showing " + etag(1)[1:9]), statuses


def test_a_paint_says_what_it_painted_and_since_when(tmp_path):
    h = Harness(tmp_path, Clock(), lambda n, sent, c: P.Frame(frame(7), TAG, 300),
                stop_after=1)
    assert h.run() == 0
    s = P.load_state(tmp_path)
    statuses = [n for n in h.notes if n.startswith("STATUS=")]
    assert statuses == [f"STATUS=showing deadbeef since {P._hm(s.painted_wall)}"]


def test_a_paint_before_the_clock_syncs_names_no_time(tmp_path):
    clock = Clock()
    clock.synced = False
    h = Harness(tmp_path, clock, lambda n, sent, c: P.Frame(frame(7), TAG, 300),
                stop_after=1)
    assert h.run() == 0
    statuses = [n for n in h.notes if n.startswith("STATUS=")]
    assert statuses == ["STATUS=showing deadbeef"]


def test_the_same_picture_under_a_new_etag_says_so_once(tmp_path):
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=10.0,
         painted_wall=1.7e9 + 10.0, attempt_start_bt=5.0, complete=True)
    h = Harness(tmp_path, Clock(), lambda n, sent, c: P.Frame(frame(1), TAG, 300),
                stop_after=2)
    assert h.run() == 0
    assert "init" not in h.panel.names()
    statuses = [n for n in h.notes if n.startswith("STATUS=")]
    assert statuses == [f"STATUS=showing deadbeef since {P._hm(1.7e9 + 10.0)}"]


@pytest.mark.parametrize("state, expected", [
    (P.State(etag=TAG), "showing deadbeef"),
    (P.State(etag=TAG, painted_wall=1.7e9), f"showing deadbeef since {P._hm(1.7e9)}"),
    (P.State(glass_sha256=P.WHITE_SHA256), "showing white"),
    (P.State(glass_sha256=sha(frame(3))), "showing the last frame"),
], ids=["etag", "etag-and-time", "white", "unknown"])
def test_the_showing_line(state, expected):
    assert P._showing(state) == expected


@pytest.mark.parametrize("first", ["frame", "outage"])
def test_a_refresh_that_cannot_be_recorded_says_so_in_status(tmp_path, monkeypatch, first):
    monkeypatch.setattr(P, "save_state", lambda *a, **k: False)

    def responder(n, sent, c):
        if first == "outage" and n == 0:
            return P.Transient("down")
        return P.Frame(frame(n), etag(n), 300)

    h = Harness(tmp_path, Clock(), responder, stop_after=3)
    assert h.run() == 0
    assert "init" not in h.panel.names()
    statuses = [n for n in h.notes if n.startswith("STATUS=")]
    record = [s for s in statuses if "could not record the refresh" in s]
    assert len(record) == 1, statuses               # once per episode
    assert statuses[-1] == record[0]
    assert statuses[-1].endswith("; the glass keeps its last frame")


def test_after_a_reboot_the_23_hour_repaint_keeps_its_wall_clock_time(tmp_path):
    """Painted 22 h ago by the wall clock, late in an earlier boot; this boot
    is young, and the server advises a day. The boot clock alone would put
    the repaint a day out."""
    clock = Clock(t=200.0)
    painted_wall = clock.walltime() - 22 * 3600
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)),
         painted_end_bt=50_000.0, painted_wall=painted_wall,
         attempt_start_bt=49_990.0, complete=True)
    h = Harness(tmp_path, clock, _daily, stop_after=3)
    assert h.run() == 0
    forced = [t for t, sent in h.fetches if sent is None]
    assert forced, h.fetches
    assert clock.wall_offset + forced[0] <= painted_wall + P.FORCE_REPAINT_S + 60
    assert h.panel.paints()


def test_after_a_reboot_without_a_wall_clock_the_repaint_comes_by_23_hours_of_uptime(tmp_path):
    """No synced clock, and a paint time from an earlier boot: at least this
    boot's uptime has passed since it, so 23 h of uptime is enough."""
    clock = Clock(t=400.0)
    clock.synced = False
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)),
         painted_end_bt=500_000.0, painted_wall=None,
         attempt_start_bt=499_990.0, complete=True)
    h = Harness(tmp_path, clock, _daily, stop_after=3)
    assert h.run() == 0
    forced = [t for t, sent in h.fetches if sent is None]
    assert forced and forced[0] <= P.FORCE_REPAINT_S + 60, h.fetches
    assert h.panel.paints()


def test_a_paint_from_an_earlier_boot_is_recorded_as_boot_time_zero(tmp_path):
    clock = Clock(t=400.0)
    clock.synced = False
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=50_000.0,
         painted_wall=None, attempt_start_bt=49_990.0, complete=True)
    seen = []

    def responder(n, sent, c):
        seen.append(P.load_state(tmp_path).painted_end_bt)
        return P.NotModified(sent, 300)

    h = Harness(tmp_path, clock, responder, stop_after=1)
    assert h.run() == 0
    assert seen == [0.0]
    assert h.fetches[0][0] == 400.0         # the floor is not lengthened


@pytest.mark.parametrize("responder, stop_after", [
    (_daily, 3),
    (lambda n, sent, c: (P.NotModified(sent, 300) if sent
                         else P.Frame(frame(1), etag(1), 300)), 300),
], ids=["daily", "every-5-min"])
def test_after_a_reboot_an_early_paint_without_a_wall_clock_is_repainted_by_23_hours(
        tmp_path, responder, stop_after):
    """The paint ended at 50,000 s of the earlier boot's uptime. Compared with
    each new uptime, it would pass for this boot's once uptime overtook it, and
    the repaint would slip to 50,000 + 82,800 s."""
    clock = Clock(t=400.0)
    clock.synced = False
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=50_000.0,
         painted_wall=None, attempt_start_bt=49_990.0, complete=True)
    h = Harness(tmp_path, clock, responder, stop_after=stop_after)
    assert h.run() == 0
    forced = [t for t, sent in h.fetches if sent is None]
    assert forced and forced[0] <= P.FORCE_REPAINT_S + 60, forced[:3]
    assert h.panel.paints()


def _late_sync_run(tmp_path, painted_age, responder, stop_after=3):
    """Paint from an earlier boot, painted_age seconds of wall time before boot
    time 300; the gate opens unsynced at 300 s, and the clock syncs at 400 s."""
    clock = LateSync(300.0, 400.0)
    painted_wall = clock.wall_offset + 300.0 - painted_age
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=50_000.0,
         painted_wall=painted_wall, attempt_start_bt=49_990.0, complete=True)
    h = Harness(tmp_path, clock, responder, stop_after=stop_after)
    assert h.run() == 0
    return h, clock, painted_wall


@pytest.mark.parametrize("responder", [_daily, _daily_304], ids=["dedupe", "304"])
def test_a_clock_that_syncs_later_still_bounds_the_23_hour_repaint(tmp_path, responder):
    h, clock, painted_wall = _late_sync_run(tmp_path, 22 * 3600, responder)
    assert h.fetches[0][0] == 300.0 and h.fetches[0][1] is not None
    assert 400.0 <= h.fetches[1][0] < 460.0      # asked again once the clock synced
    forced = [t for t, sent in h.fetches if sent is None]
    assert forced, h.fetches
    assert clock.wall_offset + forced[0] <= painted_wall + P.FORCE_REPAINT_S + 60


@pytest.mark.parametrize("responder", [_daily, _daily_304], ids=["dedupe", "304"])
def test_a_clock_that_syncs_to_an_overdue_repaint_repaints_at_once(tmp_path, responder):
    h, clock, painted_wall = _late_sync_run(tmp_path, P.FORCE_REPAINT_S - 60, responder)
    forced = [t for t, sent in h.fetches if sent is None]
    assert forced and forced[0] < 460.0, h.fetches
    assert h.panel.paints()


def test_a_clock_that_syncs_during_a_backoff_does_not_cut_it_short(tmp_path):
    h, clock, painted_wall = _late_sync_run(
        tmp_path, 22 * 3600, lambda n, sent, c: P.Throttled(3600))
    times = [t for t, _ in h.fetches]
    assert times[0] == 300.0
    assert times[1] == pytest.approx(300.0 + 3600, abs=1), times


W0 = 1.7e9      # Clock's default wall_offset


def test_a_sync_that_lands_during_a_fetch_is_not_lost(tmp_path):
    """The wall clock already says the repaint is overdue, and the clock syncs
    while the first (conditional) fetch is in flight."""
    clock = Clock(t=300.0)
    clock.synced = False
    painted_wall = clock.wall_offset + 300.0 - (P.FORCE_REPAINT_S + 600)
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=50_000.0,
         painted_wall=painted_wall, attempt_start_bt=49_990.0, complete=True)

    def responder(n, sent, c):
        if n == 0:
            c.synced = True
        return _daily_304(n, sent, c)

    h = Harness(tmp_path, clock, responder, stop_after=2)
    assert h.run() == 0
    assert h.fetches[0] == (300.0, etag(1))
    assert h.fetches[1][1] is None, h.fetches
    assert h.fetches[1][0] <= 300.0 + P.PING_SLICE_S + 1, h.fetches


def test_a_repaint_that_comes_due_during_a_fetch_is_fetched_at_once(tmp_path):
    """Same boot, no wall clock: the 23 h mark passes while a 304 is fetched.
    Waiting out the advised hour would leave it late by that hour."""
    clock = Clock(t=83_799.8)
    clock.synced = False
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=1000.0,
         painted_wall=None, attempt_start_bt=995.0, complete=True)

    def responder(n, sent, c):
        c.t += 0.5                  # the fetch takes time
        if sent is None:
            return P.Frame(frame(1), etag(1), 3600)
        return P.NotModified(sent, 3600)

    h = Harness(tmp_path, clock, responder, stop_after=2)
    assert h.run() == 0
    assert h.fetches[0][1] == etag(1)
    assert h.fetches[1][1] is None, h.fetches
    assert h.fetches[1][0] == pytest.approx(83_800.3, abs=0.01), h.fetches
    assert h.panel.paints()


def _due_mid_fetch(n, sent, c):
    c.t += 0.5                      # the fetch takes time
    if sent is None:
        return P.Frame(frame(1), etag(1), 3600)
    return P.NotModified(sent, 3600)


def test_after_the_forced_repaint_the_next_fetches_are_conditional_again(tmp_path):
    """force_next is for one fetch: once the overdue repaint is done, an
    unchanged frame is not painted again."""
    clock = Clock(t=83_799.8)
    clock.synced = False
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=1000.0,
         painted_wall=None, attempt_start_bt=995.0, complete=True)
    h = Harness(tmp_path, clock, _due_mid_fetch, stop_after=6)
    assert h.run() == 0
    assert h.fetches[1][1] is None
    assert len(h.panel.paints()) == 1
    assert [s for _, s in h.fetches[2:]] == [etag(1)] * 4


def test_a_repaint_due_by_the_wall_clock_mid_fetch_stays_forced_if_the_flag_drops(tmp_path):
    """The wall clock says due at the end of the fetch; by the next fetch the
    sync flag reads unsynced. The decision made at the end of the fetch holds."""
    clock = Clock(t=50_000.0)
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=40_000.0,
         painted_wall=W0 + 50_000.2 - P.FORCE_REPAINT_S, attempt_start_bt=39_995.0,
         complete=True)

    def responder(n, sent, c):
        answer = _due_mid_fetch(n, sent, c)
        if n == 0:
            c.synced = False
        return answer

    h = Harness(tmp_path, clock, responder, stop_after=2)
    assert h.run() == 0
    assert h.fetches[0][1] == etag(1)
    assert h.fetches[1][1] is None, h.fetches
    assert h.fetches[1][0] == pytest.approx(50_000.5, abs=0.01)


@pytest.mark.parametrize("t, synced, saved", [
    # the boot-time bound is 800 s into the backoff
    (83_000.0, False, dict(painted_end_bt=1000.0, painted_wall=None)),
    # the wall-clock bound is 800 s into the backoff, the boot bound far off
    (83_000.0, True, dict(painted_end_bt=80_000.0,
                          painted_wall=W0 + 83_000.0 - (P.FORCE_REPAINT_S - 800))),
], ids=["boot-bound", "wall-bound"])
def test_a_23_hour_bound_never_cuts_a_failure_backoff_short(tmp_path, t, synced, saved):
    clock = Clock(t=t)
    clock.synced = synced
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)),
         attempt_start_bt=saved["painted_end_bt"] - 5.0, complete=True, **saved)

    def responder(n, sent, c):
        assert n < 10, "fetched again without waiting"
        return P.Throttled(3600)

    h = Harness(tmp_path, clock, responder, stop_after=4)
    assert h.run() == 0
    times = [t for t, _ in h.fetches]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert gaps == pytest.approx([3600.0] * 3, abs=1), gaps


def test_an_earlier_boot_record_that_fails_to_save_is_saved_later(tmp_path, monkeypatch):
    """If the rewrite to boot time 0 does not reach the disk, a restart later
    in this boot would read the old time as this boot's."""
    clock = Clock(t=400.0)
    clock.synced = False
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)), painted_end_bt=50_000.0,
         painted_wall=None, attempt_start_bt=49_990.0, complete=True)
    real = P.save_state
    calls = []

    def flaky(state_dir, s):
        calls.append(s)
        return False if len(calls) == 1 else real(state_dir, s)

    monkeypatch.setattr(P, "save_state", flaky)
    h = Harness(tmp_path, clock, lambda n, sent, c: P.NotModified(sent, 300),
                stop_after=2)
    assert h.run() == 0
    assert calls[0].painted_end_bt == 0.0
    assert len(calls) >= 2
    assert P.load_state(tmp_path).painted_end_bt == 0.0


@pytest.mark.parametrize("t, synced, saved, answer, gap", [
    # overdue by the wall clock only (boot bound far off)
    (1000.0, True, dict(painted_end_bt=10.0, painted_wall=W0 + 1000.0 - 30 * 3600),
     P.Transient("down"), P.STARTUP_RETRY_S),
    # same boot, overdue by boot time, no wall clock
    (83_000.0, False, dict(painted_end_bt=10.0, painted_wall=None),
     P.Transient("down"), P.STARTUP_RETRY_S),
    # an earlier boot, with this boot's uptime past 23 h
    (83_000.0, False, dict(painted_end_bt=500_000.0, painted_wall=None),
     P.Transient("down"), P.STARTUP_RETRY_S),
    # due by the wall clock, the boot bound still 800 s off
    (83_000.0, True, dict(painted_end_bt=1000.0, painted_wall=W0 + 83_000.0 - 24 * 3600),
     P.Throttled(3600), 3600),
    # due by boot time, the wall bound still 360 s off
    (83_810.0, True, dict(painted_end_bt=1000.0,
                          painted_wall=W0 + 83_810.0 - (P.FORCE_REPAINT_S - 360)),
     P.Throttled(3600), 3600),
], ids=["wall-clock", "boot-clock", "earlier-boot", "wall-due-boot-not", "boot-due-wall-not"])
def test_an_overdue_repaint_does_not_shorten_the_retry_backoff(tmp_path, t, synced, saved,
                                                               answer, gap):
    """Once any bound says the repaint is due, the next fetch is forced whenever
    it comes, so the cap must not pull it inside the backoff. (A Transient
    before the process's first paint backs off STARTUP_RETRY_S.)"""
    clock = Clock(t=t)
    clock.synced = synced
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)),
         attempt_start_bt=saved["painted_end_bt"] - 5.0, complete=True, **saved)

    def responder(n, sent, c):
        assert n < 10, "fetched again without waiting"
        return answer

    h = Harness(tmp_path, clock, responder, stop_after=4)
    assert h.run() == 0
    times = [t for t, _ in h.fetches]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert len(gaps) == 3
    assert gaps == pytest.approx([gap] * 3, abs=1), gaps


# ── clock gate ───────────────────────────────────────────────────────────────

def test_no_fetch_before_the_clock_gate_opens(tmp_path):
    """Without an RTC the box's clock is wrong until NTP answers, and the
    server on the same box would render the wrong day."""
    clock = Clock(10.0)
    clock.synced = False
    h = Harness(tmp_path, clock, new_frames(), stop_after=1)
    assert h.run() == 0
    assert h.fetches[0][0] >= P.CLOCK_SYNC_GRACE_S


def test_the_floor_still_applies_once_the_clock_is_synced(tmp_path):
    h = Harness(tmp_path, Clock(10.0), new_frames(), stop_after=1)
    assert h.run() == 0
    assert h.fetches[0][0] >= 190


# ── signals ──────────────────────────────────────────────────────────────────

def test_a_stop_while_waiting_returns_at_once(tmp_path):
    clock = Clock()
    save(tmp_path, complete=True, painted_end_bt=clock.t - 10)
    h = Harness(tmp_path, clock, new_frames(),
                signals=[(clock.t + 5, signal.SIGTERM)])
    assert h.run() == 0
    assert h.panel.calls == []
    assert h.fetches == []


def test_a_stop_pending_at_paint_time_prevents_the_paint(tmp_path):
    def responder(n, sent, clock):
        h.signals.append((clock.t, signal.SIGTERM))
        return P.Frame(frame(n), etag(n), 180)

    h = Harness(tmp_path, Clock(), responder)
    assert h.run() == 0
    assert "init" not in h.panel.names()


def test_a_stop_during_a_refresh_lets_it_finish(tmp_path):
    """A stop that arrives mid-refresh is only taken in by the next wait,
    after sleep(): the signals are blocked, and only the collector takes them."""

    class Stopping(FakePanel):
        def display(self, data):
            h.signals.append((self.clock.t, signal.SIGTERM))
            super().display(data)

    clock = Clock()
    h = Harness(tmp_path, clock, new_frames(), panel=Stopping(clock))
    assert h.run() == 0
    assert h.panel.names() == ["init", "display", "sleep"]


WAITER_SCRIPT = """
import importlib.util, os, pathlib, signal, sys, threading, time
spec = importlib.util.spec_from_file_location("panel_under_test", sys.argv[1])
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)
signal.pthread_sigmask(signal.SIG_BLOCK, panel.WAIT_SIGNALS)
events = panel.Events(panel.start_collector(panel.WAIT_SIGNALS),
                      sysfs_root=pathlib.Path("/nonexistent"), open_key=None,
                      boottime=panel.boottime, key_enabled=False)
threading.Timer(0.1, os.kill, (os.getpid(), signal.SIGTERM)).start()
start = time.monotonic()
items = events.wait(5)
elapsed = time.monotonic() - start
print(f"{[int(i.sig) for i in items]} {elapsed:.3f}")
"""


def test_the_real_waiter_collects_a_signal_sent_from_another_thread():
    """In a child process, so a real SIGTERM can never reach pytest."""
    out = subprocess.run([sys.executable, "-I", "-c", WAITER_SCRIPT, str(F.PANEL_PY)],
                         timeout=10, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    sigs, elapsed = out.stdout.split()
    assert sigs == f"[{int(signal.SIGTERM)}]"
    assert float(elapsed) < 1.0


# ── panel failures ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("method, exc, busy_stuck, critical", [
    ("display", E.BusyTimeout("refresh", 60.0), True, False),
    ("init", OSError(5, "io"), False, False),
    ("display", ValueError("bad"), False, False),
    ("sleep", RuntimeError("bug"), False, True),
])
def test_a_panel_failure_aborts_and_exits_restartable(tmp_path, caplog, method, exc,
                                                      busy_stuck, critical):
    caplog.set_level(logging.INFO, logger="smylte-panel")
    clock = Clock()
    h = Harness(tmp_path, clock, new_frames(),
                panel=FakePanel(clock, fail={method: exc}), stop_after=5)
    assert h.run() == 1
    aborts = [c for c in h.panel.calls if c[0] == "abort"]
    assert [c[2] for c in aborts] == [busy_stuck]
    if critical:
        assert any(r.levelno == logging.CRITICAL for r in caplog.records)
    after = read_state_file(tmp_path)
    assert after["complete"] is False
    assert after["etag"] is None


# ── clear() ──────────────────────────────────────────────────────────────────

def test_clear_respects_the_floor_and_records_white(tmp_path):
    assert P.WHITE == bytes(P.BUF_BYTES)
    clock = Clock()
    painted_end = clock.t - 30
    save(tmp_path, etag=etag(1), glass_sha256=sha(frame(1)),
         painted_end_bt=painted_end, attempt_start_bt=painted_end - 5, complete=True)
    h = Harness(tmp_path, clock, new_frames())
    assert P.clear(h.deps) == 0
    assert init_times(h.panel)[0] >= painted_end + 180
    assert h.panel.displayed() == [sha(P.WHITE)]
    after = P.load_state(tmp_path)
    assert after.etag is None
    assert after.glass_sha256 == hashlib.sha256(P.WHITE).hexdigest()
    assert after.complete is True


# ── start-up via main() ──────────────────────────────────────────────────────

@pytest.fixture
def no_driver(monkeypatch):
    """P.open_driver replaced by one that records the call and fails. main()
    catches Exception around it, so the record is what the test checks."""
    called = []

    def open_driver():
        called.append(True)
        raise AssertionError("open_driver must not be called")

    monkeypatch.setattr(P, "open_driver", open_driver)
    return called


@pytest.fixture
def valid_env(tmp_path, monkeypatch):
    creds = tmp_path / "creds"
    creds.mkdir()
    (creds / P.CREDENTIAL).write_bytes(TOKEN.encode() + b"\n")
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(creds))
    monkeypatch.setenv("STATE_DIRECTORY", str(state))
    monkeypatch.delenv(P.PWR_PIN_ENV, raising=False)
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    return creds


def _fake_driver(monkeypatch, busy=1):
    """P.open_driver replaced by the real driver's Panel on fakes, with a fake
    clock so close()'s 2 s settle costs nothing. Returns the fakes."""
    rec = F.Recorder()
    lines = F.FakeLines(rec, busy=busy, busy_pin=E.BUSY_PIN)
    factory = F.SpiFactory(rec, lines)
    clock = F.FakeClock(rec=rec)

    def panel(lines_, spi_factory, *, pwr_pin=None, tick=None):
        return E.Panel(lines_, spi_factory, pwr_pin=pwr_pin, tick=tick,
                       clock=clock.monotonic, sleep=clock.sleep)

    driver = types.SimpleNamespace(
        open_hardware=lambda pwr: (lines, factory, "/dev/gpiochip0"),
        Panel=panel, PanelError=E.PanelError, BusyTimeout=E.BusyTimeout,
        HardwareMissing=E.HardwareMissing,
        SPI_BUS=E.SPI_BUS, SPI_DEVICE=E.SPI_DEVICE, SPI_HZ=E.SPI_HZ)
    monkeypatch.setattr(P, "open_driver", lambda: driver)
    return types.SimpleNamespace(rec=rec, lines=lines, factory=factory, clock=clock)


@pytest.mark.parametrize("content", [
    b"",
    b"\n",
    b"https://box.example/display/" + b"A" * 43 + b".bin",
    b"A" * 300,
    b"A" * 43 + b"\n\n",
    b"\xff" * 43,
])
def test_a_bad_credential_exits_78_without_touching_hardware(
        valid_env, monkeypatch, no_driver, guarded_main, content):
    monkeypatch.setattr(P.os, "geteuid", lambda: 1000)
    (valid_env / P.CREDENTIAL).write_bytes(content)
    assert guarded_main([]) == 78
    assert no_driver == []


@pytest.mark.parametrize("case", ["no-credentials-directory", "no-credential-file",
                                  "no-state-directory"])
def test_a_missing_setting_exits_78_without_touching_hardware(
        valid_env, monkeypatch, no_driver, guarded_main, case):
    monkeypatch.setattr(P.os, "geteuid", lambda: 1000)
    if case == "no-credentials-directory":
        monkeypatch.delenv("CREDENTIALS_DIRECTORY")
    elif case == "no-credential-file":
        (valid_env / P.CREDENTIAL).unlink()
    else:
        monkeypatch.delenv("STATE_DIRECTORY")
    assert guarded_main([]) == 78
    assert no_driver == []


def test_root_is_refused(valid_env, monkeypatch, no_driver, guarded_main):
    monkeypatch.setattr(P.os, "geteuid", lambda: 0)
    assert guarded_main([]) == 78
    assert no_driver == []


@pytest.mark.parametrize("pin_env, expected", [
    (None, 18),         # the Driver HAT's power switch, the default
    ("none", None),
    ("18", 18),
    ("8", None),        # reserved (CE0): ignored, never fatal
])
def test_power_off_works_as_root_and_drives_the_lines_low(
        monkeypatch, guarded_main, pin_env, expected):
    monkeypatch.setattr(P.os, "geteuid", lambda: 0)
    if pin_env is None:
        monkeypatch.delenv(P.PWR_PIN_ENV, raising=False)
    else:
        monkeypatch.setenv(P.PWR_PIN_ENV, pin_env)
    got = []

    def rec_fn(pwr):
        got.append(pwr)
        return True

    monkeypatch.setattr(P, "open_driver",
                        lambda: types.SimpleNamespace(drive_lines_low=rec_fn))
    assert guarded_main(["--power-off"]) == 0
    assert got == [expected]


def test_power_off_never_fails_when_the_driver_cannot_load(monkeypatch, guarded_main):
    monkeypatch.setattr(P.os, "geteuid", lambda: 0)
    monkeypatch.delenv(P.PWR_PIN_ENV, raising=False)

    def broken():
        raise RuntimeError("no driver")

    monkeypatch.setattr(P, "open_driver", broken)
    assert guarded_main(["--power-off"]) == 0


def test_power_off_never_fails_when_the_lines_cannot_be_driven(monkeypatch,
                                                               guarded_main):
    monkeypatch.setattr(P.os, "geteuid", lambda: 0)
    monkeypatch.delenv(P.PWR_PIN_ENV, raising=False)
    monkeypatch.setattr(P, "open_driver", lambda: types.SimpleNamespace(
        drive_lines_low=lambda pwr: False))
    assert guarded_main(["--power-off"]) == 0


@pytest.mark.parametrize("argv", [["--bogus"], ["--clear", "x"]])
def test_bad_usage_exits_2(guarded_main, no_driver, argv):
    assert guarded_main(argv) == 2
    assert no_driver == []


def test_missing_hardware_exits_1_so_systemd_restarts_it(valid_env, monkeypatch,
                                                         guarded_main):
    monkeypatch.setattr(P.os, "geteuid", lambda: 1000)

    def raiser(pwr):
        raise E.HardwareMissing("x", "y")

    monkeypatch.setattr(P, "open_driver", lambda: types.SimpleNamespace(
        open_hardware=raiser, HardwareMissing=E.HardwareMissing))
    assert guarded_main([]) == 1


def test_main_blocks_every_signal_it_waits_for_before_the_loop(valid_env, monkeypatch,
                                                              guarded_main):
    """Without the block, SIGTERM's default action would kill a refresh, and
    USR1 would kill the service outright."""
    monkeypatch.setattr(P.os, "geteuid", lambda: 1000)
    _fake_driver(monkeypatch)
    before = set(signal.pthread_sigmask(signal.SIG_BLOCK, []))
    assert not before & set(P.WAIT_SIGNALS), "blocked already: the test proves nothing"
    seen = []

    def fake_run(d):
        seen.append(set(signal.pthread_sigmask(signal.SIG_BLOCK, [])))
        return 0

    monkeypatch.setattr(P, "run", fake_run)
    assert guarded_main([]) == 0
    (mask,) = seen
    assert set(P.WAIT_SIGNALS) <= mask


def test_main_says_ready_and_powers_the_panel_off_on_the_way_out(valid_env, monkeypatch,
                                                                guarded_main):
    monkeypatch.setattr(P.os, "geteuid", lambda: 1000)
    hw = _fake_driver(monkeypatch)
    hw.lines.levels[E.RST_PIN] = 1      # as a refresh leaves it
    monkeypatch.setattr(P, "run", lambda d: 0)
    name = "smylte-ready-" + str(os.getpid())
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind("\0" + name)
        server.settimeout(2)
        monkeypatch.setenv("NOTIFY_SOCKET", "@" + name)
        assert guarded_main([]) == 0
        assert server.recv(4096).startswith(b"READY=1")
    assert hw.lines.released is True
    assert hw.lines.levels[E.RST_PIN] == 0


def test_selftest_powers_up_and_down_without_a_refresh(valid_env, monkeypatch,
                                                      guarded_main):
    monkeypatch.setattr(P.os, "geteuid", lambda: 1000)
    hw = _fake_driver(monkeypatch)
    assert guarded_main(["--selftest"]) == 0
    cmds = [p for dc, p in hw.rec.spi(drop_status_polls=True) if dc == 0]
    assert bytes([E.POWER_ON]) in cmds
    assert bytes([E.DEEP_SLEEP]) in cmds
    assert bytes([E.DATA_START_NEW]) not in cmds
    assert bytes([E.DISPLAY_REFRESH]) not in cmds
    assert hw.lines.released is True
    assert hw.lines.levels[E.RST_PIN] == 0


def test_a_failed_selftest_names_the_phase_it_failed_in(valid_env, monkeypatch,
                                                       guarded_main, capsys):
    """abort() leaves `phase` at "off"; the log must say where it failed."""
    monkeypatch.setattr(P.os, "geteuid", lambda: 1000)
    _fake_driver(monkeypatch, busy=0)
    assert guarded_main(["--selftest"]) == 1
    err = capsys.readouterr().err
    assert "self-test failed during power-on" in err
    assert "during off" not in err


DISTINCT = "Xy" + "w" * 41      # 43 characters


def _config_error(cred_dir) -> P.ConfigError:
    with pytest.raises(P.ConfigError) as info:
        P.load_token(cred_dir)
    assert DISTINCT not in str(info.value)
    return info.value


def test_load_token_accepts_a_token_with_or_without_one_newline(tmp_path):
    (tmp_path / P.CREDENTIAL).write_bytes(DISTINCT.encode() + b"\n")
    assert P.load_token(str(tmp_path)) == DISTINCT
    (tmp_path / P.CREDENTIAL).write_bytes(DISTINCT.encode())
    assert P.load_token(str(tmp_path)) == DISTINCT


def test_load_token_refuses_no_directory_or_no_file(tmp_path):
    _config_error(None)
    _config_error(str(tmp_path))


@pytest.mark.parametrize("content, says", [
    (b"https://box.example/display/" + DISTINCT.encode() + b".bin", "URL"),
    ((DISTINCT * 13).encode()[:513], None),
    (DISTINCT.encode() + "é".encode(), None),
])
def test_load_token_refuses_what_is_not_a_token_without_echoing_it(
        tmp_path, content, says):
    (tmp_path / P.CREDENTIAL).write_bytes(content)
    e = _config_error(str(tmp_path))
    if says is not None:
        assert says in str(e)


@pytest.mark.parametrize("value, expected", [
    (None, 18), ("", 18), ("none", None), ("18", 18),
    ("17", P.ConfigError), ("8", P.ConfigError), ("24", P.ConfigError),
    ("abc", P.ConfigError), ("40", P.ConfigError), ("1", P.ConfigError),
])
def test_pwr_pin_from_env(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv(P.PWR_PIN_ENV, raising=False)
    else:
        monkeypatch.setenv(P.PWR_PIN_ENV, value)
    if expected is P.ConfigError:
        with pytest.raises(P.ConfigError):
            P.pwr_pin_from_env()
    else:
        assert P.pwr_pin_from_env() == expected


# ── hygiene ──────────────────────────────────────────────────────────────────

def test_the_token_never_reaches_a_log_record(tmp_path, caplog):
    tok = "Tk" + "q" * 41
    assert len(tok) == 43
    caplog.set_level(logging.DEBUG)

    def responder(n, sent, clock):
        kind = n % 6
        if kind == 0:
            return P.Frame(frame(n), etag(n), 180)
        if kind == 1:
            return P.NotModified(sent or etag(n), 180)
        if kind == 2:
            return P.Transient("x")
        if kind == 3:
            return P.Gone()
        if kind == 4:
            return P.Refused("x", 200)
        return P.Throttled(60)

    h = Harness(tmp_path, Clock(), responder, stop_after=12)
    assert h.run() == 0

    creds = tmp_path / "creds"
    creds.mkdir()
    (creds / P.CREDENTIAL).write_bytes(
        b"https://box.example/display/" + tok.encode() + b".bin")
    try:
        P.load_token(str(creds))
    except P.ConfigError as e:
        logging.getLogger("smylte-panel").error("%s", e)
    else:
        pytest.fail("a URL was accepted as a token")

    assert caplog.records
    for record in caplog.records:
        assert tok not in record.getMessage()
        assert tok not in (record.exc_text or "")


def _record(level: int, msg: str) -> logging.LogRecord:
    return logging.LogRecord("smylte-panel", level, __file__, 1, msg, None, None)


def test_the_formatter_redacts_the_token_and_prefixes_priorities():
    tok = "Tk" + "q" * 41
    fmt = P._Formatter(journal=True)
    fmt.token = tok
    text = fmt.format(_record(logging.ERROR, f"x {tok} y"))
    assert text.startswith("<3>")
    assert tok[:4] + "…" in text
    assert tok not in text
    assert fmt.format(_record(logging.INFO, "hello")).startswith("<6>")
    lines = fmt.format(_record(logging.INFO, "a\nb")).split("\n")
    assert len(lines) == 2
    assert all(line.startswith("<6>") for line in lines)

    plain = P._Formatter(journal=False)
    plain.token = tok
    text = plain.format(_record(logging.ERROR, f"x {tok} y"))
    assert not re.match(r"<\d>", text)
    assert tok not in text


def test_importing_panel_changes_nothing_global():
    """The service blocks signals and sets up logging in main(), never on
    import, so a test or a tool can load it without side effects."""
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, [])
    handlers = logging.getLogger().handlers[:]
    for i in range(2):
        spec = importlib.util.spec_from_file_location(
            f"smylte_pi_panel_import_check_{i}", F.PANEL_PY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    assert signal.pthread_sigmask(signal.SIG_BLOCK, []) == mask
    assert logging.getLogger().handlers == handlers


def test_sd_notify_without_a_socket_is_false(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert P.sd_notify("READY=1") is False


def test_sd_notify_sends_to_a_path_socket(tmp_path, monkeypatch):
    path = tmp_path / "n.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind(str(path))
        server.settimeout(2)
        monkeypatch.setenv("NOTIFY_SOCKET", str(path))
        assert P.sd_notify("READY=1") is True
        assert server.recv(4096) == b"READY=1"


def test_sd_notify_sends_to_an_abstract_socket(monkeypatch):
    name = "smylte-test-" + str(os.getpid())
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind("\0" + name)
        server.settimeout(2)
        monkeypatch.setenv("NOTIFY_SOCKET", "@" + name)
        assert P.sd_notify("WATCHDOG=1") is True
        assert server.recv(4096) == b"WATCHDOG=1"


# ── the desk key, on the real loop ───────────────────────────────────────────
#
# Design §4.10's run-loop tests and the critique's timelines T1–T16, on the
# real run(): a switchable smylted (Server), the key's edges on FakeEvents, the
# screens cached on disk. As in the timelines, the process starts at boot time
# 20 s with the clock synced and no state, so its first paint (routine, full)
# is at 200 s, and the background has fetched the other views' strips by
# about 210 s. Each test ends with checks(): no stale prompt or off screen
# while Ui browses, no unconfirmed power-off, the routine floor, at most one
# paint after a stop, and the budget. FakeEvents fails any run that spins.

STRIP = (440, 480)
STRIP_BYTES = (STRIP[1] - STRIP[0]) * P.STRIDE
PAGE_BYTES = P.BUF_BYTES - STRIP_BYTES


def page_of(view: str, ver: int = 1) -> bytes:
    return bytes([0x10 * (P.VIEWS.index(view) + 1) + ver]) * PAGE_BYTES


def strip_of(view: str) -> bytes:
    return bytes([0xA0 + P.VIEWS.index(view)]) * STRIP_BYTES


def view_frame(view: str, ver: int = 1) -> bytes:
    return page_of(view, ver) + strip_of(view)


def legacy_frame(ver: int = 1) -> bytes:
    return bytes([0x60 + ver]) * P.BUF_BYTES


def tag(body: bytes) -> str:
    return '"%s"' % sha(body)[:32]


def what(body: bytes | None) -> str | None:
    """What a frame shows, as the timelines name it."""
    if body is None:
        return None
    names = {**{body: kind for kind, body in SCREEN_BODIES.items()}, P.WHITE: "white"}
    if body in names:
        return names[body]
    if 0x60 <= body[0] < 0x70:
        return "legacy"
    top, tab = P.VIEWS[(body[0] >> 4) - 1], P.VIEWS[body[-1] - 0xA0]
    return f"view:{top}" if top == tab else f"mixed:{top}-page/{tab}-tab"


class Server:
    """smylted for the desk key: three views, each a page and its tab strip;
    the screens; and the stored view for a legacy request."""

    def __init__(self, *, switchable=True, old=False, render_s=0.4, refresh_s=3600,
                 rotation=0, refuse_screens=()):
        self.switchable, self.old = switchable, old
        self.render_s, self.refresh_s, self.rotation = render_s, refresh_s, rotation
        self.refuse_screens = set(refuse_screens)
        self.version = lambda view, t: 1
        self.down: list[tuple[float, float]] = []

    def __call__(self, n, sent, clock, mode, tabs, screen):
        t = clock.t
        if any(a <= t < b for a, b in self.down):
            clock.t += 0.002
            return P.Transient("ECONNREFUSED")
        if screen is not None:
            clock.t += 0.05
            if self.old or screen in self.refuse_screens:
                return P.Refused("screen", 200)
            if screen not in SCREEN_BODIES:
                return P.Refused("HTTP 422", 422)
            body = SCREEN_BODIES[screen]
            return P.Frame(body, tag(body), self.refresh_s)
        clock.t += self.render_s
        strip = None
        if mode is not None:
            if self.old:
                return P.Refused("mode", 200)
            if not self.switchable:
                return P.Refused("HTTP 422", 422, code="views-off")
            if tabs and self.rotation in (0, 180):
                body, strip = view_frame(mode, self.version(mode, t)), STRIP
            else:
                body = page_of(mode, self.version(mode, t))[:1] * P.BUF_BYTES
        else:
            body = legacy_frame(self.version(None, t))
        if sent == tag(body):
            return P.NotModified(sent, self.refresh_s)
        return P.Frame(body, tag(body), self.refresh_s, strip=strip, mode=mode)


class Scripted(Server):
    """Server, except where `rule(t, mode, screen)` gives an answer: that
    answer, after the time the Server would have taken."""

    def __init__(self, rule, **kw):
        super().__init__(**kw)
        self.rule = rule

    def __call__(self, n, sent, clock, mode, tabs, screen):
        got = self.rule(clock.t, mode, screen)
        if got is None:
            return super().__call__(n, sent, clock, mode, tabs, screen)
        clock.t += 0.05 if screen is not None else self.render_s
        return got


def tap(t: float, d: float = 0.12) -> list[tuple[float, int]]:
    return [(t, 1), (t + d, 0)]


def hold(t: float, d: float = 1.3) -> list[tuple[float, int]]:
    return [(t, 1), (t + d, 0)]


def desk(tmp_path, *, keys=(), until=None, start=20.0, clock=None, screens=SCREEN_FRAMES,
         state=None, server=None, signals=(), **kw) -> Harness:
    """A Harness for the desk key: KEY=auto, a Server, the screens on disk."""
    clock = clock or Clock(start)
    for kind, body in SCREEN_BODIES.items():
        if body in screens:
            assert P.save_screen(tmp_path, kind, body)
    if state is not None:
        assert P.save_state(tmp_path, state)
    signals = list(signals) + ([(until, signal.SIGTERM)] if until is not None else [])
    kw.setdefault("key", "auto")
    return Harness(tmp_path, clock, server=server or Server(), keys=sorted(keys),
                   signals=signals, **kw)


def set_tokens(h: Harness, n: int):
    def poke():
        h.runner.bucket.tokens = n
        h.runner.bucket.last = h.clock.t
    return poke


def set_fast_count(h: Harness, n: int):
    def poke():
        h.runner.state = dataclasses.replace(h.runner.state, fast_count=n)
    return poke


def checks(*hs: Harness) -> None:
    """The critique's checks, over one process or several in turn."""
    painted = [p for h in hs for p in h.painted]
    # The runner's exemption is believed for one paint per process: its first
    # view paint. A later routine paint that claims it is held to the floor.
    allowed = set()
    for h in hs:
        first = next((p for p in h.painted if p.purpose in ("routine", "page")), None)
        if first is not None and first.exempt:
            allowed.add(id(first))
        # So is the first view paint after a notice left with nothing to
        # repaint: it stands in for that leave's own paint (F5). Only when it
        # is the very next paint: a notice left with a repaint has had its
        # leave paint already.
        for i, n in enumerate(h.painted):
            if n.purpose == "notice":
                nxt = h.painted[i + 1:i + 2]
                after = nxt[0] if nxt and nxt[0].purpose in ("routine", "page") else None
                if after is not None and after.exempt:
                    allowed.add(id(after))
    for h in hs:
        assert not h.stale, f"a screen on the glass while Ui browses: {h.stale}"
        prompts = [p for p in h.painted if p.purpose == "prompt"]
        presses = [t for t, v in h.keys if v == 1]
        for t_req, _ in h.poweroffs:
            before = [p for p in prompts if p.t1 <= t_req and p.frame in (CONFIRM, CONFIRM_UPDATE)]
            assert before, f"a power-off at {t_req} with no prompt drawn"
            shown = before[-1].t1
            assert any(shown <= t <= shown + P.PROMPT_S and t <= t_req for t in presses), \
                f"a power-off at {t_req} that no tap during the prompt confirmed"
        for t_req, rid in h.updater.requests:
            before = [p for p in prompts if p.t1 <= t_req and p.frame == UPDATE_PROMPT]
            assert before, f"an update request at {t_req} with no Update? drawn"
            shown = before[-1].t1
            assert any(shown <= t <= shown + P.PROMPT_S and t <= t_req for t in presses), \
                f"an update request at {t_req} that no tap during Update? confirmed"
            assert any(p.purpose == "update" and f"{p.t1:.3f}" == rid for p in h.painted), \
                f"an update request {rid} that is not the end of an Updating paint"
        if h.stop_seen is not None:
            after = [p for p in h.painted if p.t0 >= h.stop_seen]
            assert len(after) <= 1, f"{len(after)} paints after the stop at {h.stop_seen}"
        for p in h.painted:
            if p.purpose in ("strip", "page"):
                assert p.tokens >= 1, f"a key paint with {p.tokens} tokens: {p}"
        if h.runner is not None:
            assert h.runner.bucket.tokens >= 0
    for prev, p in zip(painted, painted[1:]):
        if p.purpose == "routine" and id(p) not in allowed:
            assert p.t0 >= prev.t1 + P.MIN_REFRESH_S - 1e-6, \
                f"a routine paint {p.t0 - prev.t1:.1f} s after the last refresh"


def key_paints(h: Harness, after: float = 300.0) -> list[tuple[str, str]]:
    return [(p.purpose, p.kind) for p in h.painted if p.t0 >= after]


def fetched(h: Harness, after: float = 300.0, **match) -> list[Fetch]:
    return [f for f in h.requests if f.t >= after
            and all(getattr(f, k) == v for k, v in match.items())]


# ── taps: strips and pages ───────────────────────────────────────────────────

def test_t1a_a_tap_draws_the_strip_then_one_fast_page(tmp_path):
    """§4.10: a tap gives a strip with the exact old/new bytes, then one fast
    page 0.5 s later."""
    h = desk(tmp_path, keys=tap(400), until=430)
    assert h.run() == 0
    assert key_paints(h) == [("strip", "partial"), ("page", "fast")]
    mode, old, new = h.panel.drawn[-2]
    assert mode == "partial"
    assert old == view_frame("habits")
    assert new == page_of("habits") + strip_of("now")
    [page] = fetched(h)
    assert page == Fetch(page.t, None, "now", True, None)
    assert page.t >= 400.12 + P.COALESCE_S
    assert what(h.panel.glass) == "view:now"
    assert h.runner.ui.view == "now"
    checks(h)


def test_t1b_two_quick_taps_give_two_strips_and_one_page(tmp_path):
    h = desk(tmp_path, keys=tap(400) + tap(400.3), until=430)
    assert h.run() == 0
    assert key_paints(h) == [("strip", "partial"), ("strip", "partial"), ("page", "fast")]
    assert [f.mode for f in fetched(h)] == ["calendar"]
    assert what(h.panel.glass) == "view:calendar"
    checks(h)


def test_t1c_three_taps_back_to_the_start_fetch_once_and_paint_nothing(tmp_path):
    """v3: three taps cycling back to the start view give exactly one Page
    fetch, no page paint, then a positive wait."""
    h = desk(tmp_path, keys=tap(400) + tap(400.3) + tap(400.6), until=430)
    waits_at_fetch = []
    server = h.server

    def recording(n, sent, clock, mode, tabs, screen):
        waits_at_fetch.append(len(h.waits))
        return server(n, sent, clock, mode, tabs, screen)

    h.server = recording
    assert h.run() == 0
    assert key_paints(h) == [("strip", "partial"), ("strip", "partial")]
    [page] = fetched(h)
    assert page.mode == "habits"
    assert what(h.panel.glass) == "view:habits"
    assert h.panel.glass == view_frame("habits")
    assert h.waits[waits_at_fetch[-1]] > 0
    checks(h)


def test_t2a_four_edges_during_the_first_paint_give_two_taps_and_no_prompt(tmp_path):
    h = desk(tmp_path, keys=tap(201.0) + tap(202.0), until=240)
    assert h.run() == 0
    assert [(p.purpose, p.kind) for p in h.painted] == [("routine", "full"), ("page", "fast")]
    assert h.runner.ui.view == "calendar"
    assert what(h.panel.glass) == "view:calendar"
    checks(h)


def test_t2b_four_edges_during_a_full_routine_refresh(tmp_path):
    server = Server(refresh_s=300)
    server.version = lambda view, t: 1 if t < 500 else 2
    h = desk(tmp_path, keys=tap(506.0) + tap(507.0), until=540, server=server)
    h.at(480, set_fast_count(h, P.FULL_EVERY))
    assert h.run() == 0
    assert key_paints(h, 500) == [("routine", "full"), ("strip", "partial"), ("page", "fast")]
    assert h.panel.drawn[-2][2] == page_of("habits", 2) + strip_of("calendar")
    assert h.panel.glass == view_frame("calendar", 2)
    checks(h)


# ── holds: the prompt, the off screen and the way back ───────────────────────

@pytest.mark.parametrize("render_s", [1.0, 20.0])
def test_t3a_a_hold_during_a_routine_fetch_skips_its_paint_for_the_prompt(tmp_path,
                                                                         render_s):
    server = Server(refresh_s=300, render_s=render_s)
    server.version = lambda view, t: 1 if t < 500 else 2
    first_end = 200 + render_s + PAINT_COST
    fetch_at = first_end + 300
    h = desk(tmp_path, keys=hold(fetch_at + 0.1), until=fetch_at + 250, server=server)
    assert h.run() == 0
    after = [p for p in h.painted if p.t0 >= fetch_at]
    assert [(p.purpose, p.kind) for p in after[:2]] == [("prompt", "fast"), ("leave", "fast")]
    # The prompt follows the hold (or, for a slow fetch, the fetch) at once.
    assert after[0].t0 <= max(fetch_at + 0.1 + P.HOLD_S, fetch_at + render_s) + 0.01
    assert after[1].frame == view_frame("habits", 1)
    # The new frame is drawn later, by the routine branch, on the floor.
    [routine] = [p for p in after if p.purpose == "routine"]
    assert routine.frame == view_frame("habits", 2)
    checks(h)


@pytest.mark.parametrize("held", [1.3, 1.5])
def test_t3b_a_hold_during_the_first_paint_shows_the_prompt_after_it(tmp_path, held):
    h = desk(tmp_path, keys=hold(201.0, held), until=240)
    assert h.run() == 0
    assert [(p.purpose, p.kind) for p in h.painted] == [
        ("routine", "full"), ("prompt", "fast"), ("leave", "fast")]
    assert h.painted[2].frame == view_frame("habits")
    checks(h)


def test_t4a_a_tap_after_the_prompt_draws_off_in_full_and_requests_the_power_off(
        tmp_path):
    h = desk(tmp_path, keys=hold(400) + tap(405), until=440)
    assert h.run() == 0
    assert key_paints(h) == [("prompt", "fast"), ("off", "full")]
    assert h.panel.glass == OFF
    assert [why for _, why in h.poweroffs] == ["ok"]
    assert P.load_state(tmp_path).off is True
    checks(h)


def test_t4b_a_tap_pressed_during_the_prompt_paint_does_not_confirm(tmp_path):
    h = desk(tmp_path, keys=hold(400) + tap(402.0), until=440)
    assert h.run() == 0
    assert key_paints(h) == [("prompt", "fast"), ("leave", "fast")]
    assert h.poweroffs == []
    checks(h)


def test_t4c_the_prompt_times_out_back_to_the_glass_before_it(tmp_path):
    h = desk(tmp_path, keys=hold(400), until=440)
    assert h.run() == 0
    prompt, leave = h.painted[-2:]
    assert (prompt.purpose, leave.purpose) == ("prompt", "leave")
    assert leave.t0 == pytest.approx(prompt.t1 + P.PROMPT_S, abs=0.01)
    assert leave.frame == view_frame("habits")
    assert fetched(h) == []
    s = P.load_state(tmp_path)
    assert (s.view, s.etag) == ("habits", tag(view_frame("habits")))
    checks(h)


def test_t4d_no_confirm_screen_means_no_prompt(tmp_path):
    h = desk(tmp_path, keys=hold(203.0), screens=(), until=240)
    assert h.run() == 0
    assert [p.purpose for p in h.painted] == ["routine"]
    assert any("no confirm screen yet" in s for s in h.statuses())
    # ...and the background fetches every screen, for next time.
    assert [f.screen for f in h.requests if f.screen] == list(P.SCREENS)
    assert P.load_screen(tmp_path, "confirm") == CONFIRM
    checks(h)


def test_off_with_no_off_screen_still_requests_the_power_off(tmp_path):
    h = desk(tmp_path, keys=hold(400) + tap(405), screens=(CONFIRM,), until=440,
             server=Server(refuse_screens={"off"}))
    assert h.run() == 0
    assert key_paints(h) == [("prompt", "fast")]
    assert [why for _, why in h.poweroffs] == ["ok"]
    # The refused off screen is asked for again no sooner than BG_RETRY_S.
    offs = [f.t for f in h.requests if f.screen == "off"]
    assert len(offs) >= 2 and all(b - a >= P.BG_RETRY_S for a, b in zip(offs, offs[1:]))
    checks(h)


class OffFails(FakePanel):
    def display(self, frame_):
        if frame_ == OFF:
            self._step("display", "off", 0.1)
            raise E.BusyTimeout("refresh", 60.0)
        super().display(frame_)


@pytest.mark.parametrize("poweroff, path_unit, code, when", [
    ("ok", True, 0, "at the stop"),
    ("ok", False, 1, "when the grace runs out"),
    ("failed: EACCES", True, 1, "at once"),
])
def test_off_whose_paint_fails_still_requests_the_power_off(tmp_path, poweroff, path_unit,
                                                             code, when):
    """m13: request it anyway; a stop ends it as usual; EX_FAIL only once the
    grace has run out, or at once if the request failed."""
    clock = Clock(20.0)
    h = desk(tmp_path, clock=clock, keys=hold(400) + tap(405), until=700,
             panel=OffFails(clock), poweroff=poweroff, path_unit=path_unit)
    assert h.run() == code
    [(t_req, _)] = h.poweroffs
    if when == "when the grace runs out":
        assert clock.t == pytest.approx(t_req + P.POWEROFF_GRACE_S, abs=0.01)
    elif when == "at once":
        assert clock.t == pytest.approx(t_req, abs=0.01)
    else:
        assert clock.t == pytest.approx(t_req + 3.0, abs=0.01)
    checks(h)


def test_t8a_a_failed_power_off_request_goes_back_at_once(tmp_path):
    h = desk(tmp_path, keys=hold(400) + tap(405), until=440, poweroff="failed: EACCES")
    assert h.run() == 0
    off, leave = h.painted[-2:]
    assert (off.purpose, leave.purpose) == ("off", "leave")
    assert leave.t0 == pytest.approx(off.t1, abs=0.01)
    assert leave.frame == view_frame("habits")
    assert h.runner.ui.mode == "browse"
    assert any("could not power off: failed: EACCES" in s for s in h.statuses())
    checks(h)


def test_t8b_a_power_off_nobody_acts_on_goes_back_after_the_grace(tmp_path):
    h = desk(tmp_path, keys=hold(400) + tap(405), until=560, path_unit=False)
    assert h.run() == 0
    off, leave = h.painted[-2:]
    assert (off.purpose, leave.purpose) == ("off", "leave")
    assert leave.t0 == pytest.approx(off.t1 + P.POWEROFF_GRACE_S, abs=0.01)
    assert h.cleared[-1] == pytest.approx(leave.t0, abs=0.01)    # the request removed
    assert any("could not power off" in s for s in h.statuses())
    checks(h)


def test_p1_a_tap_pressed_before_the_deadline_and_released_after_it_confirms(tmp_path):
    """v3: the press decides. While the key is down the deadline passes, and
    the loop must neither spin nor time the prompt out under the finger."""
    h = desk(tmp_path, keys=hold(400), until=440)
    shown = 400 + P.HOLD_S + INIT_COST + FAST_COST + SLEEP_COST
    deadline = shown + P.PROMPT_S
    h.keys += [(deadline - 0.1, 1), (deadline + 0.15, 0)]
    for t, v in h.keys[-2:]:
        h.events.schedule(t, P.Key(v, t))
    assert h.run() == 0
    assert key_paints(h) == [("prompt", "fast"), ("off", "full")]
    [prompt] = [p for p in h.painted if p.purpose == "prompt"]
    assert prompt.t1 == pytest.approx(shown)
    assert len(h.poweroffs) == 1
    checks(h)


# ── the budget ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tokens, expected", [
    (0, [("prompt", "fast"), ("leave", "fast")]),
    (1, [("prompt", "fast"), ("leave", "fast")]),
    (2, [("strip", "partial"), ("page", "fast"), ("prompt", "fast"), ("leave", "fast")]),
    (3, [("strip", "partial"), ("page", "fast"), ("prompt", "fast"), ("leave", "fast")]),
])
def test_t5_a_tap_needs_two_tokens_and_a_hold_and_its_way_back_never_wait(tmp_path, tokens,
                                                                         expected):
    """v3: with 2 tokens a tap draws its strip and its page; with 1 it is
    rejected. An empty bucket still allows the prompt and the leave paint."""
    h = desk(tmp_path, keys=tap(400) + hold(415), until=440)
    h.at(390, set_tokens(h, tokens))
    assert h.run() == 0
    assert key_paints(h, 390) == expected
    resting = [s for s in h.statuses() if "key resting" in s]
    assert bool(resting) == (tokens < 2)
    checks(h)


def test_an_empty_bucket_still_confirms_and_powers_off(tmp_path):
    h = desk(tmp_path, keys=hold(400) + tap(405), until=440)
    h.at(390, set_tokens(h, 0))
    assert h.run() == 0
    assert key_paints(h, 390) == [("prompt", "fast"), ("off", "full")]
    assert len(h.poweroffs) == 1
    checks(h)


def test_t5x_a_tap_during_its_page_fetch_drops_that_page(tmp_path):
    """M4: the page whose drain moved the view is dropped, unpainted and
    unpaid; the new view's strip and page follow, within the budget."""
    h = desk(tmp_path, keys=tap(400) + tap(402.0), until=440, server=Server(render_s=1.0))
    h.at(390, set_tokens(h, 3))
    assert h.run() == 0
    assert key_paints(h, 390) == [("strip", "partial"), ("strip", "partial"),
                                  ("page", "fast")]
    assert [f.mode for f in fetched(h, 390)] == ["now", "calendar"]
    assert what(h.panel.glass) == "view:calendar"
    assert h.runner.bucket.tokens == 0
    checks(h)


def test_t5e_holds_on_an_empty_bucket_come_no_more_than_the_budget_allows(tmp_path):
    keys = [k for i in range(40) for k in hold(400 + 15 * i)]
    h = desk(tmp_path, keys=keys, until=1000)
    h.at(390, set_tokens(h, 0))
    assert h.run() == 0
    prompts = [p.t0 for p in h.painted if p.purpose == "prompt"]
    assert 4 <= len(prompts) <= 14
    assert all(b - a >= 40 for a, b in zip(prompts, prompts[1:])), prompts
    checks(h)


def test_the_budget_a_crash_loop_start_rests_the_key_then_refills(tmp_path):
    """§4.10's budget: a start 160 s after the last refresh, in the same boot,
    has 3 tokens. A tap spends 2 (its strip and its page), so the next tap
    rests the key until the refill brings it back to 2. (The glass holds a
    legacy frame, so the first fetch is painted and the key is live.)"""
    s = P.State(etag=tag(legacy_frame()), glass_sha256=sha(legacy_frame()),
                painted_end_bt=840.0, attempt_start_bt=835.0, complete=True,
                fast_count=1, full_end_bt=840.0)
    h = desk(tmp_path, start=1000.0, state=s, until=1100,
             keys=tap(1035) + tap(1045) + tap(1060))
    assert h.run() == 0
    assert P.start_tokens(s, 1000.0) == 3
    assert key_paints(h, 1030) == [("strip", "partial"), ("page", "fast"),
                                   ("strip", "partial"), ("page", "fast")]
    assert [f.mode for f in fetched(h, 1030)] == ["now", "calendar"]
    resting = [s for s in h.statuses() if "key resting" in s]
    assert resting == ["STATUS=key resting; try again in 5 s; the glass keeps its last frame"]
    # Back to what is on the glass once the bucket holds 2 again.
    i = h.notes.index(resting[0])
    assert any(n.startswith("STATUS=showing") for n in h.notes[i:])
    checks(h)


def test_a_resting_key_puts_back_the_problem_it_covered(tmp_path):
    """§4.12: "key resting" covers a 404 for a while. Once the bucket holds 2
    again, STATUS names the 404 again, never "showing", until the next
    routine fetch."""
    server = Scripted(lambda t, mode, screen:
                      P.Gone() if screen is None and t >= 380 else None, refresh_s=300)
    h = desk(tmp_path, keys=tap(610), until=1300, server=server)
    h.at(600, set_tokens(h, 1))
    assert h.run() == 0
    assert len([f for f in h.requests if f.screen is None and f.t >= 380]) == 1
    statuses = h.statuses()
    i = next(i for i, s in enumerate(statuses) if "key resting" in s)
    assert "(404)" in statuses[i - 1]
    after = statuses[i + 1:]
    assert after and not any(s.startswith("STATUS=showing") for s in after)
    assert "(404)" in after[-1]
    checks(h)


def test_the_resting_status_counts_down_and_is_logged_once(tmp_path, caplog):
    """§4.12: the wait STATUS gives is sent again whenever it changes; the
    warning is still logged once."""
    h = desk(tmp_path, keys=tap(610) + tap(630), until=700)
    h.at(600, set_tokens(h, 1))
    with caplog.at_level(logging.WARNING, logger="smylte-panel"):
        assert h.run() == 0
    ns = [int(m.group(1)) for s in h.statuses()
          if (m := re.search(r"key resting; try again in (\d+) s", s))]
    assert ns[0] == 40 and min(ns) <= 20
    assert ns == sorted(set(ns), reverse=True)
    assert len([m for m in caplog.messages if "key resting" in m]) == 1
    assert h.statuses()[-1].startswith("STATUS=showing")
    checks(h)


def test_a_reboot_start_has_a_full_bucket(tmp_path):
    s = P.State(etag=tag(view_frame("habits")), glass_sha256=sha(view_frame("habits")),
                painted_end_bt=50_000.0, attempt_start_bt=49_995.0, complete=True,
                view="habits", full_end_bt=50_000.0)
    h = desk(tmp_path, start=20.0, state=s, until=25)
    assert h.run() == 0
    assert h.runner.bucket.tokens == P.KEY_BURST


def test_an_owed_page_with_no_token_is_drawn_by_the_routine_branch(tmp_path):
    """M4: a key page is painted only with a token; otherwise the routine
    branch draws the view when the floor allows. A hold before the page
    spends the last token; after the prompt the page is due again (m2)."""
    h = desk(tmp_path, keys=tap(400) + hold(400.3), until=800)
    h.at(390, set_tokens(h, 2))
    assert h.run() == 0
    assert key_paints(h, 390)[:3] == [("strip", "partial"), ("prompt", "fast"),
                                      ("leave", "fast")]
    leave = h.painted[3]
    [page] = [f for f in fetched(h, 390) if f.t < leave.t1 + 1]
    assert page.mode == "now"
    [routine] = [p for p in h.painted if p.purpose == "routine" and p.t0 > 390]
    assert routine.frame == view_frame("now")
    assert routine.t0 >= leave.t1 + P.MIN_REFRESH_S
    checks(h)


# ── the view API and legacy servers ──────────────────────────────────────────

@pytest.mark.parametrize("server, reason", [
    (Server(switchable=False, refresh_s=300), P.VIEWS_OFF_SETTING),
    (Server(old=True, refresh_s=300), P.VIEWS_OFF_TOO_OLD),
], ids=["views-off", "old-server"])
def test_t6_a_legacy_display_is_drawn_at_once_and_rechecked(tmp_path, server, reason):
    """B1: the view fetch that turns the views off is followed by the legacy
    fetch at once, not after a problem backoff; the views are asked for again
    every VIEWS_RECHECK_S; the legacy page is painted when it changes."""
    server.version = lambda view, t: 1 + int(t // 600)
    h = desk(tmp_path, until=6000, server=server)
    assert h.run() == 0
    first, second = h.requests[:2]
    assert (first.mode, second.mode) == ("habits", None)
    assert second.t == pytest.approx(first.t + server.render_s)
    assert h.painted[0].t0 < 210
    assert all(p.purpose == "routine" and what(p.frame) == "legacy" for p in h.painted)
    assert len(h.painted) >= 8
    rechecks = [f.t for f in h.requests[1:] if f.mode is not None]
    assert len(rechecks) >= 5
    assert all(b - a >= P.VIEWS_RECHECK_S for a, b in zip(rechecks, rechecks[1:]))
    assert any(s.endswith(" · desk key off: " + reason) for s in h.statuses())
    checks(h)


def test_t6_turning_desk_key_on_brings_the_views_back(tmp_path):
    """A recheck that succeeds turns the views back on: view fetches only,
    view frames on the glass, taps work, STATUS drops 'desk key off'."""
    server = Server(switchable=False, refresh_s=300)
    h = desk(tmp_path, keys=tap(2000), until=2400, server=server)
    h.at(1000, lambda: setattr(server, "switchable", True))
    assert h.run() == 0
    assert h.runner.views and h.runner.views_reason is None
    on = next(f.t for f in h.requests if f.t > 1000 and f.mode is not None)
    assert all(f.mode is not None for f in h.requests if f.t >= on and f.screen is None)
    routine = [p for p in h.painted if p.purpose == "routine" and p.t0 > on]
    assert routine and all(what(p.frame).startswith("view:") for p in routine)
    assert key_paints(h, 1990)[:2] == [("strip", "partial"), ("page", "fast")]
    assert "desk key off" not in h.statuses()[-1]
    checks(h)


def test_t6_legacy_a_hold_and_its_timeout_repaint_the_glass_with_no_fetch(tmp_path):
    """v3: legacy mode, a tap is ignored, a hold shows the prompt, and the
    timeout repaints the glass from before it, fetching nothing."""
    h = desk(tmp_path, keys=tap(400) + hold(420), until=460,
             server=Server(switchable=False, refresh_s=300))
    assert h.run() == 0
    assert key_paints(h) == [("prompt", "fast"), ("leave", "fast")]
    assert h.painted[-1].frame == legacy_frame()
    assert fetched(h) == []
    s = P.load_state(tmp_path)
    assert (s.view, s.etag) == (None, tag(legacy_frame()))
    checks(h)


def test_t6_legacy_a_confirming_tap_powers_off(tmp_path):
    h = desk(tmp_path, keys=tap(400) + hold(420) + tap(425), until=460,
             server=Server(switchable=False, refresh_s=300))
    assert h.run() == 0
    assert key_paints(h) == [("prompt", "fast"), ("off", "full")]
    assert len(h.poweroffs) == 1
    checks(h)


def test_key_off_never_asks_for_views_screens_or_the_key(tmp_path):
    h = desk(tmp_path, key="off", until=1500,
             server=Server(switchable=False, refresh_s=300))
    assert h.run() == 0
    assert all((f.mode, f.tabs, f.screen) == (None, False, None) for f in h.requests)
    assert [p.purpose for p in h.painted] == ["routine"]
    assert not any("desk key off" in s for s in h.statuses())
    checks(h)


# ── outages, stops, USR1 ─────────────────────────────────────────────────────

def test_p8_a_key_page_that_fails_leaves_the_view_to_the_routine_schedule(tmp_path):
    """v3: one fetch, no key-path retry; the routine branch then fetches the
    tapped view, unconditionally, when the floor allows."""
    server = Server()
    server.down = [(401.0, 411.0)]
    h = desk(tmp_path, keys=tap(400), until=700, server=server)
    assert h.run() == 0
    strip = h.painted[1]
    assert strip.purpose == "strip"
    page, routine = fetched(h, 390)[:2]
    assert (page.mode, page.etag) == ("now", None)
    assert routine.t >= strip.t1 + P.MIN_REFRESH_S
    assert (routine.mode, routine.etag) == ("now", None)
    assert h.painted[-1].frame == view_frame("now")
    checks(h)


def test_t7a_the_server_down_from_the_start_keeps_the_glass_white_after_a_prompt(tmp_path):
    s = P.State(etag=tag(view_frame("habits")), glass_sha256=sha(view_frame("habits")),
                painted_end_bt=10.0, attempt_start_bt=5.0, complete=True,
                view="habits", fast_count=1, full_end_bt=10.0)
    server = Server()
    server.down = [(0, 2000)]
    h = desk(tmp_path, state=s, keys=tap(300) + tap(310) + hold(320), until=2300,
             server=server)
    assert h.run() == 0
    assert [(p.purpose, what(p.frame)) for p in h.painted] == [
        ("prompt", "confirm"), ("leave", "white"), ("routine", "view:habits")]
    white_end, routine = h.painted[1].t1, h.painted[2]
    assert routine.t0 >= 2000 and routine.t0 >= white_end + P.MIN_REFRESH_S
    # 5 s retries before the first paint, then the usual 60 s.
    gaps = [b.t - a.t for a, b in zip(h.requests, h.requests[1:]) if b.t < 2000]
    assert gaps[0] == pytest.approx(P.STARTUP_RETRY_S, abs=0.01)
    assert min(g for g, f in zip(gaps, h.requests[1:]) if f.t > 340) >= P.ERROR_RETRY_S - 0.01
    checks(h)


def test_t7b_the_server_going_down_leaves_the_taps_to_the_routine_schedule(tmp_path):
    server = Server()
    server.down = [(380, 2000)]
    h = desk(tmp_path, keys=tap(400) + tap(420) + hold(440), until=2300, server=server)
    assert h.run() == 0
    assert [p.purpose for p in h.painted if p.t0 > 300] == [
        "strip", "prompt", "leave", "routine"]
    assert h.painted[-1].frame == view_frame("calendar")
    assert h.painted[-1].t0 >= 2000
    times = [f.t for f in fetched(h, 470)]
    assert all(b - a >= P.ERROR_RETRY_S - 0.01 for a, b in zip(times, times[1:]) if b < 2000)
    checks(h)


def test_the_idle_return_does_not_cut_a_routine_429_short(tmp_path):
    """§4.12: the idle return pulls the routine fetch forward only after a
    healthy answer; after a routine 429 it waits for the Retry-After."""
    server = Scripted(lambda t, mode, screen:
                      P.Throttled(3600) if screen is None and t >= 580 else None,
                      refresh_s=180)
    h = desk(tmp_path, keys=tap(400), until=1500, idle_s=600, server=server)
    assert h.run() == 0
    [throttled] = [f for f in fetched(h, 580) if f.screen is None]
    assert throttled.t < 590
    assert h.runner.ui.view == "habits"     # the idle return came, and fetched nothing
    assert h.runner.next_poll >= throttled.t + 3600
    checks(h)


def test_the_idle_return_does_not_cut_a_key_page_429_short(tmp_path):
    """§4.12: a failed key Page counts as a failure for the healthy guard."""
    server = Scripted(lambda t, mode, screen:
                      P.Throttled(3600) if screen is None and 400 <= t < 410 else None)
    h = desk(tmp_path, keys=tap(400), until=1500, idle_s=600, server=server)
    assert h.run() == 0
    [page] = [f for f in fetched(h, 390) if f.screen is None]
    assert page.mode == "now"
    assert h.runner.ui.view == "habits"
    assert h.runner.next_poll >= page.t + 3600
    checks(h)


def test_a_failed_key_page_does_not_cut_a_routine_429_short(tmp_path):
    """§4.12: a Transient on a key Page during a routine 429's backoff keeps
    the backoff (max), where after a healthy answer it would pull it in (min)."""
    def rule(t, mode, screen):
        if screen is None and 380 <= t < 390:
            return P.Throttled(3600)
        if screen is None and 400 <= t < 410:
            return P.Transient("ECONNRESET")
        return None
    h = desk(tmp_path, keys=tap(400), until=1500, server=Scripted(rule, refresh_s=180))
    assert h.run() == 0
    throttled, page = [f for f in fetched(h, 380) if f.screen is None]
    assert throttled.t < 390 and page.mode == "now" and 400 <= page.t < 410
    assert h.runner.next_poll >= throttled.t + 3600
    checks(h)


def test_the_way_back_to_white_does_not_cut_a_404_backoff_short(tmp_path):
    """§4.12: a 404, USR1 (which forgets the glass), a hold and its timeout:
    the glass goes white, and the routine still waits out the 404's backoff."""
    server = Scripted(lambda t, mode, screen:
                      P.Gone() if screen is None and t >= 380 else None, refresh_s=300)
    h = desk(tmp_path, keys=hold(620), signals=[(600.0, signal.SIGUSR1)], until=1450,
             server=server)
    assert h.run() == 0
    assert [(p.purpose, what(p.frame)) for p in h.painted if p.t0 > 300] == [
        ("prompt", "confirm"), ("leave", "white")]
    gone = [f.t for f in h.requests if f.screen is None and f.t >= 380]
    assert len(gone) == 2 and 600 <= gone[1] < 601     # the routine 404, then USR1's
    assert h.runner.next_poll >= gone[1] + P.GONE_RETRY_S
    checks(h)


@pytest.mark.parametrize("stop_at, painted", [
    (400.5, [("strip", "partial")]),     # during the strip: it finishes, no page
    (402.3, [("strip", "partial")]),     # during the page's fetch: the page is skipped
])
def test_t9_a_stop_during_a_strip_lets_it_finish_and_skips_its_page(tmp_path, stop_at,
                                                                   painted):
    """§4.10: a stop during a key refresh lets it finish, and a stop pending
    before a page skips it."""
    h = desk(tmp_path, keys=tap(400), signals=[(stop_at, signal.SIGTERM)],
             server=Server(render_s=1.0))
    assert h.run() == 0
    assert key_paints(h) == painted
    assert h.panel.names()[-1] == "sleep"
    checks(h)


def test_t9a_a_restart_after_a_stop_during_a_strip_keeps_the_floor(tmp_path):
    clock = Clock(20.0)
    h1 = desk(tmp_path, clock=clock, keys=tap(400), signals=[(400.5, signal.SIGTERM)])
    assert h1.run() == 0
    clock.t = 401.9
    h2 = desk(tmp_path, clock=clock, until=700)
    assert h2.run() == 0
    assert h2.runner.bucket.tokens <= 1         # a crash-loop start
    assert h2.painted[0].purpose == "routine"
    assert h2.painted[0].t0 >= h1.painted[-1].t1 + P.MIN_REFRESH_S
    checks(h1, h2)


def test_t9c_a_stop_while_an_off_is_queued_still_draws_it_and_requests_once(tmp_path):
    """v3: the confirming tap, a second press and a stop all at once: the
    press holds the queue, then the off screen is drawn and requested."""
    keys = hold(400) + [(405.0, 1), (405.12, 0), (405.12, 1), (405.6, 0)]
    # systemd sends no second SIGTERM to a unit that is already stopping.
    h = desk(tmp_path, keys=keys, signals=[(405.12, signal.SIGTERM)], path_unit=False)
    assert h.run() == 0
    assert key_paints(h) == [("prompt", "fast"), ("off", "full")]
    assert h.painted[-1].t0 >= 405.6
    [(t_req, _)] = h.poweroffs
    # Returned at the request, not at the grace or a second signal.
    assert h.clock.t == pytest.approx(t_req, abs=0.01)
    checks(h)


def test_t9d_a_restart_with_the_prompt_on_the_glass_repaints_at_once(tmp_path):
    """m3: the prompt a stop left on the glass is replaced as soon as the
    server answers, floor-exempt and free."""
    clock = Clock(20.0)
    h1 = desk(tmp_path, clock=clock, keys=hold(400), signals=[(405.0, signal.SIGTERM)])
    assert h1.run() == 0
    assert h1.panel.glass == CONFIRM
    clock.t = 406.0
    h2 = desk(tmp_path, clock=clock, until=800)
    assert h2.run() == 0
    first = h2.painted[0]
    assert (first.purpose, first.kind, first.exempt) == ("routine", "full", True)
    assert first.t0 == pytest.approx(406.4)
    assert what(first.frame) == "view:habits"
    checks(h1, h2)


def test_t10_usr1_during_the_prompt_goes_back_to_white_then_the_view(tmp_path):
    h = desk(tmp_path, keys=hold(400), signals=[(405.0, signal.SIGUSR1)], until=700)
    assert h.run() == 0
    assert [(p.purpose, p.kind, what(p.frame)) for p in h.painted if p.t0 > 300] == [
        ("prompt", "fast", "confirm"), ("leave", "full", "white"),
        ("routine", "fast", "view:habits")]
    checks(h)


def test_a_restart_onto_an_unchanged_view_leaves_the_prompt_to_white_then_the_view_at_the_floor(
        tmp_path):
    s = P.State(etag=tag(view_frame("habits")), glass_sha256=sha(view_frame("habits")),
                painted_end_bt=10.0, attempt_start_bt=5.0, complete=True,
                view="habits", fast_count=1, full_end_bt=10.0)
    h = desk(tmp_path, state=s, keys=hold(450), until=1000, server=Server(refresh_s=3600))
    assert h.run() == 0
    assert [(p.purpose, what(p.frame)) for p in h.painted] == [
        ("prompt", "confirm"), ("leave", "white"), ("routine", "view:habits")]
    white_end, view = h.painted[1].t1, h.painted[2]
    assert white_end + P.MIN_REFRESH_S <= view.t0 <= white_end + P.MIN_REFRESH_S + 5
    checks(h)


def test_usr1_drops_the_glass_so_the_next_tap_draws_no_strip(tmp_path):
    """§4.5: USR1 forgets the glass (no strip until a paint) and asks for a
    full refresh next."""
    h = desk(tmp_path, keys=tap(400) + tap(420), signals=[(410.0, signal.SIGUSR1)],
             until=440)
    assert h.run() == 0
    assert key_paints(h) == [("strip", "partial"), ("page", "fast"), ("page", "full")]
    checks(h)


# ── wake, the clock gate, the idle return ────────────────────────────────────

OFF_STATE = P.State(painted_end_bt=5000.0, attempt_start_bt=4995.0, complete=True,
                    off=True, glass_sha256=sha(OFF), full_end_bt=5000.0)


def test_t11a_a_wake_draws_today_as_soon_as_the_server_answers(tmp_path):
    server = Server()
    server.down = [(0, 200)]
    h = desk(tmp_path, clock=LateSync(15.0, 25.0), state=OFF_STATE, until=400,
             server=server)
    assert h.run() == 0
    assert h.runner.wake
    first = h.painted[0]
    assert (first.purpose, first.kind, first.exempt) == ("routine", "full", True)
    assert 200 <= first.t0 < 206
    assert what(first.frame) == "view:habits"
    assert not any("waking" in s for s in h.statuses())
    checks(h)


def test_a_wake_with_the_server_down_for_long_says_so(tmp_path):
    server = Server()
    server.down = [(0, 2000)]
    h = desk(tmp_path, clock=LateSync(15.0, 25.0), state=OFF_STATE, until=900,
             server=server)
    assert h.run() == 0
    assert h.painted == []
    # The 5 s startup retry ends 600 s into the process's life.
    late = [b.t - a.t for a, b in zip(h.requests, h.requests[1:])
            if a.t >= 15.0 + P.STARTUP_WINDOW_S]
    assert late and min(late) >= P.ERROR_RETRY_S - 0.01
    assert any("waking: the server is not answering" in s for s in h.statuses())
    checks(h)


def test_a_restart_in_the_same_boot_does_not_wake_again(tmp_path):
    s = dataclasses.replace(OFF_STATE, painted_end_bt=100.0, attempt_start_bt=95.0,
                            full_end_bt=100.0, view="calendar")
    h = desk(tmp_path, start=150.0, state=s, until=200)
    assert h.run() == 0
    assert not h.runner.wake
    assert h.runner.ui.view == "calendar"
    assert h.runner.bucket.tokens == 1
    checks(h)


def test_t11b_a_prompt_before_the_wake_paint_does_not_spend_its_exemption(tmp_path):
    """m12: the wake's floor exemption is the first VIEW paint's."""
    server = Server()
    server.down = [(0, 100)]
    h = desk(tmp_path, clock=LateSync(15.0, 25.0), state=OFF_STATE, keys=hold(60),
             until=600, server=server)
    assert h.run() == 0
    assert [p.purpose for p in h.painted] == ["prompt", "leave", "routine"]
    routine = h.painted[2]
    assert routine.exempt
    assert routine.t0 < h.painted[1].t1 + P.MIN_REFRESH_S
    assert routine.t0 == pytest.approx(next(f.t for f in h.requests if f.t >= 100)
                                       + server.render_s)
    checks(h)


def test_a_wake_spends_its_floor_exemption_on_the_first_view_paint_only(tmp_path):
    server = Server(refresh_s=300)
    server.version = lambda view, t: int(t // 300) + 1
    h = desk(tmp_path, clock=LateSync(15.0, 25.0), state=OFF_STATE,
             keys=tap(290), until=700, server=server)
    assert h.run() == 0
    assert [p.purpose for p in h.painted][:4] == ["routine", "strip", "page", "routine"]
    page, routine = h.painted[2], h.painted[3]
    assert routine.t0 >= page.t1 + P.MIN_REFRESH_S
    checks(h)


def test_t11c_a_wake_on_a_legacy_display_leaves_the_off_screen_at_once(tmp_path):
    h = desk(tmp_path, clock=LateSync(15.0, 25.0), state=OFF_STATE, until=400,
             server=Server(switchable=False, refresh_s=300))
    assert h.run() == 0
    first = h.painted[0]
    assert what(first.frame) == "legacy" and first.exempt
    assert first.t0 < 27
    checks(h)


def test_t12a_a_sync_during_the_gate_wait_fetches_without_spinning(tmp_path):
    h = desk(tmp_path, clock=LateSync(20.0, 250.0), until=320)
    assert h.run() == 0
    assert 250 <= h.requests[0].t < 250 + P.CLOCK_CHECK_S + 0.01
    assert len(h.waits) < 200
    checks(h)


def test_t12b_before_the_gate_opens_a_hold_works_and_a_tap_does_not(tmp_path):
    """m5: the prompt is not "the first paint" a tap needs."""
    clock = Clock(20.0)
    clock.synced = False
    h = desk(tmp_path, clock=clock, keys=hold(60) + tap(100), until=320)
    assert h.run() == 0
    assert [p.purpose for p in h.painted] == ["prompt", "leave", "routine"]
    assert h.painted[1].frame == P.WHITE
    assert all(f.t >= P.CLOCK_SYNC_GRACE_S for f in h.requests)
    checks(h)


def test_t13a_the_idle_return_waits_for_the_floor_and_costs_no_token(tmp_path):
    h = desk(tmp_path, keys=tap(445.4), until=700, idle_s=60,
             server=Server(refresh_s=300))
    h.at(460, set_tokens(h, 0))
    assert h.run() == 0
    strip, page, back = h.painted[1:4]
    assert (strip.purpose, page.purpose, back.purpose) == ("strip", "page", "routine")
    assert back.frame == view_frame("habits")
    assert back.t0 >= page.t1 + P.MIN_REFRESH_S
    assert h.runner.ui.view == "habits"
    assert h.runner.bucket.tokens == 0      # it needed none
    checks(h)


def test_t13b_the_idle_return_does_not_come_during_the_prompt(tmp_path):
    h = desk(tmp_path, keys=tap(400) + hold(450), until=520, idle_s=60)
    assert h.run() == 0
    assert key_paints(h) == [("strip", "partial"), ("page", "fast"), ("prompt", "fast"),
                             ("leave", "fast")]
    assert h.painted[-1].frame == view_frame("now")
    assert [f.mode for f in fetched(h)] == ["now"]
    checks(h)


def test_t13c_the_idle_return_does_not_come_during_the_power_off_grace(tmp_path):
    h = desk(tmp_path, keys=tap(400) + hold(440) + tap(445), until=640, idle_s=60,
             path_unit=False)
    assert h.run() == 0
    assert key_paints(h)[-2:] == [("off", "full"), ("leave", "fast")]
    assert h.painted[-1].frame == view_frame("now")
    assert [f.mode for f in fetched(h)] == ["now"]
    checks(h)


# ── refresh kinds ────────────────────────────────────────────────────────────

def test_t14_the_batch_guard_turns_quick_refresh_off(tmp_path):
    clock = Clock(20.0)
    h = desk(tmp_path, clock=clock, keys=tap(400) + tap(420) + hold(440), until=480,
             panel=FakePanel(clock, refresh_s={"partial": 1.4}))
    assert h.run() == 0
    assert key_paints(h) == [("strip", "partial"), ("page", "full"), ("page", "full"),
                             ("prompt", "full"), ("leave", "full")]
    assert P.load_state(tmp_path).quick_disabled is True
    assert any("fast refresh is off: this panel looks like a pre-2023 batch" in s
               for s in h.statuses())
    checks(h)


@pytest.mark.parametrize("count, expected", [
    (3, [("strip", "partial"), ("page", "fast"), ("prompt", "fast"), ("leave", "full")]),
    (4, [("page", "fast"), ("prompt", "fast"), ("leave", "full")]),
    (5, [("page", "full"), ("prompt", "fast"), ("leave", "fast")]),
])
def test_t15_full_every_five_and_the_prompt_always_fast(tmp_path, count, expected):
    h = desk(tmp_path, keys=tap(400) + hold(420), until=460)
    h.at(390, set_fast_count(h, count))
    assert h.run() == 0
    assert key_paints(h, 390) == expected
    checks(h)


def test_under_refresh_full_every_paint_is_full_and_there_are_no_strips(tmp_path):
    h = desk(tmp_path, keys=tap(400) + hold(420), until=460, refresh="full")
    assert h.run() == 0
    assert key_paints(h, 390) == [("page", "full"), ("prompt", "full"), ("leave", "full")]
    assert set(h.panel.modes) == {"full"}
    checks(h)


def test_t16_the_23_hour_repaint_counts_from_the_last_full_refresh(tmp_path):
    h = desk(tmp_path, keys=tap(400) + tap(600), until=84_000)
    assert h.run() == 0
    first, forced = h.painted[0], h.painted[-1]
    assert [p.kind for p in h.painted[1:-1]] == ["partial", "fast", "partial", "fast"]
    assert (forced.purpose, forced.kind) == ("routine", "full")
    assert first.t1 + P.FORCE_REPAINT_S <= forced.t0 <= first.t1 + P.FORCE_REPAINT_S + 1
    assert forced.frame == view_frame("calendar")
    checks(h)


# ── the key held down, the background, liveness ──────────────────────────────

def test_a_press_blocks_a_routine_paint_until_it_is_let_go(tmp_path):
    """§4.10: `pressed` blocks a routine paint until the release; a press of
    0.6–1.0 s is no gesture at all."""
    server = Server(refresh_s=300, render_s=1.0)
    server.version = lambda view, t: 1 if t < 500 else 2
    fetch_at = 200 + 1.0 + PAINT_COST + 300
    h = desk(tmp_path, keys=[(fetch_at + 0.5, 1), (fetch_at + 1.3, 0)], until=fetch_at + 60,
             server=server)
    assert h.run() == 0
    [routine] = [p for p in h.painted if p.t0 > 300]
    assert routine.purpose == "routine" and routine.frame == view_frame("habits", 2)
    assert routine.t0 >= fetch_at + 1.3
    assert len(fetched(h, 300)) == 2        # fetched again once let go
    assert h.runner.ui.mode == "browse"
    checks(h)


def test_a_press_during_a_key_page_fetch_puts_the_page_back(tmp_path):
    """§4.11 M3: the drain before a paint sees the press; the action goes back
    unpainted, and the hold's prompt is the next refresh."""
    press = 402.0
    h = desk(tmp_path, keys=tap(400) + hold(press), until=440)
    assert h.run() == 0
    [page_fetch] = [f for f in fetched(h, 401) if f.mode is not None and f.t <= press]
    assert page_fetch.t <= press < page_fetch.t + 0.4      # the press lands mid-fetch
    assert not [p for p in h.painted if press <= p.t0 < press + P.HOLD_S]
    [prompt] = [p for p in h.painted if p.purpose == "prompt"]
    assert prompt.t0 == pytest.approx(press + P.HOLD_S)
    checks(h)


def test_a_hold_during_a_slow_key_page_fetch_comes_before_the_page(tmp_path):
    """§4.11 M3: no paint starts while the key is down until the hold is
    seen; the page waits behind the prompt and its way back."""
    h = desk(tmp_path, keys=tap(400) + hold(402.3, 1.3), until=440,
             server=Server(render_s=1.0))
    assert h.run() == 0
    assert not [p for p in h.painted if 402.3 <= p.t0 < 402.3 + P.HOLD_S]
    assert key_paints(h, 400) == [("strip", "partial"), ("prompt", "fast"),
                                  ("leave", "fast"), ("page", "fast")]
    [prompt] = [p for p in h.painted if p.purpose == "prompt"]
    assert prompt.t0 == pytest.approx(402.3 + P.HOLD_S)
    checks(h)


def test_a_tap_and_a_hold_during_a_page_paint_leave_no_strip_before_the_prompt(tmp_path):
    """_collapse: a strip queued before a prompt is dropped, so the prompt
    follows the page at once."""
    h = desk(tmp_path, keys=tap(400) + tap(402.3) + hold(402.7, 1.3), until=440)
    assert h.run() == 0
    paints = [p for p in h.painted if p.t0 >= 400]
    assert [p.purpose for p in paints[:3]] == ["strip", "page", "prompt"]
    page, prompt = paints[1], paints[2]
    assert page.t0 < 402.3 and 402.7 + 1.3 < page.t1     # both presses inside the page paint
    assert prompt.t0 == pytest.approx(page.t1)
    checks(h)


def test_no_background_fetch_while_a_page_is_due(tmp_path):
    """§4.8 step 6: the coalesce wait is not a gap for the background."""
    h = desk(tmp_path, keys=tap(205.5), until=260, server=Server(render_s=1.0))
    assert h.run() == 0
    [page] = [p for p in h.painted if p.purpose == "page"]
    assert [f.mode for f in h.requests if 205.5 <= f.t < page.t0] == ["now"]
    checks(h)


def test_the_way_back_from_the_prompt_costs_no_token(tmp_path):
    h = desk(tmp_path, keys=hold(400), until=430)
    assert h.run() == 0
    assert key_paints(h, 390) == [("prompt", "fast"), ("leave", "fast")]
    assert h.runner.bucket.tokens == P.KEY_BURST - 1
    checks(h)


def test_only_the_hold_is_charged_when_tokens_remain(tmp_path):
    h = desk(tmp_path, keys=hold(400), until=440)
    h.at(390, set_tokens(h, 5))
    assert h.run() == 0
    assert key_paints(h, 390) == [("prompt", "fast"), ("leave", "fast")]
    assert h.runner.bucket.tokens == 4
    checks(h)


def test_a_failed_key_page_keeps_the_earlier_routine_fetch(tmp_path):
    """§4.11 m1: after a healthy answer a failed key Page may pull the routine
    fetch in, never push it back: it stays at the floor after the strip."""
    server = Scripted(lambda t, mode, screen: P.Refused("HTTP 500", 500)
                      if screen is None and 370 <= t < 375 else None, refresh_s=180)
    h = desk(tmp_path, keys=tap(370), until=1400, server=server)
    assert h.run() == 0
    [strip] = [p for p in h.painted if p.purpose == "strip"]
    page, routine = [f for f in fetched(h, 370) if f.screen is None][:2]
    assert 370 <= page.t < 375 and page.mode == "now"
    assert routine.t == pytest.approx(strip.t1 + P.MIN_REFRESH_S, abs=0.5)
    checks(h)


def test_no_tick_while_the_key_is_down(tmp_path):
    """The key down holds Ui's deadlines: the first tap's page is not fetched
    under the second press, and the second strip starts at its release."""
    h = desk(tmp_path, keys=tap(400) + tap(401.5, 0.4), until=440,
             server=Server(render_s=1.0))
    assert h.run() == 0
    assert fetched(h, 401.5, mode="now") == []
    strips = [p for p in h.painted if p.purpose == "strip"]
    assert len(strips) == 2
    assert strips[1].t0 == pytest.approx(401.9, abs=0.05)
    checks(h)


def test_a_stuck_key_is_forgotten_and_the_loop_goes_on(tmp_path, caplog):
    h = desk(tmp_path, keys=[(400.0, 1)], until=440, holds_ok=False)
    with caplog.at_level(logging.WARNING, logger="smylte-panel"):
        assert h.run() == 0
    assert not h.runner.gestures.down
    assert any("taking it as stuck" in m for m in caplog.messages)
    checks(h)


def test_background_fetches_are_one_at_a_time_apart_and_never_paint(tmp_path):
    h = desk(tmp_path, screens=(), until=260)
    assert h.run() == 0
    bg = h.requests[1:]
    assert [(f.screen, f.mode) for f in bg] == [(k, None) for k in P.SCREENS] + [
        (None, "now"), (None, "calendar")]
    ends = [f.t + (0.05 if f.screen else 0.4) for f in h.requests]
    assert all(f.t - end >= P.BG_GAP_S for f, end in zip(bg, ends))
    assert [p.purpose for p in h.painted] == ["routine"]
    assert set(h.runner.strip_cache) == set(P.VIEWS)
    checks(h)


def test_a_view_with_no_strip_is_prefetched_no_more_than_once_a_minute(tmp_path):
    """§4.12: the display is turned to 90 while a strip is still to fetch. The
    view frame that comes back has no strip, and counts as a failed item."""
    server = Server(refresh_s=300)
    server.down = [(206.0, 208.0)]
    h = desk(tmp_path, until=500, server=server)
    h.at(230, lambda: setattr(server, "rotation", 90))
    assert h.run() == 0
    nows = [f.t for f in h.requests if f.mode == "now"]
    assert nows[0] < 208 and len(nows) >= 3
    assert all(b - a >= P.BG_RETRY_S - 0.01 for a, b in zip(nows, nows[1:]))
    assert "now" not in h.runner.strip_cache
    assert [p.purpose for p in h.painted] == ["routine"]
    checks(h)


def test_the_cached_screens_are_fetched_again_every_hour(tmp_path):
    """§4.8 step 6: a screen cached on disk is revalidated after
    SCREEN_REVALIDATE_S, and the new one replaces it in memory and on disk."""
    new = bytes([0xC3]) * P.BUF_BYTES
    server = Scripted(lambda t, mode, screen: P.Frame(new, tag(new), 3600)
                      if screen == "confirm" and t > 1000 else None)
    h = desk(tmp_path, until=P.SCREEN_REVALIDATE_S + 400, server=server)
    assert h.run() == 0
    [confirm] = [f.t for f in h.requests if f.screen == "confirm"]
    assert confirm >= 20 + P.SCREEN_REVALIDATE_S
    assert h.runner.screens["confirm"] == new
    assert P.load_screen(tmp_path, "confirm") == new
    checks(h)


def test_the_routine_floor_holds_with_key_refreshes_in_between(tmp_path):
    server = Server(refresh_s=300)
    server.version = lambda view, t: 1 + int(t // 250)
    keys = [k for t in range(400, 3000, 420) for k in tap(t)]
    h = desk(tmp_path, keys=keys, until=3000, server=server)
    assert h.run() == 0
    assert sum(p.purpose == "routine" for p in h.painted) >= 3
    assert sum(p.purpose == "page" for p in h.painted) >= 5
    checks(h)


def test_the_harness_fails_a_loop_that_spins(tmp_path):
    h = Harness(tmp_path, Clock(), new_frames())
    for _ in range(FakeEvents.SPIN_LIMIT + 1):
        assert h.events.wait(0) == []
    with pytest.raises(AssertionError, match="spinning"):
        h.events.wait(0)


class _PipeCollector:
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


@pytest.mark.parametrize("case", ["late", "no-clock"])
def test_the_real_events_find_a_key_that_appears_late(tmp_path, monkeypatch, caplog, case):
    """§4.10: the key device appearing late is found and used; one whose
    clock cannot be set (EVIOCSCLOCKID) is no key, logged once, and the loop
    runs on. Real Events, on a fake sysfs, a pipe for the node and select()
    on the fake clock."""
    clock = Clock(20.0)
    sysfs = tmp_path / "sys"
    sysfs.mkdir()
    collector = _PipeCollector()
    r, w = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)

    def open_key(path):
        if case == "no-clock":
            raise OSError(errno.ENOTTY, "Inappropriate ioctl for device")
        return r

    def make_node():
        dev = sysfs / "event4" / "device"
        (dev / "capabilities").mkdir(parents=True)
        (dev / "name").write_text("pwr_button\n")
        (dev / "capabilities" / "ev").write_text("3\n")
        (dev / "capabilities" / "key").write_text("10000000000000 0\n")

    def edge(value):
        def write():
            sec = int(clock.t)
            os.write(w, P.INPUT_EVENT.pack(sec, round((clock.t - sec) * 1e6),
                                           P.EV_KEY, P.KEY_POWER, value))
        return write

    script = [(250.0, make_node), (400.0, edge(1)), (400.12, edge(0)),
              (440.0, lambda: collector.send(signal.SIGTERM))]

    def select(rl, wl, xl, timeout):
        target = clock.t + timeout
        if script and script[0][0] <= target:
            clock.t = max(clock.t, script[0][0])
            script.pop(0)[1]()
        else:
            clock.t = target
        return [], [], []

    monkeypatch.setattr(P, "select", types.SimpleNamespace(select=select))
    monkeypatch.setattr(P, "_many_keys_logged", False)
    for kind, body in SCREEN_BODIES.items():
        P.save_screen(tmp_path, kind, body)
    h = Harness(tmp_path, clock, server=Server(), key="auto")
    real = P.Events(collector, sysfs_root=sysfs, open_key=open_key,
                    boottime=clock.boottime, key_enabled=True)

    class Counted:
        zero = 0

        def wait(self, timeout):
            h.waits.append(timeout)
            if timeout > 0:
                h.unwaited = 0
                Counted.zero = 0
            else:
                Counted.zero += 1
                assert Counted.zero < 50, "spinning"
            return real.wait(timeout)

        def __getattr__(self, name):
            return getattr(real, name)

    h.deps.events = Counted()
    try:
        with caplog.at_level(logging.INFO, logger="smylte-panel"):
            assert h.run() == 0
    finally:
        os.close(w)
        os.close(r)
        os.close(collector.r)
        os.close(collector.w)
    assert h.painted[0].purpose == "routine"
    # While there is no key it is looked for every KEY_RETRY_S, so no wait is longer.
    assert max(t for t in h.waits[:40]) <= P.KEY_RETRY_S
    if case == "late":
        assert real.key_open
        assert [p.purpose for p in h.painted[1:]] == ["strip", "page"]
    else:
        assert not real.key_open
        assert len(h.painted) == 1
        assert len([m for m in caplog.messages if m.startswith("key: cannot open")]) == 1
    checks(h)


# ── start-up checks ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("deps, says", [
    (dict(holds_ok=False), "holding the key does nothing"),
    (dict(logind_present=False), "logind still powers off on a press"),
    (dict(key="off", logind_present=True), "the key does nothing — re-run panel-setup.sh"),
])
def test_what_is_wrong_with_the_setup_is_said_at_start(tmp_path, deps, says):
    h = desk(tmp_path, until=30, **deps)
    assert h.run() == 0
    assert any(says in s for s in h.statuses())


def test_a_poweroff_request_left_over_is_cleared_at_start(tmp_path):
    h = desk(tmp_path, until=30)
    assert h.run() == 0
    assert h.cleared == [20.0]


def test_a_hold_does_nothing_without_a_run_directory(tmp_path):
    h = desk(tmp_path, keys=hold(400), until=440, holds_ok=False)
    assert h.run() == 0
    assert [p.purpose for p in h.painted] == ["routine"]
    checks(h)


def test_a_restart_onto_an_unchanged_page_still_takes_taps(tmp_path):
    """The tap filter needs a view frame known to be on the glass. A restart
    whose first fetch is a 304 paints nothing, yet the glass is known: taps
    must work at once, not only after the page next changes."""
    clock = Clock(20.0)
    h1 = desk(tmp_path, clock=clock, until=400)
    assert h1.run() == 0
    assert [p.purpose for p in h1.painted] == ["routine"]
    clock.t = 1000.0
    h2 = desk(tmp_path, clock=clock, keys=tap(1100), until=1200)
    assert h2.run() == 0
    assert "routine" not in [p.purpose for p in h2.painted]     # the 304: no repaint
    pages = [p for p in h2.painted if p.purpose == "page"]
    assert pages, [(p.purpose, p.kind) for p in h2.painted]
    assert h2.runner.ui.view == "now"
    checks(h2)


def test_a_logind_warning_stays_on_the_status_line_after_a_healthy_answer(tmp_path):
    """A notice that needs the owner (re-run panel-setup.sh) must not vanish
    at the first 304, as an ordinary problem does."""
    h = desk(tmp_path, until=4000, logind_present=False)
    assert h.run() == 0
    statuses = [n for n in h.notes if n.startswith("STATUS=")]
    assert statuses[-1].startswith("STATUS=showing "), statuses
    assert "logind still powers off on a press" in statuses[-1], statuses


def test_the_batch_guard_stays_on_the_status_line(tmp_path):
    state = P.State(quick_disabled=True)
    h = desk(tmp_path, until=400, state=state)
    assert h.run() == 0
    statuses = [n for n in h.notes if n.startswith("STATUS=")]
    assert "fast refresh is off" in statuses[-1], statuses



def test_the_resting_count_is_corrected_once_the_page_takes_the_last_token(tmp_path):
    """Item 22: the first rejected tap says "try again in ~39 s" while one
    token is left; the page then takes it, and the count must be sent again
    (about 85 s), not left at 39 until the bucket refills."""
    import re
    h = desk(tmp_path, keys=tap(400) + tap(400.3), until=520)
    h.at(390, set_tokens(h, 2))
    assert h.run() == 0
    ns = [int(m.group(1)) for s in h.statuses()
          for m in [re.search(r"try again in (\d+) s", s)] if m]
    assert ns and ns[0] <= 45, ns
    assert any(n >= 80 for n in ns[1:]), ns
    checks(h)


def test_a_key_page_that_finds_desk_key_off_falls_back_at_once_inside_a_429(tmp_path):
    """B1 with `healthy` False: a routine 429 is running when the owner turns
    Desk key off and taps. The page gets views-off; the legacy fetch must
    follow at once, not wait out the 429's hour."""
    def rule(t, mode, screen):
        if screen is None and mode is not None and 380 <= t < 390:
            return P.Throttled(3600)
        return None
    srv = Scripted(rule, refresh_s=180)
    h = desk(tmp_path, keys=tap(400), until=430, server=srv)
    h.at(395, lambda: setattr(srv, "switchable", False))
    assert h.run() == 0
    assert not h.runner.views
    page = next(f for f in fetched(h, 399) if f.mode == "now")
    legacy = [f for f in fetched(h, page.t) if f.mode is None and f.screen is None]
    assert legacy and legacy[0].t - page.t < 2.0, fetched(h, 380)
    checks(h)


# ── updating from the key ────────────────────────────────────────────────────
#
# Design §3 and §6, on the real run(): the desk as above, the update units
# installed (update_present) and a FakeUpdater for the root updater, whose
# result goes through a real file and the client's own reader. A hold at 400
# draws "Shut down?" with the update hint (401.0–404.2), a second hold at 405
# draws "Update?" (406.0–409.2) and a tap at 410 draws Updating… and sends
# the request (about 413.3). Each test ends with checks(), which also holds
# every update request to a tap on a drawn "Update?" and to the end of an
# Updating paint.

def update_keys(t: float) -> list[tuple[float, int]]:
    """Hold, hold again once "Shut down?" is drawn, tap once "Update?" is."""
    return hold(t) + hold(t + 5) + tap(t + 10)


def updater(running_after: float = 3.0, final_after: float = 40.0, final="updated"):
    """An updater that writes running a little after each request, then its
    outcome (`final`, or one per request). Like the real file, the result is
    the latest one written, so an earlier request's outcome stays until the
    next request's updater writes."""
    def script(now, requests):
        out = None
        for i, (t, rid) in enumerate(requests):
            outcome = final if isinstance(final, str) else final[i]
            if now >= t + final_after:
                out = P.UpdateResult(rid, t + final_after, outcome)
            elif now >= t + running_after:
                out = P.UpdateResult(rid, t + running_after, "running")
        return out
    return script


def after(h: Harness, t: float = 300.0) -> list[tuple[str, str | None]]:
    return [(p.purpose, what(p.frame)) for p in h.painted if p.t0 > t]


@pytest.mark.parametrize("outcome", P.NOTICES)
def test_u1_an_update_draws_updating_then_its_outcome_then_the_view(tmp_path, outcome):
    """§1: the two prompts, Updating… with the request sent at its end, the
    outcome once the updater writes it, and after NOTICE_S the view from
    before the first prompt. A tap or a hold during Updating… and a hold
    during the notice do nothing."""
    keys = update_keys(400) + tap(420) + hold(425) + hold(470)
    h = desk(tmp_path, keys=keys, until=600, update_present=True,
             update=updater(final=outcome))
    assert h.run() == 0
    assert after(h) == [("prompt", "confirm-update"), ("prompt", "update"),
                        ("update", "updating"), ("notice", outcome), ("leave", "view:habits")]
    updating, notice, leave = h.painted[3:6]
    [(t_req, rid)] = h.updater.requests
    assert rid == f"{updating.t1:.3f}" and t_req == pytest.approx(updating.t1)
    assert t_req + 40 <= notice.t0 <= t_req + 40 + P.UPDATE_POLL_S + 0.01
    assert leave.t0 == pytest.approx(notice.t1 + P.NOTICE_S, abs=0.01)
    assert leave.frame == view_frame("habits")
    assert h.runner.ui.mode == "browse"
    statuses = h.statuses()
    assert any(s.startswith("STATUS=updating (asked for with the key)") for s in statuses)
    if outcome == "update-failed":
        assert P.FAILED_NOTE in h.runner.notes
        assert "update failed" in statuses[-1]
    else:
        assert P.FAILED_NOTE not in h.runner.notes
        assert statuses[-1].startswith("STATUS=showing")
    checks(h)


@pytest.mark.parametrize("press", [402.0, 403.5])
def test_u2_a_second_hold_pressed_while_shut_down_is_drawn_asks_update(tmp_path, press):
    """§3.3: its press came after the first hold's; the loop takes the hold
    only once the draw is over, whether it was let go during the draw or not."""
    h = desk(tmp_path, keys=hold(400) + hold(press) + tap(415), until=480,
             update_present=True, update=updater())
    assert h.run() == 0
    assert after(h)[:3] == [("prompt", "confirm-update"), ("prompt", "update"),
                            ("update", "updating")]
    first, second = h.painted[1:3]
    assert first.t0 < press < first.t1
    assert len(h.updater.requests) == 1
    checks(h)


def test_u3_a_tap_pressed_before_update_was_drawn_is_ignored(tmp_path):
    h = desk(tmp_path, keys=hold(400) + hold(405) + tap(407.0), until=440,
             update_present=True, update=updater())
    assert h.run() == 0
    assert after(h) == [("prompt", "confirm-update"), ("prompt", "update"),
                        ("leave", "view:habits")]
    prompt, leave = h.painted[2:4]
    assert leave.t0 == pytest.approx(prompt.t1 + P.PROMPT_S, abs=0.01)
    assert h.updater.requests == [] and h.poweroffs == []
    checks(h)


@pytest.mark.parametrize("why", ["tokens", "units", "unknown", "screens"])
def test_u4_without_the_offer_a_hold_asks_plain_shut_down_and_a_second_does_nothing(
        tmp_path, caplog, why):
    """§3.4: the update is offered only with holds, the units, every update
    screen cached and UPDATE_TOKENS. Otherwise the hold draws the plain
    "Shut down?", which a second hold does nothing to."""
    kw = dict(update_present={"units": False, "unknown": None}.get(why, True),
              update=updater())
    screens = SCREEN_FRAMES
    if why == "screens":
        screens = (CONFIRM, OFF, UPDATE_PROMPT, UPDATING)
        kw["server"] = Server(refuse_screens=set(P.UPDATE_SCREENS))
    h = desk(tmp_path, keys=hold(400) + hold(405) + hold(430), screens=screens,
             until=480, **kw)
    if why == "tokens":
        h.at(390, set_tokens(h, P.UPDATE_TOKENS - 1))
    with caplog.at_level(logging.INFO, logger="smylte-panel"):
        assert h.run() == 0
    assert after(h) == [("prompt", "confirm"), ("leave", "view:habits"),
                        ("prompt", "confirm"), ("leave", "view:habits")]
    assert h.updater.requests == [] and h.poweroffs == []
    said = [m for m in caplog.messages if "the update is not offered yet" in m]
    assert len(said) == (why == "screens")
    assert any("the key cannot update: the update units are not installed" in s
               for s in h.statuses()) == (why == "units")
    checks(h)


@pytest.mark.parametrize("tokens", [2, 3, P.KEY_BURST])
def test_u5_the_update_is_offered_only_with_its_three_tokens_and_takes_them(tmp_path,
                                                                           tokens):
    """The budget: "Shut down?", "Update?" and Updating… cost three tokens,
    taken at the two holds. With fewer the hold draws plain "Shut down?", and
    the tap then shuts down, as it does on either."""
    h = desk(tmp_path, keys=update_keys(400), until=600, update_present=True,
             update=updater())
    h.at(390, set_tokens(h, tokens))
    left = []
    h.at(409.5, lambda: left.append(h.runner.bucket.tokens))
    assert h.run() == 0
    if tokens < 3:
        assert after(h) == [("prompt", "confirm"), ("off", "off")]
        assert len(h.poweroffs) == 1 and h.updater.requests == []
        assert left == [tokens - 1]
    else:
        assert after(h)[:4] == [("prompt", "confirm-update"), ("prompt", "update"),
                                ("update", "updating"), ("notice", "updated")]
        assert len(h.updater.requests) == 1 and h.poweroffs == []
        assert left == [tokens - 3]
    checks(h)


def test_u6_a_second_update_in_the_same_process_waits_for_its_own_result(tmp_path):
    """F1: the first update's outcome is still in the result file when the
    second is asked for. It does not answer the second's wait: only the
    second request's own result does."""
    keys = update_keys(400) + tap(460) + update_keys(700)
    h = desk(tmp_path, keys=keys, until=900, update_present=True,
             update=updater(final=["up-to-date", "updated"]))
    assert h.run() == 0
    assert after(h) == [
        ("prompt", "confirm-update"), ("prompt", "update"), ("update", "updating"),
        ("notice", "up-to-date"), ("leave", "view:habits"),
        ("prompt", "confirm-update"), ("prompt", "update"), ("update", "updating"),
        ("notice", "updated"), ("leave", "view:habits")]
    (_, rid1), (t2, rid2) = h.updater.requests
    assert rid1 != rid2
    [second] = [p for p in h.painted if p.purpose == "notice" and p.t0 > t2]
    assert t2 + 40 <= second.t0 <= t2 + 40 + P.UPDATE_POLL_S + 0.01
    checks(h)


@pytest.mark.parametrize("stop_at", [410.12, 411.0])
def test_u7_a_stop_as_the_update_is_confirmed_or_drawn_still_draws_and_requests_it(
        tmp_path, stop_at):
    """§3.4: a stop with the Update queued or being drawn lets Updating… be
    drawn and the request be sent, and then ends the process with EX_OK. The
    new process takes the wait over (§3.5)."""
    h = desk(tmp_path, keys=update_keys(400), signals=[(stop_at, signal.SIGTERM)],
             update_present=True, update=updater())
    assert h.run() == 0
    assert after(h) == [("prompt", "confirm-update"), ("prompt", "update"),
                        ("update", "updating")]
    [(t_req, _)] = h.updater.requests
    assert h.clock.t == pytest.approx(t_req, abs=0.01)
    assert h.runner.ui.mode == "updating"
    checks(h)


def test_u8_a_request_that_cannot_be_sent_shows_update_failed_at_once(tmp_path):
    h = desk(tmp_path, keys=update_keys(400), until=600, update_present=True,
             update=updater(), update_request="failed: no run directory")
    assert h.run() == 0
    assert after(h) == [("prompt", "confirm-update"), ("prompt", "update"),
                        ("update", "updating"), ("notice", "update-failed"),
                        ("leave", "view:habits")]
    updating, notice = h.painted[3:5]
    assert notice.t0 == pytest.approx(updating.t1, abs=0.01)
    assert any("could not update: failed: no run directory" in s for s in h.statuses())
    assert P.FAILED_NOTE in h.runner.notes
    checks(h)


@pytest.mark.parametrize("line", [
    None,                                   # nothing acts on the request
    "{rid} {at:.3f} running",               # no newline
    "{rid} {at:.1f} updated\n",
    "{rid} {at:.3f} finished\n",
    "garbage\n",
], ids=["absent", "no-newline", "short-at", "unknown-state", "garbage"])
def test_u9_with_no_answer_the_update_fails_after_update_start_s(tmp_path, line):
    """A result that is absent or malformed answers nothing; at UPDATE_START_S
    the request is withdrawn and Update failed is shown."""
    def script(now, requests):
        if line is None or not requests:
            return None
        t, rid = requests[-1]
        return line.format(rid=rid, at=t + 3)

    h = desk(tmp_path, keys=update_keys(400), until=600, update_present=True,
             update=script)
    assert h.run() == 0
    assert after(h)[3:] == [("notice", "update-failed"), ("leave", "view:habits")]
    [(t_req, _)] = h.updater.requests
    notice = h.painted[4]
    assert t_req + P.UPDATE_START_S <= notice.t0 <= t_req + P.UPDATE_START_S + P.UPDATE_POLL_S
    assert h.updater.cleared[-1] == pytest.approx(notice.t0, abs=0.01)
    assert any(f"nothing acted on the request within {P.UPDATE_START_S} s" in s
               for s in h.statuses())
    checks(h)


def test_u10_an_update_that_stays_running_fails_after_update_max_s(tmp_path):
    """F2: a repeated "running" is held to the deadline too, so an updater
    killed outright does not leave Updating… on the glass for ever."""
    def script(now, requests):
        if not requests or now < requests[-1][0] + 3:
            return None
        t, rid = requests[-1]
        return P.UpdateResult(rid, t + 3, "running")

    h = desk(tmp_path, keys=update_keys(400), until=400 + P.UPDATE_MAX_S + 300,
             update_present=True, update=script)
    assert h.run() == 0
    assert after(h)[3:] == [("notice", "update-failed"), ("leave", "view:habits")]
    [(t_req, _)] = h.updater.requests
    notice = h.painted[4]
    first_running = next(t for t in h.updater.reads if t >= t_req + 3)
    assert first_running + P.UPDATE_MAX_S <= notice.t0 \
        <= first_running + P.UPDATE_MAX_S + P.UPDATE_POLL_S
    assert any(f"still running after {P.UPDATE_MAX_S // 60} min" in s for s in h.statuses())
    # Nothing else was fetched or drawn while it waited.
    assert not [f for f in h.requests if t_req < f.t < notice.t0]
    checks(h)


UPDATING_STATE = P.State(glass_sha256=sha(UPDATING), painted_end_bt=500.0,
                         attempt_start_bt=496.0, complete=True, fast_count=2,
                         full_end_bt=200.0)


@pytest.mark.parametrize("result, notice, notice_at", [
    (None, "update-failed", 530.0 + P.UPDATE_START_S),
    ("running", "updated", 600.0),
    ("final", "updated", 530.0),
])
def test_u11_a_start_onto_updating_takes_the_wait_over(tmp_path, result, notice,
                                                      notice_at):
    """§3.5: the panel restarted by the update (or by a crash) finds Updating…
    on the glass. It waits for a result written after that paint, or fails
    after UPDATE_START_S with none; the notice goes back to Today, at once."""
    def script(now, requests):
        if result is None:
            return None
        if result == "running" and now < 600.0:
            return P.UpdateResult("500.000", 505.0, "running")
        return P.UpdateResult("500.000", 520.0 if result == "final" else 600.0, "updated")

    h = desk(tmp_path, start=530.0, state=UPDATING_STATE, until=800,
             update_present=True, update=script)
    assert h.run() == 0
    assert after(h, 0) == [("notice", notice), ("routine", "view:habits")]
    first, routine = h.painted
    assert notice_at <= first.t0 <= notice_at + P.UPDATE_POLL_S
    assert routine.t0 == pytest.approx(first.t1 + P.NOTICE_S + Server().render_s, abs=0.01)
    assert not [f for f in h.requests if f.t < first.t1 + P.NOTICE_S]
    checks(h)


def test_u12_a_start_onto_a_rollback_shows_update_failed(tmp_path):
    """§3.5: the new code drew its notice, then was rolled back; the old code
    starts onto that notice with the result rewritten after it."""
    state = dataclasses.replace(UPDATING_STATE, glass_sha256=sha(UPDATED))
    h = desk(tmp_path, start=530.0, state=state, keys=tap(560), until=700,
             update_present=True,
             update=lambda now, requests: P.UpdateResult("450.000", 520.0, "update-failed"))
    assert h.run() == 0
    assert after(h, 0) == [("notice", "update-failed"), ("routine", "view:habits")]
    notice, routine = h.painted
    assert notice.t0 == pytest.approx(530.0)
    assert routine.t0 == pytest.approx(560.12 + Server().render_s, abs=0.01)
    assert P.FAILED_NOTE in h.runner.notes
    checks(h)


@pytest.mark.parametrize("glass", ["view", "updating"])
def test_u13_a_result_from_before_the_last_paint_is_stale_at_start(tmp_path, glass):
    """§3.5: a result written before the glass's last paint answers nothing:
    a view stays as it is, and Updating… waits for a fresh one."""
    if glass == "view":
        body = view_frame("habits")
        state = dataclasses.replace(UPDATING_STATE, glass_sha256=sha(body), etag=tag(body),
                                    view="habits")
    else:
        state = UPDATING_STATE
    h = desk(tmp_path, start=530.0, state=state, until=700, update_present=True,
             update=lambda now, requests: P.UpdateResult("300.000", 450.0, "updated"))
    assert h.run() == 0
    if glass == "view":
        assert h.painted == []          # the 304, and no notice
        assert h.runner.ui.mode == "browse"
    else:
        assert after(h, 0) == [("notice", "update-failed"), ("routine", "view:habits")]
        assert h.painted[0].t0 >= 530.0 + P.UPDATE_START_S
    checks(h)


def test_u14_a_start_onto_the_off_screen_stays_in_browse(tmp_path):
    """The off screen is not Updating…: no wait, the view at once (F9's
    byte-equal screens would have taken the update path)."""
    state = dataclasses.replace(OFF_STATE, painted_end_bt=500.0, attempt_start_bt=495.0,
                                full_end_bt=500.0)
    h = desk(tmp_path, start=530.0, state=state, until=700, update_present=True)
    assert h.run() == 0
    assert h.runner.ui.mode == "browse" and not h.runner.update_wait
    assert after(h, 0) == [("routine", "view:habits")]
    assert h.painted[0].t0 == pytest.approx(530.0 + Server().render_s)
    checks(h)


def test_u15_a_notice_with_nothing_to_go_back_to_brings_the_view_at_once(tmp_path):
    """F5: a restart onto an unchanged view has drawn nothing, so the notice's
    way back has no glass to repaint. The view follows the tap at once,
    skipping the floor once, as the leave paint it replaces would have."""
    clock = Clock(20.0)
    h1 = desk(tmp_path, clock=clock, until=400)
    assert h1.run() == 0
    clock.t = 1000.0
    h2 = desk(tmp_path, clock=clock, keys=update_keys(1100) + tap(1160), until=1300,
              update_present=True, update=updater())
    assert h2.run() == 0
    assert after(h2, 0) == [("prompt", "confirm-update"), ("prompt", "update"),
                            ("update", "updating"), ("notice", "updated"),
                            ("routine", "view:habits")]
    notice, routine = h2.painted[3:5]
    assert routine.exempt
    assert routine.t0 == pytest.approx(1160.12 + Server().render_s, abs=0.01)
    assert routine.t0 < notice.t1 + P.MIN_REFRESH_S
    checks(h1, h2)


def test_u16_usr1_during_a_notice_redraws_the_view_in_full_when_it_ends(tmp_path):
    """USR1 forgets the glass, the one before the prompts too, so the notice's
    way back is the routine fetch, at once and in full."""
    h = desk(tmp_path, keys=update_keys(400), signals=[(460.0, signal.SIGUSR1)], until=600,
             update_present=True, update=updater(final="up-to-date"))
    assert h.run() == 0
    assert after(h) == [("prompt", "confirm-update"), ("prompt", "update"),
                        ("update", "updating"), ("notice", "up-to-date"),
                        ("routine", "view:habits")]
    notice, routine = h.painted[4:6]
    assert notice.t0 < 460.0 < notice.t1 + P.NOTICE_S
    assert (routine.kind, routine.exempt) == ("full", True)
    assert routine.t0 == pytest.approx(notice.t1 + P.NOTICE_S + Server().render_s, abs=0.01)
    checks(h)


def test_u17_a_notice_left_with_a_repaint_keeps_the_floor_for_the_next_view(tmp_path):
    """F5's allowance is only for a notice left with nothing to repaint. Here
    the way back repaints the view from before the prompts, and that leave
    paint was the allowance: the routine paint after it, with the view
    changed soon after and a short refresh, still waits for the floor."""
    server = Server(refresh_s=60)
    server.version = lambda view, t: 1 if t < 500 else 2       # the view changes at 500
    h = desk(tmp_path, keys=update_keys(400), until=700, server=server,
             update_present=True, update=updater(final="up-to-date", final_after=10))
    assert h.run() == 0
    assert after(h) == [("prompt", "confirm-update"), ("prompt", "update"),
                        ("update", "updating"), ("notice", "up-to-date"),
                        ("leave", "view:habits"), ("routine", "view:habits")]
    leave, routine = h.painted[5:7]
    assert not routine.exempt
    assert routine.t0 >= leave.t1 + P.MIN_REFRESH_S
    checks(h)


def test_u18_an_update_asked_for_during_the_last_ones_watch_waits_for_it(tmp_path):
    """F4: the first update's result is written before its watch, so a second
    request made soon after its notice finds that run still active, and the
    path unit starts the second run only once it ends. The request waits for
    that (UPDATE_WATCH_S after the first result, then UPDATE_START_S), instead
    of failing UPDATE_START_S after it was sent."""
    first = updater(final_after=10)

    def script(now, requests):
        if len(requests) < 2:
            return first(now, requests)
        (t1, _), (_, rid2) = requests
        done = t1 + 10                      # when the first run wrote `updated`
        if now >= done + 180:
            return P.UpdateResult(rid2, done + 180, "updated")
        if now >= done + 170:
            return P.UpdateResult(rid2, done + 170, "running")
        return first(now, requests[:1])

    keys = update_keys(400) + tap(440) + update_keys(484)
    h = desk(tmp_path, keys=keys, until=760, update_present=True, update=script)
    h.at(480, set_tokens(h, P.KEY_BURST))
    assert h.run() == 0
    assert after(h) == [
        ("prompt", "confirm-update"), ("prompt", "update"), ("update", "updating"),
        ("notice", "updated"), ("leave", "view:habits"),
        ("prompt", "confirm-update"), ("prompt", "update"), ("update", "updating"),
        ("notice", "updated"), ("leave", "view:habits")]
    (t1, _), (t2, _) = h.updater.requests
    done = t1 + 10
    # Without the wait, this request would have failed before its run began.
    assert t2 + P.UPDATE_START_S < done + 170 < done + P.UPDATE_WATCH_S + P.UPDATE_START_S
    [second] = [p for p in h.painted if p.purpose == "notice" and p.t0 > t2]
    assert done + 180 <= second.t0 <= done + 180 + P.UPDATE_POLL_S + 0.01
    assert not [t for t in h.updater.cleared if t > 300]      # the request was never withdrawn
    assert not [s for s in h.statuses() if "could not update" in s]
    assert P.FAILED_NOTE not in h.runner.notes
    checks(h)
