# The app's three typefaces, for the server-side renderer

These are static instances of **the same three families the app already ships**
— not new typefaces and not a second download. They are built from
`frontend/public/fonts/*.woff2` by `backend/dev/build_display_fonts.py`, which
carries the reasoning behind every weight and axis value:

| file | family | slot | pinned at |
| --- | --- | --- | --- |
| `Newsreader-Medium.ttf` | Newsreader | `--serif` | `wght 500`, `opsz 12` |
| `HankenGrotesk-Regular.ttf` | Hanken Grotesk | `--sans` | `wght 400` |
| `JetBrainsMono-Medium.ttf` | JetBrains Mono | `--mono` | `wght 500` |

Rebuild them with:

```bash
cd backend && python -m dev.build_display_fonts   # needs fonttools + brotli
```

The build refuses to run if `display.css` pins the eink serif to a different
optical size than it is about to build, so the number is changed in both places
and the fonts rebuilt in the same commit; `tests/test_displays.py` holds the two
numbers together on every CI run.

A display is one design with two rasterizers — a browser and Pillow — and this
directory is what keeps the second one in the first one's typefaces. A panel on
a wall gets Newsreader headlines, tracked uppercase mono micro-labels and Hanken
Grotesk rows, the same as the page; without these it would be a dashboard that
happens to hold the same data. It is always the shipped design: a display
follows neither the account's Appearance theme nor the Classic preset.

They are TTF rather than WOFF2 because no Python rasterizer reads WOFF2 —
FreeType, which is what Pillow is, takes SFNT.

The two interesting numbers, both empirical and both explained at length in the
build script: **Newsreader is pinned to opsz 12, below its own default of 18**,
because the default is the text cut and its hairlines are exactly what a
one-bit panel destroys — measured, "August 2026" loses the thins of its 2s and
a small day number's 1 reads as an l — while 12 keeps every stroke and sets at
the width the layout was tuned against (`display.css` pins the browser to the
same instance, for the eink palette only); and **JetBrains Mono is one weight
step above the app's**, because a micro-label read at three metres needs it and
one read at arm's length does not.

All three are SIL Open Font License 1.1 — `OFL.txt` here, carrying each
family's copyright line above the one licence text they share, the same text
that ships beside the woff2 files. The OFL requires the licence to travel with
the font, which is why it is copied rather than referenced.
