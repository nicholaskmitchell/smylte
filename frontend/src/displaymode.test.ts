import { describe, expect, it, beforeEach, vi } from 'vitest'
import {
  DISPLAY_MODE_KEY, DISPLAY_TABS, canFullscreen, isDisplayTab, readDisplayMode,
  toggleFullscreen, writeDisplayMode,
} from './displaymode'

beforeEach(() => localStorage.clear())

describe('display mode, per device', () => {
  it('is off until a view is stored', () => {
    expect(readDisplayMode()).toBeNull()
    writeDisplayMode('today')
    expect(readDisplayMode()).toBe('today')
    expect(localStorage.getItem(DISPLAY_MODE_KEY)).toBe('today')
  })

  it('is cleared with null', () => {
    writeDisplayMode('calendar')
    writeDisplayMode(null)
    expect(readDisplayMode()).toBeNull()
    expect(localStorage.getItem(DISPLAY_MODE_KEY)).toBeNull()
  })

  it('reads a value naming no display view as off', () => {
    for (const v of ['scheduling', 'nope', '', '1']) {
      localStorage.setItem(DISPLAY_MODE_KEY, v)
      expect(readDisplayMode()).toBeNull()
    }
  })

  it('offers no view outside the tab strip, and not Scheduling', () => {
    expect(DISPLAY_TABS).not.toContain('scheduling')
    for (const t of DISPLAY_TABS) expect(isDisplayTab(t)).toBe(true)
  })

  it('survives storage that throws', () => {
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    expect(readDisplayMode()).toBeNull()
    expect(() => writeDisplayMode('today')).not.toThrow()
    get.mockRestore(); set.mockRestore()
  })
})

const fakeDoc = (over: Record<string, unknown>, el: Record<string, unknown> = {}) =>
  ({ documentElement: el, ...over }) as unknown as Document

describe('full screen', () => {
  it('is offered with the standard API or Safari\'s prefixed one, and only when enabled', () => {
    expect(canFullscreen(fakeDoc({ fullscreenEnabled: true }, { requestFullscreen: () => {} }))).toBe(true)
    expect(canFullscreen(fakeDoc({ webkitFullscreenEnabled: true }, { webkitRequestFullscreen: () => {} }))).toBe(true)
    // An iPhone: the method exists for video, and the document says no.
    expect(canFullscreen(fakeDoc({ webkitFullscreenEnabled: false }, { webkitRequestFullscreen: () => {} }))).toBe(false)
    expect(canFullscreen(fakeDoc({}, {}))).toBe(false)
  })

  it('enters with the prefixed method when that is all there is, and leaves', async () => {
    const enter = vi.fn()
    const leave = vi.fn()
    await toggleFullscreen(fakeDoc({ webkitFullscreenElement: null }, { webkitRequestFullscreen: enter }))
    expect(enter).toHaveBeenCalledOnce()
    await toggleFullscreen(fakeDoc({ webkitFullscreenElement: {}, webkitExitFullscreen: leave }, {}))
    expect(leave).toHaveBeenCalledOnce()
  })

  it('swallows a refusal', async () => {
    const enter = vi.fn(async () => { throw new Error('no gesture') })
    await expect(toggleFullscreen(fakeDoc({ fullscreenElement: null }, { requestFullscreen: enter })))
      .resolves.toBeUndefined()
  })
})
