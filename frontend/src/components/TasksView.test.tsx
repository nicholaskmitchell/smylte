import { useState } from 'react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TasksView } from './TasksView'
import { DataProvider } from '../data'
import { cacheLists, cacheTasks, setCacheUser } from '../cache'
import { api, AuthError, type List, type Task, type TaskGroup, type TasksViewMode } from '../api'

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
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [],
  parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null, href: '/l1/u1.ics', etag: '"1"', ...o,
})

const list: List = {
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#D9480F',
}

function setup(view: TasksViewMode = 'list', showCompleted = false, collapsedTasks: string[] = []) {
  const onExpire = vi.fn()
  const onCollapsedTasksChange = vi.fn()
  // The data lives in the provider now, so the harness mounts one — with the
  // same mocked `api` the assertions below already speak to. `collapsedTasks`
  // is held here for the same reason App holds it: it is a controlled prop, so
  // a harness that never fed the change back would test a control that appears
  // to do nothing.
  const Harness = ({ rev }: { rev: number }) => {
    const [collapsed, setCollapsed] = useState(collapsedTasks)
    return (
      <DataProvider rev={rev} onExpire={onExpire}>
        <TasksView onExpire={onExpire} view={view} onView={vi.fn()}
          sideCollapsed={false} onToggleSide={vi.fn()}
          hiddenLists={[]} onHiddenListsChange={vi.fn()}
          groups={[]} onGroupsChange={vi.fn()}
          collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
          collapsedTasks={collapsed}
          onCollapsedTasksChange={(next) => { onCollapsedTasksChange(next); setCollapsed(next) }}
          showCompleted={showCompleted} />
      </DataProvider>
    )
  }
  const { rerender } = render(<Harness rev={0} />)
  // Bumping `rev` is how the app tells the view a server-side change landed, so
  // it is also how a test replays one without reaching for the SSE mock.
  return {
    onExpire, onCollapsedTasksChange, user: userEvent.setup(),
    bumpRev: (rev: number) => rerender(<Harness rev={rev} />),
  }
}

/** The default harness passes no groups; this one does, so the sidebar renders
 *  its grouped layout and the picker order can be compared against it. */
function setupGrouped(groups: TaskGroup[]) {
  render(
    <DataProvider rev={0} onExpire={vi.fn()} taskGroups={groups}>
      <TasksView onExpire={vi.fn()} view="list" onView={vi.fn()}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenLists={[]} onHiddenListsChange={vi.fn()}
        groups={groups} onGroupsChange={vi.fn()}
        collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
        collapsedTasks={[]} onCollapsedTasksChange={vi.fn()}
        showCompleted={false} />
    </DataProvider>,
  )
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
  // No cache user, so nothing seeds from disk and each test starts cold.
  setCacheUser('')
  localStorage.clear()
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

  it('mints a new client_id when a multi-line paste retitles the row', async () => {
    // `onPasteTitle` writes `summary` straight into the row and bypassed
    // `patchRow`, so a row that failed (keeping its cid) and was then corrected
    // by a paste replayed the OLD idempotency slug with a NEW title — and the
    // server confirms the resource already written under that slug, discarding
    // the correction.
    m.createTask.mockRejectedValueOnce(new Error('boom'))
    const { user } = setup()
    await openBulk(user, ['alpha'])
    await user.click(bulkAdd(1))
    await screen.findByRole('alert')

    const firstTry = m.createTask.mock.calls[0][1].client_id
    m.createTask.mockClear()
    m.createTask.mockImplementation(async () => task({ uid: 'u2', summary: 'corrected' }))

    // A two-line paste: row 1 is overwritten, row 2 is appended.
    const row1 = screen.getByLabelText('Title, row 1')
    await user.click(row1)
    await user.paste('corrected\nextra')
    await waitFor(() => expect(row1).toHaveValue('corrected'))
    await user.click(bulkAdd(2))

    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(2))
    const ids = m.createTask.mock.calls.map((c) => c[1].client_id)
    expect(ids[0]).not.toBe(firstTry)
    expect(new Set(ids).size).toBe(2)      // and the two rows do not collide
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

// ── the list pickers follow the sidebar, not the fetch order ───────────────
// `GET /api/lists` sorts by manual calendar-order then name, and the sidebar
// renders that *through* the groups — each group's members, then the rest. So
// the moment a group exists the two orders diverge, and the pickers were
// following the one nobody can see.

describe('<TasksView> list picker order', () => {
  const l = (id: string, name: string): List => ({ ...list, id, href: `/${id}/`, name })
  const four = [l('a', 'Alpha'), l('b', 'Bravo'), l('c', 'Charlie'), l('d', 'Delta')]
  const groups: TaskGroup[] = [
    { id: 'g1', name: 'Work', lists: ['c'] },
    { id: 'g2', name: 'Home', lists: ['a'] },
  ]

  /** The sidebar's rows, top to bottom — the order the user actually sees. */
  const sidebarOrder = () =>
    [...document.querySelectorAll('.side-list .side-item .name')].map((n) => n.textContent)
  const pickerOrder = () =>
    [...screen.getByTitle('List for the new task').querySelectorAll('option')]
      .map((o) => o.textContent)

  it('offers the lists in the order the sidebar shows them', async () => {
    m.lists.mockResolvedValue(four)
    setupGrouped(groups)
    await screen.findByPlaceholderText('Add a task…')
    // Asserted against the rendered sidebar rather than a hardcoded sequence,
    // so the two cannot drift apart again without this failing.
    await waitFor(() => expect(pickerOrder()).toEqual(sidebarOrder()))
    expect(pickerOrder()).toEqual(['Charlie', 'Alpha', 'Bravo', 'Delta'])
  })

  it('leaves the order alone when nothing is grouped', async () => {
    m.lists.mockResolvedValue(four)
    setupGrouped([])
    await screen.findByPlaceholderText('Add a task…')
    await waitFor(() => expect(pickerOrder()).toEqual(['Alpha', 'Bravo', 'Charlie', 'Delta']))
  })

  it('reorders on the wire in server order, not the grouped one', async () => {
    // Dragging a row PROPPATCHes calendar-order onto every collection in
    // Radicale. Task groups are an app-only construct, so sending the grouped
    // flattening would rewrite the order Tasks.org and jtx Board read to match
    // a grouping none of them can see.
    m.lists.mockResolvedValue(four)
    m.reorderLists.mockResolvedValue({})
    setupGrouped(groups)
    await screen.findByPlaceholderText('Add a task…')
    await waitFor(() => expect(sidebarOrder()).toEqual(['Charlie', 'Alpha', 'Bravo', 'Delta']))

    const rowFor = (name: string) =>
      [...document.querySelectorAll('.side-list .side-item')]
        .find((r) => r.querySelector('.name')?.textContent === name)!
    // jsdom builds a DragEvent with no dataTransfer, and the handler sets
    // effectAllowed on it — so without a stub the drag throws asynchronously,
    // which vitest reports as an unhandled error and a non-zero exit even
    // though every assertion passed.
    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    fireEvent.dragStart(rowFor('Delta'), { dataTransfer })
    fireEvent.drop(rowFor('Alpha'), { dataTransfer })

    await waitFor(() => expect(m.reorderLists).toHaveBeenCalledTimes(1))
    // Delta moved onto Alpha's slot within the *server* sequence a,b,c,d.
    expect(m.reorderLists.mock.calls[0][0]).toEqual(['d', 'a', 'b', 'c'])
  })
})

// ── a subtask can have subtasks of its own ─────────────────────────────────
// RELATED-TO has always allowed a chain; only the flat parent-plus-children
// render stood in the way, so anything past one level was flattened onto the
// top level as though its parent were missing.

describe('<TasksView> nested subtasks', () => {
  /** Move house → Pack the kitchen → Buy boxes → Measure the cupboards. */
  const chain = [
    task({ uid: 'p1', summary: 'Move house' }),
    task({ uid: 'c1', summary: 'Pack the kitchen', parent: 'p1' }),
    task({ uid: 'g1', summary: 'Buy boxes', parent: 'c1' }),
    task({ uid: 'gg1', summary: 'Measure the cupboards', parent: 'g1' }),
  ]
  const depthOf = (title: string) => {
    const row = screen.getByText(title).closest('.task') as HTMLElement
    return row.style.getPropertyValue('--task-depth') || '0'
  }

  it('renders a chain as a tree, each level indented past the last', async () => {
    m.tasks.mockResolvedValue(chain)
    setup()
    await screen.findByText('Move house')
    expect(depthOf('Move house')).toBe('0')
    expect(depthOf('Pack the kitchen')).toBe('1')
    expect(depthOf('Buy boxes')).toBe('2')
    expect(depthOf('Measure the cupboards')).toBe('3')
    // Every row appears once — none promoted to the top level for want of a
    // renderer that could nest it.
    expect(document.querySelectorAll('.task:not(.sub)')).toHaveLength(1)
  })

  it('counts each level against its own parent, not the whole subtree', async () => {
    // The server joins RELATED-TO one level at a time, so the badge must too.
    m.tasks.mockResolvedValue(chain)
    setup()
    await screen.findByText('Move house')
    expect(screen.getAllByText('0/1')).toHaveLength(3)
  })

  it('offers "+ sub" on a subtask, so a tree can be grown from any row', async () => {
    m.tasks.mockResolvedValue(chain)
    m.createTask.mockImplementation(async (_l: string, b: Record<string, unknown>) =>
      task({ uid: `${b.client_id as string}@tasksd`, summary: b.summary as string,
        parent: (b.parent as string) ?? null }))
    const { user } = setup()
    await screen.findByText('Buy boxes')
    const row = screen.getByText('Buy boxes').closest('.task') as HTMLElement
    await user.click(within(row).getByTitle('Add subtask'))
    await user.type(await screen.findByPlaceholderText('Subtask'), 'Tape{Enter}')
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(1))
    expect(m.createTask.mock.calls[0][1].parent).toBe('g1')
    await waitFor(() => expect(depthOf('Tape')).toBe('3'))
  })

  it('survives a parent cycle another client authored', async () => {
    // Nothing on either side of the wire checks RELATED-TO for loops, so a
    // recursive render has to refuse to walk one twice rather than recurse
    // until the stack gives out.
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Alpha', parent: 'b' }),
      task({ uid: 'b', summary: 'Bravo', parent: 'a' }),
    ])
    setup()
    await screen.findByText('Alpha')
    expect(screen.getAllByText('Alpha')).toHaveLength(1)
    expect(screen.getAllByText('Bravo')).toHaveLength(1)
  })

  it('takes a promoted subtask\'s own descendants with it', async () => {
    // The parent is completed and hidden, so the child stands on its own — and
    // the grandchild has to follow it rather than vanish with the parent.
    m.tasks.mockResolvedValue([
      task({ uid: 'p1', summary: 'Move house', completed: true, status: 'COMPLETED' }),
      task({ uid: 'c1', summary: 'Pack the kitchen', parent: 'p1' }),
      task({ uid: 'g1', summary: 'Buy boxes', parent: 'c1' }),
    ])
    setup()
    await screen.findByText('Pack the kitchen')
    expect(screen.queryByText('Move house')).not.toBeInTheDocument()
    expect(depthOf('Pack the kitchen')).toBe('0')
    expect(depthOf('Buy boxes')).toBe('1')
  })
})

// ── folding a subtask tree away ─────────────────────────────────────────────

describe('<TasksView> collapsing subtasks', () => {
  const chain = [
    task({ uid: 'p1', summary: 'Move house' }),
    task({ uid: 'c1', summary: 'Pack the kitchen', parent: 'p1' }),
    task({ uid: 'g1', summary: 'Buy boxes', parent: 'c1' }),
  ]

  it('hides the whole subtree beneath the row that was folded', async () => {
    m.tasks.mockResolvedValue(chain)
    const { user, onCollapsedTasksChange } = setup()
    await screen.findByText('Buy boxes')
    await user.click(screen.getByRole('button', { name: 'Hide subtasks of Move house' }))
    expect(screen.queryByText('Pack the kitchen')).not.toBeInTheDocument()
    expect(screen.queryByText('Buy boxes')).not.toBeInTheDocument()
    expect(screen.getByText('Move house')).toBeInTheDocument()
    // Written through to the account, like the sidebar's collapsed groups —
    // as a `taskKey`, since the pane is keyed on (list, uid): the same uid can
    // live in two lists and each copy folds on its own. A bare uid stored by an
    // earlier version is still honoured on read; see the migration control in
    // backlog.aug19.stage4b.test.tsx.
    expect(onCollapsedTasksChange).toHaveBeenCalledWith(['l1\u0000p1'])
  })

  it('opens folded from a stored set, and expands again', async () => {
    m.tasks.mockResolvedValue(chain)
    const { user, onCollapsedTasksChange } = setup('list', false, ['c1'])
    await screen.findByText('Pack the kitchen')
    expect(screen.queryByText('Buy boxes')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Show subtasks of Pack the kitchen' }))
    expect(onCollapsedTasksChange).toHaveBeenCalledWith([])
  })

  it('gives a row with no children no control to fold', async () => {
    m.tasks.mockResolvedValue([task({ uid: 'p1', summary: 'Solo' })])
    setup()
    await screen.findByText('Solo')
    expect(screen.queryByRole('button', { name: /subtasks of Solo/ })).not.toBeInTheDocument()
  })

  it('unfolds a row to show the subtask being added to it', async () => {
    // Otherwise "+ sub" on a folded row types into nowhere.
    m.tasks.mockResolvedValue(chain)
    const { user, onCollapsedTasksChange } = setup('list', false, ['p1'])
    await screen.findByText('Move house')
    const row = screen.getByText('Move house').closest('.task') as HTMLElement
    await user.click(within(row).getByTitle('Add subtask'))
    expect(onCollapsedTasksChange).toHaveBeenCalledWith([])
  })

  it('drops a stored uid that no longer names a task with children', async () => {
    // Nothing ever re-creates a uid, so a set that only grows is a leak.
    m.tasks.mockResolvedValue(chain)
    const { user, onCollapsedTasksChange } = setup('list', false, ['gone', 'c1'])
    await screen.findByText('Move house')
    await user.click(screen.getByRole('button', { name: 'Hide subtasks of Move house' }))
    // 'gone' is dropped; 'c1' is KEPT even though it is the old bare-uid
    // spelling, because a task with that uid still has children — dropping it
    // would unfold a tree the user folded. The new entry is written as a
    // `taskKey`.
    expect(onCollapsedTasksChange).toHaveBeenCalledWith(['c1', 'l1\u0000p1'])
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

// ── nothing on screen may claim the account is empty before it is known ─────
// An empty `lists` before the first fetch is ignorance, not an empty account.
// Telling a user with a dozen lists to "create a list to get started" was the
// loudest thing on screen during every cold load and every tab switch.

describe('<TasksView> loading versus empty', () => {
  it('says nothing about the account while the lists are in flight', async () => {
    m.lists.mockReturnValue(new Promise(() => {}))     // never settles
    setup()
    expect(await screen.findByText('Loading…')).toBeInTheDocument()
    expect(screen.queryByText('Create a list to get started.')).not.toBeInTheDocument()
  })

  it('offers the call to action once the fetch says the account is empty', async () => {
    m.lists.mockResolvedValue([])
    setup()
    expect(await screen.findByText('Create a list to get started.')).toBeInTheDocument()
  })

  it('holds "Nothing to do here." until the tasks have actually landed', async () => {
    m.tasks.mockReturnValue(new Promise(() => {}))
    setup()
    // Re-queried rather than awaited once: the pane swaps from the no-lists
    // branch to the list branch as the lists land, and both say "Loading…" —
    // from different nodes.
    await waitFor(() => expect(m.tasks).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText('Loading…')).toBeInTheDocument())
    expect(screen.queryByText('Nothing to do here.')).not.toBeInTheDocument()
  })

  it('paints cached rows on the first frame, before any fetch resolves', async () => {
    // What the mirror is for: a reload lands on content, not on a blank pane
    // and a misleading instruction.
    setCacheUser('nick')
    cacheLists([list])
    cacheTasks([task({ uid: 'u1', summary: 'From the cache' })])
    m.lists.mockReturnValue(new Promise(() => {}))
    m.tasks.mockReturnValue(new Promise(() => {}))
    setup()
    expect(screen.getByText('From the cache')).toBeInTheDocument()
    expect(screen.queryByText('Create a list to get started.')).not.toBeInTheDocument()
  })

  it('lets the server replace what the cache seeded', async () => {
    setCacheUser('nick')
    cacheLists([list])
    cacheTasks([task({ uid: 'u1', summary: 'Stale' })])
    m.tasks.mockResolvedValue([task({ uid: 'u2', summary: 'Fresh' })])
    setup()
    expect(screen.getByText('Stale')).toBeInTheDocument()
    expect(await screen.findByText('Fresh')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Stale')).not.toBeInTheDocument())
  })

  it('does not prune list-scoped settings against a cached snapshot', async () => {
    // The seed can predate a list created in another client, so pruning against
    // it would delete a perfectly live `hidden_lists` entry. Only a real fetch
    // is evidence that a list is gone.
    setCacheUser('nick')
    cacheLists([list])
    cacheTasks([task()])
    const onHiddenListsChange = vi.fn()
    m.lists.mockReturnValue(new Promise(() => {}))
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TasksView onExpire={vi.fn()} view="list" onView={vi.fn()}
          sideCollapsed={false} onToggleSide={vi.fn()}
          hiddenLists={['l-elsewhere']} onHiddenListsChange={onHiddenListsChange}
          groups={[]} onGroupsChange={vi.fn()}
          collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
          collapsedTasks={[]} onCollapsedTasksChange={vi.fn()}
          showCompleted={false} />
      </DataProvider>,
    )
    await screen.findByText('Ship it')
    expect(onHiddenListsChange).not.toHaveBeenCalled()
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

  it('keeps the time of day when a timed due moves column', async () => {
    // The drop names a DAY. Everything else about the deadline — including the
    // hour the user set — has to survive it.
    const body = await dragTaskTo(
      task({ summary: 'Call back', due: '2026-08-10T14:00', due_is_date: false }), 2)
    expect(body.due).toBe('2026-08-12T14:00')
  })

  it('writes nothing when a task is dropped on the column it is already in', async () => {
    // The only decision `dropOnDay` makes before writing. Without it every
    // pick-up-and-put-down is a CalDAV PUT plus a re-read against the user's
    // real list, and a SEQUENCE bump every other client sees.
    const t = task({ summary: 'Stay put', due: '2026-08-10', due_is_date: true })
    m.tasks.mockResolvedValue([t])
    m.patchTask.mockResolvedValue(t)
    setup('day3')
    const card = await screen.findByText('Stay put')
    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    fireEvent.dragStart(card.closest('.day-card') || card, { dataTransfer })
    fireEvent.drop(document.querySelectorAll('.day-col')[0])      // today, its own column

    await Promise.resolve()
    expect(m.patchTask).not.toHaveBeenCalled()
  })

  it('does nothing when the dragged task is gone by the time it lands', async () => {
    // A drop that resolves no task — the row was completed or deleted in
    // another client mid-drag — must not write anything.
    const t = task({ summary: 'Vanishing', due: '2026-08-10', due_is_date: true })
    m.tasks.mockResolvedValue([t])
    m.patchTask.mockResolvedValue(t)
    setup('day3')
    await screen.findByText('Vanishing')
    fireEvent.drop(document.querySelectorAll('.day-col')[1])      // no dragStart at all

    await Promise.resolve()
    expect(m.patchTask).not.toHaveBeenCalled()
  })
})

// ── the reported bug: a row that lands in one place and moves to another ────

describe('<TasksView> order stability', () => {
  const rowTitles = () =>
    [...document.querySelectorAll('.task:not(.sub) .task-title')]
      .map((n) => n.textContent?.trim())

  const a = task({ uid: 'a', summary: 'Alpha', due: '2026-08-12', due_is_date: true })
  const b = task({ uid: 'b', summary: 'Bravo', due: '2026-08-10', due_is_date: true })
  const c = task({ uid: 'c', summary: 'Charlie', due: '2026-08-11', due_is_date: true })

  it('renders by due date, not in the order the fetch happened to build', async () => {
    // The list used to render `tasks` verbatim, which is per-list fetch blocks
    // concatenated — an order nothing on screen explains.
    m.tasks.mockResolvedValue([c, a, b])
    setup('list')
    await screen.findByText('Alpha')
    expect(rowTitles()).toEqual(['Bravo', 'Charlie', 'Alpha'])
  })

  it('does not move a row when the server returns the same tasks reshuffled', async () => {
    // This is the warp. A write publishes an SSE event, the event bumps `rev`,
    // `rev` refetches, and the new array replaced the old one wholesale — so
    // rows jumped a few hundred milliseconds after they were painted.
    m.tasks.mockResolvedValue([c, a, b])
    const { bumpRev } = setup('list')
    await screen.findByText('Alpha')
    const before = rowTitles()

    m.tasks.mockResolvedValue([b, c, a])
    bumpRev(1)
    await waitFor(() => expect(m.tasks).toHaveBeenCalledTimes(2))
    expect(rowTitles()).toEqual(before)
  })

  it('keeps an optimistic row where it first painted once the server answers', async () => {
    // The stand-in is appended to the end of the array and `settleCreate`
    // deliberately swaps the DTO in place, so nothing about the array says
    // where this row belongs — only the comparator does.
    m.tasks.mockResolvedValue([a, b])
    const created = task({ uid: 'new', summary: 'Bisect', due: '2026-08-11', due_is_date: true })
    m.createTask.mockResolvedValue(created)
    const { user, bumpRev } = setup('list')
    await screen.findByText('Alpha')

    await openAdd(user)
    await user.type(screen.getByLabelText('Title'), 'Bisect')
    await user.type(screen.getByLabelText('Due date'), '2026-08-11')
    await user.click(screen.getByRole('button', { name: 'Add' }))

    // Between Bravo (the 10th) and Alpha (the 12th) from the very first paint.
    await screen.findByText('Bisect')
    expect(rowTitles()).toEqual(['Bravo', 'Bisect', 'Alpha'])

    // And still there after the write's own refetch brings it back at the far
    // end of the array, which is where a per-list fetch would put it.
    m.tasks.mockResolvedValue([a, b, created])
    bumpRev(1)
    await waitFor(() => expect(m.tasks).toHaveBeenCalledTimes(2))
    expect(rowTitles()).toEqual(['Bravo', 'Bisect', 'Alpha'])
  })
})

// ── manual drag-reorder ─────────────────────────────────────────────────────

describe('<TasksView> drag-to-reorder', () => {
  const rowTitles = () =>
    [...document.querySelectorAll('.task:not(.sub) .task-title')]
      .map((n) => n.textContent?.trim())

  const wrapFor = (title: string) =>
    screen.getByText(title).closest('.task-drag') as HTMLElement

  const dragOnto = (from: string, to: string) => {
    // jsdom builds no DataTransfer; the wrapper's onDragStart calls setData.
    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    fireEvent.dragStart(wrapFor(from), { dataTransfer })
    fireEvent.drop(wrapFor(to), { dataTransfer })
  }

  const a = task({ uid: 'a', summary: 'Alpha', due: '2026-08-10', due_is_date: true })
  const b = task({ uid: 'b', summary: 'Bravo', due: '2026-08-11', due_is_date: true })
  const c = task({ uid: 'c', summary: 'Charlie', due: '2026-08-12', due_is_date: true })

  it('sends every task on the account, in the new order', async () => {
    // Not just the row that moved: manual position has to be comparable across
    // lists, since the pane is always the merged view.
    m.tasks.mockResolvedValue([a, b, c])
    m.reorderTasks.mockResolvedValue({ ok: true })
    setup('list')
    await screen.findByText('Alpha')

    dragOnto('Charlie', 'Alpha')
    await waitFor(() => expect(m.reorderTasks).toHaveBeenCalled())
    expect(m.reorderTasks.mock.calls[0][0]).toEqual([
      { list: 'l1', uid: 'c' }, { list: 'l1', uid: 'a' }, { list: 'l1', uid: 'b' },
    ])
  })

  it('paints the move at once and holds it through the refetch', async () => {
    m.tasks.mockResolvedValue([a, b, c])
    m.reorderTasks.mockResolvedValue({ ok: true })
    const { bumpRev } = setup('list')
    await screen.findByText('Alpha')
    expect(rowTitles()).toEqual(['Alpha', 'Bravo', 'Charlie'])

    dragOnto('Charlie', 'Alpha')
    expect(rowTitles()).toEqual(['Charlie', 'Alpha', 'Bravo'])

    // The server now knows, so the refetch carries the positions back.
    m.tasks.mockResolvedValue([
      { ...a, sort_order: 2 }, { ...b, sort_order: 3 }, { ...c, sort_order: 1 },
    ])
    bumpRev(1)
    await waitFor(() => expect(m.tasks).toHaveBeenCalledTimes(2))
    expect(rowTitles()).toEqual(['Charlie', 'Alpha', 'Bravo'])
  })

  it('puts the old order back when the write fails', async () => {
    // The UI must not keep claiming a move the server refused.
    m.tasks.mockResolvedValue([a, b, c])
    m.reorderTasks.mockRejectedValue(new Error('nope'))
    setup('list')
    await screen.findByText('Alpha')

    dragOnto('Charlie', 'Alpha')
    await waitFor(() => expect(rowTitles()).toEqual(['Alpha', 'Bravo', 'Charlie']))
  })

  it('takes a task\'s subtasks with it', async () => {
    const kid = task({ uid: 'a1', summary: 'Alpha sub', parent: 'a' })
    m.tasks.mockResolvedValue([a, b, c, kid])
    m.reorderTasks.mockResolvedValue({ ok: true })
    setup('list')
    await screen.findByText('Alpha sub')

    dragOnto('Alpha', 'Charlie')
    await waitFor(() => expect(m.reorderTasks).toHaveBeenCalled())
    // The subtask keeps its place under its parent — it is not a top-level row
    // and never leaves the subtree.
    expect(rowTitles()).toEqual(['Bravo', 'Charlie', 'Alpha'])
    expect(screen.getByText('Alpha sub').closest('.task')).toHaveClass('sub')
  })

  it('does not offer reorder in the day-column views', async () => {
    // Those columns already use drag for rescheduling; one gesture cannot mean
    // two things.
    m.tasks.mockResolvedValue([a, b, c])
    setup('day3')
    await screen.findByText('Alpha')
    expect(document.querySelectorAll('.task-drag')).toHaveLength(0)
  })
})

// ── Stage 4 backlog closures (docs/AUDIT.md) ───────────────────────────────

describe('stage 4 — list drag and the prune gate', () => {
  // AUDIT closed: TasksView.tsx:518 — the indicator pointed the wrong way.
  it('marks the drop side so the indicator matches where the row lands', async () => {
    m.lists.mockResolvedValue([list])
    m.tasks.mockResolvedValue([
      task({ uid: 'a', summary: 'Alpha', sort_order: 1 }),
      task({ uid: 'b', summary: 'Bravo', sort_order: 2 }),
      task({ uid: 'c', summary: 'Charlie', sort_order: 3 }),
    ])
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TasksView onExpire={vi.fn()} view="list" onView={vi.fn()}
          sideCollapsed={false} onToggleSide={vi.fn()}
          hiddenLists={[]} onHiddenListsChange={vi.fn()}
          groups={[]} onGroupsChange={vi.fn()}
          collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
          collapsedTasks={[]} onCollapsedTasksChange={vi.fn()}
          showCompleted={false} />
      </DataProvider>,
    )
    const row = async (name: string) =>
      (await screen.findByText(name)).closest('.task-drag') as HTMLElement

    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    // Downward: Alpha onto Charlie lands AFTER Charlie, so the line goes below.
    fireEvent.dragStart(await row('Alpha'), { dataTransfer })
    fireEvent.dragOver(await row('Charlie'), { dataTransfer })
    await waitFor(async () =>
      expect((await row('Charlie')).className).toContain('drag-below'))

    // Upward: Charlie onto Alpha lands BEFORE Alpha, so the line stays on top.
    fireEvent.dragStart(await row('Charlie'), { dataTransfer })
    fireEvent.dragOver(await row('Alpha'), { dataTransfer })
    await waitFor(async () => {
      const cls = (await row('Alpha')).className
      expect(cls).toContain('drag-over')
      expect(cls).not.toContain('drag-below')
    })
  })

  // AUDIT closed: TasksView.tsx:91 — a failed lists fetch pruned settings.
  it('does not prune list-scoped settings when the lists fetch failed', async () => {
    // The cache holds a list the (failed) fetch cannot confirm. Pruning against
    // it would drop the hidden-list entry and write that loss to the server.
    setCacheUser('u')
    cacheLists([list, { ...list, id: 'l2', name: 'Later' }])
    m.lists.mockRejectedValue(new Error('boom'))
    m.tasks.mockResolvedValue([])
    const onHiddenListsChange = vi.fn()
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TasksView onExpire={vi.fn()} view="list" onView={vi.fn()}
          sideCollapsed={false} onToggleSide={vi.fn()}
          hiddenLists={['l2']} onHiddenListsChange={onHiddenListsChange}
          groups={[]} onGroupsChange={vi.fn()}
          collapsedGroups={[]} onCollapsedGroupsChange={vi.fn()}
          collapsedTasks={[]} onCollapsedTasksChange={vi.fn()}
          showCompleted={false} />
      </DataProvider>,
    )
    await waitFor(() => expect(m.lists).toHaveBeenCalled())
    expect(onHiddenListsChange).not.toHaveBeenCalled()
  })
})

// ── the "View completed" pane ───────────────────────────────────────────────
// It renders `done`, which is derived from `tops`, and `tops` calls a task
// top-level when its parent is not RENDERED. `rendersUnder` consults the global
// `showCompleted` flag — but this pane shows done tasks regardless of it. So
// with the default showCompleted={false} a completed child of a completed
// parent was promoted into `tops` while its parent was also there, and the same
// task appeared twice in the pane.

describe('<TasksView> completed pane', () => {
  const openPane = async () => {
    const { user } = setup()
    // Nothing shows in the main pane — both tasks are done and showCompleted is
    // false — so wait for the button rather than for a row.
    await user.click(await screen.findByRole('button', { name: /view completed/i }))
    await screen.findByText('Trip')
    return user
  }

  beforeEach(() => {
    m.lists.mockResolvedValue([list])
    m.tasks.mockResolvedValue([
      task({ uid: 'trip', summary: 'Trip', completed: true, status: 'COMPLETED' }),
      task({ uid: 'flight', summary: 'Book flight', parent: 'trip',
             completed: true, status: 'COMPLETED', href: '/l1/flight.ics' }),
    ])
  })

  it('renders a completed subtask once, not as a row and a child', async () => {
    await openPane()
    expect(screen.getAllByText('Book flight')).toHaveLength(1)
    expect(screen.getAllByText('Trip')).toHaveLength(1)
  })

  it('keeps the completed subtask nested under its completed parent', async () => {
    // Nesting is what stops the duplicate: promote the child to top level and
    // it is a sibling of its own parent. Asserted through the fold control,
    // which only exists for a row that actually has children rendered under it.
    const user = await openPane()
    await user.click(screen.getByRole('button', { name: 'Hide subtasks of Trip' }))
    expect(screen.queryByText('Book flight')).not.toBeInTheDocument()
    expect(screen.getByText('Trip')).toBeInTheDocument()
  })
})
