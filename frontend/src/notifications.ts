// Which notifications exist, and the sanitizing that has to survive a
// hand-edited or out-of-date settings blob. React-free, like tabs.ts and
// dashboard.ts, so the part that matters can be reasoned about and tested on
// its own.
//
// The backend is the authority on this list (backend/tasksd/notify/rules.py
// exports the same four names, and app.py FILTERS unknown ones out of a
// settings PUT rather than 422-ing it). That filtering is what makes deploying
// these two halves apart safe in BOTH directions, unlike `tab_order`: a client
// that knows a rule the server does not loses that one key instead of the whole
// settings write. This copy exists so the UI can label and order the rules; it
// is not a second source of truth about which ones the server will honour.

export type Trigger =
  // On by default.
  | 'daily_digest'
  | 'event_starting'
  | 'item_reminder'
  | 'booking_created'
  | 'sync_stalled'
  // Off by default. Each of these was argued against in the backend's
  // notify/rules.py before it was written, and the argument is what the default
  // encodes — but a default is a starting position, not a verdict, and someone
  // who wants a 07:30 nudge knows their own working habits better than the app
  // does. The UI's job is to make the choice informed rather than blind, which
  // is why every one of them ships with the case against it as its hint.
  | 'task_due_soon'
  | 'task_overdue'
  | 'day_unplanned'
  | 'capacity_overcommitted'
  | 'day_not_shut_down'
  | 'habits_outstanding'
  | 'booking_link_broken'
  | 'sync_recovered'

// Catalogue KEYS, not text — see `timeFormatKey` in time.ts for why a
// React-free module hands back an identity. Order is the order the rows render
// in, and it is deliberate: the two that BUZZ come first, because whether a
// notification interrupts you is the thing worth knowing before you read what
// it is about.
export const TRIGGER_LABELS: Record<Trigger, string> = {
  daily_digest: 'notif.trigger.dailyDigest',
  event_starting: 'notif.trigger.eventStarting',
  item_reminder: 'notif.trigger.itemReminder',
  booking_created: 'notif.trigger.bookingCreated',
  sync_stalled: 'notif.trigger.syncStalled',
  task_due_soon: 'notif.trigger.taskDueSoon',
  task_overdue: 'notif.trigger.taskOverdue',
  day_unplanned: 'notif.trigger.dayUnplanned',
  capacity_overcommitted: 'notif.trigger.overcommitted',
  day_not_shut_down: 'notif.trigger.notShutDown',
  habits_outstanding: 'notif.trigger.habitsLeft',
  booking_link_broken: 'notif.trigger.linkBroken',
  sync_recovered: 'notif.trigger.syncRecovered',
}

export const TRIGGER_HINTS: Record<Trigger, string> = {
  daily_digest: 'notif.trigger.dailyDigest.hint',
  event_starting: 'notif.trigger.eventStarting.hint',
  item_reminder: 'notif.trigger.itemReminder.hint',
  booking_created: 'notif.trigger.bookingCreated.hint',
  sync_stalled: 'notif.trigger.syncStalled.hint',
  task_due_soon: 'notif.trigger.taskDueSoon.hint',
  task_overdue: 'notif.trigger.taskOverdue.hint',
  day_unplanned: 'notif.trigger.dayUnplanned.hint',
  capacity_overcommitted: 'notif.trigger.overcommitted.hint',
  day_not_shut_down: 'notif.trigger.notShutDown.hint',
  habits_outstanding: 'notif.trigger.habitsLeft.hint',
  booking_link_broken: 'notif.trigger.linkBroken.hint',
  sync_recovered: 'notif.trigger.syncRecovered.hint',
}

// Whether a rule buzzes or arrives silently is fixed in the backend, not
// configured — a booking and a sync failure can never wake anyone, which is why
// there are no quiet hours to set. The UI only REPORTS it, so someone deciding
// whether to leave a rule on knows what leaving it on costs them.
export const TRIGGER_IS_LOUD: Record<Trigger, boolean> = {
  daily_digest: true,
  event_starting: true,
  item_reminder: true,
  booking_created: false,
  sync_stalled: false,
  task_due_soon: true,
  task_overdue: true,
  day_unplanned: true,
  capacity_overcommitted: true,
  day_not_shut_down: true,
  habits_outstanding: true,
  booking_link_broken: false,
  sync_recovered: false,
}

export const TRIGGERS = Object.keys(TRIGGER_LABELS) as Trigger[]

// Every rule ships on. The override map is SPARSE — an absent key means the
// rule's own default — so this is what an untouched account gets, and what a
// toggle is compared against before it is written.
export const TRIGGER_DEFAULTS: Record<Trigger, boolean> = {
  daily_digest: true,
  event_starting: true,
  item_reminder: true,
  booking_created: true,
  sync_stalled: true,
  task_due_soon: false,
  task_overdue: false,
  day_unplanned: false,
  capacity_overcommitted: false,
  day_not_shut_down: false,
  habits_outstanding: false,
  booking_link_broken: false,
  sync_recovered: false,
}

/** The rules that fire at an hour the owner set rather than off a moment in
 *  their data. The section groups by this because the two behave differently:
 *  a wall-clock rule's timing is a setting on this page, and an event-driven
 *  one's is whatever the owner already put in their calendar. */
export const TRIGGER_IS_EVENING: Record<Trigger, boolean> = {
  daily_digest: false, event_starting: false, item_reminder: false,
  booking_created: false, sync_stalled: false, task_due_soon: false,
  task_overdue: false, day_unplanned: false, capacity_overcommitted: false,
  day_not_shut_down: true, habits_outstanding: true,
  booking_link_broken: false, sync_recovered: false,
}

/** Which rules ship on. The section renders the two tiers separately, because
 *  "these four are what the app thinks you need" and "these eight are available
 *  if you disagree" are different statements and a flat list makes neither. */
export const DEFAULT_ON = TRIGGERS.filter((t) => TRIGGER_DEFAULTS[t])
export const DEFAULT_OFF = TRIGGERS.filter((t) => !TRIGGER_DEFAULTS[t])

export function isTrigger(v: unknown): v is Trigger {
  return typeof v === 'string' && (TRIGGERS as string[]).includes(v)
}

/** Read a stored override map, dropping anything this build does not know. */
export function sanitizeTriggers(v: unknown): Partial<Record<Trigger, boolean>> {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return {}
  const out: Partial<Record<Trigger, boolean>> = {}
  for (const [key, value] of Object.entries(v as Record<string, unknown>)) {
    if (isTrigger(key) && typeof value === 'boolean') out[key] = value
  }
  return out
}

/** Is this rule on, given the sparse override map? */
export function triggerEnabled(
  overrides: Partial<Record<Trigger, boolean>>, t: Trigger,
): boolean {
  const v = overrides[t]
  return typeof v === 'boolean' ? v : TRIGGER_DEFAULTS[t]
}

// HH:MM on a 24-hour clock — the shape `<input type="time">` hands back and the
// only shape the server's `notify_digest_time` validator accepts. It REJECTS
// rather than filters, unlike the trigger map, so a bad value here would 422
// the whole settings PUT: this guard is what keeps a half-typed time from ever
// being sent.
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/

export function isDigestTime(v: unknown): v is string {
  return typeof v === 'string' && HHMM.test(v)
}

export const DEFAULT_DIGEST_TIME = '07:30'
export const DEFAULT_EVENING_TIME = '21:00'
export const DEFAULT_TASK_LEAD_MINUTES = 30
export const DEFAULT_EVENT_LEAD_MINUTES = 10

// Floored at 3 by the backend, and the floor is a property of the pipeline
// rather than a taste: the CalDAV poll is 30s and the notify tick is another
// 60s, so a shorter lead would routinely fire after the meeting had started —
// and the rule refuses to send then, so the alert would simply never arrive.
export const MIN_EVENT_LEAD_MINUTES = 3
export const MAX_EVENT_LEAD_MINUTES = 120

export function sanitizeTaskLead(v: unknown): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) return DEFAULT_TASK_LEAD_MINUTES
  const n = Math.round(v)
  if (n < MIN_EVENT_LEAD_MINUTES) return MIN_EVENT_LEAD_MINUTES
  // A day. Past that it is not a warning about a deadline, it is a second one.
  if (n > 1440) return 1440
  return n
}

export function sanitizeEventLead(v: unknown): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) return DEFAULT_EVENT_LEAD_MINUTES
  const n = Math.round(v)
  if (n < MIN_EVENT_LEAD_MINUTES) return MIN_EVENT_LEAD_MINUTES
  if (n > MAX_EVENT_LEAD_MINUTES) return MAX_EVENT_LEAD_MINUTES
  return n
}
