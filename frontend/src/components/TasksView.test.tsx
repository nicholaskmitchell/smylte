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

/** Quick-add's "New…" button opens the single-task form. */
async function openAdd(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'New…' }))
  return screen.findByRole('dialog', { name: 'Add task' })
}

/** …and "Add multiple" inside it hands off to the composer. */
async function openBulk(user: ReturnType<typeof userEvent.setup>, titles: string[]) {
  await openAdd(user)
  await user.click(screen.getByRole('button', { name: 'Add multiple' }))
  await screen.findByRole('dialog', { name: /add multiple tasks/i })
  for (const [i, t] of titles.entries()) {
    await user.clear(screen.getByLabelText(`Title, row ${i + 1}`))
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

describe('<TasksView> creating', () => {
  it('opens the single-task form from quick-add, carrying what was typed', async () => {
    const { user } = setup()
    await user.type(await screen.findByPlaceholderText('Add a task…'), 'buy milk')
    const dialog = await openAdd(user)
    expect(within(dialog).getByLabelText('Title')).toHaveValue('buy milk')
    // The title moved into the form rather than being left behind in the bar.
    expect(screen.getByPlaceholderText('Add a task…')).toHaveValue('')
    // Creating offers the list picker and the route to bulk, not Delete.
    expect(within(dialog).getByLabelText('List')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Add multiple' })).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })

  it('keeps Enter as the fast path — straight to a task, no modal', async () => {
    m.createTask.mockResolvedValue(task({ summary: 'solo' }))
    const { user } = setup()
    await user.type(await screen.findByPlaceholderText('Add a task…'), 'solo{Enter}')
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(1))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('opens the form from an empty bar instead of doing nothing', async () => {
    // The original report: tapping the bar's button with nothing typed was a
    // silent no-op, so the button read as broken. It must always do something.
    const { user } = setup()
    await openAdd(user)
    expect(screen.getByRole('dialog', { name: 'Add task' })).toBeInTheDocument()
    expect(m.createTask).not.toHaveBeenCalled()
    // …and creating is refused until the form has a title.
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled()
  })

  it('creates from the single-task form with its properties', async () => {
    m.createTask.mockResolvedValue(task({ summary: 'with props' }))
    const { user } = setup()
    await user.type(await screen.findByPlaceholderText('Add a task…'), 'with props')
    const dialog = await openAdd(user)
    await user.selectOptions(screen.getByLabelText('Priority'), 'high')
    await user.type(screen.getByLabelText('Due date'), '2026-08-10')
    await user.type(screen.getByLabelText('Tags'), 'a, b')
    await user.click(within(dialog).getByRole('button', { name: 'Add' }))

    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(1))
    expect(m.createTask.mock.calls[0][1]).toEqual({
      summary: 'with props', priority: 'high', due: '2026-08-10', tags: ['a', 'b'],
      client_id: expect.any(String),
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('hands the typed title on to the bulk composer', async () => {
    const { user } = setup()
    await user.type(await screen.findByPlaceholderText('Add a task…'), 'carried over')
    await openAdd(user)
    await user.click(screen.getByRole('button', { name: 'Add multiple' }))
    const bulk = await screen.findByRole('dialog', { name: /add multiple tasks/i })
    expect(within(bulk).getByLabelText('Title, row 1')).toHaveValue('carried over')
    // Only one dialog at a time — the single form gave way to the composer.
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
  })

  it('has no quick-add at all in the day-column views', async () => {
    setup('day3')
    await screen.findByRole('button', { name: 'Today' })
    expect(screen.queryByPlaceholderText('Add a task…')).not.toBeInTheDocument()
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
