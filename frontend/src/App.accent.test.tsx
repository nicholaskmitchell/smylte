// Inside the Android client, a phone that reports its wallpaper palette can take
// its accent from it: a switch in Appearance, kept on this phone only. The file
// is separate because the host env is module state per test file, and
// App.test.tsx must stay a browser.
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api } from './api'
import { ANDROID_EVENT, startAndroidHost } from './android'
import { serializeTheme, type CustomTheme } from './appearance'
import { RAMP, RAMP2, SURFACES_CSS } from './test/accent'

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

const phone = (env: Record<string, unknown>) =>
  window.dispatchEvent(new CustomEvent(ANDROID_EVENT, {
    detail: { type: 'env', env: { v: 1, ...env } },
  }))

const saveFile = vi.fn((_name: string, _mime: string, _text: string) => true)
let sheet: HTMLStyleElement

beforeAll(() => {
  // jsdom loads no stylesheet, so the shipped backgrounds come from here.
  sheet = document.createElement('style')
  sheet.textContent = SURFACES_CSS
  document.head.appendChild(sheet)
  vi.stubGlobal('SmylteAndroid', {
    hello: () => JSON.stringify({ v: 1, clock24: false, accent: RAMP }),
    saveFile,
  })
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
  phone({ clock24: false, accent: RAMP })
  m.me.mockResolvedValue({ authenticated: true, user: 'alice' })
  m.getSettings.mockResolvedValue({ time_format: '12h' })
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

const withTheme = (t: CustomTheme = MINE) =>
  m.getSettings.mockResolvedValue({
    time_format: '12h', appearance: { active: t.id, themes: [t] },
  })
const accent = () => document.documentElement.style.getPropertyValue('--accent')
const wallpaper = () => screen.getByLabelText('Accent from wallpaper')

async function openAppearance() {
  await screen.findByRole('button', { name: 'Tasks' })
  await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
  const settings = await screen.findByRole('dialog', { name: 'Settings' })
  await userEvent.click(within(settings).getByRole('tab', { name: 'Appearance' }))
  await userEvent.click(within(settings).getByRole('button', { name: 'Customize appearance' }))
  return screen.findByRole('dialog', { name: 'Appearance' })
}

describe('<App> in the Android client: the accent from the wallpaper', () => {
  it('offers the switch in Appearance, off, and paints nothing until it is on', async () => {
    render(<App />)
    await openAppearance()
    expect(wallpaper()).toHaveAttribute('aria-pressed', 'false')
    expect(wallpaper()).toHaveTextContent('Off')
    expect(accent()).toBe('')
  })

  it('paints the tone that clears 3:1 when turned on', async () => {
    render(<App />)
    await openAppearance()
    await userEvent.click(wallpaper())
    await waitFor(() => expect(accent()).toBe('#005ac1'))
    expect(localStorage.getItem('smylte-device-accent')).toBe('1')
    expect(wallpaper()).toHaveAttribute('aria-pressed', 'true')
    expect(wallpaper()).toHaveTextContent('On')
  })

  it('keeps the choice on this phone only: an edit saved to the account carries the theme\'s own accent', async () => {
    withTheme()
    render(<App />)
    const dialog = await openAppearance()
    await waitFor(() => expect(accent()).toBe('#aa3300'))
    await userEvent.click(wallpaper())
    await waitFor(() => expect(accent()).toBe('#005ac1'))
    // The switch itself writes nothing to the account, not even after the
    // settings debounce (400 ms): a synced flag would turn it on for every
    // other phone, which is the one thing it must not do.
    await new Promise((r) => setTimeout(r, 450))
    expect(m.putSettings).not.toHaveBeenCalled()

    // An edit to the theme is what writes appearance to the account (after the
    // same debounce), so make one and wait for the write of the finished value:
    // with nothing written, "the tone is not in it" would hold whatever the
    // code did, and the partial values #111 and #1111 are valid and may be
    // written on the way.
    const text = within(dialog).getByLabelText('Text', { selector: 'input.appear-text' })
    await userEvent.clear(text)
    await userEvent.type(text, '#111111')
    await waitFor(() => expect(JSON.stringify(m.putSettings.mock.calls)).toContain('#111111'),
      { timeout: 3000 })
    // Only the theme went: no other key rode along with it.
    for (const [patch] of m.putSettings.mock.calls) expect(Object.keys(patch)).toEqual(['appearance'])

    const written = JSON.stringify(m.putSettings.mock.calls)
    expect(written).toContain('#111111')
    expect(written).toContain('#aa3300')
    expect(written).not.toContain('#005ac1')
    expect(written).not.toContain('smylte-device-accent')
    expect(localStorage.getItem('smylte-appearance') ?? '').toContain('#aa3300')
    expect(localStorage.getItem('smylte-appearance') ?? '').not.toContain('#005ac1')
    // And the screen still shows the wallpaper tone, over the edited theme.
    expect(accent()).toBe('#005ac1')
  })

  it('keeps the override through a mode flip, in each mode\'s tone', async () => {
    withTheme()
    render(<App />)
    const dialog = await openAppearance()
    await waitFor(() => expect(accent()).toBe('#aa3300'))
    await userEvent.click(wallpaper())
    await waitFor(() => expect(accent()).toBe('#005ac1'))

    await userEvent.click(within(dialog).getByRole('button', { name: 'Dark' }))
    await waitFor(() => expect(accent()).toBe('#adc6ff'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Light' }))
    await waitFor(() => expect(accent()).toBe('#005ac1'))
  })

  it('restores the theme\'s accent when turned off', async () => {
    withTheme()
    render(<App />)
    await openAppearance()
    await waitFor(() => expect(accent()).toBe('#aa3300'))
    await userEvent.click(wallpaper())
    await waitFor(() => expect(accent()).toBe('#005ac1'))
    await userEvent.click(wallpaper())
    await waitFor(() => expect(accent()).toBe('#aa3300'))
    expect(localStorage.getItem('smylte-device-accent')).toBe('0')
  })

  it('leaves no accent behind on the default theme when turned off', async () => {
    render(<App />)
    await openAppearance()
    await userEvent.click(wallpaper())
    await waitFor(() => expect(accent()).toBe('#005ac1'))
    await userEvent.click(wallpaper())
    await waitFor(() => expect(accent()).toBe(''))
  })

  it('starts on when this phone turned it on before', async () => {
    localStorage.setItem('smylte-device-accent', '1')
    withTheme()
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(accent()).toBe('#005ac1'))
    await openAppearance()
    expect(wallpaper()).toHaveAttribute('aria-pressed', 'true')
    expect(wallpaper()).toHaveTextContent('On')
  })

  it('never puts the tone in the theme: an export carries the theme\'s own accent', async () => {
    withTheme()
    render(<App />)
    await openAppearance()
    await waitFor(() => expect(accent()).toBe('#aa3300'))
    await userEvent.click(wallpaper())
    await waitFor(() => expect(accent()).toBe('#005ac1'))
    await userEvent.click(screen.getByRole('button', { name: 'Export' }))
    expect(saveFile).toHaveBeenCalledTimes(1)
    const text = saveFile.mock.calls[0][2]
    expect(text).not.toContain('#005ac1')
    expect(text).toContain('#aa3300')
    expect(text).toBe(serializeTheme(MINE))
    act(() => {
      window.dispatchEvent(new CustomEvent(ANDROID_EVENT, {
        detail: { type: 'saved', outcome: 'saved' },
      }))
    })
  })

  it('keeps the theme\'s accent on a theme no wallpaper tone is readable on', async () => {
    withTheme({
      ...MINE,
      light: { '--bg': '#5a5a5a', '--bg-elev': '#5a5a5a', '--paper': '#5a5a5a', '--accent': '#aa3300' },
    })
    render(<App />)
    await openAppearance()
    await waitFor(() => expect(accent()).toBe('#aa3300'))
    await userEvent.click(wallpaper())
    expect(wallpaper()).toHaveAttribute('aria-pressed', 'true')
    expect(accent()).toBe('#aa3300')
  })

  it('repaints when the phone reports a new palette', async () => {
    render(<App />)
    await openAppearance()
    await userEvent.click(wallpaper())
    await waitFor(() => expect(accent()).toBe('#005ac1'))
    act(() => { phone({ clock24: false, accent: RAMP2 }) })
    await waitFor(() => expect(accent()).toBe('#006e1c'))
  })

  it('hides the switch and restores the theme\'s accent when the palette goes', async () => {
    withTheme()
    render(<App />)
    await openAppearance()
    await userEvent.click(wallpaper())
    await waitFor(() => expect(accent()).toBe('#005ac1'))
    act(() => { phone({ clock24: false }) })
    await waitFor(() => expect(screen.queryByLabelText('Accent from wallpaper')).toBeNull())
    expect(accent()).toBe('#aa3300')
  })
})
