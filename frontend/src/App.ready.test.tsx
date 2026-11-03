// Inside the Android client, the app tells the host when its first view is up,
// so the platform's splash screen ends on a real screen: once, the first time
// the sign-in check answers. The file is separate because the host is module
// state per test file, and App.test.tsx must stay a browser.
import { StrictMode } from 'react'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api, AuthError, HttpError } from './api'
import { startAndroidHost } from './android'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

vi.mock('./desktop', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./desktop')>()
  return {
    ...mod,
    readState: vi.fn(async () => null),
    floatWindow: vi.fn(async () => null), dockWindow: vi.fn(async () => null),
    pinWindow: vi.fn(async () => null), dragWindow: vi.fn(async () => null),
  }
})

const ready = vi.fn()
let announced: unknown

beforeAll(() => {
  const hello = vi.fn((_caps: string) => '{"v":1,"clock24":false}')
  vi.stubGlobal('SmylteAndroid', { hello, ready })
  startAndroidHost()
  announced = hello.mock.calls[0]?.[0]
})
afterAll(() => {
  vi.unstubAllGlobals()
})

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '/')
  localStorage.clear()
  m.me.mockResolvedValue({ authenticated: true, user: 'alice' })
  // The account has its own clock, so nothing is written at startup.
  m.getSettings.mockResolvedValue({ time_format: '12h' })
  m.putSettings.mockResolvedValue({})
  m.login.mockResolvedValue({ authenticated: true, user: 'alice' })
  m.logout.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
})

const deferred = <T,>() => {
  let resolve: (v: T) => void = () => {}
  let reject: (e: unknown) => void = () => {}
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })

describe('<App> in the Android client: the splash screen', () => {
  it('announces that it will say when it is ready', () => {
    expect(announced).toBe('back,haptics,ready,save')
  })

  it('says nothing while the sign-in check is in flight, then ready once it answers signed in', async () => {
    const me = deferred<{ authenticated: boolean; user: string }>()
    m.me.mockReturnValue(me.promise)
    render(<App />)
    // The booting shell paints while the check is out.
    await screen.findByRole('button', { name: 'Tasks' })
    await flush()
    expect(ready).not.toHaveBeenCalled()
    await act(async () => { me.resolve({ authenticated: true, user: 'alice' }) })
    await waitFor(() => expect(ready).toHaveBeenCalledTimes(1))
    expect(ready.mock.calls).toEqual([[]])
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await flush()
    expect(ready).toHaveBeenCalledTimes(1)
  })

  it('says ready once the sign-in card shows, and not again on signing in', async () => {
    m.me.mockRejectedValue(new AuthError('unauthenticated'))
    render(<App />)
    await screen.findByRole('button', { name: 'Sign in' })
    expect(ready).toHaveBeenCalledTimes(1)
    await userEvent.type(screen.getByLabelText('Username'), 'alice')
    await userEvent.type(screen.getByLabelText('Password'), 'secret')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByRole('button', { name: 'Tasks' })
    await flush()
    expect(ready).toHaveBeenCalledTimes(1)
  })

  it('says ready once offline, and not again when a retry signs in', async () => {
    m.me.mockRejectedValueOnce(new HttpError(502, 'bad gateway'))
    render(<App />)
    const bar = await screen.findByRole('status')
    expect(bar.textContent).toMatch(/Can’t reach the server/)
    expect(ready).toHaveBeenCalledTimes(1)
    await userEvent.click(within(bar).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull())
    await flush()
    expect(ready).toHaveBeenCalledTimes(1)
  })

  it('says it once under StrictMode, as main.tsx renders the app', async () => {
    render(<StrictMode><App /></StrictMode>)
    await waitFor(() => expect(ready).toHaveBeenCalledTimes(1))
    await flush()
    expect(ready).toHaveBeenCalledTimes(1)
  })

  it('says ready without waiting for a frame', async () => {
    const original = globalThis.requestAnimationFrame
    const frozen = vi.fn(() => 0)
    vi.stubGlobal('requestAnimationFrame', frozen)
    try {
      // Guards against a vacuous pass: the stub is the one the page sees.
      expect(window.requestAnimationFrame).toBe(frozen)
      render(<App />)
      await waitFor(() => expect(ready).toHaveBeenCalledTimes(1))
    } finally {
      vi.stubGlobal('requestAnimationFrame', original)
    }
  })
})
