import { AuthError } from './api'

// Wrap API calls so a session expiry logs the user out and other errors surface
// without crashing the view.
export function makeGuard(onExpire: () => void) {
  return async function guard<T>(fn: () => Promise<T>): Promise<T | undefined> {
    try {
      return await fn()
    } catch (e) {
      if (e instanceof AuthError) onExpire()
      else console.error(e)
      return undefined
    }
  }
}

export function fmtDue(iso: string | null, isDate: boolean): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined,
    isDate
      ? { month: 'short', day: 'numeric' }
      : { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function isOverdue(iso: string | null): boolean {
  if (!iso) return false
  const d = new Date(iso)
  return !isNaN(d.getTime()) && d.getTime() < Date.now()
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
