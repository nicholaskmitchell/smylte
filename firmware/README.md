# Smylte panels

Two clients draw a Smylte display on a Waveshare 7.5" e-Paper panel:

- `pico_epaper_7in5/`: MicroPython on a Pico 2 W, over wifi;
- `pi_epaper_7in5/`: CPython on a Raspberry Pi 5 that is also the Smylte server, driving the panel on its own SPI header.

## Pico 2 W (MicroPython)

`pico_epaper_7in5/main.py` turns a **Raspberry Pi Pico 2 W** and a **Waveshare
Pico-ePaper-7.5** (800×480, black and white) into a Smylte display. It is an
example, not a library. It is short because `.bin` is already the panel's
framebuffer: `/api/public/display/<token>.bin` returns the buffer the panel
already uses, so the client reads the socket into `epd.buffer` and shows it.

### What you need

| | |
| --- | --- |
| Board | **Pico 2 W** (the plain Pico 2 has no wifi) |
| Panel | Waveshare Pico-ePaper-7.5, 800×480, 1-bit |
| Firmware | MicroPython for RP2350 (Pico 2 W build) |
| Driver | Waveshare's `Pico-ePaper-7.5.py`, copied to the board as `epaper.py` |

The driver isn't included here. Get it from
[waveshareteam/Pico_ePaper_Code](https://github.com/waveshareteam/Pico_ePaper_Code)
(`python/Pico-ePaper-7.5.py`).

### Setting it up

1. Flash MicroPython for the Pico 2 W.
2. Copy Waveshare's `Pico-ePaper-7.5.py` to the board as `epaper.py`.
3. In Settings → Displays, add a display, set **Screen** to *E-ink* and
   **Panel size** to 800 × 480, and copy its URL.
4. Edit the constants at the top of `main.py`: `WIFI_SSID`, `WIFI_PASSWORD`,
   `HOST`, `TOKEN`. Read the TLS section below before leaving `CA_FILE` empty.
5. Copy `main.py` to the board. It runs on power-up.

### The wire format

`.bin` is the framebuffer and nothing else: no header, no compression.

| | |
| --- | --- |
| Packing | 8 pixels per byte, **MSB is the leftmost pixel** |
| Polarity | **1 = white, 0 = black** (the convention of Waveshare's Pico MicroPython driver; their Pi driver takes 1 = black, which `?invert=1` serves) |
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

### Hardware rules

- **Refresh no more than every 180 seconds, and sleep the panel in between.**
  Waveshare says leaving it powered damages it permanently. `main.py` enforces
  `MIN_REFRESH_S = 180`, calls `epd.sleep()` on every path, and treats the
  server's `X-Display-Refresh-Seconds` as a minimum only.
- **Honour the ETag.** Send `If-None-Match` and do nothing on a **304**. A full
  refresh takes seconds and flashes the panel.

### Memory

The 48,000-byte buffer is allocated once, before the loop. TLS needs most of
the rest of the RP2350's 520 KB.

- **Raw sockets, not `urequests`**, which would keep a second copy of the body.
- **`readinto` in a loop.** A socket read can return part of the frame. If the
  stream ends early, the frame is discarded and the ETag isn't saved, so the
  next poll fetches again.

### Wifi drops

On the rp2 port the station doesn't reconnect by itself after the access point
goes away. The loop checks the link each cycle and calls `connect_wifi()` again,
which retries and then resets the board if the network stays down. The panel
shows the last good frame meanwhile.

### Deep sleep

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

### The token and TLS

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

### Other hardware

Only the driver import and `machine` are Pico-specific. Any board that can open a
socket and drive a panel can use the same endpoint and checks. Get the polarity
right (`?invert=1` for 0 = white), and read `X-Display-Stride` instead of
dividing: a 250-pixel row is 32 bytes, not 31.25.

`backend/tests/` parses this file and checks its constants against the server.
It doesn't import it, because `epaper`, `machine`, `framebuf` and `network` don't
exist under CPython.

## Raspberry Pi 5 on the server box

### What it is

The Pi 5 inside the desk unit runs the Smylte server and drives the Waveshare
7.5" e-Paper V2 (800×480) directly. The Pico is removed.

| File | Job |
| --- | --- |
| `pi_epaper_7in5/panel.py` | The service: fetch, compare, paint, forever |
| `pi_epaper_7in5/epd7in5_v2.py` | The driver |
| `deploy/smylte-panel.service` | The systemd unit |
| `deploy/panel-setup.sh` | Install, update, remove |

It fetches the frame over loopback,
`http://127.0.0.1:8080/api/public/display/<token>.bin?invert=1&w=800&h=480`. It
needs no wifi and no TLS: the request never leaves the box.

**Status:** tested in CI against the server and Waveshare's driver, **not yet
run on hardware**.

### What you need

| | |
| --- | --- |
| Board | Raspberry Pi 5. 2 GB is enough for the server plus the panel |
| OS | Raspberry Pi OS Lite (64-bit) 2026-10-06 or later. That is Debian 13 "Trixie" with Python 3.13. Not the "Legacy" Bookworm image, whose Python 3.11 `setup.sh` refuses |
| Panel | The Waveshare Pico-ePaper-7.5 module with the Pico 2 W unplugged from it, or an e-Paper Driver HAT Rev2.3 or later (see "Other boards") |
| Leads | Female-female jumper leads, 20 cm or shorter |
| Packages | `python3-libgpiod`, `python3-spidev` and `gpiod`: all already in the Lite image; `apt install` them if missing |

### Wiring

Wire with the Pi unplugged, and take the Pico out of the module first. VSYS is
the Pico's power input, and a seated Pico would boot and fight the Pi on the same
wires.

| Module (Pico socket pin) | Pi 5 header pin (BCM) |
| --- | --- |
| DIN 15 | 19 (GPIO10, MOSI) |
| CLK 14 | 23 (GPIO11, SCLK) |
| CS 12 | 24 (GPIO8, CE0) |
| DC 11 | 22 (GPIO25) |
| RST 16 | 11 (GPIO17) |
| BUSY 17 | 18 (GPIO24) |
| GND 13 and 18 | 20 and 25 |
| VSYS 39 **and** 3V3(OUT) 36 | 1 or 17 (3V3) |
| — | 12 (GPIO18): leave unconnected |

- The power row works whichever way the module's J6 selector is set, and keeps
  5 V out of the harness.
- On this module the RST line also switches the panel's power: RST low means
  unpowered.
- Leave the module's switches as they are.
- Keep leads short, and use crimped housings rather than loose Dupont.

### Setting it up

1. Flash Raspberry Pi OS Lite (64-bit) with Raspberry Pi Imager. Set the
   hostname, the user `nicholaskmitchell` (`setup.sh` and `smylte.service`
   hard-code it), and an SSH key.
2. Install the server per [`docs/DEPLOY.md`](../docs/DEPLOY.md).
3. Enable SPI: `sudo raspi-config nonint do_spi 0`, then reboot.
4. Check it: `ls -l /dev/spidev0.0` shows group `spi`, and `gpiodetect` shows one
   `[pinctrl-rp1]`.
5. In Settings → Displays, add a display: **Screen** *E-ink*, **Panel size**
   800 × 480. Copy its token, or the whole URL.
6. `sudo ~/smylte/deploy/panel-setup.sh`. It checks the box, installs the client,
   asks for the token, runs a self-test (power up and down, no refresh), then
   enables and starts `smylte-panel.service`.
7. `journalctl -u smylte-panel -f`. Expect `ready: …`, maybe `waiting for the
   clock to sync`, then `painted … in N s`, within about five minutes of the
   start.
8. Look at the glass: dark ink on white paper. A negative means a polarity bug.
   Stop the service and report it.

### What it does

- The 180 s floor between refreshes holds across restarts, crashes and reboots.
  The last refresh's time is kept on CLOCK_BOOTTIME in
  `/var/lib/smylte-panel/state.json`, and is written before a refresh starts.
- A stop never interrupts a refresh.
- The panel is in deep sleep between refreshes and unpowered whenever the service
  is not running.
- It paints only a frame whose headers say exactly 800×480 `mono-hlsb-inverted`,
  48,000 bytes.
- It repaints at least every 23 h, even if nothing changed.
- It waits for the clock to sync after boot (at most 300 s of uptime), because
  the server on the same box would otherwise draw the wrong day.
- On a 404 it keeps the frame and retries every 15 min.
- With the server down, it retries every minute.
- A 429 waits the `Retry-After`, between 60 s and 1 h.
- It never shows the token in logs beyond its first four characters.

### Day to day

- `systemctl status smylte-panel`: its Status line says what is on the glass, or
  what is wrong.
- `journalctl -u smylte-panel -p warning` shows only the problems.
- `sudo systemctl kill -s USR1 smylte-panel` forces a repaint at the next allowed
  time.
- After **New URL** in Settings: `sudo ~/smylte/deploy/panel-setup.sh --rotate-token`.
- **After pulling a change to `firmware/pi_epaper_7in5/` or
  `deploy/smylte-panel.service`, re-run `sudo ~/smylte/deploy/panel-setup.sh`.**
  Autopull does not update or restart the panel, because the service runs a
  root-owned copy in `/usr/local/lib/smylte-panel`. `--status` shows whether the
  copy differs.
- Before storing the panel: `--clear` paints it white and stops the service.
- `--uninstall` removes everything. Then delete the display in Settings.
- After five failed starts in an hour the unit stays failed:
  `sudo systemctl reset-failed smylte-panel && sudo systemctl start smylte-panel`.

### Is it broken?

| The journal says | It means | Do this |
| --- | --- | --- |
| `/dev/spidev0.0: missing` | SPI is off | Enable it (setup step 3) and reboot |
| `no GPIO chip labelled 'pinctrl-rp1'` | This is not a Pi 5 | Run `gpiodetect` to see what is there |
| `held by another program` | Something else has the panel's GPIO lines | `gpioinfo` names it. Stop it |
| `permission denied` | The service lacks the `gpio` or `spi` group, or the sandbox blocks the device | Re-run `panel-setup.sh`. See "Checks only hardware can settle" |
| `BUSY stayed low for … during power-on` | The panel has no power, or BUSY is not wired | Check the 3V3 lead to pins 36 and 39, the RST lead, and BUSY |
| `BUSY stayed low … during refresh` | A cold room or a panel fault | Warm the room and try again. If it repeats, suspect the panel |
| `is not a display token` | The stored token is wrong. Exit 78, no restarts | `sudo ~/smylte/deploy/panel-setup.sh --rotate-token` |
| `does not know this display (404)` | The token was rotated, or the display was disabled or deleted | Check Settings → Displays. After a rotation, `--rotate-token` |
| `server not answering` | smylted is down. The glass keeps its frame | `systemctl status smylte` |
| `refused the server's response (…)` | The server and client disagree about the frame | Update both: pull, restart smylte, re-run `panel-setup.sh` |
| `waiting for the clock to sync` | Normal after boot | Nothing |
| `refresh failed during …` | The panel or its wiring failed mid-refresh | It retries in a minute, up to five times an hour. Then see "Day to day" |

### Checks only hardware can settle

Do these once, at bring-up.

- `sudo systemctl stop smylte-panel; pinctrl get 17,25`: both low.
- With the service stopped, measure the module's 3V3 rail. Near 0 V is right.
  1–3 V means the panel is being fed through CS: the Pi's kernel holds CE0 high.
  Report it. The options are wiring CS to a spare GPIO, or a Driver HAT.
- Start the service, wait until it is idle, then
  `sudo systemctl kill -s SIGKILL smylte-panel`. `pinctrl get 17` must read low,
  which shows that `ExecStopPost` ran. This matters because the Pi 5 keeps a GPIO
  output's level after its process dies.
- `systemd-analyze security smylte-panel.service`.
- If the first start fails on the sandbox rather than the hardware, relax
  `MemoryDenyWriteExecute` first, then `SystemCallFilter`, with
  `sudo systemctl edit smylte-panel`.

### Heat

The panel's life is only guaranteed between 0 and 40 °C. A Pi 5 gives off about
2.4–4 W in the box.

- Use the Active Cooler and a vented enclosure, with a low intake and a high
  exhaust.
- Keep a 10–15 mm gap plus a thin insulating sheet between the Pi and the back of
  the panel, and do not blow the exhaust at the panel.
- `vcgencmd measure_temp` shows the Pi's temperature.
- The journal's "painted … in N s" duration is a trend worth watching.

### Other boards

- An e-Paper Driver HAT Rev2.3 or later has a real power switch on BCM18. Set
  Display Config B and Interface 0, and add `Environment=SMYLTE_PANEL_PWR_PIN=18`
  with `sudo systemctl edit smylte-panel`.
- Other Waveshare panels need a different command sequence. This driver is for
  the 7.5" V2 only.

### How CI checks it

`backend/tests/test_firmware_pi_*.py` check:

- the contract against the live server routes;
- the driver against Waveshare's own driver, read as source (never executed);
- the loop, floor and signals on fakes;
- the unit and script against the client's constants.

## Licence

This directory is **MIT** (`LICENSE`). The rest of Smylte, including the `.bin`
route and renderer in `backend/smylted/display/`, is AGPL-3.0-only.

**Pico client.** Waveshare's Pico driver is GPL-3.0, so what runs on the board is
a GPL-3.0 combined work. MIT covers reusing `main.py` without that driver. If you
ship the driver with it, for example in a flash image, you're distributing
GPL-3.0 code. The reasoning is in [`docs/DESIGN.md`](../docs/DESIGN.md#panel-firmware).

**Pi client.** No Waveshare code runs there. `epd7in5_v2.py` is this repo's, sends
the command bytes of Waveshare's MIT-licensed `epd7in5_V2.py` and carries its
permission notice. python3-libgpiod (LGPL-2.1-or-later) and python3-spidev (MIT)
are imported from Raspberry Pi OS packages, not shipped. The copy of Waveshare's
Pi driver in `backend/tests/vendor/waveshare/` is test-only reference data.
