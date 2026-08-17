import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useIsMobile } from './hooks'

// hooks.ts had no test file at all — the only non-trivial module in src/ that
// did not. It also used to hold `useAllTasks`, whose `loading` flag was never
// cleared on a failed fetch (the Home dashboard's modules rendered permanently
// blank, with no retry and no error). That hook was dead code by the time it
// was audited — HomeView moved to `useTaskData()` in data.tsx, which clears its
// flag in a `.finally` — so it was deleted rather than fixed. What is left is
// `useIsMobile`, and it decides which layout the whole app renders.

/** A matchMedia stub that can actually fire a change, so the listener contract
 *  is testable — the global stub in test/setup.ts is inert by design. */
function stubMatchMedia(initial: boolean) {
  const listeners = new Set<(e: MediaQueryListEvent) => void>()
  const removed: string[] = []
  window.matchMedia = ((query: string) => ({
    matches: initial,
    media: query,
    onchange: null,
    addEventListener: (_type: string, fn: (e: MediaQueryListEvent) => void) => {
      listeners.add(fn)
    },
    removeEventListener: (type: string, fn: (e: MediaQueryListEvent) => void) => {
      removed.push(type)
      listeners.delete(fn)
    },
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia

  return {
    emit: (matches: boolean) =>
      act(() => {
        for (const fn of listeners) fn({ matches } as MediaQueryListEvent)
      }),
    listenerCount: () => listeners.size,
    removed,
  }
}

const desktopStub = () => {
  window.matchMedia = ((query: string) => ({
    matches: false, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

afterEach(() => {
  vi.restoreAllMocks()
  desktopStub()          // leave the shared desktop stub for other suites
})

describe('useIsMobile', () => {
  it('reads the breakpoint on first render', () => {
    stubMatchMedia(true)
    expect(renderHook(() => useIsMobile()).result.current).toBe(true)

    stubMatchMedia(false)
    expect(renderHook(() => useIsMobile()).result.current).toBe(false)
  })

  it('follows a change in the media query', () => {
    // A rotation or a resize crosses the breakpoint without remounting
    // anything, so the layout has to follow the query rather than the mount.
    const mq = stubMatchMedia(false)
    const { result } = renderHook(() => useIsMobile())
    expect(result.current).toBe(false)

    mq.emit(true)
    expect(result.current).toBe(true)

    mq.emit(false)
    expect(result.current).toBe(false)
  })

  it('removes its listener on unmount', () => {
    // Three components subscribe (HomeView, Sidebar, CalendarView) and the tab
    // strip mounts and unmounts them as the user moves around, so a leak here
    // accumulates for the life of the tab.
    const mq = stubMatchMedia(false)
    const { unmount } = renderHook(() => useIsMobile())
    expect(mq.listenerCount()).toBe(1)

    unmount()
    expect(mq.listenerCount()).toBe(0)
    expect(mq.removed).toEqual(['change'])
  })
})
