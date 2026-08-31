// Typed client for the tasksd API. Same-origin: the session cookie rides along
// automatically, so there are no tokens to manage in JS (it's HttpOnly anyway).

// Both shapes are defined next to the code that gives them meaning — the token
// allowlist and the grid math — and re-exported here so the wire contract still
// reads in one place. The backend mirrors them in SettingsPatch.
import type { Appearance } from './appearance'
import type { Language } from './lang'
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
  /** The estimate this task REMEMBERS — sidecar, so Smylte-only and invisible to
   *  Tasks.org, jtx Board and Thunderbird. It is not any day's estimate:
   *  planning the task copies this onto that day's entry, and the entry is what
   *  that day counts. This only decides where the next plan starts. */
  estimated_minutes: number | null
  /** "Notify me this many minutes before" — the task's due time, or the
   *  event's start. Null on almost everything, which is what "nobody asked to
   *  be told about this one" means.
   *
   *  Sidecar, so Smylte-only and invisible to Tasks.org, jtx Board and
   *  Thunderbird — deliberately, not as a shortcut. A VALARM is the
   *  interoperable answer and would be right if Smylte were the only client,
   *  but those three share these collections and would each fire their own
   *  alarm off it, buying interop by notifying the owner three times.
   *
   *  It is the only thing that makes a task deadline notify at all: there is no
   *  blanket "task due soon" rule, on purpose, because a lead set on ONE item is
   *  the owner asking rather than the app guessing. */
  notify_minutes_before: number | null
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
  /** "Notify me N minutes before this is due." App-only, so the server applies
   *  it after the wire create rather than putting it in the VTODO — which is
   *  also why it can be sent here at all: there is no uid to hang a sidecar row
   *  on until the create lands. */
  notify_minutes_before?: number
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
  /** Whether this event consumes the owner's time — iCalendar's TRANSP, which
   *  Apple Calendar and Google Calendar both put in front of the user as
   *  "Busy / Free" and Thunderbird as "Show Time As".
   *
   *  A boolean rather than the property's own two words because the wire has
   *  three states and only two meanings: OPAQUE, TRANSPARENT, and ABSENT — and
   *  RFC 5545 §3.8.2.7 makes absent the same as OPAQUE. The server resolves that
   *  default once (`read.blocks_time`) so no reader here has to.
   *
   *  It is not decoration: `false` takes the event out of the busy set behind
   *  the public booking page, so a slot sitting on it is offered. See
   *  `scheduling.busy_intervals`. */
  busy: boolean
  tags: string[]
  has_rrule: boolean
  /** "Notify me this many minutes before" — the task's due time, or the
   *  event's start. Null on almost everything, which is what "nobody asked to
   *  be told about this one" means.
   *
   *  Sidecar, so Smylte-only and invisible to Tasks.org, jtx Board and
   *  Thunderbird — deliberately, not as a shortcut. A VALARM is the
   *  interoperable answer and would be right if Smylte were the only client,
   *  but those three share these collections and would each fire their own
   *  alarm off it, buying interop by notifying the owner three times.
   *
   *  It is the only thing that makes a task deadline notify at all: there is no
   *  blanket "task due soon" rule, on purpose, because a lead set on ONE item is
   *  the owner asking rather than the app guessing. */
  notify_minutes_before: number | null
  href: string
  etag: string
}

/** One row of the delivery ledger. `silent` on a rule that normally buzzes is
 *  how the owner sees what the daily ceiling swallowed. */
export interface NotificationDelivery {
  trigger: string
  dedupe_key: string
  channel: string
  claimed_at: string
  settled_at: string | null
  ok: number
  silent: number
  error: string | null
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
  /** The day key this entry was deliberately MOVED to, or null.
   *
   *  Distinct from `dropped_at`, and the distinction is the point: "I am doing
   *  this on Thursday" and "I decided against this" are different things for a
   *  day to remember. The row stays on its own day either way — rolling creates
   *  an entry on the target and stamps this one, so the day that planned the
   *  work is still the day that planned it.
   *
   *  A stamped row is skipped by the automatic carry-over, or the owner would
   *  find two of it: one from their decision and one from the safety net. */
  rolled_to: string | null
  // How long this entry is expected to take, on THIS day. Null is "nobody said",
  // which is a real answer: the day's total is over the rows that carry one, so
  // an unestimated row costs the day nothing rather than counting as free.
  //
  // A COPY, never a join. A task remembers its last estimate in the sidecar, a
  // habit remembers one on its rule, and a note is remembered by the carry — but
  // all three only decide what a NEW entry starts at. Once the row exists the
  // row is what its day counts, which is what stops re-estimating something in
  // March from rewriting what January's plan said it would take.
  estimate_minutes: number | null
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
  /** What the owner SAID for this day, or null if they never said anything.
   *  Deliberately separate from `capacity` below: this one answers "did they
   *  look at this day and set a number", which is what tells a day they
   *  actually planned from one that merely inherited a weekday default. */
  capacity_minutes: number | null
  /** What the day's total should be READ AGAINST, resolved server-side through
   *  what was said for the day, the weekday default, the account default, and
   *  then nothing. **Null is a real answer** and every reader has to handle it
   *  rather than falling back to some assumed working day — see
   *  `service._effective_capacity`. */
  capacity: number | null
  /** The planning ritual was finished. */
  committed_at: string | null
  /** The shutdown ritual was finished. */
  shutdown_at: string | null
  /** A sentence or two on how the day went, written at shutdown. */
  reflection: string | null
  entries: DayEntry[]
}

/** Everything PATCH /day/{day} accepts — what the owner SAYS about a day, as
 *  opposed to what is on it. Every field tri-state: an omitted key is "not
 *  asked about", and the falsy values are real (`committed: false` re-opens a
 *  day begun by mistake). Refused entirely on a past day, with one day of
 *  grace, because a capacity is a plan and a shutdown is a boundary. */
export interface PatchDayBody {
  /** Minutes, or **-1 to clear** — the same sentinel and the same reason as
   *  `PatchDayEntryBody.estimate_minutes`: 0 is a real capacity ("not working
   *  today"), so the clear cannot borrow falsiness. */
  capacity_minutes?: number
  committed?: boolean
  shutdown?: boolean
  reflection?: string
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
  /** Minutes, or **-1 to clear**. The sentinel is explicit because an int has no
   *  spare falsy value to borrow: 0 is a legitimate estimate and an omitted key
   *  already means "not asked about". The backend bounds this at [-1, 1440], so
   *  -1 is the only negative that can arrive. */
  estimate_minutes?: number
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
  /** How long one run of this takes. The RULE remembers it and every occurrence
   *  is minted with a copy, exactly as the title is — so a habit is estimated
   *  once rather than every morning, and changing it leaves past days alone. */
  estimate_minutes: number | null
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
  estimate_minutes?: number
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
  /** Minutes, or -1 to clear — the same sentinel and bounds as
   *  `PatchDayEntryBody.estimate_minutes`, so a duration is spelled one way
   *  wherever this app takes one. */
  estimate_minutes?: number
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
  // The language the app is shown in, and the locale it formats dates with
  // (see lang.ts). Account-synced like every other display preference here —
  // what the DEVICE was set up in is a different question from what its owner
  // wants to read an app in.
  language?: Language
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
  /** How many minutes an ordinary day is expected to hold, and the per-weekday
   *  exceptions. Absent means NEVER SAID — a real answer, and the one the whole
   *  capacity feature turns on: an account that has not stated a capacity is
   *  never told it has overcommitted against a number it did not give.
   *
   *  The map is sparse and keyed by the `HABIT_DAYS` names, never by index —
   *  the server's `_WEEKDAYS` is the one place those names meet a weekday
   *  number, and a second mapping here is how "wed" comes to mean two different
   *  days on two paths. See `capacity.ts`. */
  day_capacity_minutes?: number
  day_capacity_by_weekday?: Record<string, number>
  /** Which notification rules are on, as a SPARSE override map: an absent rule
   *  means that rule's own default (all four ship on). Sparse rather than four
   *  booleans because a rule added later would otherwise be governed by
   *  whatever this blob happened to contain before it existed.
   *
   *  The server FILTERS names it does not know rather than 422-ing, so unlike
   *  `tab_order` these two halves can deploy in either order — a client that
   *  knows a rule the server does not loses that one key, not the whole
   *  settings write. See `notifications.ts`. */
  notify_triggers?: Partial<Record<string, boolean>>
  /** The hour the daily digest arrives, HH:MM on a 24-hour clock, in the
   *  account's `home_timezone`. Absent means 07:30. The server REJECTS a
   *  malformed value rather than filtering it — a half-typed time would 422 the
   *  whole PUT — which is why the field commits on blur, not on every keystroke.
   *
   *  With no `home_timezone` set the digest does not fire at all: an hour
   *  resolved against the server clock (UTC in the ordinary deploy) is not the
   *  hour anyone chose, and a rule that is on but never fires is worse than one
   *  that is off. */
  notify_digest_time?: string
  /** How many minutes before a meeting to say something. Absent means 10, and
   *  the server floors it at 3 — the CalDAV poll and the notify tick together
   *  cost most of two minutes, so a shorter lead fires after the meeting has
   *  started, and the rule refuses to send then. */
  notify_event_lead_minutes?: number
  /** The master switch. Absent means OFF — unlike the per-rule map, whose
   *  absent key means "that rule's default", this one has no safe default but
   *  off: it is what stands between a deploy that merely has a bot token in its
   *  environment and one whose owner asked to be messaged. */
  notifications_enabled?: boolean
  /** Where messages go. Not a secret (an integer naming a chat), so it reads
   *  back like any other preference. */
  notify_telegram_chat_id?: string
  /** WRITE-ONLY. Accepted by PUT, never returned by GET — the settings document
   *  is fetched on every page load, so echoing the token would put a working
   *  bot in the DOM, in the network tab, and in any screenshot of either. The
   *  two fields below are what comes back instead. Send '' to clear it and fall
   *  back to the environment. */
  notify_telegram_bot_token?: string
  /** Read-only, server-derived: whether a token is stored at all. */
  notify_telegram_bot_token_set?: boolean
  /** Read-only, server-derived: the PUBLIC half of the token — the bot's own
   *  user id — which names which bot is configured while revealing nothing that
   *  could send as it. '' when no token is stored. */
  notify_telegram_bot_id?: string
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

async function j<T>(method: string, path: string, body?: unknown,
  signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: 'same-origin',
    signal,
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
  /** `signal` so BOOT can time out. A half-open socket — a captive portal, a
   *  tunnel that accepted the connection and went away — never rejects and never
   *  resolves, and this one call decides whether the app renders at all, so
   *  without a deadline the owner gets an indefinitely blank pane rather than
   *  the offline shell. Nothing else needs one; every other call is behind a
   *  screen that is already painted. */
  me: (signal?: AbortSignal) =>
    j<{ authenticated: boolean; user: string }>('GET', '/api/me', undefined, signal),
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
  /** "Notify me N minutes before this is due." Pass -1 to clear it.
   *
   *  Its own call rather than a field on patchTask, because it is not on the
   *  wire: a PATCH would PUT the VTODO back and move its etag, making every
   *  other CalDAV client re-fetch a resource that did not change. */
  setTaskReminder: (listId: string, uid: string, minutes: number) =>
    j<Task>('PUT', `/api/lists/${listId}/tasks/${encodeURIComponent(uid)}/sidecar`,
      { notify_minutes_before: minutes }),
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
  // What the owner says about a day, as opposed to what is on it. A PATCH on
  // the DAY rather than on an entry, because none of it belongs to any row.
  patchDay: (day: string, body: PatchDayBody) =>
    j<DayPlan>('PATCH', `/api/day/${day}`, body),
  // Planned days in [from, to), `to` EXCLUSIVE and the span bounded to 190 days
  // server-side (a wider one answers 422). Days never opened are simply absent,
  // so an empty array means "nothing planned in there".
  days: (from: string, to: string) =>
    j<DayPlan[]>('GET', `/api/day?from=${from}&to=${to}`),
  addDayEntry: (day: string, body: CreateDayEntryBody) =>
    j<DayEntry>('POST', `/api/day/${day}/entries`, body),
  // A POST because it CREATES: a new entry lands on the target day and this one
  // is stamped with where it went. Nothing is moved and nothing is deleted.
  rollDayEntry: (day: string, entryId: string, to: string) =>
    j<DayEntry>('POST',
      `/api/day/${day}/entries/${encodeURIComponent(entryId)}/roll`, { to }),
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
  /** What the bot has actually said, newest first — including anything the
   *  daily ceiling downgraded to silent. */
  recentNotifications: (limit = 50) =>
    j<{ deliveries: NotificationDelivery[]; triggers: string[] }>(
      'GET', `/api/notifications/recent?limit=${limit}`),
  /** Send one message now and report what actually failed. */
  testNotification: () => j<{ sent: boolean; detail: string }>(
    'POST', '/api/notifications/test'),
  patchEvent: (calId: string, uid: string, body: Record<string, unknown>) =>
    j<CalEvent>('PATCH', `/api/calendars/${calId}/events/${encodeURIComponent(uid)}`, body),
  /** "Notify me N minutes before this starts." Pass -1 to clear it.
   *
   *  On the SERIES for a repeating event — the sidecar is keyed on the resource,
   *  so "twenty minutes before my standup" is a statement about the standup, not
   *  about next Tuesday's. There is no scope to pass. */
  setEventReminder: (calId: string, uid: string, minutes: number) =>
    j<CalEvent>('PUT', `/api/calendars/${calId}/events/${encodeURIComponent(uid)}/reminder`,
      { notify_minutes_before: minutes }),
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
