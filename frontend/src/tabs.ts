// The top-nav tab strip: which tabs exist, what order they sit in, and which one
// the app opens on. Kept free of React (like dashboard.ts) so the sanitizing —
// the part that has to survive a hand-edited or out-of-date settings blob — can
// be reasoned about and tested on its own.

// `today` and the backend's SettingsPatch ship TOGETHER. The server validates
// `tab_order`, `start_tab` and `last_tab` against Literal unions of its own
// (app.py), so a client that PUTs a token the server has not learned yet gets a
// 422 and the whole settings write is rejected — not just the tab. The backend
// therefore accepts "today" first and this token follows; deploying this half
// against an older server would break every settings write from this tab strip,
// not merely the Today tab.
export type Tab = 'today' | 'home' | 'tasks' | 'calendar' | 'scheduling'

/** Which tab the app opens on: a fixed one, or wherever the user left off. */
export type TabStart = Tab | 'last'

// Catalogue KEYS, not text — see `timeFormatKey` in time.ts for why a
// React-free module hands back an identity. `TABS` is still derived from this,
// so the set of tabs and the set of tab names cannot drift apart.
export const TAB_LABELS: Record<Tab, string> = {
  today: 'tab.today',
  home: 'tab.home',
  tasks: 'tab.tasks',
  calendar: 'tab.calendar',
  scheduling: 'tab.scheduling',
}

export const TABS = Object.keys(TAB_LABELS) as Tab[]

/** The shipped strip. Today leads: it is the surface the day is worked from,
 *  and the one place in the app that holds state of its own. */
export const DEFAULT_TAB_ORDER: Tab[] = ['today', 'home', 'tasks', 'calendar', 'scheduling']

/** …but a fresh account still OPENS on Home, which is what it has always opened
 *  on. Leading the strip and being the landing page are separate choices, and
 *  moving the landing page would change where every existing account that never
 *  touched the setting lands — a strip reorder should not do that. Anyone who
 *  wants Today first on open picks it in Settings, or reorders the strip and
 *  chooses "Last used tab". */
export const DEFAULT_TAB_START: TabStart = 'home'

export function isTab(v: unknown): v is Tab {
  return typeof v === 'string' && (TABS as string[]).includes(v)
}

/** A usable order from whatever the server (or a hand-edit) had stored.
 *
 * Unknown tokens and duplicates drop out, and any tab the blob forgot is
 * appended in shipped order — a tab can never go missing from the strip, which
 * would leave its view unreachable. */
export function sanitizeTabOrder(v: unknown): Tab[] {
  if (!Array.isArray(v)) return [...DEFAULT_TAB_ORDER]
  const out: Tab[] = []
  for (const t of v) if (isTab(t) && !out.includes(t)) out.push(t)
  for (const t of DEFAULT_TAB_ORDER) if (!out.includes(t)) out.push(t)
  return out
}

export function sanitizeTabStart(v: unknown): TabStart {
  return v === 'last' || isTab(v) ? v : DEFAULT_TAB_START
}

/** Move a tab one place along the strip. A no-op at either end. */
export function moveTab(order: Tab[], tab: Tab, dir: -1 | 1): Tab[] {
  const i = order.indexOf(tab)
  const j = i + dir
  if (i < 0 || j < 0 || j >= order.length) return order
  const next = [...order]
  next[i] = next[j]
  next[j] = tab
  return next
}

/** The tab to open on. "Last" with nothing remembered falls back to the strip's
 *  first tab, which is also what a user reordering the strip would expect. */
export function resolveStartTab(start: TabStart, last: Tab | undefined, order: Tab[]): Tab {
  if (start !== 'last') return start
  return last && order.includes(last) ? last : order[0]
}

// ── the boot cache ─────────────────────────────────────────────────────────
// The server is the source of truth; this mirror exists only so the right tab
// paints on first render instead of flashing the default while the settings
// fetch is in flight. Same contract as the theme and appearance caches.

export const TAB_KEY = 'smylte-tab'

export function cacheTab(t: Tab): void {
  try { localStorage.setItem(TAB_KEY, t) } catch { /* private mode / quota */ }
}

export function readCachedTab(): Tab | null {
  try {
    const raw = localStorage.getItem(TAB_KEY)
    return isTab(raw) ? raw : null
  } catch { return null }
}
