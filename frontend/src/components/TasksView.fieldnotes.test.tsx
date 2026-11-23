import { useState } from 'react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  const Harness = ({ rev }: { rev: number }) => {
    const [collapsed, setCollapsed] = useState<string[]>([])
    return (
      <DataProvider rev={rev} onExpire={vi.fn()}>
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
  const { container, rerender } = render(<Harness rev={0} />)
  // Bumping `rev` is how the app says a server-side change landed (an SSE
  // event); it refetches every list.
  return { container, user: userEvent.setup(), bumpRev: (rev: number) => rerender(<Harness rev={rev} />) }
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

  it('draws a task\'s fold in the pen, and keeps its glyph', async () => {
    setup()
    await screen.findByText('Book flight')
    const fold = screen.getByRole('button', { name: 'Hide subtasks of Trip planning' })
    expect(fold).toHaveClass('twisty', 'open')
    expect(fold.querySelector('svg.icon-ink[data-icon="right"][aria-hidden="true"]')).not.toBeNull()
    expect(fold).toHaveTextContent('›')
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

  it('says nothing in the editor about moving, and keeps what parking does elsewhere', async () => {
    const { user } = setup()
    await user.click(await screen.findByText('Trip planning'))
    const dialog = await screen.findByRole('dialog', { name: 'Task' })
    await user.selectOptions(within(dialog).getByLabelText('List'), 'l2')
    // The controls stay; only the sentences about them go.
    expect(within(dialog).getByRole('button', { name: 'Park it' })).toBeInTheDocument()
    expect(within(dialog).queryByText(/Its subtasks move with it/)).not.toBeInTheDocument()
    // What parking does outside Smylte is a consequence, so it stays.
    expect(within(dialog).getByText(/Other apps still show it/)).toBeInTheDocument()
  })

  it('keeps a decorative drawing above the "nothing to do" text, once loaded', async () => {
    m.tasks.mockResolvedValue([])
    const { container } = setup()
    const empty = await waitFor(() => {
      const e = container.querySelector('.scroll > .empty')
      expect(e).toHaveTextContent('Nothing to do here.')
      return e as HTMLElement
    })
    const wrap = empty.querySelector('.view-drawing')!
    expect(wrap).toHaveAttribute('aria-hidden', 'true')
    expect(empty.firstElementChild).toBe(wrap)
  })

  it('keeps the drawing in the no-lists empty state, once loaded', async () => {
    m.lists.mockResolvedValue([])
    const { container } = setup()
    const empty = await waitFor(() => {
      const e = container.querySelector('.content > .empty')
      expect(e).toHaveTextContent('Create a list to get started.')
      return e as HTMLElement
    })
    expect(empty.querySelector('.view-drawing')).toHaveAttribute('aria-hidden', 'true')
  })

  it('draws nothing while it is still loading', () => {
    m.lists.mockReturnValue(new Promise(() => {}))
    const { container } = setup()
    expect(container.querySelector('.empty')).not.toBeNull()
    expect(container.querySelector('.view-drawing')).toBeNull()
  })

  it('draws nothing in the list pane while its tasks are still loading', async () => {
    m.tasks.mockReturnValue(new Promise(() => {}))
    const { container } = setup()
    const empty = await waitFor(() => {
      const e = container.querySelector('.scroll > .empty')
      expect(e).not.toBeNull()
      return e as HTMLElement
    })
    expect(empty).toHaveTextContent('Loading')
    expect(empty).toHaveAttribute('aria-busy', 'true')
    expect(empty.querySelector('.view-drawing')).toBeNull()
    expect(container.querySelector('.view-drawing')).toBeNull()
  })

  it('leaves the presets without it', async () => {
    document.documentElement.removeAttribute('data-surface')
    m.tasks.mockResolvedValue([])
    const { container } = setup()
    await screen.findByText('Nothing to do here.')
    expect(container.querySelector('.view-drawing')).toBeNull()
  })
})

// ── a tick, drawn before the row goes ───────────────────────────────────────
// Today keeps a ticked row, so its tick and strike draw. Tasks took the row out
// of the pane in the same render as the tick, so neither was ever seen. Under
// Field notes the row now stays where it was until both have drawn, then fades
// and folds away. jsdom has no stylesheets, so the motion tokens the timing is
// read from are set on <html> here; with them absent (every other test in this
// file and all of TasksView.test.tsx) nothing is held and a row goes at once.

describe('<TasksView> a tick under Field notes', () => {
  // ink = 4 × 60 + 500 + 240 = 980ms, then leave = 450ms.
  const TOKENS: Record<string, string> = {
    '--stagger': '60ms', '--dur-stroke': '.5s', '--dur': '.24s', '--dur-slow': '.45s',
  }
  const INK = 980
  const LEAVE = 450
  const alpha = task({ uid: 'a1', summary: 'Alpha' })
  const bravo = task({ uid: 'b1', summary: 'Bravo' })
  // In steps, as a clock would: each phase's timer is set by an effect after the
  // render the previous phase caused, so one long jump only runs the first.
  const later = async (ms: number) => {
    for (let t = 0; t < ms; t += 50) await act(async () => { vi.advanceTimersByTime(Math.min(50, ms - t)) })
  }
  const rowOf = (title: string) => screen.getByText(title).closest('.task') as HTMLElement
  const tickRow = (row: HTMLElement) =>
    fireEvent.click(within(row).getByRole('button', { name: 'Toggle complete' }))

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    for (const [k, v] of Object.entries(TOKENS)) document.documentElement.style.setProperty(k, v)
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [alpha, bravo] : []))
    m.complete.mockImplementation(async (_l: string, uid: string, done?: boolean) => ({
      ...[alpha, bravo, parent, child].find((t) => t.uid === uid)!,
      completed: done ?? true, status: (done ?? true) ? 'COMPLETED' : 'NEEDS-ACTION',
    }))
  })
  afterEach(() => {
    vi.useRealTimers()
    for (const k of Object.keys(TOKENS)) document.documentElement.style.removeProperty(k)
  })

  it('keeps the ticked row, ticked and struck, then folds it away', async () => {
    const { container } = setup()
    await screen.findByText('Alpha')
    const row = rowOf('Alpha')
    const group = row.parentElement as HTMLElement
    tickRow(row)
    // The same row, done: the tick and the strike draw on it.
    expect(row.isConnected).toBe(true)
    expect(row).toHaveClass('done')
    expect(within(row).getByRole('button', { name: 'Toggle complete' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(row).getByRole('button', { name: 'Toggle complete' })).toHaveClass('on')
    // The header counts what is open, at once.
    expect(pane(container).querySelector('.content-sub')).toHaveTextContent('1 open')
    // Held rows are not dragged.
    expect(group).not.toHaveAttribute('draggable', 'true')
    await later(50)                         // StrikeInk arms two frames later
    expect(row.querySelector('.strike-ink')).toHaveClass('on')
    await later(INK - 150)
    expect(group).not.toHaveClass('leaving')
    await later(200)
    expect(group).toHaveClass('leaving')
    expect(group).toHaveAttribute('inert')
    expect(group.style.getPropertyValue('--leave-h')).toMatch(/px$/)
    await later(LEAVE - 200)
    expect(row.isConnected).toBe(true)
    await later(300)
    expect(row.isConnected).toBe(false)
    expect(screen.queryByText('Alpha')).not.toBeInTheDocument()
    expect(screen.getByText('Bravo')).toBeInTheDocument()
  })

  it('keeps an unticked row, open, for good', async () => {
    setup()
    await screen.findByText('Alpha')
    const row = rowOf('Alpha')
    tickRow(row)
    await later(400)
    tickRow(row)
    await waitFor(() => expect(m.complete).toHaveBeenCalledTimes(2))
    expect(m.complete.mock.calls[1][2]).toBe(false)
    await later(INK + LEAVE + 500)
    expect(row.isConnected).toBe(true)
    expect(row).not.toHaveClass('done')
    expect(row.parentElement).not.toHaveClass('leaving')
  })

  it('keeps an unticked row open when the tick\'s answer lands after the untick', async () => {
    // Writes are not serialised: the tick's answer (done) can land after the
    // untick, and must not tick the row again behind the user's back.
    const answers: Array<(t: Task) => void> = []
    m.complete.mockImplementation(() => new Promise<Task>((r) => { answers.push(r) }))
    setup()
    await screen.findByText('Alpha')
    const row = rowOf('Alpha')
    const check = () => within(row).getByRole('button', { name: 'Toggle complete' })
    tickRow(row)
    await later(300)
    tickRow(row)
    await waitFor(() => expect(m.complete).toHaveBeenCalledTimes(2))
    expect(row.isConnected).toBe(true)
    expect(check()).toHaveAttribute('aria-pressed', 'false')
    await act(async () => { answers[0]({ ...alpha, completed: true, status: 'COMPLETED' }) })
    expect(row.isConnected).toBe(true)
    expect(check()).toHaveAttribute('aria-pressed', 'false')
    await later(200)
    expect(row.isConnected).toBe(true)
    expect(check()).toHaveAttribute('aria-pressed', 'false')
    await act(async () => { answers[1]({ ...alpha, completed: false, status: 'NEEDS-ACTION' }) })
    expect(row.isConnected).toBe(true)
    expect(rowOf('Alpha')).toBe(row)
    expect(check()).toHaveAttribute('aria-pressed', 'false')
    await later(INK + LEAVE + 500)
    expect(rowOf('Alpha')).toBe(row)
    expect(check()).toHaveAttribute('aria-pressed', 'false')
    expect(row.parentElement).not.toHaveClass('leaving')
  })

  it('keeps a row whose write failed, open, and lets it stay', async () => {
    m.complete.mockRejectedValue(new Error('boom'))
    setup()
    await screen.findByText('Alpha')
    const row = rowOf('Alpha')
    tickRow(row)
    await waitFor(() => expect(row).not.toHaveClass('done'))
    await later(INK + LEAVE + 500)
    expect(row.isConnected).toBe(true)
    expect(row.parentElement).not.toHaveClass('leaving')
  })

  it('moves it to Completed only after it has drawn, when completed tasks show', async () => {
    const { container } = setup('list', true)
    await screen.findByText('Alpha')
    const row = rowOf('Alpha')
    tickRow(row)
    // Still in the open run, the same node, rather than remounted under
    // Completed already finished (which drew nothing).
    expect(row.isConnected).toBe(true)
    expect(pane(container).querySelector('.section-label')).toBeNull()
    await later(INK + LEAVE + 100)
    expect(row.isConnected).toBe(false)
    expect(pane(container).querySelector('.section-label')).toHaveTextContent('Completed · 1')
    expect(rowOf('Alpha')).toHaveClass('done')
  })

  it('leaves a subtask under its open parent, struck, as it always has', async () => {
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [parent, child] : []))
    const { container } = setup()
    await screen.findByText('Book flight')
    const row = rowOf('Book flight')
    tickRow(row)
    expect(await screen.findByText('1/1')).toBeInTheDocument()
    await later(INK + LEAVE + 500)
    expect(row.isConnected).toBe(true)
    expect(row).toHaveClass('done')
    expect(pane(container).querySelector('.leaving')).toBeNull()
  })

  it('draws the parent the server closed, then takes it away with its subtasks', async () => {
    // auto_close_parents: ticking the last open subtask completes the parent on
    // the server, and the pane learns of it on the next fetch.
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [parent, child] : []))
    const { bumpRev } = setup()
    await screen.findByText('Book flight')
    const top = rowOf('Trip planning')
    tickRow(rowOf('Book flight'))
    await waitFor(() => expect(m.complete).toHaveBeenCalledTimes(1))
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [
      { ...parent, completed: true, status: 'COMPLETED' },
      { ...child, completed: true, status: 'COMPLETED' },
    ] : []))
    bumpRev(1)
    await waitFor(() => expect(top).toHaveClass('done'))
    expect(top.isConnected).toBe(true)
    expect(top.parentElement).not.toHaveClass('leaving')
    await later(INK + 100)
    expect(top.parentElement).toHaveClass('leaving')
    await later(LEAVE + 100)
    expect(top.isConnected).toBe(false)
    expect(screen.queryByText('Book flight')).not.toBeInTheDocument()
  })

  it('keeps a subtask the server closed with its parent inside the parent as both leave', async () => {
    // auto_close_parents climbs: ticking Leaf closes Mid, then Grand.
    const g = task({ uid: 'g1', summary: 'Grand', children: ['m1'] })
    const mid = task({ uid: 'm1', summary: 'Mid', parent: 'g1', children: ['f1'] })
    const leaf = task({ uid: 'f1', summary: 'Leaf', parent: 'm1' })
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [g, mid, leaf] : []))
    m.complete.mockImplementation(async (_l: string, uid: string, done?: boolean) => ({
      ...[g, mid, leaf].find((t) => t.uid === uid)!,
      completed: done ?? true, status: (done ?? true) ? 'COMPLETED' : 'NEEDS-ACTION',
    }))
    const { bumpRev } = setup()
    await screen.findByText('Leaf')
    const top = rowOf('Grand')
    tickRow(rowOf('Leaf'))
    await waitFor(() => expect(m.complete).toHaveBeenCalledTimes(1))
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [g, mid, leaf].map((t) => (
      { ...t, completed: true, status: 'COMPLETED' })) : []))
    bumpRev(1)
    await waitFor(() => expect(top).toHaveClass('done'))
    const midRow = rowOf('Mid')
    await later(INK + 100)
    const group = top.parentElement as HTMLElement
    expect(group).toHaveClass('leaving')
    expect(rowOf('Mid')).toBe(midRow)
    expect(group.contains(midRow)).toBe(true)
  })

  it('renews a parent\'s watch on each subtask tick, so a late close still draws', async () => {
    const p = task({ uid: 'p2', summary: 'Pack the car', children: ['k1', 'k2'] })
    const a = task({ uid: 'k1', summary: 'Tent', parent: 'p2' })
    const b = task({ uid: 'k2', summary: 'Stove', parent: 'p2' })
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [p, a, b] : []))
    m.complete.mockImplementation(async (_l: string, uid: string, done?: boolean) => ({
      ...[a, b].find((t) => t.uid === uid)!,
      completed: done ?? true, status: (done ?? true) ? 'COMPLETED' : 'NEEDS-ACTION',
    }))
    const { bumpRev } = setup()
    await screen.findByText('Stove')
    const top = rowOf('Pack the car')
    tickRow(rowOf('Tent'))
    await later(9700)
    tickRow(rowOf('Stove'))
    await waitFor(() => expect(m.complete).toHaveBeenCalledTimes(2))
    // Past the first tick's watch, inside the second's.
    await later(500)
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [
      { ...p, completed: true, status: 'COMPLETED' },
      { ...a, completed: true, status: 'COMPLETED' },
      { ...b, completed: true, status: 'COMPLETED' },
    ] : []))
    bumpRev(1)
    await waitFor(() => expect(top).toHaveClass('done'))
    expect(top.isConnected).toBe(true)
    expect(top.querySelector('.check.on')).not.toBeNull()
    expect(top.parentElement).not.toHaveClass('leaving')
    await later(INK + 100)
    expect(top.isConnected).toBe(true)
    expect(top.parentElement).toHaveClass('leaving')
    await later(LEAVE + 100)
    expect(top.isConnected).toBe(false)
  })

  it('moves a ticked parent\'s open subtask to the top level as the parent leaves', async () => {
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [parent, child] : []))
    setup()
    await screen.findByText('Book flight')
    const top = rowOf('Trip planning')
    tickRow(top)
    await later(INK + 100)
    expect(top.parentElement).toHaveClass('leaving')
    const sub = rowOf('Book flight')
    expect(sub.closest('.leaving')).toBeNull()
    expect(sub.closest('[inert]')).toBeNull()
    expect(within(sub).getByRole('button', { name: 'Toggle complete' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('keeps an open subtask with its parent when completed tasks are shown', async () => {
    // Its next place is under the parent in "Completed": one move, not two.
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [parent, child] : []))
    setup('list', true)
    await screen.findByText('Book flight')
    const sub = rowOf('Book flight')
    tickRow(rowOf('Trip planning'))
    await later(INK + 100)
    expect(rowOf('Book flight')).toBe(sub)
    await later(LEAVE + 200)
    expect(screen.getByText('Book flight')).toBeInTheDocument()
    expect(within(rowOf('Book flight')).getByRole('button', { name: 'Toggle complete' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('keeps a subtask ticked during its parent\'s leave out of the fading parent', async () => {
    m.tasks.mockImplementation(async (id: string) => (id === 'l1' ? [parent, child] : []))
    setup()
    await screen.findByText('Book flight')
    tickRow(rowOf('Trip planning'))
    await later(INK + 100)
    const sub = rowOf('Book flight')
    expect(sub.closest('.leaving')).toBeNull()
    tickRow(sub)
    await later(50)
    expect(rowOf('Book flight')).toBe(sub)
    expect(sub.closest('.leaving')).toBeNull()
    expect(sub).toHaveClass('done')
  })

  it('keeps a day card, ticked and struck, then folds it away', async () => {
    m.tasks.mockImplementation(async (id: string) => (id === 'l1'
      ? [task({ uid: 'd1', summary: 'Due today', due: today() })] : []))
    const { container } = setup('day3')
    const card = (await screen.findByText('Due today')).closest('.day-card') as HTMLElement
    expect(pane(container).querySelector('.day-col.today .count')).toHaveTextContent('1')
    m.complete.mockResolvedValue(task({ uid: 'd1', summary: 'Due today', due: today(),
      completed: true, status: 'COMPLETED' }))
    fireEvent.click(within(card).getByRole('button', { name: 'Toggle complete' }))
    expect(card.isConnected).toBe(true)
    expect(card).toHaveClass('done')
    expect(card).toHaveAttribute('draggable', 'false')
    expect(pane(container).querySelector('.day-col.today .count')).toBeNull()
    await later(INK + 100)
    expect(card).toHaveClass('leaving')
    await later(LEAVE + 100)
    expect(card.isConnected).toBe(false)
  })

  it('lets a row go at once under reduced motion', async () => {
    for (const k of Object.keys(TOKENS)) document.documentElement.style.setProperty(k, '0s')
    setup()
    await screen.findByText('Alpha')
    const row = rowOf('Alpha')
    tickRow(row)
    expect(row.isConnected).toBe(false)
  })

  it('leaves the presets as they were: the row goes at once', async () => {
    document.documentElement.removeAttribute('data-surface')
    setup()
    await screen.findByText('Alpha')
    const row = rowOf('Alpha')
    tickRow(row)
    expect(row.isConnected).toBe(false)
  })
})
