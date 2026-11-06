// Display mode from the signed-in app: entered from Settings → Displays, held
// per device across a reload, and left from its own bar. The frame itself is
// stubbed, so these are about App's plumbing; DisplayModeFrame.test.tsx covers
// the faces and the writes.
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
vi.mock('./components/DisplayModeFrame', () => ({
  DisplayModeFrame: (p: { mode: string; onMode: (m: string) => void; onExit: () => void }) => (
    <div>
      <output aria-label="face">{p.mode}</output>
      <button onClick={() => p.onMode('now')}>stub now</button>
      <button onClick={p.onExit}>stub exit</button>
    </div>
  ),
}))
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
  it('is entered from Settings → Displays, on the month, with the app gone', async () => {
    render(<App />)
    expect(await screen.findByText('stub home')).toBeInTheDocument()
    await startFromSettings()

    expect(screen.getByLabelText('face')).toHaveTextContent('calendar')
    expect(screen.queryByText('stub home')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Settings' })).toBeNull()
    expect(screen.queryByRole('tab', { name: 'Displays' })).toBeNull()
    expect(localStorage.getItem(DISPLAY_MODE_KEY)).toBe('calendar')
  })

  it('comes back as a display after a reload', async () => {
    localStorage.setItem(DISPLAY_MODE_KEY, 'habits')
    m.getSettings.mockResolvedValue({ start_tab: 'tasks' })
    render(<App />)
    expect(await screen.findByLabelText('face')).toHaveTextContent('habits')
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    expect(screen.getByLabelText('face')).toHaveTextContent('habits')
    expect(screen.queryByText('stub tasks')).toBeNull()
  })

  it('reads a stored value that names no face as off', async () => {
    localStorage.setItem(DISPLAY_MODE_KEY, 'today')
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.queryByLabelText('face')).toBeNull()
  })

  it('remembers a face switched to on this device, and never in the account', async () => {
    localStorage.setItem(DISPLAY_MODE_KEY, 'calendar')
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'stub now' }))
    expect(screen.getByLabelText('face')).toHaveTextContent('now')
    expect(localStorage.getItem(DISPLAY_MODE_KEY)).toBe('now')
    for (const [patch] of m.putSettings.mock.calls) {
      expect(JSON.stringify(patch)).not.toContain('display')
    }
  })

  it('exits back to the app', async () => {
    localStorage.setItem(DISPLAY_MODE_KEY, 'calendar')
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'stub exit' }))
    expect(await screen.findByRole('button', { name: 'Settings' })).toBeInTheDocument()
    expect(screen.getByText('stub home')).toBeInTheDocument()
    expect(localStorage.getItem(DISPLAY_MODE_KEY)).toBeNull()
  })
})
