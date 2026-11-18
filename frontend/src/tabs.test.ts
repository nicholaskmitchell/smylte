import { describe, expect, it, beforeEach } from 'vitest'
import {
  CAL_VIEW_KEY, DEFAULT_TAB_ORDER, DEFAULT_TAB_START, TABS, TAB_KEY, TAB_LABELS, cacheCalView,
  cacheTab, fromStoredTab, isTab, moveTab, readCachedCalView, readCachedTab,
  readLegacyCachedScheduling, resolveStartTab, sanitizeTabOrder, sanitizeTabStart,
} from './tabs'
import { translate } from './i18n/index'

describe('the shipped strip', () => {
  it('leads with Today', () => {
    expect(DEFAULT_TAB_ORDER[0]).toBe('today')
    // `TAB_LABELS` holds catalogue KEYS now, so what it leads with is checked
    // through the catalogue — which is also what the strip renders.
    expect(translate('en', TAB_LABELS.today)).toBe('Today')
  })

  it('still opens a fresh account on Home', () => {
    // Leading the strip and being the landing page are separate choices —
    // moving the landing page would change where every account that never
    // touched the setting lands, which a strip reorder has no business doing.
    expect(DEFAULT_TAB_START).toBe('home')
    expect(resolveStartTab(DEFAULT_TAB_START, undefined, DEFAULT_TAB_ORDER)).toBe('home')
  })

  it('names every tab exactly once, in both directions', () => {
    // TABS is derived from TAB_LABELS and the order is written out separately,
    // so a tab added to one and forgotten in the other is a real possibility —
    // and `sanitizeTabOrder` would then silently append it to every stored
    // order forever, or drop it from the strip entirely.
    expect([...DEFAULT_TAB_ORDER].sort()).toEqual([...TABS].sort())
    expect(DEFAULT_TAB_ORDER).toHaveLength(new Set(DEFAULT_TAB_ORDER).size)
  })
})

describe('sanitizeTabOrder', () => {
  it('keeps a well-formed order as it stands', () => {
    expect(sanitizeTabOrder(['calendar', 'home', 'tasks', 'today']))
      .toEqual(['calendar', 'home', 'tasks', 'today'])
  })

  it('drops the retired Scheduling tab from a stored order', () => {
    // Scheduling is a view inside Calendar now; an older client or a blob from
    // before the move can still carry the token.
    expect(sanitizeTabOrder(['scheduling', 'tasks'])).toEqual(['tasks', 'today', 'home', 'calendar'])
  })

  it('falls back to the shipped order when nothing is stored', () => {
    expect(sanitizeTabOrder(undefined)).toEqual(DEFAULT_TAB_ORDER)
    expect(sanitizeTabOrder('tasks')).toEqual(DEFAULT_TAB_ORDER)
  })

  it('drops tokens it does not recognise', () => {
    // A tab removed in a later version, or a hand-edited blob.
    expect(sanitizeTabOrder(['tasks', 'gantt', 'home'])).not.toContain('gantt')
  })

  it('drops duplicates, keeping the first placement', () => {
    expect(sanitizeTabOrder(['tasks', 'home', 'tasks']).slice(0, 2)).toEqual(['tasks', 'home'])
  })

  it('appends any tab the stored order forgot', () => {
    // A tab missing from the strip would leave its view unreachable.
    const order = sanitizeTabOrder(['calendar'])
    expect(order[0]).toBe('calendar')
    expect([...order].sort()).toEqual([...DEFAULT_TAB_ORDER].sort())
  })

  it('always returns every tab exactly once', () => {
    for (const input of [[], ['nonsense'], ['home', 'home', 'home'], null]) {
      expect(sanitizeTabOrder(input)).toHaveLength(DEFAULT_TAB_ORDER.length)
    }
  })
})

describe('sanitizeTabStart', () => {
  it('accepts a real tab or "last"', () => {
    expect(sanitizeTabStart('calendar')).toBe('calendar')
    expect(sanitizeTabStart('last')).toBe('last')
  })

  it('falls back to Home for anything else', () => {
    expect(sanitizeTabStart(undefined)).toBe('home')
    expect(sanitizeTabStart('gantt')).toBe('home')
    expect(sanitizeTabStart(3)).toBe('home')
  })

  it('maps the retired Scheduling token to Calendar', () => {
    expect(sanitizeTabStart('scheduling')).toBe('calendar')
  })
})

describe('fromStoredTab', () => {
  it('opens Calendar for the retired Scheduling token', () => {
    expect(fromStoredTab('scheduling')).toBe('calendar')
  })

  it('passes a real tab through and refuses anything else', () => {
    expect(fromStoredTab('tasks')).toBe('tasks')
    expect(fromStoredTab('gantt')).toBeNull()
    expect(fromStoredTab('last')).toBeNull()
    expect(fromStoredTab(undefined)).toBeNull()
  })
})

describe('moveTab', () => {
  it('swaps a tab with its neighbour', () => {
    expect(moveTab(['home', 'tasks', 'calendar', 'today'], 'tasks', -1))
      .toEqual(['tasks', 'home', 'calendar', 'today'])
    expect(moveTab(['home', 'tasks', 'calendar', 'today'], 'tasks', 1))
      .toEqual(['home', 'calendar', 'tasks', 'today'])
  })

  it('does nothing at either end, or for a tab that is not there', () => {
    // Read off the strip rather than named, so this keeps testing the ENDS as
    // tabs are added or reordered instead of testing whichever two tabs used to
    // be at them.
    const order = DEFAULT_TAB_ORDER
    expect(moveTab(order, order[0], -1)).toBe(order)
    expect(moveTab(order, order[order.length - 1], 1)).toBe(order)
    expect(moveTab(['home'], 'tasks', 1)).toEqual(['home'])
  })
})

describe('resolveStartTab', () => {
  it('opens on the chosen tab', () => {
    expect(resolveStartTab('calendar', 'tasks', DEFAULT_TAB_ORDER)).toBe('calendar')
  })

  it('opens on the remembered tab when set to "last"', () => {
    expect(resolveStartTab('last', 'tasks', DEFAULT_TAB_ORDER)).toBe('tasks')
  })

  it('falls back to the strip’s first tab when nothing is remembered', () => {
    expect(resolveStartTab('last', undefined, DEFAULT_TAB_ORDER)).toBe(DEFAULT_TAB_ORDER[0])
    expect(resolveStartTab('last', undefined, ['calendar', 'home', 'tasks', 'today']))
      .toBe('calendar')
  })
})

describe('the boot cache', () => {
  beforeEach(() => localStorage.clear())

  it('round-trips a tab', () => {
    cacheTab('calendar')
    expect(readCachedTab()).toBe('calendar')
  })

  it('reads the retired Scheduling tab as Calendar', () => {
    localStorage.setItem(TAB_KEY, 'scheduling')
    expect(readCachedTab()).toBe('calendar')
  })

  it('ignores a missing or junk value rather than trusting it', () => {
    expect(readCachedTab()).toBeNull()
    localStorage.setItem(TAB_KEY, 'gantt')
    expect(readCachedTab()).toBeNull()
  })
})

describe('the calendar view cache', () => {
  beforeEach(() => localStorage.clear())

  it('round-trips a view', () => {
    cacheCalView('scheduling')
    expect(readCachedCalView()).toBe('scheduling')
    cacheCalView('month')
    expect(readCachedCalView()).toBe('month')
  })

  it('ignores a missing or junk value rather than trusting it', () => {
    expect(readCachedCalView()).toBeNull()
    localStorage.setItem(CAL_VIEW_KEY, 'agenda')
    expect(readCachedCalView()).toBeNull()
  })
})

describe('readLegacyCachedScheduling', () => {
  beforeEach(() => localStorage.clear())

  it('is true only while the tab cache holds the retired Scheduling tab', () => {
    expect(readLegacyCachedScheduling()).toBe(false)
    localStorage.setItem(TAB_KEY, 'calendar')
    expect(readLegacyCachedScheduling()).toBe(false)
    localStorage.setItem(TAB_KEY, 'scheduling')
    expect(readLegacyCachedScheduling()).toBe(true)
  })
})

describe('isTab', () => {
  it('recognises only the real tabs', () => {
    expect(isTab('home')).toBe(true)
    expect(isTab('last')).toBe(false)
    expect(isTab(null)).toBe(false)
  })
})
