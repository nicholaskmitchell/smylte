import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TodayView } from './TodayView'
import { AddMultipleModal } from './AddMultipleModal'
import { PlanRitual } from './PlanRitual'
import { ShutdownRitual } from './ShutdownRitual'
import { DataProvider } from '../data'
import { withPrompt } from '../test/back'
import { setCacheUser } from '../cache'
import { api, type DayEntry, type DayPlan, type Habit, type List, type Task } from '../api'

// The dialogs and sheets under Field notes: the lines that explain them are
// gone, and the warnings, the refusal and the truncation notice stay. The
// preset behaviour is the existing suites', and is not repeated here.
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

const habit = (o: Partial<Habit> = {}): Habit => ({
  id: 'hb1', title: 'Read', days: '', paused_at: null, position: 1,
  estimate_minutes: null, created_at: '2026-08-01T08:00:00.000Z', ...o,
})

const plan = (entries: DayEntry[] = []): DayPlan => ({
  day: today(), planned: true, entries,
  capacity_minutes: null, capacity: null,
  committed_at: null, committed_over_minutes: null, shutdown_at: null, reflection: null,
})

const offPlanTask = {
  uid: 't1', id: 't1', list: 'l1', summary: 'Sent the invoice', completed: true,
  completed_at: `${today()}T10:00:00`,
} as unknown as Task

beforeEach(() => {
  vi.clearAllMocks()
  setCacheUser('')
  localStorage.clear()
  // Before the render: `useFieldNotes` reads the attribute when it mounts.
  document.documentElement.setAttribute('data-surface', 'app')
})

afterEach(() => {
  document.documentElement.removeAttribute('data-surface')
})

describe('<AddMultipleModal> under Field notes', () => {
  const setup = () => render(
    <AddMultipleModal lists={[list]} defaultList="l1" onSubmit={vi.fn(async () => [])}
      onClose={vi.fn()} />)

  it('drops the paste line and the tooltip, and keeps the + row button named', () => {
    const { container } = setup()
    expect(screen.queryByText(/Paste a list of titles/)).not.toBeInTheDocument()
    expect(container.querySelector('[title]')).toBeNull()
    expect(screen.getByRole('button', { name: '+ row' })).toBeInTheDocument()
  })

  it('keeps the notice that says rows were dropped', async () => {
    const user = userEvent.setup()
    setup()
    // Pasting more lines than the cap holds is what raises the notice.
    const lines = Array.from({ length: 105 }, (_, i) => `Task ${i + 1}`).join('\n')
    await user.click(screen.getByLabelText('Title, row 1'))
    await user.paste(lines)
    expect(screen.getByText(/Only the first \d+ rows were kept\./)).toBeInTheDocument()
  })
})

describe('<PlanRitual> under Field notes', () => {
  const setup = () => render(
    <PlanRitual entries={[entry()]} suggestions={[]} capacity={null} planned={0}
      meetingMinutes={0} unestimated={0} committedAt={null}
      renderRow={(e) => <li key={e.entry_id}>{e.title}</li>} colorOf={() => null}
      onCapacity={vi.fn()} onAddTask={vi.fn()} onCommit={vi.fn()} onClose={vi.fn()} />)

  it('drops the capacity hint, and keeps the refusal', async () => {
    const user = userEvent.setup()
    setup()
    expect(screen.queryByText(/Applies to today only/)).not.toBeInTheDocument()
    const field = screen.getByLabelText('How long you are working today')
    await user.type(field, 'banana')
    await user.tab()
    expect(screen.getByRole('status')).toHaveTextContent(/^Try /)
  })

  it('drops the line above the day\'s rows', async () => {
    const user = userEvent.setup()
    setup()
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('Water the plants')).toBeInTheDocument()
    expect(screen.queryByText(/Tap an estimate to set it/)).not.toBeInTheDocument()
  })
})

describe('<ShutdownRitual> under Field notes', () => {
  const setup = (offPlan: Task[] = []) => render(
    <ShutdownRitual day={today()} entries={[entry()]} offPlan={offPlan} planned={0}
      done={0} doneMinutes={0} unestimated={0} shutdownAt={null} reflection={null}
      renderRow={(e) => <li key={e.entry_id}>{e.title}</li>} colorOf={() => null}
      isDone={() => false} titleOf={(e) => e.title ?? ''}
      onRoll={vi.fn()} onDrop={vi.fn()} onReflect={vi.fn()} onShutdown={vi.fn()}
      onClose={vi.fn()} />)

  it('draws the done mark of an off-plan task instead of typing a tick', () => {
    setup([offPlanTask])
    const mark = screen.getByRole('img', { name: 'Done' })
    expect(mark.querySelector('.check-ink')).not.toBeNull()
    expect(mark).not.toHaveTextContent('✓')
  })

  it('drops the carry-over line and the reflection line', async () => {
    const user = userEvent.setup()
    setup()
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.queryByText(/carries over by itself/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByLabelText('A note about today')).toBeInTheDocument()
    expect(screen.queryByText(/Shown when you look back at this day/)).not.toBeInTheDocument()
  })
})

describe('the habits sheet under Field notes', () => {
  it('drops the blurb, and keeps the warning on deleting a habit', async () => {
    m.lists.mockResolvedValue([list])
    m.tasks.mockResolvedValue([])
    m.calendars.mockResolvedValue([])
    m.events.mockResolvedValue([])
    m.openDay.mockResolvedValue(plan())
    m.day.mockImplementation(async () => plan())
    m.days.mockResolvedValue([])
    m.completedCounts.mockImplementation(async (from, to) => (
      { from, to, days: {}, total: 0 }))
    m.habits.mockResolvedValue([habit()])
    render(withPrompt(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TodayView rev={0} onExpire={vi.fn()} />
      </DataProvider>,
    ))
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'More actions' }))
    await user.click(await screen.findByRole('button', { name: 'Habits' }))
    const sheet = await screen.findByRole('dialog', { name: 'Habits' })

    await user.click(await within(sheet).findByRole('button', { name: 'Delete Read' }))
    expect(within(sheet).getByText(/Past days keep their entries/)).toBeInTheDocument()
    expect(within(sheet).queryByText(/Habits add a line to your day/)).not.toBeInTheDocument()
  })
})
