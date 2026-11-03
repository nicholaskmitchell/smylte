// A phone with no wallpaper palette (Android 11, or an APK from before the
// accent) offers no switch, and a choice stored on it paints nothing. The file
// is separate because the host env is module state per test file, and
// App.test.tsx must stay a browser.
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api } from './api'
import { startAndroidHost } from './android'
import type { CustomTheme } from './appearance'
import { SURFACES_CSS } from './test/accent'

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

let sheet: HTMLStyleElement

beforeAll(() => {
  // jsdom loads no stylesheet, so the shipped backgrounds come from here.
  sheet = document.createElement('style')
  sheet.textContent = SURFACES_CSS
  document.head.appendChild(sheet)
  vi.stubGlobal('SmylteAndroid', { hello: () => '{"v":1,"clock24":false}' })
  startAndroidHost()
})
afterAll(() => {
  sheet.remove()
  vi.unstubAllGlobals()
})

const MINE: CustomTheme = {
  id: 't1', name: 'Mine', base: 'light',
  light: { '--accent': '#aa3300' }, dark: { '--accent': '#ff8844' },
}

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '/')
  document.documentElement.dataset.theme = 'light'
  document.documentElement.removeAttribute('style')
  localStorage.clear()
  m.me.mockResolvedValue({ authenticated: true, user: 'alice' })
  m.getSettings.mockResolvedValue({
    time_format: '12h', appearance: { active: MINE.id, themes: [MINE] },
  })
  m.putSettings.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.displays.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
})

const accent = () => document.documentElement.style.getPropertyValue('--accent')

describe('<App> in the Android client without a palette', () => {
  it('offers no switch, and a stored choice paints nothing', async () => {
    localStorage.setItem('smylte-device-accent', '1')
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(accent()).toBe('#aa3300'))
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    const settings = await screen.findByRole('dialog', { name: 'Settings' })
    await userEvent.click(within(settings).getByRole('tab', { name: 'Appearance' }))
    await userEvent.click(within(settings).getByRole('button', { name: 'Customize appearance' }))
    await screen.findByRole('dialog', { name: 'Appearance' })
    expect(screen.queryByLabelText('Accent from wallpaper')).toBeNull()
    expect(accent()).toBe('#aa3300')
  })
})
