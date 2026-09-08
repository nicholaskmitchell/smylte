/**
 * Stage 4 of the audit backlog: user-visible correctness and rendering.
 *
 * **Stage 4 is CLOSED.** These began as `it.fails` pins and the findings are
 * fixed and ticked in docs/AUDIT.md, so these are ordinary regression tests that
 * must stay green.
 *
 * They are also all BEHAVIOURAL now. Ten of them were originally structural —
 * they read the component source and asserted the shape that caused the defect —
 * on the mistaken belief that no drag/data-provider test harness existed. One
 * does, and is used throughout `TasksView.test.tsx`. That mistake cost something
 * real: six of those pins failed to recognise their own fix, because the fix
 * used a different helper name, a different CSS class, or a different approach
 * than the pin had guessed. A pin that only accepts the repair you imagined is
 * not a regression test.
 *
 * Where a component had no test file (TaskModal, SchedulingView) these are the
 * first, so they cover the finding rather than the component as a whole.
 */
import { useState } from 'react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { isValidValue } from './appearance'
import { sortTasks } from './order'
import { DataProvider, useTaskData } from './data'
import { TaskModal } from './components/TaskModal'
import { SchedulingView } from './components/SchedulingView'
import { api, type List, type Task } from './api'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, parked: false, parked_at: null,
  priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  // Present on every DTO the server sends; see api.ts's Task.
  completed_at: null, kanban_column: null, estimated_minutes: null, notify_minutes_before: null, has_rrule: false,
  created: null, last_modified: null,
 
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const list: List = {
  id: 'l1', href: '/l1/', name: 'Work', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#D9480F',
}

const CREATED = {
  token: 'tok-new', title: 'Intro call', description: null, calendar: 'c1',
  calendar_name: 'Work', duration_minutes: 30, timezone: 'UTC',
  availability: { '0': ['09:00-17:00'] }, show_busy: false, buffer_minutes: 0,
  min_notice_hours: 24, horizon_days: 30, enabled: true, booking_count: 0,
  calendar_missing: false, url: 'https://x/book/tok-new',
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
})

// ── appearance ─────────────────────────────────────────────────────────────

describe('stage 4 — appearance', () => {
  // AUDIT closed: appearance.ts:289
  it('rejects a word that is not a real CSS colour', () => {
    // `isColor` accepted /^[a-z]{3,20}$/i wholesale, so a typo was stored and
    // written into the CSSOM, where the browser dropped it — blanking that token
    // with nothing in the editor to say why.
    for (const bad of ['notacolour', 'bluu', 'reddish', 'chartruse']) {
      expect(isValidValue('color', bad)).toBe(false)
    }
  })

  it('still accepts every form a real value takes', () => {
    // `var(--x)` used to be in this list and is now REFUSED, deliberately: the
    // 2026-08-19 sweep's isColor finding names `var(--serif)` as a defect of the
    // same class, and `--x` is not a token at all. A var() naming anything but a
    // COLOUR token resolves to garbage and the declaration is dropped at
    // computed-value time — the very failure this describe block exists for.
    // `var(--accent)` is the legitimate form and stays valid. Recorded as a
    // supersession in docs/AUDIT.md rather than quietly edited.
    for (const ok of ['transparent', 'currentColor', 'red', 'rebeccapurple',
                      '#abc', '#aabbccdd', 'oklch(0.7 0.1 250)', 'var(--accent)']) {
      expect(isValidValue('color', ok)).toBe(true)
    }
    expect(isValidValue('color', 'var(--x)')).toBe(false)
  })
})

// ── ordering ───────────────────────────────────────────────────────────────

describe('stage 4 — task order', () => {
  // AUDIT closed: data.tsx:457 -> order.ts
  it('places a task created after a drag by its due date, not at the bottom', () => {
    // A drag renumbers the whole account, so afterwards a null position means
    // "created since the last drag". Sinking those buried every new task at the
    // bottom of every view.
    const placed = [
      task({ uid: 'a', sort_order: 1, due: '2026-01-10' }),
      task({ uid: 'b', sort_order: 2, due: '2026-03-10' }),
      task({ uid: 'c', sort_order: 3, due: '2026-05-10' }),
    ]
    const fresh = task({ uid: 'new', due: '2026-02-01' })
    expect(sortTasks([...placed, fresh]).map((t) => t.uid))
      .toEqual(['a', 'new', 'b', 'c'])
  })

  it('still honours a drag exactly — placed rows keep their order', () => {
    // The control. Threading a new task through must not reshuffle the ones the
    // user placed by hand, even where their due dates disagree with the order.
    const out = sortTasks([
      task({ uid: 'a', sort_order: 1, due: '2026-12-01' }),
      task({ uid: 'b', sort_order: 2, due: '2026-01-01' }),
      task({ uid: 'new', due: '2026-06-01' }),
    ]).map((t) => t.uid)
    expect(out.filter((u) => u !== 'new')).toEqual(['a', 'b'])
  })
})

// ── the task data provider ─────────────────────────────────────────────────

/** A probe that exposes the provider's actions to the test. */
function Probe({ onReady }: { onReady: (d: ReturnType<typeof useTaskData>) => void }) {
  const d = useTaskData()
  onReady(d)
  return <div data-testid="order">{d.tasks.map((t) => `${t.uid}:${t.sort_order ?? '-'}`).join(' ')}</div>
}

describe('stage 4 — task data provider', () => {
  // AUDIT closed: data.tsx:465
  it('a failed reorder restores positions without discarding a concurrent write', async () => {
    // The rollback snapshotted the WHOLE array, so an SSE update or an edit from
    // another tab that landed while the reorder was in flight was reverted with
    // it — silently undoing a write the user had just made.
    m.lists.mockResolvedValue([list])
    m.tasks.mockResolvedValue([
      task({ uid: 'a', sort_order: 1, summary: 'A' }),
      task({ uid: 'b', sort_order: 2, summary: 'B' }),
    ])
    let never: (v: unknown) => void = () => {}
    m.reorderTasks.mockReturnValue(new Promise((_, rej) => { never = rej }))

    let d!: ReturnType<typeof useTaskData>
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <Probe onReady={(x) => { d = x }} />
      </DataProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('order').textContent).toContain('a:1'))

    // `reorder` takes the ROWS as of the 2026-08-25 stage 3 fix — a uid alone is
    // ambiguous once one is copied into a second list — and, since subtasks
    // became reorderable, the RUN they are displayed in as well: a drag is
    // measured in the sequence on screen, and only the caller knows whether that
    // is the pane's top-level rows or one parent's subtasks. Only the ARGUMENT
    // SHAPE changes here; the tasks named, the gesture and every assertion below
    // are untouched.
    const moving = d.reorder(d.tasks,
                             task({ uid: 'b', sort_order: 2, summary: 'B' }),
                             task({ uid: 'a', sort_order: 1, summary: 'A' }))
    // A concurrent write lands mid-flight — an ordinary edit, which the provider
    // applies to the same array the rollback was about to overwrite.
    m.patchTask.mockResolvedValue(
      task({ uid: 'a', sort_order: 1, summary: 'A (edited)' }))
    await d.saveDetail(task({ uid: 'a', sort_order: 1, summary: 'A' }),
                       { summary: 'A (edited)' })
    never(new Error('boom'))
    await moving.catch(() => {})

    await waitFor(() => {
      expect(d.tasks.find((t) => t.uid === 'a')?.sort_order).toBe(1)   // rolled back
      expect(d.tasks.find((t) => t.uid === 'a')?.summary).toBe('A (edited)')  // kept
    })
  })
})

// ── modals ─────────────────────────────────────────────────────────────────

describe('stage 4 — TaskModal', () => {
  const props = {
    task: null, lists: [list], defaultList: 'l1',
    onClose: vi.fn(), onCreate: vi.fn(), onSave: vi.fn(),
    onDelete: vi.fn(), onMultiple: vi.fn(),
  }

  // AUDIT closed: TaskModal.tsx:118
  it('does not close when a drag-select started inside is released on the scrim', async () => {
    const onClose = vi.fn()
    const { container } = render(<TaskModal {...props} onClose={onClose} />)
    const scrim = container.querySelector('.overlay')!
    const dialog = container.querySelector('.modal')!

    // Press inside the form, release on the scrim — what selecting text does.
    fireEvent.mouseDown(dialog)
    fireEvent.click(scrim)
    expect(onClose).not.toHaveBeenCalled()
  })

  it('still closes on a genuine scrim click', async () => {
    const onClose = vi.fn()
    const { container } = render(<TaskModal {...props} onClose={onClose} />)
    const scrim = container.querySelector('.overlay')!
    fireEvent.mouseDown(scrim)
    fireEvent.click(scrim)
    expect(onClose).toHaveBeenCalled()
  })
})

describe('stage 4 — booking-link editor', () => {
  /** The editor is a subcomponent of SchedulingView; render it via the view. */
  function openEditor() {
    m.schedulingLinks.mockResolvedValue([])
    m.calendars.mockResolvedValue([
      { ...list, id: 'c1', name: 'Cal', is_calendar: true, is_task_list: false }])
    m.schedulingBookings.mockResolvedValue([])
    return render(<SchedulingView rev={0} onExpire={vi.fn()} />)
  }

  // AUDIT closed: SchedulingView.tsx:348 and :235 — covered together because
  // both are properties of the same editor dialog.
  it('publishes one link for a double-click, and is a dialog Escape closes', async () => {
    const user = userEvent.setup()
    openEditor()
    await user.click(await screen.findByRole('button', { name: 'New link' }))

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')

    await user.type(screen.getByPlaceholderText('30-minute intro call'), 'Intro call')
    const create = screen.getByRole('button', { name: /create link/i })
    let resolve: () => void = () => {}
    // Resolves with a REAL link, not `{}`. The empty object resolved truthily,
    // so the list rendered a card with `key={undefined}` and a
    // `/book/undefined` URL — the React key warning this file printed while
    // passing. Nothing here asserted the created link renders, which is why a
    // stand-in that the real API never returns went unnoticed.
    m.createSchedulingLink.mockReturnValue(
      new Promise((r) => { resolve = () => r(CREATED as never) }))

    await user.click(create)
    await user.click(create)                      // the second click, mid-flight
    expect(m.createSchedulingLink).toHaveBeenCalledTimes(1)
    resolve()

    // The half nothing asserted: the published link has to appear in the list,
    // with its real token. With the old `{}` stand-in this rendered a card keyed
    // `undefined` showing `/book/undefined`, and the suite passed anyway.
    // (The card shows the server's absolute `url` when the DTO carries one —
    // the 2026-09-03 sweep, SchedulingView.tsx `publicUrl` — and this fixture
    // always has.)
    expect(await screen.findByText('https://x/book/tok-new')).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})
