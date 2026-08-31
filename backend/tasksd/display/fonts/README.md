# The app's three typefaces, for the server-side renderer

These are static instances of **the same three families the app already ships**
— not new typefaces and not a second download. They are built from
`frontend/public/fonts/*.woff2` by `backend/dev/build_display_fonts.py`, which
carries the reasoning behind every weight and axis value:

| file | family | slot | pinned at |
| --- | --- | --- | --- |
| `Fraunces-Medium.ttf` | Fraunces | `--serif` | `wght 500`, `opsz 9` |
| `Inter-Regular.ttf` | Inter | `--sans` | `wght 400` |
| `JetBrainsMono-Medium.ttf` | JetBrains Mono | `--mono` | `wght 500` |

Rebuild them with:

```bash
cd backend && python -m dev.build_display_fonts   # needs fonttools + brotli
```

A display is one design with two rasterizers — a browser and Pillow — and this
directory is what keeps the second one in the first one's typefaces. A panel on
a wall gets Fraunces headlines, tracked uppercase mono micro-labels and Inter
rows, the same as the page; without these it would be a dashboard that happens
to hold the same data.

They are TTF rather than WOFF2 because no Python rasterizer reads WOFF2 —
FreeType, which is what Pillow is, takes SFNT.

The two interesting numbers, both empirical and both explained at length in the
build script: **Fraunces is pinned to the bottom of its optical-size axis**,
because its display cut's fine hairlines are exactly what a one-bit panel
destroys (and because `font-optical-sizing: none` in `display.css` resolves the
browser to the same instance), and **JetBrains Mono is one weight step above
the app's**, because a micro-label read at three metres needs it and one read at
arm's length does not.

All three are SIL Open Font License 1.1 — `OFL.txt` here, the same licence text
that ships beside the woff2 files. The OFL requires the licence to travel with
the font, which is why it is copied rather than referenced.
