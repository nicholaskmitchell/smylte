"""The firmware example, held to the endpoint it talks to.

`firmware/` is a new top-level directory and every CI job in this repo is scoped
to `backend/`, `frontend/`, `desktop/` or `.github/workflows/tests/` — nothing
globs the root. So without this file the example would ship with no check of any
kind, and would go on saying 48,000 bytes and `mono-hlsb` long after the server
had stopped meaning it.

The repo already has the idiom: `test_ci_interpreters.py` parses `ci.yml`,
`deploy/setup.sh` and `docs/DEPLOY.md` — files it never executes — for exactly
this reason, and `ci.yml` says why in its own words: "reading the `run:` block
out of the YAML so the thing under test cannot drift from the thing that ships".

COMPILE-ONLY, never imported. `main.py` imports `machine`, `network`, `framebuf`
and Waveshare's `epaper`, none of which exist under the CPython matrix CI runs —
and the driver is deliberately not vendored (it is third-party code with its own
licence). So this parses the source and reads its constants out of the AST.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi.testclient import TestClient
from test_displays import _api_settings

from tasksd.app import create_app
from tasksd.display import render
from tasksd.service import TaskService

REPO = pathlib.Path(__file__).resolve().parents[2]
FIRMWARE = REPO / "firmware" / "pico_epaper_7in5" / "main.py"


@pytest.fixture(scope="module")
def source() -> str:
    return FIRMWARE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def constants(source: str) -> dict:
    """Every module-level literal assignment in the example.

    Read out of the AST rather than by importing, and rather than by regex: a
    regex over `WIDTH = 800` would happily match it inside a comment or a
    docstring, and the whole value of this file is that it reads what the
    program actually says.
    """
    found: dict = {}

    def value_of(node):
        """A literal, or simple arithmetic over constants already defined.

        `BUF_BYTES = STRIDE * HEIGHT` is the reason this is not just
        `ast.literal_eval`: the example derives it rather than writing 48000,
        which is right — a hand-typed product is a second place to be wrong —
        and it means the reader has to do the multiplication too.
        """
        try:
            return ast.literal_eval(node)
        except ValueError:
            pass
        if isinstance(node, ast.Name) and node.id in found:
            return found[node.id]
        if isinstance(node, ast.BinOp):
            left, right = value_of(node.left), value_of(node.right)
            if isinstance(left, int) and isinstance(right, int):
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Add):
                    return left + right
        return None

    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                resolved = value_of(node.value)
                if resolved is not None:
                    found[target.id] = resolved
    return found


def test_the_example_is_valid_python(source: str):
    """A syntax error cannot ship. Nothing else here would catch one, because
    nothing imports this file — on the board or in CI."""
    ast.parse(source)


def test_the_constants_this_file_pins_are_actually_there(constants: dict):
    """The anti-vacuity guard, and it is not a formality.

    Every assertion below reads a name out of `constants`. Rename one in the
    example and those assertions would quietly test nothing at all — which is
    the trap `test_source_encodable.py` calls out by name with its own
    `len(files) > 40` floor.
    """
    for name in ("WIDTH", "HEIGHT", "STRIDE", "BUF_BYTES", "PATH_FMT",
                 "EXPECT_FORMAT", "MIN_REFRESH_S", "TOKEN"):
        assert name in constants, f"{name} is no longer a module-level literal"


def test_the_buffer_the_example_allocates_is_the_frame_the_server_sends(constants: dict):
    """The contract, asserted against the real renderer rather than restated.

    If the packing, the padding or the geometry ever changes server-side, this
    fails here rather than as a torn calendar on a wall.
    """
    width, height = constants["WIDTH"], constants["HEIGHT"]
    assert constants["STRIDE"] == -(-width // 8)          # ceil, the row padding
    assert constants["BUF_BYTES"] == constants["STRIDE"] * height

    import test_displays as T

    body, media = render.render_frame(
        T._frame(), width=width, height=height, fmt="raw")
    assert media == "application/octet-stream"
    assert len(body) == constants["BUF_BYTES"], (
        "the example allocates a buffer the server would not fill exactly")


def test_the_example_names_the_format_the_server_says_it_sends(constants: dict):
    # Imported, not retyped: renaming the header value server-side has to fail
    # here rather than on the panel.
    assert constants["EXPECT_FORMAT"] == render.RAW_FORMAT


def test_the_device_floor_is_never_below_the_servers(constants: dict):
    """`X-Display-Refresh-Seconds` is advisory — nothing enforces it on a
    device — so the firmware carries its own floor, and that floor may never be
    laxer than the one the server would apply to an e-ink panel."""
    assert constants["MIN_REFRESH_S"] >= TaskService._REFRESH_MIN_EINK_S


def test_the_example_reads_every_header_the_route_actually_sets(constants: dict, tmp_path):
    """The anti-drift assertion that earns its keep.

    Rename a header on the route and this fails, instead of a panel silently
    failing its own safety check and refusing every frame forever.
    """
    with TestClient(create_app(_api_settings(tmp_path))) as c:
        assert c.post("/api/login",
                      json={"username": "admin", "password": "testpass123"}
                      ).status_code == 200
        token = c.post("/api/displays",
                       json={"name": "Panel", "palette": "eink",
                             "panel_width": constants["WIDTH"],
                             "panel_height": constants["HEIGHT"]}).json()["token"]
        r = c.get(f"/api/public/display/{token}.bin")
        assert r.status_code == 200

        src = FIRMWARE.read_text(encoding="utf-8")
        for header in ("etag", "x-display-width", "x-display-height",
                       "x-display-stride", "x-display-format",
                       "x-display-refresh-seconds"):
            assert header in r.headers, f"the route stopped sending {header}"
            assert header in src, f"the example never reads {header}"
        # And the bytes really are what it allocates for.
        assert len(r.content) == constants["BUF_BYTES"]


def test_the_example_calls_the_route_that_exists(constants: dict, source: str, tmp_path):
    """The suffix in the example must be a route the app registers. Renaming
    `.bin` server-side fails here rather than on the wall."""
    app = create_app(_api_settings(tmp_path))
    paths = {getattr(r, "path", "") for r in app.routes}
    suffix = constants["PATH_FMT"].split("%s")[-1]
    assert suffix, "PATH_FMT no longer has a suffix after the token"
    assert any(p.endswith(suffix) and p.startswith("/api/public/display/")
               for p in paths), f"no route ends in {suffix}"


def test_the_example_carries_no_real_credential(constants: dict):
    """A display token is a bearer credential for a calendar. A placeholder that
    stopped looking like one is a token somebody pasted and committed."""
    assert constants["TOKEN"].startswith("<") and constants["TOKEN"].endswith(">")


def test_the_example_does_not_reach_for_the_conveniences_that_would_break_it(source: str):
    """Three specific things, each of which looks like a tidy-up and is not.

    `urequests` buffers the whole body into a second object — 48 KB of copy on a
    board also holding TLS buffers. A JSON import means it went to the wrong
    endpoint. And a panel left out of sleep is held at high voltage, which
    Waveshare say damages it beyond repair.

    Checked over the IMPORTS rather than over the text: the file names
    `urequests` in a comment saying why it does not use one, and a substring
    scan would fail on the explanation — which would teach whoever hit it to
    delete the comment rather than keep the property.
    """
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"urequests", "requests", "json", "ujson"}, imported
    assert "socket" in imported, "the example stopped talking to a socket directly"

    assert "epd.sleep()" in source, "the panel is never put back to sleep"
    # deepsleep resets the board on rp2, which loses the ETag and makes every
    # wake a full repaint — the README documents the variant that persists it.
    assert "machine.lightsleep" in source


# ── the example's own logic, actually executed ──────────────────────────────
#
# Everything above reads the file's constants. These run its FUNCTIONS: the
# checks that decide whether a frame reaches the glass are pure — headers in,
# bool out — so they can be exec'd under CPython even though the module around
# them imports `machine`, `network` and Waveshare's driver.
#
# Worth the machinery because these are the safety checks. Before this file they
# had no test at all, and one of them was `BUF_BYTES == BUF_BYTES`.

@pytest.fixture(scope="module")
def usable(source: str, constants: dict):
    """The example's `usable`, bound to the example's own constants."""
    tree = ast.parse(source)
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "usable"), None)
    assert fn is not None, "the example no longer has a `usable`"
    ns: dict = dict(constants)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(FIRMWARE), "exec"), ns)
    return ns["usable"]


def _headers(constants: dict, **over) -> dict:
    good = {
        "x-display-format": constants["EXPECT_FORMAT"],
        "x-display-width": str(constants["WIDTH"]),
        "x-display-height": str(constants["HEIGHT"]),
        "x-display-stride": str(constants["STRIDE"]),
        "content-length": str(constants["BUF_BYTES"]),
    }
    good.update(over)
    return {k: v for k, v in good.items() if v is not None}


def test_the_example_accepts_the_frame_the_route_really_sends(usable, constants, tmp_path):
    """The anti-vacuity half: a refusal that refuses everything is not a check.

    Built from the LIVE response rather than from a dict written here, so a
    header the route stops sending fails this rather than passing it.
    """
    with TestClient(create_app(_api_settings(tmp_path))) as c:
        c.post("/api/login", json={"username": "admin", "password": "testpass123"})
        token = c.post("/api/displays",
                       json={"name": "Panel", "palette": "eink",
                             "panel_width": constants["WIDTH"],
                             "panel_height": constants["HEIGHT"]}).json()["token"]
        r = c.get(f"/api/public/display/{token}.bin")
        assert r.status_code == 200
        live = {k.lower(): v for k, v in r.headers.items()}
        assert usable(live), "the example would refuse the frame the route sends"


@pytest.mark.parametrize("bad", [
    # A re-framed body. The read loop proves 48,000 bytes came off the SOCKET,
    # which is not the same fact — and this is the check that used to be
    # `BUF_BYTES == BUF_BYTES` and therefore always true.
    {"content-length": "12345"},
    {"content-length": None},
    {"content-length": None, "transfer-encoding": "chunked"},
    {"content-encoding": "gzip"},
    # A panel of a different shape, or a server that changed its packing.
    {"x-display-width": "600"},
    {"x-display-height": "448"},
    {"x-display-stride": "75"},
    {"x-display-format": "mono-hlsb-inverted"},
    {"x-display-format": None},
])
def test_the_example_refuses_a_frame_it_cannot_safely_paint(usable, constants, bad):
    """Each of these would clock a mis-shaped buffer onto the glass — diagonal
    garbage on a wall in another room, with nothing on screen to say why."""
    assert not usable(_headers(constants, **bad))


def test_the_example_never_sleeps_outside_the_range_its_hardware_allows(constants):
    """The refresh clamp, evaluated as the example writes it.

    `machine.lightsleep` takes a machine word and the value comes off the
    network, so the ceiling is not tidiness: on the 32-bit rp2 port an
    out-of-range argument raises OverflowError, and that call used to be the one
    statement in the loop outside the try.
    """
    lo, hi = constants["MIN_REFRESH_S"], constants["MAX_REFRESH_S"]
    assert lo >= TaskService._REFRESH_MIN_EINK_S
    assert hi <= 86_400
    clamp = lambda n: min(hi, max(lo, n))          # noqa: E731 — the source line
    assert clamp(1) == lo and clamp(0) == lo and clamp(-99) == lo
    assert clamp(10 ** 12) == hi
    assert clamp(900) == 900
    # And the source really is the expression this mirrors.
    src = FIRMWARE.read_text(encoding="utf-8")
    assert "min(MAX_REFRESH_S," in src and "max(MIN_REFRESH_S," in src
    # ...inside the guarded region, which is the half that ends the program.
    assert "try:\n            machine.lightsleep(wait * 1000)" in src


def test_the_raw_route_never_advises_an_interval_the_glass_forbids(constants, tmp_path):
    """`raw` IS an e-ink request, whatever the display is configured as.

    The stored floor is keyed on the palette, and the schema defaults it to
    `color` — so a panel fetching `.bin` was being advised 60 seconds for glass
    rated at 180 and documented as damaged beyond repair below it.
    """
    with TestClient(create_app(_api_settings(tmp_path))) as c:
        c.post("/api/login", json={"username": "admin", "password": "testpass123"})
        token = c.post("/api/displays",
                       json={"name": "Panel", "palette": "color",
                             "refresh_seconds": 60,
                             "panel_width": constants["WIDTH"],
                             "panel_height": constants["HEIGHT"]}).json()["token"]
        # The colour formats keep the owner's setting: an LCD has no such limit.
        assert c.get(f"/api/public/display/{token}.png"
                     ).headers["X-Display-Refresh-Seconds"] == "60"
        raw = c.get(f"/api/public/display/{token}.bin")
        assert int(raw.headers["X-Display-Refresh-Seconds"]) >= TaskService._REFRESH_MIN_EINK_S
        # And the firmware would not go below its own floor anyway — the header
        # is advice, which is exactly why it must not be bad advice.
        assert constants["MIN_REFRESH_S"] >= TaskService._REFRESH_MIN_EINK_S


def test_the_example_verifies_tls_when_it_is_given_a_ca_and_says_so_when_it_is_not(
        source: str, constants: dict):
    """MicroPython's `ssl.wrap_socket` does NOT verify by default.

    `cert_reqs` defaults to CERT_NONE and `server_hostname` only sets SNI, so an
    unconfigured handshake completes against any certificate at all. TOKEN is a
    bearer credential for the owner's calendar, so the file has to either verify
    or stop claiming that TLS protects it.
    """
    assert "CA_FILE" in constants
    assert constants["CA_FILE"] == "", "a real path would be someone's own server"
    assert "ssl.CERT_REQUIRED" in source and "load_verify_locations" in source
    # And the honest caveat is there for the unset case, rather than the earlier
    # claim that TLS alone kept the token safe.
    assert "passive" in source.lower()


def test_the_loop_re_joins_wifi_after_a_drop_rather_than_polling_a_dead_link(source: str):
    """2026-09-03 sweep. `connect_wifi()` was called exactly once, before
    `while True:`, and its return value was discarded. On the rp2/cyw43 port the
    STA interface does not re-associate on its own after the access point goes
    away (cyw43_ctrl.c clears the join state on DISASSOC and never retries), so
    after a router reboot every `fetch()` raised at `getaddrinfo`, the
    `except Exception:` swallowed it, and the panel showed the last frame until
    someone cut the power — the exact failure SOCKET_TIMEOUT_S's own comment says
    this file avoids. `connect_wifi` already carries the self-heal (retries, then
    `machine.reset()`); it was simply unreachable after boot.

    Read out of the AST like the constants: the loop body must check the link
    and call `connect_wifi` again, and `main` must keep the `wlan` object the
    check is made on. No existing test looked inside the loop at all.
    """
    tree = ast.parse(source, str(FIRMWARE))
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    loop = next(n for n in ast.walk(main) if isinstance(n, ast.While))

    kept = [n for n in ast.walk(main)
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name) and n.value.func.id == "connect_wifi"]
    assert kept, "main() discards what connect_wifi() returns, so nothing can ask it later"

    in_loop = list(ast.walk(loop))
    assert any(isinstance(n, ast.Attribute) and n.attr == "isconnected" for n in in_loop), \
        "the loop never asks whether the link is still up"
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "connect_wifi" for n in in_loop), \
        "the loop never re-joins: connect_wifi's retry-then-reset path is unreachable after boot"
