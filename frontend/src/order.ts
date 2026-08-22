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
 * Everything except the manual position: due date, then priority, then title,
 * then uid. This is the order that applies when nothing has been placed by hand,
 * and it is also how an unplaced task is measured against a placed one.
 */
function compareIntrinsic(a: Task, b: Task): number {
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

/**
 * The order any list of tasks is shown in.
 *
 * In turn: manual position, then due date, then priority, then title, then uid.
 * Each key is only consulted when the one before it ties.
 *
 * `sort_order` is the manual position drag-reorder writes, and it is null until
 * something is dragged — or forever, for tasks created in another CalDAV client,
 * since the sidecar that holds it is app-only and never goes on the wire.
 *
 * This comparator still sorts a null position LAST, which is right when it is
 * asked about two tasks in isolation. It is NOT how a list is ordered — see
 * `sortTasks`, which is what every view calls. The difference matters because a
 * drag renumbers the whole account (the server's ReorderTasks model says so
 * explicitly: "nothing left null once a drag lands"), so after the first drag a
 * null position stops meaning "ordinary, unplaced" and starts meaning "created
 * since the last drag" — and sinking those to the bottom of every view is not
 * what anyone wants.
 */
export function compareTasks(a: Task, b: Task): number {
  const manual = nullsLast(a.sort_order ?? null, b.sort_order ?? null, (x, y) => x - y)
  if (manual) return manual
  return compareIntrinsic(a, b)
}

/**
 * `tasks` in display order, as a new array.
 *
 * Not simply `sort(compareTasks)`, because an unplaced task has to be *placed
 * among* the manually ordered ones rather than after all of them. That cannot be
 * done pairwise: comparing placed-to-placed by position while comparing
 * placed-to-unplaced by due date is not transitive — given P1(pos 1, due Dec),
 * P2(pos 2, due Jan) and U(due Jun) you get P1 < P2 < U < P1 — and
 * `Array.prototype.sort` on an inconsistent comparator is implementation-defined,
 * which is exactly the class of bug this module exists to prevent.
 *
 * So every task is first given ONE effective position: a placed task keeps its
 * own (normalised to its index, so gaps and duplicates cannot matter), and an
 * unplaced task takes a spot just before the first placed task that ought to
 * come after it. Ordering by that single number, tie-broken by the intrinsic
 * keys, is a genuine total order again.
 */
/**
 * A task's identity ACROSS lists.
 *
 * The backend keys items on `(collection_href, uid)`, and `sortTasks` is handed
 * the merged multi-list set — so the same uid genuinely can appear twice.
 * Copying a VTODO between lists in Tasks.org, DAVx5 or Thunderbird preserves the
 * uid, and the trust model treats those clients as equal-rights writers.
 *
 * Keyed on the bare uid, the unplaced-task loop below overwrote the placed
 * twin's entry, so the row the user had dragged into position jumped somewhere
 * else on every render — and `data.reorder` builds the POST payload from
 * `sortTasks(tasks)`, so the next drag persisted the scrambled sequence for the
 * whole account.
 */
export function taskKey(t: Task): string {
  return `${t.list}\u0000${t.uid}`
}

export function sortTasks(tasks: Task[]): Task[] {
  const placed = tasks
    .filter((t) => t.sort_order != null)
    .sort((a, b) => (a.sort_order! - b.sort_order!) || compareIntrinsic(a, b))

  // Nothing has been dragged (the common case, and every case before the first
  // drag): the intrinsic order is the whole answer.
  if (!placed.length) return [...tasks].sort(compareIntrinsic)

  const at = new Map<string, number>()
  placed.forEach((t, i) => at.set(taskKey(t), i))
  for (const t of tasks) {
    if (t.sort_order != null) continue
    const next = placed.findIndex((p) => compareIntrinsic(t, p) < 0)
    // Half a step before its first later neighbour — or the end, when it is
    // later than everything, which is where it used to land unconditionally.
    at.set(taskKey(t), next < 0 ? placed.length : next - 0.5)
  }

  return [...tasks].sort(
    (a, b) => (at.get(taskKey(a))! - at.get(taskKey(b))!) || compareIntrinsic(a, b))
}

/**
 * Completed and cancelled tasks, most recently finished first.
 *
 * `completed_at` is the VTODO COMPLETED property — the instant the wire actually
 * records — and it is the only honest answer to "what did I finish lately". It
 * has always been on the wire (`ical/edit.py` writes it on every completion) and
 * cached (`items.completed`); it simply was not in the task DTO, so both callers
 * of this ordering fell back to sorting by DUE date descending and a comment
 * asserting no timestamp existed.
 *
 * Two groups, not one, because the fallback is not comparable with the real
 * thing: a task can be COMPLETED with no COMPLETED property (a foreign client's
 * choice), and a CANCELLED one never gets a stamp at all, since cancelling is
 * not completing. Interleaving a due date with a completion instant would order
 * by two different quantities and read as random. So tasks that know when they
 * were finished come first, newest first; everything else keeps the old
 * due-descending proxy behind them, undated last.
 *
 * Shared rather than duplicated: the Tasks pane's completed view and the Home
 * dashboard's "recently completed" module had this same block written out twice
 * and would otherwise have to be fixed twice.
 */
export function sortByCompletion(tasks: Task[]): Task[] {
  // Parsed once per task into a map, not per comparison: `at` is read by the
  // partition below AND by every step of the sort, and a comparator that
  // re-parses a string on each call is the cost `dueAt` documents avoiding.
  // Parsed rather than string-compared, because another client may anchor the
  // stamp to a zone while this app writes UTC, and those two do not sort
  // lexically against each other.
  const at = new Map<string, number>()
  for (const t of tasks) {
    if (!t.completed_at) continue
    // Local parse rather than util's parseDate, keeping this module free of
    // imports the way its header describes — the same choice `dueAt` makes.
    // COMPLETED is a DATE-TIME in RFC 5545, so the bare-date branch is only
    // defensiveness against a malformed value.
    const ms = t.completed_at.includes('T')
      ? new Date(t.completed_at).getTime()
      : new Date(`${t.completed_at}T00:00`).getTime()
    if (!isNaN(ms)) at.set(taskKey(t), ms)
  }
  const stamped = tasks.filter((t) => at.has(taskKey(t)))
  const rest = tasks.filter((t) => !at.has(taskKey(t)))
  return [
    // Tie-broken by the intrinsic order so this stays a TOTAL order, the same
    // property `compareTasks` exists to guarantee — two tasks completed in the
    // same second must not permute between renders.
    ...stamped.sort((a, b) =>
      (at.get(taskKey(b))! - at.get(taskKey(a))!) || compareIntrinsic(a, b)),
    ...sortTasks(rest.filter((t) => t.due)).reverse(),
    ...sortTasks(rest.filter((t) => !t.due)),
  ]
}
