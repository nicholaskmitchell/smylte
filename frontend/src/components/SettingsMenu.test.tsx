import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { DEFAULT_FOCUS } from '../focus'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createRef } from 'react'
import { SettingsMenu } from './SettingsMenu'
import { api } from '../api'
import { DEFAULT_TAB_ORDER } from '../tabs'
import { pressBack } from '../test/back'
import { DiscardPrompt } from './DiscardPrompt'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked }
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
  m.calendars.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
})

const SECTIONS = ['General', 'Appearance', 'Calendar', 'Tasks', 'Focus', 'Notifications', 'Account']

function show(over: Partial<Parameters<typeof SettingsMenu>[0]> = {}) {
  const onClose = vi.fn()
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
    notifyChatId="" onNotifyChatIdChange={vi.fn()}
    notifyTokenSet={false} notifyBotId="" onNotifyTokenChange={vi.fn()}
    notifyTriggers={{}} onNotifyTriggersChange={vi.fn()}
    notifyDigestTime="07:30" onNotifyDigestTimeChange={vi.fn()}
    notifyEventLead={10} onNotifyEventLeadChange={vi.fn()}
    notifyEveningTime="21:00" onNotifyEveningTimeChange={vi.fn()}
    notifyTaskLead={30} onNotifyTaskLeadChange={vi.fn()}
    user="admin" sessionTtl={null} onCycleSessionTtl={vi.fn()}
    onLogout={vi.fn()} onExpire={vi.fn()} onClose={onClose}
    {...over} />)
  return { onClose }
}

const nav = (name: string) => screen.getByRole('tab', { name })
const panel = () => screen.getByRole('tabpanel')

// ── desktop: nav column beside a panel ──────────────────────────────────────

describe('<SettingsMenu> on a desktop', () => {
  beforeEach(() => stubMatchMedia(false))

  it('opens on the first section with the whole nav in reach', () => {
    show()
    for (const s of SECTIONS) expect(nav(s)).toBeVisible()
    expect(nav('General')).toHaveAttribute('aria-selected', 'true')
  })

  it('shows one section at a time, and every one of them is reachable', async () => {
    // The defect this layout exists for: a strip of tabs across a popover drops
    // whichever section comes last off the end. A column cannot.
    show()
    for (const s of SECTIONS) {
      await userEvent.click(nav(s))
      expect(nav(s)).toHaveAttribute('aria-selected', 'true')
      expect(panel()).toHaveAttribute('aria-labelledby', `set-tab-${s.toLowerCase()}`)
      expect(screen.getAllByRole('tabpanel')).toHaveLength(1)
    }
  })

  it('keeps the nav a permanent column, with nothing to go back to', async () => {
    show()
    await userEvent.click(nav('Account'))
    expect(nav('General')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument()
  })

  it('puts each setting in its own section', async () => {
    show()
    // A sample per section — the point is that they are apart, not together.
    expect(within(panel()).getByLabelText('Opens on')).toBeInTheDocument()

    await userEvent.click(nav('Appearance'))
    expect(within(panel()).getByRole('button', { name: 'Customize appearance' })).toBeInTheDocument()

    await userEvent.click(nav('Calendar'))
    expect(within(panel()).getByRole('button', { name: 'Fixed or dynamic calendar grid' })).toBeInTheDocument()

    await userEvent.click(nav('Tasks'))
    expect(within(panel()).getByRole('button', { name: /Hidden|Shown/ })).toBeInTheDocument()

    await userEvent.click(nav('Focus'))
    expect(within(panel()).getByLabelText('Interval')).toBeInTheDocument()
    expect(within(panel()).getByLabelText('When an interval ends')).toHaveTextContent('Wait for me')

    await userEvent.click(nav('Account'))
    expect(within(panel()).getByRole('button', { name: 'How long to stay signed in' })).toBeInTheDocument()
    expect(within(panel()).getByRole('button', { name: /log out/i })).toBeInTheDocument()
  })

  it('has a Shares section, and opens its panel', async () => {
    // Not in SECTIONS above: that list is the ones whose panels need no network,
    // and this one lists the account's shares on mount.
    m.shares.mockResolvedValue([])
    m.lists.mockResolvedValue([])
    show()
    await userEvent.click(nav('Shares'))
    expect(nav('Shares')).toHaveAttribute('aria-selected', 'true')
    expect(panel()).toHaveAttribute('aria-labelledby', 'set-tab-shares')
    expect(await within(panel()).findByText('No shares yet.')).toBeInTheDocument()
    expect(within(panel()).getByText(/read-only link for someone else/i)).toBeInTheDocument()
  })

  it('closes on Escape, since there is no drill-down to unwind', async () => {
    const { onClose } = show()
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('asks before Back drops a display name typed but not added, and Keep leaves it', async () => {
    // The name goes only by Enter or Add, so closing Settings would lose it.
    m.displays.mockResolvedValue([])
    m.lists.mockResolvedValue([])
    const { onClose } = show()
    render(<DiscardPrompt />)
    await userEvent.click(nav('Displays'))
    const name = await within(panel()).findByLabelText('Name')
    await userEvent.type(name, 'Hallway')

    pressBack()
    expect(screen.getByRole('alertdialog', { name: 'Discard changes?' })).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(onClose).not.toHaveBeenCalled()
    expect(name).toHaveValue('Hallway')
  })

  // A name being added is on its way whatever Back does, so "Discard" would
  // promise what it cannot do; and closing Settings left a failed add nowhere
  // to put the name back. So Back waits, then asks if the name is still there.
  it.each([
    ['display', 'Displays', 'Name', 'Hallway', 'Add', 'createDisplay', 'displays'],
    ['share', 'Shares', 'Who is it for?', 'Sam', 'Create link', 'createShare', 'shares'],
  ] as const)('waits on Back while a %s name is being added, and asks after it fails',
    async (_kind, section, label, typed, button, create, listing) => {
      m[listing].mockResolvedValue([])
      m.lists.mockResolvedValue([])
      let fail: (e: Error) => void = () => {}
      m[create].mockReturnValue(new Promise((_, reject) => { fail = reject }) as never)
      const { onClose } = show()
      render(<DiscardPrompt />)
      await userEvent.click(nav(section))
      const field = await within(panel()).findByLabelText(label)
      await userEvent.type(field, typed)
      await userEvent.click(within(panel()).getByRole('button', { name: button }))
      expect(m[create]).toHaveBeenCalledOnce()

      expect(pressBack()).toBe(true)
      expect(screen.queryByRole('alertdialog')).toBeNull()
      expect(onClose).not.toHaveBeenCalled()

      await act(async () => { fail(new Error('offline')) })
      expect(field).toHaveValue(typed)
      pressBack()
      expect(screen.getByRole('alertdialog', { name: 'Discard changes?' })).toBeInTheDocument()
      expect(onClose).not.toHaveBeenCalled()
    })

  it('closes on Back once an add has landed', async () => {
    m.displays.mockResolvedValue([])
    m.lists.mockResolvedValue([])
    let land: () => void = () => {}
    m.createDisplay.mockReturnValue(new Promise((r) => {
      land = () => r({
        token: 'tok-hallway', name: 'Hallway', mode: 'calendar', palette: 'color',
        calendars: [], lists: [], hide_done_habits: true, hide_done_tasks: true,
        refresh_seconds: 300, panel_width: null, panel_height: null, rotation: 0,
        panel_too_small: null, enabled: true, last_seen_at: null,
        created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z',
      } as never)
    }))
    const { onClose } = show()
    render(<DiscardPrompt />)
    await userEvent.click(nav('Displays'))
    await userEvent.type(await within(panel()).findByLabelText('Name'), 'Hallway')
    await userEvent.click(within(panel()).getByRole('button', { name: 'Add' }))
    pressBack()
    expect(onClose).not.toHaveBeenCalled()

    await act(async () => { land() })
    pressBack()
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(onClose).toHaveBeenCalledOnce()
  })
})

// ── about: the licence's own requirement, rendered ──────────────────────────

describe('<SettingsMenu> → About', () => {
  beforeEach(() => stubMatchMedia(false))

  it('offers the source of the running version, as AGPL §13 asks', async () => {
    // Not decoration. The licence obliges anyone running a modified copy over a
    // network to offer its source to the people using it, and this link is the
    // only place the app does that — a README is not something a person
    // interacting with the server ever sees.
    show()
    await userEvent.click(nav('About'))
    const link = within(panel()).getByRole('link', { name: /github\.com/ })
    expect(link).toHaveAttribute('href', 'https://github.com/nicholaskmitchell/smylte')
  })

  it('shows the same address it links to', async () => {
    // The failure this pins is a fork that repoints the href and leaves the
    // visible text naming this repository — a link that lies about where the
    // source is fails §13 more completely than no link, because it looks
    // answered. The label is derived from the URL so the two cannot drift.
    show()
    await userEvent.click(nav('About'))
    const link = within(panel()).getByRole('link', { name: /github\.com/ })
    expect(link.getAttribute('href')).toContain(link.textContent!.trim())
  })

  it('names the licence it is offering the source under', async () => {
    show()
    await userEvent.click(nav('About'))
    expect(within(panel()).getByText('AGPL-3.0-only')).toBeInTheDocument()
  })
})

// ── phone: an index, then the section you tapped ────────────────────────────

describe('<SettingsMenu> on a phone', () => {
  beforeEach(() => stubMatchMedia(true))
  afterEach(() => stubMatchMedia(false))

  const sheet = () => document.querySelector('.set-sheet')!

  it('opens on the index of sections, not on one of them', () => {
    show()
    expect(sheet()).toHaveAttribute('data-view', 'index')
    expect(screen.getByText('Settings')).toBeInTheDocument()
  })

  it('drills into a section and names it in the title bar', async () => {
    // Six sections never fit a strip across a phone; the ones past the right
    // edge were simply unreachable. An index you drill into has no such edge.
    show()
    for (const s of SECTIONS) {
      await userEvent.click(nav(s))
      expect(sheet()).toHaveAttribute('data-view', 'panel')
      expect(document.querySelector('.set-title')).toHaveTextContent(s)
      await userEvent.click(screen.getByRole('button', { name: 'Back' }))
      expect(sheet()).toHaveAttribute('data-view', 'index')
    }
  })

  it('steps back to the index before it closes', async () => {
    const { onClose } = show()
    await userEvent.click(nav('Account'))
    await userEvent.keyboard('{Escape}')
    expect(sheet()).toHaveAttribute('data-view', 'index')
    expect(onClose).not.toHaveBeenCalled()

    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('takes the same steps on Back: index first, then closed', async () => {
    const { onClose } = show()
    await userEvent.click(nav('Account'))
    pressBack()
    expect(sheet()).toHaveAttribute('data-view', 'index')
    expect(onClose).not.toHaveBeenCalled()

    pressBack()
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('leaves the archived-calendar agenda before the section on Back', async () => {
    m.calendars.mockResolvedValue([
      { id: 'c1', name: 'Old work', color: '#888', event_count: 2 },
    ] as never)
    m.events.mockResolvedValue([])
    const { onClose } = show({ archivedCals: ['c1'] })

    await userEvent.click(nav('Calendar'))
    await userEvent.click(await screen.findByRole('button', { name: 'View events' }))
    expect(document.querySelector('.set-title')).toHaveTextContent('Old work')

    pressBack()
    expect(document.querySelector('.set-title')).toHaveTextContent('Calendar')
    pressBack()
    expect(sheet()).toHaveAttribute('data-view', 'index')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('asks before the Back that closes Settings drops a share name not yet added', async () => {
    // Stepping back to the index keeps the section, and the typed name, mounted
    // underneath, so that step asks nothing; the step that closes does.
    m.shares.mockResolvedValue([])
    m.lists.mockResolvedValue([])
    const { onClose } = show()
    render(<DiscardPrompt />)
    await userEvent.click(nav('Shares'))
    await userEvent.type(await within(panel()).findByLabelText('Who is it for?'), 'Sam')

    pressBack()
    expect(sheet()).toHaveAttribute('data-view', 'index')
    expect(screen.queryByRole('alertdialog')).toBeNull()

    pressBack()
    expect(screen.getByRole('alertdialog', { name: 'Discard changes?' })).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('closes without asking once a typed share name is cleared again', async () => {
    m.shares.mockResolvedValue([])
    m.lists.mockResolvedValue([])
    const { onClose } = show()
    render(<DiscardPrompt />)
    await userEvent.click(nav('Shares'))
    const name = await within(panel()).findByLabelText('Who is it for?')
    await userEvent.type(name, 'Sam')
    await userEvent.clear(name)

    pressBack()
    pressBack()
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('commits a half-typed field before it steps back, as the section\'s ‹ would', async () => {
    // The inline fields are not layers: they stop Escape at the field and
    // commit on blur, so Back leaves the field first and then takes the step.
    const onFocusChange = vi.fn()
    show({ onFocusChange })
    await userEvent.click(nav('Focus'))
    const interval = within(panel()).getByLabelText('Interval')
    await userEvent.clear(interval)
    await userEvent.type(interval, '50')
    expect(onFocusChange).not.toHaveBeenCalled()

    pressBack()
    expect(onFocusChange).toHaveBeenCalledWith(expect.objectContaining({ interval: 50 }))
    expect(sheet()).toHaveAttribute('data-view', 'index')
  })

  it('unwinds the archived-calendar agenda one step at a time', async () => {
    // Calendar → the archived list → one calendar's events is three deep. Back
    // has to leave the agenda before it leaves the section, or the step out of
    // the section is the step that looks broken.
    m.calendars.mockResolvedValue([
      { id: 'c1', name: 'Old work', color: '#888', event_count: 2 },
    ] as never)
    m.events.mockResolvedValue([])
    const { onClose } = show({ archivedCals: ['c1'] })

    await userEvent.click(nav('Calendar'))
    await userEvent.click(await screen.findByRole('button', { name: 'View events' }))
    expect(document.querySelector('.set-title')).toHaveTextContent('Old work')

    // The agenda replaces the section: with the title bar naming the calendar,
    // leaving "Calendar window" above it would file that row under "Old work".
    expect(within(panel()).queryByRole('button', { name: 'Fixed or dynamic calendar grid' }))
      .not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(document.querySelector('.set-title')).toHaveTextContent('Calendar')
    expect(sheet()).toHaveAttribute('data-view', 'panel')
    expect(within(panel()).getByRole('button', { name: 'Fixed or dynamic calendar grid' }))
      .toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(sheet()).toHaveAttribute('data-view', 'index')
    expect(onClose).not.toHaveBeenCalled()
  })

  it('closes from the scrim and the ✕, since a full-width sheet has no outside', async () => {
    const { onClose } = show()
    await userEvent.click(screen.getByRole('button', { name: 'Close settings' }))
    expect(onClose).toHaveBeenCalledOnce()

    await userEvent.click(document.querySelector('.set-overlay')!)
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})

describe('<SettingsMenu> finishing a checklist with its last step', () => {
  beforeEach(() => stubMatchMedia(false))

  it('offers the one preference here that writes to the calendar server', async () => {
    // Every other switch in this app changes what the OWNER sees. This one
    // completes a real VTODO on their behalf, which reaches Tasks.org and
    // Thunderbird within a sync — so it has to be refusable, and the hint has
    // to say that rather than describing it as a display convenience.
    const onToggle = vi.fn()
    const user = userEvent.setup()
    show({ autoCloseParents: true, onToggleAutoCloseParents: onToggle })
    await user.click(nav('Tasks'))

    // Named by its <label htmlFor>, not by its own text — which is the point of
    // the pairing: a screen reader reads what the switch is FOR, and
    // `aria-pressed` carries which way it is set.
    const toggle = screen.getByRole('button', { name: 'Complete a task when its last subtask is done' })
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(toggle).toHaveTextContent('On')
    expect(panel()).toHaveTextContent(/syncs to your other apps/)

    await user.click(toggle)
    expect(onToggle).toHaveBeenCalled()
  })

  it('says Off when it is off, rather than only styling it', async () => {
    // The state has to be readable, not just pressable: this is the switch that
    // decides whether the app writes to somebody's calendar server, and "which
    // way is it set" must not be a question about a colour.
    const user = userEvent.setup()
    show({ autoCloseParents: false })
    await user.click(nav('Tasks'))
    const toggle = screen.getByRole('button', { name: 'Complete a task when its last subtask is done' })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    expect(toggle).toHaveTextContent('Off')
  })
})

describe('<SettingsMenu> asking about work that has waited', () => {
  beforeEach(() => stubMatchMedia(false))

  it('commits the threshold on blur, not on every keystroke', async () => {
    // A PUT per digit would briefly store "1" on the way to "14", and each one
    // is a settings write that reaches every other tab.
    const onChange = vi.fn()
    const user = userEvent.setup()
    show({ staleOverdue: 3, onStaleOverdueChange: onChange })
    await user.click(nav('Tasks'))

    const field = screen.getByLabelText('Days overdue before asking')
    await user.clear(field)
    await user.type(field, '14')
    expect(onChange).not.toHaveBeenCalled()
    await user.tab()
    expect(onChange).toHaveBeenCalledWith(14)
  })

  it('clamps a number out of range rather than refusing it', async () => {
    // A number field hands back a number or nothing, so "91" is a value out of
    // range rather than a line this cannot read — and the bounds are the
    // server's own, so a clamp here is what stops a 422 taking the whole
    // settings write down with it.
    const onChange = vi.fn()
    const user = userEvent.setup()
    show({ staleOverdue: 3, onStaleOverdueChange: onChange })
    await user.click(nav('Tasks'))

    const field = screen.getByLabelText('Days overdue before asking')
    await user.clear(field)
    await user.type(field, '900')
    await user.tab()
    expect(onChange).toHaveBeenCalledWith(90)
  })

  it('snaps an emptied field back rather than reading it as off', async () => {
    // 0 is the OFF switch and must only ever be reached deliberately. An empty
    // field is somebody mid-edit, not somebody turning the feature off.
    const onChange = vi.fn()
    const user = userEvent.setup()
    show({ staleOverdue: 3, onStaleOverdueChange: onChange })
    await user.click(nav('Tasks'))

    const field = screen.getByLabelText('Days overdue before asking')
    await user.clear(field)
    await user.tab()
    expect(onChange).not.toHaveBeenCalled()
    expect(field).toHaveValue(3)
  })

  it('refuses a negative rather than clamping it onto the off switch', async () => {
    // `<input min={0}>` does not stop -5 being typed, and `Math.max(0, …)`
    // turned it into 0 — which is the OFF switch. Disabling the triage group is
    // a decision, and it must not be reachable by mistyping a threshold.
    const onChange = vi.fn()
    const user = userEvent.setup()
    show({ staleOverdue: 3, onStaleOverdueChange: onChange })
    await user.click(nav('Tasks'))

    const field = screen.getByLabelText('Days overdue before asking')
    await user.clear(field)
    await user.type(field, '-5')
    await user.tab()
    expect(onChange).not.toHaveBeenCalled()
    expect(field).toHaveValue(3)
  })

  it('says what off means when it is off', async () => {
    const user = userEvent.setup()
    show({ staleOverdue: 0 })
    await user.click(nav('Tasks'))
    expect(panel()).toHaveTextContent(/Overdue tasks are offered for today however late/)
  })
})

describe('<SettingsMenu> planning the work you answer with today', () => {
  beforeEach(() => stubMatchMedia(false))

  const NAME = 'Plan tasks moved to today'

  it('offers the switch, off by default, and says what it would do', async () => {
    // Worded as the RULE rather than as the button: the date field beside "Due
    // today" does the same thing when you pick the same day, so a label naming
    // the button would describe half of what the switch governs.
    const onToggle = vi.fn()
    const user = userEvent.setup()
    show({ planOnDueToday: false, onTogglePlanOnDueToday: onToggle })
    await user.click(nav('Tasks'))

    const toggle = screen.getByRole('button', { name: NAME })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    expect(toggle).toHaveTextContent('Off')
    // The hint has to carry the exclusion, because it is the half that is not
    // obvious from the label: a task moved to Thursday is scheduled, not
    // planned, and there is no day plan to put it on.
    expect(panel()).toHaveTextContent(/overdue task given today as its new date/)

    await user.click(toggle)
    expect(onToggle).toHaveBeenCalled()
  })

  it('says On when it is on, rather than only styling it', async () => {
    const user = userEvent.setup()
    show({ planOnDueToday: true })
    await user.click(nav('Tasks'))
    const toggle = screen.getByRole('button', { name: NAME })
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(toggle).toHaveTextContent('On')
  })

  it('stays on screen when the group it governs is off, and says why', async () => {
    // A control that vanishes is one nobody can find again to work out why it
    // stopped mattering. With the threshold at 0 nothing is asked about, so
    // there are no answers for this to change — which the line says outright
    // rather than leaving a switch that silently does nothing.
    const user = userEvent.setup()
    show({ staleOverdue: 0, planOnDueToday: true })
    await user.click(nav('Tasks'))
    expect(screen.getByRole('button', { name: NAME })).toBeInTheDocument()
    expect(panel()).toHaveTextContent(/Has no effect while the setting above is 0/)
  })
})
