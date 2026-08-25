import { useEffect, useState } from 'react'

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
