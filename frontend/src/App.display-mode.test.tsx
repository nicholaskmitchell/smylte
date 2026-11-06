// Display mode from the signed-in app: entered from Settings → Displays, held
// per device across a reload, switched between views from its own bar, and
// left the same way. The views are stubs, so these are about App's frame and
// not about any view's rows.
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api } from './api'
import { DISPLAY_MODE_KEY } from './displaymode'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})

vi.mock('./desktop', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./desktop')>()
  return {
    ...mod,
    readState: vi.fn(async () => null),
    floatWindow: vi.fn(async () => null), dockWindow: vi.fn(async () => null),
    pinWindow: vi.fn(async () => null), dragWindow: vi.fn(async () => null),
  }
})

vi.mock('./components/HomeView', () => ({ HomeView: () => <div>stub home</div> }))
vi.mock('./components/TodayView', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./components/TodayView')>()
  return { ...mod, TodayView: () => <div>stub today</div> }
})
vi.mock('./components/CalendarView', () => ({ CalendarView: () => <div>stub calendar</div> }))
vi.mock('./components/TasksView', () => ({ TasksView: () => <div>stub tasks</div> }))

const m = vi.mocked(api)

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '/')
  localStorage.clear()
  m.me.mockResolvedValue({ authenticated: true, user: 'admin' })
  m.getSettings.mockResolvedValue({})
  m.putSettings.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.displays.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
  m.shares.mockResolvedValue([])
  m.mailStatus.mockResolvedValue({
    enabled: false, deployment_enabled: false, running: false, pending_count: 0,
    cursors: [], counts: {},
  })
  m.mailSuggestions.mockResolvedValue({ enabled: false, suggestions: [], pending_count: 0 })
})

afterEach(cleanup)

const startFromSettings = async () => {
  await userEvent.click(await screen.findByRole('button', { name: 'Settings' }))
  await userEvent.click(await screen.findByRole('tab', { name: 'Displays' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Start display mode' }))
}

describe('<App> display mode', () => {
  it('is entered from Settings → Displays, on the view that was open', async () => {
    render(<App />)
    expect(await screen.findByText('stub home')).toBeInTheDocument()
    await startFromSettings()

    expect(screen.getByText('stub home')).toBeInTheDocument()
    // The app's frame is gone: no gear, no tab strip, no settings panel.
    expect(screen.queryByRole('button', { name: 'Settings' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Tasks' })).toBeNull()
    expect(screen.queryByRole('tab', { name: 'Displays' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Display controls' })).toBeInTheDocument()
    expect(localStorage.getItem(DISPLAY_MODE_KEY)).toBe('home')
  })

  it('comes back as a display after a reload, whatever the start tab says', async () => {
    localStorage.setItem(DISPLAY_MODE_KEY, 'calendar')
    m.getSettings.mockResolvedValue({ start_tab: 'tasks' })
    render(<App />)
    expect(await screen.findByText('stub calendar')).toBeInTheDocument()
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    expect(screen.getByText('stub calendar')).toBeInTheDocument()
    expect(screen.queryByText('stub tasks')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Settings' })).toBeNull()
  })

  it('reads a stored value that names no display view as off', async () => {
    localStorage.setItem(DISPLAY_MODE_KEY, 'scheduling')
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Display controls' })).toBeNull()
  })

  it('switches views from its bar and remembers the choice on this device', async () => {
    localStorage.setItem(DISPLAY_MODE_KEY, 'calendar')
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Display controls' }))
    const bar = screen.getByRole('toolbar', { name: 'Display controls' })
    expect(bar).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Today' }))
    expect(screen.getByText('stub today')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Today' })).toHaveAttribute('aria-pressed', 'true')
    expect(localStorage.getItem(DISPLAY_MODE_KEY)).toBe('today')
    // Nothing about display mode goes into the account's settings.
    for (const [patch] of m.putSettings.mock.calls) {
      expect(JSON.stringify(patch)).not.toContain('display')
    }
  })

  it('exits onto the view it was showing, with the frame back', async () => {
    localStorage.setItem(DISPLAY_MODE_KEY, 'calendar')
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Display controls' }))
    await userEvent.click(screen.getByRole('button', { name: 'Exit display mode' }))
    expect(await screen.findByRole('button', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.getByText('stub calendar')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Display controls' })).toBeNull()
    expect(localStorage.getItem(DISPLAY_MODE_KEY)).toBeNull()
  })
})
