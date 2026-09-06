import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { DEFAULT_FOCUS } from '../focus'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createRef } from 'react'
import { SettingsMenu } from './SettingsMenu'
import { api } from '../api'
import { DEFAULT_TAB_ORDER } from '../tabs'

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

  it('closes on Escape, since there is no drill-down to unwind', async () => {
    const { onClose } = show()
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
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
    const toggle = screen.getByRole('button', { name: 'Finish a checklist with its last step' })
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(toggle).toHaveTextContent('On')
    expect(panel()).toHaveTextContent(/shows up in your other calendar apps/)

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
    const toggle = screen.getByRole('button', { name: 'Finish a checklist with its last step' })
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

    const field = screen.getByLabelText('Ask about work more than this many days late')
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

    const field = screen.getByLabelText('Ask about work more than this many days late')
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

    const field = screen.getByLabelText('Ask about work more than this many days late')
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

    const field = screen.getByLabelText('Ask about work more than this many days late')
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
    expect(panel()).toHaveTextContent(/Overdue work is offered to your day like anything else/)
  })
})
