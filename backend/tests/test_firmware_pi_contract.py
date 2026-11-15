"""The Pi panel client, held to the live server and to a real socket.

`firmware/pi_epaper_7in5/panel.py` speaks to the Smylte server over HTTP and
imports nothing from it, so nothing but a test can notice the two drifting
apart. Its constants (size, format name, refresh bounds, address, route) are
checked here against the server's own, its header checks are run against a real
response from the real app, and `fetch()` is run through http.client against a
scripted TCP server, so the client and the server cannot change alone.

Also pinned: the bytes the controller receives are the bytes the Pico example
sends, and loading the client and the driver touches no hardware library.
"""
from __future__ import annotations

import ast
import socket
import struct
import sys
import time
import urllib.parse

import pi_panel_fakes as F
import pytest
from fastapi.testclient import TestClient
from test_displays import _api_settings, _frame

from smylted.app import create_app
from smylted.display import render
from smylted.service import SmylteService

P = F.load_panel()
E = F.load_driver()

GOOD = [("content-type", "application/octet-stream"), ("content-length", "48000"),
        ("etag", '"' + "a" * 32 + '"'), ("x-display-width", "800"), ("x-display-height", "480"),
        ("x-display-stride", "100"), ("x-display-format", "mono-hlsb-inverted"),
        ("x-display-refresh-seconds", "300")]


def new_display(c) -> str:
    return c.post("/api/displays", json={"name": "Desk", "palette": "eink",
                                         "panel_width": 800, "panel_height": 480}).json()["token"]


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    with TestClient(create_app(_api_settings(tmp_path_factory.mktemp("pi")))) as c:
        assert c.post("/api/login", json={"username": "admin", "password": "testpass123"}).status_code == 200
        token = new_display(c)
        yield c, token


@pytest.fixture(scope="module")
def live_response(live):
    c, token = live
    r = c.get(P.request_target(token))
    assert r.status_code == 200
    return r.headers.multi_items(), r.content, r


# ── constants against the server ─────────────────────────────────────────────

def test_loading_the_client_and_the_driver_touches_no_hardware():
    F.load_panel()
    F.load_driver()
    assert "gpiod" not in sys.modules
    assert "spidev" not in sys.modules


def test_the_frame_size_agrees_between_client_driver_and_server():
    assert P.WIDTH == 800
    assert P.HEIGHT == 480
    assert P.STRIDE == (P.WIDTH + 7) // 8
    assert P.BUF_BYTES == P.STRIDE * P.HEIGHT
    assert E.WIDTH == P.WIDTH
    assert E.HEIGHT == P.HEIGHT
    assert E.BUF_BYTES == P.BUF_BYTES
    body, media = render.render_frame(_frame(), width=P.WIDTH, height=P.HEIGHT,
                                      fmt="raw", invert=True)
    assert len(body) == P.BUF_BYTES
    assert media == P.EXPECT_MEDIA


def test_the_format_name_is_the_servers_inverted_one():
    assert P.EXPECT_FORMAT == render.RAW_FORMAT_INVERTED
    assert P.EXPECT_FORMAT != render.RAW_FORMAT


def test_the_refresh_bounds_agree_with_the_server_and_the_driver():
    assert P.MIN_REFRESH_S >= SmylteService._REFRESH_MIN_EINK_S
    assert P.MAX_REFRESH_S == SmylteService._REFRESH_MAX_S
    assert P.FORCE_REPAINT_S < 86_400
    assert P.PAINT_MAX_S >= E.PAINT_WORST_S


def test_the_address_is_the_one_the_server_binds():
    tree = ast.parse((F.REPO / "backend" / "smylted" / "__main__.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and ast.unparse(n.func) == "uvicorn.run"]
    assert len(calls) == 1
    kw = {k.arg: ast.literal_eval(k.value) for k in calls[0].keywords}
    assert kw["host"] == P.HOST
    assert kw["port"] == P.PORT


def test_the_request_target_is_a_registered_route(tmp_path):
    target = P.request_target("x" * 43)
    path, _, query = target.partition("?")
    assert path == "/api/public/display/" + "x" * 43 + ".bin"
    paths = [getattr(r, "path", None) for r in create_app(_api_settings(tmp_path)).routes]
    assert P.PATH_FMT % "{token}" in paths
    assert urllib.parse.parse_qs(query) == {"invert": ["1"], "w": [str(P.WIDTH)],
                                            "h": [str(P.HEIGHT)]}
    assert "palette" not in query


# ── the live frame ───────────────────────────────────────────────────────────

def test_the_live_frame_passes_every_header_check(live):
    c, token = live
    r = c.get(P.request_target(token))
    assert r.status_code == 200
    assert P.check_headers(200, r.headers.multi_items(), chunked=False,
                           length=int(r.headers["content-length"])) is None
    assert len(r.content) == P.BUF_BYTES


def test_every_required_header_is_really_sent_once(live_response):
    items, _, r = live_response
    names = [k.lower() for k, _ in r.headers.multi_items()]
    for name in P.REQUIRED_HEADERS:
        assert names.count(name) == 1, name


def test_the_plain_frame_is_refused_on_its_format(live):
    c, token = live
    r = c.get(f"/api/public/display/{token}.bin?w=800&h=480")
    assert P.check_headers(200, r.headers.multi_items(),
                           length=int(r.headers["content-length"])) == "x-display-format"


def test_a_matching_etag_gets_a_304(live):
    c, token = live
    target = P.request_target(token)
    r1 = c.get(target)
    r2 = c.get(target, headers={"If-None-Match": r1.headers["etag"]})
    assert r2.status_code == 304
    assert r2.headers["etag"] == r1.headers["etag"]


def test_a_rotated_token_is_gone(live):
    c, _ = live
    t = new_display(c)
    rot = c.post(f"/api/displays/{t}/rotate")
    assert rot.status_code == 200
    new = rot.json()["token"]
    assert new != t
    assert c.get(P.request_target(t)).status_code == 404
    assert c.get(P.request_target(new)).status_code == 200


def test_a_disabled_display_is_gone(live):
    c, _ = live
    t = new_display(c)
    assert c.patch(f"/api/displays/{t}", json={"enabled": False}).status_code == 200
    assert c.get(P.request_target(t)).status_code == 404


def test_the_glass_receives_exactly_what_the_pico_sent(live):
    """Waveshare's Pico MicroPython driver sends OLD (0x10) = buffer and NEW
    (0x13) = ~buffer from the plain `.bin`. Ours sends OLD = ~frame and NEW =
    frame from the inverted one. So the controller gets identical bytes."""
    c, token = live
    plain = c.get(f"/api/public/display/{token}.bin?w=800&h=480").content
    inv = c.get(P.request_target(token)).content
    assert inv == bytes(b ^ 0xFF for b in plain)
    panel, rec, *_ = F.make_panel()
    panel.init()
    panel.display(inv)
    panel.sleep()
    frames = [t for t in rec.spi() if len(t[1]) == P.BUF_BYTES]
    assert frames == [(1, plain), (1, inv)]
    # A calendar page is mostly white paper, and 1 = black ink here.
    assert sum(bin(b).count("1") for b in inv) < len(inv) * 8 / 2


# ── check_headers, clamp_refresh, parse_retry_after ──────────────────────────

def _set(items, name, value):
    return [(k, value if k == name else v) for k, v in items]


def _drop(items, name):
    return [(k, v) for k, v in items if k != name]


def test_a_known_good_header_list_passes():
    assert P.check_headers(200, GOOD, length=48000) is None
    assert P.check_headers(200, [(k.title(), v) for k, v in GOOD], length=48000) is None
    assert P.check_headers(200, GOOD + [("content-encoding", "identity")],
                           length=48000) is None


REFUSALS = [
    ("length-header-wrong", _set(GOOD, "content-length", "12345"), {}, "content-length"),
    ("length-header-missing", _drop(GOOD, "content-length"), {}, "header-content-length"),
    ("length-header-twice", GOOD + [("content-length", "48000")], {}, "header-content-length"),
    ("length-header-plus-sign", _set(GOOD, "content-length", "+48000"), {}, "content-length"),
    ("length-argument-short", GOOD, {"length": 47999}, "content-length"),
    ("transfer-encoding-header", GOOD + [("transfer-encoding", "chunked")], {},
     "transfer-encoding"),
    ("chunked-flag", GOOD, {"chunked": True}, "transfer-encoding"),
    ("content-encoding-gzip", GOOD + [("content-encoding", "gzip")], {}, "content-encoding"),
    ("width", _set(GOOD, "x-display-width", "600"), {}, "x-display-width"),
    ("height", _set(GOOD, "x-display-height", "448"), {}, "x-display-height"),
    ("stride", _set(GOOD, "x-display-stride", "75"), {}, "x-display-stride"),
    ("format-plain", _set(GOOD, "x-display-format", "mono-hlsb"), {}, "x-display-format"),
    ("format-missing", _drop(GOOD, "x-display-format"), {}, "header-x-display-format"),
    ("content-type", _set(GOOD, "content-type", "text/html"), {}, "content-type"),
    ("etag-weak", _set(GOOD, "etag", 'W/"abc"'), {}, "etag"),
    ("etag-empty", _set(GOOD, "etag", '""'), {}, "etag"),
    ("etag-space", _set(GOOD, "etag", '"a b"'), {}, "etag"),
    ("etag-too-long", _set(GOOD, "etag", '"' + "a" * 129 + '"'), {}, "etag"),
    ("status-206", GOOD, {"status": 206}, "status-206"),
    ("status-301", GOOD, {"status": 301}, "status-301"),
]


@pytest.mark.parametrize("items,kwargs,expected",
                         [pytest.param(i, k, e, id=n) for n, i, k, e in REFUSALS])
def test_check_headers_refuses(items, kwargs, expected):
    kw = {"length": 48000, "chunked": False, **kwargs}
    status = kw.pop("status", 200)
    assert P.check_headers(status, items, **kw) == expected


@pytest.mark.parametrize("value", [None, "0", "1", "-5", "abc", "1e3", "", "9" * 99,
                                   " 300", "180"])
def test_clamp_refresh_falls_back_to_the_floor(value):
    assert P.clamp_refresh(value) == 180


def test_clamp_refresh_keeps_a_value_in_range():
    assert P.clamp_refresh("300") == 300


@pytest.mark.parametrize("value", ["86400", "86401", "999999999"])
def test_clamp_refresh_stops_at_a_day(value):
    assert P.clamp_refresh(value) == 86400


@pytest.mark.parametrize("value", [None, "1e3", "-1", "Wed, 21 Oct 2015 07:28:00 GMT", "9999999"])
def test_parse_retry_after_falls_back_to_the_default(value):
    assert P.parse_retry_after(value) == 300


@pytest.mark.parametrize("value,expected", [("0", 60), ("59", 60), ("60", 60), ("120", 120),
                                            ("3600", 3600), ("3601", 3600)])
def test_parse_retry_after_is_held_to_a_minute_and_an_hour(value, expected):
    assert P.parse_retry_after(value) == expected


# ── fetch() over a real socket ───────────────────────────────────────────────

def _fetch(token, script, etag=None, **kw):
    """fetch() against a ReplayServer playing `script`; returns (result, server)."""
    with F.ReplayServer(script) as server:
        result = P.fetch(token, etag, port=server.port, **kw)
    return result, server


@pytest.fixture(scope="module")
def good(live_response):
    items, body, _ = live_response
    return F.raw_response(200, items, body, "OK")


def test_fetch_returns_the_live_frame(live, live_response, good):
    _, token = live
    items, body, r = live_response
    result, server = _fetch(token, [good])
    assert result == P.Frame(body=body, etag=r.headers["etag"],
                             refresh_s=P.clamp_refresh(r.headers["x-display-refresh-seconds"]))
    assert len(server.requests) == 1
    lines = server.requests[0].decode("latin-1").split("\r\n")
    assert lines[0] == f"GET {P.request_target(token)} HTTP/1.1"
    h = F.request_headers(server.requests[0])
    assert h["accept-encoding"] == ["identity"]
    assert "if-none-match" not in h
    assert "x-real-ip" not in h
    assert h["user-agent"] == [P.USER_AGENT]


def test_fetch_sends_the_etag_and_accepts_the_matching_304(live):
    _, token = live
    tag = '"' + "b" * 32 + '"'
    reply = F.raw_response(304, [("etag", tag), ("x-display-refresh-seconds", "300")],
                           b"", "Not Modified")
    result, server = _fetch(token, [reply], etag=tag)
    assert F.request_headers(server.requests[0])["if-none-match"] == [tag]
    assert result == P.NotModified(etag=tag, refresh_s=300)


def test_fetch_refuses_a_duplicated_content_length(live, live_response):
    _, token = live
    items, body, _ = live_response
    reply = F.raw_response(200, items + [("content-length", "48000")], body, "OK")
    result, _ = _fetch(token, [reply])
    assert isinstance(result, P.Refused)
    assert result.reason == "header-content-length"


def test_fetch_refuses_a_transfer_encoding_header(live, live_response):
    _, token = live
    items, body, _ = live_response
    reply = F.raw_response(200, items + [("transfer-encoding", "chunked")], body, "OK")
    result, _ = _fetch(token, [reply])
    assert isinstance(result, P.Refused)
    assert result.reason == "transfer-encoding"


def test_fetch_treats_a_short_body_as_transient(live, live_response):
    _, token = live
    items, body, _ = live_response
    result, _ = _fetch(token, [F.raw_response(200, items, body[:1000], "OK")])
    assert isinstance(result, P.Transient)


def test_fetch_reads_only_the_declared_length(live, live_response):
    _, token = live
    items, body, _ = live_response
    result, _ = _fetch(token, [F.raw_response(200, items, body + b"\x00" * 10, "OK")])
    assert isinstance(result, P.Frame)
    assert result.body == body


def test_fetch_gives_up_on_a_slow_drip_at_the_deadline(live, live_response):
    _, token = live
    items, body, _ = live_response

    def drip(conn):
        try:
            conn.sendall(F.raw_response(200, items, b"", "OK"))
            for i in range(0, len(body), 1000):
                conn.sendall(body[i:i + 1000])
                time.sleep(0.05)
        except OSError:
            return

    started = time.monotonic()
    result, _ = _fetch(token, [drip], timeout=2, deadline_s=0.5)
    assert isinstance(result, P.Transient)
    assert time.monotonic() - started < 3


def test_fetch_treats_a_reset_mid_body_as_transient(live, live_response):
    _, token = live
    items, body, _ = live_response

    def reset(conn):
        conn.sendall(F.raw_response(200, items, body[:1000], "OK"))
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))

    result, _ = _fetch(token, [reset])
    assert isinstance(result, P.Transient)


def test_fetch_refuses_a_304_when_it_sent_no_etag(live):
    _, token = live
    reply = F.raw_response(304, [("etag", '"' + "a" * 32 + '"')], b"", "Not Modified")
    result, _ = _fetch(token, [reply], etag=None)
    assert result == P.Refused("304-etag", 304)


def test_fetch_refuses_a_304_for_a_different_etag(live):
    _, token = live
    reply = F.raw_response(304, [("etag", '"' + "a" * 32 + '"')], b"", "Not Modified")
    result, _ = _fetch(token, [reply], etag='"' + "b" * 32 + '"')
    assert isinstance(result, P.Refused)
    assert result.reason == "304-etag"


def test_fetch_reports_a_404_as_gone(live):
    _, token = live
    result, _ = _fetch(token, [F.raw_response(404, [("content-length", "0")], b"", "Not Found")])
    assert result == P.Gone()


def test_fetch_reads_retry_after_on_a_429(live):
    _, token = live
    reply = F.raw_response(429, [("retry-after", "120"), ("content-length", "0")], b"",
                           "Too Many Requests")
    result, _ = _fetch(token, [reply])
    assert result == P.Throttled(120)


def test_fetch_defaults_a_429_without_retry_after(live):
    _, token = live
    reply = F.raw_response(429, [("content-length", "0")], b"", "Too Many Requests")
    result, _ = _fetch(token, [reply])
    assert result == P.Throttled(300)


def test_fetch_treats_a_500_as_transient(live):
    _, token = live
    reply = F.raw_response(500, [("content-length", "0")], b"", "Internal Server Error")
    result, _ = _fetch(token, [reply])
    assert isinstance(result, P.Transient)


def test_fetch_does_not_follow_a_redirect(live):
    _, token = live
    reply = F.raw_response(302, [("location", "http://127.0.0.1:1/"), ("content-length", "0")],
                           b"", "Found")
    result, server = _fetch(token, [reply])
    assert result == P.Refused("HTTP 302", 302)
    assert len(server.requests) == 1


def test_fetch_refuses_a_422(live):
    _, token = live
    reply = F.raw_response(422, [("content-length", "0")], b"", "Unprocessable Entity")
    result, _ = _fetch(token, [reply])
    assert isinstance(result, P.Refused)
    assert result.status == 422


def test_fetch_treats_a_close_without_a_reply_as_transient(live):
    _, token = live
    result, _ = _fetch(token, [])
    assert isinstance(result, P.Transient)


def test_fetch_treats_a_port_with_nothing_listening_as_transient(live):
    _, token = live
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert isinstance(P.fetch(token, None, port=port, timeout=1), P.Transient)


def test_fetch_gives_up_on_a_server_that_stalls_before_replying(live, good):
    _, token = live

    def stall(conn):
        time.sleep(1.0)
        conn.sendall(good)

    started = time.monotonic()
    result, _ = _fetch(token, [stall], timeout=0.2)
    assert isinstance(result, P.Transient)
    assert time.monotonic() - started < 3


# ── the desk key's views and screens, against the live server ───────────────

def new_switchable_display(c) -> str:
    return c.post("/api/displays", json={"name": "Desk", "palette": "eink", "panel_width": 800,
                                         "panel_height": 480, "switchable": True}).json()["token"]


def _live_fetch(c, token, etag=None, **kw):
    """fetch() of what the live server answers to the same request, replayed
    over a real socket. Returns (result, the live response)."""
    target = P.request_target(token, **kw)
    r = c.get(target, headers={"If-None-Match": etag} if etag else {})
    raw = F.raw_response(r.status_code, r.headers.multi_items(), r.content,
                         r.reason_phrase or "X")
    result, server = _fetch(token, [raw], etag, **kw)
    assert server.requests[0].decode("latin-1").split("\r\n")[0] == f"GET {target} HTTP/1.1"
    return result, r


def test_a_view_fetch_of_a_switchable_display_is_that_view_with_its_strip(live):
    c, _ = live
    token = new_switchable_display(c)
    result, r = _live_fetch(c, token, mode="now", tabs=True)
    assert isinstance(result, P.Frame), result
    assert (result.mode, result.strip) == ("now", (440, 480))
    assert result.body == r.content
    assert result.etag == r.headers["etag"]


def test_a_screen_fetch_is_a_frame_with_no_view_and_no_strip(live):
    c, _ = live
    token = new_switchable_display(c)
    result, r = _live_fetch(c, token, screen="confirm")
    assert isinstance(result, P.Frame), result
    assert (result.mode, result.strip) == (None, None)
    assert result.body == r.content


def test_a_view_fetch_with_its_own_etag_is_not_modified(live):
    c, _ = live
    token = new_switchable_display(c)
    first, _ = _live_fetch(c, token, mode="now", tabs=True)
    assert isinstance(first, P.Frame), first
    again, r = _live_fetch(c, token, etag=first.etag, mode="now", tabs=True)
    assert r.status_code == 304
    assert again == P.NotModified(first.etag, first.refresh_s)


def test_a_view_fetch_of_a_display_that_does_not_switch_is_refused_as_views_off(live):
    c, _ = live
    token = new_display(c)
    result, r = _live_fetch(c, token, mode="now")
    assert r.status_code == 422
    assert isinstance(result, P.Refused), result
    assert (result.status, result.code) == (422, "views-off")
