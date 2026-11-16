# Copy to write

Field notes (Nov 2026) keeps every existing label. Where the redesign needed text
that did not exist, the app shows a visible `[placeholder: …]` instead of copy
written for you. Each one is listed here with its screen, its purpose and the
i18n key that holds it (both `en.ts` and `de.ts` carry the same placeholder).

Replace a placeholder by editing its key in `frontend/src/i18n/en.ts` and
`frontend/src/i18n/de.ts`, then delete its row here.

## Placeholders

| Screen | Purpose | Key |
|---|---|---|
| Settings → Appearance, theme picker | The name of the Sep 2026 design, now a preset beside Classic and Workspace | `PRESETS` in `frontend/src/appearance.ts` (`preset:refined`; preset names are not in the catalogue, like "Classic" and "Workspace") |

## Removed

Field notes has no tooltips and no helper text ("UI text names things; it does not
explain them"). Every string removed for that reason is listed here, so any one
can come back. Accessible names (`aria-label`) were kept everywhere.

| Screen | What it was | Key | English text |
|---|---|---|---|
| Today, header | The hover tooltip on Start working (its accessible name stays) | `today.startWorking` | Start working |

## Notes
