# A Smylte panel on a microcontroller

`pico_epaper_7in5/main.py` turns a **Raspberry Pi Pico 2 W** and a **Waveshare
Pico-ePaper-7.5** (800×480, black and white) into a Smylte display: a screen on a
wall showing the month, or today's habits, with nothing to tap.

It is an **example, not a library and not a product**. It is about sixty lines
because the server does the hard part — `/api/public/display/<token>.bin` answers
with the packed framebuffer the panel already wants, so the whole client is
"read the socket into `epd.buffer` and show it".

## What you need

| | |
| --- | --- |
| Board | **Pico 2 W** — the plain Pico 2 has no radio, and this needs wifi |
| Panel | Waveshare Pico-ePaper-7.5, 800×480, 1-bit |
| Firmware | MicroPython for RP2350 (Pico 2 W build) |
| Driver | Waveshare's own `Pico_ePaper-7.5.py`, copied onto the board as `epaper.py` |

The driver is **not vendored here**. It is third-party code with its own licence
and its own release cadence, and a stale copy in this repo would be worse than
no copy — get it from
[waveshareteam/Pico_ePaper_Code](https://github.com/waveshareteam/Pico_ePaper_Code).
That is also why the contract test in `backend/tests/` parses this file rather
than importing it: `epaper`, `machine`, `framebuf` and `network` do not exist
under CPython.

## Setting it up

1. Flash MicroPython for the Pico 2 W.
2. Copy Waveshare's `Pico_ePaper-7.5.py` to the board as `epaper.py`.
3. In Settings → Displays, make a display, set its **Screen** to *E-ink* and its
   **Panel size** to 800 × 480, and copy the URL it shows you.
4. Edit the four constants at the top of `main.py` — `WIFI_SSID`,
   `WIFI_PASSWORD`, `HOST`, `TOKEN` — and read the TLS section below before
   leaving `CA_FILE` empty.
5. Copy `main.py` to the board. It runs on power-up.

## The wire format

`.bin` is the panel's framebuffer and nothing else — no header, no compression,
no row order to undo:

| | |
| --- | --- |
| Packing | 8 pixels per byte, **MSB is the leftmost pixel** |
| Polarity | **bit 1 = white paper, 0 = black ink** — Waveshare's own convention (`Clear(0xff)` blanks a panel) |
| Rows | top to bottom, each padded to a whole byte: `stride = ceil(width / 8)` |
| Length | `stride × height` — **exactly 48,000 bytes** at 800×480 |

That is `framebuf.MONO_HLSB`, which is what the driver's `epd.buffer` already
is. Hence `readinto(epd.buffer)` and no transformation at either end.

If your controller's convention is the other way round — 0 for white — add
`?invert=1` and the server flips the bits for you, which is cheaper there than
on a board with 520 KB of RAM. The response says which it sent in
`X-Display-Format`: `mono-hlsb` or `mono-hlsb-inverted`.

**Check before you paint, and check before you *read*.** The response carries
`X-Display-Width`, `X-Display-Height`, `X-Display-Stride` and
`X-Display-Format`, and `Content-Length` must equal `stride × height`.
`main.py` compares all five against its own constants **before it reads a byte
of the body**, because the body is read straight into `epd.buffer` — the
panel's live framebuffer — and refusing afterwards leaves the mis-shaped frame
sitting in the thing that gets clocked onto the glass. It also sends
`Accept-Encoding: identity` and rejects a chunked or re-encoded body: RFC 9110
§12.5.3 says an absent `Accept-Encoding` means any coding is acceptable, and a
gzipped framebuffer is not something this board can undo. The failure mode all
of this avoids is diagonal garbage on a wall in another room, with nothing on
screen to say why.

## Two rules that are about the hardware

**Refresh no more than every 180 seconds, and sleep the panel in between.**
Waveshare are explicit: leaving the screen powered holds it at high voltage and
*"will damage the e-Paper and cannot be repaired"*. `main.py` has its own
`MIN_REFRESH_S = 180` floor and calls `epd.sleep()` on every path including the
error one. The server's `X-Display-Refresh-Seconds` is advisory — the firmware
takes `max()` of the two and never the server's word alone.

**Honour the ETag.** Send `If-None-Match` and do nothing at all on a **304**. A
full refresh of this panel is seconds of power and a visible flash across the
room, and most polls have nothing new in them. This is the difference between a
panel that flashes at you 288 times a day and one that redraws when the month
changes.

## Memory, and why the loop looks like that

48,000 bytes of framebuffer against the RP2350's 520 KB, allocated **once**
before the loop — plus whatever mbedTLS wants for the handshake, which is the
real pressure. Two consequences visible in the code:

- **Raw sockets, not `urequests`.** That library buffers the entire body into a
  second object before handing it over, which doubles the frame in RAM for no
  reason. It needs to read the headers itself anyway.
- **`readinto` in a loop.** Socket reads are short — one call is not one frame.
  Assuming otherwise leaves the buffer half new and half last-hour, and it
  paints as a calendar torn across the middle. If the stream ends early the
  frame is discarded and the ETag is *not* saved, so the next poll refetches.

## Wifi drops

The join is not for life. On the rp2/cyw43 port the station does **not**
re-associate on its own once the access point goes away — after a router reboot
or a channel change `wlan.isconnected()` stays `False` until something calls
`connect()` again. So the loop checks the link at the top of every cycle and
calls `connect_wifi()` again when it is down, which retries for a while and then
`machine.reset()`s the board if the network stays gone. Between the drop and the
re-join the panel keeps showing the last good frame, which is the whole
advantage of e-paper; what it must never do is keep showing it forever.

## Deep sleep

`main.py` uses `machine.lightsleep`, which retains RAM — so the ETag survives as
an ordinary variable. On the rp2 port **`machine.deepsleep` resets the board**,
which loses it and makes every wake a full repaint, undoing the one optimisation
that matters. If you need deepsleep for battery life, persist the ETag to a file
and write it only when it changes:

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

Flash on these boards is rated in the tens of thousands of writes per sector, so
the "only when it changes" is the part that matters.

## The token, and what TLS here does and does not do

`TOKEN` is a bearer credential for your calendar: anyone holding it can read
everything the screen shows. `USE_TLS` is on by default, but **MicroPython does
not verify certificates unless you tell it to** — `ssl.wrap_socket` defaults to
`cert_reqs=CERT_NONE`, and `server_hostname` only sets the SNI extension. Left
that way, the handshake succeeds against any certificate at all, so the token is
protected from someone passively listening and not from anyone able to answer
for your host. On the wifi a wall panel lives on, the second is the likelier of
the two.

To verify properly, export the issuing CA in DER and point `CA_FILE` at it:

```sh
openssl x509 -in ca.pem -outform der -out ca.der   # then copy ca.der to the board
```

`main.py` then builds an `SSLContext` with `CERT_REQUIRED`, which also checks
the hostname. A validity check needs a roughly correct clock, so set the board's
time from NTP at boot if you do this.

## Other hardware

Nothing here is Pico-specific except the driver import and `machine`. An ESP32,
an Inkplate, anything that can open a socket and push bits at a panel wants the
same endpoint and the same four checks. The two things to get right are the
polarity (`?invert=1` if your driver wants 0 for white) and the stride at a width
that is not a multiple of eight — 250 pixels is 32 bytes a row, not 31.25, and a
client that divides rather than reading `X-Display-Stride` shears its picture a
little further on every row.
