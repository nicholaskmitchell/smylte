// What the shell hands the Home tab: a way to open Settings at a section, a way
// into the Tasks pane for email suggestions, and the two counters its modules
// re-read on. HomeView is replaced by a stub that exposes exactly those, so
// these tests are about App's plumbing and not about any module's rows.
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api, subscribe } from './api'

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

vi.mock('./components/HomeView', () => ({
  HomeView: (p: {
    mailRev?: number; sharesRev?: number; onOpenSuggested?: () => void
    onOpenSettings?: (section: 'mail' | 'shares') => void
  }) => (
    <div>
      <output aria-label="mailRev">{p.mailRev}</output>
      <output aria-label="sharesRev">{p.sharesRev}</output>
      <button onClick={() => p.onOpenSuggested?.()}>stub open suggested</button>
      <button onClick={() => p.onOpenSettings?.('mail')}>stub open mail settings</button>
      <button onClick={() => p.onOpenSettings?.('shares')}>stub open shares settings</button>
    </div>
  ),
}))

const m = vi.mocked(api)
const emit = () => vi.mocked(subscribe).mock.calls[0][0]

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
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
  m.shares.mockResolvedValue([])
  m.mailStatus.mockResolvedValue({
    enabled: false, deployment_enabled: false, running: false, pending_count: 0,
    cursors: [], counts: {},
  })
  m.mailSuggestions.mockResolvedValue({ enabled: false, suggestions: [], pending_count: 0 })
})

afterEach(cleanup)

describe('<App> opening Settings from Home', () => {
  it('opens Settings at the requested section', async () => {
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'stub open shares settings' }))
    expect(await screen.findByRole('tab', { name: 'Shares' })).toHaveAttribute('aria-selected', 'true')
  })

  it('moves to the requested section when Settings is already open at another', async () => {
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'stub open mail settings' }))
    expect(await screen.findByRole('tab', { name: 'Email' })).toHaveAttribute('aria-selected', 'true')

    // No mousedown: a real click on the module sits outside the menu and closes
    // it, and the second open would then be a plain first one. The menu stays
    // open here, so only the remount `key={settingsKey}` can move it.
    fireEvent.click(screen.getByRole('button', { name: 'stub open shares settings' }))
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Shares' })).toHaveAttribute('aria-selected', 'true'))
    expect(screen.getByRole('tab', { name: 'Email' })).toHaveAttribute('aria-selected', 'false')
  })
})

describe('<App> opening the Suggested pane from Home', () => {
  it('goes to Tasks with the Suggested pane up, and only that once', async () => {
    m.mailSuggestions.mockResolvedValue({
      enabled: true, pending_count: 1,
      suggestions: [{
        id: 'sg1', kind: 'task', status: 'pending', title: 'Return the permission slip',
        notes: '', due: null, confidence: 0.8, event: null, target: null,
        source: {
          sender: 'office@school.example', sender_name: 'Ms Smith', subject: 'Trip',
          sent_at: '2026-10-05T08:00:00Z', message_id: 'm1', thread_id: 't1', folder: 'INBOX',
        },
        updates: [], created_at: '2026-10-05T08:01:00Z', decided_at: null, result: null,
      }],
    })
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'stub open suggested' }))
    expect(screen.getByRole('button', { name: 'Tasks' }).className).toContain('active')
    expect(await screen.findByDisplayValue('Return the permission slip')).toBeInTheDocument()

    // The ask was handed back, so a later visit to Tasks opens as usual.
    await userEvent.click(screen.getByRole('button', { name: 'Home' }))
    await userEvent.click(screen.getByRole('button', { name: 'Tasks' }))
    await screen.findByText('Create a list to get started.')
    expect(screen.queryByDisplayValue('Return the permission slip')).not.toBeInTheDocument()
  })
})

describe('<App> live updates for Home', () => {
  it('bumps the shares counter for a share event without refetching task data', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(subscribe).toHaveBeenCalled())
    const before = m.lists.mock.calls.length
    expect(screen.getByLabelText('sharesRev')).toHaveTextContent('0')

    await act(async () => {
      emit()('share_updated')
      await new Promise((r) => setTimeout(r, 300))   // past the coalescing debounce
    })
    expect(screen.getByLabelText('sharesRev')).toHaveTextContent('1')
    expect(m.lists.mock.calls.length).toBe(before)
  })

  it('bumps the mail counter for a mail event', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(subscribe).toHaveBeenCalled())
    await act(async () => { emit()('mail_updated') })
    expect(screen.getByLabelText('mailRev')).toHaveTextContent('1')
  })
})
