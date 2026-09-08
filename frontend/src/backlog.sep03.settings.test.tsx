/**
 * The 2026-09-03 sweep: the Settings sections and the display page.
 *
 * Seven findings, all in the sheet the owner opens to change something and the
 * one page a display draws from it. Every pin here was written FIRST and run
 * red against the code as it stood; the assertion names the CORRECT behaviour
 * and the comment beside it records what the old code did instead.
 *
 * Four of them are a convention this repo already adopted somewhere else and
 * never carried across: the lead-minute fields clamp on every keystroke (the
 * closed Duration-field finding, unapplied); the add-display form has no
 * in-flight guard (the closed sidebar and booking-link findings, unapplied);
 * `MinutesRow`, the token field and the display fields let Escape close the
 * sheet from under a draft (the capacity field two sections up stops it); and
 * ConnectionsSection rolls back a whole-array snapshot (DisplaysSection in the
 * same panel was rewritten to roll back one row). The other three are English
 * where the reader chose German: five Settings hints whose translations sat
 * unused in de.ts, and the display page's stale strip and gone card.
 *
 * The rolling face's lost headline size (DisplayView.tsx `fitNow`) is the one
 * finding of this group that jsdom cannot see — it lives in the React /
 * ResizeObserver interaction — and is pinned in
 * `backlog.sep03.display.browser.test.tsx` instead.
 */
import { createRef, useState } from 'react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { I18nProvider } from './i18n'
import { DEFAULT_FOCUS } from './focus'
import { DEFAULT_TAB_ORDER } from './tabs'
import { sanitizeEventLead, sanitizeTaskLead } from './notifications'
import { useEscape } from './hooks'
import { ConnectionsSection } from './components/ConnectionsSection'
import { DisplaysSection } from './components/DisplaysSection'
import { DisplayView } from './components/DisplayView'
import { FocusSection } from './components/FocusSection'
import { NotificationsSection } from './components/NotificationsSection'
import { SettingsMenu } from './components/SettingsMenu'
import { api, HttpError, type Display, type DisplayFrame } from './api'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

vi.mock('./notify', () => ({
  notifyPermission: vi.fn(() => 'default'),
  requestNotify: vi.fn(async () => 'granted'),
  showNotify: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
  cleanup()
})
afterEach(() => { vi.useRealTimers() })

/** A promise whose settlement the test holds, so a request can be "in flight". */
function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

// ── fixtures ────────────────────────────────────────────────────────────────

const notifProps = {
  enabled: true, onEnabledChange: vi.fn(),
  chatId: '1', onChatIdChange: vi.fn(),
  tokenSet: false, botId: '', onTokenChange: vi.fn(),
  onExpire: vi.fn(),
  triggers: {}, onTriggersChange: vi.fn(),
  digestTime: '07:30', onDigestTimeChange: vi.fn(),
  eveningTime: '21:00', onEveningTimeChange: vi.fn(),
  homeTz: 'America/New_York',
}

/** App.tsx's two handlers, exactly: clamp, then write the clamped value back
 *  into the controlled prop. The bug is only visible with the clamp in the
 *  loop — a bare `vi.fn()` never rewrites the field. */
function LeadHost({ onEvent, onTask }: { onEvent: (n: number) => void; onTask: (n: number) => void }) {
  const [eventLead, setEventLead] = useState(10)
  const [taskLead, setTaskLead] = useState(30)
  return (
    <NotificationsSection {...notifProps}
      eventLead={eventLead}
      onEventLeadChange={(n) => { const clean = sanitizeEventLead(n); onEvent(clean); setEventLead(clean) }}
      taskLead={taskLead}
      onTaskLeadChange={(n) => { const clean = sanitizeTaskLead(n); onTask(clean); setTaskLead(clean) }} />
  )
}

const DISPLAY: Display = {
  token: 'tok-hallway', name: 'Hallway', mode: 'calendar', palette: 'color',
  calendars: [], lists: [], hide_done_habits: true, hide_done_tasks: true,
  refresh_seconds: 300, panel_width: null, panel_height: null, rotation: 0,
  panel_too_small: null, enabled: true, last_seen_at: null,
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T10:00:00Z',
}

const GRANT_A = { family_id: 'fam-a', client_name: 'App A', scope: 'mcp:read mcp:write',
  granted_at: 1_756_000_000, last_used_at: null }
const GRANT_B = { ...GRANT_A, family_id: 'fam-b', client_name: 'App B' }

const CAL_DE: DisplayFrame = {
  display: { name: 'Flur', mode: 'calendar', palette: 'color', refresh_seconds: 300, rotation: 0 },
  generated_at: '2026-09-03T22:00:00.000Z',
  day: '2026-09-03',
  language: 'de',
  time_format: '24h',
  sources: [],
  calendar: {
    month: '2026-09',
    title: 'September 2026',
    weekday_names: ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'],
    too_small_text: 'Zu klein für einen Monat.',
    too_small_hint: 'Stell sie auf Gewohnheiten + heute.',
    weeks: [[
      { day: '2026-09-03', label: '3', in_month: true, today: true, items: [], hidden: 0 },
    ]],
  },
}

/** The settings sheet with every prop it needs, on a desktop. */
function showSettings(lang: 'en' | 'de', over: Partial<Parameters<typeof SettingsMenu>[0]> = {}) {
  const onClose = vi.fn()
  m.calendars.mockResolvedValue([])
  m.mcpConnections.mockResolvedValue([])
  render(
    <I18nProvider value={lang}>
      <SettingsMenu panelRef={createRef<HTMLDivElement>()}
        theme="light" onToggleTheme={vi.fn()} onCustomizeAppearance={vi.fn()}
        tabOrder={DEFAULT_TAB_ORDER} startTab="home"
        onTabOrderChange={vi.fn()} onStartTabChange={vi.fn()}
        timeFormat="12h" onToggleTimeFormat={vi.fn()}
        language={lang} onLanguageChange={vi.fn()}
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
        {...over} />
    </I18nProvider>)
  return { onClose }
}

/** The settings panel's Escape, as App mounts it: `useEscape` on the window,
 *  and the whole subtree gone when it fires. A section under test is rendered
 *  inside this so "Escape closed the sheet" is observable as an unmount. */
function Sheet({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(true)
  useEscape(() => setOpen(false))
  return open ? <div data-testid="sheet">{children}</div> : null
}

// ── the notification lead fields ────────────────────────────────────────────

describe('2026-09-03 — the notification lead fields', () => {
  // ── NotificationsSection.tsx:249-267 — both lead fields call the parent on
  //    every keystroke, and the parent clamps at 3 before writing the state
  //    back into the controlled field, so "15" becomes "35" ─────────────────
  it('lets 15 minutes be typed into the meeting lead and writes 15, once', async () => {
    // Old code: clear → Number('') = 0 → sanitize → 3 → field "3"; then '1'
    // and '5' append → "31", "315" → 31, 120. The account got 120, not 15.
    const onEvent = vi.fn(), onTask = vi.fn()
    render(<LeadHost onEvent={onEvent} onTask={onTask} />)
    const field = document.getElementById('notif-lead') as HTMLInputElement
    await userEvent.clear(field)
    await userEvent.type(field, '15')
    expect(onEvent).not.toHaveBeenCalled()      // not on every keystroke
    await userEvent.tab()
    expect(onEvent.mock.calls).toEqual([[15]])
    expect(field.value).toBe('15')
  })

  it('lets 10 minutes be typed into the task lead, committed on Enter', async () => {
    const onEvent = vi.fn(), onTask = vi.fn()
    render(<LeadHost onEvent={onEvent} onTask={onTask} />)
    const field = document.getElementById('notif-task-lead') as HTMLInputElement
    await userEvent.clear(field)
    await userEvent.type(field, '10{Enter}')
    expect(onTask.mock.calls).toEqual([[10]])
  })

  it('CONTROL: a value below the floor is still clamped, on commit', async () => {
    // The clamp is right; only its timing was wrong. A committed "1" is 3.
    const onEvent = vi.fn(), onTask = vi.fn()
    render(<LeadHost onEvent={onEvent} onTask={onTask} />)
    const field = document.getElementById('notif-lead') as HTMLInputElement
    await userEvent.clear(field)
    await userEvent.type(field, '1')
    await userEvent.tab()
    expect(onEvent.mock.calls).toEqual([[3]])
    expect(field.value).toBe('3')
  })
})

// ── adding a display ────────────────────────────────────────────────────────

describe('2026-09-03 — adding a display', () => {
  beforeEach(() => {
    m.calendars.mockResolvedValue([{ id: 'work', name: 'Work' }] as never)
    m.lists.mockResolvedValue([{ id: 'inbox', name: 'Inbox' }] as never)
    m.displays.mockResolvedValue([] as never)
  })

  // ── DisplaysSection.tsx:104 — `add()` has no in-flight guard, so a second
  //    Enter during the round trip mints a second display and a second live
  //    unauthenticated token with the same name ──────────────────────────────
  it('creates ONE display for a double Enter during the round trip', async () => {
    const d = deferred<Display>()
    m.createDisplay.mockReturnValue(d.promise as never)
    render(<DisplaysSection onExpire={vi.fn()} />)
    await screen.findByText(/no displays yet/i)
    const field = screen.getByLabelText('Name')
    await userEvent.type(field, 'Kitchen{Enter}{Enter}')
    // Old code: called twice, two rows named Kitchen, two tokens.
    expect(m.createDisplay).toHaveBeenCalledTimes(1)
    // And the button is not an alternative route in.
    expect(screen.getByRole('button', { name: /^add$/i })).toBeDisabled()

    await act(async () => { d.resolve({ ...DISPLAY, name: 'Kitchen', token: 'tok-k' }) })
    expect(await screen.findAllByText('Kitchen')).toHaveLength(1)
  })

  it('CONTROL: once the first add has landed, a second display can be added', async () => {
    m.createDisplay
      .mockResolvedValueOnce({ ...DISPLAY, name: 'Kitchen', token: 'tok-k' } as never)
      .mockResolvedValueOnce({ ...DISPLAY, name: 'Hall', token: 'tok-h' } as never)
    render(<DisplaysSection onExpire={vi.fn()} />)
    await screen.findByText(/no displays yet/i)
    // By placeholder: once the first add lands its editor opens with a
    // second field labelled "Name".
    await userEvent.type(screen.getByPlaceholderText('Hallway'), 'Kitchen{Enter}')
    await screen.findByText('Kitchen')
    await userEvent.type(screen.getByPlaceholderText('Hallway'), 'Hall{Enter}')
    await screen.findByText('Hall')
    expect(m.createDisplay).toHaveBeenCalledTimes(2)
  })

  it('CONTROL: a refused add lets the owner try again', async () => {
    m.createDisplay
      .mockRejectedValueOnce(new HttpError(502, 'nope'))
      .mockResolvedValueOnce({ ...DISPLAY, name: 'Kitchen', token: 'tok-k' } as never)
    render(<DisplaysSection onExpire={vi.fn()} />)
    await screen.findByText(/no displays yet/i)
    await userEvent.type(screen.getByPlaceholderText('Hallway'), 'Kitchen{Enter}')
    await waitFor(() => expect(m.createDisplay).toHaveBeenCalledTimes(1))
    // The name is still there to retry with, and the guard has let go.
    await waitFor(() => expect(screen.getByRole('button', { name: /^add$/i })).toBeEnabled())
    await userEvent.keyboard('{Enter}')
    await screen.findByText('Kitchen')
    expect(m.createDisplay).toHaveBeenCalledTimes(2)
  })
})

// ── the five Settings hints ─────────────────────────────────────────────────

describe('2026-09-03 — the Settings hints in German', () => {
  // ── SettingsMenu.tsx:275, 301, 313, 333, 392 — five `.hintline` paragraphs
  //    are literal English in the JSX while en.ts AND de.ts carry their keys ──
  it('renders every hint paragraph from the catalogue, not from the JSX', async () => {
    showSettings('de')
    const panel = () => screen.getByRole('tabpanel')

    await userEvent.click(screen.getByRole('tab', { name: 'Darstellung' }))
    expect(within(panel()).queryByText(/Customize opens the full editor/)).toBeNull()
    expect(within(panel()).getByText(/Anpassen öffnet den vollständigen Editor/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Kalender' }))
    expect(within(panel()).queryByText(/A fixed calendar window/)).toBeNull()
    expect(within(panel()).getByText(/Eine feste Kalenderansicht/)).toBeInTheDocument()
    expect(within(panel()).queryByText(/Archiving hides a calendar/)).toBeNull()
    expect(await within(panel()).findByText(/Archivieren blendet einen Kalender aus/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Aufgaben' }))
    expect(within(panel()).queryByText(/Whether completed tasks/)).toBeNull()
    expect(within(panel()).getByText(/Ob erledigte Aufgaben/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Konto' }))
    expect(within(panel()).queryByText(/A shorter sign-in applies/)).toBeNull()
    expect(within(panel()).getByText(/Eine kürzere Anmeldung gilt sofort/)).toBeInTheDocument()
  })

  it('CONTROL: the English sheet still reads the same five sentences', async () => {
    showSettings('en')
    await userEvent.click(screen.getByRole('tab', { name: 'Appearance' }))
    expect(screen.getByText(/Customize opens the full editor/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Account' }))
    expect(screen.getByText(/A shorter sign-in applies at once/)).toBeInTheDocument()
  })
})

// ── the display page's own three strings ────────────────────────────────────

describe('2026-09-03 — the display page in German', () => {
  // ── DisplayView.tsx:153 — the stale strip is the literal 'Not updated
  //    recently' under a frame whose every other word arrived in German ──────
  it('announces staleness in the language the frame carries', async () => {
    vi.useFakeTimers()
    m.publicDisplayFrame.mockResolvedValue(CAL_DE)
    render(<DisplayView token="tok" />)
    await act(async () => { await Promise.resolve() })
    expect(screen.getByText('September 2026')).toBeInTheDocument()
    m.publicDisplayFrame.mockRejectedValue(new Error('offline'))
    await act(async () => { vi.advanceTimersByTime(45 * 60_000) })
    // Old code: 'Not updated recently' across the bottom of a German month.
    expect(screen.queryByText('Not updated recently')).toBeNull()
    expect(screen.getByText('Länger nicht aktualisiert')).toBeInTheDocument()
  })

  // ── DisplayView.tsx:140-141 — the gone card is English too, although a
  //    display that has drawn a frame knows the owner's language ─────────────
  it('says a revoked display is gone in the language of the last frame it drew', async () => {
    vi.useFakeTimers()
    m.publicDisplayFrame.mockResolvedValueOnce(CAL_DE)
      .mockRejectedValue(new HttpError(404, 'unknown display'))
    render(<DisplayView token="tok" />)
    await act(async () => { await Promise.resolve() })
    expect(screen.getByText('September 2026')).toBeInTheDocument()
    await act(async () => { vi.advanceTimersByTime(300_000) })
    await act(async () => { await Promise.resolve() })
    expect(screen.queryByText(/no longer connected/i)).toBeNull()
    expect(screen.getByText('Diese Anzeige ist nicht mehr verbunden.')).toBeInTheDocument()
    expect(screen.getByText(/Einstellungen → Anzeigen/)).toBeInTheDocument()
  })

  // ── filed during remediation — the frame's language never reached the
  //    document, so index.html's `lang="en"` stood over a German panel ───────
  it('writes the frame\'s language onto the document', async () => {
    vi.useFakeTimers()
    document.documentElement.lang = 'en'
    m.publicDisplayFrame.mockResolvedValue(CAL_DE)
    render(<DisplayView token="tok" />)
    await act(async () => { await Promise.resolve() })
    expect(document.documentElement.lang).toBe('de')
  })

  it('CONTROL: an English frame reads exactly what it read before', async () => {
    vi.useFakeTimers()
    m.publicDisplayFrame.mockResolvedValue({ ...CAL_DE, language: 'en' })
    render(<DisplayView token="tok" />)
    await act(async () => { await Promise.resolve() })
    m.publicDisplayFrame.mockRejectedValue(new Error('offline'))
    await act(async () => { vi.advanceTimersByTime(45 * 60_000) })
    expect(screen.getByText('Not updated recently')).toBeInTheDocument()
  })
})

// ── Escape over a half-typed field ──────────────────────────────────────────

describe('2026-09-03 — Escape over a draft in a settings section', () => {
  // ── FocusSection.tsx:133 — `MinutesRow` commits on blur/Enter only; Escape
  //    reaches the window listener, the sheet unmounts, no blur fires, and the
  //    typed length is dropped. The capacity field two sections up guards this.
  it('abandons a half-typed focus length WITHOUT closing the sheet', async () => {
    const onChange = vi.fn()
    render(<Sheet><FocusSection value={DEFAULT_FOCUS} onChange={onChange} /></Sheet>)
    const field = screen.getByLabelText('Interval')
    await userEvent.clear(field)
    await userEvent.type(field, '45')
    await userEvent.keyboard('{Escape}')
    // Old code: the sheet is gone and 45 with it — onChange never called,
    // and reopening shows the old 25.
    expect(screen.getByTestId('sheet')).toBeInTheDocument()
    expect(field).toHaveValue(DEFAULT_FOCUS.interval)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('abandons a pasted bot token WITHOUT closing the sheet', async () => {
    const onTokenChange = vi.fn()
    render(<Sheet><NotificationsSection {...notifProps} eventLead={10} onEventLeadChange={vi.fn()}
      taskLead={30} onTaskLeadChange={vi.fn()} onTokenChange={onTokenChange} /></Sheet>)
    const field = document.getElementById('notif-token') as HTMLInputElement
    await userEvent.type(field, '123:abc')
    await userEvent.keyboard('{Escape}')
    expect(screen.getByTestId('sheet')).toBeInTheDocument()
    expect(field).toHaveValue('')
    expect(onTokenChange).not.toHaveBeenCalled()
  })

  it('abandons a half-typed display name and size WITHOUT closing the sheet', async () => {
    m.calendars.mockResolvedValue([] as never)
    m.lists.mockResolvedValue([] as never)
    m.displays.mockResolvedValue([DISPLAY] as never)
    render(<Sheet><DisplaysSection onExpire={vi.fn()} /></Sheet>)
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    const name = document.getElementById(`disp-name-${DISPLAY.token}`) as HTMLInputElement
    await userEvent.clear(name)
    await userEvent.type(name, 'Kitch')
    await userEvent.keyboard('{Escape}')
    expect(screen.getByTestId('sheet')).toBeInTheDocument()
    expect(name).toHaveValue('Hallway')

    const width = screen.getByLabelText('Panel width in pixels')
    await userEvent.type(width, '80')
    await userEvent.keyboard('{Escape}')
    expect(screen.getByTestId('sheet')).toBeInTheDocument()
    expect(width).toHaveValue(null)
    expect(m.patchDisplay).not.toHaveBeenCalled()
  })

  it('CONTROL: Escape with nothing being typed still closes the sheet', async () => {
    render(<Sheet><FocusSection value={DEFAULT_FOCUS} onChange={vi.fn()} /></Sheet>)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByTestId('sheet')).toBeNull()
  })
})

// ── disconnecting a grant ───────────────────────────────────────────────────

describe('2026-09-03 — disconnecting one MCP grant while another is in flight', () => {
  // ── ConnectionsSection.tsx:50-55 — `disconnect` snapshots the whole array
  //    and restores it on failure, resurrecting a grant revoked meanwhile ─────
  it('puts back only the grant whose revoke failed', async () => {
    m.mcpConnections.mockResolvedValue([GRANT_A, GRANT_B] as never)
    const a = deferred<null>(), b = deferred<null>()
    m.mcpDisconnect.mockImplementation(((id: string) =>
      id === 'fam-a' ? a.promise : b.promise) as never)
    render(<ConnectionsSection onExpire={vi.fn()} />)
    await screen.findByText('App A')

    const row = (name: string) => screen.getByText(name).closest('.conn') as HTMLElement
    await userEvent.click(within(row('App A')).getByRole('button', { name: /disconnect/i }))
    await userEvent.click(within(row('App A')).getByRole('button', { name: /disconnect/i }))
    expect(screen.queryByText('App A')).toBeNull()
    await userEvent.click(within(row('App B')).getByRole('button', { name: /disconnect/i }))
    await userEvent.click(within(row('App B')).getByRole('button', { name: /disconnect/i }))
    expect(screen.queryByText('App B')).toBeNull()

    await act(async () => { b.resolve(null) })        // B's 204 lands
    await act(async () => { a.reject(new HttpError(502, 'boom')) })

    // A is back — its revoke did not happen. B is NOT: its family is revoked
    // server-side, and the old code showed it as connected read/write.
    expect(await screen.findByText('App A')).toBeInTheDocument()
    expect(screen.queryByText('App B')).toBeNull()
  })
})

// ── the display's own absolute URL, for the Windows client ──────────────────

describe('2026-09-03 — a display row inside the Windows client', () => {
  beforeEach(() => {
    m.calendars.mockResolvedValue([{ id: 'work', name: 'Work' }] as never)
    m.lists.mockResolvedValue([{ id: 'inbox', name: 'Inbox' }] as never)
  })

  // The same defect "Copy link" had: `location.origin` is http://localhost:<port>
  // in the exe, so the URL on the row and on the clipboard opened nowhere else.
  // The server now names the page when it knows its origin; the row prefers it.
  it('shows and copies the absolute URL the server names', async () => {
    m.displays.mockResolvedValue([{ ...DISPLAY, url: 'https://x.example/display/tok-hallway' }] as never)
    render(<DisplaysSection onExpire={vi.fn()} />)
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    expect(screen.getByText('https://x.example/display/tok-hallway')).toBeInTheDocument()
    expect(screen.queryByText(`${location.origin}/display/tok-hallway`)).toBeNull()
  })

  it('CONTROL: falls back to this origin when the server names none', async () => {
    m.displays.mockResolvedValue([DISPLAY] as never)
    render(<DisplaysSection onExpire={vi.fn()} />)
    await userEvent.click(await screen.findByRole('button', { name: /set up/i }))
    expect(screen.getByText(`${location.origin}/display/tok-hallway`)).toBeInTheDocument()
  })
})
