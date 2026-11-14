# Waveshare's 7.5" V2 driver, as a test reference

`epd7in5_V2.py` is a verbatim copy of Waveshare's Raspberry Pi driver for the
7.5" e-Paper V2. It is here for one test, `tests/test_firmware_pi_driver.py`,
which checks that `firmware/pi_epaper_7in5/epd7in5_v2.py` sends the panel
exactly the bytes Waveshare's own driver sends.

**It is data, not code.** It is downloaded third-party code, so
`tests/pi_panel_fakes.py` reads it with `ast` and turns its `init()`,
`display()` and `sleep()` into the SPI stream they would produce. Nothing
imports or executes it. Its `epdconfig.py` (the GPIO and SPI layer, which
shells out and claims GPIOs at import) is deliberately not copied.

| | |
|---|---|
| Source | https://github.com/waveshareteam/e-Paper, `RaspberryPi_JetsonNano/python/lib/waveshare_epd/epd7in5_V2.py` |
| Commit | `d28b3c4` (2026-10-27) |
| sha256 | `fafc41091c47d2ea367c3e85d84dca437e42370451cae5f5424b72b4614b55f2` |
| Licence | MIT-style permission notice in the file's header, kept as is |

The sha256 is pinned in `tests/pi_panel_fakes.py`. To update the reference,
replace the file, read the whole of it, then update the hash and this table
together.
