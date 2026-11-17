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
| Today, planning band | The sentence beside Plan my day when the day has no capacity (removed under Field notes only) | `today.bandNoCapacity` | Today isn’t planned yet. |
| Today, planning band | The button that dismissed the planning nudge for the day, shown as ✕; Plan my day now stays until the day is planned (removed under Field notes only) | `today.notNow` | Not now |
| Today, list | The habits hint under the day's rows; Habits stays in the ⋯ menu (removed under Field notes only) | `today.habitsHint`, `today.setOneUp` | Habits add a line to your day on the days you choose. Set one up |
| Today, list | The "The day" label when no Habits section is above it; the list keeps it as its accessible name (removed under Field notes only) | `today.theDay` | The day |
| Tasks, header | The hover tooltip on ‹ beside Today; its accessible name stays (removed under Field notes only) | `tasks.earlier` | Earlier |
| Tasks, header | The hover tooltip on › beside Today; its accessible name stays (removed under Field notes only) | `tasks.later` | Later |
| Tasks, rows | The hover tooltip on a row's tick, in the list and on a day card; its accessible name stays (removed under Field notes only) | `tasks.toggleComplete` | Toggle complete |
| Tasks, rows | The hover tooltip on a parent row's fold arrow; its accessible name stays (removed under Field notes only) | `tasks.showSubtasks`, `tasks.hideSubtasks` | Show subtasks of {task} / Hide subtasks of {task} |
| Tasks, rows | The hover tooltip on "+ sub"; it is the button's accessible name instead (removed under Field notes only) | `tasks.addSubtask` | Add subtask |
| Tasks, rows | The hover tooltip on "del"; it is the button's accessible name instead (removed under Field notes only) | `common.delete` | Delete |
| Tasks, quick add | The hover tooltip on the list picker; it is the picker's accessible name instead (removed under Field notes only) | `tasks.quickAddList` | List for the new task |
| Tasks, quick add | The hover tooltip on New…; the button's text names it (removed under Field notes only) | `tasks.openFullForm` | Open the full form for a new task |
| Task editor | The line under the fields saying what a move to another list takes with it (removed under Field notes only) | `taskModal.moveTakesSubtasks`, `taskModal.moveLeavesParent` | Its subtasks move with it. / It moves out from under its parent task, which stays where it is. |
| Task editor | The line beside Park it / Bring it back (removed under Field notes only) | `tasks.parkHint`, `tasks.parkedHint` | Hides it from your lists and your day until you bring it back. Other apps still show it. / Parked. Bring it back to return it to your lists. |

## Notes
