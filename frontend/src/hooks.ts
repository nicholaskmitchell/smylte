import { useEffect, useState } from 'react'
import { msUntilMidnight, ymd } from './util'

// Keep in sync with the mobile breakpoint in styles/app.css.
const MOBILE_QUERY = '(max-width: 720px)'

export function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(() => window.matchMedia(MOBILE_QUERY).matches)
  useEffect(() => {
    const mq = window.matchMedia(MOBILE_QUERY)
    const onChange = (e: MediaQueryListEvent) => setMobile(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return mobile
}

/**
 * Close on Escape, from wherever focus happens to be.
 *
 * Bound to `window`, the widest of the three spellings this REPLACED — DayPopover
 * and SchedulingView used `window`, AppearancePanel `document` — and the one that
 * subsumes them: a keydown on the document bubbles to the window. All three call
 * this hook now, and it holds the only keydown registration left in the app. A listener on the modal element does NOT subsume either — it only
 * fires while focus is inside the dialog, and with no focus trap that is exactly
 * the state a keyboard user needs the escape hatch from.
 *
 * `globalThis.KeyboardEvent` because React re-exports a `KeyboardEvent` type of
 * its own, and a component importing that one shadows the DOM's.
 */
export function useEscape(onEscape: () => void): void {
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape') onEscape() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onEscape])
}

/**
 * Today's day key, kept honest across midnight.
 *
 * For any surface that says "today" and is left open. A dashboard sitting on a
 * second monitor overnight would otherwise go on showing yesterday's plan under
 * a heading that says today — which is the one mistake a day-scoped surface
 * cannot make, because every row under it is a claim about a day.
 *
 * `TodayView` has a timer of its own and is deliberately NOT rewired onto this.
 * It does a second job when the rollover fires — move the day PICKER, but only
 * when the picker is parked on today, so somebody reviewing last Tuesday at
 * 23:59 does not have the page jump out from under them — and folding that into
 * a hook every caller pays for would be the wrong shape. What the two share is
 * `msUntilMidnight`, which is the part that is subtle.
 */
export function useToday(): string {
  const [today, setToday] = useState(() => ymd(new Date()))
  // Re-armed by its own answer rather than by an interval: one timeout per day,
  // and `armed` changing is what schedules the next one.
  const [armed, setArmed] = useState(0)
  useEffect(() => {
    const t = setTimeout(() => {
      // The WALL CLOCK decides, never arithmetic on the key we were holding. A
      // laptop asleep through midnight fires this late — possibly days late, and
      // browsers throttle background timers besides — so reading the clock lands
      // on the day it actually is rather than on the day after the stale one.
      setToday(ymd(new Date()))
      setArmed((n) => n + 1)
    }, msUntilMidnight())
    return () => clearTimeout(t)
  }, [armed])
  return today
}
