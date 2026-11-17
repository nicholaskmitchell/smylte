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
| Sidebar, rows | The hover tooltip on ⋯ beside a list; its accessible name stays (removed under Field notes only) | `side.edit` | Edit |
| Sidebar, phone bar and rail | The hover tooltips on the Completed, Parked and Suggested buttons; their accessible names stay (removed under Field notes only) | `side.backToTasksShort`, `side.viewCompletedShort`, `side.viewParkedShort`, `side.viewSuggestedShort` | Back to tasks / View completed / View parked / Suggested from email |
| Sidebar, header and drawer | The hover tooltips on + and on the new-group button; their accessible names stay (removed under Field notes only) | `side.lists.new`, `side.calendars.new`, `side.newGroup` | New list / New calendar / New group |
| Sidebar, phone drawer | The hover tooltip on ✕, which closes the drawer; its accessible name is Close (removed under Field notes only) | `side.drawerDone` | Done |
| Sidebar, header and rail | The hover tooltips on » and «; their accessible names stay (removed under Field notes only) | `side.expand`, `side.collapse` | Expand sidebar / Collapse sidebar |
| Sidebar, group header | The hover tooltips on a group's fold arrow and its show or hide all button; their accessible names stay (removed under Field notes only) | `side.groupExpand`, `side.groupCollapse`, `side.hideAllInGroup`, `side.showAllInGroup` | Expand / Collapse / Hide all in group / Show all in group |
| Sidebar, group header | The hover tooltips on a group's confirm-delete, keep, rename and delete buttons; their accessible names stay (removed under Field notes only) | `side.deleteGroupTitle`, `side.keepGroup`, `side.renameGroup`, `side.deleteGroup` | Delete group (lists are kept) / Keep the group / Rename group / Delete group |
| Sidebar, colour row | The hover tooltips on the no-colour and custom-colour squares; their accessible names stay (removed under Field notes only) | `side.noColor`, `side.customColor` | No color / Custom color |
| Sidebar, list editor | The hover tooltip on Archive; the button's text names it (removed under Field notes only) | `side.archiveTitle` | Hide without deleting. Restore from Settings. |
| Sidebar, phone drawer | The line under the header saying what a tap on a row and on ⋯ does (removed under Field notes only) | `side.lists.tapHint`, `side.archiveClause`, `side.calendars.tapHint` | Tap a list to show or hide it. Tap ⋯ to rename, recolor{archive} or delete. / , archive / Tap a calendar to show or hide it. Tap ⋯ to rename, recolor{archive} or delete. |
| Sidebar, empty group | The words in a group with no lists, which stays as an empty drop zone (removed under Field notes only) | `side.lists.groupEmpty`, `side.lists.dropHere`, `side.calendars.groupEmpty`, `side.calendars.dropHere` | Empty. Add a list from its ⋯ menu. / Drag a list here / Empty. Add a calendar from its ⋯ menu. / Drag a calendar here |
| Suggested, rows | The hover tooltip on the confidence figure, which stays on the row (removed under Field notes only) | `mail.sug.confidence` | How sure the model was |
| Home, header | The line beside the title while arranging (removed under Field notes only; the module count stays) | `home.arrangeHint` | Drag to move · corner to resize |
| Home, arranging | The hover tooltip on a module's ✕; its accessible name stays (removed under Field notes only) | `common.remove` | Remove |
| Home, module picker | The one-line description under each module's name (removed under Field notes only) | `module.today.blurb`, `module.overdue.blurb`, `module.upcoming.blurb`, `module.mini_calendar.blurb`, `module.completed.blurb`, `module.booking_links.blurb`, `module.bookings.blurb`, `module.quick_add.blurb`, `module.suggested.blurb`, `module.shares.blurb`, `module.week.blurb`, `module.day_plan.blurb` | Tasks due today, across every list. / Anything past its due date. / The next seven days of tasks. / This month, dotted in each calendar's color. / Tasks you finished recently. / Your scheduling links and their state. / Who has booked time with you. / Add a task to a list. / Tasks and events your email suggests, to add or dismiss in one tap. / Your share links: who is looking, and a switch to turn each off. / Tasks completed per week. / Today’s plan, habits and notes. |

## Notes
