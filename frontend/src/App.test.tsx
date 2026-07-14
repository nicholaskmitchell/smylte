import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api, subscribe } from './api'

// Mock the whole API module: every method becomes a vi.fn() so the shell and
// whichever view mounts never touch the network (jsdom has no EventSource).
vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})

const m = vi.mocked(api)

beforeEach(() => {
  vi.clearAllMocks()
  document.documentElement.dataset.theme = 'light'
  m.me.mockResolvedValue({ authenticated: true, user: 'admin' })
  m.getSettings.mockResolvedValue({})
  m.putSettings.mockResolvedValue({})
  m.logout.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
})

describe('<App> auth gate', () => {
  it('shows only the login form when the session is invalid', async () => {
    m.me.mockRejectedValue(new Error('unauthenticated'))
    render(<App />)
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
    // Nothing from the authed shell leaks out to a logged-out visitor.
    expect(screen.queryByRole('button', { name: 'Tasks' })).not.toBeInTheDocument()
    expect(m.getSettings).not.toHaveBeenCalled()
    expect(subscribe).not.toHaveBeenCalled()
  })

  it('renders the shell with all three tabs once authenticated', async () => {
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Tasks' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Calendar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Scheduling' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /sign in/i })).not.toBeInTheDocument()
    expect(m.lists).toHaveBeenCalled()          // default tab (Tasks) loaded
    expect(subscribe).toHaveBeenCalledOnce()    // live updates wired up
  })

  it('applies the account-synced theme on load', async () => {
    m.getSettings.mockResolvedValue({ theme: 'dark' })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await vi.waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe('dark'))
  })

  it('logs out back to the login form', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('button', { name: /log out/i }))
    expect(m.logout).toHaveBeenCalledOnce()
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })
})
