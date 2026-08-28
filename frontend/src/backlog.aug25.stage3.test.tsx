/**
 * The 2026-08-25 sweep, stage 3: silent data corruption in the SPA.
 *
 * Nothing raises, nothing is logged, and the answer is quietly wrong. Both
 * closed backlogs call this the dangerous stage and `backlog.aug19.stage3`'s
 * header names the theme exactly: *state that overwrites or discards the user's
 * real data without saying so*. Nine of the stage's twelve findings are here;
 * the other three are backend and live in
 * `backend/tests/test_backlog_aug25_stage3.py`.
 *
 * **These findings are CLOSED**, and every test here is now an ordinary
 * regression test that must stay green. Each pin was written first as
 * `it.fails` — asserting the CORRECTED behaviour, green while the bug was open
 * and red the moment it was fixed — and its marker was dropped in the commit
 * that fixed it. The CONTROLS beside them were always ordinary passing tests:
 * the feature still works, beside every pin whose cheap over-correction would
 * satisfy it by deleting the feature.
 *
 * Tests added DURING remediation sit beside the originals and say so in their
 * own comments. Each exists because a MUTATION escaped: every fix was run
 * against two to five deliberately wrong versions of itself, and whatever
 * survived got a test rather than a comment. Several of the findings turned out
 * to have a second manifestation, or a second half, that no pin could see —
 * reorder's target lookup, `CapacityStep`, the ORDER of a DURATION's two halves,
 * the scope of the add box's retry ref.
 *
 * Every pin is BEHAVIOURAL: each drives the real component (or the real exported
 * function) and asserts what the user or the API would see. None reads source
 * text. Where a finding has more than one correct repair the assertion names the
 * OUTCOME rather than the repair — three here genuinely do, and STAGES.md
 * records what pins that only accept the fix their author imagined have cost.
 *
 * The api-mocking preamble is `backlog.aug19.stage3.test.tsx`'s, which is
 * `backlog.stage4.test.tsx`'s. The suite runs pinned to America/New_York
 * (vite.config.ts), which is what makes the DURATION pin's spring-forward real.
 */
import { readFileSync } from 'node:fs'
import { useState } from 'react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DataProvider } from './data'
import { setCacheUser } from './cache'
import { durationMs, endFromDuration } from './calendar'
import { CalendarView } from './components/CalendarView'
import { HomeView } from './components/HomeView'
import { SchedulingView } from './components/SchedulingView'
import { TasksView } from './components/TasksView'
import { TodayView } from './components/TodayView'
import { DEFAULT_LAYOUT, type DashboardModule } from './dashboard'
import { api, HttpError, type BookingLink, type CalEvent, type DayEntry, type DayPlan,
  type List, type Task } from './api'

vi.mock('./api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('./api')>()
  const mocked = Object.fromEntries(Object.keys(mod.api).map((k) => [k, vi.fn()]))
  return { ...mod, api: mocked, subscribe: vi.fn(() => () => {}) }
})
const m = vi.mocked(api)

// ── fixtures ───────────────────────────────────────────────────────────────

const task = (o: Partial<Task> = {}): Task => ({
  uid: 'u1', list: 'l1', summary: 'Ship it', notes: null, status: 'NEEDS-ACTION',
  completed: false, cancelled: false, priority: null, priority_label: 'none',
  percent_complete: null, due: null, due_is_date: true, start: null, start_is_date: true,
  tags: [], parent: null, children: [], child_count: 0, completed_child_count: 0,
  derived_percent: null, pinned: false, sort_order: null,
  completed_at: null, kanban_column: null, estimated_minutes: null, has_rrule: false,
  created: null, last_modified: null,
  href: '/l1/u1.ics', etag: '"1"', ...o,
})

const home: List = {
  id: 'l1', href: '/l1/', name: 'Home', is_task_list: true, is_calendar: false,
  open_count: 0, task_count: 0, event_count: 0, total: 0, color: '#D9480F',
}
const work: List = { ...home, id: 'l2', href: '/l2/', name: 'Work', color: '#1565C0' }
const cal: List = {
  id: 'c1', href: '/c1/', name: 'Personal', is_task_list: false, is_calendar: true,
  open_count: 0, task_count: 0, event_count: 1, total: 1, color: '#1971C2',
}

const ev = (o: Partial<CalEvent> = {}): CalEvent => ({
  uid: 'u1', id: 'u1', recurrence_id: null, is_recurring: false, calendar: '/c1/',
  summary: 'Standup', description: null, location: null,
  start: '2026-03-02T09:00:00', start_is_date: false,
  end: '2026-03-02T09:30:00', end_is_date: false, duration: null,
  all_day: false, status: null, busy: true, tags: [], has_rrule: false,
  href: '/c1/u1.ics', etag: '"1"', ...o,
})

/** A recurring occurrence, as the expander hands one to the grid. */
const occurrence = (o: Partial<CalEvent> = {}) => ev({
  id: 'u1::2026-03-09T09:00:00', recurrence_id: '2026-03-09T09:00:00',
  is_recurring: true, has_rrule: true,
  start: '2026-03-09T09:00:00', end: '2026-03-09T09:30:00', ...o,
})

const link = (o: Partial<BookingLink> = {}): BookingLink => ({
  token: 'tok-a', title: 'Intro call', description: null, calendar: 'c1',
  calendar_name: 'Personal', calendar_missing: false, duration_minutes: 30,
  timezone: 'UTC', availability: { '0': ['09:00-17:00'] }, show_busy: false,
  buffer_minutes: 0, min_notice_hours: 24, horizon_days: 30, enabled: true,
  booking_count: 0, created_at: '2026-08-01T08:00:00.000Z',
  updated_at: '2026-08-01T08:00:00.000Z', ...o,
})

const pad = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const today = () => ymd(new Date())

const dayEntry = (o: Partial<DayEntry> = {}): DayEntry => ({
  entry_id: 'e1', day: today(), kind: 'note', list: null, uid: null,
  title: 'Water the plants', source: 'user', position: 1,
  done_at: null, dropped_at: null, habit_id: null, estimate_minutes: null,
  rolled_to: null, created_at: '2026-08-21T08:00:00.000Z', ...o,
})

const plan = (entries: DayEntry[] = [], day = today(), o: Partial<DayPlan> = {}): DayPlan => ({
  day, planned: true, entries, capacity_minutes: null, capacity: null,
  committed_at: null, shutdown_at: null, reflection: null, ...o,
})

let errSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  vi.clearAllMocks()
  // No cache user, so nothing seeds from the disk mirror and each test is cold.
  setCacheUser('')
  localStorage.clear()
  m.me.mockResolvedValue({ authenticated: true, user: 'owner' })
  m.getSettings.mockResolvedValue({})
  m.putSettings.mockResolvedValue({})
  m.lists.mockResolvedValue([])
  m.tasks.mockResolvedValue([])
  m.calendars.mockResolvedValue([])
  m.events.mockResolvedValue([])
  m.schedulingLinks.mockResolvedValue([])
  m.schedulingBookings.mockResolvedValue([])
  m.openDay.mockResolvedValue(plan())
  m.day.mockImplementation(async (d) => plan([], d))
  m.days.mockResolvedValue([])
  m.habits.mockResolvedValue([])
  m.patchDay.mockImplementation(async (d, body) => plan([], d, body as Partial<DayPlan>))
  m.patchEvent.mockResolvedValue(ev())
  m.createEvent.mockResolvedValue(ev())
  m.deleteEvent.mockResolvedValue(null)
  // `makeGuard` logs every non-401 failure; three pins below deliberately
  // reject one call, and the log is noise rather than signal here.
  errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => errSpy.mockRestore())

// ════════════════════════════════════════════════════════════════════════════
// SchedulingView — the booking-link list
// ════════════════════════════════════════════════════════════════════════════

describe('2026-08-25 — a failed booking-link toggle', () => {
  const cards = () => [...document.querySelectorAll('.sched-card')] as HTMLElement[]
  const boxes = () =>
    cards().map((c) => c.querySelector('input[type=checkbox]') as HTMLInputElement)

  // ── AUDIT (open): SchedulingView.tsx:83 — a failed booking-link toggle rolls
  //    back a whole-array snapshot, reverting a concurrent toggle the server
  //    accepted ──────────────────────────────────────────────────────────────
  it('rolls back only the link that failed', async () => {
    // EVIDENCE. `toggleEnabled` captures `const prev = links` — the ENTIRE array
    // as of that render — and on failure does `setLinks(prev)`. Any write that
    // landed while the first request was in flight is inside that snapshot in
    // its OLD state, so a failure on one link silently un-does a successful
    // change to a different one. `remove` (line 89) has the identical shape.
    //
    // Reproduced: two links, both live. Tap A's toggle (its PATCH hangs), then
    // tap B's (its PATCH resolves — the server now has B off). Both boxes read
    // off. A's PATCH then rejects with a 502 and `setLinks(prev)` restores
    // `[A(on), B(on)]`. Measured box state after: `[true, true]`; correct is
    // `[true, false]`. The owner is now looking at a link labelled "Live" that
    // the server has switched off — and if they "fix" it by toggling it, they
    // turn it back ON. Nothing refetches to correct the screen.
    //
    // ASSERTED AS THE OUTCOME: B's accepted state survives A's failure. A
    // per-row functional rollback, a refetch, or holding the second write until
    // the first settles all satisfy it.
    m.schedulingLinks.mockResolvedValue([
      link({ token: 'tok-a', title: 'A' }),
      link({ token: 'tok-b', title: 'B' }),
    ])
    let rejectA: (e: Error) => void = () => {}
    m.patchSchedulingLink.mockImplementation(async (token: string, body) => {
      if (token === 'tok-a') {
        return new Promise((_res, rej) => { rejectA = rej }) as Promise<never>
      }
      return link({ token, ...body }) as never
    })

    const user = userEvent.setup()
    render(<SchedulingView rev={0} onExpire={vi.fn()} />)
    await waitFor(() => expect(cards()).toHaveLength(2))

    await user.click(boxes()[0])            // A: hangs
    await user.click(boxes()[1])            // B: the server accepts it
    await waitFor(() => expect(boxes()[1].checked).toBe(false))

    await act(async () => {
      rejectA(new HttpError(502, 'bad gateway'))
      await Promise.resolve()
    })
    await waitFor(() => expect(boxes()[0].checked).toBe(true))

    expect(boxes().map((b) => b.checked)).toEqual([true, false])
  })

  // The finding names `remove` too — "line 89 has the identical shape" — and it
  // is not pinned, so it gets a test rather than an inference. A delete that
  // fails must put back ONE link, at its place, without resurrecting a link
  // deleted while it was in flight. Deleting goes through the editor: Edit,
  // Delete, "Really delete?".
  it('puts back only the link whose delete failed, where it was', async () => {
    m.schedulingLinks.mockResolvedValue([
      link({ token: 'tok-a', title: 'A' }),
      link({ token: 'tok-b', title: 'B' }),
      link({ token: 'tok-c', title: 'C' }),
    ])
    let rejectA: (e: Error) => void = () => {}
    m.deleteSchedulingLink.mockImplementation(async (token: string) => {
      if (token === 'tok-a') return new Promise((_r, rej) => { rejectA = rej }) as Promise<never>
      return null as never
    })

    const user = userEvent.setup()
    render(<SchedulingView rev={0} onExpire={vi.fn()} />)
    await waitFor(() => expect(cards()).toHaveLength(3))

    const titles = () =>
      cards().map((c) => c.querySelector('.sched-card-title')?.textContent)
    const deleteCard = async (title: string) => {
      const card = cards().find((c) =>
        c.querySelector('.sched-card-title')?.textContent === title)!
      await user.click([...card.querySelectorAll('button')]
        .find((b) => b.textContent === 'Edit')!)
      await user.click(await screen.findByRole('button', { name: 'Delete' }))
      await user.click(await screen.findByRole('button', { name: 'Really delete?' }))
    }

    await deleteCard('A')                          // hangs
    await waitFor(() => expect(titles()).toEqual(['B', 'C']))
    await deleteCard('B')                          // accepted
    await waitFor(() => expect(titles()).toEqual(['C']))

    await act(async () => {
      rejectA(new HttpError(502, 'bad gateway'))
      await Promise.resolve()
    })

    // Not ['A', 'B', 'C']: B's delete was accepted and must stay gone. And A
    // comes back FIRST — appending it would put the owner's link somewhere they
    // did not leave it, which is the same "close enough" the snapshot was.
    await waitFor(() => expect(titles()).toEqual(['A', 'C']))
  })

  // Not pinned either, and the reason the rollback restores one FIELD rather
  // than the row: the same link can be EDITED while its toggle is in flight, and
  // the editor replaces the row with the server's DTO. Putting the pre-tap row
  // back wholesale reverts that edit — the finding's own defect, one level down.
  it('keeps an edit that landed while the same link\'s toggle was in flight', async () => {
    m.schedulingLinks.mockResolvedValue([link({ token: 'tok-a', title: 'A' })])
    let rejectToggle: (e: Error) => void = () => {}
    m.patchSchedulingLink.mockImplementation(async (token: string, body: any) => {
      if (Object.keys(body).length === 1 && 'enabled' in body) {
        return new Promise((_r, rej) => { rejectToggle = rej }) as Promise<never>
      }
      return link({ token, ...body }) as never
    })

    const user = userEvent.setup()
    render(<SchedulingView rev={0} onExpire={vi.fn()} />)
    await waitFor(() => expect(cards()).toHaveLength(1))

    await user.click(boxes()[0])                   // the toggle hangs
    await user.click([...cards()[0].querySelectorAll('button')]
      .find((b) => b.textContent === 'Edit')!)
    const title = await screen.findByLabelText('Title')
    await user.clear(title)
    await user.type(title, 'A renamed')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(
      cards()[0].querySelector('.sched-card-title')?.textContent).toBe('A renamed'))

    await act(async () => {
      rejectToggle(new HttpError(502, 'bad gateway'))
      await Promise.resolve()
    })

    await waitFor(() => expect(boxes()[0].checked).toBe(true))
    expect(cards()[0].querySelector('.sched-card-title')?.textContent).toBe('A renamed')
  })

  // CONTROL (passes today, must keep passing). A toggle the server ACCEPTS
  // still sticks. The cheap over-correction for the pin above is to stop
  // rolling anything back at all — or to refetch so eagerly that the optimistic
  // paint is undone — and either would satisfy it while making the control read
  // whatever the stale fetch answers.
  it('leaves an accepted toggle switched', async () => {
    m.schedulingLinks.mockResolvedValue([link({ token: 'tok-a', title: 'A' })])
    m.patchSchedulingLink.mockImplementation(async (token: string, body) =>
      link({ token, ...body }) as never)

    const user = userEvent.setup()
    render(<SchedulingView rev={0} onExpire={vi.fn()} />)
    await waitFor(() => expect(cards()).toHaveLength(1))

    await user.click(boxes()[0])
    await waitFor(() => expect(m.patchSchedulingLink).toHaveBeenCalledWith(
      'tok-a', { enabled: false }))
    expect(boxes()[0].checked).toBe(false)
  })
})

// ════════════════════════════════════════════════════════════════════════════
// HomeView — the dashboard drag
// ════════════════════════════════════════════════════════════════════════════

describe('2026-08-25 — an aborted dashboard drag', () => {
  // jsdom implements no pointer capture, and `onPointerDown` calls it
  // unconditionally — without these the handler throws before a drag ever
  // starts, `drag.current` stays null, and BOTH tests below report "nothing was
  // committed", which is the pin's own passing condition. The uncaught
  // TypeError is the only thing that gives it away, and vitest reports that as
  // an unhandled error rather than a failure.
  beforeEach(() => {
    Element.prototype.setPointerCapture = vi.fn()
    Element.prototype.releasePointerCapture = vi.fn()
    Element.prototype.hasPointerCapture = vi.fn(() => false)
  })

  const TWO: DashboardModule[] = [
    { id: 'a', kind: 'today', x: 0, y: 0, w: 4, h: 6 },
    { id: 'b', kind: 'overdue', x: 4, y: 0, w: 4, h: 5 },
  ]

  /** Mount, enter Arrange mode, and give the grid a real width.
   *
   *  The width is not decoration. `onPointerMove` early-returns on
   *  `!gridRef.current?.clientWidth`, and EVERY element in jsdom reports 0 —
   *  so without this stub no preview is ever computed, the commit-on-cancel
   *  branch is never reached, and the pin below would pass green against
   *  unfixed code. That is the failure mode stage 2 hit four times over, and
   *  the control beside the pin is what proves this stub works.
   */
  async function arrange() {
    const onLayoutChange = vi.fn()
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <HomeView rev={0} onExpire={vi.fn()} layout={TWO} onLayoutChange={onLayoutChange} />
      </DataProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Arrange' }))
    const grid = document.querySelector('.dash-grid') as HTMLElement
    Object.defineProperty(grid, 'clientWidth', { value: 1200, configurable: true })
    const head = [...document.querySelectorAll('.dash-mod-head')][1] as HTMLElement
    return { onLayoutChange, grid, head }
  }

  /** Press on `b`'s header and drag two columns right and four rows down. */
  const dragTwoColumns = (grid: HTMLElement, head: HTMLElement) => {
    fireEvent.pointerDown(head, { pointerId: 1, clientX: 500, clientY: 20 })
    fireEvent.pointerMove(grid, { pointerId: 1, clientX: 700, clientY: 200 })
  }

  // CONTROL FIRST, and it is load-bearing rather than decorative: it is the only
  // thing that proves the harness can produce a preview at all. If this fails,
  // the `clientWidth` stub is wrong and the pin below is worthless.
  it('commits a gesture the user actually finished', async () => {
    const { onLayoutChange, grid, head } = await arrange()
    dragTwoColumns(grid, head)
    fireEvent.pointerUp(grid, { pointerId: 1, clientX: 700, clientY: 200 })

    expect(onLayoutChange).toHaveBeenCalledTimes(1)
    const next = onLayoutChange.mock.calls[0][0] as DashboardModule[]
    expect(next.find((mo) => mo.id === 'b')!.x).not.toBe(4)
  })

  // ── AUDIT (open): HomeView.tsx:265 — a cancelled pointer gesture COMMITS the
  //    half-finished dashboard drag instead of discarding it ─────────────────
  it('discards a gesture the platform cancelled', async () => {
    // EVIDENCE. `onPointerCancel={endDrag}` and `endDrag` commits:
    // `if (preview) commit(preview)`. A `pointercancel` means the gesture was
    // ABORTED by the platform, not completed, so the module is written to
    // wherever the pointer happened to be when the browser took over — and
    // `commit` calls `onLayoutChange`, which App persists with
    // `saveSettingsSoon({dashboard})`. The comment above the sibling effect says
    // a cancelled gesture "must not leave the layout stuck in preview", which is
    // what the author intended; committing satisfies the letter and inverts the
    // meaning.
    //
    // Not theoretical on touch: nothing in app.css sets `touch-action` anywhere,
    // and `preventDefault()` on pointerdown does not suppress a browser pan.
    // Arrange mode is gated on `useIsMobile` (max-width: 720px), so every touch
    // device WIDER than that — an iPad in landscape at 1180px, a Surface, a
    // touchscreen laptop — gets Arrange mode with drags the browser will steal
    // for a scroll of the enclosing `.scroll` container, firing pointercancel
    // every time. Measured with this layout and a 1200px grid: pointerDown on
    // b's header at (500,20), pointerMove to (700,200), then pointerCancel ->
    // `onLayoutChange` called once with b moved from column 4 to column 6, and
    // that arrangement written to /api/settings.
    //
    // ASSERTED AS THE OUTCOME: nothing is persisted. Splitting the handlers is
    // the obvious repair and not the only one.
    const { onLayoutChange, grid, head } = await arrange()
    dragTwoColumns(grid, head)
    fireEvent.pointerCancel(grid, { pointerId: 1, clientX: 700, clientY: 200 })

    expect(onLayoutChange).not.toHaveBeenCalled()
  })

  // Not pinned, and the other thing a cancel has to do: the sibling effect's
  // comment says an aborted gesture "must not leave the layout stuck in
  // preview", and clearing `drag.current` alone satisfies the pin (nothing is
  // persisted) while leaving the module PAINTED two columns over until the user
  // leaves Arrange mode. On screen that is indistinguishable from a move that
  // took, and the next thing they do is drag it back.
  it('un-paints a gesture the platform cancelled', async () => {
    const { grid, head } = await arrange()
    const box = () => (grid.querySelectorAll('.dash-mod')[1] as HTMLElement).style.left
    const before = box()
    dragTwoColumns(grid, head)
    expect(box(), 'the drag never previewed').not.toBe(before)

    fireEvent.pointerCancel(grid, { pointerId: 1, clientX: 700, clientY: 200 })
    expect(box()).toBe(before)
  })

  // The other half of the fix, and not pinned: the cancel should not be reached
  // in the first place. `touch-action: none` on the drag handles is the only
  // thing that stops a browser claiming a downward drag as a pan of the
  // enclosing `.scroll` — `preventDefault()` on pointerdown does not, which the
  // finding says in as many words. jsdom applies no stylesheet, so this is read
  // off app.css rather than off a computed style: the assertion is that the rule
  // EXISTS and is scoped to arrange mode, which is what a reviewer would check.
  it('opts the drag handles out of browser touch gestures while arranging',
    async () => {
      // Comments STRIPPED first. The prose above the rule names the selectors
      // and says "scoped to `.arranging`", so matching against the raw file made
      // every assertion below true of the comment rather than of the CSS — a
      // mutation that dropped the scoping passed until this line was added.
      const css = readFileSync('src/styles/app.css', 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
      const rule = css.match(
        /([^}]*)\{[^}]*touch-action:\s*none[^}]*\}/)?.[1] ?? ''
      expect(rule, 'no touch-action: none anywhere in app.css').not.toBe('')
      for (const sel of ['.dash-mod-head', '.dash-grip']) {
        expect(rule, `${sel} can still be stolen for a pan`).toContain(sel)
      }
      expect(rule, 'touch-action is not scoped to arrange mode, so reading a '
        + 'module with a finger no longer scrolls').toContain('.arranging')
    })

  // CONTROL for the rule above: ordinary (non-arranging) module bodies must NOT
  // be covered, or a finger can no longer scroll the dashboard at all.
  it('leaves an unarranged dashboard scrollable with a finger', async () => {
    const css = readFileSync('src/styles/app.css', 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
    for (const m of css.matchAll(/([^{}]*)\{[^}]*touch-action:\s*none[^}]*\}/g)) {
      expect(m[1], 'touch-action: none on a selector that is not a drag handle')
        .toMatch(/\.dash-mod-head|\.dash-grip/)
    }
  })
})

// ════════════════════════════════════════════════════════════════════════════
// TasksView / data.tsx — drag-to-reorder
// ════════════════════════════════════════════════════════════════════════════

describe('2026-08-25 — reordering with one uid in two lists', () => {
  const rowTitles = () =>
    [...document.querySelectorAll('.task:not(.sub) .task-title')]
      .map((n) => n.textContent?.trim())

  const wrapFor = (title: string) =>
    screen.getByText(title).closest('.task-drag') as HTMLElement

  const dragOnto = (from: string, to: string) => {
    // jsdom builds no DataTransfer; the wrapper's onDragStart calls setData.
    // `mousedown` first, on the title, because that is the order a browser
    // produces and the wrapper's text-field guard reads it.
    const dataTransfer = { setData: vi.fn(), getData: vi.fn(), effectAllowed: '' }
    fireEvent.mouseDown(screen.getByText(from))
    fireEvent.dragStart(wrapFor(from), { dataTransfer })
    fireEvent.drop(wrapFor(to), { dataTransfer })
  }

  /** Answer each list with ITS OWN rows. See the note in the pin below. */
  const seedTasks = (rows: Task[]) =>
    m.tasks.mockImplementation(async (listId: string) =>
      rows.filter((t) => t.list === listId))

  function setup() {
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
  }

  // ── AUDIT (open): data.tsx:588 — drag-to-reorder resolves the dragged row by
  //    bare uid, so with one UID in two lists the wrong row moves ────────────
  it('moves the row the user dragged, not the first one sharing its uid', async () => {
    // EVIDENCE. `TasksView`'s drop handler carefully resolves both `taskKey`s
    // back to real rows and then throws the disambiguation away, passing bare
    // uids to `reorder`, which re-finds them with
    // `placed.findIndex((t) => t.uid === uid)` — FIRST-WINS across the merged
    // multi-list array. The comment at TasksView.tsx:158 claims the rows are
    // "resolved back before the wire call", but `reorder`'s signature only takes
    // uids, so nothing is actually resolved.
    //
    // The trust model treats a VTODO copied between lists in Tasks.org / DAVx5 /
    // Thunderbird as ORDINARY — the UID is preserved and the backend keys on
    // `(collection_href, uid)` — so the copy that sorts first is the one that
    // moves. `reorder` then renumbers `sort_order` for every task on the
    // account and POSTs it, so the wrong order is persisted permanently.
    //
    // Reproduced against the real components: Home(l1) holds uid X titled "A
    // home copy" and uid b titled "B second"; Work(l2) holds a COPY of uid X
    // titled "C work copy". Dragging "C work copy" onto "B second" POSTed
    // [{l1,b},{l1,X},{l2,X}] and left the screen reading
    // ["B second", "A home copy", "C work copy"] — the row the user dragged
    // never moved, an unrelated row in a different list did.
    //
    // (Second manifestation, same cause and no separate pin: dropping the Work
    // copy onto the HOME copy calls `reorder('X','X')`, hits the `uid === target`
    // early return, and the drag silently does nothing. A fix that keys on
    // `taskKey` closes both.)
    //
    // TasksView.test.tsx's whole drag-to-reorder block uses distinct uids, so
    // nothing there fails.
    m.lists.mockResolvedValue([home, work])
    // PER LIST, not one array for both. `data.tsx` fans out with
    // `lists.map((l) => api.tasks(l.id))` and concatenates, so a
    // `mockResolvedValue` answers every list with the same rows and the pane
    // renders each task twice — which is a harness fault that looks exactly like
    // the defect under test. Every other suite here has one list and never met
    // it.
    seedTasks([
      task({ uid: 'X', list: 'l1', summary: 'A home copy', href: '/l1/X.ics', sort_order: 1 }),
      task({ uid: 'b', list: 'l1', summary: 'B second', href: '/l1/b.ics', sort_order: 2 }),
      task({ uid: 'X', list: 'l2', summary: 'C work copy', href: '/l2/X.ics', sort_order: 3 }),
    ])
    m.reorderTasks.mockResolvedValue({ ok: true } as never)
    setup()
    await screen.findByText('A home copy')
    expect(rowTitles()).toEqual(['A home copy', 'B second', 'C work copy'])

    dragOnto('C work copy', 'B second')

    // Dropping on a row further UP lands before it — the gesture's documented
    // meaning, and the one `reorder` implements by reading `to` before the
    // removal.
    await waitFor(() => expect(m.reorderTasks).toHaveBeenCalled())
    expect(rowTitles()).toEqual(['A home copy', 'C work copy', 'B second'])
    expect(m.reorderTasks.mock.calls[0][0]).toEqual([
      { list: 'l1', uid: 'X' }, { list: 'l2', uid: 'X' }, { list: 'l1', uid: 'b' },
    ])
  })

  // The SECOND MANIFESTATION the pin names in passing and does not assert:
  // dropping one copy onto the other called `reorder('X','X')`, hit the
  // `uid === target` early return and did nothing at all. Keying the lookups on
  // `taskKey` while leaving that guard on the bare uid closes the pin and leaves
  // this exactly as it was, so it gets its own test rather than an inference.
  it('moves one copy onto the other, which share a uid', async () => {
    m.lists.mockResolvedValue([home, work])
    seedTasks([
      task({ uid: 'X', list: 'l1', summary: 'A home copy', href: '/l1/X.ics', sort_order: 1 }),
      task({ uid: 'b', list: 'l1', summary: 'B second', href: '/l1/b.ics', sort_order: 2 }),
      task({ uid: 'X', list: 'l2', summary: 'C work copy', href: '/l2/X.ics', sort_order: 3 }),
    ])
    m.reorderTasks.mockResolvedValue({ ok: true } as never)
    setup()
    await screen.findByText('A home copy')

    dragOnto('C work copy', 'A home copy')

    await waitFor(() => expect(m.reorderTasks).toHaveBeenCalled())
    expect(rowTitles()).toEqual(['C work copy', 'A home copy', 'B second'])
    expect(m.reorderTasks.mock.calls[0][0]).toEqual([
      { list: 'l2', uid: 'X' }, { list: 'l1', uid: 'X' }, { list: 'l1', uid: 'b' },
    ])
  })

  // The TARGET is ambiguous too, and neither test above shows it: in both, the
  // duplicated uid's first occurrence IS the row being dropped on, so a uid
  // lookup lands on the right index by luck. Here the target is the SECOND copy
  // — dropping onto it must put the row after it, not before the first copy.
  it('drops onto the second copy sharing a uid, not the first', async () => {
    m.lists.mockResolvedValue([home, work])
    seedTasks([
      task({ uid: 'X', list: 'l1', summary: 'A home copy', href: '/l1/X.ics', sort_order: 1 }),
      task({ uid: 'b', list: 'l1', summary: 'B second', href: '/l1/b.ics', sort_order: 2 }),
      task({ uid: 'X', list: 'l2', summary: 'C work copy', href: '/l2/X.ics', sort_order: 3 }),
    ])
    m.reorderTasks.mockResolvedValue({ ok: true } as never)
    setup()
    await screen.findByText('A home copy')

    dragOnto('B second', 'C work copy')

    await waitFor(() => expect(m.reorderTasks).toHaveBeenCalled())
    expect(rowTitles()).toEqual(['A home copy', 'C work copy', 'B second'])
  })

  // CONTROL for the guard that moved: dropping a row on ITSELF is still a no-op,
  // and must not renumber the account. `taskKey` equality is the whole
  // difference between this and the test above.
  it('writes nothing when a row is dropped on itself', async () => {
    m.lists.mockResolvedValue([home])
    seedTasks([
      task({ uid: 'p', list: 'l1', summary: 'Alpha', href: '/l1/p.ics', sort_order: 1 }),
      task({ uid: 'q', list: 'l1', summary: 'Bravo', href: '/l1/q.ics', sort_order: 2 }),
    ])
    m.reorderTasks.mockResolvedValue({ ok: true } as never)
    setup()
    await screen.findByText('Alpha')

    dragOnto('Bravo', 'Bravo')

    await new Promise((r) => setTimeout(r, 0))
    expect(m.reorderTasks).not.toHaveBeenCalled()
    expect(rowTitles()).toEqual(['Alpha', 'Bravo'])
  })

  // CONTROL (passes today, must keep passing). Ordinary reordering — distinct
  // uids — still moves the dragged row and still writes the whole sequence. The
  // over-correction is a `taskKey` lookup that misses and silently returns.
  it('still reorders rows whose uids are distinct', async () => {
    m.lists.mockResolvedValue([home])
    seedTasks([
      task({ uid: 'p', list: 'l1', summary: 'Alpha', href: '/l1/p.ics', sort_order: 1 }),
      task({ uid: 'q', list: 'l1', summary: 'Bravo', href: '/l1/q.ics', sort_order: 2 }),
      task({ uid: 'r', list: 'l1', summary: 'Charlie', href: '/l1/r.ics', sort_order: 3 }),
    ])
    m.reorderTasks.mockResolvedValue({ ok: true } as never)
    setup()
    await screen.findByText('Alpha')

    dragOnto('Charlie', 'Bravo')

    await waitFor(() => expect(m.reorderTasks).toHaveBeenCalled())
    expect(rowTitles()).toEqual(['Alpha', 'Charlie', 'Bravo'])
  })
})

// ════════════════════════════════════════════════════════════════════════════
// CalendarView — the event editor
// ════════════════════════════════════════════════════════════════════════════

function CalHarness() {
  const now = new Date()
  const [cursor, setCursor] = useState(() => new Date(now.getFullYear(), now.getMonth(), 1))
  const [shown, setShown] = useState<string[]>([])
  return (
    <DataProvider rev={0} onExpire={vi.fn()}>
      <CalendarView onExpire={vi.fn()} cursor={cursor} onCursorChange={setCursor}
        sideCollapsed={false} onToggleSide={vi.fn()}
        hiddenCalendars={[]} onHiddenCalendarsChange={vi.fn()}
        archivedCalendars={[]} onArchivedCalendarsChange={vi.fn()}
        calTaskLists={shown} onCalTaskListsChange={setShown}
        calShowDone={false} onCalShowDoneChange={vi.fn()} fit="dynamic" />
    </DataProvider>
  )
}

/** Open an event's edit modal by clicking its chip. */
async function openEvent(user: ReturnType<typeof userEvent.setup>, name = 'Standup') {
  await waitFor(() => expect(screen.getAllByTitle(new RegExp(`^${name}`))[0]).toBeInTheDocument())
  await user.click(screen.getAllByTitle(new RegExp(`^${name}`))[0])
  return screen.findByRole('dialog')
}

const patchBody = () => m.patchEvent.mock.calls[0][2] as Record<string, unknown>

describe('2026-08-25 — the event editor', () => {
  beforeEach(() => {
    // The grid opens on today's month, so the clock decides which fixtures
    // render. March 2026 puts the 03-08 spring-forward on screen, which the
    // DURATION pin below needs.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.setSystemTime(new Date(2026, 2, 5))
    m.calendars.mockResolvedValue([cal])
  })
  afterEach(() => { vi.useRealTimers() })

  const setup = (events: CalEvent[]) => {
    m.events.mockResolvedValue(events)
    render(<CalHarness />)
    return userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  }

  // ── AUDIT (open): CalendarView.tsx:907 — any save from the event editor
  //    splits a CATEGORIES value containing a comma into two tags ────────────
  it('keeps a category containing a comma whole across an unrelated save', async () => {
    // EVIDENCE. `EventModal` holds tags as one comma-JOINED string
    // (`useState((e?.tags || []).join(', '))`) and re-SPLITS it on every commit
    // (`tags.split(',').map(s => s.trim())`), and `commit()` sends
    // `tags: tagList()` unconditionally — even for a save that only changed the
    // title. `CATEGORIES:Home\,Garden` is a SINGLE category per RFC 5545: the
    // backend reads it correctly through icalendar's `.cats` and writes it back
    // escaped via `todo.add("CATEGORIES", list(cats))`, and `app.py:889` copies
    // `req.tags` straight onto the VEVENT, so the split really reaches the wire.
    //
    // This is exactly the defect the TASK side was fixed for — AddMultipleModal's
    // `TagInput` docstring spells it out ("any delimiter-joined text field
    // corrupts it") and TasksView has a regression test ("keeps a category
    // containing a comma whole") — but the event editor was never converted.
    //
    // Reproduced against the real component. Event with tags
    // ['Home,Garden', 'Errands']; the field reads `Home,Garden, Errands`; change
    // ONLY the title and press Save -> PATCH tags ["Home","Garden","Errands"].
    // One category has become two, permanently, on a pure rename.
    //
    // ASSERTED AS THE OUTCOME: the categories the event had survive a save that
    // did not touch them. Omitting `tags` when it is unchanged (what TaskModal
    // does) and holding each category whole in a `TagInput` both satisfy it.
    const user = setup([ev({ tags: ['Home,Garden', 'Errands'] })])
    const dialog = await openEvent(user)

    const title = within(dialog).getByLabelText('Title')
    await user.clear(title)
    await user.type(title, 'Renamed')
    await user.click(within(dialog).getByText('Save'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    const sent = patchBody()
    expect(sent.summary).toBe('Renamed')
    if ('tags' in sent) {
      expect(sent.tags).toEqual(['Home,Garden', 'Errands'])
    } else {
      expect(sent).not.toHaveProperty('tags')
    }
  })

  // CONTROL (passes today, must keep passing). An ordinary tag edit still
  // reaches the wire. The cheap over-correction for the pin above is to stop
  // sending `tags` at all, which would satisfy it by making the field inert.
  //
  // DELIBERATE TEST EDIT, recorded in AUDIT.md: the field is now the shared
  // `TagInput` chip control, so a tag is added by typing it and pressing Enter
  // rather than by rewriting a comma-joined string. This is the affordance the
  // finding's own suggested fix asks for, and it is how `TasksView.test.tsx`
  // drives the same control. What is asserted — an edited tag list reaches the
  // wire — is unchanged.
  it('still sends the tags when the user edits them', async () => {
    const user = setup([ev({ tags: ['Errands'] })])
    const dialog = await openEvent(user)

    await user.type(within(dialog).getByLabelText('Tags'), 'Admin{Enter}')
    await user.click(within(dialog).getByText('Save'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(patchBody().tags).toEqual(['Errands', 'Admin'])
  })

  // `sameValue` on top of the chip control, and what it is actually for. Once
  // tags are held whole, ALWAYS sending them is harmless to the VALUE — it is
  // the same array either way, which is why the pin above accepts both and a
  // mutation dropping this guard passes it. What it is not harmless to is the
  // WIRE: a pure rename that carries `tags` rewrites CATEGORIES on the server,
  // overwriting a tag edit another CalDAV client made since this modal opened.
  // TaskModal omits unchanged fields for exactly that reason.
  it('sends no tags at all on a save that did not touch them', async () => {
    const user = setup([ev({ tags: ['Home,Garden', 'Errands'] })])
    const dialog = await openEvent(user)

    const title = within(dialog).getByLabelText('Title')
    await user.clear(title)
    await user.type(title, 'Renamed')
    await user.click(within(dialog).getByText('Save'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(patchBody()).not.toHaveProperty('tags')
  })

  // The other half of the tags fix, and not pinned: a category with a comma in
  // it must survive an edit to the tag list, not only a save that leaves it
  // alone. Omitting `tags` when unchanged — which is all the pin requires —
  // still splits the category the moment the user adds one tag beside it,
  // because the old field re-read its own comma-joined text. The chip control
  // holds each category as its own value, so adding one does not touch the rest.
  it('keeps a comma-bearing category whole while the owner adds another tag',
    async () => {
      const user = setup([ev({ tags: ['Home,Garden'] })])
      const dialog = await openEvent(user)

      await user.type(within(dialog).getByLabelText('Tags'), 'Admin{Enter}')
      await user.click(within(dialog).getByText('Save'))

      await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
      expect(patchBody().tags).toEqual(['Home,Garden', 'Admin'])
    })

  // CONTROL for the cadence refusal: "This event" with the repeat LEFT ALONE is
  // an ordinary per-occurrence edit and must still go through. The cheap
  // over-correction is to refuse "This event" whenever the event repeats.
  it('still saves one occurrence when the repeat was not touched', async () => {
    const user = setup([occurrence()])
    const dialog = await openEvent(user)

    const title = within(dialog).getByLabelText('Title')
    await user.clear(title)
    await user.type(title, 'Renamed once')
    await user.click(within(dialog).getByText('Save'))
    await user.click(await screen.findByText('This event'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(patchBody()).toMatchObject({ summary: 'Renamed once', scope: 'this' })
    expect(patchBody()).not.toHaveProperty('repeat')
  })

  // The half of the cadence fix the pin cannot see: "This & following" must
  // CARRY the change, not refuse it. The pin takes "sent or refused" for
  // whichever button it clicks, so refusing all three passes it — and that
  // would leave the only way to re-schedule a series from a point in time
  // being to re-schedule the whole thing.
  it('carries a cadence change on “This & following”', async () => {
    const user = setup([occurrence()])
    const dialog = await openEvent(user)

    await user.selectOptions(within(dialog).getByLabelText('Repeat'), 'weekly')
    await user.click(within(dialog).getByText('Save'))
    await user.click(await screen.findByText('This & following'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(patchBody()).toMatchObject({ repeat: 'weekly', scope: 'thisandfuture' })
  })

  // ── AUDIT (open): CalendarView.tsx:934 — changing a repeating event's cadence
  //    and then picking "This event" silently discards it and reports success ─
  it('never drops a cadence change on the floor', async () => {
    // EVIDENCE. `commit()` folds `repeatFields()` into the body only on the
    // `recurring && scope === 'all'` branch and on the non-recurring branch. For
    // `scope === 'this'` and `scope === 'thisandfuture'` the repeat select's
    // value never reaches the wire, so a user who deliberately changes Repeat
    // from "Keep current schedule" to "Weekly" (or to "Does not repeat") and
    // then answers the scope prompt with either of the two per-occurrence
    // options gets no rule change, no error and no warning — the modal closes
    // and the grid repaints as if it worked. The prompt itself gives no hint
    // that two of its three buttons cannot carry the edit just made.
    //
    // Measured on a recurring occurrence, selecting Repeat=weekly and then the
    // scope button:
    //   scope=this: {"summary":"Standup",...,"recurrence_id":"2026-03-09T09:00:00",
    //                "scope":"this"}                       <- no `repeat`
    //   scope=all : {"summary":"Standup",...,"repeat":"weekly","scope":"all"}
    // The same holds for "This & following".
    //
    // ASSERTED AS THE OUTCOME, and it takes EITHER correct answer: the cadence
    // is SENT, or the save is REFUSED (the per-occurrence buttons disabled, the
    // dialog still open with the change still on screen). What is not correct is
    // the third thing — closing as if it worked. Both branches assert, because
    // an `if (sent) {...}` here could execute zero assertions and pass.
    const user = setup([occurrence()])
    const dialog = await openEvent(user)

    await user.selectOptions(within(dialog).getByLabelText('Repeat'), 'weekly')
    await user.click(within(dialog).getByText('Save'))
    await user.click(await screen.findByText('This event'))

    if (m.patchEvent.mock.calls.length) {
      expect(patchBody()).toHaveProperty('repeat', 'weekly')
    } else {
      // Refused. The editor must still be standing with the change in it —
      // closing silently is the loss, whether or not anything was sent.
      expect(screen.queryByRole('dialog')).toBeInTheDocument()
      expect(within(screen.getByRole('dialog')).getByLabelText('Repeat')).toHaveValue('weekly')
    }
  })

  // ── AUDIT (open): calendar.ts:72 — endFromDuration treats P1D/P1W as exact
  //    milliseconds, so a DURATION-only event gains an hour across a DST edge ─
  it('seeds and saves a nominal DURATION at the same wall clock', async () => {
    // EVIDENCE. RFC 5545 §3.3.6 makes the WEEKS/DAYS part of a DURATION
    // *nominal* — P1D means the same wall-clock time the next day, i.e. 23 or 25
    // real hours across a transition — and only the TIME part exact. The backend
    // implements exactly this split (`ical/read.py:split_duration` + `advance()`,
    // with an explicit comment), but `durationMs` folds weeks and days into fixed
    // 86400000 ms and `endFromDuration` adds the whole thing to the instant.
    //
    // `EventModal` seeds its End picker from `endFromDuration` for the
    // DURATION-only events DAVx5 and jtx Board write, and `commit()` sends
    // `end: endOut` on EVERY save; `_apply_event_fields` deletes DURATION
    // whenever a dtend is supplied. So the fabricated end is written and the
    // original span is gone — the precise outcome the `endUnknown`/`derivedEnd`
    // machinery was added to prevent.
    //
    // Measured (TZ=America/New_York, spring-forward 2026-03-08 02:00). Event:
    // DTSTART 2026-03-07T09:00:00, DURATION:P1D, DTEND absent.
    //   End picker shows 2026-03-08T10:00   (RFC says 2026-03-08T09:00)
    //   change only the Title, press Save -> PATCH end 2026-03-08T10:00
    // The event is now an hour longer than its author wrote it, its DURATION is
    // deleted, and the frontend and backend disagree about the same event's end.
    // `DURATION:P1W` from the same start shows 2026-03-14T10:00 instead of
    // ...T09:00; across a fall-back the same code SHORTENS the event by an hour.
    //
    // Pinned on `endFromDuration`, NOT on `durationMs`:
    // backlog.aug19.stage4a.test.tsx has a green control asserting
    // `durationMs('P1D') === 86400000`, and the audit's suggested fix changes
    // that function's return SHAPE. The defect the user sees is the end, and the
    // end is what this asserts — the split can land wherever the fix wants it.
    expect(endFromDuration('2026-03-07T09:00:00', 'P1D')).toBe('2026-03-08T09:00')
    expect(endFromDuration('2026-03-07T09:00:00', 'P1W')).toBe('2026-03-14T09:00')
    // And through the component, which is where it reaches the wire.
    const user = setup([ev({
      start: '2026-03-07T09:00:00', end: null, duration: 'P1D',
    })])
    const dialog = await openEvent(user)

    const title = within(dialog).getByLabelText('Title')
    await user.clear(title)
    await user.type(title, 'Renamed')
    await user.click(within(dialog).getByText('Save'))

    await waitFor(() => expect(m.patchEvent).toHaveBeenCalled())
    expect(patchBody().end).toBe('2026-03-08T09:00')
  })

  // The table the suggested fix asks for, and the half neither the pin nor the
  // control below reaches: FALL-BACK, and a duration carrying BOTH halves. The
  // pin only spans spring-forward, where a nominal day is 23h — so an
  // implementation that hard-coded 23 would pass it. And P1DT2H is where the
  // ORDER of the two halves shows: stepping the day first and then adding two
  // elapsed hours is not the same as adding 26 hours, nor the same as adding two
  // hours and then stepping the day from the far side of the transition.
  it.each([
    // label                        start                  dur       end
    ['spring-forward, nominal day', '2026-03-07T09:00:00', 'P1D',    '2026-03-08T09:00'],
    ['fall-back, nominal day',      '2026-10-31T09:00:00', 'P1D',    '2026-11-01T09:00'],
    ['fall-back, nominal week',     '2026-10-28T09:00:00', 'P1W',    '2026-11-04T09:00'],
    ['spring-forward, both halves', '2026-03-07T09:00:00', 'P1DT2H', '2026-03-08T11:00'],
    ['fall-back, both halves',      '2026-10-31T09:00:00', 'P1DT2H', '2026-11-01T11:00'],
    ['no transition, both halves',  '2026-06-01T09:00:00', 'P1DT2H', '2026-06-02T11:00'],
    // THE ORDER CASE. Starting an hour before spring-forward, the two halves
    // give different answers depending on which is applied first, and only here:
    // day-then-exact steps to 03-09T01:00 and adds two elapsed hours -> 03:00.
    // Exact-then-day adds two elapsed hours across the SKIPPED one first
    // (01:00 -> 04:00) and lands 04:00. Every other row above agrees either way,
    // and a mutation swapping the order passed all of them. This is also the
    // order `read.py::advance` uses — "wall clock, then…" — and matching the
    // backend is the whole point of the split.
    ['spring-forward, order matters', '2026-03-08T01:00:00', 'P1DT2H', '2026-03-09T03:00'],
  ])('resolves %s', (_label, start, dur, end) => {
    expect(endFromDuration(start, dur)).toBe(end)
  })

  // The overflow refusal, at the boundary the guard actually sits on.
  // `backlog.aug19.stage4a` pins a 400-digit day count, which `Number` turns
  // straight into Infinity — so a guard checking only the DAY COUNT passes it.
  // The threshold that matters is the one where the days are finite and their
  // MILLISECONDS are not, which starts around 304 digits.
  it('refuses a day count whose milliseconds overflow, not just an infinite one', () => {
    const digits304 = '9'.repeat(304)
    expect(Number(digits304)).toBeLessThan(Number.MAX_VALUE)        // days: finite
    expect(Number(digits304) * 86400000).toBe(Infinity)             // ms: not
    expect(durationMs(`P${digits304}D`)).toBeNull()
    expect(endFromDuration('2026-03-07T09:00:00', `P${digits304}D`)).toBeNull()
  })

  // CONTROL (passes today, must keep passing). The EXACT half of a DURATION is
  // still exact, including across the same transition: PT2H from 01:00 on
  // spring-forward day really is 04:00, because two elapsed hours span the
  // skipped one. A fix that made the whole duration nominal would answer 03:00
  // and break every timed event.
  it('still adds the time part of a DURATION as elapsed time', () => {
    expect(endFromDuration('2026-03-07T09:00:00', 'PT2H')).toBe('2026-03-07T11:00')
    expect(endFromDuration('2026-03-08T01:00:00', 'PT2H')).toBe('2026-03-08T04:00')
    expect(endFromDuration('2026-03-07T09:00:00', 'nonsense')).toBeNull()
  })
})

// ════════════════════════════════════════════════════════════════════════════
// TodayView — the add box and the shutdown ritual
// ════════════════════════════════════════════════════════════════════════════

describe('2026-08-25 — the Today add box', () => {
  const setup = () => {
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TodayView rev={0} onExpire={vi.fn()} />
      </DataProvider>,
    )
    return userEvent.setup()
  }

  beforeEach(() => {
    m.lists.mockResolvedValue([home])
    m.createTask.mockImplementation(async (list: string, body) => task({
      uid: `made-${(body as { client_id?: string }).client_id}`, list,
      summary: String((body as { summary?: string }).summary ?? ''),
    }) as never)
    m.addDayEntry.mockImplementation(async (d, body) => dayEntry({
      entry_id: 'e-new', day: d, kind: body.kind,
      list: body.list ?? null, uid: body.uid ?? null, title: body.title ?? null,
      position: 9,
    }))
  })

  /** The client_ids `create` minted, one per authored VTODO. */
  const authored = () =>
    m.createTask.mock.calls.map(([, body]) => (body as { client_id?: string }).client_id)

  // ── AUDIT (open): TodayView.tsx:1236 — retrying the add box after a failed
  //    day-entry POST creates a second real task on the CalDAV list ──────────
  it('does not author a second task when the retry follows a failed day write', async () => {
    // EVIDENCE. `addParsedTask` is a two-step compound write with no idempotency
    // across the pair and no compensation: it first authors a real VTODO with
    // `create(...)`, then points the day at it with `addTask(on, t)`
    // (POST /api/day/{day}/entries). If only the SECOND call fails, the VTODO is
    // already on the list, `commit` puts the typed line back in the box (its own
    // comment: "so a rejected line is never simply lost"), and the obvious retry
    // mints a brand-new `client_id` in `data.tsx::create` — authoring a SECOND
    // identical VTODO that syncs to Tasks.org / Thunderbird / DAVx5.
    //
    // A different trigger from the already-fixed bulk-composer finding: there
    // the create's RESPONSE was lost, so client_id reuse was the whole fix; here
    // the create was acknowledged and only the day write failed.
    //
    // Reproduced: `addDayEntry` rejects once, type "invoice friday" + Enter,
    // wait for the line to reappear in the box, press Enter again. `createTask`
    // was called twice with two DISTINCT client_ids -> two real tasks "invoice"
    // due 2026-08-28 on list l1, one of them on no day at all.
    //
    // ASSERTED AS THE OUTCOME: one typed line authors one task. Minting the
    // client_id once per line and retrying only the day write both satisfy it —
    // the first leaves two calls with one id, the second leaves one call.
    m.addDayEntry.mockRejectedValueOnce(new Error('nope'))
    const user = setup()
    const box = await screen.findByLabelText('Add to today')

    await user.type(box, 'invoice friday{Enter}')
    await waitFor(() => expect(box).toHaveValue('invoice friday'))
    await user.type(box, '{Enter}')
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledTimes(2))

    expect(new Set(authored()).size).toBe(1)
  })

  // Which of the two repairs actually landed, and the reason for choosing both:
  // the retry re-sends ONLY the half that failed. The pin takes either — "the
  // first leaves two calls with one id, the second leaves one call" — but they
  // are not equally good. Replaying the create makes the retry depend on the
  // backend resolving the client_id to the resource already written; skipping it
  // does not, so a working day write finishes the line even if that resolution
  // ever regresses.
  it('re-sends only the day write when the task itself already landed', async () => {
    m.addDayEntry.mockRejectedValueOnce(new Error('nope'))
    const user = setup()
    const box = await screen.findByLabelText('Add to today')

    await user.type(box, 'invoice friday{Enter}')
    await waitFor(() => expect(box).toHaveValue('invoice friday'))
    await user.type(box, '{Enter}')
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledTimes(2))

    expect(m.createTask).toHaveBeenCalledTimes(1)
    // Both attempts pointed the day at the SAME task, not at a second one.
    const uids = m.addDayEntry.mock.calls.map(([, b]) => b.uid)
    expect(new Set(uids).size).toBe(1)
  })

  // The other half of the id fix, which the test above hides by never reaching
  // the create twice: when the CREATE is what failed, the retry must reuse the
  // id rather than mint a new one — that is the case where the response was
  // lost and the VTODO may exist on the server unseen.
  it('retries a failed create under the same client_id', async () => {
    m.createTask.mockRejectedValueOnce(new Error('nope'))
    const user = setup()
    const box = await screen.findByLabelText('Add to today')

    await user.type(box, 'invoice friday{Enter}')
    await waitFor(() => expect(box).toHaveValue('invoice friday'))
    await user.type(box, '{Enter}')
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(2))

    expect(new Set(authored()).size).toBe(1)
  })

  // The ref belongs to ONE line, and both halves of that need saying. A failure
  // must not make the NEXT line inherit the failed one's id or its task — the
  // user gives up on "invoice friday" and types something else, and that
  // something else would be pointed at the invoice task. A mutation that reused
  // the ref for any line passed everything else here.
  it('does not carry a failed line\'s task onto the next line typed', async () => {
    m.addDayEntry.mockRejectedValueOnce(new Error('nope'))
    const user = setup()
    const box = await screen.findByLabelText('Add to today')

    await user.type(box, 'invoice friday{Enter}')
    await waitFor(() => expect(box).toHaveValue('invoice friday'))
    await user.clear(box)
    await user.type(box, 'call the vet monday{Enter}')
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(2))

    expect(new Set(authored()).size).toBe(2)
    expect(m.createTask.mock.calls.map(([, b]) => (b as { summary?: string }).summary))
      .toEqual(['invoice', 'call the vet'])
  })

  // And the ref must not outlive the line either: fail, retry successfully, then
  // type the same text again — a repeated errand, a second "invoice friday" —
  // and that is a NEW task, not a second attempt at the finished one. Only
  // reachable in three steps, which is why clearing on success survived a
  // mutation until this test.
  it('starts fresh when a line is retyped after its retry succeeded', async () => {
    m.addDayEntry.mockRejectedValueOnce(new Error('nope'))
    const user = setup()
    const box = await screen.findByLabelText('Add to today')

    await user.type(box, 'invoice friday{Enter}')
    await waitFor(() => expect(box).toHaveValue('invoice friday'))
    await user.type(box, '{Enter}')                       // the retry, accepted
    await waitFor(() => expect(m.addDayEntry).toHaveBeenCalledTimes(2))

    await user.type(box, 'invoice friday{Enter}')
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(2))
    expect(new Set(authored()).size).toBe(2)
  })

  // CONTROL for the ref that remembers all this: a line that SUCCEEDS must not
  // leave anything behind, or typing the same text a second time — "gym friday",
  // twice, because the first one was for a different thing — would re-point the
  // day at the task already authored instead of authoring another.
  it('authors a fresh task when the same line is typed again after it succeeded',
    async () => {
      const user = setup()
      const box = await screen.findByLabelText('Add to today')

      await user.type(box, 'gym friday{Enter}')
      await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(1))
      await user.type(box, 'gym friday{Enter}')
      await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(2))

      expect(new Set(authored()).size).toBe(2)
    })

  // CONTROL (passes today, must keep passing). Two DIFFERENT lines still author
  // two tasks. The cheap over-correction is a global "one create per session"
  // latch, which would satisfy the pin by breaking the box.
  it('still authors one task per distinct line', async () => {
    const user = setup()
    const box = await screen.findByLabelText('Add to today')

    await user.type(box, 'invoice friday{Enter}')
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(1))
    await user.type(box, 'call the vet monday{Enter}')
    await waitFor(() => expect(m.createTask).toHaveBeenCalledTimes(2))

    expect(new Set(authored()).size).toBe(2)
  })

  // ── AUDIT (open): TodayView.tsx:1240 — a line pinned to "task" that the
  //    parser read nothing in writes its untrimmed text as the VTODO SUMMARY ─
  it('trims the summary of a line the parser read nothing in', async () => {
    // EVIDENCE. `parseEntry` returns `summary: text` byte for byte when it
    // recognises nothing (its documented "'' in, '' out" rule —
    // `daytext.ts:454`, `const verbatim: ParsedEntry = { summary: text, ... }`),
    // so on the pinned-task path `create(list, { summary: p.summary })` sends the
    // raw input including leading and trailing whitespace. The NOTE path right
    // beside it sends `raw = text.trim()`, and the parsed-task path sends
    // `without()`'s trimmed remnant, so this one branch is the odd one out.
    //
    // A leading space is invisible in the chip preview but real in the VTODO the
    // whole account then sees: `sortTasks` orders by summary, so the task sorts
    // ahead of everything, and it goes out over CalDAV to Tasks.org and
    // Thunderbird that way. A trailing space is the common case on a phone,
    // where the space bar is pressed before Enter or autocorrect appends one.
    // `CreateTask.summary` is `XmlSafeText` (app.py:161) with no strip and no
    // min_length, so nothing downstream trims it either.
    //
    // Pinned at the `createTask` boundary rather than in `daytext.ts`:
    // `daytext.test.ts`'s "the empty line" case asserts `parse('   ')` returns
    // its input UNTOUCHED, which is the parser's contract. The call site is
    // where the contract is misused.
    const user = setup()
    const box = await screen.findByLabelText('Add to today')

    await user.type(box, '  buy milk  ')
    await user.click(await screen.findByRole('button', { name: 'Make it a task' }))
    await user.type(box, '{Enter}')

    await waitFor(() => expect(m.createTask).toHaveBeenCalled())
    const summary = String((m.createTask.mock.calls[0][1] as { summary?: string }).summary)
    expect(summary).toBe('buy milk')
  })
})

describe('2026-08-25 — the shutdown ritual', () => {
  const setup = () => {
    render(
      <DataProvider rev={0} onExpire={vi.fn()}>
        <TodayView rev={0} onExpire={vi.fn()} />
      </DataProvider>,
    )
    return userEvent.setup()
  }

  const openReflect = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole('button', { name: 'Shut down' }))
    const dialog = await screen.findByRole('dialog', { name: 'Shut down the day' })
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    await user.click(within(dialog).getByRole('button', { name: 'Next' }))
    return dialog
  }

  // ── AUDIT (open): ShutdownRitual.tsx:316 — Escape discards an unsaved
  //    reflection (and an unsaved capacity) because both commit only on blur ─
  it('keeps a reflection the owner closed with Escape', async () => {
    // EVIDENCE. `ReflectStep` writes the day's reflection only from `onBlur`.
    // Both rituals bind `useEscape(onClose)` to the window, and `onClose`
    // unmounts the whole overlay. Browsers do not fire `blur`/`focusout` for a
    // focused element REMOVED from the DOM (Chrome and Safari, i.e. every iOS
    // install), so pressing Escape with the cursor still in the textarea
    // silently throws the typed prose away — on the one field in the app that
    // holds free text and whose own hint promises "Kept with the day. You will
    // see it whenever you look back at today."
    //
    // The ✕ and the scrim are safe: their mousedown blurs the field first.
    // Escape is the one closer that is not. `PlanRitual`'s `CapacityStep` has
    // the identical shape at PlanRitual.tsx:191, so "until 6pm" typed and then
    // Escaped is never stored either — one fix covers both.
    //
    // Reproduced: open Shut down -> Next -> Next, type "shipped the thing" into
    // "A note about today", `keyDown(window, { key: 'Escape' })`, wait for the
    // dialog to unmount. `api.patchDay` calls: `[]`. Re-opening the ritual shows
    // an empty box and the look-back shows no "How it went" section.
    //
    // ASSERTED AS THE OUTCOME: the prose reaches the server. A cleanup-effect
    // flush, a flush before `onClose`, or committing on change all satisfy it.
    const user = setup()
    const dialog = await openReflect(user)

    await user.type(within(dialog).getByLabelText('A note about today'), 'shipped the thing')
    expect(m.patchDay).not.toHaveBeenCalled()

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(
      screen.queryByRole('dialog', { name: 'Shut down the day' })).not.toBeInTheDocument())

    expect(m.patchDay).toHaveBeenCalledWith(today(), { reflection: 'shipped the thing' })
  })

  // The unmount flush must not DOUBLE-write. The blur handler and the cleanup
  // both send, so a fix that fired the cleanup unconditionally would PATCH the
  // same reflection twice for the ordinary path — blur, then close — which is a
  // second write of identical prose against a field the whole design keeps out
  // of a write storm.
  it('writes once when the reflection was already saved on blur', async () => {
    const user = setup()
    const dialog = await openReflect(user)

    await user.type(within(dialog).getByLabelText('A note about today'), 'shipped it')
    await user.tab()
    await waitFor(() => expect(m.patchDay).toHaveBeenCalledTimes(1))

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(
      screen.queryByRole('dialog', { name: 'Shut down the day' })).not.toBeInTheDocument())

    expect(m.patchDay).toHaveBeenCalledTimes(1)
  })

  // `CapacityStep` — the OTHER half the finding names ("the identical shape at
  // PlanRitual.tsx:191, so 'until 6pm' typed and then Escaped is never stored
  // either"), and not pinned. Fixing only `ReflectStep` closes the pin and
  // leaves this exactly as it was.
  it('keeps a capacity the owner closed with Escape', async () => {
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Plan my day' }))
    const dialog = await screen.findByRole('dialog', { name: 'Plan your day' })

    await user.type(
      within(dialog).getByLabelText('How long you are working today'), '5h')
    expect(m.patchDay).not.toHaveBeenCalled()

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(
      screen.queryByRole('dialog', { name: 'Plan your day' })).not.toBeInTheDocument())

    expect(m.patchDay).toHaveBeenCalledWith(today(), { capacity_minutes: 300 })
  })

  // CONTROL for the capacity flush: a draft the PARSER REFUSES writes nothing on
  // unmount. Blur gives that same answer and shows the hint instead; storing a
  // guessed number from text the app has already said it cannot read would be
  // worse than losing it.
  it('writes no capacity from a draft the parser refused', async () => {
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Plan my day' }))
    const dialog = await screen.findByRole('dialog', { name: 'Plan your day' })

    await user.type(
      within(dialog).getByLabelText('How long you are working today'), 'whenever')

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(
      screen.queryByRole('dialog', { name: 'Plan your day' })).not.toBeInTheDocument())

    expect(m.patchDay).not.toHaveBeenCalled()
  })

  // CONTROL (passes today, must keep passing). The blur commit still saves, and
  // still trims. The fix has to ADD a path rather than move one: a repair that
  // committed only on unmount would satisfy the pin and lose the write that
  // happens when the owner tabs on to the Shut down button.
  it('still writes the reflection on blur, trimmed', async () => {
    const user = setup()
    const dialog = await openReflect(user)

    await user.type(within(dialog).getByLabelText('A note about today'),
      '  Slow start, good afternoon.  ')
    expect(m.patchDay).not.toHaveBeenCalled()
    await user.tab()

    await waitFor(() => expect(m.patchDay).toHaveBeenCalledWith(
      today(), { reflection: 'Slow start, good afternoon.' }))
  })
})
