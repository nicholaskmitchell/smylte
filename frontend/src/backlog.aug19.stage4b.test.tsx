/**
 * The 2026-08-19 sweep, stage 4b: rendering, keys, focus/a11y, dashboard bounds
 * and the test-harness gap.
 *
 * **All eleven are CLOSED.** Ten began as `it.fails` pins asserting the
 * behaviour the app SHOULD have while failing against the code as it stood, and
 * the eleventh was always an ordinary test (see the test gap below). The findings
 * are fixed and ticked in docs/AUDIT.md, the markers are gone, and every test
 * here must stay green. Same contract as `backlog.stage4.test.tsx`, whose
 * api-mocking preamble this copies.
 *
 * The `AUDIT open:` banners below are kept in the past tense they were written
 * in: a closed finding's value is the record of what the bug was, which is what
 * stops it being reintroduced.
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
import { createRef, useState, type ReactElement } from 'react'
import { DEFAULT_FOCUS } from './focus'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DataProvider, useTaskData } from './data'
import {
  addModule, moveModule, removeModule, resizeModule, sanitizeLayout, MODULE_KINDS,
  type DashboardModule,
} from './dashboard'
import { setCacheUser } from './cache'
import { DEFAULT_TAB_ORDER } from './tabs'
import { useIsMobile } from './hooks'
import { breakpointListeners, resetBreakpoint, setBreakpoint } from './test/setup'
import { AddMultipleModal } from './components/AddMultipleModal'
import { SettingsMenu } from './components/SettingsMenu'
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
  completed: false, cancelled: false, parked: false, parked_at: null,
  priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  // Present on every DTO the server sends; see api.ts's Task.
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
 
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
  all_day: false, status: null, busy: true, notify_minutes_before: null, tags: [], has_rrule: false,
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
  it('gives every task chip and every popover row a key unique per collection', async () => {
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
      // `[data-kind="task"]`, not `.ev-dot.task`: the kind moved out of the
      // class list because a bare `task` class collides with the Tasks pane's
      // global row rule and rendered the 5px dot as a 28x23 slab. What this
      // line asserts — both copies render, and React raised no duplicate-key
      // warning — is unchanged.
      await waitFor(() =>
        expect(document.querySelectorAll('.ev-dot[data-kind="task"]')).toHaveLength(2))
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

  // WIDENING: "React raised no duplicate-key warning" is satisfied by a key
  // that is merely unique among SIBLINGS, and `key={i}` is exactly that. An
  // adversarial review got the index past every warning-counting pin above,
  // which reinstates the whole defect silently: an index key ties the DOM node
  // to the POSITION rather than to the row, so the moment the day's list
  // reorders, React repaints each node with a different row's content instead
  // of moving the node — and any state or handler bound to the node follows the
  // position, not the event. That is the "a click handler can bind to the wrong
  // instance" half of the finding, and no warning is ever raised for it.
  //
  // So this asserts identity directly: swap the order and demand that each
  // node FOLLOWED ITS ROW. A key derived from the row passes however it is
  // composed; a positional key cannot.
  it('moves a row\u2019s node with the row when the day reorders', () => {
    const due = todayYmd()
    // Two collections, one uid — the collision the finding is about. The
    // summaries differ only so the test can say which node is which; the key
    // is not derived from them either way.
    const evAt = (calendar: string, summary: string): DayEv =>
      ev({ uid: 'shared', id: 'shared', calendar, summary })
    const taskAt = (list: string, summary: string) =>
      task({ uid: 't1', list, summary, due })

    const props = (order: 0 | 1) => ({
      day: due, x: 40, y: 40,
      events: order === 0
        ? [evAt('/c1/', 'Standup work'), evAt('/c2/', 'Standup home')]
        : [evAt('/c2/', 'Standup home'), evAt('/c1/', 'Standup work')],
      tasks: order === 0
        ? [taskAt('l1', 'Passport work'), taskAt('l2', 'Passport home')]
        : [taskAt('l2', 'Passport home'), taskAt('l1', 'Passport work')],
      styleOf: () => undefined,
      taskStyleOf: () => undefined,
      onClose: vi.fn(),
    })

    const { rerender } = render(<DayPopover {...props(0)} />)
    const before = {
      evWork: screen.getByText('Standup work').closest('.agenda-ev'),
      evHome: screen.getByText('Standup home').closest('.agenda-ev'),
      taskWork: screen.getByText(/Passport work/).closest('.agenda-task'),
      taskHome: screen.getByText(/Passport home/).closest('.agenda-task'),
    }
    expect(before.evWork).not.toBe(before.evHome)
    expect(before.taskWork).not.toBe(before.taskHome)

    rerender(<DayPopover {...props(1)} />)

    expect(screen.getByText('Standup work').closest('.agenda-ev'),
      'the event row was repainted in place instead of moved: its key is positional')
      .toBe(before.evWork)
    expect(screen.getByText('Standup home').closest('.agenda-ev'),
      'the event row was repainted in place instead of moved: its key is positional')
      .toBe(before.evHome)
    expect(screen.getByText(/Passport work/).closest('.agenda-task'),
      'the task row was repainted in place instead of moved: its key is positional')
      .toBe(before.taskWork)
    expect(screen.getByText(/Passport home/).closest('.agenda-task'),
      'the task row was repainted in place instead of moved: its key is positional')
      .toBe(before.taskHome)
    expect(keyWarnings(), 'the reordered day popover').toBe(0)
  })

  // WIDENING: the mobile leg above duplicates a TASK uid, so the event dot and
  // the agenda's event row — two of the six sites the finding names — were
  // never driven by anything. Same defect, different map.
  it('gives every event dot and mobile agenda row a key unique per collection', async () => {
    const due = todayYmd()
    m.calendars.mockResolvedValue([cal, { ...cal, id: 'c2', href: '/c2/', name: 'Personal' }])
    m.events.mockImplementation(async (calId: string) =>
      [ev({ uid: 'shared', id: 'shared', calendar: `/${calId}/`,
        summary: 'Standup', start: `${due}T09:00:00`, end: `${due}T09:30:00` })])

    stubMatchMedia(true)
    try {
      render(<CalendarHarness />)
      await waitFor(() => expect(document.querySelectorAll('.ev-dot')).toHaveLength(2))
      expect(document.querySelectorAll('.day-agenda .agenda-ev')).toHaveLength(2)
      expect(keyWarnings(), 'mobile event dots and agenda rows').toBe(0)
    } finally { stubMatchMedia(false) }
  })

  // WIDENING: the other half of this finding's suggested fix, which no
  // assertion reached — `applyLocal` and `del` match on `e.uid` alone, so an
  // edit or a delete aimed at one collection's copy hits both. The React key is
  // only the visible symptom; this is the data loss under it.
  it('removes only the calendar copy that was deleted', async () => {
    const due = todayYmd()
    m.calendars.mockResolvedValue([cal, { ...cal, id: 'c2', href: '/c2/', name: 'Personal' }])
    m.events.mockImplementation(async (calId: string) =>
      [ev({ uid: 'shared', id: 'shared', calendar: `/${calId}/`,
        summary: 'Standup', start: `${due}T09:00:00`, end: `${due}T09:30:00` })])
    m.deleteEvent.mockResolvedValue(null as never)

    const user = userEvent.setup()
    render(<CalendarHarness />)
    await waitFor(() => expect(document.querySelectorAll('.cal-ev')).toHaveLength(2))

    const before = Array.from(document.querySelectorAll('.cal-ev'))
    await user.click(before[0] as HTMLElement)
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByText('Delete'))

    await waitFor(() => expect(m.deleteEvent).toHaveBeenCalledTimes(1))
    // The wire call is already correct; it is local state that loses both.
    expect(document.querySelectorAll('.cal-ev')).toHaveLength(1)
    // …and the ONE that survived is the second copy's own node, not the first
    // copy's node repainted with the second's content. That distinction is
    // invisible to a duplicate-key warning and is the whole of the defect: a
    // positional key (`key={i}`) hands the removal to React as "the list got
    // shorter", so node 0 stays and node 1 is destroyed — the surviving row
    // inherits the deleted row's DOM node, its scroll position, and anything
    // bound to it.
    expect(document.querySelectorAll('.cal-ev')[0],
      'the surviving copy inherited the deleted copy\u2019s node: the key is positional')
      .toBe(before[1])
  })

  // Control (passes today, must keep passing): scoping the local mutation must
  // not stop it happening. `calHref` answers '' until the calendar list has
  // loaded, so a predicate that requires a matching href with no fallback turns
  // every optimistic delete into a no-op — and `applyLocal` reports success, so
  // nothing reloads to cover for it.
  it('still removes the only copy of an event that lives in one calendar', async () => {
    const due = todayYmd()
    m.events.mockResolvedValue([ev({
      uid: 'solo', id: 'solo', calendar: '/c1/', summary: 'Standup',
      start: `${due}T09:00:00`, end: `${due}T09:30:00`,
    })])
    m.deleteEvent.mockResolvedValue(null as never)

    const user = userEvent.setup()
    render(<CalendarHarness />)
    await waitFor(() => expect(document.querySelectorAll('.cal-ev')).toHaveLength(1))

    await user.click(document.querySelectorAll('.cal-ev')[0] as HTMLElement)
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByText('Delete'))

    await waitFor(() => expect(m.deleteEvent).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(document.querySelectorAll('.cal-ev')).toHaveLength(0))
  })
})

/** The tasks pane over a real provider — the Sidebar comes with it. */
/** The pane with `collapsed_tasks` actually round-tripping, the way App holds
 *  it. `tasksSetup`'s `vi.fn()` swallows the change, so a fold never comes back
 *  down as a prop and nothing ever collapses — a harness that would report the
 *  fold working whatever the code did. */
function FoldHarness({ initial = [] as string[] }) {
  const [collapsedTasks, setCollapsedTasks] = useState<string[]>(initial)
  return (
    <DataProvider rev={0} onExpire={vi.fn()}>
      <TasksView onExpire={vi.fn()} view="list" onView={vi.fn()}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenLists={[]} onHiddenListsChange={vi.fn()}
        groups={[]} onGroupsChange={vi.fn()}
        collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
        collapsedTasks={collapsedTasks} onCollapsedTasksChange={setCollapsedTasks}
        showCompleted={false} />
    </DataProvider>
  )
}

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
  it('deletes only the copy whose row was clicked', async () => {
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

    const before = screen.getAllByText('Ship it')
      .map((n) => n.closest('.task') as HTMLElement)
    await user.click(within(before[0]).getByTitle('Delete'))

    await waitFor(() => expect(m.deleteTask).toHaveBeenCalledTimes(1))
    expect(m.deleteTask.mock.calls[0][0]).toBe('l1')          // only the Work copy
    // …and the other list's task is still on screen.
    expect(screen.queryAllByText('Ship it')).toHaveLength(1)
    // The surviving row must be the HOME copy's own node. `key={i}` satisfies
    // every warning-counting assertion in this file — indices are unique among
    // siblings — while tying each node to its POSITION, so removing the first
    // row leaves node 0 in place wearing the second row's text. See the
    // popover's reorder test for the other face of the same defect.
    expect(screen.getByText('Ship it').closest('.task'),
      'the Home copy inherited the deleted Work copy\u2019s row node')
      .toBe(before[1])
  })

  // WIDENING: delete is one of four provider mutations that match on the bare
  // uid. Completing is the one a user does every day, and it is worse to get
  // wrong because nothing about it looks destructive — the other list's task
  // silently reads as done, and the next refetch un-does it.
  it('completes only the copy whose box was ticked', async () => {
    m.lists.mockResolvedValue([work, home])
    m.tasks.mockImplementation(async (listId: string) =>
      [task({ uid: 'shared', list: listId, summary: 'Ship it' })])
    m.complete.mockImplementation(async (listId: string) =>
      task({ uid: 'shared', list: listId, summary: 'Ship it', completed: true,
        status: 'COMPLETED' }))
    const user = tasksSetup()

    await waitFor(() => expect(screen.getAllByText('Ship it')).toHaveLength(2))
    const rows = () => Array.from(document.querySelectorAll('.task')) as HTMLElement[]
    await user.click(within(rows()[0]).getByTitle('Toggle complete'))

    await waitFor(() => expect(m.complete).toHaveBeenCalledTimes(1))
    expect(m.complete.mock.calls[0][0]).toBe('l1')
    // Exactly one row reads as done. `showCompleted` is false, so the ticked
    // one leaves the pane and the other stays — either way, not both.
    await waitFor(() => expect(screen.queryAllByText('Ship it')).toHaveLength(1))
    expect(rows()[0].className).not.toMatch(/\bdone\b/)
  })

  // AUDIT: TasksView.tsx:203 — the sibling of the keying finding above, left
  // open there on purpose: "a refactor of that size inside a keying fix is how
  // the Stage 3 regressions got in". The React keys and the provider's
  // optimistic mutations are scoped by (list, uid); the pane's own maps are not.
  // `byUid`, `parentByUid`/`kidsByParent`, `kidRows`, `collapsedSet` and
  // `TaskGroup`'s entire prop surface are typed on a bare uid string, so with
  // one uid in two lists both rows show ONE row's subtasks, ONE row's progress
  // ring and ONE row's fold state.
  it('shows each copy of a shared uid its own subtasks and its own ring', async () => {
    // Same uid in both lists; only the WORK copy has a subtask under it.
    m.lists.mockResolvedValue([work, home])
    m.tasks.mockImplementation(async (listId: string) => (listId === 'l1'
      ? [task({ uid: 'shared', list: 'l1', summary: 'Ship it' }),
         task({ uid: 'kid', list: 'l1', summary: 'Write the notes', parent: 'shared' })]
      : [task({ uid: 'shared', list: 'l2', summary: 'Ship it' })]))
    tasksSetup()

    await waitFor(() => expect(screen.getAllByText('Ship it')).toHaveLength(2))
    // Exactly one 'Write the notes' on screen — not one under each copy, and
    // not zero. Zero is what happens today, and it is worse than the finding
    // states: `byUid` is last-wins over ALL tasks, so the l1 child's `parent`
    // resolves to the l2 copy, fails the same-list guard, and the subtask is
    // dropped from the pane entirely — invisible, and so uncompletable and
    // undeletable, while the sidebar count still includes it.
    expect(screen.getAllByText('Write the notes'),
      'the subtask rendered under both copies of the uid').toHaveLength(1)

    // …and exactly one copy shows a subtask count, since only one has children.
    expect(document.querySelectorAll('.child-progress'),
      'both copies of the uid drew a subtask count, but only one has a subtask')
      .toHaveLength(1)
    expect(document.querySelector('.child-progress')?.textContent).toBe('0/1')
  })

  it('folds each copy of a shared uid independently', async () => {
    // Fold state is persisted per uid in settings, so this is the one that
    // needs a tolerate-both read rather than a straight re-key: a migration
    // that dropped the old shape would silently unfold everyone's trees.
    m.lists.mockResolvedValue([work, home])
    m.tasks.mockImplementation(async (listId: string) => [
      task({ uid: 'shared', list: listId, summary: 'Ship it' }),
      task({ uid: `kid-${listId}`, list: listId, summary: `Sub ${listId}`,
        parent: 'shared' }),
    ])
    render(<FoldHarness />)
    const user = userEvent.setup()

    await waitFor(() => expect(screen.getAllByText('Ship it')).toHaveLength(2))
    expect(screen.getByText('Sub l1')).toBeInTheDocument()
    expect(screen.getByText('Sub l2')).toBeInTheDocument()

    // Fold the FIRST copy only.
    const carets = screen.getAllByTitle(/^Hide subtasks of Ship it$/)
    expect(carets.length, 'both rows should offer a fold control').toBe(2)
    await user.click(carets[0])

    await waitFor(() => expect(screen.queryByText('Sub l1')).toBeNull())
    expect(screen.getByText('Sub l2'),
      "folding one copy of the uid folded the other list's row too")
      .toBeInTheDocument()
  })

  it('reschedules the copy that was dragged, not the other list\u2019s', async () => {
    // Filed by the closing review as a scope claim this commit overstated. The
    // nesting and fold maps were re-keyed; `dropOnDay` still did
    // `tasks.find(x => x.uid === dragUid)` and `orderIndex` still did
    // `findIndex(t => t.uid === uid)`, both FIRST-WINS across all lists. So
    // dragging the Home copy onto a day column wrote a new due date to the
    // WORK one — a real CalDAV write to a task the user never touched, while
    // the one they dragged did not move.
    m.lists.mockResolvedValue([work, home])
    m.tasks.mockImplementation(async (listId: string) =>
      [task({ uid: 'shared', list: listId, summary: 'Ship it', due: todayYmd(),
        href: `/${listId}/shared.ics` })])
    m.patchTask.mockImplementation(async (listId: string, uid: string, body: unknown) =>
      task({ uid, list: listId, summary: 'Ship it', ...(body as object) }))

    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TasksView onExpire={vi.fn()} view="week" onView={vi.fn()}
          sideCollapsed={false} onToggleSide={vi.fn()}
          hiddenLists={[]} onHiddenListsChange={vi.fn()}
          groups={[]} onGroupsChange={vi.fn()}
          collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
          collapsedTasks={[]} onCollapsedTasksChange={vi.fn()}
          showCompleted={false} />
      </DataProvider>,
    )
    await waitFor(() => expect(screen.getAllByText('Ship it')).toHaveLength(2))

    // The SECOND card is the Home copy — the lists are fetched in order.
    const cards = Array.from(document.querySelectorAll('.day-card')) as HTMLElement[]
    expect(cards.length, 'both copies should be draggable cards').toBe(2)
    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    fireEvent.dragStart(cards[1], { dataTransfer })
    // A column that is NOT today, asked of the DOM rather than assumed.
    //
    // This was `[1]`, and it made the test fail every Monday. The week view
    // starts its columns on Sunday (`start.getDate() - start.getDay()`), so
    // index 1 is Monday — and the fixture's due date is today. Dropping a card
    // onto the day it is already due is a no-op by design (`dropOnDay` returns
    // early when `dayKey(t.due) === key`, because rescheduling a task to where
    // it already is should not write to CalDAV), so on Mondays nothing was
    // patched and the assertion read as the identity bug this test exists to
    // catch. It was the calendar, not the code.
    //
    // The column carries `today` as a class, so the DOM already knows which one
    // to avoid — no need to re-derive the week's start or its convention here.
    const col = [...document.querySelectorAll('.day-col')]
      .find((c) => !c.classList.contains('today')) as HTMLElement
    expect(col, 'a week always has a column that is not today').toBeTruthy()
    fireEvent.drop(col, { dataTransfer })

    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    const [listId, uid] = m.patchTask.mock.calls[0]
    expect({ listId, uid },
      'the drag rescheduled the other list\u2019s copy of the same uid')
      .toEqual({ listId: 'l2', uid: 'shared' })
  })

  it('honours a fold saved as a bare uid, and retires it on the next toggle', async () => {
    // The migration control, and the one that matters most here. `collapsed_tasks`
    // is PERSISTED — a list of bare uids in the account's settings, written by
    // every version of this pane so far — and `onCollapsedTasksChange` goes
    // straight to `saveSettingsSoon`. A straight re-key to `taskKey` matches
    // none of them, so every folded tree in every account springs open on first
    // load and the prune then writes that loss back to the server. Silent, and
    // not recoverable from the client.
    m.lists.mockResolvedValue([work])
    m.tasks.mockResolvedValue([
      task({ uid: 'shared', list: 'l1', summary: 'Ship it' }),
      task({ uid: 'kid', list: 'l1', summary: 'Write the notes', parent: 'shared' }),
    ])
    render(<FoldHarness initial={['shared']} />)     // the OLD spelling
    const user = userEvent.setup()

    await screen.findByText('Ship it')
    expect(screen.queryByText('Write the notes'),
      'a fold saved under the old bare-uid spelling was ignored').toBeNull()

    // Unfolding it drops the legacy entry rather than leaving it to re-fold the
    // row on the next load.
    await user.click(screen.getByTitle('Show subtasks of Ship it'))
    expect(await screen.findByText('Write the notes')).toBeInTheDocument()

    // …and folding again writes the new spelling, which also works.
    await user.click(screen.getByTitle('Hide subtasks of Ship it'))
    await waitFor(() => expect(screen.queryByText('Write the notes')).toBeNull())
  })

  // Control (passes today, must keep passing). Scoping a mutation must not stop
  // it happening: a predicate that demands a matching list with no fallback
  // would make every optimistic update a no-op for the ordinary single-copy
  // task, which is every task most accounts have.
  it('still completes and deletes an ordinary task that lives in one list', async () => {
    m.lists.mockResolvedValue([work])
    m.tasks.mockResolvedValue([task({ uid: 'solo', list: 'l1', summary: 'Buy milk' })])
    m.complete.mockResolvedValue(
      task({ uid: 'solo', list: 'l1', summary: 'Buy milk', completed: true, status: 'COMPLETED' }))
    m.deleteTask.mockResolvedValue(null)
    const user = tasksSetup()

    await screen.findByText('Buy milk')
    const row = () => document.querySelector('.task') as HTMLElement
    await user.click(within(row()).getByTitle('Toggle complete'))
    await waitFor(() => expect(m.complete).toHaveBeenCalledTimes(1))
    // showCompleted is false, so completing it takes it out of the pane.
    await waitFor(() => expect(screen.queryByText('Buy milk')).toBeNull())
  })
})

// ── the completed pane ──────────────────────────────────────────────────────

describe('aug19 stage 4b — the Completed pane and a RELATED-TO ring', () => {
  // AUDIT open: TasksView.tsx:334
  it('shows a completed ring another client authored', async () => {
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

  // WIDENING: a THREE-node ring. The two-node case above is satisfied by a
  // one-hop widening ("a done task is a top when its parent is not done, or
  // when its parent is itself parented"), which is the obvious repair and still
  // loses a→b→c→a entirely. Rings arrive from other clients and nothing on
  // either side of the wire prevents them, so the length is not bounded.
  it('shows a completed ring of three the same way', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Alpha', parent: 'b', completed: true, status: 'COMPLETED' }),
      task({ uid: 'b', summary: 'Bravo', parent: 'c', completed: true, status: 'COMPLETED' }),
      task({ uid: 'c', summary: 'Cass', parent: 'a', completed: true, status: 'COMPLETED' }),
    ])
    const user = tasksSetup()
    await user.click(await screen.findByText(/View completed/))

    for (const name of ['Alpha', 'Bravo', 'Cass']) {
      expect(screen.getAllByText(name).length, name).toBeGreaterThan(0)
    }
    // …and each exactly once: a repair that puts the whole ring at the top
    // level AND nests it would render duplicates.
    for (const name of ['Alpha', 'Bravo', 'Cass']) {
      expect(screen.getAllByText(name), name).toHaveLength(1)
    }
  })

  // Control (passes today, must keep passing). This pane needs its own
  // top-level set precisely because `tops` consults the global `showCompleted`;
  // the comment at TasksView.tsx:337 records why. A repair that gives up and
  // puts every done task at the top level satisfies both pins above and undoes
  // that — the child would sit beside the parent it belongs under.
  it('still nests an ordinary completed child under its completed parent', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: 'p', summary: 'Move house', completed: true, status: 'COMPLETED' }),
      task({ uid: 'k', summary: 'Book the van', parent: 'p', completed: true, status: 'COMPLETED' }),
    ])
    const user = tasksSetup()
    await user.click(await screen.findByText(/View completed/))

    await screen.findByText('Move house')
    expect(screen.getAllByText('Book the van')).toHaveLength(1)
    // The child renders as a SUBTASK, not as a top-level row beside the parent
    // it belongs under. `.sub` is what TaskRow puts on any row with depth > 0.
    const child = screen.getByText('Book the van').closest('.task') as HTMLElement
    const parentRow = screen.getByText('Move house').closest('.task') as HTMLElement
    expect(child.className, 'the completed child is indented under its parent').toMatch(/\bsub\b/)
    expect(parentRow.className).not.toMatch(/\bsub\b/)
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
  it('closes on Escape, like every other dialog in the app', async () => {
    // The app's most-used dialog registers no keydown listener at all, while
    // AddMultipleModal, AppearancePanel, DayPopover, SettingsMenu and the
    // booking-link editor all honour Escape. With `aria-modal="true"` and no
    // focus trap either, a keyboard or screen-reader user has no keyboard route
    // out of it.
    //
    // WIDENED. Dispatching at the dialog was satisfied by a handler on ANY
    // ancestor, including one bound to the modal element itself — and a
    // dialog-local handler only fires while focus is inside the dialog, which is
    // exactly the complaint. So the key is also dispatched at `document` and at
    // `window`, where only a global listener answers.
    const onClose = vi.fn()
    const { unmount } = render(<TaskModal {...props} onClose={onClose} />)

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(onClose, 'Escape at the dialog').toHaveBeenCalled()
    unmount()

    // …and from wherever focus actually is. A modal with no focus trap can be
    // left with focus on the page behind it, which is the state a keyboard user
    // most needs the escape hatch from.
    for (const target of [document, window] as const) {
      const close = vi.fn()
      const view = render(<TaskModal {...props} onClose={close} />)
      fireEvent.keyDown(target as unknown as Element, { key: 'Escape' })
      expect(close, `Escape at ${target === document ? 'document' : 'window'}`)
        .toHaveBeenCalled()
      view.unmount()
    }
  })
})

describe('aug19 stage 4b — the login form', () => {
  // AUDIT open: Login.tsx:34
  it('gives both fields an accessible name', async () => {
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
  it('stops saying "Loading…" once the fetch has failed', async () => {
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

  // WIDENING: `ArchivedEvents` — the sibling ten lines below in the same file,
  // with the identical shape for `api.events`. Reached by drilling into an
  // archived calendar's agenda, which is the only place its "Loading…" shows.
  it('stops saying "Loading…" once the EVENT fetch has failed', async () => {
    m.calendars.mockResolvedValue([{ ...cal, id: 'c1', href: '/c1/', name: 'Old work' }])
    m.events.mockRejectedValue(new Error('network down'))
    render(<ArchivedCalendarsSection archived={['c1']} onChange={vi.fn()}
      onExpire={vi.fn()}
      viewing={{ ...cal, id: 'c1', href: '/c1/', name: 'Old work' }} onViewing={vi.fn()} />)

    await act(async () => { await Promise.resolve() })
    expect(screen.queryByText('Loading…'),
      'the archived-events agenda is still saying Loading…').toBeNull()
  })

  // Control (passes today, must keep passing). Settling `loaded` in a `finally`
  // must not also settle it BEFORE the rows arrive: a repair that sets it
  // eagerly would satisfy both pins and render "No archived calendars." over a
  // list that is about to appear.
  //
  // The assertion that does that work is the FIRST one, and it is deliberately
  // SYNCHRONOUS. An adversarial review got `useState(true)` — never render
  // "Loading…" at all — past the earlier version of this control, because
  // `findByText('Old work')` WAITS: it flushes the fetch, and only then is the
  // negative assertion evaluated, by which time the transient lie has already
  // been repainted into the true list. The lie is only observable in the tick
  // before the promise settles, so that is where it has to be caught.
  //
  // What is asserted there is the property, not the wording: the section must
  // not CLAIM AN EMPTY ARCHIVE while it is still fetching. "Loading…", a
  // spinner or a skeleton all satisfy it.
  it('still lists the archived calendars when the fetch succeeds', async () => {
    let release: (rows: List[]) => void = () => {}
    m.calendars.mockReturnValue(new Promise<List[]>((res) => { release = res }))
    render(<ArchivedCalendarsSection archived={['c1']} onChange={vi.fn()}
      onExpire={vi.fn()} viewing={null} onViewing={vi.fn()} />)

    // In flight — nothing has been fetched yet, so nothing may be claimed.
    expect(screen.queryByText('No archived calendars.'),
      'the archive was reported empty before the fetch had answered').toBeNull()
    expect(screen.queryByText(/Couldn.t load/),
      'the fetch was reported failed before it had answered').toBeNull()

    await act(async () => {
      release([{ ...cal, id: 'c1', href: '/c1/', name: 'Old work' }])
    })
    expect(await screen.findByText('Old work')).toBeInTheDocument()
    expect(screen.queryByText('No archived calendars.')).toBeNull()
  })
})

describe('aug19 stage 4b — the theme rename bar', () => {
  function AppearanceHarness({ initial }: { initial: Appearance }) {
    const [appearance, setAppearance] = useState(initial)
    return <AppearancePanel appearance={appearance} onChange={setAppearance}
      mode="light" onMode={vi.fn()} onClose={vi.fn()} />
  }

  // AUDIT open: AppearancePanel.tsx:45
  it('never renames the theme the user switched to with the old name', async () => {
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

    // WIDENED. This used to click Save only `if (save)`, so a fix that closes
    // the row passed with the rename never attempted — the assertion that
    // matters was unreachable in exactly the branch the fix creates. Stated as
    // the outcome instead: the row is either gone, or it is about the theme the
    // user is now looking at. Both repairs the docstring blesses satisfy it,
    // and doing nothing does not.
    const field = screen.queryByLabelText('Theme name')
    if (field) expect(field).toHaveValue('Beta')

    // …and whatever it does, dismissing it must not put Alpha's name anywhere
    // it does not belong.
    const save = screen.queryByRole('button', { name: 'Save' })
    if (save) await user.click(save)
    const names = screen.getAllByRole('option').map((o) => o.textContent)
    expect(names.filter((n) => n === 'Alpha')).toHaveLength(1)
    expect(names).toContain('Beta')
  })

  // WIDENING: the picker is one of three paths that retarget `active`, and the
  // finding names all three. Duplicate is the one a user reaches while already
  // in the middle of renaming, since both buttons sit in the same row.
  it('never renames the copy Duplicate just made with the original name', async () => {
    const user = userEvent.setup()
    render(<AppearanceHarness initial={{
      active: 'a', themes: [{ id: 'a', name: 'Alpha', base: 'light', light: {}, dark: {} }],
    }} />)

    await user.click(screen.getByRole('button', { name: 'Rename' }))
    expect(screen.getByLabelText('Theme name')).toHaveValue('Alpha')

    await user.click(screen.getByRole('button', { name: 'Duplicate' }))

    const field = screen.queryByLabelText('Theme name')
    if (field) expect(field).not.toHaveValue('Alpha')
    const save = screen.queryByRole('button', { name: 'Save' })
    if (save) await user.click(save)

    // Two themes, two distinct names — the id is never shown, so the name is
    // the only thing that tells them apart. Scoped to the theme picker: the
    // font selects contribute options too, and some of their labels repeat
    // across the serif/sans/mono tiers by design.
    const picker = screen.getByRole('combobox', { name: 'Theme' })
    const names = within(picker).getAllByRole('option').map((o) => o.textContent)
    expect(new Set(names).size).toBe(names.length)
  })

  // WIDENING: Import is the THIRD retarget path, and the finding names all
  // three ("the picker, Duplicate and Import"). The shipped one-line effect —
  // `useEffect(() => setRenaming(false), [appearance.active])` — does cover it,
  // but nothing drove it: an adversarial review deleted the effect and reset
  // `renaming` inside `selectTheme` and `duplicate` by hand, and the whole
  // suite stayed green while Import went on retargeting a live rename.
  //
  // Import is if anything the worst of the three, because the theme it
  // retargets onto is one the user has never seen: they press Save expecting to
  // rename "Alpha" and rename the file they just imported instead, leaving two
  // themes called Alpha and no way to tell them apart.
  it('never renames the theme Import just added with the old name', async () => {
    const user = userEvent.setup()
    render(<AppearanceHarness initial={{
      active: 'a', themes: [{ id: 'a', name: 'Alpha', base: 'light', light: {}, dark: {} }],
    }} />)

    await user.click(screen.getByRole('button', { name: 'Rename' }))
    expect(screen.getByLabelText('Theme name')).toHaveValue('Alpha')

    // The real control is a hidden <input type="file"> the Import button
    // clicks; jsdom cannot drive that click through to a picker, so the file is
    // handed to the input directly — the same change event the picker fires.
    const file = new File(
      [JSON.stringify({ smylte_theme: 1, name: 'Nordic', base: 'light',
        light: { '--accent': '#5e81ac' }, dark: { '--accent': '#88c0d0' } })],
      'nordic.smylte-theme.json', { type: 'application/json' })
    const picker = document.querySelector('input[type="file"]') as HTMLInputElement
    expect(picker, 'the Import control is gone').not.toBeNull()
    await user.upload(picker, file)

    await screen.findByRole('option', { name: 'Nordic' })

    const field = screen.queryByLabelText('Theme name')
    if (field) expect(field).not.toHaveValue('Alpha')
    const save = screen.queryByRole('button', { name: 'Save' })
    if (save) await user.click(save)

    const select = screen.getByRole('combobox', { name: 'Theme' })
    const names = within(select).getAllByRole('option').map((o) => o.textContent)
    expect(names, 'the imported theme was renamed with the old theme\u2019s name')
      .toContain('Nordic')
    expect(names).toContain('Alpha')
    expect(new Set(names).size).toBe(names.length)
  })
})

// ── bounds: a layout the server will refuse ─────────────────────────────────

describe('aug19 stage 4b — the dashboard grid', () => {
  // AUDIT open: dashboard.ts:93
  it('never emits a module below the row the server accepts', () => {
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

  // WIDENING: `sanitizeLayout` is not what the app PUTs. HomeView holds the
  // result of `moveModule`/`resizeModule`/`addModule`/`removeModule` as its
  // live layout and sends that, so a clamp applied only in `sanitizeLayout`
  // leaves every intermediate over the bound — and it is an intermediate that
  // 422s the settings write.
  it('never emits a module below that row from any editing operation', () => {
    let mods: DashboardModule[] = []
    MODULE_KINDS.forEach((kind, i) => { mods = addModule(mods, kind, `m${i}`) })
    for (const mod of [...mods]) mods = resizeModule(mods, mod.id, 12, 40)
    expect(mods.map((m) => m.y).filter((y) => y > 200), 'after resizeModule').toEqual([])

    const moved = moveModule(mods, mods[mods.length - 1].id, 0, 200)
    expect(moved.map((m) => m.y).filter((y) => y > 200), 'after moveModule').toEqual([])

    const added = addModule(moved, MODULE_KINDS[0], 'extra')
    expect(added.map((m) => m.y).filter((y) => y > 200), 'after addModule').toEqual([])

    const removed = removeModule(added, added[0].id)
    expect(removed.map((m) => m.y).filter((y) => y > 200), 'after removeModule').toEqual([])
  })

  // Control (passes today, must keep passing): an ordinary layout is untouched
  // by the clamp, and — the reason this is here — the pinned module still holds
  // the row the drag put it on. The naive repair clamps inside `packDown`'s
  // pinned `while`, where a clamped y can still overlap and the loop never
  // terminates; the other naive repair drops the pinned branch entirely and the
  // dragged card snaps back.
  it('leaves a normal layout alone and keeps a pinned module on its row', () => {
    let mods: DashboardModule[] = []
    MODULE_KINDS.slice(0, 3).forEach((kind, i) => { mods = addModule(mods, kind, `n${i}`) })
    expect(sanitizeLayout(mods)).toEqual(mods)

    const target = mods[0]
    const moved = moveModule(mods, target.id, target.x, target.y + 6)
    expect(moved.find((m) => m.id === target.id)?.y).toBe(target.y + 6)
  })
})

// ── the modal contract, made checkable ──────────────────────────────────────

describe('aug19 leftovers — every dialog answers Escape at the window', () => {
  // AUDIT: hooks.ts:16 — five dialogs inlined the same effect with THREE
  // different bindings (two on `window`, one on `document`, one guarded by
  // `busy`), and nothing made the contract checkable. That is how TaskModal —
  // the app's most-used dialog — shipped with no Escape handler at all for as
  // long as it did: there was no list for it to be missing from.
  //
  // The binding difference is not cosmetic. A `document` listener does not see
  // a keydown dispatched at `window`, so this table dispatches at **window**
  // deliberately: it is the widest spelling, it subsumes `document` (a keydown
  // there bubbles up), and a dialog-local listener fails it — which is correct,
  // because a dialog-local listener only fires while focus is inside the
  // dialog, and with no focus trap that is exactly the state a keyboard user
  // needs the escape hatch from.
  //
  // Enumerated rather than written out per dialog, so a NEW dialog joins by
  // being added to one array. That is the coverage that would have caught
  // finding 58 before it was filed.
  const dialogs: Array<[string, (onClose: () => void) => ReactElement]> = [
    ['TaskModal', (onClose) => (
      <TaskModal task={null} lists={[work]} defaultList="l1" onClose={onClose}
        onCreate={vi.fn()} onSave={vi.fn()} onDelete={vi.fn()} onMultiple={vi.fn()} />
    )],
    ['DayPopover', (onClose) => (
      <DayPopover day={todayYmd()} x={40} y={40} events={[]} tasks={[]}
        styleOf={() => undefined} onClose={onClose} />
    )],
    ['AddMultipleModal', (onClose) => (
      <AddMultipleModal lists={[work]} defaultList="l1"
        onSubmit={vi.fn()} onClose={onClose} />
    )],
    ['AppearancePanel', (onClose) => (
      <AppearancePanel appearance={{}} onChange={vi.fn()} mode="light"
        onMode={vi.fn()} onClose={onClose} />
    )],
  ]

  it.each(dialogs)('%s closes on an Escape dispatched at the window', (_name, make) => {
    const onClose = vi.fn()
    const view = render(make(onClose))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose, 'the dialog did not answer an Escape at the window')
      .toHaveBeenCalled()
    view.unmount()
  })

  it.each(dialogs)('%s unsubscribes when it unmounts', (_name, make) => {
    // A dialog whose listener outlives it closes the NEXT one that opens, or
    // sets state on a dead tree. Same reason the breakpoint listener is counted
    // above.
    const onClose = vi.fn()
    render(make(onClose)).unmount()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose, 'the Escape listener outlived the dialog that registered it')
      .not.toHaveBeenCalled()
  })

  // Control: the guard that kept AddMultipleModal out of the first pass. Escape
  // must NOT close it mid-batch — a dismissal there strands a half-created run
  // with nowhere to report its failures — so consolidating onto the hook has to
  // preserve the condition, not drop it.
  it('AddMultipleModal still refuses Escape while a batch is in flight', async () => {
    const onClose = vi.fn()
    // Resolves the failed-row array the real `onSubmit` contract returns — an
    // undefined there is an unhandled rejection inside the component, not a
    // finding.
    let release: () => void = () => {}
    const onSubmit = vi.fn(() =>
      new Promise<string[]>((res) => { release = () => res([]) }))
    render(<AddMultipleModal lists={[work]} defaultList="l1"
      onSubmit={onSubmit as never} onClose={onClose} />)

    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Title, row 1'), 'buy milk')
    await user.click(screen.getByRole('button', { name: 'Add 1 task' }))
    await waitFor(() => expect(onSubmit).toHaveBeenCalled())

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose, 'Escape closed the composer mid-batch').not.toHaveBeenCalled()

    await act(async () => { release() })
  })

  // SettingsMenu was left out of the table on the grounds that its own suite is
  // the control. It is not, and a review proved it: reverting it to a
  // hand-rolled **`document`** listener left all 725 tests green, because
  // `SettingsMenu.test.tsx` uses `userEvent.keyboard('{Escape}')`, which
  // dispatches at `document.activeElement` and bubbles to `document` AND
  // `window` — it cannot tell the two bindings apart, which is precisely the
  // distinction this table exists for. So it is in the table now, driven with
  // its real prop surface.
  it('SettingsMenu answers an Escape at the window', async () => {
    // What this table is for: the BINDING. On a desktop there is no drill-down
    // to unwind, so `back()` falls through to `onClose` — its own suite covers
    // the mobile agenda -> section -> closed sequence, and that part is
    // genuinely fine. What its suite cannot check is that the listener is on
    // `window` at all, because `userEvent.keyboard` bubbles through both.
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
      onLogout={vi.fn()} onExpire={vi.fn()} onClose={onClose} />)

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose, 'SettingsMenu did not answer an Escape dispatched at the window')
      .toHaveBeenCalled()
  })

  // And the enumeration itself. A table is only as good as its membership, and
  // nothing derived that membership from the code — which is how finding 58
  // happened: TaskModal was missing from a set nobody maintained. This reads
  // the component tree and fails when a dialog adopts the hook without joining
  // the table, so the next one cannot be forgotten silently.
  it('every component using useEscape is covered by this file', async () => {
    // `import.meta.glob` is Vite's, and this project does not pull in
    // vite/client's ambient types, so it is reached through a narrow cast
    // rather than by widening the whole tsconfig for one test.
    const files = (import.meta as unknown as {
      glob: (p: string, o: object) => Record<string, () => Promise<string>>
    }).glob('./components/*.tsx', { query: '?raw', import: 'default' })
    const users: string[] = []
    for (const [path, load] of Object.entries(files)) {
      // The glob is a DIRECTORY sweep, and the tests for these components live
      // in that directory too. A test file is not a dialog: one that names the
      // hook — in prose, in a mock, in an assertion about it — was enumerated
      // as a component owing an Escape case, which is a failure that says
      // nothing about the app and can only be answered by editing the table.
      if (/\.test\.tsx$/.test(path)) continue
      const src = await load()
      if (/\buseEscape\s*\(/.test(src)) users.push(path.split('/').pop()!.replace('.tsx', ''))
    }
    expect(users.length, 'nothing imports useEscape any more?').toBeGreaterThan(0)

    const covered = new Set([
      ...dialogs.map(([name]) => name),
      'SettingsMenu',              // the case just above
      'SchedulingView',            // backlog.stage4.test.tsx:228, at window
      // The habits sheet, which is a dialog like the rest. Driven by
      // TodayView.test.tsx's 'closes on an Escape dispatched at the window' and
      // its companion asserting the listener leaves with the sheet.
      'TodayView',
      // The planning ritual, driven by TodayView.test.tsx's 'closes on an
      // Escape dispatched at the window' in its own describe block. It is a
      // dialog like the rest and answers the key at the window for the same
      // reason: there is no focus trap in any of them.
      'PlanRitual',
      // The shutdown ritual, driven by TodayView.test.tsx's 'closes on an
      // Escape dispatched at the window' in the shutdown describe block. Same
      // shape and same reason as the planning one above.
      'ShutdownRitual',
      // The last two dialogs to adopt the hook, both found by the 2026-08-25
      // sweep. This enumeration derives its membership from components that
      // ALREADY import `useEscape`, which is a guard pointed one way only: it
      // cannot see a dialog that never adopted it at all, and these two never
      // had. `modal-contract.test.tsx` is the other direction — it sweeps every
      // component rendering an `.overlay` and asserts all three halves of the
      // contract — and it drives Sidebar's edit modal behaviourally.
      'Sidebar',
      // CalendarView's EventModal and its move-scope prompt. Escape is driven by
      // modal-contract.test.tsx's source sweep; the scrim guard likewise.
      'CalendarView',
      // The focus surface: not a dialog but a full-bleed page with one way
      // out, and Escape is that way. FocusView.test.tsx's 'leaves on an Escape
      // dispatched at the window'.
      'FocusView',
    ])
    const missing = users.filter((u) => !covered.has(u))
    expect(missing,
      `${missing.join(', ')} use(s) useEscape and is in no Escape test. Add it `
      + 'to `dialogs` above, or to `covered` with the file that drives it.')
      .toEqual([])
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
  it('discovers a session that lapsed while the tab was idle', async () => {
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
    // NARROWED, deliberately, and this replaces what stood here. The original
    // blessed either repair — probe the session, or "give up and surface a live
    // updates disconnected state" — and accepted `probed || gaveUp`. The second
    // outcome is not reachable: `subscribe` takes one callback and has no
    // channel to surface any UI state, so "gave up" means a tab that is silently
    // frozen, which is the very thing the finding is about. So the contract is
    // the outcome the user needs: the app finds out, and says so by routing to
    // the auth guard the rest of the SPA already uses.
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
      const onExpire = vi.fn()
      const stop = (subscribe as unknown as
        (f: (t: string) => void, e?: () => void) => () => void)(vi.fn(), onExpire)
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
      void gaveUp
      expect(fetchMock.mock.calls.length,
        'the reconnect loop never asked the server whether the session was alive')
        .toBeGreaterThan(0)
      expect(onExpire,
        'the session was found to be gone and nothing told the app').toHaveBeenCalled()
      stop()
    } finally {
      vi.useRealTimers()
      vi.unstubAllGlobals()
    }
  })

  // Control — green today (the second argument is simply ignored) and the more
  // important half of this finding once it is not. A server that is down is not
  // a session that is gone: if the probe says the session is FINE, the loop must
  // keep reconnecting and must not sign anybody out. Otherwise one 502 from the
  // tunnel logs the user out of a live session, which is a worse bug than the
  // one being fixed — and no pin would notice, because the pin above only asks
  // that `onExpire` fires.
  it('keeps reconnecting, and signs nobody out, while the session is alive', async () => {
    const { subscribe } = await vi.importActual<typeof import('./api')>('./api')
    const fetchMock = vi.fn().mockResolvedValue({
      status: 200, ok: true, statusText: 'OK',
      json: () => Promise.resolve({ authenticated: true, user: 'admin' }),
    })
    const onExpire = vi.fn()
    FakeES.instances = []
    vi.stubGlobal('EventSource', FakeES)
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()
    try {
      const stop = (subscribe as unknown as
        (f: (t: string) => void, e?: () => void) => () => void)(vi.fn(), onExpire)
      FakeES.instances[0].accept()

      for (let i = 0; i < 20; i++) {
        const before = FakeES.instances.length
        FakeES.instances[before - 1].hardFail()
        await vi.advanceTimersByTimeAsync(60_000)
        expect(FakeES.instances.length,
          'the loop stopped reconnecting although the session was alive')
          .toBeGreaterThan(before)
      }
      expect(onExpire, 'a healthy session was signed out').not.toHaveBeenCalled()
      stop()
    } finally {
      vi.useRealTimers()
      vi.unstubAllGlobals()
    }
  })

  // …and the case the control above NAMES but does not drive. It says "one 502
  // from the tunnel logs the user out of a live session"; it then answers the
  // probe **200**, which is the server saying the session is fine — a different
  // scenario, and the easy one. When the server is down the probe does not
  // answer at all: `api.me()` rejects, with an HttpError for a 5xx the tunnel
  // synthesises or a TypeError for a socket that never opened. Neither is an
  // AuthError, and neither is evidence about the session.
  //
  // An adversarial review shipped `onExpire` on ANY probe rejection and the
  // suite stayed green, because nothing drove a probe that fails. That reads as
  // "your session expired, sign in again" to everyone holding the tab open
  // through a deploy or a dropped tunnel — one restart signs out the whole
  // account, and their unsaved composer text goes with it.
  it.each([
    ['a 502 from the tunnel', () => Promise.resolve({
      status: 502, ok: false, statusText: 'Bad Gateway',
      json: () => Promise.resolve({ detail: 'bad gateway' }),
    })],
    ['a socket that never opened', () => Promise.reject(new TypeError('Failed to fetch'))],
  ])('keeps the session while the server is unreachable: %s', async (_label, answer) => {
    const { subscribe } = await vi.importActual<typeof import('./api')>('./api')
    const fetchMock = vi.fn().mockImplementation(answer)
    const onExpire = vi.fn()
    FakeES.instances = []
    vi.stubGlobal('EventSource', FakeES)
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()
    try {
      const stop = (subscribe as unknown as
        (f: (t: string) => void, e?: () => void) => () => void)(vi.fn(), onExpire)
      FakeES.instances[0].accept()

      for (let i = 0; i < 20; i++) {
        const before = FakeES.instances.length
        FakeES.instances[before - 1].hardFail()
        await vi.advanceTimersByTimeAsync(60_000)
        expect(FakeES.instances.length,
          'the loop stopped reconnecting although nothing said the session was gone')
          .toBeGreaterThan(before)
      }
      expect(fetchMock.mock.calls.length,
        'the probe never ran, so this proves nothing about how it answers')
        .toBeGreaterThan(0)
      expect(onExpire,
        'an unreachable server signed the user out of a live session')
        .not.toHaveBeenCalled()
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

  it('flips at the same width the stylesheet uses', async () => {
    // `hooks.ts` asks for this in a comment — keep MOBILE_QUERY in sync with
    // app.css — and nothing enforced it. With a stub that answered `matches`
    // for any query, moving the hook to 480px while the stylesheet kept 720px
    // passed every test in this file: the app would swap to the mobile tree at
    // one width and restyle at another, so between them the phone layout
    // renders with desktop rules.
    // Read off disk. Vitest does not process CSS by default, so both a plain
    // import and Vite's `?raw` loader come back empty here — an empty string
    // would make this assertion vacuous, which is the failure mode this whole
    // test exists to close.
    const { readFileSync } = await import('node:fs')
    const css = readFileSync('src/styles/app.css', 'utf8')
    const widths = [...css.matchAll(/@media[^{]*max-width:\s*(\d+)px/g)]
      .map((m) => Number(m[1]))
    expect(widths.length, 'app.css has no max-width media query any more?')
      .toBeGreaterThan(0)
    const breakpoint = Math.max(...widths)

    // One pixel either side of the stylesheet's own breakpoint.
    const { result } = renderHook(() => useIsMobile())
    act(() => { setBreakpoint(breakpoint) })
    expect(result.current,
      `useIsMobile is false at ${breakpoint}px, where app.css switches to the `
      + 'mobile rules').toBe(true)
    act(() => { setBreakpoint(breakpoint + 1) })
    expect(result.current,
      `useIsMobile is still true at ${breakpoint + 1}px, past where app.css `
      + 'switches back').toBe(false)
  })

  // WIDENING, and the half of this finding the pin above cannot reach. Every
  // mobile assertion here — and in Sidebar, SettingsMenu and the pin above —
  // installs a stub whose `addEventListener` is a NO-OP and then mounts. That
  // fixes the breakpoint at mount time, so what is exercised is
  // `useState(() => matchMedia(...).matches)` and never the effect underneath
  // it. The effect is the entire reason the hook is not a plain read: a
  // rotation, a window resize or a devtools device-toolbar toggle crosses the
  // breakpoint WITHOUT remounting anything.
  //
  // `hooks.test.ts` does drive that change, but against `renderHook` — the hook
  // alone, with no component reading it. Nothing anywhere asserted that a real
  // view answers the change, which is where it would actually be noticed.
  //
  // This uses the SHARED stub from test/setup.ts, which now keeps a real
  // listener registry precisely so a suite can cross the breakpoint without
  // replacing the stub wholesale — the last piece of this finding's suggested
  // fix.
  it('follows the breakpoint across a rotation, without remounting', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date(2026, 2, 5))
    try {
      m.events.mockResolvedValue([ev({ summary: 'Retro' })])

      // Desktop first — the shared stub's default, and no local stub in sight.
      resetBreakpoint()
      const view = render(<CalendarHarness />)
      await waitFor(() => expect(document.querySelectorAll('.cal-ev').length)
        .toBeGreaterThan(0))
      expect(document.querySelector('.day-agenda'),
        'the mobile agenda rendered at the desktop breakpoint').toBeNull()

      const before = document.querySelector('.cal-scroll')
      expect(before, 'the calendar did not render').not.toBeNull()
      expect(breakpointListeners(),
        'nothing subscribed to the breakpoint, so no change could ever arrive')
        .toBeGreaterThan(0)

      // The phone turns sideways. Nothing unmounts.
      act(() => { setBreakpoint(true) })

      await waitFor(() => expect(document.querySelector('.day-agenda')).not.toBeNull())
      expect(document.querySelectorAll('.cal-ev'),
        'the desktop chips survived a crossing into the mobile layout')
        .toHaveLength(0)
      expect(document.querySelectorAll('.ev-dot').length).toBeGreaterThan(0)
      // Same DOM node throughout: this is a re-render, not a remount. If the
      // view had been torn down and rebuilt the assertions above would pass
      // while saying nothing about the effect.
      expect(document.querySelector('.cal-scroll'),
        'the calendar remounted rather than re-rendering').toBe(before)

      // …and back, because a fix that latches on the first change would pass
      // everything above.
      act(() => { setBreakpoint(false) })
      await waitFor(() => expect(document.querySelector('.day-agenda')).toBeNull())
      expect(document.querySelectorAll('.cal-ev').length).toBeGreaterThan(0)

      // Unmounting must unsubscribe, or every crossed breakpoint sets state on
      // a dead tree for the life of the page.
      const subscribed = breakpointListeners()
      view.unmount()
      expect(breakpointListeners(),
        'the breakpoint listener outlived the component that registered it')
        .toBeLessThan(subscribed)
    } finally {
      vi.useRealTimers()
      resetBreakpoint()
    }
  })
})
