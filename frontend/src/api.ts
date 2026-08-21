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
  href: string
  etag: string
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
  collapsed_tasks?: string[]       // uids of tasks whose subtask trees are folded away
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
