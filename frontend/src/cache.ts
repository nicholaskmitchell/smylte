// Last-known-good task, calendar and day-plan data, mirrored to localStorage.
//
// Same contract the tab and appearance caches already state: the server is the
// source of truth, and this is only what to show until it answers. What it buys
// is that the answer is no longer the difference between a populated screen and
// an empty one. A cold load used to be four sequential round trips — /api/me
// (the whole app rendered `null`), /api/settings, /api/lists, then one request
// per list — and during the third the Tasks pane offered "Create a list to get
// started." to a user with a dozen lists. Switching tabs unmounts a view, so
// every navigation replayed it.
//
// Nothing here gates rendering on freshness. Cached rows paint as though live
// and are replaced when the fetch lands; a fetch that fails already raises a
// toast through `makeGuard`, so there is nothing a "possibly stale" chrome
// would tell the user that they are not told anyway.
//
// React-free on purpose, like tabs.ts and dashboard.ts, so the part that has to
// survive a hand-edited or out-of-date blob can be tested on its own.

import type { CalEvent, DayEntry, DayPlan, Habit, List, Task } from './api'

export const CACHE_PREFIX = 'smylte-cache'

/** How long after a change the mirror is written. One drag, one write.
 *
 *  Here rather than in `data.tsx` because there are now four writers on three
 *  surfaces — the task and calendar mirrors, the day plan, the fortnight behind
 *  the Today tab and the habit rules — and a second spelling of this number is
 *  how one of them comes to write on every keystroke while the others coalesce. */
export const CACHE_DEBOUNCE_MS = 400
/** Bumped when a cached shape changes; older versions are swept on boot. */
export const CACHE_VERSION = 1

// An entry past this is quota owed to a session nobody came back to.
const MAX_AGE_MS = 14 * 24 * 60 * 60 * 1000

// Two separate bounds, because they fail differently. Dropping *rows* is safe:
// a partial first paint completes silently a beat later, which beats a blank
// one. Dropping *bytes* is not — the tail of a JSON document is not a valid
// document — so a payload over the ceiling is refused whole.
//
// The two bounds are meant to do DIFFERENT jobs: the row cap is the ordinary
// one, and the byte ceiling exists for the outliers above it that a row count
// cannot catch — a handful of tasks carrying very long notes. That only works
// while a full row-capped payload of ORDINARY rows fits under the ceiling with
// room to spare, and for a long time it did not.
//
// This comment used to estimate a task DTO at "roughly 300 bytes", putting the
// row cap "near 600 KB". Measured, a plain task is about 508 bytes and 2000 of
// them serialize to ~1.02 MB — which was three per cent UNDER a 1 MiB ceiling,
// not half of it. The two bounds had quietly become one, the ceiling was
// protecting nothing, and adding a single nullable field to `Task` (25 bytes a
// row) pushed the row-capped payload over it and disabled the task cache
// outright for any account near the cap. Silently: an over-ceiling payload is
// refused whole and the entry removed, so the symptom is a mirror that simply
// stops painting.
//
// 2 MiB restores the gap the design assumed — roughly double what the row cap
// can produce — and is still well inside the ~5 MB an origin usually gets, with
// the events window and the lists budgeted for alongside. `cache.test.ts` pins
// the relationship rather than the numbers, so the next field added to a Task
// cannot re-close it in silence.
export const MAX_ROWS = 2000
export const MAX_BYTES = 2 * 1024 * 1024

// Which account the cached rows belong to. Set from /api/me — but that is a
// round trip, and the whole point of the mirror is to paint before it returns.
// So the name is also remembered here and resolved lazily on the first read,
// which is what lets the very first frame have content. It is no more of a
// disclosure than the keys themselves, which are named after the user.
//
// A read with no user resolvable is a miss, so a fresh browser (or a test) sees
// nothing, and one account never reads another's rows.
const LAST_USER_KEY = `${CACHE_PREFIX}:last-user`
let currentUser = ''

export function setCacheUser(user: string): void {
  currentUser = user
  try {
    if (user) localStorage.setItem(LAST_USER_KEY, user)
    else localStorage.removeItem(LAST_USER_KEY)
  } catch { /* private mode */ }
}

/** Who the mirror was last written for, or '' if nobody. */
export function lastCacheUser(): string {
  if (currentUser) return currentUser
  try { return localStorage.getItem(LAST_USER_KEY) ?? '' } catch { return '' }
}

const keyFor = (kind: string): string | null => {
  const user = lastCacheUser()
  return user ? `${CACHE_PREFIX}:${CACHE_VERSION}:${user}:${kind}` : null
}

/** Every cache key this origin holds, at any version, for any user. */
function ownKeys(): string[] {
  const out: string[] = []
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k?.startsWith(`${CACHE_PREFIX}:`)) out.push(k)
    }
  } catch { /* private mode */ }
  return out
}

/** Drop cached data. With no user, drops every user's — that is logout. */
export function clearCache(user?: string): void {
  const scope = user ? `${CACHE_PREFIX}:${CACHE_VERSION}:${user}:` : `${CACHE_PREFIX}:`
  try {
    for (const k of ownKeys()) {
      // The remembered name is not a cache entry; clearing one user's rows must
      // not forget who the *other* one was.
      if (user && k === LAST_USER_KEY) continue
      if (k.startsWith(scope)) localStorage.removeItem(k)
    }
  } catch { /* private mode */ }
}

/** Drop entries written by an older shape of this module. */
export function sweepOldVersions(): void {
  const keep = `${CACHE_PREFIX}:${CACHE_VERSION}:`
  try {
    for (const k of ownKeys()) {
      if (k !== LAST_USER_KEY && !k.startsWith(keep)) localStorage.removeItem(k)
    }
  } catch { /* private mode */ }
}

// ── the raw read/write pair ─────────────────────────────────────────────────

function write(kind: string, rows: unknown[]): void {
  const key = keyFor(kind)
  if (!key) return
  try {
    const body = JSON.stringify({ at: Date.now(), rows: rows.slice(0, MAX_ROWS) })
    // Over the ceiling, drop any existing entry rather than leaving yesterday's
    // rows to outlive the data that was too big to replace them.
    if (body.length > MAX_BYTES) { localStorage.removeItem(key); return }
    localStorage.setItem(key, body)
  } catch { /* private mode / quota — the server copy still wins next load */ }
}

function read<T>(kind: string, sanitize: (v: unknown) => T | null): T[] | null {
  const key = keyFor(kind)
  if (!key) return null
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const blob = JSON.parse(raw) as { at?: unknown; rows?: unknown }
    if (typeof blob.at !== 'number' || Date.now() - blob.at > MAX_AGE_MS) {
      localStorage.removeItem(key)
      return null
    }
    if (!Array.isArray(blob.rows)) return null
    const rows = blob.rows.map(sanitize).filter((r): r is T => r !== null)
    // A blob that sanitizes to nothing is a miss, not an empty account —
    // otherwise a corrupt entry would confidently render "no tasks".
    return rows.length ? rows : null
  } catch { return null }
}

// ── sanitizers ──────────────────────────────────────────────────────────────
// These rows go straight into render paths that call `t.due.includes('T')` and
// `e.tags.map(...)`, and localStorage is writable by anything that ever gets
// script execution on this origin. So each field is rebuilt to its own type
// with a documented default rather than trusted — the same discipline
// `sanitizeAppearance` applies to the token blob.

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)
const orNull = (v: unknown): string | null => (typeof v === 'string' ? v : null)
const bool = (v: unknown): boolean => v === true
const num = (v: unknown): number => (typeof v === 'number' && isFinite(v) ? v : 0)
const numOrNull = (v: unknown): number | null =>
  typeof v === 'number' && isFinite(v) ? v : null
const boolOrNull = (v: unknown): boolean | null => (typeof v === 'boolean' ? v : null)
const strs = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []

const obj = (v: unknown): Record<string, unknown> | null =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null

export function sanitizeList(v: unknown): List | null {
  const o = obj(v)
  const id = o && str(o.id)
  const href = o && str(o.href)
  if (!o || !id || !href) return null
  return {
    id,
    href,
    name: orNull(o.name) ?? '',
    is_task_list: bool(o.is_task_list),
    is_calendar: bool(o.is_calendar),
    open_count: num(o.open_count),
    task_count: num(o.task_count),
    event_count: num(o.event_count),
    total: num(o.total),
    color: orNull(o.color),
  }
}

export function sanitizeTask(v: unknown): Task | null {
  const o = obj(v)
  const uid = o && str(o.uid)
  const list = o && str(o.list)
  if (!o || !uid || !list) return null
  return {
    uid,
    list,
    summary: orNull(o.summary),
    notes: orNull(o.notes),
    status: orNull(o.status) ?? 'NEEDS-ACTION',
    completed: bool(o.completed),
    // Absent from anything this cache wrote before the field existed, which
    // `orNull` already renders as null — the same "unstamped" case a foreign
    // client's COMPLETED-less task produces, so `sortByCompletion` handles it.
    completed_at: orNull(o.completed_at),
    cancelled: bool(o.cancelled),
    // Absent from anything this cache wrote before parking existed, which
    // `bool` renders as false — "still live", the only answer that could be
    // assumed without setting work aside on the owner's behalf.
    parked: bool(o.parked),
    parked_at: orNull(o.parked_at),
    priority: numOrNull(o.priority),
    priority_label: orNull(o.priority_label) ?? 'none',
    percent_complete: numOrNull(o.percent_complete),
    due: orNull(o.due),
    due_is_date: bool(o.due_is_date),
    start: orNull(o.start),
    start_is_date: bool(o.start_is_date),
    tags: strs(o.tags),
    parent: orNull(o.parent),
    children: strs(o.children),
    child_count: num(o.child_count),
    completed_child_count: num(o.completed_child_count),
    derived_percent: numOrNull(o.derived_percent),
    pinned: bool(o.pinned),
    // Rebuilt field-by-field like the rest: anything not listed here is dropped
    // on the way through the disk cache, so a missing line means manual order
    // would work on a fresh load and silently vanish on a cached one.
    sort_order: numOrNull(o.sort_order),
    kanban_column: orNull(o.kanban_column),
    // Absent from anything this cache wrote before estimates existed, which
    // `numOrNull` renders as null — "nobody said how long this takes", the same
    // thing a task nobody has estimated says. Nothing to migrate.
    estimated_minutes: numOrNull(o.estimated_minutes),
    notify_minutes_before: null,
    has_rrule: bool(o.has_rrule),
    href: orNull(o.href) ?? '',
    etag: orNull(o.etag) ?? '',
    created: orNull(o.created),
    last_modified: orNull(o.last_modified),
  }
}

export function sanitizeEvent(v: unknown): CalEvent | null {
  const o = obj(v)
  const uid = o && str(o.uid)
  const id = o && str(o.id)
  const calendar = o && str(o.calendar)
  if (!o || !uid || !id || !calendar) return null
  return {
    uid,
    id,
    recurrence_id: orNull(o.recurrence_id),
    is_recurring: bool(o.is_recurring),
    calendar,
    summary: orNull(o.summary),
    description: orNull(o.description),
    location: orNull(o.location),
    start: orNull(o.start),
    start_is_date: bool(o.start_is_date),
    end: orNull(o.end),
    end_is_date: bool(o.end_is_date),
    duration: orNull(o.duration),
    all_day: bool(o.all_day),
    status: orNull(o.status),
    // `!== false`, not `bool(...)`. Absent from anything this cache wrote
    // before the field existed, and the DTO's own default for an event with no
    // TRANSP is BUSY — so a missing value has to read as true or an upgrade
    // would paint every cached event as free for one round trip. `bool()`
    // would answer false for exactly those rows.
    busy: o.busy !== false,
    notify_minutes_before: null,
    tags: strs(o.tags),
    has_rrule: bool(o.has_rrule),
    href: orNull(o.href) ?? '',
    etag: orNull(o.etag) ?? '',
  }
}

// ── the day plan's own sanitizers ───────────────────────────────────────────
//
// The Today tab holds a SNAPSHOT rather than a query (see TodayView.tsx's
// header), which is exactly why it wants a mirror: every other task surface can
// recompute itself from the tasks already on disk, and this one cannot — the
// rows it paints exist nowhere but in `day_plan`. Without this the tab was the
// one screen in the app that still opened blank on a cold load and blanked
// again on every return to it, because switching tabs unmounts the view.

/** `kind` and `source` come back as free strings on purpose.
 *
 *  Both unions widen SILENTLY — api.ts says so of `DayEntryKind` in as many
 *  words, and TodayView reads both through fallback maps (`KIND_LABEL`,
 *  `REVIEW_ARM`) for that reason. Narrowing them to an allowlist here would
 *  rewrite a kind this build has not heard of into one it has, on the way
 *  through the disk cache only, so a row would read one way live and another
 *  way cached. Required rather than defaulted, though: a row that does not say
 *  what it is, or which day it belongs to, is not a row. */
export function sanitizeDayEntry(v: unknown): DayEntry | null {
  const o = obj(v)
  const entry_id = o && str(o.entry_id)
  const day = o && str(o.day)
  const kind = o && str(o.kind)
  const source = o && str(o.source)
  if (!o || !entry_id || !day || !kind || !source) return null
  return {
    entry_id,
    day,
    kind: kind as DayEntry['kind'],
    source: source as DayEntry['source'],
    list: orNull(o.list),
    uid: orNull(o.uid),
    title: orNull(o.title),
    position: numOrNull(o.position),
    done_at: orNull(o.done_at),
    dropped_at: orNull(o.dropped_at),
    habit_id: orNull(o.habit_id),
    rolled_to: orNull(o.rolled_to),
    estimate_minutes: numOrNull(o.estimate_minutes),
    worked_seconds: numOrNull(o.worked_seconds),
    // Tri-state, and the null must survive the mirror: a row that never said
    // follows the account's default, and a blob that turned that into `false`
    // would pin every row to "until done" for the length of one fetch.
    capped: boolOrNull(o.capped),
    // `orderEntries` tie-breaks on this with `localeCompare`, so it has to be a
    // string whatever the blob says — a null here would throw while sorting the
    // day. '' is the earliest value there is, so a row that arrived without a
    // stamp sorts first among the rows it ties with rather than moving between
    // renders; `entry_id` behind it keeps the order total either way.
    created_at: orNull(o.created_at) ?? '',
  }
}

/** A whole day. `entries: []` is a REAL answer here and is kept — an opened day
 *  the owner emptied is a day with nothing on it, and reporting that as a miss
 *  would make the tab paint blank for exactly the account whose last look at it
 *  was blank. That is the one place this differs from `read` above, which treats
 *  an empty row set as a corrupt entry. */
export function sanitizeDayPlan(v: unknown): DayPlan | null {
  const o = obj(v)
  const day = o && str(o.day)
  if (!o || !day) return null
  const rows = Array.isArray(o.entries) ? o.entries : []
  return {
    day,
    planned: bool(o.planned),
    capacity_minutes: numOrNull(o.capacity_minutes),
    // Null is a REAL answer and every reader has to handle it — an account that
    // never stated a capacity must not be told it has overcommitted against a
    // number it never gave. `numOrNull` says exactly that for a missing field.
    capacity: numOrNull(o.capacity),
    committed_at: orNull(o.committed_at),
    // Absent from anything this cache wrote before the app recorded it, which
    // `numOrNull` renders as null — the same null a day committed inside its
    // capacity gets, and the same thing it means there: nothing to record.
    committed_over_minutes: numOrNull(o.committed_over_minutes),
    shutdown_at: orNull(o.shutdown_at),
    reflection: orNull(o.reflection),
    entries: rows.slice(0, MAX_ROWS)
      .map(sanitizeDayEntry).filter((e): e is DayEntry => e !== null),
  }
}

export function sanitizeHabit(v: unknown): Habit | null {
  const o = obj(v)
  const id = o && str(o.id)
  if (!o || !id) return null
  return {
    id,
    title: orNull(o.title) ?? '',
    // '' is EVERY DAY, spelled as the absence of a restriction — see api.ts.
    // So the default is not a stand-in for a missing value, it IS the value a
    // habit with no restriction carries.
    days: orNull(o.days) ?? '',
    paused_at: orNull(o.paused_at),
    position: numOrNull(o.position),
    estimate_minutes: numOrNull(o.estimate_minutes),
    created_at: orNull(o.created_at) ?? '',
  }
}

// ── the typed surface the views use ─────────────────────────────────────────

export const cacheLists = (rows: List[]) => write('lists', rows)
export const readCachedLists = () => read('lists', sanitizeList)

export const cacheTasks = (rows: Task[]) => write('tasks', rows)
export const readCachedTasks = () => read('tasks', sanitizeTask)

export const cacheCalendars = (rows: List[]) => write('calendars', rows)
export const readCachedCalendars = () => read('calendars', sanitizeCalendarList)

// Calendars and lists are the same DTO on the wire; the alias keeps the two
// call sites reading for what they mean.
function sanitizeCalendarList(v: unknown): List | null {
  return sanitizeList(v)
}

// Events are cached for one window — the month the app boots on, which is the
// only one where an instant paint is the difference between content and a blank
// grid. Navigating to a month nobody has open can take its round trip. The
// window is stored with the rows so a cache written for another month is a miss
// rather than a grid of events from the wrong six weeks.
export function cacheEvents(from: string, to: string, rows: CalEvent[]): void {
  const key = keyFor('events')
  if (!key) return
  try {
    const body = JSON.stringify({ at: Date.now(), from, to, rows: rows.slice(0, MAX_ROWS) })
    if (body.length > MAX_BYTES) { localStorage.removeItem(key); return }
    localStorage.setItem(key, body)
  } catch { /* private mode / quota */ }
}

export function readCachedEvents(from: string, to: string): CalEvent[] | null {
  const key = keyFor('events')
  if (!key) return null
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const blob = JSON.parse(raw) as { at?: unknown; from?: unknown; to?: unknown; rows?: unknown }
    if (typeof blob.at !== 'number' || Date.now() - blob.at > MAX_AGE_MS) {
      localStorage.removeItem(key)
      return null
    }
    if (blob.from !== from || blob.to !== to || !Array.isArray(blob.rows)) return null
    const rows = blob.rows.map(sanitizeEvent).filter((r): r is CalEvent => r !== null)
    return rows.length ? rows : null
  } catch { return null }
}

// ── the day plan, the fortnight behind it, and the habit rules ──────────────

// ONE day, stored with the key it is for, so a blob written yesterday is a miss
// rather than yesterday's rows under today's heading — the same shape, and the
// same reason, as the event window above.
//
// One is enough because the Today tab always MOUNTS on today: `day` is seeded
// from the wall clock, so a look-back never survives a tab switch and a mirror
// of last Tuesday could never be read back. TodayView only writes today's for
// that reason — a past day's would evict the one entry that gets used.
export function cacheDayPlan(plan: DayPlan): void {
  const key = keyFor('day')
  if (!key) return
  try {
    const body = JSON.stringify({
      at: Date.now(),
      day: plan.day,
      plan: { ...plan, entries: plan.entries.slice(0, MAX_ROWS) },
    })
    if (body.length > MAX_BYTES) { localStorage.removeItem(key); return }
    localStorage.setItem(key, body)
  } catch { /* private mode / quota */ }
}

export function readCachedDayPlan(day: string): DayPlan | null {
  const key = keyFor('day')
  if (!key) return null
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const blob = JSON.parse(raw) as { at?: unknown; day?: unknown; plan?: unknown }
    if (typeof blob.at !== 'number' || Date.now() - blob.at > MAX_AGE_MS) {
      localStorage.removeItem(key)
      return null
    }
    if (blob.day !== day) return null
    const plan = sanitizeDayPlan(blob.plan)
    // The envelope and the body have to name the SAME day. TodayView keys every
    // render of the day on `plan.day === day` and every write carries the key in
    // its URL, so a blob whose two halves disagree is corrupt rather than merely
    // stale, and painting either answer would be a claim about a day.
    return plan && plan.day === day ? plan : null
  } catch { return null }
}

// The fortnight behind the habit counts and the "still open from a recent plan"
// suggestions — one `api.days` window, mirrored like the event window and read
// back only for the window it was written for. Both ends move at a rollover and
// at every step of the picker, so a window that does not match is a miss.
export function cacheDayRange(from: string, to: string, plans: DayPlan[]): void {
  const key = keyFor('days')
  if (!key) return
  try {
    const body = JSON.stringify({ at: Date.now(), from, to, rows: plans.slice(0, MAX_ROWS) })
    if (body.length > MAX_BYTES) { localStorage.removeItem(key); return }
    localStorage.setItem(key, body)
  } catch { /* private mode / quota */ }
}

export function readCachedDayRange(from: string, to: string): DayPlan[] | null {
  const key = keyFor('days')
  if (!key) return null
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const blob = JSON.parse(raw) as { at?: unknown; from?: unknown; to?: unknown; rows?: unknown }
    if (typeof blob.at !== 'number' || Date.now() - blob.at > MAX_AGE_MS) {
      localStorage.removeItem(key)
      return null
    }
    if (blob.from !== from || blob.to !== to || !Array.isArray(blob.rows)) return null
    const rows = blob.rows.map(sanitizeDayPlan).filter((p): p is DayPlan => p !== null)
    // Empty IS a miss here, unlike a single day above: "no plans in the window"
    // and "nothing cached" are indistinguishable to every reader of this
    // (`recentPlans` answers `[]` either way), so there is nothing to preserve
    // and the ordinary corrupt-blob rule applies.
    return rows.length ? rows : null
  } catch { return null }
}

// The habit RULES, so the sheet paints its list the moment it opens rather than
// after a round trip. Definitions only — occurrences are day-plan rows and ride
// in the mirror above, which is the same split the API draws.
export const cacheHabits = (rows: Habit[]) => write('habits', rows)
export const readCachedHabits = () => read('habits', sanitizeHabit)
