"""Fakes for the Pi panel client's tests (firmware/pi_epaper_7in5/).

The client runs on a Raspberry Pi 5 against python3-libgpiod and python3-spidev,
neither of which exists under CI. These stand in for them at the narrowest
point the client and driver touch, so the REAL sequencing code runs:

  * `FakeLines` is the driver's `Lines` adapter (set/get/release on BCM pins).
  * `FakeSpi` is a `spidev.SpiDev` as the driver uses it, and records every
    transfer with the DC level at that moment. Values are masked `& 0xFF`,
    which is what spidev's C code does (`(__u8)PyLong_AS_LONG(val)`), so
    Waveshare's list of negative ints and our bytes compare equal.
  * `FakeClock` is a monotonic clock whose sleep() advances it.
  * `waveshare_ops()` / `waveshare_transfers()` read the vendored copy of
    Waveshare's own driver (tests/vendor/waveshare/) as DATA: parsed with
    `ast`, never imported or executed, since it is downloaded third-party
    code. They turn its init()/display()/sleep() into the SPI stream it would
    send, so ours can be compared with it byte for byte.
  * `ReplayServer` is a real TCP server on 127.0.0.1 that answers each
    connection with scripted bytes, so `fetch()` is tested through
    http.client and a real socket rather than a mock of either.

Nothing here imports gpiod, spidev or Waveshare's epdconfig.
"""
from __future__ import annotations

import ast
import functools
import hashlib
import importlib.util
import pathlib
import socket
import threading

REPO = pathlib.Path(__file__).resolve().parents[2]
PI_DIR = REPO / "firmware" / "pi_epaper_7in5"
PANEL_PY = PI_DIR / "panel.py"
DRIVER_PY = PI_DIR / "epd7in5_v2.py"
UNIT = REPO / "deploy" / "smylte-panel.service"
SETUP_SH = REPO / "deploy" / "panel-setup.sh"
VENDOR_WAVESHARE = pathlib.Path(__file__).resolve().parent / "vendor" / "waveshare" / "epd7in5_V2.py"
# The vendored file is downloaded code that CI executes; it is pinned.
VENDOR_WAVESHARE_SHA256 = "fafc41091c47d2ea367c3e85d84dca437e42370451cae5f5424b72b4614b55f2"


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def load_panel():
    """firmware/pi_epaper_7in5/panel.py, loaded by path (never put on sys.path)."""
    return _load("smylte_pi_panel", PANEL_PY)


@functools.cache
def load_driver():
    """firmware/pi_epaper_7in5/epd7in5_v2.py, loaded by path."""
    return _load("smylte_pi_epd", DRIVER_PY)


class FakeClock:
    """Monotonic seconds; sleep() advances time instead of waiting."""

    def __init__(self, t: float = 1000.0):
        self.t = float(t)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


class Recorder:
    """One ordered event log shared by the fakes.

    Events are tuples:
      ("gpio", pin, value)          a line set to 0 or 1
      ("read", pin, value)          a line read
      ("spi", dc, payload_bytes)    one transfer, with DC's level at the time
      ("spi-open",) / ("spi-close",)
      ("release",)                  the GPIO request released
      ("sleep", seconds)            only from the Waveshare fake's delay_ms
    """

    def __init__(self):
        self.events: list[tuple] = []

    def spi(self, *, drop_status_polls: bool = False) -> list[tuple[int, bytes]]:
        """(dc, payload) for every transfer; optionally without GET_STATUS (0x71)
        polls, whose count depends on how long BUSY stayed low."""
        out = [(e[1], e[2]) for e in self.events if e[0] == "spi"]
        if drop_status_polls:
            out = [t for t in out if t != (0, b"\x71")]
        return out

    def gpio(self, pin: int | None = None) -> list[tuple[int, int]]:
        return [(e[1], e[2]) for e in self.events
                if e[0] == "gpio" and (pin is None or e[1] == pin)]


class FakeLines:
    """The driver's Lines adapter. BUSY (BCM24) answers from `busy`.

    `busy` is either an int (always that level) or a callable taking the
    number of BUSY reads so far (0, 1, 2, ...) and returning 0 or 1. Every
    other pin reads back the last level it was set to (0 if never set).
    """

    def __init__(self, rec: Recorder, busy=1, busy_pin: int = 24):
        self.rec = rec
        self.levels: dict[int, int] = {}
        self.busy = busy
        self.busy_pin = busy_pin
        self.busy_reads = 0
        self.released = False
        self.fail_set: set[int] = set()   # pins whose set() raises OSError

    def set(self, pin: int, high) -> None:
        if pin in self.fail_set:
            raise OSError(5, "fake GPIO failure")
        v = 1 if high else 0
        self.levels[pin] = v
        self.rec.events.append(("gpio", pin, v))

    def get(self, pin: int) -> int:
        if pin == self.busy_pin:
            v = self.busy(self.busy_reads) if callable(self.busy) else int(self.busy)
            self.busy_reads += 1
        else:
            v = self.levels.get(pin, 0)
        self.rec.events.append(("read", pin, v))
        return v

    def release(self) -> None:
        self.released = True
        self.rec.events.append(("release",))


class FakeSpi:
    """`spidev.SpiDev` as the drivers use it. Records transfers with DC's level."""

    def __init__(self, rec: Recorder, lines: FakeLines, dc_pin: int = 25):
        self.rec = rec
        self.lines = lines
        self.dc_pin = dc_pin
        self.closed = False
        self.max_speed_hz = None
        self.mode = None
        self.fail_writes = False

    def _record(self, data) -> None:
        if self.closed:
            raise OSError(9, "fake SPI is closed")
        if self.fail_writes:
            raise OSError(5, "fake SPI failure")
        payload = bytes(int(v) & 0xFF for v in data)
        self.rec.events.append(("spi", self.lines.levels.get(self.dc_pin, 0), payload))

    def writebytes(self, data) -> None:
        self._record(data)

    def writebytes2(self, data) -> None:
        self._record(data)

    def close(self) -> None:
        self.closed = True
        self.rec.events.append(("spi-close",))


class SpiFactory:
    """What open_hardware() hands Panel: a callable that opens a new SPI."""

    def __init__(self, rec: Recorder, lines: FakeLines):
        self.rec = rec
        self.lines = lines
        self.opened: list[FakeSpi] = []

    def __call__(self) -> FakeSpi:
        spi = FakeSpi(self.rec, self.lines)
        self.opened.append(spi)
        self.rec.events.append(("spi-open",))
        return spi


def make_panel(*, busy=1, pwr_pin=None, cut_between=False, tick=None):
    """A real driver Panel on fakes. Returns (panel, rec, lines, factory, clock)."""
    epd = load_driver()
    rec = Recorder()
    lines = FakeLines(rec, busy=busy, busy_pin=epd.BUSY_PIN)
    factory = SpiFactory(rec, lines)
    clock = FakeClock()
    panel = epd.Panel(lines, factory, pwr_pin=pwr_pin, cut_between=cut_between,
                      clock=clock.monotonic, sleep=clock.sleep, tick=tick)
    return panel, rec, lines, factory, clock


def _ws_literal(node):
    """An int (or the name of a variable) as written in Waveshare's source."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ast.unparse(node)


def waveshare_ops(method: str) -> list[tuple]:
    """What one method of Waveshare's EPD class does, read from its SOURCE.

    The vendored file is downloaded third-party code, so it is treated as data:
    parsed, never imported or executed. Each call the method makes on `self`
    or `epdconfig` becomes one op, in source order:

      ("cmd", 0x06)               self.send_command(0x06)
      ("data", 0x17)              self.send_data(0x17)
      ("data2", "image1")         self.send_data2(image1)   (argument's name)
      ("delay_ms", 100)           epdconfig.delay_ms(100)
      ("busy",)                   self.ReadBusy()
      ("reset",)                  self.reset()
      ("write", "reset_pin", 1)   epdconfig.digital_write(self.reset_pin, 1)
      ("module_init",) / ("module_exit",)
      ("invert", "image1", "image")   image1[...] = ~image[...]

    Calls to builtins (int, range) and logging are ignored.
    """
    data = VENDOR_WAVESHARE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == VENDOR_WAVESHARE_SHA256, \
        "the vendored Waveshare driver changed; re-verify it before trusting it"
    tree = ast.parse(data.decode("ascii"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "EPD")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method)
    found = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.UnaryOp) \
                and isinstance(node.value.op, ast.Invert) \
                and isinstance(node.targets[0], ast.Subscript) \
                and isinstance(node.value.operand, ast.Subscript):
            found.append(((node.lineno, node.col_offset),
                          ("invert", _ws_literal(node.targets[0].value),
                           _ws_literal(node.value.operand.value))))
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        name = node.func.attr
        if not isinstance(owner, ast.Name) or owner.id not in ("self", "epdconfig"):
            continue
        args = [_ws_literal(a) for a in node.args]
        op = {
            "send_command": lambda: ("cmd", args[0]),
            "send_data": lambda: ("data", args[0]),
            "send_data2": lambda: ("data2", args[0]),
            "delay_ms": lambda: ("delay_ms", args[0]),
            "ReadBusy": lambda: ("busy",),
            "reset": lambda: ("reset",),
            "digital_write": lambda: ("write", args[0], args[1]),
            "module_init": lambda: ("module_init",),
            "module_exit": lambda: ("module_exit",),
        }.get(name)
        if op is None:
            raise AssertionError(f"Waveshare's {method}() calls {owner.id}.{name}, "
                                 "which this reader does not know")
        found.append(((node.lineno, node.col_offset), op()))
    return [op for _, op in sorted(found)]


def waveshare_transfers(method: str, frame: bytes | None = None) -> list[tuple[int, bytes]]:
    """The (dc, payload) SPI transfers Waveshare's `method` makes, GET_STATUS
    polls left out, derived from waveshare_ops(). `frame` stands in for the
    `image` argument of display(); `image1` is its complement, as the source's
    own `image1[...] = ~image[...]` loop builds it (asserted, not assumed)."""
    ops = waveshare_ops(method)
    out = []
    for op in ops:
        if op[0] == "cmd":
            out.append((0, bytes([op[1]])))
        elif op[0] == "data":
            out.append((1, bytes([op[1]])))
        elif op[0] == "data2":
            assert frame is not None, f"{method}() sends a frame; pass one"
            if op[1] == "image":
                out.append((1, bytes(frame)))
            elif op[1] == "image1":
                assert ("invert", "image1", "image") in ops, \
                    "image1 is no longer built as ~image"
                out.append((1, bytes(255 - b for b in frame)))
            else:
                raise AssertionError(f"send_data2({op[1]}) is not understood")
    return out


def raw_response(status: int, headers, body: bytes = b"", reason: str = "X") -> bytes:
    """An HTTP/1.1 response as bytes. `headers` is a list of (name, value) and
    is sent exactly as given: duplicates, order and all. Nothing is added."""
    head = f"HTTP/1.1 {status} {reason}\r\n"
    head += "".join(f"{k}: {v}\r\n" for k, v in headers)
    return head.encode("latin-1") + b"\r\n" + body


class ReplayServer:
    """A one-thread TCP server on 127.0.0.1 that answers connection N with
    `script[N]`, then closes it. Records each request's head.

    A script entry is either bytes (sent whole, then the socket is closed) or a
    callable taking the connected socket (for drips, resets, stalls); the
    server closes the socket after it returns. Connections past the end of the
    script are closed without a reply. Use as a context manager.
    """

    def __init__(self, script):
        self.script = list(script)
        self.requests: list[bytes] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> "ReplayServer":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._sock.close()

    def _read_head(self, conn: socket.socket) -> bytes:
        conn.settimeout(5)
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 65536:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
        return buf

    def _serve(self) -> None:
        n = 0
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (socket.timeout, OSError):
                continue
            with conn:
                try:
                    self.requests.append(self._read_head(conn))
                    if n < len(self.script):
                        entry = self.script[n]
                        if callable(entry):
                            entry(conn)
                        else:
                            conn.sendall(entry)
                except OSError:
                    pass
                n += 1


def request_headers(raw: bytes) -> dict[str, list[str]]:
    """The headers of a recorded request head, lower-cased, keeping repeats."""
    lines = raw.decode("latin-1").split("\r\n")[1:]
    out: dict[str, list[str]] = {}
    for line in lines:
        if not line:
            break
        name, _, value = line.partition(":")
        out.setdefault(name.strip().lower(), []).append(value.strip())
    return out
