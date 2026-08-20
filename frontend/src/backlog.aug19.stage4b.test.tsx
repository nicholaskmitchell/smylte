/**
 * The 2026-08-19 sweep, stage 4b: rendering, keys, focus/a11y, dashboard bounds
 * and the test-harness gap.
 *
 * **These eleven findings are OPEN.** Ten of the tests below assert the
 * behaviour the app SHOULD have and fail against the code as it stands, so each
 * is marked `it.fails` — the file passes while the finding is open, and the
 * moment one is fixed its pin XPASSes, the file goes red, and somebody has to
 * tick the finding off and drop the marker. Same contract as
 * `backlog.stage4.test.tsx`, whose api-mocking preamble this copies.
 *
 * The eleventh is a **test gap**, not a bug: the global `matchMedia` stub in
 * `src/test/setup.ts` answers `matches: false` for every query, so
 * `useIsMobile()` is permanently false and CalendarView's and HomeView's entire
 * mobile renders were never exercised by anything. That one is written as an
 * ORDINARY PASSING TEST — the missing coverage was the whole finding, and once
 * written it goes green, which is what the last line of its docstring records.
 * See `backend/tests/test_backlog_stage5.py` for the same distinction on the
 * backend side.
 *
 * The theme is what the user sees and what the user can reach: a React key that
 * is not unique so two real rows share one identity, a rename bar that retargets
 * itself onto a theme it was never opened for, a settings section frozen on
 * "Loading…", a login form whose two fields have no accessible name, a modal
 * with no keyboard way out, and a dashboard that quietly builds a layout the
 * server will refuse.
 *
 * Every pin here is BEHAVIOURAL: each drives the real component (or the real
 * exported function) and asserts what a user, a screen reader or the API would
 * see. None reads source text. Where a finding could correctly be repaired in
 * more than one shape, the assertion names the OUTCOME rather than the repair —
 * docs/STAGES.md records what pins that only accept the fix you imagined cost
 * the last time.
 */
import { useState } from 'react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DataProvider, useTaskData } from './data'
import { addModule, resizeModule, sanitizeLayout, MODULE_KINDS, type DashboardModule } from './dashboard'
import { setCacheUser } from './cache'
import { AppearancePanel } from './components/AppearancePanel'
import { ArchivedCalendarsSection } from './components/ArchivedCalendarsSection'
import { CalendarView } from './components/CalendarView'
import { DayPopover } from './components/DayPopover'
import { HomeView } from './components/HomeView'
import { Login } from './components/Login'
import { TaskModal } from './components/TaskModal'
import { TasksView } from './components/TasksView'
import type { Appearance } from './appearance'
import type { CalendarFit, DayEv } from './calendar'
import { api, type CalEvent, type List, type Task } from './api'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const work: List = {
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#D9480F',
}
const home: List = { ...work, id: 'l2', href: '/l2/', name: 'Home', color: '#1565C0' }

const cal: List = {
  id: 'c1', href: '/c1/', name: 'Work', is_task_list: false, is_calendar: true,
  open_count: 0, task_count: 0, event_count: 1, total: 1, color: '#D9480F',
}

const ev = (o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'e1', id: 'e1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
  summary: 'Standup', description: null, location: null,
  start: '2026-03-06T09:00:00', start_is_date: false,
  end: '2026-03-06T09:30:00', end_is_date: false, duration: null,
  all_day: false, status: null, tags: [], has_rrule: false,
  href: '/c1/e1.ics', etag: '"1"', ...o,
})

/** Today as YYYY-MM-DD. The grid opens on the current month, so a fixture has
 *  to be dated into it or it renders in no cell at all. */
const todayYmd = () => {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** Force the mobile breakpoint (or put the desktop stub back). Same shape as the
 *  helper Sidebar.test.tsx defines — the global stub in setup.ts is frozen at
 *  the desktop answer, which is finding 11 below. */
const stubMatchMedia = (matches: boolean) => {
  window.matchMedia = ((query: string) => ({
    matches, media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

/** CalendarView with the props App holds for it, controlled where the real app
 *  controls them (a harness that swallowed the change would test toggles that
 *  appear to do nothing). */
function CalendarHarness({ taskLists = [] as string[], fit = 'dynamic' as CalendarFit }) {
  const now = new Date()
  const [cursor, setCursor] = useState(() => new Date(now.getFullYear(), now.getMonth(), 1))
  const [shown, setShown] = useState(taskLists)
  return (
    <DataProvider rev={0} onExpire={vi.fn()}>
      <CalendarView onExpire={vi.fn()} cursor={cursor} onCursorChange={setCursor}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenCalendars={[]} onHiddenCalendarsChange={vi.fn()}
        archivedCalendars={[]} onArchivedCalendarsChange={vi.fn()}
        calTaskLists={shown} onCalTaskListsChange={setShown}
        calShowDone={false} onCalShowDoneChange={vi.fn()}
        fit={fit} />
    </DataProvider>
  )
}

let errSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.clearAllMocks()
  setCacheUser('')            // nothing seeds from disk; every test starts cold
  localStorage.clear()
  m.lists.mockResolvedValue([work])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([cal])
  m.events.mockResolvedValue([])
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => errSpy.mockRestore())

/** Whatever React said about duplicate keys since the last clear. */
const keyWarnings = () =>
  errSpy.mock.calls.flat().join(' ').match(/same key/gi)?.length ?? 0

// ── keys: one uid, two collections ──────────────────────────────────────────

describe('aug19 stage 4b — chip, dot, agenda and popover identity', () => {
  // AUDIT open: CalendarView.tsx:614 (and :545, :548, :648, :652; DayPopover.tsx:103, :106)
  it.fails('gives every task chip and every popover row a key unique per collection', async () => {
    // The stage-4 fix keyed the desktop EVENT chip `${calendar}::${id}` and
    // tested exactly that element. A CalDAV UID is unique per COLLECTION, not
    // per account, and the trust model treats Tasks.org / DAVx5 / Thunderbird
    // as equal-rights writers — so the same uid legitimately lives in two lists
    // (or two calendars), and every other render site still keys on the bare
    // `t.uid` / `e.id`. React drops the duplicate from its key map: the row is
    // torn down and recreated on every update, and a click handler can bind to
    // the wrong instance.
    //
    // Asserted as "React raised no duplicate-key warning while both copies
    // rendered", which is the defect itself rather than any particular key
    // string — a fix that composes the key some other way passes just as well.
    const due = todayYmd()
    m.lists.mockResolvedValue([work, home])
    m.tasks.mockImplementation(async (listId: string) =>
      [task({ uid: 't1', list: listId, summary: 'Renew passport', due })])

    const desktop = render(<CalendarHarness taskLists={['l1', 'l2']} />)
    // Both copies are real rows and both must render…
    await waitFor(() => expect(document.querySelectorAll('.cal-task')).toHaveLength(2))
    expect(keyWarnings(), 'desktop task chips').toBe(0)
    desktop.unmount()

    // …the same on a phone, where the cell carries dots and the agenda below
    // the grid carries the rows (both keyed the same way)…
    errSpy.mockClear()
    stubMatchMedia(true)
    try {
      const mobile = render(<CalendarHarness taskLists={['l1', 'l2']} />)
      await waitFor(() => expect(document.querySelectorAll('.ev-dot.task')).toHaveLength(2))
      expect(document.querySelectorAll('.day-agenda .agenda-task')).toHaveLength(2)
      expect(keyWarnings(), 'mobile dots and day agenda').toBe(0)
      mobile.unmount()
    } finally { stubMatchMedia(false) }

    // …and in the "+N more" popover, which lists both kinds.
    errSpy.mockClear()
    const shared = (calendar: string): DayEv =>
      ev({ uid: 'shared', id: 'shared', calendar, summary: 'Standup' })
    render(<DayPopover day={due} x={40} y={40}
      events={[shared('/c1/'), shared('/c2/')]}
      tasks={[task({ uid: 't1', list: 'l1', summary: 'Renew passport', due }),
        task({ uid: 't1', list: 'l2', summary: 'Renew passport', due })]}
      styleOf={() => undefined} taskStyleOf={() => undefined} onClose={vi.fn()} />)
    expect(within(screen.getByRole('dialog')).getAllByText('Standup')).toHaveLength(2)
    expect(within(screen.getByRole('dialog')).getAllByText(/Renew passport/)).toHaveLength(2)
    expect(keyWarnings(), 'the day popover').toBe(0)
  })
})

/** The tasks pane over a real provider — the Sidebar comes with it. */
function tasksSetup() {
  render(
    <DataProvider rev={0} onExpire={vi.fn()}>
      <TasksView onExpire={vi.fn()} view="list" onView={vi.fn()}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenLists={[]} onHiddenListsChange={vi.fn()}
        groups={[]} onGroupsChange={vi.fn()}
        collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
        collapsedTasks={[]} onCollapsedTasksChange={vi.fn()}
        showCompleted={false} />
    </DataProvider>,
  )
  return userEvent.setup()
}

describe('aug19 stage 4b — the tasks pane and one uid in two lists', () => {
  // AUDIT open: TasksView.tsx:442
  it.fails('deletes only the copy whose row was clicked', async () => {
    // Rows key on the bare uid and the provider's optimistic mutations match on
    // it too, so the two copies are one row as far as the pane is concerned:
    // React warns about the duplicate key, and `del` on the Work copy — correct
    // on the wire — filters BOTH out of local state. The Home task is gone from
    // the pane although it still exists on the server, and only a full refetch
    // brings it back.
    m.lists.mockResolvedValue([work, home])
    m.tasks.mockImplementation(async (listId: string) =>
      [task({ uid: 'shared', list: listId, summary: 'Ship it' })])
    m.deleteTask.mockResolvedValue(null)      // what a 204 resolves to
    const user = tasksSetup()

    await waitFor(() => expect(screen.getAllByText('Ship it')).toHaveLength(2))
    expect(keyWarnings()).toBe(0)

    const first = screen.getAllByText('Ship it')[0].closest('.task') as HTMLElement
    await user.click(within(first).getByTitle('Delete'))

    await waitFor(() => expect(m.deleteTask).toHaveBeenCalledTimes(1))
    expect(m.deleteTask.mock.calls[0][0]).toBe('l1')          // only the Work copy
    // …and the other list's task is still on screen.
    expect(screen.queryAllByText('Ship it')).toHaveLength(1)
  })
})

// ── the completed pane ──────────────────────────────────────────────────────

describe('aug19 stage 4b — the Completed pane and a RELATED-TO ring', () => {
  // AUDIT open: TasksView.tsx:334
  it.fails('shows a completed ring another client authored', async () => {
    // `tops` elects a ring's lowest uid as its root so the loop renders;
    // `completedTops`, written later for this pane, uses a plain one-hop "my
    // parent is not also done" test. In a cycle every member fails it, so the
    // pane — the one surface whose whole job is to show completed tasks —
    // renders "No completed tasks." and both are unreachable.
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Alpha', parent: 'b', completed: true, status: 'COMPLETED' }),
      task({ uid: 'b', summary: 'Bravo', parent: 'a', completed: true, status: 'COMPLETED' }),
      // The control: an ordinary completed task, so "the pane rendered and the
      // fetch landed" is established before the ring is looked for.
      task({ uid: 'c', summary: 'Charlie', completed: true, status: 'COMPLETED' }),
    ])
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TasksView onExpire={vi.fn()} view="list" onView={vi.fn()}
          sideCollapsed={false} onToggleSide={vi.fn()}
          hiddenLists={[]} onHiddenListsChange={vi.fn()}
          groups={[]} onGroupsChange={vi.fn()}
          collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
          collapsedTasks={[]} onCollapsedTasksChange={vi.fn()}
          showCompleted={false} />
      </DataProvider>,
    )
    const user = userEvent.setup()
    await user.click(await screen.findByText(/View completed/))

    await screen.findByText('Charlie')
    expect(screen.queryByText('No completed tasks.')).toBeNull()
    // However the ring is anchored — one root with the other nested, or both at
    // the top level — neither task may disappear.
    expect(screen.getAllByText('Alpha').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Bravo').length).toBeGreaterThan(0)
  })
})

// ── modals and forms: the keyboard route ────────────────────────────────────

describe('aug19 stage 4b — TaskModal', () => {
  const props = {
    task: task(), lists: [work], defaultList: 'l1',
    onClose: vi.fn(), onCreate: vi.fn(), onSave: vi.fn(),
    onDelete: vi.fn(), onMultiple: vi.fn(),
  }

  // AUDIT open: TaskModal.tsx:121
  it.fails('closes on Escape, like every other dialog in the app', async () => {
    // The app's most-used dialog registers no keydown listener at all, while
    // AddMultipleModal, AppearancePanel, DayPopover, SettingsMenu and the
    // booking-link editor all honour Escape. With `aria-modal="true"` and no
    // focus trap either, a keyboard or screen-reader user has no keyboard route
    // out of it. The key is dispatched at the dialog so it bubbles through the
    // modal, the scrim, the document and the window — a handler on any of those
    // satisfies this.
    const onClose = vi.fn()
    render(<TaskModal {...props} onClose={onClose} />)
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })
})

describe('aug19 stage 4b — the login form', () => {
  // AUDIT open: Login.tsx:34
  it.fails('gives both fields an accessible name', async () => {
    // Both labels are siblings of their inputs with no htmlFor, no id and no
    // aria-label, and they do not wrap them — so a screen reader announces
    // "edit text, blank" and "password edit, blank", and clicking a label
    // focuses nothing. This is the only form in the app that gets it wrong
    // (TaskModal, the event modal, TabsSection and AppearancePanel all pair
    // them), and the only page an unauthenticated visitor ever sees.
    render(<Login onLogin={vi.fn()} />)

    const username = screen.queryByLabelText('Username')
    const password = screen.queryByLabelText('Password')
    expect(username, 'the Username field has no accessible name').not.toBeNull()
    expect(password, 'the Password field has no accessible name').not.toBeNull()

    // …and the names are on the right controls, not merely present.
    await userEvent.type(username as HTMLElement, 'admin')
    expect(username).toHaveValue('admin')
    expect(password).toHaveAttribute('type', 'password')
  })
})

// ── settings: sections that never finish, and a rename that retargets ───────

describe('aug19 stage 4b — archived calendars', () => {
  // AUDIT open: ArchivedCalendarsSection.tsx:39
  it.fails('stops saying "Loading…" once the fetch has failed', async () => {
    // `setLoaded(true)` sits inside the guarded callback, after the awaited
    // request; `makeGuard` swallows the rejection and returns undefined, so on
    // failure the statement is never reached and `loaded` stays false for the
    // life of the mount. The section then renders "Loading…" forever with no
    // error state and no retry — the only way out is to leave the settings
    // section and come back, which remounts it. ConnectionsSection, the other
    // body in the same panel, guards this with `.finally`.
    //
    // What replaces it is deliberately not asserted: an empty list, a
    // "couldn't load" message or a retry button all close the finding.
    m.calendars.mockRejectedValue(new Error('network down'))
    render(<ArchivedCalendarsSection archived={['c1']} onChange={vi.fn()}
      onExpire={vi.fn()} viewing={null} onViewing={vi.fn()} />)

    await act(async () => { await Promise.resolve() })
    expect(screen.queryByText('Loading…'),
      'the archived-calendars section is still saying Loading…').toBeNull()
  })
})

describe('aug19 stage 4b — the theme rename bar', () => {
  function AppearanceHarness({ initial }: { initial: Appearance }) {
    const [appearance, setAppearance] = useState(initial)
    return <AppearancePanel appearance={appearance} onChange={setAppearance}
      mode="light" onMode={vi.fn()} onClose={vi.fn()} />
  }

  // AUDIT open: AppearancePanel.tsx:45
  it.fails('never renames the theme the user switched to with the old name', async () => {
    // `renaming`/`name` are captured when Rename is pressed and cleared only by
    // the row's own Save and Cancel. Nothing resets them when `appearance.active`
    // changes underneath, and the row's guard is `renaming && active` — "some
    // theme is active", not "still the one this was opened for". The picker sits
    // directly above the row, so switching themes leaves it open, pre-filled
    // with the previous theme's name and now bound to a different object.
    //
    // Either shape of fix passes: close the row on a target change, or re-prime
    // it for the new target. What must not happen is two themes reading the same
    // name — the only thing that tells them apart, since ids are never shown.
    const user = userEvent.setup()
    render(<AppearanceHarness initial={{
      active: 'a',
      themes: [
        { id: 'a', name: 'Alpha', base: 'light', light: {}, dark: {} },
        { id: 'b', name: 'Beta', base: 'light', light: {}, dark: {} },
      ],
    }} />)

    await user.click(screen.getByRole('button', { name: 'Rename' }))
    expect(screen.getByLabelText('Theme name')).toHaveValue('Alpha')

    // Change of mind: look at Beta instead.
    await user.selectOptions(screen.getByRole('combobox', { name: 'Theme' }), 'b')
    // If the row survived the switch, dismissing it must not rename anything.
    const save = screen.queryByRole('button', { name: 'Save' })
    if (save) await user.click(save)

    const names = screen.getAllByRole('option').map((o) => o.textContent)
    expect(names.filter((n) => n === 'Alpha')).toHaveLength(1)
    expect(names).toContain('Beta')
  })
})

// ── bounds: a layout the server will refuse ─────────────────────────────────

describe('aug19 stage 4b — the dashboard grid', () => {
  // AUDIT open: dashboard.ts:93
  it.fails('never emits a module below the row the server accepts', () => {
    // `clampToGrid` bounds y to MAX_ROWS = 200, but `packDown` runs AFTER the
    // clamp and re-derives y by stacking, and nothing re-clamps the result. So
    // `sanitizeLayout` — the function whose entire job is to hand the caller a
    // legal layout — can emit y > 200, which `DashboardModule.y`
    // (Field(ge=0, le=200), app.py:381) rejects. `saveSettingsSoon` batches the
    // dashboard with anything else written in the same 400 ms window, so the
    // whole PUT 422s and those preferences are lost too: from then on every
    // drag, resize, add or remove raises
    // "dashboard.6.y: Input should be less than or equal to 200" and the
    // arrangement disappears on the next reload.
    //
    // Every geometry below is reachable through the editor — `resizeModule`
    // itself clamps w to 12 and h to 40, so each module is individually legal.
    // It is only the stack that overflows.
    let mods: DashboardModule[] = []
    MODULE_KINDS.forEach((kind, i) => { mods = addModule(mods, kind, `m${i}`) })
    for (const mod of [...mods]) mods = resizeModule(mods, mod.id, 12, 40)

    const out = sanitizeLayout(mods)
    expect(out).toHaveLength(MODULE_KINDS.length)
    expect(out.map((mo) => mo.y).filter((y) => y > 200)).toEqual([])
  })
})

// ── the SSE stream and a lapsed session ─────────────────────────────────────

describe('aug19 stage 4b — an SSE reconnect that 401s', () => {
  /** Minimal EventSource stand-in — jsdom has none, and the failure mode only
   *  happens over a network. Same shape as the one in api.test.ts. */
  class FakeES {
    static CONNECTING = 0
    static OPEN = 1
    static CLOSED = 2
    static instances: FakeES[] = []
    readyState = 0
    onopen: (() => void) | null = null
    onmessage: ((e: { data: string }) => void) | null = null
    onerror: (() => void) | null = null
    constructor(public url: string) { FakeES.instances.push(this) }
    close() { this.readyState = 2 }
    accept() { this.readyState = 1; this.onopen?.() }
    /** Non-200 (401 / 502): the spec fails the connection outright. */
    hardFail() { this.readyState = 2; this.onerror?.() }
  }

  // AUDIT open: api.ts:475
  it.fails('discovers a session that lapsed while the tab was idle', async () => {
    // The comment above `subscribe` names this case ("a 401 once the session TTL
    // lapses") and the handling it describes is an unbounded capped-backoff
    // reconnect loop. EventSource exposes no status, so a 401 is
    // indistinguishable from a 502 and nothing in this path can ever route one
    // to the auth guard. Nothing else in the SPA polls and `rev` only advances
    // on an SSE frame, so a tab whose session expires over a long weekend keeps
    // showing Friday's tasks and calendar — with no staleness chrome and no
    // login card — while firing an unauthenticated GET /api/events every 30 s
    // for the life of the page.
    //
    // Deliberately permissive about the repair: a fix may probe the session over
    // HTTP (`api.me()` and an onExpire callback, as suggested), or give up and
    // surface a "live updates disconnected" state. Either one satisfies this.
    // What it may not do is retry silently forever having never asked anybody.
    const { subscribe } = await vi.importActual<typeof import('./api')>('./api')
    const fetchMock = vi.fn().mockResolvedValue({
      status: 401, ok: false, statusText: 'Unauthorized',
      json: () => Promise.resolve({ detail: 'authentication required' }),
    })
    FakeES.instances = []
    vi.stubGlobal('EventSource', FakeES)
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()
    try {
      const stop = subscribe(vi.fn())
      FakeES.instances[0].accept()           // the stream the tab has been on

      // The session lapses; the server restarts; every reconnect now answers 401.
      // Twenty rounds is over ten minutes of wall clock at the 30 s cap.
      let gaveUp = false
      for (let i = 0; i < 20; i++) {
        const before = FakeES.instances.length
        FakeES.instances[before - 1].hardFail()
        await vi.advanceTimersByTimeAsync(60_000)
        if (FakeES.instances.length === before) { gaveUp = true; break }
      }
      const probed = fetchMock.mock.calls.length > 0        // it asked the server
      expect(probed || gaveUp,
        'the reconnect loop neither probed the session nor stopped retrying').toBe(true)
      stop()
    } finally {
      vi.useRealTimers()
      vi.unstubAllGlobals()
    }
  })
})

// ── the provider's fan-out key ──────────────────────────────────────────────

/** Exposes the provider's actions and its request count to the test. */
function Probe({ onReady }: { onReady: (d: ReturnType<typeof useTaskData>) => void }) {
  const d = useTaskData()
  onReady(d)
  return <div data-testid="lists">{d.lists.map((l) => l.id).join(',')}</div>
}

describe('aug19 stage 4b — reordering the sidebar', () => {
  // AUDIT open: data.tsx:180
  it('does not refetch every task in the account when only the order changed', async () => {
    // `loadKey` is `*|${lists.map(l => l.id).join(',')}` — order-sensitive — and
    // it is both a dependency of the task fan-out effect and the commit guard
    // for every response in flight. A sidebar drag-reorder hands back the SAME
    // ids in a new order, so the key changes: the effect re-runs and issues one
    // GET /api/lists/{id}/tasks per list for data that cannot have changed, and
    // any response already in flight fails `key === keyRef.current` and is
    // thrown away. Rename and recolor don't change ids and correctly don't
    // refetch, which is what shows the identity is meant to be the SET.
    // WIDENED. The original drove `setLists` from a Probe, which proves the
    // provider's own dep but not that the sidebar reaches it; the drag is fired
    // on the real rows here instead. The two halves the key controls are then
    // driven separately: the fan-out (this test) and the commit guard (below).
    m.lists.mockResolvedValue([work, home])
    m.tasks.mockResolvedValue([])
    const user = tasksSetup()

    await waitFor(() => expect(m.tasks).toHaveBeenCalledTimes(2))

    // Sidebar's own drop handler: dragStart on one row, drop on another. It
    // computes the new order, calls `onItems` (the provider's setLists) and
    // PATCHes the order to the server.
    const rows = () => Array.from(document.querySelectorAll('.side-item')) as HTMLElement[]
    const rowFor = (name: string) =>
      rows().find((r) => r.textContent?.includes(name)) as HTMLElement
    const from = rowFor('Home'), onto = rowFor('Work')
    expect(from && onto).toBeTruthy()

    fireEvent.dragStart(from, { dataTransfer: { effectAllowed: '' } })
    fireEvent.dragOver(onto)
    fireEvent.drop(onto)
    await act(async () => { await Promise.resolve() })

    expect(m.tasks).toHaveBeenCalledTimes(2)
    // …and the reorder did reach the server, so this is not passing because the
    // drag never happened.
    expect(m.reorderLists).toHaveBeenCalledTimes(1)
    void user
  })

  // CONTROL for data.tsx:194 — the same key, its OTHER consumer. Green today,
  // and it must stay green; it is the reason this commit changes the CONSTANT
  // rather than the effect's dependency list.
  it('keeps a task fetch that was in flight when the order changed', async () => {
    // `loadKey` is not only the effect's dependency, it is the commit guard:
    // `if (token === fetchToken.current && key === keyRef.current) setTasks(ts)`.
    // A reorder changes the key under a response already on the wire, so that
    // response IS discarded today — but the effect also re-runs, so the tasks
    // arrive via the second fan-out and nothing is visibly lost. That is why
    // this is a control and not a pin: it passes now.
    //
    // It becomes load-bearing the moment the refetch is the thing being
    // removed. Sort the ids in the effect's dependency list only, leave
    // `keyRef` on the unsorted key, and this path drops the response with
    // nothing left to re-issue it — strictly worse than the bug being fixed.
    let release!: (rows: Task[]) => void
    m.lists.mockResolvedValue([work, home])
    m.tasks.mockImplementation((listId: string) =>
      listId === 'l1'
        ? new Promise<Task[]>((res) => { release = (rows) => res(rows) })
        : Promise.resolve([]))

    let d!: ReturnType<typeof useTaskData>
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <Probe onReady={(x) => { d = x }} />
      </DataProvider>,
    )
    await waitFor(() => expect(m.tasks).toHaveBeenCalledTimes(2))

    // The drag lands while Work's tasks are still on the wire.
    await act(async () => { d.setLists([home, work]) })
    await act(async () => {
      release([task({ uid: 'inflight', list: 'l1', summary: 'Still arriving' })])
      await Promise.resolve()
    })
    await act(async () => { await Promise.resolve() })

    expect(d.tasks.map((t) => t.uid)).toContain('inflight')
  })

  // Control (passes today, must keep passing): the key is the SET, so changing
  // the set still refetches. Without this, "never re-run the effect" satisfies
  // the pin above and a newly-created list would never load its tasks.
  it('still refetches when a list is added or removed', async () => {
    m.lists.mockResolvedValue([work, home])
    m.tasks.mockResolvedValue([])

    let d!: ReturnType<typeof useTaskData>
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <Probe onReady={(x) => { d = x }} />
      </DataProvider>,
    )
    await waitFor(() => expect(m.tasks).toHaveBeenCalledTimes(2))

    const third: List = { ...home, id: 'l3', href: '/l3/', name: 'Reading' }
    await act(async () => { d.setLists([work, home, third]) })
    await waitFor(() => expect(m.tasks).toHaveBeenCalledTimes(5))   // 2 + a fan-out of 3

    await act(async () => { d.setLists([work, third]) })
    await waitFor(() => expect(m.tasks).toHaveBeenCalledTimes(7))   // + a fan-out of 2
  })
})

// ── the test gap: the mobile renders nothing ever reached ───────────────────

describe('aug19 stage 4b — the mobile breakpoint', () => {
  afterEach(() => stubMatchMedia(false))    // restore the desktop stub

  // AUDIT open: src/test/setup.ts:5 — a TEST GAP, and this is the missing test.
  // It PASSES: the mobile branches are correct as written, only uncovered. Kept
  // as an ordinary test (no `it.fails`) exactly as test_backlog_stage5.py keeps
  // the gaps that turned out to hide no bug — the finding is closed by this
  // test existing, and from here a regression in either branch fails CI.
  it('renders the mobile calendar and the mobile dashboard', async () => {
    // The global stub answers `matches: false` for every query and its
    // addEventListener is a no-op, so `useIsMobile()` is permanently false in
    // every suite that does not replace it — and only Sidebar, SettingsMenu and
    // hooks do. CalendarView and HomeView both branch on it, and neither of
    // their suites touched matchMedia, so a tap on a phone MEANING something
    // different (focus the day, not open the composer), the dots that replace
    // the chips, the whole day-agenda panel, the fixed-grid opt-out and
    // HomeView's entire stack were unexecuted by anything.
    stubMatchMedia(true)
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date(2026, 2, 5))       // Thu 5 March 2026; the 1st is a Sunday
    try {
      m.events.mockResolvedValue([ev({ summary: 'Retro' })])   // on the 6th
      const view = render(<CalendarHarness fit="fixed" />)
      await waitFor(() => expect(document.querySelector('.day-agenda')).not.toBeNull())

      const cellFor = (day: string) =>
        [...document.querySelectorAll('.cal-cell')].find((c) =>
          !c.classList.contains('dim')
          && c.querySelector('.daynum')?.textContent === day) as HTMLElement

      // (1) dots, not chips.
      expect(document.querySelectorAll('.ev-dot').length).toBeGreaterThan(0)
      expect(document.querySelectorAll('.cal-ev')).toHaveLength(0)
      // (2) the fitted grid is a desktop mode; mobile opts out even at fit="fixed".
      expect(document.querySelector('.cal-scroll')!.classList.contains('fixed')).toBe(false)
      // (3) the agenda follows the focused day, which starts at today (the 5th).
      const agenda = () => document.querySelector('.day-agenda') as HTMLElement
      expect(within(agenda()).getByText('Nothing this day.')).toBeInTheDocument()

      // (4) the first tap on another day FOCUSES it — it must not open the composer.
      fireEvent.click(cellFor('6'))
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(cellFor('6').classList.contains('focus')).toBe(true)
      expect(cellFor('5').classList.contains('focus')).toBe(false)
      expect(within(agenda()).getByText('Retro')).toBeInTheDocument()

      // (5) …and the second tap on the focused day opens it.
      fireEvent.click(cellFor('6'))
      expect(await screen.findByRole('dialog')).toBeInTheDocument()
      view.unmount()

      // (6) HomeView answers the same breakpoint with a plain stack in reading
      //     order, and none of the desktop arranging affordances.
      const layout: DashboardModule[] = [
        { id: 'b', kind: 'overdue', x: 6, y: 0, w: 6, h: 5 },
        { id: 'a', kind: 'today', x: 0, y: 0, w: 6, h: 6 },
        { id: 'c', kind: 'completed', x: 0, y: 6, w: 12, h: 5 },
      ]
      render(
        <DataProvider rev={0} onExpire={vi.fn()}>
          <HomeView rev={0} onExpire={vi.fn()} layout={layout} onLayoutChange={vi.fn()} />
        </DataProvider>,
      )
      await waitFor(() => expect(document.querySelectorAll('.dash-stack .dash-mod').length).toBe(3))
      expect([...document.querySelectorAll('.dash-stack .dash-mod .label')]
        .map((el) => el.textContent)).toEqual(['Today', 'Overdue', 'Recently completed'])
      expect(screen.queryByRole('button', { name: 'Arrange' })).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
})
