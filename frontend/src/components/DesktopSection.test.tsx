// The Appearance section that only exists inside a desktop client — and which
// had no test at all, on either platform.
//
// Two things make it worth one now. It is the only place in the app whose COPY
// depends on which operating system is on the other end of the bridge, and
// getting that wrong is not a crash: it is a Linux user being told to check
// their Start menu. And it reconciles optimistically, so a regression that
// dropped the host's answer would look right on click and be wrong a moment
// later — the state the eye never catches.

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DesktopSection } from './DesktopSection'
import { readState, setIcon, setTitleBar, type DesktopState } from '../desktop'

vi.mock('../desktop', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../desktop')>()
  return { ...mod, readState: vi.fn(), setIcon: vi.fn(), setTitleBar: vi.fn() }
})

const host = (over: Partial<DesktopState> = {}): DesktopState => ({
  available: true,
  choice: 'Auto',
  resolved: 'Ink',
  systemUsesLightTheme: true,
  startMenuShortcut: false,
  captionColour: true,
  systemTitleBar: false,
  ...over,
} as DesktopState)

beforeEach(() => {
  vi.clearAllMocks()
  cleanup()
  vi.mocked(setIcon).mockResolvedValue(null)
  vi.mocked(setTitleBar).mockResolvedValue(null)
})

describe('outside a desktop client', () => {
  it('renders nothing at all rather than an empty section', async () => {
    // Absent, not hidden. In a browser /desktop/state 404s and readState
    // resolves to null, and a settings heading with nothing under it would be
    // a thing every web user could see and no desktop user ever would.
    vi.mocked(readState).mockResolvedValue(null)
    const { container } = render(<DesktopSection />)
    await waitFor(() => expect(readState).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})

describe('inside the Windows client', () => {
  it('names the Start menu and the Windows theme', async () => {
    // An absent `platform` key IS the Windows case — the client has never sent
    // one — so this is also the assertion that the new key did not change what
    // every installed exe shows.
    vi.mocked(readState).mockResolvedValue(host())
    render(<DesktopSection />)

    expect(await screen.findByLabelText('Start menu shortcut')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Follow the Windows theme' })).toBeInTheDocument()
    expect(screen.getByText(/taskbar button shows a grouped icon/)).toBeInTheDocument()
    expect(screen.getByText(/Windows is currently light/)).toBeInTheDocument()
  })

  it('says so when the build can only be told light or dark', async () => {
    vi.mocked(readState).mockResolvedValue(host({ captionColour: false }))
    render(<DesktopSection />)
    expect(await screen.findByText(/only supports a light or dark title bar/)).toBeInTheDocument()
  })

  it('drops that sentence once the caption has been handed back', async () => {
    // What Windows 10 could have been told is not worth a line when it is not
    // being told anything — and leaving it there reads as the setting having
    // failed rather than having been obeyed.
    vi.mocked(readState).mockResolvedValue(
      host({ captionColour: false, systemTitleBar: true }))
    render(<DesktopSection />)
    await screen.findByLabelText('System title bar')
    expect(screen.queryByText(/only supports a light or dark title bar/)).not.toBeInTheDocument()
  })

  it('does not promise a restart Windows does not need', async () => {
    vi.mocked(readState).mockResolvedValue(host())
    render(<DesktopSection />)
    await screen.findByLabelText('System title bar')
    expect(screen.getByText(/the colour Windows draws it/)).toBeInTheDocument()
    expect(screen.queryByText(/next time Smylte starts/)).not.toBeInTheDocument()
  })
})

describe('inside the Linux client', () => {
  it('names the applications menu and the system theme instead', async () => {
    vi.mocked(readState).mockResolvedValue(host({ platform: 'linux', canPin: true }))
    render(<DesktopSection />)

    expect(await screen.findByLabelText('Applications menu entry')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Follow the system theme' })).toBeInTheDocument()
    expect(screen.getByText(/applications grid and to search/)).toBeInTheDocument()
    expect(screen.getByText(/The system is currently light/)).toBeInTheDocument()

    // And none of the Windows wording survives, which is the half a
    // half-finished platform switch would leave behind.
    expect(screen.queryByText(/taskbar/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Start menu/)).not.toBeInTheDocument()
    expect(screen.queryByText(/only supports a light or dark title bar/)).not.toBeInTheDocument()
  })

  it('states the trade and the restart, which Windows has neither of', async () => {
    // The two halves a Linux reader has to be told, because both are
    // surprising: the app background stops reaching the strip (they are
    // exclusive — nothing on X11 or Wayland tints a frame the client did not
    // draw), and nothing visibly happens until the client is restarted.
    vi.mocked(readState).mockResolvedValue(host({ platform: 'linux', canPin: true }))
    render(<DesktopSection />)

    await screen.findByLabelText('System title bar')
    expect(screen.getByText(/window manager draw the title bar/)).toBeInTheDocument()
    expect(screen.getByText(/next time Smylte starts/)).toBeInTheDocument()
    expect(screen.queryByText(/the colour Windows draws it/)).not.toBeInTheDocument()
  })

  it('keeps the plate names, which are colours and not operating systems', async () => {
    vi.mocked(readState).mockResolvedValue(host({ platform: 'linux' }))
    render(<DesktopSection />)
    expect(await screen.findByRole('option', { name: 'Cream plate' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Bare mark' })).toBeInTheDocument()
  })

  it('explains the missing pin under Wayland, where the float window cannot say so', async () => {
    // The floating window has no room for a sentence — its whole geometry
    // contract is 420x280 down to 320x200 — so the explanation lives here.
    vi.mocked(readState).mockResolvedValue(host({ platform: 'linux', canPin: false }))
    render(<DesktopSection />)
    expect(await screen.findByText(/Wayland session/)).toBeInTheDocument()
    expect(screen.getByText(/"Backend": "x11"/)).toBeInTheDocument()
  })

  it('says nothing about pinning when the host can pin', async () => {
    vi.mocked(readState).mockResolvedValue(host({ platform: 'linux', canPin: true }))
    render(<DesktopSection />)
    await screen.findByLabelText('Applications menu entry')
    expect(screen.queryByText(/Wayland session/)).not.toBeInTheDocument()
  })
})

describe('the title bar', () => {
  it('is not offered at all by a client that has never heard of it', async () => {
    // The web build updates itself on every launch and the client does not, so
    // this page routinely runs inside an older one. An absent key is that
    // client, and a checkbox it cannot answer is worse than no checkbox: it
    // would render unchecked, POST to a route that 404s, and stay unchecked.
    const { systemTitleBar: _omitted, ...older } = host()
    vi.mocked(readState).mockResolvedValue(older as DesktopState)
    render(<DesktopSection />)

    await screen.findByLabelText('App icon')
    expect(screen.queryByLabelText('System title bar')).not.toBeInTheDocument()
    expect(screen.queryByText(/the colour Windows draws it/)).not.toBeInTheDocument()
  })

  it('applies at once and then takes the host answer over its own guess', async () => {
    const user = userEvent.setup()
    vi.mocked(readState).mockResolvedValue(host({ platform: 'linux', canPin: true }))
    // Answered with the theme flipped, which is a value only the host can
    // compute — so its arrival is the only observable proof of the reconcile,
    // the same trick the icon test below uses.
    vi.mocked(setTitleBar).mockResolvedValue(host({
      platform: 'linux', canPin: true, systemTitleBar: true, systemUsesLightTheme: false }))

    render(<DesktopSection />)
    const toggle = await screen.findByLabelText('System title bar')
    expect((toggle as HTMLInputElement).checked).toBe(false)

    await user.click(toggle)
    expect(setTitleBar).toHaveBeenCalledWith(true)
    expect((toggle as HTMLInputElement).checked).toBe(true)
    await waitFor(() =>
      expect(screen.getByText(/The system is currently dark/)).toBeInTheDocument())
  })

  it('sends false when it is being turned back off', async () => {
    // Absent and false must not read the same on this route — the host answers
    // 400 rather than guessing — so the page has to send the boolean either way.
    const user = userEvent.setup()
    vi.mocked(readState).mockResolvedValue(host({ systemTitleBar: true }))
    render(<DesktopSection />)

    await user.click(await screen.findByLabelText('System title bar'))
    expect(setTitleBar).toHaveBeenCalledWith(false)
  })

  it('does not disturb the icon choice', async () => {
    // Two routes, two settings. A toggle that re-sent the icon would carry
    // whatever the page last believed, which is how a stale flag deletes a
    // launcher entry.
    const user = userEvent.setup()
    vi.mocked(readState).mockResolvedValue(host({ platform: 'linux', startMenuShortcut: true }))
    render(<DesktopSection />)

    await user.click(await screen.findByLabelText('System title bar'))
    expect(setIcon).not.toHaveBeenCalled()
  })
})

describe('choosing', () => {
  it('applies at once and then takes the host answer over its own guess', async () => {
    // `resolved` is the host's to compute — it depends on the system theme —
    // so the optimistic update deliberately does not try, and the reconcile is
    // what makes the hint correct. A regression that dropped the answer would
    // look right on click and be wrong one paint later.
    const user = userEvent.setup()
    vi.mocked(readState).mockResolvedValue(host({ platform: 'linux', canPin: true }))
    vi.mocked(setIcon).mockResolvedValue(
      host({ platform: 'linux', canPin: true, choice: 'Auto', resolved: 'Paper',
             startMenuShortcut: true, systemUsesLightTheme: false }))

    render(<DesktopSection />)
    const shortcut = await screen.findByLabelText('Applications menu entry')

    // Before the click the hint says light, which is what the first read said.
    expect(screen.getByText(/The system is currently light/)).toBeInTheDocument()
    await user.click(shortcut)
    expect(setIcon).toHaveBeenCalledWith('Auto', true)

    // The toggle flipped optimistically, but the THEME sentence could not — it
    // is derived from a value only the host has. That it changes is the
    // reconcile, and it is the only observable proof the answer was taken.
    await waitFor(() =>
      expect(screen.getByText(/The system is currently dark/)).toBeInTheDocument())
    expect((shortcut as HTMLInputElement).checked).toBe(true)
  })

  it('sends the chosen variant with the shortcut flag it already had', async () => {
    const user = userEvent.setup()
    vi.mocked(readState).mockResolvedValue(host({ startMenuShortcut: true }))
    render(<DesktopSection />)

    const select = await screen.findByLabelText('App icon')
    await user.selectOptions(select, 'Mark')
    // Both fields on every call: the route takes them together, and sending a
    // stale flag would silently turn somebody's launcher off.
    expect(setIcon).toHaveBeenCalledWith('Mark', true)
  })
})
