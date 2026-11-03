// main.tsx's routes without a sign-in tell the Android client their first view
// is up as soon as they render; the app's own route leaves it to App, which says
// it when its sign-in check answers (App.ready.test.tsx).
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('./App', () => ({ App: () => null }))
vi.mock('./components/BookingPage', () => ({ BookingPage: () => null }))
vi.mock('./components/DisplayView', () => ({ DisplayView: () => null }))
vi.mock('./components/SharePage', () => ({ SharePage: () => null }))
vi.mock('./desktop', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./desktop')>()),
  startCaptionSync: vi.fn(),
}))

const ready = vi.fn()

async function load(path: string, withBridge = true) {
  vi.resetModules()
  history.replaceState(null, '', path)
  document.body.innerHTML = '<div id="root"></div>'
  if (withBridge) vi.stubGlobal('SmylteAndroid', { hello: () => '{"v":1}', ready })
  await import('./main')
}

afterEach(() => {
  vi.unstubAllGlobals()
  ready.mockClear()
  document.body.innerHTML = ''
  history.replaceState(null, '', '/')
})

describe('main.tsx: the splash signal', () => {
  it.each(['/book/abc', '/display/abc', '/share/abc'])('%s says ready once, as soon as it has rendered', async (path) => {
    await load(path)
    expect(ready).toHaveBeenCalledTimes(1)
  })

  it('the app\'s own route leaves it to App', async () => {
    await load('/')
    expect(ready).not.toHaveBeenCalled()
  })

  it('outside the Android client, a route without a sign-in loads without error', async () => {
    await expect(load('/book/abc', false)).resolves.toBeUndefined()
  })
})
