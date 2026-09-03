import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  dockWindow, dragWindow, floatWindow, isFloatWindow, pinWindow, readState, setIcon,
  startCaptionSync,
} from './desktop'

// The load-bearing property of the desktop bridge is what it does when there is
// no desktop: nothing at all, and quietly. Everything under /desktop/ exists
// only on the local server the Windows client runs, so in a browser these are
// 404s against the deployed backend — and a settings section that rendered
// anyway, or a POST fired on every theme toggle, would be a bug users on the web
// would see and desktop users never would.

const respond = (body: unknown, ok = true) =>
  vi.fn().mockResolvedValue({ ok, json: async () => body } as Response)

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('bridge detection', () => {
  it('reads null when the host route is missing, which is the browser case', async () => {
    vi.stubGlobal('fetch', respond({}, false))
    expect(await readState()).toBeNull()
  })

  it('reads null when fetch throws outright', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    expect(await readState()).toBeNull()
  })

  it('returns the host state when the route answers', async () => {
    const state = {
      available: true, choice: 'Auto', resolved: 'Ink', systemUsesLightTheme: true,
      startMenuShortcut: false, captionColour: true,
    }
    vi.stubGlobal('fetch', respond(state))
    expect(await readState()).toEqual(state)
  })
})

describe('caption sync', () => {
  it('makes no further request when there is no host', async () => {
    const fetchMock = respond({}, false)
    vi.stubGlobal('fetch', fetchMock)
    startCaptionSync()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled())
    // Only the probe. Nothing observes, so a later theme change posts nothing.
    document.documentElement.dataset.theme = 'dark'
    await new Promise(r => setTimeout(r, 80))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/desktop/state')
  })
})

describe('setIcon', () => {
  it('posts the choice and the shortcut flag together', async () => {
    const fetchMock = respond({ available: true, choice: 'Mark' })
    vi.stubGlobal('fetch', fetchMock)
    await setIcon('Mark', true)
    const [path, init] = fetchMock.mock.calls[0]
    expect(path).toBe('/desktop/icon')
    expect(JSON.parse((init as RequestInit).body as string))
      .toEqual({ choice: 'Mark', startMenuShortcut: true })
  })
})

describe('the floating window', () => {
  it('posts each verb on the one route, the pin with its flag', async () => {
    const fetchMock = respond({ available: true, floating: true, pinned: false })
    vi.stubGlobal('fetch', fetchMock)
    await floatWindow()
    await dockWindow()
    await dragWindow()
    expect(await pinWindow(false)).toMatchObject({ floating: true, pinned: false })
    const bodies = fetchMock.mock.calls.map(([path, init]) =>
      [path, JSON.parse((init as RequestInit).body as string)])
    expect(bodies).toEqual([
      ['/desktop/window', { action: 'float' }],
      ['/desktop/window', { action: 'dock' }],
      ['/desktop/window', { action: 'drag' }],
      ['/desktop/window', { action: 'pin', pinned: false }],
    ])
  })

  it('answers null from a client that has no such window, like every other route', async () => {
    // An exe older than the feature 404s the route; the page must read that
    // as "not here" rather than as a state to paint.
    vi.stubGlobal('fetch', respond({}, false))
    expect(await floatWindow()).toBeNull()
  })

  it('knows whether this document is the floating one from the query string', () => {
    history.replaceState(null, '', '/focus?float=1')
    expect(isFloatWindow()).toBe(true)
    history.replaceState(null, '', '/focus')
    expect(isFloatWindow()).toBe(false)
    history.replaceState(null, '', '/')
  })
})
