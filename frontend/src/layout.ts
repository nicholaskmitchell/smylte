// The app's frame: where navigation lives and where the Tasks and Calendar
// collections sit. React-free, like tabs.ts, so the part that has to survive a
// hand-edited settings blob can be tested on its own.
//
// Two frames ship. `sidebar` is the default since the September 2026
// refinement: one paper column down the left holds the wordmark, the views and
// Settings, and the view you are on lends it its collections (Lists on Tasks,
// Calendars on Calendar). `classic` is the frame the app shipped with — a top
// tab strip, each of Tasks and Calendar carrying its own sidebar — kept exactly
// as it was for anyone who prefers it.
//
// This is a separate choice from the Classic DESIGN preset (appearance.ts). A
// preset changes type, shape and colour; this changes where things are. Any of
// the four combinations is a real one.

// The backend's SettingsPatch validates `layout` against a Literal of its own,
// so a token added here has to be accepted there first (see tabs.ts on why the
// order matters: a 422 loses the whole PUT, not just this key).
export type Layout = 'sidebar' | 'classic'

export const LAYOUTS: readonly Layout[] = ['sidebar', 'classic']

/** What an account that never chose gets — the settings blob has no key. */
export const DEFAULT_LAYOUT: Layout = 'sidebar'

export function isLayout(v: unknown): v is Layout {
  return v === 'sidebar' || v === 'classic'
}

/** The settings row cycles, like the clock and the calendar window. */
export function nextLayout(l: Layout): Layout {
  return l === 'sidebar' ? 'classic' : 'sidebar'
}

// Catalogue KEYS, not text — see `timeFormatKey` in time.ts.
export function layoutKey(l: Layout): string {
  return l === 'sidebar' ? 'layout.sidebar' : 'layout.classic'
}

// The boot cache. The frame is structure, not paint: a first frame drawn in
// the wrong one and then swapped for the other moves every control on screen,
// which is worse than the colour flash index.html's pre-paint script exists to
// prevent. So the last known value is kept beside the tab cache and seeds the
// shell's state before `/api/settings` answers.
export const LAYOUT_KEY = 'smylte-layout'

export function cacheLayout(l: Layout): void {
  try { localStorage.setItem(LAYOUT_KEY, l) } catch { /* private mode / quota */ }
}

export function readCachedLayout(): Layout | null {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY)
    return isLayout(raw) ? raw : null
  } catch { return null }
}
