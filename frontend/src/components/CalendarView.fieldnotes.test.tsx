import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CalendarView } from './CalendarView'
import { DayPopover } from './DayPopover'
import { SchedulingView } from './SchedulingView'
import { DataProvider } from '../data'
import { setCacheUser } from '../cache'
import { api, type CalEvent, type List, type Task } from '../api'
import type { DayEv } from '../calendar'
import { withPrompt } from '../test/back'
import { setBreakpoint } from '../test/setup'
import fixture from '../test/drawing-fixture.json'

// The Calendar, its day popup and Scheduling under Field notes, the design that
// names things and does not explain them. The preset behaviour is
// CalendarView.test.tsx's, DayPopover.test.tsx's and the backlog files', and is
// not repeated here.
vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})

const m = vi.mocked(api)

const cal: List = {
  id: 'c1', href: '/c1/', name: 'Work', is_task_list: false, is_calendar: true,
  open_count: 0, task_count: 0, event_count: 1, total: 1, color: '#D9480F',
}

const taskList: List = {
  id: 'tl1', href: '/tl1/', name: 'Errands', is_task_list: true, is_calendar: false,
  open_count: 2, task_count: 2, event_count: 0, total: 2, color: '#1565C0',
}

const ev = (o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'u1', id: 'u1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
  summary: 'Standup', description: null, location: null,
  start: '2026-03-02T09:00:00', start_is_date: false,
  end: '2026-03-02T09:30:00', end_is_date: false, duration: null,
  all_day: false, status: null, busy: true, notify_minutes_before: null, tags: [], has_rrule: false,
  href: '/c1/u1.ics', etag: '"1"', ...o,
})

const tsk = (o: Partial<Task> = {}): Task => ({
  uid: 't1', list: 'tl1', summary: 'Renew passport', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, parked: false, parked_at: null,
  original_due: null, original_due_is_date: false, original_due_moved: false,
  priority: null, priority_label: 'none',
  percent_complete: null, due: '2026-03-04', due_is_date: true,
  start: null, start_is_date: true, tags: [], parent: null, children: [],
  child_count: 0, completed_child_count: 0, derived_percent: null,
  pinned: false, sort_order: null,
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/tl1/t1.ics', etag: '"1"', ...o,
})

const link = (o: Record<string, unknown> = {}) => ({
  token: 'tok1', title: 'Intro call', description: null, calendar: 'c1', calendar_name: 'Work',
  calendar_missing: false, duration_minutes: 30, timezone: 'UTC',
  availability: { '0': ['09:00-17:00'] }, show_busy: true, buffer_minutes: 0, min_notice_hours: 24,
  horizon_days: 30, enabled: true, booking_count: 0, url: 'https://x/book/tok1', ...o,
})

function Harness() {
  const [cursor, setCursor] = useState(() => new Date(2026, 2, 1))
  return (
    <DataProvider rev={0} onExpire={vi.fn()}>
      <CalendarView onExpire={vi.fn()} cursor={cursor} onCursorChange={setCursor}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenCalendars={[]} onHiddenCalendarsChange={vi.fn()}
        archivedCalendars={[]} onArchivedCalendarsChange={vi.fn()}
        calTaskLists={['tl1']} onCalTaskListsChange={vi.fn()}
        calShowDone onCalShowDoneChange={vi.fn()}
        fit="dynamic" />
    </DataProvider>
  )
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 2, 5))
  vi.clearAllMocks()
  setCacheUser('')
  localStorage.clear()
  // Before the render: `useFieldNotes` reads the attribute when it mounts.
  document.documentElement.setAttribute('data-surface', 'app')
  m.calendars.mockResolvedValue([cal])
  m.lists.mockResolvedValue([taskList])
  m.tasks.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
})

afterEach(() => {
  vi.useRealTimers()
  document.documentElement.removeAttribute('data-surface')
})

const userSetup = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

describe('<CalendarView> under Field notes', () => {
  it('draws the month without a tooltip, a glyph tick or a plain strike', async () => {
    m.events.mockResolvedValue([ev()])
    m.tasks.mockResolvedValue([
      tsk({ uid: 'a', summary: 'Renew passport' }),
      tsk({ uid: 'b', summary: 'Post letter', completed: true, status: 'COMPLETED' }),
    ])
    const { container } = render(withPrompt(<Harness />))
    await waitFor(() => expect(container.querySelectorAll('.cal-task')).toHaveLength(2))

    expect(container.querySelectorAll('[title]')).toHaveLength(0)
    const done = container.querySelector('.cal-task.done')!
    expect(done.querySelector('.tick svg.check-ink')).not.toBeNull()
    expect(done.querySelector('bdi .strike-ink.on')).not.toBeNull()
    const open = container.querySelector('.cal-task:not(.done)')!
    expect(open.querySelector('.tick svg.check-ink')).not.toBeNull()
    expect(open.querySelector('.strike-ink.on')).toBeNull()
    expect(container.querySelector('.cal-grid, .cal')!.textContent).not.toMatch(/[☑☐]/)
    // The chip is named by its content now that it has no title.
    expect(screen.getAllByRole('button', { name: /Standup/ })[0]).toBeInTheDocument()
  })

  it('keeps no "Doesn’t block slots" line under Free', async () => {
    m.events.mockResolvedValue([ev({ busy: false })])
    render(withPrompt(<Harness />))
    const user = userSetup()
    await user.click((await screen.findAllByRole('button', { name: /Standup/ }))[0])
    await screen.findByRole('dialog')
    expect(screen.getByLabelText('Show as')).toHaveValue('free')
    expect(screen.queryByText(/block slots on your booking links/i)).toBeNull()
  })

  it('keeps no "All events" line on a repeating event', async () => {
    m.events.mockResolvedValue([ev({
      id: 'u1::2026-03-09T09:00:00', recurrence_id: '2026-03-09T09:00:00', is_recurring: true,
      has_rrule: true, start: '2026-03-09T09:00:00', end: '2026-03-09T09:30:00',
    })])
    render(withPrompt(<Harness />))
    const user = userSetup()
    await user.click((await screen.findAllByRole('button', { name: /Standup/ }))[0])
    await screen.findByRole('dialog')
    expect(screen.queryByText(/shifts every occurrence/i)).toBeNull()
  })

  it('keeps a decorative drawing above "Nothing this day" on a phone', async () => {
    act(() => setBreakpoint(true))
    const { container } = render(withPrompt(<Harness />))
    const empty = await waitFor(() => {
      const e = container.querySelector('.agenda-empty')
      expect(e).not.toBeNull()
      return e as HTMLElement
    })
    expect(empty).toHaveTextContent('Nothing this day.')
    const wrap = empty.querySelector('.view-drawing')!
    expect(wrap).toHaveAttribute('aria-hidden', 'true')
    expect(empty.firstElementChild).toBe(wrap)
  })

  it('keeps the drawing in the no-calendars empty state, once loaded', async () => {
    m.calendars.mockResolvedValue([])
    const { container } = render(withPrompt(<Harness />))
    const empty = await waitFor(() => {
      const e = container.querySelector('.content > .empty')
      expect(e).toHaveTextContent('Create a calendar to get started.')
      return e as HTMLElement
    })
    expect(empty.querySelector('.view-drawing')).toHaveAttribute('aria-hidden', 'true')
  })

  it('draws nothing while the calendars are still loading', async () => {
    m.calendars.mockReturnValue(new Promise(() => {}))
    const { container } = render(withPrompt(<Harness />))
    const empty = await waitFor(() => {
      const e = container.querySelector('.content > .empty')
      expect(e).not.toBeNull()
      return e as HTMLElement
    })
    expect(empty).toHaveAttribute('aria-busy', 'true')
    expect(container.querySelector('.view-drawing')).toBeNull()
  })

  it('leaves the presets without it', async () => {
    document.documentElement.removeAttribute('data-surface')
    act(() => setBreakpoint(true))
    const { container } = render(withPrompt(<Harness />))
    await waitFor(() => expect(container.querySelector('.agenda-empty')).not.toBeNull())
    expect(container.querySelector('.view-drawing')).toBeNull()
  })
})

describe('<DayPopover> under Field notes', () => {
  const dayEv = (o: Partial<DayEv> = {}): DayEv => ({ ...ev(), ...o })

  it('closes with a button named Close and no tooltip', () => {
    render(<DayPopover day="2026-03-04" x={40} y={40} events={[dayEv()]}
      styleOf={() => undefined} onClose={vi.fn()} />)
    const close = within(screen.getByRole('dialog')).getByRole('button', { name: 'Close' })
    expect(close).not.toHaveAttribute('title')
    expect(document.querySelectorAll('[title]')).toHaveLength(0)
  })

  it('draws a done task with the ink tick and strike, and an open one with a tick only', () => {
    render(<DayPopover day="2026-03-04" x={40} y={40} events={[]}
      tasks={[tsk({ uid: 'a', summary: 'Done already', completed: true, status: 'COMPLETED' }),
        tsk({ uid: 'b', summary: 'Still open' })]}
      styleOf={() => undefined} onClose={vi.fn()} />)
    const done = screen.getByText('Done already').closest('.agenda-task')!
    expect(done.classList.contains('done')).toBe(true)
    expect(done.querySelector('.tick .check-ink')).not.toBeNull()
    expect(done.querySelector('.strike-ink.on')).not.toBeNull()
    const open = screen.getByText('Still open').closest('.agenda-task')!
    expect(open.querySelector('.tick .check-ink')).not.toBeNull()
    expect(open.querySelector('.strike-ink.on')).toBeNull()
    expect(screen.getByRole('dialog').textContent).not.toMatch(/[☑☐]/)
  })
})

describe('<SchedulingView> under Field notes', () => {
  it('lays out its empty states from the stylesheet and keeps no tooltip', async () => {
    m.schedulingLinks.mockResolvedValue([link(), link({ token: 'tok2', title: 'Off', enabled: false }),
      link({ token: 'tok3', title: 'Gone', calendar_missing: true })] as never)
    const { container } = render(<SchedulingView rev={0} onExpire={vi.fn()} />)
    await screen.findByText('Intro call')
    expect(container.querySelectorAll('[title]')).toHaveLength(0)
    const empty = container.querySelector('.empty')!
    expect(empty).not.toHaveAttribute('style')
    expect(container.querySelector('.section-label')).not.toHaveAttribute('style')
  })

  it('shows an empty list with no inline padding', async () => {
    const { container } = render(<SchedulingView rev={0} onExpire={vi.fn()} />)
    await screen.findByText('Nothing booked yet.', { exact: false })
    expect(container.querySelectorAll('.empty').length).toBeGreaterThan(0)
    for (const e of container.querySelectorAll('.empty')) expect(e).not.toHaveAttribute('style')
  })

  it('names the add-range button without a tooltip, and keeps no busy-times line', async () => {
    m.schedulingLinks.mockResolvedValue([link()] as never)
    render(<SchedulingView rev={0} onExpire={vi.fn()} />)
    const user = userSetup()
    await user.click(await screen.findByRole('button', { name: /edit/i }))
    const dialog = await screen.findByRole('dialog')
    const add = within(dialog).getAllByRole('button', { name: 'Add another range' })[0]
    expect(add).not.toHaveAttribute('title')
    expect(within(dialog).queryByText(/Shown as unlabeled/)).toBeNull()
    expect(dialog.querySelectorAll('[title]')).toHaveLength(0)
  })
})

describe('<CalendarView> under Field notes: the month as a page', () => {
  const cell = (c: HTMLElement, day: string) => c.querySelector(`.cal-cell[data-day="${day}"]`)!

  it('rules the grid, crosses off the days gone and circles today, all as decoration', async () => {
    const { container } = render(withPrompt(<Harness />))
    await waitFor(() => expect(container.querySelectorAll('.cal-cell')).toHaveLength(42))
    const ink = container.querySelector('.cal-grid')!.lastElementChild!
    expect(ink.matches('svg.grid-ink')).toBe(true)
    expect(ink).toHaveAttribute('aria-hidden', 'true')
    expect(cell(container, '2026-03-05')).toHaveAttribute('aria-current', 'date')
    expect(container.querySelectorAll('[aria-current="date"]')).toHaveLength(1)
    expect(cell(container, '2026-03-05').querySelector('.daynum > svg.today-ink[aria-hidden="true"]')).not.toBeNull()
    for (const d of ['2026-03-01', '2026-03-02', '2026-03-03', '2026-03-04']) {
      expect(cell(container, d).querySelector('.daynum > svg.cross-ink[aria-hidden="true"]'), d).not.toBeNull()
    }
    expect(container.querySelectorAll('.cross-ink')).toHaveLength(4)
    expect(cell(container, '2026-03-05').querySelector('.cross-ink')).toBeNull()
    expect(cell(container, '2026-03-05').querySelector('.daynum')!.textContent).toBe('5')
  })

  it('leaves the presets their grid, and still names today', async () => {
    document.documentElement.removeAttribute('data-surface')
    const { container } = render(withPrompt(<Harness />))
    await waitFor(() => expect(container.querySelectorAll('.cal-cell')).toHaveLength(42))
    expect(container.querySelector('.grid-ink, .today-ink, .cross-ink')).toBeNull()
    expect(cell(container, '2026-03-05')).toHaveAttribute('aria-current', 'date')
  })
})

describe('<CalendarView> under Field notes: events in pen and marker', () => {
  // Offsite runs Tue 10 to Thu 12, Cabin Fri 13 to Mon 16 (over a week's
  // turn: Sun 15 is the grid's index 14), Birthday is the one day of Wed 18,
  // and the timed Standup is on Mon 2.
  const events = () => [
    ev({ uid: 'a', id: 'a', summary: 'Offsite', all_day: true, start: '2026-03-10', end: '2026-03-13', start_is_date: true, end_is_date: true }),
    ev({ uid: 'b', id: 'b', summary: 'Cabin', all_day: true, start: '2026-03-13', end: '2026-03-17', start_is_date: true, end_is_date: true }),
    ev({ uid: 'c', id: 'c', summary: 'Birthday', all_day: true, start: '2026-03-18', end: '2026-03-19', start_is_date: true, end_is_date: true }),
    ev(),
  ]
  const cell = (c: HTMLElement, day: string) => c.querySelector(`.cal-cell[data-day="${day}"]`)!
  const chip = (c: HTMLElement, day: string, title: string) => {
    const found = [...cell(c, `2026-03-${day}`).querySelectorAll('.cal-ev')]
      .find((e) => e.querySelector('bdi')?.textContent === title)
    expect(found, `${title} on the ${day}th`).toBeDefined()
    return found!
  }

  it('cuts an all-day run into one swipe and writes its title once a week', async () => {
    m.events.mockResolvedValue(events())
    const { container } = render(withPrompt(<Harness />))
    await waitFor(() => expect(container.querySelectorAll('.cal-ev').length).toBeGreaterThan(0))

    expect(chip(container, '10', 'Offsite')).toHaveAttribute('data-span', 'start')
    expect(chip(container, '10', 'Offsite')).not.toHaveAttribute('data-quiet')
    expect(chip(container, '11', 'Offsite')).toHaveAttribute('data-span', 'mid')
    expect(chip(container, '11', 'Offsite')).toHaveAttribute('data-quiet')
    expect(chip(container, '12', 'Offsite')).toHaveAttribute('data-span', 'end')
    expect(chip(container, '12', 'Offsite')).toHaveAttribute('data-quiet')

    expect(chip(container, '13', 'Cabin')).toHaveAttribute('data-span', 'start')
    expect(chip(container, '14', 'Cabin')).toHaveAttribute('data-span', 'mid')
    expect(chip(container, '14', 'Cabin')).toHaveAttribute('data-quiet')
    // A Sunday starts the next row: the title is written again there.
    expect(chip(container, '15', 'Cabin')).toHaveAttribute('data-span', 'mid')
    expect(chip(container, '15', 'Cabin')).not.toHaveAttribute('data-quiet')
    expect(chip(container, '16', 'Cabin')).toHaveAttribute('data-span', 'end')
    expect(chip(container, '16', 'Cabin')).toHaveAttribute('data-quiet')

    for (const [day, title] of [['18', 'Birthday'], ['02', 'Standup']]) {
      expect(chip(container, day, title)).not.toHaveAttribute('data-span')
      expect(chip(container, day, title)).not.toHaveAttribute('data-quiet')
    }
  })

  it('draws an all-day run as a marker band on a phone, and only the rest as dots', async () => {
    act(() => setBreakpoint(true))
    m.events.mockResolvedValue(events())
    const { container } = render(withPrompt(<Harness />))
    await waitFor(() => expect(container.querySelectorAll('.ev-band').length).toBeGreaterThan(0))

    expect(cell(container, '2026-03-11').querySelector('.ev-band[data-span="mid"]')).not.toBeNull()
    const birthday = cell(container, '2026-03-18').querySelector('.ev-band')
    expect(birthday).not.toBeNull()
    expect(birthday).not.toHaveAttribute('data-span')
    expect(container.querySelector('.ev-dot.allday')).toBeNull()
    expect(cell(container, '2026-03-02').querySelector('.ev-dots .ev-dot')).not.toBeNull()
  })

  it('leaves the presets their chips and dots', async () => {
    document.documentElement.removeAttribute('data-surface')
    m.events.mockResolvedValue(events())
    const { container, unmount } = render(withPrompt(<Harness />))
    await waitFor(() => expect(container.querySelectorAll('.cal-ev').length).toBeGreaterThan(0))
    expect(container.querySelector('[data-span]')).toBeNull()
    expect(container.querySelector('[data-quiet]')).toBeNull()
    expect(container.querySelector('.ev-band')).toBeNull()
    unmount()

    act(() => setBreakpoint(true))
    const phone = render(withPrompt(<Harness />)).container
    await waitFor(() => expect(phone.querySelectorAll('.ev-dot.allday').length).toBeGreaterThan(0))
    expect(phone.querySelector('[data-span]')).toBeNull()
    expect(phone.querySelector('.ev-band')).toBeNull()
  })
})

describe('<CalendarView> under Field notes: the page\'s top', () => {
  const kids = (c: HTMLElement) => [...c.querySelector('.cal-head')!.children].map((e) => e.getAttribute('class'))

  it('writes the month first on a desktop, the controls after it', async () => {
    const { container } = render(withPrompt(<Harness />))
    await screen.findByRole('button', { name: 'New event' })
    expect(kids(container)).toEqual(['cal-drawing', 'cal-title', 'spacer', 'icon-btn', 'btn ghost', 'icon-btn', 'btn'])
    const title = container.querySelector('.cal-title')!
    expect(title).toHaveTextContent('March 2026')
    expect(title.textContent).toBe('March 2026')
    const month = container.querySelector('.cal-month')!
    expect(month.textContent).toBe('March')
    expect(month.querySelector('svg.month-ink[aria-hidden="true"]')).not.toBeNull()
    expect(container.querySelector('.cal-year')!.textContent).toBe('2026')
    expect(screen.getByRole('button', { name: 'Previous month' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next month' })).toBeInTheDocument()
  })

  it('keeps the controls before the month on a phone', async () => {
    act(() => setBreakpoint(true))
    const { container } = render(withPrompt(<Harness />))
    await waitFor(() => expect(container.querySelector('.cal-month')).not.toBeNull())
    const head = container.querySelector('.cal-head')!
    expect(head.children[0]).toHaveClass('icon-btn')
    expect(head.children[1]).toHaveClass('btn', 'ghost')
    expect(head.children[2]).toHaveClass('icon-btn')
    expect(head.children[3]).toHaveClass('cal-title')
    expect(head.children[3].querySelector('.cal-month')).not.toBeNull()
  })

  it('leaves the presets their order and their plain title', async () => {
    document.documentElement.removeAttribute('data-surface')
    const { container } = render(withPrompt(<Harness />))
    await screen.findByRole('button', { name: 'New event' })
    expect(container.querySelector('.cal-head')!.children[0]).toHaveClass('icon-btn')
    expect(container.querySelector('.cal-title')!.textContent).toBe('March 2026')
    expect(container.querySelector('.cal-month')).toBeNull()
  })
})

describe("<CalendarView> under Field notes: the month's drawing", () => {
  const monthDrawing = (day: string) => ({
    ...fixture, view: 'month', day, subject: 'month-test', viewBox: [0, 0, 200, 110], ambient: null,
    marks: (fixture.marks as { reward: number | null; when: unknown[]; frames: string[] }[])
      .filter((mk) => mk.reward === null && mk.when.length === 0)
      .map((mk) => ({ ...mk, frames: mk.frames.slice(0, 1) })),
  })
  const monthCalls = () => m.drawing.mock.calls.filter((c) => c[0] === 'month')

  it('heads the page on a desktop', async () => {
    m.drawing.mockResolvedValue(monthDrawing('2026-03-01'))
    const user = userSetup()
    const { container } = render(withPrompt(<Harness />))
    await screen.findByRole('button', { name: 'New event' })
    const first = container.querySelector('.cal-head')!.firstElementChild!
    expect(first).toHaveClass('cal-drawing')
    expect(first).toHaveAttribute('aria-hidden', 'true')
    await waitFor(() => expect(first.querySelector('svg.day-drawing')).not.toBeNull())
    expect(m.drawing).toHaveBeenCalledWith('month', '2026-03-01', 'light')
    await user.click(screen.getByRole('button', { name: 'Next month' }))
    await waitFor(() => expect(m.drawing).toHaveBeenCalledWith('month', '2026-04-01', 'light'))
  })

  it('is not drawn on a phone', async () => {
    act(() => setBreakpoint(true))
    const { container } = render(withPrompt(<Harness />))
    await waitFor(() => expect(container.querySelector('.cal-month')).not.toBeNull())
    expect(container.querySelector('.cal-drawing')).toBeNull()
    expect(monthCalls()).toHaveLength(0)
  })

  it('keeps one illustration', async () => {
    m.calendars.mockResolvedValue([])
    const { container } = render(withPrompt(<Harness />))
    await waitFor(() => expect(container.querySelector('.content > .empty .view-drawing')).not.toBeNull())
    expect(container.querySelector('.cal-drawing')).toBeNull()
  })

  it('leaves the presets without it', async () => {
    document.documentElement.removeAttribute('data-surface')
    const { container } = render(withPrompt(<Harness />))
    await screen.findByRole('button', { name: 'New event' })
    expect(container.querySelector('.cal-drawing')).toBeNull()
    expect(monthCalls()).toHaveLength(0)
  })
})
