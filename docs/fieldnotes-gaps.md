# Field notes: token gaps and deviations

The redesign takes every colour, radius, duration and easing from the design
system (`frontend/src/styles/ds/`). Where it needed a value the design system has
no CSS token for, it used the closest existing one, or a value the design system
states elsewhere (`tokens.json`), and the gap is listed here.

| What | Where it is needed | What was used | Why |
|---|---|---|---|
| The app type scale (52 · 32 · 26 · 22 · 20 · 18 · 17 · 15 · 14 · 13) | Every Field notes text size | `--fs-app-*` in the Field notes lever block (`tokens.css`), from `tokens.json` "Apps · Field notes" | The design system gives the scale in `tokens.json` only; `themes.css` has no size tokens beyond `--fs-control` |
| The share page's clock on the board | The focus card's countdown on `/share/<token>` from 1024px wide | `calc(96px * var(--fs-scale))` (`fieldnotes.css`, cp3 · Public) | The scale stops at the 52px display; the clock is that page's one number, as the Focus view's is (`app.css` `.focus-clock`, up to 168px), and in the board's 400px column 112px leaves "1:02:03" no room |
| The pen: `--stroke-pen` 1.8px, `--stroke-tick` 2.6px, `--stroke-strike` 2px, `--wobble` 1px | Checks, strikes, the tab underline, icons, drawings | The Field notes lever block, from `tokens.json` spacing | In `tokens.json`, not in `themes.css` |
| `--r-xs` 3px and `--r-lg` 22px | Every Field notes corner at those steps | `calc(var(--radius) * 0.375)` and `calc(var(--radius) * 2.75)`, equal to the design system's values at the default 8px (tested) | `themes.css` writes them as literals, which would stop the Appearance editor's radius slider moving them |
| `--row-y` 8px | Task and list rows | The Field notes lever block, from `tokens.json` ("Field notes rows run 8px with a 60px minimum height") | Not in `themes.css` |
| A wallpaper accent's floor | The Android client's accent from the wallpaper | 4.5:1 under Field notes (it is text there), 3:1 under the presets as before | The design system sets no rule for a device accent |
| The day's drawing: its pen | The Today drawing | The pen scales with the drawing, as the mockup's does: `calc(var(--stroke-pen) * 1.25)` in drawing units, so exactly `--stroke-pen` (1.8px) at the phone's 128px and 2.7px at the desktop's 192px (owner's call, 17 Nov) | `--stroke-pen` is written for 24px icons; a fixed pixel pen made the larger desktop drawing look spindlier than the phone's |
| The day's drawing: its wobble | The Today drawing's boil | 1.25 drawing units: 1px on the phone (the design system's `--wobble`), 1.5px on the desktop, in proportion to the larger drawing | `--wobble` is a pixel limit for 24px icons; at 0.8 units the boil was half the mockup's |
| Light at night | The dark drawings: the moon, a lamp, lit windows, fireflies, bulbs | A `glow` role: `--wash` in a radial gradient fading to nothing, drawn by the client (`DayDrawing.tsx`) | The design system has a wash but no soft light; flat sage blobs read as stains, not light |
| Light at night, in the dark theme | The glow's colour on dark paper | `color-mix(in oklab, var(--wash) 70%, var(--fg))`: the sage lifted 30% toward the ink, 3:1 on the ground and 2:1 over the wash (`fieldnotes.css`). **Needs the owner's sign-off**: it changes a colour role's value in dark | The dark `--wash` (#3D4233) is 1.5:1 on `--bg`, and over the sage wash a glow of it vanishes: a lit window read as unlit |
| The ruling nib: `--stroke-rule` 1.1px | The Calendar's ruled grid under Field notes | The Field notes lever block (`tokens.css`). The month's lines are 32% ink at this nib: 1.9:1 light and 2.6:1 dark, against the hairline's 1.3:1 and 1.5:1. The page's frame and the chosen day's box use the pen | The design system has one pen width for drawing and no nib for ruling |
| The month's name on the Calendar | The Calendar's header under Field notes | `--fs-app-display` (52px, the scale's "day's date on Today"); `--fs-app-title` in a header under 840px; `--fs-app-headline` on a phone, `--fs-app-section` on one under 360px, its year at `--fs-app-small` | The app scale names no size for a page's month |
| The month's drawing | The Calendar's header on a desktop | A landscape page, 200 x 110 units, shown at 210px (160px in a header under 840px); still, like the view drawings; one per month, northern seasons | The design system's drawings are portrait day drawings; a page's top is wide and short |
| A secondary control's face | Ghost buttons, settings toggles that cycle, the lone view tab, booking days and slots, habit days, the dashed adds, destructive buttons (`fieldnotes.css`, "controls") | `--ctl-face`: `color-mix(in oklab, var(--fg) 8%, transparent)`, and 6% in the dark theme (`tokens.css`). No edge at rest; `--edge-control` (`--rule-strong`, 3:1) under the pointer and on press. A face carries `--fg` or `--warn` words only | The design system has no token for a control's resting face. `--paper` measured 1.06:1 on a dark card and vanishes on the `--paper` sidebar; the ink at 8% reads 1.16:1 on every ground in light, and at 6% 1.17:1 in dark, where 8% put a `--warn` word on a sheet at 4.3:1. A derived colour, chosen with Buttons C (22 Nov); the 6% at night was found while planning it |
| On or chosen | A setting that is on (until it is drawn as a check), Home's Arrange while on, a chosen booking day, habit day or display chip | `--ctl-on`: `var(--highlight)`, behind `--fg` text only | The design system names the highlighter for marking text, not a control's state |
| Native parts at night | Date and time glyphs, an unticked native checkbox, a select's open list, in the dark theme | `color-scheme: dark` on `:root[data-surface="app"][data-theme="dark"]` (`fieldnotes.css`) | The design system declares no `color-scheme`; without it the date glyph drew black on the dark field (1.36:1) |
| The pen's icon set | Icon buttons, the Today line's ⋯, a chip's ×, Today's day arrows, a select's caret, a date or time field's page and clock, a theme token's reset, a list group's caret, rename, delete and cancel, a list's edit, a Home module's remove, Today's and the plan's add and remove, a task's fold, the Focus float's pin, the phone bar's switches and add, and the Calendar's Tasks caret (a group's show-all is the drawn check) | `IconInk` (`Marks.tsx`): 18 icons on the 24-unit grid at `--stroke-pen`, round caps, the control's colour; 24px, 18px in dense rows. The way back to today is `HomeInk`, a drawn arrow after the word | The design system says icons are hand-inked plain glyphs on the pen's grid but ships no set; these were drawn for the controls job (22 Nov), the chevrons shared with Today's day arrows |

## Secondary controls with no edge at rest: a deviation the owner chose

The design system's colour table gives `--rule-strong` as "Control and checkbox
borders (3:1 or better)", and until 22 Nov every secondary control here wore
that edge at rest (`fieldnotes-edges.browser.test.tsx` held it). The owner chose
Buttons C ("Paper and pen") knowing it drops that edge: a ghost button, a
settings toggle that cycles, a pick or an add is now a face (`--ctl-face`) under
its word, and its 3:1 edge shows under the pointer. WCAG 1.4.11 asks for no
boundary where the word identifies the control, and every one of them carries a
`--fg` or `--warn` word at 4.5:1 or more on its face (`docs/contrast.md`).
Fields keep their 3:1 edge at rest, and a setting that is on or off is a drawn
checkbox whose frame is the pen (12.9:1); one whose words name its value
("Shown" / "Hidden") keeps the face, since a check beside a value word would
read as its negation.

On 23 Nov the owner approved amending the design system's colour table to say
so: "`--rule-strong`: field and checkbox borders, and a
secondary control's edge under the pointer (3:1 or better). A secondary control
has no edge at rest: it is a face, the ink at 8% (6% at night) over its ground,
under a `--fg` or `--warn` word."

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

## The app icon: a deviation the owner chose

The design system draws an app's favicon as its wordmark's letter ("Wordmark,
favicon: Newsreader italic 500, accent period"), and Smylte's icon was that: an
italic S and a coral period. On 22 Nov the owner chose the drawn check instead:
the app's own CheckInk frame in `--fg` and its tick in `--accent`, on a `--bg`
plate (`brand/app-icon.svg`, made into every platform's file by
`backend/dev/build_app_icon.py`). It is the gesture the app is used for, the
design system keeps ticks and strikes at small sizes, and in a 16px tab 53 of
its 256 pixels clear 3:1 against the plate, where the S had 15. From 40px down
the pen is heavier (4.8 and 6.4 units of 64, against 3.2 and 4.4), so the frame
stays a device pixel wide. The in-app wordmark, "Smylte." in Newsreader italic
with its accent period, is unchanged.

On 23 Nov the owner approved amending the design system's README to say so:
"Wordmark: Newsreader italic 500, accent period. Favicon and
app icon: the wordmark's letter and its period, unless the app has a signature
mark; Smylte's is its drawn check, the CheckInk frame in --fg and its tick in
--accent on a --bg plate, with a heavier pen from 40px down."

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
light that is always on (a glow of 600 units² or more with no condition). And every
wash closes inside the picture, at least 6 units from each edge: a wash the
frame cuts shows the frame as a straight, jagged edge nobody drew. So ground is
an ink line (it may run near the edges, as a horizon does), and colour goes on
things that close (a canopy, a rock, a bush) or is a soft blob with no outline
(blob()), behind them or across the line, as the washing line's hedge is by day
and its ground by night. Never a band across the
width, and never an outlined slab of land under the ground line, which floats
like an island once it is closed inside the picture.
