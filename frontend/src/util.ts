import { AuthError } from './api'
import type { Task } from './api'

// App registers a notifier so guarded API failures surface as a toast instead
// of dying silently in the console.
let notifyError: ((msg: string) => void) | null = null
export function setErrorNotifier(fn: ((msg: string) => void) | null) {
  notifyError = fn
}

// Wrap API calls so a session expiry logs the user out and other errors surface
// without crashing the view.
export function makeGuard(onExpire: () => void) {
  return async function guard<T>(fn: () => Promise<T>): Promise<T | undefined> {
    try {
      return await fn()
    } catch (e) {
      if (e instanceof AuthError) onExpire()
      else {
        console.error(e)
        notifyError?.(e instanceof Error ? e.message : String(e))
      }
      return undefined
    }
  }
}

// Date-only strings ("2026-07-11") parse as UTC midnight per the JS spec, which
// puts them on the previous day for any viewer west of UTC — parse them as
// local instead. Datetime strings go through Date as-is (naive ones are local).
export function parseDate(iso: string): Date {
  if (!iso.includes('T')) {
    const [y, m, d] = iso.split('-').map(Number)
    return new Date(y, (m || 1) - 1, d || 1)
  }
  return new Date(iso)
}

// The local calendar day an ISO date/datetime falls on, as YYYY-MM-DD.
export function dayKey(iso: string): string {
  const d = parseDate(iso)
  return isNaN(d.getTime()) ? iso.slice(0, 10) : ymd(d)
}

// Value for a datetime-local input, in the viewer's timezone.
export function toLocalInput(iso: string): string {
  const d = parseDate(iso)
  if (isNaN(d.getTime())) return iso.slice(0, 16)
  return `${ymd(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// Does this ISO datetime name an instant (carries a UTC offset or Z), rather
// than a floating local wall time? A property another CalDAV client anchored to
// a zone reads back with an offset; one the app wrote itself is floating.
export function hasZone(iso: string | null | undefined): boolean {
  if (!iso || !iso.includes('T')) return false
  const time = iso.slice(iso.indexOf('T') + 1)
  return time.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(time)
}

// A local date+time (as the pickers hold them) sent back as the instant it
// names, so the server can re-express it in the property's original zone. A
// naive string would arrive floating and strip the TZID a foreign client set.
export function instantFromLocal(date: string, time: string): string {
  const d = new Date(`${date}T${time}`)
  return isNaN(d.getTime()) ? `${date}T${time}` : d.toISOString()
}

// `fmtDue` and the rest of the clock formatting live in time.ts — they need the
// 12/24-hour preference, and this module is imported by things that have no
// business knowing about it.

export function isOverdue(iso: string | null, isDate = false): boolean {
  if (!iso) return false
  const d = parseDate(iso)
  if (isNaN(d.getTime())) return false
  // An all-day item isn't overdue until its whole day has passed.
  if (isDate || !iso.includes('T')) {
    const endOfDay = addDays(d, 1)
    return endOfDay.getTime() <= Date.now()
  }
  return d.getTime() < Date.now()
}

/**
 * How many whole days late a deadline is, measured against the day key `day`,
 * or null when it is not late at all.
 *
 * TWO RULES ON PURPOSE, and they are not redundant. Whether something is late
 * comes from `isOverdue` — the instant rule, which gives an all-day deadline
 * its whole day — so nothing can be counted here that the rest of the app does
 * not already call overdue. How late is a DAY-KEY subtraction, which is
 * coarser, and that is the right currency: "more than three days past due" is
 * not a claim about seventy-two hours, and a threshold that flipped at some
 * hour of the morning would be a rule nobody could predict.
 *
 * `day` is a parameter rather than today, for the reason every other date
 * function here takes one: the reading has to be decidable without the wall
 * clock, and the Today tab already steps its own day back and forth.
 */
export function daysPastDue(
  iso: string | null, isDate: boolean, day: string,
): number | null {
  if (!isOverdue(iso, isDate)) return null
  const due = dayKey(iso!)
  if (!due || due >= day) return null
  // Through Date rather than by subtracting the strings, so a month or year
  // boundary is arithmetic rather than a special case. Both parsed as LOCAL
  // midnight — the `${key}T00:00` spelling this file buckets by everywhere —
  // and rounded, because a day containing a DST transition is 23 or 25 hours
  // long and a floor would report it as one day fewer twice a year.
  const ms = new Date(`${day}T00:00`).getTime() - new Date(`${due}T00:00`).getTime()
  if (!Number.isFinite(ms)) return null
  return Math.round(ms / 86_400_000)
}

/** The four fields a slip is read off. A `Pick` rather than the whole `Task`
 *  so a test fixture — and the optimistic row `data.tsx` paints before the
 *  server answers — can be the shape these take without being a task. */
export type Slippable = Pick<Task,
  'due' | 'due_is_date' | 'original_due' | 'original_due_is_date'>

/**
 * The deadline this task was moved off AFTER IT HAD ALREADY PASSED, as
 * `(iso, is_date)` — or null when there is no such deadline.
 *
 * `original_due` is written by the server and only by the server
 * (`service.py::_deadline_being_missed`), once, from something that actually
 * happened: it is the FIRST deadline missed, never the previous one, and
 * nothing but an explicit "forget it" clears it. So this is a fact about the
 * past that the app reads, never a judgement it makes.
 *
 * SUPPRESSED WHEN IT EQUALS `due`, which is what a deadline moved and then
 * moved back looks like. Compared as the strings the server sent, so a
 * remembered all-day deadline and a timed one on the same day stay the
 * different answers they are — the same rule the chip rendered before this was
 * a function, kept in one place now that four surfaces ask it.
 */
export function slippedFrom(t: Slippable): [string, boolean] | null {
  if (!t.original_due || t.original_due === t.due) return null
  return [t.original_due, t.original_due_is_date]
}

/**
 * How many whole days ago the first missed deadline was, or null.
 *
 * Null covers two different cases and callers must not collapse them into a
 * zero. A task that has not slipped has no such deadline at all; a task whose
 * 09:00 deadline was moved at 10:00 HAS one, but it is on the day being
 * measured against, and "0d late" is a worse thing to print than nothing. Ask
 * `slippedFrom` whether there is a deadline to name and this for how old it is.
 */
export function daysSlipped(t: Slippable, day: string): number | null {
  const from = slippedFrom(t)
  return from ? daysPastDue(from[0], from[1], day) : null
}

/**
 * How many whole days late, measured against the deadline this task is
 * ANSWERABLE TO — the first one it missed when it has been moved off one, and
 * the one it carries otherwise. Null when it is not late at all.
 *
 * This is `daysPastDue` for everything that has never slipped, and the whole
 * difference for everything that has. DUE holds one value, so rescheduling
 * overwrites how late a task was with how late it is — and the Today tab's
 * triage strip is built entirely around rescheduling, which made pressing
 * "Due today" on something three weeks late an answer that ERASED the question.
 * Four days later it came back reading "1 day late", and pressing it again each
 * morning meant it never came back at all: the threshold counted from a date
 * the press had just reset. Measured from the promise instead, the count only
 * grows, because `original_due` is never overwritten.
 *
 * IT STILL GATES ON THE CURRENT DEADLINE, and that is what keeps the press
 * meaningful rather than making the strip argumentative. A task rescheduled
 * into the future — or onto today — is NOT LATE, whatever it once was, so this
 * answers null for it and the triage group does not reclaim it on the same
 * paint as the answer. Tomorrow it is late again, and what the threshold sees
 * then is the age of the promise (22) rather than of the reprieve (1).
 */
export function daysLate(t: Slippable, day: string): number | null {
  const now = daysPastDue(t.due, t.due_is_date, day)
  if (now == null) return null
  return Math.max(now, daysSlipped(t, day) ?? 0)
}

export function pad(n: number): string {
  return String(n).padStart(2, '0')
}

export function ymd(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Half a second past midnight, and the reason it is not midnight exactly.
 *
 *  A timeout armed for the millisecond of the changeover can fire a hair EARLY:
 *  a callback that reads the wall clock at 23:59:59.999 sees yesterday, sets the
 *  day it already holds, and arms the next timer for a midnight 24 hours away —
 *  so the surface sits on the wrong day for a whole day. Half a second is
 *  invisible and removes the whole class. */
export const MIDNIGHT_SLACK_MS = 500

/**
 * How long until the next local midnight, with `MIDNIGHT_SLACK_MS` on the end.
 *
 * Built from the local calendar FIELDS rather than by adding 86_400_000ms,
 * which is an hour wrong on both changeover days in any zone that observes DST
 * — and this repo's suite runs in America/New_York precisely so that class of
 * bug can fail a test.
 *
 * Shared by every surface that has to notice a rollover, which is now two: the
 * Today tab and the dashboard's plan module. Only the arithmetic is shared —
 * what each does when the timer fires is its own business, and the Today tab's
 * is genuinely different because it also has to decide whether to move a picker
 * somebody may be reading last Tuesday through.
 *
 * Clamped at zero: a system clock that jumps backwards mid-render must not arm
 * a negative timeout, which fires immediately and spins.
 */
export function msUntilMidnight(now: Date = new Date()): number {
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1).getTime()
  return Math.max(0, next - now.getTime()) + MIDNIGHT_SLACK_MS
}

export function addDays(d: Date, n: number): Date {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}

/** Value equality for a row/slot value, which may be a string or a string[].
 *
 * Shared because `===` on the array-valued slots is a REFERENCE comparison, and
 * two of the places that ask "did this change?" were silently always answering
 * yes (or always no) for tags because of it. One definition, so a third caller
 * cannot drift from the other two.
 *
 * A string on one side and an array on the other is not equal — the callers
 * only ever compare a slot against another value for the same slot, so that
 * pairing means something has already gone wrong.
 */
export function sameValue(a: string | string[], b: string | string[]): boolean {
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b)
      && a.length === b.length && a.every((x, i) => x === b[i])
  }
  return a === b
}

/** A collection color, or null if it is not one.
 *
 * `List.color` comes off the wire: it is served from whatever another CalDAV
 * client wrote into the collection's `ical:calendar-color`, an Apple dead
 * property that anything sharing the collection can PROPPATCH to arbitrary
 * text. It is then written straight into element styles — as a `background`,
 * and as the `--ev-c` custom property that app.css resolves into
 * `background: var(--ev-c, var(--accent))`. So `url(https://evil.example/x.png)`
 * on a rendered 3-5px dot makes the browser fetch it: a beacon that fires
 * whenever the owner opens the Calendar tab or the Home mini-calendar. There is
 * no Content-Security-Policy anywhere in this app to stop it.
 *
 * The same shape the backend now enforces at ingest (dav/xml.py `clean_color`)
 * and has always enforced on write, so a legitimate color is unaffected. This
 * is the belt to that braces: it holds for rows cached before the backend fix,
 * and for any future path that forgets.
 */
const HEX_COLOR = /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/
export const cssColor = (c: string | null | undefined): string | null =>
  (c && HEX_COLOR.test(c.trim()) ? c.trim() : null)

/**
 * `'rtl'` when `s` reads right to left, else undefined — meant for the `dir`
 * attribute on an element holding one user-supplied title.
 *
 * Which end of a title an ellipsis eats depends on the direction of the box it
 * overflows, not on the text: an Arabic summary inside a left-to-right chip
 * gets clipped at its *beginning*, which is the half you need to recognise it.
 * Marking the chip rtl puts the ellipsis on the left and the clock prefix on
 * the reading edge, so what is lost is the tail — the same bargain a Latin
 * title gets.
 *
 * The first strong character decides, which is what `dir="auto"` would do if it
 * could be aimed at the summary alone; on the chip itself it would read the
 * "AM" of the clock prefix instead and answer ltr for everything.
 */
const RTL_FIRST = /^\P{L}*[\p{Script=Arabic}\p{Script=Hebrew}\p{Script=Syriac}\p{Script=Thaana}\p{Script=Nko}]/u
export const textDir = (s: string | null | undefined): 'rtl' | undefined =>
  (s && RTL_FIRST.test(s) ? 'rtl' : undefined)
