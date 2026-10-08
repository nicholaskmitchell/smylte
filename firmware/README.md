# A Smylte panel on a microcontroller

`pico_epaper_7in5/main.py` turns a **Raspberry Pi Pico 2 W** and a **Waveshare
Pico-ePaper-7.5** (800×480, black and white) into a Smylte display. It is an
example, not a library. It is about sixty lines because
`/api/public/display/<token>.bin` returns the framebuffer the panel already
uses, so the client reads the socket into `epd.buffer` and shows it.

## What you need

| | |
| --- | --- |
| Board | **Pico 2 W** (the plain Pico 2 has no wifi) |
| Panel | Waveshare Pico-ePaper-7.5, 800×480, 1-bit |
| Firmware | MicroPython for RP2350 (Pico 2 W build) |
| Driver | Waveshare's `Pico_ePaper-7.5.py`, copied to the board as `epaper.py` |

The driver isn't included here. Get it from
[waveshareteam/Pico_ePaper_Code](https://github.com/waveshareteam/Pico_ePaper_Code).

## Setting it up

1. Flash MicroPython for the Pico 2 W.
2. Copy Waveshare's `Pico_ePaper-7.5.py` to the board as `epaper.py`.
3. In Settings → Displays, add a display, set **Screen** to *E-ink* and
   **Panel size** to 800 × 480, and copy its URL.
4. Edit the constants at the top of `main.py`: `WIFI_SSID`, `WIFI_PASSWORD`,
   `HOST`, `TOKEN`. Read the TLS section below before leaving `CA_FILE` empty.
5. Copy `main.py` to the board. It runs on power-up.

## The wire format

`.bin` is the framebuffer and nothing else: no header, no compression.

| | |
| --- | --- |
| Packing | 8 pixels per byte, **MSB is the leftmost pixel** |
| Polarity | **1 = white, 0 = black** (Waveshare's convention) |
| Rows | top to bottom, each padded to a whole byte: `stride = ceil(width / 8)` |
| Length | `stride × height`, **exactly 48,000 bytes** at 800×480 |

That is `framebuf.MONO_HLSB`, the same layout as `epd.buffer`. If your
controller uses 0 for white, add `?invert=1`. `X-Display-Format` says which was
sent: `mono-hlsb` or `mono-hlsb-inverted`.

**Check the headers before reading the body.** The response carries
`X-Display-Width`, `X-Display-Height`, `X-Display-Stride` and `X-Display-Format`,
and `Content-Length` must equal `stride × height`. `main.py` checks all five
before reading, because the body goes straight into the panel's live buffer. It
also sends `Accept-Encoding: identity` and rejects chunked or encoded bodies,
since the board can't decompress.

## Hardware rules

- **Refresh no more than every 180 seconds, and sleep the panel in between.**
  Waveshare says leaving it powered damages it permanently. `main.py` enforces
  `MIN_REFRESH_S = 180`, calls `epd.sleep()` on every path, and treats the
  server's `X-Display-Refresh-Seconds` as a minimum only.
- **Honour the ETag.** Send `If-None-Match` and do nothing on a **304**. A full
  refresh takes seconds and flashes the panel.

## Memory

The 48,000-byte buffer is allocated once, before the loop. TLS needs most of
the rest of the RP2350's 520 KB.

- **Raw sockets, not `urequests`**, which would keep a second copy of the body.
- **`readinto` in a loop.** A socket read can return part of the frame. If the
  stream ends early, the frame is discarded and the ETag isn't saved, so the
  next poll fetches again.

## Wifi drops

On the rp2 port the station doesn't reconnect by itself after the access point
goes away. The loop checks the link each cycle and calls `connect_wifi()` again,
which retries and then resets the board if the network stays down. The panel
shows the last good frame meanwhile.

## Deep sleep

`main.py` uses `machine.lightsleep`, which keeps RAM and so keeps the ETag. On
the rp2 port `machine.deepsleep` resets the board, which loses the ETag and
repaints on every wake. To use deep sleep, save the ETag to a file, and write it
only when it changes, since flash endurance is limited:

```python
try:
    etag = open("etag.txt").read()
except OSError:
    etag = ""
...
if new_etag != etag:
    with open("etag.txt", "w") as f:
        f.write(new_etag)
```

## The token and TLS

`TOKEN` is a credential: anyone with it can read what the screen shows.
`USE_TLS` is on by default, but **MicroPython doesn't verify certificates unless
told to**. `ssl.wrap_socket` defaults to `CERT_NONE`, so the connection is
protected from passive listeners but not from anyone who can impersonate your
host.

To verify, export the issuing CA as DER and set `CA_FILE`:

```sh
openssl x509 -in ca.pem -outform der -out ca.der   # copy ca.der to the board
```

`main.py` then uses `CERT_REQUIRED`, which also checks the hostname. Set the
board's clock from NTP at boot so validity checks work.

## Other hardware

Only the driver import and `machine` are Pico-specific. Any board that can open a
socket and drive a panel can use the same endpoint and checks. Get the polarity
right (`?invert=1` for 0 = white), and read `X-Display-Stride` instead of
dividing: a 250-pixel row is 32 bytes, not 31.25.

`backend/tests/` parses this file and checks its constants against the server.
It doesn't import it, because `epaper`, `machine`, `framebuf` and `network` don't
exist under CPython.

## Licence

This directory is **MIT** (`LICENSE`). The rest of Smylte, including the `.bin`
route and renderer in `backend/smylted/display/`, is AGPL-3.0-only. Waveshare's
driver is GPL-3.0, so what runs on the board is a GPL-3.0 combined work. MIT
covers reusing `main.py` without that driver. If you ship the driver with it, for
example in a flash image, you're distributing GPL-3.0 code. The reasoning is in
[`docs/DESIGN.md`](../docs/DESIGN.md#panel-firmware).
