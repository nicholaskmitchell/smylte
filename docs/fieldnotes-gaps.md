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
