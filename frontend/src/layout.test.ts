import { beforeEach, describe, expect, it } from 'vitest'
import {
  DEFAULT_LAYOUT, LAYOUTS, LAYOUT_KEY, SIDEBAR_COLLAPSED_KEY, cacheLayout,
  cacheSidebarCollapsed, isLayout, layoutKey, nextLayout, readCachedLayout,
  readCachedSidebarCollapsed,
} from './layout'
import { translate } from './i18n/index'

describe('the shipped frames', () => {
  it('opens on the sidebar', () => {
    // An account that never chose has no `layout` key at all, and that absence
    // is the refinement's frame. Classic is kept, not defaulted to.
    expect(DEFAULT_LAYOUT).toBe('sidebar')
  })

  it('knows exactly the two frames the backend accepts', () => {
    // SettingsPatch.layout is Literal["sidebar", "classic"]; a third token here
    // would be a 422 that loses the whole settings write.
    expect([...LAYOUTS].sort()).toEqual(['classic', 'sidebar'])
    for (const l of LAYOUTS) expect(isLayout(l)).toBe(true)
  })

  it('refuses anything else off the wire', () => {
    for (const v of ['', 'tabs', 'Sidebar', null, undefined, 0, {}, ['sidebar']]) {
      expect(isLayout(v)).toBe(false)
    }
  })

  it('cycles between the two', () => {
    expect(nextLayout('sidebar')).toBe('classic')
    expect(nextLayout('classic')).toBe('sidebar')
  })

  it('names each frame in both catalogues', () => {
    // `layoutKey` hands back a key; an entry missing from a catalogue renders
    // as the key itself, which is the thing this pins.
    for (const lang of ['en', 'de'] as const) {
      for (const l of LAYOUTS) {
        const name = translate(lang, layoutKey(l))
        expect(name).not.toBe(layoutKey(l))
        expect(name.length).toBeGreaterThan(0)
      }
    }
    expect(translate('en', layoutKey('sidebar'))).toBe('Sidebar')
    expect(translate('en', layoutKey('classic'))).toBe('Classic')
  })
})

describe('the boot cache', () => {
  beforeEach(() => localStorage.clear())

  it('is empty until something is stored', () => {
    expect(readCachedLayout()).toBeNull()
  })

  it('round-trips both frames', () => {
    cacheLayout('classic')
    expect(readCachedLayout()).toBe('classic')
    cacheLayout('sidebar')
    expect(readCachedLayout()).toBe('sidebar')
  })

  it('ignores a value it did not write', () => {
    // localStorage is writable by anything with script on this origin, and the
    // value decides which tree the shell mounts.
    localStorage.setItem(LAYOUT_KEY, 'masthead')
    expect(readCachedLayout()).toBeNull()
  })
})

describe('the fold\'s boot cache', () => {
  beforeEach(() => localStorage.clear())

  it('is empty until something is stored', () => {
    expect(readCachedSidebarCollapsed()).toBeNull()
  })

  it('round-trips both states', () => {
    cacheSidebarCollapsed(true)
    expect(readCachedSidebarCollapsed()).toBe(true)
    cacheSidebarCollapsed(false)
    expect(readCachedSidebarCollapsed()).toBe(false)
  })

  it('ignores a value it did not write', () => {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, 'true')
    expect(readCachedSidebarCollapsed()).toBeNull()
  })
})
