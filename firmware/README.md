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
   `WIFI_PASSWORD`, `HOST`, `TOKEN`.
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

**Check before you paint.** The response carries `X-Display-Width`,
`X-Display-Height`, `X-Display-Stride` and `X-Display-Format`, and
`Content-Length` must equal `stride × height`. `main.py` refuses a frame that
disagrees with its own constants rather than clocking a mis-shaped buffer onto
the glass — the failure mode is diagonal garbage on a wall in another room, with
nothing on screen to say why.

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

## Other hardware

Nothing here is Pico-specific except the driver import and `machine`. An ESP32,
an Inkplate, anything that can open a socket and push bits at a panel wants the
same endpoint and the same four checks. The two things to get right are the
polarity (`?invert=1` if your driver wants 0 for white) and the stride at a width
that is not a multiple of eight — 250 pixels is 32 bytes a row, not 31.25, and a
client that divides rather than reading `X-Display-Stride` shears its picture a
little further on every row.
