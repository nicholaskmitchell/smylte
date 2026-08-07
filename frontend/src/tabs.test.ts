import { describe, expect, it, beforeEach } from 'vitest'
import {
  DEFAULT_TAB_ORDER, TAB_KEY, cacheTab, isTab, moveTab, readCachedTab,
  resolveStartTab, sanitizeTabOrder, sanitizeTabStart,
} from './tabs'

describe('sanitizeTabOrder', () => {
  it('keeps a well-formed order as it stands', () => {
    expect(sanitizeTabOrder(['calendar', 'home', 'scheduling', 'tasks']))
      .toEqual(['calendar', 'home', 'scheduling', 'tasks'])
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
    const order = sanitizeTabOrder(['scheduling'])
    expect(order[0]).toBe('scheduling')
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
})

describe('moveTab', () => {
  it('swaps a tab with its neighbour', () => {
    expect(moveTab(['home', 'tasks', 'calendar', 'scheduling'], 'tasks', -1))
      .toEqual(['tasks', 'home', 'calendar', 'scheduling'])
    expect(moveTab(['home', 'tasks', 'calendar', 'scheduling'], 'tasks', 1))
      .toEqual(['home', 'calendar', 'tasks', 'scheduling'])
  })

  it('does nothing at either end, or for a tab that is not there', () => {
    const order = DEFAULT_TAB_ORDER
    expect(moveTab(order, 'home', -1)).toBe(order)
    expect(moveTab(order, 'scheduling', 1)).toBe(order)
    expect(moveTab(['home'], 'tasks', 1)).toEqual(['home'])
  })
})

describe('resolveStartTab', () => {
  it('opens on the chosen tab', () => {
    expect(resolveStartTab('calendar', 'tasks', DEFAULT_TAB_ORDER)).toBe('calendar')
  })

  it('opens on the remembered tab when set to "last"', () => {
    expect(resolveStartTab('last', 'scheduling', DEFAULT_TAB_ORDER)).toBe('scheduling')
  })

  it('falls back to the strip’s first tab when nothing is remembered', () => {
    expect(resolveStartTab('last', undefined, DEFAULT_TAB_ORDER)).toBe('home')
    expect(resolveStartTab('last', undefined, ['calendar', 'home', 'tasks', 'scheduling']))
      .toBe('calendar')
  })
})

describe('the boot cache', () => {
  beforeEach(() => localStorage.clear())

  it('round-trips a tab', () => {
    cacheTab('scheduling')
    expect(readCachedTab()).toBe('scheduling')
  })

  it('ignores a missing or junk value rather than trusting it', () => {
    expect(readCachedTab()).toBeNull()
    localStorage.setItem(TAB_KEY, 'gantt')
    expect(readCachedTab()).toBeNull()
  })
})

describe('isTab', () => {
  it('recognises only the real tabs', () => {
    expect(isTab('home')).toBe(true)
    expect(isTab('last')).toBe(false)
    expect(isTab(null)).toBe(false)
  })
})
