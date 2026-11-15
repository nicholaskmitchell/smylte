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

import contextlib
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
    """Stands in for epd.Panel: records each call, and each call costs time."""

    COSTS = {"init": INIT_COST, "display": DISPLAY_COST, "sleep": SLEEP_COST}
    PHASES = {"init": "init", "display": "refresh", "sleep": "power-off"}

    def __init__(self, clock: Clock, fail: dict | None = None):
        self.clock = clock
        self.fail = dict(fail or {})
        self.calls: list[tuple] = []
        self.phase = "idle"
        self.aborted_in = None

    def _step(self, name: str, extra=None) -> None:
        if name in self.PHASES:
            self.phase = self.PHASES[name]
        self.calls.append((name, self.clock.t, extra))
        if name in self.fail:
            raise self.fail[name]
        self.clock.t += self.COSTS.get(name, 0.0)

    def init(self) -> None:
        self._step("init")

    def display(self, frame: bytes) -> None:
        self._step("display", hashlib.sha256(frame).hexdigest())

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


class Harness:
    """P.Deps on fakes: a scripted fetch and a waiter that advances the clock."""

    def __init__(self, tmp_path, clock: Clock, responder, *, panel=None,
                 stop_after=None, signals=()):
        self.clock = clock
        self.responder = responder
        self.panel = panel or FakePanel(clock)
        self.stop_after = stop_after
        self.signals = list(signals)
        self.fetches: list[tuple[float, str | None]] = []
        self.notes: list[str] = []
        self.unwaited = 0       # fetches since the last real wait
        self.waits: list[float] = []
        self.deps = P.Deps(state_dir=tmp_path, panel=self.panel, epd=E,
                           fetch=self.fetch, wait=self.wait,
                           boottime=clock.boottime, walltime=clock.walltime,
                           synced=clock.synced_fn, notify=self.notify)

    def fetch(self, etag):
        # A loop that fetches without ever waiting would spin here for ever;
        # fail instead, so a regression turns CI red rather than hanging it.
        self.unwaited += 1
        assert self.unwaited <= 3, "fetched again and again without waiting"
        n = len(self.fetches)
        self.fetches.append((self.clock.t, etag))
        return self.responder(n, etag, self.clock)

    def wait(self, timeout):
        self.waits.append(timeout)
        if timeout > 0:             # wait(0) is run()'s drain, not a wait
            self.unwaited = 0
        if self.signals and self.signals[0][0] <= self.clock.t + timeout:
            at_t, signo = self.signals.pop(0)
            self.clock.t = max(self.clock.t, at_t)
            return signo
        # Only a real wait ends the run: wait(0) is run()'s drain, which loops
        # until nothing is pending, so it must see scheduled signals only.
        if timeout > 0 and self.stop_after is not None \
                and len(self.fetches) >= self.stop_after:
            return signal.SIGTERM
        self.clock.t += timeout
        return None

    def notify(self, msg):
        self.notes.append(msg)

    def run(self) -> int:
        return P.run(self.deps)


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


@pytest.fixture
def guarded_main():
    """Call P.main() with the root logger and the signal mask restored after:
    main() blocks signals and replaces the root logger's handlers."""
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
    after_frame = isinstance(result, P.NotModified)

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
    (P.State(complete=True, painted_end_bt=NOW_BT - 82800), NOW_BT, True, True),
    (P.State(complete=True, painted_end_bt=NOW_BT - 82799), NOW_BT, True, False),
    # A paint time later than now is from an earlier boot, so at least `now`
    # has passed since it: 23 h of this boot's uptime is enough on its own.
    (P.State(complete=True, painted_end_bt=NOW_BT + 5, painted_wall=None),
     NOW_BT, False, True),
    (P.State(complete=True, painted_end_bt=82800 + 5, painted_wall=None),
     82800, False, True),
    (P.State(complete=True, painted_end_bt=82799 + 5, painted_wall=None),
     82799, False, False),
    # Early in a boot, only the synced wall clock can tell.
    (P.State(complete=True, painted_end_bt=EARLY_BT + 5,
             painted_wall=NOW_WALL - 82800), EARLY_BT, True, True),
    (P.State(complete=True, painted_end_bt=EARLY_BT + 5,
             painted_wall=NOW_WALL - 82800), EARLY_BT, False, False),
    (P.State(complete=True, painted_end_bt=EARLY_BT + 5,
             painted_wall=NOW_WALL - 82799), EARLY_BT, True, False),
    (P.State(complete=True, painted_end_bt=EARLY_BT + 5, painted_wall=None),
     EARLY_BT, True, False),
])
def test_the_forced_due_table(state, now_bt, synced, expected):
    assert P.forced_due(state, now_bt, NOW_WALL, synced) is expected


@pytest.mark.parametrize("state, now_bt, synced, expected", [
    (P.State(complete=False, attempt_start_bt=1.0), 2000.0, True, None),
    (P.State(complete=True, painted_end_bt=1000.0), 2000.0, False, 83_800.0),
    (P.State(complete=True, painted_end_bt=1000.0), 83_800.0, False, None),
    (P.State(complete=True, painted_end_bt=500_000.0), 1000.0, False, 82_800.0),
    (P.State(complete=True, painted_end_bt=1000.0, painted_wall=NOW_WALL - 82_000),
     2000.0, True, 2800.0),
    (P.State(complete=True, painted_end_bt=1000.0, painted_wall=NOW_WALL - 82_000),
     2000.0, False, 83_800.0),
    (P.State(complete=True, painted_end_bt=1000.0, painted_wall=NOW_WALL - 90_000),
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
     P.Transient("down"), None),
    # same boot, overdue by boot time, no wall clock
    (83_000.0, False, dict(painted_end_bt=10.0, painted_wall=None),
     P.Transient("down"), None),
    # an earlier boot, with this boot's uptime past 23 h
    (83_000.0, False, dict(painted_end_bt=500_000.0, painted_wall=None),
     P.Transient("down"), None),
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
    it comes, so the cap must not pull it inside the backoff."""
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
    assert all(g >= P.ERROR_RETRY_S for g in gaps), gaps
    if gap is not None:
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
    """With the stop signals blocked, a SIGTERM raised mid-refresh stays
    pending and is only collected by the next wait, after sleep()."""

    class Stopping(FakePanel):
        def display(self, data):
            signal.raise_signal(signal.SIGTERM)
            super().display(data)

    clock = Clock()
    old = signal.pthread_sigmask(signal.SIG_BLOCK, [])
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK, P.WAIT_SIGNALS)
        h = Harness(tmp_path, clock, new_frames(), panel=Stopping(clock))

        def wait(timeout):
            sig = P.wait_for_signal(0)
            if sig:
                return sig
            clock.t += timeout
            return None

        h.deps.wait = wait
        assert h.run() == 0
        assert h.panel.names() == ["init", "display", "sleep"]
    finally:
        while signal.sigtimedwait(P.WAIT_SIGNALS, 0):
            pass
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


WAITER_SCRIPT = """
import importlib.util, os, signal, sys, threading, time
spec = importlib.util.spec_from_file_location("panel_under_test", sys.argv[1])
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)
signal.pthread_sigmask(signal.SIG_BLOCK, panel.WAIT_SIGNALS)
threading.Timer(0.1, os.kill, (os.getpid(), signal.SIGTERM)).start()
start = time.monotonic()
sig = panel.wait_for_signal(5)
elapsed = time.monotonic() - start
print(f"{sig} {elapsed:.3f}")
"""


def test_the_real_waiter_collects_a_signal_sent_from_another_thread():
    """In a child process, so a real SIGTERM can never reach pytest."""
    out = subprocess.run([sys.executable, "-I", "-c", WAITER_SCRIPT, str(F.PANEL_PY)],
                         timeout=10, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    sig, elapsed = out.stdout.split()
    assert int(sig) == int(signal.SIGTERM)
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
    (None, None),
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
    (None, None), ("", None), ("none", None), ("18", 18),
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
