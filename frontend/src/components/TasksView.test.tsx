import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

function setup(view: TasksViewMode = 'list', showCompleted = false) {
  const onExpire = vi.fn()
  const ui = (rev: number) => (
    <TasksView rev={rev} onExpire={onExpire} view={view} onView={vi.fn()}
      sideCollapsed={false} onToggleSide={vi.fn()}
      hiddenLists={[]} onHiddenListsChange={vi.fn()}
      groups={[]} onGroupsChange={vi.fn()}
      collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
      showCompleted={showCompleted} />
  )
  const { rerender } = render(ui(0))
  // Bumping `rev` is how the app tells the view a server-side change landed, so
  // it is also how a test replays one without reaching for the SSE mock.
  return { onExpire, user: userEvent.setup(), bumpRev: (rev: number) => rerender(ui(rev)) }
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
    expect(m.patchTask).toHaveBeenCalledWith('l1', 'u1', { start: '2026-08-09' })
  })

  it('sends only what changed, so a rename cannot rewrite other properties', async () => {
    // Every value in this form has round-tripped through a lossy representation,
    // so resending an unchanged field would rewrite a property another CalDAV
    // client authored.
    m.tasks.mockResolvedValue([task({
      summary: 'Ship it', due: '2026-08-10T09:30:00+02:00', due_is_date: false,
      priority: 3, priority_label: 'high', tags: ['Home,Garden'],
    })])
    m.patchTask.mockResolvedValue(task({ summary: 'Ship it now' }))
    const { user } = setup()
    await user.click(await screen.findByText('Ship it'))
    const title = screen.getByLabelText('Title')
    await user.clear(title)
    await user.type(title, 'Ship it now')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    expect(m.patchTask).toHaveBeenCalledWith('l1', 'u1', { summary: 'Ship it now' })
  })

  it('keeps a timed start editable instead of flattening it to a date', async () => {
    m.tasks.mockResolvedValue([task({ summary: 'Ship it', start: '2026-08-09T14:30:00' })])
    m.patchTask.mockResolvedValue(task({ summary: 'Ship it' }))
    const { user } = setup()
    await user.click(await screen.findByText('Ship it'))
    expect((screen.getByLabelText('Start time') as HTMLInputElement).value).toBe('14:30')

    // Touch only the date; the time rides along instead of being dropped.
    await user.clear(screen.getByLabelText('Start date'))
    await user.type(screen.getByLabelText('Start date'), '2026-08-11')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    expect(m.patchTask).toHaveBeenCalledWith('l1', 'u1', { start: '2026-08-11T14:30' })
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

// ── a retry must replay the create, not author a second task ────────────────
// `client_id` is the idempotency slug the server derives the CalDAV resource
// name from. Minting a fresh one per attempt meant a create whose response was
// lost on the way back — indistinguishable from one that never landed, and the
// exact failure the composer invites you to retry — arrived twice.

describe('<TasksView> retrying a bulk create', () => {
  it('replays the same client_id for a row that failed', async () => {
    m.createTask
      .mockImplementationOnce(async () => task({ uid: 'u1', summary: 'alpha' }))
      .mockRejectedValueOnce(new Error('boom'))
    const { user } = setup()
    await openBulk(user, ['alpha', 'bravo'])
    await user.click(bulkAdd(2))
    await screen.findByRole('alert')

    const firstTry = m.createTask.mock.calls[1][1].client_id
    m.createTask.mockClear()
    m.createTask.mockImplementation(async () => task({ uid: 'u2', summary: 'bravo' }))
    await user.click(bulkAdd(1))

    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(1))
    expect(m.createTask.mock.calls[0][1].client_id).toBe(firstTry)
  })

  it('mints a new client_id when the row is retitled before the retry', async () => {
    // A different title is a different task, and the server answers a replayed
    // slug by confirming the resource already written under it — which would
    // silently discard the edit.
    m.createTask.mockRejectedValueOnce(new Error('boom'))
    const { user } = setup()
    await openBulk(user, ['alpha'])
    await user.click(bulkAdd(1))
    await screen.findByRole('alert')

    const firstTry = m.createTask.mock.calls[0][1].client_id
    m.createTask.mockClear()
    m.createTask.mockImplementation(async () => task({ uid: 'u2', summary: 'alpha fixed' }))
    await user.type(screen.getByLabelText('Title, row 1'), ' fixed')
    await user.click(bulkAdd(1))

    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(1))
    expect(m.createTask.mock.calls[0][1].client_id).not.toBe(firstTry)
  })
})

// ── a subtask must reach the DOM even when its parent row does not ──────────
// A subtask renders only underneath its own parent. Anything whose parent is
// not rendered was absent from the List view entirely — invisible, and so
// uncompletable, uneditable and undeletable — while the sidebar count still
// included it.

describe('<TasksView> orphaned subtasks', () => {
  it('shows an open subtask whose parent is completed and hidden', async () => {
    // The default: showCompleted is off, so the parent is not rendered.
    m.tasks.mockResolvedValue([
      task({ uid: 'p1', summary: 'Trip planning', completed: true, status: 'COMPLETED' }),
      task({ uid: 'c1', summary: 'Book flight', parent: 'p1' }),
    ])
    setup()
    expect(await screen.findByText('Book flight')).toBeInTheDocument()
    expect(screen.queryByText('Trip planning')).not.toBeInTheDocument()
  })

  it('shows a subtask whose parent does not exist at all', async () => {
    // Another client can write RELATED-TO pointing at a deleted parent, or at a
    // task in a different list; `parent` is that raw UID with no existence check.
    m.tasks.mockResolvedValue([task({ uid: 'c1', summary: 'Orphan', parent: 'ghost' })])
    setup()
    expect(await screen.findByText('Orphan')).toBeInTheDocument()
  })

  it('still nests a subtask under a parent that is rendered', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: 'p1', summary: 'Trip planning' }),
      task({ uid: 'c1', summary: 'Book flight', parent: 'p1' }),
    ])
    setup()
    await screen.findByText('Trip planning')
    // Rendered once, as a child — not promoted to a second top-level row.
    expect(screen.getAllByText('Book flight')).toHaveLength(1)
    expect(screen.getByText('Book flight').closest('.task')).toHaveClass('sub')
  })

  it('nests it under a completed parent once completed tasks are shown', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: 'p1', summary: 'Trip planning', completed: true, status: 'COMPLETED' }),
      task({ uid: 'c1', summary: 'Book flight', parent: 'p1' }),
    ])
    setup('list', true)
    await screen.findByText('Trip planning')
    expect(screen.getAllByText('Book flight')).toHaveLength(1)
    expect(screen.getByText('Book flight').closest('.task')).toHaveClass('sub')
  })
})

// ── a write issued against a row whose create is still in flight ────────────
// The stand-in used to wear the bare client_id while the task the server was
// actually writing carried `${client_id}@tasksd`. Every write aimed at the row
// in that window therefore named a resource that did not exist. For a subtask
// that meant a RELATED-TO pointing at nothing — persisted to CalDAV, so the
// child came back as its own top-level task and no reload ever fixed it.

describe('<TasksView> creates still in flight', () => {
  /** A server that answers like the real one: uid derived from the slug sent. */
  const echoServer = () =>
    m.createTask.mockImplementation(async (_l: string, b: Record<string, unknown>) =>
      task({
        uid: `${b.client_id as string}@tasksd`,
        list: 'l1',
        summary: b.summary as string,
        parent: (b.parent as string) ?? null,
      }))

  /** A parent whose response stays open until the returned `release` is called.
   *
   *  Holding it is the whole point: let the create settle first and the row is
   *  already wearing its server uid by the time the subtask is typed, so the
   *  window the bug lived in is never entered and the test passes against the
   *  broken code too. */
  const heldParent = () => {
    const held = { cid: '', release: () => {} }
    m.createTask.mockImplementationOnce((_l: string, b: Record<string, unknown>) =>
      new Promise<Task>((res) => {
        held.cid = b.client_id as string
        held.release = () => res(task({ uid: `${held.cid}@tasksd`, list: 'l1', summary: 'trip' }))
      }))
    echoServer()
    return held
  }

  /** Quick-add a top-level task and add a subtask to the row it paints. */
  const addParentThenSub = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.type(await screen.findByPlaceholderText('Add a task…'), 'trip{Enter}')
    await user.click(await screen.findByTitle('Add subtask'))
    await user.type(await screen.findByPlaceholderText('Subtask'), 'book flight{Enter}')
  }

  it('sends the uid the server will derive, not the create id', async () => {
    const parent = heldParent()
    const { user } = setup()
    await addParentThenSub(user)
    parent.release()
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(2))
    // The assertion is about the relationship between the two requests, so the
    // id is read back off the first rather than guessed.
    expect(m.createTask.mock.calls[1][1].parent).toBe(`${parent.cid}@tasksd`)
  })

  it('keeps the subtask nested once both creates settle', async () => {
    const parent = heldParent()
    const { user } = setup()
    await addParentThenSub(user)
    parent.release()
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(2))
    // The reported symptom, exactly: the child became its own top-level task.
    // Note this holds by two routes — the uid sent is right, and the legacy
    // heal would rescue the display even if it weren't. The wire value itself
    // is pinned by the test above, which is the one that matters to the other
    // CalDAV clients reading the same collection.
    await waitFor(() =>
      expect(screen.getByText('book flight').closest('.task')).toHaveClass('sub'))
    expect(screen.getAllByText('book flight')).toHaveLength(1)
    expect(document.querySelectorAll('.task:not(.sub)')).toHaveLength(1)
  })

  it('orders the subtask behind its parent rather than racing it', async () => {
    const parent = heldParent()
    const { user } = setup()
    await addParentThenSub(user)
    // Both rows are painted, but only the parent's request has gone out — a
    // subtask sent now would reach a server that has never heard of its parent.
    expect(await screen.findByText('book flight')).toBeInTheDocument()
    expect(m.createTask).toHaveBeenCalledTimes(1)
    parent.release()
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(2))
  })

  it('drops a pending subtask when its parent create fails, unsent', async () => {
    let rejectParent: (e: Error) => void = () => {}
    m.createTask.mockImplementationOnce(
      () => new Promise<Task>((_res, rej) => { rejectParent = rej }))
    echoServer()
    const { user } = setup()
    await addParentThenSub(user)
    expect(await screen.findByText('book flight')).toBeInTheDocument()
    rejectParent(new Error('boom'))
    // The child would otherwise have been written against a parent uid that
    // will never exist — orphaned on the server for good.
    await waitFor(() => expect(screen.queryByText('book flight')).not.toBeInTheDocument())
    expect(screen.queryByText('trip')).not.toBeInTheDocument()
    expect(m.createTask).toHaveBeenCalledTimes(1)
  })

  it('completes a row whose create has not settled, by its real uid', async () => {
    // Not just subtasks: toggle, delete and edit all send the rendered uid too.
    let release: (t: Task) => void = () => {}
    let cid = ''
    m.createTask.mockImplementation((_l: string, b: Record<string, unknown>) =>
      new Promise<Task>((res) => {
        cid = b.client_id as string
        release = () => res(task({ uid: `${cid}@tasksd`, summary: 'solo' }))
      }))
    m.complete.mockResolvedValue(task({ uid: 'ignored', completed: true }))
    const { user } = setup()
    await user.type(await screen.findByPlaceholderText('Add a task…'), 'solo{Enter}')
    await user.click(await screen.findByTitle('Toggle complete'))
    await waitFor(() => expect(m.complete).toHaveBeenCalledTimes(1))
    expect(m.complete.mock.calls[0][1]).toBe(`${cid}@tasksd`)
    release(task())
  })

  it('shows one row when a refetch lands between the paint and the settle', async () => {
    // The SSE bump can bring the real task in while the create is still open.
    // Both now share a uid, so a naive settle would leave two identical rows.
    let release: (t: Task) => void = () => {}
    let landed: Task | null = null
    m.createTask.mockImplementation((_l: string, b: Record<string, unknown>) =>
      new Promise<Task>((res) => {
        landed = task({ uid: `${b.client_id as string}@tasksd`, summary: 'solo' })
        release = () => res(landed!)
      }))
    const { user } = setup()
    await user.type(await screen.findByPlaceholderText('Add a task…'), 'solo{Enter}')
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(1))
    m.tasks.mockResolvedValue([landed!])
    release(landed!)
    await waitFor(() => expect(screen.getAllByText('solo')).toHaveLength(1))
  })
})

// ── subtask progress, counted from the tasks on hand ────────────────────────
// The badge used to render the server's child_count, a snapshot of the last
// refetch — so it stayed stale until an SSE bump landed a whole refetch later,
// while the nesting beside it (computed locally) had already moved.

describe('<TasksView> subtask progress', () => {
  const parent = task({ uid: 'p1', summary: 'Trip planning' })

  it('counts the children on hand, not the DTO field', async () => {
    // The server field is deliberately wrong here: the local count must win.
    m.tasks.mockResolvedValue([
      task({ ...parent, child_count: 99, completed_child_count: 99 }),
      task({ uid: 'c1', summary: 'Book flight', parent: 'p1' }),
      task({ uid: 'c2', summary: 'Pack', parent: 'p1', completed: true, status: 'COMPLETED' }),
    ])
    setup()
    expect(await screen.findByText('1/2')).toBeInTheDocument()
  })

  it('moves the moment a subtask is added, with no refetch', async () => {
    m.tasks.mockResolvedValue([parent])
    m.createTask.mockImplementation(async (_l: string, b: Record<string, unknown>) =>
      task({ uid: `${b.client_id as string}@tasksd`, summary: 'Book flight', parent: 'p1' }))
    const { user } = setup()
    await screen.findByText('Trip planning')
    const fetches = m.tasks.mock.calls.length
    await user.click(screen.getByTitle('Add subtask'))
    await user.type(await screen.findByPlaceholderText('Subtask'), 'Book flight{Enter}')
    expect(await screen.findByText('0/1')).toBeInTheDocument()
    expect(m.tasks).toHaveBeenCalledTimes(fetches)
  })

  it('moves when a subtask is ticked', async () => {
    const child = task({ uid: 'c1', summary: 'Book flight', parent: 'p1' })
    m.tasks.mockResolvedValue([parent, child])
    m.complete.mockResolvedValue({ ...child, completed: true, status: 'COMPLETED' })
    const { user } = setup()
    expect(await screen.findByText('0/1')).toBeInTheDocument()
    const row = screen.getByText('Book flight').closest('.task')!
    await user.click(within(row as HTMLElement).getByTitle('Toggle complete'))
    expect(await screen.findByText('1/1')).toBeInTheDocument()
  })

  it('drops the badge when the last subtask is deleted', async () => {
    const child = task({ uid: 'c1', summary: 'Book flight', parent: 'p1' })
    m.tasks.mockResolvedValue([parent, child])
    m.deleteTask.mockResolvedValue(null)
    const { user } = setup()
    expect(await screen.findByText('0/1')).toBeInTheDocument()
    const row = screen.getByText('Book flight').closest('.task')!
    await user.click(within(row as HTMLElement).getByTitle('Delete'))
    await waitFor(() => expect(screen.queryByText('0/1')).not.toBeInTheDocument())
  })

  it('ignores a child pointing across lists, as the server does', async () => {
    // child_count is a join within one collection, so a RELATED-TO reaching
    // into another list counts for nothing there. Counting it here would put a
    // number on the row that no other client — and no reload — agrees with.
    m.lists.mockResolvedValue([list, { ...list, id: 'l2', href: '/l2/', name: 'Personal' }])
    m.tasks.mockImplementation(async (id: string) =>
      id === 'l1'
        ? [parent]
        : [task({ uid: 'c1', list: 'l2', summary: 'Book flight', parent: 'p1' })])
    setup()
    await screen.findByText('Trip planning')
    expect(screen.queryByText('0/1')).not.toBeInTheDocument()
    // …and it stands on its own rather than being hidden under a parent that
    // is not really its parent.
    expect(screen.getByText('Book flight').closest('.task')).not.toHaveClass('sub')
  })
})

// ── subtasks written before the uid contract was honoured ───────────────────

describe('<TasksView> legacy orphans', () => {
  const cid = 'a'.repeat(32)

  it('repairs the stored pointer, not just the display', async () => {
    // The nesting below is cosmetic and local; the RELATED-TO on the wire is
    // what the server counts and what Tasks.org and jtx Board read.
    m.tasks.mockResolvedValue([
      task({ uid: `${cid}@tasksd`, summary: 'Trip planning' }),
      task({ uid: 'c1', summary: 'Book flight', parent: cid }),
    ])
    m.patchTask.mockResolvedValue(task({ uid: 'c1', summary: 'Book flight', parent: `${cid}@tasksd` }))
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {})
    setup()
    await waitFor(() => expect(m.patchTask).toHaveBeenCalledTimes(1))
    expect(m.patchTask).toHaveBeenCalledWith('l1', 'c1', { parent: `${cid}@tasksd` })
    infoSpy.mockRestore()
  })

  it('repairs a row once, even across refetches', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: `${cid}@tasksd`, summary: 'Trip planning' }),
      task({ uid: 'c1', summary: 'Book flight', parent: cid }),
    ])
    // The write fails, so the server keeps serving the broken row. Retrying it
    // on every refetch would be an endless loop of failing PATCHes.
    m.patchTask.mockRejectedValue(new Error('boom'))
    const infoSpy = vi.spyOn(console, 'info').mockImplementation(() => {})
    const { bumpRev } = setup()
    await waitFor(() => expect(m.patchTask).toHaveBeenCalledTimes(1))
    const fetches = m.tasks.mock.calls.length
    bumpRev(1)
    await waitFor(() => expect(m.tasks.mock.calls.length).toBeGreaterThan(fetches))
    expect(m.patchTask).toHaveBeenCalledTimes(1)
    infoSpy.mockRestore()
  })

  it('leaves a parent in another list alone', async () => {
    // child_count is a per-collection join, so a cross-list match is not the
    // signature of this bug and must not be rewritten.
    m.lists.mockResolvedValue([list, { ...list, id: 'l2', href: '/l2/', name: 'Personal' }])
    m.tasks.mockImplementation(async (id: string) =>
      id === 'l1'
        ? [task({ uid: `${cid}@tasksd`, summary: 'Trip planning' })]
        : [task({ uid: 'c1', list: 'l2', summary: 'Book flight', parent: cid })])
    setup()
    await screen.findByText('Trip planning')
    expect(m.patchTask).not.toHaveBeenCalled()
  })

  it('nests a subtask whose parent is the bare create id', async () => {
    m.tasks.mockResolvedValue([
      task({ uid: `${cid}@tasksd`, summary: 'Trip planning' }),
      task({ uid: 'c1', summary: 'Book flight', parent: cid }),
    ])
    setup()
    await screen.findByText('Trip planning')
    expect(screen.getByText('Book flight').closest('.task')).toHaveClass('sub')
    expect(await screen.findByText('0/1')).toBeInTheDocument()
  })

  it('leaves a parent that is not a create id alone', async () => {
    // A foreign client's RELATED-TO must never be reinterpreted.
    m.tasks.mockResolvedValue([
      task({ uid: 'not-hex@tasksd', summary: 'Trip planning' }),
      task({ uid: 'c1', summary: 'Orphan', parent: 'not-hex' }),
    ])
    setup()
    await screen.findByText('Trip planning')
    expect(screen.getByText('Orphan').closest('.task')).not.toHaveClass('sub')
  })

  it('leaves a bare-hex parent alone when no task matches it', async () => {
    m.tasks.mockResolvedValue([task({ uid: 'c1', summary: 'Orphan', parent: cid })])
    setup()
    expect(await screen.findByText('Orphan')).toBeInTheDocument()
    expect(screen.getByText('Orphan').closest('.task')).not.toHaveClass('sub')
  })
})

// ── what the editor sends for a value it cannot represent exactly ───────────

describe('<TasksView> lossy round-trips', () => {
  const zoned = () => task({
    summary: 'Pay rent', due: '2026-08-10T09:30:00+02:00', due_is_date: false,
    priority: 3, priority_label: 'high', tags: ['Home,Garden', 'Errands'],
  })

  async function openTask(user: ReturnType<typeof userEvent.setup>, t = zoned()) {
    m.tasks.mockResolvedValue([t])
    m.patchTask.mockResolvedValue(t)
    await user.click(await screen.findByText(t.summary!))
    return screen.findByRole('dialog', { name: 'Task' })
  }

  it('sends the instant, not a naive wall clock, for a zone-anchored due', async () => {
    // The suite runs in America/New_York, so Berlin 09:30 shows as 03:30 here.
    // Sending "2026-08-10T04:30" naive would strip the TZID and move the
    // deadline; sending the instant lets the server put it back in Berlin.
    const { user } = setup()
    await openTask(user)
    expect(screen.getByLabelText('Due time')).toHaveValue('03:30')
    fireEvent.change(screen.getByLabelText('Due time'), { target: { value: '04:30' } })
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    expect(m.patchTask.mock.calls[0][2]).toEqual({ due: '2026-08-10T08:30:00.000Z' })
  })

  it('sends a naive local string for a due that was already floating', async () => {
    const { user } = setup()
    await openTask(user, task({
      summary: 'Floating', due: '2026-08-10T09:30:00', due_is_date: false,
    }))
    fireEvent.change(screen.getByLabelText('Due time'), { target: { value: '10:30' } })
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    expect(m.patchTask.mock.calls[0][2]).toEqual({ due: '2026-08-10T10:30' })
  })

  it('keeps an all-day due a bare date', async () => {
    const { user } = setup()
    await openTask(user, task({ summary: 'All day', due: '2026-08-10', due_is_date: true }))
    fireEvent.change(screen.getByLabelText('Due date'), { target: { value: '2026-08-12' } })
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    expect(m.patchTask.mock.calls[0][2]).toEqual({ due: '2026-08-12' })
  })

  it('keeps a category containing a comma whole', async () => {
    // `CATEGORIES:Home\,Garden` is ONE tag. The comma-joined text field read it
    // back as "Home,Garden, Errands" and saved that as three.
    const { user } = setup()
    await openTask(user)
    expect(screen.getByRole('button', { name: 'Remove Home,Garden' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Tags'), 'urgent{Enter}')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    expect(m.patchTask.mock.calls[0][2]).toEqual({ tags: ['Home,Garden', 'Errands', 'urgent'] })
  })

  it('removes exactly the tag whose chip was dismissed', async () => {
    const { user } = setup()
    await openTask(user)
    await user.click(screen.getByRole('button', { name: 'Remove Errands' }))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    expect(m.patchTask.mock.calls[0][2]).toEqual({ tags: ['Home,Garden'] })
  })

  it('does not send a priority the user changed and then put back', async () => {
    // PRIORITY:3 can only be rendered as "high" by a four-way picker, so
    // resending "high" would quantise it to 1. Nothing changed, so nothing goes.
    const { user } = setup()
    await openTask(user)
    await user.selectOptions(screen.getByLabelText('Priority'), 'low')
    await user.selectOptions(screen.getByLabelText('Priority'), 'high')
    const title = screen.getByLabelText('Title')
    await user.clear(title)
    await user.type(title, 'Pay rent now')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    expect(m.patchTask.mock.calls[0][2]).toEqual({ summary: 'Pay rent now' })
  })

  it('still sends a priority the user genuinely changed', async () => {
    const { user } = setup()
    await openTask(user)
    await user.selectOptions(screen.getByLabelText('Priority'), 'low')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    expect(m.patchTask.mock.calls[0][2]).toEqual({ priority: 'low' })
  })
})

// ── drag-to-reschedule across day columns ───────────────────────────────────
// The day-column drag writes a DUE to a real CalDAV resource and had no test at
// all, which is how it kept bypassing `dateOut` long after the editor was fixed.

describe('<TasksView> day-column drag', () => {
  // Pin the clock: the day columns are relative to "today", so an absolute due
  // date would drift out of the window and make this test rot.
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date('2026-08-10T12:00:00-04:00'))
  })
  afterEach(() => vi.useRealTimers())

  const dragTaskTo = async (t: ReturnType<typeof task>, dayIndex: number) => {
    m.tasks.mockResolvedValue([t])
    m.patchTask.mockResolvedValue(t)
    setup('day3')
    const card = await screen.findByText(t.summary!)
    // jsdom builds no DataTransfer; the card's onDragStart calls setData on it.
    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    fireEvent.dragStart(card.closest('.day-card') || card, { dataTransfer })
    fireEvent.drop(document.querySelectorAll('.day-col')[dayIndex])
    await waitFor(() => expect(m.patchTask).toHaveBeenCalled())
    return m.patchTask.mock.calls[0][2] as { due?: string }
  }

  it('sends the instant for a zone-anchored due, not the viewer wall clock', async () => {
    // DUE;TZID=Europe/Berlin 09:30 on the 10th reads as 03:30 in the suite's
    // New York zone. A naive "2026-08-11T03:30" would land on the wire verbatim
    // and strip the TZID, moving the deadline six hours for every other client
    // sharing the collection.
    const body = await dragTaskTo(
      task({ summary: 'Pay rent', due: '2026-08-10T09:30:00+02:00', due_is_date: false }), 1)
    expect(body.due).toMatch(/Z$/)
  })

  it('still sends a plain day key for an all-day due', async () => {
    const body = await dragTaskTo(
      task({ summary: 'Bin day', due: '2026-08-10', due_is_date: true }), 1)
    expect(body.due).not.toContain('T')
  })
})
