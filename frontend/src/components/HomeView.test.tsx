import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
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
  derived_percent: null, pinned: false, sort_order: null, href: '/l1/u1.ics', etag: '"1"', ...o,
})

const list = { id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 1, task_count: 1, event_count: 0, total: 1, color: '#D9480F' }

/** Render with a controlled layout so assertions can watch it change. */
function setup(initial: DashboardModule[] = DEFAULT_LAYOUT,
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
  it('falls back to the stock arrangement when nothing is saved', async () => {
    setup([])
    expect(await screen.findByText('Today')).toBeInTheDocument()
    expect(screen.getByText('Upcoming')).toBeInTheDocument()
    expect(screen.getByText('Mini calendar')).toBeInTheDocument()
  })

  it('does not persist the stock arrangement until something is changed', async () => {
    const { onLayoutChange } = setup([])
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
  end: `${key(day)}T${p2(hour + 1)}:00:00`, end_is_date: false,
  all_day: false, status: null, tags: [], has_rrule: false,
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
