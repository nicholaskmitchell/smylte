# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Nicholas K. Mitchell
#
# Driver for the Waveshare 7.5" e-Paper V2 (800x480, black and white) on a
# Raspberry Pi 5, over SPI0 and the RP1 GPIO block.
#
# The command bytes, their order and the timings follow Waveshare's
# `epd7in5_V2.py` (github.com/waveshareteam/e-Paper, commit d28b3c4), whose
# permission notice is reproduced below as that notice requires. The code
# around them is this repo's, written so it can run in a sandboxed service:
#
#   * Importing this file touches no hardware. Waveshare's `epdconfig.py` claims
#     its GPIOs and shells out to `cat /proc/cpuinfo` the moment it is imported,
#     and on anything that is not a Pi it falls back to Jetson libraries. Here
#     `gpiod` and `spidev` are imported inside `open_hardware()` and nowhere
#     else, so CI can load this file and check it byte for byte against
#     Waveshare's (backend/tests/test_firmware_pi_driver.py).
#   * Every wait on BUSY has a deadline. Waveshare's `ReadBusy()` loops forever,
#     and an unpowered panel holds BUSY low forever, so one loose wire would hang
#     the refresh with nothing in the log.
#   * GPIO goes through libgpiod (python3-libgpiod), not gpiozero/lgpio. It finds
#     the header's chip by its label rather than by number (it is gpiochip0 on
#     current kernels and was gpiochip4 on early ones). It needs no writable
#     working directory, which lgpio does. It holds the lines exclusively, and
#     `gpioinfo` shows who holds them.
#   * SPI is opened once per refresh and closed in `sleep()`. Waveshare's
#     `init()` opens it again on every call without closing it.
#
# Nothing in this file reads /proc, starts a process or loads a C library. The
# systemd unit's `ProcSubset=pid` relies on that, and an AST test in CI checks
# it.
#
# Waveshare's notice for the original driver, verbatim (typos included):
#
# -----------------------------------------------------------------------------
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documnetation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to  whom the Software is
# furished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS OR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
# -----------------------------------------------------------------------------

import errno
import logging
import os
import time

log = logging.getLogger("smylte-panel.epd")

# ── the glass ────────────────────────────────────────────────────────────────
WIDTH = 800
HEIGHT = 480
BUF_BYTES = WIDTH // 8 * HEIGHT    # 48,000: one bit per pixel, 1 = black ink

# ── the header (BCM numbers) ─────────────────────────────────────────────────
# Waveshare's pins, so a board wired for their HAT works unchanged. CS is not
# here: the Pi 5's SPI driver runs CE0 (GPIO8) itself, as a kernel-owned GPIO,
# and any userspace claim on it fails "busy".
RST_PIN = 17      # header pin 11. On the Pico-ePaper-7.5 module this line also
                  # switches the panel's power: low means unpowered.
DC_PIN = 25       # header pin 22
BUSY_PIN = 24     # header pin 18. Low while the controller is busy.
PWR_PIN = 18      # header pin 12. Only Driver HAT Rev2.3 and later have it.

SPI_BUS = 0
SPI_DEVICE = 0          # /dev/spidev0.0, chip select CE0
SPI_HZ = 4_000_000      # Waveshare's value
SPI_MODE = 0

CHIP_LABEL = "pinctrl-rp1"      # the 40-pin header on a Pi 5
CONSUMER = "smylte-panel"       # what `gpioinfo` shows as the lines' holder

# ── timings ──────────────────────────────────────────────────────────────────
# Reset: high, low, high, in milliseconds. 50/2/50 is the Pico driver's, proven
# on the module this replaces; Waveshare's Pi driver uses 20/2/20. The first
# high is also the module's power-up, so the longer one is the safer one. The
# low pulse stays short on purpose: Waveshare's FAQ warns that a long one powers
# an RST-gated board off and the reset then fails.
RESET_MS = (50, 2, 50)
CMD_SETTLE_S = 0.1          # after POWER ON and after REFRESH, as Waveshare
BUSY_POLL_S = 0.02          # between status polls while BUSY is low
BUSY_RELEASE_S = 0.02       # after BUSY goes high, as Waveshare
DEEP_SLEEP_SETTLE_S = 2.0   # deep sleep, then this long before power is cut

# How long each BUSY phase may take before the refresh is abandoned. The
# panel's spec gives a full refresh as 4 s typical and 8 s at most at 25 °C; a
# cold room is slower. These are bounds on a fault, not on a slow day.
POWER_ON_TIMEOUT_S = 10
REFRESH_TIMEOUT_S = 60
POWER_OFF_TIMEOUT_S = 10

# The longest init()+display()+sleep() can take before it either finishes or
# raises: every fixed delay, every BUSY deadline, and 5 s for the 96,000 bytes
# of SPI traffic (about 0.2 s at 4 MHz) and scheduling. The systemd unit's
# TimeoutStopSec is checked against this in CI, because a stop that lands
# mid-refresh waits for the refresh to finish.
PAINT_WORST_S = (sum(RESET_MS) / 1000 + 2 * CMD_SETTLE_S + 3 * BUSY_RELEASE_S
                 + POWER_ON_TIMEOUT_S + REFRESH_TIMEOUT_S + POWER_OFF_TIMEOUT_S
                 + 5)

# ── commands (GD7965 controller) ─────────────────────────────────────────────
PANEL_SETTING = 0x00
POWER_SETTING = 0x01
POWER_OFF = 0x02
POWER_ON = 0x04
BOOSTER_SOFT_START = 0x06
DEEP_SLEEP = 0x07
DATA_START_OLD = 0x10       # "OLD" frame
DISPLAY_REFRESH = 0x12
DATA_START_NEW = 0x13       # "NEW" frame
DUAL_SPI = 0x15
VCOM_DATA_INTERVAL = 0x50
TCON = 0x60
RESOLUTION = 0x61
GET_STATUS = 0x71

DEEP_SLEEP_CHECK = 0xA5     # the byte DEEP_SLEEP needs, or it is ignored
VCOM_FOR_POWER_OFF = 0xF7

# Waveshare's init(), in two halves around POWER ON and its BUSY wait.
INIT_BEFORE_POWER_ON = (
    (BOOSTER_SOFT_START, b"\x17\x17\x28\x17"),
    (POWER_SETTING, b"\x07\x07\x28\x17"),       # VGH 20 V, VGL -20 V, VDH 15 V, VDL -15 V
)
INIT_AFTER_POWER_ON = (
    (PANEL_SETTING, b"\x1f"),                   # KW mode, OTP waveform
    (RESOLUTION, b"\x03\x20\x01\xe0"),          # 800 x 480
    (DUAL_SPI, b"\x00"),
    (VCOM_DATA_INTERVAL, b"\x10\x07"),
    (TCON, b"\x22"),
)

# Complements every byte. The OLD frame is the NEW frame inverted, as
# Waveshare's display() sends it.
INVERT = bytes(255 - i for i in range(256))


class PanelError(Exception):
    """The panel, or the hardware path to it, did not do what it was told."""


class BusyTimeout(PanelError):
    def __init__(self, phase: str, waited_s: float):
        super().__init__(
            f"BUSY stayed low for {waited_s:.1f} s during {phase} — the panel is "
            "unpowered, not wired to BCM24, or a different model")
        self.phase = phase
        self.waited_s = waited_s


class HardwareMissing(PanelError):
    def __init__(self, what: str, hint: str):
        super().__init__(f"{what}: {hint}")
        self.what = what
        self.hint = hint


class Lines:
    """The panel's GPIO lines, held by one libgpiod v2 request."""

    def __init__(self, request, value_cls):
        self._req = request
        self._on = value_cls.ACTIVE
        self._off = value_cls.INACTIVE

    def set(self, pin: int, high) -> None:
        self._req.set_value(pin, self._on if high else self._off)

    def get(self, pin: int) -> int:
        return 1 if self._req.get_value(pin) == self._on else 0

    def release(self) -> None:
        self._req.release()


def find_chip(gpiod, label: str = CHIP_LABEL, paths=None) -> str:
    """The one /dev/gpiochip* whose label is `label`.

    By label because the number is not stable: the header was gpiochip4 on the
    Pi 5's first kernels and is gpiochip0 since 6.6.45, with a gpiochip4
    symlink kept by udev. Paths are de-duplicated by their real path so the
    symlink does not count twice. A chip this process may not open is skipped,
    not fatal: the Pi 5 has several, and only one is the header.
    """
    if paths is None:
        try:
            names = os.listdir("/dev")
        except OSError as e:
            raise HardwareMissing("/dev", f"cannot list it ({e})") from e
        paths = sorted("/dev/" + n for n in names if n.startswith("gpiochip"))
    found, errors, denied, seen = [], [], [], set()
    for path in paths:
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        try:
            if not gpiod.is_gpiochip_device(real):
                continue
            with gpiod.Chip(real) as chip:
                if chip.get_info().label == label:
                    found.append(real)
        except OSError as e:
            errors.append(f"{real}: {e}")
            if e.errno in (errno.EACCES, errno.EPERM):
                denied.append(real)
    if len(found) == 1:
        return found[0]
    if found:
        raise HardwareMissing(
            "GPIO chip", f"{len(found)} chips are labelled {label!r} "
                         f"({', '.join(found)}); expected one")
    if denied:
        # Every chip node has the same owner and mode, so one this process may
        # not open is the likelier story than a board that is not a Pi 5.
        raise HardwareMissing(
            "GPIO chip", f"permission denied opening {', '.join(denied[:3])} — "
                         "the service needs group `gpio` and "
                         "DeviceAllow=char-gpiochip, or the sandbox blocks the "
                         "device")
    hint = (f"no GPIO chip labelled {label!r} — this is not a Pi 5, or "
            "`gpiodetect` will show what is there")
    if errors:
        hint += "; could not open: " + "; ".join(errors[:3])
    raise HardwareMissing("GPIO chip", hint)


def _gpio_error(e: OSError) -> HardwareMissing:
    if e.errno == errno.EBUSY:
        return HardwareMissing(
            "GPIO lines", f"{RST_PIN}/{DC_PIN}/{BUSY_PIN} are held by another "
                          "program — `gpioinfo` names it")
    if e.errno in (errno.EACCES, errno.EPERM):
        return HardwareMissing(
            "GPIO lines", "permission denied — the service needs group `gpio` "
                          "and DeviceAllow=char-gpiochip")
    return HardwareMissing("GPIO lines", str(e))


def _spi_error(e: OSError) -> HardwareMissing:
    node = f"/dev/spidev{SPI_BUS}.{SPI_DEVICE}"
    if e.errno == errno.ENOENT:
        return HardwareMissing(
            node, "missing — SPI is off: `sudo raspi-config nonint do_spi 0`, "
                  "then reboot")
    if e.errno in (errno.EACCES, errno.EPERM):
        return HardwareMissing(
            node, "permission denied — the service needs group `spi` and "
                  "DeviceAllow=char-spi")
    return HardwareMissing(node, str(e))


def open_hardware(pwr_pin=None):
    """Claim the panel's lines and check SPI. Returns (Lines, spi_factory, chip).

    The outputs start LOW, which on the Pico module means the panel is
    unpowered. That is the state Waveshare's own driver leaves it in, and the
    one the module's pull-down holds while nothing drives the line.
    """
    try:
        import gpiod
        from gpiod.line import Bias, Direction, Value
    except ImportError as e:
        raise HardwareMissing(
            "gpiod", "not importable — `sudo apt install python3-libgpiod`, and "
                     "run with /usr/bin/python3, not a venv") from e
    try:
        import spidev
    except ImportError as e:
        raise HardwareMissing(
            "spidev", "not importable — `sudo apt install python3-spidev`, and "
                      "run with /usr/bin/python3, not a venv") from e

    chip = find_chip(gpiod)
    outputs = (RST_PIN, DC_PIN) + ((pwr_pin,) if pwr_pin is not None else ())
    config = {
        outputs: gpiod.LineSettings(direction=Direction.OUTPUT,
                                    output_value=Value.INACTIVE),
        BUSY_PIN: gpiod.LineSettings(direction=Direction.INPUT,
                                     bias=Bias.PULL_DOWN),
    }
    try:
        request = gpiod.request_lines(chip, consumer=CONSUMER, config=config)
    except OSError as e:
        raise _gpio_error(e) from e
    lines = Lines(request, Value)

    def spi_factory():
        spi = spidev.SpiDev()
        try:
            spi.open(SPI_BUS, SPI_DEVICE)
            spi.max_speed_hz = SPI_HZ
            spi.mode = SPI_MODE
        except OSError as e:
            try:
                spi.close()
            except Exception:
                pass
            raise _spi_error(e) from e
        return spi

    try:
        spi_factory().close()    # fail at start, not at the first refresh
    except BaseException:
        lines.release()
        raise
    return lines, spi_factory, chip


class Panel:
    """One panel. init() → display() → sleep(), and close() on the way out.

    `clock` and `sleep` are injectable so CI can run the real sequencing on a
    fake clock, and `tick` is called on every BUSY poll so the caller can keep
    a watchdog fed through a long refresh.
    """

    def __init__(self, lines, spi_factory, *, pwr_pin=None,
                 cut_between: bool = False, clock=time.monotonic,
                 sleep=time.sleep, tick=None):
        self._lines = lines
        self._spi_factory = spi_factory
        self._pwr_pin = pwr_pin
        self._cut_between = cut_between
        self._clock = clock
        self._sleep = sleep
        self._tick = tick or (lambda: None)
        self._spi = None
        self._deep_sleep_at = None
        self.phase = "idle"
        # The phase a failure happened in: abort() records it before it powers
        # down, because cut_power() then sets `phase` to "off".
        self.aborted_in = None

    # ── wire framing ─────────────────────────────────────────────────────────
    # A command is DC low and one one-byte transfer. Parameters are DC high and
    # one transfer per byte, as Waveshare's send_data(). A frame is DC high and
    # one writebytes2() of all 48,000 bytes, which spidev splits into its
    # buffer-sized blocks. CS is never touched: the kernel asserts CE0 around
    # each transfer.

    def _command(self, cmd: int) -> None:
        self._lines.set(DC_PIN, 0)
        self._spi.writebytes([cmd])

    def _params(self, data: bytes) -> None:
        self._lines.set(DC_PIN, 1)
        for b in data:
            self._spi.writebytes([b])

    def _frame(self, data: bytes) -> None:
        self._lines.set(DC_PIN, 1)
        self._spi.writebytes2(data)

    def _send(self, cmd: int, data: bytes = b"") -> None:
        self._command(cmd)
        if data:
            self._params(data)

    def _require_spi(self) -> None:
        if self._spi is None:
            raise PanelError("SPI is closed — call init() first")

    def _close_spi(self) -> None:
        spi, self._spi = self._spi, None
        if spi is not None:
            try:
                spi.close()
            except Exception as e:      # never let cleanup mask the real error
                log.warning("closing SPI: %s", e)

    def _reset(self) -> None:
        high1, low, high2 = RESET_MS
        self._lines.set(RST_PIN, 1)
        self._sleep(high1 / 1000)
        self._lines.set(RST_PIN, 0)
        self._sleep(low / 1000)
        self._lines.set(RST_PIN, 1)
        self._sleep(high2 / 1000)

    def wait_idle(self, phase: str, timeout_s: float) -> None:
        """Poll GET_STATUS until BUSY goes high, or raise BusyTimeout."""
        start = self._clock()
        deadline = start + timeout_s
        while True:
            self._command(GET_STATUS)
            if self._lines.get(BUSY_PIN):
                self._sleep(BUSY_RELEASE_S)
                return
            now = self._clock()
            if now >= deadline:
                raise BusyTimeout(phase, now - start)
            self._tick()
            self._sleep(BUSY_POLL_S)

    # ── the three steps ──────────────────────────────────────────────────────

    def init(self) -> None:
        """Power up, reset, and configure. Takes the panel out of deep sleep."""
        self.phase = "init"
        self.aborted_in = None
        if self._pwr_pin is not None:
            self._lines.set(self._pwr_pin, 1)
        if self._spi is None:
            self._spi = self._spi_factory()
        self._deep_sleep_at = None
        self._reset()
        for cmd, data in INIT_BEFORE_POWER_ON:
            self._send(cmd, data)
        self.phase = "power-on"
        self._command(POWER_ON)
        self._sleep(CMD_SETTLE_S)
        self.wait_idle("power-on", POWER_ON_TIMEOUT_S)
        self.phase = "init"
        for cmd, data in INIT_AFTER_POWER_ON:
            self._send(cmd, data)

    def display(self, frame: bytes) -> None:
        """Send one frame (1 = black, MSB leftmost, rows of 100 bytes) and refresh.

        Refuses anything but exactly 48,000 bytes BEFORE any SPI traffic. A
        short buffer would make Waveshare's loop raise halfway through a
        transfer, and a long one sends the extra bytes into the controller.
        """
        if type(frame) is not bytes:
            raise ValueError(f"frame must be bytes, not {type(frame).__name__}")
        if len(frame) != BUF_BYTES:
            raise ValueError(f"frame is {len(frame)} bytes, not {BUF_BYTES}")
        self._require_spi()
        self.phase = "transfer"
        self._command(DATA_START_OLD)
        self._frame(frame.translate(INVERT))
        self._command(DATA_START_NEW)
        self._frame(frame)
        self.phase = "refresh"
        self._command(DISPLAY_REFRESH)
        self._sleep(CMD_SETTLE_S)
        self.wait_idle("refresh", REFRESH_TIMEOUT_S)

    def sleep(self) -> None:
        """Turn the high voltage off and put the controller in deep sleep.

        The panel stays POWERED (RST high) unless `cut_between` is set. That is
        how this module ran under the Pico, whose driver never drops RST after a
        refresh, and deep sleep is the state Waveshare's "sleep or power off"
        asks for. Leaving the logic powered keeps the panel from being fed
        through CS: the kernel holds CE0 high, so with RST low the controller's
        CS input sees 3.3 V while its supply is off.
        """
        self._require_spi()
        self.phase = "power-off"
        self._send(VCOM_DATA_INTERVAL, bytes([VCOM_FOR_POWER_OFF]))
        self._command(POWER_OFF)
        self.wait_idle("power-off", POWER_OFF_TIMEOUT_S)
        self._send(DEEP_SLEEP, bytes([DEEP_SLEEP_CHECK]))
        self._deep_sleep_at = self._clock()
        self._close_spi()
        self._lines.set(DC_PIN, 0)
        self.phase = "idle"
        if self._cut_between:
            self.cut_power()

    # ── getting out ──────────────────────────────────────────────────────────

    def cut_power(self) -> None:
        """RST, DC and PWR low, after deep sleep has settled. Never raises."""
        if self._deep_sleep_at is not None:
            remaining = DEEP_SLEEP_SETTLE_S - (self._clock() - self._deep_sleep_at)
            if remaining > 0:
                try:
                    self._sleep(remaining)
                except Exception as e:
                    log.warning("waiting before power-off: %s", e)
        self._close_spi()
        pins = [RST_PIN, DC_PIN]
        if self._pwr_pin is not None:
            pins.append(self._pwr_pin)
        for pin in pins:
            try:
                self._lines.set(pin, 0)
            except Exception as e:
                log.warning("driving GPIO%d low: %s", pin, e)
        self._deep_sleep_at = None
        self.phase = "off"

    def abort(self, busy_stuck: bool = False) -> None:
        """After a failure: try to power the panel down cleanly, then cut power.

        Never raises. With `busy_stuck` the commands are still sent but BUSY is
        not waited on again, since it has just shown it will not answer.
        """
        self.aborted_in = self.phase
        if self._spi is not None:
            try:
                self._send(VCOM_DATA_INTERVAL, bytes([VCOM_FOR_POWER_OFF]))
                self._command(POWER_OFF)
                if not busy_stuck:
                    self.wait_idle("power-off", POWER_OFF_TIMEOUT_S)
                self._send(DEEP_SLEEP, bytes([DEEP_SLEEP_CHECK]))
                self._deep_sleep_at = self._clock()
            except Exception as e:
                log.warning("clean power-down after the failure did not "
                            "finish: %s", e)
        self.cut_power()

    def close(self) -> None:
        """Cut power and give the lines back. Never raises."""
        self.cut_power()
        try:
            self._lines.release()
        except Exception as e:
            log.warning("releasing GPIO lines: %s", e)


def drive_lines_low(pwr_pin=None) -> bool:
    """Drive RST, DC (and PWR) low and let go. For the unit's ExecStopPost.

    RP1 keeps a GPIO output at its last level after the line is released
    (pinctrl-rp1's `persist_gpio_outputs`, on by default). So a client killed
    while RST was high would leave the panel powered, and mid-refresh at high
    voltage, until something drove the line again. This is that something. It
    never touches BUSY or SPI, and never raises: it runs on every stop, and
    failing a stop would only hide the main process's own exit status.
    """
    try:
        import gpiod
        from gpiod.line import Direction, Value
        chip = find_chip(gpiod)
        outputs = (RST_PIN, DC_PIN) + ((pwr_pin,) if pwr_pin is not None else ())
        request = gpiod.request_lines(
            chip, consumer=CONSUMER + "-off",
            config={outputs: gpiod.LineSettings(direction=Direction.OUTPUT,
                                                output_value=Value.INACTIVE)})
        request.release()
        return True
    except Exception as e:
        log.warning("could not drive the panel's lines low: %s", e)
        return False
