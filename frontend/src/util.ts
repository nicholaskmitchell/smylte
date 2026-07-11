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

export function fmtDue(iso: string | null, isDate: boolean): string {
  if (!iso) return ''
  const d = parseDate(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined,
    isDate
      ? { month: 'short', day: 'numeric' }
      : { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

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
