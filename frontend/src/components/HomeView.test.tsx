import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HomeView } from './HomeView'
import { api } from '../api'
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
  percent_complete: null, due: null, due_is_date: true, start: null, tags: [],
  parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, href: '/l1/u1.ics', etag: '"1"', ...o,
})

const list = { id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 1, task_count: 1, event_count: 0, total: 1, color: '#D9480F' }

/** Render with a controlled layout so assertions can watch it change. */
function setup(initial: DashboardModule[] = DEFAULT_LAYOUT) {
  const onLayoutChange = vi.fn()
  render(<HomeView rev={0} onExpire={vi.fn()} layout={initial} onLayoutChange={onLayoutChange} />)
  return { onLayoutChange }
}

const today = () => {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

beforeEach(() => {
  vi.clearAllMocks()
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
    // No calendar or scheduling module is on the board, so those endpoints
    // should never be touched.
    expect(m.calendars).not.toHaveBeenCalled()
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
    expect(m.createTask).toHaveBeenCalledWith('l1', { summary: 'New thing' })
  })
})
