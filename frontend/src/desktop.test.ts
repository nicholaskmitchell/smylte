import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  dockWindow, dragWindow, floatWindow, isFloatWindow, pinWindow, platformOf, readState,
  setIcon, startCaptionSync, type DesktopState,
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

  it('carries the optional keys through untouched when the host sends them', async () => {
    // Nothing here filters or defaults on the way in — the readers do that,
    // each for its own key — so a host that grows a key reaches them all.
    const state = {
      available: true, choice: 'Mark', resolved: 'Mark', systemUsesLightTheme: false,
      startMenuShortcut: true, captionColour: true,
      floating: true, pinned: false, nativeDrag: false,
      platform: 'linux', canPin: false,
    }
    vi.stubGlobal('fetch', respond(state))
    expect(await readState()).toEqual(state)
  })
})

describe('which host', () => {
  const state = (over: Partial<DesktopState> = {}) => ({
    available: true, choice: 'Auto', resolved: 'Ink', systemUsesLightTheme: true,
    startMenuShortcut: false, captionColour: true, ...over,
  } as DesktopState)

  it('reads an absent platform as Windows', () => {
    // The compatibility rule, asserted rather than described. The Windows
    // client has never sent this key and never will; if absence meant anything
    // else, every installed exe would start showing Linux wording the moment a
    // new web build reached it — and the web build updates on every launch.
    expect(platformOf(state())).toBe('windows')
  })

  it('reads the platform the host states', () => {
    expect(platformOf(state({ platform: 'linux' }))).toBe('linux')
    expect(platformOf(state({ platform: 'windows' }))).toBe('windows')
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

  // ── the desktop arm ──────────────────────────────────────────────────────
  //
  // Everything above pins what happens when there is NO host, which was the
  // whole of this describe block. The arm that runs on the desktop — the
  // observer, the coalescing, and the value that actually crosses the bridge —
  // had no test at all, and it is the only page-side code that touches `--bg`
  // before handing it to a host that paints a window frame with it.
  //
  // **One test, deliberately.** `startCaptionSync` installs a MutationObserver
  // on <html> and has no teardown — it is a one-shot for the life of the page,
  // which is right for the app and means a second call in a second test leaves
  // the first observer attached and posting. Split across four tests the counts
  // below drift with the order they run in. So the desktop arm is walked
  // through once, in order, with the assertions labelled.

  it('walks the caption from first paint through a theme change and a preset burst', async () => {
    const appearance = (mock: ReturnType<typeof respond>) =>
      mock.mock.calls.filter(([path]) => path === '/desktop/appearance')
    const background = (call: unknown[]) =>
      JSON.parse((call[1] as RequestInit).body as string).background

    const fetchMock = respond({ available: true })
    vi.stubGlobal('fetch', fetchMock)

    // 1. No --bg yet: before first paint, or in a harness. An empty string is
    //    not a colour, and posting one would make the host reset a frame it had
    //    already painted correctly.
    startCaptionSync()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await new Promise(r => setTimeout(r, 80))
    expect(appearance(fetchMock)).toHaveLength(0)

    // 2. The theme lands. The observer watches <html>'s attributes because --bg
    //    moves for four different reasons that share no call site — the toggle,
    //    a preset, a custom theme's tokens, and the pre-paint script in
    //    index.html — and all four end in an attribute change here.
    document.documentElement.style.setProperty('--bg', '#0C0C10')
    await vi.waitFor(() => expect(appearance(fetchMock)).toHaveLength(1))
    expect(background(appearance(fetchMock)[0])).toBe('#0C0C10')

    // 3. Hex crosses the bridge exactly as the theme authored it. The host
    //    parses `#RGB` and `#RRGGBB` and is strict about it — six hex digits,
    //    no whitespace inside — so dropping the hash or padding the value would
    //    hand the frame back to the system with no error anywhere.
    document.documentElement.style.setProperty('--bg', '#abc')
    await vi.waitFor(() => expect(appearance(fetchMock)).toHaveLength(2))
    expect(background(appearance(fetchMock)[1])).toBe('#abc')

    // 4. Coalescing. Writes SPACED OUT — a colour the user is dragging, or a
    //    preset applied across ticks — must still cost one POST, not one per
    //    step. Deliberately not a synchronous loop: a MutationObserver batches
    //    everything in one microtask checkpoint into a single callback anyway,
    //    so twenty writes in a `for` would produce one push with the debounce
    //    removed as well, and the assertion would be vacuous. Ten milliseconds
    //    apart is inside the fifty-millisecond window and in separate ticks,
    //    which is the case only the debounce handles.
    const before = appearance(fetchMock).length
    for (const step of ['#111111', '#222222', '#FBFAF7']) {
      document.documentElement.style.setProperty('--bg', step)
      await new Promise(r => setTimeout(r, 10))
    }
    await new Promise(r => setTimeout(r, 120))

    expect(appearance(fetchMock).length - before).toBe(1)
    // And the one it sends is where the drag LANDED, not where it started.
    const posts = appearance(fetchMock)
    expect(background(posts[posts.length - 1])).toBe('#FBFAF7')

    document.documentElement.style.removeProperty('--bg')
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
