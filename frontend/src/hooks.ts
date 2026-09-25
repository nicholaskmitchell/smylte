import { useEffect, useLayoutEffect, useState, type RefObject } from 'react'
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
 * Whether the window is at least `px` wide, following resizes. For the rare
 * layout that has to change its ELEMENTS at a width rather than its styles —
 * a stylesheet can move a block, but not put it in a different column's DOM.
 *
 * `innerWidth` and `resize` rather than `matchMedia`: the unit suite's
 * matchMedia stub treats every listener as a listener to the phone breakpoint
 * (see test/setup.ts), so a second query subscribed through it would be told
 * "matches" whenever a test crossed to the phone, whatever it had asked about.
 * Setting state to the value it already holds is a no-op, so a drag-resize
 * re-renders only on the frame that crosses `px`.
 */
export function useMinWidth(px: number): boolean {
  const [wide, setWide] = useState(() => window.innerWidth >= px)
  useEffect(() => {
    const onResize = () => setWide(window.innerWidth >= px)
    onResize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [px])
  return wide
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

/**
 * Put a segmented control's thumb under its active segment (F5), by measuring
 * the segment rather than by arithmetic.
 *
 * The stylesheet can place the thumb on its own — segment `--i` of `--n`, each
 * `1 / n` of the track — and that is right exactly while the segments are equal.
 * They are equal only while the track has room: squeezed by a busy header (the
 * Tasks pane's 3-Day and Week views between 721px and ~860px, which is iPad
 * portrait), the grid holds the widest label at its min-content and hands the
 * others what is left, and the arithmetic then parks the thumb beside the
 * segment it is meant to be under. So the track gets `--thumb-x` / `--thumb-w`
 * from the active segment's own box, re-measured whenever the track resizes.
 *
 * `useLayoutEffect` so the first paint already has them. Without ResizeObserver
 * (jsdom) it measures once, and the CSS fallback covers anything unmeasured.
 * Pass `shown` when the track is rendered conditionally.
 */
export function useSegmentThumb(
  track: RefObject<HTMLElement | null>, active: number, shown = true,
): void {
  useLayoutEffect(() => {
    const el = track.current
    if (!el) return
    const place = () => {
      const seg = el.children[active] as HTMLElement | undefined
      if (!seg || !seg.offsetWidth) return
      el.style.setProperty('--thumb-x', `${seg.offsetLeft}px`)
      el.style.setProperty('--thumb-w', `${seg.offsetWidth}px`)
    }
    place()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(place)
    ro.observe(el)
    return () => ro.disconnect()
    // `shown` is for a track the caller renders conditionally: the ref is null
    // while it is hidden, and nothing else would re-run this once it appears.
  }, [track, active, shown])
}
