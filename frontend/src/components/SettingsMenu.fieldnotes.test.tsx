import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createRef } from 'react'
import { SettingsMenu } from './SettingsMenu'
import { api } from '../api'
import { DEFAULT_FOCUS } from '../focus'
import { DEFAULT_TAB_ORDER } from '../tabs'
import { readState, type DesktopState } from '../desktop'

// Settings under Field notes, the design that names things and does not
// explain them. The preset behaviour is SettingsMenu.test.tsx's, and is not
// repeated here.
vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked }
})
vi.mock('../desktop', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../desktop')>()
  return { ...mod, readState: vi.fn() }
})

const m = vi.mocked(api)

const stubMatchMedia = (matches: boolean) => {
  window.matchMedia = ((query: string) => ({
    matches, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

beforeEach(() => {
  vi.clearAllMocks()
  stubMatchMedia(false)
  // Before the render: `useFieldNotes` reads the attribute when it mounts.
  document.documentElement.setAttribute('data-surface', 'app')
  m.calendars.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
  vi.mocked(readState).mockResolvedValue(null)
})

afterEach(() => {
  document.documentElement.removeAttribute('data-surface')
})

function show(over: Partial<Parameters<typeof SettingsMenu>[0]> = {}) {
  render(<SettingsMenu panelRef={createRef<HTMLDivElement>()}
    layout="sidebar" onToggleLayout={vi.fn()}
    theme="light" onToggleTheme={vi.fn()} onCustomizeAppearance={vi.fn()}
    tabOrder={DEFAULT_TAB_ORDER} startTab="home"
    onTabOrderChange={vi.fn()} onStartTabChange={vi.fn()}
    timeFormat="12h" onToggleTimeFormat={vi.fn()}
    language="en" onLanguageChange={vi.fn()}
    dayCapacity={null} onDayCapacityChange={vi.fn()}
    dayCapacityByWeekday={{}} onDayCapacityByWeekdayChange={vi.fn()}
    homeTz="" onToggleHomeTz={vi.fn()}
    calFit="dynamic" onToggleCalFit={vi.fn()}
    archivedCals={[]} onArchivedCalsChange={vi.fn()}
    showCompleted={false} onToggleShowCompleted={vi.fn()}
    autoCloseParents={true} onToggleAutoCloseParents={vi.fn()}
    staleOverdue={3} onStaleOverdueChange={vi.fn()}
    planOnDueToday={false} onTogglePlanOnDueToday={vi.fn()}
    focus={DEFAULT_FOCUS} onFocusChange={vi.fn()}
    notifyEnabled={false} onNotifyEnabledChange={vi.fn()}
    notifyTokenSet={false} notifyTokenEnv={false} onNotifyTokenChange={vi.fn()}
    notifyTriggers={{}} onNotifyTriggersChange={vi.fn()}
    notifyDigestTime="07:30" onNotifyDigestTimeChange={vi.fn()}
    notifyEventLead={10} onNotifyEventLeadChange={vi.fn()}
    notifyEveningTime="21:00" onNotifyEveningTimeChange={vi.fn()}
    notifyTaskLead={30} onNotifyTaskLeadChange={vi.fn()}
    user="admin" sessionTtl={null} onCycleSessionTtl={vi.fn()}
    onLogout={vi.fn()} onExpire={vi.fn()} onClose={vi.fn()}
    {...over} />)
}

const nav = (name: string) => screen.getByRole('tab', { name })
const panel = () => screen.getByRole('tabpanel')

describe('<SettingsMenu> under Field notes', () => {
  it('lists the sections by name alone, with a drawn underline on the open one', async () => {
    show()
    const items = screen.getAllByRole('tab')
    expect(items.length).toBeGreaterThan(5)
    for (const item of items) {
      expect(item).not.toHaveAttribute('title')
      expect(item).not.toHaveAttribute('aria-describedby')
      expect(item.querySelector('.tab-ink')).not.toBeNull()
    }
    expect(document.querySelector('.set-nav-blurb')).toBeNull()
    expect(screen.queryByText(/Language, clock, time zone and working day/)).not.toBeInTheDocument()
    expect(nav('General').className).toContain('active')
    expect(nav('General').querySelector('.tab-ink')).not.toBeNull()
    // The name is the item's own text, so nothing else has to carry it.
    expect(nav('Account')).toHaveAccessibleName('Account')
  })

  it('does not say Language and Clock twice, and keeps Working day and Time zone', () => {
    show()
    const p = panel()
    expect(p.querySelectorAll('.menu-head')).toHaveLength(2)
    expect(within(p).getByText('Working day', { selector: '.menu-head' })).toBeInTheDocument()
    expect(within(p).getByText('Time zone', { selector: '.menu-head' })).toBeInTheDocument()
    // The row labels are what name the controls, so they stay.
    expect(within(p).getByLabelText('Language')).toBeInTheDocument()
    expect(within(p).getByText('Clock', { selector: 'label' })).toBeInTheDocument()
  })

  it('removes the hints, the "Default:" tails, the clock fold and the tooltips from General', () => {
    show()
    const p = panel()
    expect(p.querySelector('[title]')).toBeNull()
    expect(p.querySelector('details.menu-more')).toBeNull()
    expect(p.textContent).not.toMatch(/Default:/)
    expect(within(p).queryByText(/Also sets how dates are written/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/How times are written/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/How the clock reaches date pickers/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/Date and time pickers follow it/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/Blank weekdays use Most days/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/The zone your events are written in/)).not.toBeInTheDocument()
    // The controls themselves are still named.
    expect(within(p).getByRole('button', { name: /time zone|timezone/i })).toBeInTheDocument()
    expect(within(p).getByLabelText('Working time for the default working day')).toBeInTheDocument()
  })

  it('removes the hints from Appearance, and the whole desktop line', async () => {
    vi.mocked(readState).mockResolvedValue({
      available: true, choice: 'Auto', resolved: 'Ink', systemUsesLightTheme: true,
      startMenuShortcut: false, captionColour: false, systemTitleBar: false, canPin: false,
    } as DesktopState)
    show()
    await userEvent.click(nav('Appearance'))
    // The desktop controls are there, so the line under them is absent on purpose.
    expect(await within(panel()).findByLabelText('Start menu shortcut')).toBeInTheDocument()
    const p = panel()
    expect(p.querySelector('[title]')).toBeNull()
    expect(p.textContent).not.toMatch(/Default:/)
    expect(within(p).queryByText(/Sidebar puts the views/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/Light or dark, on every device/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/Colour, type and spacing/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/Sets the order in the sidebar/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/taskbar icon comes from/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/Wayland/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/only a light or dark title bar/)).not.toBeInTheDocument()
    expect(within(p).getByRole('button', { name: 'Customize appearance' })).toBeInTheDocument()
  })

  it('removes the hints from Calendar and Tasks, and keeps the note that syncs', async () => {
    show()
    await userEvent.click(nav('Calendar'))
    expect(panel().querySelector('[title]')).toBeNull()
    expect(within(panel()).queryByText(/Fixed fits the whole month/)).not.toBeInTheDocument()
    expect(within(panel()).getByRole('button', { name: 'Fixed or dynamic calendar grid' })).toBeInTheDocument()
    // Where archived calendars still show is a consequence, so it stays.
    expect(within(panel()).getByText(/Archived calendars are hidden/)).toBeInTheDocument()

    await userEvent.click(nav('Tasks'))
    const p = panel()
    expect(p.textContent).not.toMatch(/Default:/)
    expect(within(p).queryByText(/Whether lists show the tasks/)).not.toBeInTheDocument()
    // The fold is closed, so its contents are checked in the DOM.
    expect(p.textContent).not.toMatch(/asks for a new date or to be parked/)
    expect(p.textContent).not.toMatch(/Has no effect while the setting above is 0/)
    // A warning that the change reaches other apps is not an explanation.
    expect(within(p).getByText(/syncs to your other apps/)).toBeInTheDocument()
  })

  it('removes the Focus introduction and hints, and keeps the units', async () => {
    show()
    await userEvent.click(nav('Focus'))
    const p = panel()
    expect(within(p).queryByText(/Start a focus session from Today/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/Changes apply from the next phase/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/the clock stops if it runs out/)).not.toBeInTheDocument()
    expect(within(p).queryByText(/The default for each row/)).not.toBeInTheDocument()
    expect(within(p).getAllByText('minutes').length).toBeGreaterThan(0)
    expect(within(p).getByLabelText('Interval')).toBeInTheDocument()
  })

  it('keeps the notification read-out once the browser has answered', async () => {
    // jsdom has no Notification, so the answer is "unsupported".
    show({ focus: { ...DEFAULT_FOCUS, notify: true } })
    await userEvent.click(nav('Focus'))
    expect(within(panel()).getByText('Not available in this browser.')).toBeInTheDocument()
    expect(within(panel()).queryByText(/Shows even when the window is in the background/))
      .not.toBeInTheDocument()
  })

  it('removes the Account line and keeps the one that revokes access', async () => {
    show()
    await userEvent.click(nav('Account'))
    expect(within(panel()).queryByText(/A shorter time applies at once/)).not.toBeInTheDocument()
    expect(await within(panel()).findByText(/revokes access immediately/)).toBeInTheDocument()
    expect(within(panel()).getByRole('button', { name: /log out/i })).toBeInTheDocument()
  })

  it('keeps the licence notice', async () => {
    show()
    await userEvent.click(nav('About'))
    expect(within(panel()).getByText(/AGPL requires/)).toBeInTheDocument()
  })

  it('removes the introductions at the top of Mail, Displays and Shares', async () => {
    m.shares.mockResolvedValue([])
    m.lists.mockResolvedValue([])
    show()
    await userEvent.click(nav('Shares'))
    await waitFor(() => expect(m.shares).toHaveBeenCalled())
    expect(within(panel()).queryByText(/read-only link for someone else/i)).not.toBeInTheDocument()
    await userEvent.click(nav('Displays'))
    expect(within(panel()).queryByText(/Read-only screens for your calendar or day/)).not.toBeInTheDocument()
    expect(within(panel()).queryByText(/Shows the same faces as a desk display/)).not.toBeInTheDocument()
  })

  it('ends the section column with a decorative drawing that is not a tab', () => {
    show()
    const drawing = document.querySelector('.set-nav > .view-drawing.set-nav-drawing')!
    expect(drawing).toHaveAttribute('aria-hidden', 'true')
    expect(drawing).toBe(document.querySelector('.set-nav')!.lastElementChild)
    expect(screen.getAllByRole('tab').every((t) => !drawing.contains(t))).toBe(true)
  })

  it('leaves the presets without it', () => {
    document.documentElement.removeAttribute('data-surface')
    show()
    expect(document.querySelector('.view-drawing')).toBeNull()
  })
})
