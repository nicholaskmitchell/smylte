// Typed client for the tasksd API. Same-origin: the session cookie rides along
// automatically, so there are no tokens to manage in JS (it's HttpOnly anyway).

// Both shapes are defined next to the code that gives them meaning — the token
// allowlist and the grid math — and re-exported here so the wire contract still
// reads in one place. The backend mirrors them in SettingsPatch.
import type { Appearance } from './appearance'
import type { CalendarFit } from './calendar'
import type { DashboardModule } from './dashboard'
import type { Tab, TabStart } from './tabs'
import type { TimeFormat } from './time'
export type { Appearance, DashboardModule }

export class AuthError extends Error {}

/** A non-2xx the server actually answered, carrying its status.
 *
 * Without it every failure looked alike to callers: a 429 from the booking
 * rate-limiter was indistinguishable from a genuine 404, and a dropped
 * connection from a rejected request. Callers that need to tell them apart
 * (retryable vs terminal) check `status`; a network failure is still a plain
 * Error, because nothing answered at all. */
export class HttpError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
  }
}

export interface List {
  id: string
  href: string
  name: string
  is_task_list: boolean
  is_calendar: boolean
  open_count: number
  task_count: number
  event_count: number
  total: number
  color: string | null
}

export interface Task {
  uid: string
  list: string
  summary: string | null
  notes: string | null
  status: string
  completed: boolean
  // The instant the VTODO records as COMPLETED, or null. Distinct from the flag
  // above, which is derived from STATUS: a client can write STATUS:COMPLETED and
  // no COMPLETED property, so this is null for some completed tasks and anything
  // ordering by it needs a fallback.
  completed_at: string | null
  cancelled: boolean
  priority: number | null
  priority_label: string
  percent_complete: number | null
  due: string | null
  due_is_date: boolean
  start: string | null
  start_is_date: boolean
  tags: string[]
  parent: string | null
  children: string[]
  child_count: number
  completed_child_count: number
  derived_percent: number | null
  pinned: boolean
  // Manual position (see order.ts). Lives in the app-only sidecar, so it is
  // null until something is dragged, and stays null for tasks another CalDAV
  // client created — the sidecar never goes on the wire.
  sort_order: number | null
  // Sidecar too, and unused by any view today — declared because the endpoint
  // returns it, and a field the server sends that the type denies exists is how
  // the four below went missing in the first place.
  kanban_column: string | null
  // This task carries an RRULE or RDATE. VTODO recurrence is GATED (see
  // docs/recurrence-findings.md) so nothing in this app advances such a task —
  // but one written by Tasks.org or jtx Board is already in the cache, and a
  // view that completes it should be able to say so rather than treating it as
  // an ordinary task.
  has_rrule: boolean
  href: string
  etag: string
  // Wire timestamps, both nullable: CREATED and LAST-MODIFIED are optional
  // properties and plenty of clients omit them.
  created: string | null
  last_modified: string | null
}

// The priority vocabulary the backend maps to iCal PRIORITY ints (edit.py's
// PRIORITY table). Lives here rather than in a view so the task list and the
// bulk composer can share it without importing each other.
export const PRIORITIES = ['none', 'low', 'medium', 'high'] as const

// Everything POST /lists/{id}/tasks accepts (backend CreateTask), minus the
// client_id the api client mints. Optional keys are *omitted* to mean "leave
// unset" — the backend only copies non-None fields onto the VTODO, so sending
// notes: '' would write an empty DESCRIPTION rather than no description.
export interface CreateTaskBody {
  summary: string
  notes?: string
  priority?: string          // 'low' | 'medium' | 'high' ('none' is omitted)
  due?: string               // 'YYYY-MM-DD' (all-day) or 'YYYY-MM-DDTHH:MM' (timed)
  start?: string             // 'YYYY-MM-DD'
  tags?: string[]
  parent?: string            // parent task uid, for subtasks
}

export interface CalEvent {
  uid: string
  id: string                 // unique per rendered instance (uid, or `uid::recurrence_id`)
  recurrence_id: string | null
  is_recurring: boolean
  calendar: string
  summary: string | null
  description: string | null
  location: string | null
  start: string | null
  start_is_date: boolean
  end: string | null
  end_is_date: boolean
  // An iCalendar DURATION (e.g. "PT1H30M") when the VEVENT carries one INSTEAD
  // of a DTEND — the shape DAVx5 and the phone clients write. `end` is null for
  // those, so anything reconstructing a span has to look here before assuming
  // the event has no length.
  duration: string | null
  all_day: boolean
  status: string | null
  tags: string[]
  has_rrule: boolean
  href: string
  etag: string
}

// Which slice of a recurring series a write applies to.
export type EventScope = 'all' | 'this' | 'thisandfuture'

// ── client scheduling (booking links) ──────────────────────────────────────

// Weekly availability: keys "0" (Monday) … "6" (Sunday) → "HH:MM-HH:MM" ranges.
export type Availability = Record<string, string[]>

export interface BookingLink {
  token: string
  title: string
  description: string | null
  calendar: string                 // target calendar id
  calendar_name: string | null
  calendar_missing: boolean          // target calendar is gone; the link is disabled until repointed
  duration_minutes: number
  timezone: string                 // IANA name
  availability: Availability
  show_busy: boolean
  buffer_minutes: number
  min_notice_hours: number
  horizon_days: number
  enabled: boolean
  booking_count: number
  created_at: string
  updated_at: string
}

export interface BookingLinkInput {
  title: string
  description?: string | null
  calendar: string
  duration_minutes?: number
  timezone: string
  availability?: Availability
  show_busy?: boolean
  buffer_minutes?: number
  min_notice_hours?: number
  horizon_days?: number
  enabled?: boolean
}

export interface Booking {
  id: string
  link: string
  link_title: string | null
  event_uid: string
  calendar: string
  name: string
  email: string
  notes: string | null
  start: string                    // ISO with offset (link tz)
  end: string
  created_at: string
}

export interface PublicSlot {
  start: string                    // ISO with offset — Date() parses it directly
  end: string
}

export interface PublicBookingInfo {
  token: string
  title: string
  description: string | null
  duration_minutes: number
  timezone: string
  slots: PublicSlot[]
  busy?: PublicSlot[]              // redacted: times only, present when the owner opted in
}

export interface PublicBookingResult {
  id: string
  start: string
  end: string
  title: string
  duration_minutes: number
  timezone: string
}

// How the tasks pane lays out: a flat list, or date columns (3-day / week).
export type TasksViewMode = 'list' | 'day3' | 'week'

// A named grouping of task lists in the sidebar. Purely a UI construct — the
// lists stay first-class CalDAV collections; a group only records which list
// ids sit under one collapsible header. `lists` is a membership set (render
// order still follows the global list order, so drag-reorder keeps working).
export interface TaskGroup {
  id: string
  name: string
  lists: string[]
}

// ── the day plan (the Today tab) ───────────────────────────────────────────
//
// A day plan is a SNAPSHOT, not a query. Every other task surface in this app
// recomputes "what is due today" from the wire on each paint, so the list moves
// under the owner all day. `day_plan` is the sidecar row that freezes what a
// day held when it was first opened, and from then on the day is something the
// owner arranges rather than a filter that keeps changing.
//
// The table lives in SQLite only — there is no VTODO, VEVENT or CalDAV property
// for "I plan to do this today", and inventing one would write this app's
// planning model into collections that Tasks.org, jtx Board and Thunderbird
// share. So a day is app-only state, like `sort_order` and the task groups.

/** What a day entry points at: a task on a list, a note that lives only in the
 *  day, or one occurrence of a HABIT (see `Habit` below).
 *
 *  A habit occurrence is an ORDINARY day-plan row — it ticks, drops and orders
 *  like everything else here, and there is no second ledger behind it. Widening
 *  this union is silent: nothing in the app switches on `kind` exhaustively, so
 *  the compiler cannot point at the places that now see a third value. They are
 *  enumerated in TodayView.tsx, which is the only module that reads it. */
export type DayEntryKind = 'task' | 'note' | 'habit'

/** How an entry got onto the day: `auto` from the first open's snapshot,
 *  `carried` from the previous plan's leftovers, `user` from a deliberate add,
 *  `habit` minted by a habit rule when the day was opened.
 *  The backend's carry-over rule reads this — only `user` entries follow the
 *  owner into the next day — so it is a fact about the row, not a label. That
 *  is also why a habit occurrence is not carried: tomorrow gets its own from
 *  the rule, and a carried one would double it. */
export type DayEntrySource = 'auto' | 'carried' | 'user' | 'habit'

export interface DayEntry {
  entry_id: string
  day: string                // YYYY-MM-DD
  kind: DayEntryKind
  // Task entries: the list's SHORT id, the same value `Task.list` carries, so
  // an entry joins back to its task on (list, uid). Null on a note.
  list: string | null
  uid: string | null
  // Note entries: the text. Null on a TASK entry, deliberately — a task entry's
  // text is the task's own SUMMARY, read live, so there is no second copy here
  // to go stale when the task is renamed.
  //
  // A HABIT occurrence carries a title too, and that one IS a copy — taken from
  // the habit the moment the row was minted. That is the opposite choice from a
  // task entry and the right one for it: renaming a habit must not rewrite what
  // last Tuesday says the owner planned, because a past day is a finished
  // record rather than a projection of the current rules.
  title: string | null
  source: DayEntrySource
  position: number | null
  // The instant the entry was ticked, or null. A NOTE's field: a task's
  // doneness is its VTODO STATUS, the one answer every client on the account
  // shares, so `done` on a task entry is refused by the backend with a 422
  // rather than written as a second one. TodayView routes a task row's checkbox
  // through `api.complete` for the same reason.
  done_at: string | null
  // "I decided not to do this", which is the most useful thing a past day can
  // report. Dropping stamps this column rather than deleting the row, so a
  // dropped entry still comes back on every read and the client filters it.
  dropped_at: string | null
  // The habit rule that minted this occurrence; null on every other kind. It
  // deliberately has no foreign key behind it and is allowed to DANGLE: deleting
  // a habit removes the rule, and the days it already ran on keep their rows.
  // Nothing resolves it back to a definition — the row carries its own copied
  // title — so its only job is to be an identity the week's occurrences of one
  // habit can be counted under.
  habit_id: string | null
  created_at: string
}

export interface DayPlan {
  day: string
  /** This day has a plan: it has been opened, or something has been added to
   *  it. Not the same as "a snapshot was derived" — adding a row to a day nobody
   *  has opened makes it planned without deriving one, and the server tracks
   *  those separately.
   *
   *  False means neither has happened, and `entries` is then `[]`. The converse
   *  does not hold, which is the whole reason this flag exists: an opened day
   *  the owner emptied is planned with nothing in it, and re-opening it must not
   *  snapshot over that. */
  planned: boolean
  entries: DayEntry[]
}

/** Everything POST /day/{day}/entries accepts. `list` + `uid` name a task;
 *  `title` carries a note. Which pair is required follows from `kind`. */
export interface CreateDayEntryBody {
  // Client-generated, like `client_id` on a task create and for the same
  // reason: a POST retried after a dropped response has to land on the row the
  // first attempt made rather than beside it.
  entry_id: string
  // 'task' or 'note' only, and narrower than `DayEntry.kind` on purpose. A
  // habit OCCURRENCE is minted by its rule when a day is opened, never handed
  // in by a client — the backend refuses kind='habit' here with a 422 — so
  // admitting it would only let a caller spell a request that cannot succeed.
  kind: Exclude<DayEntryKind, 'habit'>
  list?: string
  uid?: string
  title?: string
}

/** Everything PATCH /day/{day}/entries/{entry_id} accepts. Every field is
 *  optional and an omitted one is left alone — `done: false` and `dropped:
 *  false` are real values (the undo path), so they cannot be spelled by
 *  omission. */
export interface PatchDayEntryBody {
  done?: boolean
  dropped?: boolean
  position?: number
}

// ── habits (the repeating spine of a day) ──────────────────────────────────
//
// A habit is A RULE THAT INSERTS ENTRIES, not a parallel subsystem. Opening a
// day gives it one ordinary `day_plan` row per active habit scheduled on that
// weekday (kind="habit", source="habit"), and from there the row behaves like
// any other: it is ticked through `patchDayEntry`, dropped through the same
// call, and ordered by the same key.
//
// Nothing here reaches the wire. There is no VTODO for a habit, no RRULE is
// written for one, and the gated `completions` table is not involved — VTODO
// recurrence is deliberately still closed (docs/recurrence-findings.md) and a
// habit is not a way in through the side door. Like `day_plan` itself, this is
// app-only state that the collections shared with Tasks.org, jtx Board and
// Thunderbird never learn about.

export interface Habit {
  id: string
  title: string
  /** '' is EVERY DAY, spelled as the absence of a restriction rather than as
   *  all seven names, so "every day" has exactly one representation. Otherwise
   *  a comma list drawn from `HABIT_DAYS`. Always in mon..sun order coming
   *  back: the server re-orders on write, so "fri,mon" and "mon,fri" cannot
   *  return as two strings that compare unequal and make a client think a
   *  schedule changed when it did not. */
  days: string
  /** Set while the habit is paused. Pausing hides it from days opened FROM NOW
   *  ON; every occurrence it has already put on a day stays exactly as it was,
   *  because those are rows in the day plan and the rule cannot reach them. */
  paused_at: string | null
  position: number | null
  created_at: string
}

/** The seven day names a habit's `days` is written in, in the order the server
 *  canonicalises to.
 *
 *  ORDER AND SPELLING ONLY — deliberately NOT a name→weekday-number table.
 *  Which days a habit runs on is decided server-side, off the day key's own
 *  characters (`service.habit_runs_on`), and a second name↔number mapping on
 *  this side is exactly how "wed" comes to mean Wednesday on one path and
 *  Thursday on the other, silently and for one weekday only. Nothing in the
 *  frontend may turn one of these strings into an index. */
export const HABIT_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

/** Everything POST /habits accepts. `days` defaults to '' (every day) and
 *  `position` to the end of the list. */
export interface CreateHabitBody {
  title: string
  days?: string
  position?: number
}

/** Everything PATCH /habits/{id} accepts. Every field is optional and an
 *  omitted one is left alone — `paused: false` is a real value (resuming), so
 *  it cannot be spelled by omission. Same shape, same reason, as
 *  `PatchDayEntryBody`. */
export interface PatchHabitBody {
  title?: string
  days?: string
  paused?: boolean
  position?: number
}

// One application connected through the MCP connector. Identified by its
// rotation family rather than by any token value — the grant is the thing the
// owner recognises, and no secret needs to leave the server to name it.
export interface McpConnection {
  family_id: string
  client_id: string
  client_name: string | null
  scope: string
  resource: string
  granted_at: number      // UNIX seconds
  refreshed_at: number
  expires_at: number
}

// Account-synced UI preferences (stored server-side, not per-browser).
export interface Settings {
  theme?: 'light' | 'dark'
  appearance?: Appearance          // custom theme overrides (see appearance.ts)
  dashboard?: DashboardModule[]    // Home tab module arrangement (see dashboard.ts)
  tab_order?: Tab[]                // top-nav order, sanitized on read (see tabs.ts)
  start_tab?: TabStart             // which tab the app opens on; 'last' remembers
  last_tab?: Tab                   // where the user left off; only written while start_tab is 'last'
  tasks_view?: TasksViewMode
  sidebar_collapsed?: boolean
  hidden_calendars?: string[]      // calendar ids hidden in the calendar view
  archived_calendars?: string[]    // calendar ids archived (hidden + listed in settings, restorable)
  hidden_lists?: string[]          // task-list ids hidden from the combined "All lists" view
  task_groups?: TaskGroup[]        // named, collapsible groupings of task lists
  collapsed_groups?: string[]      // ids of task groups currently collapsed in the sidebar
  // `taskKey`s (`list\0uid`) of tasks whose subtask trees are folded away.
  // Bare uids written by earlier versions are still honoured on read — see
  // TasksView's tolerate-both note — and retire as the user toggles them.
  collapsed_tasks?: string[]
  session_ttl_s?: number | null    // how long a login lasts; null defers to the deployment
  show_completed_tasks?: boolean   // show completed/cancelled tasks inline in the main view (default hidden)
  time_format?: TimeFormat         // 12- or 24-hour clock across the app (see time.ts); default '12h'
  calendar_task_lists?: string[]   // task-list ids DRAWN on the calendar — an allowlist, empty by default
  calendar_show_done_tasks?: boolean  // keep completed tasks on the calendar (default hidden)
  // Whether the month grid fits the pane ('fixed': six equal week rows, a busy
  // day collapsing into "+N more") or grows to its busiest day and scrolls
  // ('dynamic', the default and what the grid did before this was settable).
  calendar_fit?: CalendarFit
  // The IANA zone this account authors times in. The app writes non-all-day
  // events as floating local wall time, which names no instant on its own, so
  // the booking busy-set has to be told which clock they were written on —
  // without this it assumed the *link's* zone and read every one of the owner's
  // own events at the wrong instant. '' clears it.
  home_timezone?: string
}

// Creates carry a client-generated id that becomes the CalDAV resource slug,
// so a replayed request (retry after a lost response, transport resend) lands
// on the same resource instead of duplicating it. Hex only — it is an href.
// Exported so optimistic UIs can mint the id up front and key the pending row
// by it — a client_id passed in the create body wins over the generated one.
export const clientId = () => crypto.randomUUID().replace(/-/g, '')

/** The UID the server will give a resource created with this client_id.
 *
 * Deterministic by contract — `engine.create_task` builds `f"{slug}@tasksd"`
 * from the slug we send — and knowing it up front is what lets an optimistic
 * stand-in carry its *final* identity from the very first paint. It has to:
 * a subtask added to a task whose create is still in flight sends the parent's
 * rendered uid as its RELATED-TO, and that value is written to the VTODO
 * verbatim. While the stand-in wore the bare client_id, that pointer named a
 * UID which would never exist, so the subtask was orphaned in CalDAV — it came
 * back from the server as its own top-level task, and no reload fixed it.
 *
 * `test_api.py::test_created_uid_is_derived_from_client_id` pins the format
 * from the other side, so the two can't drift apart silently. */
export const UID_SUFFIX = '@tasksd'
export const uidFor = (cid: string) => `${cid}${UID_SUFFIX}`

/** A FastAPI `detail` as something a person can read.
 *
 * It is a string for the errors this app raises itself, but a LIST for every
 * pydantic validation failure — the app's own RequestValidationError handler
 * answers `{"detail": [{type, loc, msg}, ...]}`. That went into `new Error(...)`
 * unchecked, so the constructor stringified the array and the user was shown
 * the literal "[object Object]": the login card renders `(ex as Error).message`
 * verbatim, and the settings toast interpolates it. `loc` starts with the body
 * location ("body"), which means nothing to a reader, so it is dropped. */
function detailText(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        if (typeof e === 'string') return e
        const item = e as { loc?: unknown[]; msg?: unknown }
        const where = Array.isArray(item?.loc) ? item.loc.slice(1).join('.') : ''
        const what = typeof item?.msg === 'string' ? item.msg : ''
        return where && what ? `${where}: ${what}` : what || where
      })
      .filter(Boolean)
      .join('; ')
  }
  return ''
}

async function j<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: 'same-origin',
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const data = await res.json()
      msg = detailText(data?.detail) || msg
    } catch {
      /* ignore */
    }
    // The server's own words carry through a 401 too. Throwing a fixed
    // 'unauthenticated' before reading the body meant the login form rendered
    // that internal token at the user instead of the endpoint's "invalid
    // credentials".
    if (res.status === 401) throw new AuthError(msg)
    throw new HttpError(res.status, msg)
  }
  if (res.status === 204) return null as T
  return res.json() as Promise<T>
}

export const api = {
  // auth
  me: () => j<{ authenticated: boolean; user: string }>('GET', '/api/me'),
  login: (username: string, password: string) =>
    j<{ authenticated: boolean; user: string }>('POST', '/api/login', { username, password }),
  logout: () => j<unknown>('POST', '/api/logout'),

  // tasks
  lists: () => j<List[]>('GET', '/api/lists'),
  createList: (name: string, color?: string | null) => j<List>('POST', '/api/lists', { name, color }),
  updateList: (id: string, body: { name?: string; color?: string | null }) =>
    j<List>('PATCH', `/api/lists/${id}`, body),
  deleteList: (id: string) => j<null>('DELETE', `/api/lists/${id}`),
  reorderLists: (ids: string[]) => j<unknown>('POST', '/api/lists/reorder', { ids }),
  // Every task the client holds, in the order it wants them — not just the one
  // that moved, and not just the visible lists. See order.ts and the endpoint's
  // own docstring: the pane is always the merged view, so positions have to be
  // comparable across lists, and a hidden list left out would come back with
  // stale positions interleaved through the new ones.
  reorderTasks: (items: Array<{ list: string; uid: string }>) =>
    j<unknown>('POST', '/api/tasks/reorder', { items }),
  tasks: (listId: string, includeDone = true) =>
    j<Task[]>('GET', `/api/lists/${listId}/tasks?include_done=${includeDone}`),
  createTask: (listId: string, body: Record<string, unknown>) =>
    j<Task>('POST', `/api/lists/${listId}/tasks`, { client_id: clientId(), ...body }),
  patchTask: (listId: string, uid: string, body: Record<string, unknown>) =>
    j<Task>('PATCH', `/api/lists/${listId}/tasks/${encodeURIComponent(uid)}`, body),
  complete: (listId: string, uid: string, done = true) =>
    j<Task>('POST', `/api/lists/${listId}/tasks/${encodeURIComponent(uid)}/complete?done=${done}`),
  cancel: (listId: string, uid: string) =>
    j<Task>('POST', `/api/lists/${listId}/tasks/${encodeURIComponent(uid)}/cancel`),
  deleteTask: (listId: string, uid: string) =>
    j<null>('DELETE', `/api/lists/${listId}/tasks/${encodeURIComponent(uid)}`),

  // the day plan (the Today tab)
  //
  // `openDay` is the ONLY call that can create a plan, and `day` below is a
  // pure read that never does. The split is the contract, not a convention: a
  // GET that quietly opened days would fill the record with plans the owner
  // never made — a client prefetching a week would open six days it never
  // showed anyone, each frozen at whatever happened to be due at prefetch time
  // — and the `planned` flag would stop meaning what it says.
  openDay: (day: string) => j<DayPlan>('POST', `/api/day/${day}/open`),
  day: (day: string) => j<DayPlan>('GET', `/api/day/${day}`),
  // Planned days in [from, to), `to` EXCLUSIVE and the span bounded to 190 days
  // server-side (a wider one answers 422). Days never opened are simply absent,
  // so an empty array means "nothing planned in there".
  days: (from: string, to: string) =>
    j<DayPlan[]>('GET', `/api/day?from=${from}&to=${to}`),
  addDayEntry: (day: string, body: CreateDayEntryBody) =>
    j<DayEntry>('POST', `/api/day/${day}/entries`, body),
  patchDayEntry: (day: string, entryId: string, body: PatchDayEntryBody) =>
    j<DayEntry>('PATCH', `/api/day/${day}/entries/${encodeURIComponent(entryId)}`, body),

  // habits (the rules that put entries on a day)
  //
  // These four manage DEFINITIONS. Nothing here reads or writes a day: the
  // occurrences are day-plan rows, reached through the calls above, and the
  // only moment the two meet is when opening a day mints the rows a rule is
  // owed. Keeping them apart is what makes "there is no second ledger" true
  // rather than aspirational.
  //
  // `habits` lists PAUSED habits too — this is the list the habits sheet edits,
  // not the subset today happens to schedule.
  habits: () => j<Habit[]>('GET', '/api/habits'),
  createHabit: (body: CreateHabitBody) => j<Habit>('POST', '/api/habits', body),
  patchHabit: (id: string, body: PatchHabitBody) =>
    j<Habit>('PATCH', `/api/habits/${encodeURIComponent(id)}`, body),
  // The DEFINITION only, which is the whole of what a habit is. Occurrences
  // already on a day are ordinary rows and survive it — they keep their copied
  // title and a `habit_id` that now points at nothing, so a past day still says
  // what the owner planned.
  deleteHabit: (id: string) => j<null>('DELETE', `/api/habits/${encodeURIComponent(id)}`),

  // calendars / events
  calendars: () => j<List[]>('GET', '/api/calendars'),
  createCalendar: (name: string, color?: string | null) =>
    j<List>('POST', '/api/calendars', { name, color }),
  updateCalendar: (id: string, body: { name?: string; color?: string | null }) =>
    j<List>('PATCH', `/api/calendars/${id}`, body),
  deleteCalendar: (id: string) => j<null>('DELETE', `/api/calendars/${id}`),
  reorderCalendars: (ids: string[]) => j<unknown>('POST', '/api/calendars/reorder', { ids }),
  events: (calId: string, start: string, end: string) =>
    j<CalEvent[]>('GET', `/api/calendars/${calId}/events?start=${start}&end=${end}`),
  createEvent: (calId: string, body: Record<string, unknown>) =>
    j<CalEvent>('POST', `/api/calendars/${calId}/events`, { client_id: clientId(), ...body }),
  patchEvent: (calId: string, uid: string, body: Record<string, unknown>) =>
    j<CalEvent>('PATCH', `/api/calendars/${calId}/events/${encodeURIComponent(uid)}`, body),
  moveEvent: (calId: string, uid: string, toCalId: string) =>
    j<CalEvent>('POST', `/api/calendars/${calId}/events/${encodeURIComponent(uid)}/move`,
      { calendar: toCalId }),
  deleteEvent: (calId: string, uid: string,
    opts?: { recurrence_id?: string | null; scope?: EventScope }) => {
    const p = new URLSearchParams()
    if (opts?.scope) p.set('scope', opts.scope)
    if (opts?.recurrence_id) p.set('recurrence_id', opts.recurrence_id)
    const qs = p.toString()
    return j<null>('DELETE',
      `/api/calendars/${calId}/events/${encodeURIComponent(uid)}${qs ? `?${qs}` : ''}`)
  },

  // client scheduling (owner side)
  schedulingLinks: () => j<BookingLink[]>('GET', '/api/scheduling/links'),
  createSchedulingLink: (body: BookingLinkInput) =>
    j<BookingLink>('POST', '/api/scheduling/links', body),
  patchSchedulingLink: (token: string, body: Partial<BookingLinkInput>) =>
    j<BookingLink>('PATCH', `/api/scheduling/links/${encodeURIComponent(token)}`, body),
  deleteSchedulingLink: (token: string) =>
    j<null>('DELETE', `/api/scheduling/links/${encodeURIComponent(token)}`),
  schedulingBookings: (token?: string) =>
    j<Booking[]>('GET',
      `/api/scheduling/bookings${token ? `?link=${encodeURIComponent(token)}` : ''}`),

  // client scheduling (public booking page — no session needed)
  publicBookingInfo: (token: string) =>
    j<PublicBookingInfo>('GET', `/api/public/booking/${encodeURIComponent(token)}`),
  // `client_id` is the idempotency key the server replays on. The caller owns
  // it and must keep it stable across a retry of the SAME booking — a fresh one
  // per call turns a lost response into a second event on the owner's calendar.
  // The default is a last resort for a caller with nothing to retry.
  publicBook: (
    token: string,
    body: { start: string; name: string; email: string; notes?: string; client_id?: string },
  ) =>
    j<PublicBookingResult>('POST',
      `/api/public/booking/${encodeURIComponent(token)}/book`, { client_id: clientId(), ...body }),

  // settings (account-synced UI preferences)
  getSettings: () => j<Settings>('GET', '/api/settings'),
  putSettings: (patch: Settings) => j<Settings>('PUT', '/api/settings', patch),

  // connected applications (MCP connector grants). Cookie-gated like the rest
  // of /api — this is the owner managing their own grants, not a client.
  mcpConnections: () => j<McpConnection[]>('GET', '/api/mcp/connections')
    .then((r) => (r as unknown as { connections: McpConnection[] }).connections ?? []),
  mcpDisconnect: (familyId: string) =>
    j<null>('DELETE', `/api/mcp/connections/${encodeURIComponent(familyId)}`),

  // misc
  tags: () => j<string[]>('GET', '/api/tags'),
  search: (q: string) => j<Task[]>('GET', `/api/search?q=${encodeURIComponent(q)}`),
}

// Server-Sent Events: fires the callback whenever the server reports a change.
//
// EventSource only retries by itself when an ESTABLISHED stream drops. If the
// response is anything but a 200 text/event-stream — a 401 once the session TTL
// lapses, a 502 while the server is restarting — the spec has it *fail* the
// connection: readyState goes CLOSED and it never tries again. Nothing else in
// the SPA polls, so that silently froze live updates for the life of the page.
// Reconnect on a capped, jittered backoff instead, and refetch on the way back
// up: events published while we were disconnected are gone, so the reconnect
// itself has to stand in for them.
const _SSE_MAX_BACKOFF_MS = 30_000
// Consecutive hard failures before the loop asks whether the session is alive.
const _SSE_PROBE_AFTER = 3

/**
 * @param onExpire called once the session is established to be GONE, so the app
 *   can route to the login card the way every other 401 does.
 *
 *   EventSource exposes no status, so a 401 is indistinguishable from a 502 and
 *   nothing in this path could ever tell them apart: a tab whose session lapsed
 *   over a weekend kept showing Friday's data — no staleness chrome, no login
 *   card — while firing an unauthenticated GET every 30 s for the life of the
 *   page. After `PROBE_AFTER` consecutive hard failures the loop asks over HTTP.
 *
 *   Only an AuthError stops it. A server that is down is not a session that is
 *   gone, and signing a live session out on one 502 from the tunnel would be a
 *   worse bug than the one this fixes.
 */
export function subscribe(
  onChange: (type: string) => void, onExpire?: () => void,
): () => void {
  let es: EventSource | null = null
  let retry: ReturnType<typeof setTimeout> | undefined
  let attempts = 0
  let missed = false        // disconnected at least once since the last open
  let stopped = false
  let hardFails = 0
  let probing = false

  const open = () => {
    if (stopped) return
    es = new EventSource('/api/events')
    es.onopen = () => {
      attempts = 0
      hardFails = 0             // a stream that opened proves the session
      if (missed) {
        missed = false
        onChange('reconnect')   // resync whatever changed while we were away
      }
    }
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        // The type goes to the caller: not every published event is a data
        // change, and treating them alike made a UI-preference write refetch
        // every list and task in every open tab.
        if (data.type && data.type !== 'hello') onChange(String(data.type))
      } catch {
        /* ignore keepalives */
      }
    }
    es.onerror = () => {
      missed = true
      // Still CONNECTING means the browser is handling the retry itself.
      if (es && es.readyState !== EventSource.CLOSED) return
      es?.close()
      es = null
      if (stopped) return
      // Three, not one: one hard failure is an ordinary blip (a restart, a
      // tunnel hiccup) and probing on it would put an HTTP request on a path
      // that is meant to be quiet — and would fire an unmocked `fetch` inside
      // api.test.ts, which drives exactly one failure.
      if (++hardFails >= _SSE_PROBE_AFTER && !probing) {
        // Counted back down, not left over the threshold. Leaving it there made
        // every subsequent reconnect probe again, so against a server that is
        // merely down — or any proxy that buffers /api/events into oblivion —
        // the tab became a permanent /api/me poller for the life of the page.
        // That is the traffic this was meant to remove, doubled.
        hardFails = 0
        probing = true
        void api.me()
          .catch((e) => {
            // `stopped` re-checked: the caller may have unsubscribed while this
            // was in flight, and firing `onExpire` then bounces a session that
            // has since been re-established back to the login card.
            if (e instanceof AuthError && !stopped) {
              stopped = true
              clearTimeout(retry)
              es?.close()
              es = null
              onExpire?.()
            }
          })
          .finally(() => { probing = false })
      }
      if (stopped) return
      const backoff = Math.min(_SSE_MAX_BACKOFF_MS, 1000 * 2 ** attempts)
      attempts++
      retry = setTimeout(open, backoff * (0.5 + Math.random() / 2))
    }
  }

  open()
  return () => {
    stopped = true
    clearTimeout(retry)
    es?.close()
  }
}
