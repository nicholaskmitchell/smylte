# A Smylte display on a Raspberry Pi Pico 2 W and a Waveshare 7.5" e-paper HAT.
#
# The whole program is: ask the server whether anything changed, and if it did,
# read 48,000 bytes straight into the panel's own framebuffer and show them.
# There is no image decoder here and there is not meant to be one. `/…​.bin`
# answers with the packed 1-bit buffer this driver already holds — eight pixels
# a byte, MSB leftmost, rows of `ceil(width / 8)`, bit 1 = white — which is
# exactly `framebuf.MONO_HLSB`. The bytes go from the socket to the glass.
#
# The other two formats are here for boards that are not this one. `.png` is
# saved with adaptive row filtering, so decoding it needs zlib and all five PNG
# unfilters; `.bmp` is a 62-byte container stored bottom-up with rows padded to
# four bytes. Either is a decoder you would have to write before you could see a
# calendar, on a board that has better things to do with its RAM.
#
# MicroPython, tested shape: Pico 2 W (the plain Pico 2 has no radio) + the
# Waveshare Pico-ePaper-7.5. See ../README.md for the driver, the wiring and the
# three constants below that you have to change.

import framebuf  # noqa: F401 — imported for the record; the driver subclasses it
import machine
import network
import socket
import ssl
import time

from epaper import EPD_7in5  # Waveshare's driver — see ../README.md

# ── things you change ────────────────────────────────────────────────────────
WIFI_SSID = "<your-wifi>"
WIFI_PASSWORD = "<your-wifi-password>"
HOST = "<your-smylte-host>"
# From Settings → Displays. It is a bearer credential for your calendar: anyone
# holding it can read what this screen shows, so treat it like a password and
# rotate it from that screen if it gets out.
TOKEN = "<paste-your-display-token-here>"

# ── the contract with the server ─────────────────────────────────────────────
# These are checked against the response before anything is painted, and
# `backend/tests/test_firmware_example.py` checks them against the server, so
# this file cannot quietly drift from the endpoint it talks to.
WIDTH = 800
HEIGHT = 480
STRIDE = 100                       # ceil(WIDTH / 8) — bytes per row
BUF_BYTES = STRIDE * HEIGHT        # 48,000
PATH_FMT = "/api/public/display/%s.bin"
EXPECT_FORMAT = "mono-hlsb"

# TLS by default, because TOKEN is a credential and a plain request puts it in
# the clear for everyone on the network. Set False only for a server on your own
# LAN that has no certificate — and know what you are choosing.
USE_TLS = True
PORT = 443 if USE_TLS else 80

# The floor this device will not go below whatever the server says. The server
# has its own e-ink floor, but `X-Display-Refresh-Seconds` is ADVISORY — a
# firmware that trusted it blindly would be one misconfiguration away from
# refreshing every minute. Waveshare rate this panel at one refresh per 180
# seconds and require it to sleep in between; the alternative damages it beyond
# repair, and no server-side setting can protect glass on your wall.
MIN_REFRESH_S = 180

# How long a fetch may hang. A panel at the edge of its wifi range will meet a
# half-open socket eventually, and a display that blocks forever is a display
# that shows Tuesday until someone power-cycles it.
SOCKET_TIMEOUT_S = 30
WIFI_ATTEMPTS = 20


def connect_wifi():
    """Join the network, or reset the board trying.

    A screen on a wall has nobody at a REPL. Every failure path here ends in
    `machine.reset()` rather than an exception, because a board that reboots
    into a retry is a display that heals itself overnight.
    """
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        for _ in range(WIFI_ATTEMPTS):
            if wlan.isconnected():
                break
            time.sleep(1)
    if not wlan.isconnected():
        machine.reset()
    return wlan


def fetch(buf, etag):
    """Ask for a frame. Returns (status, headers, new_etag).

    On 200 `buf` has been filled with exactly BUF_BYTES. On 304 it is untouched,
    which is the case worth optimising for: a full refresh of this panel is
    seconds of power and a visible flash across the room, and most polls have
    nothing new to show.

    Raw sockets rather than `urequests`, deliberately. That library buffers the
    whole body into a second object before handing it over — 48 KB of copy on a
    board that is also holding mbedTLS record buffers — and this needs to read
    the headers itself anyway.
    """
    addr = socket.getaddrinfo(HOST, PORT)[0][-1]
    sock = socket.socket()
    sock.settimeout(SOCKET_TIMEOUT_S)
    try:
        sock.connect(addr)
        stream = ssl.wrap_socket(sock, server_hostname=HOST) if USE_TLS else sock
        request = (
            "GET " + (PATH_FMT % TOKEN) + " HTTP/1.1\r\n"
            "Host: " + HOST + "\r\n"
            "Connection: close\r\n"
        )
        if etag:
            # The line that stops the panel repainting for nothing.
            request += "If-None-Match: " + etag + "\r\n"
        stream.write((request + "\r\n").encode())

        status = int(stream.readline().split()[1])
        headers = {}
        while True:
            line = stream.readline()
            if not line or line == b"\r\n":
                break
            name, _, value = line.decode().partition(":")
            headers[name.strip().lower()] = value.strip()

        if status != 200:
            return status, headers, etag

        # Read until the buffer is FULL. `readinto` returns short reads — one
        # call is not one frame — and assuming otherwise is the classic bug
        # here: it leaves the buffer half new and half last-hour, which paints
        # as a calendar torn across the middle.
        view = memoryview(buf)
        got = 0
        while got < BUF_BYTES:
            n = stream.readinto(view[got:])
            if not n:
                break
            got += n
        if got != BUF_BYTES:
            # A short frame is not painted and its ETag is not kept, so the next
            # poll fetches the whole thing again.
            return 0, headers, etag
        return 200, headers, headers.get("etag", "")
    finally:
        try:
            stream.close()
        except Exception:
            pass
        sock.close()


def usable(headers, body_len):
    """Is this frame safe to put on the glass?

    Refusing is cheap and repainting a mis-shaped buffer is not: the failure
    shows up as diagonal garbage on a wall in another room, with nothing on the
    screen to say what went wrong.
    """
    return (
        headers.get("x-display-format") == EXPECT_FORMAT
        and headers.get("x-display-width") == str(WIDTH)
        and headers.get("x-display-height") == str(HEIGHT)
        and headers.get("x-display-stride") == str(STRIDE)
        and body_len == BUF_BYTES
    )


def main():
    connect_wifi()
    epd = EPD_7in5()
    # Allocated ONCE, for the life of the program. `epd.buffer` is the driver's
    # own `bytearray(WIDTH * HEIGHT // 8)` behind its MONO_HLSB FrameBuffer, and
    # the server's bytes are that array — so the frame is read straight into the
    # thing that gets clocked out to the panel. No decode, no copy, no second
    # 48 KB allocation on a board with 520 KB.
    buf = epd.buffer
    etag = ""
    epd.sleep()

    while True:
        wait = MIN_REFRESH_S
        try:
            status, headers, new_etag = fetch(buf, etag)
            # The server's interval is a request, never a permission: this panel
            # will not refresh faster than its own floor whatever it is told.
            wait = max(MIN_REFRESH_S,
                       int(headers.get("x-display-refresh-seconds", MIN_REFRESH_S)))
            if status == 200 and usable(headers, BUF_BYTES):
                epd.init()
                epd.display(buf)
                # Straight back to sleep. Waveshare are explicit that leaving
                # the panel powered holds it at high voltage and damages it
                # permanently, so this call is not an optimisation.
                epd.sleep()
                etag = new_etag
            # 304, a short read, or a frame that failed `usable`: the panel is
            # not touched and the old ETag is kept, so nothing repaints and the
            # next poll tries again.
        except Exception:
            # Never die on a wall. A failed cycle is a cycle; the next one may
            # well work, and the screen goes on showing the last good frame in
            # the meantime — which is the whole advantage of e-paper.
            try:
                epd.sleep()
            except Exception:
                pass
        # `lightsleep` rather than `deepsleep`: on the rp2 port deepsleep RESETS
        # the board, which loses `etag` and makes every wake a full repaint. See
        # ../README.md for the deepsleep variant, which has to persist the ETag
        # to a file to be worth anything.
        machine.lightsleep(wait * 1000)


main()
