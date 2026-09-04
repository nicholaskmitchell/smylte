/**
 * The 2026-09-03 sweep — the app shell, the data layer, Focus, Home, Scheduling
 * and the plural forms in the catalogues.
 *
 * Sixteen findings, and what they share is a surface that says something the
 * server does not: a settings write built from shipped defaults while the shell
 * is offline; a reconnect that refetches tasks and not preferences; a task from
 * a list that failed to load counted as DONE; a discarded fan-out with nothing
 * left to re-issue it; a toast in the wrong language; a document that declares
 * English over a German UI; a tab strip with no selected state; a cap toggle
 * that never rolls back; a blank Focus pane; a booking URL only one machine can
 * open; an editor that shows one calendar and sends another; a dashboard that
 * says "no links" over a 502; a mini calendar frozen on last month; "you were
 * away" said to someone who was here; and "1 hours before".
 *
 * Every test here was written FIRST and run RED against the code as it stood,
 * then made green by the smallest fix that answers it. The one exception is
 * the sign-out pin (#8), a TEST-GAP finding: the code was already right, and
 * the pin was shown red by temporarily deleting the two lines it guards.
 *
 * Same conventions as `backlog.aug25.stage4.test.tsx`: the API module mocked
 * whole at the transport boundary, the real components above it, one `it` per
 * finding named for the CORRECT behaviour, and a CONTROL beside any pin whose
 * cheap over-correction would be to refuse the live path too.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { App } from './App'
import { DataProvider, useTaskData, type TaskData } from './data'
import { cacheLists, cacheTasks, lastCacheUser, setCacheUser } from './cache'
import { FocusView } from './components/FocusView'
import { HomeView } from './components/HomeView'
import { SchedulingView } from './components/SchedulingView'
import { DEFAULT_FOCUS } from './focus'
import { translate } from './i18n/index'
import { type DashboardModule } from './dashboard'
import { playChime } from './chime'
import {
  api, AuthError, HttpError, subscribe,
  type BookingLink, type DayEntry, type DayPlan, type FocusSession, type List, type Task,
} from './api'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
// A browser, not the Windows client — except `isFloatWindow`, which stays real
// (it reads the query string), as App.test.tsx does.
vi.mock('./desktop', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./desktop')>()
  return {
    ...mod,
    readState: vi.fn(async () => null),
    floatWindow: vi.fn(async () => null), dockWindow: vi.fn(async () => null),
    pinWindow: vi.fn(async () => null), dragWindow: vi.fn(async () => null),
  }
})
vi.mock('./chime', () => ({
  playChime: vi.fn(), unlockChime: vi.fn(), chimeReady: vi.fn(() => true), _resetChime: vi.fn(),
}))
vi.mock('./notify', () => ({
  showNotify: vi.fn(() => true), notifyPermission: vi.fn(() => 'granted'),
  requestNotify: vi.fn(async () => 'granted'),
}))

const m = vi.mocked(api)

// ── fixtures ───────────────────────────────────────────────────────────────

const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const today = () => ymd(new Date())

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null,
  has_rrule: false, created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const list = (o: Partial<List> = {}): List => ({
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 1, task_count: 1, event_count: 0, total: 1, color: '#D9480F', ...o,
})

const entry = (o: Partial<DayEntry> = {}): DayEntry => ({
  entry_id: 'n1', day: today(), kind: 'note', list: null, uid: null,
  title: 'Memo', source: 'user', position: 1,
  done_at: null, dropped_at: null, habit_id: null, rolled_to: null,
  estimate_minutes: null, worked_seconds: null, capped: null,
  created_at: '2026-09-03T08:00:00.000Z', ...o,
})
const plan = (entries: DayEntry[], o: Partial<DayPlan> = {}): DayPlan => ({
  day: today(), planned: true, entries, capacity_minutes: null, capacity: null,
  committed_at: null, shutdown_at: null, reflection: null, ...o,
})
/** A session anchored `agoS` seconds before now. */
const session = (o: Partial<FocusSession> = {}, agoS = 0): FocusSession => ({
  day: today(), phase: 'focus', phase_length_s: 1500, phase_elapsed_s: 0,
  running_since: new Date(Date.now() - agoS * 1000).toISOString(),
  intervals_done: 0, entry_id: 'n1', passed: [],
  started_at: new Date().toISOString(), ended_at: null, updated_at: new Date().toISOString(),
  ...o,
})

const link = (o: Partial<BookingLink> = {}): BookingLink => ({
  token: 'tok1', title: 'Intro call', description: null, calendar: 'c1', calendar_name: 'Work',
  calendar_missing: false, duration_minutes: 30, timezone: 'UTC',
  availability: { '0': ['09:00-17:00'] }, show_busy: true, buffer_minutes: 0,
  min_notice_hours: 0, horizon_days: 14, enabled: true, booking_count: 0,
  created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z', ...o,
})

const calendar = (id: string, name: string): List =>
  list({ id, href: `/${id}/`, name, is_task_list: false, is_calendar: true })

/** Open the gear and, when a section is named, drill into it. The nav items
 *  are `role="tab"`, which is what keeps the settings *Tasks* section apart
 *  from the *Tasks* tab in the strip. */
const openSettings = async (section?: string, gear = 'Settings') => {
  await userEvent.click(await screen.findByRole('button', { name: gear }))
  if (section) await userEvent.click(await screen.findByRole('tab', { name: section }))
}

const showFocus = (settings = DEFAULT_FOCUS) => render(
  <DataProvider rev={0} onExpire={vi.fn()}>
    <FocusView rev={0} focusRev={0} onExpire={vi.fn()} onLeave={vi.fn()} settings={settings} />
  </DataProvider>,
)

const showHome = (layout: DashboardModule[]) => render(
  <DataProvider rev={0} onExpire={vi.fn()}>
    <HomeView rev={0} onExpire={vi.fn()} layout={layout} onLayoutChange={vi.fn()} />
  </DataProvider>,
)

const tick = (seconds: number) => act(() => { vi.advanceTimersByTime(seconds * 1000) })

beforeEach(() => {
  vi.clearAllMocks()
  history.replaceState(null, '', '/')
  document.documentElement.dataset.theme = 'light'
  document.documentElement.removeAttribute('style')
  setCacheUser('')
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
  m.mcpConnections.mockResolvedValue([])
  m.day.mockResolvedValue(plan([entry()]))
  m.focus.mockResolvedValue(session())
  m.focusClock.mockImplementation(async () => session())
  m.focusCursor.mockResolvedValue(session({ entry_id: null, passed: ['n1'] }))
  m.patchDayEntry.mockImplementation(async (_d, id, body) => entry({ entry_id: id, ...body }))
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  document.title = 'Smylte'
})

// ════════════════════════════════════════════════════════════════════════════
// App — settings
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — the shell while the server cannot be reached', () => {
  // ── App.tsx:324 — the 'offline' boot state never ISSUES the settings read,
  //    so `settingsFailed` stays at its initial false and a merge-class gesture
  //    PUTs a value built from shipped defaults over the account's real one ──
  it('holds a merge-class settings write while the shell is offline', async () => {
    m.me.mockRejectedValue(new HttpError(502, 'bad gateway'))
    render(<App />)
    await screen.findByRole('status')                // the offline bar
    expect(m.getSettings).not.toHaveBeenCalled()

    await openSettings('General')
    await userEvent.click(await screen.findByRole('button', { name: 'Move Calendar left' }))
    await act(async () => { await Promise.resolve() })

    const wrote = m.putSettings.mock.calls
      .map((c) => c[0] as Record<string, unknown>).filter((b) => 'tab_order' in b)
    expect(wrote, 'the shipped tab order was PUT over the account while offline').toEqual([])
    expect(screen.getByRole('alert')).toHaveTextContent(/didn.t load/)
  })

  it('CONTROL: writes again once Retry brings the server back', async () => {
    // The gate is a refusal, and the cheap over-correction is a ref that never
    // resets: the settings read on the way back IN must re-arm the live path.
    m.me.mockRejectedValueOnce(new HttpError(502, 'bad gateway'))
      .mockResolvedValue({ authenticated: true, user: 'admin' })
    render(<App />)
    const bar = await screen.findByRole('status')
    await userEvent.click(within(bar).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(m.getSettings).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())

    await openSettings('General')
    await userEvent.click(await screen.findByRole('button', { name: 'Move Calendar left' }))
    await waitFor(() => expect(m.putSettings).toHaveBeenCalledWith(
      expect.objectContaining({ tab_order: expect.any(Array) })))
  })
})

describe('2026-09-03 — the SSE stream reconnecting', () => {
  // ── App.tsx:978 — `subscribe` emits 'reconnect' to stand in for every event
  //    lost while the stream was down, and App treats it as a DATA change only:
  //    tasks are refetched, the settings blob is not, so a settings_updated
  //    missed overnight is written back over whole on the next gesture ─────
  it('re-reads settings as well as data on a reconnect', async () => {
    let handler: ((type: string) => void) | null = null
    vi.mocked(subscribe).mockImplementation((fn) => { handler = fn; return () => {} })
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await waitFor(() => expect(m.getSettings).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(m.lists).toHaveBeenCalledTimes(1))

    act(() => { handler!('reconnect') })

    await waitFor(() => expect(m.lists).toHaveBeenCalledTimes(2))     // the data half
    await waitFor(() => expect(m.getSettings).toHaveBeenCalledTimes(2)) // the settings half
  })
})

describe('2026-09-03 — a settings write the server rejects, on a German account', () => {
  // ── App.tsx:624 — `saveSettings` closes over `tr`, and the []-dependency
  //    `change*` callbacks hold the FIRST render's `saveSettings`, whose `tr`
  //    is English because `language` is the default until the read lands ────
  it('toasts in the language the account is set to', async () => {
    m.getSettings.mockResolvedValue({ language: 'de' })
    m.putSettings.mockRejectedValue(new HttpError(422, 'nope'))
    render(<App />)
    await screen.findByRole('button', { name: 'Einstellungen' })
    await openSettings('Allgemein', 'Einstellungen')
    await userEvent.click(await screen.findByRole('button', { name: 'Kalender nach links' }))

    expect(await screen.findByRole('alert'))
      .toHaveTextContent('Deine Einstellungen konnten nicht gespeichert werden: nope')
  })
})

describe('2026-09-03 — the document language', () => {
  // ── index.html:2 — `<html lang="en">` is static and nothing writes
  //    `document.documentElement.lang`, so a German UI is read with English
  //    rules by assistive tech (WCAG 3.1.1) ────────────────────────────────
  it('follows the account language onto the document element', async () => {
    // jsdom starts the attribute empty; the shipped shell says "en".
    document.documentElement.lang = 'en'
    m.getSettings.mockResolvedValue({ language: 'de' })
    render(<App />)
    await screen.findByRole('button', { name: 'Einstellungen' })
    await waitFor(() => expect(document.documentElement.lang).toBe('de'))
  })
})

describe('2026-09-03 — the tab strip', () => {
  // ── App.tsx:1089 — the current tab is marked by a class alone, so a screen
  //    reader hears five identical buttons. (The 44px tap box on a phone is a
  //    CSS rule and lives with the styles.) ───────────────────────────────────
  it('tells assistive tech which tab is current', async () => {
    render(<App />)
    const home = await screen.findByRole('button', { name: 'Home' })
    expect(home).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'Tasks' })).not.toHaveAttribute('aria-current')
    await userEvent.click(screen.getByRole('button', { name: 'Tasks' }))
    expect(screen.getByRole('button', { name: 'Tasks' })).toHaveAttribute('aria-current', 'page')
    expect(home).not.toHaveAttribute('aria-current')
  })
})

describe('2026-09-03 — signing out', () => {
  // ── App.tsx:1032 (test gap) — `onLogout` is the only place the disk mirror
  //    is cleared, and deleting its two lines passed all 1569 tests ─────────
  const cacheKeys = () => Object.keys(localStorage).filter((k) => k.startsWith('smylte-cache:'))

  it('clears the disk mirror on an explicit sign-out', async () => {
    setCacheUser('admin')
    cacheLists([list()])
    cacheTasks([task({ summary: 'ADMIN SECRET' })])
    expect(cacheKeys().length).toBeGreaterThan(0)
    render(<App />)
    await screen.findByRole('button', { name: 'Tasks' })
    await openSettings('Account')
    await userEvent.click(screen.getByRole('button', { name: /log out/i }))
    await screen.findByRole('button', { name: /sign in/i })

    expect(cacheKeys(), 'the mirror survived an explicit sign-out').toEqual([])
    expect(lastCacheUser()).toBe('')
  })

  it('CONTROL: keeps the mirror when the session merely expired', async () => {
    // Usually the same person about to sign back in, and keeping it makes that
    // instant — the comment over `onLogout` says so, and this holds it to it.
    setCacheUser('admin')
    cacheLists([list()])
    cacheTasks([task()])
    m.getSettings.mockRejectedValue(new AuthError('expired'))
    render(<App />)
    await screen.findByRole('button', { name: /sign in/i })
    expect(cacheKeys().length).toBeGreaterThan(0)
    expect(lastCacheUser()).toBe('admin')
  })
})

// ════════════════════════════════════════════════════════════════════════════
// The data layer
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — a write that fails while a task fan-out is in flight', () => {
  // ── data.tsx:275 — `invalidateFetches()` drops the fan-out on arrival, and
  //    the module's safety net is the write's own SSE bump; a write that FAILS
  //    publishes nothing, so the pre-fetch array (the disk mirror, on a cold
  //    boot) stays painted as the live account with no error and no retry ───
  function Harness({ out }: { out: React.MutableRefObject<TaskData | null> }) {
    const d = useTaskData()
    out.current = d
    return <div data-testid="rows">{d.tasks.map((t) => t.uid).join(',')}</div>
  }

  it('re-issues the fan-out so the ghost row goes away', async () => {
    setCacheUser('admin')
    cacheLists([list()])
    cacheTasks([task({ uid: 'ghost' })])
    m.lists.mockResolvedValue([list()])
    let release: (v: Task[]) => void = () => {}
    m.tasks.mockReturnValueOnce(new Promise<Task[]>((res) => { release = res }))
      .mockResolvedValue([])
    m.complete.mockRejectedValue(new HttpError(404, 'that item no longer exists'))

    const out = { current: null as TaskData | null }
    render(<DataProvider rev={0} onExpire={vi.fn()}><Harness out={out} /></DataProvider>)
    expect(screen.getByTestId('rows')).toHaveTextContent('ghost')
    await waitFor(() => expect(m.tasks).toHaveBeenCalledTimes(1))

    // The write, inside the fan-out's flight, against the row that is gone.
    await act(async () => { await out.current!.toggle(task({ uid: 'ghost' })) })
    expect(m.complete).toHaveBeenCalled()
    // Now the fan-out lands: the server has no such task.
    await act(async () => { release([]) })

    await waitFor(() => expect(m.tasks.mock.calls.length).toBeGreaterThanOrEqual(2))
    await waitFor(() => expect(screen.getByTestId('rows')).toHaveTextContent(''))
  })
})

// ════════════════════════════════════════════════════════════════════════════
// Focus
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — a task row from a list that failed to load', () => {
  // ── focus.ts:156 — `finished()` answers `tasksLoaded` for a row whose task is
  //    not in the array, and one list's GET failing removes its tasks from the
  //    array; so the row the server named is counted done, the surface prints
  //    "All done." with an End button, and a sync is sent off a client-only
  //    misjudgement ─────────────────────────────────────────────────────────
  const work = list({ id: 'work', href: '/work/', name: 'Work' })
  const shared = list({ id: 'shared', href: '/shared/', name: 'Shared' })
  const poison = () => {
    m.lists.mockResolvedValue([work, shared])
    m.tasks.mockImplementation(async (id: string) => {
      if (id === 'shared') throw new HttpError(500, 'poison VTODO')
      return [task({ uid: 'w1', list: 'work', summary: 'Ship the invoice' })]
    })
  }
  const rows = [
    entry({ entry_id: 't1', kind: 'task', list: 'shared', uid: 's1', title: null, position: 1 }),
    entry({ entry_id: 'n2', title: 'Memo', position: 2 }),
  ]

  it('keeps the Focus surface on the row rather than declaring the queue done', async () => {
    poison()
    m.day.mockResolvedValue(plan(rows))
    m.focus.mockResolvedValue(session({ entry_id: 't1' }))
    showFocus()
    await waitFor(() => expect(m.tasks).toHaveBeenCalledTimes(2))
    // The banner is the signal that the pane is short, as TasksView has it.
    expect(await screen.findByText(/Couldn.t load Shared/)).toBeInTheDocument()

    expect(screen.queryByText('All done.')).not.toBeInTheDocument()
    expect(screen.queryByText('This task is no longer in your lists')).not.toBeInTheDocument()
    expect(screen.getByRole('heading')).toBeInTheDocument()   // the current row, still
    expect(screen.getByText('0 / 2 done')).toBeInTheDocument()
    await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
    expect(m.focusClock).not.toHaveBeenCalledWith(today(), { action: 'sync' })
  })

  it('CONTROL: still syncs when the named row really is finished', async () => {
    poison()
    m.day.mockResolvedValue(plan([entry({ entry_id: 'n1', done_at: new Date().toISOString() })]))
    m.focus.mockResolvedValue(session({ entry_id: 'n1' }))
    showFocus()
    await waitFor(() => expect(m.focusClock).toHaveBeenCalledWith(today(), { action: 'sync' }))
  })

  it('does not mark such a row orphan on the Home day plan, and says the list failed', async () => {
    poison()
    m.day.mockResolvedValue(plan(rows))
    showHome([
      { id: 'p', kind: 'day_plan', x: 0, y: 0, w: 6, h: 6 },
      { id: 't', kind: 'today', x: 6, y: 0, w: 6, h: 6 },
    ])
    await waitFor(() => expect(m.tasks).toHaveBeenCalledTimes(2))
    await screen.findByText('Memo')
    expect(screen.queryByText('This task is no longer in your lists')).not.toBeInTheDocument()
    expect(screen.getAllByText(/Couldn.t load Shared/).length).toBeGreaterThan(0)
    expect(screen.queryByText('Nothing due today.')).not.toBeInTheDocument()
  })
})

describe('2026-09-03 — the cap toggle on the Focus surface', () => {
  // ── FocusView.tsx:272 — the settle maps over the plan AFTER the optimistic
  //    paint, so on failure `capped: e.capped` writes the optimistic value back
  //    over itself; the client's local flag then drives a real `pass` ────────
  it('rolls a failed cap toggle back and never passes the row', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    m.day.mockResolvedValue(plan([
      entry({ entry_id: 'n1', title: 'Memo', estimate_minutes: 1, capped: false, worked_seconds: 55 }),
      entry({ entry_id: 'n2', title: 'Invoice', position: 2 }),
    ]))
    m.patchDayEntry.mockRejectedValue(new HttpError(502, 'bad gateway'))
    showFocus()
    await screen.findByRole('heading', { name: 'Memo' })
    const cap = screen.getByRole('button', { name: 'Whether to stop at the estimate' })
    expect(cap).toHaveTextContent('Until done')
    await user.click(cap)
    await waitFor(() => expect(m.patchDayEntry).toHaveBeenCalledWith(today(), 'n1', { capped: true }))
    await waitFor(() => expect(cap).toHaveTextContent('Until done'))
    tick(10)
    expect(m.focusCursor).not.toHaveBeenCalled()
  })
})

describe('2026-09-03 — a failed read on the Focus surface', () => {
  // ── FocusView.tsx:359 — `guard` swallows the failure into a toast, `planTried`
  //    stays false, and the render emits `body = null`: a header over an empty
  //    page with no error and no retry, the defect TodayView was fixed for ────
  it('says the day could not be read, and Retry re-reads it', async () => {
    m.day.mockRejectedValueOnce(new HttpError(502, 'bad gateway'))
      .mockResolvedValue(plan([entry()]))
    showFocus()
    expect(await screen.findByText(/Couldn.t load/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('heading', { name: 'Memo' })).toBeInTheDocument()
    expect(m.day).toHaveBeenCalledTimes(2)
  })

  it('says so for the session read too', async () => {
    m.focus.mockRejectedValueOnce(new HttpError(502, 'bad gateway'))
      .mockResolvedValue(session())
    showFocus()
    expect(await screen.findByText(/Couldn.t load/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('heading', { name: 'Memo' })).toBeInTheDocument()
    expect(m.focus).toHaveBeenCalledTimes(2)
  })
})

describe('2026-09-03 — "you were away", said to someone who was here', () => {
  // ── focus.ts:131 — `wasAway` is a pure function of the anchor's age, and the
  //    server never clears `running_since` when a phase merely runs out, so 90s
  //    after a bell announced on a LIVE screen the label flips to "you were
  //    away". The fix latches how the END was experienced: announced on a
  //    visible document, the phase stays "over" however long the owner takes.
  //    Not the `ended` effect's own firing — a throttled background tab fires
  //    it too — but the document's visibility at that moment, which is the
  //    presence signal the verifier asked for ─────────────────────────────────
  it('keeps saying "Interval over" after the grace on a screen that heard the bell', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    m.focus.mockResolvedValue(session({}, 1500))
    showFocus()                                     // autoContinue off: the default
    await screen.findByRole('heading', { name: 'Memo' })
    tick(2)
    expect(playChime).toHaveBeenCalledWith('focus')
    expect(screen.getByText('Interval over')).toBeInTheDocument()
    tick(120)
    expect(screen.getByText('Interval over')).toBeInTheDocument()
    expect(screen.queryByText('Interval over · you were away')).not.toBeInTheDocument()
    expect(screen.queryByText(/Nothing rolled on without you/)).not.toBeInTheDocument()
  })

  it('CONTROL: still says away when the bell rang in a hidden tab', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const desc = Object.getOwnPropertyDescriptor(Document.prototype, 'visibilityState')
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
    try {
      m.focus.mockResolvedValue(session({}, 1500))
      showFocus()
      await screen.findByRole('heading', { name: 'Memo' })
      tick(2)
      expect(screen.getByText('Interval over')).toBeInTheDocument()
      tick(120)
      expect(screen.getByText('Interval over · you were away')).toBeInTheDocument()
    } finally {
      delete (document as unknown as Record<string, unknown>).visibilityState
      if (desc) Object.defineProperty(Document.prototype, 'visibilityState', desc)
    }
  })
})

// ════════════════════════════════════════════════════════════════════════════
// Scheduling
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — the booking link the owner copies', () => {
  // ── SchedulingView.tsx:83 — the URL is built from `location.origin`, which
  //    inside the Windows client is the loopback server; the DTO now carries
  //    the server's absolute `url` when a public URL is configured ──────────
  const clip = () => {
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    return writeText
  }

  it('copies the absolute URL the server names', async () => {
    const writeText = clip()
    m.schedulingLinks.mockResolvedValue([link({ url: 'https://tasks.example.com/book/tok1' })])
    render(<SchedulingView rev={0} onExpire={vi.fn()} />)
    expect(await screen.findByText('https://tasks.example.com/book/tok1')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Copy link' }))
    expect(writeText).toHaveBeenCalledWith('https://tasks.example.com/book/tok1')
  })

  it('CONTROL: falls back to this origin when the server names none', async () => {
    const writeText = clip()
    m.schedulingLinks.mockResolvedValue([link({ url: null })])
    render(<SchedulingView rev={0} onExpire={vi.fn()} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Copy link' }))
    expect(writeText).toHaveBeenCalledWith(`${location.origin}/book/tok1`)
  })
})

describe('2026-09-03 — repointing a link whose calendar was deleted', () => {
  // ── SchedulingView.tsx:327 — the editor seeds `calendar` with the deleted id,
  //    which matches no option; React selects the first option in the DOM while
  //    state (and the PATCH) still carries the deleted slug, and the server
  //    refuses it with a message naming an id nowhere on screen ──────────────
  it('sends the calendar the editor shows', async () => {
    m.schedulingLinks.mockResolvedValue([link({ calendar: 'old', calendar_missing: true, calendar_name: null })])
    m.calendars.mockResolvedValue([calendar('c1', 'Work'), calendar('c2', 'Home')])
    m.patchSchedulingLink.mockImplementation(async (_t, body) => link({ ...body, calendar_missing: false } as never))
    render(<SchedulingView rev={0} onExpire={vi.fn()} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
    const select = await screen.findByLabelText('Calendar') as HTMLSelectElement
    expect(select.value).toBe('c1')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(m.patchSchedulingLink).toHaveBeenCalled())
    expect((m.patchSchedulingLink.mock.calls[0][1] as { calendar: string }).calendar).toBe('c1')
  })
})

// ════════════════════════════════════════════════════════════════════════════
// Home
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — the Home scheduling modules when their fetch fails', () => {
  // ── HomeView.tsx:744 — `makeGuard` swallows the failure, `links`/`bookings`
  //    stay `[]`, and the modules print "No booking links yet." / "No upcoming
  //    bookings." over a 502 — the confident lie SchedulingView was fixed for ─
  it('does not print the empty copy over a failed fetch', async () => {
    m.schedulingLinks.mockRejectedValue(new HttpError(502, 'bad gateway'))
    showHome([
      { id: 'l', kind: 'booking_links', x: 0, y: 0, w: 6, h: 6 },
      { id: 'b', kind: 'bookings', x: 6, y: 0, w: 6, h: 6 },
    ])
    await waitFor(() => expect(m.schedulingLinks).toHaveBeenCalled())
    expect(await screen.findAllByText(/Couldn.t load/)).not.toHaveLength(0)
    expect(screen.queryByText('No booking links yet.')).not.toBeInTheDocument()
    expect(screen.queryByText('No upcoming bookings.')).not.toBeInTheDocument()
  })

  it('CONTROL: prints it when the account really has none', async () => {
    showHome([{ id: 'l', kind: 'booking_links', x: 0, y: 0, w: 6, h: 6 }])
    expect(await screen.findByText('No booking links yet.')).toBeInTheDocument()
  })
})

describe('2026-09-03 — the Home bookings module with links in two zones', () => {
  // ── HomeView.tsx:833 — `BookingList` sorted by `a.start.localeCompare(b.start)`;
  //    `start` carries each link's own offset, so the text order is not the
  //    clock order. Found by the verifier of the store-side finding
  //    (list_bookings ordered by the same string) and fixed on both sides. ────
  it('lists them in clock order, not string order', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-09-01T12:00:00Z'))
    const booking = (id: string, name: string, start: string) => ({
      id, link: 'l', link_title: null, event_uid: id, calendar: 'c1', name,
      email: 'x@example.com', notes: null, start, end: start, created_at: start,
    })
    m.schedulingBookings.mockResolvedValue([
      // 09:00 in Los Angeles is 16:00Z; 10:00 in Berlin is 08:00Z — earlier.
      booking('la', 'Los Angeles', '2026-09-02T09:00:00-07:00'),
      booking('be', 'Berlin', '2026-09-02T10:00:00+02:00'),
    ])
    showHome([{ id: 'b', kind: 'bookings', x: 0, y: 0, w: 6, h: 6 }])
    await screen.findByText('Berlin')
    const names = Array.from(document.querySelectorAll('.dash-task-title')).map((n) => n.textContent)
    expect(names).toEqual(['Berlin', 'Los Angeles'])
    vi.useRealTimers()
  })
})

describe('2026-09-03 — the mini calendar across a month boundary', () => {
  // ── HomeView.tsx:192 — `days` is memoised on `rev` alone, which moves only
  //    when the server publishes a change; a dashboard left open overnight on a
  //    quiet account keeps last month's grid ─────────────────────────────────
  it('moves to the new month at midnight', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date(2026, 7, 31, 23, 59, 50))
    showHome([{ id: 'c', kind: 'mini_calendar', x: 0, y: 0, w: 6, h: 6 }])
    const inMonth = () => document.querySelectorAll('.mini-day:not(.dim)').length
    await waitFor(() => expect(inMonth()).toBe(31))       // August
    tick(60)
    await waitFor(() => expect(inMonth()).toBe(30))       // September
  })
})

// ════════════════════════════════════════════════════════════════════════════
// i18n
// ════════════════════════════════════════════════════════════════════════════

describe('2026-09-03 — the counted strings', () => {
  // ── en.ts:61 — `reminder.hours`, `reminder.days`, `reminder.minutes` and
  //    `home.moduleCount` are flat strings, so the shipped 60- and 1440-minute
  //    reminder choices read "1 hours before" / "1 days before" (and "1 Stunden
  //    vorher" / "1 Tage vorher"), and a one-module board says "1 modules" ────
  it('take the singular for one', () => {
    expect(translate('en', 'reminder.hours', { n: 1 })).toBe('1 hour before')
    expect(translate('en', 'reminder.days', { n: 1 })).toBe('1 day before')
    expect(translate('en', 'reminder.minutes', { n: 1 })).toBe('1 minute before')
    expect(translate('en', 'home.moduleCount', { count: 1 })).toBe('1 module')
    expect(translate('de', 'reminder.hours', { n: 1 })).toBe('1 Stunde vorher')
    expect(translate('de', 'reminder.days', { n: 1 })).toBe('1 Tag vorher')
    expect(translate('de', 'reminder.minutes', { n: 1 })).toBe('1 Minute vorher')
    expect(translate('de', 'home.moduleCount', { count: 1 })).toBe('1 Modul')
  })

  it('CONTROL: and the plural for more', () => {
    expect(translate('en', 'reminder.hours', { n: 2 })).toBe('2 hours before')
    expect(translate('en', 'reminder.days', { n: 2 })).toBe('2 days before')
    expect(translate('en', 'home.moduleCount', { count: 5 })).toBe('5 modules')
    expect(translate('de', 'reminder.hours', { n: 2 })).toBe('2 Stunden vorher')
    expect(translate('de', 'home.moduleCount', { count: 5 })).toBe('5 Module')
  })
})
