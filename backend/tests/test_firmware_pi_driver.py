"""The Pi panel driver, held to Waveshare's and to its own safety rules.

`firmware/pi_epaper_7in5/epd7in5_v2.py` is a rewrite of Waveshare's
`epd7in5_V2.py`, and the panel only works if the bytes it sends are the bytes
Waveshare's driver sends. Waveshare's file is downloaded third-party code, so
it is never imported or run: `pi_panel_fakes.waveshare_ops()` parses its source
as data, and the tests below compare our SPI stream with what that source
would send, byte for byte, DC level for DC level.

Then the rules that are ours and not Waveshare's, which a wrong edit would
break without any panel in the room to show it:

  * `display()` refuses a bad frame before a single byte goes out;
  * every wait on BUSY has a deadline, polled rather than spun;
  * power is cut only after deep sleep has settled, and cutting never raises;
  * `abort()` always ends with the lines low, whatever failed.

`find_chip`, `open_hardware` and `drive_lines_low` run against fake `gpiod` and
`spidev` modules (neither exists under CI). The AST guards at the end pin what
the systemd unit's sandbox relies on: no /proc, no subprocess, no C library,
`gpiod` and `spidev` imported only where they are used, and the licence text
that Waveshare's notice requires.
"""
from __future__ import annotations

import ast
import enum
import errno
import hashlib
import os
import sys
import types

import pytest

import pi_panel_fakes as F

P = F.load_panel()
E = F.load_driver()

FRAME = hashlib.sha256(b"smylte").digest() * 1500
SPI_STATUS = (0, b"\x71")


def _run_cycle(panel):
    panel.init()
    panel.display(FRAME)
    panel.sleep()


def test_the_test_frame_is_one_full_frame_long():
    assert len(FRAME) == E.BUF_BYTES == 48000


# ── equivalence with Waveshare (read as source, never executed) ──────────────

def test_the_driver_sends_the_same_bytes_as_waveshares():
    """This pins the command bytes, the parameter bytes, the order, the DC level
    of each transfer, and the OLD/NEW frame contents."""
    panel, rec, lines, factory, clock = F.make_panel(
        busy=lambda n: 1 if n % 3 == 2 else 0)
    _run_cycle(panel)
    assert rec.spi(drop_status_polls=True) == (
        F.waveshare_transfers("init")
        + F.waveshare_transfers("display", FRAME)
        + F.waveshare_transfers("sleep"))


def test_commands_and_parameters_go_one_byte_at_a_time_and_frames_in_two_blocks():
    panel, rec, lines, factory, clock = F.make_panel(
        busy=lambda n: 1 if n % 3 == 2 else 0)
    _run_cycle(panel)
    transfers = rec.spi()
    assert all(len(p) == 1 for dc, p in transfers if dc == 0)
    data = [len(p) for dc, p in transfers if dc == 1]
    assert [n for n in data if n != 1] == [E.BUF_BYTES, E.BUF_BYTES]


def test_every_busy_read_is_preceded_by_a_status_poll():
    panel, rec, lines, factory, clock = F.make_panel(
        busy=lambda n: 1 if n % 3 == 2 else 0)
    _run_cycle(panel)
    polls = [t for t in rec.spi() if t == SPI_STATUS]
    assert polls
    assert len(polls) == lines.busy_reads
    reads = [i for i, e in enumerate(rec.events)
             if e[0] == "read" and e[1] == E.BUSY_PIN]
    assert len(reads) == lines.busy_reads
    for i in reads:
        assert rec.events[i - 1] == ("spi", 0, b"\x71")


def test_the_reset_pulse_has_waveshares_shape_and_at_least_its_lengths():
    ws = F.waveshare_ops("reset")
    assert [op[:2] if op[0] == "write" else op[:1] for op in ws] == [
        ("write", "reset_pin"), ("delay_ms",), ("write", "reset_pin"),
        ("delay_ms",), ("write", "reset_pin"), ("delay_ms",)]
    assert [op[2] for op in ws if op[0] == "write"] == [1, 0, 1]
    a, b, c = (op[1] for op in ws if op[0] == "delay_ms")
    assert all(isinstance(x, int) for x in (a, b, c))
    # The low pulse is Waveshare's exactly (a long one powers an RST-gated
    # board off); the highs may be longer.
    assert E.RESET_MS[1] == b
    assert E.RESET_MS[0] >= a
    assert E.RESET_MS[2] >= c


def test_init_pulses_rst_high_low_high_on_the_reset_timings():
    panel, rec, lines, factory, clock = F.make_panel()
    panel.init()
    assert rec.gpio(E.RST_PIN) == [(17, 1), (17, 0), (17, 1)]
    assert clock.sleeps[:3] == [m / 1000 for m in E.RESET_MS]


def test_the_settle_delays_are_waveshares():
    def after(ops, cmd):
        i = ops.index(("cmd", cmd))
        return ops[i + 1], ops[i + 2]

    assert after(F.waveshare_ops("init"), 0x04) == (("delay_ms", 100), ("busy",))
    assert after(F.waveshare_ops("display"), 0x12) == (("delay_ms", 100), ("busy",))
    assert E.CMD_SETTLE_S * 1000 == 100
    assert ("delay_ms", 2000) in F.waveshare_ops("sleep")
    assert E.DEEP_SLEEP_SETTLE_S * 1000 == 2000


def test_the_settle_delays_sit_where_the_driver_needs_them():
    """After POWER ON and after DISPLAY REFRESH the controller needs time to
    pull BUSY low before the first status poll, and each BUSY release is
    followed by the release settle. Checked in the event stream, not as
    constants."""
    panel, rec, lines, factory, clock = F.make_panel()
    _run_cycle(panel)
    ev = [e for e in rec.events if e[0] in ("spi", "sleep", "read")]
    for cmd in (E.POWER_ON, E.DISPLAY_REFRESH):
        i = ev.index(("spi", 0, bytes([cmd])))
        assert ev[i + 1] == ("sleep", E.CMD_SETTLE_S), (hex(cmd), ev[i:i + 3])
        assert ev[i + 2] == ("spi", 0, bytes([E.GET_STATUS])), (hex(cmd), ev[i:i + 3])
    released = [i for i, e in enumerate(ev)
                if e[0] == "read" and e[1] == E.BUSY_PIN and e[2] == 1]
    assert len(released) == 3       # power-on, refresh, power-off
    for i in released:
        assert ev[i + 1] == ("sleep", E.BUSY_RELEASE_S)


def test_the_panel_is_left_powered_in_deep_sleep_where_waveshare_cuts_power():
    """Waveshare's sleep() ends with module_exit(), which cuts power. Ours does
    not by default: the Pico driver also leaves RST high after a refresh. On the
    Pico-ePaper-7.5 module RST switches the panel's power, so this is deep
    sleep with the logic powered, by policy (see the driver's sleep()
    docstring)."""
    assert F.waveshare_ops("sleep")[-1] == ("module_exit",)
    panel, rec, lines, factory, clock = F.make_panel()
    _run_cycle(panel)
    assert lines.levels[E.RST_PIN] == 1


def test_the_vendored_reference_is_the_pinned_one():
    assert hashlib.sha256(F.VENDOR_WAVESHARE.read_bytes()).hexdigest() \
        == F.VENDOR_WAVESHARE_SHA256
    readme = (F.VENDOR_WAVESHARE.parent / "README.md").read_text(encoding="utf-8")
    assert F.VENDOR_WAVESHARE_SHA256 in readme


# ── safety ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    bytearray(48000),
    list(bytes(48000)),
    "x" * 48000,
    memoryview(bytes(48000)),
    bytes(47999),
    bytes(48001),
], ids=["bytearray", "list", "str", "memoryview", "one-short", "one-long"])
def test_display_refuses_a_bad_frame_before_any_spi_write(bad):
    panel, rec, lines, factory, clock = F.make_panel()
    panel.init()
    n = len(rec.spi())
    with pytest.raises(ValueError):
        panel.display(bad)
    assert len(rec.spi()) == n


def test_display_before_init_raises_a_panel_error():
    panel, rec, lines, factory, clock = F.make_panel()
    with pytest.raises(E.PanelError):
        panel.display(FRAME)
    assert rec.spi() == []


def test_init_twice_opens_spi_once():
    panel, rec, lines, factory, clock = F.make_panel()
    panel.init()
    panel.init()
    assert len(factory.opened) == 1


def test_a_stuck_busy_at_power_on_times_out_by_polling_not_spinning():
    panel, rec, lines, factory, clock = F.make_panel(busy=0)
    with pytest.raises(E.BusyTimeout) as info:
        panel.init()
    e = info.value
    assert e.phase == "power-on"
    assert E.POWER_ON_TIMEOUT_S <= e.waited_s < E.POWER_ON_TIMEOUT_S + 1
    polls = rec.spi().count(SPI_STATUS)
    assert 0.9 * E.POWER_ON_TIMEOUT_S / E.BUSY_POLL_S <= polls \
        <= E.POWER_ON_TIMEOUT_S / E.BUSY_POLL_S + 2


def test_a_stuck_busy_during_refresh_times_out_in_the_refresh_phase():
    panel, rec, lines, factory, clock = F.make_panel(
        busy=lambda n: 1 if n == 0 else 0)
    panel.init()
    with pytest.raises(E.BusyTimeout) as info:
        panel.display(FRAME)
    assert info.value.phase == "refresh"
    assert info.value.waited_s >= E.REFRESH_TIMEOUT_S


def test_a_stuck_busy_during_power_off_times_out_in_the_power_off_phase():
    panel, rec, lines, factory, clock = F.make_panel(
        busy=lambda n: 1 if n < 2 else 0)
    panel.init()
    panel.display(FRAME)
    with pytest.raises(E.BusyTimeout) as info:
        panel.sleep()
    assert info.value.phase == "power-off"


def test_tick_is_called_on_every_poll_while_busy_is_low():
    ticks = []
    panel, rec, lines, factory, clock = F.make_panel(
        tick=lambda: ticks.append(1), busy=lambda n: 1 if n >= 5 else 0)
    panel.init()
    assert len(ticks) == 5


def test_sleep_leaves_rst_high_dc_low_and_spi_closed():
    panel, rec, lines, factory, clock = F.make_panel()
    _run_cycle(panel)
    assert lines.levels[E.RST_PIN] == 1
    assert lines.levels[E.DC_PIN] == 0
    assert factory.opened[-1].closed is True
    # RST was pulsed by init's reset and never dropped again.
    assert rec.gpio(17) == [(17, 1), (17, 0), (17, 1)]


def test_cut_between_drops_rst_only_after_deep_sleep_has_settled():
    panel, rec, lines, factory, clock = F.make_panel(cut_between=True)
    panel.init()
    panel.display(FRAME)

    times = {}
    real_set = lines.set

    def set_noting(pin, high):
        real_set(pin, high)
        if pin == E.RST_PIN and not high:
            times["rst_low"] = clock.t
    lines.set = set_noting

    spi = factory.opened[-1]
    real_write = spi.writebytes

    def write_noting(data):
        real_write(data)
        if bytes(data) == b"\x07":
            times["deep_sleep"] = clock.t
    spi.writebytes = write_noting

    panel.sleep()
    assert lines.levels[E.RST_PIN] == 0
    assert times["rst_low"] - times["deep_sleep"] >= E.DEEP_SLEEP_SETTLE_S - 1e-9


def test_cut_between_with_a_power_pin_raises_it_before_reset_and_drops_it_at_the_end():
    panel, rec, lines, factory, clock = F.make_panel(cut_between=True, pwr_pin=18)
    _run_cycle(panel)
    pwr_on = rec.events.index(("gpio", 18, 1))
    first_rst = next(i for i, e in enumerate(rec.events)
                     if e[0] == "gpio" and e[1] == E.RST_PIN)
    assert pwr_on < first_rst
    assert lines.levels[18] == 0
    assert lines.levels[E.RST_PIN] == 0


def test_cut_power_waits_out_the_deep_sleep_settle_once():
    panel, rec, lines, factory, clock = F.make_panel()
    _run_cycle(panel)
    t0 = clock.t
    panel.cut_power()
    assert clock.t - t0 >= E.DEEP_SLEEP_SETTLE_S - 1e-9
    assert lines.levels[E.RST_PIN] == 0
    assert lines.levels[E.DC_PIN] == 0
    t1 = clock.t
    panel.cut_power()
    assert clock.t == t1


def test_cut_power_never_raises():
    panel, rec, lines, factory, clock = F.make_panel(pwr_pin=18)
    _run_cycle(panel)
    lines.fail_set = {17, 25, 18}
    panel.cut_power()


def test_close_never_raises_and_releases_the_lines():
    panel, rec, lines, factory, clock = F.make_panel()
    _run_cycle(panel)
    panel.close()
    assert lines.released is True


def test_close_never_raises_when_the_release_fails():
    panel, rec, lines, factory, clock = F.make_panel()
    _run_cycle(panel)

    def broken_release():
        raise OSError(5, "fake release failure")
    lines.release = broken_release
    panel.close()
    assert lines.levels[E.RST_PIN] == 0


def test_abort_with_busy_stuck_sends_the_power_down_without_polling():
    panel, rec, lines, factory, clock = F.make_panel()
    panel.init()
    mark = len(rec.events)
    panel.abort(busy_stuck=True)
    after = [(e[1], e[2]) for e in rec.events[mark:] if e[0] == "spi"]
    assert after == [(0, b"\x50"), (1, b"\xf7"), (0, b"\x02"),
                     (0, b"\x07"), (1, b"\xa5")]
    assert lines.levels[E.RST_PIN] == 0
    assert factory.opened[-1].closed is True


def test_abort_without_busy_stuck_waits_for_power_off_before_deep_sleep():
    panel, rec, lines, factory, clock = F.make_panel()
    panel.init()
    mark = len(rec.events)
    panel.abort(busy_stuck=False)
    after = [(e[1], e[2]) for e in rec.events[mark:] if e[0] == "spi"]
    assert [t for t in after if t != SPI_STATUS] == [
        (0, b"\x50"), (1, b"\xf7"), (0, b"\x02"), (0, b"\x07"), (1, b"\xa5")]
    assert after.count(SPI_STATUS) >= 1
    assert after.index(SPI_STATUS) > after.index((0, b"\x02"))
    assert after.index(SPI_STATUS) < after.index((0, b"\x07"))
    assert lines.levels[E.RST_PIN] == 0


def test_abort_after_sleep_sends_no_spi_and_leaves_rst_low():
    panel, rec, lines, factory, clock = F.make_panel()
    _run_cycle(panel)
    mark = len(rec.events)
    panel.abort()
    assert [e for e in rec.events[mark:] if e[0] == "spi"] == []
    assert lines.levels[E.RST_PIN] == 0


def test_abort_never_raises_when_spi_writes_fail():
    panel, rec, lines, factory, clock = F.make_panel()
    panel.init()
    factory.opened[-1].fail_writes = True
    panel.abort()
    assert lines.levels[E.RST_PIN] == 0


def test_without_a_power_pin_bcm18_is_never_touched():
    panel, rec, lines, factory, clock = F.make_panel()
    _run_cycle(panel)
    panel.close()
    assert [e for e in rec.events if e[0] == "gpio" and e[1] == 18] == []


# ── fake gpiod / spidev ──────────────────────────────────────────────────────

class FakeRequest:
    def __init__(self):
        self.sets = []
        self.releases = 0
        self.values = {}        # offset -> Value: as last set, or as a test scripts it

    def set_value(self, pin, v):
        self.sets.append((pin, v))
        self.values[pin] = v

    def get_value(self, pin):
        return self.values.get(pin, self.value_active)

    def release(self):
        self.releases += 1


class FakeGpiod:
    """A `gpiod` (and `gpiod.line`) as the driver touches them."""

    def __init__(self, devices=(), labels=None, denied=(), denied_errno=13):
        self.devices = set(devices)
        self.labels = dict(labels or {})
        self.denied = set(denied)
        self.denied_errno = denied_errno
        self.requests = []          # (path, consumer, config)
        self.request = None
        self.request_error = None  # an OSError to raise from request_lines

        gl = types.ModuleType("gpiod.line")
        gl.Direction = enum.Enum("Direction", "INPUT OUTPUT")
        gl.Bias = enum.Enum("Bias", "PULL_DOWN PULL_UP")
        gl.Value = enum.Enum("Value", "ACTIVE INACTIVE")
        self.line = gl
        FakeRequest.value_active = gl.Value.ACTIVE

        g = types.ModuleType("gpiod")
        g.line = gl
        g.LineSettings = lambda **kw: types.SimpleNamespace(**kw)
        g.is_gpiochip_device = lambda path: path in self.devices
        g.Chip = self._chip
        g.request_lines = self._request_lines
        self.module = g

    def _chip(self, path):
        if path in self.denied:
            raise OSError(self.denied_errno, "denied")
        labels = self.labels

        class _Chip:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_info(self):
                return types.SimpleNamespace(label=labels[path])
        return _Chip()

    def _request_lines(self, path, consumer=None, config=None):
        if self.request_error is not None:
            raise self.request_error
        self.requests.append((path, consumer, config))
        self.request = FakeRequest()
        return self.request


class FakeSpidev:
    """A `spidev` whose SpiDev() records its open/close and attributes."""

    def __init__(self):
        self.opened = []
        self.closed = 0
        self.instances = []
        self.open_error = None
        outer = self

        class SpiDev:
            max_speed_hz = None
            mode = None

            def __init__(self):
                outer.instances.append(self)

            def open(self, bus, dev):
                if outer.open_error is not None:
                    raise outer.open_error
                outer.opened.append((bus, dev))

            def close(self):
                outer.closed += 1

        self.module = types.ModuleType("spidev")
        self.module.SpiDev = SpiDev


@pytest.fixture
def hardware(monkeypatch):
    """Fake gpiod and spidev installed, with `find_chip` patched to a fixed chip."""
    g = FakeGpiod()
    s = FakeSpidev()
    monkeypatch.setitem(sys.modules, "gpiod", g.module)
    monkeypatch.setitem(sys.modules, "gpiod.line", g.line)
    monkeypatch.setitem(sys.modules, "spidev", s.module)
    monkeypatch.setattr(
        E, "find_chip",
        lambda gpiod, label=E.CHIP_LABEL, paths=None: "/dev/gpiochip0")
    return g, s


# ── find_chip ────────────────────────────────────────────────────────────────

def _chips(tmp_path, *names):
    paths = []
    for n in names:
        p = tmp_path / n
        p.write_text("")
        paths.append(os.path.realpath(p))
    return paths


def test_find_chip_returns_the_one_chip_with_the_headers_label(tmp_path):
    a, b, c = _chips(tmp_path, "gpiochip0", "gpiochip1", "gpiochip2")
    g = FakeGpiod(devices={a, b, c},
                  labels={a: "gpio-brcmstb", b: "pinctrl-rp1", c: "other"})
    assert E.find_chip(g.module, paths=[a, b, c]) == b


def test_find_chip_counts_a_symlink_and_its_target_once(tmp_path):
    (real,) = _chips(tmp_path, "gpiochip0")
    link = tmp_path / "gpiochip4"
    link.symlink_to(tmp_path / "gpiochip0")
    g = FakeGpiod(devices={real}, labels={real: "pinctrl-rp1"})
    assert E.find_chip(g.module, paths=[str(tmp_path / "gpiochip0"), str(link)]) == real


def test_find_chip_with_no_match_names_the_label_it_wanted(tmp_path):
    a, b = _chips(tmp_path, "gpiochip0", "gpiochip1")
    g = FakeGpiod(devices={a, b}, labels={a: "x", b: "y"})
    with pytest.raises(E.HardwareMissing, match="pinctrl-rp1"):
        E.find_chip(g.module, paths=[a, b])


def test_find_chip_with_two_distinct_matches_refuses_to_guess(tmp_path):
    a, b = _chips(tmp_path, "gpiochip0", "gpiochip1")
    g = FakeGpiod(devices={a, b}, labels={a: "pinctrl-rp1", b: "pinctrl-rp1"})
    with pytest.raises(E.HardwareMissing, match="expected one"):
        E.find_chip(g.module, paths=[a, b])


def test_find_chip_skips_a_denied_chip_listed_before_the_right_one(tmp_path):
    a, b = _chips(tmp_path, "gpiochip0", "gpiochip1")
    g = FakeGpiod(devices={a, b}, labels={b: "pinctrl-rp1"}, denied={a})
    assert E.find_chip(g.module, paths=[a, b]) == b


@pytest.mark.parametrize("err", [errno.EACCES, errno.EPERM], ids=["EACCES", "EPERM"])
def test_find_chip_with_only_a_denied_chip_says_so(tmp_path, err):
    (a,) = _chips(tmp_path, "gpiochip0")
    g = FakeGpiod(devices={a}, labels={a: "pinctrl-rp1"}, denied={a},
                  denied_errno=err)
    with pytest.raises(E.HardwareMissing, match=r"permission denied opening .*group `gpio`"):
        E.find_chip(g.module, paths=[a])


def test_find_chip_with_a_chip_that_fails_otherwise_is_not_called_a_permission_problem(tmp_path):
    (a,) = _chips(tmp_path, "gpiochip0")
    g = FakeGpiod(devices={a}, labels={a: "pinctrl-rp1"}, denied={a},
                  denied_errno=errno.EIO)
    with pytest.raises(E.HardwareMissing) as info:
        E.find_chip(g.module, paths=[a])
    assert "no GPIO chip labelled" in str(info.value)
    assert "could not open" in str(info.value)
    assert "permission denied" not in str(info.value)


def test_find_chip_skips_a_path_that_is_not_a_gpio_chip_device(tmp_path):
    """The not-a-device file carries the right label too: were it not skipped,
    two chips would match and this would raise."""
    a, b = _chips(tmp_path, "notachip", "gpiochip0")
    g = FakeGpiod(devices={b}, labels={a: "pinctrl-rp1", b: "pinctrl-rp1"})
    assert E.find_chip(g.module, paths=[a, b]) == b


# ── open_hardware ────────────────────────────────────────────────────────────

def test_open_hardware_requests_the_lines_and_probes_spi(hardware):
    g, s = hardware
    gl = g.line
    lines, factory, chip = E.open_hardware(None)
    assert chip == "/dev/gpiochip0"
    assert callable(factory)

    (path, consumer, config), = g.requests
    assert path == "/dev/gpiochip0"
    assert consumer == "smylte-panel"
    assert set(config) == {(17, 25), 24}
    assert config[(17, 25)].direction == gl.Direction.OUTPUT
    assert config[(17, 25)].output_value == gl.Value.INACTIVE
    assert config[24].direction == gl.Direction.INPUT
    assert config[24].bias == gl.Bias.PULL_DOWN

    assert s.opened == [(0, 0)]
    assert s.closed == 1
    assert s.instances[0].max_speed_hz == 4_000_000
    assert s.instances[0].mode == 0

    lines.set(17, 1)
    assert g.request.sets == [(17, gl.Value.ACTIVE)]
    assert lines.get(24) == 1


def test_the_lines_adapter_maps_both_levels_both_ways(hardware):
    """The one seam between the tested sequencing and real GPIO: low must be
    INACTIVE going out, and INACTIVE must read as 0 coming back."""
    g, s = hardware
    Value = g.line.Value
    lines, factory, chip = E.open_hardware(None)
    lines.set(17, 1)
    lines.set(17, 0)
    lines.set(25, True)
    lines.set(25, False)
    assert g.request.sets == [(17, Value.ACTIVE), (17, Value.INACTIVE),
                              (25, Value.ACTIVE), (25, Value.INACTIVE)]
    g.request.values[24] = Value.INACTIVE
    assert lines.get(24) == 0
    g.request.values[24] = Value.ACTIVE
    assert lines.get(24) == 1
    lines.release()
    assert g.request.releases == 1


def test_open_hardware_with_a_power_pin_adds_it_to_the_outputs(hardware):
    g, s = hardware
    E.open_hardware(18)
    (_, _, config), = g.requests
    assert set(config) == {(17, 25, 18), 24}


def test_open_hardware_without_spi_points_at_raspi_config_and_lets_go(hardware):
    g, s = hardware
    s.open_error = OSError(errno.ENOENT, "no such file")
    with pytest.raises(E.HardwareMissing, match="raspi-config"):
        E.open_hardware(None)
    assert g.request.releases == 1


def test_open_hardware_with_the_lines_held_elsewhere_points_at_gpioinfo(hardware):
    g, s = hardware
    g.request_error = OSError(errno.EBUSY, "busy")
    with pytest.raises(E.HardwareMissing, match="gpioinfo"):
        E.open_hardware(None)


def test_open_hardware_without_gpiod_names_the_package(hardware, monkeypatch):
    monkeypatch.setitem(sys.modules, "gpiod", None)
    with pytest.raises(E.HardwareMissing, match="python3-libgpiod"):
        E.open_hardware(None)


def test_open_hardware_without_spidev_names_the_package(hardware, monkeypatch):
    monkeypatch.setitem(sys.modules, "spidev", None)
    with pytest.raises(E.HardwareMissing, match="python3-spidev"):
        E.open_hardware(None)


# ── drive_lines_low ──────────────────────────────────────────────────────────

def test_drive_lines_low_drives_the_outputs_low_and_lets_go(hardware, monkeypatch):
    g, s = hardware
    monkeypatch.setitem(sys.modules, "spidev", None)    # it must not need SPI
    assert E.drive_lines_low(None) is True
    (path, consumer, config), = g.requests
    assert path == "/dev/gpiochip0"
    assert set(config) == {(17, 25)}
    assert config[(17, 25)].output_value == g.line.Value.INACTIVE
    assert g.request.releases == 1


def test_drive_lines_low_includes_the_power_pin_when_there_is_one(hardware):
    g, s = hardware
    assert E.drive_lines_low(18) is True
    (_, _, config), = g.requests
    assert set(config) == {(17, 25, 18)}


def test_drive_lines_low_returns_false_when_the_lines_are_held(hardware):
    g, s = hardware
    g.request_error = OSError(errno.EBUSY, "busy")
    assert E.drive_lines_low(None) is False


def test_drive_lines_low_returns_false_without_gpiod(hardware, monkeypatch):
    monkeypatch.setitem(sys.modules, "gpiod", None)
    assert E.drive_lines_low(None) is False


# ── AST guards on the source ─────────────────────────────────────────────────

def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _import_roots(node):
    if isinstance(node, ast.Import):
        return [a.name.split(".")[0] for a in node.names]
    return [(node.module or "").split(".")[0]]


def test_the_drivers_module_level_imports_are_the_four_it_may_have():
    roots = {r for n in _tree(F.DRIVER_PY).body
             if isinstance(n, (ast.Import, ast.ImportFrom))
             for r in _import_roots(n)}
    assert roots <= {"errno", "logging", "os", "time"}


def test_gpiod_and_spidev_are_imported_only_inside_the_two_functions_that_use_them():
    tree = _tree(F.DRIVER_PY)
    allowed = {id(n)
               for f in tree.body
               if isinstance(f, ast.FunctionDef)
               and f.name in ("open_hardware", "drive_lines_low")
               for n in ast.walk(f)}
    found = [n for n in ast.walk(tree)
             if isinstance(n, (ast.Import, ast.ImportFrom))
             and {"gpiod", "spidev"} & set(_import_roots(n))]
    assert found
    for n in found:
        assert id(n) in allowed, f"line {n.lineno} imports hardware outside the two functions"


def _docstring_ids(tree):
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = n.body[0] if n.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


@pytest.mark.parametrize("path", [F.DRIVER_PY, F.PANEL_PY], ids=["driver", "panel"])
def test_no_process_ffi_or_proc_access_in_the_firmware(path):
    tree = _tree(path)
    docstrings = _docstring_ids(tree)
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for root in _import_roots(n):
                assert root not in ("subprocess", "ctypes"), f"line {n.lineno}: imports {root}"
        elif isinstance(n, ast.Attribute):
            if isinstance(n.value, ast.Name) and n.value.id == "os":
                assert n.attr not in ("system", "popen") \
                    and not n.attr.startswith("exec"), f"line {n.lineno}: os.{n.attr}"
        elif isinstance(n, ast.Name):
            assert n.id != "CDLL", f"line {n.lineno}: CDLL"
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            if id(n) not in docstrings:
                assert "/proc" not in n.value, f"line {n.lineno}: reads /proc"


def test_the_driver_touches_only_libgpiod_v2s_api():
    allowed = {"is_gpiochip_device", "Chip", "LineSettings", "request_lines"}
    used = {n.attr for n in ast.walk(_tree(F.DRIVER_PY))
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name) and n.value.id == "gpiod"}
    assert used
    assert used <= allowed


@pytest.mark.parametrize("path", [F.DRIVER_PY, F.PANEL_PY], ids=["driver", "panel"])
def test_the_firmware_declares_its_licence_in_its_first_lines(path):
    head = path.read_text(encoding="utf-8").splitlines()[:3]
    assert any("SPDX-License-Identifier: MIT" in line for line in head)


def test_the_driver_carries_waveshares_permission_notice():
    text = F.DRIVER_PY.read_text(encoding="utf-8")
    assert "Permission is hereby granted, free of charge" in text
    assert "waveshareteam/e-Paper" in text


def test_the_clients_module_level_imports_are_standard_library_only():
    for n in _tree(F.PANEL_PY).body:
        if isinstance(n, ast.ImportFrom):
            assert n.level == 0, f"line {n.lineno}: relative import"
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for root in _import_roots(n):
                assert root in sys.stdlib_module_names, f"line {n.lineno}: {root}"
