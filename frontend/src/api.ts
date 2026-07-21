// Typed client for the tasksd API. Same-origin: the session cookie rides along
// automatically, so there are no tokens to manage in JS (it's HttpOnly anyway).

export class AuthError extends Error {}

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
  tags: string[]
  parent: string | null
  children: string[]
  child_count: number
  completed_child_count: number
  derived_percent: number | null
  pinned: boolean
  href: string
  etag: string
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

// Account-synced UI preferences (stored server-side, not per-browser).
export interface Settings {
  theme?: 'light' | 'dark'
  tasks_view?: TasksViewMode
  sidebar_collapsed?: boolean
  hidden_calendars?: string[]      // calendar ids hidden in the calendar view
  archived_calendars?: string[]    // calendar ids archived (hidden + listed in settings, restorable)
  hidden_lists?: string[]          // task-list ids hidden from the combined "All lists" view
  task_groups?: TaskGroup[]        // named, collapsible groupings of task lists
  collapsed_groups?: string[]      // ids of task groups currently collapsed in the sidebar
  show_completed_tasks?: boolean   // show completed/cancelled tasks inline in the main view (default hidden)
}

// Creates carry a client-generated id that becomes the CalDAV resource slug,
// so a replayed request (retry after a lost response, transport resend) lands
// on the same resource instead of duplicating it. Hex only — it is an href.
// Exported so optimistic UIs can mint the id up front and key the pending row
// by it — a client_id passed in the create body wins over the generated one.
export const clientId = () => crypto.randomUUID().replace(/-/g, '')

async function j<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: 'same-origin',
  })
  if (res.status === 401) throw new AuthError('unauthenticated')
  if (!res.ok) {
    let msg = res.statusText
    try {
      const data = await res.json()
      msg = data.detail || msg
    } catch {
      /* ignore */
    }
    throw new Error(msg)
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
  createList: (name: string, color?: string) => j<List>('POST', '/api/lists', { name, color }),
  updateList: (id: string, body: { name?: string; color?: string | null }) =>
    j<List>('PATCH', `/api/lists/${id}`, body),
  deleteList: (id: string) => j<null>('DELETE', `/api/lists/${id}`),
  reorderLists: (ids: string[]) => j<unknown>('POST', '/api/lists/reorder', { ids }),
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
  createCalendar: (name: string, color?: string) =>
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
  publicBook: (token: string, body: { start: string; name: string; email: string; notes?: string }) =>
    j<PublicBookingResult>('POST',
      `/api/public/booking/${encodeURIComponent(token)}/book`, { client_id: clientId(), ...body }),

  // settings (account-synced UI preferences)
  getSettings: () => j<Settings>('GET', '/api/settings'),
  putSettings: (patch: Settings) => j<Settings>('PUT', '/api/settings', patch),

  // misc
  tags: () => j<string[]>('GET', '/api/tags'),
  search: (q: string) => j<Task[]>('GET', `/api/search?q=${encodeURIComponent(q)}`),
}

// Server-Sent Events: fires the callback whenever the server reports a change.
export function subscribe(onChange: () => void): () => void {
  const es = new EventSource('/api/events')
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data.type && data.type !== 'hello') onChange()
    } catch {
      /* ignore keepalives */
    }
  }
  return () => es.close()
}
