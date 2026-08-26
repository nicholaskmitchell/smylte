import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { api, AuthError, HttpError, subscribe } from './api'
import { DEFAULT_TAB_ORDER, TAB_LABELS, TAB_KEY } from './tabs'

/** The shipped strip, as the top bar spells it. Derived rather than written out
 *  so adding a tab does not silently need this file edited in four places —
 *  what the strip *should* contain is pinned in tabs.test.ts, and what belongs
 *  here is that the shell renders it. */
const SHIPPED = DEFAULT_TAB_ORDER.map((t) => TAB_LABELS[t])

// Mock the whole API module: every method becomes a vi.fn() so the shell and
// whichever view mounts never touch the network (jsdom has no EventSource).
vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})

const m = vi.mocked(api)

/** Open settings and, when a section is named, drill into it.
 *
 * The nav items are `role="tab"`, not buttons — which is also what keeps the
 * *Tasks* section from colliding with the *Tasks* tab in the strip above, since
 * every `getByRole('button', { name: 'Tasks' })` here means the strip. */
const openSettings = async (section?: string) => {
  await userEvent.click(screen.getByRole('button', { name: 'Settings' }))
  if (section) await userEvent.click(screen.getByRole('tab', { name: section }))
}

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
  // The Account section mounts the connected-apps list, so opening settings
  // now fetches this too.
  m.mcpConnections.mockResolvedValue([])
})

describe('<App> auth gate', () => {
  it('shows only the login form when the session is invalid', async () => {
    // A REAL `AuthError`, not a bare Error. Boot now branches on the error —
    // only a 401 is a sign-out, everything else is "can't reach the server" —
    // and a bare Error is neither an AuthError nor a 401, so this pinned the old
    // conflation and could not tell the two cases apart. The 2026-08-25 stage 4
    // pin that closed that finding says so in its own docstring and names this
    // line. What the test asserts is unchanged; only the failure it simulates
    // is now the one it always claimed to be.
    m.me.mockRejectedValue(new AuthError('unauthenticated'))
    render(<App />)
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
    // Nothing from the authed shell leaks out to a logged-out visitor.
    expect(screen.queryByRole('button', { name: 'Tasks' })).not.toBeInTheDocument()
    expect(m.getSettings).not.toHaveBeenCalled()
    expect(subscribe).not.toHaveBeenCalled()
  })

  it('renders the shell with every tab once authenticated', async () => {
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Tasks' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Today' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Calendar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Scheduling' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Home' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /sign in/i })).not.toBeInTheDocument()
    // The strip paints while /api/me is still in flight now, so the data layer
    // starting up is a beat behind it rather than a precondition of it.
    await waitFor(() => expect(m.calendars).toHaveBeenCalled())
    expect(subscribe).toHaveBeenCalledOnce()    // live updates wired up
  })

  it('opens on Home, which is no longer the head of the strip', async () => {
    render(<App />)
    const home = await screen.findByRole('button', { name: 'Home' })
    // Today leads the strip; Home is still what a fresh account lands on. The
    // two used to be the same tab, and the boot seed reads DEFAULT_TAB_START
    // rather than the strip's head precisely so they can differ without the
    // first paint flashing the wrong view (see App.tsx and tabs.ts).
    expect(home.className).toContain('active')
    expect(screen.getByRole('button', { name: 'Today' }).className).not.toContain('active')
    expect([...document.querySelectorAll('.tabs .tab')].map((b) => b.textContent))
      .toEqual(SHIPPED)
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
    await openSettings('Account')
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
    await openSettings('Account')
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
    await openSettings('Account')
    await userEvent.click(screen.getByRole('button', { name: /log out/i }))

    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })
})

describe('<App> home timezone', () => {
  // The app writes non-all-day events as floating local wall time, which names
  // no instant on its own. A scheduling link used to assume its OWN zone for
  // those, so a link published in another zone read every one of the owner's
  // events at the wrong instant and offered their busy hours as bookable.
  const open = async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    return screen.getByRole('button', { name: 'Timezone your events are written in' })
  }

  it('starts unset, falling back to each link’s own zone', async () => {
    expect(await open()).toHaveTextContent('Not set')
  })

  it('shows the stored zone', async () => {
    m.getSettings.mockResolvedValue({ home_timezone: 'Europe/Berlin' })
    await waitFor(async () => expect(await open()).toHaveTextContent('Europe/Berlin'))
  })

  it('adopts this device’s zone, and clears back off', async () => {
    const here = Intl.DateTimeFormat().resolvedOptions().timeZone
    const btn = await open()
    await userEvent.click(btn)
    expect(btn).toHaveTextContent(here)
    expect(m.putSettings).toHaveBeenCalledWith({ home_timezone: here })

    await userEvent.click(btn)
    expect(btn).toHaveTextContent('Not set')
    expect(m.putSettings).toHaveBeenLastCalledWith({ home_timezone: '' })
  })
})

describe('<App> session length', () => {
  const open = async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('Account')
    return screen.getByRole('button', { name: 'How long to stay signed in' })
  }

  it('opens on the shipped default when the account has not chosen', async () => {
    expect(await open()).toHaveTextContent('7 days')
  })

  it('shows the stored choice', async () => {
    m.getSettings.mockResolvedValue({ session_ttl_s: 24 * 3600 })
    await waitFor(async () => expect(await open()).toHaveTextContent('1 day'))
  })

  it('cycles the choice and writes it through', async () => {
    const btn = await open()
    await userEvent.click(btn)
    expect(btn).toHaveTextContent('30 days')
    expect(m.putSettings).toHaveBeenCalledWith({ session_ttl_s: 30 * 24 * 3600 })
  })

  it('ignores a stored value the server would refuse', async () => {
    // The blob is hand-editable and this one decides how long a login lives;
    // showing it back would make the menu lie about what is in force.
    m.getSettings.mockResolvedValue({ session_ttl_s: 99 as never })
    expect(await open()).toHaveTextContent('7 days')
  })
})

describe('<App> tab preferences', () => {
  const strip = () => [...document.querySelectorAll('.tabs .tab')].map((b) => b.textContent)
  const active = () =>
    document.querySelector('.tabs .tab.active')?.textContent ?? null

  it('renders the account’s saved order', async () => {
    m.getSettings.mockResolvedValue({
      tab_order: ['calendar', 'scheduling', 'home', 'tasks', 'today'],
    })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() =>
      expect(strip()).toEqual(['Calendar', 'Scheduling', 'Home', 'Tasks', 'Today']))
  })

  it('repairs a stored order that lost a tab', async () => {
    m.getSettings.mockResolvedValue({ tab_order: ['scheduling'] as never })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    // A missing tab would leave its view unreachable, so it is appended — in
    // shipped order, behind whatever the stored blob did name.
    await waitFor(() =>
      expect(strip()).toEqual(['Scheduling', 'Today', 'Home', 'Tasks', 'Calendar']))
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
    await openSettings('General')
    await userEvent.click(screen.getByRole('button', { name: 'Move Calendar left' }))
    expect(m.putSettings).toHaveBeenCalledWith({
      tab_order: ['today', 'home', 'calendar', 'tasks', 'scheduling'],
    })
    await waitFor(() =>
      expect(strip()).toEqual(['Today', 'Home', 'Calendar', 'Tasks', 'Scheduling']))
  })

  it('saves the tab to open on', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
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

  it('DOES re-read the settings for a settings write, so another device cannot be overwritten', async () => {
    // The other half of the same event. Dropping it outright left this tab
    // holding whatever the blob said when it loaded — and `getSettings` is
    // reached from exactly one effect, keyed on an auth transition, so that was
    // for the life of the tab.
    //
    // `store.update_settings` merges SHALLOWLY, and every list-shaped preference
    // is written back WHOLE from local state. So: create a group on the phone,
    // then rename a different one in the desktop tab that has been open since
    // morning, and the PUT carries the morning array — the new group is gone
    // from the account, on both devices, with no error. Same shape wipes a theme
    // saved on another device.
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(subscribe).toHaveBeenCalled())
    await waitFor(() => expect(m.getSettings).toHaveBeenCalledTimes(1))
    const listsBefore = m.lists.mock.calls.length

    // The other device changed something.
    m.getSettings.mockResolvedValue({ task_groups: [{ id: 'g2', name: 'From the phone', lists: [] }] })
    await act(async () => {
      emit()('settings_updated')
      await new Promise((r) => setTimeout(r, 400))
    })

    await waitFor(() => expect(m.getSettings).toHaveBeenCalledTimes(2))
    // ...and still no task/event refetch, which is what the early return was for.
    expect(m.lists.mock.calls.length).toBe(listsBefore)
  })
})

describe('<App> clock setting', () => {
  it('opens on 12-hour and cycles to 24-hour, persisting the choice', async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
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
    await openSettings('General')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '12- or 24-hour clock' })).toHaveTextContent('24-hour'))
  })

  it('falls back to 12-hour when the stored value is junk', async () => {
    // The blob is hand-editable, so an unknown token has to degrade to the
    // default rather than reaching a formatter.
    m.getSettings.mockResolvedValue({ time_format: 'H:mm' } as never)
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    expect(screen.getByRole('button', { name: '12- or 24-hour clock' })).toHaveTextContent('12-hour')
  })
})

describe('<App> calendar window setting', () => {
  const open = async () => {
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('Calendar')
    return screen.getByRole('button', { name: 'Fixed or dynamic calendar grid' })
  }

  it('opens on the shape the grid has always had, and cycles', async () => {
    const row = await open()
    expect(row).toHaveTextContent('Dynamic')
    await userEvent.click(row)
    expect(row).toHaveTextContent('Fixed')
    await waitFor(() => expect(m.putSettings).toHaveBeenCalledWith({ calendar_fit: 'fixed' }))
    await userEvent.click(row)
    expect(row).toHaveTextContent('Dynamic')
    expect(m.putSettings).toHaveBeenLastCalledWith({ calendar_fit: 'dynamic' })
  })

  it('restores a stored choice', async () => {
    m.getSettings.mockResolvedValue({ calendar_fit: 'fixed' })
    await waitFor(async () => expect(await open()).toHaveTextContent('Fixed'))
  })

  it('falls back to dynamic when the stored value is junk', async () => {
    // Hand-editable blob: an unknown token degrades to the shipped shape rather
    // than reaching the grid as a class nothing styles.
    m.getSettings.mockResolvedValue({ calendar_fit: 'squeeze' } as never)
    expect(await open()).toHaveTextContent('Dynamic')
  })
})

// ── a settings write that fails must not be swallowed ───────────────────────

describe('<App> day capacity', () => {
  // The wiring the Today tab's whole capacity feature rests on, and none of it
  // was asserted: `grep -rn 'day_capacity' src --include=*.test.tsx` returned
  // nothing. Three separable rules — how a stored value is READ, how a clear is
  // WRITTEN, and which of the two settings is merged.

  const capacityField = () =>
    screen.getByLabelText('Working time for the default working day')

  it('reads a stored capacity back into the field', async () => {
    m.getSettings.mockResolvedValue({ day_capacity_minutes: 300 })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    expect(capacityField()).toHaveValue('5h')
  })

  it('reads junk as "never said" rather than as a number nobody gave', async () => {
    // Every settings value is treated as hand-edited. A capacity read out of
    // junk would be a number the owner never stated, which is the one thing
    // this feature must not produce — so anything unusable falls back to unset,
    // and the tab simply says nothing about how full the day is.
    //
    // Note for anyone mutation-testing the guard: `typeof x === 'number'` is
    // REDUNDANT with `Number.isFinite(x)`, which already returns false for
    // every non-number (it does not coerce). Removing the typeof arm is an
    // equivalent mutant, not a hole in this test — the `>= 0` and `isFinite`
    // arms are the two that carry weight, and both fail here when dropped.
    // Cast at the boundary on purpose: these are values a hand-edited settings
    // blob can really hold, and the type says they cannot — which is exactly
    // why the runtime guard exists and has to be tested.
    for (const bad of ['300', null, NaN, Infinity, {}, [], true] as unknown[]) {
      cleanup()
      vi.clearAllMocks()
      m.me.mockResolvedValue({ authenticated: true, user: 'admin' })
      m.putSettings.mockResolvedValue({})
      m.getSettings.mockResolvedValue({ day_capacity_minutes: bad } as never)
      render(<App />)
      await screen.findByRole('button', { name: 'Tasks' })
      await openSettings('General')
      expect(capacityField(), JSON.stringify(bad)).toHaveValue('')
    }
  })

  it('reads a NEGATIVE stored value as "never said"', async () => {
    // -1 is the clear sentinel at rest: it is what a clear WRITES, so it is
    // what a later read has to find, and it has to come back as unset rather
    // than as a capacity of minus one minute.
    m.getSettings.mockResolvedValue({ day_capacity_minutes: -1 })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    expect(capacityField()).toHaveValue('')
  })

  it('keeps a deliberate zero, which is a real capacity', async () => {
    // "I am not working today" is a statement, and it has to survive every
    // falsy check between the settings blob and the field.
    m.getSettings.mockResolvedValue({ day_capacity_minutes: 0 })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    expect(capacityField()).toHaveValue('0m')
  })

  it('writes a typed capacity as minutes', async () => {
    m.getSettings.mockResolvedValue({})
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    await userEvent.type(capacityField(), '5h')
    await userEvent.tab()
    expect(m.putSettings).toHaveBeenCalledWith({ day_capacity_minutes: 300 })
  })

  it('spells a CLEAR as -1, because the server merge skips null', async () => {
    // `store.update_settings` merges shallowly and SKIPS None, so sending null
    // would leave the old value in place and the owner could never get back to
    // "never said" once they had said something. 0 cannot be the sentinel —
    // it is a real capacity.
    m.getSettings.mockResolvedValue({ day_capacity_minutes: 300 })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    await userEvent.clear(capacityField())
    await userEvent.tab()
    expect(m.putSettings).toHaveBeenCalledWith({ day_capacity_minutes: -1 })
  })

  it('sends the WHOLE weekday map, so one change cannot drop the rest', async () => {
    // The map is read-modify-write: the section rebuilds the entire object to
    // change one weekday. That is why `day_capacity_by_weekday` is on
    // MERGED_SETTINGS and `day_capacity_minutes` deliberately is not.
    m.getSettings.mockResolvedValue({ day_capacity_by_weekday: { mon: 240, fri: 180 } })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    await userEvent.type(screen.getByLabelText('Working time for Sun'), '2h')
    await userEvent.tab()
    expect(m.putSettings).toHaveBeenCalledWith({
      day_capacity_by_weekday: { mon: 240, fri: 180, sun: 120 },
    })
  })

  it('HOLDS a weekday write when the settings read failed, but not the default', async () => {
    // The reason `day_capacity_by_weekday` is on MERGED_SETTINGS and
    // `day_capacity_minutes` deliberately is not, and the only thing that makes
    // the distinction observable.
    //
    // When the read failed, local state is the empty default rather than the
    // account's real map — so writing the map back would send `{sun: 120}` and
    // silently delete every other weekday the account had. The scalar has no
    // such problem: it carries the value just typed, like `start_tab`, and
    // holding it would lose a change for nothing.
    m.getSettings.mockRejectedValue(new HttpError(500, 'nope'))
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await screen.findByText(/Couldn't load your preferences/i)
    await openSettings('General')

    await userEvent.type(screen.getByLabelText('Working time for Sun'), '2h')
    await userEvent.tab()
    expect(m.putSettings).not.toHaveBeenCalled()
    expect(await screen.findByText(/this change wasn't saved/i)).toBeInTheDocument()

    // The default still goes, because there is nothing of the account's to lose.
    await userEvent.type(capacityField(), '5h')
    await userEvent.tab()
    expect(m.putSettings).toHaveBeenCalledWith({ day_capacity_minutes: 300 })
  })

  it('drops a hand-edited weekday map to what it can actually use', async () => {
    m.getSettings.mockResolvedValue({
      day_capacity_by_weekday: { mon: 240, funday: 60, tue: '90', wed: -5 },
    } as never)
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    expect(screen.getByLabelText('Working time for Mon')).toHaveValue('4h')
    for (const day of ['Tue', 'Wed']) {
      expect(screen.getByLabelText(`Working time for ${day}`), day).toHaveValue('')
    }
  })
})

describe('<App> settings writes', () => {
  it('returns to the login form when the session has expired', async () => {
    // These were `.catch(() => {})`, which ate an AuthError as happily as an
    // offline blip: the tab kept accepting preference changes, never fell back
    // to the login form, and lost every one of them on the next reload.
    m.putSettings.mockRejectedValue(new AuthError('unauthenticated'))
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    await userEvent.click(screen.getByRole('button', { name: 'Move Calendar left' }))
    expect(await screen.findByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('surfaces a rejection from a server it did reach', async () => {
    m.putSettings.mockRejectedValue(new HttpError(422, 'dashboard.0.h: less than or equal to 40'))
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    await userEvent.click(screen.getByRole('button', { name: 'Move Calendar left' }))
    expect(await screen.findByText(/couldn't save your preferences/i)).toBeInTheDocument()
  })

  it('stays quiet when the request never reached a server', async () => {
    // Offline is ordinary and the local state stands in fine.
    m.putSettings.mockRejectedValue(new TypeError('Failed to fetch'))
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    await userEvent.click(screen.getByRole('button', { name: 'Move Calendar left' }))
    await waitFor(() => expect(m.putSettings).toHaveBeenCalled())
    expect(screen.queryByText(/couldn't save/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /sign in/i })).not.toBeInTheDocument()
  })
})

// ── the settings refetch, and the two things it must not disturb ────────────
// `settings_updated` re-runs the settings effect. That effect does more than
// load values: it also RESTORES THE OPENING TAB. Both cases below are about the
// difference between "read the account again" and "boot again".

describe('<App> settings refetch', () => {
  const emit = () => vi.mocked(subscribe).mock.calls[0][0]
  const active = () => document.querySelector('.tabs .tab.active')?.textContent ?? null

  it('does not follow another device onto its tab', async () => {
    // Switching tabs on the phone writes `last_tab` and publishes to every
    // subscriber. On the desktop tab the restore is guarded by `tabTouched`,
    // which is false for a tab the user simply has not switched — so the guard
    // did not hold and the open desktop view jumped to whatever the phone was
    // showing, with `cacheTab` persisting the jump for the next reload.
    m.getSettings.mockResolvedValue({ start_tab: 'last', last_tab: 'calendar' })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(active()).toBe('Calendar'))
    await waitFor(() => expect(subscribe).toHaveBeenCalled())

    m.getSettings.mockResolvedValue({ start_tab: 'last', last_tab: 'tasks' })
    await act(async () => {
      emit()('settings_updated')
      await new Promise((r) => setTimeout(r, 400))
    })

    await waitFor(() => expect(m.getSettings).toHaveBeenCalledTimes(2))
    expect(active()).toBe('Calendar')
    expect(localStorage.getItem(TAB_KEY)).toBe('calendar')
  })

  it('holds the re-read until its own write has landed', async () => {
    // The server publishes to the writer too, so the event that arrives right
    // after a preference change is usually this tab's own — and re-reading
    // mid-flight paints the value the write is about to replace. The guard was
    // `pendingPatch`, which is emptied when the PUT is ISSUED, so the whole
    // flight of the request looked idle.
    let land: (() => void) | undefined
    m.putSettings.mockImplementation(() => new Promise((res) => { land = () => res({}) }))
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(subscribe).toHaveBeenCalled())
    await waitFor(() => expect(m.getSettings).toHaveBeenCalledTimes(1))

    await openSettings('General')
    await userEvent.click(screen.getByRole('button', { name: '12- or 24-hour clock' }))
    await waitFor(() => expect(m.putSettings).toHaveBeenCalled())

    await act(async () => {
      emit()('settings_updated')
      await new Promise((r) => setTimeout(r, 400))
    })
    expect(m.getSettings).toHaveBeenCalledTimes(1)

    // ...and the moment it lands, the re-read goes ahead. Waiting must not mean
    // dropping: this is the only path that re-reads settings, and the event may
    // have been another device's.
    await act(async () => {
      land!()
      await new Promise((r) => setTimeout(r, 500))
    })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalledTimes(2))
  })
})

// ── the settings read must not undo a gesture it raced ──────────────────────
// The gear is clickable the instant `/api/me` returns — the same commit that
// ISSUES `api.getSettings()` — so the whole read RTT is a window in which the
// user can change a preference. `get_settings` takes the backend's single global
// service lock, which is also held across CalDAV round trips during a sync
// sweep, so that window is seconds. The read applied its payload
// unconditionally; the author had guarded exactly one field (`tabTouched`, for
// the tab) and every other setter clobbered whatever had just been chosen.

describe('<App> a slow settings read', () => {
  /** Render with `getSettings` held open; returns the resolver. */
  const holdSettings = (answer: object) => {
    let release!: () => void
    m.getSettings.mockImplementation(() => new Promise((res) => {
      release = () => res(answer as never)
    }))
    render(<App />)
    return () => release()
  }

  it('does not revert a preference the user changed while it was in flight', async () => {
    // The finding's own reproduction. The account holds 12h; the user cycles the
    // clock to 24h during the read; the read then answers with the pre-click
    // value. The write landed, so the account holds 24h — and the row used to
    // snap back to "12-hour", after which the next click cycled from a value
    // nobody had.
    const release = holdSettings({ time_format: '12h' })
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    const clock = screen.getByRole('button', { name: '12- or 24-hour clock' })
    await userEvent.click(clock)
    expect(clock).toHaveTextContent('24-hour')
    await waitFor(() => expect(m.putSettings).toHaveBeenCalledWith({ time_format: '24h' }))

    await act(async () => { release(); await Promise.resolve() })

    expect(clock, 'the stale read reverted a preference the account already holds')
      .toHaveTextContent('24-hour')
  })

  it('still applies every preference the user did NOT touch', async () => {
    // The control. A guard that held back the whole payload would satisfy the
    // case above and lose the account's settings on every boot.
    const release = holdSettings({ time_format: '12h', session_ttl_s: 30 * 24 * 3600 })
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('General')
    await userEvent.click(screen.getByRole('button', { name: '12- or 24-hour clock' }))

    await act(async () => { release(); await Promise.resolve() })

    // Only the UNTOUCHED preference is asserted here — that is what makes this a
    // control. It passes against the pre-fix tree too, so a `keep` that held
    // back the whole payload would show up as this test failing and the one
    // above passing, rather than as both going green.
    // The menu is already open — `openSettings` would toggle it shut.
    await userEvent.click(screen.getByRole('tab', { name: 'Account' }))
    expect(screen.getByRole('button', { name: 'How long to stay signed in' }),
      'a preference the user never touched was held back too')
      .toHaveTextContent('30 days')
  })

  it('guards every key it reads, so the next preference cannot be forgotten', async () => {
    // The pattern this sweep kept finding: a guard is only as wide as the set it
    // enumerates. `tabTouched` guarded one field out of twenty-three because it
    // was written per-field. `keep` is per-field too — so this is the check that
    // adding a preference and forgetting it is a failure rather than a silent
    // revert.
    const load = (import.meta as unknown as {
      glob: (p: string, o: object) => Record<string, () => Promise<string>>
    }).glob('./App.tsx', { query: '?raw', import: 'default' })['./App.tsx']
    const src = await load()
    const from = src.indexOf('const writesBefore')
    const to = src.indexOf('.catch((e) =>', from)
    expect(from, 'could not locate the settings read — rename the markers here too')
      .toBeGreaterThan(-1)
    const body = src.slice(from, to)
    const read = new Set([...body.matchAll(/\bs\.([a-z_]+)/g)].map((mm) => mm[1]))
    const kept = new Set([...body.matchAll(/keep\('([a-z_]+)'\)/g)].map((mm) => mm[1]))
    expect(read.size, 'no payload keys found — the markers have drifted').toBeGreaterThan(15)
    expect([...read].filter((k) => !kept.has(k)),
      'these settings keys are applied with no `keep` guard, so a read that '
      + 'lands after the user changed them silently reverts the gesture')
      .toEqual([])
  })
})
