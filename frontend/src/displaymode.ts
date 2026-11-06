// Display mode: this device, signed in, used as a screen for the day.
//
// Not the same thing as a paired display (Settings → Displays), and the two are
// kept apart on purpose. A paired display reaches the calendar through a token
// in its URL with no session, which is why it is read-only by design: anyone
// holding that URL can see it, and letting the URL write as well would let
// anyone holding it change the calendar. Display mode is the ordinary app,
// signed in, with the app's own frame taken away — so a tablet propped on a
// counter or hung on a wall can check off a task or drag an event with a
// finger, through the same writes, the same undo and the same sync as
// everywhere else.
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

import { isTab, type Tab } from './tabs'

export const DISPLAY_MODE_KEY = 'smylte-display-mode'

/** The views display mode offers, in the order its control bar lists them.
 *  Scheduling is left out: it is a page for managing booking links, and
 *  nothing about it is worth leaving on a screen. */
export const DISPLAY_TABS: readonly Tab[] = ['today', 'calendar', 'home', 'tasks']

export function isDisplayTab(v: unknown): v is Tab {
  return isTab(v) && DISPLAY_TABS.includes(v)
}

/** Which view this device shows in display mode, or null when it is not in
 *  display mode. A stored value that names no display view reads as off,
 *  rather than as a display of something it cannot show. */
export function readDisplayMode(): Tab | null {
  try {
    const v = localStorage.getItem(DISPLAY_MODE_KEY)
    return isDisplayTab(v) ? v : null
  } catch {
    return null
  }
}

/** Store the view, or clear display mode with null. */
export function writeDisplayMode(tab: Tab | null): void {
  try {
    if (tab === null) localStorage.removeItem(DISPLAY_MODE_KEY)
    else localStorage.setItem(DISPLAY_MODE_KEY, tab)
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
