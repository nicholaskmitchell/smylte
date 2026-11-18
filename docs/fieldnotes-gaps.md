# Field notes: token gaps and deviations

The redesign takes every colour, radius, duration and easing from the design
system (`frontend/src/styles/ds/`). Where it needed a value the design system has
no CSS token for, it used the closest existing one, or a value the design system
states elsewhere (`tokens.json`), and the gap is listed here.

| What | Where it is needed | What was used | Why |
|---|---|---|---|
| The app type scale (52 · 32 · 26 · 22 · 20 · 18 · 17 · 15 · 14 · 13) | Every Field notes text size | `--fs-app-*` in the Field notes lever block (`tokens.css`), from `tokens.json` "Apps · Field notes" | The design system gives the scale in `tokens.json` only; `themes.css` has no size tokens beyond `--fs-control` |
| The pen: `--stroke-pen` 1.8px, `--stroke-tick` 2.6px, `--stroke-strike` 2px, `--wobble` 1px | Checks, strikes, the tab underline, icons, drawings | The Field notes lever block, from `tokens.json` spacing | In `tokens.json`, not in `themes.css` |
| `--r-xs` 3px and `--r-lg` 22px | Every Field notes corner at those steps | `calc(var(--radius) * 0.375)` and `calc(var(--radius) * 2.75)`, equal to the design system's values at the default 8px (tested) | `themes.css` writes them as literals, which would stop the Appearance editor's radius slider moving them |
| `--row-y` 8px | Task and list rows | The Field notes lever block, from `tokens.json` ("Field notes rows run 8px with a 60px minimum height") | Not in `themes.css` |
| A wallpaper accent's floor | The Android client's accent from the wallpaper | 4.5:1 under Field notes (it is text there), 3:1 under the presets as before | The design system sets no rule for a device accent |
| The day's drawing: its pen | The Today drawing | The pen scales with the drawing, as the mockup's does: `calc(var(--stroke-pen) * 1.25)` in drawing units, so exactly `--stroke-pen` (1.8px) at the phone's 128px and 2.7px at the desktop's 192px (owner's call, 17 Nov) | `--stroke-pen` is written for 24px icons; a fixed pixel pen made the larger desktop drawing look spindlier than the phone's |
| The day's drawing: its wobble | The Today drawing's boil | 1.25 drawing units: 1px on the phone (the design system's `--wobble`), 1.5px on the desktop, in proportion to the larger drawing | `--wobble` is a pixel limit for 24px icons; at 0.8 units the boil was half the mockup's |
| Light at night | The dark drawings: the moon, a lamp, lit windows, fireflies, bulbs | A `glow` role: `--wash` in a radial gradient fading to nothing, drawn by the client (`DayDrawing.tsx`) | The design system has a wash but no soft light; flat sage blobs read as stains, not light |
| Light at night, in the dark theme | The glow's colour on dark paper | `color-mix(in oklab, var(--wash) 70%, var(--fg))`: the sage lifted 30% toward the ink, 3:1 on the ground and 2:1 over the wash (`fieldnotes.css`). **Needs the owner's sign-off**: it changes a colour role's value in dark | The dark `--wash` (#3D4233) is 1.5:1 on `--bg`, and over the sage wash a glow of it vanishes: a lit window read as unlit |

## The desk unit's e-paper: a deviation the owner chose

The design system says (README, *Every app surface*): "Colour roles become ink
weights: accent is solid ink, the highlighter is a 25% hatch, the wash is
dropped." Solid ink turned a full day's rewards into the heaviest marks on the
panel: twelve notes became a grid of black squares, and the washing became
black silhouettes that hid their own pegs. On 17 Nov the owner chose a pen hatch
instead (`backend/smylted/drawing/paper.py`):

- accent marks in the interface (ticks, strikes) stay solid ink;
- an accent fill in a drawing 8 units across or more is a pen hatch at about the
  coral's 40% tone, always inside its ink outline, on the opposite diagonal to
  the highlighter's;
- a smaller fill is solid ink, and a round reward (a fruit) stays solid at any
  size with a paper glint, as the owner's choice put it ("small ones like fruit
  stay solid with a paper glint"): a disc with a glint reads as fruit, a hatched
  disc as a button;
- the wash and the glow are dropped.

The sentence to amend in the design system's README, if the owner wants the
system to say so: "Colour roles become ink weights: accent marks are solid ink
and accent fills in an illustration a 40% pen hatch inside their ink outline
(solid below 8 units), the highlighter is a 25% hatch, the wash and glows are
dropped."

## Drawing a new subject

Subjects 4 to 14 inherit the rules the first three were redrawn to. They are
written down where a subject is written (the docstring of
`backend/smylted/drawing/subjects/_kit.py`) and held by the tests over the whole
roster, on a week of days under two salts, both themes and every hour
(`backend/tests/test_drawing.py`, *the geometry rules, over the roster*):
nothing leaves the frame; every reward is at least 10 units across and 60 units²
of coral; ink touches ink only where the subject's `JOINS` says it may, measured
at the pen's own width (2.25 units) on every boil frame and every frame of the
focus loop, and two rewards never touch at all; and the night is its own
picture, not the day recoloured (at most 90% of its marks where a day mark is,
allowing for both boils' wobble, and at least four marks of its own), with a
light that is always on (a glow of 600 units² or more with no condition).
