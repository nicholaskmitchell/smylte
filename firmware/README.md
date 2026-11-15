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
7.5" e-Paper V2 (800×480) directly. The Pico is removed. One key, wired to the
Pi's power-button pads, chooses the view and shuts the box down.

| File | Job |
| --- | --- |
| `pi_epaper_7in5/panel.py` | The service: fetch, compare, paint, read the key, forever |
| `pi_epaper_7in5/epd7in5_v2.py` | The driver |
| `deploy/smylte-panel.service` | The systemd unit |
| `deploy/70-smylte-panel-key.rules` | udev: only the power key is readable by the unit |
| `deploy/smylte-panel-poweroff.path` and `.service` | Power the box off when the panel asks |
| `deploy/logind-smylte-panel.conf` | Tells logind to ignore the power key |
| `deploy/panel-setup.sh` | Install, update, remove |

It fetches the frame over loopback,
`http://127.0.0.1:8080/api/public/display/<token>.bin?invert=1&w=800&h=480`,
with `&mode=…&tabs=1` for a view of the desk key and `&screen=…` for the
shutdown screens. It needs no wifi and no TLS: the request never leaves the
box.

**Status:** tested in CI against the server and Waveshare's driver, **not yet
run on hardware**.

### What you need

| | |
| --- | --- |
| Board | Raspberry Pi 5. 2 GB is enough for the server plus the panel |
| OS | Raspberry Pi OS Lite (64-bit) 2026-10-06 or later. That is Debian 13 "Trixie" with Python 3.13. Not the "Legacy" Bookworm image, whose Python 3.11 `setup.sh` refuses |
| Panel | The **Waveshare e-Paper Driver HAT (Rev2.3 or later)** with the 7.5" V2 panel, seated on the 40-pin header. The jumpered Pico-ePaper-7.5 module is the alternative (see "Pico module instead of the HAT") |
| Key | One momentary key, wired across the Pi 5's J2 pads (the power-button breakout). The onboard power button is the same signal, so you can test before the case exists |
| Leads | Female-female jumper leads, 20 cm or shorter, for the Pico module only |
| Packages | `python3-libgpiod`, `python3-spidev` and `gpiod`: all already in the Lite image; `apt install` them if missing |

### Wiring

Wire with the Pi unplugged.

**The HAT.** Seat it on the 40-pin header and set its switches: Display Config
**B** and Interface **0** (4-wire SPI). Its power switch is BCM18, which is the
default `SMYLTE_PANEL_PWR_PIN`, so there is nothing to configure.

**The key.** Wire the key across the two J2 pads.

#### Pico module instead of the HAT

Take the Pico out of the module first. VSYS is the Pico's power input, and a
seated Pico would boot and fight the Pi on the same wires.

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
- GPIO18 is unconnected here, so the default `SMYLTE_PANEL_PWR_PIN=18` does
  nothing. You may set it to `none`.

### Setting it up

1. Flash Raspberry Pi OS Lite (64-bit) with Raspberry Pi Imager. Set the
   hostname, the user `nicholaskmitchell` (`setup.sh` and `smylte.service`
   hard-code it), and an SSH key.
2. Install the server per [`docs/DEPLOY.md`](../docs/DEPLOY.md).
3. Enable SPI: `sudo raspi-config nonint do_spi 0`, then reboot.
4. Check it: `ls -l /dev/spidev0.0` shows group `spi`, and `gpiodetect` shows one
   `[pinctrl-rp1]`.
5. In Settings → Displays, add a display: **Screen** *E-ink*, **Panel size**
   800 × 480, and **turn on "Desk key (Today · Now · Calendar)"**. Without it
   the key cannot change the view. Today and Now read the display's lists,
   Calendar its calendars. Copy its token, or the whole URL.
6. `sudo ~/smylte/deploy/panel-setup.sh`. It checks the box, writes
   `/etc/default/smylte-panel` (once: see "Settings"), installs the client, the
   udev rule, the power-off units and the logind drop-in, asks for the token,
   runs a self-test (power up and down, no refresh), then enables and starts
   `smylte-panel.service`.
7. Check the key: `sudo ~/smylte/deploy/panel-setup.sh --keytest`. See "Day to
   day".
8. `journalctl -u smylte-panel -f`. Expect `ready: …`, maybe `waiting for the
   clock to sync`, then `painted … in N s`, within about five minutes of the
   start.
9. Look at the glass: dark ink on white paper. A negative means a polarity bug.
   Stop the service and report it.

### The key

| You do | The panel does |
| --- | --- |
| Tap (press and let go within 0.6 s) | Shows the next view: Today, then Now, then Calendar, then Today again |
| Hold about 1 s, then let go | Draws "Shut down?" |
| Tap once "Shut down?" is fully drawn | Draws "Off", then the box shuts down |
| Wait 10 s | "Shut down?" goes away and the view comes back |
| Press while the Pi is off | The Pi boots, and the service draws Today |

**Let go after about a second. Never hold the key to wait for the screen: at
about 5 s the Pi cuts its own power, and that is not a clean shutdown.**

- A press let go between 0.6 s and 1 s does nothing, and neither does one
  shorter than 0.03 s.
- The prompt comes 2–3 s after you let go, or later if a refresh or a fetch is
  running. A tap counts for "Shut down?" only if it started after the prompt was
  drawn and within 10 s of that.
- Taps are coalesced. The tab strip along the bottom changes first (a partial
  refresh), and the page follows 0.5 s after the last tap (a fast refresh).
- The key has a budget: 12 view-change refreshes, refilled one per 50 s. A tap
  needs two left, one for its strip and one for its page. When they run out,
  taps are ignored and the Status line says `key resting; try again in N s`.
  The confirming tap, the "Off" screen and the way back from the prompt cost
  nothing.
- After the "Off" screen the Pi powers off by itself, and the glass keeps the
  screen with no power. A press boots it again. It takes a few minutes: the
  panel draws Today as soon as the server answers.
- logind is told to ignore the key, so **while the service is not running the
  key does nothing**. Shut down over SSH, or hold the key for about 5 s for the
  hardware cut, which is not clean.

### Settings

`panel-setup.sh` writes `/etc/default/smylte-panel` once, with the defaults, and
never overwrites it. Change it with `sudoedit /etc/default/smylte-panel`. A bad
value stops the service with exit 78 and no restarts; `panel-setup.sh` checks
the values first.

| Variable | Values | Default | Meaning |
| --- | --- | --- | --- |
| `SMYLTE_PANEL_PWR_PIN` | a free BCM pin, or `none` | `18` (also when unset or empty) | The Driver HAT's power switch. `none` uses no pin |
| `SMYLTE_PANEL_REFRESH` | `fast` or `full` | `fast` | `fast`: partial and fast refreshes for the key. `full`: every refresh is full |
| `SMYLTE_PANEL_IDLE_RETURN_S` | `0`, or 60–86400 | `0` (off) | Seconds with no key before the glass goes back to Today. It is a routine refresh, so the 180 s floor applies |
| `SMYLTE_PANEL_KEY` | `auto` or `off` | `auto` | `off`: the service never opens the key, and `panel-setup.sh` leaves logind alone, so a press powers the box off |

After changing `SMYLTE_PANEL_KEY`, re-run `sudo ~/smylte/deploy/panel-setup.sh`:
it installs or removes the logind drop-in. After changing any other setting,
`sudo systemctl restart smylte-panel`.

### What it does

- The 180 s floor holds before every routine refresh (a new frame, the 23 h
  repaint, the idle return), across restarts, crashes and reboots. The key's
  refreshes are exempt from it, and the budget bounds them. The last refresh's
  time, of any kind, is kept on CLOCK_BOOTTIME in
  `/var/lib/smylte-panel/state.json`, and is written before a refresh starts.
- A stop never interrupts a refresh.
- The panel is in deep sleep between refreshes and unpowered whenever the service
  is not running. On the HAT, deep sleep leaves PWR and RST high, on purpose.
- It paints only a frame whose headers say exactly 800×480 `mono-hlsb-inverted`,
  48,000 bytes, and for a view the view it asked for.
- The strip is a partial refresh. Its page and the prompt are fast refreshes. A
  full refresh follows after every 5 fast or partial ones (`FULL_EVERY`), and
  the "Off" screen, `--clear`, the 23 h repaint and the first paint after a
  start are always full. With `SMYLTE_PANEL_REFRESH=full`, every refresh is full.
- It repaints in full at least every 23 h, even if nothing changed, and within
  23 h of the service's latest start even after a reboot. The 23 h are measured
  from the last full refresh, so fast and partial ones do not reset them. If the
  last full refresh happened with a synced clock and the clock syncs again after
  the boot, it keeps that refresh's wall-clock time, give or take the 180 s floor
  and up to 15 s to notice the sync.
- The batch guard: a partial refresh that takes longer than 1.0 s
  (`QUICK_PARTIAL_MAX_S`), or a fast refresh longer than 3.0 s
  (`QUICK_FAST_MAX_S`), looks like a panel from before the 2023 batch. The
  panel then turns quick refresh off, and draws everything in full. Setting
  `SMYLTE_PANEL_REFRESH=fast` again does not clear it. Clear it with
  `sudo ~/smylte/deploy/panel-setup.sh --reset-refresh`.
- The "Off" screen persists with no power.
- Without Desk key on the display, or with an old smylted, the panel works as a
  plain display of the view stored for it, and the Status line says why. Taps do
  nothing then; a hold still asks "Shut down?" once the screen is cached. Every 15 min it asks the server
  for the views again.
- A refresh it cannot first record in its state file is never started. It
  retries every minute, and the Status line says so.
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
- **After pulling a change to `firmware/pi_epaper_7in5/`, `deploy/smylte-panel.service`
  or the panel's udev, power-off and logind files in `deploy/`, re-run
  `sudo ~/smylte/deploy/panel-setup.sh`.**
  Autopull does not update or restart the panel, because the service runs a
  root-owned copy in `/usr/local/lib/smylte-panel`. `--status` shows whether the
  copy differs.
- `panel-setup.sh --keytest` listens to the key for 30 s and prints each press
  and release with how long it lasted and what the panel would make of it (tap,
  hold, noise or ignored). It prints "let go now" once the key has been down for 1 s.
  It never touches the panel. It refuses to run until logind ignores the key
  (an install does that), because the first press would power the box off. It
  stops the service around itself and starts it again.
- `panel-setup.sh --reset-refresh` turns fast and partial refresh back on after
  the batch guard turned them off. It stops the service around itself and
  starts it again.
- `panel-setup.sh --status` also shows logind's `HandlePowerKey` settings, the
  power-off path unit and the key's device node.
- Before storing the panel: `--clear` paints it white and stops the service.
- `--uninstall` removes everything, including any `systemctl edit` override,
  `/etc/default/smylte-panel`, the udev rule, the `smylte-panel-key` group, the
  power-off units and the logind drop-in. Then delete the display in Settings.
  **After uninstall, the key powers the box off again (the OS default).**
- After five failed starts in an hour the unit stays failed:
  `sudo systemctl reset-failed smylte-panel && sudo systemctl start smylte-panel`.
  Manual starts count towards the five; `panel-setup.sh` resets the count before
  each start it makes.

### Is it broken?

A problem's Status line is its journal text followed by `; the glass keeps its
last frame`.

| The journal says | It means | Do this |
| --- | --- | --- |
| (nothing: the key does nothing) | The service is not running, and logind ignores the key meanwhile | `systemctl status smylte-panel`. Power off over SSH, or hold the key for about 5 s (the hardware cut, not clean) |
| No journal line. `--keytest` says `no pwr_button input device (is gpio_keys loaded?)`, and `--status` says `no pwr_button input device (gpio_keys not loaded?)`. The journal may say `key: cannot open …` | The Pi has no `pwr_button` input device, or the unit cannot read it. The service looks again every 10 s | Check the key's wiring. `panel-setup.sh --status` shows the node and its group; re-run `panel-setup.sh` to install the udev rule |
| `desk key off: turn on Desk key for this display in Settings → Displays` (the Status line ends `· desk key off: …`) | The server answered 422 `views-off`. The panel shows the display's stored view, and taps do nothing | Turn on Desk key for the display in Settings → Displays. The panel asks again every 15 min |
| `desk key off: smylted is too old for the desk key — update it` | The server does not know the `mode` parameter | Pull and restart smylte |
| `key resting; try again in N s` | The key's budget is spent (12, refilled one per 50 s). Taps are ignored | Wait |
| `no confirm screen yet` | A hold was ignored: the "Shut down?" screen has not been fetched yet. It is fetched in the background after the first successful fetch, and kept in `/var/lib/smylte-panel` | Wait a minute and hold again. If it stays, smylted is probably too old |
| `logind still powers off on a press — re-run panel-setup.sh`, or `the key does nothing — re-run panel-setup.sh` | The logind drop-in does not match `SMYLTE_PANEL_KEY`: with `auto` it is missing, with `off` it is present | `sudo ~/smylte/deploy/panel-setup.sh` |
| `could not power off: failed: …` or `could not power off: nothing acted on the request within 120 s` | The panel could not write its request file, or the power-off path unit did not act on it. The glass goes back to the view | `systemctl status smylte-panel-poweroff.path`, re-run `panel-setup.sh`, and shut down over SSH meanwhile |
| `waking: the server is not answering` | The Pi was started with the key, and 10 min later the server still does not answer. The glass keeps the "Off" screen | `systemctl status smylte` |
| `fast refresh is off: this panel looks like a pre-2023 batch; see firmware/README.md` (later `· fast refresh is off (see firmware/README.md)`) | The batch guard turned quick refresh off | See "What it does". `panel-setup.sh --reset-refresh` clears it |
| `/dev/spidev0.0: missing` | SPI is off | Enable it (setup step 3) and reboot |
| `no GPIO chip labelled 'pinctrl-rp1'` | This is not a Pi 5 | Run `gpiodetect` to see what is there |
| `held by another program` | Something else has the panel's GPIO lines | `gpioinfo` names it. Stop it |
| `permission denied` | The service lacks the `gpio` or `spi` group, or the sandbox blocks the device | Re-run `panel-setup.sh`. See "Checks only hardware can settle" |
| `BUSY stayed low for … during power-on` | The panel has no power, or BUSY is not wired | On the HAT, check that it is fully seated and PWR is BCM18. On the Pico module, check the 3V3 lead to pins 36 and 39, the RST lead, and BUSY |
| `BUSY stayed low … during refresh` | A cold room or a panel fault | Warm the room and try again. If it repeats, suspect the panel |
| `is not a display token` | The stored token is wrong. Exit 78, no restarts | `sudo ~/smylte/deploy/panel-setup.sh --rotate-token` |
| `Failed to set up credentials` (status `243/CREDENTIALS`) | `/etc/credstore/smylte-panel-token` is missing. No restarts | `sudo ~/smylte/deploy/panel-setup.sh --rotate-token` |
| `does not know this display (404)` | The token was rotated, or the display was disabled or deleted | Check Settings → Displays. After a rotation, `--rotate-token` |
| `server not answering` | smylted is down. The glass keeps its frame | `systemctl status smylte` |
| `refused the server's response (…)` | The server and client disagree about the frame | Update both: pull, restart smylte, re-run `panel-setup.sh` |
| `waiting for the clock to sync` | Normal after boot | Nothing |
| `could not record the refresh` | The state file cannot be written: the disk is full or the SD card went read-only. Nothing is painted | Free some space, or check the card (`dmesg`). It retries every minute |
| `refresh failed during …` | The panel or its wiring failed mid-refresh | It retries in a minute, up to five times an hour. Then see "Day to day" |

### Checks only hardware can settle

Do these once, at bring-up.

- Run `sudo ~/smylte/deploy/panel-setup.sh --keytest`. Taps must show as taps, a
  1.5 s hold as a hold, and both the press and the release must appear.
- `sudo systemctl stop smylte-panel; pinctrl get 17,25`: both low. On the HAT,
  `pinctrl get 18` is low too.
- With the service stopped, measure the panel's 3V3 rail. Near 0 V is right.
  1–3 V means the panel is being fed through CS: the Pi's kernel holds CE0 high.
  Report it. On the Pico module the options are wiring CS to a spare GPIO, or
  the Driver HAT. On the HAT, measure the panel side of its switch, with PWR
  low.
- The kill check. It only proves something if RST is high when the client dies,
  and RST is high only after a refresh in that run:
  1. `sudo systemctl start smylte-panel`, then
     `sudo systemctl kill -s USR1 smylte-panel` to ask for a repaint.
  2. Wait for `painted … in N s` in the journal: up to about three minutes,
     because of the floor. `pinctrl get 17` now reads high (deep sleep,
     powered).
  3. `sudo systemctl kill -s SIGKILL smylte-panel`, and within a minute, before
     systemd restarts it, `pinctrl get 17` must read low. That shows
     `ExecStopPost` ran. This matters because the Pi 5 keeps a GPIO output's
     level after its process dies.
- Strip partials: tap five times, each after several idle minutes. The tab must
  change cleanly with no ghost, and then a full refresh comes.
- A clean shutdown with the key: hold, let go, tap. Then press the key once: the
  Pi boots and Today is drawn.
- With `POWER_OFF_ON_HALT=1` in the bootloader config (`sudo rpi-eeprom-config`),
  check that a press still boots the halted Pi.
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

- The Driver HAT is the main path now. The Pico module is the alternative.
- Other Waveshare panels need a different command sequence. This driver is for
  the 7.5" V2 only.

### How CI checks it

`backend/tests/test_firmware_pi_*.py` check:

- the contract against the live server routes;
- the driver against Waveshare's own driver, read as source (never executed);
- the loop, floor and signals on fakes;
- the unit and script against the client's constants;
- `test_firmware_pi_key.py`: the gestures, the `Ui`, the key's budget and the
  key input.

The server's own tests cover the tab strip and the screens.

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
