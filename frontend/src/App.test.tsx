import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api, AuthError, HttpError, subscribe } from './api'

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
  document.documentElement.removeAttribute('style')
  localStorage.clear()
  m.me.mockResolvedValue({ authenticated: true, user: 'admin' })
  m.getSettings.mockResolvedValue({})
  m.putSettings.mockResolvedValue({})
  m.logout.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
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

  it('renders the shell with all four tabs once authenticated', async () => {
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Tasks' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Calendar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Scheduling' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Home' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /sign in/i })).not.toBeInTheDocument()
    // The strip paints while /api/me is still in flight now, so the data layer
    // starting up is a beat behind it rather than a precondition of it.
    await waitFor(() => expect(m.calendars).toHaveBeenCalled())
    expect(subscribe).toHaveBeenCalledOnce()    // live updates wired up
  })

  it('opens on Home, at the head of the strip', async () => {
    render(<App />)
    const home = await screen.findByRole('button', { name: 'Home' })
    expect(home.className).toContain('active')
    expect(screen.getByRole('button', { name: 'Tasks' }).className).not.toContain('active')
    expect([...document.querySelectorAll('.tabs .tab')].map((b) => b.textContent))
      .toEqual(['Home', 'Tasks', 'Calendar', 'Scheduling'])
  })

  it('switches tabs on a click', async () => {
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Tasks' }))
    expect(screen.getByRole('button', { name: 'Tasks' }).className).toContain('active')
    expect(screen.getByRole('button', { name: 'Home' }).className).not.toContain('active')
  })

  it('applies the account-synced theme on load', async () => {
    m.getSettings.mockResolvedValue({ theme: 'dark' })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await vi.waitFor(() =>
      expect(document.documentElement.dataset.theme).toBe('dark'))
  })

  it('applies an account-synced custom theme to the document', async () => {
    m.getSettings.mockResolvedValue({
      theme: 'light',
      appearance: {
        active: 't1',
        themes: [{
          id: 't1', name: 'Mine', base: 'light',
          light: { '--accent': '#ff0000', '--radius': '6px' }, dark: {},
        }],
      },
    })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await vi.waitFor(() => {
      expect(document.documentElement.style.getPropertyValue('--accent')).toBe('#ff0000')
      expect(document.documentElement.style.getPropertyValue('--radius')).toBe('6px')
    })
  })

  it('ignores a hostile token smuggled into the settings blob', async () => {
    // The server validates too; this is the client half of that boundary.
    m.getSettings.mockResolvedValue({
      appearance: {
        active: 't1',
        themes: [{
          id: 't1', name: 'x', base: 'light',
          light: { '--bg': 'url(https://evil.example/beacon)' }, dark: {},
        }],
      },
    })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await vi.waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    expect(document.documentElement.style.getPropertyValue('--bg')).toBe('')
  })

  it('leaves the document untouched when no custom theme is active', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await vi.waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    // The shipped design is the absence of overrides, not a set of them.
    expect(document.documentElement.getAttribute('style')).toBeFalsy()
  })

  it('logs out back to the login form', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('button', { name: /log out/i }))
    expect(m.logout).toHaveBeenCalledOnce()
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('stays signed in, and says so, when the sign-out request fails', async () => {
    // POST /api/logout is the only thing that revokes the token and the only
    // thing that can clear the HttpOnly cookie. Showing the login card on a
    // failure told the user they were signed out while the session was still
    // live — on a cookie that is the whole perimeter.
    m.logout.mockRejectedValue(new HttpError(502, 'bad gateway'))
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('button', { name: /log out/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/still signed in/i)
    expect(screen.queryByRole('button', { name: /sign in/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Tasks' })).toBeInTheDocument()
  })

  it('treats a 401 from logout as already signed out', async () => {
    // The session is gone either way; there is nothing to keep the user in for.
    m.logout.mockRejectedValue(new AuthError('not authenticated'))
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('button', { name: /log out/i }))

    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })
})

describe('<App> home timezone', () => {
  // The app writes non-all-day events as floating local wall time, which names
  // no instant on its own. A scheduling link used to assume its OWN zone for
  // those, so a link published in another zone read every one of the owner's
  // events at the wrong instant and offered their busy hours as bookable.
  const openSettings = async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    return screen.getByRole('button', { name: 'Timezone your events are written in' })
  }

  it('starts unset, falling back to each link’s own zone', async () => {
    expect(await openSettings()).toHaveTextContent('Not set')
  })

  it('shows the stored zone', async () => {
    m.getSettings.mockResolvedValue({ home_timezone: 'Europe/Berlin' })
    await waitFor(async () => expect(await openSettings()).toHaveTextContent('Europe/Berlin'))
  })

  it('adopts this device’s zone, and clears back off', async () => {
    const here = Intl.DateTimeFormat().resolvedOptions().timeZone
    const btn = await openSettings()
    await userEvent.click(btn)
    expect(btn).toHaveTextContent(here)
    expect(m.putSettings).toHaveBeenCalledWith({ home_timezone: here })

    await userEvent.click(btn)
    expect(btn).toHaveTextContent('Not set')
    expect(m.putSettings).toHaveBeenLastCalledWith({ home_timezone: '' })
  })
})

describe('<App> session length', () => {
  const openSettings = async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    return screen.getByRole('button', { name: 'How long to stay signed in' })
  }

  it('opens on the shipped default when the account has not chosen', async () => {
    expect(await openSettings()).toHaveTextContent('7 days')
  })

  it('shows the stored choice', async () => {
    m.getSettings.mockResolvedValue({ session_ttl_s: 24 * 3600 })
    await waitFor(async () => expect(await openSettings()).toHaveTextContent('1 day'))
  })

  it('cycles the choice and writes it through', async () => {
    const btn = await openSettings()
    await userEvent.click(btn)
    expect(btn).toHaveTextContent('30 days')
    expect(m.putSettings).toHaveBeenCalledWith({ session_ttl_s: 30 * 24 * 3600 })
  })

  it('ignores a stored value the server would refuse', async () => {
    // The blob is hand-editable and this one decides how long a login lives;
    // showing it back would make the menu lie about what is in force.
    m.getSettings.mockResolvedValue({ session_ttl_s: 99 as never })
    expect(await openSettings()).toHaveTextContent('7 days')
  })
})

describe('<App> tab preferences', () => {
  const strip = () => [...document.querySelectorAll('.tabs .tab')].map((b) => b.textContent)
  const active = () =>
    document.querySelector('.tabs .tab.active')?.textContent ?? null

  it('renders the account’s saved order', async () => {
    m.getSettings.mockResolvedValue({ tab_order: ['calendar', 'scheduling', 'home', 'tasks'] })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(strip()).toEqual(['Calendar', 'Scheduling', 'Home', 'Tasks']))
  })

  it('repairs a stored order that lost a tab', async () => {
    m.getSettings.mockResolvedValue({ tab_order: ['scheduling'] as never })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    // A missing tab would leave its view unreachable, so it is appended.
    await waitFor(() => expect(strip()).toEqual(['Scheduling', 'Home', 'Tasks', 'Calendar']))
  })

  it('opens on the chosen tab', async () => {
    m.getSettings.mockResolvedValue({ start_tab: 'calendar' })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(active()).toBe('Calendar'))
  })

  it('reopens where the user left off', async () => {
    m.getSettings.mockResolvedValue({ start_tab: 'last', last_tab: 'scheduling' })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(active()).toBe('Scheduling'))
  })

  it('falls back to the first tab when there is nothing to remember', async () => {
    m.getSettings.mockResolvedValue({ start_tab: 'last', tab_order: ['calendar', 'home'] })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(active()).toBe('Calendar'))
  })

  it('remembers the tab only while set to reopen on the last one', async () => {
    m.getSettings.mockResolvedValue({ start_tab: 'last' })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await userEvent.click(screen.getByRole('button', { name: 'Calendar' }))
    expect(m.putSettings).toHaveBeenCalledWith({ last_tab: 'calendar' })
  })

  it('writes nothing on a tab click when the start tab is fixed', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await userEvent.click(screen.getByRole('button', { name: 'Calendar' }))
    expect(m.putSettings).not.toHaveBeenCalled()
  })

  it('saves a reorder from the tabs editor', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('button', { name: 'Customize tabs' }))
    await userEvent.click(screen.getByRole('button', { name: 'Move Calendar left' }))
    expect(m.putSettings).toHaveBeenCalledWith({
      tab_order: ['home', 'calendar', 'tasks', 'scheduling'],
    })
    await waitFor(() => expect(strip()).toEqual(['Home', 'Calendar', 'Tasks', 'Scheduling']))
  })

  it('saves the tab to open on', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('button', { name: 'Customize tabs' }))
    await userEvent.selectOptions(screen.getByLabelText('Opens on'), 'scheduling')
    expect(m.putSettings).toHaveBeenCalledWith({ start_tab: 'scheduling' })
  })

  it('paints the remembered tab before the settings fetch lands', async () => {
    // The boot cache exists only to avoid a flash of the wrong tab; the server
    // still gets the last word a moment later.
    localStorage.setItem('smylte-tab', 'scheduling')
    let settle: (v: unknown) => void = () => {}
    m.getSettings.mockReturnValue(new Promise((r) => { settle = r }) as never)
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    expect(active()).toBe('Scheduling')
    settle({ start_tab: 'calendar' })
    await waitFor(() => expect(active()).toBe('Calendar'))
  })

  it('does not yank the view away from a tab clicked while loading', async () => {
    let settle: (v: unknown) => void = () => {}
    m.getSettings.mockReturnValue(new Promise((r) => { settle = r }) as never)
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Tasks' }))
    settle({ start_tab: 'calendar' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    expect(active()).toBe('Tasks')
  })
})

// ── SSE routing: a preference write is not a data change ────────────────────

describe('<App> live updates', () => {
  /** Grab the handler App passed to subscribe, so events can be delivered. */
  const emit = () => vi.mocked(subscribe).mock.calls[0][0]

  it('refetches task data on a data event', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(subscribe).toHaveBeenCalled())
    const before = m.lists.mock.calls.length

    await act(async () => {
      emit()('task_updated')
      await new Promise((r) => setTimeout(r, 300))   // past the coalescing debounce
    })
    await waitFor(() => expect(m.lists.mock.calls.length).toBeGreaterThan(before))
  })

  it('does not refetch anything for a settings write', async () => {
    // The server publishes settings_updated to every subscriber including the
    // tab that made the write, and this used to bump `rev` — 1 + N requests per
    // event in TasksView alone, so one appearance-slider drag (which writes on
    // every step) became a request storm over data the change cannot affect.
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(subscribe).toHaveBeenCalled())
    const before = m.lists.mock.calls.length

    await act(async () => {
      emit()('settings_updated')
      await new Promise((r) => setTimeout(r, 300))
    })
    expect(m.lists.mock.calls.length).toBe(before)
  })
})

describe('<App> clock setting', () => {
  it('opens on 12-hour and cycles to 24-hour, persisting the choice', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    const clock = screen.getByRole('button', { name: '12- or 24-hour clock' })
    expect(clock).toHaveTextContent('12-hour')
    await userEvent.click(clock)
    expect(clock).toHaveTextContent('24-hour')
    await waitFor(() => expect(m.putSettings).toHaveBeenCalledWith({ time_format: '24h' }))
    await userEvent.click(clock)
    expect(clock).toHaveTextContent('12-hour')
  })

  it('restores a stored 24-hour choice', async () => {
    m.getSettings.mockResolvedValue({ time_format: '24h' })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '12- or 24-hour clock' })).toHaveTextContent('24-hour'))
  })

  it('falls back to 12-hour when the stored value is junk', async () => {
    // The blob is hand-editable, so an unknown token has to degrade to the
    // default rather than reaching a formatter.
    m.getSettings.mockResolvedValue({ time_format: 'H:mm' } as never)
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    expect(screen.getByRole('button', { name: '12- or 24-hour clock' })).toHaveTextContent('12-hour')
  })
})

// ── a settings write that fails must not be swallowed ───────────────────────

describe('<App> settings writes', () => {
  it('returns to the login form when the session has expired', async () => {
    // These were `.catch(() => {})`, which ate an AuthError as happily as an
    // offline blip: the tab kept accepting preference changes, never fell back
    // to the login form, and lost every one of them on the next reload.
    m.putSettings.mockRejectedValue(new AuthError('unauthenticated'))
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('button', { name: 'Customize tabs' }))
    await userEvent.click(screen.getByRole('button', { name: 'Move Calendar left' }))
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('surfaces a rejection from a server it did reach', async () => {
    m.putSettings.mockRejectedValue(new HttpError(422, 'dashboard.0.h: less than or equal to 40'))
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('button', { name: 'Customize tabs' }))
    await userEvent.click(screen.getByRole('button', { name: 'Move Calendar left' }))
    expect(await screen.findByText(/couldn't save your preferences/i)).toBeInTheDocument()
  })

  it('stays quiet when the request never reached a server', async () => {
    // Offline is ordinary and the local state stands in fine.
    m.putSettings.mockRejectedValue(new TypeError('Failed to fetch'))
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
    await userEvent.click(screen.getByRole('button', { name: 'Customize tabs' }))
    await userEvent.click(screen.getByRole('button', { name: 'Move Calendar left' }))
    await waitFor(() => expect(m.putSettings).toHaveBeenCalled())
    expect(screen.queryByText(/couldn't save/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /sign in/i })).not.toBeInTheDocument()
  })
})
