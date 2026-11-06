// Display mode: this device, signed in, used as a screen for the day.
//
// It draws the desk unit's faces — the month, habits + today, now + next —
// the same components the page at /display/<token> draws, so an iPad on the
// counter looks like the panel on the desk. What it adds is touch: a tap ticks
// a row off, a tap on what you are on finishes it, and an event can be dragged
// to another day. That is why it is signed in rather than paired. A paired
// display reaches the calendar through a token in its URL with no session, and
// is read-only by design: anyone holding that URL can see it, and letting the
// URL write as well would let anyone holding it change the calendar. Here the
// writes go through the session like any other.
//
// The choice is PER DEVICE, in localStorage, and never in the account's
// settings: the iPad in the kitchen is a display and the laptop is not, and a
// setting that followed the account would turn every device it signs in on
// into one. It is also what makes a tablet come back as a display after a
// reload, a restart or a launch from the home screen, with nobody there to
// pick it again.
//
// React-free, like tabs.ts and session.ts, so what it stores can be tested
// without a render.

import type { DisplayMode } from './api'

export const DISPLAY_MODE_KEY = 'smylte-display-mode'

/** The faces display mode offers, in the order its control bar lists them —
 *  the order Settings → Displays cycles a paired display's mode in. */
export const DISPLAY_MODES: readonly DisplayMode[] = ['calendar', 'habits', 'now']

const LEGACY_DAY_VIEWS = ['today', 'home', 'tasks']

export function isDisplayMode(v: unknown): v is DisplayMode {
  return typeof v === 'string' && (DISPLAY_MODES as readonly string[]).includes(v)
}

/** Which face this device shows in display mode, or null when it is not in
 *  display mode. A stored value that names no face reads as off, rather than
 *  as a display of something it cannot show. */
export function readDisplayMode(): DisplayMode | null {
  try {
    const v = localStorage.getItem(DISPLAY_MODE_KEY)
    if (isDisplayMode(v)) return v
    // The first display mode drew the app's views and stored a tab. A tablet
    // left on one of those is still a display: the views about the day map to
    // the day's face, and the Calendar tab was already stored as 'calendar'.
    return v !== null && LEGACY_DAY_VIEWS.includes(v) ? 'habits' : null
  } catch {
    return null
  }
}

/** Store the face, or clear display mode with null. */
export function writeDisplayMode(mode: DisplayMode | null): void {
  try {
    if (mode === null) localStorage.removeItem(DISPLAY_MODE_KEY)
    else localStorage.setItem(DISPLAY_MODE_KEY, mode)
  } catch {
    // Private mode or quota: display mode holds until this page is closed.
  }
}

// The Fullscreen API, with Safari's prefix. iPadOS Safari has the prefixed
// element method and no unprefixed one before 16.4; an iPhone has neither for
// anything but video, and a home-screen web app is already full screen, so the
// control simply is not offered there.
type FsDocument = Document & {
  webkitFullscreenElement?: Element | null
  webkitExitFullscreen?: () => Promise<void> | void
  webkitFullscreenEnabled?: boolean
}
type FsElement = HTMLElement & {
  webkitRequestFullscreen?: () => Promise<void> | void
}

export function canFullscreen(doc: Document = document): boolean {
  const d = doc as FsDocument
  const el = d.documentElement as FsElement
  const enabled = d.fullscreenEnabled ?? d.webkitFullscreenEnabled ?? false
  return enabled && (typeof el.requestFullscreen === 'function'
    || typeof el.webkitRequestFullscreen === 'function')
}

export function isFullscreen(doc: Document = document): boolean {
  const d = doc as FsDocument
  return Boolean(d.fullscreenElement ?? d.webkitFullscreenElement)
}

/** Into or out of full screen. Has to be called from a tap: browsers refuse a
 *  request that no gesture is behind. A refusal is swallowed, because the
 *  control is a convenience and the display works the same without it. */
export async function toggleFullscreen(doc: Document = document): Promise<void> {
  const d = doc as FsDocument
  const el = d.documentElement as FsElement
  try {
    if (isFullscreen(d)) {
      if (typeof d.exitFullscreen === 'function') await d.exitFullscreen()
      else await d.webkitExitFullscreen?.()
    } else if (typeof el.requestFullscreen === 'function') {
      await el.requestFullscreen()
    } else {
      await el.webkitRequestFullscreen?.()
    }
  } catch {
    // Refused (no gesture, a policy): nothing to undo.
  }
}
