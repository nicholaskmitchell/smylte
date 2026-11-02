// Inside the Android client, a toggle in Settings plays its haptic, and a save
// that fails plays reject with the toast. The file is separate because the
// host is module state per test file, and App.test.tsx must stay a browser.
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api, HttpError } from './api'
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

const haptic = vi.fn()

beforeAll(() => {
  vi.stubGlobal('SmylteAndroid', { hello: () => '{"v":1,"clock24":false}', haptic })
  startAndroidHost()
})
afterAll(() => {
  vi.unstubAllGlobals()
})

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '/')
  localStorage.clear()
  m.me.mockResolvedValue({ authenticated: true, user: 'alice' })
  m.getSettings.mockResolvedValue({})
  m.putSettings.mockResolvedValue({})
  m.logout.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
})

const flipToggle = async () => {
  render(<App />)
  await screen.findByRole('button', { name: 'Tasks' })
  await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
  await userEvent.click(screen.getByRole('tab', { name: 'Tasks' }))
  haptic.mockClear()
  // Pressed by default.
  await userEvent.click(
    screen.getByRole('button', { name: 'Complete a task when its last subtask is done' }))
}

describe('<App> in the Android client: haptics', () => {
  it('plays a toggle\'s haptic and nothing more when its save lands', async () => {
    await flipToggle()
    await waitFor(() => expect(m.putSettings).toHaveBeenCalled())
    expect(haptic.mock.calls).toEqual([['toggleOff']])
  })

  it('plays reject with the toast when the save fails', async () => {
    m.putSettings.mockRejectedValue(new HttpError(500, 'boom'))
    await flipToggle()
    await screen.findByRole('alert')
    expect(haptic.mock.calls).toEqual([['toggleOff'], ['reject']])
  })
})
