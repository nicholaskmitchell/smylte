import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TodayView } from './TodayView'
import { DataProvider } from '../data'
import { withPrompt } from '../test/back'
import { setCacheUser } from '../cache'
import { api, type DayEntry, type DayPlan, type List } from '../api'

// Today under Field notes, the design that calms the screen. The preset
// behaviour is TodayView.test.tsx's, and is not repeated here.
vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})

const m = vi.mocked(api)

const pad = (n: number) => String(n).padStart(2, '0')
const today = () => {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

const list: List = {
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 1, task_count: 1, event_count: 0, total: 1, color: '#D9480F',
}

const entry = (o: Partial<DayEntry> = {}): DayEntry => ({
  entry_id: 'e1', day: today(), kind: 'note', list: null, uid: null,
  title: 'Water the plants', source: 'user', position: 1,
  done_at: null, dropped_at: null, habit_id: null, estimate_minutes: null,
  rolled_to: null, worked_seconds: null, capped: null,
  created_at: '2026-08-21T08:00:00.000Z', ...o,
})

const occurrence = (o: Partial<DayEntry> = {}): DayEntry => entry({
  entry_id: 'h-today', kind: 'habit', source: 'habit', habit_id: 'hb1',
  title: 'Read', position: 0, ...o,
})

const plan = (entries: DayEntry[] = [], o: Partial<DayPlan> = {}): DayPlan => ({
  day: today(), planned: true, entries,
  capacity_minutes: null, capacity: null,
  committed_at: null, committed_over_minutes: null, shutdown_at: null, reflection: null, ...o,
})

function setup() {
  render(withPrompt(
    <DataProvider rev={0} onExpire={vi.fn()}>
      <TodayView rev={0} onExpire={vi.fn()} />
    </DataProvider>,
  ))
  return userEvent.setup()
}

beforeEach(() => {
  vi.clearAllMocks()
  setCacheUser('')
  localStorage.clear()
  // Before the render: `useFieldNotes` reads the attribute when it mounts.
  document.documentElement.setAttribute('data-surface', 'app')
  m.lists.mockResolvedValue([list])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.openDay.mockResolvedValue(plan())
  m.day.mockImplementation(async (d) => plan([], { day: d }))
  m.days.mockResolvedValue([])
  m.completedCounts.mockImplementation(async (from, to) => (
    { from, to, days: {}, total: 0 }))
  m.habits.mockResolvedValue([])
})

afterEach(() => {
  document.documentElement.removeAttribute('data-surface')
})

/** Field notes' focus card repeats the first open row's title, so a row is read
 *  through the day's own list rather than through the text alone. */
const dayList = () => screen.findByRole('list', { name: 'The day' })
const titleIn = (title: string) =>
  within(screen.getByRole('list', { name: 'The day' })).getByText(title)
const rowOf = (title: string) => titleIn(title).closest('li') as HTMLElement

describe('<TodayView> under Field notes', () => {
  it('keeps one control in the header and moves Review into the menu', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    const user = setup()
    await dayList()

    expect(screen.queryByRole('button', { name: 'Review' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'More actions' }))
    const review = await screen.findByRole('button', { name: 'Review' })
    const shutDown = screen.getByRole('button', { name: 'Shut down' })
    // Before Shut down, in document order.
    expect(review.compareDocumentPosition(shutDown) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy()

    await user.click(review)
    // The menu closes under the pressed item; its layer gives focus back to the
    // ⋯ that opened it (layers.ts) rather than letting it fall to the page.
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'More actions' }))
    // Review is a render-level switch, so the same item now offers the way back.
    await user.click(screen.getByRole('button', { name: 'More actions' }))
    expect(await screen.findByRole('button', { name: 'Plan' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Review' })).not.toBeInTheDocument()
  })

  it('nudges with Plan my day alone when the day has no capacity', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    setup()
    await dayList()

    expect(screen.getByRole('button', { name: 'Plan my day' })).toBeInTheDocument()
    expect(screen.queryByText('Today isn’t planned yet.')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Not now' })).not.toBeInTheDocument()
  })

  it('names the day only when a Habits section is above it, and drops the habits hint', async () => {
    m.openDay.mockResolvedValue(plan([entry({ title: 'Water the plants' })]))
    setup()
    await dayList()

    // The list keeps its accessible name; only the visible label goes.
    expect(screen.queryByText('The day')).not.toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'The day' })).toBeInTheDocument()
    expect(screen.queryByText(/Habits add a line to your day/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Set one up' })).not.toBeInTheDocument()
  })

  it('shows the day label under a Habits section', async () => {
    m.openDay.mockResolvedValue(plan([occurrence(), entry({ title: 'Water the plants' })]))
    setup()
    await dayList()

    expect(screen.getByText('The day')).toBeInTheDocument()
  })

  it('shows one row\'s tools at a time, and puts them away on a press elsewhere', async () => {
    m.openDay.mockResolvedValue(plan([
      entry({ entry_id: 'a', title: 'Water the plants' }),
      entry({ entry_id: 'b', title: 'Ring the bank', position: 2 }),
    ]))
    const user = setup()
    await dayList()
    expect(rowOf('Water the plants')).not.toHaveAttribute('data-tools')

    await user.click(titleIn('Water the plants'))
    expect(rowOf('Water the plants')).toHaveAttribute('data-tools')
    expect(rowOf('Ring the bank')).not.toHaveAttribute('data-tools')

    await user.click(titleIn('Ring the bank'))
    expect(rowOf('Ring the bank')).toHaveAttribute('data-tools')
    expect(rowOf('Water the plants')).not.toHaveAttribute('data-tools')

    fireEvent.pointerDown(document.body)
    await waitFor(() => expect(rowOf('Ring the bank')).not.toHaveAttribute('data-tools'))
  })
})
