# Inter, for the server-side renderer

`Inter-Regular.ttf` and `Inter-Bold.ttf` are static instances (wght 400 and 700)
of the **same Inter the app already ships**, built from
`frontend/public/fonts/inter-latin.woff2` and `inter-latin-ext.woff2` — not a
new typeface and not a second download. A panel rendered by the server therefore
reads in the face the browser page renders in, which is the point: a display is
one design with two rasterizers, and two typefaces would make it two designs.

They are TTF rather than WOFF2 because no Python rasterizer reads WOFF2 —
FreeType, which is what Pillow is, takes SFNT. The conversion is mechanical
(decompress, pin the variable `wght` axis, merge the two subsets) and reproducible:

```bash
pip install fonttools brotli
python - <<'PY'
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools.merge import Merger
SRC = "frontend/public/fonts"
for weight, out in ((400, "Inter-Regular.ttf"), (700, "Inter-Bold.ttf")):
    parts = []
    for subset in ("inter-latin.woff2", "inter-latin-ext.woff2"):
        font = TTFont(f"{SRC}/{subset}")
        instancer.instantiateVariableFont(font, {"wght": weight}, inplace=True)
        font.save(path := f"/tmp/{subset}.{weight}.ttf")
        parts.append(path)
    Merger().merge(parts).save(out)
PY
```

The two subsets are merged rather than one being picked, because they carve up
the alphabet between them: `inter-latin` holds ASCII and Latin-1 (so `ü`, `é`,
`ç`), `inter-latin-ext` holds the rest of extended Latin (so `ż`, `ł`). Titles
on a display are the owner's own text and a list called *Ćwiczenia* should not
render as boxes.

Licensed under the SIL Open Font License 1.1 — `OFL.txt` here, the same licence
already carried beside the woff2 files. The OFL requires the licence to travel
with the font, which is why it is copied rather than referenced.
