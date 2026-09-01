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

  it('does not offer an e-ink screen an interval its glass forbids', async () => {
    // The panel makers rate these at one refresh per 180s and require them to
    // sleep in between; the alternative damages them permanently. "Every
    // minute" on an e-ink display is the app recommending its own destruction.
    m.displays.mockResolvedValue([{ ...DISPLAY, palette: 'eink' }] as never)
    m.patchDisplay.mockImplementation(((_t: string, body: object) =>
      Promise.resolve({ ...DISPLAY, palette: 'eink', ...body })) as never)
    const { unmount } = mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    expect(screen.getByText(/three minutes is the floor on e-ink/i)).toBeInTheDocument()

    // Cycling from 5 minutes lands on 15, never on 1.
    await userEvent.click(screen.getByRole('button', { name: 'Every 5 minutes' }))
    expect(m.patchDisplay).toHaveBeenCalledWith('tok-hallway', { refresh_seconds: 900 })
    unmount()

    // A colour screen is a backlight and keeps the minute, with no lecture.
    m.displays.mockResolvedValue([DISPLAY] as never)
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    expect(screen.queryByText(/three minutes is the floor/i)).not.toBeInTheDocument()
  })

  it('points an e-ink screen at the raw framebuffer, not the PNG', async () => {
    // A microcontroller has no PNG decoder. Handing it the .png would be asking
    // a board with 520KB to grow a zlib inflater and five unfilters first.
    m.displays.mockResolvedValue([{ ...DISPLAY, palette: 'eink' }] as never)
    const { unmount } = mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    expect(screen.getByText(new RegExp(`${DISPLAY.token}\\.bin`))).toBeInTheDocument()
    unmount()

    m.displays.mockResolvedValue([DISPLAY] as never)
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    expect(screen.getByText(new RegExp(`${DISPLAY.token}\\.png`))).toBeInTheDocument()
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

  it('cycles through all three modes and writes the one it lands on', async () => {
    m.displays.mockResolvedValue([DISPLAY] as never)
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    // One `.menu-toggle` showing the current value, cycled — the same control
    // the rotation and the refresh interval beside it already are. A mode that
    // could not be reached here would be a feature with no way in.
    await userEvent.click(screen.getByRole('button', { name: /the month/i }))
    expect(m.patchDisplay).toHaveBeenCalledWith('tok-hallway', { mode: 'habits' })

    m.displays.mockResolvedValue([{ ...DISPLAY, mode: 'habits' }] as never)
    cleanup()
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    await userEvent.click(screen.getByRole('button', { name: /habits \+ today/i }))
    expect(m.patchDisplay).toHaveBeenCalledWith('tok-hallway', { mode: 'now' })

    m.displays.mockResolvedValue([{ ...DISPLAY, mode: 'now' }] as never)
    cleanup()
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    // And back round: three values, not a one-way door.
    await userEvent.click(screen.getByRole('button', { name: /now \+ next/i }))
    expect(m.patchDisplay).toHaveBeenCalledWith('tok-hallway', { mode: 'calendar' })
  })

  it('states what the rolling mode costs, beside the interval it costs it in', async () => {
    m.displays.mockResolvedValue([{ ...DISPLAY, mode: 'now' }] as never)
    const { unmount } = mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    // The honest caveat, on the screen where the choice is made rather than in
    // a README: this face moves on the panel's next refresh, not on the tick.
    expect(screen.getByText(/on this screen’s next refresh/i)).toBeInTheDocument()
    unmount()

    m.displays.mockResolvedValue([DISPLAY] as never)
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    expect(screen.queryByText(/on this screen’s next refresh/i)).not.toBeInTheDocument()
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
    cleanup()

    // And not on a `now` display: that face has no done rows to hide — they are
    // simply behind the cursor — so the switch would be a control over nothing.
    m.displays.mockResolvedValue([{ ...DISPLAY, mode: 'now' }] as never)
    mount()
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    expect(screen.queryByText(/hide habits once done/i)).not.toBeInTheDocument()
    // It IS offered lists, because its queue is scoped by the same allowlist
    // the habits face is.
    expect(screen.getByText(/which lists/i)).toBeInTheDocument()
  })
})

// ── the allowlist, and the rollback ─────────────────────────────────────────
//
// Both decide what an unauthenticated display URL reaches, and both had exactly
// one test apiece pointed at the input shape where the bug does not fire.

/** Open the editor on the first row. With more than one display on screen
 *  there is a "Set up" per row, so the first is named rather than assumed. */
const openEditor = async () => {
  const buttons = await screen.findAllByRole('button', { name: /set up/i })
  await userEvent.click(buttons[0])
}

describe('the calendars a display is allowed to show', () => {
  it('refuses to turn off the last one rather than writing "everything"', async () => {
    // An emptied allowlist is indistinguishable from an unset one, and unset
    // means EVERYTHING — so writing [] here would do the exact opposite of what
    // the click says and light every chip the owner had just turned off.
    m.displays.mockResolvedValue([{ ...DISPLAY, calendars: ['work'] }] as never)
    mount()
    await openEditor()
    const work = await screen.findByRole('button', { name: 'Work', pressed: true })
    expect(work).toBeDisabled()
    await userEvent.click(work)
    expect(m.patchDisplay).not.toHaveBeenCalled()
  })

  it('collapses to "everything" by set membership, not by length', async () => {
    // An allowlist carrying an id that is no longer on offer — a calendar since
    // deleted or archived — used to match the LENGTH of the offered set while
    // excluding one of it. The click then turned that excluded calendar back
    // on, and the chip stayed lit as though nothing had happened.
    m.displays.mockResolvedValue([
      { ...DISPLAY, calendars: ['gone-from-the-server'] },
    ] as never)
    m.patchDisplay.mockImplementation(async (_t, body) =>
      ({ ...DISPLAY, ...body }) as never)
    mount()
    await openEditor()
    // Both offered calendars are currently OFF: the stored allowlist holds one
    // id, and it is not either of them.
    expect(await screen.findByRole('button', { name: 'Work', pressed: false }))
      .toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Home', pressed: false }))
      .toBeInTheDocument()
    // Turning Work ON makes the list two ids long — the same LENGTH as the two
    // calendars on offer, which is what used to collapse it to [] and quietly
    // turn Home on as well.
    await userEvent.click(screen.getByRole('button', { name: 'Work' }))
    expect(m.patchDisplay).toHaveBeenCalledWith('tok-hallway', {
      calendars: ['gone-from-the-server', 'work'],
    })
    await waitFor(() => expect(
      screen.getByRole('button', { name: 'Home' })).toHaveAttribute('aria-pressed', 'false'))
  })

  it('does not offer an archived calendar as a source', async () => {
    // `api.calendars()` returns archived calendars — the backend never filters,
    // which is what ArchivedCalendarsSection relies on — but the frame builder
    // drops them. Offering one drew a chip lit up as something the wall panel
    // was showing when it was not.
    m.displays.mockResolvedValue([DISPLAY] as never)
    render(<DisplaysSection onExpire={vi.fn()} archived={['home']} />)
    await openEditor()
    expect(await screen.findByRole('button', { name: 'Work' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Home' })).toBeNull()
  })
})

describe('a write that the server refuses', () => {
  it('puts the name back rather than leaving the refused value on screen', async () => {
    // The draft used to live in `rows`, so the rollback snapshot was taken
    // AFTER the keystrokes — restoring exactly the value the server had just
    // refused, with no way back but a reload.
    m.displays.mockResolvedValue([DISPLAY] as never)
    m.patchDisplay.mockRejectedValue(new HttpError(422, 'no'))
    mount()
    await openEditor()
    const field = await waitFor(() => screen.getByLabelText<HTMLInputElement>('Name', { selector: '#disp-name-tok-hallway' }))
    await userEvent.clear(field)
    await userEvent.type(field, 'Kitchen')
    await userEvent.tab()
    await waitFor(() => expect(m.patchDisplay).toHaveBeenCalled())
    await waitFor(() => expect(field).toHaveValue('Hallway'))
  })

  it('puts an emptied name back instead of writing nothing and showing nothing',
    async () => {
      // Refusing the write was right; leaving the field and the list row blank
      // while the server still held the old name was not. The name is what is
      // drawn on the panel, so the owner was left believing they had wiped it.
      m.displays.mockResolvedValue([DISPLAY] as never)
      mount()
      await openEditor()
      const field = await waitFor(() => screen.getByLabelText<HTMLInputElement>('Name', { selector: '#disp-name-tok-hallway' }))
      await userEvent.clear(field)
      await userEvent.tab()
      expect(m.patchDisplay).not.toHaveBeenCalled()
      await waitFor(() => expect(field).toHaveValue('Hallway'))
    })

  it('rolls back only its own row, not every change made meanwhile', async () => {
    // Restoring a snapshot of the whole array discarded anything else that
    // landed while the write was in flight — including a delete.
    const other: Display = { ...DISPLAY, token: 'tok-kitchen', name: 'Kitchen' }
    m.displays.mockResolvedValue([DISPLAY, other] as never)
    let release: (v: unknown) => void = () => {}
    m.patchDisplay.mockImplementation(
      () => new Promise((_ok, fail) => { release = () => fail(new HttpError(422, 'no')) }))
    m.deleteDisplay.mockResolvedValue(null as never)
    mount()
    await openEditor()          // opens the FIRST row, Hallway
    // Start a write on Hallway that will fail...
    await userEvent.click(await screen.findByRole('button', { name: '0°' }))
    // ...and delete Kitchen while it is still in flight.
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }))
    await userEvent.click(screen.getByRole('button', { name: /delete display/i }))
    await waitFor(() => expect(m.deleteDisplay).toHaveBeenCalledWith('tok-hallway'))
    expect(screen.queryByText('Hallway')).toBeNull()
    // Now let the rotation fail. Its rollback must touch its own row only —
    // restoring the whole array would bring the deleted display back, with its
    // live token, on the one screen that can revoke one.
    release(null)
    await waitFor(() => expect(m.patchDisplay).toHaveBeenCalled())
    expect(screen.queryByText('Hallway')).toBeNull()
    expect(screen.getByText('Kitchen')).toBeInTheDocument()
  })
})
