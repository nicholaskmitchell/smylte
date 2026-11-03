// In a browser, and in the desktop clients, there is no Android host: App still
// makes its one call when the sign-in check answers, and the call finds nothing
// to tell. The file is separate because the host is module state per test file,
// and here there must be none.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { App } from './App'
import { api, AuthError, HttpError } from './api'
import { isAndroidHost, markReady } from './android'

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

vi.mock('./android', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./android')>()
  return { ...mod, markReady: vi.fn(mod.markReady) }
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

const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })

describe('<App> outside the Android client: the splash signal', () => {
  const outcomes: [string, () => void, () => Promise<HTMLElement>][] = [
    ['signed in', () => {}, async () => {
      const tasks = await screen.findByRole('button', { name: 'Tasks' })
      await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
      return tasks
    }],
    ['the sign-in card', () => m.me.mockRejectedValue(new AuthError('unauthenticated')),
      () => screen.findByRole('button', { name: 'Sign in' })],
    ['offline', () => m.me.mockRejectedValue(new HttpError(502, 'bad gateway')),
      () => screen.findByRole('status')],
  ]

  it.each(outcomes)('%s: one call, and nothing to call', async (_name, arrange, shown) => {
    arrange()
    expect('SmylteAndroid' in window).toBe(false)
    render(<App />)
    const element = await shown()
    await waitFor(() => expect(vi.mocked(markReady)).toHaveBeenCalledTimes(1))
    await flush()
    // An effect that threw would have unmounted the tree.
    expect(document.body.contains(element)).toBe(true)
    expect(isAndroidHost()).toBe(false)
    expect('SmylteAndroid' in window).toBe(false)
  })
})
