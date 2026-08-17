import { AuthError } from './api'

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

export function pad(n: number): string {
  return String(n).padStart(2, '0')
}

export function ymd(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
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
