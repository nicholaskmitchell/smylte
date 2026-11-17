import { useState } from 'react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TasksView } from './TasksView'
import { DataProvider } from '../data'
import { setCacheUser } from '../cache'
import { api, type List, type Task, type TasksViewMode } from '../api'

// Tasks under Field notes: no tooltips, calm rows, and an editor that carries
// "Add subtask" for a touchscreen, whose rows show no tools. The preset
// behaviour is TasksView.test.tsx's, and is not repeated here.
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

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, parked: false, parked_at: null,
  original_due: null, original_due_is_date: false, original_due_moved: false,
  priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [],
  parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const list: List = {
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#D9480F',
}
const personal: List = { ...list, id: 'l2', href: '/l2/', name: 'Personal' }

function setup(view: TasksViewMode = 'list', showCompleted = false) {
  const Harness = () => {
    const [collapsed, setCollapsed] = useState<string[]>([])
    return (
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TasksView onExpire={vi.fn()} view={view} onView={vi.fn()}
          sideCollapsed={false} onToggleSide={vi.fn()}
          hiddenLists={[]} onHiddenListsChange={vi.fn()}
          groups={[]} onGroupsChange={vi.fn()}
          collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
          collapsedTasks={collapsed} onCollapsedTasksChange={setCollapsed}
          showCompleted={showCompleted} />
      </DataProvider>
    )
  }
  const { container } = render(<Harness />)
  return { container, user: userEvent.setup() }
}

/** The Tasks pane itself. The sidebar beside it is its own screen. */
const pane = (container: HTMLElement) => container.querySelector('.content') as HTMLElement

const parent = task({ uid: 'p1', summary: 'Trip planning', children: ['c1'] })
const child = task({ uid: 'c1', summary: 'Book flight', parent: 'p1' })

beforeEach(() => {
  vi.clearAllMocks()
  setCacheUser('')
  localStorage.clear()
  // Before the render: `useFieldNotes` reads the attribute when it mounts.
  document.documentElement.setAttribute('data-surface', 'app')
  m.lists.mockResolvedValue([list, personal])
  m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [parent, child] : []))
})

afterEach(() => {
  document.documentElement.removeAttribute('data-surface')
})

describe('<TasksView> under Field notes', () => {
  it('has no tooltips in the list view', async () => {
    const { container } = setup()
    await screen.findByText('Book flight')
    // The parent's fold arrow, both ticks, "+ sub" and "del", the list picker
    // and New… all carried one.
    expect(screen.getByRole('button', { name: 'Hide subtasks of Trip planning' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'List for the new task' })).toBeInTheDocument()
    expect(pane(container).querySelectorAll('[title]')).toHaveLength(0)
  })

  it('has no tooltips in the day view', async () => {
    m.tasks.mockImplementation(async (id: string) => (id === 'l1'
      ? [task({ uid: 'd1', summary: 'Due today', due: today() })]
      : []))
    const { container } = setup('day3')
    await screen.findByText('Due today')
    expect(screen.getByRole('button', { name: 'Earlier' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Later' })).toBeInTheDocument()
    expect(pane(container).querySelectorAll('[title]')).toHaveLength(0)
  })

  it('names the row tools and the list picker without a tooltip', async () => {
    setup()
    const row = (await screen.findByText('Book flight')).closest('.task') as HTMLElement
    expect(within(row).getByRole('button', { name: 'Add subtask' })).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Delete' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'List for the new task' })).toBeInTheDocument()
  })

  it('strikes a won\'t-do row', async () => {
    // A won't-do row is `.done`, which Field notes draws struck rather than
    // lined through, so it needs the drawn strike as a completed one does.
    const declined = task({ uid: 'x1', summary: 'Skip this', cancelled: true, status: 'CANCELLED',
      due: today() })
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [declined] : []))
    const { container } = setup('list', true)
    await screen.findByText('Skip this')
    expect(pane(container).querySelector('.task-title .strike-ink')).toHaveClass('on')
  })

  it('strikes a won\'t-do day card', async () => {
    const declined = task({ uid: 'x1', summary: 'Skip this', cancelled: true, status: 'CANCELLED',
      due: today() })
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [declined] : []))
    const { container } = setup('day3', true)
    await screen.findByText('Skip this')
    expect(pane(container).querySelector('.day-card-title .strike-ink')).toHaveClass('on')
  })

  it('adds a subtask from the editor, under the row it was opened from', async () => {
    m.tasks.mockImplementation(async (id: string) => (id === 'l1'
      ? [task({ uid: 'a1', summary: 'Alpha' }), task({ uid: 'b1', summary: 'Bravo' })]
      : []))
    const { user } = setup()
    await user.click(await screen.findByText('Bravo'))
    const dialog = await screen.findByRole('dialog', { name: 'Task' })
    await user.click(within(dialog).getByRole('button', { name: 'Add subtask' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    const field = await screen.findByPlaceholderText('Subtask')
    const group = field.closest('.task-drag') as HTMLElement
    expect(within(group).getByText('Bravo')).toBeInTheDocument()
    expect(within(group).queryByText('Alpha')).not.toBeInTheDocument()
    await waitFor(() => expect(field).toHaveFocus())
  })

  it('says nothing in the editor about moving or parking', async () => {
    const { user } = setup()
    await user.click(await screen.findByText('Trip planning'))
    const dialog = await screen.findByRole('dialog', { name: 'Task' })
    await user.selectOptions(within(dialog).getByLabelText('List'), 'l2')
    // The controls stay; only the sentences about them go.
    expect(within(dialog).getByRole('button', { name: 'Park it' })).toBeInTheDocument()
    expect(within(dialog).queryByText(/Its subtasks move with it/)).not.toBeInTheDocument()
    expect(within(dialog).queryByText(/Hides it from your lists/)).not.toBeInTheDocument()
  })
})
