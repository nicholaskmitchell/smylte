import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomeView } from './HomeView'
import { DataProvider } from '../data'
import { setCacheUser } from '../cache'
import { api } from '../api'
import { monthGrid } from '../calendar'
import { DEFAULT_LAYOUT, type DashboardModule } from '../dashboard'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})

const m = vi.mocked(api)

const task = (o: Partial<import('../api').Task> = {}): import('../api').Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [],
  parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  // Present on every DTO the server sends; see api.ts's Task.
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const list = { id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 1, task_count: 1, event_count: 0, total: 1, color: '#D9480F' }

/** Render with a controlled layout so assertions can watch it change. */
function setup(initial: DashboardModule[] | null = DEFAULT_LAYOUT,
  props: { hiddenCalendars?: string[]; archivedCalendars?: string[] } = {}) {
  const onLayoutChange = vi.fn()
  render(
    <DataProvider rev={0} onExpire={vi.fn()}>
      <HomeView rev={0} onExpire={vi.fn()} layout={initial}
        onLayoutChange={onLayoutChange} {...props} />
    </DataProvider>,
  )
  return { onLayoutChange }
}

const today = () => {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

beforeEach(() => {
  vi.clearAllMocks()
  setCacheUser('')
  localStorage.clear()
  m.lists.mockResolvedValue([list])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
})

describe('<HomeView>', () => {
  // NULL is "nothing is saved" as of the 2026-08-25 stage 4 fix; `[]` now means
  // a board the owner deliberately cleared. These two tests said `[]` and meant
  // the first, which is the conflation that fix was about — removing the last
  // module produced `[]` and put the stock five straight back. Only the value
  // standing for "unset" changed here; both assertions are as they were.
  it('falls back to the stock arrangement when nothing is saved', async () => {
    setup(null)
    expect(await screen.findByText('Today')).toBeInTheDocument()
    expect(screen.getByText('Upcoming')).toBeInTheDocument()
    expect(screen.getByText('Mini calendar')).toBeInTheDocument()
  })

  it('does not persist the stock arrangement until something is changed', async () => {
    const { onLayoutChange } = setup(null)
    await screen.findByText('Today')
    // An untouched dashboard stays "unset" server-side, so a later change to the
    // shipped default still reaches accounts that never arranged anything.
    expect(onLayoutChange).not.toHaveBeenCalled()
  })

  it('renders a saved arrangement instead of the default', async () => {
    setup([{ id: 'only', kind: 'overdue', x: 0, y: 0, w: 6, h: 5 }])
    expect(await screen.findByText('Overdue')).toBeInTheDocument()
    expect(screen.queryByText('Mini calendar')).not.toBeInTheDocument()
  })

  it('shows drag and remove affordances only while arranging', async () => {
    setup()
    await screen.findByText('Today')
    expect(screen.queryByRole('button', { name: /remove today/i })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Arrange' }))
    expect(screen.getByRole('button', { name: /remove today/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add module' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.queryByRole('button', { name: /remove today/i })).not.toBeInTheDocument()
  })

  it('removes a module and saves the result', async () => {
    const { onLayoutChange } = setup()
    await screen.findByText('Today')
    await userEvent.click(screen.getByRole('button', { name: 'Arrange' }))
    await userEvent.click(screen.getByRole('button', { name: /remove today/i }))

    expect(onLayoutChange).toHaveBeenCalledOnce()
    const saved = onLayoutChange.mock.calls[0][0] as DashboardModule[]
    expect(saved.some((x) => x.kind === 'today')).toBe(false)
    expect(saved).toHaveLength(DEFAULT_LAYOUT.length - 1)
  })

  it('offers only modules that are not already placed', async () => {
    setup([{ id: 'only', kind: 'today', x: 0, y: 0, w: 4, h: 6 }])
    await screen.findByText('Today')
    await userEvent.click(screen.getByRole('button', { name: 'Arrange' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add module' }))

    const picker = screen.getByRole('dialog', { name: /add a module/i })
    expect(within(picker).getByText('Overdue')).toBeInTheDocument()
    expect(within(picker).queryByText('Today')).not.toBeInTheDocument()
  })

  it('adds a picked module and saves the result', async () => {
    const { onLayoutChange } = setup([{ id: 'only', kind: 'today', x: 0, y: 0, w: 4, h: 6 }])
    await screen.findByText('Today')
    await userEvent.click(screen.getByRole('button', { name: 'Arrange' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add module' }))
    const picker = screen.getByRole('dialog', { name: /add a module/i })
    await userEvent.click(within(picker).getByText('Quick add'))

    const saved = onLayoutChange.mock.calls[0][0] as DashboardModule[]
    expect(saved.map((x) => x.kind)).toEqual(['today', 'quick_add'])
  })
})

describe('<HomeView> module contents', () => {
  it('shows only tasks due today in the Today module', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Due today', due: today() }),
      task({ uid: 'b', summary: 'Undated' }),
      task({ uid: 'c', summary: 'Far off', due: '2099-01-01' }),
    ])
    setup([{ id: 'x', kind: 'today', x: 0, y: 0, w: 6, h: 6 }])
    expect(await screen.findByText('Due today')).toBeInTheDocument()
    expect(screen.queryByText('Undated')).not.toBeInTheDocument()
    expect(screen.queryByText('Far off')).not.toBeInTheDocument()
  })

  it('leaves completed tasks out of the open modules', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Done already', due: today(), completed: true, status: 'COMPLETED' }),
    ])
    setup([{ id: 'x', kind: 'today', x: 0, y: 0, w: 6, h: 6 }])
    expect(await screen.findByText('Nothing due today.')).toBeInTheDocument()
  })

  it('leaves subtasks out, so rows are not duplicated without their parent', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Parent', due: today() }),
      task({ uid: 'b', summary: 'Child', due: today(), parent: 'a' }),
    ])
    setup([{ id: 'x', kind: 'today', x: 0, y: 0, w: 6, h: 6 }])
    expect(await screen.findByText('Parent')).toBeInTheDocument()
    expect(screen.queryByText('Child')).not.toBeInTheDocument()
  })

  it('says so when a module has nothing to show', async () => {
    setup([{ id: 'x', kind: 'overdue', x: 0, y: 0, w: 6, h: 5 }])
    expect(await screen.findByText('Nothing overdue.')).toBeInTheDocument()
  })

  it('only fetches what the arrangement actually shows', async () => {
    setup([{ id: 'x', kind: 'today', x: 0, y: 0, w: 6, h: 6 }])
    await screen.findByText('Nothing due today.')
    // No calendar or scheduling module is on the board, so nothing here should
    // pull a month of events or poll the scheduling endpoints. The calendar
    // *list* is fetched once for the whole app by the provider, so it is not
    // this view's to avoid — the per-calendar events fan-out is.
    expect(m.events).not.toHaveBeenCalled()
    expect(m.schedulingLinks).not.toHaveBeenCalled()
  })

  it('fetches calendar data once a calendar module is on the board', async () => {
    setup([{ id: 'x', kind: 'mini_calendar', x: 0, y: 0, w: 6, h: 6 }])
    await screen.findByText('Mini calendar')
    await vi.waitFor(() => expect(m.calendars).toHaveBeenCalled())
  })

  it('quick-add writes to the chosen list', async () => {
    m.createTask.mockResolvedValue(task())
    setup([{ id: 'x', kind: 'quick_add', x: 0, y: 0, w: 6, h: 3 }])
    const input = await screen.findByRole('textbox', { name: /add a task/i })
    await userEvent.type(input, 'New thing')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    // Through the shared optimistic create, so the body carries the idempotency
    // slug the stand-in's uid is derived from.
    expect(m.createTask).toHaveBeenCalledWith('l1',
      expect.objectContaining({ summary: 'New thing', client_id: expect.any(String) }))
  })
})

// ── mini calendar ──────────────────────────────────────────────────────────
// The module always renders the current month, so fixtures are built from
// today rather than a fixed date — the same trick as `today()` above.

const grid = monthGrid(new Date())
const p2 = (n: number) => String(n).padStart(2, '0')
const key = (d: Date) => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`
/** A day comfortably inside the rendered month, and a quiet one after it. */
const busyDay = grid.find((d) => d.getDate() === 15)!
const quietDay = grid.find((d) => d.getDate() === 16)!
const longLabel = (d: Date) =>
  d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })

const cal = (id: string, color: string | null): import('../api').List => ({
  id, href: `/${id}/`, name: id, is_task_list: false, is_calendar: true,
  open_count: 0, task_count: 0, event_count: 1, total: 1, color,
})

const event = (calId: string, id: string, summary: string, hour = 9,
  day: Date = busyDay, over: Partial<import('../api').CalEvent> = {},
): import('../api').CalEvent => ({
  uid: id, id, recurrence_id: null, is_recurring: false, calendar: `/${calId}/`,
  summary, description: null, location: null,
  start: `${key(day)}T${p2(hour)}:00:00`, start_is_date: false,
  end: `${key(day)}T${p2(hour + 1)}:00:00`, end_is_date: false, duration: null,
  all_day: false, status: null, busy: true, notify_minutes_before: null, tags: [], has_rrule: false,
  href: `/${calId}/${id}.ics`, etag: '"1"', ...over,
})

/** An all-day event over `days` days, written the way the wire does it: DTEND
 *  is EXCLUSIVE, so a one-day event ends on the following date. */
const allDayEvent = (calId: string, id: string, day: Date, days = 1) => {
  const end = new Date(day.getFullYear(), day.getMonth(), day.getDate() + days)
  return event(calId, id, 'All day', 0, day, {
    start: key(day), start_is_date: true,
    end: key(end), end_is_date: true, all_day: true,
  })
}

/** Mock the calendar endpoints, routing each calendar's events by id. */
function withCalendars(cals: import('../api').List[],
  events: Record<string, import('../api').CalEvent[]>) {
  m.calendars.mockResolvedValue(cals)
  m.events.mockImplementation(async (id: string) => events[id] ?? [])
}

const MINI: DashboardModule[] = [{ id: 'x', kind: 'mini_calendar', x: 0, y: 0, w: 4, h: 6 }]

// ── the day-plan module ────────────────────────────────────────────────────

/** A day entry, shaped like the wire's. Kept beside this suite rather than
 *  imported from `TodayView.test.tsx`: a factory shared between two suites is a
 *  third thing both have to agree with, and the fields that matter here are not
 *  the ones that matter there. */
const entry = (o: Partial<import('../api').DayEntry> = {}): import('../api').DayEntry => ({
  entry_id: 'e1', day: today(), kind: 'note', list: null, uid: null,
  title: 'Water the plants', source: 'user', position: 1,
  done_at: null, dropped_at: null, habit_id: null, estimate_minutes: null,
  rolled_to: null, worked_seconds: null, capped: null, created_at: '2026-08-21T08:00:00.000Z', ...o,
})

const dayPlan = (entries: import('../api').DayEntry[] = [], day = today()) =>
  ({
    day, planned: true, entries, capacity_minutes: null, capacity: null,
    committed_at: null, shutdown_at: null, reflection: null,
  } as import('../api').DayPlan)

const PLAN_MODULE: DashboardModule[] = [{ id: 'x', kind: 'day_plan', x: 0, y: 0, w: 6, h: 6 }]

describe("the day-plan module", () => {
  it('shows the day plan, in the order the day gives it', async () => {
    m.day.mockResolvedValue(dayPlan([
      entry({ entry_id: 'b', title: 'Second', position: 2 }),
      entry({ entry_id: 'a', title: 'First', position: 1 }),
    ]))
    setup(PLAN_MODULE)
    expect(await screen.findByText('First')).toBeInTheDocument()
    // `orderEntries` is the Today tab's, so the two screens cannot disagree
    // about which row comes first.
    const titles = [...document.querySelectorAll('.dash-task-title')].map((n) => n.textContent)
    expect(titles).toEqual(['First', 'Second'])
  })

  it('READS the day and never opens it', async () => {
    // The invariant this module is built around. `openDay` is the only call
    // that can CREATE a plan — it derives a snapshot from CalDAV and writes it —
    // and a dashboard that called it would snapshot a day on a morning the owner
    // never looked at. The Today tab is the only caller, by design.
    m.day.mockResolvedValue(dayPlan([entry({ title: 'A row' })]))
    setup(PLAN_MODULE)
    await screen.findByText('A row')
    expect(m.day).toHaveBeenCalledWith(today())
    expect(m.openDay).not.toHaveBeenCalled()
  })

  it('is not fetched at all when the module is not on the board', async () => {
    setup([{ id: 'x', kind: 'overdue', x: 0, y: 0, w: 6, h: 5 }])
    await screen.findByText('Nothing overdue.')
    expect(m.day).not.toHaveBeenCalled()
  })

  it('says what to do when the day has nothing on it', async () => {
    m.day.mockResolvedValue(dayPlan([]))
    setup(PLAN_MODULE)
    // A day nobody has opened answers `planned: false` with no rows, and this
    // reads the same to a user as one they opened and emptied. The card points
    // at the tab that can change it rather than offering to plan the day here.
    expect(await screen.findByText('Nothing on today yet. Plan it from the Today tab.'))
      .toBeInTheDocument()
  })

  it('leaves dropped rows out', async () => {
    // "I am not doing this" is a decision and belongs in the day's own record,
    // not on a card answering "what am I doing".
    m.day.mockResolvedValue(dayPlan([
      entry({ entry_id: 'a', title: 'Still on' }),
      entry({ entry_id: 'b', title: 'Dropped', dropped_at: '2026-08-21T09:00:00.000Z' }),
    ]))
    setup(PLAN_MODULE)
    expect(await screen.findByText('Still on')).toBeInTheDocument()
    expect(screen.queryByText('Dropped')).not.toBeInTheDocument()
  })

  it('does not show a plan for a different day', async () => {
    // The rollover guard. Rows from yesterday under a heading that says today
    // is the one mistake a day-scoped surface cannot make, so this is gated
    // rather than filtered.
    m.day.mockResolvedValue(dayPlan([entry({ title: 'Yesterday row' })], '2020-01-01'))
    setup(PLAN_MODULE)
    await waitFor(() => expect(m.day).toHaveBeenCalled())
    expect(screen.queryByText('Yesterday row')).not.toBeInTheDocument()
  })

  it('ticks a NOTE through the day entry', async () => {
    m.day.mockResolvedValue(dayPlan([entry({ entry_id: 'n1', title: 'A note' })]))
    m.patchDayEntry.mockResolvedValue(entry({ entry_id: 'n1', title: 'A note',
      done_at: '2026-08-21T10:00:00.000Z' }))
    setup(PLAN_MODULE)
    const box = await screen.findByRole('button', { name: 'Check A note' })
    await userEvent.click(box)
    expect(m.patchDayEntry).toHaveBeenCalledWith(today(), 'n1', { done: true })
    // And the row flips: the accessible name is the other half of the toggle.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Uncheck A note' }))
      .toBeInTheDocument())
  })

  it('ticks a TASK through the task, never through the entry', async () => {
    // A task entry records no doneness of its own — the task's state is the
    // truth, and two writers for one fact is how they come to disagree.
    m.tasks.mockResolvedValue([task({ uid: 'u1', list: 'l1', summary: 'Ship it' })])
    m.day.mockResolvedValue(dayPlan([
      entry({ entry_id: 't1', kind: 'task', list: 'l1', uid: 'u1', title: null }),
    ]))
    m.complete.mockResolvedValue(task({ uid: 'u1', list: 'l1', summary: 'Ship it',
      completed: true, status: 'COMPLETED' }))
    setup(PLAN_MODULE)
    const box = await screen.findByRole('button', { name: 'Check Ship it' })
    await userEvent.click(box)
    await waitFor(() => expect(m.complete).toHaveBeenCalledWith('l1', 'u1', true))
    expect(m.patchDayEntry).not.toHaveBeenCalled()
  })

  it('shows a task entry whose task is gone, but will not tick it', async () => {
    // `entryTitle` says what happened; there is nothing left to tick, so the
    // control is disabled rather than absent and the row keeps its column.
    m.tasks.mockResolvedValue([])
    m.day.mockResolvedValue(dayPlan([
      entry({ entry_id: 't1', kind: 'task', list: 'l1', uid: 'gone', title: null }),
    ]))
    setup(PLAN_MODULE)
    expect(await screen.findByText('This task is no longer in your lists')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Check / })).toBeDisabled()
  })

  it('shows the estimate when there is one, and a due date only when it is not today', async () => {
    // One cell, and it has to say something. A due of today repeated down every
    // row of a card headed "Today's plan" is the date already in the heading.
    m.tasks.mockResolvedValue([
      task({ uid: 'a', list: 'l1', summary: 'Due today', due: today() }),
      task({ uid: 'b', list: 'l1', summary: 'Due later', due: '2099-03-04' }),
    ])
    m.day.mockResolvedValue(dayPlan([
      entry({ entry_id: '1', title: 'Estimated', estimate_minutes: 45 }),
      entry({ entry_id: '2', kind: 'task', list: 'l1', uid: 'a', title: null }),
      entry({ entry_id: '3', kind: 'task', list: 'l1', uid: 'b', title: null }),
    ]))
    setup(PLAN_MODULE)
    await screen.findByText('Estimated')
    expect(screen.getByText('45m')).toBeInTheDocument()
    const row = (t: string) => screen.getByText(t).closest('.dash-task')!
    expect(row('Due today').querySelector('.dash-task-due')).toBeNull()
    expect(row('Due later').querySelector('.dash-task-due')).not.toBeNull()
  })
})

describe('mini calendar', () => {
  const dayButton = (d: Date) =>
    screen.getByRole('button', { name: new RegExp(`^${longLabel(d)}`) })

  it('fetches the whole rendered grid, not just the current month', async () => {
    withCalendars([cal('c1', '#1565C0')], {})
    setup(MINI)
    await waitFor(() => expect(m.events).toHaveBeenCalled())
    // The grid's first and last cells belong to the neighbouring months; before
    // this they were fetched out of range and could never carry a dot.
    expect(m.events).toHaveBeenCalledWith('c1', key(grid[0]), key(new Date(
      grid[41].getFullYear(), grid[41].getMonth(), grid[41].getDate() + 1)))
  })

  it('dots a day in each of its calendars’ colors, deduped', async () => {
    withCalendars([cal('c1', '#1565C0'), cal('c2', '#D9480F')], {
      // Two events on c1: one dot, not two — the strip says which calendars.
      c1: [event('c1', 'a', 'Standup'), event('c1', 'b', 'Retro', 11)],
      c2: [event('c2', 'c', 'Dentist', 14)],
    })
    setup(MINI)
    await waitFor(() => expect(dayButton(busyDay)).toBeEnabled())
    const dots = dayButton(busyDay).querySelectorAll('.mini-dot')
    expect(dots).toHaveLength(2)
    expect(dots[0].getAttribute('style')).toContain('--ev-c: #1565C0')
    expect(dots[1].getAttribute('style')).toContain('--ev-c: #D9480F')
  })

  it('caps the dots at three however many calendars land on a day', async () => {
    const cals = ['c1', 'c2', 'c3', 'c4'].map((id, i) =>
      cal(id, ['#1565C0', '#D9480F', '#2E7D32', '#6A1B9A'][i]))
    withCalendars(cals, Object.fromEntries(
      cals.map((c, i) => [c.id, [event(c.id, `e${i}`, `Event ${i}`, 9 + i)]])))
    setup(MINI)
    await waitFor(() => expect(dayButton(busyDay)).toBeEnabled())
    expect(dayButton(busyDay).querySelectorAll('.mini-dot')).toHaveLength(3)
    // The count the dots can't show still reaches a screen reader.
    expect(dayButton(busyDay)).toHaveAccessibleName(`${longLabel(busyDay)}, 4 events`)
  })

  it('opens a read-only popover of the day’s events', async () => {
    withCalendars([cal('c1', '#1565C0')], { c1: [event('c1', 'a', 'Standup')] })
    setup(MINI)
    await waitFor(() => expect(dayButton(busyDay)).toBeEnabled())
    await userEvent.click(dayButton(busyDay))
    const pop = screen.getByRole('dialog')
    expect(within(pop).getByText('Standup')).toBeInTheDocument()
    // Home shows the day; the Calendar tab is where it gets edited.
    expect(within(pop).queryByRole('button')).toBeNull()
  })

  it('closes the popover on Escape and returns focus to the day', async () => {
    withCalendars([cal('c1', '#1565C0')], { c1: [event('c1', 'a', 'Standup')] })
    setup(MINI)
    await waitFor(() => expect(dayButton(busyDay)).toBeEnabled())
    await userEvent.click(dayButton(busyDay))
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(dayButton(busyDay)).toHaveFocus()
  })

  it('leaves a day with no events inert', async () => {
    withCalendars([cal('c1', '#1565C0')], { c1: [event('c1', 'a', 'Standup')] })
    setup(MINI)
    await waitFor(() => expect(dayButton(busyDay)).toBeEnabled())
    expect(dayButton(quietDay)).toBeDisabled()
    expect(dayButton(quietDay).querySelector('.mini-dot')).toBeNull()
  })

  it('drops a hidden calendar’s dots without refetching', async () => {
    withCalendars([cal('c1', '#1565C0'), cal('c2', '#D9480F')], {
      c1: [event('c1', 'a', 'Standup')],
      c2: [event('c2', 'c', 'Dentist', 14)],
    })
    setup(MINI, { hiddenCalendars: ['c2'] })
    await waitFor(() => expect(dayButton(busyDay)).toBeEnabled())
    const dots = dayButton(busyDay).querySelectorAll('.mini-dot')
    expect(dots).toHaveLength(1)
    expect(dots[0].getAttribute('style')).toContain('--ev-c: #1565C0')
    // Visibility is a pure filter — hiding a calendar costs no round trip.
    expect(m.events).toHaveBeenCalledTimes(2)
  })

  it('never fetches an archived calendar', async () => {
    withCalendars([cal('c1', '#1565C0'), cal('c2', '#D9480F')], {
      c1: [event('c1', 'a', 'Standup')],
      c2: [event('c2', 'c', 'Dentist', 14)],
    })
    setup(MINI, { archivedCalendars: ['c2'] })
    await waitFor(() => expect(dayButton(busyDay)).toBeEnabled())
    expect(m.events).toHaveBeenCalledTimes(1)
    expect(m.events).toHaveBeenCalledWith('c1', expect.any(String), expect.any(String))
  })
})

// ── the mini calendar must not dot a day the event does not cover ───────────
// An all-day DTEND is exclusive, and a timed end sitting exactly on midnight
// belongs to the previous day. Walking to the end date inclusive dotted one day
// past every such event — a birthday marked tomorrow busy too. The rule lives
// in calendar.lastDayOf now, shared with the month grid, rather than in a
// second copy here; these pin it at this level, which is where it went wrong.

describe('mini calendar spans', () => {
  const dayButton = (d: Date) =>
    screen.getByRole('button', { name: new RegExp(`^${longLabel(d)}`) })
  const isBusy = (d: Date) => dayButton(d).querySelectorAll('.mini-dot').length > 0

  it('dots exactly one day for a one-day all-day event', async () => {
    withCalendars([cal('c1', '#1565C0')], { c1: [allDayEvent('c1', 'a', busyDay)] })
    setup(MINI)
    await waitFor(() => expect(dayButton(busyDay)).toBeEnabled())
    expect(isBusy(busyDay)).toBe(true)
    expect(isBusy(quietDay)).toBe(false)
  })

  it('dots exactly three days for a three-day all-day event', async () => {
    const [d1, d2, d3, d4] = [15, 16, 17, 18].map((n) => grid.find((d) => d.getDate() === n)!)
    withCalendars([cal('c1', '#1565C0')], { c1: [allDayEvent('c1', 'a', d1, 3)] })
    setup(MINI)
    await waitFor(() => expect(dayButton(d1)).toBeEnabled())
    expect([isBusy(d1), isBusy(d2), isBusy(d3), isBusy(d4)]).toEqual([true, true, true, false])
  })

  it('dots only its own day for a timed event ending at midnight', async () => {
    const next = new Date(busyDay.getFullYear(), busyDay.getMonth(), busyDay.getDate() + 1)
    withCalendars([cal('c1', '#1565C0')], {
      c1: [event('c1', 'a', 'Evening', 20, busyDay, { end: `${key(next)}T00:00:00` })],
    })
    setup(MINI)
    await waitFor(() => expect(dayButton(busyDay)).toBeEnabled())
    expect(isBusy(busyDay)).toBe(true)
    expect(isBusy(quietDay)).toBe(false)
  })
})


// ── the scheduling fetch must not be won by a stale batch ───────────────────
// The effect re-runs on `rev`, so two SSE-driven refreshes put two two-request
// batches in flight and whichever settled last won — painting whatever the
// older one happened to see. Every other fetch in the app carries this guard
// (`useTaskData`'s token ref, `fetchWindow`'s per-window generation); this was
// the last one without it.

describe('scheduling modules', () => {
  const layout: DashboardModule[] = [
    { id: 'l', kind: 'booking_links', x: 0, y: 0, w: 6, h: 6 },
  ]

  const link = (token: string, title: string) => ({
    token, title, description: null, calendar: 'c1', calendar_name: 'Work',
    calendar_missing: false, duration_minutes: 30, timezone: 'UTC',
    availability: {}, show_busy: true, buffer_minutes: 0, min_notice_hours: 0,
    horizon_days: 14, enabled: true, booking_count: 0,
    created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
  })

  it('ignores an older batch that settles after a newer one', async () => {
    let releaseFirst: (v: unknown[]) => void = () => {}
    const first = new Promise<unknown[]>((res) => { releaseFirst = res })
    m.schedulingLinks
      .mockReturnValueOnce(first as never)
      .mockResolvedValue([link('new', 'Newer link')] as never)

    const onLayoutChange = vi.fn()
    const { rerender } = render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <HomeView rev={0} onExpire={vi.fn()} layout={layout} onLayoutChange={onLayoutChange} />
      </DataProvider>,
    )
    // A second refresh — the shape an SSE bump takes.
    rerender(
      <DataProvider rev={1} onExpire={vi.fn()}>
        <HomeView rev={1} onExpire={vi.fn()} layout={layout} onLayoutChange={onLayoutChange} />
      </DataProvider>,
    )
    await waitFor(() => expect(m.schedulingLinks).toHaveBeenCalledTimes(2))
    expect(await screen.findByText('Newer link')).toBeInTheDocument()

    // Now the first batch — the one the user has already moved past — lands.
    releaseFirst([link('old', 'Stale link')])
    await act(async () => { await first })

    expect(screen.getByText('Newer link')).toBeInTheDocument()
    expect(screen.queryByText('Stale link')).not.toBeInTheDocument()
  })
})
