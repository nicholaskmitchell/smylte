// Settings → Displays: the only screen that shows which tokens reach this
// account's calendar without a session, and the only place one can be rotated
// or revoked. Shaped after ConnectionsSection's suite for the same reason the
// component is shaped after ConnectionsSection: they are the same kind of
// object, and a regression in either is silent by construction — the component
// renders confident prose in every state.

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DisplaysSection } from './DisplaysSection'
import { api, HttpError, type Display } from '../api'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked }
})

const m = vi.mocked(api)

const DISPLAY: Display = {
  token: 'tok-hallway', name: 'Hallway', mode: 'calendar', palette: 'color',
  calendars: [], lists: [], hide_done_habits: true, hide_done_tasks: true,
  refresh_seconds: 300, panel_width: null, panel_height: null, rotation: 0,
  panel_too_small: null, enabled: true, last_seen_at: null,
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z',
}

const CALS = [{ id: 'work', name: 'Work' }, { id: 'home', name: 'Home' }]

beforeEach(() => {
  vi.clearAllMocks()
  cleanup()
  m.calendars.mockResolvedValue(CALS as never)
  m.lists.mockResolvedValue([{ id: 'inbox', name: 'Inbox' }] as never)
})

const mount = (onExpire = vi.fn()) => render(<DisplaysSection onExpire={onExpire} />)

describe('<DisplaysSection>', () => {
  it('lists a display with what it shows and whether it has ever connected',
    async () => {
      m.displays.mockResolvedValue([DISPLAY] as never)
      mount()
      expect(await screen.findByText('Hallway')).toBeInTheDocument()
      expect(screen.getByText('The month')).toBeInTheDocument()
      // `last_seen_at` is the only thing recorded about the device, and it
      // exists to answer exactly this: has that screen gone dark?
      expect(screen.getByText(/never connected/i)).toBeInTheDocument()
    })

  it('says the account has no displays only when it really has none', async () => {
    m.displays.mockResolvedValue([] as never)
    const { unmount } = mount()
    expect(await screen.findByText(/no displays yet/i)).toBeInTheDocument()
    unmount()

    // A failed fetch is not an empty account. Saying "none" over a 502 is a
    // confident lie on the one screen that can revoke a live token.
    m.displays.mockRejectedValue(new HttpError(502, 'bad gateway'))
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn’t load/i)
    expect(screen.queryByText(/no displays yet/i)).not.toBeInTheDocument()
  })

  it('shows the URL to point a screen at, and warns what it is', async () => {
    m.displays.mockResolvedValue([DISPLAY] as never)
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    expect(screen.getByText(`${location.origin}/display/tok-hallway`))
      .toBeInTheDocument()
    // The honest caveat, on screen rather than in a comment: this URL is a
    // password in a browser's address bar.
    expect(screen.getByText(/is a password in a browser’s address bar/i))
      .toBeInTheDocument()
  })

  it('rotating a token keeps the display and re-keys the URL shown', async () => {
    m.displays.mockResolvedValue([DISPLAY] as never)
    m.rotateDisplayToken.mockResolvedValue(
      { ...DISPLAY, token: 'tok-fresh', last_seen_at: null } as never)
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    await userEvent.click(screen.getByRole('button', { name: /new url/i }))
    await waitFor(() => {
      expect(screen.getByText(`${location.origin}/display/tok-fresh`))
        .toBeInTheDocument()
    })
    // The editor follows the new key rather than collapsing — the row's
    // identity IS the token.
    expect(screen.getByText('Hallway')).toBeInTheDocument()
  })

  it('deleting asks first, then removes the row', async () => {
    m.displays.mockResolvedValue([DISPLAY] as never)
    m.deleteDisplay.mockResolvedValue(null as never)
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }))
    expect(m.deleteDisplay).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: /delete display/i }))
    await waitFor(() => expect(m.deleteDisplay).toHaveBeenCalledWith('tok-hallway'))
    expect(screen.queryByText('Hallway')).not.toBeInTheDocument()
  })

  it('puts a failed edit back rather than leaving the row claiming it landed',
    async () => {
      m.displays.mockResolvedValue([DISPLAY] as never)
      m.patchDisplay.mockRejectedValue(new HttpError(500, 'nope'))
      mount()
      await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
      await userEvent.click(screen.getByRole('button', { name: 'The month' }))
      await waitFor(() => expect(m.patchDisplay).toHaveBeenCalled())
      // Painted immediately, rolled back on failure — the same contract every
      // other write in the app keeps.
      await waitFor(() => {
        expect(screen.getAllByText('The month').length).toBeGreaterThan(0)
      })
    })

  it('toggling one calendar off materializes the allowlist first', async () => {
    m.displays.mockResolvedValue([DISPLAY] as never)
    m.patchDisplay.mockImplementation(((_t: string, body: object) =>
      Promise.resolve({ ...DISPLAY, ...body })) as never)
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    await userEvent.click(screen.getByRole('button', { name: 'Home' }))
    // An empty allowlist means EVERYTHING, so turning one calendar off has to
    // write the rest explicitly — otherwise the first click would turn them all
    // off at once.
    expect(m.patchDisplay).toHaveBeenCalledWith('tok-hallway', { calendars: ['work'] })
  })

  it('lets a panel size be typed, digit by digit, without being rejected',
    async () => {
      m.displays.mockResolvedValue([DISPLAY] as never)
      m.patchDisplay.mockImplementation(((_t: string, body: object) =>
        Promise.resolve({ ...DISPLAY, ...body })) as never)
      mount()
      await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
      const width = screen.getByLabelText('Panel size')
      await userEvent.type(width, '800')
      // Nothing is written on the way: "800" passes through 8 and 80, the
      // server floors a panel at 100, and a per-keystroke write 422'd twice and
      // rolled the field back under the cursor.
      expect(m.patchDisplay).not.toHaveBeenCalled()
      await userEvent.tab()
      expect(m.patchDisplay).toHaveBeenCalledWith('tok-hallway', { panel_width: 800 })
    })

  it('warns when the panel is too small for the month it is set to show',
    async () => {
      // Answered by the renderer, never recomputed here — a 2.9" panel is a
      // 39px column and seven of those is a smear. Said beside the size field,
      // because the alternative is finding out on a wall in another room.
      m.displays.mockResolvedValue(
        [{ ...DISPLAY, panel_width: 296, panel_height: 128, panel_too_small: true }] as never)
      const { unmount } = mount()
      await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
      expect(screen.getByRole('alert')).toHaveTextContent(/too small for a month/i)
      unmount()

      // And stays quiet when there is nothing to judge.
      m.displays.mockResolvedValue([DISPLAY] as never)
      mount()
      await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    })

  it('adds a display and opens it, because a new one is useless unpaired',
    async () => {
      m.displays.mockResolvedValue([] as never)
      m.createDisplay.mockResolvedValue({ ...DISPLAY, name: 'Kitchen' } as never)
      mount()
      await screen.findByText(/no displays yet/i)
      await userEvent.type(screen.getByLabelText('Name'), 'Kitchen')
      await userEvent.click(screen.getByRole('button', { name: /^add$/i }))
      await waitFor(() => expect(m.createDisplay).toHaveBeenCalledWith({ name: 'Kitchen' }))
      // Straight into the editor: the URL to point a panel at is inside it.
      expect(await screen.findByText(`${location.origin}/display/tok-hallway`))
        .toBeInTheDocument()
    })

  it('offers the habits-only toggles only on a habits display', async () => {
    m.displays.mockResolvedValue([DISPLAY] as never)
    const { unmount } = mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    expect(screen.queryByText(/hide habits once done/i)).not.toBeInTheDocument()
    unmount()

    m.displays.mockResolvedValue([{ ...DISPLAY, mode: 'habits' }] as never)
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    expect(screen.getByText(/hide habits once done/i)).toBeInTheDocument()
    // The setting the whole habit-tracker idea rests on, and the reason it is
    // stated next to the switch.
    expect(screen.getByText(/getting shorter as the day goes/i)).toBeInTheDocument()
  })
})
