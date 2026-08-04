import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TasksView } from './TasksView'
import { api, AuthError, type List, type Task, type TasksViewMode } from '../api'

// Mock the whole API module: every method becomes a vi.fn() so the view never
// touches the network.
vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})

const m = vi.mocked(api)

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, tags: [],
  parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, href: '/l1/u1.ics', etag: '"1"', ...o,
})

const list: List = {
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#D9480F',
}

function setup(view: TasksViewMode = 'list') {
  const onExpire = vi.fn()
  render(
    <TasksView rev={0} onExpire={onExpire} view={view} onView={vi.fn()}
      sideCollapsed={false} onToggleSide={vi.fn()}
      hiddenLists={[]} onHiddenListsChange={vi.fn()}
      groups={[]} onGroupsChange={vi.fn()}
      collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
      showCompleted={false} />,
  )
  return { onExpire, user: userEvent.setup() }
}

/** Open the bulk composer and put a title in each of the first `n` rows. */
async function openBulk(user: ReturnType<typeof userEvent.setup>, titles: string[]) {
  await user.click(await screen.findByRole('button', { name: 'Add multiple' }))
  await screen.findByRole('dialog', { name: /add multiple tasks/i })
  for (const [i, t] of titles.entries()) {
    await user.type(screen.getByLabelText(`Title, row ${i + 1}`), t)
  }
}

const bulkAdd = (n: number) =>
  screen.getByRole('button', { name: `Add ${n} ${n === 1 ? 'task' : 'tasks'}` })

let errSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.clearAllMocks()
  m.lists.mockResolvedValue([list])
  m.tasks.mockResolvedValue([])
  // createMany logs non-auth failures rather than raising N toasts.
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => errSpy.mockRestore())

describe('<TasksView> "Add multiple"', () => {
  it('sits beside the quick-add in List view only', async () => {
    const { user } = setup()
    expect(await screen.findByRole('button', { name: 'Add multiple' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add multiple' }))
    expect(screen.getByRole('dialog', { name: /add multiple tasks/i })).toBeInTheDocument()
  })

  it('is absent from the day-column views, which have no quick-add', async () => {
    setup('day3')
    await screen.findByRole('button', { name: 'Today' })
    expect(screen.queryByRole('button', { name: 'Add multiple' })).not.toBeInTheDocument()
  })

  it('creates every row, then closes and paints the results', async () => {
    m.createTask.mockImplementation(async (listId, body) =>
      task({ uid: `u-${body.summary}`, list: listId, summary: String(body.summary) }))
    const { user } = setup()
    await openBulk(user, ['alpha', 'bravo'])
    await user.click(bulkAdd(2))

    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(2))
    expect(m.createTask).toHaveBeenNthCalledWith(1, 'l1',
      expect.objectContaining({ summary: 'alpha', client_id: expect.any(String) }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(await screen.findByText('alpha')).toBeInTheDocument()
    expect(screen.getByText('bravo')).toBeInTheDocument()
  })

  it('sends the batch one request at a time', async () => {
    let release: (t: Task) => void = () => {}
    m.createTask
      .mockImplementationOnce(() => new Promise<Task>((r) => { release = r }))
      .mockImplementation(async (listId, body) =>
        task({ uid: 'u2', list: listId, summary: String(body.summary) }))
    const { user } = setup()
    await openBulk(user, ['alpha', 'bravo'])
    await user.click(bulkAdd(2))

    // The second create must wait on the first — the server serializes writes
    // behind one lock, so firing them together would only queue there.
    expect(m.createTask).toHaveBeenCalledTimes(1)
    release(task({ uid: 'u1', summary: 'alpha' }))
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(2))
  })

  it('keeps the failed row in the modal and the successful one in the list', async () => {
    m.createTask
      .mockImplementationOnce(async () => task({ uid: 'u1', summary: 'alpha' }))
      .mockRejectedValueOnce(new Error('boom'))
    const { onExpire, user } = setup()
    await openBulk(user, ['alpha', 'bravo'])
    await user.click(bulkAdd(2))

    expect(await screen.findByRole('alert')).toHaveTextContent(/1 task couldn't be created/)
    expect(screen.getByRole('dialog', { name: /add multiple tasks/i })).toBeInTheDocument()
    expect(screen.getByLabelText('Title, row 1')).toHaveValue('bravo')
    // The one that landed is painted behind the modal; the one that didn't left
    // no stand-in behind.
    expect(screen.getByText('alpha')).toBeInTheDocument()
    expect(screen.queryByText('bravo')).not.toBeInTheDocument()
    expect(onExpire).not.toHaveBeenCalled()
  })

  it('stops the batch and logs out when the session expires mid-run', async () => {
    m.createTask.mockRejectedValue(new AuthError('unauthenticated'))
    const { onExpire, user } = setup()
    await openBulk(user, ['alpha', 'bravo'])
    await user.click(bulkAdd(2))

    await waitFor(() => expect(onExpire).toHaveBeenCalled())
    // Row 2 is never attempted, and neither stand-in is left painted.
    expect(m.createTask).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('alpha')).not.toBeInTheDocument()
  })

  it('shares its property controls with the task editor', async () => {
    // Both forms render from one FIELDS table, so the editor must offer the
    // same properties (bar the list, which PATCH can't move) under the same
    // accessible names the composer uses.
    m.tasks.mockResolvedValue([task({ summary: 'Ship it', priority_label: 'high' })])
    const { user } = setup()
    await user.click(await screen.findByText('Ship it'))
    const dialog = await screen.findByRole('dialog', { name: 'Task' })
    for (const name of ['Due date', 'Due time', 'Start date', 'Priority', 'Tags']) {
      expect(within(dialog).getByLabelText(name)).toBeInTheDocument()
    }
    expect(within(dialog).getByLabelText('Title')).toHaveValue('Ship it')
    expect(within(dialog).getByLabelText('Priority')).toHaveValue('high')
    // The list picker belongs to the composer alone.
    expect(within(dialog).queryByLabelText('List')).not.toBeInTheDocument()
  })

  it('saves a start date, which nothing exposed before', async () => {
    m.tasks.mockResolvedValue([task({ summary: 'Ship it' })])
    m.patchTask.mockResolvedValue(task({ summary: 'Ship it', start: '2026-08-09' }))
    const { user } = setup()
    await user.click(await screen.findByText('Ship it'))
    await user.type(screen.getByLabelText('Start date'), '2026-08-09')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    expect(m.patchTask).toHaveBeenCalledWith('l1', 'u1',
      expect.objectContaining({ summary: 'Ship it', start: '2026-08-09' }))
  })

  it('still round-trips an all-day due as a bare date and a timed one with a T', async () => {
    m.tasks.mockResolvedValue([task({ summary: 'Ship it', due: '2026-08-10', due_is_date: true })])
    m.patchTask.mockResolvedValue(task())
    const { user } = setup()
    await user.click(await screen.findByText('Ship it'))
    expect(screen.getByLabelText('Due date')).toHaveValue('2026-08-10')
    await user.type(screen.getByLabelText('Due time'), '09:30')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    expect(m.patchTask.mock.calls[0][2]).toMatchObject({ due: '2026-08-10T09:30' })
  })

  it('deletes from the editor', async () => {
    m.tasks.mockResolvedValue([task({ summary: 'Ship it' })])
    m.deleteTask.mockResolvedValue(null)
    const { user } = setup()
    await user.click(await screen.findByText('Ship it'))
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(m.deleteTask).toHaveBeenCalledWith('l1', 'u1'))
  })

  it('leaves the plain quick-add sending a minimal body', async () => {
    m.createTask.mockResolvedValue(task({ summary: 'solo' }))
    const { user } = setup()
    await user.type(await screen.findByPlaceholderText('Add a task…'), 'solo{Enter}')
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(1))
    // The widened create path must not start sending empty notes/tags/priority.
    expect(m.createTask.mock.calls[0][1]).toEqual({ summary: 'solo', client_id: expect.any(String) })
  })
})
