// The one order tasks are listed in, everywhere.
//
// There used to be no order at all in the list view: `active` was a filter over
// whatever array the fetch happened to build, which is per-list blocks
// concatenated in list order. An optimistic create appended to the end of that
// array, so a new task painted at the bottom — and then the write's own SSE
// bump refetched, replaced the array wholesale with the server's due-sorted
// order, and the row jumped somewhere else a few hundred milliseconds after it
// appeared. Two other views did sort, by comparators that disagreed with each
// other about where an undated task goes (one first, one last) and had no final
// tie-break, so equal-due tasks also permuted on every refetch.
//
// The fix is not to make the array's order correct — it is to stop the array's
// order mattering. `compareTasks` is a *total* order: it ends in a uid
// comparison, so no two distinct tasks ever compare equal, and sorting any
// permutation of the same set yields the same sequence. Applied at render, an
// optimistic append lands in its final position on the first paint and does not
// move when the real data arrives.
//
// React-free like lists.ts and tabs.ts so the rule can be tested on its own.

import type { Task } from './api'

/** Ascending, nulls last — the shape most of the keys below want. */
function nullsLast<T>(a: T | null, b: T | null, cmp: (x: T, y: T) => number): number {
  if (a === null) return b === null ? 0 : 1
  if (b === null) return -1
  return cmp(a, b)
}

/** When this task is due, as a timestamp, or null if it has no due date.
 *
 * Parsed rather than string-compared. A due may be a bare date, a floating
 * local datetime this app wrote, or a zone-anchored one another CalDAV client
 * wrote — and those three do not sort lexically in the order they actually
 * fall in. `parseDate` reads a bare date as local midnight, which is what puts
 * an all-day task ahead of a timed one on the same day. */
function dueAt(t: Task): number | null {
  if (!t.due) return null
  // Cheap local parse rather than importing util's parseDate: this runs once
  // per comparison on every render, and the date-only branch is the hot one.
  const ms = t.due.includes('T')
    ? new Date(t.due).getTime()
    : new Date(`${t.due}T00:00`).getTime()
  return isNaN(ms) ? null : ms
}

/** iCal PRIORITY: 1 is the highest, 9 the lowest, 0 or absent means unset.
 *  Unset sorts last, so a flagged task leads the ones nobody ranked. */
function priorityOf(t: Task): number | null {
  return t.priority && t.priority > 0 ? t.priority : null
}

/**
 * The order any list of tasks is shown in.
 *
 * In turn: manual position, then due date, then priority, then title, then uid.
 * Each key is only consulted when the one before it ties.
 *
 * `sort_order` is the manual position drag-reorder writes. It is null for every
 * task until something is dragged, and stays null forever for tasks created in
 * another CalDAV client (the sidecar that holds it is app-only and never goes
 * on the wire), so null sorting last is not a transitional state to be tidied
 * away — it is the permanent, ordinary case for anything the user has not
 * placed by hand. Those tasks fall through to due date, which is where they
 * were before manual ordering existed.
 */
export function compareTasks(a: Task, b: Task): number {
  const manual = nullsLast(a.sort_order ?? null, b.sort_order ?? null, (x, y) => x - y)
  if (manual) return manual

  const due = nullsLast(dueAt(a), dueAt(b), (x, y) => x - y)
  if (due) return due

  const pri = nullsLast(priorityOf(a), priorityOf(b), (x, y) => x - y)
  if (pri) return pri

  const title = nullsLast(a.summary || null, b.summary || null,
    (x, y) => x.localeCompare(y))
  if (title) return title

  // The tie-break that makes this a total order. Without it, tasks equal on
  // every key above are left in whatever order the array had — which is the
  // whole bug this module exists to fix.
  return a.uid < b.uid ? -1 : a.uid > b.uid ? 1 : 0
}

/** `tasks` in display order, as a new array. */
export function sortTasks(tasks: Task[]): Task[] {
  return [...tasks].sort(compareTasks)
}
