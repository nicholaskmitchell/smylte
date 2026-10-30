// The fold follower without the Tasks pane: moves are made where the pane is
// not mounted (the calendar's editor, another tab), so it has to keep a fold
// on its task from beside the data alone.
import { useState } from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DataProvider, useTaskData } from '../data'
import { setCacheUser } from '../cache'
import { api, type List, type Task } from '../api'
import { FoldFollower } from './FoldFollower'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

const list = (id: string): List => ({
  id, href: `/${id}/`, name: id, color: null, is_task_list: true, is_calendar: false,
} as unknown as List)

const task = (o: Partial<Task>): Task => ({
  uid: 'p1', list: 'l1', summary: 'Trip planning', notes: null, status: 'NEEDS-ACTION',
  completed: false, completed_at: null, cancelled: false, parked: false, parked_at: null,
  priority: null, priority_label: 'none', percent_complete: null, due: null, due_is_date: false,
  original_due: null, original_due_is_date: false, original_due_moved: false,
  start: null, start_is_date: false, tags: [], parent: null, children: [], child_count: 0,
  completed_child_count: 0, derived_percent: null, pinned: false, kanban_column: null,
  sort_order: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  href: '/l1/p1.ics', etag: '"1"', created: null, last_modified: null, ...o,
} as Task)

/** No Tasks pane: a bare button that moves, as the calendar's editor does. */
function Mover({ t, to }: { t: Task; to: string }) {
  const { moveTask, tasks } = useTaskData()
  return (
    <button onClick={() => { void moveTask(tasks.find((x) => x.uid === t.uid && x.list === t.list) ?? t, to) }}>
      move ({tasks.length})
    </button>
  )
}

function setup(collapsed: string[], t: Task) {
  const onChange = vi.fn()
  const Harness = () => {
    const [folds, setFolds] = useState(collapsed)
    return (
      <DataProvider rev={0} onExpire={vi.fn()}>
        <FoldFollower collapsed={folds} onChange={(next) => { onChange(next); setFolds(next) }} />
        <Mover t={t} to="l2" />
      </DataProvider>
    )
  }
  render(<Harness />)
  return { onChange, user: userEvent.setup() }
}

beforeEach(() => {
  vi.clearAllMocks()
  setCacheUser('')
  localStorage.clear()
  m.lists.mockResolvedValue([list('l1'), list('l2')])
})

describe('<FoldFollower>', () => {
  it('keeps a fold on a task moved where no Tasks pane is mounted', async () => {
    const parent = task({})
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [parent] : []))
    m.moveTask.mockResolvedValue({ ...parent, list: 'l2' })
    const { onChange, user } = setup(['l1\u0000p1'], parent)
    await screen.findByText('move (1)')
    await user.click(screen.getByRole('button'))
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(['l2\u0000p1']))
  })

  it('follows a retry that finds the task in both lists and only removes the old one', async () => {
    // Nothing arrives, because the copy was already showing; only the
    // announcement of the move can say where the fold belongs.
    const here = task({})
    const there = task({ list: 'l2', href: '/l2/p1.ics' })
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [here] : [there]))
    m.moveTask.mockResolvedValue(there)
    const { onChange, user } = setup(['l1\u0000p1'], here)
    await screen.findByText('move (2)')
    await user.click(screen.getByRole('button'))
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(['l2\u0000p1']))
  })

  it('applies a move made before it mounted, once the folds have loaded', async () => {
    // App mounts the follower only after the account's folds have arrived, and
    // the owner can move a task from cached rows before that. The data layer
    // keeps the session's moves and tells a new follower about them.
    const parent = task({})
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [parent] : []))
    m.moveTask.mockResolvedValue({ ...parent, list: 'l2' })
    const onChange = vi.fn()
    const Late = () => {
      const [shown, setShown] = useState(false)
      const [folds, setFolds] = useState(['l1\u0000p1'])
      return (
        <DataProvider rev={0} onExpire={vi.fn()}>
          {shown && <FoldFollower collapsed={folds} onChange={(n) => { onChange(n); setFolds(n) }} />}
          <Mover t={parent} to="l2" />
          <button onClick={() => setShown(true)}>folds loaded</button>
        </DataProvider>
      )
    }
    render(<Late />)
    const user = userEvent.setup()
    await screen.findByText('move (1)')
    await user.click(screen.getByText('move (1)'))
    await waitFor(() => expect(m.moveTask).toHaveBeenCalled())
    await new Promise((r) => setTimeout(r, 20))
    expect(onChange).not.toHaveBeenCalled()
    await user.click(screen.getByText('folds loaded'))
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(['l2\u0000p1']))
  })

  it('leaves the folds alone when nothing moved', async () => {
    const parent = task({})
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [parent] : []))
    const { onChange } = setup(['l1\u0000p1', 'legacy-uid'], parent)
    await screen.findByText('move (1)')
    await new Promise((r) => setTimeout(r, 20))
    expect(onChange).not.toHaveBeenCalled()
  })
})
